"""Native and gateway boundaries for the October 13 review follow-up."""

import json
from dataclasses import replace
import sqlite3

import pytest
from fastmcp import Client
from sqlalchemy.exc import OperationalError

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.decisions import PolicyDecision
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.errors import DatabaseQueryError, classify_database_error
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.sqlite import SQLiteAdapter
from tests.support import write_toml
from sql_safety_executor.skills.catalog import _extract_table_names


@pytest.fixture
def fixture_database(tmp_path):
    path = tmp_path / "fixture.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE allowed(id INTEGER);
            INSERT INTO allowed VALUES(1);
            CREATE TABLE blocked(id INTEGER);
            INSERT INTO blocked VALUES(1);
        """)
    return path


def policy(*tables):
    return ConnectionPolicy(read_mode="allowlist", allowed_tables=frozenset(tables))


@pytest.mark.parametrize("rhs", ["blocked", "main.blocked", '"blocked"', "`blocked`", "[blocked]"])
@pytest.mark.parametrize("operator", ["IN", "NOT IN"])
def test_membership_relation_is_authorized(fixture_database, rhs, operator):
    sql = f"SELECT id FROM allowed WHERE 1 {operator} {rhs}"
    with sqlite3.connect(fixture_database) as db:
        db.execute(sql).fetchall()  # Genuine SQLite syntax.
    decision = _validate_sql_query_policy(None, sql, policy("allowed"))
    assert decision.error_code == "table_access_denied"


@pytest.mark.parametrize("sql", [
    "SELECT id FROM allowed WHERE 1 IN allowed",
    "SELECT id FROM allowed WHERE (1) NOT IN allowed",
    "SELECT id FROM allowed WHERE 1 IN (SELECT id FROM allowed)",
    "SELECT id FROM allowed WHERE id IN (1,2,3)",
    "WITH c AS (SELECT id FROM allowed) SELECT 1 IN c",
    "SELECT 1 IN main.allowed",
])
def test_authorized_membership_keeps_sqlite_semantics(fixture_database, sql):
    with sqlite3.connect(fixture_database) as db:
        db.execute(sql).fetchall()
    assert _validate_sql_query_policy(None, sql, policy("allowed", "main.allowed")).allowed


@pytest.mark.parametrize("sql", [
    "SELECT id FROM allowed WHERE EXISTS (SELECT 1 WHERE 1 IN blocked)",
    "SELECT id FROM allowed WHERE (1,1) IN (SELECT id,id FROM blocked)",
])
def test_membership_preserves_cte_scope_and_nested_authorization(sql):
    assert _validate_sql_query_policy(None, sql, policy("allowed")).error_code == "table_access_denied"


def test_sqlite_forward_membership_binds_cte_not_same_named_physical_table(fixture_database):
    sql = "WITH a AS (SELECT 7 IN blocked AS id), blocked AS (SELECT 7 AS id) SELECT * FROM a"
    with sqlite3.connect(fixture_database) as db:
        assert db.execute(sql).fetchall() == [(1,)]
    assert _validate_sql_query_policy(None, sql, policy("allowed")).allowed


@pytest.mark.parametrize("sql", [
    "SELECT 1 IN pragma_table_info('blocked')",
    "SELECT 1 NOT IN main.pragma_table_info('blocked')",
    'SELECT 1 IN "pragma_table_info"(\'blocked\')',
    "SELECT 1 IN 'pragma_table_info'('blocked')",
    "SELECT 1 WHERE (0,'id','INTEGER',0,NULL,0) IN pragma_table_info('blocked')",
    "WITH c AS (SELECT 1 IN pragma_table_list AS x) SELECT * FROM c",
])
@pytest.mark.parametrize("read_policy", [policy("allowed"), ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))])
def test_membership_pragma_denied_independently_of_allowlist(sql, read_policy):
    decision = _validate_sql_query_policy(None, sql, read_policy)
    assert not decision.allowed and "PRAGMA" in decision.message


def test_membership_virtual_table_is_not_a_cte_exemption():
    assert _validate_sql_query_policy(None, "SELECT (0,1,'integer',1,1,NULL,'$[0]','$') IN json_each('[1]')", policy("json_each")).allowed
    decision = _validate_sql_query_policy(None, "WITH json_each AS (SELECT 1) SELECT 1 IN json_each('[1]')", policy("allowed"))
    assert decision.error_code == "table_access_denied"


@pytest.mark.parametrize("sql", [
    "SELECT 'union', 'x FROM (y', 'LOAD_FILE(x)', 'INTO OUTFILE' FROM allowed",
    "SELECT id AS `union` FROM allowed",
    "SELECT 'IN blocked', 'pragma_table_info(blocked)' FROM allowed",
    "WITH RECURSIVE c(n) AS (SELECT 1) SELECT n FROM c",
])
def test_literals_identifiers_and_nonunion_cte_remain_valid(fixture_database, sql):
    with sqlite3.connect(fixture_database) as db:
        db.execute(sql).fetchall()
    assert _validate_sql_query_policy(None, sql, policy("allowed")) == PolicyDecision.allow()


@pytest.mark.parametrize("sql,code", [
    ("SELECT 1 UNION ALL SELECT 2", "union_disabled"),
    ("SELECT 1; SELECT 2", "multiple_statements"),
    ("PRAGMA index_list('allowed')", "pragma_statement_denied"),
    ("SHOW INDEX FROM allowed", "show_statement_denied"),
    ("EXPLAIN ANALYZE SELECT 1", "executing_explain_denied"),
    ("UPDATE allowed SET id=2", "read_only_required"),
])
def test_rejection_reason_and_recovery_hint(sql, code):
    decision = _validate_sql_query_policy(None, sql, policy("allowed"))
    assert decision.error_code == code
    assert decision.hint
    assert decision.error_payload()["success"] is False


@pytest.mark.parametrize("sql,code", [
    ("SELECT missing FROM allowed", "unknown_column"),
    ("SELECT DATE_FORMAT(id,'%Y') FROM allowed", "unknown_function"),
    ("SELECT * FROM absent", "unknown_table"),
    ("SELECT * FROM allowed WHERE", "incomplete_sql"),
    ("SELECT FROM allowed", "sql_syntax_error"),
])
def test_sqlite_adapter_raises_typed_errors(fixture_database, sql, code):
    adapter = SQLiteAdapter(config=DatabaseConfig(
        connection_id="fixture", db_type="sqlite", query_timeout_seconds=30,
        connect_timeout_seconds=10, policy=policy("allowed"),
        sqlite_database_path=str(fixture_database),
    ))
    try:
        with pytest.raises(DatabaseQueryError) as raised:
            adapter.execute(sql)
        assert raised.value.error_code == code
        assert "missing" not in str(raised.value)
    finally:
        adapter.close()


@pytest.mark.parametrize("errno,code", [
    (1054, "unknown_column"), (1146, "unknown_table"), (1305, "unknown_function"),
    (1064, "sql_syntax_error"), (1582, "invalid_function_arguments"),
    (3024, "query_timeout"), (2013, "database_connection_lost"),
    (1045, "database_access_denied"), (9999, "database_query_failed"),
])
def test_mysql_driver_codes_and_redaction(errno, code):
    import pymysql
    secret = "private_password /private/path private-host"
    error = OperationalError("SELECT :secret", {"secret": secret}, pymysql.err.OperationalError(errno, secret))
    sanitized = classify_database_error(error, "mysql")
    assert sanitized.error_code == code
    assert secret not in json.dumps(sanitized.error_payload())


def test_error_text_cannot_impersonate_mysql_driver_errno():
    assert classify_database_error(Exception("1054 private-host"), "mysql").error_code == "database_query_failed"


def test_skill_inferred_dependencies_use_scoped_parser():
    assert _extract_table_names("WITH c AS (SELECT id FROM allowed) SELECT 'FROM blocked' FROM c WHERE 1 IN other") == ["allowed", "other"]


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_gateway_failure_contract_and_before_execute(fixture_database, tmp_path, monkeypatch, mode):
    directory = tmp_path / "skills" / "read-probe"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text("---\nname: read-probe\ndescription: Read probe\ntype: query\nsource: query.sql\nrisk: low\nparams: {}\n---\n")
    (directory / "query.sql").write_text("SELECT missing FROM allowed")
    denied_directory = directory.parent / "membership-probe"
    denied_directory.mkdir()
    (denied_directory / "skill_def.md").write_text("---\nname: membership-probe\ndescription: Membership probe\ntype: query\nsource: query.sql\nrisk: low\nparams: {}\n---\n")
    (denied_directory / "query.sql").write_text("SELECT id FROM allowed WHERE 1 IN blocked")
    write_toml(tmp_path / "server.toml", {"schema_version": 1, "files": {"connections": "connections.toml", "skills": "skills.toml"}, "server": {"default_connection": "demo"}})
    write_toml(tmp_path / "connections.toml", {"schema_version": 1, "connections": {"demo": {"type": "sqlite", "sqlite": {"path": str(fixture_database)}, "read": {"mode": "allowlist", "tables": ["allowed"]}}}})
    write_toml(tmp_path / "skills.toml", {"schema_version": 1, "skills": {"enabled": True, "directory": str(directory.parent), "readiness": {"check_schema": False}, "audit": {"path": str(tmp_path / "audit.jsonl"), "queries": True}}})
    server = create_server(load_config(tmp_path / "server.toml"))
    try:
        async with Client(server, mode=mode) as client:
            for name, arguments in (("query", {"sql": "SELECT missing FROM allowed"}), ("execute_query_skill", {"skill_name": "read-probe", "params": {}})):
                payload = (await client.call_tool(name, arguments)).structured_content
                assert payload["success"] is False and payload["error_code"] == "unknown_column"
                assert payload["db_type"] == "sqlite" and "describe_table" in payload["hint"]
            assert "unknown_column" in (tmp_path / "audit.jsonl").read_text()
            def unexpected_execute(*args, **kwargs):
                pytest.fail("Rejected query reached the database")
            monkeypatch.setattr(server.gateway_runtime.registry.get_adapter("demo"), "execute", unexpected_execute)
            monkeypatch.setattr(server.gateway_runtime.registry.get_adapter("demo"), "get_read_relations", unexpected_execute)
            server.gateway_runtime.config = replace(
                server.gateway_runtime.config,
                skills=server.gateway_runtime.config.skills.model_copy(update={
                    "readiness": server.gateway_runtime.config.skills.readiness.model_copy(update={"check_schema": True}),
                }),
            )
            for sql in ("SELECT id FROM allowed WHERE 1 IN blocked", "SELECT 1 IN pragma_table_info('blocked')", "SELECT 1; SELECT 2"):
                payload = (await client.call_tool("query", {"sql": sql})).structured_content
                assert payload["success"] is False and payload["error_code"]
            denied = (await client.call_tool("execute_query_skill", {"skill_name": "membership-probe", "params": {}})).structured_content
            assert denied["error_code"] == "table_access_denied"
    finally:
        server.gateway_runtime.close()
