"""Regression tests for the shared MCP SQL safety policy."""

import importlib
import sys
from pathlib import Path

import pytest


def _reload_server(monkeypatch):
    monkeypatch.setenv("ENABLE_SKILLS", "0")
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", ":memory:")
    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("mcp_sql_server")


def test_shared_sql_policy_allows_normal_read_query(monkeypatch):
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy(
        "SELECT id, name FROM users WHERE id = 1"
    )

    assert is_safe is True
    assert error is None


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN ANALYZE DELETE FROM orders WHERE id = 1",
        "EXPLAIN/**/ANALYZE UPDATE orders SET status = 'cancelled'",
        "EXPLAIN (ANALYZE TRUE, BUFFERS TRUE) DELETE FROM orders",
        "DESCRIBE ANALYZE DELETE FROM orders WHERE id = 1",
        "SELECT 1; EXPLAIN ANALYZE DELETE FROM orders WHERE id = 1",
    ],
)
def test_shared_sql_policy_blocks_executing_explain_forms(monkeypatch, sql):
    """EXPLAIN ANALYZE can execute its child statement on supported MySQL."""
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(allow_union=False, allowed_tables={"*"})

    is_safe, error = module._validate_sql_query_policy(sql, policy)

    assert is_safe is False
    assert error == (
        "Only read-only queries allowed "
        "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
    )


def test_basic_sql_policy_blocks_select_shaped_nested_write_cte(monkeypatch):
    module = _reload_server(monkeypatch)

    assert module.is_sql_safe(
        "WITH changed AS (DELETE FROM orders RETURNING *) "
        "SELECT * FROM changed"
    ) is False


def test_basic_sql_policy_preserves_read_cte_and_plain_explain(monkeypatch):
    """Plain EXPLAIN inspects a plan; ANALYZE is the executing variant."""
    module = _reload_server(monkeypatch)

    assert module.is_sql_safe(
        "WITH current_orders AS (SELECT * FROM orders) "
        "SELECT * FROM current_orders"
    ) is True
    assert module.is_sql_safe("EXPLAIN DELETE FROM orders WHERE id = 1") is True
    assert module.is_sql_safe("DESC orders") is True


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN FOR CONNECTION 123",
        "EXPLAIN FORMAT=JSON FOR CONNECTION 123",
        "DESCRIBE FOR CONNECTION 123",
    ],
)
def test_basic_and_shared_policy_block_explain_for_connection(monkeypatch, sql):
    """Session inspection is privilege-dependent and outside raw-query scope."""
    module = _reload_server(monkeypatch)

    assert module.is_sql_safe(sql) is False
    is_safe, error = module._validate_sql_query_policy(sql)
    assert is_safe is False
    assert error == (
        "Only read-only queries allowed "
        "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
    )


def test_shared_sql_policy_blocks_mysql_file_operations(monkeypatch):
    module = _reload_server(monkeypatch)

    blocked_queries = [
        "SELECT * FROM users INTO OUTFILE '/tmp/users.txt'",
        "SELECT * FROM users INTO/**/DUMPFILE '/tmp/users.bin'",
        "SELECT LOAD_FILE('/etc/passwd')",
    ]

    for sql in blocked_queries:
        is_safe, error = module._validate_sql_query_policy(sql)
        assert is_safe is False
        assert error == "MySQL server-side file operations are not allowed"


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN /*! ANALYZE */ UPDATE a JOIN b ON a.id=b.id SET a.x=1",
        "SELECT * FROM orders /*! INTO OUTFILE '/tmp/leak' */",
        "SELECT /*+ SET_VAR(max_execution_time=0) */ SLEEP(1000)",
        "SELECT /*M! SLEEP(1000) */ 1",
        "SELECT 1--1 INTO OUTFILE '/tmp/leak'",
        "SELECT 1--1, authentication_string FROM mysql.user",
    ],
)
def test_shared_sql_policy_rejects_mysql_comment_semantic_mismatches(
    monkeypatch, sql
):
    """Comment stripping must not hide SQL that MySQL would execute."""
    module = _reload_server(monkeypatch)

    assert module.is_sql_safe(sql) is False
    is_safe, error = module._validate_sql_query_policy(sql)

    assert is_safe is False
    assert error == (
        "Only read-only queries allowed "
        "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 -- ordinary comment\n",
        "SELECT '--1 is string data'",
        "SELECT '/*! not executable inside a string */'",
    ],
)
def test_shared_sql_policy_preserves_safe_comments_and_string_literals(
    monkeypatch, sql
):
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy(sql)

    assert is_safe is True
    assert error is None


