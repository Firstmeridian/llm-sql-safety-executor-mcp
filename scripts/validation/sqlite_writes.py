"""Private-file SQLite preview/confirm/replay and independent post-cleanup truth.

Uses both managed classifiers, both Client modes and in-process/child stdio.
Application records are not full protocol frames or model-usage measurements.
Never opens the repository's configured databases or changes their grants.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


BEFORE = [(1, 7), (2, 8)]
UPDATED = [(1, 99), (2, 8)]
CTE = "WITH chosen AS (SELECT 1 AS id) "
# name, original SQL, expected direct count, outcome, independent final rows
CASES = [
    ("plain-update", "UPDATE orders SET n=99 WHERE id=1", 1, "committed", UPDATED),
    ("cte-update", CTE+"UPDATE orders SET n=99 WHERE id IN(SELECT id FROM chosen)", 1, "committed", UPDATED),
    ("recursive-update", "WITH RECURSIVE chosen(id) AS(SELECT 1) UPDATE orders SET n=99 WHERE id IN(SELECT id FROM chosen)", 1, "committed", UPDATED),
    ("semicolon-update", ";UPDATE orders SET n=99 WHERE id=1", 1, "committed", UPDATED),
    ("cte-insert", CTE+"INSERT INTO orders VALUES(3,99)", 1, "committed", BEFORE+[(3,99)]),
    ("cte-delete", CTE+"DELETE FROM orders WHERE id=1", 1, "committed", [(2,8)]),
    ("returning-update", "UPDATE orders SET n=99 WHERE id=1 RETURNING n", 1, "committed", UPDATED),
    ("returning-insert", "INSERT INTO orders VALUES(3,99) RETURNING n", 1, "committed", BEFORE+[(3,99)]),
    ("returning-delete", "DELETE FROM orders WHERE id=1 RETURNING n", 1, "committed", [(2,8)]),
    ("cte-returning", CTE+"UPDATE orders SET n=99 WHERE id=1 RETURNING n", 1, "committed", UPDATED),
    ("semicolon-returning", ";UPDATE orders SET n=99 WHERE id=1 RETURNING n", 1, "committed", UPDATED),
    ("cte-two-mismatch", CTE+"UPDATE orders SET n=n+100", 1, "rolled_back", BEFORE),
    ("returning-mismatch", "UPDATE orders SET n=99 WHERE id=1 RETURNING n", 0, "rolled_back", BEFORE),
    ("cte-partial-fail", CTE+"UPDATE OR FAIL orders SET n=99", 1, "rolled_back", BEFORE),
    ("trigger-fail", CTE+"UPDATE orders SET n=99 WHERE id=1", 1, "rolled_back", BEFORE),
    ("engine-auto-rollback", CTE+"UPDATE OR ROLLBACK orders SET n=99", 1, "unknown", BEFORE),
    ("zero-returning", CTE+"UPDATE orders SET n=99 WHERE id=999 RETURNING n", 0, "committed", BEFORE),
]


def redacted(value):
    if isinstance(value, dict):
        return {k: "<redacted>" if k in {"preview_token", "preview_token_id"} else redacted(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redacted(v) for v in value]
    if isinstance(value, str) and value.startswith("{"):
        try:
            return json.dumps(redacted(json.loads(value)), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    return value


def observe(database, table):
    with sqlite3.connect(database) as db:
        return db.execute(f'SELECT id,n FROM "{table}" ORDER BY id').fetchall()


async def run(args):
    if args.source:
        sys.path.insert(0, str(args.source.resolve()))
    import sql_safety_executor
    from sql_safety_executor import create_server, load_config
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    package = Path(sql_safety_executor.__file__).resolve().parent
    if args.source:
        assert package == args.source.resolve() / "sql_safety_executor"
    else:
        assert package.is_relative_to(Path(sys.prefix)) and "site-packages" in str(package)
    assert not args.output.exists()
    records, runs, final_truth = [], [], []
    for transport_kind in ("inprocess", "stdio"):
        for parser in ("sqlglot", "sqlparse"):
            for mode in ("auto", "legacy"):
                with tempfile.TemporaryDirectory(prefix="sqlite-write-lifecycle-") as directory:
                    root = Path(directory)
                    database = root / "fixture.sqlite"
                    for name, sql, expected, _, _ in CASES:
                        table = name.replace("-", "_")
                        with sqlite3.connect(database) as db:
                            db.executescript(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY,n INTEGER UNIQUE);'
                                             f'INSERT INTO "{table}" VALUES(1,7),(2,8);')
                            if name == "trigger-fail":
                                db.executescript(f'CREATE TRIGGER private_fail AFTER UPDATE ON "{table}" '
                                                 "BEGIN SELECT RAISE(FAIL,'fixture'); END;")
                        skill = root / "skills" / name
                        skill.mkdir(parents=True)
                        (skill / "skill_def.md").write_text(
                            f"---\nname: {name}\nversion: '1.0'\ndescription: Private transaction verification\n"
                            f"type: mutation\nsource: mutation.py\nrisk: medium\nrequires_confirmation: true\n"
                            f"idempotent: false\ndatabases: [sqlite]\ntables: [{table}]\nparams: {{}}\n---\nPrivate fixture only.\n")
                        (skill / "mutation.py").write_text(
                            "from sql_safety_executor.skills.mutation import ManagedMutationBase, ManagedMutationPlan\n"
                            "class Mutation(ManagedMutationBase):\n"
                            f"    managed_plan = ManagedMutationPlan({sql.replace('orders', table)!r}, (), {expected})\n"
                            "    def validate(self, params):\n        return {'valid': True}\n"
                            "    def preview(self, params):\n        return {'affected_rows_estimate': 1, 'requires_confirmation': True}\n")
                    (root / "server.toml").write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="fixture"\n')
                    (root / "connections.toml").write_text(
                        'schema_version=1\n[connections.fixture]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\n'
                        'read.mode="all"\nmutation.enabled=true\nmutation.skills=' + json.dumps([c[0] for c in CASES]) + '\n')
                    (root / "skills.toml").write_text(
                        'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
                        '[skills.readiness]\ncheck_schema=true\n[skills.mutation]\nenabled=true\n'
                        'allowed_connections=["fixture"]\nmanaged_plan_parser="' + parser + '"\n'
                        '[skills.mutation.mrtr]\nenabled=false\n[skills.audit]\npath="audit.jsonl"\n')
                    server = None
                    if transport_kind == "inprocess":
                        server = create_server(load_config(root / "server.toml"))
                        transport = server
                    else:
                        environment = os.environ.copy()
                        environment.pop("PYTHONPATH", None)
                        if args.source:
                            environment["PYTHONPATH"] = str(args.source.resolve())
                        transport = StdioTransport(command=sys.executable,
                            args=["-m", "sql_safety_executor", "serve", "--config", str(root / "server.toml")],
                            cwd=str(root), env=environment)
                    try:
                        async with Client(transport, mode=mode, init_timeout=20, timeout=20) as client:
                            identity = {"transport": transport_kind, "parser": parser, "client_mode": mode}
                            runs.append({**identity, "protocol": client.protocol_version})

                            async def call(tool, arguments):
                                response = await client.call_tool(tool, {"connection_id": "fixture", **arguments}, raise_on_error=False)
                                for block in response.content:
                                    if getattr(block, "type", None) == "text" and not response.is_error:
                                        assert json.loads(block.text) == response.structured_content
                                records.append({**identity, "tool": tool, "arguments": redacted(arguments),
                                    "isError": response.is_error, "structured": redacted(response.structured_content),
                                    "meta": redacted(response.meta), "content": redacted([
                                        block.model_dump(mode="json", exclude_none=True) for block in response.content])})
                                return response

                            for name, _, expected, outcome, truth in CASES:
                                table = name.replace("-", "_")
                                arguments = {"skill_name": name, "params": {}}
                                preview = await call("execute_mutation_skill", arguments)
                                assert preview.structured_content["success"], records[-1]
                                assert preview.structured_content["execution_outcome"] == "not_executed"
                                assert observe(database, table) == BEFORE
                                confirm = {**arguments, "confirm": True, "preview_token": preview.structured_content["preview_token"]}
                                executed = await call("execute_mutation_skill", confirm)
                                payload = executed.structured_content
                                assert payload["execution_outcome"] == outcome, records[-1]
                                assert payload["success"] is (outcome == "committed"), records[-1]
                                assert executed.meta["preview_token_consumed"] is True
                                if outcome == "committed":
                                    assert payload["result"]["rowcount"] == expected, records[-1]
                                if "mismatch" in name:
                                    assert payload["error_code"] == "expected_rowcount_mismatch"
                                assert observe(database, table) == truth, records[-1]
                                replay = await call("execute_mutation_skill", confirm)
                                assert replay.is_error and observe(database, table) == truth
                            read = await call("query", {"sql": "SELECT 7 AS n"})
                            assert read.structured_content["data"] == [{"n": 7}]
                            refusal = await call("query", {"sql": "UPDATE plain_update SET n=100 WHERE id=1"})
                            assert not refusal.structured_content["success"]
                            refusal = await call("query", {"sql": "SELECT sleep(1)"})
                            assert refusal.structured_content["error_code"] == "expensive_function_denied"
                    finally:
                        if server is not None:
                            server.gateway_runtime.close()
                    for name, _, _, _, truth in CASES:
                        rows = observe(database, name.replace("-", "_"))
                        assert rows == truth
                        final_truth.append({**identity, "case": name, "independent_post_cleanup_rows": rows})
    result = {"scope": __doc__, "package": str(package), "records": records,
        "runs": runs, "flows": len(final_truth), "independent_truth": final_truth,
        "resources": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in package.rglob("*") if p.is_file() and p.suffix in {".py", ".md"}},
        "passed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False, indent=2).encode(), mtime=0))
    print(json.dumps({"calls": len(records), "flows": len(final_truth), "runs": len(runs), "passed": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
