"""Reproducible child-stdio checks for views, JSON, FTS and schema scope.

Use --source <absolute-src> for source; otherwise use an independent wheel
interpreter. Only disposable fixtures are written. Records are application
results, not complete JSON-RPC frames or model-usage evidence.
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


async def check(args):
    if args.source:
        sys.path.insert(0, str(args.source))
    import sql_safety_executor
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    package = Path(sql_safety_executor.__file__).resolve().parent
    assert package == args.source / "sql_safety_executor" if args.source else "site-packages" in str(package)
    assert not args.output.exists(), "Use a fresh output path; preserve earlier evidence."
    records, inventories = [], []
    with tempfile.TemporaryDirectory(prefix="v382-read-capabilities-") as temporary:
        root = Path(temporary)
        database = root / "fixture.sqlite"
        with sqlite3.connect(database) as db:
            db.executescript(
                "CREATE TABLE orders(n);INSERT INTO orders VALUES(7);"
                "CREATE TABLE hidden(n);INSERT INTO hidden VALUES(99);"
                "CREATE TABLE audit_log(n);"
                "CREATE VIEW approved AS SELECT n FROM (SELECT n FROM hidden) AS chosen;"
                "CREATE VIEW json_view AS SELECT value AS n FROM json_each('[7,8]');"
                "CREATE VIEW catalog_view AS SELECT name FROM main.sqlite_schema WHERE name='orders';"
                "CREATE VIEW blocked_view AS SELECT n FROM hidden WHERE SLEEP(n)=0;"
                "CREATE TABLE docs(id INTEGER PRIMARY KEY,title TEXT,body TEXT);"
                "INSERT INTO docs VALUES(1,'Hello world','alpha'),(2,'Other title','beta');"
                "CREATE VIRTUAL TABLE docs_fts USING fts5(title,body,content='docs',content_rowid='id');"
                "INSERT INTO docs_fts(rowid,title,body) SELECT id,title,body FROM docs;"
                "CREATE TRIGGER order_audit AFTER INSERT ON orders BEGIN INSERT INTO audit_log "
                "SELECT (WITH chosen AS MATERIALIZED (SELECT value FROM json_each('[7,8]')) SELECT COUNT(*) FROM chosen);END;"
            )
            native_truth = {
                "derived": db.execute("SELECT n FROM approved").fetchall(),
                "json": db.execute("SELECT n FROM json_view ORDER BY n").fetchall(),
                "fts": db.execute("SELECT title FROM docs_fts('hello')").fetchall(),
            }
        original_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        (root / "server.toml").write_text(
            'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
            '[server]\ndefault_connection="scoped"\n[tools]\ntable_summary=true\n')
        (root / "connections.toml").write_text(
            'schema_version=1\n[connections.scoped]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\n'
            'read.mode="allowlist"\nread.allow_union=true\n'
            'read.relations=[{schema="main",name="orders"},{name="approved"},{name="json_view"},'
            '{name="docs_fts"},{name="audit_log"},{name="blocked_view"},{name="catalog_view"}]\n'
            '[connections.all_scope]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\nread.mode="all"\nread.allow_union=true\n')
        (root / "skills.toml").write_text(
            'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
            '[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        for name, sql in {
            "derived-report": "SELECT n FROM main.approved",
            "json-report": "SELECT n FROM json_view ORDER BY n",
            "fts-report": "SELECT title FROM docs_fts('hello')",
            "plan-report": "EXPLAIN WITH data AS (SELECT 99 AS n) REPLACE INTO orders SELECT n FROM data",
        }.items():
            skill = root / "skills" / name
            skill.mkdir(parents=True)
            (skill / "skill_def.md").write_text(
                f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Read capability\nparams: {{}}\n---\n")
            (skill / "query.sql").write_text(sql)
        source_line = f"import sys;sys.path.insert(0,{str(args.source)!r})\n" if args.source else ""
        launcher = root / "launcher.py"
        launcher.write_text(source_line +
            "from sql_safety_executor import create_server,load_config\n"
            "server=create_server(load_config('server.toml'))\ncalls=[]\n"
            "for alias in ('scoped','all_scope'):\n"
            " adapter=server.gateway_runtime.registry.get_adapter(alias)\n adapter.connect()\n"
            " with adapter._engine.begin() as db:\n"
            "  raw=db.connection.dbapi_connection\n"
            "  raw.create_function('SLEEP',1,lambda n:calls.append(n) or 0)\n"
            "  raw.create_function('boundary_calls',0,lambda:len(calls))\n"
            "  if alias=='all_scope':\n"
            "   db.exec_driver_sql('CREATE TEMP TABLE orders(n)')\n"
            "   db.exec_driver_sql('INSERT INTO temp.orders VALUES(123)')\n"
            "   db.exec_driver_sql(\"ATTACH ':memory:' AS aux\")\n"
            "   db.exec_driver_sql('CREATE TABLE aux.orders(n)')\n"
            "   db.exec_driver_sql('INSERT INTO aux.orders VALUES(456)')\n"
            "server.run(transport='stdio',show_banner=False)\n")
        environment = os.environ.copy()
        if args.source:
            environment["PYTHONPATH"] = str(args.source)
        for mode in ("auto", "legacy"):
            transport = StdioTransport(command=sys.executable, args=[str(launcher)], cwd=str(root), env=environment)
            async with Client(transport, mode=mode) as client:
                inventories.append({"mode": mode, "protocol": client.protocol_version,
                    "tools": [tool.model_dump(mode="json", exclude_none=True) for tool in await client.list_tools()]})

                async def call(tool, arguments, *, data=None, code=None):
                    arguments = {"connection_id": "scoped", **arguments}
                    result = await client.call_tool(tool, arguments, raise_on_error=False)
                    payload = result.structured_content
                    records.append({"mode": mode, "tool": tool, "arguments": arguments,
                        "isError": result.is_error, "structured": payload,
                        "content": [item.model_dump(mode="json", exclude_none=True) for item in result.content]})
                    assert not result.is_error, records[-1]
                    assert isinstance(payload, dict)
                    if code:
                        assert payload.get("success") is False and payload.get("error_code") == code, records[-1]
                    elif data is not None:
                        assert payload.get("data") == data, records[-1]
                    else:
                        assert payload.get("success", True) is not False, records[-1]
                    return payload

                await call("query", {"sql": "SELECT n FROM orders"}, data=[{"n": 7}])
                await call("query", {"sql": "SELECT n FROM main.orders"}, data=[{"n": 7}])
                for name, sql, data in [
                    ("derived-report", "SELECT n FROM approved", [{"n": 99}]),
                    ("json-report", "SELECT n FROM json_view ORDER BY n", [{"n": 7}, {"n": 8}]),
                    ("fts-report", "SELECT title FROM docs_fts('hello')", [{"title": "Hello world"}]),
                ]:
                    await call("query", {"sql": sql}, data=data)
                    await call("execute_query_skill", {"skill_name": name, "params": {}}, data=data)
                    detail = await call("get_skill_detail", {"skill_name": name})
                    assert detail["skill"]["executable"]
                listing = await call("list_skills", {"detail_level": "full"})
                assert len(listing["skills"]) == 4
                await call("query", {"sql": "SELECT COUNT(*) AS n FROM catalog_view"}, data=[{"n": 1}])
                await call("query", {"sql": "SELECT name FROM catalog_view"}, data=[{"name": "orders"}])
                for table, count in [("approved", 1), ("json_view", 2), ("docs_fts", 2), ("catalog_view", 1)]:
                    for tool, extra in [("sample", {}), ("describe_table", {}),
                                        ("get_table_summary", {}), ("get_table_summary", {"exact_count": True})]:
                        payload = await call(tool, {"table_name": table, **extra})
                        assert payload["row_count"] == count
                for sql, code in [
                    ("SELECT n FROM (SELECT n FROM orders)", "relation_group_unsupported"),
                    ("SELECT * FROM hidden", "table_access_denied"),
                    ("SELECT name FROM sqlite_schema", "table_access_denied"),
                    ("SELECT * FROM docs", "table_access_denied"),
                    ("SELECT * FROM docs_fts_idx", "table_access_denied"),
                    ("SELECT docs.title FROM docs,docs_fts('hello')", "table_access_denied"),
                    ("SELECT * FROM pragma_data_version,docs_fts('hello')", "server_state_denied"),
                    ("SELECT * FROM blocked_view", "expensive_function_denied"),
                    ("SELECT ?1", "parameter_binding_unsupported"),
                    ("INSERT INTO orders VALUES(99)", "read_only_required"),
                ]:
                    await call("query", {"sql": sql}, code=code)
                for tool, extra in [("sample", {}), ("get_table_summary", {"exact_count": True})]:
                    await call(tool, {"table_name": "blocked_view", **extra}, code="expensive_function_denied")
                estimate = await call("describe_table", {"table_name": "blocked_view"})
                assert estimate["row_count"] is None
                await call("execute_query_skill", {"skill_name": "plan-report", "params": {}})
                await call("query", {"sql": "SELECT boundary_calls() AS n"}, data=[{"n": 0}])
                await call("query", {"sql": "SELECT COUNT(*) AS n FROM audit_log"}, data=[{"n": 0}])
                for source in ("orders", "temp.orders", "aux.orders"):
                    await call("query", {"sql": f"SELECT n FROM {source}", "connection_id": "all_scope"}, code="table_access_denied")
                await call("query", {"sql": "SELECT n FROM main.orders", "connection_id": "all_scope"}, data=[{"n": 7}])
                for catalog in ("sqlite_master", "sqlite_schema"):
                    star = await call("query", {"sql": f"SELECT COUNT(*) AS n FROM {catalog}", "connection_id": "all_scope"})
                    named = await call("query", {"sql": f"SELECT COUNT(name) AS n FROM {catalog}", "connection_id": "all_scope"})
                    assert star["data"] == named["data"]
        assert hashlib.sha256(database.read_bytes()).hexdigest() == original_hash
        payload = {"package": str(package), "version": sql_safety_executor.__version__,
            "collection_layer": "Client application results; not full JSON-RPC frames or model usage",
            "sqlite": sqlite3.sqlite_version, "database_sha256_unchanged": original_hash,
            "native_truth": native_truth, "inventories": inventories, "records": records,
            "package_files": {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in package.rglob("*") if path.suffix in {".py", ".md"}}}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(args.output, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"calls": len(records), "protocols": [item["protocol"] for item in inventories],
                          "database_unchanged": True, "package": str(package)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source:
        args.source = args.source.resolve()
    args.output = args.output.resolve()
    asyncio.run(check(args))
