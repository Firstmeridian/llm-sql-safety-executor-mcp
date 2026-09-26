from __future__ import annotations
import asyncio
import logging
from typing import Any
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

from .models import DatabaseConfig
from .base import DatabaseAdapter
from .outcomes import (
    MetadataQueryError,
    WriteExecutionOutcome,
    WriteExecutionPhase,
    WriteExecutionResult,
    WriteExecutionError,
    ExpectedRowcountMismatchError,
    _validate_expected_rowcount,
    _rollback_outcome,
    _precommit_failure_error_code,
    _close_write_connection,
)
from .identifiers import _adapter_logging_name, _metadata_identifier_is_rejected


class MySQLAdapter(DatabaseAdapter):
    """
    MySQL database adapter using SQLAlchemy with PyMySQL driver.

    Features:
    - Connection pooling with QueuePool
    - Read-query timeout via MAX_EXECUTION_TIME + connection timeouts
    - Mutation row-lock wait timeout via innodb_lock_wait_timeout
    - INFORMATION_SCHEMA for metadata queries

    Backward Compatibility:
    - Preserves all existing MySQL behavior from sql_safety_checker.py
    - Uses same connection parameters and timeout settings
    """

    def __init__(self, config: DatabaseConfig, *, diagnostic: bool = False):
        self._diagnostic = diagnostic
        self._config = config
        if self._config.db_type != "mysql":
            raise ValueError("MySQLAdapter requires a mysql DatabaseConfig")
        self._engine: Engine | None = None
        self._connection_id = self._config.connection_id
        self._db_user = self._config.mysql_user
        self._db_password = (
            self._config.mysql_password.get_secret_value()
            if self._config.mysql_password is not None
            else None
        )
        self._db_host = self._config.mysql_host
        self._db_name = self._config.mysql_database
        self._query_timeout_seconds = self._config.query_timeout_seconds
        self._connect_timeout_seconds = self._config.connect_timeout_seconds
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
            from sqlalchemy.engine import URL
            from sqlalchemy.pool import NullPool

            # Build URL structurally so special characters in credentials are
            # escaped by SQLAlchemy instead of hand-built string interpolation.
            database_url = URL.create(
                "mysql+pymysql",
                username=self._db_user,
                password=self._db_password,
                host=self._db_host,
                database=self._db_name,
                query={"charset": "utf8mb4"},
            )

            # Create engine with connection pooling
            # Reference: SQLAlchemy QueuePool for MySQL
            self._engine = create_engine(
                database_url,
                pool_pre_ping=True,  # Verify connection before use
                **(
                    {"poolclass": NullPool}
                    if self._diagnostic
                    else {
                        "pool_size": 5,
                        "max_overflow": 10,
                        "pool_timeout": 30,
                    }
                ),
                hide_parameters=True,
                logging_name=_adapter_logging_name(
                    "mysql_adapter", self._connection_id
                ),
                pool_logging_name=_adapter_logging_name(
                    "mysql_adapter_pool", self._connection_id
                ),
                connect_args={
                    "connect_timeout": self._connect_timeout_seconds,
                    "read_timeout": self._query_timeout_seconds,
                    "write_timeout": self._query_timeout_seconds,
                },
            )
            self._connected = True
            logger.info(
                "MySQL adapter connected (connection_id=%s)", self._connection_id
            )
            return True

        except ImportError:
            logger.error("PyMySQL not installed. Run: pip install PyMySQL")
            return False
        except Exception as e:
            logger.error("MySQL connection failed: %s", e.__class__.__name__)
            return False

    def execute(
        self, sql: str, timeout: int | None = None, params: dict | None = None
    ) -> list | str:
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
        engine = self._engine
        if engine is None:
            return "Error: Database engine could not be initialized."

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError

            with engine.connect() as connection:
                # Set session-level query timeout for MySQL
                # MAX_EXECUTION_TIME is in milliseconds
                timeout_ms = timeout * 1000
                try:
                    connection.execute(
                        text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}")
                    )
                except SQLAlchemyError:
                    # Fallback: Some MySQL versions may not support MAX_EXECUTION_TIME
                    logger.debug(
                        "MAX_EXECUTION_TIME not supported, using connection timeout"
                    )

                if params:
                    result = connection.execute(text(sql), params)
                else:
                    result = connection.execute(text(sql))
                rows = list(result.fetchall())
                return rows

        except Exception as e:
            return self._handle_error(e, timeout)

    def execute_write(
        self,
        sql: str,
        params: dict,
        timeout: int | None = None,
        *,
        expected_rowcount: int | None = None,
    ) -> dict:
        """Execute one parameterized write with explicit transaction evidence.

        The optional row-count invariant is checked before COMMIT. A COMMIT
        exception is always classified as unknown, even if a subsequent
        rollback call returns normally, because the server may already have
        made the transaction durable before the acknowledgement was lost.
        """
        _validate_expected_rowcount(expected_rowcount)
        if not self._engine:
            if not self.connect():
                raise WriteExecutionError(
                    "Database engine could not be initialized.",
                    execution_outcome=WriteExecutionOutcome.NOT_EXECUTED,
                    phase=WriteExecutionPhase.SETUP,
                    error_code="database_execution_failed",
                )
        engine = self._engine
        if engine is None:
            raise WriteExecutionError(
                "Database engine could not be initialized.",
                execution_outcome=WriteExecutionOutcome.NOT_EXECUTED,
                phase=WriteExecutionPhase.SETUP,
                error_code="database_execution_failed",
            )

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        connection = None
        transaction = None
        business_write_attempted = False
        phase = WriteExecutionPhase.SETUP
        try:
            connection = engine.connect()
            transaction = connection.begin()
            lock_wait_timeout = max(1, int(timeout))
            try:
                connection.execute(
                    text("SET SESSION innodb_lock_wait_timeout = :timeout_seconds"),
                    {"timeout_seconds": lock_wait_timeout},
                )
            except SQLAlchemyError as exc:
                logger.warning(
                    "Failed to configure MySQL mutation lock-wait timeout: %s",
                    exc.__class__.__name__,
                )
                raise RuntimeError(
                    "MySQL mutation lock-wait timeout could not be configured."
                ) from exc

            phase = WriteExecutionPhase.EXECUTE
            business_write_attempted = True
            result = connection.execute(text(sql), params)
            rowcount = result.rowcount

            phase = WriteExecutionPhase.ROWCOUNT_CHECK
            if expected_rowcount is not None and rowcount != expected_rowcount:
                raise ExpectedRowcountMismatchError(
                    expected_rowcount=expected_rowcount,
                    actual_rowcount=rowcount,
                    execution_outcome=WriteExecutionOutcome.UNKNOWN,
                )
        except BaseException as error:
            if transaction is None:
                outcome = WriteExecutionOutcome.NOT_EXECUTED
                rollback_error = None
            else:
                outcome, rollback_error = _rollback_outcome(
                    transaction,
                    connection=connection,
                    business_write_attempted=business_write_attempted,
                )
            _close_write_connection(connection)
            if not isinstance(error, Exception):
                raise
            if isinstance(error, ExpectedRowcountMismatchError):
                raise ExpectedRowcountMismatchError(
                    expected_rowcount=error.expected_rowcount,
                    actual_rowcount=error.actual_rowcount,
                    execution_outcome=outcome,
                    original_error=rollback_error,
                ) from error
            raise WriteExecutionError(
                "Parameterized write failed before COMMIT.",
                execution_outcome=outcome,
                phase=phase,
                error_code=_precommit_failure_error_code(outcome, rollback_error),
                original_error=rollback_error or error,
            ) from error

        phase = WriteExecutionPhase.COMMIT
        active_transaction = transaction
        assert active_transaction is not None
        try:
            active_transaction.commit()
        except BaseException as error:
            # Cleanup after a failed COMMIT acknowledgement is not evidence
            # that the server did not commit.
            try:
                active_transaction.rollback()
            except BaseException as rollback_error:
                logger.warning(
                    "Rollback cleanup after uncertain COMMIT failed: %s",
                    rollback_error.__class__.__name__,
                )
            _close_write_connection(connection)
            # Cancellation during COMMIT has the same acknowledgement
            # ambiguity as a connection exception. Convert it to typed
            # `unknown` evidence when execution can still return a result;
            # preserve other process-control BaseExceptions after cleanup.
            if not isinstance(error, (Exception, asyncio.CancelledError)):
                raise
            raise WriteExecutionError(
                "Database COMMIT acknowledgement failed.",
                execution_outcome=WriteExecutionOutcome.UNKNOWN,
                phase=phase,
                error_code="commit_outcome_unknown",
                original_error=error,
            ) from error

        _close_write_connection(connection)
        return WriteExecutionResult(rowcount)

    def _handle_error(self, e: Exception, timeout: int | None = None) -> str:
        """
        Sanitize error messages for security.

        Preserves original error handling logic from sql_safety_checker.py.

        Args:
            e: The exception that occurred
            timeout: Optional timeout value for error message context
        """
        error_str = str(e)
        logger.warning("SQL execution error: %s", e.__class__.__name__)

        timeout_suffix = f" ({timeout}s limit)" if timeout is not None else ""

        if "Access denied" in error_str or "permission" in error_str.lower():
            return "Error: Access denied"
        elif "doesn't exist" in error_str or "Unknown table" in error_str:
            return "Error: Table or column not found"
        elif "syntax" in error_str.lower():
            return "Error: SQL syntax error"
        elif (
            "timeout" in error_str.lower() or "max_execution_time" in error_str.lower()
        ):
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
            logger.error("Failed to list MySQL tables")
            raise MetadataQueryError("listing tables")

        return [{"table_name": row[0], "row_count": row[1]} for row in result]

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """Get column information from INFORMATION_SCHEMA."""
        if _metadata_identifier_is_rejected(table_name):
            return []

        sql = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
            ORDER BY ORDINAL_POSITION
        """
        result = self.execute(sql, params={"table_name": table_name})

        if isinstance(result, str):
            logger.error("Failed to read MySQL column metadata")
            raise MetadataQueryError("reading table columns")

        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "nullable": row[2],
                "key_type": row[3],
                "default_value": row[4],
            }
            for row in result
        ]

    def get_row_estimate(self, table_name: str) -> int | None:
        """Get row count estimate from INFORMATION_SCHEMA.TABLES."""
        if _metadata_identifier_is_rejected(table_name):
            return None

        sql = """
            SELECT TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
        """
        result = self.execute(sql, params={"table_name": table_name})

        if isinstance(result, str):
            logger.error("Failed to read MySQL row estimate metadata")
            raise MetadataQueryError("estimating table rows")
        if not result:
            return None

        row_count = result[0][0]
        return None if row_count is None else int(row_count)

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
            logger.info("MySQL adapter closed (connection_id=%s)", self._connection_id)
