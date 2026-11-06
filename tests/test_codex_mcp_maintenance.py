"""Maintenance cooperation and receipts, using owned children and fake Hosts only."""

from contextlib import contextmanager
import json
from pathlib import Path
import select
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_recreate import host  # noqa: F401
from tests.test_codex_mcp_restart import helper
from tests.test_codex_mcp_shared_host import CURRENT, OTHER, shared_host  # noqa: F401


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux maintenance helper")


@pytest.fixture
def locks(tmp_path):
    root = tmp_path / "private-locks"

    def acquire(path):
        return helper.HostMaintenanceLock(path, root=root)

    return SimpleNamespace(root=root, acquire=acquire)


def assert_locked(locks, path):
    with pytest.raises(helper.ControlError, match="^host_maintenance_in_progress$"):
        locks.acquire(path)


def assert_released(locks, path):
    lock = locks.acquire(path)
    lock.close()


@contextmanager
def child_lock(path, root):
    """A separate interpreter holds the actual flock; stdin controls its lifetime."""
    source = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('owned_helper', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
lock = module.HostMaintenanceLock(sys.argv[2], root=sys.argv[3])
print('locked', flush=True)
sys.stdin.readline()
os._exit(0)  # Deliberately leave the descriptor open until process exit.
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source, helper.__file__, str(path), str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "Owned lock-holder did not initialize"
        assert process.stdout.readline().strip() == "locked"
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)


@pytest.mark.parametrize("exit_method", ["exit", "terminate"])
def test_cross_process_lock_excludes_aliases_and_releases_on_exit(tmp_path, locks, exit_method):
    endpoint = tmp_path / "control.sock"
    endpoint.touch()
    alias = tmp_path / "endpoint-alias"
    alias.symlink_to(endpoint)
    with child_lock(endpoint, locks.root) as process:
        assert_locked(locks, endpoint)
        assert_locked(locks, alias)
        files = list(locks.root.iterdir())
        assert len(files) == 1
        original_inode = files[0].stat().st_ino
        assert locks.root.stat().st_mode & 0o777 == 0o700
        assert files[0].stat().st_mode & 0o777 == 0o600
        if exit_method == "exit":
            process.stdin.write("exit\n")
            process.stdin.flush()
        else:
            process.terminate()
        process.wait(timeout=10)
        assert_released(locks, alias)
        # Removal/recreation would permit contenders to hold different inodes.
        assert files[0].stat().st_ino == original_inode
    assert_released(locks, endpoint)


def test_different_host_endpoints_do_not_block_each_other(tmp_path, locks):
    first = locks.acquire(tmp_path / "first.sock")
    try:
        assert_released(locks, tmp_path / "second.sock")
        assert_locked(locks, tmp_path / "first.sock")
    finally:
        first.close()


@pytest.mark.parametrize("thread,server", [(CURRENT, "sql"), (OTHER, "another-server")])
def test_same_host_lock_ignores_server_and_thread_but_allows_readonly(
    shared_host, locks, monkeypatch, thread, server,
):
    env = shared_host
    original = env.host.call

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "mcpServerStatus/list":
            result["data"][0]["name"] = params["serverName"]
        return result

    monkeypatch.setattr(env.host, "call", call)
    held = locks.acquire(env.host.path)
    try:
        options = dict(connection="test", factory=lambda *args: env.host,
                       allow_host_wide=True, lock_factory=locks.acquire)
        refused = helper.run([env.host.path], thread, server, action="refresh", **options)
        assert refused["reason"] == "host_maintenance_in_progress"
        assert not refused["reload_attempted"] and not refused["process_stop_attempted"]
        assert refused["next_action"]["action"] == "wait_for_other_maintenance"

        def forbidden_lock(_path):
            pytest.fail("Read-only commands must not acquire an exclusive maintenance lock")

        options["lock_factory"] = forbidden_lock
        for action, status in [("probe", "binding_verified"), ("verify", "connection_verified")]:
            result = helper.run([env.host.path], thread, server, action=action, **options)
            assert result["status"] == status
            assert not result["maintenance_lock_acquired"]
        assert not any(event[0] in {"signal", "config/mcpServer/reload"} for event in env.events)
    finally:
        held.close()


def test_recreate_contention_precedes_config_changes_and_dry_run_remains_available(host, locks):
    held = locks.acquire(host.path)
    try:
        report = host.run(lock_factory=locks.acquire)
        assert report["reason"] == "host_maintenance_in_progress"
        assert not host.writes and host.refreshes == 0 and not host.journal.exists()
        assert host.config.read_bytes() == host.original_bytes

        def forbidden_lock(_path):
            pytest.fail("A read-only recreate plan must not acquire the maintenance lock")

        plan = host.run(dry_run=True, lock_factory=forbidden_lock)
        assert plan["status"] == "recreate_plan_verified"
        assert not host.writes and not host.journal.exists()
    finally:
        held.close()


