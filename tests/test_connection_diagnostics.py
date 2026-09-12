"""Disposable probes and batch resource ownership, without live databases."""

import asyncio
from dataclasses import replace
import importlib
import json
import sqlite3
import sys
import textwrap
from threading import Event, Lock, get_ident
from types import SimpleNamespace

from fastmcp import Client
from mcp.shared.exceptions import McpError
from jsonschema import Draft202012Validator
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

import connection_diagnostics as diagnostics
from db_adapter import ConnectionPolicy, DatabaseConfig, create_adapter


def config(alias: str = "main", path: str = ":memory:") -> DatabaseConfig:
    return DatabaseConfig(
        connection_id=alias, db_type="sqlite", query_timeout_seconds=3,
        connect_timeout_seconds=2, policy=ConnectionPolicy(), sqlite_database_path=path,
    )


async def until(predicate):
    # Yield to workers without blocking the event loop; fail rather than hang.
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("successes", [set(), {"b"}, {"a", "b", "c"}])
async def test_batch_outcomes_and_order(successes):
    def probe(item):
        if item.connection_id in successes:
            return diagnostics.ConnectedCheck(db_type=item.db_type, status="connected", connected=True)
        return diagnostics.FailedCheck(db_type=item.db_type, status="failed", connected=False, error="Safe failure")

    runner = diagnostics.ConnectionDiagnostics(probe)
    runner.start()
    try:
        report = await runner.run([config(alias) for alias in ("a", "b", "c")], 2)
        assert list(report.results) == ["a", "b", "c"]
        assert report.connected_count == len(successes)
        assert report.all_connected is (len(successes) == 3)
        assert report.complete is True
        diagnostics.ConnectionReport.model_validate(report.model_dump())
    finally:
        runner.close()


@pytest.mark.asyncio
async def test_timeout_retains_workers_and_completed_results():
    release = Event()
    slow_started: set[str] = set()
    lock = Lock()
    active = 0
    peak = 0

    def probe(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
        try:
            if item.connection_id != "fast":
                with lock:
                    slow_started.add(item.connection_id)
                assert release.wait(3)
            return diagnostics.ConnectedCheck(db_type=item.db_type, status="connected", connected=True)
        finally:
            with lock:
                active -= 1

    runner = diagnostics.ConnectionDiagnostics(probe)
    runner.start()
    aliases = ["fast", "slow1", "slow2", "slow3", "slow4", "queued"]
    try:
        task = asyncio.create_task(runner.run([config(alias) for alias in aliases], 0.3))
        await until(lambda: len(slow_started) == 4)
        # This runs while four blocking worker calls are outstanding.
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="busy"):
            await runner.run([config()], 1)
        report = await task
        assert report.results["fast"].connected is True
        assert report.results["slow1"].status == "timeout"
        assert report.results["slow1"].connected is None
        assert report.results["queued"].status == "not_checked"
        assert not report.complete and not report.all_connected
        assert report.connected_count == 1
        assert peak == 4
        snapshot = report.model_dump_json()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="busy"):
            await runner.run([config()], 1)
        release.set()
        await until(lambda: not runner._batch_active)
        assert report.model_dump_json() == snapshot
        assert (await runner.run([config("fast")], 1)).all_connected
    finally:
        release.set()
        runner.close()


@pytest.mark.asyncio
async def test_cancellation_retains_batch_until_cleanup_and_shutdown_blocks_calls():
    started, release, cleaned = Event(), Event(), Event()

    def probe(item):
        started.set()
        try:
            assert release.wait(3)
            return diagnostics.ConnectedCheck(db_type=item.db_type, status="connected", connected=True)
        finally:
            cleaned.set()

    runner = diagnostics.ConnectionDiagnostics(probe)
    with pytest.raises(diagnostics.DiagnosticsUnavailable, match="stopped"):
        await runner.run([config()], 1)
    runner.start()
    task = asyncio.create_task(runner.run([config()], 2))
    try:
        await until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not cleaned.is_set()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="busy"):
            await runner.run([config()], 1)
        runner.close()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="stopped"):
            await runner.run([config()], 1)
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="draining"):
            runner.start()
        release.set()
        await until(lambda: not runner._batch_active)
        assert cleaned.is_set()
        runner.start()
        assert (await runner.run([config()], 1)).all_connected
    finally:
        release.set()
        runner.close()


@pytest.mark.parametrize("timeout, expected", [(None, 30), (0, 30), (120, 30), (10, 8), (0.1, 0.08)])
def test_budget_leaves_room_for_mcp_response(timeout, expected):
    assert diagnostics.diagnostic_budget(timeout) == pytest.approx(expected)


