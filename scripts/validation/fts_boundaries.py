"""Exercise FTS cold/warm content guards and schema grants over child stdio.

Writes only disposable SQLite fixtures/configuration. Logs application results,
not full JSON-RPC frames or model usage. Source and installed wheels use the
same script. Restricted test functions count calls and never sleep/read files.
"""
import argparse
import asyncio
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


DDL = """
CREATE TABLE docs(id INTEGER PRIMARY KEY,title TEXT,body TEXT);
INSERT INTO docs VALUES(1,'Hello world','alpha');
CREATE VIEW content_view AS SELECT id,SLEEP(0) AS title,body FROM docs;
CREATE VIEW safe_view AS SELECT * FROM (SELECT id,lower(title) AS title,body FROM docs);
CREATE VIRTUAL TABLE view_fts USING fts5(title,body,content='content_view',content_rowid='id');
CREATE VIRTUAL TABLE safe_fts USING fts5(title,body,content='safe_view',content_rowid='id');
INSERT INTO view_fts(rowid,title,body) VALUES(1,'Hello world','alpha');
INSERT INTO safe_fts(rowid,title,body) VALUES(1,'hello world','alpha');
"""


async def check(args):
    if args.source:
        sys.path.insert(0, str(args.source))
    import sql_safety_executor
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    package = Path(sql_safety_executor.__file__).resolve().parent
    assert package == args.source / "sql_safety_executor" if args.source else package.is_relative_to(Path(sys.prefix))
    assert not args.output.exists()
    records, inventories = [], []
    with tempfile.TemporaryDirectory(prefix="fts-boundaries-") as temp:
        root = Path(temp)
        hashes = {}
        config = "schema_version=1\n"
        for alias in ("cold", "columns", "trusted", "all_scope"):
            path = root / f"{alias}.db"
            with sqlite3.connect(path) as db:
                db.executescript(DDL)
            hashes[alias] = hashlib.sha256(path.read_bytes()).hexdigest()
            config += (f'[connections.{alias}]\ntype="sqlite"\nsqlite.path="{alias}.db"\n')
            if alias == "all_scope":
                config += 'read.mode="all"\n'
            else:
                config += ('read.mode="allowlist"\nread.relations=['
                    '{schema="main",name="view_fts"},{schema="main",name="safe_fts"},'
                    '{schema="aux",name="aux_fts"}]\n')
        (root / "connections.toml").write_text(config)
        (root / "server.toml").write_text(
            'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
            '[server]\ndefault_connection="cold"\n[tools]\ntable_summary=true\n')
        (root / "skills.toml").write_text(
            'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
            '[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        skill = root / "skills" / "fts-report"
        skill.mkdir(parents=True)
        (skill / "skill_def.md").write_text(
            '---\nname: fts-report\ntype: query\nsource: query.sql\nrisk: low\n'
            'description: FTS report\nparams: {}\n---\n')
        (skill / "query.sql").write_text("SELECT title FROM view_fts('hello')")
        source_line = f"import sys;sys.path.insert(0,{str(args.source)!r})\n" if args.source else ""
        launcher = root / "serve.py"
        launcher.write_text(source_line +
            "from sql_safety_executor import create_server,load_config\n"
            "server=create_server(load_config('server.toml'))\n"
            "for alias in ('cold','columns','trusted','all_scope'):\n"
            " adapter=server.gateway_runtime.registry.get_adapter(alias)\n adapter.connect()\n"
            " calls=[]\n"
            " with adapter._engine.begin() as db:\n"
            "  raw=db.connection.dbapi_connection\n"
            "  raw.create_function('SLEEP',1,lambda n,c=calls:c.append(n) or 'Hello world')\n"
            "  raw.create_function('boundary_calls',0,lambda c=calls:len(c))\n"
            "  raw.executescript(\"ATTACH ':memory:' AS aux;CREATE VIRTUAL TABLE aux.aux_fts USING fts5(title);INSERT INTO aux.aux_fts VALUES('Hello world');\")\n"
            " if alias=='columns':adapter.get_columns('view_fts')\n"
            " if alias=='trusted':adapter.execute(\"SELECT title FROM view_fts WHERE view_fts MATCH 'hello'\")\n"
            "server.run(transport='stdio',show_banner=False)\n")
        for mode in ("auto", "legacy"):
            transport = StdioTransport(command=sys.executable, args=[str(launcher)], cwd=temp)
            async with Client(transport, mode=mode) as client:
                inventories.append({"mode": mode, "protocol": client.protocol_version,
                    "tools": [tool.model_dump(mode="json", exclude_none=True) for tool in await client.list_tools()]})

                async def call(alias, tool, arguments, *, code=None, data=None):
                    arguments = {"connection_id": alias, **arguments}
                    result = await client.call_tool(tool, arguments, raise_on_error=False)
                    body = result.structured_content
                    records.append({"mode": mode, "tool": tool, "arguments": arguments,
                        "isError": result.is_error, "structured": body,
                        "content": [item.model_dump(mode="json", exclude_none=True) for item in result.content]})
                    assert not result.is_error and isinstance(body, dict), records[-1]
                    if code:
                        assert body.get("success") is False and body.get("error_code") == code, records[-1]
                    elif data is not None:
                        assert body.get("data") == data, records[-1]
                    else:
                        assert body.get("success", True) is not False, records[-1]
                    return body

                for alias in ("cold", "columns", "trusted"):
                    before = [{"n": 1 if alias == "trusted" else 0}]
                    await call(alias, "query", {"sql": "SELECT boundary_calls() AS n"}, data=before)
                    for sql in ("SELECT title FROM view_fts WHERE view_fts MATCH 'hello'",
                                "SELECT title FROM view_fts('hello')"):
                        await call(alias, "query", {"sql": sql}, code="expensive_function_denied")
                    await call(alias, "execute_query_skill", {"skill_name": "fts-report", "params": {}}, code="expensive_function_denied")
                    await call(alias, "sample", {"table_name": "view_fts"}, code="expensive_function_denied")
                    await call(alias, "get_table_summary", {"table_name": "view_fts", "exact_count": True}, code="expensive_function_denied")
                    metadata = await call(alias, "describe_table", {"table_name": "view_fts"})
                    assert metadata["row_count"] is None
                    await call(alias, "query", {"sql": "SELECT title FROM safe_fts('hello')"}, data=[{"title": "hello world"}])
                    for source in ("docs", "content_view", "view_fts_idx"):
                        await call(alias, "query", {"sql": "SELECT * FROM " + source}, code="table_access_denied")
                    for sql, data in (
                        ("SELECT title FROM aux.aux_fts WHERE aux_fts MATCH 'hello'", [{"title": "Hello world"}]),
                        ("SELECT title FROM aux.aux_fts('hello')", [{"title": "Hello world"}]),
                        ("SELECT 'Hello world' IN aux.aux_fts('hello') AS n", [{"n": 1}]),
                    ):
                        await call(alias, "query", {"sql": sql}, data=data)
                    await call(alias, "query", {"sql": "SELECT * FROM aux.json_each('[7]')"}, code="relation_scope_unresolved")
                    await call(alias, "query", {"sql": "SELECT * FROM aux.aux_fts_idx"}, code="table_access_denied")
                    await call(alias, "query", {"sql": "SELECT boundary_calls() AS n"}, data=before)
                await call("all_scope", "query", {"sql": "SELECT title FROM aux.aux_fts('hello')"}, code="table_access_denied")
                await call("all_scope", "query", {"sql": "SELECT COUNT(*) AS n FROM main.docs"}, data=[{"n": 1}])
        for alias, digest in hashes.items():
            assert hashlib.sha256((root / f"{alias}.db").read_bytes()).hexdigest() == digest
        payload = {"version": sql_safety_executor.__version__, "package": str(package),
            "collection_layer": "Client application results, not full JSON-RPC frames or model usage",
            "sqlite": sqlite3.sqlite_version, "unchanged_databases": hashes,
            "inventories": inventories, "records": records,
            "package_files": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in package.rglob("*") if p.is_file() and p.suffix in {".py", ".md"}}}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False, indent=2).encode(), mtime=0))
        print(json.dumps({"calls": len(records), "protocols": [row["protocol"] for row in inventories],
                          "databases_unchanged": True, "package": str(package)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.source:
        options.source = options.source.resolve()
    options.output = options.output.resolve()
    asyncio.run(check(options))
