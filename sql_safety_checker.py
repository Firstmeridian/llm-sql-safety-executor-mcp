
import sqlparse
import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Database connection settings
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")

# Query timeout in seconds (P0 security: prevent long-running queries)
# Reference: Microsoft Azure best practices - "Set appropriate timeouts for database operations"
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))

# Connection timeout in seconds
CONNECT_TIMEOUT_SECONDS = int(os.getenv("CONNECT_TIMEOUT_SECONDS", "10"))

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}?charset=utf8mb4"

try:
    # Best practice: Configure connection with timeouts
    # Reference: PyMySQL connect_args for timeout settings
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        connect_args={
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "read_timeout": QUERY_TIMEOUT_SECONDS,
            "write_timeout": QUERY_TIMEOUT_SECONDS,
        }
    )
except ImportError:
    print("Error: PyMySQL is not installed. Please install it using: pip install PyMySQL")
    engine = None


def execute_sql(sql_query: str, timeout_override: int | None = None) -> list | str:
    """
    Executes a SQL query after checking if it is safe, using SQLAlchemy for connection pooling.
    
    Includes query timeout protection (P0 security measure).
    Reference: Microsoft Azure best practices - "Set appropriate timeouts for database operations"

    Args:
        sql_query: The SQL query to execute.
        timeout_override: Optional timeout in seconds (overrides default QUERY_TIMEOUT_SECONDS)

    Returns:
        A list of tuples representing the rows of the result, or an error message string.
    """
    if not engine:
        return "Error: Database engine could not be initialized. Please check your installation."

    if not is_sql_safe(sql_query):
        return "Error: Only read-only queries are allowed (SELECT, SHOW, DESCRIBE, EXPLAIN)."

    timeout = timeout_override if timeout_override is not None else QUERY_TIMEOUT_SECONDS
    
    try:
        with engine.connect() as connection:
            # Set session-level query timeout for MySQL
            # MAX_EXECUTION_TIME is in milliseconds
            # Reference: MySQL 5.7+ supports MAX_EXECUTION_TIME optimizer hint
            timeout_ms = timeout * 1000
            try:
                connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
            except SQLAlchemyError:
                # Fallback: Some MySQL versions may not support MAX_EXECUTION_TIME
                # The connection-level read_timeout will still apply
                logger.debug("MAX_EXECUTION_TIME not supported, using connection timeout")
            
            result = connection.execute(text(sql_query))
            rows = result.fetchall()
            return rows
    except SQLAlchemyError as e:
        # Security: Sanitize error messages to prevent information disclosure
        # Log full error internally, return generic message to client
        error_str = str(e)
        logger.warning(f"SQL execution error: {error_str[:200]}")  # Log truncated error
        
        if "Access denied" in error_str or "permission" in error_str.lower():
            return "Error: Access denied"
        elif "doesn't exist" in error_str or "Unknown table" in error_str:
            return "Error: Table or column not found"
        elif "syntax" in error_str.lower():
            return "Error: SQL syntax error"
        elif "timeout" in error_str.lower() or "max_execution_time" in error_str.lower():
            return f"Error: Query timeout exceeded ({timeout}s limit)"
        elif "timed out" in error_str.lower() or "2013" in error_str:
            # PyMySQL error 2013: Lost connection during query (timeout)
            return f"Error: Query timeout exceeded ({timeout}s limit)"
        elif "read timed out" in error_str.lower():
            return f"Error: Query timeout exceeded ({timeout}s limit)"
        elif "Lost connection" in error_str:
            return f"Error: Query timeout exceeded ({timeout}s limit)"
        else:
            return "Error: Database query failed"
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
    # Note: To run this example, you need to have a MySQL database running
    # and have the .env file configured with your database credentials.
    # You also need to install the required libraries:
    # pip install sqlalchemy PyMySQL python-dotenv

    if not engine:
        exit()

    safe_query = "SELECT * FROM test_users LIMIT 1"
    unsafe_query = "DELETE FROM test_users WHERE id = 1"

    print(f"Is '{safe_query}' safe? {is_sql_safe(safe_query)}")
    print(f"Is '{unsafe_query}' safe? {is_sql_safe(unsafe_query)}")

    print("\n--- Testing SQL Execution ---")
    # Create a dummy 'test_users' table for testing if it doesn't exist
    try:
        with engine.connect() as connection:
            with connection.begin(): # Start a single transaction for setup
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS test_users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255)
                    )
                """))
                # Check if table is empty before inserting
                result = connection.execute(text("SELECT COUNT(*) FROM test_users"))
                if result.scalar_one() == 0:
                    connection.execute(text("INSERT INTO test_users (name) VALUES ('Alice'), ('Bob')"))
    except SQLAlchemyError as e:
        print(f"Database setup for example failed: {e}")
        print("Please ensure your database is running and .env is configured correctly.")
        exit()

    print(f"\nExecuting safe query: '{safe_query}'")
    result = execute_sql(safe_query)
    print(f"Result: {result}")

    print(f"\nExecuting unsafe query: '{unsafe_query}'")
    result = execute_sql(unsafe_query)
    print(f"Result: {result}")