def test_sqlite_readonly_special_path_and_missing_file(tmp_path):
    path = tmp_path / "诊断 ?#% database.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE rows (id INTEGER)")
    item = config(path=str(path))
    assert diagnostics.probe_connection(item).connected is True
    adapter = create_adapter(config=item, diagnostic=True)
    try:
        assert adapter.connect()
        engine = getattr(adapter, "_engine", None)
        assert isinstance(engine, Engine)
        with engine.connect() as db:
            with pytest.raises(Exception, match="readonly"):
                db.execute(text("CREATE TABLE forbidden (id INTEGER)"))
    finally:
        adapter.close()
    missing = tmp_path / "missing.db"
    result = diagnostics.probe_connection(config(path=str(missing)))
    assert result.connected is False
    assert not missing.exists()
    assert str(tmp_path) not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [False, True])
async def test_diagnostic_does_not_rollback_business_transaction(tmp_path, memory):
    item = config(path=":memory:" if memory else str(tmp_path / "business.db"))
    business = create_adapter(config=item)
    runner = diagnostics.ConnectionDiagnostics()
    runner.start()
    try:
        engine = getattr(business, "_engine", None)
        assert isinstance(engine, Engine)
        with engine.begin() as db:
            db.execute(text("CREATE TABLE rows (id INTEGER)"))
        with engine.connect() as db:
            transaction = db.begin()
            db.execute(text("INSERT INTO rows VALUES (1)"))
            assert (await runner.run([item], 2)).all_connected
            assert db.execute(text("SELECT COUNT(*) FROM rows")).scalar_one() == 1
            transaction.rollback()
    finally:
        runner.close()
        business.close()


@pytest.mark.asyncio
async def test_sqlite_wal_diagnostic_preserves_pending_business_transaction(tmp_path):
    path = tmp_path / "wal.db"
    business = sqlite3.connect(path)
    item = config(path=str(path))
    runner = diagnostics.ConnectionDiagnostics()
    adapter = create_adapter(config=item, diagnostic=True)
    runner.start()
    try:
        assert business.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        business.execute("CREATE TABLE records (id INTEGER)")
        business.execute("INSERT INTO records VALUES (1)")
        business.commit()
        business.execute("INSERT INTO records VALUES (2)")
        assert (await runner.run([item], 2)).all_connected
        assert business.in_transaction
        assert business.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2
        assert adapter.connect()
        engine = getattr(adapter, "_engine", None)
        assert isinstance(engine, Engine)
        with engine.connect() as reader:
            # Read committed WAL content, without sharing the pending transaction.
            assert reader.execute(text("SELECT COUNT(*) FROM records")).scalar_one() == 1
            with pytest.raises(DBAPIError, match="readonly"):
                reader.execute(text("INSERT INTO records VALUES (3)"))
        business.rollback()
        assert business.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
    finally:
        runner.close()
        adapter.close()
        business.close()


@pytest.mark.asyncio
async def test_process_exit_waits_for_blocked_diagnostic_worker():
    # The parent owns this disposable child and can always kill it on failure.
    script = textwrap.dedent('''
        import asyncio
        import sys
        from connection_diagnostics import ConnectionDiagnostics, ConnectedCheck
        from db_adapter import DatabaseConfig, ConnectionPolicy

        def probe(config):
            try:
                assert sys.stdin.readline().strip() == "release"
                return ConnectedCheck(db_type="sqlite", status="connected", connected=True)
            finally:
                print("worker-cleaned", flush=True)

        async def main():
            runner = ConnectionDiagnostics(probe)
            runner.start()
            try:
                config = DatabaseConfig(
                    connection_id="isolated", db_type="sqlite",
                    query_timeout_seconds=1, connect_timeout_seconds=1,
                    policy=ConnectionPolicy(), sqlite_database_path=":memory:",
                )
                report = await runner.run([config], 0.2)
                assert report.results["isolated"].status == "timeout"
            finally:
                runner.close()
            print("shutdown-returned", flush=True)

        asyncio.run(main())
    ''')
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-c", script,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert process.stdout is not None and process.stdin is not None
        assert await asyncio.wait_for(process.stdout.readline(), 10) == b"shutdown-returned\n"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), 0.2)
        process.stdin.write(b"release\n")
        await process.stdin.drain()
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, stderr.decode()
        assert b"worker-cleaned" in stdout
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


