"""Positive capabilities and scope contracts from the 2c0a9e7 review."""
from types import SimpleNamespace
import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.mysql import MySQLAdapter
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from tests.test_v38_config import bundle as bundle


@pytest.fixture
def review_server(bundle, tmp_path):
    main, connections, skills, save = bundle
    main["tools"] = {"table_summary": True}
    servers = []

    def build(sql, *, ddl="", read=None):
        with sqlite3.connect(tmp_path / "db.sqlite") as db:
            db.executescript("CREATE TABLE orders(n INTEGER); INSERT INTO orders VALUES(7);" + ddl)
        directory = tmp_path / "skills" / "review-probe"
        directory.mkdir(parents=True)
        (directory / "skill_def.md").write_text(
            "---\nname: review-probe\ntype: query\nsource: query.sql\nrisk: low\n"
            "description: Independent review probe\nparams: {}\n---\n")
        (directory / "query.sql").write_text(sql)
        connections["connections"]["demo"]["read"] = read or {
            "mode": "allowlist", "tables": ["orders"], "allow_union": True}
        skills["skills"] = {"enabled": True, "directory": str(directory.parent),
            "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
        server = create_server(load_config(save(use_skills=True)))
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("body", [
    "SELECT n FROM (SELECT n FROM orders) AS chosen",
    "SELECT n FROM (WITH chosen AS (SELECT n FROM orders) SELECT n FROM chosen)",
    "SELECT n FROM orders JOIN (SELECT 1 AS marker) AS chosen ON marker=1",
])
async def test_derived_view_and_skill_are_readable_but_raw_subset_stays_explicit(review_server, mode, body):
    server = review_server("SELECT n FROM main.approved",
        ddl=f"CREATE VIEW approved AS {body}; CREATE VIEW nested AS SELECT n FROM approved;",
        read={"mode": "allowlist", "tables": ["approved", "nested"], "allow_union": True})
    async with Client(server, mode=mode) as client:
        for source in ("approved", "nested"):
            result = await client.call_tool("query", {"sql": f"SELECT n FROM {source}"})
            assert result.structured_content["data"] == [{"n": 7}]
        listed = await client.call_tool("list_skills", {"detail_level": "full"})
        assert listed.structured_content["skills"][0]["executable"]
        executed = await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})
        assert executed.structured_content["data"] == [{"n": 7}]
        denied = await client.call_tool("query", {"sql": body})
        assert denied.structured_content["error_code"] == "relation_group_unsupported"
        denied = await client.call_tool("query", {"sql": "SELECT n FROM orders"})
        assert denied.structured_content["error_code"] == "table_access_denied"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("grant", ["orders", "main.orders"])
async def test_default_schema_identity_shared_by_raw_skill_and_metadata(review_server, mode, grant):
    server = review_server("SELECT n FROM main.orders", read={"mode": "allowlist", "tables": [grant]})
    async with Client(server, mode=mode) as client:
        for sql in ("SELECT n FROM orders", "SELECT n FROM main.orders"):
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["data"] == [{"n": 7}]
        listing = await client.call_tool("list_skills", {"detail_level": "full"})
        detail = await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})
        for state in (listing.structured_content["skills"][0], detail.structured_content["skill"]):
            assert state["executable"] and state["schema_ready"]
        executed = await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})
        assert executed.structured_content["data"] == [{"n": 7}]
        listed = await client.call_tool("list_tables", {})
        assert [row["table_name"] for row in listed.structured_content["tables"]] == ["orders"]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_all_is_bound_to_default_schema_even_with_temp_shadow(review_server, mode):
    server = review_server("SELECT n FROM main.orders", read={"mode": "all"})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE TEMP TABLE orders(n)")
        db.exec_driver_sql("INSERT INTO temp.orders VALUES(99)")
        db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql("CREATE TABLE aux.orders(n)")
        db.exec_driver_sql("INSERT INTO aux.orders VALUES(123)")
    async with Client(server, mode=mode) as client:
        allowed = await client.call_tool("query", {"sql": "SELECT n FROM main.orders"})
        assert allowed.structured_content["data"] == [{"n": 7}]
        for sql in ("SELECT n FROM temp.orders", "SELECT n FROM aux.orders", "SELECT n FROM orders"):
            denied = await client.call_tool("query", {"sql": sql})
            assert denied.structured_content["error_code"] == "table_access_denied"


