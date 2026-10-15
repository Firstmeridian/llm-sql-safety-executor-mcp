"""Keyword-like CTE names are reads; genuinely unresolved WITH stays closed."""
import sqlite3
import sqlparse

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.sql import classify_sql_statement
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle

NAMES = ["unıon", "offſet", "wındow", "window", "offset", "lock", "user"]


def query(name, quote="{}"):
    target = quote.format(name)
    return f"WITH {target} AS (SELECT 7 AS n)\nSELECT n FROM {target};"


def assert_read_recovery(decision):
    assert not decision.allowed and decision.error_code == "sql_parse_failed"
    assert decision.message and "WITH" in decision.message
    hint = decision.hint or ""
    assert "same connection" in hint and "CTE" in hint
    assert all(word not in hint.lower() for word in ("mutation", "list_skills", "preview"))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("quote", ["{}", '"{}"', "`{}`", "[{}]"])
def test_native_cte_identity_does_not_depend_on_get_type_grouping(name, quote):
    sql = query(name, quote)
    with sqlite3.connect(":memory:") as db:
        assert db.execute(sql).fetchall() == [(7,)]
    decision = classify_sql_statement(sql)
    policy_decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    if quote == "{}":
        assert sqlparse.parse(sql)[0].get_type() == "UNKNOWN"
    assert decision.allowed and policy_decision.allowed


@pytest.mark.parametrize("sql", [
    "WITH", "WITH x AS",
    "WITH x AS (SELECT 7)",
    "WITH x(n,) AS (SELECT 7) SELECT n FROM x",
    "WITH x AS NOT (SELECT 7) SELECT n FROM x",
    "WITH main.x AS (SELECT 7) SELECT * FROM main.x",
])
def test_unknown_with_remains_closed_without_write_discovery(sql):
    assert_read_recovery(classify_sql_statement(sql))


@pytest.mark.parametrize("sql", [
    "UPDATE orders SET n=99",
    "INSERT INTO orders VALUES(99)",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "WITH c AS (SELECT 7 AS n) UPDATE orders SET n=99",
    "WITH window AS (SELECT 7 AS n) UPDATE orders SET n=99",
    "WITH unıon AS (SELECT 7 AS n) DELETE FROM orders",
])
def test_known_write_types_keep_read_only_rejection_and_approval_guidance(sql):
    decision = classify_sql_statement(sql)
    assert not decision.allowed and decision.error_code == "read_only_required"
    assert "mutation Skills" in (decision.hint or "")
    assert "explicit approval" in (decision.hint or "")


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("all_scope", [False, True])
async def test_raw_and_cached_skill_ambiguity_stays_closed_with_quote_recovery(bundle, tmp_path, monkeypatch, mode, all_scope):
    _, connections, skills, save = bundle
    with sqlite3.connect(tmp_path/"db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n);INSERT INTO orders VALUES(7);")
    for i, name in enumerate(NAMES):
        for quote in ('{}', '"{}"'):
            label = f"cte-{i}-"+("bare" if quote == "{}" else "quoted")
            directory = tmp_path/"skills"/label
            directory.mkdir(parents=True)
            (directory/"skill_def.md").write_text(f"---\nname: {label}\ntype: query\nsource: query.sql\nrisk: low\ndescription: CTE classification\nparams: {{}}\n---\n")
            (directory/"query.sql").write_text(query(name, quote))
    connections["connections"]["demo"]["read"] = {"mode": "all"} if all_scope else {"mode": "allowlist", "tables": ["orders"]}
    skills["skills"] = {"enabled": True, "directory": str(tmp_path/"skills"),
                        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path/"audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            listed = await client.call_tool("list_skills", {"detail_level": "full"})
            assert {s["name"] for s in listed.structured_content["skills"]} == {f"cte-{i}-{style}" for i in range(len(NAMES)) for style in ("bare", "quoted")}
            for i, name in enumerate(NAMES):
                quoted = query(name, '"{}"')
                raw = await client.call_tool("query", {"sql": quoted})
                detail = await client.call_tool("get_skill_detail", {"skill_name": f"cte-{i}-quoted", "detail_level": "full"})
                execution = await client.call_tool("execute_query_skill", {"skill_name": f"cte-{i}-quoted", "params": {}})
                assert raw.structured_content["data"] == execution.structured_content["data"] == [{"n": 7}]
                assert detail.structured_content["skill"]["executable"]
                meta = server.gateway_runtime.catalog.get_skills_cache()[f"cte-{i}-quoted"]
                original = meta._sql_template
                # A valid bare name must execute, while malformed cached SQL
                # still fails before capability/schema/business database I/O.
                bare = await client.call_tool("execute_query_skill", {"skill_name": f"cte-{i}-bare", "params": {}})
                assert bare.structured_content["data"] == [{"n": 7}]
                malformed = f"WITH {name} AS"
                meta._sql_template = malformed
                try:
                    with monkeypatch.context() as denied_io:
                        def unexpected_io(*args, **kwargs):
                            pytest.fail("Unclassified WITH reached database I/O")
                        adapter = server.gateway_runtime.registry.get_adapter("demo")
                        for method in ("execute", "connect", "get_read_relations"):
                            denied_io.setattr(adapter, method, unexpected_io)
                        for tool, args in [("query", {"sql": malformed}), ("execute_query_skill", {"skill_name": f"cte-{i}-quoted", "params": {}})]:
                            result = await client.call_tool(tool, args, raise_on_error=False)
                            assert not result.is_error
                            data = result.structured_content
                            assert not data["success"] and data["error_code"] == "sql_parse_failed"
                            assert "mutation" not in data.get("hint", "").lower()
                finally:
                    meta._sql_template = original
    finally:
        server.gateway_runtime.close()
    with sqlite3.connect(tmp_path/"db.sqlite") as db:
        assert db.execute("SELECT n FROM orders").fetchall() == [(7,)]