def test_mysql_diagnostic_config_pool_and_safe_driver_failure(monkeypatch):
    import sqlalchemy
    from sqlalchemy.pool import NullPool

    captured = {}
    events = []
    owner = get_ident()

    class Engine:
        def connect(self):
            assert get_ident() == owner
            events.append("connect")
            raise RuntimeError("secret-password host.example /private/path")

        def dispose(self):
            assert get_ident() == owner
            events.append("dispose")

    def fake_create_engine(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Engine()

    monkeypatch.setattr(sqlalchemy, "create_engine", fake_create_engine)
    item = replace(config(), db_type="mysql", mysql_user="tester", mysql_password="secret-password",
                   mysql_host="host.example", mysql_database="demo")
    result = diagnostics.probe_connection(item)
    assert result.connected is False
    assert events == ["connect", "dispose"]
    assert captured["poolclass"] is NullPool
    assert captured["connect_args"] == {"connect_timeout": 2, "read_timeout": 3, "write_timeout": 3}
    assert captured["url"].password == "secret-password"
    for secret in ("secret-password", "host.example", "/private/path"):
        assert secret not in result.model_dump_json()


@pytest.mark.asyncio
async def test_adapter_cleanup_remains_on_worker_after_cancel(monkeypatch):
    created, release = Event(), Event()
    threads = []

    class Adapter:
        def check_connection(self):
            threads.append(get_ident())
            created.set()
            assert release.wait(3)
            raise RuntimeError("private details")

        def close(self):
            threads.append(get_ident())

    def factory(**kwargs):
        assert kwargs["diagnostic"] is True
        threads.append(get_ident())
        return Adapter()

    monkeypatch.setattr(diagnostics, "create_adapter", factory)
    runner = diagnostics.ConnectionDiagnostics()
    runner.start()
    task = asyncio.create_task(runner.run([config()], 2))
    try:
        await until(created.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await until(lambda: not runner._batch_active)
        assert len(threads) == 3 and len(set(threads)) == 1
        assert threads[0] != get_ident()
    finally:
        release.set()
        runner.close()


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_SKILLS", "0")
    monkeypatch.setenv("ENABLE_TOOL_TELEMETRY", "1")
    monkeypatch.setenv("TOOL_TELEMETRY_LOG_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.setenv("TOOL_TELEMETRY_SAMPLE_RATE", "1")
    sys.modules.pop("mcp_sql_server", None)
    module = importlib.import_module("mcp_sql_server")
    yield module
    module._connection_diagnostics.close()
    sys.modules.pop("mcp_sql_server", None)


@pytest.mark.asyncio
async def test_mcp_schema_partial_results_routing_and_telemetry(server, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "list_connection_configs", lambda: [config("ok"), config("bad", str(tmp_path / "missing.db"))])
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["check_connections"]
        assert tool.inputSchema.get("properties", {}) == {}
        assert tool.outputSchema is not None
        assert tool.annotations is not None and tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is False
        result = await client.call_tool("check_connections", {})
        assert not result.is_error
        payload = result.structured_content
        assert isinstance(payload, dict)
        assert payload["complete"] and not payload["all_connected"]
        assert payload["results"]["ok"]["connected"] is True
        assert payload["results"]["bad"]["connected"] is False
        diagnostics.ConnectionReport.model_validate(payload)
        assert isinstance(result.meta, dict)
        assert result.meta["connection_scope"] == "all"
        assert "connection_id" not in result.meta and "db_type" not in result.meta
        invalid = await client.call_tool("check_connections", {"connection_ids": ["ok"]}, raise_on_error=False)
        assert invalid.is_error
    records = [json.loads(line) for line in (tmp_path / "telemetry.jsonl").read_text().splitlines()]
    record = next(row for row in records if row["call_completed"])
    assert record["connection_scope"] == "all" and record["success"] is False
    assert record["connected_count"] == 1
    assert "connection_id" not in record and "db_type" not in record
    assert str(tmp_path) not in json.dumps(records)
    assert "check_connections() directly" in server._CONNECTION_ROUTING_GUIDANCE


@pytest.mark.asyncio
async def test_single_check_routing_and_list_remain_unchanged(server, monkeypatch):
    seen = []

    class Adapter:
        def check_connection(self):
            return True, "SQLite connection successful"

    def resolve(alias=None):
        seen.append(alias)
        item = config(alias or "default")
        return SimpleNamespace(adapter=Adapter(), db_type="sqlite", connection_id=item.connection_id, config=item)

    monkeypatch.setattr(server, "_resolve_connection_context", resolve)
    async with Client(server.mcp) as client:
        await client.call_tool("list_connections", {})
        assert not seen
        for args, expected in [({}, "default"), ({"connection_id": "other"}, "other")]:
            result = await client.call_tool("check_connection", args)
            assert isinstance(result.structured_content, dict)
            assert result.structured_content["connection_id"] == expected
            assert result.structured_content["connected"] is True
            assert "results" not in result.structured_content
    assert seen == [None, "other"]


@pytest.mark.asyncio
async def test_mcp_short_timeout_returns_partial_report_and_busy_telemetry(server, monkeypatch, tmp_path):
    release, started = Event(), Event()

    def probe(item):
        started.set()
        assert release.wait(3)
        return diagnostics.ConnectedCheck(db_type=item.db_type, status="connected", connected=True)

    runner = diagnostics.ConnectionDiagnostics(probe)
    monkeypatch.setattr(server, "_connection_diagnostics", runner)
    monkeypatch.setattr(server, "_MCP_TOOL_TIMEOUT", 0.25)
    monkeypatch.setattr(server, "list_connection_configs", lambda: [config()])
    # Also shorten the actual FastMCP wrapper, not just the internal budget.
    tool = await server.mcp.get_tool("check_connections")
    monkeypatch.setattr(tool, "timeout", 0.25)
    try:
        async with Client(server.mcp) as client:
            task = asyncio.create_task(client.call_tool("check_connections", {}))
            await until(started.is_set)
            # Metadata-only discovery remains responsive during blocking I/O.
            assert not (await client.call_tool("list_connections", {})).is_error
            result = await task
            assert not result.is_error
            assert isinstance(result.structured_content, dict)
            assert result.structured_content["results"]["main"]["connected"] is None
            assert result.structured_content["results"]["main"]["status"] == "timeout"
            busy = await client.call_tool("check_connections", {}, raise_on_error=False)
            assert busy.is_error
            release.set()
            await until(lambda: not runner._batch_active)
            recovered = await client.call_tool("check_connections", {})
            assert isinstance(recovered.structured_content, dict)
            assert recovered.structured_content["all_connected"]
        records = [json.loads(line) for line in (tmp_path / "telemetry.jsonl").read_text().splitlines()]
        failure = next(row for row in records if not row["call_completed"])
        assert failure["connection_scope"] == "all"
        assert "connection_id" not in failure and "db_type" not in failure
    finally:
        release.set()
        runner.close()


@pytest.mark.asyncio
async def test_shutdown_during_active_batch_and_worker_exception():
    started, release = Event(), Event()

    def probe(item):
        started.set()
        assert release.wait(3)
        raise RuntimeError("private host or credentials")

    runner = diagnostics.ConnectionDiagnostics(probe)
    runner.start()
    task = asyncio.create_task(runner.run([config()], 2))
    try:
        await until(started.is_set)
        runner.close()
        release.set()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="shutdown"):
            await task
        await until(lambda: not runner._batch_active)
        runner.start()
        report = await runner.run([config()], 1)
        assert report.complete and not report.all_connected
        assert "private" not in report.model_dump_json()
    finally:
        release.set()
        runner.close()


def test_agent_advertises_batch_tool_only_when_server_exposes_it():
    from agent_examples.autogen_sql_agent_new import ServerCapabilities, build_sql_executor_prompt

    caps = ServerCapabilities()
    assert "check_connections()" not in build_sql_executor_prompt(caps)
    caps.tool_names.add("check_connections")
    prompt = build_sql_executor_prompt(caps)
    assert "check_connections()" in prompt
    assert "never before routine queries" in prompt


@pytest.mark.asyncio
async def test_mcp_client_cancellation_keeps_diagnostic_busy_until_cleanup(server, monkeypatch):
    started, release = Event(), Event()

    def probe(item):
        started.set()
        assert release.wait(3)
        return diagnostics.ConnectedCheck(db_type=item.db_type, status="connected", connected=True)

    runner = diagnostics.ConnectionDiagnostics(probe)
    monkeypatch.setattr(server, "_connection_diagnostics", runner)
    monkeypatch.setattr(server, "list_connection_configs", lambda: [config()])
    try:
        async with Client(server.mcp) as client:
            request_id = client.session._request_id
            task = asyncio.create_task(client.call_tool("check_connections", {}))
            await until(started.is_set)
            # Cancelling a local asyncio task alone does not notify the server.
            await client.cancel(request_id, reason="Diagnostic no longer needed")
            await until(lambda: runner._draining)
            with pytest.raises(McpError, match="Request cancelled"):
                await task
            busy = await client.call_tool("check_connections", {}, raise_on_error=False)
            assert busy.is_error
            release.set()
            await until(lambda: not runner._batch_active)
            result = await client.call_tool("check_connections", {})
            assert isinstance(result.structured_content, dict)
            assert result.structured_content["all_connected"]
    finally:
        release.set()
        runner.close()


@pytest.mark.parametrize("status, connected, extra", [
    ("connected", True, {}), ("failed", False, {"error": "safe"}),
    ("timeout", None, {}), ("not_checked", None, {}),
])
def test_wire_schema_requires_status_and_connected(status, connected, extra):
    validator = Draft202012Validator(diagnostics.ConnectionReport.model_json_schema())
    item = {"db_type": "sqlite", "status": status, "connected": connected, **extra}
    report = {"all_connected": False, "complete": False, "connection_count": 1,
              "connected_count": 0, "cleanup_failed": False, "results": {"main": item}}
    assert validator.is_valid(report)
    for field in ("status", "connected"):
        incomplete = {key: value for key, value in item.items() if key != field}
        assert not validator.is_valid({**report, "results": {"main": incomplete}})


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [True, False])
async def test_cleanup_failure_preserves_connectivity_and_disables_further_work(monkeypatch, connected):
    created = []

    class Adapter:
        def check_connection(self):
            return connected, "Safe connection failure"

        def close(self):
            raise RuntimeError("private host password")

    def factory(**kwargs):
        created.append(kwargs["config"].connection_id)
        return Adapter()

    monkeypatch.setattr(diagnostics, "create_adapter", factory)
    monkeypatch.setattr(diagnostics, "MAX_DIAGNOSTIC_WORKERS", 1)
    runner = diagnostics.ConnectionDiagnostics()
    runner.start()
    try:
        report = await runner.run([config("first"), config("later")], 1)
        assert report.cleanup_failed
        assert report.results["first"].connected is connected
        assert report.results["first"].cleanup_failed
        assert report.results["later"].status == "not_checked"
        assert "cleanup failure" in report.results["later"].model_dump()["error"]
        assert created == ["first"]
        assert "private" not in report.model_dump_json()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="Restart the server process"):
            await runner.run([config()], 1)
        runner.close()
        runner.start()
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="disabled"):
            await runner.run([config()], 1)
    finally:
        runner.close()


