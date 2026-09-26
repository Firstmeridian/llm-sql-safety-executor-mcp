from __future__ import annotations
import logging
import time
from typing import Annotated, Any
from pydantic import Field
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    OperationContext as Context,
    OperationResult as ToolResult,
)
from sql_safety_executor.database.outcomes import MetadataQueryError

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import _CONNECTION_ID_FIELD, SchemaDetailLevel

from sql_safety_executor.core.connections import (
    require_read_access,
    _public_database_name,
    _resolve_connection_context,
)
from sql_safety_executor.core.policy import _is_table_allowed, _is_valid_identifier
from sql_safety_executor.core.results import (
    _metadata_failure_result,
    _normalize_schema_detail_level,
    _require_boolean,
    _schema_metadata_signature,
    _serialize_result,
    _tool_result,
)


async def list_tables(
    runtime,
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Visible database overview: list allowed tables with approximate row counts."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    require_read_access(connection)
    await ctx.info(
        f"Listing database tables on connection '{connection.connection_id}'"
    )

    adapter = connection.adapter
    database_name = _public_database_name(connection)

    # Use adapter method for cross-database compatibility
    try:
        tables = adapter.get_tables()
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            runtime,
            ctx=ctx,
            tool_name="list_tables",
            start_time=start_time,
            connection=connection,
            error=exc,
        )

    if not tables:
        await ctx.info(f"No tables found in {database_name}")
        return _tool_result(
            runtime,
            {
                "success": True,
                "database_name": database_name,
                "db_type": connection.db_type,
                "connection_id": connection.connection_id,
                "returned_table_count": 0,
                "total_tables": 0,
                "tables": [],
                "row_count_approximate": True,
                "truncated": False,
                "truncation_note": None,
                "hint": "No tables found in database.",
            },
            tool_name="list_tables",
            start_time=start_time,
            connection=connection,
            success=True,
            returned_table_count=0,
            total_tables=0,
            truncated=False,
        )

    # Filter by allowlist if configured (P1 Security)
    # Skip filtering if read.mode=all (explicit allow all)
    allowed_tables = connection.policy.allowed_tables
    if allowed_tables is not None and "*" not in allowed_tables:
        original_count = len(tables)
        tables = [t for t in tables if t["table_name"].lower() in allowed_tables]
        if len(tables) < original_count:
            await ctx.info(
                f"Filtered {original_count - len(tables)} tables by allowlist"
            )

    # Apply truncation to prevent token overflow (consistent with get_full_schema)
    total_tables = len(tables)
    truncated = False
    if (
        runtime.config.server.limits.overview_tables > 0
        and total_tables > runtime.config.server.limits.overview_tables
    ):
        tables = tables[: runtime.config.server.limits.overview_tables]
        truncated = True
        await ctx.warning(
            f"Overview truncated: showing {runtime.config.server.limits.overview_tables}/{total_tables} tables"
        )

    await ctx.info(f"Found {len(tables)} tables in {database_name}")

    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    payload = {
        "success": True,
        "database_name": database_name,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "returned_table_count": len(tables),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "tables": tables,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(tables)}/{total_tables} tables. Use describe_table(table_name=...) for specific tables."
        )
        if truncated
        else None,
        "hint": (
            "Row counts are estimates; null means an estimate is unavailable, "
            "not that the table is empty. For broad columns, call "
            "get_full_schema(detail_level='compact') directly; for one selected "
            "table's full adapter-visible column metadata, use "
            "describe_table(table_name=...). This is not complete DDL. total_tables = "
            f"visible after allowlist. DB type: {connection.db_type}"
        ),
    }
    return _tool_result(
        runtime,
        payload,
        tool_name="list_tables",
        start_time=start_time,
        success=True,
        connection=connection,
        returned_table_count=len(tables),
        total_tables=total_tables,
        truncated=truncated,
    )


