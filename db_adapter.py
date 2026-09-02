"""
Database Adapter Module

Provides a unified interface for different database backends (MySQL, SQLite).
Uses Abstract Base Class pattern to enable extension for future databases (PostgreSQL).

Design Decisions:
- ABC base class for consistent interface and future extension
- Factory function for adapter creation based on environment config
- MySQL read queries use MAX_EXECUTION_TIME; writes use InnoDB lock-wait timeout
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
import re
import time
import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, cast
from dotenv import load_dotenv
from sqlalchemy.engine import Engine

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

METADATA_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]{0,63}$")
CONNECTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MUTATION_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class MetadataQueryError(RuntimeError):
    """Signal that adapter metadata could not be read without exposing DB details."""

    def __init__(self, operation: str):
        super().__init__(f"Database metadata query failed while {operation}.")


@dataclass(frozen=True)
class ConnectionPolicy:
    """Read and mutation policy bound to one configured database connection."""

    allow_union: bool = False
    allowed_tables: frozenset[str] | None = None
    allow_mutations: bool = False
    mutation_skills: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DatabaseConfig:
    """Sanitized runtime configuration for one named database connection."""

    connection_id: str
    db_type: str
    query_timeout_seconds: int
    connect_timeout_seconds: int
    policy: ConnectionPolicy
    mysql_user: str | None = None
    mysql_password: str | None = None
    mysql_host: str | None = None
    mysql_database: str | None = None
    sqlite_database_path: str | None = None
    sqlite_progress_handler_interval: int = SQLITE_PROGRESS_HANDLER_INTERVAL


def _parse_env_bool_value(raw: str | None, default: bool = False) -> bool:
    """Parse a boolean-like env value with a conservative fallback."""
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid boolean env value %r; falling back to %s", raw, default)
    return default


def _parse_int_value(raw: str | None, default: int, name: str) -> int:
    """Parse an integer env value and fail with a clear configuration error."""
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer value for {name}: {raw!r}") from exc


def _parse_allowed_tables_value(raw: str | None) -> frozenset[str] | None:
    """Parse an ALLOWED_TABLES-style value for one connection."""
    if raw is None or not raw.strip():
        return None
    normalized = raw.strip()
    if normalized == "*":
        return frozenset({"*"})
    values = frozenset(
        item.strip().lower()
        for item in normalized.split(",")
        if item.strip()
    )
    return values or None


def _parse_mutation_skills_value(raw: str | None, name: str) -> frozenset[str]:
    """Parse and validate a per-connection mutation skill allowlist."""
    if raw is None or not raw.strip():
        return frozenset()

    values = frozenset(
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    )
    invalid = sorted(
        value
        for value in values
        if value != "*" and not MUTATION_SKILL_NAME_PATTERN.fullmatch(value)
    )
    if invalid:
        raise ValueError(
            f"Invalid mutation skill name(s) in {name}: {invalid}. "
            "Use lowercase letters, digits, and hyphens, or '*'."
        )
    return values


def normalize_connection_id(connection_id: str | None) -> str:
    """Normalize and validate configured connection ids used by tools."""
    if connection_id is None:
        return get_default_connection_id()
    normalized = connection_id.strip().lower()
    if not CONNECTION_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Invalid connection_id. Use 1-64 lowercase letters, digits, or underscores, "
            "starting with a letter."
        )
    return normalized


def _connection_env_name(connection_id: str, suffix: str) -> str:
    return f"DB_{connection_id.upper()}_{suffix}"


def _connection_env(
    connection_id: str,
    suffix: str,
    *,
    legacy_name: str | None = None,
    default: str | None = None,
    use_legacy_fallback: bool = False,
    use_connection_value: bool = True,
) -> str | None:
    """Read a per-connection env var, then optional legacy fallback."""
    if use_connection_value:
        value = os.getenv(_connection_env_name(connection_id, suffix))
        if value is not None:
            return value
    if use_legacy_fallback and legacy_name:
        legacy_value = os.getenv(legacy_name)
        if legacy_value is not None:
            return legacy_value
    return default


def _connection_ids_from_env() -> list[str]:
    raw = os.getenv("DB_CONNECTIONS", "").strip()
    if not raw:
        return ["default"]

    connection_ids: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if not CONNECTION_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                f"Invalid DB_CONNECTIONS entry {item!r}. Use lowercase letters, "
                "digits, or underscores; ids must start with a letter."
            )
        if normalized in seen:
            raise ValueError(f"Duplicate DB_CONNECTIONS entry: {normalized}")
        seen.add(normalized)
        connection_ids.append(normalized)

    if not connection_ids:
        raise ValueError("DB_CONNECTIONS is set but contains no valid connection ids")
    return connection_ids


def _build_database_config(
    connection_id: str,
    *,
    use_legacy_fallback: bool,
    db_type_override: str | None = None,
    use_connection_env: bool = True,
) -> DatabaseConfig:
    """Build one DatabaseConfig from per-connection env plus legacy fallback."""
    db_type = (
        db_type_override
        or _connection_env(
            connection_id,
            "TYPE",
            legacy_name="DB_TYPE",
            default=DB_TYPE,
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        )
        or DB_TYPE
    ).strip().lower()

    query_timeout = _parse_int_value(
        _connection_env(
            connection_id,
            "QUERY_TIMEOUT_SECONDS",
            legacy_name="QUERY_TIMEOUT_SECONDS",
            default=str(QUERY_TIMEOUT_SECONDS),
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        ),
        QUERY_TIMEOUT_SECONDS,
        _connection_env_name(connection_id, "QUERY_TIMEOUT_SECONDS"),
    )
    connect_timeout = _parse_int_value(
        _connection_env(
            connection_id,
            "CONNECT_TIMEOUT_SECONDS",
            legacy_name="CONNECT_TIMEOUT_SECONDS",
            default=str(CONNECT_TIMEOUT_SECONDS),
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        ),
        CONNECT_TIMEOUT_SECONDS,
        _connection_env_name(connection_id, "CONNECT_TIMEOUT_SECONDS"),
    )

    allow_union = _parse_env_bool_value(
        _connection_env(
            connection_id,
            "ALLOW_UNION",
            legacy_name="ALLOW_UNION",
            default="0",
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        ),
        False,
    )
    allowed_tables = _parse_allowed_tables_value(
        _connection_env(
            connection_id,
            "ALLOWED_TABLES",
            legacy_name="ALLOWED_TABLES",
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        )
    )
    allow_mutations = _parse_env_bool_value(
        _connection_env(
            connection_id,
            "ALLOW_MUTATIONS",
            default="0",
            use_connection_value=use_connection_env,
        ),
        False,
    )
    mutation_skills_env_name = _connection_env_name(
        connection_id,
        "MUTATION_SKILLS",
    )
    mutation_skills = _parse_mutation_skills_value(
        _connection_env(
            connection_id,
            "MUTATION_SKILLS",
            use_connection_value=use_connection_env,
        ),
        mutation_skills_env_name,
    )
    policy = ConnectionPolicy(
        allow_union=allow_union,
        allowed_tables=allowed_tables,
        allow_mutations=allow_mutations,
        mutation_skills=mutation_skills,
    )

    if db_type == "mysql":
        return DatabaseConfig(
            connection_id=connection_id,
            db_type=db_type,
            query_timeout_seconds=query_timeout,
            connect_timeout_seconds=connect_timeout,
            policy=policy,
            mysql_user=_connection_env(
                connection_id,
                "USER",
                legacy_name="DB_USER",
                default=DB_USER,
                use_legacy_fallback=use_legacy_fallback,
                use_connection_value=use_connection_env,
            ),
            mysql_password=_connection_env(
                connection_id,
                "PASSWORD",
                legacy_name="DB_PASSWORD",
                default=DB_PASSWORD,
                use_legacy_fallback=use_legacy_fallback,
                use_connection_value=use_connection_env,
            ),
            mysql_host=_connection_env(
                connection_id,
                "HOST",
                legacy_name="DB_HOST",
                default=DB_HOST,
                use_legacy_fallback=use_legacy_fallback,
                use_connection_value=use_connection_env,
            ),
            mysql_database=_connection_env(
                connection_id,
                "NAME",
                legacy_name="DB_NAME",
                default=DB_NAME,
                use_legacy_fallback=use_legacy_fallback,
                use_connection_value=use_connection_env,
            ),
            sqlite_progress_handler_interval=SQLITE_PROGRESS_HANDLER_INTERVAL,
        )

    if db_type == "sqlite":
        sqlite_path = _connection_env(
            connection_id,
            "SQLITE_DATABASE_PATH",
            legacy_name="SQLITE_DATABASE_PATH",
            default=SQLITE_DATABASE_PATH,
            use_legacy_fallback=use_legacy_fallback,
            use_connection_value=use_connection_env,
        )
        progress_interval = _parse_int_value(
            _connection_env(
                connection_id,
                "SQLITE_PROGRESS_HANDLER_INTERVAL",
                legacy_name="SQLITE_PROGRESS_HANDLER_INTERVAL",
                default=str(SQLITE_PROGRESS_HANDLER_INTERVAL),
                use_legacy_fallback=use_legacy_fallback,
                use_connection_value=use_connection_env,
            ),
            SQLITE_PROGRESS_HANDLER_INTERVAL,
            _connection_env_name(connection_id, "SQLITE_PROGRESS_HANDLER_INTERVAL"),
        )
        return DatabaseConfig(
            connection_id=connection_id,
            db_type=db_type,
            query_timeout_seconds=query_timeout,
            connect_timeout_seconds=connect_timeout,
            policy=policy,
            sqlite_database_path=sqlite_path or ":memory:",
            sqlite_progress_handler_interval=progress_interval,
        )

    raise ValueError(
        f"Unsupported database type for connection '{connection_id}': {db_type}. "
        "Supported types: mysql, sqlite"
    )


def _load_connection_configs() -> tuple[dict[str, DatabaseConfig], str]:
    named_connections_enabled = bool(os.getenv("DB_CONNECTIONS", "").strip())
    connection_ids = _connection_ids_from_env()
    if named_connections_enabled:
        requested_default = os.getenv("DEFAULT_DB_CONNECTION", connection_ids[0]).strip().lower()
    else:
        requested_default = connection_ids[0]
    if not CONNECTION_ID_PATTERN.fullmatch(requested_default):
        raise ValueError("DEFAULT_DB_CONNECTION is not a valid connection id")
    if requested_default not in connection_ids:
        raise ValueError(
            f"DEFAULT_DB_CONNECTION={requested_default!r} is not listed in DB_CONNECTIONS"
        )

    configs: dict[str, DatabaseConfig] = {}
    for connection_id in connection_ids:
        configs[connection_id] = _build_database_config(
            connection_id,
            use_legacy_fallback=connection_id == requested_default,
            use_connection_env=named_connections_enabled,
        )
    return configs, requested_default


_CONNECTION_CONFIGS, _DEFAULT_CONNECTION_ID = _load_connection_configs()

# Keep legacy module constants aligned with the default connection when the new
# registry env syntax is used. Existing imports still see DB_TYPE and timeout
# values for the default connection.
_default_config = _CONNECTION_CONFIGS[_DEFAULT_CONNECTION_ID]
DB_TYPE = _default_config.db_type
QUERY_TIMEOUT_SECONDS = _default_config.query_timeout_seconds
CONNECT_TIMEOUT_SECONDS = _default_config.connect_timeout_seconds
if _default_config.db_type == "mysql":
    DB_USER = _default_config.mysql_user
    DB_PASSWORD = _default_config.mysql_password
    DB_HOST = _default_config.mysql_host
    DB_NAME = _default_config.mysql_database
elif _default_config.db_type == "sqlite":
    SQLITE_DATABASE_PATH = _default_config.sqlite_database_path or ":memory:"
    SQLITE_PROGRESS_HANDLER_INTERVAL = _default_config.sqlite_progress_handler_interval


def get_default_connection_id() -> str:
    """Return the configured default connection id."""
    return _DEFAULT_CONNECTION_ID


def get_connection_config(connection_id: str | None = None) -> DatabaseConfig:
    """Return sanitized config for a configured connection id."""
    normalized = normalize_connection_id(connection_id)
    try:
        return _CONNECTION_CONFIGS[normalized]
    except KeyError as exc:
        known = ", ".join(sorted(_CONNECTION_CONFIGS))
        raise ValueError(
            f"Unknown connection_id '{normalized}'. Configured connections: {known}"
        ) from exc


def list_connection_configs() -> list[DatabaseConfig]:
    """Return all configured connection configs in DB_CONNECTIONS order."""
    return list(_CONNECTION_CONFIGS.values())


def _legacy_config_for_adapter(db_type: str | None = None) -> DatabaseConfig:
    """Build a direct-constructor config from current legacy module globals."""
    selected_type = (db_type or DB_TYPE).lower()
    policy = ConnectionPolicy(
        allow_union=_parse_env_bool_value(os.getenv("ALLOW_UNION"), False),
        allowed_tables=_parse_allowed_tables_value(os.getenv("ALLOWED_TABLES")),
    )
    return DatabaseConfig(
        connection_id="default",
        db_type=selected_type,
        query_timeout_seconds=QUERY_TIMEOUT_SECONDS,
        connect_timeout_seconds=CONNECT_TIMEOUT_SECONDS,
        policy=policy,
        mysql_user=DB_USER,
        mysql_password=DB_PASSWORD,
        mysql_host=DB_HOST,
        mysql_database=DB_NAME,
        sqlite_database_path=SQLITE_DATABASE_PATH,
        sqlite_progress_handler_interval=SQLITE_PROGRESS_HANDLER_INTERVAL,
    )


def _adapter_logging_name(prefix: str, connection_id: str) -> str:
    """Keep legacy default log names, add safe id for named connections."""
    return prefix if connection_id == "default" else f"{prefix}.{connection_id}"


def _is_valid_metadata_identifier(identifier: str) -> bool:
    return isinstance(identifier, str) and bool(METADATA_IDENTIFIER_PATTERN.fullmatch(identifier))


def _metadata_identifier_is_rejected(identifier: str) -> bool:
    if _is_valid_metadata_identifier(identifier):
        return False
    logger.warning("Invalid metadata identifier rejected at adapter boundary")
    return True


def _quote_sqlite_identifier(identifier: str) -> str:
    if not _is_valid_metadata_identifier(identifier):
        raise ValueError("Invalid metadata identifier")
    return f'"{identifier}"'


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
            List of dicts with 'table_name' and 'row_count' keys. row_count is
            None when the backend cannot provide a safe estimate.

        Raises:
            MetadataQueryError: If the metadata query cannot be completed
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

        Raises:
            MetadataQueryError: If the metadata query cannot be completed
        """
        pass
    
    @abstractmethod
    def get_row_estimate(self, table_name: str) -> int | None:
        """
        Get estimated row count for a table.
        
        Note: This is an estimate, not exact count.
        For SQLite, uses sqlite_stat1 or bounded sampling.
        For MySQL, uses INFORMATION_SCHEMA.TABLES.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Estimated row count, or None when the table is not found or the
            backend cannot provide a safe estimate

        Raises:
            MetadataQueryError: If the metadata query cannot be completed
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
        logger.warning("Database error: %s", e.__class__.__name__)
        return "Error: Database query failed"

    @property
    def connection_id(self) -> str:
        """Return the configured connection id for this adapter instance."""
        return getattr(self, "_connection_id", "default")

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
    - Read-query timeout via MAX_EXECUTION_TIME + connection timeouts
    - Mutation row-lock wait timeout via innodb_lock_wait_timeout
    - INFORMATION_SCHEMA for metadata queries
    
    Backward Compatibility:
    - Preserves all existing MySQL behavior from sql_safety_checker.py
    - Uses same connection parameters and timeout settings
    """
    
    def __init__(self, config: DatabaseConfig | None = None):
        self._config = config or _legacy_config_for_adapter("mysql")
        if self._config.db_type != "mysql":
            raise ValueError("MySQLAdapter requires a mysql DatabaseConfig")
        self._engine: Engine | None = None
        self._connection_id = self._config.connection_id
        self._db_user = self._config.mysql_user
        self._db_password = self._config.mysql_password
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
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                hide_parameters=True,
                logging_name=_adapter_logging_name("mysql_adapter", self._connection_id),
                pool_logging_name=_adapter_logging_name("mysql_adapter_pool", self._connection_id),
                connect_args={
                    "connect_timeout": self._connect_timeout_seconds,
                    "read_timeout": self._query_timeout_seconds,
                    "write_timeout": self._query_timeout_seconds,
                }
            )
            self._connected = True
            logger.info("MySQL adapter connected (connection_id=%s)", self._connection_id)
            return True
            
        except ImportError:
            logger.error("PyMySQL not installed. Run: pip install PyMySQL")
            return False
        except Exception as e:
            logger.error("MySQL connection failed: %s", e.__class__.__name__)
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
                    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
                except SQLAlchemyError:
                    # Fallback: Some MySQL versions may not support MAX_EXECUTION_TIME
                    logger.debug("MAX_EXECUTION_TIME not supported, using connection timeout")
                
                if params:
                    result = connection.execute(text(sql), params)
                else:
                    result = connection.execute(text(sql))
                rows = list(result.fetchall())
                return rows
                
        except Exception as e:
            return self._handle_error(e, timeout)

    def execute_write(self, sql: str, params: dict, timeout: int | None = None) -> dict:
        """
        Execute a parameterized write SQL within a MySQL transaction.

        Configures InnoDB row-lock wait timeout before executing the mutation,
        then relies on engine.begin() for explicit transaction handling
        (auto-commit on success, auto-rollback on exception). MySQL
        MAX_EXECUTION_TIME is SELECT-oriented and is not used as mutation
        timeout protection here. Exceptions propagate to caller (MutationBase)
        for error sanitization.
        """
        if not self._engine:
            if not self.connect():
                raise RuntimeError("Database engine could not be initialized.")
        engine = self._engine
        if engine is None:
            raise RuntimeError("Database engine could not be initialized.")

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        with engine.begin() as connection:
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
        logger.warning("SQL execution error: %s", e.__class__.__name__)

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
                "default_value": row[4]
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
    
    def __init__(self, database_path: str | None = None, *, config: DatabaseConfig | None = None):
        self._config = config or _legacy_config_for_adapter("sqlite")
        if self._config.db_type != "sqlite":
            raise ValueError("SQLiteAdapter requires a sqlite DatabaseConfig")
        self._connection_id = self._config.connection_id
        self._database_path = database_path or self._config.sqlite_database_path or SQLITE_DATABASE_PATH
        self._query_timeout_seconds = self._config.query_timeout_seconds
        self._progress_handler_interval = self._config.sqlite_progress_handler_interval
        self._engine: Engine | None = None
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
                connect_args={"check_same_thread": False},
                hide_parameters=True,
                logging_name=_adapter_logging_name("sqlite_adapter", self._connection_id),
                pool_logging_name=_adapter_logging_name("sqlite_adapter_pool", self._connection_id),
            )
            self._connected = True
            logger.info("SQLite adapter connected (connection_id=%s)", self._connection_id)
            return True
            
        except Exception as e:
            logger.error("SQLite connection failed: %s", e.__class__.__name__)
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
                sqlite_conn.set_progress_handler(timeout_handler, self._progress_handler_interval)
                
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
        engine = self._engine
        if engine is None:
            raise RuntimeError("Database engine could not be initialized.")

        timeout = timeout if timeout is not None else self._query_timeout_seconds

        from sqlalchemy import text

        with engine.begin() as connection:
            raw_conn = connection.connection.dbapi_connection
            if raw_conn is None:
                raise RuntimeError("Database engine could not be initialized.")
            sqlite_conn = cast(sqlite3.Connection, raw_conn)
            start_time = time.time()

            def timeout_handler():
                if time.time() - start_time > timeout:
                    return 1
                return 0

            sqlite_conn.set_progress_handler(timeout_handler, self._progress_handler_interval)
            try:
                result = connection.execute(text(sql), params)
                return {"success": True, "rowcount": result.rowcount}
            finally:
                sqlite_conn.set_progress_handler(None, 0)

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
            columns.append({
                "column_name": row[1],
                "data_type": row[2] or "TEXT",  # SQLite allows empty type
                "nullable": "NO" if row[3] else "YES",
                "key_type": "PRI" if row[5] else "",
                "default_value": row[4]
            })
        
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
        check_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
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


