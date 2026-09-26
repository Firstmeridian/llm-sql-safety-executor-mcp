from __future__ import annotations
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MetadataQueryError(RuntimeError):
    """Signal that adapter metadata could not be read without exposing DB details."""

    def __init__(self, operation: str):
        super().__init__(f"Database metadata query failed while {operation}.")


class WriteExecutionOutcome(str, Enum):
    """Database state supported by evidence collected inside execute_write()."""

    NOT_EXECUTED = "not_executed"
    ROLLED_BACK = "rolled_back"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


class WriteExecutionPhase(str, Enum):
    """Last transaction phase reached by a write attempt."""

    SETUP = "setup"
    EXECUTE = "execute"
    ROWCOUNT_CHECK = "rowcount_check"
    COMMIT = "commit"


class WriteExecutionResult(dict[str, Any]):
    """Backward-compatible dict result with typed internal commit evidence."""

    execution_outcome = WriteExecutionOutcome.COMMITTED

    def __init__(self, rowcount: int):
        super().__init__(success=True, rowcount=rowcount)


class WriteExecutionError(RuntimeError):
    """Typed adapter failure carrying the strongest known transaction outcome."""

    def __init__(
        self,
        message: str,
        *,
        execution_outcome: WriteExecutionOutcome,
        phase: WriteExecutionPhase,
        error_code: str,
        original_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.execution_outcome = execution_outcome
        self.phase = phase
        self.error_code = error_code
        self.original_error = original_error


class ExpectedRowcountMismatchError(WriteExecutionError):
    """Raised before COMMIT when a write affects an unexpected row count."""

    def __init__(
        self,
        *,
        expected_rowcount: int,
        actual_rowcount: int,
        execution_outcome: WriteExecutionOutcome,
        original_error: BaseException | None = None,
    ) -> None:
        super().__init__(
            (
                "Write affected an unexpected number of rows "
                f"(expected {expected_rowcount}, actual {actual_rowcount})."
            ),
            execution_outcome=execution_outcome,
            phase=WriteExecutionPhase.ROWCOUNT_CHECK,
            error_code=(
                "expected_rowcount_mismatch"
                if execution_outcome is WriteExecutionOutcome.ROLLED_BACK
                else (
                    "rollback_failed"
                    if original_error is not None
                    else "rollback_unconfirmed"
                )
            ),
            original_error=original_error,
        )
        self.expected_rowcount = expected_rowcount
        self.actual_rowcount = actual_rowcount


def _validate_expected_rowcount(expected_rowcount: int | None) -> None:
    """Validate the row-count invariant before opening a connection."""
    if expected_rowcount is None:
        return
    if isinstance(expected_rowcount, bool) or not isinstance(expected_rowcount, int):
        raise TypeError("expected_rowcount must be a non-negative integer or None")
    if expected_rowcount < 0:
        raise ValueError("expected_rowcount must be a non-negative integer or None")


def _write_connection_is_valid(connection: Any) -> bool:
    """Inspect without reconnecting an invalidated SQLAlchemy connection."""
    try:
        return (
            connection.closed is False
            and connection.invalidated is False
            and connection.connection.is_valid is True
        )
    except Exception:
        return False


def _rollback_outcome(
    transaction: Any,
    *,
    connection: Any,
    business_write_attempted: bool,
) -> tuple[WriteExecutionOutcome, BaseException | None]:
    """Attempt rollback without treating a post-COMMIT rollback as evidence."""
    # SQLAlchemy can finish rollback locally when the transaction is inactive
    # or its DBAPI connection was invalidated. That is not a server acknowledgement.
    rollback_can_be_confirmed = getattr(
        transaction, "is_active", False
    ) is True and _write_connection_is_valid(connection)
    try:
        transaction.rollback()
    except BaseException as rollback_error:
        logger.warning(
            "Write transaction rollback failed: %s",
            rollback_error.__class__.__name__,
        )
        if business_write_attempted:
            return WriteExecutionOutcome.UNKNOWN, rollback_error
        return WriteExecutionOutcome.NOT_EXECUTED, rollback_error
    if business_write_attempted:
        if rollback_can_be_confirmed and _write_connection_is_valid(connection):
            return WriteExecutionOutcome.ROLLED_BACK, None
        return WriteExecutionOutcome.UNKNOWN, None
    return WriteExecutionOutcome.NOT_EXECUTED, None


def _precommit_failure_error_code(
    outcome: WriteExecutionOutcome,
    rollback_error: BaseException | None,
) -> str:
    """Distinguish a raised rollback error from insufficient rollback proof."""
    if outcome is not WriteExecutionOutcome.UNKNOWN:
        return "database_execution_failed"
    if rollback_error is not None:
        return "rollback_failed"
    return "rollback_unconfirmed"


def _close_write_connection(connection: Any) -> None:
    """Best-effort connection cleanup that never changes a known DB outcome."""
    if connection is None:
        return
    try:
        connection.close()
    except BaseException as close_error:
        logger.warning(
            "Write connection cleanup failed after transaction resolution: %s",
            close_error.__class__.__name__,
        )
