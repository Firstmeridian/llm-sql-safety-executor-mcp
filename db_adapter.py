"""
Database Adapter Module

Provides a unified interface for different database backends (MySQL, SQLite).
Uses Abstract Base Class pattern to enable extension for future databases (PostgreSQL).

Design Decisions:
- ABC base class for consistent interface and future extension
- Factory function for adapter creation based on environment config
- SQLite uses set_progress_handler() for query timeout (no MAX_EXECUTION_TIME)
- SQLite uses StaticPool (single connection), MySQL uses QueuePool
- Adapter methods replace SHOW/DESCRIBE SQL for cross-database compatibility

Backward Compatibility:
- Default DB_TYPE=mysql maintains existing behavior
- All MySQL-specific configurations continue to work
- execute_sql() signature unchanged for mcp_sql_server.py compatibility

References:
- SQLAlchemy pool types: https://docs.sqlalchemy.org/en/20/core/pooling.html
- SQLite set_progress_handler: https://docs.python.org/3/library/sqlite3.html
- aiosqlite architecture (for future async): https://github.com/omnilib/aiosqlite
"""

import os
import time
import logging
import sqlite3
from abc import ABC, abstractmethod
from typing import Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Database type: 'mysql' (default) or 'sqlite'
DB_TYPE = os.getenv("DB_TYPE", "mysql").lower()

# Query timeout in seconds (P0 security: prevent long-running queries)
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))

# Connection timeout in seconds
CONNECT_TIMEOUT_SECONDS = int(os.getenv("CONNECT_TIMEOUT_SECONDS", "10"))

# SQLite-specific configuration
SQLITE_DATABASE_PATH = os.getenv("SQLITE_DATABASE_PATH", ":memory:")

# MySQL-specific configuration (preserved for backward compatibility)
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")

# Progress handler interval for SQLite timeout
# Lower value = more responsive timeout, higher CPU overhead
# Recommended: 100-1000 (100 = ~10μs overhead per check)
SQLITE_PROGRESS_HANDLER_INTERVAL = int(os.getenv("SQLITE_PROGRESS_HANDLER_INTERVAL", "100"))


# =============================================================================
# Abstract Base Class
# =============================================================================

class DatabaseAdapter(ABC):
    """
    Abstract base class for database adapters.
    
    Provides unified interface for different database backends.
    Subclasses must implement all abstract methods.
    
    Design Note:
    - Uses ABC to enforce interface contract
    - Reserves extension point for PostgreSQL and other databases
    - Methods return consistent formats across all implementations
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish database connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def execute(self, sql: str, timeout: int | None = None, params: dict | None = None) -> list | str:
        """
        Execute a SQL query with timeout protection.
        
        Args:
            sql: SQL query to execute
            timeout: Optional timeout in seconds (overrides default)
            params: Optional parameter dict for named-parameter binding
                    (e.g., {"year": 2026} for ":year" in SQL template).
                    Uses SQLAlchemy text() parameterized execution.
            
        Returns:
            List of row tuples on success, error string on failure
        """
        pass

    @abstractmethod
    def execute_write(self, sql: str, params: dict, timeout: int | None = None) -> dict:
        """
        Execute a parameterized write SQL statement within a transaction.

        Uses SQLAlchemy text() + connection.execute(text_obj, params) for
        parameterized queries (SQL injection prevention).
        Runs inside connection.begin() block: auto-commit on success,
        auto-rollback on exception.

        Args:
            sql: SQL with named parameters (e.g., "UPDATE t SET col=:val WHERE id=:id")
            params: Parameter dict for binding
            timeout: Optional timeout override in seconds

        Returns:
            {"success": True, "rowcount": N} on success

        Raises:
            SQLAlchemyError (or subclass) on failure — not caught here,
            propagates to caller (MutationBase) for error sanitization.
        """
        pass
    
    @abstractmethod
    def get_tables(self) -> list[dict[str, Any]]:
        """
        Get list of all tables with metadata.
        
        Returns:
            List of dicts with 'table_name' and 'row_count' keys
        """
        pass
    
    @abstractmethod
    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """
        Get column information for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of dicts with column metadata (name, type, nullable, key, default)
        """
        pass
    
    @abstractmethod
    def get_row_estimate(self, table_name: str) -> int:
        """
        Get estimated row count for a table.
        
        Note: This is an estimate, not exact count.
        For SQLite, uses sampling strategy.
        For MySQL, uses INFORMATION_SCHEMA.TABLES.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Estimated row count (0 if table not found)
        """
        pass
    
    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """
        Check if database connection is working.
        
        Returns:
            (success, message) tuple
        """
        pass
    
    @abstractmethod
    def get_database_name(self) -> str | None:
        """
        Get the current database name.
        
        Returns:
            Database name or None if not available
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close database connection and cleanup resources."""
        pass

    def _handle_error(self, e: Exception, timeout: int | None = None) -> str:
        """
        Sanitize error messages for security.

        Subclasses should override with DB-specific patterns.
        Default: generic safe message.

        Args:
            e: The exception that occurred
            timeout: Optional timeout value for error message context

        Returns:
            Sanitized error string safe for client display
        """
        logger.warning(f"Database error: {str(e)[:200]}")
        return "Error: Database query failed"

    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return database type identifier ('mysql', 'sqlite', etc.)."""
        pass