async def describe_table(
    runtime,
    table_name: str,
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Get one selected table's full adapter-visible column metadata and row count"""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    require_read_access(connection)
    # Validate table name to prevent SQL injection
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Invalid table name: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="describe_table",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Check table allowlist (P1 Security)
    if not _is_table_allowed(runtime, table_name, connection.policy):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Access denied to table: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="describe_table",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    await ctx.info(
        f"Describing table on connection '{connection.connection_id}': {table_name}"
    )

    # Use adapter methods for cross-database compatibility
    adapter = connection.adapter

    try:
        columns_data = adapter.get_columns(table_name)
        row_count = adapter.get_row_estimate(table_name)
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            runtime,
            ctx=ctx,
            tool_name="describe_table",
            start_time=start_time,
            connection=connection,
            error=exc,
        )

    if not columns_data:
        await ctx.error(f"Table not found: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Table '{table_name}' not found",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="describe_table",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Do not turn an unavailable estimate into a false "small table" signal.
    row_count_approximate = True if row_count is not None else None
    is_large = (
        row_count > runtime.config.server.tools.large_table_threshold
        if row_count is not None
        else None
    )
    displayed_row_count = f"~{row_count}" if row_count is not None else "unknown"

    await ctx.info(
        f"Table {table_name}: {displayed_row_count} rows, {len(columns_data)} columns"
    )

    # Build response with query recommendations
    result_payload = {
        "success": True,
        "table_name": table_name,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "row_count": row_count,
        "row_count_approximate": row_count_approximate,
        "column_count": len(columns_data),
        "columns": columns_data,
        "is_large": is_large,
    }

    # Add recommendation only for large tables (reduce token overhead)
    if is_large is True:
        result_payload["recommendation"] = (
            f"Large table (~{row_count} rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
        )

    return _tool_result(
        runtime,
        result_payload,
        tool_name="describe_table",
        start_time=start_time,
        connection=connection,
        success=True,
        row_count=row_count,
        is_large=is_large,
    )


async def get_full_schema(
    runtime,
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    detail_level: Annotated[
        SchemaDetailLevel,
        Field(
            description=(
                "Use compact for table discovery, broad schema explanation, or "
                "multi-table planning. Use full for nullable, default, and key "
                "metadata. Defaults to compact."
            )
        ),
    ] = "compact",
    group_identical: Annotated[
        bool,
        Field(
            description=(
                "Compact mode only; defaults to true. Group tables when their "
                "complete current adapter-visible column metadata and column "
                "order are equal. This is not proof of full DDL, index, or "
                "constraint equivalence. Ignored in full mode."
            )
        ),
    ] = True,
) -> ToolResult:
    """Get a compact or full visible database schema overview in one call."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    require_read_access(connection)
    try:
        resolved_detail_level = _normalize_schema_detail_level(detail_level)
        resolved_group_identical = _require_boolean(
            group_identical,
            "group_identical",
        )
    except ValueError as exc:
        await ctx.warning(f"Schema projection parameter error: {exc}")
        raise ToolError(str(exc)) from exc

    await ctx.info(
        "Fetching visible database schema for connection "
        f"'{connection.connection_id}' (detail_level={resolved_detail_level}, "
        f"group_identical={resolved_group_identical})..."
    )

    adapter = connection.adapter

    # Step 1: Get all tables with row counts using adapter
    try:
        tables_data = adapter.get_tables()
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            runtime,
            ctx=ctx,
            tool_name="get_full_schema",
            start_time=start_time,
            connection=connection,
            error=exc,
        )

    if not tables_data:
        await ctx.info("No tables found in database")
        empty_projection = (
            {
                "schema_groups": [],
                "schema_group_count": 0,
                "grouped_by_schema": resolved_group_identical,
                "grouping_basis": (
                    "adapter_visible_column_metadata_and_order"
                    if resolved_group_identical
                    else "none"
                ),
            }
            if resolved_detail_level == "compact"
            else {"schema": {}}
        )
        return _tool_result(
            runtime,
            {
                "success": True,
                **empty_projection,
                "db_type": connection.db_type,
                "connection_id": connection.connection_id,
                "detail_level": resolved_detail_level,
                "returned_table_count": 0,
                "total_tables": 0,
                "total_columns": 0,
                "row_count_approximate": True,
                "truncated": False,
                "truncation_note": None,
                "hint": "No tables found in database.",
            },
            tool_name="get_full_schema",
            start_time=start_time,
            connection=connection,
            success=True,
            returned_table_count=0,
            total_tables=0,
            truncated=False,
            detail_level=resolved_detail_level,
        )

    # Filter tables by allowlist if configured (P1 Security)
    # Skip filtering if read.mode=all (explicit allow all)
    allowed_tables = connection.policy.allowed_tables
    if allowed_tables is not None and "*" not in allowed_tables:
        tables_data = [
            t for t in tables_data if t["table_name"].lower() in allowed_tables
        ]
        await ctx.info(f"Allowlist active: showing {len(tables_data)} allowed tables")

    # Step 2: Apply truncation to prevent token overflow (P0 security/performance)
    # Reference: Google Gemini best practices - token limits
    total_tables = len(tables_data)
    truncated = False

    if (
        runtime.config.server.limits.schema_tables > 0
        and total_tables > runtime.config.server.limits.schema_tables
    ):
        tables_data = tables_data[: runtime.config.server.limits.schema_tables]
        truncated = True
        await ctx.warning(
            f"Schema truncated: showing {runtime.config.server.limits.schema_tables}/{total_tables} tables"
        )

    # Step 3: Read each table once, then project the same metadata for either mode.
    table_metadata = []
    for table in tables_data:
        table_name = table["table_name"]
        if not _is_valid_identifier(table_name):
            return await _metadata_failure_result(
                runtime,
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=ValueError(
                    "Database contains a table name that schema tools cannot "
                    "safely describe."
                ),
                error_code="unsupported_metadata_identifier",
            )
        try:
            columns_data = adapter.get_columns(table_name)
        except MetadataQueryError as exc:
            return await _metadata_failure_result(
                runtime,
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=exc,
            )
        if not columns_data:
            return await _metadata_failure_result(
                runtime,
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=MetadataQueryError(
                    "reading columns for a table returned by table discovery"
                ),
            )
        table_metadata.append((table, columns_data))

    total_columns_shown = sum(len(columns) for _, columns in table_metadata)
    if resolved_detail_level == "compact":
        groups_by_signature: dict[str, dict[str, Any]] = {}
        for index, (table, columns_data) in enumerate(table_metadata):
            signature = (
                _schema_metadata_signature(columns_data)
                if resolved_group_identical
                else f"table:{index}"
            )
            group = groups_by_signature.get(signature)
            if group is None:
                group = {
                    "tables": [],
                    "column_count": len(columns_data),
                    "columns": [
                        [column["column_name"], column["data_type"]]
                        for column in columns_data
                    ],
                    "primary_key": [
                        column["column_name"]
                        for column in columns_data
                        if column["key_type"] == "PRI"
                    ],
                }
                groups_by_signature[signature] = group
            group["tables"].append(
                {
                    "name": table["table_name"],
                    "row_count": table["row_count"],
                }
            )
        schema_groups = list(groups_by_signature.values())
        projection = {
            "schema_groups": schema_groups,
            "schema_group_count": len(schema_groups),
            "grouped_by_schema": resolved_group_identical,
            "grouping_basis": (
                "adapter_visible_column_metadata_and_order"
                if resolved_group_identical
                else "none"
            ),
        }
        hint = (
            "Columns are [name, type] pairs. Tables in one group have identical "
            "current adapter-visible column metadata and order; this does not "
            "prove full DDL, index, or constraint equivalence. Use "
            "describe_table(table_name=...) for one table's nullable, default, and "
            "non-primary key details, or get_full_schema(detail_level='full') "
            "when those fields are needed across several tables."
        )
    else:
        schema = {
            table["table_name"]: {
                "row_count": table["row_count"],
                "columns": [
                    {
                        "name": column["column_name"],
                        "type": column["data_type"],
                        "nullable": column["nullable"],
                        "key": column["key_type"],
                        "default": column["default_value"],
                    }
                    for column in columns_data
                ],
            }
            for table, columns_data in table_metadata
        }
        projection = {"schema": schema}
        hint = (
            "Full adapter column metadata is shown. Use LIMIT for large tables "
            f"(row_count > {runtime.config.server.tools.large_table_threshold})."
        )

    returned_table_count = len(table_metadata)
    await ctx.info(
        f"Schema loaded: {returned_table_count} tables, "
        f"{total_columns_shown} columns ({resolved_detail_level})"
    )

    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    payload = {
        "success": True,
        **projection,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "detail_level": resolved_detail_level,
        "returned_table_count": returned_table_count,
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "total_columns": total_columns_shown,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {returned_table_count}/{total_tables} tables. "
            "Use describe_table(table_name=...) for specific tables."
        )
        if truncated
        else None,
        "hint": (
            f"Row counts are estimates; null means unavailable, not empty. "
            f"{hint} total_tables = visible after "
            f"allowlist. DB type: {connection.db_type}"
        ),
    }
    return _tool_result(
        runtime,
        payload,
        tool_name="get_full_schema",
        start_time=start_time,
        success=True,
        connection=connection,
        returned_table_count=returned_table_count,
        total_tables=total_tables,
        truncated=truncated,
        detail_level=resolved_detail_level,
    )


async def get_table_summary(
    runtime,
    table_name: str,
    ctx: Context,
    exact_count: Annotated[
        bool,
        Field(
            description=(
                "When true, execute SELECT COUNT(*) for an exact row count. "
                "This may require a full scan, be slow on large tables, and "
                "encounter MySQL metadata-lock contention. Use only when "
                "precision is required. Defaults to false."
            )
        ),
    ] = False,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Table statistics with optional exact row count."""
    start_time = time.perf_counter()
    try:
        resolved_exact_count = _require_boolean(exact_count, "exact_count")
    except ValueError as exc:
        await ctx.warning(f"Table summary parameter error: {exc}")
        raise ToolError(str(exc)) from exc
    connection = _resolve_connection_context(runtime, connection_id)
    require_read_access(connection)
    # Validate table name
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Invalid table name: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="get_table_summary",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Check table allowlist (P1 Security)
    if not _is_table_allowed(runtime, table_name, connection.policy):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Access denied to table: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="get_table_summary",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    await ctx.info(
        f"Getting summary for table on connection '{connection.connection_id}': "
        f"{table_name} (exact_count={resolved_exact_count})"
    )

    adapter = connection.adapter

    # Get row count — use adapter for cross-database compatibility
    if resolved_exact_count:
        # WARNING: COUNT(*) can be slow on large tables
        row_count_approximate = False
        await ctx.warning(
            f"Running COUNT(*) on {table_name} - may be slow on large tables"
        )
        quote = "`" if adapter.db_type == "mysql" else '"'
        count_sql = f"SELECT COUNT(*) as total_rows FROM {quote}{table_name}{quote}"
        count_result = adapter.execute(count_sql)
        if isinstance(count_result, str) and count_result.startswith("Error:"):
            await ctx.error(f"Failed to count rows: {count_result}")
            return _tool_result(
                runtime,
                {
                    "success": False,
                    "error": count_result,
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                },
                tool_name="get_table_summary",
                start_time=start_time,
                connection=connection,
                success=False,
            )
        count_data = _serialize_result(count_result)
        total_rows = count_data[0]["total_rows"] if count_data else 0
        total_rows = total_rows or 0
    else:
        # Fast estimate via adapter (uses INFORMATION_SCHEMA or sqlite_stat1)
        try:
            total_rows = adapter.get_row_estimate(table_name)
        except MetadataQueryError as exc:
            return await _metadata_failure_result(
                runtime,
                ctx=ctx,
                tool_name="get_table_summary",
                start_time=start_time,
                connection=connection,
                error=exc,
            )
        row_count_approximate = True if total_rows is not None else None

    # Get column info via adapter (cross-database)
    try:
        columns_data = adapter.get_columns(table_name)
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            runtime,
            ctx=ctx,
            tool_name="get_table_summary",
            start_time=start_time,
            connection=connection,
            error=exc,
        )

    if not columns_data:
        await ctx.error(f"Table not found: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Table '{table_name}' not found",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="get_table_summary",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # An unavailable estimate is not evidence that the table is small.
    is_large = (
        total_rows > runtime.config.server.tools.large_table_threshold
        if total_rows is not None
        else None
    )
    if total_rows is None:
        displayed_row_count = "unknown"
    elif row_count_approximate:
        displayed_row_count = f"~{total_rows}"
    else:
        displayed_row_count = str(total_rows)

    await ctx.info(
        f"Table {table_name}: {displayed_row_count} rows, {len(columns_data)} columns"
    )

    result_payload = {
        "success": True,
        "table_name": table_name,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "row_count": total_rows,
        "row_count_approximate": row_count_approximate,
        "column_count": len(columns_data),
        "columns": columns_data,
        "is_large": is_large,
    }

    if is_large is True:
        result_payload["recommendation"] = (
            f"Large table ({'~' if row_count_approximate else ''}{total_rows} rows). "
            "Use LIMIT or aggregation (COUNT/GROUP BY)."
        )

    return _tool_result(
        runtime,
        result_payload,
        tool_name="get_table_summary",
        start_time=start_time,
        success=True,
        connection=connection,
        row_count=total_rows,
        is_large=is_large,
        exact_count=resolved_exact_count,
    )


async def sample(
    runtime,
    table_name: str,
    ctx: Context,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=20,
            description=(
                "Number of sample rows to return, from 1 through 20. "
                "Defaults to 5; out-of-range values are rejected."
            ),
        ),
    ] = 5,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Get sample rows from a table to preview its data."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    require_read_access(connection)
    # Validate inputs
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Invalid table name: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="sample",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # Check table allowlist (P1 Security)
    if not _is_table_allowed(runtime, table_name, connection.policy):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": f"Access denied to table: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="sample",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    # FastMCP enforces the same range at the MCP boundary. Keep an explicit
    # handler check so direct Python callers receive the same rejection.
    if type(limit) is not int or not 1 <= limit <= 20:
        message = "limit must be an integer from 1 through 20"
        await ctx.warning(f"Sample parameter error: {message}")
        raise ToolError(message)

    await ctx.info(
        f"Sampling {limit} rows from connection '{connection.connection_id}': {table_name}"
    )

    # Use adapter-compatible quoting (backticks for MySQL, double-quotes for SQLite)
    adapter = connection.adapter
    quote = "`" if adapter.db_type == "mysql" else '"'
    sql = f"SELECT * FROM {quote}{table_name}{quote} LIMIT {limit}"
    result = adapter.execute(sql)

    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Failed to sample table: {result}")
        return _tool_result(
            runtime,
            {
                "success": False,
                "error": result,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
            tool_name="sample",
            start_time=start_time,
            connection=connection,
            success=False,
        )

    data = _serialize_result(result)

    return _tool_result(
        runtime,
        {
            "success": True,
            "table_name": table_name,
            "data": data,
            "row_count": len(data),
            "query": sql,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        },
        tool_name="sample",
        start_time=start_time,
        connection=connection,
        success=True,
        row_count=len(data),
    )
