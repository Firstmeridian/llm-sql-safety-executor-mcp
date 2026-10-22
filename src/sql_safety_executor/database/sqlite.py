from __future__ import annotations
import asyncio
import time
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast
from threading import RLock
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

from .models import ConnectionPolicy, DatabaseConfig
from .base import DatabaseAdapter
from .errors import DatabaseQueryError, classify_database_error
from .indexes import IndexMetadataBudget, MAX_INDEXES, MAX_INDEX_KEY_PARTS
from .relations import ReadRelation, RelationReference, SQLiteJSONNameObservation, render_relation
from .authorizer import SQLiteReadGuard, build_read_guard
from .execution import exclusive_connection, operation_scope
from .transport import statement_text
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
    ascii_identifier_lower,
)

# Internal names have the literal sqlite_ prefix. LIKE's unescaped underscore
# would also hide legitimate sqliteX... names. Keep both directories aligned.
_PUBLIC_RELATION_FILTER = "substr(name, 1, 7) COLLATE NOCASE != 'sqlite_'"
_JSON_NAME_SCHEMA_LIMIT = 32
# SQLite index b-trees may include both keys and WITHOUT ROWID auxiliary
# columns. Bound raw PRAGMA rows separately from the public key-part budget.
_PRAGMA_ROW_LIMIT = 65536


def _stat_row_count(stat: Any) -> int | None:
    """The first stat1 integer is cardinality only after source verification."""
    parts = stat.split() if isinstance(stat, str) else []
    if parts:
        try:
            value = int(parts[0])
            if value >= 0:
                return value
        except ValueError:
            pass
    return None


