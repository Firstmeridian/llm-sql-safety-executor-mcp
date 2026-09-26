from __future__ import annotations
import logging
from typing import Any
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    ConnectionContext,
)
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.diagnostics import ConnectionScope

logger = logging.getLogger(__name__)


def _resolve_connection_context(
    runtime, connection_id: str | None = None
) -> ConnectionContext:
    """Resolve the target connection before policy, schema, or execution."""
    try:
        config = runtime.registry.get_config(connection_id)
        adapter = runtime.registry.get_adapter(config.connection_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ConnectionContext(
        connection_id=config.connection_id,
        config=config,
        adapter=adapter,
        policy=config.policy,
    )


def _select_diagnostic_configs(
    runtime,
    connection_id: str | None = None,
    scope: ConnectionScope = "single",
) -> list[DatabaseConfig]:
    """Validate and resolve diagnostics without obtaining a business adapter.

    Also used by telemetry before execution so busy/disabled errors retain the
    actual request scope. Invalid requests do not acquire a connection identity.
    """
    if not isinstance(scope, str) or scope not in ("single", "all"):
        raise ToolError("scope must be 'single' or 'all'.")
    if scope == "all":
        if connection_id is not None:
            raise ToolError("connection_id must be omitted or null when scope='all'.")
        return runtime.registry.list_configs()
    if connection_id is not None and (
        not isinstance(connection_id, str)
        or not connection_id.strip()
        or len(connection_id) > 64
    ):
        raise ToolError("connection_id must be a non-empty configured alias or null.")
    try:
        return [runtime.registry.get_config(connection_id)]
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _policy_summary(policy: ConnectionPolicy) -> dict[str, Any]:
    """Return a non-sensitive summary of connection policy."""
    allowed_tables = policy.allowed_tables
    if allowed_tables is None:
        mode = "unrestricted"
        values: list[str] | None = None
    elif "*" in allowed_tables:
        mode = "explicit_all"
        values = ["*"]
    else:
        mode = "allowlist"
        values = sorted(allowed_tables)
    mutation_skills = policy.mutation_skills
    if "*" in mutation_skills:
        mutation_skills_mode = "explicit_all"
        mutation_skill_values = ["*"]
    elif mutation_skills:
        mutation_skills_mode = "allowlist"
        mutation_skill_values = sorted(mutation_skills)
    else:
        mutation_skills_mode = "deny_all"
        mutation_skill_values = []

    return {
        "read_mode": policy.read_mode,
        "read_enabled": policy.read_mode != "deny" and bool(allowed_tables),
        "allow_union": policy.allow_union,
        "allowed_tables_mode": mode,
        "allowed_tables": values,
        "allowed_tables_count": len(allowed_tables)
        if allowed_tables is not None
        else None,
        "allow_mutations": policy.allow_mutations,
        "mutation_skills_mode": mutation_skills_mode,
        "mutation_skills": mutation_skill_values,
        "mutation_skills_count": len(mutation_skills),
    }


def _public_database_name(connection: ConnectionContext) -> str | None:
    """Return a non-sensitive database display name for tool payloads/logs."""
    if connection.db_type == "sqlite":
        return f"sqlite:{connection.connection_id}"
    return connection.adapter.get_database_name()


def require_read_access(connection: ConnectionContext) -> None:
    policy = connection.policy
    if policy.read_mode == "deny" or (
        policy.read_mode == "allowlist" and not policy.allowed_tables
    ):
        raise ToolError("Reading is disabled by the target connection read policy.")