# =============================================================================
# Factory Function
# =============================================================================

def create_adapter(
    db_type: str | None = None,
    *,
    config: DatabaseConfig | None = None,
    connection_id: str | None = None,
) -> DatabaseAdapter:
    """
    Create appropriate database adapter based on configuration.
    
    Args:
        db_type: Database type override ('mysql' or 'sqlite').
                 If None, uses DB_TYPE environment variable.
        config: Optional explicit DatabaseConfig for a named connection.
        connection_id: Optional configured connection id to resolve.
    
    Returns:
        DatabaseAdapter instance (MySQLAdapter or SQLiteAdapter)
    
    Raises:
        ValueError: If unsupported database type is specified
    
    Example:
        adapter = create_adapter()  # Uses DB_TYPE env var
        adapter = create_adapter('sqlite')  # Force SQLite
    """
    if config is None and connection_id is not None:
        config = get_connection_config(connection_id)
    if config is None:
        config = _legacy_config_for_adapter(db_type)
    elif db_type is not None and db_type.lower() != config.db_type:
        raise ValueError(
            f"db_type override '{db_type}' does not match config db_type '{config.db_type}'"
        )

    db_type = config.db_type
    
    if db_type == "mysql":
        logger.info("Creating MySQL adapter (connection_id=%s)", config.connection_id)
        adapter = MySQLAdapter(config)
        adapter.connect()
        return adapter
    
    elif db_type == "sqlite":
        logger.info("Creating SQLite adapter (connection_id=%s)", config.connection_id)
        adapter = SQLiteAdapter(config=config)
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

