"""Target-specific CTE inference must match raw queries without erasing declarations."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from sql_safety_executor.database.relations import ReadRelation, RelationReference
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import _extract_tables_from_sql
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.mysql import MySQLAdapter, _CTE_CASE_PROBE
from sql_safety_executor.skills.catalog import SkillCatalog
from sql_safety_executor.skills.access import _query_skill_policy_decision, _required_skill_tables
from sql_safety_executor.core.types import ConnectionContext
from sql_safety_executor.database.sqlite import SQLiteAdapter
from sql_safety_executor.database.semantics import DialectContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
@pytest.mark.parametrize("declared", [False, True])
async def test_sqlite_mixed_cte_raw_discovery_and_execution(bundle, tmp_path, mode, read_mode, declared):
    main, connections, skills, save = bundle
    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE orders(id INTEGER); INSERT INTO orders VALUES(1); "
                           "CREATE TABLE f(id INTEGER); INSERT INTO f VALUES(999);")
    directory = tmp_path / "skills" / "mixed-case"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        "---\nname: mixed-case\ntype: query\nsource: query.sql\nrisk: low\n"
        "description: CTE dependency regression\nparams: {}\n"
        + ("tables: [orders]\n" if declared else "") + "---\n")
    sql = "WITH F AS (SELECT id FROM orders) SELECT id FROM f"
    (directory / "query.sql").write_text(sql)
    connections["connections"]["demo"]["read"] = {"mode": read_mode, "tables": ["orders"] if read_mode == "allowlist" else []}
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
                        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        meta = server.gateway_runtime.catalog.get_skills_cache()["mixed-case"]
        assert meta.tables == (["orders"] if declared else [])
        assert meta._inferred_analysis == {}  # Pure analysis starts with the target context.
        # Inference and execution must use the cached source, never re-read it.
        (directory / "query.sql").write_text("SELECT id FROM f")
        async with Client(server, mode=mode) as client:
            raw = (await client.call_tool("query", {"sql": sql})).structured_content
            listed = (await client.call_tool("list_skills", {"detail_level": "full"})).structured_content
            row = listed["skills"][0]
            assert row["executable"] and row["policy_allowed"] and row["schema_ready"]
            assert row["tables"] == ["orders"] and row["inferred_tables"] == ["orders"]
            assert row["declared_tables"] == (["orders"] if declared else [])
            detail = (await client.call_tool("get_skill_detail", {"skill_name": "mixed-case", "detail_level": "full"})).structured_content
            assert detail["skill"]["tables"] == ["orders"]
            searched = (await client.call_tool("list_skills", {"search": "orders"})).structured_content
            assert [row["name"] for row in searched["skills"]] == ["mixed-case"]
            executed = (await client.call_tool("execute_query_skill", {"skill_name": "mixed-case", "params": {}})).structured_content
            assert raw["success"] and executed["success"]
            assert raw["data"] == executed["data"] == [{"id": 1}]
    finally:
        server.gateway_runtime.close()


def test_cte_folding_preserves_physical_spelling_and_qualification():
    sql = "WITH F AS (SELECT id FROM Orders) SELECT id FROM f JOIN private.f ON 1=1"
    assert _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=False) == ["Orders", "private.f"]
    assert _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=True) == ["Orders", "f", "private.f"]


def test_cte_folding_does_not_invent_unicode_alias_equivalence():
    sql = 'WITH "K" AS (SELECT 1 AS id) SELECT id FROM "K"'
    with sqlite3.connect(":memory:") as conn:
        conn.execute('CREATE TABLE "K"(id INTEGER)')
        conn.execute('INSERT INTO "K" VALUES(999)')
        assert conn.execute(sql).fetchall() == [(999,)]
    assert _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=False) == ["K"]


@pytest.mark.parametrize("sql,expected,refs,grant", [
    ('WITH F AS (SELECT 7 AS id) SELECT id FROM " f "', 999, [" f "], "allowed"),
    ('WITH " F " AS (SELECT 7 AS id) SELECT id FROM f', 1, ["f"], "allowed"),
    ('WITH " F " AS (SELECT 7 AS id) SELECT id FROM " f "', 7, [], "allowed"),
    ('SELECT id FROM " f "', 999, [" f "], " f "),
])
def test_quoted_whitespace_is_real_identity(sql, expected, refs, grant):
    with sqlite3.connect(":memory:") as conn:
        conn.executescript('CREATE TABLE f(id INTEGER); INSERT INTO f VALUES(1); '
                           'CREATE TABLE " f "(id INTEGER); INSERT INTO " f " VALUES(999);')
        assert conn.execute(sql).fetchall() == [(expected,)]
    assert _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=False) == refs
    policy = ConnectionPolicy(allowed_tables=frozenset({grant}))
    assert _validate_sql_query_policy(None, sql, policy).allowed is (not refs or refs == [grant])


def test_declared_physical_names_keep_spaces_through_catalog_and_policy(tmp_path):
    directory = tmp_path / "skills" / "space-probe"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        '---\nname: space-probe\ntype: query\nsource: query.sql\nrisk: low\n'
        'description: Physical identifier identity\ntables: [" f "]\nprofiles: [" DEMO "]\n---\n')
    (directory / "query.sql").write_text('SELECT id FROM " f "')
    meta = SkillCatalog().discover(directory.parent)["space-probe"]
    policy = ConnectionPolicy(allowed_tables=frozenset({" f "}))
    config = DatabaseConfig(connection_id="demo", db_type="sqlite", policy=policy,
                            query_timeout_seconds=10, connect_timeout_seconds=5,
                            sqlite_database_path=str(tmp_path / "unused.sqlite"))
    connection = ConnectionContext("demo", config, SQLiteAdapter(config=config), policy)
    assert meta.tables == [" f "] and meta.profiles == ["demo"]
    assert _query_skill_policy_decision(meta, connection).allowed
    assert _required_skill_tables(meta, connection) == [" f "]


def probe_adapter(monkeypatch, *outcomes):
    calls = []
    queue = list(outcomes)
    def execute(sql):
        assert sql == _CTE_CASE_PROBE
        calls.append(sql)
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(scalar_one=lambda: value)
    @contextmanager
    def connect():
        yield SimpleNamespace(exec_driver_sql=execute)
    adapter = MySQLAdapter(DatabaseConfig(
        connection_id="mysql_case", db_type="mysql", query_timeout_seconds=10,
        connect_timeout_seconds=5, policy=ConnectionPolicy(case_sensitive_tables=True),
        mysql_database="fixture", mysql_sql_mode=(),
    ))
    adapter._engine = cast(Engine, SimpleNamespace(connect=connect, dispose=lambda: None))
    monkeypatch.setattr(adapter, "connect", lambda: True)
    return adapter, calls


def driver_error(errno):
    import pymysql
    return OperationalError("probe", {}, pymysql.err.OperationalError(errno, "private_driver_details"))


@pytest.mark.parametrize("outcome,sensitive", [(1, True), (1066, False), (4004, False)])
def test_mysql_capability_measures_constant_cte_names_and_caches(monkeypatch, outcome, sensitive):
    adapter, calls = probe_adapter(monkeypatch, 1 if outcome == 1 else driver_error(outcome))
    assert adapter.cte_case_sensitive is None
    for _ in range(3):
        assert adapter.resolve_cte_case_sensitive() is sensitive
    assert adapter.cte_case_sensitive is sensitive and len(calls) == 1
    adapter.close()
    assert adapter.cte_case_sensitive is None and adapter._cte_probe_retry_after == 0


def test_mysql_probe_unknown_error_is_conservative_and_retries(monkeypatch, caplog):
    import sql_safety_executor.database.mysql as mysql
    clock = [100.0]
    monkeypatch.setattr(mysql.time, "monotonic", lambda: clock[0])
    adapter, calls = probe_adapter(monkeypatch, driver_error(1064), driver_error(1066))
    assert adapter.resolve_cte_case_sensitive() is True
    assert adapter.cte_case_sensitive is None
    assert adapter.resolve_cte_case_sensitive() is True and len(calls) == 1
    clock[0] += 31
    assert adapter.resolve_cte_case_sensitive() is False and len(calls) == 2
    assert "private_driver_details" not in caplog.text


def test_mysql_probe_concurrent_requests_share_one_measurement(monkeypatch):
    adapter, calls = probe_adapter(monkeypatch, driver_error(1066))
    with ThreadPoolExecutor(max_workers=6) as executor:
        assert list(executor.map(lambda _: adapter.resolve_cte_case_sensitive(), range(12))) == [False] * 12
    assert len(calls) == 1


@pytest.mark.parametrize("outcome,allowed", [(1, False), (1066, True), (4004, True)])
def test_mysql_query_policy_respects_measured_cte_case(monkeypatch, outcome, allowed):
    adapter, calls = probe_adapter(monkeypatch, 1 if outcome == 1 else driver_error(outcome))
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), case_sensitive_tables=True)
    sql = "WITH F AS (SELECT id FROM orders) SELECT id FROM f"
    verdict = _validate_sql_query_policy(None, sql, policy, adapter=adapter)
    assert verdict.allowed is allowed
    assert len(calls) == 1
    if not allowed:
        assert verdict.error_code == "table_access_denied" and "f" in verdict.message


@pytest.mark.parametrize("sql", [
    "SELECT id FROM orders",
    "WITH F AS (SELECT id FROM orders) SELECT id FROM F",
    "WITH F AS (SELECT id FROM blocked) SELECT id FROM f",
    "WITH orders AS (SELECT id FROM orders) SELECT id FROM orders",
    "WITH earlier AS (SELECT id FROM later), later AS (SELECT 1 AS id) SELECT id FROM earlier",
    "WITH F AS (SELECT 1 AS id) SELECT id FROM f; SELECT 2",
    "WITH F AS (SELECT 1 AS id UNION ALL SELECT 2) SELECT id FROM f",
    "WITH F AS (SELECT id FROM information_schema.tables) SELECT id FROM f",
])
def test_unambiguous_or_definitely_denied_queries_do_not_probe(monkeypatch, sql):
    adapter, calls = probe_adapter(monkeypatch)  # Any actual probe would fail.
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), case_sensitive_tables=True)
    _validate_sql_query_policy(None, sql, policy, adapter=adapter)
    assert calls == [] and adapter.cte_case_sensitive is None


@pytest.mark.parametrize("cte_sensitive", [False, True])
@pytest.mark.parametrize("sql,physical", [
    ("WITH Orders AS (SELECT id FROM orders) SELECT id FROM Orders", "orders"),
    ("WITH earlier AS (SELECT id FROM Later), later AS (SELECT 1 AS id) SELECT id FROM earlier", "Later"),
    ("WITH F AS (SELECT 1 AS id) SELECT id FROM private.f", "private.f"),
])
def test_measured_cte_rules_never_exempt_self_forward_or_qualified_tables(cte_sensitive, sql, physical):
    assert physical in _extract_tables_from_sql(sql, case_sensitive=True, context=DialectContext("mysql", cte_case_sensitive=cte_sensitive))


def test_sqlite_unicode_physical_table_is_not_an_ascii_grant(bundle):
    main, connections, skills, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["K"]}
    config = load_config(save())
    policy = config.connections["demo"].policy
    assert policy.allows_table("k") and policy.allows_table("K")
    assert not policy.allows_table("K")
    sql = 'WITH "K" AS (SELECT 1 AS id) SELECT id FROM "K"'
    assert _validate_sql_query_policy(None, sql, policy).error_code == "table_access_denied"


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_one_skill_resolves_independently_across_mysql_connections(bundle, tmp_path, monkeypatch, mode):
    main, connections, skills, save = bundle
    main["server"]["default_connection"] = "ci"
    connections["connections"] = {
        alias: {"type": "mysql", "mysql": {"host": "fixture", "user": "fixture", "database": "fixture", "password": {"value": "fixture"}, "sql_mode": []},
                "read": {"mode": "allowlist", "tables": ["orders"]}}
        for alias in ("ci", "exact")
    }
    directory = tmp_path / "skills" / "case-probe"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        "---\nname: case-probe\ntype: query\nsource: query.sql\nrisk: low\n"
        "description: Target resolution\nparams: {}\n---\n")
    sql = "WITH F AS (SELECT id FROM orders) SELECT id FROM f"
    (directory / "query.sql").write_text(sql)
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
                        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        for alias in ("ci", "exact"):
            adapter = server.gateway_runtime.registry.get_adapter(alias)
            assert isinstance(adapter, MySQLAdapter)
            adapter._cte_case_sensitive = alias == "exact"
            monkeypatch.setattr(adapter, "get_read_relations", lambda: [ReadRelation(RelationReference(name, "fixture"), "table") for name in ("orders", "f")])
            if alias == "ci":
                monkeypatch.setattr(adapter, "execute", lambda *args, **kwargs: [{"id": 1}])
            else:
                def unauthorized_execution(*args, **kwargs):
                    pytest.fail("Exact-case physical f was executed without a grant")
                monkeypatch.setattr(adapter, "execute", unauthorized_execution)
        async with Client(server, mode=mode) as client:
            for alias in ("ci", "exact", "ci"):
                full = (await client.call_tool("list_skills", {"connection_id": alias, "available_only": False, "detail_level": "full"})).structured_content
                row = full["skills"][0]
                assert row["tables"] == (["orders"] if alias == "ci" else ["f", "orders"])
                assert row["policy_allowed"] is (alias == "ci")
                result = (await client.call_tool("execute_query_skill", {"skill_name": "case-probe", "params": {}, "connection_id": alias})).structured_content
                assert result["success"] is (alias == "ci")
                if alias == "ci":
                    assert result["data"] == [{"id": 1}]
                else:
                    assert result["error_code"] == "table_access_denied"
        assert server.gateway_runtime.catalog.get_skills_cache()["case-probe"].tables == []
    finally:
        server.gateway_runtime.close()
