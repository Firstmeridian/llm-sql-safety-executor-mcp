"""Smoke tests for the opt-in tool telemetry middleware (v3.4.2).

The middleware only activates when ENABLE_TOOL_TELEMETRY=1 at import time, so
we reload the module under that env var. We then invoke the middleware's
``on_call_tool`` hook directly with a stub ``call_next`` and verify a sanitized
JSONL record is appended.

Logged fields MUST remain non-sensitive: no SQL, params, rows, or credentials.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SKILLS_LIB = PROJECT_ROOT / "skills" / "_lib"
if _SKILLS_LIB.is_dir() and str(_SKILLS_LIB) not in sys.path:
    sys.path.insert(0, str(_SKILLS_LIB))


@pytest.fixture()
def telemetry_module(tmp_path, monkeypatch):
    log_path = tmp_path / "tool_calls.jsonl"
    monkeypatch.setenv("ENABLE_TOOL_TELEMETRY", "1")
    monkeypatch.setenv("TOOL_TELEMETRY_LOG_PATH", str(log_path))
    # Force a clean reimport so the env vars are honored.
    sys.modules.pop("mcp_sql_server", None)
    module = importlib.import_module("mcp_sql_server")
    yield module, log_path


@pytest.mark.asyncio
async def test_telemetry_logs_successful_call(telemetry_module):
    module, log_path = telemetry_module
    middleware = module._ToolTelemetryMiddleware(str(log_path))

    async def fake_call_next(_ctx):
        return SimpleNamespace(
            meta={
                "tool_name": "query",
                "execution_ms": 1.0,
                "success": True,
                "preview_token_id": "0123456789abcdef",
            }
        )

    ctx = SimpleNamespace(message=SimpleNamespace(name="query"))
    await middleware.on_call_tool(ctx, fake_call_next)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool_name"] == "query"
    assert record["call_completed"] is True
    assert record["success"] is True
    assert record["error_class"] is None
    assert "timestamp" in record
    assert "execution_ms" in record
    # Sanitization invariants
    for forbidden in (
        "sql",
        "params",
        "data",
        "rows",
        "password",
        "credentials",
        "preview_token_id",
    ):
        assert forbidden not in record


@pytest.mark.asyncio
async def test_telemetry_logs_failure(telemetry_module):
    module, log_path = telemetry_module
    middleware = module._ToolTelemetryMiddleware(str(log_path))

    async def fake_call_next(_ctx):
        raise RuntimeError("boom")

    ctx = SimpleNamespace(message=SimpleNamespace(name="query"))
    with pytest.raises(RuntimeError):
        await middleware.on_call_tool(ctx, fake_call_next)

    record = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["call_completed"] is False
    assert record["success"] is False
    assert record["error_class"] == "RuntimeError"


@pytest.mark.asyncio
async def test_telemetry_honors_meta_success_false(telemetry_module):
    """B1 fix: business-level rejection (e.g. unsafe SQL) returns ToolResult
    with meta.success=False but does NOT raise. Telemetry must record
    success=False while call_completed remains True."""
    module, log_path = telemetry_module
    middleware = module._ToolTelemetryMiddleware(str(log_path))

    async def fake_call_next(_ctx):
        return SimpleNamespace(
            meta={"tool_name": "query", "execution_ms": 1.0, "success": False}
        )

    ctx = SimpleNamespace(message=SimpleNamespace(name="query"))
    await middleware.on_call_tool(ctx, fake_call_next)

    record = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["call_completed"] is True
    assert record["success"] is False
    assert record["error_class"] is None


@pytest.mark.asyncio
async def test_telemetry_sample_rate_zero_suppresses_writes(telemetry_module):
    """3b: SAMPLE_RATE=0.0 should drop all records."""
    module, log_path = telemetry_module
    middleware = module._ToolTelemetryMiddleware(str(log_path), sample_rate=0.0)

    async def fake_call_next(_ctx):
        return SimpleNamespace(meta={"success": True})

    ctx = SimpleNamespace(message=SimpleNamespace(name="query"))
    for _ in range(5):
        await middleware.on_call_tool(ctx, fake_call_next)

    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""


def test_parse_telemetry_sample_rate_clamps(telemetry_module):
    module, _ = telemetry_module
    assert module._parse_telemetry_sample_rate(None) == 1.0
    assert module._parse_telemetry_sample_rate("") == 1.0
    assert module._parse_telemetry_sample_rate("not-a-float") == 1.0
    assert module._parse_telemetry_sample_rate("nan") == 1.0
    assert module._parse_telemetry_sample_rate("inf") == 1.0
    assert module._parse_telemetry_sample_rate("-0.5") == 0.0
    assert module._parse_telemetry_sample_rate("2.5") == 1.0
    assert module._parse_telemetry_sample_rate("0.25") == 0.25
