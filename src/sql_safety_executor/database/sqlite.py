from __future__ import annotations
import asyncio
import time
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast
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
from .identifiers import (
    _adapter_logging_name,
    _metadata_identifier_is_rejected,
    _quote_sqlite_identifier,
)


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
        - StaticPool keeps a single process-local connection; SQLite file-level
            write locks still apply when mutation skills are enabled
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

    def __init__(self, *, config: DatabaseConfig, diagnostic: bool = False):
        self._diagnostic = diagnostic
        self._config = config
        if self._config.db_type != "sqlite":
            raise ValueError("SQLiteAdapter requires a sqlite DatabaseConfig")
        self._connection_id = self._config.connection_id
        database_path = self._config.sqlite_database_path
        if not database_path:
            raise ValueError("SQLite path is required")
        self._database_path: str = database_path
        self._query_timeout_seconds = self._config.query_timeout_seconds
        self._progress_handler_interval = self._config.sqlite_progress_handler_interval
        self._engine: Engine | None = None
        self._connection = None
        self._connected = False

    @property
    def db_type(self) -> str:
        return "sqlite"

    def connect(self) -> bool:
        """Create a business StaticPool or a disposable diagnostic NullPool."""
        if self._engine is not None:
            return True

        try:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import NullPool, StaticPool
            from sqlalchemy.engine import URL

            # Build SQLite URL
            # Handle both file paths and :memory:
            if self._database_path == ":memory:":
                database_url = "sqlite:///:memory:"
            elif self._diagnostic:
                # as_uri encodes ?, #, %, spaces and Unicode as filename data.
                # mode=ro prevents a connectivity check from creating a database.
                # WAL auxiliary files may still require filesystem writes.
                database_url = URL.create(
                    "sqlite",
                    database=Path(self._database_path).absolute().as_uri(),
                    query={"mode": "ro", "uri": "true"},
                )
            else:
                database_url = f"sqlite:///{self._database_path}"

            # Business checkouts share StaticPool; diagnostic checkouts use NullPool.
            # Reference: SQLAlchemy SQLite pooling docs
            # Only business connections enable cross-thread usage.
            self._engine = create_engine(
                database_url,
                poolclass=NullPool if self._diagnostic else StaticPool,
                connect_args=(
                    {
                        "timeout": self._config.connect_timeout_seconds,
                    }
                    if self._diagnostic
                    else {"check_same_thread": False}
                ),
                hide_parameters=True,
                logging_name=_adapter_logging_name(
                    "sqlite_adapter", self._connection_id
                ),
                pool_logging_name=_adapter_logging_name(
                    "sqlite_adapter_pool", self._connection_id
                ),
            )
            self._connected = True
            logger.info(
                "SQLite adapter connected (connection_id=%s)", self._connection_id
            )
            return True

        except Exception as e:
            logger.error("SQLite connection failed: %s", e.__class__.__name__)
            return False

    def execute(
        self, sql: str, timeout: int | None = None, params: dict | None = None
    ) -> list | str:
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
        engine = self._engine
        if engine is None:
            return "Error: Database engine could not be initialized."

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        try:
            from sqlalchemy import text

            with engine.connect() as connection:
                # Get raw sqlite3 connection for set_progress_handler
                raw_conn = connection.connection.dbapi_connection
                if raw_conn is None:
                    return "Error: Database engine could not be initialized."
                sqlite_conn = cast(sqlite3.Connection, raw_conn)

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
                sqlite_conn.set_progress_handler(
                    timeout_handler, self._progress_handler_interval
                )

                try:
                    if params:
                        result = connection.execute(text(sql), params)
                    else:
                        result = connection.execute(text(sql))
                    rows = list(result.fetchall())
                    return rows
                finally:
                    # Remove progress handler after query
                    sqlite_conn.set_progress_handler(None, 0)

        except sqlite3.OperationalError as e:
            return self._handle_error(e, timeout)
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
        """Execute one parameterized SQLite write with transaction evidence."""
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

        connection = None
        transaction = None
        sqlite_conn: sqlite3.Connection | None = None
        handler_installed = False
        business_write_attempted = False
        phase = WriteExecutionPhase.SETUP
        try:
            connection = engine.connect()
            transaction = connection.begin()
            raw_conn = connection.connection.dbapi_connection
            if raw_conn is None:
                raise RuntimeError("Database engine could not be initialized.")
            sqlite_conn = cast(sqlite3.Connection, raw_conn)
            start_time = time.time()

            def timeout_handler():
                if time.time() - start_time > timeout:
                    return 1
                return 0

            sqlite_conn.set_progress_handler(
                timeout_handler,
                self._progress_handler_interval,
            )
            handler_installed = True
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

            # Handler cleanup is pre-COMMIT: cleanup failure remains safely
            # rollback-capable rather than being reported after a commit.
            sqlite_conn.set_progress_handler(None, 0)
            handler_installed = False
        except BaseException as error:
            if handler_installed and sqlite_conn is not None:
                try:
                    sqlite_conn.set_progress_handler(None, 0)
                except BaseException as handler_error:
                    logger.warning(
                        "SQLite progress handler cleanup failed: %s",
                        handler_error.__class__.__name__,
                    )
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
            try:
                active_transaction.rollback()
            except BaseException as rollback_error:
                logger.warning(
                    "Rollback cleanup after uncertain COMMIT failed: %s",
                    rollback_error.__class__.__name__,
                )
            _close_write_connection(connection)
            # See the MySQL path: COMMIT cancellation is typed as unknown;
            # unrelated process-control exceptions still propagate.
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

        Args:
            e: The exception that occurred
            timeout: Optional timeout value (ignored for SQLite, kept for
                     signature consistency with MySQLAdapter)
        """
        error_str = str(e)
        logger.warning("SQLite execution error: %s", e.__class__.__name__)

        if "interrupted" in error_str.lower():
            timeout_suffix = f" ({timeout}s limit)" if timeout is not None else ""
            return f"Error: Query timeout exceeded{timeout_suffix}"
        elif "no such table" in error_str.lower():
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
        Row counts are estimated via sqlite_stat1 or bounded sampling.
        """
        sql = """
            SELECT name as table_name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
        result = self.execute(sql)

        if isinstance(result, str):
            logger.error("Failed to list SQLite tables")
            raise MetadataQueryError("listing tables")

        tables = []
        for row in result:
            table_name = row[0]
            # Discovery can safely return an unusual table name, but the
            # conservative identifier grammar intentionally prevents using it
            # in generated metadata SQL. Preserve the table and mark its row
            # estimate unknown instead of misreporting it as an empty table.
            row_count = (
                None
                if _metadata_identifier_is_rejected(table_name)
                else self.get_row_estimate(table_name)
            )
            tables.append({"table_name": table_name, "row_count": row_count})

        return tables

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """
        Get column information using PRAGMA table_info.

        PRAGMA table_info returns:
        (cid, name, type, notnull, dflt_value, pk)
        """
        if _metadata_identifier_is_rejected(table_name):
            return []

        quoted_table_name = _quote_sqlite_identifier(table_name)
        sql = f"PRAGMA table_info({quoted_table_name})"
        result = self.execute(sql)

        if isinstance(result, str):
            logger.error("Failed to read SQLite column metadata")
            raise MetadataQueryError("reading table columns")

        columns = []
        for row in result:
            # Map SQLite PRAGMA output to consistent format
            columns.append(
                {
                    "column_name": row[1],
                    "data_type": row[2] or "TEXT",  # SQLite allows empty type
                    "nullable": "NO" if row[3] else "YES",
                    "key_type": "PRI" if row[5] else "",
                    "default_value": row[4],
                }
            )

        return columns

    def get_row_estimate(self, table_name: str) -> int | None:
        """
        Estimate row count using sqlite_stat1 or bounded sampling.

        Strategy:
        1. First try sqlite_stat1 if ANALYZE has been run
        2. Fallback to bounded sampling

        This avoids full table scan for large tables.
        """
        if _metadata_identifier_is_rejected(table_name):
            return None

        # Try sqlite_stat1 first (if ANALYZE has been run)
        # First check if sqlite_stat1 exists to avoid error logging
        check_sql = (
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
        )
        check_result = self.execute(check_sql)

        if isinstance(check_result, str):
            logger.error("Failed to inspect SQLite statistics metadata")
            raise MetadataQueryError("estimating table rows")

        if check_result:
            # sqlite_stat1 exists, query it
            stat_sql = "SELECT stat FROM sqlite_stat1 WHERE tbl = :table_name LIMIT 1"
            stat_result = self.execute(stat_sql, params={"table_name": table_name})

            if isinstance(stat_result, str):
                logger.error("Failed to read SQLite statistics metadata")
                raise MetadataQueryError("estimating table rows")

            if stat_result:
                # sqlite_stat1.stat format: "row_count col1_distinct col2_distinct ..."
                try:
                    stat_str = stat_result[0][0]
                    if stat_str:
                        row_count = int(stat_str.split()[0])
                        return row_count
                except (ValueError, IndexError):
                    pass

        # Fallback: bounded sample-based estimation. This intentionally avoids
        # a full COUNT(*) on large tables; exact counts are opt-in elsewhere.
        sample_limit = 10000
        quoted_table_name = _quote_sqlite_identifier(table_name)
        sample_sql = f"SELECT COUNT(*) FROM (SELECT 1 FROM {quoted_table_name} LIMIT {sample_limit})"
        sample_result = self.execute(sample_sql)

        if isinstance(sample_result, str):
            if sample_result == "Error: Table or column not found":
                return None
            logger.error("Failed to sample SQLite table rows")
            raise MetadataQueryError("estimating table rows")
        if not sample_result:
            return 0

        sample_count = sample_result[0][0] or 0

        if sample_count < sample_limit:
            # Table has fewer than 10000 rows - return exact count
            return sample_count

        # Table has at least sample_limit rows. Return the lower-bound estimate
        # instead of upgrading metadata discovery into an expensive full count.
        return sample_count

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
            logger.info("SQLite adapter closed (connection_id=%s)", self._connection_id)
