"""Observable request boundaries, independent of SQL/approval success semantics."""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from sql_safety_executor.observability import telemetry


def middleware(path, rate=1.0):
    settings = SimpleNamespace(path=str(path), sample_rate=rate)
    runtime = SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(
        observability=SimpleNamespace(telemetry=settings)
    )))
    return telemetry.ToolTelemetryMiddleware(runtime)


def context(request="request-secret", session="session-secret"):
    return SimpleNamespace(
        message=SimpleNamespace(name="query", arguments={"sql": "SELECT 'private'"}),
        fastmcp_context=SimpleNamespace(
            request_context=SimpleNamespace(request_id=request), session_id=session
        ),
    )


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def ok(_):
    return SimpleNamespace(meta={"success": True})


async def test_entry_is_visible_while_pending_and_cancellation_has_a_finish(tmp_path):
    path = tmp_path / "events.jsonl"
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def pending(_):
        entered.set()
        await gate.wait()

    task = asyncio.create_task(middleware(path).on_call_tool(context(), pending))
    await asyncio.wait_for(entered.wait(), timeout=2)
    before = records(path)
    assert len(before) == 1 and before[0]["event"] == "tool_call_started"
    assert not {"success", "call_completed", "execution_ms", "connection_id"} & before[0].keys()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    after = records(path)
    assert len(after) == 2 and after[1]["event"] == "tool_call_finished"
    assert after[0]["call_id"] == after[1]["call_id"]
    assert after[1]["error_class"] == "CancelledError"
    assert after[1]["call_completed"] is False and after[1]["success"] is False
    assert after[1]["execution_ms"] >= 0