# =============================================================================
# MySQL Adapter
# =============================================================================

class MySQLAdapter(DatabaseAdapter):
    """
    MySQL database adapter using SQLAlchemy with PyMySQL driver.
    
    Features:
    - Connection pooling with QueuePool
    - Query timeout via MAX_EXECUTION_TIME + connection timeouts
    - INFORMATION_SCHEMA for metadata queries
    
    Backward Compatibility:
    - Preserves all existing MySQL behavior from sql_safety_checker.py
    - Uses same connection parameters and timeout settings
    """
    
    def __init__(self):
        self._engine = None
        self._db_name = DB_NAME
        self._connected = False
    
    @property
    def db_type(self) -> str:
        return "mysql"
    
    def connect(self) -> bool:
        """Create SQLAlchemy engine with connection pool."""
        if self._engine is not None:
            return True
        
        try:
            from sqlalchemy import create_engine
            
            # Build connection URL (same as original sql_safety_checker.py)
            database_url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}?charset=utf8mb4"
            
            # Create engine with connection pooling
            # Reference: SQLAlchemy QueuePool for MySQL
            self._engine = create_engine(
                database_url,
                pool_pre_ping=True,  # Verify connection before use
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                connect_args={
                    "connect_timeout": CONNECT_TIMEOUT_SECONDS,
                    "read_timeout": QUERY_TIMEOUT_SECONDS,
                    "write_timeout": QUERY_TIMEOUT_SECONDS,
                }
            )
            self._connected = True
            logger.info(f"MySQL adapter connected to {DB_HOST}/{DB_NAME}")
            return True
            
        except ImportError:
            logger.error("PyMySQL not installed. Run: pip install PyMySQL")
            return False
        except Exception as e:
            logger.error(f"MySQL connection failed: {e}")
            return False
    
    def execute(self, sql: str, timeout: int | None = None, params: dict | None = None) -> list | str:
        """
        Execute SQL query with timeout protection.
        
        Uses MySQL MAX_EXECUTION_TIME optimizer hint for query-level timeout.
        Falls back to connection-level read_timeout if not supported.

        Args:
            sql: SQL query to execute
            timeout: Optional timeout in seconds (overrides default)
            params: Optional parameter dict for named-parameter binding
        """
        if not self._engine:
            if not self.connect():
                return "Error: Database engine could not be initialized."
        
        timeout = timeout if timeout is not None else QUERY_TIMEOUT_SECONDS
        
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError
            
            with self._engine.connect() as connection:
                # Set session-level query timeout for MySQL
                # MAX_EXECUTION_TIME is in milliseconds
                timeout_ms = timeout * 1000
                try:
                    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
                except SQLAlchemyError:
                    # Fallback: Some MySQL versions may not support MAX_EXECUTION_TIME
                    logger.debug("MAX_EXECUTION_TIME not supported, using connection timeout")
                
                if params:
                    result = connection.execute(text(sql), params)
                else:
                    result = connection.execute(text(sql))
                rows = result.fetchall()
                return rows
                
        except Exception as e:
            return self._handle_error(e, timeout)

    def execute_write(self, sql: str, params: dict, timeout: int | None = None) -> dict:
        """
        Execute a parameterized write SQL within a MySQL transaction.

        Uses MAX_EXECUTION_TIME for timeout, connection.begin() for explicit
        transaction (auto-commit on success, auto-rollback on exception).
        Exceptions propagate to caller (MutationBase) for error sanitization.
        """
        if not self._engine:
            if not self.connect():
                raise RuntimeError("Database engine could not be initialized.")

        timeout = timeout if timeout is not None else QUERY_TIMEOUT_SECONDS

        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        with self._engine.begin() as connection:
            timeout_ms = timeout * 1000
            try:
                connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
            except SQLAlchemyError:
                logger.debug("MAX_EXECUTION_TIME not supported, using connection timeout")

            result = connection.execute(text(sql), params)
            return {"success": True, "rowcount": result.rowcount}

    def _handle_error(self, e: Exception, timeout: int | None = None) -> str:
        """
        Sanitize error messages for security.
        
        Preserves original error handling logic from sql_safety_checker.py.

        Args:
            e: The exception that occurred
            timeout: Optional timeout value for error message context
        """
        error_str = str(e)
        logger.warning(f"SQL execution error: {error_str[:200]}")

        timeout_suffix = f" ({timeout}s limit)" if timeout is not None else ""
        
        if "Access denied" in error_str or "permission" in error_str.lower():
            return "Error: Access denied"
        elif "doesn't exist" in error_str or "Unknown table" in error_str:
            return "Error: Table or column not found"
        elif "syntax" in error_str.lower():
            return "Error: SQL syntax error"
        elif "timeout" in error_str.lower() or "max_execution_time" in error_str.lower():
            return f"Error: Query timeout exceeded{timeout_suffix}"
        elif "timed out" in error_str.lower() or "2013" in error_str:
            return f"Error: Query timeout exceeded{timeout_suffix}"
        elif "read timed out" in error_str.lower():
            return f"Error: Query timeout exceeded{timeout_suffix}"
        elif "Lost connection" in error_str:
            return f"Error: Query timeout exceeded{timeout_suffix}"
        else:
            return "Error: Database query failed"
    
    def get_tables(self) -> list[dict[str, Any]]:
        """Get all tables with row count estimates from INFORMATION_SCHEMA."""
        sql = """
            SELECT 
                TABLE_NAME as table_name, 
                TABLE_ROWS as row_count
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        result = self.execute(sql)
        
        if isinstance(result, str):
            logger.error(f"Failed to get tables: {result}")
            return []
        
        return [{"table_name": row[0], "row_count": row[1] or 0} for row in result]
    
    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """Get column information from INFORMATION_SCHEMA."""
        sql = f"""
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        result = self.execute(sql)
        
        if isinstance(result, str):
            logger.error(f"Failed to get columns for {table_name}: {result}")
            return []
        
        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "nullable": row[2],
                "key_type": row[3],
                "default_value": row[4]
            }
            for row in result
        ]
    
    def get_row_estimate(self, table_name: str) -> int:
        """Get row count estimate from INFORMATION_SCHEMA.TABLES."""
        sql = f"""
            SELECT TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
        """
        result = self.execute(sql)
        
        if isinstance(result, str) or not result:
            return 0
        
        return result[0][0] or 0
    
    def check_connection(self) -> tuple[bool, str]:
        """Check MySQL connection status."""
        result = self.execute("SELECT 1")
        
        if isinstance(result, str):
            return False, result
        
        return True, "MySQL connection successful"
    
    def get_database_name(self) -> str | None:
        """Get current database name."""
        result = self.execute("SELECT DATABASE()")
        
        if isinstance(result, str) or not result:
            return self._db_name
        
        return result[0][0]
    
    def close(self) -> None:
        """Dispose SQLAlchemy engine."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._connected = False
            logger.info("MySQL adapter closed")


# =============================================================================
# SQLite Adapter
# =============================================================================

class SQLiteAdapter(DatabaseAdapter):
    """
    SQLite database adapter using SQLAlchemy with sqlite3 driver.
    
    Features:
    - StaticPool for single connection (recommended for SQLite)
    - Query timeout via set_progress_handler() callback
    - sqlite_master and PRAGMA for metadata queries
    - check_same_thread=False for cross-thread usage
    
    Design Decisions:
    - Uses synchronous sqlite3 (not aiosqlite) for simplicity
    - StaticPool ensures single connection, avoiding file lock issues
    - set_progress_handler provides query-level timeout without external threads
    
    Timeout Implementation:
    - Uses sqlite3.Connection.set_progress_handler() which is called periodically
      during query execution (every N virtual machine instructions)
    - Callback returns non-zero to interrupt the query
    - This is a native SQLite feature, compatible with both sync and async usage
    
    Limitations:
    - Row count estimation uses sampling (not exact like INFORMATION_SCHEMA)
    - No SHOW/DESCRIBE commands - uses sqlite_master and PRAGMA instead
    """
    
    def __init__(self, database_path: str | None = None):
        self._database_path = database_path or SQLITE_DATABASE_PATH
        self._engine = None
        self._connection = None
        self._connected = False
    
    @property
    def db_type(self) -> str:
        return "sqlite"
    
    def connect(self) -> bool:
        """Create SQLAlchemy engine with StaticPool."""
        if self._engine is not None:
            return True
        
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import StaticPool
            
            # Build SQLite URL
            # Handle both file paths and :memory:
            if self._database_path == ":memory:":
                database_url = "sqlite:///:memory:"
            else:
                database_url = f"sqlite:///{self._database_path}"
            
            # Create engine with StaticPool (single connection)
            # Reference: SQLAlchemy SQLite pooling docs
            # check_same_thread=False allows cross-thread usage
            self._engine = create_engine(
                database_url,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False}
            )
            self._connected = True
            logger.info(f"SQLite adapter connected to {self._database_path}")
            return True
            
        except Exception as e:
            logger.error(f"SQLite connection failed: {e}")
            return False
    
    def execute(self, sql: str, timeout: int | None = None, params: dict | None = None) -> list | str:
        """
        Execute SQL query with timeout protection via set_progress_handler.
        
        Timeout Mechanism:
        - set_progress_handler callback is invoked every N virtual machine ops
        - Callback checks elapsed time and returns 1 (interrupt) if exceeded
        - This provides query-level timeout without external threads
        
        Note: set_progress_handler is thread-safe and works with SQLAlchemy

        Args:
            sql: SQL query to execute
            timeout: Optional timeout in seconds (overrides default)
            params: Optional parameter dict for named-parameter binding
        """
        if not self._engine:
            if not self.connect():
                return "Error: Database engine could not be initialized."
        
        timeout = timeout if timeout is not None else QUERY_TIMEOUT_SECONDS
        
        try:
            from sqlalchemy import text
            
            with self._engine.connect() as connection:
                # Get raw sqlite3 connection for set_progress_handler
                raw_conn = connection.connection.dbapi_connection
                
                # Set up timeout handler
                start_time = time.time()
                
                def timeout_handler():
                    """Progress handler callback for query timeout."""
                    if time.time() - start_time > timeout:
                        return 1  # Interrupt query
                    return 0  # Continue
                
                # Install progress handler
                # N = number of VM instructions between callbacks
                # Lower N = more responsive but higher overhead
                raw_conn.set_progress_handler(timeout_handler, SQLITE_PROGRESS_HANDLER_INTERVAL)
                
                try:
                    if params:
                        result = connection.execute(text(sql), params)
                    else:
                        result = connection.execute(text(sql))
                    rows = result.fetchall()
                    return rows
                finally:
                    # Remove progress handler after query
                    raw_conn.set_progress_handler(None, 0)
                
        except sqlite3.OperationalError as e:
            error_str = str(e)
            if "interrupted" in error_str.lower():
                return f"Error: Query timeout exceeded ({timeout}s limit)"
            return self._handle_error(e)
        except Exception as e:
            return self._handle_error(e)

    def execute_write(self, sql: str, params: dict, timeout: int | None = None) -> dict:
        """
        Execute a parameterized write SQL within a SQLite transaction.

        Uses set_progress_handler for timeout, connection.begin() for explicit
        transaction (auto-commit on success, auto-rollback on exception).
        Exceptions propagate to caller (MutationBase) for error sanitization.
        """
        if not self._engine:
            if not self.connect():
                raise RuntimeError("Database engine could not be initialized.")

        timeout = timeout if timeout is not None else QUERY_TIMEOUT_SECONDS

        from sqlalchemy import text

        with self._engine.begin() as connection:
            raw_conn = connection.connection.dbapi_connection
            start_time = time.time()

            def timeout_handler():
                if time.time() - start_time > timeout:
                    return 1
                return 0

            raw_conn.set_progress_handler(timeout_handler, SQLITE_PROGRESS_HANDLER_INTERVAL)
            try:
                result = connection.execute(text(sql), params)
                return {"success": True, "rowcount": result.rowcount}
            finally:
                raw_conn.set_progress_handler(None, 0)

    def _handle_error(self, e: Exception, timeout: int | None = None) -> str:
        """
        Sanitize error messages for security.

        Args:
            e: The exception that occurred
            timeout: Optional timeout value (ignored for SQLite, kept for
                     signature consistency with MySQLAdapter)
        """
        error_str = str(e)
        logger.warning(f"SQLite execution error: {error_str[:200]}")
        
        if "no such table" in error_str.lower():
            return "Error: Table or column not found"
        elif "syntax error" in error_str.lower():
            return "Error: SQL syntax error"
        elif "database is locked" in error_str.lower():
            return "Error: Database is locked"
        elif "readonly" in error_str.lower() or "read-only" in error_str.lower():
            return "Error: Database is read-only"
        else:
            return "Error: Database query failed"
    
    def get_tables(self) -> list[dict[str, Any]]:
        """
        Get all tables from sqlite_master.
        
        Note: SQLite doesn't have INFORMATION_SCHEMA, uses sqlite_master instead.
        Row counts are estimated via sampling strategy.
        """
        sql = """
            SELECT name as table_name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        result = self.execute(sql)
        
        if isinstance(result, str):
            logger.error(f"Failed to get tables: {result}")
            return []
        
        tables = []
        for row in result:
            table_name = row[0]
            row_count = self.get_row_estimate(table_name)
            tables.append({"table_name": table_name, "row_count": row_count})
        
        return tables
    
    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """
        Get column information using PRAGMA table_info.
        
        PRAGMA table_info returns:
        (cid, name, type, notnull, dflt_value, pk)
        """
        sql = f"PRAGMA table_info({table_name})"
        result = self.execute(sql)
        
        if isinstance(result, str):
            logger.error(f"Failed to get columns for {table_name}: {result}")
            return []
        
        columns = []
        for row in result:
            # Map SQLite PRAGMA output to consistent format
            columns.append({
                "column_name": row[1],
                "data_type": row[2] or "TEXT",  # SQLite allows empty type
                "nullable": "NO" if row[3] else "YES",
                "key_type": "PRI" if row[5] else "",
                "default_value": row[4]
            })
        
        return columns
    
    def get_row_estimate(self, table_name: str) -> int:
        """
        Estimate row count using sampling strategy.
        
        Strategy:
        1. First try sqlite_stat1 if ANALYZE has been run
        2. Fallback to limited COUNT with sampling
        
        This avoids full table scan for large tables.
        
        Design Decision:
        - Use sample-based estimation for performance
        - sqlite_stat1 is preferred when available (populated by ANALYZE)
        - Fallback counts up to 10000 rows and extrapolates
        """
        # Try sqlite_stat1 first (if ANALYZE has been run)
        # First check if sqlite_stat1 exists to avoid error logging
        check_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
        check_result = self.execute(check_sql)
        
        if not isinstance(check_result, str) and check_result:
            # sqlite_stat1 exists, query it
            stat_sql = f"SELECT stat FROM sqlite_stat1 WHERE tbl = '{table_name}' LIMIT 1"
            stat_result = self.execute(stat_sql)
            
            if not isinstance(stat_result, str) and stat_result:
                # sqlite_stat1.stat format: "row_count col1_distinct col2_distinct ..."
                try:
                    stat_str = stat_result[0][0]
                    if stat_str:
                        row_count = int(stat_str.split()[0])
                        return row_count
                except (ValueError, IndexError):
                    pass
        
        # Fallback: Sample-based estimation
        # Count first 10000 rows, then check if more exist
        sample_sql = f"SELECT COUNT(*) FROM (SELECT 1 FROM {table_name} LIMIT 10000)"
        sample_result = self.execute(sample_sql)
        
        if isinstance(sample_result, str) or not sample_result:
            return 0
        
        sample_count = sample_result[0][0] or 0
        
        if sample_count < 10000:
            # Table has fewer than 10000 rows - return exact count
            return sample_count
        
        # Table has 10000+ rows - get exact count for accuracy
        # Note: For very large tables, this could be slow
        # Future optimization: Use ROWID estimation
        count_sql = f"SELECT COUNT(*) FROM {table_name}"
        count_result = self.execute(count_sql)
        
        if isinstance(count_result, str) or not count_result:
            return sample_count  # Return sample if full count fails
        
        return count_result[0][0] or sample_count
    
    def check_connection(self) -> tuple[bool, str]:
        """Check SQLite connection status."""
        result = self.execute("SELECT 1")
        
        if isinstance(result, str):
            return False, result
        
        return True, "SQLite connection successful"
    
    def get_database_name(self) -> str | None:
        """
        Get database name (file path for SQLite).
        
        For :memory: databases, returns ':memory:'.
        For file databases, returns the file path.
        """
        return self._database_path
    
    def close(self) -> None:
        """Dispose SQLAlchemy engine."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._connected = False
            logger.info("SQLite adapter closed")


# =============================================================================
# Factory Function
# =============================================================================

def create_adapter(db_type: str | None = None) -> DatabaseAdapter:
    """
    Create appropriate database adapter based on configuration.
    
    Args:
        db_type: Database type override ('mysql' or 'sqlite').
                 If None, uses DB_TYPE environment variable.
    
    Returns:
        DatabaseAdapter instance (MySQLAdapter or SQLiteAdapter)
    
    Raises:
        ValueError: If unsupported database type is specified
    
    Example:
        adapter = create_adapter()  # Uses DB_TYPE env var
        adapter = create_adapter('sqlite')  # Force SQLite
    """
    db_type = (db_type or DB_TYPE).lower()
    
    if db_type == "mysql":
        logger.info("Creating MySQL adapter")
        adapter = MySQLAdapter()
        adapter.connect()
        return adapter
    
    elif db_type == "sqlite":
        logger.info(f"Creating SQLite adapter for {SQLITE_DATABASE_PATH}")
        adapter = SQLiteAdapter(SQLITE_DATABASE_PATH)
        adapter.connect()
        return adapter
    
    else:
        raise ValueError(
            f"Unsupported database type: {db_type}. "
            "Supported types: mysql, sqlite"
        )


# =============================================================================
# Global Adapter Instance
# =============================================================================

# Create global adapter instance on module load
# This maintains backward compatibility with existing execute_sql() usage
_adapter: DatabaseAdapter | None = None


def get_adapter() -> DatabaseAdapter:
    """
    Get or create the global database adapter.
    
    Returns:
        The global DatabaseAdapter instance
    """
    global _adapter
    if _adapter is None:
        _adapter = create_adapter()
    return _adapter


def reset_adapter() -> None:
    """
    Reset the global adapter (for testing or reconfiguration).
    
    Closes existing connection and clears the global instance.
    """
    global _adapter
    if _adapter is not None:
        _adapter.close()
        _adapter = None