@pytest.mark.parametrize("suffix", ["FOR UPDATE", "FOR UPDATE NOWAIT", "FOR UPDATE SKIP LOCKED", "FOR SHARE", "LOCK IN SHARE MODE"])
def test_executing_locking_reads_denied_but_nonexecuting_plans_retained(suffix):
    context = DialectContext("mysql", default_schema="business")
    adapter = SimpleNamespace(analysis_context=context, resolve_analysis_context=lambda: context, cte_case_sensitive=False)
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), case_sensitive_tables=True)
    sql = "SELECT n FROM orders " + suffix
    assert _validate_sql_query_policy(None, sql, policy, adapter=adapter).error_code == "locking_read_denied"
    assert _validate_sql_query_policy(None, "EXPLAIN " + sql, policy, adapter=adapter).allowed
    assert _validate_sql_query_policy(None, "EXPLAIN ANALYZE " + sql, policy, adapter=adapter).error_code == "executing_explain_denied"


@pytest.mark.parametrize("sql", ["SELECT n INTO @x FROM orders", "SELECT n FROM orders INTO @x", "SELECT @x := 1"])
def test_session_assignment_is_not_mislabeled_as_file_output(sql):
    context = DialectContext("mysql", default_schema="business")
    adapter = SimpleNamespace(analysis_context=context, resolve_analysis_context=lambda: context, cte_case_sensitive=False)
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})), adapter=adapter)
    assert decision.error_code == "session_assignment_denied"


@pytest.mark.parametrize("command", ["DO 1", "HANDLER orders OPEN"])
def test_recognized_nonreading_commands_have_no_parse_failure_hint(command):
    policy = ConnectionPolicy(allowed_tables=frozenset({"*"}), read_mode="all", case_sensitive_tables=True)
    assert _validate_sql_query_policy(None, command, policy).error_code == "read_only_required"


def test_mysql_database_display_uses_bound_schema_without_trusted_query(monkeypatch):
    adapter = MySQLAdapter.__new__(MySQLAdapter)
    adapter._db_name = "business"
    monkeypatch.setattr(adapter, "execute", lambda *a, **kw: pytest.fail("display name caused trusted execution"))
    assert adapter.get_database_name() == "business"


@pytest.mark.parametrize("name", ["with", "window", "offset", "unıon", "offſet", "wındow", "pragma_locKing_mode"])
def test_relation_role_fix_retains_keyword_and_unicode_business_names(name):
    analysis = analyze_sql(f"SELECT n FROM {name}", DialectContext("sqlite"))
    assert analysis.complete
    assert analysis.relations == (RelationReference(name),)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("source", ["json_each", "main.json_each", "MAIN.JSON_EACH", "json_tree"])
async def test_json_builtin_has_no_physical_grant_but_checks_argument_dependencies(review_server, mode, source):
    sql = f"SELECT SUM(value) AS n FROM {source}((SELECT '[7,8]' FROM orders)) WHERE type='integer'"
    server = review_server(sql, ddl="CREATE TABLE hidden(n); INSERT INTO hidden VALUES(99);")
    async with Client(server, mode=mode) as client:
        for name in ("query", "execute_query_skill"):
            result = await client.call_tool(name, {"sql": sql} if name == "query" else {"skill_name": "review-probe", "params": {}})
            assert result.structured_content["data"] == [{"n": 15}]
        listed = await client.call_tool("list_skills", {"detail_level": "full"})
        assert listed.structured_content["skills"][0]["executable"]
        denied = await client.call_tool("query", {"sql": sql.replace("FROM orders", "FROM hidden")})
        assert denied.structured_content["error_code"] == "table_access_denied"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", ["json_each", "json_tree"])
