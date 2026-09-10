"""
Unit Tests for Database Adapters

Tests for:
- SQLiteAdapter: Connection, queries, metadata, timeout
- MySQLAdapter: Basic connection and query (if MySQL is available)
- Factory function: create_adapter() with different DB_TYPE values

Test Categories:
- Unit tests: Mock database interactions
- Integration tests: Real database queries (SQLite always, MySQL if configured)

Usage:
    pytest tests/test_db_adapter.py -v
"""

import os
import sys
import time
import logging
import sqlite3
import importlib
from typing import cast

import pytest
from sqlalchemy.engine import Engine
from unittest.mock import patch, MagicMock


# =============================================================================
# SQLiteAdapter Tests
# =============================================================================

class TestSQLiteAdapter:
    """Unit tests for SQLiteAdapter class."""
    
    def test_db_type_property(self, sqlite_adapter):
        """Test that db_type returns 'sqlite'."""
        assert sqlite_adapter.db_type == "sqlite"
    
    def test_connect_success(self, sqlite_test_db):
        """Test successful connection to SQLite database."""
        from db_adapter import SQLiteAdapter
        
        adapter = SQLiteAdapter(sqlite_test_db)
        result = adapter.connect()
        
        assert result is True
        assert adapter._engine is not None
        
        adapter.close()
    
    def test_connect_memory_database(self):
        """Test connection to in-memory SQLite database."""
        from db_adapter import SQLiteAdapter
        
        adapter = SQLiteAdapter(":memory:")
        result = adapter.connect()
        
        assert result is True
        assert adapter._engine is not None
        
        adapter.close()
    
    def test_execute_simple_query(self, sqlite_adapter):
        """Test executing a simple SELECT query."""
        result = sqlite_adapter.execute("SELECT 1 as test")
        
        assert not isinstance(result, str)  # Not an error string
        assert len(result) == 1
        assert result[0][0] == 1
    
    def test_execute_select_from_table(self, sqlite_adapter):
        """Test executing SELECT from test table."""
        result = sqlite_adapter.execute("SELECT * FROM users ORDER BY id")
        
        assert not isinstance(result, str)
        assert len(result) == 3
        # Check first user
        assert result[0][1] == "Alice"
        assert result[0][2] == "alice@example.com"
    
    def test_execute_with_error(self, sqlite_adapter):
        """Test that errors return sanitized error strings."""
        result = sqlite_adapter.execute("SELECT * FROM nonexistent_table")
        
        assert isinstance(result, str)
        assert result.startswith("Error:")
        assert "Table or column not found" in result

    def test_handle_error_logs_exception_class_not_values(self, caplog):
        """Adapter logs should not include SQL text or bound parameter values."""
        from db_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(":memory:")
        with caplog.at_level(logging.WARNING):
            result = adapter._handle_error(
                Exception("SELECT * FROM users WHERE token='super-secret-token'")
            )

        assert result == "Error: Database query failed"
        assert "Exception" in caplog.text
        assert "super-secret-token" not in caplog.text
        assert "SELECT * FROM users" not in caplog.text
    
    def test_execute_syntax_error(self, sqlite_adapter):
        """Test that syntax errors return appropriate message."""
        result = sqlite_adapter.execute("SLECT * FROM users")  # Typo
        
        assert isinstance(result, str)
        assert result.startswith("Error:")
    
    def test_get_tables(self, sqlite_adapter):
        """Test getting list of tables."""
        tables = sqlite_adapter.get_tables()
        
        assert len(tables) == 3
        table_names = [t["table_name"] for t in tables]
        assert "users" in table_names
        assert "products" in table_names
        assert "orders" in table_names
    
    def test_get_tables_excludes_sqlite_internal(self, sqlite_adapter):
        """Test that sqlite_* internal tables are excluded."""
        tables = sqlite_adapter.get_tables()
        
        table_names = [t["table_name"] for t in tables]
        for name in table_names:
            assert not name.startswith("sqlite_")

    def test_get_tables_marks_unsupported_identifier_row_count_unknown(
        self,
        sqlite_adapter,
    ):
        """An unavailable estimate must not be reported as an empty table."""
        sqlite_adapter.execute_write(
            'CREATE TABLE "odd-name" (id INTEGER PRIMARY KEY)',
            {},
        )

        tables = sqlite_adapter.get_tables()

        odd_table = next(
            table for table in tables if table["table_name"] == "odd-name"
        )
        assert odd_table["row_count"] is None

    def test_sqlite_metadata_query_errors_are_not_reported_as_empty(self, monkeypatch):
        """Database failures must remain distinct from valid empty metadata."""
        from db_adapter import MetadataQueryError, SQLiteAdapter

        adapter = SQLiteAdapter(":memory:")
        monkeypatch.setattr(
            adapter,
            "execute",
            lambda *_a, **_k: "Error: Database query failed",
        )

        with pytest.raises(MetadataQueryError, match="listing tables"):
            adapter.get_tables()
        with pytest.raises(MetadataQueryError, match="reading table columns"):
            adapter.get_columns("users")
        with pytest.raises(MetadataQueryError, match="estimating table rows"):
            adapter.get_row_estimate("users")
    
    def test_get_columns(self, sqlite_adapter):
        """Test getting column information for a table."""
        columns = sqlite_adapter.get_columns("users")
        
        assert len(columns) == 3
        
        column_names = [c["column_name"] for c in columns]
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names
        
        # Check id column is primary key
        id_col = next(c for c in columns if c["column_name"] == "id")
        assert id_col["key_type"] == "PRI"
    
    def test_get_columns_nonexistent_table(self, sqlite_adapter):
        """Test that get_columns returns empty list for nonexistent table."""
        columns = sqlite_adapter.get_columns("nonexistent_table")
        
        assert columns == []

    def test_metadata_rejects_invalid_table_identifiers_without_execute(self, monkeypatch):
        """Adapter metadata methods should fail closed before SQL construction."""
        from db_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(":memory:")

        def fail_execute(*args, **kwargs):
            pytest.fail("Invalid metadata identifier should not reach execute()")

        monkeypatch.setattr(adapter, "execute", fail_execute)

        invalid_names = ["users) --", "main.users", "`users`", '"users"']
        for table_name in invalid_names:
            assert adapter.get_columns(table_name) == []
            assert adapter.get_row_estimate(table_name) is None

    def test_row_estimate_quotes_sqlite_identifier_for_bounded_sample(self, monkeypatch):
        """Valid SQLite metadata identifiers are quoted before use as identifiers."""
        from db_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(":memory:")
        calls = []

        def fake_execute(sql, timeout=None, params=None):
            calls.append((sql, params))
            if "sqlite_master" in sql:
                return []
            if "COUNT(*)" in sql:
                return [(3,)]
            return []

        monkeypatch.setattr(adapter, "execute", fake_execute)

        assert adapter.get_row_estimate("users") == 3
        assert 'FROM "users" LIMIT 10000' in calls[-1][0]
    
    def test_get_row_estimate(self, sqlite_adapter):
        """Test getting row count estimate."""
        row_count = sqlite_adapter.get_row_estimate("users")
        
        # Should be exact for small tables
        assert row_count == 3
    
    def test_get_row_estimate_products(self, sqlite_adapter):
        """Test row count for products table."""
        row_count = sqlite_adapter.get_row_estimate("products")
        
        assert row_count == 5
    
    def test_get_row_estimate_nonexistent_table(self, sqlite_adapter):
        """Test that a nonexistent table has no row estimate."""
        row_count = sqlite_adapter.get_row_estimate("nonexistent_table")
        
        assert row_count is None

    def test_get_row_estimate_returns_unknown_when_table_disappears(self, monkeypatch):
        """A table dropped after discovery must not be reported as empty."""
        from db_adapter import SQLiteAdapter

        adapter = SQLiteAdapter(":memory:")

        def fake_execute(sql, timeout=None, params=None):
            if "sqlite_master" in sql:
                return []
            if "COUNT(*)" in sql:
                return "Error: Table or column not found"
            return []

        monkeypatch.setattr(adapter, "execute", fake_execute)

        assert adapter.get_row_estimate("vanished_table") is None
    
    def test_check_connection_success(self, sqlite_adapter):
        """Test connection check returns success."""
        success, message = sqlite_adapter.check_connection()
        
        assert success is True
        assert "successful" in message.lower()
    
    def test_get_database_name(self, sqlite_test_db, sqlite_adapter):
        """Test getting database name (file path for SQLite)."""
        db_name = sqlite_adapter.get_database_name()
        
        assert db_name == sqlite_test_db
    
    def test_get_database_name_memory(self):
        """Test getting database name for in-memory database."""
        from db_adapter import SQLiteAdapter
        
        adapter = SQLiteAdapter(":memory:")
        adapter.connect()
        
        assert adapter.get_database_name() == ":memory:"
        
        adapter.close()
    
    def test_close_clears_engine(self, sqlite_test_db):
        """Test that close() disposes engine."""
        from db_adapter import SQLiteAdapter
        
        adapter = SQLiteAdapter(sqlite_test_db)
        adapter.connect()
        assert adapter._engine is not None
        
        adapter.close()
        assert adapter._engine is None


