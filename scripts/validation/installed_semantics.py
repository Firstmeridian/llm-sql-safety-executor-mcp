"""Installed-wheel, real child-stdio checks for the v3.8.2 semantic boundary.

Use a wheel-only interpreter from outside the repository. A private launcher
creates connection-local temp fixtures before serving; no configured DB is used.
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
import subprocess
import sys
import tempfile


async def check(output: Path):
    import sql_safety_executor
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    assert "site-packages" in sql_safety_executor.__file__
    records = []
    with tempfile.TemporaryDirectory(prefix="v382-wheel-") as temporary:
        directory = Path(temporary)
        with sqlite3.connect(directory / "fixture.sqlite") as native:
            native.executescript('CREATE TABLE orders(n INTEGER);INSERT INTO orders VALUES(7);CREATE TABLE hidden(n);INSERT INTO hidden VALUES(99);CREATE TABLE "main.orders"(n);INSERT INTO "main.orders" VALUES(13);CREATE TABLE "pragma_locKing_mode"(n);INSERT INTO "pragma_locKing_mode" VALUES(17);CREATE VIEW approved AS WITH internal_cte AS (SELECT n FROM hidden) SELECT n FROM internal_cte;')
            native.execute("CREATE VIEW count_approved AS WITH data AS MATERIALIZED (SELECT n FROM hidden) SELECT COUNT(*) AS n FROM data")
        (directory / "server.toml").write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="probe"\n[tools]\ntable_summary=true\n')
        (directory / "connections.toml").write_text('schema_version=1\n[connections.probe]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\nread.mode="allowlist"\nread.allow_union=true\nread.relations=[{name="orders"},{schema="main",name="orders"},{schema="main",name="main.orders"},{schema="main",name="approved"},{schema="main",name="count_approved"},{schema="main",name="pragma_locKing_mode"}]\n')
        (directory / "skills.toml").write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        for name, sql in {
            "orders-report": "WITH data(n) AS (SELECT n FROM main.orders) SELECT n FROM data",
            "view-report": "SELECT n FROM main.approved",
            "count-report": "WITH data AS MATERIALIZED (SELECT n FROM main.orders) SELECT COUNT(*) AS n FROM data",
            "unicode-report": 'SELECT n FROM main."pragma_locKing_mode"',
        }.items():
            skill = directory / "skills" / name
            skill.mkdir(parents=True)
            (skill / "skill_def.md").write_text(f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Installed semantic fixture\nparams: {{}}\n---\n")
            (skill / "query.sql").write_text(sql)
        launcher = directory / "launcher.py"
        launcher.write_text("from sql_safety_executor import create_server,load_config\nserver=create_server(load_config('server.toml'))\na=server.gateway_runtime.registry.get_adapter('probe')\nassert a.connect()\nwith a._engine.begin() as c:\n c.exec_driver_sql('CREATE TEMP TABLE orders(n)')\n c.exec_driver_sql('INSERT INTO temp.orders VALUES(100)')\nserver.run(transport='stdio',show_banner=False)\n")
        for operation in ("check", "explain"):
            process = subprocess.run([sys.executable, "-m", "sql_safety_executor", "config", operation, "--config", str(directory / "server.toml")], cwd=directory, capture_output=True, text=True)
            assert process.returncode == 0, process.stderr
        for mode in ("auto", "legacy"):
            transport = StdioTransport(command=sys.executable, args=[str(launcher)], cwd=str(directory))
            async with Client(transport, mode=mode) as client:
                async def call(tool, arguments):
                    response = await client.call_tool(tool, arguments, raise_on_error=False)
                    records.append({"mode": mode, "protocol": client.protocol_version, "tool": tool, "arguments": arguments,
                        "isError": response.is_error, "structured": response.structured_content,
                        "content": [c.model_dump(mode="json", exclude_none=True) for c in response.content]})
                    assert not response.is_error
                    return response.structured_content
                for sql, n in [("SELECT n FROM main.orders", 7), ('SELECT n FROM main."main.orders"', 13), ('SELECT n FROM main."pragma_locKing_mode"', 17), ("SELECT n FROM main.approved", 99), ("WITH window(n) AS (SELECT n FROM main.orders) SELECT n FROM window", 7), ("WITH a AS (SELECT n FROM later), later AS (SELECT 23 AS n) SELECT n FROM a", 23)]:
                    assert (await call("query", {"sql": sql}))["data"] == [{"n": n}]
                for sql in ("WITH data AS MATERIALIZED (SELECT n FROM main.orders) SELECT COUNT(*) AS n FROM data", "SELECT n FROM main.count_approved"):
                    assert (await call("query", {"sql": sql}))["data"] == [{"n": 1}]
                compound = "WITH data AS (SELECT 7 AS n) SELECT COUNT(*) AS n FROM data UNION ALL SELECT SUM(n) AS n FROM data"
                counted = await call("query", {"sql": compound})
                assert counted.get("success"), counted
                assert counted["data"] == [{"n": 1}, {"n": 7}]
                for sql, code in [("SELECT n FROM orders", "table_access_denied"), ("SELECT n FROM temp.orders", "table_access_denied"), ("SELECT n FROM main.hidden", "table_access_denied"), ("SELECT SLEEP(0)", "expensive_function_denied"), ("SELECT GET_LOCK('fixture',0)", "lock_function_denied"), ("SELECT * FROM pragma_database_list", "server_state_denied"), ("UPDATE orders SET n=19", "read_only_required"), ("SELECT CURRENT_USER FROM main.orders", "unknown_column")]:
                    assert (await call("query", {"sql": sql}))["error_code"] == code
                assert (await call("sample", {"table_name": "orders"}))["data"] == [{"n": 7}]
                assert (await call("get_table_summary", {"table_name": "orders", "exact_count": True}))["row_count"] == 1
                assert (await call("describe_table", {"table_name": "main.orders"}))["row_count"] == 1
                full = await call("list_skills", {"detail_level": "full"})
                assert len(full["skills"]) == 4 and all(s["executable"] and s["analysis_complete"] for s in full["skills"])
                for name, n in [("orders-report", 7), ("view-report", 99), ("count-report", 1), ("unicode-report", 17)]:
                    detail = await call("get_skill_detail", {"skill_name": name, "detail_level": "full"})
                    assert detail["skill"]["schema_ready"]
                    assert (await call("execute_query_skill", {"skill_name": name, "params": {}}))["data"] == [{"n": n}]
        result = {"version": sql_safety_executor.__version__, "calls": len(records), "records": records,
            "installed_source_sha256": {str(p.relative_to(Path(sql_safety_executor.__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(sql_safety_executor.__file__).parent.rglob("*")) if p.is_file() and p.suffix in {".py", ".md"}},
            "recording_profile": "Real child stdio; decoded application content/structured results. Full frames/notifications not captured. Private temporary fixtures only."}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(gzip.compress((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode(), mtime=0))
        print(json.dumps({"version": result["version"], "calls": len(records), "passed": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new batch")
    output = args.output.resolve()
    os.chdir(tempfile.gettempdir())
    asyncio.run(check(output))
