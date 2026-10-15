"""Literal internal-name filtering must retain legitimate table/view names."""

import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("kind", ["table", "view"])
@pytest.mark.parametrize("name", ["sqliteXorders", "SQLITEXorders", "sqlite"])
async def test_literal_internal_prefix_across_directories_and_skills(bundle, tmp_path, mode, kind, name):
    _, connections, skills, save = bundle
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        if kind == "table":
            db.execute(f'CREATE TABLE "{name}"(n INTEGER)')
            db.execute(f'INSERT INTO "{name}" VALUES(7)')
        else:
            db.execute(f'CREATE VIEW "{name}" AS SELECT 7 AS n')
        db.executescript("CREATE TABLE control(id INTEGER PRIMARY KEY AUTOINCREMENT); INSERT INTO control DEFAULT VALUES;")
        assert db.execute("SELECT name FROM main.sqlite_master WHERE name='sqlite_sequence'").fetchone()
    directory = tmp_path / "skills" / "prefix-read"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text("---\nname: prefix-read\ntype: query\nsource: query.sql\nrisk: low\ndescription: Literal prefix\nparams: {}\n---\n")
    sql = f'SELECT n FROM main."{name}"'
    (directory / "query.sql").write_text(sql)
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["main." + name]}
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    try:
        async with Client(server, mode=mode) as client:
            raw = await client.call_tool("query", {"sql": sql})
            tables = await client.call_tool("list_tables", {})
            full = await client.call_tool("get_full_schema", {"detail_level": "full"})
            listed = await client.call_tool("list_skills", {"detail_level": "full"})
            detail = await client.call_tool("get_skill_detail", {"skill_name": "prefix-read"})
            executed = await client.call_tool("execute_query_skill", {"skill_name": "prefix-read", "params": {}})
            assert raw.structured_content["data"] == executed.structured_content["data"] == [{"n": 7}]
            for state in (listed.structured_content["skills"][0], detail.structured_content["skill"]):
                assert state["policy_allowed"] and state["schema_ready"] and state["executable"]
                assert state["missing_tables"] == state["unverified_tables"] == []
            assert [t["table_name"] for t in tables.structured_content["tables"]] == ([name] if kind == "table" else [])
            assert set(full.structured_content["schema"]) == ({name} if kind == "table" else set())
            observed = adapter.get_read_relations()
            assert any(r.reference.name == name and r.kind == kind for r in observed)
            assert all(not r.reference.name.startswith("sqlite_") for r in observed)
            assert all(not t["table_name"].startswith("sqlite_") for t in adapter.get_tables())
    finally:
        server.gateway_runtime.close()
