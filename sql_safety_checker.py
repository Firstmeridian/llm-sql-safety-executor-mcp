"""
SQL Safety Checker Module

Provides conservative SQL query safety validation and execution for the
currently supported MySQL and SQLite adapters.

The checker is a lightweight statement-shape gate, not a comprehensive SQL
parser or a guarantee for untested dialects. New database backends must review
their read/explain semantics before reusing this policy.

Backward Compatibility:
- execute_sql() signature unchanged
- is_sql_safe() remains the shared public safety predicate (uses sqlparse)
- All existing imports continue to work

Changes in v2.0 (SQLite support):
- Database connection now delegated to db_adapter.py
- Removed MySQL-specific engine creation
- execute_sql() now uses adapter.execute()
"""

import logging
import re

import sqlparse
from sqlparse import tokens as sql_tokens
from db_adapter import get_adapter, get_connection_config

logger = logging.getLogger(__name__)


def execute_sql(
    sql_query: str,
    timeout_override: int | None = None,
    connection_id: str | None = None,
) -> list | str:
    """
    Executes a SQL query after checking if it is safe.
    
    Uses database adapter for actual execution (MySQL or SQLite).
    Includes query timeout protection (P0 security measure).
    
    Reference: Microsoft Azure best practices - "Set appropriate timeouts for database operations"

    Args:
        sql_query: The SQL query to execute.
        timeout_override: Optional timeout in seconds (overrides default QUERY_TIMEOUT_SECONDS)
        connection_id: Optional configured connection id. Omit for the default
            connection to preserve pre-v3.5 behavior.

    Returns:
        A list of tuples representing the rows of the result, or an error message string.
        
    Backward Compatibility:
        - Same function signature as before
        - Same return format (list of tuples or error string)
        - Top-level safe query type names remain SELECT, SHOW, DESCRIBE,
          and EXPLAIN; executing ANALYZE forms are excluded
        
    Note on SHOW/DESCRIBE with SQLite:
        - SQLite does not support SHOW/DESCRIBE commands
        - These are handled at the MCP tool level via adapter methods
        - Direct SHOW/DESCRIBE queries will fail on SQLite with syntax error

    Policy boundary:
        This compatibility helper applies only the shared statement-shape
        predicate in ``is_sql_safe()``. It resolves and executes on the selected
        connection, but does not enforce the MCP layer's per-connection
        ``ALLOW_UNION``, ``ALLOWED_TABLES``, raw-SHOW, system-schema, or extended
        table-scope policy. Security-sensitive integrations should use the MCP
        query/Skill tools or enforce an equivalent application policy.
    """
    try:
        config = get_connection_config(connection_id)
    except ValueError as e:
        return f"Error: {e}"

    if not is_sql_safe(sql_query):
        return (
            "Error: Only read-only queries are allowed "
            "(SELECT, SHOW, DESCRIBE, non-ANALYZE EXPLAIN)."
        )

    timeout = timeout_override if timeout_override is not None else config.query_timeout_seconds
    
    try:
        adapter = get_adapter(config.connection_id)
        result = adapter.execute(sql_query, timeout)
        return result
    except Exception as e:
        logger.exception("Unexpected error during SQL execution")
        return "Error: An unexpected error occurred"

# Safe read-only SQL statement types
SAFE_SQL_TYPES = {'SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN'}
_NESTED_WRITE_DML_TYPES = {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'MERGE'}
_EXECUTING_EXPLAIN_PATTERN = re.compile(
    r'^(?:EXPLAIN|DESCRIBE|DESC)\s+'
    r'(?:ANALYZE\b|\([^)]*\bANALYZE\b[^)]*\))',
    re.IGNORECASE,
)

_MYSQL_DASH_COMMENT_WHITESPACE = " \t\r\n\f\v"


