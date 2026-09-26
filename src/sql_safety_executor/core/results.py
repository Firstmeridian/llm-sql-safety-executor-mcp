from __future__ import annotations
import json
import logging
import time
from typing import Any, Literal
from sql_safety_executor.core.types import (
    OperationContext as Context,
    OperationResult as ToolResult,
    ConnectionContext,
)
from sql_safety_executor.database.models import DatabaseConfig
from sql_safety_executor.skills.catalog import SkillMetadata

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import _SCHEMA_DETAIL_LEVELS, SchemaDetailLevel


def _serialize_result(data: Any) -> Any:
    """Convert SQLAlchemy Row objects to JSON-serializable format."""
    if data is None:
        return None
    if isinstance(data, list):
        return [_serialize_result(item) for item in data]
    if hasattr(data, "_mapping"):
        return dict(data._mapping)
    if hasattr(data, "__dict__"):
        return {k: v for k, v in data.__dict__.items() if not k.startswith("_")}
    return data


def _truncate_result(runtime, data: list, total_rows: int) -> dict[str, Any]:
    """
    Truncate query results to prevent token explosion.

    Set MAX_RESULT_ROWS=0 or MAX_RESULT_CHARS=0 to disable respective limits.

    Returns:
        Dict with truncated data and metadata
    """

    truncated = False
    truncation_reason = None
    returned_rows = len(data)

    # Step 1: Limit by row count (0 = disabled)
    if (
        runtime.config.server.limits.result_rows > 0
        and len(data) > runtime.config.server.limits.result_rows
    ):
        data = data[: runtime.config.server.limits.result_rows]
        truncated = True
        truncation_reason = f"row_limit ({runtime.config.server.limits.result_rows})"
        returned_rows = runtime.config.server.limits.result_rows

    # Step 2: Limit by character count (0 = disabled)
    if runtime.config.server.limits.result_chars > 0:
        try:
            json_str = json.dumps(data, ensure_ascii=False, default=str)
            if len(json_str) > runtime.config.server.limits.result_chars:
                # Binary search for optimal row count within char limit
                low, high = 1, len(data)
                while low < high:
                    mid = (low + high + 1) // 2
                    test_str = json.dumps(data[:mid], ensure_ascii=False, default=str)
                    if len(test_str) <= runtime.config.server.limits.result_chars:
                        low = mid
                    else:
                        high = mid - 1
                data = data[:low]
                truncated = True
                truncation_reason = (
                    f"char_limit ({runtime.config.server.limits.result_chars})"
                )
                returned_rows = low
        except (TypeError, ValueError):
            pass  # If JSON encoding fails, skip char limit check

    return {
        "data": data,
        "returned_rows": returned_rows,
        "total_rows": total_rows,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
    }


def _elapsed_ms_from(start_time: float) -> float:
    """Return elapsed milliseconds rounded for stable runtime metadata."""
    return round((time.perf_counter() - start_time) * 1000, 3)


def _tool_result(
    runtime,
    payload: dict[str, Any],
    *,
    tool_name: str,
    start_time: float,
    connection: ConnectionContext | None = None,
    connection_config: DatabaseConfig | None = None,
    connection_scope: Literal["single", "all"] = "single",
    **meta_extras: Any,
) -> ToolResult:
    """
    Wrap a dict-shaped tool response in ``ToolResult`` and attach runtime metadata.

    ``_meta`` carries ``tool_name`` and ``execution_ms``. Single-connection
    results also carry ``db_type`` and ``connection_id``; aggregate results
    carry ``connection_scope=all`` without a misleading default connection.
    Callers may add tool-specific fields via ``**meta_extras`` (None values are
    dropped). Metadata is non-sensitive diagnostics only — never raw SQL,
    returned rows, parameter values, or credentials.

    Per MCP spec the ``_meta`` field is OPTIONAL: clients MAY ignore it. This
    helper is primarily a server-side observability hook.
    """
    config = connection.config if connection is not None else connection_config
    db_type = (
        config.db_type if config is not None else runtime.registry.get_config().db_type
    )
    connection_id = (
        config.connection_id if config is not None else runtime.default_connection_id()
    )
    runtime_meta: dict[str, Any] = {
        "tool_name": tool_name,
        "db_type": db_type,
        "connection_id": connection_id,
        "execution_ms": _elapsed_ms_from(start_time),
    }
    runtime_meta.update({k: v for k, v in meta_extras.items() if v is not None})
    if connection_config is not None:
        runtime_meta["connection_scope"] = connection_scope
    if connection_scope == "all":
        runtime_meta.pop("db_type", None)
        runtime_meta.pop("connection_id", None)
        runtime_meta["connection_scope"] = "all"
    return ToolResult(structured_content=payload, meta=runtime_meta)


