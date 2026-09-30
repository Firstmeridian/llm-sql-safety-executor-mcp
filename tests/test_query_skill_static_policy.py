"""Discovery must preflight cached Query SQL against the selected connection."""

import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from tests.test_v38_config import bundle as bundle

SKILL = "static-policy-probe"


@pytest.fixture
def policy_server(bundle, tmp_path):
    main, connections, skills, save = bundle
    directory = tmp_path / "skills" / SKILL
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        "---\nname: static-policy-probe\nversion: '1.0'\n"
        "description: Static policy regression\ntype: query\n"
        "source: query.sql\nrisk: low\nparams: {}\n---\n",
        encoding="utf-8",
    )
    skills["skills"] = {
        "enabled": True,
        "directory": str(directory.parent),
        "readiness": {"check_schema": False},
        "audit": {"path": str(tmp_path / "audit.jsonl")},
    }
    main["server"]["default_connection"] = "denied"
    servers = []

    def build(sql, denied_read, allowed_read):
        source = directory / "query.sql"
        source.write_text(sql, encoding="utf-8")
        connections["connections"] = {}
        for alias, read in (("denied", denied_read), ("allowed", allowed_read)):
            path = tmp_path / f"{alias}.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE items(value INTEGER)")
                db.execute("INSERT INTO items VALUES(7)")
            connections["connections"][alias] = {
                "type": "sqlite", "sqlite": {"path": str(path)}, "read": read,
            }
        server = create_server(load_config(save(use_skills=True)))
        servers.append(server)
        # Neither discovery nor execution may re-read a changed/missing source.
        source.unlink()
        return server

    yield build
    for server in servers:
        server.gateway_runtime.close()


async def assert_policy_contract(server, mode, reason, expected_data, monkeypatch):
    def unexpected_io(*args, **kwargs):
        pytest.fail("Static discovery or denied execution performed database I/O")

    for alias in ("denied", "allowed"):
        adapter = server.gateway_runtime.registry.get_adapter(alias)
        monkeypatch.setattr(adapter, "get_tables", unexpected_io)
        if alias == "denied":
            monkeypatch.setattr(adapter, "execute", unexpected_io)

    async with Client(server, mode=mode) as client:
        # The default denies this template, but it must remain in the catalog.
        default = await client.call_tool("list_skills", {})
        assert default.structured_content["skills"] == []
        # Alternating targets also detects a mistakenly shared policy verdict.
        for alias in ("denied", "allowed", "denied"):
            allowed = alias == "allowed"
            visible = await client.call_tool("list_skills", {"connection_id": alias})
            assert bool(visible.structured_content["skills"]) is allowed
            full = await client.call_tool("list_skills", {
                "connection_id": alias, "available_only": False, "detail_level": "full",
            })
            row = full.structured_content["skills"][0]
            assert row["name"] == SKILL
            assert row["executable"] is allowed and row["policy_allowed"] is allowed
            if not allowed:
                assert reason in row["disabled_reason"]
            for projection in ("execution", "full"):
                detail = await client.call_tool("get_skill_detail", {
                    "skill_name": SKILL, "connection_id": alias, "detail_level": projection,
                })
                assert detail.structured_content["skill"]["executable"] is allowed
                if not allowed:
                    assert reason in detail.structured_content["usage_hint"]
            result = await client.call_tool("execute_query_skill", {
                "skill_name": SKILL, "params": {}, "connection_id": alias,
            }, raise_on_error=False)
            assert result.is_error is not allowed
            if allowed:
                assert result.structured_content["data"] == expected_data
                assert result.structured_content["connection_id"] == alias
            else:
                assert reason in str(result)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
async def test_union_discovery_obeys_each_connection(policy_server, monkeypatch, mode, read_mode):
    read = {"mode": read_mode}
    if read_mode == "allowlist":
        read["tables"] = ["items"]
    server = policy_server(
        "SELECT 1 AS value UNION ALL SELECT 2 AS value",
        {**read, "allow_union": False}, {**read, "allow_union": True},
    )
    await assert_policy_contract(
        server, mode, "UNION queries disabled", [{"value": 1}, {"value": 2}], monkeypatch
    )


async def test_discovery_reuses_parsed_table_policy_not_only_union(policy_server, monkeypatch):
    server = policy_server(
        'SELECT value FROM "items"',
        {"mode": "allowlist", "tables": ["other"]},
        {"mode": "allowlist", "tables": ["items"]},
    )
    # Metadata extraction is intentionally only a catalog heuristic. The full
    # SQL policy must still check a quoted table it does not enumerate.
    assert server.gateway_runtime.catalog.get_skills_cache()[SKILL].tables == []
    await assert_policy_contract(
        server, "auto", "Access denied to table(s): items", [{"value": 7}], monkeypatch
    )


async def test_missing_cached_template_never_claims_executable(policy_server):
    server = policy_server("SELECT 1", {"mode": "all"}, {"mode": "all"})
    server.gateway_runtime.catalog.get_skills_cache()[SKILL]._sql_template = None
    async with Client(server) as client:
        visible = await client.call_tool("list_skills", {})
        assert visible.structured_content["skills"] == []
        detail = await client.call_tool("get_skill_detail", {"skill_name": SKILL})
        assert detail.structured_content["skill"]["policy_allowed"] is False
        assert "SQL template" in detail.structured_content["usage_hint"]
        result = await client.call_tool("execute_query_skill", {
            "skill_name": SKILL, "params": {},
        }, raise_on_error=False)
        assert result.is_error and "SQL template" in str(result)
