"""Native empty-column CTE reads must not become physical relation grants."""
import sqlite3

import pytest

from sql_safety_executor.database.authorizer import SQLiteReadGuard
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.sqlite import SQLiteAdapter


@pytest.fixture
def adapter(tmp_path):
    path = tmp_path / "cte-count.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE orders(n);INSERT INTO orders VALUES(7);"
            "CREATE TABLE hidden(n);INSERT INTO hidden VALUES(99);"
            "CREATE VIEW report AS WITH selected AS MATERIALIZED "
            "(SELECT n FROM hidden) SELECT COUNT(*) AS n FROM selected;"
        )
    value = SQLiteAdapter(config=DatabaseConfig(
        "fixture", "sqlite", 5, 5, ConnectionPolicy(), sqlite_database_path=str(path)))
    assert value.connect()
    yield value
    value.close()


def grant(*names):
    return ConnectionPolicy(allowed_tables=frozenset(names))


@pytest.mark.parametrize("sql,expected", [
    ("WITH selected AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM selected", [(1,)]),
    ("WITH selected AS MATERIALIZED (SELECT n FROM orders), next AS (SELECT n FROM selected) SELECT COUNT(*) FROM next", [(1,)]),
    ("WITH selected AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM selected UNION ALL SELECT SUM(n) FROM selected", [(1,), (7,)]),
    ("WITH selected AS (SELECT 7 n) SELECT COUNT(*) FROM selected UNION ALL SELECT SUM(n) FROM selected", [(1,), (7,)]),
    ('WITH "订单" AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM "订单"', [(1,)]),
])
def test_empty_column_cte_read_uses_verified_ephemeral_identity(adapter, sql, expected):
    assert adapter.execute_read(sql, policy=grant("orders")) == expected


def test_internal_view_cte_count_does_not_grant_its_base(adapter):
    assert adapter.execute_read("SELECT n FROM main.report", policy=grant("main.report")) == [(1,)]
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT COUNT(*) FROM main.hidden", policy=grant("main.report"))
    assert denied.value.error_code == "table_access_denied"


@pytest.mark.parametrize("schema", ["main", "temp", "aux"])
def test_cte_empty_read_does_not_guess_when_a_catalog_object_shares_its_name(adapter, schema):
    if schema == "aux":
        adapter.execute_write("ATTACH ':memory:' AS aux", {})
    adapter.execute_write(f"CREATE TABLE {schema}.selected(n)", {})
    adapter.execute_write(f"INSERT INTO {schema}.selected VALUES(99)", {})
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(
            "WITH selected AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM selected",
            policy=grant("orders"))
    assert denied.value.error_code == "view_scope_unresolved"


@pytest.mark.parametrize("sql", [
    "WITH hidden AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM main.hidden",
    "WITH selected AS MATERIALIZED (SELECT n FROM hidden) SELECT COUNT(*) FROM selected",
    "WITH selected AS MATERIALIZED (SELECT n FROM orders) SELECT COUNT(*) FROM hidden",
])
def test_cte_count_never_authorizes_an_ungranted_physical_dependency(adapter, sql):
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(sql, policy=grant("orders"))
    assert denied.value.error_code == "table_access_denied"


def test_missing_database_is_not_a_blanket_cte_name_exception():
    guard = SQLiteReadGuard(grant("orders"), "main", frozenset({"selected"}))
    # Without catalog-verified ephemeral identity, names alone grant nothing.
    assert guard.authorize(sqlite3.SQLITE_READ, "selected", "", None, None) == sqlite3.SQLITE_DENY
    assert guard.authorize(sqlite3.SQLITE_READ, "selected", "n", None, None) == sqlite3.SQLITE_DENY
    assert guard.authorize(sqlite3.SQLITE_READ, "selected", "", "temp", None) == sqlite3.SQLITE_DENY


@pytest.mark.parametrize("name,code", [("SLEEP", "expensive_function_denied"), ("USER", "server_state_denied")])
def test_ephemeral_count_keeps_function_checks_before_evaluation(adapter, name, code):
    called = []
    with adapter._engine.connect() as connection:
        connection.connection.dbapi_connection.create_function(name, 0, lambda: called.append(True) or 7)
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(
            f'WITH selected AS MATERIALIZED (SELECT "{name}"() AS n FROM orders) SELECT COUNT(*) FROM selected',
            policy=grant("orders"))
    assert denied.value.error_code == code and called == []
