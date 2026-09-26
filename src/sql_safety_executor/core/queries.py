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
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.core.results import (
    _serialize_result,
    _tool_result,
    _truncate_result,
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
    is_safe, error_msg = _validate_sql_query_policy(runtime, sql, connection.policy)
    if not is_safe:
        await ctx.warning(f"Rejected query: {error_msg}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": error_msg,
                "query": sql,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="query",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Execute query
    result = connection.adapter.execute(sql, connection.config.query_timeout_seconds)

    # Handle error
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Query failed: {result}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": result,
                "query": sql,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="query",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Success - Apply token optimization with truncation
    # Best practice: Limit response size to prevent context overflow
    # Reference: Google Gemini - "Token limits: function descriptions and parameters count toward input token limits"
    data = _serialize_result(result)
    total_rows = len(result) if isinstance(result, list) else 0

    # Apply truncation to prevent token explosion (root cause of 454K token issue)
    truncation_result = _truncate_result(runtime, data, total_rows)

    if truncation_result["truncated"]:
        await ctx.warning(
            f"Truncated returned payload: {truncation_result['returned_rows']}/{total_rows} rows shown. "
            f"Add WHERE/LIMIT/ORDER BY to limit database work and stabilize ordering."
        )
    else:
        await ctx.info(f"Query returned {total_rows} rows")

    payload = {
        "success": True,
        "data": truncation_result["data"],
        "row_count": truncation_result["returned_rows"],
        "total_rows": total_rows,
        "truncated": truncation_result["truncated"],
        "truncation_note": (
            f"Showing {truncation_result['returned_rows']}/{total_rows} fetched rows. "
            f"Truncation limits the returned payload only; add WHERE/LIMIT/ORDER BY "
            f"to limit database work and stabilize ordering."
        )
        if truncation_result["truncated"]
        else None,
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
        row_count=truncation_result["returned_rows"],
        total_rows=total_rows,
        truncated=truncation_result["truncated"],
    )
