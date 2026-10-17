"""Read-call restrictions must precede I/O and preserve SQL identifiers/data."""
from types import SimpleNamespace
import sqlite3

import pytest
from fastmcp import Client
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_query_skill_static_policy import policy_server, bundle


@pytest.mark.parametrize("sql,code", [
    ("SELECT GET_LOCK('x',0)", "lock_function_denied"),
    ("SELECT RELEASE_LOCK('x')", "lock_function_denied"),
    ("SELECT RELEASE_ALL_LOCKS()", "lock_function_denied"),
    ("SELECT SLEEP(0)", "expensive_function_denied"),
    ("SELECT BENCHMARK(0,1)", "expensive_function_denied"),
    ('SELECT "sleep"(0)', "expensive_function_denied"),
    ("SELECT [SLEEP](0)", "expensive_function_denied"),
    ("SELECT `SLEEP`(0)", "expensive_function_denied"),
    ("SELECT business.SLEEP(0)", "expensive_function_denied"),
    ("SELECT SLEEP/**/(0)", "expensive_function_denied"),
    ("SELECT ABS(SLEEP(0))", "expensive_function_denied"),
    ("WITH SLEEP(n) AS (SELECT SLEEP(0)) SELECT n FROM SLEEP", "expensive_function_denied"),
    ("WITH f AS (SELECT GET_LOCK('x',0)) SELECT * FROM f", "lock_function_denied"),
    ("EXPLAIN SELECT BENCHMARK(0,1)", "expensive_function_denied"),
])
@pytest.mark.parametrize("mysql", [False, True])
def test_reserved_calls_before_capability_or_table_io(sql, code, mysql):
    def io():
        pytest.fail("A rejected function reached database capability probing")
    adapter = SimpleNamespace(analysis_context=DialectContext("sqlite"), cte_case_sensitive=None, resolve_cte_case_sensitive=io)
    decision = _validate_sql_query_policy(None, sql,
        ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}), case_sensitive_tables=mysql),
        adapter=adapter)
    assert decision.error_code == code and not decision.allowed
    assert decision.hint and "same connection" in decision.hint


@pytest.mark.parametrize("sql", [
    "SELECT 'SLEEP(10), GET_LOCK(1), BENCHMARK(2,3)' AS label",
    "SELECT 7 AS SLEEP, ABS(-7) AS BENCHMARK",
    'SELECT "SLEEP", "BENCHMARK" FROM orders',
    "SELECT SLEEP, GET_LOCK FROM orders",
    "SELECT 1 /* SLEEP(100) */",
    "WITH SLEEP(n) AS (SELECT 7) SELECT n FROM SLEEP",
    'WITH "SLEEP"(n) AS (SELECT 7) SELECT n FROM "SLEEP"',
    "WITH first_cte(n) AS (SELECT 7), BENCHMARK(n) AS (SELECT n FROM first_cte) SELECT n FROM BENCHMARK",
    "WITH RECURSIVE SLEEP(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM SLEEP WHERE n<3) SELECT n FROM SLEEP",
])
def test_real_sqlite_queries_preserve_names_and_literals(sql):
    with sqlite3.connect(":memory:") as db:
        db.executescript("CREATE TABLE orders(SLEEP INTEGER,GET_LOCK INTEGER,BENCHMARK INTEGER);INSERT INTO orders VALUES(1,2,3);")
        assert db.execute(sql).fetchall()
    policy = ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}), allow_union=True)
    assert _validate_sql_query_policy(None, sql, policy).allowed


@pytest.mark.parametrize("sql", ['SELECT "SLEEP"(0)', "SELECT [SLEEP](0)", "SELECT `SLEEP`(0)"])
def test_quoted_names_are_real_calls_not_columns(sql):
    with sqlite3.connect(":memory:") as db:
        db.create_function("SLEEP", 1, lambda n: 7)
        assert db.execute(sql).fetchone() == (7,)
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}))).error_code == "expensive_function_denied"


def test_ascii_reserved_names_do_not_normalize_unicode_function_identity():
    sql = "SELECT ſleep(0)"
    with sqlite3.connect(":memory:") as db:
        db.create_function("ſleep", 1, lambda n: 7)
        assert db.execute(sql).fetchone() == (7,)
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}))).allowed


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("sql,code", [
    ("SELECT SLEEP(0) AS value", "expensive_function_denied"),
    ("SELECT GET_LOCK('x',0) AS value", "lock_function_denied"),
])
async def test_discovery_and_both_query_routes_refuse_without_io(policy_server, monkeypatch, mode, sql, code):
    # Startup quarantines these templates. Replay an already cached template
    # to verify that runtime policy independently refuses before any I/O.
    server = policy_server("SELECT 7 AS value", {"mode":"all"}, {"mode":"all"})
    server.gateway_runtime.catalog.get_skills_cache()["static-policy-probe"]._sql_template = sql
    def io(*args, **kwargs):
        pytest.fail("Denied read performed adapter I/O")
    for alias in ("denied", "allowed"):
        adapter = server.gateway_runtime.registry.get_adapter(alias)
        monkeypatch.setattr(adapter, "get_read_relations", io)
        monkeypatch.setattr(adapter, "execute", io)
        monkeypatch.setattr(adapter, "connect", io)
    async with Client(server, mode=mode) as client:
        full = await client.call_tool("list_skills", {"connection_id":"allowed","available_only":False,"detail_level":"full"})
        skill = full.structured_content["skills"][0]
        assert skill["policy_allowed"] is False and skill["executable"] is False
        for tool, parameters in [
            ("query", {"sql":sql}),
            ("execute_query_skill", {"skill_name":"static-policy-probe","params":{}}),
        ]:
            result = await client.call_tool(tool, {**parameters,"connection_id":"allowed"}, raise_on_error=False)
            assert not result.is_error
            assert result.structured_content["success"] is False
            assert result.structured_content["error_code"] == code


@pytest.mark.parametrize("sql", ["SELECT SLEEP(0)", "SELECT GET_LOCK('x',0)"])
def test_unsafe_query_skill_is_quarantined_offline_at_startup(policy_server, sql):
    server = policy_server(sql, {"mode":"all"}, {"mode":"all"})
    assert server.gateway_runtime.catalog.get_skills_cache() == {}
    for alias in ("denied","allowed"):
        assert server.gateway_runtime.registry.get_adapter(alias)._engine is None
