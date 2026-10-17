"""Actual SQLite compilation, connection ownership and view authorization."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
from threading import Event

import pytest

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.sqlite import SQLiteAdapter


@pytest.fixture
def adapter(tmp_path):
    path = tmp_path / "guard.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE orders(n INTEGER);INSERT INTO orders VALUES(7);"
            "CREATE TABLE hidden(n INTEGER);INSERT INTO hidden VALUES(99);"
            "CREATE VIEW approved AS SELECT n FROM hidden;"
            "CREATE VIEW report AS SELECT n FROM approved;"
        )
    value = SQLiteAdapter(config=DatabaseConfig(
        "fixture", "sqlite", 5, 5, ConnectionPolicy(), sqlite_database_path=str(path)))
    assert value.connect()
    yield value
    value.close()


def grant(*names):
    return ConnectionPolicy(allowed_tables=frozenset(names))


@pytest.mark.parametrize("source", ["approved", "report"])
def test_authorized_view_does_not_grant_direct_base_access(adapter, source):
    policy = grant(f"main.{source}")
    assert adapter.execute_read(f"SELECT n FROM main.{source}", policy=policy) == [(99,)]
    with pytest.raises(DatabaseQueryError, match="not authorized"):
        adapter.execute_read("SELECT n FROM main.hidden", policy=policy)
    assert adapter.execute_read(f"SELECT n FROM main.{source}", policy=policy) == [(99,)]


@pytest.mark.parametrize("temporary", ["TABLE orders(n)", "VIEW orders AS SELECT n FROM hidden"])
def test_actual_temp_binding_never_inherits_main_grant(adapter, temporary):
    with adapter._engine.begin() as conn:
        conn.exec_driver_sql("CREATE TEMP " + temporary)
        if temporary.startswith("TABLE"):
            conn.exec_driver_sql("INSERT INTO temp.orders VALUES(99)")
    for policy in (grant("orders"), grant("main.orders")):
        assert adapter.execute_read("SELECT n FROM main.orders", policy=policy) == [(7,)]
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read("SELECT n FROM orders", policy=policy)
        assert denied.value.error_code == "table_access_denied"


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM main.orders",
    "WITH selected AS (SELECT n FROM main.orders) SELECT COUNT(*) FROM selected",
    "WITH first AS (SELECT n FROM main.orders), second AS (SELECT n FROM first) SELECT COUNT(*) FROM second",
])
def test_count_and_cte_source_events_keep_real_authorization(adapter, sql):
    assert adapter.execute_read(sql, policy=grant("main.orders")) == [(1,)]


@pytest.mark.parametrize("sql", [
    "SELECT n FROM main.hidden",
    "WITH report AS (SELECT n FROM main.hidden) SELECT n FROM report",
    "SELECT n FROM main.report UNION ALL SELECT n FROM main.hidden",
])
def test_view_grant_cannot_be_reused_through_cte_or_direct_union(adapter, sql):
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(sql, policy=grant("main.report"))
    assert denied.value.error_code == "table_access_denied"


def test_trusted_preparation_and_metadata_do_not_poison_reused_read(adapter):
    sql = "SELECT n FROM main.hidden"
    assert adapter.execute(sql) == [(99,)]
    assert adapter.get_columns("hidden")
    for _ in range(3):
        with pytest.raises(DatabaseQueryError):
            adapter.execute_read(sql, policy=grant("orders"))
        assert adapter.execute_read(sql, policy=grant("hidden")) == [(99,)]
    assert adapter.get_columns("hidden")


@pytest.mark.parametrize("sql,code", [
    ("UPDATE main.orders SET n=99", "read_only_required"),
    ("DELETE FROM main.orders", "read_only_required"),
    ("PRAGMA main.table_info(orders)", "server_state_denied"),
    ("ATTACH ':memory:' AS extra", "read_only_required"),
    ("BEGIN", "read_only_required"),
    ("SAVEPOINT probe", "read_only_required"),
])
def test_compile_guard_denies_operations_even_without_frontend_policy(adapter, sql, code):
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(sql, policy=grant("orders"))
    assert denied.value.error_code == code
    assert adapter.execute("SELECT n FROM main.orders") == [(7,)]


@pytest.mark.parametrize("name,code", [
    ("SLEEP", "expensive_function_denied"), ("BENCHMARK", "expensive_function_denied"),
    ("GET_LOCK", "lock_function_denied"), ("RELEASE_LOCK", "lock_function_denied"),
    ("RELEASE_ALL_LOCKS", "lock_function_denied"), ("LOAD_FILE", "file_operation_denied"),
    ("USER", "server_state_denied"),
])
def test_reserved_calls_in_view_are_denied_before_harmless_udf_runs(adapter, name, code):
    called = []
    with adapter._engine.begin() as conn:
        conn.connection.dbapi_connection.create_function(name, 0, lambda: called.append(True) or 7)
        conn.exec_driver_sql(f'CREATE VIEW probe AS SELECT "{name}"() AS n')
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT n FROM main.probe", policy=grant("main.probe"))
    assert denied.value.error_code == code
    assert called == []


def test_udf_exception_restores_context_and_progress_handler(adapter):
    def fail():
        raise ValueError("private callback detail")
    with adapter._engine.connect() as conn:
        conn.connection.dbapi_connection.create_function("business_failure", 0, fail)
    with pytest.raises(DatabaseQueryError):
        adapter.execute_read("SELECT business_failure()", policy=grant("orders"))
    assert adapter._active_guard is None and adapter._read_request is None
    assert adapter.execute_read("SELECT n FROM orders", policy=grant("orders")) == [(7,)]
    assert adapter.get_columns("hidden")


def test_physical_connection_is_owned_until_result_consumption(adapter):
    entered, release, second_started = Event(), Event(), Event()
    def gate(value):
        entered.set()
        assert release.wait(5)
        return value
    with adapter._engine.connect() as conn:
        conn.connection.dbapi_connection.create_function("business_gate", 1, gate)
    def denied_operation():
        second_started.set()
        with pytest.raises(DatabaseQueryError):
            adapter.execute_read("SELECT n FROM hidden", policy=grant("orders"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adapter.execute_read, "SELECT business_gate(n) FROM orders", policy=grant("orders"))
        try:
            assert entered.wait(3)
            second = pool.submit(denied_operation)
            assert second_started.wait(3)
            assert not second.done()
        finally:
            release.set()
        assert first.result(timeout=5) == [(7,)]
        second.result(timeout=5)


@pytest.mark.parametrize("name", [" f ", "  f  ", "main.orders", 'a"b', "a:b", ":binding", r"\:binding", "a;SELECT 1", "a--b", "K", "订单 汇总", "x" * 80])
def test_metadata_and_reads_share_exact_name_components(adapter, name):
    quoted = '"' + name.replace('"', '""') + '"'
    with adapter._engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TABLE main.{quoted}(n INTEGER)")
        conn.exec_driver_sql(f"INSERT INTO main.{quoted} VALUES(13)")
    policy = ConnectionPolicy(allowed_tables=frozenset({name}), allowed_relations=frozenset({RelationReference(name, "main")}))
    adapter._config = replace(adapter._config, policy=policy)
    assert adapter.valid_metadata_identifier(name)
    assert adapter.get_columns(name)[0]["column_name"] == "n"
    assert adapter.get_row_estimate(name) == 1
    assert adapter.execute_read(f"SELECT n FROM main.{quoted}", policy=policy) == [(13,)]


def test_only_real_parameters_bind_and_driver_receives_original_literal_content(adapter):
    from sqlalchemy import event
    captured = []
    event.listen(adapter._engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: captured.append((statement, params)))
    sql = r'''SELECT ':literal' AS "out:name", '\:data' AS original, :value AS n -- :comment'''
    with sqlite3.connect(":memory:") as native:
        expected = native.execute(sql, {"value": 23}).fetchall()
    assert adapter.execute_read(sql, params={"value": 23}, policy=grant("orders")) == expected
    statement, params = captured[-1]
    assert "':literal'" in statement and '"out:name"' in statement
    assert r"'\:data'" in statement and "-- :comment" in statement
    assert params == (23,)


def test_rowid_plan_empty_column_events_keep_schema_binding(adapter):
    adapter.execute_write("CREATE TABLE main.widgets(id INTEGER PRIMARY KEY)", {})
    adapter.execute_write("INSERT INTO main.widgets VALUES(7)", {})
    policy = grant("widgets")
    assert adapter.execute_read("SELECT id FROM widgets ORDER BY id", policy=policy) == [(7,)]
    adapter.execute_write("CREATE TEMP TABLE widgets(id INTEGER PRIMARY KEY)", {})
    adapter.execute_write("INSERT INTO temp.widgets VALUES(99)", {})
    with pytest.raises(DatabaseQueryError):
        adapter.execute_read("SELECT id FROM widgets ORDER BY id", policy=policy)
    assert adapter.execute_read("SELECT id FROM main.widgets ORDER BY id", policy=policy) == [(7,)]


@pytest.mark.parametrize("definition", [
    "WITH data AS (SELECT n FROM hidden) SELECT n FROM data",
    "WITH data AS MATERIALIZED (SELECT n FROM hidden), next AS (SELECT n FROM data) SELECT n FROM next",
])
def test_view_cte_dependencies_keep_view_only_authorization(adapter, definition):
    adapter.execute_write("CREATE VIEW main.cte_report AS " + definition, {})
    assert adapter.execute_read("SELECT n FROM main.cte_report", policy=grant("main.cte_report")) == [(99,)]
    with pytest.raises(DatabaseQueryError):
        adapter.execute_read("SELECT n FROM main.hidden", policy=grant("main.cte_report"))


def test_ambiguous_view_and_query_source_label_is_explicitly_unsupported(adapter):
    adapter.execute_write("CREATE VIEW main.cte_report AS WITH data AS (SELECT n FROM hidden) SELECT n FROM data", {})
    sql = "WITH data AS (SELECT n FROM main.orders) SELECT n FROM main.cte_report WHERE n IN data"
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(sql, policy=grant("main.orders", "main.cte_report"))
    assert denied.value.error_code == "view_scope_unresolved"


def test_view_redefinition_cannot_reuse_previous_callback_edges(adapter):
    assert adapter.execute_read("SELECT n FROM main.approved", policy=grant("main.approved")) == [(99,)]
    # A new definition is trusted schema, but its actual calls are still checked.
    called = []
    with adapter._engine.begin() as conn:
        conn.connection.dbapi_connection.create_function("SLEEP", 0, lambda: called.append(True) or 13)
        conn.exec_driver_sql("DROP VIEW main.approved")
        conn.exec_driver_sql("CREATE VIEW main.approved AS SELECT SLEEP() AS n")
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT n FROM main.approved", policy=grant("main.approved"))
    assert denied.value.error_code == "expensive_function_denied" and called == []
    assert adapter.execute_read("SELECT n FROM main.orders", policy=grant("main.orders")) == [(7,)]


def test_explicit_attached_grant_is_independent_of_default_schema(adapter):
    with adapter._engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS aux")
    adapter.execute_write("CREATE TABLE aux.orders(n)", {})
    adapter.execute_write("INSERT INTO aux.orders VALUES(23)", {})
    with pytest.raises(DatabaseQueryError):
        adapter.execute_read("SELECT n FROM aux.orders", policy=grant("orders"))
    assert adapter.execute_read("SELECT n FROM aux.orders", policy=grant("aux.orders")) == [(23,)]
    assert adapter.execute_read("SELECT n FROM main.orders", policy=grant("main.orders")) == [(7,)]


def test_external_schema_change_after_preparation_cannot_inherit_stale_edges(adapter, monkeypatch):
    import sql_safety_executor.database.sqlite as module
    build = module.build_read_guard
    changed = False
    def change_after_build(connection, policy, context, analysis, **kwargs):
        nonlocal changed
        result = build(connection, policy, context, analysis, **kwargs)
        if not changed:
            changed = True
            with sqlite3.connect(adapter._database_path) as external:
                external.executescript("DROP VIEW approved;CREATE VIEW approved AS SELECT n FROM orders;")
        return result
    monkeypatch.setattr(module, "build_read_guard", change_after_build)
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT n FROM main.approved", policy=grant("main.approved"))
    assert denied.value.error_code == "table_access_denied"
    # A later request deliberately rebuilds the now-current reviewed view path.
    assert adapter.execute_read("SELECT n FROM main.approved", policy=grant("main.approved")) == [(7,)]
