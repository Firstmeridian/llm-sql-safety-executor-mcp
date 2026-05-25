"""
SQL Safety Checker Module

Provides SQL query safety validation and execution.

This module is database-agnostic for safety checking, but uses the
database adapter for execution. The is_sql_safe() function works
with any SQL dialect (MySQL, SQLite, PostgreSQL).

Backward Compatibility:
- execute_sql() signature unchanged
- is_sql_safe() logic unchanged (uses sqlparse)
- All existing imports continue to work

Changes in v2.0 (SQLite support):
- Database connection now delegated to db_adapter.py
- Removed MySQL-specific engine creation
- execute_sql() now uses adapter.execute()
"""

import sqlparse
import logging
from db_adapter import get_adapter, QUERY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


def execute_sql(sql_query: str, timeout_override: int | None = None) -> list | str:
    """
    Executes a SQL query after checking if it is safe.
    
    Uses database adapter for actual execution (MySQL or SQLite).
    Includes query timeout protection (P0 security measure).
    
    Reference: Microsoft Azure best practices - "Set appropriate timeouts for database operations"

    Args:
        sql_query: The SQL query to execute.
        timeout_override: Optional timeout in seconds (overrides default QUERY_TIMEOUT_SECONDS)

    Returns:
        A list of tuples representing the rows of the result, or an error message string.
        
    Backward Compatibility:
        - Same function signature as before
        - Same return format (list of tuples or error string)
        - Safe query types unchanged: SELECT, SHOW, DESCRIBE, EXPLAIN
        
    Note on SHOW/DESCRIBE with SQLite:
        - SQLite does not support SHOW/DESCRIBE commands
        - These are handled at the MCP tool level via adapter methods
        - Direct SHOW/DESCRIBE queries will fail on SQLite with syntax error
    """
    if not is_sql_safe(sql_query):
        return "Error: Only read-only queries are allowed (SELECT, SHOW, DESCRIBE, EXPLAIN)."

    timeout = timeout_override if timeout_override is not None else QUERY_TIMEOUT_SECONDS
    
    try:
        adapter = get_adapter()
        result = adapter.execute(sql_query, timeout)
        return result
    except Exception as e:
        logger.exception("Unexpected error during SQL execution")
        return "Error: An unexpected error occurred"

# Safe read-only SQL statement types
SAFE_SQL_TYPES = {'SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN'}


def is_sql_safe(sql_query: str) -> bool:
    """
    Checks if a given SQL query is safe by ensuring it only contains read-only statements.

    Allowed statement types:
    - SELECT: Standard data retrieval
    - SHOW: Database metadata (SHOW TABLES, SHOW COLUMNS, etc.)
    - DESCRIBE: Table structure information
    - EXPLAIN: Query execution plan analysis

    Args:
        sql_query: The SQL query to check.

    Returns:
        True if the query is safe (read-only), False otherwise.
    """
    if not sql_query:
        return True

    try:
        parsed = sqlparse.parse(sql_query)
        for statement in parsed:
            stmt_type = statement.get_type()
            # sqlparse returns 'UNKNOWN' for SHOW/DESCRIBE/EXPLAIN, check first token
            if stmt_type == 'UNKNOWN' or stmt_type is None:
                first_token = statement.token_first(skip_cm=True)
                if first_token:
                    stmt_type = first_token.normalized.upper()
            if stmt_type not in SAFE_SQL_TYPES:
                return False
    except Exception:
        # In case of a parsing error, we consider it unsafe
        return False

    return True

# Example usage:
if __name__ == '__main__':
    """
    Example demonstrating SQL safety checking and execution.
    
    To run this example:
    1. Set DB_TYPE environment variable ('mysql' or 'sqlite')
    2. For MySQL: Configure DB_USER, DB_PASSWORD, DB_HOST, DB_NAME in .env
    3. For SQLite: Set SQLITE_DATABASE_PATH in .env (or use :memory:)
    4. Install required libraries: pip install -r requirements.txt
    """
    from db_adapter import get_adapter, reset_adapter, DB_TYPE
    import os
    
    print(f"Database type: {DB_TYPE}")
    
    # Get adapter instance
    adapter = get_adapter()
    
    # Test connection
    success, message = adapter.check_connection()
    if not success:
        print(f"Connection failed: {message}")
        exit(1)
    print(f"Connection status: {message}")

    safe_query = "SELECT 1 as test_value"
    unsafe_query = "DELETE FROM test_users WHERE id = 1"

    print(f"\nIs '{safe_query}' safe? {is_sql_safe(safe_query)}")
    print(f"Is '{unsafe_query}' safe? {is_sql_safe(unsafe_query)}")

    print("\n--- Testing SQL Execution ---")
    
    # Create a dummy 'test_users' table for testing if it doesn't exist
    # This requires write access - only works in dev environment
    try:
        engine = getattr(adapter, "_engine", None)
        if engine is None:
            print("Database setup for example failed: adapter engine is unavailable.")
            exit(1)

        if adapter.db_type == "mysql":
            # MySQL-specific setup
            from sqlalchemy import text
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text("""
                        CREATE TABLE IF NOT EXISTS test_users (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(255)
                        )
                    """))
                    result = connection.execute(text("SELECT COUNT(*) FROM test_users"))
                    if result.scalar_one() == 0:
                        connection.execute(text("INSERT INTO test_users (name) VALUES ('Alice'), ('Bob')"))
            test_query = "SELECT * FROM test_users LIMIT 1"
            
        elif adapter.db_type == "sqlite":
            # SQLite-specific setup
            from sqlalchemy import text
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text("""
                        CREATE TABLE IF NOT EXISTS test_users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT
                        )
                    """))
                    result = connection.execute(text("SELECT COUNT(*) FROM test_users"))
                    if result.scalar_one() == 0:
                        connection.execute(text("INSERT INTO test_users (name) VALUES ('Alice'), ('Bob')"))
            test_query = "SELECT * FROM test_users LIMIT 1"
        else:
            print(f"Unsupported database type: {adapter.db_type}")
            exit(1)
            
    except Exception as e:
        print(f"Database setup for example failed: {e}")
        print("Please ensure your database is configured correctly.")
        exit(1)

    print(f"\nExecuting safe query: '{test_query}'")
    result = execute_sql(test_query)
    print(f"Result: {result}")

    print(f"\nExecuting unsafe query: '{unsafe_query}'")
    result = execute_sql(unsafe_query)
    print(f"Result: {result}")
    
    # Cleanup
    reset_adapter()

