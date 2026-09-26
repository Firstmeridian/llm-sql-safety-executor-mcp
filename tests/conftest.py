"""
Pytest Fixtures for MCP SQL Server Tests

Provides reusable test fixtures for:
- SQLite in-memory and file-based test databases
- Database adapters with test data
- Environment variable mocking
- Test database cleanup

Design Decisions:
- Uses pytest's tmp_path fixture for file-based SQLite tests
- SQLite in-memory databases are used by default for speed
- Fixtures handle setup and teardown automatically
- MySQL fixtures are optional (skip if not configured)
"""

from tests.support import SCENARIO

import os
import pytest
import sqlite3
from unittest.mock import patch

from tests.support import SCENARIO, cleanup

_MYSQL_INTEGRATION_REQUESTED = os.environ.get("RUN_MYSQL_INTEGRATION_TESTS") == "1"

@pytest.fixture(autouse=True)
def isolated_scenarios():
    from tests import support_catalog
    SCENARIO.clear()
    support_catalog.reset()
    yield
    cleanup()
    SCENARIO.clear()
    support_catalog.reset()

# =============================================================================
# SQLite Test Fixtures
# =============================================================================

@pytest.fixture
def sqlite_memory_db():
    """
    Create an in-memory SQLite database with test data.
    
    Returns:
        Path string ':memory:'
    """
    return ":memory:"


@pytest.fixture
def sqlite_file_db(tmp_path):
    """
    Create a file-based SQLite database with test data.
    
    Uses pytest's tmp_path fixture for automatic cleanup.
    
    Args:
        tmp_path: Pytest fixture providing temporary directory
        
    Returns:
        Path to the SQLite database file
    """
    db_path = tmp_path / "test_database.db"
    return str(db_path)


@pytest.fixture
def sqlite_test_db(tmp_path):
    """
    Create a SQLite database with test tables and data.
    
    Tables created:
    - users: id, name, email (3 rows)
    - products: id, name, price (5 rows)
    - orders: id, user_id, product_id, quantity (2 rows)
    
    Args:
        tmp_path: Pytest fixture providing temporary directory
        
    Returns:
        Path to the SQLite database file
    """
    db_path = tmp_path / "test_database.db"
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    
    # Insert test data
    cursor.executemany(
        "INSERT INTO users (name, email) VALUES (?, ?)",
        [
            ("Alice", "alice@example.com"),
            ("Bob", "bob@example.com"),
            ("Charlie", "charlie@example.com"),
        ]
    )
    
    cursor.executemany(
        "INSERT INTO products (name, price) VALUES (?, ?)",
        [
            ("Widget", 9.99),
            ("Gadget", 19.99),
            ("Gizmo", 29.99),
            ("Doohickey", 39.99),
            ("Thingamajig", 49.99),
        ]
    )
    
    cursor.executemany(
        "INSERT INTO orders (user_id, product_id, quantity) VALUES (?, ?, ?)",
        [
            (1, 1, 2),
            (2, 3, 1),
        ]
    )
    
    conn.commit()
    conn.close()
    
    return str(db_path)