# Default adapter alias plus connection-id keyed registry. The alias preserves
# older tests and direct imports; the registry is the v3.5 multi-connection path.
_adapter: DatabaseAdapter | None = None
_adapters: dict[str, DatabaseAdapter] = {}


def get_adapter(connection_id: str | None = None) -> DatabaseAdapter:
    """
    Get or create an adapter for the configured connection id.
    
    Returns:
        The DatabaseAdapter instance for the selected connection.
    """
    global _adapter
    config = get_connection_config(connection_id)
    adapter = _adapters.get(config.connection_id)
    if adapter is None:
        adapter = create_adapter(config=config)
        _adapters[config.connection_id] = adapter
    if config.connection_id == _DEFAULT_CONNECTION_ID:
        _adapter = adapter
    return adapter


def reset_adapter(connection_id: str | None = None) -> None:
    """
    Reset adapter(s) for testing or reconfiguration.
    
    With no connection_id, closes all cached adapters. With a connection_id,
    closes only that configured adapter.
    """
    global _adapter
    if connection_id is None:
        for adapter in list(_adapters.values()):
            adapter.close()
        _adapters.clear()
        if _adapter is not None and _adapter.connection_id not in _adapters:
            _adapter = None
        return

    config = get_connection_config(connection_id)
    adapter = _adapters.pop(config.connection_id, None)
    if adapter is not None:
        adapter.close()
    if _adapter is not None and _adapter.connection_id == config.connection_id:
        _adapter = None
