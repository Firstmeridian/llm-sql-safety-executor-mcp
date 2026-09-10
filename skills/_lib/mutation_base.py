"""
Mutation Base Module — Abstract Base Class for Write Operation Skills

Implements the Anthropic "plan-validate-execute" pattern with three stages:
1. validate(params): Pre-condition checks (e.g., record exists, status valid)
2. preview(params):  Dry-run — returns SQL preview and impact estimate
3. execute(params) or execute_with_binding(...): actual transactional write

Error Handling Chain:
    adapter.execute_write(sql, params, expected_rowcount=...)
      ├─ COMMIT confirmed → backward-compatible dict result
      └─ failure → typed WriteExecutionError with transaction evidence

    MutationBase.run_execute(...)
      ├─ success → best-effort success audit + result
      └─ failure → sanitized MutationExecutionError for structured MCP output

Execution Constraints:
    mutation.py write paths should ONLY call self.adapter.execute_write().
    Direct file I/O, network requests, or subprocess calls are prohibited.
    Enforced by code review (not runtime sandbox).

Design References:
- Anthropic: "Low freedom for fragile operations" — mutation.py defines each step
- Anthropic: "Verifiable intermediate outputs" — preview before execute
- FastMCP: ToolError inherits FastMCPError, bypasses mask_error_details
- MCP Spec §7: Validate all tool inputs
"""

import logging
from abc import ABC, abstractmethod

from fastmcp.exceptions import ToolError
from db_adapter import (
    WriteExecutionError,
    WriteExecutionOutcome,
)

logger = logging.getLogger(__name__)


class MutationWriteError(ToolError):
    """Keep direct Skill callers compatible while retaining adapter evidence."""

    def __init__(
        self,
        write_error: WriteExecutionError,
        message: str | None = None,
    ) -> None:
        super().__init__(message or str(write_error))
        self.write_error = write_error


class MutationExecutionError(ToolError):
    """Sanitized execution failure plus whole-Skill outcome evidence."""

    def __init__(
        self,
        message: str,
        *,
        execution_outcome: str,
        error_code: str,
        audit_logged: bool,
    ) -> None:
        super().__init__(message)
        self.execution_outcome = execution_outcome
        self.error_code = error_code
        self.audit_logged = audit_logged


class MutationExecutionResult(dict):
    """Internal result carrying whole-Skill outcome evidence out of the base."""

    def __init__(self, result: dict, *, execution_outcome: str) -> None:
        super().__init__(result)
        self.execution_outcome = execution_outcome


