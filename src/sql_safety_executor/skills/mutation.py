"""
Mutation Base Module — Abstract Base Class for Write Operation Skills

Implements the plan-validate-execute pattern with three stages:
1. validate(params): Pre-condition checks (e.g., record exists, status valid)
2. preview(params): Business context and state; the framework adds managed SQL
3. execute: either an imperative callback with conservative outcome semantics,
   or one framework-owned ManagedMutationPlan statement

Error Handling Chain:
    adapter.execute_write(sql, params, expected_rowcount=...)
      ├─ COMMIT confirmed → backward-compatible dict result
      └─ failure → typed WriteExecutionError with transaction evidence

    MutationBase.run_execute(...)
      ├─ success → best-effort success audit + result
      └─ failure → sanitized MutationExecutionError for structured MCP output

Execution Constraints:
    MutationBase.run_execute() is framework-owned and may not be overridden.
    Imperative mutation.py code is trusted and receives only conservative
    whole-Skill outcome semantics. ManagedMutationBase subclasses declare one
    immutable statement plan; confirmation executes it without a Skill callback.

Design References:
- Anthropic, Building Effective Agents: prefer simple, composable workflows.
  Framework-owned managed execution is this project's application of that advice.
- FastMCP: ToolError inherits FastMCPError, bypasses mask_error_details
- MCP Spec §7: Validate all tool inputs
"""

from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, final

import sqlparse
from sqlalchemy import text

from sql_safety_executor.core.types import OperationError as ToolError
from sql_safety_executor.database.outcomes import (
    WriteExecutionError,
    WriteExecutionOutcome,
)

logger = logging.getLogger(__name__)


_MANAGED_WRITE_TYPES = frozenset({"INSERT", "UPDATE", "DELETE"})
_MANAGED_SOURCE_TYPES = frozenset({"params", "binding", "constant"})
_MANAGED_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_MANAGED_RESULT_FIELDS = frozenset(
    {"success", "rowcount", "execution_outcome", "_audit_logged", "error", "error_code"}
)


@dataclass(frozen=True)
class ManagedMutationValue:
    """Declarative source for one SQL parameter or public result field."""

    target: str
    source: Literal["params", "binding", "constant"]
    key: str | None = None
    value: str | int | float | bool | None = None

    @classmethod
    def from_params(cls, target: str, key: str | None = None) -> "ManagedMutationValue":
        return cls(
            target=target,
            source="params",
            key=target if key is None else key,
        )

    @classmethod
    def from_binding(
        cls, target: str, key: str | None = None
    ) -> "ManagedMutationValue":
        return cls(
            target=target,
            source="binding",
            key=target if key is None else key,
        )

    @classmethod
    def constant(
        cls,
        target: str,
        value: str | int | float | bool | None,
    ) -> "ManagedMutationValue":
        return cls(target=target, source="constant", value=value)


@dataclass(frozen=True)
class ManagedMutationPlan:
    """One immutable statement executed solely by the mutation framework."""

    sql: str
    parameters: tuple[ManagedMutationValue, ...]
    expected_rowcount: int
    result_fields: tuple[ManagedMutationValue, ...] = ()


def _validate_managed_value(
    item: ManagedMutationValue,
    *,
    result_field: bool,
) -> None:
    if type(item) is not ManagedMutationValue:
        raise TypeError(
            "Managed mutation values must be ManagedMutationValue instances"
        )
    if not isinstance(item.target, str) or not _MANAGED_NAME_PATTERN.fullmatch(
        item.target
    ):
        raise TypeError("Managed mutation value targets must be safe identifiers")
    if result_field and item.target in _RESERVED_MANAGED_RESULT_FIELDS:
        raise TypeError(f"Managed mutation result field '{item.target}' is reserved")
    if item.source not in _MANAGED_SOURCE_TYPES:
        raise TypeError("Managed mutation value source is unsupported")
    if item.source in {"params", "binding"}:
        if not isinstance(item.key, str) or not _MANAGED_NAME_PATTERN.fullmatch(
            item.key
        ):
            raise TypeError(
                "Managed mutation parameter/binding keys must be safe identifiers"
            )
        if item.value is not None:
            raise TypeError(
                "Managed mutation non-constant values cannot define a constant"
            )
    else:
        if item.key is not None:
            raise TypeError("Managed mutation constants cannot define a source key")
        if type(item.value) not in {str, int, float, bool, type(None)}:
            raise TypeError("Managed mutation constants must be JSON scalar values")
        if isinstance(item.value, float) and not math.isfinite(item.value):
            raise TypeError("Managed mutation float constants must be finite")


