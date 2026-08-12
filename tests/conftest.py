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

import os
import sys
import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Keep the default pytest suite hermetic even when a developer's shell or local
# .env configures a live database, mutation routing, Skills, or telemetry.
# python-dotenv honors PYTHON_DOTENV_DISABLED, so module reloads cannot silently
# restore values that a test removed to exercise configuration defaults.
_MYSQL_INTEGRATION_REQUESTED = (
    os.environ.get("RUN_MYSQL_INTEGRATION_TESTS", "").strip() == "1"
)
_NAMED_CONNECTION_SUFFIXES = (
    "TYPE",
    "QUERY_TIMEOUT_SECONDS",
    "CONNECT_TIMEOUT_SECONDS",
    "ALLOW_UNION",
    "ALLOWED_TABLES",
    "ALLOW_MUTATIONS",
    "MUTATION_SKILLS",
    "USER",
    "PASSWORD",
    "HOST",
    "NAME",
    "SQLITE_DATABASE_PATH",
    "SQLITE_PROGRESS_HANDLER_INTERVAL",
)
for _env_name in tuple(os.environ):
    if not _env_name.startswith("DB_"):
        continue
    _env_remainder = _env_name[3:]
    if any(
        _env_remainder.endswith(f"_{suffix}")
        for suffix in _NAMED_CONNECTION_SUFFIXES
    ):
        os.environ.pop(_env_name, None)

_SAFE_PYTEST_ENV = {
    "PYTHON_DOTENV_DISABLED": "1",
    "DB_CONNECTIONS": "",
    "DEFAULT_DB_CONNECTION": "",
    "DB_TYPE": "sqlite",
    "SQLITE_DATABASE_PATH": ":memory:",
    "QUERY_TIMEOUT_SECONDS": "30",
    "CONNECT_TIMEOUT_SECONDS": "10",
    "SQLITE_PROGRESS_HANDLER_INTERVAL": "100",
    "ALLOW_UNION": "0",
    "ALLOWED_TABLES": "",
    "ENABLE_SCHEMA_TOOLS": "1",
    "ENABLE_TABLE_SUMMARY": "0",
    "LARGE_TABLE_THRESHOLD": "1000",
    "MAX_RESULT_ROWS": "100",
    "MAX_RESULT_CHARS": "16000",
    "MAX_SQL_LENGTH": "20000",
    "MAX_SCHEMA_TABLES": "50",
    "MAX_OVERVIEW_TABLES": "100",
    "MCP_TOOL_TIMEOUT_SECONDS": "120",
    "ENABLE_SKILLS": "0",
    "SKILLS_ALLOW_MUTATIONS": "0",
    "SKILLS_ALLOW_MUTATION_CONNECTIONS": "",
    "SKILLS_DIR": "skills/",
    "SKILLS_LIST_DEFAULT_DETAIL": "summary",
    "SKILLS_LIST_AVAILABLE_ONLY_DEFAULT": "1",
    "SKILLS_CHECK_SCHEMA_ON_LIST": "1",
    "SKILLS_EXCLUDE_PROFILES": "",
    "SKILLS_AUDIT_QUERIES": "0",
    "MUTATION_PREVIEW_TOKEN_SECRET": "",
    "MUTATION_PREVIEW_TOKEN_TTL_SECONDS": "300",
    "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES": "10000",
    "ENABLE_TOOL_TELEMETRY": "0",
    "TOOL_TELEMETRY_SAMPLE_RATE": "1.0",
}
if not _MYSQL_INTEGRATION_REQUESTED:
    _SAFE_PYTEST_ENV.update(
        {
            "DB_USER": "",
            "DB_PASSWORD": "",
            "DB_HOST": "",
            "DB_NAME": "",
        }
    )
os.environ.update(_SAFE_PYTEST_ENV)


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
    from db_adapter import SQLiteAdapter
    
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
    from db_adapter import SQLiteAdapter
    
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
    
    with patch.dict(os.environ, env_vars):
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

    from db_adapter import MySQLAdapter

    required_env = {
        "DB_USER": os.getenv("DB_USER"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_NAME": os.getenv("DB_NAME"),
    }
    missing = [name for name, value in required_env.items() if not value]
    if missing:
        pytest.skip(f"MySQL integration tests require env vars: {', '.join(missing)}")
    
    adapter = MySQLAdapter()
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
    from db_adapter import reset_adapter
    
    reset_adapter()
    yield
    reset_adapter()