def has_unsafe_mysql_comment_semantics(sql_query: str) -> bool:
    """Detect comment forms whose MySQL meaning differs from generic SQL parsing.

    MySQL executes the body of ``/*! ... */`` comments and interprets
    ``/*+ ... */`` as optimizer directives. MariaDB additionally executes
    ``/*M! ... */`` comments. MySQL also recognizes ``--`` comments only when
    the second dash is followed by whitespace or a control character, while
    sqlparse treats forms such as ``--1`` as a comment. Reject these forms
    before any comment-stripping normalization so policy checks cannot
    accidentally discard executable SQL or server directives.
    """
    try:
        statements = sqlparse.parse(sql_query)
        for statement in statements:
            for token in statement.flatten():
                if token.ttype not in sql_tokens.Comment:
                    continue

                comment = token.value.lstrip()
                if comment.startswith(("/*!", "/*+", "/*M!")):
                    return True
                if comment.startswith("--") and (
                    len(comment) == 2
                    or comment[2] not in _MYSQL_DASH_COMMENT_WHITESPACE
                ):
                    return True
    except Exception:
        # A syntax gate must fail closed if its parser cannot classify comments.
        return True
    return False


def _is_explain_for_connection(statement: sqlparse.sql.Statement) -> bool:
    """Detect MySQL's privilege-dependent inspection of another session."""
    tokens = [
        token
        for token in statement.flatten()
        if not token.is_whitespace and token.ttype not in sql_tokens.Comment
    ]
    if not tokens or tokens[0].normalized.upper() not in {
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
    }:
        return False
    return any(
        token.normalized.upper() == "FOR"
        and tokens[index + 1].normalized.upper() == "CONNECTION"
        for index, token in enumerate(tokens[:-1])
    )


def is_sql_safe(sql_query: str) -> bool:
    """
    Checks if a given SQL query is safe by ensuring it only contains read-only statements.

    Allowed statement types for the current MySQL/SQLite runtime:
    - SELECT: Standard data retrieval
    - SHOW: Database metadata (SHOW TABLES, SHOW COLUMNS, etc.)
    - DESCRIBE: Table structure information
    - EXPLAIN: Non-ANALYZE execution-plan inspection

    ``EXPLAIN ANALYZE`` is rejected because supported MySQL versions can
    execute the analyzed statement. SELECT-shaped statements that contain a
    nested write DML token are also rejected. This remains a conservative
    syntax gate rather than comprehensive semantic SQL analysis.

    Args:
        sql_query: The SQL query to check.

    Returns:
        True if the query is safe (read-only), False otherwise.
    """
    if not sql_query:
        return True

    try:
        if has_unsafe_mysql_comment_semantics(sql_query):
            return False

        parsed = [
            statement
            for statement in sqlparse.parse(sql_query)
            if str(statement).strip(" \t\r\n;")
        ]
        # A raw query is one database operation. Besides simplifying audit and
        # timeout semantics, this prevents a safe first statement from hiding
        # a later statement from prefix-oriented policy checks.
        if len(parsed) != 1:
            return False

        for statement in parsed:
            if _is_explain_for_connection(statement):
                return False
            normalized_statement = sqlparse.format(
                str(statement),
                strip_comments=True,
            )
            normalized_statement = re.sub(
                r'\s+',
                ' ',
                normalized_statement,
            ).strip()
            if _EXECUTING_EXPLAIN_PATTERN.match(normalized_statement):
                return False

            stmt_type = statement.get_type()
            # sqlparse returns 'UNKNOWN' for SHOW/DESCRIBE/EXPLAIN, check first token
            if stmt_type == 'UNKNOWN' or stmt_type is None:
                first_token = statement.token_first(skip_cm=True)
                if first_token:
                    stmt_type = first_token.normalized.upper()
            if stmt_type not in SAFE_SQL_TYPES:
                return False
            if stmt_type == 'SELECT' and any(
                token.ttype is sql_tokens.DML
                and token.normalized.upper() in _NESTED_WRITE_DML_TYPES
                for token in statement.flatten()
            ):
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