def validate_managed_mutation_plan(plan: ManagedMutationPlan) -> ManagedMutationPlan:
    """Fail closed on plans that are not one direct, fully bound DML statement."""
    if type(plan) is not ManagedMutationPlan:
        raise TypeError("managed_plan must be a ManagedMutationPlan")
    if not isinstance(plan.sql, str) or not plan.sql.strip():
        raise TypeError("Managed mutation SQL must be a non-empty string")
    statements = [
        statement
        for statement in sqlparse.parse(plan.sql)
        if str(statement).strip(" \t\r\n;")
    ]
    if (
        len(statements) != 1
        or statements[0].get_type().upper() not in _MANAGED_WRITE_TYPES
    ):
        raise TypeError(
            "Managed mutation plans require one direct INSERT, UPDATE, or DELETE statement"
        )
    if isinstance(plan.expected_rowcount, bool) or not isinstance(
        plan.expected_rowcount, int
    ):
        raise TypeError(
            "Managed mutation expected_rowcount must be a non-negative integer"
        )
    if plan.expected_rowcount < 0:
        raise TypeError(
            "Managed mutation expected_rowcount must be a non-negative integer"
        )
    if type(plan.parameters) is not tuple or type(plan.result_fields) is not tuple:
        raise TypeError("Managed mutation parameters and result_fields must be tuples")

    parameter_targets: list[str] = []
    for item in plan.parameters:
        _validate_managed_value(item, result_field=False)
        parameter_targets.append(item.target)
    if len(parameter_targets) != len(set(parameter_targets)):
        raise TypeError("Managed mutation SQL parameter targets must be unique")

    bind_targets = set(text(plan.sql).compile().params)
    if bind_targets != set(parameter_targets):
        raise TypeError(
            "Managed mutation plan parameters must exactly match SQL named binds"
        )

    result_targets: list[str] = []
    for item in plan.result_fields:
        _validate_managed_value(item, result_field=True)
        result_targets.append(item.target)
    if len(result_targets) != len(set(result_targets)):
        raise TypeError("Managed mutation result field targets must be unique")
    return plan


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
    """Sanitized execution failure plus framework-classified outcome evidence."""

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
    """Internal result carrying framework-classified outcome evidence."""

    def __init__(self, result: dict, *, execution_outcome: str) -> None:
        super().__init__(result)
        self.execution_outcome = execution_outcome


