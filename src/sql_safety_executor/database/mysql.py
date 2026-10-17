from __future__ import annotations
import asyncio
import logging
import time
from threading import RLock
from typing import Any
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

from .models import DatabaseConfig
from .base import DatabaseAdapter
from .errors import DatabaseQueryError, classify_database_error
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
from .identifiers import _adapter_logging_name
from .indexes import IndexMetadataBudget, MAX_INDEX_KEY_PARTS
from .relations import ReadRelation, RelationReference
from .semantics import DialectContext, mysql_modes
from .execution import operation_kind, operation_analysis
from .transport import statement_text

# Both definitions contain constants and the final SELECT has no FROM clause:
# the probe never names or reads a physical table, even on case-sensitive servers.
_CTE_CASE_PROBE = (
    "WITH `mcp_Cte_Case_A` AS (SELECT 1 AS n), "
    "`mcp_cte_case_a` AS (SELECT 2 AS n) SELECT 1 AS n"
)


class MySQLAdapter(DatabaseAdapter):
    """
    MySQL database adapter using SQLAlchemy with PyMySQL driver.

    Features:
    - Connection pooling with QueuePool
    - Read-query timeout via MAX_EXECUTION_TIME + connection timeouts
    - Mutation row-lock wait timeout via innodb_lock_wait_timeout
    - INFORMATION_SCHEMA for metadata queries

    Every physical connection enforces the adapter's full SQL-mode contract.
    Trusted arbitrary operations retire their session before pool reuse.
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
        self._cte_case_sensitive: bool | None = None
        self._cte_probe_lock = RLock()
        self._cte_probe_retry_after = 0.0
        self._session_modes: frozenset[str] | None = None
        self._session_mode_lock = RLock()

    @property
    def db_type(self) -> str:
        return "mysql"

    @property
    def metadata_schema(self) -> str:
        if self._db_name is None:
            raise ValueError("MySQL metadata requires a configured database")
        return self._db_name

    @property
    def cte_case_sensitive(self) -> bool | None:
        return self._cte_case_sensitive

    @property
    def analysis_context(self) -> DialectContext:
        modes = self._session_modes
        if modes is None:
            modes = mysql_modes(self._config.mysql_sql_mode)
        return DialectContext("mysql", modes, self.cte_case_sensitive is not False, self.metadata_schema)

    def resolve_analysis_context(self) -> DialectContext:
        if self._config.mysql_sql_mode is not None:
            # The initializer enforces this explicit contract before execution.
            return self.analysis_context
        if self._session_modes is None:
            if not self.connect() or self._engine is None:
                raise DatabaseQueryError("session_semantics_unavailable")
            try:
                with self._engine.connect():
                    pass
            except Exception:
                raise DatabaseQueryError("session_semantics_unavailable") from None
        if self._session_modes is None:
            raise DatabaseQueryError("session_semantics_unavailable")
        return self.analysis_context

    def _initialize_session(self, dbapi_connection, connection_record) -> None:
        """Enforce one complete mode set on every physical connection.

        Runs before SQLAlchemy's own dialect inspection. This is connection
        setup, never an Agent-requested SET or a per-query detection step.
        """
        with self._session_mode_lock:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SELECT @@SESSION.sql_mode")
                observed = mysql_modes(cursor.fetchone()[0])
                target = self._session_modes
                if target is None:
                    target = (mysql_modes(self._config.mysql_sql_mode)
                              if self._config.mysql_sql_mode is not None else observed)
                if observed != target:
                    cursor.execute("SET SESSION sql_mode = %s", (",".join(sorted(target)),))
                    cursor.execute("SELECT @@SESSION.sql_mode")
                    if mysql_modes(cursor.fetchone()[0]) != target:
                        raise DatabaseQueryError("session_semantics_unavailable")
                self._session_modes = target
                connection_record.info["sql_modes"] = target
            except Exception:
                raise DatabaseQueryError("session_semantics_unavailable") from None
            finally:
                cursor.close()

    def resolve_cte_case_sensitive(self) -> bool:
        """Measure ASCII CTE name comparison once, without any table access.

        Distinct names succeed on exact-comparison servers. MySQL 1066 and
        MariaDB 4004 identify a duplicate CTE name under insensitive comparison.
        Other failures do not relax policy; retry after 30 seconds. No capability
        is acquired during construction or ordinary unambiguous queries.
        """
        from sqlalchemy.exc import DBAPIError

        with self._cte_probe_lock:
            if self._cte_case_sensitive is not None:
                return self._cte_case_sensitive
            if time.monotonic() < self._cte_probe_retry_after:
                return True
            try:
                if not self.connect() or self._engine is None:
                    raise DatabaseQueryError("database_connection_failed")
                with self._engine.connect() as connection:
                    value = connection.exec_driver_sql(_CTE_CASE_PROBE).scalar_one()
                if type(value) is not int or value != 1:
                    raise DatabaseQueryError()
                self._cte_case_sensitive = True
            except DBAPIError as error:
                args = getattr(error.orig, "args", ())
                errno = args[0] if args and type(args[0]) is int else None
                if errno in {1066, 4004}:
                    self._cte_case_sensitive = False
                else:
                    self._cte_probe_retry_after = time.monotonic() + 30
                    logger.warning("CTE case capability unavailable: %s", type(error).__name__)
            except Exception as error:
                self._cte_probe_retry_after = time.monotonic() + 30
                logger.warning("CTE case capability unavailable: %s", type(error).__name__)
            return self._cte_case_sensitive is not False

    def connect(self) -> bool:
        """Create SQLAlchemy engine with connection pool."""
        if self._engine is not None:
            return True

        try:
            from sqlalchemy import create_engine, event
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
            event.listen(self._engine, "connect", self._initialize_session, insert=True)
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
        self, sql: str, timeout: int | float | None = None, params: dict | None = None
    ) -> list:
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
                raise DatabaseQueryError("database_connection_failed")
        engine = self._engine
        if engine is None:
            raise DatabaseQueryError("database_connection_failed")

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError

            with engine.connect() as connection:
                # Set session-level query timeout for MySQL
                # MAX_EXECUTION_TIME is in milliseconds
                # A fractional remaining metadata budget still needs a valid,
                # nonzero integer millisecond server timeout.
                timeout_ms = max(1, int(timeout * 1000))
                try:
                    connection.execute(
                        text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}")
                    )
                except SQLAlchemyError:
                    # Fallback: Some MySQL versions may not support MAX_EXECUTION_TIME
                    logger.debug(
                        "MAX_EXECUTION_TIME not supported, using connection timeout"
                    )

                try:
                    if params:
                        result = connection.execute(statement_text(sql, self.analysis_context, operation_analysis()), params)
                    else:
                        result = connection.execute(statement_text(sql, self.analysis_context, operation_analysis()))
                    rows = list(result.fetchall())
                    return rows
                finally:
                    if operation_kind() == "trusted":
                        # Arbitrary trusted callbacks may change session mode
                        # or create temporary objects. Their physical session
                        # must not re-enter the controlled-read pool.
                        connection.invalidate()

        except Exception as e:
            raise self._handle_error(e, timeout) from None

    def execute_read(self, sql, timeout=None, params=None, *, policy=None, analysis=None) -> list:
        from sql_safety_executor.core.analysis import analyze_sql
        if policy is None:
            raise ValueError("A read operation requires an explicit connection policy")
        if policy.read_mode == "deny" or policy.read_mode == "allowlist" and not policy.allowed_tables:
            raise DatabaseQueryError("read_disabled")
        context = self.resolve_analysis_context()
        analysis = analysis or analyze_sql(sql, context)
        if not analysis.complete or analysis.context_key != context.fingerprint:
            raise DatabaseQueryError("session_semantics_unavailable")
        if analysis.statement_kind not in {"select", "explain"}:
            raise DatabaseQueryError("read_only_required")
        return super().execute_read(sql, timeout, params, policy=policy, analysis=analysis)

    def _retire_write_connection(self, connection) -> None:
        # Outcome has already been determined. Cleanup must not invent a
        # rollback or change committed/unknown evidence.
        if connection is not None:
            try:
                connection.invalidate()
            except Exception as error:
                logger.warning("MySQL session retirement failed: %s", type(error).__name__)
        _close_write_connection(connection)

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
            result = connection.execute(statement_text(sql, self.analysis_context), params)
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
            self._retire_write_connection(connection)
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
            self._retire_write_connection(connection)
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

        self._retire_write_connection(connection)
        return WriteExecutionResult(rowcount)

    def _handle_error(self, e: Exception, timeout: int | float | None = None) -> DatabaseQueryError:
        logger.warning("mysql execution error: %s", e.__class__.__name__)
        return classify_database_error(e, "mysql")

    def get_tables(self) -> list[dict[str, Any]]:
        """Get all tables with row count estimates from INFORMATION_SCHEMA."""
        sql = """
            SELECT 
                TABLE_NAME as table_name, 
                TABLE_ROWS as row_count
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = :schema_name AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        result = self._execute_metadata(sql, 'listing tables', params={"schema_name": self.metadata_schema})


        return [{"table_name": row[0], "row_count": row[1]} for row in result]

    def get_read_relations(self) -> list[ReadRelation]:
        rows = self._execute_metadata(
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = :schema_name AND TABLE_TYPE IN ('BASE TABLE', 'VIEW') "
            "ORDER BY TABLE_NAME",
            "observing read relations", params={"schema_name": self.metadata_schema},
        )
        return [ReadRelation(RelationReference(row[0], self.metadata_schema),
                            "view" if row[1] == "VIEW" else "table") for row in rows]

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """Get column information from INFORMATION_SCHEMA."""
        if not self.valid_metadata_identifier(table_name):
            return []

        sql = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :schema_name AND TABLE_NAME = :table_name
            ORDER BY ORDINAL_POSITION
        """
        result = self._execute_metadata(sql, 'reading table columns', params={"schema_name": self.metadata_schema, "table_name": table_name})


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

    def get_indexes(self, table_name: str) -> list[dict[str, Any]]:
        """Get bounded index structure, preserving unknown legacy visibility."""
        if not self.valid_metadata_identifier(table_name):
            raise MetadataQueryError("reading table indexes")
        budget = IndexMetadataBudget(self._query_timeout_seconds)
        # MySQL 5.7 has no IS_VISIBLE. Probe the metadata column, not a version
        # string. A failed probe fails collection; errors are never interpreted
        # as proof that this is an old server, nor retried with weaker metadata.
        visibility_rows = budget.rows(
            self._execute_metadata(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = 'information_schema' "
                "AND TABLE_NAME = 'STATISTICS' AND COLUMN_NAME = 'IS_VISIBLE' LIMIT 1", 'reading table indexes',
                timeout=budget.remaining(),
            )
        )
        visibility_column = "IS_VISIBLE" if visibility_rows else "NULL AS IS_VISIBLE"
        # CARDINALITY is not selected: reading it can refresh cached statistics.
        sql = f"""
            SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, INDEX_TYPE,
                   SUB_PART, COLLATION, {visibility_column}
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = :schema_name AND TABLE_NAME = :table_name
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
            LIMIT :row_limit
        """
        result = budget.rows(
            self._execute_metadata(
                sql, 'reading table indexes',
                timeout=budget.remaining(),
                params={"schema_name": self.metadata_schema, "table_name": table_name, "row_limit": MAX_INDEX_KEY_PARTS + 1},
            )
        )

        indexes: dict[str, dict[str, Any]] = {}
        for (
            name, non_unique, _seq, column, index_type, prefix_length, direction, visible
        ) in result:
            index = indexes.setdefault(
                name,
                {
                    "name": name,
                    "primary": name == "PRIMARY",
                    "unique": int(non_unique) == 0,
                    "columns": [],
                    "key_parts": [],
                    "visible": {"YES": True, "NO": False}.get(visible),
                },
            )
            index["columns"].append(column)
            index["key_parts"].append(
                {
                    "column": column,
                    "prefix_length": None if prefix_length is None else int(prefix_length),
                    "sort_order": {"A": "asc", "D": "desc"}.get(direction),
                }
            )
            if column is None:
                index["has_expression"] = True
            if index_type and str(index_type).upper() != "BTREE":
                index["type"] = str(index_type).upper()
        return budget.finish(
            sorted(indexes.values(), key=lambda item: (not item["primary"], item["name"]))
        )

    def get_row_estimate(self, table_name: str) -> int | None:
        """Get row count estimate from INFORMATION_SCHEMA.TABLES."""
        if not self.valid_metadata_identifier(table_name):
            return None

        sql = """
            SELECT TABLE_ROWS
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = :schema_name AND TABLE_NAME = :table_name
        """
        result = self._execute_metadata(sql, 'estimating table rows', params={"schema_name": self.metadata_schema, "table_name": table_name})

        if not result:
            return None

        row_count = result[0][0]
        return None if row_count is None else int(row_count)

    def check_connection(self) -> tuple[bool, str]:
        """Check MySQL connection status."""
        try:
            self.execute("SELECT 1")
        except DatabaseQueryError as error:
            return False, str(error)

        return True, "MySQL connection successful"

    def get_database_name(self) -> str | None:
        """Get current database name."""
        try:
            result = self.execute("SELECT DATABASE()")
        except DatabaseQueryError:
            return self._db_name

        if not result:
            return self._db_name

        return result[0][0]

    def close(self) -> None:
        """Dispose SQLAlchemy engine."""
        self._cte_case_sensitive = None
        self._cte_probe_retry_after = 0.0
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._connected = False
            logger.info("MySQL adapter closed (connection_id=%s)", self._connection_id)
