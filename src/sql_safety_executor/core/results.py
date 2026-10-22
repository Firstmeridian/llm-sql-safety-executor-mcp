from __future__ import annotations
import json
import base64
import math
import logging
import time
from collections.abc import Mapping
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal
from uuid import UUID
from typing import Any, Literal
from pydantic_core import to_json, to_jsonable_python
from sql_safety_executor.core.types import (
    OperationContext as Context,
    OperationResult as ToolResult,
    ConnectionContext,
)
from sql_safety_executor.database.models import DatabaseConfig
from sql_safety_executor.skills.catalog import SkillMetadata

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import _SCHEMA_DETAIL_LEVELS, SchemaDetailLevel


class ReadResultError(ValueError):
    """A database read succeeded, but its result cannot be represented faithfully."""

    def __init__(self, *, duplicate_columns: bool = False):
        self.error_code = "duplicate_result_columns" if duplicate_columns else "result_encoding_failed"
        super().__init__("Result column labels must be unique." if duplicate_columns
                         else "The read result contains an unsupported value.")
        self.hint = ("Use unique AS aliases for all output columns on the same connection."
                     if duplicate_columns else
                     "Select supported values or explicitly convert the affected column in SQL on the same connection.")

    def error_payload(self) -> dict[str, Any]:
        return {"success": False, "error_code": self.error_code, "error": str(self), "hint": self.hint}


def _serialize_result(data: Any) -> Any:
    """Normalize read values once, before JSON sizing and protocol serialization."""
    if data is None or isinstance(data, (bool, int)):
        return data
    if isinstance(data, str):
        data.encode("utf-8")  # Reject invalid Unicode before protocol encoding.
        return data
    if isinstance(data, float):
        if math.isfinite(data):
            return data
        return {"$type": "float", "value": "NaN" if math.isnan(data) else
                "Infinity" if data > 0 else "-Infinity"}
    if isinstance(data, (bytes, bytearray, memoryview)):
        return {"$type": "binary", "encoding": "base64",
                "data": base64.b64encode(bytes(data)).decode("ascii")}
    if hasattr(data, "_mapping"):
        mapping = data._mapping
        labels = list(mapping.keys())
        if len(set(labels)) != len(labels):
            raise ReadResultError(duplicate_columns=True)
        return {_serialize_result(key): _serialize_result(mapping[key]) for key in labels}
    if isinstance(data, Mapping):
        if any(not isinstance(key, str) for key in data):
            raise ReadResultError()
        return {_serialize_result(key): _serialize_result(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_serialize_result(item) for item in data]
    if isinstance(data, (date, datetime, datetime_time, timedelta, Decimal, UUID)):
        return to_jsonable_python(data)
    # Never stringify arbitrary objects or expose their implementation fields.
    raise ReadResultError()


def _truncate_result(runtime, data: list, total_rows: int) -> dict[str, Any]:
    """
    Truncate query results to prevent token explosion.

    Set MAX_RESULT_ROWS=0 or MAX_RESULT_CHARS=0 to disable respective limits.

    Returns:
        Dict with truncated data and metadata
    """

    row_limit = runtime.config.server.limits.result_rows
    char_limit = runtime.config.server.limits.result_chars
    row_limited = bool(row_limit and len(data) > row_limit)
    selected = data[:row_limit] if row_limited else data
    char_limited = False
    returned_rows = len(selected)
    if char_limit:
        # Compact JSON array size: brackets, each encoded row, and separators.
        # Encode each considered row once; never keep an oversized first row.
        size, returned_rows = 2, 0
        for row in selected:
            encoded = to_json(row).decode("utf-8")
            candidate = size + len(encoded) + bool(returned_rows)
            if candidate > char_limit:
                char_limited = True
                break
            size = candidate
            returned_rows += 1
        selected = selected[:returned_rows]
    reasons = [name for name, active in (("row_limit", row_limited), ("char_limit", char_limited)) if active]

    return {
        "data": selected,
        "returned_rows": returned_rows,
        "total_rows": total_rows,
        "truncated": bool(reasons),
        "truncation_reason": "+".join(reasons) or None,
    }


def _prepare_read_result(runtime, rows: list) -> dict[str, Any]:
    """The common read-result boundary for query, Query Skill and sample."""
    try:
        result = _truncate_result(runtime, _serialize_result(rows), len(rows))
    except ReadResultError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ReadResultError() from None
    note = None
    if result["truncated"]:
        note = f"Showing {result['returned_rows']}/{len(rows)} fetched rows. "
        if not result["returned_rows"] and rows:
            note += "The first row exceeds the character limit; select fewer columns or a shorter SQL projection. "
        note += ("Truncation limits the returned data only; add WHERE/LIMIT/ORDER BY "
                 "to limit database work and stabilize ordering.")
    return {"data": result["data"], "row_count": result["returned_rows"],
            "total_rows": len(rows), "truncated": result["truncated"],
            **({"truncation_reason": result["truncation_reason"]} if result["truncated"] else {}),
            "truncation_note": note}


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