def test_recreate_post_lock_preflight_io_error_is_not_misattributed_to_storage(host, locks, monkeypatch):
    def unavailable_owner(_path):
        assert_locked(locks, host.path)
        raise OSError("test-owned process metadata became unavailable")

    monkeypatch.setattr(helper, "socket_owner", unavailable_owner)
    report = host.run(lock_factory=locks.acquire)
    assert report["maintenance_lock_acquired"]
    assert report["phase"] == "target_preflight"
    assert report["reason"] == "local_operation_failed"
    assert report["next_action"]["action"] != "inspect_lock_storage"
    assert not host.writes and host.refreshes == 0 and not host.journal.exists()
    assert_released(locks, host.path)


@pytest.mark.parametrize("mode", ["restart", "recreate"])
def test_client_cleanup_exception_still_releases_maintenance_lock(
    shared_host, host, locks, monkeypatch, mode,
):
    target = shared_host.host if mode == "restart" else host

    def failed_close():
        assert_locked(locks, target.path)
        raise RuntimeError("test-owned cleanup failure")

    monkeypatch.setattr(target, "close", failed_close)
    # Real Client.close suppresses transport cleanup errors; an injected failure
    # must still never strand the cooperation lock in this interpreter.
    with pytest.raises(RuntimeError, match="test-owned cleanup failure"):
        if mode == "restart":
            shared_host.run(lock_factory=locks.acquire)
        else:
            host.run(lock_factory=locks.acquire)
    assert_released(locks, target.path)


@pytest.mark.parametrize("case,refreshes", [("ok", 1), ("busy", 0), ("lost_reload", 1), ("bad_after", 1)])
def test_restart_holds_lock_until_client_cleanup_and_never_replays_refresh(
    shared_host, locks, monkeypatch, case, refreshes,
):
    env = shared_host
    env.host.case = case
    original_call, original_close = env.host.call, env.host.close
    observed = []

    def call(method, params, *, timeout=None):
        if method in {"mcpServer/tool/call", "config/mcpServer/reload"}:
            assert_locked(locks, env.host.path)
            observed.append(method)
        return original_call(method, params, timeout=timeout)

    def close():
        assert_locked(locks, env.host.path)
        observed.append("client_cleanup")
        original_close()

    monkeypatch.setattr(env.host, "call", call)
    monkeypatch.setattr(env.host, "close", close)
    report = env.run(lock_factory=locks.acquire)
    assert report["maintenance_lock_acquired"]
    assert observed[-1] == "client_cleanup"
    assert observed.count("config/mcpServer/reload") == refreshes
    assert_released(locks, env.host.path)
    if case != "ok":
        assert report["status"] != "connection_verified"


@pytest.mark.parametrize("failure", [None, "refresh_1", "restore_conflict"])
def test_recreate_keeps_lock_through_restoration_final_journal_sync_and_close(
    host, locks, monkeypatch, failure,
):
    host.failure = failure
    original_call, original_fsync, original_open = host.call, helper.os.fsync, Path.open
    observed = []

    def call(method, params, *, timeout=None):
        if method in {"config/batchWrite", "config/mcpServer/reload"}:
            assert_locked(locks, host.path)
            observed.append(method)
        return original_call(method, params, timeout=timeout)

    def fsync(fd):
        original_fsync(fd)
        assert_locked(locks, host.path)
        observed.append("journal_sync")

    class Journal:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            assert_locked(locks, host.path)
            observed.append("journal_close")
            self.stream.close()

    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return Journal(stream) if path == host.journal and args and args[0] == "x" else stream

    monkeypatch.setattr(host, "call", call)
    monkeypatch.setattr(helper.os, "fsync", fsync)
    monkeypatch.setattr(Path, "open", open_file)
    report = host.run(lock_factory=locks.acquire)
    assert observed[-2:] == ["journal_sync", "journal_close"]
    assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))
    assert_released(locks, host.path)
    assert host.refreshes == (2 if failure is None else 1)
    assert len(host.writes) == 2
    if failure == "refresh_1":
        assert report["config_restored"] and report["manual_recovery_required"]
        assert not report["process_restart_verified"]


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.mark.parametrize("failure", [None, "lost_reload"])
def test_restart_phase_times_include_failure_and_total_includes_client_cleanup(
    shared_host, locks, monkeypatch, failure,
):
    env, clock = shared_host, Clock()
    env.host.case = failure or "ok"
    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.advance))
    original_call, original_close = env.host.call, env.host.close

    def call(method, params, *, timeout=None):
        if method == "initialize":
            clock.advance(.25)
        if method == "config/mcpServer/reload":
            clock.advance(.5)
        if env.host.refreshed and method == "mcpServerStatus/list":
            clock.advance(1)
        if env.host.refreshed and method == "mcpServer/tool/call":
            clock.advance(.5)
        return original_call(method, params, timeout=timeout)

    def stopped(readers, writers, errors, timeout):
        assert timeout <= 10
        clock.advance(1.25)
        return readers, [], []

    def close():
        clock.advance(.125)
        original_close()

    monkeypatch.setattr(env.host, "call", call)
    monkeypatch.setattr(env.host, "close", close)
    monkeypatch.setattr(helper, "select", SimpleNamespace(select=stopped))
    report = env.run(lock_factory=locks.acquire)
    times = report["timings_ms"]
    assert times["host_binding"] == 250
    assert times["process_stop"] == 1250
    assert times["host_refresh"] == 500
    if failure:
        assert report["reason"] == "rpc_timeout"
        assert times["total"] == 2125
        assert "consumer_verification" not in times
    else:
        assert times["consumer_verification"] == 3000  # Two catalogs and two canaries.
        assert times["total"] == 5125
        assert report["consumer_readiness_budget_sec"] == 30
    assert env.events.count(("config/mcpServer/reload",)) == 1