class TestSQLiteAdapterTimeout:
    """Tests for SQLite query timeout functionality."""
    
    def test_timeout_short_query_completes(self, sqlite_memory_adapter):
        """Test that short queries complete within timeout."""
        result = sqlite_memory_adapter.execute("SELECT 1", timeout=5)
        
        assert not isinstance(result, str)
        assert result[0][0] == 1
    
    def test_timeout_parameter_accepted(self, sqlite_memory_adapter):
        """Test that timeout parameter is accepted."""
        # Just verify no error is raised
        result = sqlite_memory_adapter.execute("SELECT * FROM test_table", timeout=10)
        
        assert not isinstance(result, str)

    def test_timeout_interrupted_query_returns_timeout_error(self, sqlite_memory_adapter):
        """Interrupted SQLite queries should be reported as timeout errors."""
        result = sqlite_memory_adapter.execute(
            """
            WITH RECURSIVE counter(value) AS (
                SELECT 1
                UNION ALL
                SELECT value + 1 FROM counter WHERE value < 10000000
            )
            SELECT max(value) FROM counter
            """,
            timeout=0,
        )

        assert result == "Error: Query timeout exceeded (0s limit)"


class TestSQLiteAdapterLargeTable:
    """Tests for SQLite row count estimation with large tables."""
    
    def test_large_table_row_count_uses_bounded_sample(self, sqlite_large_table_db, monkeypatch):
        """Large tables without sqlite_stat1 return the sample cap, not COUNT(*)."""
        from db_adapter import SQLiteAdapter
        
        adapter = SQLiteAdapter(sqlite_large_table_db)
        adapter.connect()

        original_execute = adapter.execute
        executed_sql = []

        def execute_spy(sql, timeout=None, params=None):
            normalized_sql = " ".join(sql.split()).lower()
            executed_sql.append(normalized_sql)
            assert normalized_sql != "select count(*) from large_table"
            return original_execute(sql, timeout=timeout, params=params)

        monkeypatch.setattr(adapter, "execute", execute_spy)
        
        row_count = adapter.get_row_estimate("large_table")
        
        assert row_count == 10000
        assert any("limit 10000" in sql for sql in executed_sql)
        
        adapter.close()

    def test_large_table_row_count_prefers_sqlite_stat1(self, sqlite_large_table_db):
        """When ANALYZE has populated sqlite_stat1, use its estimate first."""
        import sqlite3
        from db_adapter import SQLiteAdapter

        conn = sqlite3.connect(sqlite_large_table_db)
        conn.execute("ANALYZE")
        conn.close()

        adapter = SQLiteAdapter(sqlite_large_table_db)
        adapter.connect()

        row_count = adapter.get_row_estimate("large_table")

        assert row_count == 15000

        adapter.close()


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateAdapter:
    """Tests for create_adapter() factory function."""
    
    def test_create_sqlite_adapter(self, sqlite_test_db, reset_global_adapter):
        """Test creating SQLite adapter via factory."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            from db_adapter import create_adapter
            
            # Need to reimport to pick up new env vars
            import importlib
            import db_adapter
            importlib.reload(db_adapter)
            
            adapter = db_adapter.create_adapter("sqlite")
            
            assert adapter.db_type == "sqlite"
            adapter.close()
    
    def test_create_adapter_with_override(self, sqlite_test_db, reset_global_adapter):
        """Test that db_type parameter overrides environment variable."""
        with patch.dict(os.environ, {
            "DB_TYPE": "mysql",  # Env says mysql
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            from db_adapter import create_adapter, SQLiteAdapter
            
            # Force SQLite despite env
            adapter = create_adapter("sqlite")
            
            assert isinstance(adapter, SQLiteAdapter)
            adapter.close()
    
    def test_create_adapter_invalid_type(self, reset_global_adapter):
        """Test that invalid db_type raises ValueError."""
        from db_adapter import create_adapter
        
        with pytest.raises(ValueError) as exc_info:
            create_adapter("postgresql")  # Not yet supported
        
        assert "Unsupported database type" in str(exc_info.value)
        assert "postgresql" in str(exc_info.value)


# =============================================================================
# Global Adapter Tests
# =============================================================================

class TestGlobalAdapter:
    """Tests for global adapter management functions."""
    
    def test_get_adapter_creates_singleton(self, sqlite_test_db, reset_global_adapter):
        """Test that get_adapter returns same instance."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            importlib.reload(db_adapter)
            
            adapter1 = db_adapter.get_adapter()
            adapter2 = db_adapter.get_adapter()
            
            assert adapter1 is adapter2
            
            db_adapter.reset_adapter()

    def test_legacy_mode_ignores_default_connection_env(
        self, sqlite_test_db, monkeypatch, reset_global_adapter
    ):
        """DB_DEFAULT_* vars are inactive unless DB_CONNECTIONS is enabled."""
        monkeypatch.setenv("DB_CONNECTIONS", "")
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("SQLITE_DATABASE_PATH", sqlite_test_db)
        monkeypatch.setenv("DB_DEFAULT_TYPE", "mysql")
        monkeypatch.setenv("DB_DEFAULT_HOST", "ignored.example")
        monkeypatch.setenv("DB_DEFAULT_NAME", "ignored")

        sys.modules.pop("sql_safety_checker", None)
        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            assert db_adapter.get_default_connection_id() == "default"
            assert db_adapter.get_connection_config().db_type == "sqlite"
            adapter = db_adapter.get_adapter()
            assert adapter.db_type == "sqlite"
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)

    def test_legacy_mode_ignores_default_connection_selection(
        self, sqlite_test_db, monkeypatch, reset_global_adapter
    ):
        """DEFAULT_DB_CONNECTION is inactive unless DB_CONNECTIONS is enabled."""
        monkeypatch.setenv("DB_CONNECTIONS", "")
        monkeypatch.setenv("DEFAULT_DB_CONNECTION", "analytics")
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("SQLITE_DATABASE_PATH", sqlite_test_db)

        sys.modules.pop("sql_safety_checker", None)
        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            assert db_adapter.get_default_connection_id() == "default"
            assert db_adapter.get_connection_config().db_type == "sqlite"
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)

    def test_named_sqlite_connections_are_isolated(self, tmp_path, monkeypatch):
        """v3.5: registry keeps two configured SQLite connections separate."""
        default_db = tmp_path / "default.db"
        analytics_db = tmp_path / "analytics.db"

        for db_path, label in ((default_db, "default-row"), (analytics_db, "analytics-row")):
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
            conn.execute("INSERT INTO items (label) VALUES (?)", (label,))
            conn.commit()
            conn.close()

        monkeypatch.setenv("DB_CONNECTIONS", "default,analytics")
        monkeypatch.setenv("DEFAULT_DB_CONNECTION", "default")
        monkeypatch.setenv("DB_DEFAULT_TYPE", "sqlite")
        monkeypatch.setenv("DB_DEFAULT_SQLITE_DATABASE_PATH", str(default_db))
        monkeypatch.setenv("DB_ANALYTICS_TYPE", "sqlite")
        monkeypatch.setenv("DB_ANALYTICS_SQLITE_DATABASE_PATH", str(analytics_db))

        sys.modules.pop("sql_safety_checker", None)
        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            default_adapter = db_adapter.get_adapter()
            analytics_adapter = db_adapter.get_adapter("analytics")

            assert default_adapter is db_adapter.get_adapter("default")
            assert analytics_adapter is not default_adapter
            assert db_adapter.get_default_connection_id() == "default"
            assert [c.connection_id for c in db_adapter.list_connection_configs()] == [
                "default",
                "analytics",
            ]

            default_rows = default_adapter.execute("SELECT label FROM items")
            analytics_rows = analytics_adapter.execute("SELECT label FROM items")

            assert not isinstance(default_rows, str)
            assert not isinstance(analytics_rows, str)
            assert default_rows[0].label == "default-row"
            assert analytics_rows[0].label == "analytics-row"

            db_adapter.reset_adapter("analytics")
            assert db_adapter.get_adapter("default") is default_adapter
            assert db_adapter.get_adapter("analytics") is not analytics_adapter
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)

    def test_named_connections_parse_mutation_policy(self, tmp_path, monkeypatch):
        """v3.6: write policy is explicit and scoped to each named connection."""
        mysql_db = tmp_path / "mysql.db"
        analytics_db = tmp_path / "analytics.db"
        monkeypatch.setenv("DB_CONNECTIONS", "mysql,analytics")
        monkeypatch.setenv("DEFAULT_DB_CONNECTION", "mysql")
        monkeypatch.setenv("DB_MYSQL_TYPE", "sqlite")
        monkeypatch.setenv("DB_MYSQL_SQLITE_DATABASE_PATH", str(mysql_db))
        monkeypatch.setenv("DB_MYSQL_ALLOW_MUTATIONS", "0")
        monkeypatch.setenv("DB_MYSQL_MUTATION_SKILLS", "")
        monkeypatch.setenv("DB_ANALYTICS_TYPE", "sqlite")
        monkeypatch.setenv(
            "DB_ANALYTICS_SQLITE_DATABASE_PATH",
            str(analytics_db),
        )
        monkeypatch.setenv("DB_ANALYTICS_ALLOW_MUTATIONS", "1")
        monkeypatch.setenv(
            "DB_ANALYTICS_MUTATION_SKILLS",
            "update-order-status,close-ticket",
        )

        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            mysql_policy = db_adapter.get_connection_config("mysql").policy
            analytics_policy = db_adapter.get_connection_config("analytics").policy

            assert mysql_policy.allow_mutations is False
            assert mysql_policy.mutation_skills == frozenset()
            assert analytics_policy.allow_mutations is True
            assert analytics_policy.mutation_skills == frozenset(
                {"update-order-status", "close-ticket"}
            )
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)

    def test_legacy_mode_ignores_named_mutation_policy(
        self,
        sqlite_test_db,
        monkeypatch,
    ):
        """Named mutation policy cannot leak into legacy single-connection mode."""
        monkeypatch.setenv("DB_CONNECTIONS", "")
        monkeypatch.setenv("DB_TYPE", "sqlite")
        monkeypatch.setenv("SQLITE_DATABASE_PATH", sqlite_test_db)
        monkeypatch.setenv("DB_DEFAULT_ALLOW_MUTATIONS", "1")
        monkeypatch.setenv("DB_DEFAULT_MUTATION_SKILLS", "*")

        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            policy = db_adapter.get_connection_config().policy
            assert policy.allow_mutations is False
            assert policy.mutation_skills == frozenset()
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)

    def test_unknown_connection_id_fails_closed(self, sqlite_test_db, monkeypatch):
        """Unknown ids must not fall back to the default connection."""
        monkeypatch.setenv("DB_CONNECTIONS", "default")
        monkeypatch.setenv("DEFAULT_DB_CONNECTION", "default")
        monkeypatch.setenv("DB_DEFAULT_TYPE", "sqlite")
        monkeypatch.setenv("DB_DEFAULT_SQLITE_DATABASE_PATH", sqlite_test_db)

        import db_adapter
        db_adapter = importlib.reload(db_adapter)

        try:
            with pytest.raises(ValueError, match="Unknown connection_id"):
                db_adapter.get_adapter("missing")
        finally:
            db_adapter.reset_adapter()
            sys.modules.pop("db_adapter", None)
            sys.modules.pop("sql_safety_checker", None)
    
    def test_reset_adapter_clears_instance(self, sqlite_test_db, reset_global_adapter):
        """Test that reset_adapter clears the global instance."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            importlib.reload(db_adapter)
            
            adapter1 = db_adapter.get_adapter()
            db_adapter.reset_adapter()
            adapter2 = db_adapter.get_adapter()
            
            # Should be different instances
            assert adapter1 is not adapter2
            
            db_adapter.reset_adapter()


# =============================================================================
# MySQL Adapter Tests (Optional - run only if MySQL is configured)
# =============================================================================

class TestMySQLAdapter:
    """
    Integration tests for MySQLAdapter.
    
    These tests require a running MySQL server and proper .env configuration.
    Tests are skipped if MySQL environment variables are not set.
    """

    def test_mysql_connect_uses_structured_url_and_hides_parameters(self, monkeypatch):
        """Special characters in credentials should be preserved, not f-string parsed."""
        import sqlalchemy
        import db_adapter
        from sqlalchemy.engine import URL

        captured = {}

        class DummyEngine:
            def dispose(self):
                pass

        def fake_create_engine(database_url, **kwargs):
            captured["database_url"] = database_url
            captured["kwargs"] = kwargs
            return DummyEngine()

        monkeypatch.setattr(sqlalchemy, "create_engine", fake_create_engine)
        monkeypatch.setattr(db_adapter, "DB_USER", "report_user")
        monkeypatch.setattr(db_adapter, "DB_PASSWORD", "p@ss:word/with@chars")
        monkeypatch.setattr(db_adapter, "DB_HOST", "db.example.test")
        monkeypatch.setattr(db_adapter, "DB_NAME", "analytics")

        adapter = db_adapter.MySQLAdapter()

        assert adapter.connect() is True
        assert isinstance(captured["database_url"], URL)
        assert captured["database_url"].password == "p@ss:word/with@chars"
        assert captured["database_url"].drivername == "mysql+pymysql"
        assert captured["kwargs"]["hide_parameters"] is True
        assert captured["kwargs"]["logging_name"] == "mysql_adapter"

    def test_mysql_handle_error_logs_exception_class_not_values(self, caplog):
        """MySQL adapter error logging should not leak SQL or parameter values."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        with caplog.at_level(logging.WARNING):
            result = adapter._handle_error(
                Exception("SELECT * FROM users WHERE token='super-secret-token'")
            )

        assert result == "Error: Database query failed"
        assert "Exception" in caplog.text
        assert "super-secret-token" not in caplog.text
        assert "SELECT * FROM users" not in caplog.text

    def test_mysql_metadata_uses_bound_table_name(self, monkeypatch):
        """INFORMATION_SCHEMA metadata predicates should bind table names."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        calls = []

        def fake_execute(sql, timeout=None, params=None):
            calls.append((sql, params))
            if "INFORMATION_SCHEMA.COLUMNS" in sql:
                return [("id", "int", "NO", "PRI", None)]
            return [(7,)]

        monkeypatch.setattr(adapter, "execute", fake_execute)

        columns = adapter.get_columns("users")
        row_count = adapter.get_row_estimate("users")

        assert columns[0]["column_name"] == "id"
        assert row_count == 7
        assert calls[0][1] == {"table_name": "users"}
        assert calls[1][1] == {"table_name": "users"}
        assert "TABLE_NAME = :table_name" in calls[0][0]
        assert "TABLE_NAME = 'users'" not in calls[0][0]

    def test_mysql_metadata_query_errors_are_not_reported_as_empty(self, monkeypatch):
        """Database failures must remain distinct from valid empty metadata."""
        from db_adapter import MetadataQueryError, MySQLAdapter

        adapter = MySQLAdapter()
        monkeypatch.setattr(
            adapter,
            "execute",
            lambda *_a, **_k: "Error: Database query failed",
        )

        with pytest.raises(MetadataQueryError, match="listing tables"):
            adapter.get_tables()
        with pytest.raises(MetadataQueryError, match="reading table columns"):
            adapter.get_columns("users")
        with pytest.raises(MetadataQueryError, match="estimating table rows"):
            adapter.get_row_estimate("users")

    def test_mysql_get_tables_preserves_unknown_row_estimate(self, monkeypatch):
        """A NULL INFORMATION_SCHEMA estimate must remain unknown, not zero."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        monkeypatch.setattr(
            adapter,
            "execute",
            lambda *_a, **_k: [("unknown_rows", None), ("empty_table", 0)],
        )

        assert adapter.get_tables() == [
            {"table_name": "unknown_rows", "row_count": None},
            {"table_name": "empty_table", "row_count": 0},
        ]

    def test_mysql_get_row_estimate_preserves_unknown_value(self, monkeypatch):
        """A single-table NULL estimate must remain distinct from zero."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        monkeypatch.setattr(adapter, "execute", lambda *_a, **_k: [(None,)])

        assert adapter.get_row_estimate("unknown_rows") is None

    def test_mysql_get_row_estimate_returns_unknown_for_missing_table(self, monkeypatch):
        """An absent INFORMATION_SCHEMA row is not a zero-row estimate."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        monkeypatch.setattr(adapter, "execute", lambda *_a, **_k: [])

        assert adapter.get_row_estimate("missing_table") is None

    def test_mysql_metadata_rejects_invalid_table_identifiers_without_execute(self, monkeypatch):
        """Invalid MySQL metadata table names should not reach execute()."""
        from db_adapter import MySQLAdapter

        adapter = MySQLAdapter()

        def fail_execute(*args, **kwargs):
            pytest.fail("Invalid metadata identifier should not reach execute()")

        monkeypatch.setattr(adapter, "execute", fail_execute)

        invalid_names = ["users' OR '1'='1", "main.users", "`users`", "users) --"]
        for table_name in invalid_names:
            assert adapter.get_columns(table_name) == []
            assert adapter.get_row_estimate(table_name) is None

    def test_mysql_execute_write_sets_lock_wait_timeout_not_max_execution_time(self):
        """MySQL writes should configure InnoDB lock waits, not SELECT timeout."""
        from db_adapter import MySQLAdapter

        class DummyResult:
            rowcount = 2

        class DummyConnection:
            def __init__(self):
                self.calls = []
                self.transaction = MagicMock()

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                return DummyResult()

            def begin(self):
                return self.transaction

            def close(self):
                pass

        class DummyEngine:
            def __init__(self, connection):
                self.connection = connection

            def connect(self):
                return self.connection

        connection = DummyConnection()
        adapter = MySQLAdapter()
        adapter._engine = cast(Engine, DummyEngine(connection))

        result = adapter.execute_write(
            "UPDATE orders SET status = :status WHERE id = :id",
            {"status": "shipped", "id": 7},
            timeout=3,
        )

        assert result == {"success": True, "rowcount": 2}
        connection.transaction.commit.assert_called_once_with()
        assert connection.calls == [
            (
                "SET SESSION innodb_lock_wait_timeout = :timeout_seconds",
                {"timeout_seconds": 3},
            ),
            (
                "UPDATE orders SET status = :status WHERE id = :id",
                {"status": "shipped", "id": 7},
            ),
        ]
        assert all(
            "MAX_EXECUTION_TIME" not in statement
            for statement, _params in connection.calls
        )

    def test_mysql_execute_write_clamps_lock_wait_timeout_to_mysql_minimum(self):
        """MySQL innodb_lock_wait_timeout has a minimum session value of 1."""
        from db_adapter import MySQLAdapter

        class DummyResult:
            rowcount = 1

        class DummyConnection:
            def __init__(self):
                self.calls = []
                self.transaction = MagicMock()

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                return DummyResult()

            def begin(self):
                return self.transaction

            def close(self):
                pass

        class DummyEngine:
            def __init__(self, connection):
                self.connection = connection

            def connect(self):
                return self.connection

        connection = DummyConnection()
        adapter = MySQLAdapter()
        adapter._engine = cast(Engine, DummyEngine(connection))

        adapter.execute_write(
            "UPDATE orders SET status = :status",
            {"status": "new"},
            timeout=0,
        )

        assert connection.calls[0] == (
            "SET SESSION innodb_lock_wait_timeout = :timeout_seconds",
            {"timeout_seconds": 1},
        )

    def test_mysql_expected_rowcount_mismatch_rolls_back_before_commit(self):
        """The shared exact-row contract must also hold on the MySQL path."""
        from db_adapter import (
            ExpectedRowcountMismatchError,
            MySQLAdapter,
            WriteExecutionOutcome,
        )

        class DummyResult:
            rowcount = 2

        class DummyConnection:
            def __init__(self):
                self.transaction = MagicMock()
                self.transaction.is_active = True
                self.closed = False
                self.invalidated = False
                self.connection = MagicMock()
                self.connection.is_valid = True

            def execute(self, _statement, _params=None):
                return DummyResult()

            def begin(self):
                return self.transaction

            def close(self):
                pass

        class DummyEngine:
            def __init__(self, connection):
                self.connection = connection

            def connect(self):
                return self.connection

        connection = DummyConnection()
        adapter = MySQLAdapter()
        adapter._engine = cast(Engine, DummyEngine(connection))

        with pytest.raises(ExpectedRowcountMismatchError) as raised:
            adapter.execute_write(
                "UPDATE orders SET status = :status",
                {"status": "new"},
                expected_rowcount=1,
            )

        assert raised.value.actual_rowcount == 2
        assert (
            raised.value.execution_outcome
            is WriteExecutionOutcome.ROLLED_BACK
        )
        connection.transaction.rollback.assert_called_once_with()
        connection.transaction.commit.assert_not_called()

    def test_mysql_execute_write_fails_closed_when_lock_wait_timeout_fails(self):
        """Mutation SQL should not run if the lock-wait guard cannot be set."""
        from sqlalchemy.exc import SQLAlchemyError
        from db_adapter import MySQLAdapter

        class DummyConnection:
            def __init__(self):
                self.calls = []
                self.transaction = MagicMock()

            def execute(self, statement, params=None):
                self.calls.append((str(statement), params))
                raise SQLAlchemyError("unsupported session variable")

            def begin(self):
                return self.transaction

            def close(self):
                pass

        class DummyEngine:
            def __init__(self, connection):
                self.connection = connection

            def connect(self):
                return self.connection

        connection = DummyConnection()
        adapter = MySQLAdapter()
        adapter._engine = cast(Engine, DummyEngine(connection))

        from db_adapter import WriteExecutionError, WriteExecutionOutcome

        with pytest.raises(WriteExecutionError) as raised:
            adapter.execute_write(
                "UPDATE orders SET status = :status",
                {"status": "new"},
                timeout=3,
            )
        assert raised.value.execution_outcome is WriteExecutionOutcome.NOT_EXECUTED
        connection.transaction.rollback.assert_called_once_with()

        assert connection.calls == [
            (
                "SET SESSION innodb_lock_wait_timeout = :timeout_seconds",
                {"timeout_seconds": 3},
            )
        ]
    
    def test_mysql_connection(self, mysql_adapter):
        """Test MySQL connection."""
        # mysql_adapter fixture already connects
        success, message = mysql_adapter.check_connection()
        assert success is True
    
    def test_mysql_check_connection(self, mysql_adapter):
        """Test MySQL connection check."""
        success, message = mysql_adapter.check_connection()
        
        assert success is True
        assert "successful" in message.lower()
    
    def test_mysql_db_type(self, mysql_adapter):
        """Test that db_type returns 'mysql'."""
        assert mysql_adapter.db_type == "mysql"