def _normalize_schema_detail_level(
    detail_level: SchemaDetailLevel,
) -> SchemaDetailLevel:
    """Validate the already non-null schema projection argument."""
    if detail_level not in _SCHEMA_DETAIL_LEVELS:
        allowed = ", ".join(sorted(_SCHEMA_DETAIL_LEVELS))
        raise ValueError(
            f"Invalid detail_level '{detail_level}'. Allowed values: {allowed}"
        )
    return detail_level


def _require_boolean(value: bool, parameter_name: str) -> bool:
    """Reject Python values that do not match an MCP boolean schema."""
    if type(value) is not bool:
        raise ValueError(f"{parameter_name} must be a boolean")
    return value


def _schema_metadata_signature(columns: list[dict[str, Any]]) -> str:
    """Return an order-sensitive signature over adapter-visible column metadata."""
    return json.dumps(
        columns,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


async def _metadata_failure_result(
    runtime,
    *,
    ctx: Context,
    tool_name: str,
    start_time: float,
    connection: ConnectionContext,
    error: Exception,
    error_code: str = "metadata_query_failed",
) -> ToolResult:
    """Return a stable, sanitized failure instead of an empty metadata result."""
    await ctx.error(str(error))
    return _tool_result(
        runtime,
        {
            "success": False,
            "error": str(error),
            "error_code": error_code,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        },
        tool_name=tool_name,
        start_time=start_time,
        connection=connection,
        success=False,
    )


def _context_client_id(ctx: Context) -> str | None:
    """Return the optional MCP client id without failing direct tests."""
    try:
        return getattr(ctx, "client_id", None)
    except Exception:
        return None


def _elapsed_ms(start_time: float) -> float:
    """Return elapsed milliseconds rounded for stable runtime metadata."""
    return round((time.perf_counter() - start_time) * 1000, 3)


def _skill_tool_result(
    payload: dict[str, Any],
    meta: SkillMetadata,
    *,
    mode: str,
    start_time: float,
    connection: ConnectionContext,
    row_count: int | None = None,
    total_rows: int | None = None,
    truncated: bool | None = None,
    audit_logged: bool | None = None,
    preview_token_required: bool | None = None,
    preview_token_validated: bool | None = None,
    preview_token_consumed: bool | None = None,
    preview_token_id: str | None = None,
) -> ToolResult:
    """Attach runtime metadata without changing the structured payload."""
    payload_success = payload.get("success")
    tool_name = (
        "execute_mutation_skill" if meta.type == "mutation" else "execute_query_skill"
    )
    runtime_meta: dict[str, Any] = {
        "tool_name": tool_name,
        "skill_name": meta.name,
        "skill_type": meta.type,
        "skill_version": meta.version,
        "mode": mode,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "execution_ms": _elapsed_ms(start_time),
        "success": payload_success if isinstance(payload_success, bool) else True,
        "idempotent": meta.idempotent,
    }
    if meta.type == "mutation":
        runtime_meta["execution_outcome"] = payload.get("execution_outcome")
        if "error_code" in payload:
            runtime_meta["error_code"] = payload.get("error_code")
    optional_fields = {
        "row_count": row_count,
        "total_rows": total_rows,
        "truncated": truncated,
        "audit_logged": audit_logged,
        "preview_token_required": preview_token_required,
        "preview_token_validated": preview_token_validated,
        "preview_token_consumed": preview_token_consumed,
        "preview_token_id": preview_token_id,
    }
    runtime_meta.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )
    return ToolResult(structured_content=payload, meta=runtime_meta)
