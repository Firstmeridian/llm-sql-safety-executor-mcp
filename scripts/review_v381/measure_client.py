"""Fixed Client trace on private SQLite; source A/B/C, never live effects."""
import argparse
import asyncio
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=ROOT / "src")
parser.add_argument("--stage", required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source))
from fastmcp import Client
from sql_safety_executor import create_server, load_config
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
OUTPUT = ROOT / "docs/validation/v3.8/phase123_2026_10_14"
base = load_config(ROOT / "config/server.toml")
SQL = [
    ("query", {"sql": "WITH F AS (SELECT COUNT(*) AS n FROM orders) SELECT n FROM f"}),
    ("query", {"sql": "SELECT 'SLEEP(99)' AS label, ABS(-7) AS n"}),
    ("query", {"sql": "SELECT SLEEP(0) AS n"}),
    ("query", {"sql": "SELECT GET_LOCK('probe',0) AS n"}),
    ("execute_query_skill", {"skill_name": "delay-probe", "params": {}}),
]

def compact(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

async def main():
    records = []
    with tempfile.TemporaryDirectory(prefix="phase123-client-") as directory:
        path = Path(directory)
        db = path / "fixture.sqlite"
        with sqlite3.connect(db) as conn:
            conn.executescript("CREATE TABLE orders(id INTEGER);INSERT INTO orders VALUES(1),(2),(3);")
        skill = path / "skills/delay-probe"
        skill.mkdir(parents=True)
        (skill / "skill_def.md").write_text("---\nname: delay-probe\ntype: query\nsource: query.sql\nrisk: low\ndescription: Controlled delay-function refusal\nparams: {}\n---\n")
        (skill / "query.sql").write_text("SELECT SLEEP(0) AS n")
        cfg = DatabaseConfig(connection_id="probe", db_type="sqlite", sqlite_database_path=str(db),
            query_timeout_seconds=30, connect_timeout_seconds=10,
            policy=ConnectionPolicy(allowed_tables=frozenset({"orders"})))
        skills = base.skills.model_copy(update={"enabled": True, "directory": str(skill.parent),
            "readiness": base.skills.readiness.model_copy(update={"check_schema": False}),
            "mutation": base.skills.mutation.model_copy(update={"enabled": False}),
            "audit": base.skills.audit.model_copy(update={"path": str(path/"audit.jsonl")})})
        settings = base.server.model_copy(update={"server": base.server.server.model_copy(update={"default_connection": "probe"})})
        config = replace(base, server=settings, skills=skills, connections=MappingProxyType({"probe": cfg}))
        for mode in ("auto", "legacy"):
            server = create_server(config)
            try:
                async with Client(server, mode=mode) as client:
                    tools = await client.list_tools()
                    metadata = {"instructions": client.instructions, "tools": [
                        {"name": t.name, "description": t.description, "inputSchema": t.inputSchema, "outputSchema": t.outputSchema}
                        for t in tools]}
                    raw = compact(metadata).encode()
                    name = args.stage + "-metadata-" + client.protocol_version + ".json.gz"
                    (OUTPUT / name).write_bytes(gzip.compress(raw, mtime=0))
                    samples, first = [], []
                    for repeat in range(12):
                        elapsed = []
                        for tool, parameters in SQL:
                            started = time.perf_counter_ns()
                            result = await client.call_tool(tool, {**parameters, "connection_id": "probe"}, raise_on_error=False)
                            elapsed.append((time.perf_counter_ns()-started)/1e6)
                            if repeat == 0:
                                first.append({"tool": tool, "params": {**parameters, "connection_id":"probe"},
                                    "result": {"content": [c.model_dump(mode="json",exclude_none=True) for c in result.content],
                                        "structuredContent": result.structured_content, "isError": result.is_error, "meta": result.meta}})
                        samples.append(elapsed)
                    discovery = await client.call_tool("list_skills", {"connection_id":"probe","available_only":False,"detail_level":"full"})
                    assert first[0]["result"]["structuredContent"]["data"] == [{"n":3}]
                    assert first[1]["result"]["structuredContent"]["success"] is True
                    fixed_input = {"instructions": metadata["instructions"], "tools": [
                        {k:v for k,v in t.items() if k!="outputSchema"} for t in metadata["tools"]]}
                    records.append({"protocol": client.protocol_version, "metadata_path": name,
                        "metadata_sha256": hashlib.sha256(raw).hexdigest(),
                        "fixed_metadata_characters_without_output_schema": len(compact(fixed_input)),
                        "output_schema_characters": sum(len(compact(t["outputSchema"])) for t in metadata["tools"]),
                        "samples_ms": samples, "trace_median_ms": statistics.median(sum(x) for x in samples[1:]),
                        "trace": first, "discovery": discovery.structured_content,
                        "structured_result_characters": [len(compact(r["result"]["structuredContent"])) for r in first],
                        "text_result_characters": [sum(len(c.get("text","")) for c in r["result"]["content"]) for r in first]})
            finally:
                server.gateway_runtime.close()
    (OUTPUT / (args.stage + "_client.json")).write_text(json.dumps({"stage":args.stage,"records":records,
        "scope":"Actual in-process Client, decoded application results; repeated returned payloads stored once",
        "limits":"No full transport capture; characters are not model tokens; fixed trace does not imply model billing",
        "writes":"Only private temporary SQLite fixture; no configured database modified"}, ensure_ascii=False,indent=2)+"\n")
    print(args.stage, "Client traces passed", [r["protocol"] for r in records])

asyncio.run(main())
