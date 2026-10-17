"""Semantic identities and mode-aware parsing, independent of live databases."""
import sqlite3

import pytest

from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext


@pytest.mark.parametrize("name", ["data", "summary", "result", "window", "offset", "unıon", "offſet", "wındow", "K", "like", "regexp", "replace"])
def test_native_cte_and_analysis_agree(name):
    sql = f"WITH {name}(n) AS (SELECT 7) SELECT n FROM {name}"
    with sqlite3.connect(":memory:") as native:
        assert native.execute(sql).fetchall() == [(7,)]
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete, result
    assert result.statement_kind == "select"
    assert result.relations == ()


@pytest.mark.parametrize("source,expected", [
    ("main.orders", RelationReference("orders", "main")),
    ('"main.orders"', RelationReference("main.orders")),
    ('" f "', RelationReference(" f ")),
    ('"  f  "', RelationReference("  f  ")),
    ('"a""b"', RelationReference('a"b')),
    ("[orders]", RelationReference("orders")),
    ("`orders`", RelationReference("orders")),
])
def test_reference_components_and_lexical_occurrence(source, expected):
    sql = "SELECT * FROM " + source
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete
    assert result.relations == (expected,)
    occurrence = next(n for n in result.names if n.role == "relation")
    assert occurrence.raw == ("orders" if source == "main.orders" else source)
    assert occurrence.name == expected.name


@pytest.mark.parametrize("prefix", ["EXPLAIN", "EXPLAIN QUERY PLAN"])
def test_sqlite_explain_keeps_real_dependencies(prefix):
    result = analyze_sql(prefix + " SELECT n FROM main.orders", DialectContext("sqlite"))
    assert result.complete
    assert result.statement_kind == "explain"
    assert result.relations == (RelationReference("orders", "main"),)


@pytest.mark.parametrize("sql", ["SELECT 7 IN main.orders", "SELECT 7 NOT IN main.orders"])
def test_membership_has_a_real_dependency(sql):
    assert analyze_sql(sql, DialectContext("sqlite")).relations == (RelationReference("orders", "main"),)


def test_scope_order_does_not_hide_physical_self_or_forward_reference():
    context = DialectContext("mysql")
    for sql in [
        "WITH orders AS (SELECT n FROM orders) SELECT n FROM orders",
        "WITH first AS (SELECT n FROM orders), orders AS (SELECT 7 AS n) SELECT * FROM first",
    ]:
        result = analyze_sql(sql, context)
        assert result.complete
        assert result.relations == (RelationReference("orders"),)


@pytest.mark.parametrize("sql,expected", [
    ("WITH first AS (SELECT n FROM orders), orders AS (SELECT 7 AS n) SELECT * FROM first", [(7,)]),
    ("WITH orders(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM orders WHERE n<3) SELECT n FROM orders", [(1,), (2,), (3,)]),
])
def test_sqlite_forward_and_implicit_recursive_visibility_match_native(sql, expected):
    with sqlite3.connect(":memory:") as native:
        native.execute("CREATE TABLE orders(n)")
        native.execute("INSERT INTO orders VALUES(99)")
        assert native.execute(sql).fetchall() == expected
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete and result.relations == ()
    assert result.ctes and result.scopes


@pytest.mark.parametrize("quoted", ['"SLEEP"', "`SLEEP`", "SLEEP"])
def test_cte_body_functions_remain_visible(quoted):
    result = analyze_sql(f'WITH "data"(n) AS (SELECT {quoted}(0)) SELECT n FROM "data"', DialectContext("sqlite"))
    assert result.complete
    assert result.functions == frozenset({"sleep"})


def test_partial_analysis_is_not_empty_dependencies():
    result = analyze_sql("SELECT * FROM pragma_table_info('orders')", DialectContext("sqlite"))
    assert result.status == "partial"
    assert "virtual_relation" in result.unsupported
    assert result.relations == (RelationReference("pragma_table_info"),)


def test_nested_write_and_parameters_are_independent():
    result = analyze_sql("WITH x AS (DELETE FROM orders RETURNING n) SELECT :value FROM x", DialectContext("sqlite"))
    assert result.has_nested_write
    assert result.parameters == frozenset({"value"})