async def test_json_view_and_count_remain_guarded(review_server, mode, name):
    server = review_server("SELECT COUNT(*) AS n FROM approved",
        ddl=f"CREATE VIEW approved AS SELECT value FROM {name}('[7,8]') WHERE type='integer';",
        read={"mode": "allowlist", "tables": ["approved"]})
    async with Client(server, mode=mode) as client:
        for sql in ("SELECT COUNT(*) AS n FROM approved", f"SELECT COUNT(*) AS n FROM {name}('[7,8]') WHERE type='integer'"):
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["data"] == [{"n": 2}]
        result = await client.call_tool("describe_table", {"table_name": "approved"})
        assert result.structured_content["row_count"] == 2


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", ["sqlite_schema", "sqlite_master"])
@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
async def test_catalog_count_and_projection_share_authorized_identity(review_server, mode, name, read_mode):
    read = {"mode": read_mode}
    if read_mode == "allowlist":
        read["tables"] = [name]
    server = review_server(f"SELECT COUNT(*) AS n FROM {name}", read=read)
    async with Client(server, mode=mode) as client:
        for expression in ("COUNT(*)", "COUNT(name)"):
            result = await client.call_tool("query", {"sql": f"SELECT {expression} AS n FROM {name}"})
            assert result.structured_content["data"] == [{"n": 1}]
        result = await client.call_tool("query", {"sql": f"SELECT name FROM main.{name}"})
        assert result.structured_content["data"] == [{"name": "orders"}]


def test_mysql_json_table_keeps_its_real_argument_dependency():
    context = DialectContext("mysql", default_schema="business")
    adapter = SimpleNamespace(analysis_context=context, resolve_analysis_context=lambda: context, cte_case_sensitive=False)
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), case_sensitive_tables=True)
    sql = "SELECT jt.n FROM orders, JSON_TABLE('[1,2]', '$[*]' COLUMNS(n INT PATH '$')) AS jt"
    assert _validate_sql_query_policy(None, sql, policy, adapter=adapter).allowed
    assert _validate_sql_query_policy(None, sql.replace("FROM orders,", "FROM hidden,"), policy, adapter=adapter).error_code == "table_access_denied"


@pytest.mark.parametrize("sql", ["SELECT ?", "SELECT ?1", "WITH chosen AS (SELECT ?15 AS n) SELECT n FROM chosen"])
def test_positional_parameters_get_an_actionable_binding_error(sql):
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"})))
    assert decision.error_code == "parameter_binding_unsupported"
    assert "named parameters" in decision.hint


@pytest.mark.parametrize("sql", ["SELECT '?' AS n", "SELECT :value AS n", "SELECT 'INTO @x FOR UPDATE' AS n"])
def test_diagnostic_tokens_do_not_change_literals_or_named_bindings(sql):
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))).allowed


@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
def test_mysql_bound_scope_refuses_other_schemas_without_connecting(read_mode):
    context = DialectContext("mysql", default_schema="business")
    def unexpected():
        pytest.fail("A definite scope refusal opened a session")
    adapter = SimpleNamespace(analysis_context=context, resolve_analysis_context=unexpected, cte_case_sensitive=None)
    policy = ConnectionPolicy(allowed_tables=frozenset({"*"} if read_mode == "all" else {"orders"}),
        read_mode=read_mode, case_sensitive_tables=True, default_schema="business")
    assert _validate_sql_query_policy(None, "SELECT n FROM other.orders", policy, adapter=adapter).error_code == "table_access_denied"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("sql,expected", [
    ("WITH chosen AS (SELECT value FROM json_each('[7,8]')) SELECT COUNT(*) AS n FROM chosen", 2),
    ("SELECT SUM(value) AS n FROM orders,json_each(json_array(orders.n,8))", 15),
    ("SELECT COUNT(*) AS n FROM orders WHERE 7 IN (SELECT value FROM json_each('[7,8]'))", 1),
])
async def test_json_cte_correlated_and_membership_roles(review_server, mode, sql, expected):
    server = review_server(sql)
    async with Client(server, mode=mode) as client:
        result = await client.call_tool("query", {"sql": sql})
        assert result.structured_content["data"] == [{"n": expected}]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("catalog", ["sqlite_schema", "sqlite_master"])
async def test_catalog_aliases_in_view_preserve_view_only_permission(review_server, mode, catalog):
    server = review_server("SELECT COUNT(*) AS n FROM approved",
        ddl=f"CREATE VIEW approved AS SELECT name FROM main.{catalog} WHERE type='table';",
        read={"mode": "allowlist", "tables": ["approved"]})
    async with Client(server, mode=mode) as client:
        result = await client.call_tool("query", {"sql": "SELECT COUNT(*) AS n FROM approved"})
        assert result.structured_content["data"] == [{"n": 1}]
        result = await client.call_tool("query", {"sql": "SELECT name FROM approved"})
        assert result.structured_content["data"] == [{"name": "orders"}]
        result = await client.call_tool("query", {"sql": f"SELECT name FROM {catalog}"})
        assert result.structured_content["error_code"] == "table_access_denied"