@pytest.mark.asyncio
async def test_cleanup_failure_after_timeout_latches_without_rewriting_report(monkeypatch):
    started, release = Event(), Event()

    class Adapter:
        def check_connection(self):
            return True, "ok"

        def close(self):
            started.set()
            assert release.wait(3)
            raise RuntimeError("private cleanup detail")

    monkeypatch.setattr(diagnostics, "create_adapter", lambda **kwargs: Adapter())
    runner = diagnostics.ConnectionDiagnostics()
    runner.start()
    try:
        task = asyncio.create_task(runner.run([config()], 0.2))
        await until(started.is_set)
        report = await task
        assert report.results["main"].status == "timeout"
        assert report.cleanup_failed is False
        snapshot = report.model_dump_json()
        release.set()
        await until(lambda: not runner._batch_active)
        assert runner.cleanup_failed
        assert report.model_dump_json() == snapshot
        with pytest.raises(diagnostics.DiagnosticsUnavailable, match="disabled"):
            await runner.run([config()], 1)
    finally:
        release.set()
        runner.close()


@pytest.mark.asyncio
async def test_mcp_cleanup_failure_report_and_telemetry(server, monkeypatch, tmp_path):
    class Adapter:
        def check_connection(self):
            return True, "ok"

        def close(self):
            raise RuntimeError("private cleanup detail")

    monkeypatch.setattr(diagnostics, "create_adapter", lambda **kwargs: Adapter())
    monkeypatch.setattr(server, "list_connection_configs", lambda: [config()])
    async with Client(server.mcp) as client:
        result = await client.call_tool("check_connections", {})
        assert isinstance(result.structured_content, dict)
        assert result.structured_content["all_connected"]
        assert result.structured_content["complete"]
        assert result.structured_content["cleanup_failed"]
        assert isinstance(result.meta, dict)
        assert result.meta["success"] is False
        disabled = await client.call_tool("check_connections", {}, raise_on_error=False)
        assert disabled.is_error
        assert not (await client.call_tool("list_connections", {})).is_error
    records = [json.loads(line) for line in (tmp_path / "telemetry.jsonl").read_text().splitlines()]
    checks = [row for row in records if row["tool_name"] == "check_connections"]
    assert len(checks) == 2
    assert all(row["cleanup_failed"] and not row["success"] for row in checks)
    assert checks[0]["call_completed"] and not checks[1]["call_completed"]
    assert "private" not in json.dumps(records)