@pytest.mark.parametrize("role", ["schema", "relation", "column"])
def test_mysql_invalid_physical_names_are_not_trimmed(role):
    context = DialectContext("mysql")
    assert not context.valid_name(" f ", role)
    assert context.valid_name(" f", role)
    assert DialectContext("sqlite").valid_name(" f ", role)


@pytest.mark.parametrize("role", ["cte", "table_alias", "column_alias"])
def test_physical_trailing_space_rule_is_not_applied_to_other_roles(role):
    assert DialectContext("mysql").valid_name(" f ", role)


def test_session_modes_change_double_quote_interpretation():
    standard = analyze_sql('SELECT "n" AS result', DialectContext("mysql"))
    ansi = analyze_sql('SELECT "n" AS result', DialectContext("mysql", frozenset({"ANSI_QUOTES"})))
    assert standard.complete and ansi.complete
    # A quoted function is a callable identifier only in the ANSI profile.
    standard_call = analyze_sql('SELECT "SLEEP"(0)', DialectContext("mysql"))
    ansi_call = analyze_sql('SELECT "SLEEP"(0)', DialectContext("mysql", frozenset({"ANSI_QUOTES"})))
    assert not standard_call.complete
    assert ansi_call.functions == frozenset({"sleep"})
    assert standard.context_key != ansi.context_key


@pytest.mark.parametrize("name", ["for", "glob", "rollback", "with"])
def test_sqlite_membership_contextual_name_is_a_real_dependency(name):
    sql = f"SELECT 99 IN {name}"
    with sqlite3.connect(":memory:") as db:
        db.execute(f'CREATE TABLE "{name}"(n)')
        db.execute(f'INSERT INTO "{name}" VALUES(99)')
        assert db.execute(sql).fetchall() == [(1,)]
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete and result.relations == (RelationReference(name),)


@pytest.mark.parametrize("tail", ["window", "lock", "for", "INDEXED BY for", 'INDEXED BY "window"'])
def test_sqlite_alias_or_index_never_hides_the_following_relation(tail):
    from sql_safety_executor.core.policy import _validate_sql_query_policy
    from sql_safety_executor.database.models import ConnectionPolicy
    sql = f"SELECT b.n FROM orders {tail}, other AS b"
    with sqlite3.connect(":memory:") as db:
        db.executescript('CREATE TABLE orders(n);INSERT INTO orders VALUES(7);CREATE TABLE other(n);INSERT INTO other VALUES(99);CREATE INDEX "for" ON orders(n);CREATE INDEX "window" ON orders(n);')
        assert db.execute(sql).fetchall() == [(99,)]
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete and set(result.relations) == {RelationReference("orders"), RelationReference("other")}
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).error_code == "table_access_denied"


def test_real_named_window_clause_is_not_consumed_as_an_alias():
    sql = "SELECT SUM(n) OVER win AS n FROM orders WINDOW win AS (ORDER BY n)"
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete and result.relations == (RelationReference("orders"),)


@pytest.mark.parametrize("name", ["CURRENT_USER", "current_user", "CuRrEnT_UsEr", "CURRENT_DATETIME", "CURRENT_ROLE", "LOCALTIME", "LOCALTIMESTAMP"])
def test_sqlite_bare_standard_function_spelling_remains_a_business_column(name):
    from sql_safety_executor.core.policy import _validate_sql_query_policy
    from sql_safety_executor.database.models import ConnectionPolicy
    sql = f"SELECT {name} FROM orders"
    with sqlite3.connect(":memory:") as db:
        db.execute(f'CREATE TABLE orders("{name}" INTEGER)')
        db.execute("INSERT INTO orders VALUES(7)")
        assert db.execute(sql).fetchall() == [(7,)]
    result = analyze_sql(sql, DialectContext("sqlite"))
    assert result.complete and not result.functions
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).allowed


@pytest.mark.parametrize("dialect,sql", [("sqlite", "SELECT CURRENT_USER()"), ("mysql", "SELECT CURRENT_USER()"), ("mysql", "SELECT CURRENT_USER")])
def test_actual_account_functions_keep_their_own_dialect_rules(dialect, sql):
    from types import SimpleNamespace
    from sql_safety_executor.core.policy import _validate_sql_query_policy
    from sql_safety_executor.database.models import ConnectionPolicy
    context = DialectContext(dialect)
    adapter = SimpleNamespace(analysis_context=context, cte_case_sensitive=True)
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"})), adapter=adapter).error_code == "server_state_denied"
