from __future__ import annotations
import logging
import time
from typing import Annotated
from pydantic import Field
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    OperationContext as Context,
    OperationResult as ToolResult,
)
from sql_safety_executor.database.diagnostics import (
    ConnectionScope,
    DiagnosticsUnavailable,
    diagnostic_budget,
)

logger = logging.getLogger(__name__)


from sql_safety_executor.core.connections import (
    _policy_summary,
    _select_diagnostic_configs,
)
from sql_safety_executor.core.results import _tool_result


async def list_connections(runtime, ctx: Context) -> ToolResult:
    """List configured database connection ids and non-sensitive policy metadata."""
    start_time = time.perf_counter()
    await ctx.info("Listing configured database connections")

    default_connection_id = runtime.default_connection_id()
    connections = []
    for config in runtime.registry.list_configs():
        connections.append(
            {
                "connection_id": config.connection_id,
                "db_type": config.db_type,
                "is_default": config.connection_id == default_connection_id,
                "query_timeout_seconds": config.query_timeout_seconds,
                "connect_timeout_seconds": config.connect_timeout_seconds,
                "policy": _policy_summary(config.policy),
            }
        )

    payload = {
        "success": True,
        "default_connection_id": default_connection_id,
        "connection_count": len(connections),
        "connections": connections,
        "hint": (
            "Configuration only; no database was inspected. allowed_tables is an "
            "access policy, not proof of table existence or a complete table inventory. "
            "Say 'configured to allow orders', not 'the database only has orders'."
        ),
    }
    return _tool_result(
        runtime,
        payload,
        tool_name="list_connections",
        start_time=start_time,
        success=True,
        connection_count=len(connections),
    )


async def check_connection(
    runtime,
    ctx: Context,
    connection_id: Annotated[
        str | None,
        Field(
            description=(
                "Configured alias for scope='single'; omit or use null for the default. "
                "Pass an already resolved target explicitly. Must be omitted or null for scope='all'."
            ),
            min_length=1,
            max_length=64,
        ),
    ] = None,
    scope: Annotated[
        ConnectionScope,
        Field(
            description="single checks one alias or the default; all explicitly checks every configured alias.",
        ),
    ] = "single",
) -> ToolResult:
    """Check fresh connectivity to one or all configured database connections."""
    start_time = time.perf_counter()
    configs = _select_diagnostic_configs(runtime, connection_id, scope)
    try:
        report = await runtime.diagnostics.run(
            configs,
            diagnostic_budget(runtime.tool_timeout),
            scope=scope,
        )
    except DiagnosticsUnavailable as exc:
        raise ToolError(str(exc)) from exc
    return _tool_result(
        runtime,
        report.model_dump(),
        tool_name="check_connection",
        start_time=start_time,
        connection_config=configs[0] if scope == "single" else None,
        connection_scope=scope,
        success=report.all_connected and not report.cleanup_failed,
        cleanup_failed=report.cleanup_failed,
        connection_count=report.connection_count,
        connected_count=report.connected_count,
    )
