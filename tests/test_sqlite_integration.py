"""
SQLite Integration Tests

End-to-end tests for SQLite database operations through the full stack:
- sql_safety_checker.execute_sql()
- Database adapter methods
- MCP tool simulation (without actual MCP server)

These tests verify that:
1. SQLite databases work correctly with the MCP SQL Server codebase
2. All read-only operations function as expected
3. Safety checks work for SQLite dialect
4. Timeout mechanism functions correctly

Usage:
    pytest tests/test_sqlite_integration.py -v
"""

import os
import sqlite3
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# =============================================================================
# SQL Safety Checker Integration Tests
# =============================================================================

class TestSQLiteSafetyChecker:
    """Integration tests for sql_safety_checker with SQLite."""
    
    def test_execute_sql_select(self, sqlite_test_db, reset_global_adapter):
        """Test execute_sql with SELECT query."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("SELECT * FROM users ORDER BY id")
            
            assert not isinstance(result, str)  # Not an error
            assert len(result) == 3
            
            db_adapter.reset_adapter()
    
    def test_execute_sql_with_limit(self, sqlite_test_db, reset_global_adapter):
        """Test execute_sql with LIMIT clause."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("SELECT * FROM users LIMIT 1")
            
            assert not isinstance(result, str)
            assert len(result) == 1
            
            db_adapter.reset_adapter()
    
    def test_execute_sql_blocks_delete(self, sqlite_test_db, reset_global_adapter):
        """Test that DELETE queries are blocked."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("DELETE FROM users WHERE id = 1")
            
            assert isinstance(result, str)
            assert "Error:" in result
            assert "read-only" in result.lower()
            
            db_adapter.reset_adapter()
    
    def test_execute_sql_blocks_insert(self, sqlite_test_db, reset_global_adapter):
        """Test that INSERT queries are blocked."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("INSERT INTO users (name) VALUES ('Hacker')")
            
            assert isinstance(result, str)
            assert "Error:" in result
            
            db_adapter.reset_adapter()
    
    def test_execute_sql_blocks_update(self, sqlite_test_db, reset_global_adapter):
        """Test that UPDATE queries are blocked."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("UPDATE users SET name = 'Hacked' WHERE id = 1")
            
            assert isinstance(result, str)
            assert "Error:" in result
            
            db_adapter.reset_adapter()
    
    def test_execute_sql_blocks_drop(self, sqlite_test_db, reset_global_adapter):
        """Test that DROP queries are blocked."""
        with patch.dict(os.environ, {
            "DB_TYPE": "sqlite",
            "SQLITE_DATABASE_PATH": sqlite_test_db,
        }):
            import importlib
            import db_adapter
            import sql_safety_checker
            importlib.reload(db_adapter)
            importlib.reload(sql_safety_checker)
            
            result = sql_safety_checker.execute_sql("DROP TABLE users")
            
            assert isinstance(result, str)
            assert "Error:" in result
            
            db_adapter.reset_adapter()


class TestSQLiteSafetyCheckerQueries:
    """Test various query types with SQLite."""
    
    def test_is_sql_safe_select(self):
        """Test that SELECT is considered safe."""
        from sql_safety_checker import is_sql_safe
        
        assert is_sql_safe("SELECT * FROM users") is True
        assert is_sql_safe("SELECT id, name FROM users WHERE id = 1") is True
        assert is_sql_safe("SELECT COUNT(*) FROM users") is True
    
    def test_is_sql_safe_show_describe(self):
        """Test that SHOW/DESCRIBE are considered safe."""
        from sql_safety_checker import is_sql_safe
        
        # Note: These won't actually work on SQLite, but safety check passes
        assert is_sql_safe("SHOW TABLES") is True
        assert is_sql_safe("DESCRIBE users") is True
        assert is_sql_safe("EXPLAIN SELECT * FROM users") is True
    
    def test_is_sql_safe_dangerous_queries(self):
        """Test that dangerous queries are blocked."""
        from sql_safety_checker import is_sql_safe
        
        assert is_sql_safe("DELETE FROM users") is False
        assert is_sql_safe("INSERT INTO users VALUES (1, 'test')") is False
        assert is_sql_safe("UPDATE users SET name = 'hacked'") is False
        assert is_sql_safe("DROP TABLE users") is False
        assert is_sql_safe("TRUNCATE TABLE users") is False
        assert is_sql_safe("ALTER TABLE users ADD COLUMN hack TEXT") is False


# =============================================================================
# Adapter Integration Tests
# =============================================================================

class TestSQLiteAdapterIntegration:
    """Integration tests for SQLite adapter with test data."""
    
    def test_full_workflow(self, sqlite_adapter):
        """Test complete workflow: list tables -> get columns -> query."""
        # Step 1: List tables
        tables = sqlite_adapter.get_tables()
        table_names = [t["table_name"] for t in tables]
        
        assert "users" in table_names
        
        # Step 2: Get columns for users table
        columns = sqlite_adapter.get_columns("users")
        column_names = [c["column_name"] for c in columns]
        
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names
        
        # Step 3: Query the table
        result = sqlite_adapter.execute("SELECT * FROM users WHERE name = 'Alice'")
        
        assert not isinstance(result, str)
        assert len(result) == 1
        assert result[0][1] == "Alice"
    
    def test_join_query(self, sqlite_adapter):
        """Test JOIN query across tables."""
        result = sqlite_adapter.execute("""
            SELECT u.name, p.name as product, o.quantity
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN products p ON o.product_id = p.id
            ORDER BY o.id
        """)
        
        assert not isinstance(result, str)
        assert len(result) == 2
        
        # First order: Alice bought Widget
        assert result[0][0] == "Alice"
        assert result[0][1] == "Widget"
        assert result[0][2] == 2
    
    def test_aggregate_query(self, sqlite_adapter):
        """Test aggregate functions."""
        result = sqlite_adapter.execute("""
            SELECT COUNT(*) as total, AVG(price) as avg_price
            FROM products
        """)
        
        assert not isinstance(result, str)
        assert result[0][0] == 5  # 5 products
        assert result[0][1] == pytest.approx(29.99, rel=0.01)  # Average price
    
    def test_group_by_query(self, sqlite_adapter):
        """Test GROUP BY query."""
        result = sqlite_adapter.execute("""
            SELECT user_id, SUM(quantity) as total_items
            FROM orders
            GROUP BY user_id
            ORDER BY user_id
        """)
        
        assert not isinstance(result, str)
        assert len(result) == 2  # 2 users with orders
        
        # User 1 (Alice) ordered 2 items
        assert result[0][1] == 2


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestSQLiteErrorHandling:
    """Test error handling for SQLite operations."""
    
    def test_nonexistent_table_error(self, sqlite_adapter):
        """Test error message for nonexistent table."""
        result = sqlite_adapter.execute("SELECT * FROM fake_table")
        
        assert isinstance(result, str)
        assert "Error:" in result
        assert "not found" in result.lower()
    
    def test_syntax_error(self, sqlite_adapter):
        """Test error message for SQL syntax error."""
        result = sqlite_adapter.execute("SELCT * FROM users")  # Typo
        
        assert isinstance(result, str)
        assert "Error:" in result
    
    def test_column_not_found_error(self, sqlite_adapter):
        """Test error for nonexistent column."""
        result = sqlite_adapter.execute("SELECT fake_column FROM users")
        
        assert isinstance(result, str)
        assert "Error:" in result


# =============================================================================
# SQLite-Specific Feature Tests
# =============================================================================

class TestSQLiteSpecificFeatures:
    """Test SQLite-specific behaviors and limitations."""
    
    def test_pragma_query_blocked(self, sqlite_adapter):
        """
        Test that PRAGMA queries are blocked by safety checker.
        
        Note: PRAGMA is SQLite-specific and could be dangerous (e.g., PRAGMA writable_schema).
        The safety checker should block it as it's not in SAFE_SQL_TYPES.
        """
        from sql_safety_checker import is_sql_safe
        
        # PRAGMA should be blocked (not in SAFE_SQL_TYPES)
        assert is_sql_safe("PRAGMA table_info(users)") is False
    
    def test_sqlite_functions(self, sqlite_adapter):
        """Test SQLite built-in functions."""
        result = sqlite_adapter.execute("""
            SELECT 
                sqlite_version() as version,
                typeof(1) as int_type,
                typeof('text') as text_type
        """)
        
        assert not isinstance(result, str)
        assert len(result) == 1
        # Should have SQLite version
        assert result[0][0] is not None
        assert result[0][1] == "integer"
        assert result[0][2] == "text"
    
    def test_case_insensitive_like(self, sqlite_adapter):
        """Test case-insensitive LIKE (SQLite default)."""
        result = sqlite_adapter.execute("""
            SELECT name FROM users WHERE name LIKE 'alice'
        """)
        
        assert not isinstance(result, str)
        # SQLite LIKE is case-insensitive by default for ASCII
        assert len(result) == 1
        assert result[0][0] == "Alice"
    
    def test_null_handling(self, sqlite_adapter):
        """Test NULL handling in queries."""
        result = sqlite_adapter.execute("""
            SELECT 
                NULL IS NULL as is_null,
                COALESCE(NULL, 'default') as coalesced
        """)
        
        assert not isinstance(result, str)
        assert result[0][0] == 1  # TRUE in SQLite
        assert result[0][1] == "default"


# =============================================================================
# Column Type Mapping Tests
# =============================================================================

class TestSQLiteColumnTypes:
    """Test SQLite column type handling."""
    
    def test_get_columns_returns_types(self, sqlite_adapter):
        """Test that get_columns returns correct type information."""
        columns = sqlite_adapter.get_columns("products")
        
        id_col = next(c for c in columns if c["column_name"] == "id")
        name_col = next(c for c in columns if c["column_name"] == "name")
        price_col = next(c for c in columns if c["column_name"] == "price")
        
        assert "INTEGER" in id_col["data_type"].upper()
        assert "TEXT" in name_col["data_type"].upper()
        assert "REAL" in price_col["data_type"].upper()
    
    def test_get_columns_returns_nullable(self, sqlite_adapter):
        """Test that get_columns returns nullable information."""
        columns = sqlite_adapter.get_columns("users")
        
        # id has AUTOINCREMENT, name has NOT NULL, email has UNIQUE (nullable)
        name_col = next(c for c in columns if c["column_name"] == "name")
        email_col = next(c for c in columns if c["column_name"] == "email")
        
        assert name_col["nullable"] == "NO"  # NOT NULL
        assert email_col["nullable"] == "YES"  # Nullable (only UNIQUE, not NOT NULL)


# =============================================================================
# Row Count Estimation Tests
# =============================================================================

class TestSQLiteRowCountEstimation:
    """Test row count estimation strategies."""
    
    def test_small_table_exact_count(self, sqlite_adapter):
        """Test that small tables get exact count."""
        count = sqlite_adapter.get_row_estimate("users")
        
        assert count == 3  # Exact count
    
    def test_empty_table_returns_zero(self, sqlite_test_db):
        """Test that empty table returns 0."""
        # Create an empty table
        conn = sqlite3.connect(sqlite_test_db)
        conn.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY)")
        conn.close()
        
        from db_adapter import SQLiteAdapter
        adapter = SQLiteAdapter(sqlite_test_db)
        adapter.connect()
        
        count = adapter.get_row_estimate("empty_table")
        
        assert count == 0
        
        adapter.close()
