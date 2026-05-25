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
import time
import pytest
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
        """Test that nonexistent table returns 0."""
        row_count = sqlite_adapter.get_row_estimate("nonexistent_table")
        
        assert row_count == 0
    
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
