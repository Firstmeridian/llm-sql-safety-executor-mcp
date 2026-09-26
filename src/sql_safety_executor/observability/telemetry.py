"""Opt-in metadata-only telemetry; an input request is not business success."""

import json
import logging
import random as _random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import InputRequiredToolResult
from fastmcp.exceptions import ToolError
from sql_safety_executor.core.types import OperationError
from sql_safety_executor.core.connections import _select_diagnostic_configs
from sql_safety_executor.database.diagnostics import ConnectionScope

logger = logging.getLogger(__name__)


class ToolTelemetryMiddleware(Middleware):
    """Append a sanitized JSONL record for each tools/call invocation.

    Records reflect both transport-level outcome (no exception escaped
    ``call_next``) and business-level outcome (``ToolResult.meta.success``
    when present). ``call_completed`` captures the former, ``success``
    captures the latter so operators can tell e.g. a safety rejection
    (``call_completed=True``, ``success=False``) apart from a crash
    (``call_completed=False``, ``success=False``).
    """

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        settings = runtime.config.server.observability.telemetry
        log_path, sample_rate = settings.path, settings.sample_rate
        self._log_path: Path | None = Path(log_path)
        self._sample_rate = sample_rate
        try:
            assert self._log_path is not None
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - filesystem edge case
            logger.warning(f"Tool telemetry disabled (mkdir failed): {exc}")
            self._log_path = None

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next):  # type: ignore[override]
        runtime = self.runtime
        tool_name = getattr(context.message, "name", None) or "unknown"
        started = time.perf_counter()
        call_completed = True
        error_class: str | None = None
        success: bool | None = True
        phase = "complete"
        diagnostic = tool_name == "check_connection"
        result_db_type = None if diagnostic else runtime.registry.get_config().db_type
        result_connection_id = None if diagnostic else runtime.default_connection_id()
        diagnostic_scope: ConnectionScope | None = None
        if diagnostic:
            arguments = getattr(context.message, "arguments", None) or {}
            if isinstance(arguments, dict):
                try:
                    configs = _select_diagnostic_configs(runtime, **arguments)
                    diagnostic_scope = arguments.get("scope", "single")
                    if diagnostic_scope == "single":
                        result_db_type = configs[0].db_type
                        result_connection_id = configs[0].connection_id
                except (OperationError, ToolError, TypeError, ValueError):
                    # Observability must not change validation or fabricate
                    # a default identity for an invalid request.
                    pass
        aggregate = diagnostic_scope == "all"
        aggregate_counts: dict[str, int] = {}
        cleanup_failed = diagnostic and runtime.diagnostics.cleanup_failed
        try:
            result = await call_next(context)
            if isinstance(result, InputRequiredToolResult):
                success = None
                phase = "awaiting_approval"
            meta = getattr(result, "meta", None) or {}
            meta_success = meta.get("success") if isinstance(meta, dict) else None
            if isinstance(meta_success, bool):
                success = meta_success
            if isinstance(meta, dict):
                aggregate = aggregate or meta.get("connection_scope") == "all"
                if diagnostic or aggregate:
                    cleanup_failed = meta.get("cleanup_failed") is True
                    for key in ("connection_count", "connected_count"):
                        if type(meta.get(key)) is int:
                            aggregate_counts[key] = meta[key]
                if isinstance(meta.get("db_type"), str):
                    result_db_type = meta["db_type"]
                if isinstance(meta.get("connection_id"), str):
                    result_connection_id = meta["connection_id"]
            return result
        except BaseException as exc:
            call_completed = False
            success = False
            error_class = type(exc).__name__
            raise
        finally:
            if self._log_path is not None and (
                self._sample_rate >= 1.0 or _random.random() < self._sample_rate
            ):
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "tool_name": tool_name,
                    "execution_ms": round((time.perf_counter() - started) * 1000, 3),
                    "call_completed": call_completed,
                    "phase": phase,
                    "success": success,
                    "error_class": error_class,
                    "db_type": result_db_type,
                    "connection_id": result_connection_id,
                }
                if diagnostic or aggregate:
                    if aggregate or result_connection_id is None:
                        record.pop("connection_id")
                        record.pop("db_type")
                    if diagnostic_scope is not None:
                        record["connection_scope"] = diagnostic_scope
                    elif aggregate:
                        record["connection_scope"] = "all"
                    record["cleanup_failed"] = cleanup_failed
                    record.update(aggregate_counts)
                try:
                    with self._log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                except OSError as exc:  # pragma: no cover - filesystem edge case
                    logger.warning(f"Tool telemetry write failed: {exc}")