@pytest.mark.parametrize("failure", [None, "refresh_1"])
def test_recreate_refresh_times_accumulate_and_failed_cleanup_is_timed(host, locks, monkeypatch, failure):
    clock = Clock()
    host.failure = failure
    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.advance))
    original = host.call

    def call(method, params, *, timeout=None):
        if method == "initialize":
            clock.advance(.25)
        if method == "config/mcpServer/reload":
            clock.advance(.5)
        if method == "config/batchWrite" and params["edits"][0]["value"] is not False:
            clock.advance(.75)
        if method == "mcpServer/tool/call":
            clock.advance(1)
        return original(method, params, timeout=timeout)

    monkeypatch.setattr(host, "call", call)
    report = host.run(lock_factory=locks.acquire)
    times = report["timings_ms"]
    assert times["host_binding"] == 250
    if failure:
        assert times["host_refresh"] == 500
        assert times["config_cleanup"] == 750
        assert times["total"] == 1500
        assert report["config_restored"] and not report["read_probe_verified"]
    else:
        assert times["host_refresh"] == 1000
        assert "config_cleanup" not in times
        assert times["consumer_verification"] == 1000
        assert times["total"] == 3000
    assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))


@pytest.mark.parametrize("action", ["refresh", "recreate"])
def test_timing_does_not_extend_operation_or_readiness_budget(shared_host, host, locks, monkeypatch, action):
    clock = Clock()
    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.advance))
    target = shared_host.host if action == "refresh" else host
    if action == "refresh":
        target.threads = {CURRENT}
    original = target.call
    timeouts = []

    def call(method, params, *, timeout=None):
        if method == "initialize":
            clock.advance(45)  # Only fifteen seconds remain from the original sixty.
        ready = (target.refreshed if action == "refresh" else target.refreshes == 2)
        if ready and method == "mcpServerStatus/list":
            timeouts.append(timeout)
            assert target.deadline == 160
            clock.advance(timeout)
            raise helper.ControlError("rpc_timeout")
        return original(method, params, timeout=timeout)

    monkeypatch.setattr(target, "call", call)
    if action == "refresh":
        report = shared_host.run(action="refresh", allow_shared_host=False, lock_factory=locks.acquire)
    else:
        report = host.run(timeout=1, lock_factory=locks.acquire)
    assert report["reason"] == "rpc_timeout"
    assert timeouts == [15] and report["consumer_readiness_budget_sec"] == 15
    assert report["timings_ms"]["consumer_verification"] == 15000
    assert report["timings_ms"]["total"] == 60000
    assert not report["read_probe_verified"]
    if action == "refresh":
        assert shared_host.events.count(("config/mcpServer/reload",)) == 1
    else:
        assert host.refreshes == 2 and len(host.writes) == 2


@pytest.mark.parametrize("fields,action,phrase", [
    ({"reason": "host_maintenance_in_progress"}, "wait_for_other_maintenance", "does not wait or retry"),
    ({"reason": "other_thread_not_idle"}, "resolve_maintenance_scope", "Do not automatically widen scope"),
    ({"reason": "loaded_threads_changed"}, "resolve_maintenance_scope", "unconfirmed writes"),
    ({"reload_attempted": True}, "verify_runtime_read_only", "do not infer recovery"),
    ({"process_stop_attempted": True}, "inspect_target_read_only", "does not prove exit"),
    ({"refresh_attempts": 1, "config_restored": True, "manual_recovery_required": True},
     "reconcile_config_and_runtime", "Restored configuration does not prove runtime recovery"),
])
def test_next_action_is_guidance_and_preserves_uncertainty(fields, action, phrase):
    report = {"status": "unverified", "phase": "test", **fields}
    before = dict(report)
    helper.add_next_action(report)
    suggestion = report.pop("next_action")
    assert report == before
    assert suggestion["action"] == action and phrase in suggestion["message"]
    assert "wrote nothing" not in suggestion["message"].lower()
    assert "not executed" not in suggestion["message"].lower()