def _sqlite_dml_needs_count(sql: str, context) -> bool:
    """Identify a DML root only when sqlite3 cannot report its row count.

    This uses the existing dialect lexer, not read policy or a second AST
    validator. SQL has already executed as one statement inside our transaction.
    Ignore empty prefixes and CTE bodies/declaration names; SELECT, EXPLAIN and
    DDL must never inherit changes() from a previous business statement.
    """
    from sql_safety_executor.core.analysis import _tokens
    from sqlglot.tokenizer_core import TokenType

    _, raw_tokens = _tokens(sql, context)
    tokens = [token for token in raw_tokens if token.token_type != TokenType.HINT]
    first = next((i for i, token in enumerate(tokens)
                  if token.token_type != TokenType.SEMICOLON), None)
    if first is None:
        return False
    dml = {TokenType.INSERT, TokenType.UPDATE, TokenType.DELETE, TokenType.REPLACE}
    if tokens[first].token_type != TokenType.WITH:
        return tokens[first].token_type in dml
    depth = 0
    for index in range(first + 1, len(tokens)):
        kind = tokens[index].token_type
        if kind == TokenType.L_PAREN:
            depth += 1
        elif kind == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and kind in dml | {TokenType.SELECT, TokenType.VALUES}:
            if kind in {TokenType.SELECT, TokenType.VALUES}:
                return False
            # SQLite permits some keyword-like CTE names (e.g. replace).
            following = tokens[index + 1].token_type if index + 1 < len(tokens) else None
            if following in {TokenType.ALIAS, TokenType.L_PAREN}:
                continue
            return kind in dml
    return False


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
        self._operation_lock = RLock()
        self._read_request = None
        self._active_guard: SQLiteReadGuard | None = None

    @property
    def db_type(self) -> str:
        return "sqlite"

    @property
    def metadata_schema(self) -> str:
        return "main"

    @exclusive_connection
    def connect(self) -> bool:
        """Create a business StaticPool or a disposable diagnostic NullPool."""
        if self._engine is not None:
            return True

        try:
            from sqlalchemy import create_engine, event
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
                        "cached_statements": 0,
                    }
                    if self._diagnostic
                    else {"check_same_thread": False, "cached_statements": 0}
                ),
                hide_parameters=True,
                logging_name=_adapter_logging_name(
                    "sqlite_adapter", self._connection_id
                ),
                pool_logging_name=_adapter_logging_name(
                    "sqlite_adapter_pool", self._connection_id
                ),
            )
            event.listen(self._engine, "connect", self._initialize_authorizer)
            self._connected = True
            logger.info(
                "SQLite adapter connected (connection_id=%s)", self._connection_id
            )
            return True

        except Exception as e:
            logger.error("SQLite connection failed: %s", e.__class__.__name__)
            return False

    def _initialize_authorizer(self, connection, record) -> None:
        def authorize(action, first, second, database, source):
            guard = self._active_guard
            if guard is None:
                return sqlite3.SQLITE_OK  # Explicit trusted adapter operation.
            try:
                return guard.authorize(action, first, second, database, source)
            except Exception:
                return guard.deny("table_access_denied")
        connection.set_authorizer(authorize)

    @exclusive_connection
    def execute_read(self, sql, timeout=None, params=None, *, policy=None, analysis=None) -> list:
        from sql_safety_executor.core.analysis import analyze_sql
        if policy is None:
            raise ValueError("A read operation requires an explicit connection policy")
        if policy.read_mode == "deny" or policy.read_mode == "allowlist" and not policy.allowed_tables:
            raise DatabaseQueryError("read_disabled")
        context = self.analysis_context
        analysis = analysis or analyze_sql(sql, context)
        if (not analysis.complete or analysis.context_key != context.fingerprint
                or analysis.source_sql != sql):
            raise DatabaseQueryError("session_semantics_unavailable")
        if self._read_request is not None:
            raise RuntimeError("Nested read ownership is not supported")
        self._read_request = (policy, analysis)
        try:
            with operation_scope("read", analysis):
                arguments = {}
                if timeout is not None:
                    arguments["timeout"] = timeout
                if params is not None:
                    arguments["params"] = params
                return self.execute(sql, **arguments)
        finally:
            self._read_request = None
            self._active_guard = None

    @exclusive_connection
    def execute(
        self, sql: str, timeout: int | float | None = None, params: dict | None = None,
        *, _fetch_limit: int | None = None,
    ) -> list:
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
                raise DatabaseQueryError("database_connection_failed")
        engine = self._engine
        if engine is None:
            raise DatabaseQueryError("database_connection_failed")

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        guard = None
        try:
            from sqlalchemy import text

            with engine.connect() as connection:
                # Get raw sqlite3 connection for set_progress_handler
                raw_conn = connection.connection.dbapi_connection
                if raw_conn is None:
                    raise DatabaseQueryError("database_connection_failed")
                sqlite_conn = cast(sqlite3.Connection, raw_conn)
                # Set up timeout handler
                start_time = time.monotonic()

                def timeout_handler():
                    """Progress handler callback for query timeout."""
                    if time.monotonic() - start_time > timeout:
                        return 1  # Interrupt query
                    return 0  # Continue

                # Install progress handler
                # N = number of VM instructions between callbacks
                # Lower N = more responsive but higher overhead
                sqlite_conn.set_progress_handler(
                    timeout_handler, self._progress_handler_interval
                )

                try:
                    plan_reads = frozenset()
                    catalog_limit = 2048
                    while True:
                        if self._read_request is not None:
                            policy, analysis = self._read_request
                            guard = build_read_guard(sqlite_conn, policy, self.analysis_context, analysis,
                                                     deadline=start_time + timeout, plan_reads=plan_reads,
                                                     catalog_limit=catalog_limit)
                            catalog_limit -= guard.catalog_lookups
                            self._active_guard = guard
                        try:
                            if time.monotonic() >= start_time + timeout:
                                raise DatabaseQueryError("query_timeout")
                            statement = statement_text(sql, self.analysis_context, self._read_request[1] if self._read_request else None)
                            result = connection.execute(statement, params) if params else connection.execute(statement)
                            try:
                                return list(result.fetchall() if _fetch_limit is None
                                            else result.fetchmany(_fetch_limit + 1))
                            finally:
                                result.close()
                        except Exception:
                            if guard is None or not guard.explain_dml or not guard.pending_plan_reads:
                                raise
                            # Preparation was refused. The only retryable reads
                            # belong to a verified, original-SQL-bound DML plan;
                            # no actual write or function evaluation is retried.
                            new_reads = frozenset(guard.pending_plan_reads) - plan_reads
                            plan_reads = plan_reads | new_reads
                            if not new_reads or len(plan_reads) > 128:
                                guard.denial = "view_scope_unresolved"
                                raise
                            guard.denial = None
                        finally:
                            # Trusted fixed catalog work on the next iteration
                            # runs after the callback returned, under the same
                            # connection ownership and cumulative timeout/budget.
                            self._active_guard = None
                finally:
                    # Remove progress handler after query
                    self._active_guard = None
                    sqlite_conn.set_progress_handler(None, 0)

        except sqlite3.OperationalError as e:
            if guard is not None and guard.denial is not None:
                raise DatabaseQueryError(guard.denial) from None
            raise self._handle_error(e, timeout) from None
        except Exception as e:
            if guard is not None and guard.denial is not None:
                raise DatabaseQueryError(guard.denial) from None
            raise self._handle_error(e, timeout) from None

    @exclusive_connection
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

        connection = None
        transaction = None
        result = None
        sqlite_conn: sqlite3.Connection | None = None
        handler_installed = False
        handler_cleanup_failed = False
        result_cleanup_failed = False
        business_write_attempted = False
        phase = WriteExecutionPhase.SETUP

        def transaction_state() -> bool | None:
            if sqlite_conn is None or result_cleanup_failed:
                return None
            return sqlite_conn.in_transaction

        try:
            connection = engine.connect()
            transaction = connection.begin()
            raw_conn = connection.connection.dbapi_connection
            if raw_conn is None:
                raise RuntimeError("Database engine could not be initialized.")
            sqlite_conn = cast(sqlite3.Connection, raw_conn)
            start_time = time.monotonic()

            def check_deadline():
                if time.monotonic() - start_time > timeout:
                    raise TimeoutError("SQLite write deadline exceeded")

            def timeout_handler():
                if time.monotonic() - start_time > timeout:
                    return 1
                return 0

            sqlite_conn.set_progress_handler(
                timeout_handler,
                self._progress_handler_interval,
            )
            handler_installed = True
            check_deadline()
            # Legacy sqlite3 only emits BEGIN for a subset of DML spellings.
            # A logical SQLAlchemy begin() alone does not protect WITH/; DML.
            # Keep this explicit boundary local to writes, outside read guards.
            if not sqlite_conn.in_transaction:
                connection.exec_driver_sql("BEGIN").close()
            if sqlite_conn.in_transaction is not True:
                raise RuntimeError("SQLite physical transaction was not established")
            check_deadline()
            phase = WriteExecutionPhase.EXECUTE
            business_write_attempted = True
            result = connection.execute(statement_text(sql, self.analysis_context), params)
            cursor = result.cursor
            if result.returns_rows:
                # RETURNING/count_changes can keep a write VM open. Complete
                # it under the deadline without buffering all rows in Python.
                while result.fetchmany(256):
                    check_deadline()
            # CursorResult.rowcount may have memoized 0 before RETURNING was
            # consumed. SQLite's underlying cursor now has the completed count.
            rowcount = cursor.rowcount if cursor is not None else result.rowcount
            result.close()
            result = None
            check_deadline()
            if rowcount < 0 and _sqlite_dml_needs_count(sql, self.analysis_context):
                result = connection.exec_driver_sql("SELECT changes()")
                rowcount = result.scalar_one()
                result.close()
                result = None
                if type(rowcount) is not int or rowcount < 0:
                    raise RuntimeError("SQLite DML row count could not be established")
            check_deadline()

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
                    handler_cleanup_failed = True
                    logger.warning(
                        "SQLite progress handler cleanup failed: %s",
                        handler_error.__class__.__name__,
                    )
            if result is not None:
                try:
                    result.close()
                except BaseException as close_error:
                    result_cleanup_failed = True
                    logger.warning("SQLite write result cleanup failed: %s",
                                   close_error.__class__.__name__)
            if transaction is None:
                outcome = WriteExecutionOutcome.NOT_EXECUTED
                rollback_error = None
            else:
                outcome, rollback_error = _rollback_outcome(
                    transaction,
                    connection=connection,
                    business_write_attempted=business_write_attempted,
                    transaction_state=transaction_state,
                )
            retire_connection = result_cleanup_failed or handler_cleanup_failed
            if outcome is WriteExecutionOutcome.UNKNOWN:
                try:
                    retire_connection = retire_connection or transaction_state() is not False
                except Exception:
                    retire_connection = True
            if retire_connection and connection is not None:
                try:
                    connection.invalidate()
                except BaseException as invalidate_error:
                    logger.warning("SQLite write connection retirement failed: %s",
                                   invalidate_error.__class__.__name__)
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
            if transaction_state() is not False:
                raise RuntimeError("SQLite COMMIT did not finish the physical transaction")
        except BaseException as error:
            try:
                active_transaction.rollback()
            except BaseException as rollback_error:
                logger.warning(
                    "Rollback cleanup after uncertain COMMIT failed: %s",
                    rollback_error.__class__.__name__,
                )
            try:
                if transaction_state() is not False and connection is not None:
                    connection.invalidate()
            except BaseException as invalidate_error:
                logger.warning("SQLite uncertain COMMIT connection retirement failed: %s",
                               invalidate_error.__class__.__name__)
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

    def _handle_error(self, e: Exception, timeout: int | float | None = None) -> DatabaseQueryError:
        logger.warning("sqlite execution error: %s", e.__class__.__name__)
        return classify_database_error(e, "sqlite")

    @exclusive_connection
    def get_json_name_observation(self) -> SQLiteJSONNameObservation:
        """Observe two names in lookup order on the owned physical connection.

        Bound directory count and total time, including catalog discovery.
        Partial observations never prove builtin identity. This is trusted
        catalog access, not permission to evaluate any observed object.
        """
        deadline = time.monotonic() + self._query_timeout_seconds
        references: list[RelationReference] = []
        searched: list[str] = []
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return SQLiteJSONNameObservation()
            # Use the statement form: an ordinary table can shadow the
            # pragma_database_list() table-valued function in trusted SQL.
            rows = self.execute("PRAGMA database_list", timeout=remaining)
            schemas = ["temp", "main", *(str(row[1]) for row in rows
                        if str(row[1]) not in {"temp", "main"})]
            complete = len(schemas) <= _JSON_NAME_SCHEMA_LIMIT
            for schema in schemas[:_JSON_NAME_SCHEMA_LIMIT]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return SQLiteJSONNameObservation(tuple(references), tuple(searched))
                catalog = render_relation(RelationReference("sqlite_master", schema), "sqlite")
                matches = self.execute(
                    f"SELECT name FROM {catalog} WHERE type IN ('table','view') "
                    "AND name COLLATE NOCASE IN ('json_each','json_tree') LIMIT 2",
                    timeout=remaining,
                )
                references.extend(RelationReference(str(row[0]), schema) for row in matches)
                searched.append(schema)
            return SQLiteJSONNameObservation(tuple(references), tuple(searched), complete)
        except DatabaseQueryError:
            logger.warning("Skills JSON-name readiness observation is incomplete.")
            return SQLiteJSONNameObservation(tuple(references), tuple(searched))

    def get_table_directory(self) -> list[dict[str, Any]]:
        """Discover main-schema tables without evaluating table/view contents."""
        sql = f"""
            SELECT name as table_name
            FROM main.sqlite_master
            WHERE type='table' AND {_PUBLIC_RELATION_FILTER}
            ORDER BY name
        """
        result = self._execute_metadata(sql, 'listing tables')


        return [{"table_name": row[0], "row_count": None} for row in result]

    def enrich_row_estimates(self, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        estimates = self._row_estimates([table["table_name"] for table in tables])
        return [{**table, "row_count": estimates[table["table_name"]]} for table in tables]

    def get_read_relations(self) -> list[ReadRelation]:
        rows = self._execute_metadata(
            "SELECT name, type FROM main.sqlite_master "
            f"WHERE type IN ('table', 'view') AND {_PUBLIC_RELATION_FILTER} ORDER BY name",
            "observing read relations",
        )
        return [ReadRelation(RelationReference(row[0], self.metadata_schema), row[1]) for row in rows]

    def _metadata_pragma(self, operation: str, name: str, target: str, *,
                         timeout: float | None = None, row_limit: int = _PRAGMA_ROW_LIMIT,
                         overflow_ok: bool = False) -> list:
        """Fixed main-bound catalog statements, immune to relation-name shadows.

        PRAGMA arguments cannot be bound parameters. Encode one SQL string
        literal; pragma names and schema never come from a tool argument.
        Fetch one overflow row so callers fail without a partial success.
        """
        if name not in {"table_xinfo", "table_info", "index_list", "index_xinfo", "table_list"}:
            raise ValueError("Unsupported metadata PRAGMA")
        literal = "'" + target.replace("'", "''") + "'"
        try:
            with operation_scope("metadata"):
                rows = self.execute(f"PRAGMA main.{name}({literal})", timeout=timeout,
                                    params=None, _fetch_limit=row_limit)
        except DatabaseQueryError:
            raise MetadataQueryError(operation) from None
        if len(rows) > row_limit and not overflow_ok:
            raise MetadataQueryError(operation)
        return rows

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        """
        Return SELECT-star columns, including generated columns, in cid order.

        table_xinfo hidden=1 denotes virtual-table hidden columns, excluded
        from this projection; 2/3 denote visible VIRTUAL/STORED generated columns.
        Preserve the database-reported type, including an empty string. It
        describes metadata, not inferred affinity or the stored value's type.
        """
        if not self.valid_metadata_identifier(table_name):
            return []

        result = self._metadata_pragma('reading table columns', 'table_xinfo', table_name)


        columns = []
        for row in sorted(result, key=lambda row: row[0]):
            if row[6] == 1:
                continue
            # Map SQLite PRAGMA output to consistent format
            column = {
                    "column_name": row[1],
                    "data_type": row[2],
                    "nullable": "NO" if row[3] else "YES",
                    "key_type": "PRI" if row[5] else "",
                    "default_value": row[4],
                }
            if row[5]:
                column["primary_key_position"] = int(row[5])
            if row[6] in (2, 3):
                column["generation_type"] = "virtual" if row[6] == 2 else "stored"
            columns.append(column)

        return columns

    @exclusive_connection
    def get_indexes(self, table_name: str) -> list[dict[str, Any]]:
        """Read main indexes with bounded, non-shadowable PRAGMA statements."""
        if not self.valid_metadata_identifier(table_name):
            raise MetadataQueryError("reading table indexes")
        budget = IndexMetadataBudget(self._query_timeout_seconds)
        listed = self._metadata_pragma('reading table indexes', 'index_list', table_name,
                                       timeout=budget.remaining(), row_limit=MAX_INDEXES)
        budget.remaining()
        index_rows = []
        for _seq, name, unique, origin, partial in sorted(listed, key=lambda row: row[1]):
            parts = self._metadata_pragma('reading table indexes', 'index_xinfo', name,
                                          timeout=budget.remaining())
            index_rows.extend((name, unique, origin, partial, *row[:5])
                              for row in sorted(parts, key=lambda row: row[0]) if row[5] == 1)
            budget.rows(index_rows)
        pk_rows = sorted((row for row in self._metadata_pragma(
            'reading table indexes', 'table_info', table_name, timeout=budget.remaining())
            if row[5] > 0), key=lambda row: row[5])
        budget.rows(pk_rows)

        by_name: dict[str, dict[str, Any]] = {}
        for (
            name, unique, origin, partial, _seq, cid, column, descending, collation
        ) in index_rows:
            index = by_name.setdefault(
                name,
                {
                    "name": name,
                    "primary": origin == "pk",
                    "unique": bool(unique),
                    "columns": [],
                    "key_parts": [],
                    "partial": bool(partial),
                },
            )
            # cid -2 marks an expression key part; key=0 auxiliary columns
            # are filtered from PRAGMA rows before projection into key parts.
            column = None if cid == -2 else column
            index["columns"].append(column)
            index["key_parts"].append(
                {
                    "column": column,
                    "sort_order": "desc" if descending else "asc",
                    "collation": collation,
                }
            )
            if cid == -2:
                index["has_expression"] = True

        indexes = list(by_name.values())
        # An INTEGER PRIMARY KEY aliases the rowid and has no index entry.
        if pk_rows and not any(index["primary"] for index in indexes):
            indexes.append(
                {
                    "name": None,
                    "primary": True,
                    "unique": True,
                    "columns": [row[1] for row in pk_rows],
                    # Synthetic keys have no index_xinfo direction/collation.
                    "key_parts": [
                        {"column": row[1], "sort_order": None, "collation": None}
                        for row in pk_rows
                    ],
                    "partial": False,
                }
            )
        return budget.finish(
            sorted(indexes, key=lambda item: (not item["primary"], item["name"] or ""))
        )

    def get_row_estimate(self, table_name: str) -> int | None:
        """Estimate one object using fresh statistics or guarded bounded reads."""
        return self._row_estimates([table_name])[table_name]

    @exclusive_connection
    def _row_estimates(self, table_names: list[str]) -> dict[str, int | None]:
        """Operation-local statistics, authorized names only; never an auth cache."""
        estimates: dict[str, int | None] = dict.fromkeys(table_names)
        policy = self._config.policy
        eligible = [
            name for name in estimates
            if self.valid_metadata_identifier(name) and policy.read_mode != "deny"
            and policy.allows_metadata_relation(RelationReference(name, self.metadata_schema))
        ]
        if not eligible:
            return estimates
        statistics = self._row_statistics(eligible)
        for name in eligible:
            count = statistics.get(name)
            estimates[name] = count if count is not None else self._bounded_row_estimate(name, policy)
        return estimates

    def _row_statistics(self, table_names: list[str]) -> dict[str, int]:
        """Prefer table statistics; verify full-index sources before use.

        Partial-index cardinality is not table cardinality. Only objects in the
        authorized projection reach this stage. No ANALYZE or data scan occurs.
        """
        deadline = time.monotonic() + self._query_timeout_seconds

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise MetadataQueryError("estimating table rows within budget")
            return seconds

        exists = self._execute_metadata(
            "SELECT name FROM main.sqlite_master WHERE type='table' AND name='sqlite_stat1'",
            "estimating table rows", timeout=remaining(),
        )
        if not exists:
            return {}
        statistics: dict[str, int] = {}
        for start in range(0, len(table_names), 200):
            params = {f"name_{i}": name for i, name in enumerate(table_names[start:start + 200])}
            values = ", ".join("(:" + key + ")" for key in params)
            try:
                with operation_scope("metadata"):
                    rows = self.execute(
                        "WITH requested(name) AS (VALUES " + values + ") "
                        "SELECT name, (SELECT stat FROM main.sqlite_stat1 "
                        "WHERE tbl = requested.name AND idx IS NULL LIMIT 1), "
                        "EXISTS(SELECT 1 FROM main.sqlite_stat1 WHERE tbl = requested.name) FROM requested",
                        params=params, timeout=remaining(),
                    )
            except DatabaseQueryError as error:
                if error.error_code == "unknown_table":
                    # ANALYZE statistics can be removed after the existence
                    # check. Fall back to guarded reads, not fabricated zeros.
                    return {}
                raise MetadataQueryError("estimating table rows") from None
            for name, stat, has_statistics in rows:
                count = _stat_row_count(stat)
                if count is None and has_statistics:
                    count = self._full_index_row_statistic(name, remaining)
                if count is not None:
                    statistics[name] = count
        remaining()
        return statistics

    def _full_index_row_statistic(self, name, remaining) -> int | None:
        """Use a current nonpartial index, including WITHOUT ROWID's PK tree.

        An oversized/incomplete catalog gives no statistic, so the caller uses
        the existing guarded bounded estimate. Driver failures remain errors.
        """
        indexes = self._metadata_pragma(
            "estimating table rows", "index_list", name, timeout=remaining(),
            row_limit=MAX_INDEXES, overflow_ok=True)
        if len(indexes) > MAX_INDEXES:
            return None
        candidates = [row[1] for row in indexes if row[4] == 0]
        if any(row[3] == "pk" for row in indexes):
            tables = self._metadata_pragma(
                "estimating table rows", "table_list", name, timeout=remaining(), row_limit=1)
            if (tables and tables[0][0] == "main" and tables[0][2] == "table"
                    and ascii_identifier_lower(tables[0][1]) == ascii_identifier_lower(name)
                    and tables[0][4] == 1):
                # stat1 uses the table name for this tree, while index_list
                # reports sqlite_autoindex_*. They are not string aliases.
                candidates.insert(0, tables[0][1])
        if not candidates:
            return None
        params = {f"index_{i}": candidate for i, candidate in enumerate(candidates)}
        placeholders = ",".join(":" + key for key in params)
        params["table"] = name
        try:
            with operation_scope("metadata"):
                rows = self.execute(
                    "SELECT idx, stat FROM main.sqlite_stat1 WHERE tbl=:table "
                    f"AND idx IN ({placeholders}) LIMIT {MAX_INDEXES + 1}",
                    params=params, timeout=remaining(), _fetch_limit=MAX_INDEXES)
        except DatabaseQueryError as error:
            if error.error_code == "unknown_table":
                return None
            raise MetadataQueryError("estimating table rows") from None
        if len(rows) > MAX_INDEXES:
            return None
        by_index = dict(rows)
        for candidate in candidates:
            count = _stat_row_count(by_index.get(candidate))
            if count is not None:
                return count
        return None

    def _bounded_row_estimate(self, table_name: str, policy: ConnectionPolicy) -> int | None:
        # Fallback: bounded sample-based estimation. This intentionally avoids
        # a full COUNT(*) on large tables; exact counts are opt-in elsewhere.
        sample_limit = 10000
        quoted_table_name = self.render_metadata_relation(RelationReference(table_name, "main"))
        estimate_cte = "__mcp_row_estimate"
        if self.analysis_context.cte_key(table_name) == estimate_cte:
            estimate_cte += "_"
        sample_sql = (
            f'WITH "{estimate_cte}"(marker) AS (SELECT 1 FROM {quoted_table_name} LIMIT {sample_limit}) '
            f'SELECT COUNT(marker) FROM "{estimate_cte}"'
        )
        try:
            # This fixed template evaluates user data and view expressions;
            # unlike catalog/statistics SQL, it needs the normal read guard.
            sample_result = self.execute_read(sample_sql, policy=policy)
        except DatabaseQueryError as error:
            if error.error_code in {
                "unknown_table", "table_access_denied", "server_state_denied",
                "lock_function_denied", "expensive_function_denied",
                "file_operation_denied", "view_scope_unresolved", "read_disabled",
                "session_semantics_unavailable",
            }:
                return None
            raise MetadataQueryError("estimating table rows") from None
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
        try:
            self.execute("SELECT 1")
        except DatabaseQueryError as error:
            return False, str(error)

        return True, "SQLite connection successful"

    def get_database_name(self) -> str | None:
        """
        Get database name (file path for SQLite).

        For :memory: databases, returns ':memory:'.
        For file databases, returns the file path.
        """
        return self._database_path

    @exclusive_connection
    def close(self) -> None:
        """Dispose SQLAlchemy engine."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._connected = False
            logger.info("SQLite adapter closed (connection_id=%s)", self._connection_id)