def test_shared_sql_policy_blocks_comment_separated_show(monkeypatch):
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy("SHOW/**/VARIABLES")

    assert is_safe is False
    assert error == (
        "SHOW statements are not allowed in raw queries. "
        "Use list_tables() or describe_table() instead."
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SHOW TABLES",
        "SHOW FULL TABLES",
        "SHOW TABLE STATUS",
        "SHOW CREATE TABLE forbidden",
        "SHOW CREATE USER CURRENT_USER",
        "SHOW FULL PROCESSLIST",
        "SHOW GLOBAL VARIABLES",
        "SHOW REPLICA STATUS",
    ],
)
def test_shared_sql_policy_blocks_all_raw_show_forms(monkeypatch, sql):
    """Metadata tools replace the broad, privilege-dependent SHOW grammar."""
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy(sql)

    assert is_safe is False
    assert error == (
        "SHOW statements are not allowed in raw queries. "
        "Use list_tables() or describe_table() instead."
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SHOW VARIABLES",
        "SELECT 1; SELECT 2",
        "SELECT 1;; SELECT 2",
    ],
)
def test_basic_and_shared_policy_reject_multiple_statements(monkeypatch, sql):
    module = _reload_server(monkeypatch)

    assert module.is_sql_safe(sql) is False
    is_safe, error = module._validate_sql_query_policy(sql)

    assert is_safe is False
    assert error == (
        "Only read-only queries allowed "
        "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
    )


def test_shared_sql_policy_blocks_quoted_system_schemas(monkeypatch):
    module = _reload_server(monkeypatch)

    blocked_queries = [
        "SELECT * FROM `information_schema`.`tables`",
        "SELECT * FROM `mysql`.`user`",
        "SELECT * FROM performance_schema.events_statements_summary_by_digest",
        "SELECT * FROM sys.session",
        "SELECT * FROM `sys`.`statement_analysis`",
        'SELECT * FROM "mysql"."user"',
        'SELECT * FROM "information_schema"."tables"',
        'SELECT * FROM "performance_schema"."threads"',
        'SELECT * FROM "sys"."session"',
    ]

    for sql in blocked_queries:
        is_safe, error = module._validate_sql_query_policy(sql)
        assert is_safe is False
        assert error == (
            "Access to system databases not allowed. "
            "Use list_tables() or describe_table() instead."
        )


def test_system_schema_names_in_string_literals_are_not_tables(monkeypatch):
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy(
        "SELECT 'mysql.user', 'information_schema.tables', 'sys.session'"
    )

    assert is_safe is True
    assert error is None


def test_table_allowlist_blocks_quoted_identifiers(monkeypatch):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(allow_union=False, allowed_tables={"orders"})

    blocked_queries = [
        'SELECT * FROM "forbidden"',
        'SELECT * FROM [forbidden]',
        'SELECT * FROM main."forbidden"',
        'EXPLAIN SELECT * FROM "forbidden"',
    ]

    for sql in blocked_queries:
        is_safe, error = module._validate_sql_query_policy(sql, policy)
        assert is_safe is False
        assert "forbidden" in error

    is_safe, error = module._validate_sql_query_policy(
        'SELECT * FROM "orders"', policy
    )
    assert is_safe is True
    assert error is None


@pytest.mark.parametrize(
    ("sql", "blocked_table"),
    [
        ("SELECT * FROM orders, forbidden", "forbidden"),
        ("SELECT * FROM/* ordinary comment */ forbidden", "forbidden"),
        ("SELECT * FROM other_database.orders", "other_database.orders"),
        ("SELECT * FROM orders o JOIN forbidden f ON o.id = f.id", "forbidden"),
        (
            "SELECT * FROM orders WHERE EXISTS "
            "(SELECT 1 FROM forbidden WHERE forbidden.id = orders.id)",
            "forbidden",
        ),
        (
            "WITH selected AS (SELECT * FROM forbidden) SELECT * FROM selected",
            "forbidden",
        ),
        ("EXPLAIN SELECT * FROM forbidden", "forbidden"),
    ],
)
def test_table_allowlist_blocks_every_referenced_table(
    monkeypatch, sql, blocked_table
):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=True,
        allowed_tables=frozenset({"orders"}),
    )

    assert blocked_table in module._extract_tables_from_sql(sql)
    is_safe, error = module._validate_sql_query_policy(sql, policy)

    assert is_safe is False
    assert blocked_table in error


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN UPDATE forbidden SET status = 'cancelled'",
        "EXPLAIN UPDATE orders o JOIN forbidden f ON o.id = f.id "
        "SET o.status = 'cancelled'",
        "EXPLAIN INSERT INTO forbidden (id) VALUES (1)",
        "EXPLAIN INSERT LOW_PRIORITY IGNORE INTO forbidden (id) "
        "SELECT id FROM orders",
        "EXPLAIN INSERT INTO orders (id) SELECT id FROM forbidden",
        "EXPLAIN REPLACE INTO forbidden (id) VALUES (1)",
        "EXPLAIN DELETE FROM forbidden WHERE id = 1",
        "EXPLAIN DELETE FROM orders USING orders, forbidden "
        "WHERE orders.id = forbidden.id",
        "DESCRIBE UPDATE forbidden SET status = 'cancelled'",
        "DESC INSERT INTO forbidden (id) VALUES (1)",
        "EXPLAIN WITH selected AS (SELECT * FROM forbidden) "
        "SELECT * FROM selected",
    ],
)
def test_table_allowlist_blocks_explained_dml_targets_and_sources(
    monkeypatch, sql
):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=True,
        allowed_tables=frozenset({"orders"}),
    )

    is_safe, error = module._validate_sql_query_policy(sql, policy)

    assert is_safe is False
    assert "forbidden" in error


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN UPDATE orders SET status = 'cancelled'",
        "EXPLAIN UPDATE LOW_PRIORITY IGNORE orders SET status = 'cancelled'",
        "EXPLAIN UPDATE orders a, orders b SET a.status = b.status",
        "EXPLAIN INSERT INTO orders (id) VALUES (1)",
        "EXPLAIN INSERT LOW_PRIORITY IGNORE INTO orders (id) "
        "SELECT id FROM orders",
        "EXPLAIN INSERT INTO orders (id) VALUES (1) "
        "ON DUPLICATE KEY UPDATE id = VALUES(id)",
        "EXPLAIN REPLACE INTO orders (id) VALUES (1)",
        "EXPLAIN REPLACE orders (id) VALUES (1)",
        "EXPLAIN DELETE FROM orders WHERE id = 1",
        "EXPLAIN DELETE FROM orders USING orders, orders AS archived "
        "WHERE orders.id = archived.id",
        "EXPLAIN DELETE orders FROM orders JOIN orders AS archived USING (id)",
        "DESCRIBE DELETE LOW_PRIORITY FROM orders USING orders "
        "WHERE orders.id = 1",
        "DESCRIBE UPDATE orders SET status = 'cancelled'",
        "DESC INSERT INTO orders (id) VALUES (1)",
        "EXPLAIN WITH selected AS (SELECT * FROM orders) "
        "SELECT * FROM selected",
    ],
)
def test_table_allowlist_preserves_explained_dml_for_allowed_tables(
    monkeypatch, sql
):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=True,
        allowed_tables=frozenset({"orders"}),
    )

    is_safe, error = module._validate_sql_query_policy(sql, policy)

    assert is_safe is True
    assert error is None