async def test_sampling_selects_both_events_once_and_never_exports_ids(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    draws = iter([0.1, 0.9])
    monkeypatch.setattr(telemetry._random, "random", lambda: next(draws))
    instance = middleware(path, rate=0.5)
    assert (await instance.on_call_tool(context(), ok)).meta["success"]
    assert (await instance.on_call_tool(context(), ok)).meta["success"]
    rows = records(path)
    assert [r["event"] for r in rows] == ["tool_call_started", "tool_call_finished"]
    assert rows[0]["call_id"] == rows[1]["call_id"]
    expected = hashlib.sha256(
        json.dumps([rows[0]["server_instance_id"], "request_id", "request-secret"],
                   ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert rows[0]["request_id_hash"] == rows[1]["request_id_hash"] == expected
    assert all(len(r["session_id_hash"]) == 64 for r in rows)
    text = path.read_text()
    for secret in ("request-secret", "session-secret", "SELECT", "private"):
        assert secret not in text


async def test_concurrent_reused_ids_and_recreated_instances_do_not_mix(tmp_path):
    path = tmp_path / "events.jsonl"
    first = middleware(path)
    pending = asyncio.Event()
    both_entered = asyncio.Event()
    count = 0

    async def overlap(_):
        nonlocal count
        count += 1
        if count == 2:
            both_entered.set()
        await pending.wait()
        return await ok(_)

    tasks = [asyncio.create_task(first.on_call_tool(context("7", session), overlap))
             for session in ("a", "b")]
    await asyncio.wait_for(both_entered.wait(), timeout=2)
    assert len(records(path)) == 2
    pending.set()
    await asyncio.gather(*tasks)
    await first.on_call_tool(context("7", "a"), ok)
    await middleware(path).on_call_tool(context("7", "a"), ok)
    rows = records(path)
    starts = [r for r in rows if r["event"] == "tool_call_started"]
    assert len(starts) == len({r["call_id"] for r in starts}) == 4
    assert starts[0]["server_instance_id"] == starts[1]["server_instance_id"] == starts[2]["server_instance_id"]
    assert starts[3]["server_instance_id"] != starts[0]["server_instance_id"]
    assert starts[0]["session_id_hash"] != starts[1]["session_id_hash"]
    assert starts[0]["session_id_hash"] == starts[2]["session_id_hash"]
    for start in starts:
        pair = [r for r in rows if r["call_id"] == start["call_id"]]
        assert [r["event"] for r in pair] == ["tool_call_started", "tool_call_finished"]
        assert pair[0]["request_id_hash"] == pair[1]["request_id_hash"]


async def test_duration_uses_monotonic_clock_not_wall_clock(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    ticks = iter([100.0, 100.125])
    walls = iter([datetime(2026, 10, 28, tzinfo=timezone.utc),
                  datetime(2026, 10, 27, tzinfo=timezone.utc)])
    monkeypatch.setattr(telemetry, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    monkeypatch.setattr(telemetry, "datetime", SimpleNamespace(now=lambda _: next(walls)))
    path = tmp_path / "events.jsonl"
    await middleware(path).on_call_tool(context(), ok)
    rows = records(path)
    assert rows[1]["timestamp"] < rows[0]["timestamp"]
    assert rows[1]["execution_ms"] == 125.0


@pytest.mark.parametrize("fail_call", [False, True])
async def test_unwritable_log_does_not_replace_result_or_error(tmp_path, fail_call, caplog):
    path = tmp_path / "unwritable-secret"
    path.mkdir()
    marker = RuntimeError("business-error-private")
    result = object()

    async def call(_):
        if fail_call:
            raise marker
        return result

    instance = middleware(path)
    if fail_call:
        with pytest.raises(RuntimeError) as exc:
            await instance.on_call_tool(context(), call)
        assert exc.value is marker
    else:
        assert await instance.on_call_tool(context(), call) is result
    assert caplog.text.count("Tool telemetry write failed") == 2
    assert "unwritable-secret" not in caplog.text
    assert "business-error-private" not in caplog.text


async def test_missing_wire_context_is_explicit_not_a_fabricated_request_id(tmp_path):
    path = tmp_path / "events.jsonl"
    ctx = SimpleNamespace(message=SimpleNamespace(name="query"))
    await middleware(path).on_call_tool(ctx, ok)
    rows = records(path)
    assert all(r["request_id_hash"] is None and r["session_id_hash"] is None for r in rows)
    assert rows[0]["call_id"] == rows[1]["call_id"]


async def test_notification_has_no_request_and_escaped_ids_do_not_collide(tmp_path):
    path = tmp_path / "events.jsonl"
    instance = middleware(path)
    for request in (None, "\ud800", "\\ud800", 1, "1"):
        await instance.on_call_tool(context(request), ok)
    starts = [r for r in records(path) if r["event"] == "tool_call_started"]
    assert starts[0]["request_id_hash"] is None
    assert len({r["request_id_hash"] for r in starts[1:]}) == 4


async def test_unexpected_diagnostic_preparation_error_retains_boundary(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    marker = RuntimeError("private-preparation-error")

    def fail(*args, **kwargs):
        raise marker

    monkeypatch.setattr(telemetry, "_select_diagnostic_configs", fail)
    ctx = context()
    ctx.message.name = "check_connection"
    with pytest.raises(RuntimeError) as exc:
        await middleware(path).on_call_tool(ctx, ok)
    assert exc.value is marker
    rows = records(path)
    assert [r["event"] for r in rows] == ["tool_call_started", "tool_call_finished"]
    assert rows[1]["error_class"] == "RuntimeError"
    assert rows[1]["success"] is False and rows[1]["call_completed"] is False
    assert "private-preparation-error" not in path.read_text()


@pytest.mark.parametrize("mode,version", [("auto", "2026-07-28"), ("legacy", "2025-11-25")])
async def test_stdio_lifecycle_and_restart_with_real_requests(tmp_path, mode, version):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    config = tmp_path / "server.toml"
    config.write_text(
        'schema_version=1\n[files]\nconnections="connections.toml"\n'
        '[server]\ndefault_connection="test"\n'
        '[observability.telemetry]\nenabled=true\npath="events.jsonl"\nsample_rate=1.0\n'
    )
    (tmp_path / "connections.toml").write_text(
        'schema_version=1\n[connections.test]\ntype="sqlite"\n'
        'sqlite.path=":memory:"\nread.mode="all"\n'
    )
    # Source tests use the editable tree; copying this file outside the tree
    # with a wheel interpreter also validates the installed implementation.
    source = Path(__file__).resolve().parents[1] / "src"
    env = {"PYTHONPATH": str(source)} if source.is_dir() else None
    for _ in range(2):
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "sql_safety_executor", "serve", "--config", str(config)],
            cwd=str(tmp_path), env=env,
        )
        async with Client(transport, mode=mode, init_timeout=10, timeout=10) as client:
            assert client.protocol_version == version
            success = await client.call_tool("query", {"sql": "SELECT 7 AS n"})
            assert success.structured_content["data"] == [{"n": 7}]
            denied = await client.call_tool("query", {"sql": "DELETE FROM orders"})
            assert denied.structured_content["success"] is False
            error = await client.call_tool("nonexistent_tool", {}, raise_on_error=False)
            assert error.is_error
    rows = records(tmp_path / "events.jsonl")
    starts = [r for r in rows if r["event"] == "tool_call_started"]
    finishes = [r for r in rows if r["event"] == "tool_call_finished"]
    assert len(starts) == len(finishes) == 6
    assert len({r["server_instance_id"] for r in rows}) == 2
    assert len({r["call_id"] for r in starts}) == 6
    assert all(r["request_id_hash"] and r["session_id_hash"] for r in rows)
    for start in starts:
        end = next(r for r in finishes if r["call_id"] == start["call_id"])
        assert end["server_instance_id"] == start["server_instance_id"]
        assert end["request_id_hash"] == start["request_id_hash"]
        assert end["session_id_hash"] == start["session_id_hash"]
        assert end["execution_ms"] >= 0
    assert [(r["call_completed"], r["success"]) for r in finishes] == [
        (True, True), (True, False), (False, False),
    ] * 2
    assert not any(s in (tmp_path / "events.jsonl").read_text()
                   for s in ("SELECT 7", "DELETE FROM", "orders"))