class MutationBase(ABC):
    """
    Abstract base class for mutation skills.

    Each mutation.py must export a class named 'Mutation' that inherits
    from this base class and implements validate(), preview(), and execute().

    The adapter and audit_logger are injected at instantiation by
    skill_loader.load_mutation().

    Attributes:
        adapter: DatabaseAdapter instance (provides execute_write())
        logger: AuditLogger instance (provides log())
    """

    # Only built-ins that perform one adapter-managed statement opt in. A
    # custom Skill may have issued other statements or external side effects,
    # so one adapter exception cannot prove its whole operation rolled back.
    exact_transaction_outcome = False

    def __init__(self, adapter, audit_logger):
        """
        Initialize with injected dependencies.

        Args:
            adapter: DatabaseAdapter instance (MySQLAdapter or SQLiteAdapter)
            audit_logger: AuditLogger instance for recording operations
        """
        self.adapter = adapter
        self.logger = audit_logger

    @abstractmethod
    def validate(self, params: dict) -> dict:
        """
        Pre-condition validation before any write.

        Should check business rules (e.g., record exists, valid state transition).
        Called in both preview and execute phases.

        Args:
            params: Validated parameters from frontmatter schema

        Returns:
            {"valid": True} on success
            {"valid": False, "errors": ["reason1", ...]} on failure
        """
        pass

    @abstractmethod
    def preview(self, params: dict) -> dict:
        """
        Dry-run: generate SQL preview and impact estimate without writing.

        Called when confirm=False (default). Should show the user what
        WOULD happen if they confirm.

        Args:
            params: Validated parameters from frontmatter schema

        Returns:
            {
                "sql": "UPDATE ... WHERE ...",
                "bound_params": {"key": "value", ...},
                "affected_rows_estimate": N,  # optional
                "warnings": ["..."],           # optional
                "requires_confirmation": True
            }
            On failure, return {"error": "safe reason", ...}, return
            {"success": False, ...}, or raise ToolError. The server does not
            issue a token for any declared failure, including an empty or null
            error value.
        """
        pass

    @abstractmethod
    def execute(self, params: dict) -> dict:
        """
        Execute the actual write operation within a transaction.

        Should call self.adapter.execute_write(sql, params) for the
        actual database write. The base class wraps this with error
        handling and audit logging via run_execute().

        Args:
            params: Validated parameters from frontmatter schema

        Returns:
            {"success": True, "rowcount": N} on success

        Note:
            Subclasses implement the SQL logic. A Skill that requires preview
            state may make this unbound method raise ToolError and implement
            execute_with_binding() as its only write path. Use run_execute()
            in the MCP tool layer for automatic error handling and audit.
        """
        pass

    def build_execution_binding(
        self,
        params: dict,
        validation: dict,
        preview: dict,
    ) -> dict:
        """Return minimal displayed preview state that execution must honor."""
        return {}

    def execute_with_binding(
        self,
        params: dict,
        execution_binding: dict,
    ) -> dict:
        """Execute with verified preview state, rejecting ignored bindings."""
        if execution_binding:
            raise ToolError(
                "Mutation skill produced an execution binding but does not "
                "implement execute_with_binding()."
            )
        return self.execute(params)

    def run_execute(
        self,
        params: dict,
        skill_name: str,
        mode: str = "execute",
        client_id: str | None = None,
        connection_id: str | None = None,
        db_type: str | None = None,
        execution_binding: dict | None = None,
    ) -> MutationExecutionResult:
        """
        Template method: wraps execute() with error handling and audit logging.

        Called by the MCP tool layer (execute_mutation_skill). Adapter failures
        are sanitized and converted to MutationExecutionError so the server can
        return a structured execution outcome.

        Args:
            params: Validated parameters
            skill_name: Skill name for audit logging
            mode: "preview" or "execute"
            client_id: Optional MCP client id for audit logging
            connection_id: Optional configured connection id for audit logging
            db_type: Optional actual database type for audit logging
            execution_binding: Preview-time state verified by the token layer

        Returns:
            Result dict from execute() on success

        Raises:
            MutationExecutionError: On a processable execution failure.
        """
        try:
            result = self.execute_with_binding(params, execution_binding or {})
        except (WriteExecutionError, MutationWriteError) as caught_error:
            error = (
                caught_error.write_error
                if isinstance(caught_error, MutationWriteError)
                else caught_error
            )
            if self.exact_transaction_outcome:
                execution_outcome = error.execution_outcome.value
                error_code = error.error_code
            else:
                execution_outcome = WriteExecutionOutcome.UNKNOWN.value
                error_code = "execution_outcome_unknown"

            if error.error_code == "expected_rowcount_mismatch":
                if getattr(error, "actual_rowcount", None) == 0:
                    sanitized = (
                        "Mutation target no longer matches the previewed state; "
                        "the write was not committed."
                    )
                else:
                    sanitized = (
                        "Mutation target cardinality was unsafe; the write was "
                        "not committed."
                    )
            elif error.error_code == "commit_outcome_unknown":
                sanitized = "Database COMMIT result could not be confirmed."
            else:
                source_error = error.original_error
                sanitized = self.adapter._handle_error(
                    source_error if isinstance(source_error, Exception) else error
                )

            audit_logged = self._log_execution_failure(
                params=params,
                skill_name=skill_name,
                mode=mode,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
                message=sanitized,
                execution_outcome=execution_outcome,
                error_code=error_code,
            )
            raise MutationExecutionError(
                sanitized,
                execution_outcome=execution_outcome,
                error_code=error_code,
                audit_logged=audit_logged,
            ) from error
        except ToolError as error:
            # A custom Skill can raise after arbitrary work. Without complete
            # evidence, do not infer whole-Skill rollback from one statement.
            sanitized = str(error)
            audit_logged = self._log_execution_failure(
                params=params,
                skill_name=skill_name,
                mode=mode,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
                message=sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
            )
            raise MutationExecutionError(
                sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
                audit_logged=audit_logged,
            ) from error
        except Exception as error:
            sanitized = self.adapter._handle_error(error)
            logger.error("Mutation '%s' failed: %s", skill_name, sanitized)
            audit_logged = self._log_execution_failure(
                params=params,
                skill_name=skill_name,
                mode=mode,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
                message=sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
            )
            raise MutationExecutionError(
                sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
                audit_logged=audit_logged,
            ) from error

        if not isinstance(result, dict) or result.get("success") is not True:
            sanitized = (
                "Mutation Skill returned an invalid success result; its final "
                "write outcome cannot be confirmed."
            )
            audit_logged = self._log_execution_failure(
                params=params,
                skill_name=skill_name,
                mode=mode,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
                message=sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="invalid_skill_result",
            )
            raise MutationExecutionError(
                sanitized,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="invalid_skill_result",
                audit_logged=audit_logged,
            )

        adapter_outcome = getattr(result, "execution_outcome", None)
        adapter_outcome_value = getattr(adapter_outcome, "value", adapter_outcome)
        if self.exact_transaction_outcome:
            if adapter_outcome_value != WriteExecutionOutcome.COMMITTED.value:
                sanitized = (
                    "Mutation Skill reported success without confirmed COMMIT "
                    "evidence; its final write outcome cannot be confirmed."
                )
                audit_logged = self._log_execution_failure(
                    params=params,
                    skill_name=skill_name,
                    mode=mode,
                    client_id=client_id,
                    connection_id=connection_id,
                    db_type=db_type,
                    message=sanitized,
                    execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                    error_code="missing_commit_evidence",
                )
                raise MutationExecutionError(
                    sanitized,
                    execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                    error_code="missing_commit_evidence",
                    audit_logged=audit_logged,
                )
            success_outcome = WriteExecutionOutcome.COMMITTED.value
        else:
            # A custom Skill's ordinary dict return proves only that its Python
            # handler completed. It does not prove a whole-Skill transaction,
            # the absence of external effects, or a database COMMIT.
            success_outcome = WriteExecutionOutcome.UNKNOWN.value

        try:
            audit_result = self.logger.log(
                skill_name=skill_name,
                params=params,
                mode=mode,
                result={**result, "execution_outcome": success_outcome},
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
            )
            audit_logged = True if audit_result is None else bool(audit_result)
        except Exception as audit_error:
            logger.warning(
                "Mutation success audit failed after Skill completion (%s): %s",
                success_outcome,
                audit_error.__class__.__name__,
            )
            audit_logged = False
        return MutationExecutionResult(
            {**result, "_audit_logged": audit_logged},
            execution_outcome=success_outcome,
        )

    def _log_execution_failure(
        self,
        *,
        params: dict,
        skill_name: str,
        mode: str,
        client_id: str | None,
        connection_id: str | None,
        db_type: str | None,
        message: str,
        execution_outcome: str,
        error_code: str,
    ) -> bool:
        """Write one best-effort business-failure audit entry."""
        try:
            audit_result = self.logger.log(
                skill_name=skill_name,
                params=params,
                mode=mode,
                result={
                    "success": False,
                    "error": message,
                    "execution_outcome": execution_outcome,
                    "error_code": error_code,
                },
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
            )
            return True if audit_result is None else bool(audit_result)
        except Exception as audit_error:
            logger.warning(
                "Mutation failure audit failed: %s",
                audit_error.__class__.__name__,
            )
            return False
