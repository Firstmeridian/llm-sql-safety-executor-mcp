"""Structured declarations remain identities across raw/Skill/metadata entry points."""
import sqlite3
import json

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.config.loader import ConfigError
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", ["main.orders", " f ", "*", ":binding", 'a"b'])
async def test_structured_name_is_not_reparsed_as_a_grant(bundle, tmp_path, mode, name):
    _, connections, skills, save = bundle
    quoted = '"' + name.replace('"', '""') + '"'
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        conn.executescript("CREATE TABLE orders(n);INSERT INTO orders VALUES(7);")
        conn.execute(f"CREATE TABLE main.{quoted}(n)")
        conn.execute(f"INSERT INTO main.{quoted} VALUES(99)")
    target = connections["connections"]["demo"]
    target["read"] = {"mode": "allowlist", "relations": [{"schema": "main", "name": name}]}
    directory = tmp_path / "skills" / "structured-read"
    directory.mkdir(parents=True)
    declaration = json.dumps([{"schema": "main", "name": name}], ensure_ascii=False)
    (directory / "skill_def.md").write_text("---\nname: structured-read\ntype: query\nsource: query.sql\nrisk: low\ndescription: Literal structured relation\nparams: {}\nrelations: " + declaration + "\n---\n")
    (directory / "query.sql").write_text(f"SELECT n FROM main.{quoted}")
    skills["skills"] = {"enabled": True, "directory": str(directory.parent), "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            denied = (await client.call_tool("query", {"sql": "SELECT n FROM main.orders"})).structured_content
            assert denied["error_code"] == "table_access_denied"
            raw = (await client.call_tool("query", {"sql": f"SELECT n FROM main.{quoted}"})).structured_content
            assert raw["data"] == [{"n": 99}]
            listing = (await client.call_tool("list_skills", {"detail_level": "full"})).structured_content
            assert len(listing["skills"]) == 1
            assert listing["skills"][0]["schema_ready"]
            assert listing["skills"][0]["analysis_complete"]
            assert listing["skills"][0]["declared_tables"] == listing["skills"][0]["inferred_tables"]
            executed = (await client.call_tool("execute_query_skill", {"skill_name": "structured-read", "params": {}})).structured_content
            assert executed["data"] == raw["data"]
            described = (await client.call_tool("describe_table", {"table_name": name})).structured_content
            assert described["success"] and described["row_count"] == 1
            sample = (await client.call_tool("sample", {"table_name": name, "limit": 1})).structured_content
            assert sample["data"] == raw["data"]
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("grant", [{"name": "x", "schema": "main", "unexpected": True}, {"name": ""}, {"name": "a\x00b"}, {"name": "x", "schema": ""}])
def test_structured_grant_rejects_invalid_components_and_unknown_keys(bundle, grant):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "relations": [grant]}
    with pytest.raises(ConfigError):
        load_config(save())


def test_offline_explain_serializes_structured_relations(bundle, capsys):
    from sql_safety_executor.cli import main
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "relations": [{"schema": "main", "name": "main.orders"}]}
    config = save()
    assert main(["config", "explain", "--config", str(config)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "main.orders" in json.dumps(result)
