from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Any

from .outcomes import MetadataQueryError
from .errors import DatabaseQueryError
from .relations import ReadRelation, RelationReference, render_relation_for_text

logger = logging.getLogger(__name__)


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

    @property
    @abstractmethod
    def metadata_schema(self) -> str:
        """Configured schema for metadata and internally generated reads; no I/O."""
        raise NotImplementedError

    def render_metadata_relation(self, reference: RelationReference) -> str:
        """Render the same scoped identity that the metadata tool authorized."""
        if reference.schema != self.metadata_schema:
            raise ValueError("Metadata relation must use the adapter's configured schema")
        return render_relation_for_text(reference, self.db_type)

    @property
    def cte_case_sensitive(self) -> bool | None:
        """Known CTE comparison rules; None means no verified capability yet."""
        return False if self.db_type == "sqlite" else None

    def resolve_cte_case_sensitive(self) -> bool:
        """Unknown backends retain exact matching; never infer a table grant."""
        return self.cte_case_sensitive is not False

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish database connection.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def execute(
        self, sql: str, timeout: int | float | None = None, params: dict | None = None
    ) -> list:
        """
        Execute a SQL query with timeout protection.

        Args:
            sql: SQL query to execute
            timeout: Optional timeout in seconds (overrides default)
            params: Optional parameter dict for named-parameter binding
                    (e.g., {"year": 2026} for ":year" in SQL template).
                    Uses SQLAlchemy text() parameterized execution.

        Returns:
            List of row tuples on success. Raises DatabaseQueryError on failure.
        """
        pass

    @abstractmethod
    def execute_write(
        self,
        sql: str,
        params: dict,
        timeout: int | None = None,
        *,
        expected_rowcount: int | None = None,
    ) -> dict:
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
            expected_rowcount: Optional exact affected-row invariant. It is
                checked after statement execution and before COMMIT.

        Returns:
            {"success": True, "rowcount": N} on success

        Raises:
            ExpectedRowcountMismatchError: The pre-COMMIT invariant failed.
            WriteExecutionError: A typed write/rollback/commit failure.
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
    def get_read_relations(self) -> list[ReadRelation]:
        """Observe table/view identities for readiness, without row estimates.

        This is distinct from table-only discovery. MetadataQueryError means
        observation failed; an empty list means no observed readable relations.
        It does not prove query executability or grant access to view sources.
        """
        raise NotImplementedError

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

    def get_indexes(self, table_name: str) -> list[dict[str, Any]]:
        """
        Get the table's indexes, primary key first, then by name.

        Each dict has name (None for an implicit SQLite rowid key), primary,
        unique, ordered columns (None for an expression key part), and matching
        key_parts with column and sort_order (asc/desc/None). SQLite key_parts
        add collation and its indexes add partial. MySQL key_parts instead add
        prefix_length; visible is True/False/None for optimizer visibility.
        Optional has_expression and type identify special index forms.
        Built-in adapters enforce fixed all-or-unavailable collection limits.
        Comments, expressions, partial-index predicates and cardinality are
        not returned.

        Raises:
            MetadataQueryError: If index metadata cannot be read within budget
        """
        raise MetadataQueryError("reading table indexes")

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

    def _execute_metadata(self, sql: str, operation: str, *, timeout: int | float | None = None, params: dict | None = None) -> list:
        try:
            return self.execute(sql, timeout=timeout, params=params)
        except DatabaseQueryError:
            raise MetadataQueryError(operation) from None

    def _handle_error(self, e: Exception, timeout: int | float | None = None) -> DatabaseQueryError:
        logger.warning("Database error: %s", e.__class__.__name__)
        return DatabaseQueryError()

    @property
    def connection_id(self) -> str:
        """Return the configured connection id for this adapter instance."""
        return getattr(self, "_connection_id", "default")

    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return database type identifier ('mysql', 'sqlite', etc.)."""
        pass