@pytest.fixture
def sqlite_large_table_db(tmp_path):
    """
    Create a SQLite database with a large table for testing row count estimation.
    
    Creates a table with 15,000 rows to test the sampling fallback.
    
    Args:
        tmp_path: Pytest fixture providing temporary directory
        
    Returns:
        Path to the SQLite database file
    """
    db_path = tmp_path / "large_test_database.db"
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE large_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT
        )
    """)
    
    # Insert 15,000 rows in batches
    batch_size = 1000
    for batch in range(15):
        cursor.executemany(
            "INSERT INTO large_table (data) VALUES (?)",
            [(f"row_{i}",) for i in range(batch * batch_size, (batch + 1) * batch_size)]
        )
    
    conn.commit()
    conn.close()
    
    return str(db_path)


# =============================================================================
# Database Adapter Fixtures
# =============================================================================

@pytest.fixture
def sqlite_adapter(sqlite_test_db):
    """
    Create a SQLiteAdapter connected to test database.
    
    Args:
        sqlite_test_db: Path to test database fixture
        
    Returns:
        Connected SQLiteAdapter instance
    """
    from tests.support_adapters import SQLiteAdapter
    
    adapter = SQLiteAdapter(sqlite_test_db)
    adapter.connect()
    yield adapter
    adapter.close()


@pytest.fixture
def sqlite_memory_adapter():
    """
    Create a SQLiteAdapter connected to in-memory database.
    
    Returns:
        Connected SQLiteAdapter instance
    """
    from tests.support_adapters import SQLiteAdapter
    
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    assert adapter._engine is not None
    
    # Create test table
    from sqlalchemy import text
    with adapter._engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE test_table (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    value REAL
                )
            """))
            conn.execute(text("""
                INSERT INTO test_table (id, name, value) VALUES
                (1, 'test1', 1.5),
                (2, 'test2', 2.5),
                (3, 'test3', 3.5)
            """))
    
    yield adapter
    adapter.close()


# =============================================================================
# Environment Variable Fixtures
# =============================================================================

@pytest.fixture
def sqlite_env(sqlite_test_db):
    """
    Set environment variables for SQLite testing.
    
    Args:
        sqlite_test_db: Path to test database fixture
        
    Yields:
        Dict of environment variables set
    """
    env_vars = {
        "DB_TYPE": "sqlite",
        "SQLITE_DATABASE_PATH": sqlite_test_db,
    }
    
    with patch.dict(SCENARIO, env_vars):
        yield env_vars


@pytest.fixture
def mysql_env():
    """
    Get MySQL environment variables for testing.
    
    Requires DB_USER, DB_PASSWORD, DB_HOST, DB_NAME to be set in environment.
    
    Returns:
        Dict of MySQL environment variables
    """
    return {
        "DB_TYPE": "mysql",
        "DB_USER": os.getenv("DB_USER"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_NAME": os.getenv("DB_NAME"),
    }


@pytest.fixture
def mysql_adapter():
    """
    Create a MySQLAdapter connected to test database.
    
    Requires explicit RUN_MYSQL_INTEGRATION_TESTS=1 opt-in plus exported MySQL
    credentials. The default pytest process intentionally does not load .env.
    
    Returns:
        Connected MySQLAdapter instance
    """
    if not _MYSQL_INTEGRATION_REQUESTED:
        pytest.skip(
            "MySQL integration tests require RUN_MYSQL_INTEGRATION_TESTS=1"
        )

    from tests.support_adapters import MySQLAdapter

    required_env = {
        "DB_USER": os.getenv("DB_USER"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_NAME": os.getenv("DB_NAME"),
    }
    missing = [name for name, value in required_env.items() if not value]
    if missing:
        pytest.skip(f"MySQL integration tests require env vars: {', '.join(missing)}")
    
    from pydantic import SecretStr
    from sql_safety_executor.database.models import DatabaseConfig, ConnectionPolicy
    adapter = MySQLAdapter(config=DatabaseConfig(
        connection_id="mysql_integration", db_type="mysql", query_timeout_seconds=30,
        connect_timeout_seconds=10, policy=ConnectionPolicy(),
        mysql_host=required_env["DB_HOST"], mysql_user=required_env["DB_USER"],
        mysql_database=required_env["DB_NAME"], mysql_password=SecretStr(required_env["DB_PASSWORD"]),
    ))
    if not adapter.connect():
        pytest.skip("MySQL integration tests require a reachable MySQL server")

    success, message = adapter.check_connection()
    if not success:
        adapter.close()
        pytest.skip(f"MySQL integration tests skipped: {message}")

    yield adapter
    adapter.close()


# =============================================================================
# Helper Fixtures
# =============================================================================

@pytest.fixture
def reset_global_adapter():
    """
    Reset the global adapter before and after each test.
    
    Ensures test isolation by clearing any cached adapter instance.
    """
    from tests.support_adapters import reset_adapter
    
    reset_adapter()
    yield
    reset_adapter()