def test_table_allowlist_fails_closed_on_ambiguous_explained_dml_target(
    monkeypatch,
):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=False,
        allowed_tables=frozenset({"orders"}),
    )

    is_safe, error = module._validate_sql_query_policy(
        "EXPLAIN UPDATE (SELECT * FROM orders) SET status = 'cancelled'",
        policy,
    )

    assert is_safe is False
    assert error == "Table allowlist could not safely determine every referenced table"

    is_safe, error = module._validate_sql_query_policy(
        "EXPLAIN DELETE FROM orders USING (SELECT * FROM orders)",
        policy,
    )
    assert is_safe is False
    assert error == "Table allowlist could not safely determine every referenced table"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        'SELECT * FROM "orders"',
        "SELECT * FROM orders a JOIN orders b ON a.id = b.id",
        "SELECT * FROM orders a JOIN orders b USING (id)",
        "WITH selected AS (SELECT * FROM orders) SELECT * FROM selected",
        "EXPLAIN SELECT * FROM orders",
        "EXPLAIN FORMAT=JSON SELECT * FROM orders",
        "DESCRIBE orders",
    ],
)
def test_table_allowlist_preserves_supported_allowed_queries(monkeypatch, sql):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=True,
        allowed_tables=frozenset({"orders"}),
    )

    is_safe, error = module._validate_sql_query_policy(sql, policy)

    assert is_safe is True
    assert error is None


def test_table_allowlist_requires_exact_qualified_reference(monkeypatch):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=False,
        allowed_tables=frozenset({"analytics.orders"}),
    )

    assert module._validate_sql_query_policy(
        "SELECT * FROM analytics.orders", policy
    ) == (True, None)
    is_safe, error = module._validate_sql_query_policy(
        "SELECT * FROM orders", policy
    )
    assert is_safe is False
    assert "orders" in error


def test_table_allowlist_fails_closed_on_ambiguous_table_target(monkeypatch):
    module = _reload_server(monkeypatch)
    policy = module.ConnectionPolicy(
        allow_union=False,
        allowed_tables=frozenset({"orders"}),
    )

    is_safe, error = module._validate_sql_query_policy(
        "SELECT * FROM json_each('[1, 2]')", policy
    )

    assert is_safe is False
    assert error == "Table allowlist could not safely determine every referenced table"

    is_safe, error = module._validate_sql_query_policy(
        "SELECT * FROM json_each('[1, 2]') AS item", policy
    )
    assert is_safe is False
    assert error == "Table allowlist could not safely determine every referenced table"


def test_skills_dir_sibling_prefix_is_rejected(monkeypatch):
    """SKILLS_DIR must be inside project root, not just string-prefix similar."""
    project_root = Path(__file__).resolve().parents[1]
    sibling = project_root.parent / f"{project_root.name}-sibling-prefix-test"
    assert str(sibling).startswith(str(project_root))

    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", str(sibling))
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", ":memory:")
    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)

    try:
        module = importlib.import_module("mcp_sql_server")
        assert module._is_path_within(sibling, project_root) is False
        assert module.SKILLS_ENABLED is False
    finally:
        for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(module_name, None)
