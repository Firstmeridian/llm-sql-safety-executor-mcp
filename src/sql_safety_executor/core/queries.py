from __future__ import annotations
import logging
import time
from typing import Annotated
from sql_safety_executor.core.types import (
    OperationContext as Context,
    OperationResult as ToolResult,
)

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import _CONNECTION_ID_FIELD, _SQL_QUERY_FIELD

from sql_safety_executor.core.connections import _resolve_connection_context
from sql_safety_executor.core.policy import _prepare_sql_read
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.core.results import (
    _prepare_read_result,
    ReadResultError,
    _tool_result,
)


async def query(
    runtime,
    sql: Annotated[str, _SQL_QUERY_FIELD],
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Execute one policy-approved read-only SQL statement on the database."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    if (
        runtime.config.server.limits.sql_chars > 0
        and len(sql) > runtime.config.server.limits.sql_chars
    ):
        await ctx.warning(
            f"Rejected overlong SQL query: {len(sql)} characters "
            f"(max {runtime.config.server.limits.sql_chars})"
        )
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": (
                    "SQL query is too long; maximum length is "
                    f"{runtime.config.server.limits.sql_chars} characters"
                ),
                "error_code": "sql_too_long",
                "hint": "Shorten the query within the configured SQL length limit.",
                "query_length": len(sql),
                "max_sql_length": runtime.config.server.limits.sql_chars,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="query",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    await ctx.info(f"Executing query on connection '{connection.connection_id}': {sql}")

    # Validate the shared read-query policy used by raw queries and query skills.
    plan = _prepare_sql_read(runtime, sql, connection.policy, adapter=connection.adapter)
    decision = plan.decision
    if not decision.allowed:
        await ctx.warning(f"Rejected query: {decision.error_code}")
        return _tool_result(
            runtime,
            {
                **decision.error_payload(),
                "query": sql,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="query",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    try:
        result = connection.adapter.execute_read(sql, connection.config.query_timeout_seconds, policy=connection.policy, analysis=plan.analysis)
        prepared = _prepare_read_result(runtime, result)
    except (DatabaseQueryError, ReadResultError) as error:
        await ctx.error(f"Query failed: {error.error_code}")
        return _tool_result(
            runtime,
            {
                **error.error_payload(),
                "query": sql,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="query",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    if prepared["truncated"]:
        await ctx.warning(prepared["truncation_note"])
    else:
        await ctx.info(f"Query returned {prepared['total_rows']} rows")

    payload = {
        "success": True,
        **prepared,
        "query": sql,
        "connection_id": connection.connection_id,
        "db_type": connection.db_type,
    }
    return _tool_result(
        runtime,
        payload,
        tool_name="query",
        start_time=start_time,
        connection=connection,
        success=True,
        row_count=prepared["row_count"],
        total_rows=prepared["total_rows"],
        truncated=prepared["truncated"],
    )
