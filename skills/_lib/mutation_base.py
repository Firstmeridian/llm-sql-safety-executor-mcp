"""
Mutation Base Module — Abstract Base Class for Write Operation Skills

Implements the Anthropic "plan-validate-execute" pattern with three stages:
1. validate(params): Pre-condition checks (e.g., record exists, status valid)
2. preview(params):  Dry-run — returns SQL preview and impact estimate
3. execute(params):  Actual write via adapter.execute_write() in a transaction

Error Handling Chain:
    adapter.execute_write(sql, params)
      ├─ Success → return {"success": True, "rowcount": N}
      └─ Failure → SQLAlchemyError propagates naturally
    
    MutationBase.execute(params)  (base class template)
      ├─ try:
      │    result = self.adapter.execute_write(sql, params)
      │    self.logger.log(...)
      │    return result
      └─ except Exception as e:
           sanitized = self.adapter._handle_error(e)
           raise ToolError(sanitized)  → FastMCP passes through to Client

Execution Constraints:
    mutation.py execute() should ONLY call self.adapter.execute_write().
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

logger = logging.getLogger(__name__)


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
            Subclasses implement the SQL logic. Use run_execute() in the
            MCP tool layer for automatic error handling and audit logging.
        """
        pass

    def build_execution_binding(
        self,
        params: dict,
        validation: dict,
        preview: dict,
    ) -> dict:
        """Return minimal preview-time state that execution must honor."""
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
    ) -> dict:
        """
        Template method: wraps execute() with error handling and audit logging.

        Called by the MCP tool layer (execute_mutation_skill). Catches
        exceptions from adapter.execute_write(), sanitizes via
        adapter._handle_error(), and raises ToolError for safe client delivery.

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
            ToolError: On any execution failure (sanitized error message)
        """
        try:
            result = self.execute_with_binding(params, execution_binding or {})
            audit_result = self.logger.log(
                skill_name=skill_name,
                params=params,
                mode=mode,
                result=result,
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
            )
            audit_logged = True if audit_result is None else bool(audit_result)
            if isinstance(result, dict):
                result = {**result, "_audit_logged": audit_logged}
            return result
        except ToolError as e:
            # Audit-log business logic failures before re-raising
            self.logger.log(
                skill_name=skill_name,
                params=params,
                mode=mode,
                result={"success": False, "error": str(e)},
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
            )
            raise
        except Exception as e:
            sanitized = self.adapter._handle_error(e)
            logger.error(f"Mutation '{skill_name}' failed: {sanitized}")
            self.logger.log(
                skill_name=skill_name,
                params=params,
                mode=mode,
                result={"success": False, "error": sanitized},
                client_id=client_id,
                connection_id=connection_id,
                db_type=db_type,
            )
            raise ToolError(sanitized) from e
