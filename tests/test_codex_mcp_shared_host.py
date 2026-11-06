"""Opt-in shared-Host restart signals only the verified current consumer.

The Host is entirely fake. The process tests below own every child they signal;
none of these tests discovers or connects to an actual Codex Host.
"""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_restart import helper


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix/pidfd helper")
CURRENT, OTHER = "z-current", "a-other"
THREADS = {CURRENT, OTHER}


@pytest.fixture
def shared_host(tmp_path, monkeypatch):
    """Exercise run and the real shared guard methods without OS side effects."""
    events = []

    class Host:
        def __init__(self, path, timeout):
            self.path = path
            self.case = "ok"
            self.threads = set(THREADS)
            self.busy = False
            self.refreshed = False
            self.stopped = False
            self.config_reads = 0
            self.reads = {False: [], True: []}
            self.before = [(10, "other-old"), (11, "current-old")]

        @property
        def members(self):
            if not self.refreshed:
                return list(self.before)
            current = (11, "current-old") if self.case == "not_replaced" else (21, "current-new")
            other = (20, "other-new") if self.case == "host_replaces_other" else self.before[0]
            return sorted([other, current])

        def close(self):
            events.append(("close",))

        def send(self, message):
            assert message == {"method": "initialized"}

        def call(self, method, params, *, timeout=None):
            events.append((method,))
            if method == "initialize":
                return {}
            if method == "thread/loaded/list":
                threads = set(self.threads)
                if self.refreshed and self.case == "thread_after_refresh":
                    threads.add("new-chat")
                return {"data": sorted(threads)}
            if method == "thread/read":
                assert params["includeTurns"] is False
                other = params["threadId"] != CURRENT
                busy = other and (self.busy or self.case == "busy")
                cwd = tmp_path if other and self.case == "different_workspace" else Path.cwd()
                return {"thread": {"cwd": str(cwd), "status": {"type": "active" if busy else "idle"}}}
            if method == "mcpServerStatus/list":
                if params["threadId"] == OTHER and self.case == "missing_catalog":
                    return {"data": []}
                return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            if method == "config/read":
                self.config_reads += 1
                if self.config_reads == 2:
                    if self.case == "active_during_config":
                        self.busy = True
                    if self.case == "thread_during_config":
                        self.threads.add("new-chat")
                args = ["changed"] if self.config_reads == 2 and self.case == "config_drift" else []
                return {"config": {"mcp_servers": {"sql": {
                    "command": sys.executable, "args": args, "cwd": str(Path.cwd())}}}}
            if method == "mcpServer/tool/call":
                thread = params["threadId"]
                self.reads[self.refreshed].append(thread)
                assert params["arguments"] == {
                    "connection_id": "test", "sql": "SELECT 1 AS codex_mcp_restart_canary"}
                current = next(member for member in self.members if member[0] in {11, 21})
                other = next(member for member in self.members if member != current)
                pid = current[0] if thread == CURRENT else other[0]
                if self.case == "shared_pid" and not self.refreshed:
                    pid = 11
                if self.case == "wrong_pid" and thread == CURRENT and not self.refreshed:
                    pid = 999
                if self.case == "bad_after" and self.refreshed:
                    raise helper.ControlError("rpc_timeout")
                return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1}]},
                        "_meta": {"server_pid": pid}}
            if method == "config/mcpServer/reload":
                assert params is None
                self.refreshed = True
                if self.case == "lost_reload":
                    raise helper.ControlError("rpc_timeout")
                return {}
            pytest.fail(f"Unexpected RPC: {method}")

    host = Host(tmp_path / "fake-control", 10)

    class Guard(helper.SharedHostGuard):
        def __init__(self, client, server, threads, thread_id):
            assert client is host and server == "sql" and threads == THREADS and thread_id == CURRENT
            self.client, self.server = client, server
            self.threads, self.thread_id = sorted(threads), thread_id
            self.before = self.observed = None
            self.host_pid = 1
            _, self.command, self.args, self.cwd = helper.process_configuration(client, server)
            self.members = self.current()
            self.fds = [pid for pid, _ in self.members]
            self.consumers_verified = False
            self.signals_sent = self.stops_confirmed = 0

        def current(self):
            return self.client.members

        def close(self):
            events.append(("guard_close",))

    def send_signal(fd, sig):
        assert sig == signal.SIGTERM
        events.append(("signal", fd))
        host.stopped = True
        if host.case == "active_after_stop":
            host.busy = True
        if host.case == "thread_after_stop":
            host.threads.add("new-chat")

    def state(pid):
        return 1, dict(host.before)[pid]

    monkeypatch.setattr(helper, "owned_socket", lambda path: None)
    monkeypatch.setattr(helper, "process_state", state)
    monkeypatch.setattr(helper, "signal", SimpleNamespace(SIGTERM=signal.SIGTERM, pidfd_send_signal=send_signal))
    monkeypatch.setattr(helper, "select", SimpleNamespace(select=lambda r, w, x, timeout: (r, [], [])))

    def run(**options):
        kwargs = dict(action="restart", connection="test", allow_host_wide=True, allow_shared_host=True,
                      factory=lambda *args: host, shared_guard_factory=Guard)
        kwargs.update(options)
        return helper.run([host.path], CURRENT, "sql", **kwargs)

    return SimpleNamespace(host=host, events=events, run=run)


