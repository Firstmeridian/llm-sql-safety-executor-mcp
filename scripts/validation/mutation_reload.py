"""Owned-fixture same-process stdio Mutation publication and committed truth.

SQLite is always run. Optional MySQL uses the existing disposable-schema
fixture, never configured business tables, grants, Host or private TOMLs.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError


def definition(root, *, offset=0, parameter="new_n"):
    directory = root / "change-n"
    directory.mkdir(exist_ok=True)
    (directory / "skill_def.md").write_text(
        "---\nname: change-n\ntype: mutation\nsource: mutation.py\nrisk: medium\n"
        "description: Isolated reload validation\nversion: '1.0'\nrequires_confirmation: true\n"
        "databases: [sqlite, mysql]\ntables: [orders]\nparams:\n"
        "  order_id: {type: int, required: true}\n"
        f"  {parameter}: {{type: int, required: true}}\n---\n", encoding="utf-8")
    sql = f"UPDATE orders SET n=:{parameter}+{offset} WHERE id=:order_id AND n=:expected"
    (directory / "mutation.py").write_text(
        "import os\n"
        "from sql_safety_executor.skills.mutation import ManagedMutationBase, ManagedMutationPlan, ManagedMutationValue\n"
        "class Mutation(ManagedMutationBase):\n"
        f"    managed_plan = ManagedMutationPlan(sql={sql!r}, parameters=(\n"
        f"        ManagedMutationValue.from_params({parameter!r}),\n"
        "        ManagedMutationValue.from_params('order_id'),\n"
        "        ManagedMutationValue.from_binding('expected'),\n"
        "    ), expected_rowcount=1)\n"
        "    def validate(self, params):\n        return {'valid': True}\n"
        "    def preview(self, params):\n"
        "        rows = self.adapter.execute('SELECT n FROM orders WHERE id=:id', params={'id': params['order_id']})\n"
        "        return {'expected': rows[0][0], 'server_pid': os.getpid(), 'affected_rows_estimate': 1}\n"
        "    def build_execution_binding(self, params, validation, preview):\n"
        "        return {'expected': preview['expected']}\n", encoding="utf-8")


@contextmanager
def database(root, backend, mysql_config, mysql_alias):
    if backend == "sqlite":
        path = root / "db.sqlite"
        with sqlite3.connect(path) as connection:
            connection.executescript(
                "CREATE TABLE orders(id INTEGER PRIMARY KEY,n INTEGER);"
                "INSERT INTO orders VALUES(1,7),(2,8);"
                "CREATE TABLE audit_log(old_n INTEGER,new_n INTEGER);"
                "CREATE TRIGGER audit_u AFTER UPDATE ON orders BEGIN "
                "INSERT INTO audit_log VALUES(OLD.n,NEW.n); END;")
        def observe():
            with sqlite3.connect(path) as connection:
                return {"n": connection.execute("SELECT n FROM orders WHERE id=1").fetchone()[0],
                        "audit": [list(row) for row in connection.execute("SELECT old_n,new_n FROM audit_log ORDER BY rowid")],
                        "other_n": connection.execute("SELECT n FROM orders WHERE id=2").fetchone()[0]}
        yield '[connections.demo]\ntype="sqlite"\n[connections.demo.sqlite]\npath="db.sqlite"\n', {}, observe, {"SQLite": sqlite3.sqlite_version}
    else:
        from sql_safety_executor import load_config
        from mysql_writes import Fixture
        config = load_config(mysql_config).connections[mysql_alias]
        if config.db_type != "mysql":
            raise ValueError("The selected test alias is not MySQL")
        fixture = Fixture(config)
        with fixture:
            def observe():
                truth = fixture.observe()
                return {"n": truth["orders"][0][1],
                        "audit": [[row[2], row[3]] for row in truth["audit"]],
                        "other_n": truth["orders"][1][1]}
            q = json.dumps
            text = ('[connections.demo]\ntype="mysql"\n[connections.demo.mysql]\n'
                    f'host={q(config.mysql_host)}\nuser={q(config.mysql_user)}\ndatabase={q(fixture.schema)}\n')
            if config.mysql_sql_mode is not None:
                text += "sql_mode=" + q(list(config.mysql_sql_mode)) + "\n"
            text += '[connections.demo.mysql.password]\nenv="MUTATION_RELOAD_FIXTURE_PASSWORD"\n'
            with fixture.connect(autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT VERSION(),@@SESSION.sql_mode")
                    version, sql_mode = cursor.fetchone()
            secret = config.mysql_password.get_secret_value() if config.mysql_password else ""
            yield text, {"MUTATION_RELOAD_FIXTURE_PASSWORD": secret}, observe, {"MySQL": version, "sql_mode": sql_mode}
        assert not fixture.created


def redacted(value):
    if isinstance(value, dict):
        return {key: "<redacted>" if key in {"preview_token", "preview_token_id"} else redacted(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


async def workflow(python, package_root, mode, backend, mysql_config=None, mysql_alias=None):
    ledger = []
    with tempfile.TemporaryDirectory(prefix="mutation-reload-stdio-") as temporary:
        root = Path(temporary)
        skills = root / "skills"
        skills.mkdir()
        definition(skills)
        with database(root, backend, mysql_config, mysql_alias) as (target, extra_env, observe, identity):
            (root / "server.toml").write_text(
                'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
                '[server]\ndefault_connection="demo"\n')
            (root / "connections.toml").write_text(
                "schema_version=1\n" + target
                + '[connections.demo.read]\nmode="all"\n[connections.demo.mutation]\nenabled=true\nskills=["change-n"]\n')
            (root / "skills.toml").write_text(
                'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
                '[skills.mutation]\nenabled=true\nallowed_connections=["demo"]\n'
                '[skills.mutation.mrtr]\nenabled=false\n')
            environment = {**os.environ, **extra_env, "PYTHONDONTWRITEBYTECODE": "1"}
            dependencies = subprocess.check_output(
                [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
            environment["PYTHONPATH"] = os.pathsep.join([str(package_root), dependencies])
            origin = subprocess.check_output(
                [python, "-c", "import sql_safety_executor; print(sql_safety_executor.__file__)"],
                env=environment, cwd=root, text=True).strip()
            assert Path(origin).is_relative_to(package_root), "Wrong product import origin"
            transport = StdioTransport(command=python, args=["-m", "sql_safety_executor", "serve", "--config", str(root / "server.toml")], env=environment, cwd=str(root))
            async with Client(transport, mode=mode) as client:
                tools = await client.list_tools()
                tool = next(tool for tool in tools if tool.name == "reload_skills")
                assert tool.inputSchema["properties"]["skill_type"]["enum"] == ["query", "mutation"]
                assert tool.annotations.destructive_hint and not tool.annotations.idempotent_hint
                async def call(label, name, args, *, reject=False):
                    start = time.perf_counter()
                    try:
                        result = (await client.call_tool(name, args, timeout=30)).structured_content
                    except ToolError as error:
                        ledger.append({"label": label, "tool": name, "expected_error": reject,
                                       "error": str(error), "client_ms": (time.perf_counter() - start) * 1000})
                        if not reject: raise
                        return None
                    assert not reject, f"Unexpected success: {label}"
                    ledger.append({"label": label, "tool": name, "result": redacted(result),
                                   "client_ms": (time.perf_counter() - start) * 1000})
                    return result
                def args(parameter="new_n", n=8, proposal=None):
                    result = {"skill_name": "change-n", "params": {"order_id": 1, parameter: n}, "connection_id": "demo"}
                    if proposal is not None:
                        result.update(confirm=True, preview_token=proposal["preview_token"])
                    return result

                old = await call("v1_preview", "execute_mutation_skill", args())
                assert old["success"] and observe() == {"n": 7, "audit": [], "other_n": 8}
                pid = old["preview"]["server_pid"]
                definition(skills, offset=10, parameter="target_n")
                query_receipt = await call("query_scope_preserves_mutation", "reload_skills", {})
                assert query_receipt["revision"] == 0 and query_receipt["invalidated_previews"] == 0
                receipt = await call("publish_v2", "reload_skills", {"skill_type": "mutation"})
                assert receipt["changed"] == ["change-n"] and receipt["invalidated_previews"] == 1
                detail = await call("v2_detail", "get_skill_detail", {"skill_name": "change-n", "connection_id": "demo"})
                assert "target_n" in detail["skill"]["params"] and "new_n" not in detail["skill"]["params"]
                await call("old_preview_rejected", "execute_mutation_skill", args("target_n", proposal=old), reject=True)
                assert observe() == {"n": 7, "audit": [], "other_n": 8}
                fresh = await call("v2_preview", "execute_mutation_skill", args("target_n"))
                assert fresh["preview"]["server_pid"] == pid
                done = await call("v2_execute", "execute_mutation_skill", args("target_n", proposal=fresh))
                assert done["execution_outcome"] == "committed"
                assert observe() == {"n": 18, "audit": [[7, 18]], "other_n": 8}
                await call("replay_rejected", "execute_mutation_skill", args("target_n", proposal=fresh), reject=True)
                pending = await call("pending_before_bad_candidate", "execute_mutation_skill", args("target_n", 9))
                entry, parked = skills / "change-n", root / "parked-mutation"
                for replacement in ("file", "dangling"):
                    entry.rename(parked)
                    try:
                        if replacement == "file":
                            entry.write_text("incomplete deployment")
                        else:
                            entry.symlink_to("missing-target", target_is_directory=True)
                        rejected = await call(f"reject_{replacement}_entry", "reload_skills", {"skill_type": "mutation"})
                        assert not rejected["success"] and rejected["reason"] == "skill_directory_unavailable"
                        assert rejected["revision"] == receipt["revision"]
                        assert observe() == {"n": 18, "audit": [[7, 18]], "other_n": 8}
                    finally:
                        entry.unlink()
                        parked.rename(entry)
                (skills / "change-n/mutation.py").write_text("raise RuntimeError('private candidate failure')")
                bad = await call("reject_candidate", "reload_skills", {"skill_type": "mutation"})
                assert not bad["success"] and bad["revision"] == receipt["revision"]
                survivor = await call("old_catalog_survives", "execute_mutation_skill", args("target_n", 9, pending))
                assert survivor["execution_outcome"] == "committed"
                assert observe() == {"n": 19, "audit": [[7, 18], [18, 19]], "other_n": 8}
                definition(skills, offset=10, parameter="target_n")
                noop = await call("noop_reuses_active", "reload_skills", {"skill_type": "mutation"})
                assert noop["revision"] == receipt["revision"] and not noop["changed"]
                doomed = await call("pending_before_removal", "execute_mutation_skill", args("target_n", 12))
                shutil.rmtree(skills / "change-n")
                removal = await call("remove", "reload_skills", {"skill_type": "mutation"})
                assert removal["removed"] == ["change-n"] and removal["invalidated_previews"] == 1
                definition(skills)
                added = await call("readd", "reload_skills", {"skill_type": "mutation"})
                assert added["added"] == ["change-n"]
                await call("old_preview_stays_invalid", "execute_mutation_skill", args(proposal=doomed), reject=True)
                last = await call("added_preview", "execute_mutation_skill", args(n=11))
                assert last["preview"]["server_pid"] == pid
                last_done = await call("added_execute", "execute_mutation_skill", args(n=11, proposal=last))
                assert last_done["execution_outcome"] == "committed"
            final_truth = observe()
            assert final_truth == {"n": 11, "audit": [[7, 18], [18, 19], [19, 11]], "other_n": 8}
        return {"mode": mode, "backend": backend, "origin": origin, "identity": identity,
                "same_process": True, "calls": ledger, "independent_truth": final_truth,
                "fixture_cleanup": True, "protocol_frames_captured": False}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mysql-config", type=Path)
    parser.add_argument("--mysql-alias")
    args = parser.parse_args()
    if sys.flags.optimize or args.output.exists(): parser.error("Assertions required; choose a new output")
    if bool(args.mysql_config) != bool(args.mysql_alias): parser.error("Pass both MySQL options")
    backends = ["sqlite", "mysql"] if args.mysql_config else ["sqlite"]
    reports = [await workflow(args.python, args.package_root.resolve(), mode, backend,
                              args.mysql_config, args.mysql_alias)
               for backend in backends for mode in ("auto", "legacy")]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"reports": reports,
        "native_Host": "not tested by this script", "model_trial": False}, indent=2))
    print(json.dumps({"scenarios": len(reports), "calls": sum(len(row["calls"]) for row in reports),
                      "backends": backends, "cleanup": "verified"}))


if __name__ == "__main__":
    asyncio.run(main())
