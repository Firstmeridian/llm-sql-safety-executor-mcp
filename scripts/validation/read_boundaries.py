"""Source-selectable real stdio checks for view reads and SQLite DML plans.

Use --expect before only with the frozen pre-repair v3.8.2 source. UDFs are
harmless counters; every database/configuration belongs to a temporary fixture.
Records contain decoded application results, not complete protocol frames.
"""
from __future__ import annotations
import argparse
import asyncio
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


async def check(args):
    if args.source:
        sys.path.insert(0, str(args.source))
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    import sql_safety_executor

    after = args.expect == "after"
    records = []
    with tempfile.TemporaryDirectory(prefix="v382-read-boundaries-") as temp:
        root = Path(temp)
        with sqlite3.connect(root / "db.sqlite") as db:
            db.executescript(
                "CREATE TABLE orders(n); INSERT INTO orders VALUES(7);"
                "CREATE TABLE hidden(n); INSERT INTO hidden VALUES(99);"
                "CREATE VIEW normal_view AS SELECT n FROM hidden;"
                "CREATE VIEW sleep_view AS SELECT n FROM orders WHERE SLEEP(0)=0;"
                "CREATE VIEW pragma_view AS SELECT seq AS n FROM pragma_database_list;"
            )
        (root / "server.toml").write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="probe"\n[tools]\nschema=true\ntable_summary=true\n')
        (root / "connections.toml").write_text('schema_version=1\n[connections.probe]\ntype="sqlite"\nsqlite.path="db.sqlite"\nread.mode="allowlist"\nread.tables=["orders","main.orders","main.normal_view","main.sleep_view","main.pragma_view"]\n')
        (root / "skills.toml").write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        skill = root / "skills" / "plan-orders"
        skill.mkdir(parents=True)
        (skill / "skill_def.md").write_text('---\nname: plan-orders\ntype: query\nsource: query.sql\nrisk: low\ndescription: Non-executing private plan\nparams: {}\n---\n')
        (skill / "query.sql").write_text("EXPLAIN UPDATE main.orders SET n=99")
        launcher = root / "launcher.py"
        source_line = f"import sys; sys.path.insert(0,{str(args.source)!r})\n" if args.source else ""
        launcher.write_text(source_line + "from sql_safety_executor import create_server,load_config\n"
            "server=create_server(load_config('server.toml'))\n"
            "adapter=server.gateway_runtime.registry.get_adapter('probe')\nassert adapter.connect()\ncalls=[]\n"
            "with adapter._engine.connect() as db:\n"
            " db.connection.dbapi_connection.create_function('SLEEP',1,lambda _: calls.append(1) or 0)\n"
            " db.connection.dbapi_connection.create_function('boundary_calls',0,lambda:len(calls))\n"
            "server.run(transport='stdio',show_banner=False)\n")
        cli_results = []
        for operation in ("check", "explain"):
            code = source_line + "from sql_safety_executor.cli import main; main()"
            cli = subprocess.run([sys.executable, "-c", code, "config", operation, "--config", str(root / "server.toml")], cwd=root, capture_output=True, text=True)
            assert cli.returncode == 0, cli.stderr
            cli_results.append({"operation": operation, "passed": True})
        for mode in ("auto", "legacy"):
            transport = StdioTransport(command=sys.executable, args=[str(launcher)], cwd=str(root))
            async with Client(transport, mode=mode) as client:
                async def call(tool, arguments):
                    result = await client.call_tool(tool, arguments, raise_on_error=False)
                    records.append({"mode": mode, "protocol": client.protocol_version, "tool": tool, "arguments": arguments,
                        "isError": result.is_error, "structured": result.structured_content,
                        "content": [c.model_dump(mode="json", exclude_none=True) for c in result.content]})
                    assert not result.is_error
                    payload = result.structured_content
                    assert isinstance(payload, dict)
                    return payload
                assert (await call("query", {"sql": "SELECT 7 AS n"}))["data"] == [{"n": 7}]
                for view in ["normal_view", "sleep_view", "pragma_view"]:
                    blocked = view != "normal_view"
                    code = "expensive_function_denied" if view == "sleep_view" else "server_state_denied" if after else "unknown_table"
                    for tool, arguments, read_data, approximate in [
                        ("query", {"sql": f"SELECT n FROM main.{view}"}, True, False),
                        ("sample", {"table_name": view}, True, False),
                        ("get_table_summary", {"table_name": view, "exact_count": True}, False, False),
                        ("get_table_summary", {"table_name": view}, False, True),
                        ("describe_table", {"table_name": view}, False, True),
                    ]:
                        payload = await call(tool, arguments)
                        denied = blocked and (tool == "query" or after and not approximate)
                        if denied:
                            assert not payload["success"] and payload["error_code"] == code, payload
                        else:
                            assert payload["success"], payload
                            assert payload["row_count"] == (None if blocked and after else 1)
                            if approximate:
                                assert payload["columns"]
                            if read_data:
                                assert payload["data"] == [{"n": 99 if view == "normal_view" else 7 if view == "sleep_view" else 0}]
                for sql in ["EXPLAIN UPDATE orders SET n=99", "EXPLAIN QUERY PLAN DELETE FROM orders", "EXPLAIN INSERT INTO orders VALUES(99)", "EXPLAIN REPLACE INTO orders VALUES(99)", "EXPLAIN QUERY PLAN REPLACE INTO orders VALUES(99)", "EXPLAIN UPDATE orders SET n=99 RETURNING n"]:
                    payload = await call("query", {"sql": sql})
                    assert payload["success"] is after, payload
                    if not after:
                        assert payload["error_code"] == ("sql_parse_failed" if "REPLACE" in sql else "read_only_required")
                for sql in ["UPDATE orders SET n=99", "DELETE FROM orders", "INSERT INTO orders VALUES(99)"]:
                    assert (await call("query", {"sql": sql}))["error_code"] == "read_only_required"
                for sql in ["SELECT n FROM main.hidden", "EXPLAIN UPDATE main.hidden SET n=0"]:
                    assert (await call("query", {"sql": sql}))["error_code"] == "table_access_denied"
                payload = await call("query", {"sql": "SELECT COUNT(*) AS n FROM main.normal_view"})
                assert payload["success"] is after, payload
                if after:
                    assert payload["data"] == [{"n": 1}]
                assert (await call("query", {"sql": "SELECT boundary_calls() AS n"}))["data"] == [{"n": 0 if after else 4}]
                assert (await call("list_skills", {"detail_level": "full"}))["skills"][0]["executable"]
                assert (await call("get_skill_detail", {"skill_name": "plan-orders"}))["skill"]["schema_ready"]
                assert (await call("execute_query_skill", {"skill_name": "plan-orders", "params": {}}))["success"] is after
                assert (await call("query", {"sql": "SELECT n FROM main.orders"}))["data"] == [{"n": 7}]
                assert (await call("sample", {"table_name": "orders"}))["data"] == [{"n": 7}]
                assert (await call("get_table_summary", {"table_name": "orders", "exact_count": True}))["row_count"] == 1
                assert [t["table_name"] for t in (await call("list_tables", {}))["tables"]] == ["orders"]
                assert (await call("get_full_schema", {}))["total_tables"] == 1
        with sqlite3.connect(root / "db.sqlite") as db:
            assert db.execute("SELECT n FROM orders").fetchall() == [(7,)]
            assert db.execute("SELECT n FROM hidden").fetchall() == [(99,)]
        result = {"version": sql_safety_executor.__version__, "expected": args.expect, "calls": len(records),
            "cli": cli_results, "records": records, "data_unchanged": True,
            "source_sha256": {str(p.relative_to(Path(sql_safety_executor.__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(sql_safety_executor.__file__).parent.rglob("*")) if p.is_file() and p.suffix in {".py", ".md"}},
            "recording_profile": "Real child stdio; decoded application content/structured results. Full frames/notifications not captured. Harmless counter UDF; private temporary fixtures only."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(gzip.compress((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode(), mtime=0))
        print(json.dumps({"version": result["version"], "expected": args.expect, "calls": len(records), "passed": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--expect", choices=["before", "after"], default="after")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.source = args.source.resolve() if args.source else None
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("Output exists; use a new batch")
    asyncio.run(check(args))
