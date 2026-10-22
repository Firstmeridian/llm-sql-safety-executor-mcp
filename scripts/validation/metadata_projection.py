"""Check projected metadata through source or installed-wheel child stdio.

Only generated temporary databases/configuration are written. Application
results are recorded; this does not collect full protocol frames/model usage.
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
    records = []
    with tempfile.TemporaryDirectory(prefix="metadata-projection-") as temp:
        root = Path(temp)
        names = ['a:b', 'a"b', "Korders", "korders", " f ", "  f  "]
        hashes = {}
        for analyzed in (False, True):
            path = root / f"stats{int(analyzed)}.db"
            with sqlite3.connect(path) as db:
                for index, name in enumerate(names):
                    quoted = '"' + name.replace('"', '""') + '"'
                    db.execute(f"CREATE TABLE {quoted}(n INTEGER)")
                    db.executemany(f"INSERT INTO {quoted} VALUES(?)", [(7,)] * (index + 1))
                if analyzed:
                    db.execute("ANALYZE")
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (root / "server.toml").write_text(
            'schema_version=1\n[files]\nconnections="connections.toml"\n'
            '[server]\ndefault_connection="nostats"\n[limits]\noverview_tables=2\nschema_tables=2\n')
        config = "schema_version=1\n"
        for alias, analyzed, grants in (
            ("nostats", False, names[:4]), ("stats", True, names[:4]), ("empty", False, ["absent"]),
        ):
            config += (f"[connections.{alias}]\ntype=\"sqlite\"\nsqlite.path=\"stats{int(analyzed)}.db\"\n"
                       "read.mode=\"allowlist\"\nread.relations=[" +
                       ",".join('{schema="main",name=' + json.dumps(name,ensure_ascii=False) + "}"
                                for name in grants) + "]\n")
        (root / "connections.toml").write_text(config)
        source_line = f"import sys;sys.path.insert(0,{str(args.source)!r})\n" if args.source else ""
        launcher = root / "serve.py"
        launcher.write_text(source_line +
            "from sql_safety_executor import create_server,load_config\n"
            "server=create_server(load_config('server.toml'))\n"
            "server.run(transport='stdio',show_banner=False)\n")
        for mode in ("auto", "legacy"):
            async with Client(StdioTransport(command=sys.executable,args=[str(launcher)],cwd=temp), mode=mode) as client:
                for alias in ("nostats", "stats", "empty"):
                    expected_names = ["a:b", 'a"b']
                    # SQLite ORDER BY uses binary name order: quote precedes colon.
                    expected_names.sort()
                    expected_counts = {'a:b':1, 'a"b':2}
                    for tool, extra in (
                        ("list_tables", {}), ("get_full_schema", {"detail_level":"compact"}),
                        ("get_full_schema", {"detail_level":"full"}),
                    ):
                        result = await client.call_tool(tool, {"connection_id":alias, **extra})
                        body = result.structured_content
                        assert body["success"]
                        assert body["total_tables"] == (0 if alias=="empty" else 4)
                        assert body["returned_table_count"] == (0 if alias=="empty" else 2)
                        assert body["truncated"] == (alias!="empty")
                        if alias!="empty":
                            if tool=="list_tables":
                                actual={t["table_name"]:t["row_count"] for t in body["tables"]}
                            elif extra["detail_level"]=="full":
                                actual={name:t["row_count"] for name,t in body["schema"].items()}
                            else:
                                actual={t["name"]:t["row_count"] for group in body["schema_groups"] for t in group["tables"]}
                            assert list(actual)==expected_names and actual==expected_counts
                        records.append({"mode":mode,"protocol":client.protocol_version,"tool":tool,
                                        "arguments":{"connection_id":alias,**extra},"response":body})
                    if alias!="empty":
                        for tool, extra in (
                            ("describe_table", {"table_name":"Korders"}),
                            ("query", {"sql":'SELECT COUNT(*) AS n FROM "Korders"'}),
                        ):
                            result=await client.call_tool(tool,{"connection_id":alias,**extra})
                            body=result.structured_content
                            assert body["success"]
                            if tool=="describe_table":
                                assert body["row_count"]==3
                            else:
                                assert body["data"]==[{"n":3}]
                            records.append({"mode":mode,"protocol":client.protocol_version,"tool":tool,
                                            "arguments":{"connection_id":alias,**extra},"response":body})
        assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==h for name,h in hashes.items())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(gzip.compress(json.dumps({
        "records":records, "database_sha256_unchanged":hashes,
        "package":str(package), "resources":{str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in package.rglob("*") if p.is_file() and p.suffix in (".py",".md")},
        "collection_layer":"Client application results; not complete frames or model usage",
    },ensure_ascii=False,indent=2).encode(),mtime=0))
    print(json.dumps({"calls":len(records),"database_unchanged":True}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.source:
        args.source=args.source.resolve()
    args.output=args.output.resolve()
    asyncio.run(check(args))
