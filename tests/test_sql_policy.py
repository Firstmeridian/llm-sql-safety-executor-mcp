"""Regression tests for the shared MCP SQL safety policy."""

import importlib
import shutil
import sys
from pathlib import Path


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


def test_shared_sql_policy_blocks_comment_separated_show(monkeypatch):
    module = _reload_server(monkeypatch)

    is_safe, error = module._validate_sql_query_policy("SHOW/**/VARIABLES")

    assert is_safe is False
    assert error == "This SHOW command is not allowed for security reasons"


def test_shared_sql_policy_blocks_quoted_system_schemas(monkeypatch):
    module = _reload_server(monkeypatch)

    blocked_queries = [
        "SELECT * FROM `information_schema`.`tables`",
        "SELECT * FROM `mysql`.`user`",
        "SELECT * FROM performance_schema.events_statements_summary_by_digest",
    ]

    for sql in blocked_queries:
        is_safe, error = module._validate_sql_query_policy(sql)
        assert is_safe is False
        assert error == (
            "Access to system databases not allowed. "
            "Use list_tables() or describe_table() instead."
        )


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


def test_skills_dir_sibling_prefix_is_rejected(monkeypatch):
    """SKILLS_DIR must be inside project root, not just string-prefix similar."""
    project_root = Path(__file__).resolve().parents[1]
    sibling = project_root.parent / f"{project_root.name}-sibling-prefix-test"
    shutil.rmtree(sibling, ignore_errors=True)
    sibling.mkdir()

    try:
        monkeypatch.setenv("ENABLE_SKILLS", "1")
        monkeypatch.setenv("SKILLS_DIR", str(sibling))
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("SQLITE_DATABASE_PATH", ":memory:")
        for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(module_name, None)

        module = importlib.import_module("mcp_sql_server")

        assert module.SKILLS_ENABLED is False
    finally:
        shutil.rmtree(sibling, ignore_errors=True)
        for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(module_name, None)