@pytest.mark.parametrize("case,reason,signals,reloads", [
    ("ok", None, 1, 1),
    ("host_replaces_other", None, 1, 1),
    ("busy", "other_thread_not_idle", 0, 0),
    ("different_workspace", "loaded_thread_workspace_mismatch", 0, 0),
    ("missing_catalog", "target_server_not_observed", 0, 0),
    ("shared_pid", "consumer_process_identity_mismatch", 0, 0),
    ("wrong_pid", "consumer_process_identity_mismatch", 0, 0),
    ("config_drift", "target_configuration_changed", 0, 0),
    ("active_during_config", "other_thread_not_idle", 0, 0),
    ("thread_during_config", "loaded_threads_changed", 0, 0),
    ("active_after_stop", "other_thread_not_idle", 1, 0),
    ("thread_after_stop", "loaded_threads_changed", 1, 0),
    ("thread_after_refresh", "loaded_threads_changed_after_refresh", 1, 1),
    ("lost_reload", "rpc_timeout", 1, 1),
    ("bad_after", "rpc_timeout", 1, 1),
    ("not_replaced", "process_replacement_not_verified", 1, 1),
])
def test_shared_restart_keeps_exact_stop_scope_and_does_not_retry(shared_host, case, reason, signals, reloads):
    env = shared_host
    env.host.case = case
    report = env.run()
    assert report.get("reason") == reason
    assert [e for e in env.events if e[0] == "signal"] == [("signal", 11)] * signals
    assert env.events.count(("config/mcpServer/reload",)) == reloads
    assert report.get("process_signals_sent", 0) == signals
    assert report["reload_attempted"] == bool(reloads)
    assert report["process_scope"] == "current_thread_exclusive_child"
    assert report["other_chat_refresh_impact"] == "possible"
    assert report["model_tool_visibility"] == "unverified"
    assert env.events[-1] == ("close",)
    if reason is None:
        assert report["status"] == "connection_verified"
        assert report["process_restart_verified"] and report["read_probe_verified_thread_count"] == 2
        assert report["thread_process_mapping"] == "consumer_pid_verified"
        assert env.host.reads == {False: sorted(THREADS), True: sorted(THREADS)}
        observed = report["consumer_process_observations"]
        assert len(observed) == 2
        by_hash = {r["thread_sha256"]: r for r in observed}
        current = by_hash[hashlib.sha256(CURRENT.encode()).hexdigest()[:16]]
        other = by_hash[hashlib.sha256(OTHER.encode()).hexdigest()[:16]]
        assert current == {"thread_sha256": current["thread_sha256"], "current_thread": True,
                           "before": (11, "current-old"), "after": (21, "current-new"), "process_replaced": True}
        assert other["current_thread"] is False
        assert other["process_replaced"] == (case == "host_replaces_other")
        assert other["before"] == (10, "other-old")
        assert other["after"] == ((20, "other-new") if case == "host_replaces_other" else (10, "other-old"))
    else:
        assert not report["process_restart_verified"]
        if signals == 0:
            assert not env.host.stopped