class MutationBase(ABC):
    """
    Abstract base class for mutation skills.

    Each mutation.py must export a class named 'Mutation' that inherits from
    this base class. Imperative subclasses implement validate(), preview(), and
    execute(); managed subclasses inherit the final rejecting execute methods,
    implement preview hooks, and declare a ManagedMutationPlan.

    The adapter and audit_logger are injected at instantiation by
    skill_loader.load_mutation().

    Attributes:
        adapter: DatabaseAdapter instance (provides execute_write())
        logger: AuditLogger instance (provides log())
    """

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
        Called in preview and in imperative confirmation. Managed confirmation
        uses the cached plan and does not invoke this callback.

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
        Dry-run: describe the proposed effect without writing.

        Called when confirm=False (default). Should show the user what
        WOULD happen if they confirm.

        Args:
            params: Validated parameters from frontmatter schema

        Managed subclasses return business context, warnings and binding state
        only. They must not return preview_sql or bound_params: the framework
        generates those from the cached plan and final binding before issuing
        a preview token. Both SQL parameters and result mappings must resolve.

        Imperative return example:
            {
                "preview_sql": "UPDATE ... WHERE ...",
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

    @final
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
        Framework-owned template method for error handling and audit logging.

        Called by the MCP tool layer (execute_mutation_skill). Adapter failures
        are sanitized and converted to MutationExecutionError so the server can
        return a structured execution outcome. Mutation Skills must customize
        execute() or execute_with_binding(), not override this wrapper. The
        loader enforces that rule at runtime; @final also informs type checkers.

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
            execution_outcome = WriteExecutionOutcome.UNKNOWN.value
            error_code = "execution_outcome_unknown"

            if error.error_code == "expected_rowcount_mismatch":
                if getattr(error, "actual_rowcount", None) == 0:
                    reason = "Mutation target no longer matches the previewed state"
                else:
                    reason = "Mutation target cardinality was unsafe"
                # An imperative Skill may have committed earlier statements or
                # performed non-database effects. One rolled-back statement is
                # not evidence about the outcome of the whole callback.
                sanitized = f"{reason}; the whole Skill outcome cannot be confirmed."
            elif error.error_code == "commit_outcome_unknown":
                sanitized = "Database COMMIT result could not be confirmed."
            else:
                source_error = error.original_error
                sanitized = self.adapter._handle_error(
                    source_error if isinstance(source_error, Exception) else error
                )

            audit_logged = _log_execution_failure(
                audit_logger=self.logger,
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
            audit_logged = _log_execution_failure(
                audit_logger=self.logger,
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
            audit_logged = _log_execution_failure(
                audit_logger=self.logger,
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
            audit_logged = _log_execution_failure(
                audit_logger=self.logger,
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

        # A callback return proves only that its Python handler completed. It
        # does not prove a whole-Skill transaction or absence of other effects.
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


class ManagedMutationBase(MutationBase):
    """Preview-capable Skill whose confirmed write is owned by the framework.

    Subclasses declare ``managed_plan`` and may implement validate(), preview(),
    and build_execution_binding() for the preview phase. The MCP confirmation
    path does not instantiate or call the subclass.
    """

    managed_plan: ClassVar[ManagedMutationPlan]

    @final
    def execute(self, params: dict) -> dict:
        raise ToolError(
            "Managed mutations can only execute through the framework confirmation path."
        )

    @final
    def execute_with_binding(
        self,
        params: dict,
        execution_binding: dict,
    ) -> dict:
        raise ToolError(
            "Managed mutations can only execute through the framework confirmation path."
        )


def _resolve_managed_values(
    values: tuple[ManagedMutationValue, ...],
    *,
    params: dict,
    execution_binding: dict,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for item in values:
        if item.source == "params":
            source = params
            source_name = "validated parameters"
        elif item.source == "binding":
            source = execution_binding
            source_name = "preview binding"
        else:
            resolved[item.target] = item.value
            continue

        key = item.key
        if key is None or key not in source:
            raise KeyError(
                f"Managed mutation source key is missing from {source_name}: {key!r}"
            )
        value = source[key]
        if type(value) not in {str, int, float, bool, type(None)}:
            raise TypeError(
                f"Managed mutation source value from {source_name} must be a scalar"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                f"Managed mutation source value from {source_name} must be finite"
            )
        resolved[item.target] = value
    return resolved


def validate_managed_preview(preview: dict) -> None:
    """Keep the SQL and bound values under framework ownership."""
    if {"preview_sql", "bound_params"}.intersection(preview):
        raise ToolError(
            "Managed mutation preview must not supply preview_sql or bound_params; "
            "these fields are generated by the framework. No preview token was issued."
        )


def resolve_managed_plan_values(
    plan: ManagedMutationPlan,
    *,
    params: dict,
    execution_binding: dict,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use identical value resolution before issuing a handle and before writing."""
    return (
        _resolve_managed_values(
            plan.parameters, params=params, execution_binding=execution_binding
        ),
        _resolve_managed_values(
            plan.result_fields, params=params, execution_binding=execution_binding
        ),
    )


def _log_execution_failure(
    *,
    audit_logger: Any,
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
    try:
        audit_result = audit_logger.log(
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


def run_managed_mutation(
    *,
    plan: ManagedMutationPlan,
    adapter: Any,
    audit_logger: Any,
    params: dict,
    execution_binding: dict,
    skill_name: str,
    mode: str = "execute",
    client_id: str | None = None,
    connection_id: str | None = None,
    db_type: str | None = None,
) -> MutationExecutionResult:
    """Resolve and execute one cached managed statement without Skill callbacks."""
    try:
        statement_params, result_fields = resolve_managed_plan_values(
            plan,
            params=params,
            execution_binding=execution_binding,
        )
    except (KeyError, TypeError, ValueError) as error:
        message = (
            "Managed mutation preview state was incomplete; no write was attempted."
        )
        audit_logged = _log_execution_failure(
            audit_logger=audit_logger,
            params=params,
            skill_name=skill_name,
            mode=mode,
            client_id=client_id,
            connection_id=connection_id,
            db_type=db_type,
            message=message,
            execution_outcome=WriteExecutionOutcome.NOT_EXECUTED.value,
            error_code="managed_plan_resolution_failed",
        )
        raise MutationExecutionError(
            message,
            execution_outcome=WriteExecutionOutcome.NOT_EXECUTED.value,
            error_code="managed_plan_resolution_failed",
            audit_logged=audit_logged,
        ) from error

    try:
        write_result = adapter.execute_write(
            plan.sql,
            statement_params,
            expected_rowcount=plan.expected_rowcount,
        )
    except Exception as error:
        # Accept the adapter's typed protocol even across in-process module
        # reloads, where Python class identity changes. Only the framework-owned
        # adapter is invoked here; Skill code cannot supply this exception.
        raw_outcome = getattr(error, "execution_outcome", None)
        execution_outcome = getattr(raw_outcome, "value", raw_outcome)
        raw_error_code = getattr(error, "error_code", None)
        is_typed_write_error = (
            execution_outcome
            in {
                WriteExecutionOutcome.NOT_EXECUTED.value,
                WriteExecutionOutcome.ROLLED_BACK.value,
                WriteExecutionOutcome.UNKNOWN.value,
            }
            and isinstance(raw_error_code, str)
            and bool(raw_error_code)
        )
        if not is_typed_write_error:
            message = adapter._handle_error(error)
            audit_logged = _log_execution_failure(
                audit_logger=audit_logger,
                params=params,
                skill_name=skill_name,
                mode=mode,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
                message=message,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
            )
            raise MutationExecutionError(
                message,
                execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
                error_code="execution_outcome_unknown",
                audit_logged=audit_logged,
            ) from error

        typed_execution_outcome: str = (
            execution_outcome
            if isinstance(execution_outcome, str)
            else WriteExecutionOutcome.UNKNOWN.value
        )
        error_code: str = (
            raw_error_code
            if isinstance(raw_error_code, str)
            else "execution_outcome_unknown"
        )
        if error_code == "expected_rowcount_mismatch":
            if getattr(error, "actual_rowcount", None) == 0:
                reason = "Mutation target no longer matches the previewed state"
            else:
                reason = "Mutation target cardinality was unsafe"
            message = f"{reason}; the write was not committed."
        elif error_code == "commit_outcome_unknown":
            message = "Database COMMIT result could not be confirmed."
        else:
            source_error = getattr(error, "original_error", None)
            message = adapter._handle_error(
                source_error if isinstance(source_error, Exception) else error
            )
        audit_logged = _log_execution_failure(
            audit_logger=audit_logger,
            params=params,
            skill_name=skill_name,
            mode=mode,
            client_id=client_id,
            connection_id=connection_id,
            db_type=db_type,
            message=message,
            execution_outcome=typed_execution_outcome,
            error_code=error_code,
        )
        raise MutationExecutionError(
            message,
            execution_outcome=typed_execution_outcome,
            error_code=error_code,
            audit_logged=audit_logged,
        ) from error

    adapter_outcome = getattr(write_result, "execution_outcome", None)
    adapter_outcome_value = getattr(adapter_outcome, "value", adapter_outcome)
    if (
        not isinstance(write_result, dict)
        or write_result.get("success") is not True
        or adapter_outcome_value != WriteExecutionOutcome.COMMITTED.value
    ):
        message = (
            "Managed mutation completed without confirmed COMMIT evidence; "
            "its final write outcome cannot be confirmed."
        )
        audit_logged = _log_execution_failure(
            audit_logger=audit_logger,
            params=params,
            skill_name=skill_name,
            mode=mode,
            client_id=client_id,
            connection_id=connection_id,
            db_type=db_type,
            message=message,
            execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
            error_code="missing_commit_evidence",
        )
        raise MutationExecutionError(
            message,
            execution_outcome=WriteExecutionOutcome.UNKNOWN.value,
            error_code="missing_commit_evidence",
            audit_logged=audit_logged,
        )

    public_result = {**write_result, **result_fields}
    try:
        audit_result = audit_logger.log(
            skill_name=skill_name,
            params=params,
            mode=mode,
            result={
                **public_result,
                "execution_outcome": WriteExecutionOutcome.COMMITTED.value,
            },
            client_id=client_id,
            connection_id=connection_id,
            db_type=db_type,
        )
        audit_logged = True if audit_result is None else bool(audit_result)
    except Exception as audit_error:
        logger.warning(
            "Managed mutation success audit failed after commit: %s",
            audit_error.__class__.__name__,
        )
        audit_logged = False
    return MutationExecutionResult(
        {**public_result, "_audit_logged": audit_logged},
        execution_outcome=WriteExecutionOutcome.COMMITTED.value,
    )