def test_shared_verify_proves_consumers_without_claiming_a_restart(shared_host):
    report = shared_host.run(action="verify", check_process=True, allow_host_wide=False)
    assert report["status"] == "connection_verified"
    assert report["process_binding_verified"] and report["read_probe_verified_thread_count"] == 2
    assert not report["process_restart_verified"] and not report["process_stop_attempted"]
    assert not report["reload_attempted"]
    assert shared_host.host.reads == {False: sorted(THREADS), True: []}
    assert all(not item["process_replaced"] for item in report["consumer_process_observations"])
    assert not any(e[0] in {"signal", "config/mcpServer/reload"} for e in shared_host.events)


@pytest.mark.parametrize("options,reason", [
    ({"allow_shared_host": False}, "single_loaded_thread_required_for_process_restart"),
    ({"all_loaded_targets": True}, "shared_host_requires_restart_or_process_verify"),
    ({"action": "probe"}, "shared_host_requires_restart_or_process_verify"),
    ({"action": "refresh"}, "shared_host_requires_restart_or_process_verify"),
    ({"action": "verify"}, "shared_host_requires_restart_or_process_verify"),
    ({"allow_host_wide": False}, "host_wide_consent_required"),
])
def test_shared_scope_is_explicit_and_flag_combinations_do_not_expand_it(shared_host, options, reason):
    report = shared_host.run(**options)
    assert report["reason"] == reason
    assert not report["process_stop_attempted"] and not report["reload_attempted"]
    assert not any(e[0] in {"signal", "config/mcpServer/reload", "config/read"} for e in shared_host.events)


def test_shared_host_thread_budget_precedes_process_binding(shared_host):
    shared_host.host.threads.update(f"other-{i}" for i in range(7))
    report = shared_host.run()
    assert report["reason"] == "target_group_thread_budget_exceeded"
    assert not report["process_stop_attempted"] and not report["reload_attempted"]
    assert ("config/read",) not in shared_host.events


@pytest.mark.parametrize("case", ["exclusive", "configuration_drift", "scope_change"])
def test_real_pidfds_signal_only_the_current_owned_child(tmp_path, monkeypatch, case):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        pytest.skip("Linux pidfd required")
    args = ["-c", "import time; time.sleep(35)"]
    owned = []

    def spawn():
        child = subprocess.Popen([sys.executable, *args], cwd=tmp_path)
        owned.append(child)
        return child

    other, current = spawn(), spawn()
    config = {"sql": {"command": sys.executable, "args": args, "cwd": str(tmp_path)}}
    config_reads = []

    class Host:
        path = tmp_path / "unused-control"

        def call(self, method, params, *, timeout=None):
            assert method == "config/read"
            config_reads.append(True)
            return {"config": {"mcp_servers": config}}

    monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
    guard = None
    try:
        guard = helper.SharedHostGuard(Host(), "sql", THREADS, CURRENT)
        assert {pid for pid, _ in guard.members} == {p.pid for p in owned}
        guard.verify_consumers([other.pid, current.pid], guard.current_members())
        assert all(p.poll() is None for p in owned)
        scope_checks = []

        def scope():
            # This callback must run after the stop-time config read, before SIGTERM.
            assert len(config_reads) == 2 and all(p.poll() is None for p in owned)
            scope_checks.append(True)
            if case == "scope_change":
                raise helper.ControlError("other_thread_not_idle")

        if case == "configuration_drift":
            config["sql"]["args"] = ["-c", "changed"]
            with pytest.raises(helper.ControlError, match="target_configuration_changed"):
                guard.stop(scope_check=scope)
            assert not scope_checks
        elif case == "scope_change":
            with pytest.raises(helper.ControlError, match="other_thread_not_idle"):
                guard.stop(scope_check=scope)
        else:
            guard.stop(scope_check=scope)
            current.wait(timeout=2)
            assert current.returncode == -signal.SIGTERM
            assert other.poll() is None
            assert guard.signals_sent == guard.stops_confirmed == 1
            replacement = spawn()
            guard.verify_consumers([other.pid, replacement.pid], guard.current_members())
            assert guard.replaced()
            observations = guard.observations()
            assert [(r["current_thread"], r["process_replaced"]) for r in observations] == [(False, False), (True, True)]
            assert other.poll() is None
        if case != "exclusive":
            assert guard.signals_sent == guard.stops_confirmed == 0
            assert all(p.poll() is None for p in owned)
        assert len(scope_checks) == (case != "configuration_drift")
    finally:
        if guard is not None:
            guard.close()
        for child in owned:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=2)
