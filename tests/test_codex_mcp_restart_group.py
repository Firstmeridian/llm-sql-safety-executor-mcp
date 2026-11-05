"""Whole-target restarts are explicit; ambiguous thread/PID maps stay unclaimed."""

import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from tests.test_codex_mcp_restart import helper

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix/pidfd helper")


@pytest.mark.parametrize("case,reason", [
    ("ok", None), ("probe", None), ("verify", None),
    ("busy", "other_thread_not_idle"),
    ("different_workspace", "loaded_thread_workspace_mismatch"),
    ("disconnected", "target_server_not_connected"),
    ("thread_drift", "loaded_threads_changed"),
    ("after_thread_drift", "loaded_threads_changed_after_refresh"),
    ("bad_before", "canary_result_unverified"),
    ("bad_after", "canary_result_unverified"),
    ("binding", "target_process_count_mismatch"),
    ("partial_stop", "target_stop_unconfirmed"),
    ("lost_refresh", "rpc_timeout"),
    ("not_replaced", "process_replacement_not_verified"),
])
def test_group_restart_requires_every_consumer_and_preserves_uncertainty(tmp_path, case, reason):
    path = tmp_path / "control.sock"
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(path))
    events, before_reads, after_reads = [], [], []
    action = case if case in {"probe", "verify"} else "restart"

    class Fake:
        def __init__(self, *args): self.lists = 0; self.refreshed = False
        def close(self): events.append("client_close")
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            events.append(method)
            if method == "initialize": return {}
            if method == "thread/loaded/list":
                self.lists += 1
                if ((case == "thread_drift" and self.lists > 1)
                        or (case == "after_thread_drift" and self.refreshed)):
                    return {"data": ["current", "new"]}
                return {"data": ["current", "other"]}
            if method == "thread/read":
                assert params["includeTurns"] is False
                other = params["threadId"] == "other"
                return {"thread": {"status": {"type": "active" if case == "busy" or not other else "idle"},
                                   "cwd": str(tmp_path if case == "different_workspace" and other else Path.cwd())}}
            if method == "mcpServerStatus/list":
                assert params["threadId"] in {"current", "other"}
                connected = not (case == "disconnected" and params["threadId"] == "other")
                return {"data": [{"name": "sql", "runtimeStatus": "connected" if connected else "starting",
                                  "tools": {"query": {}}}]}
            if method == "mcpServer/tool/call":
                reads = after_reads if self.refreshed or action == "verify" else before_reads
                reads.append(params["threadId"])
                valid = not (params["threadId"] == "other" and (
                    (case == "bad_before" and not self.refreshed)
                    or (case == "bad_after" and self.refreshed)))
                pid = (12 if self.refreshed else 10) + (params["threadId"] == "other")
                return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1 if valid else 0}]},
                        "_meta": {"server_pid": pid}}
            if method == "config/mcpServer/reload":
                self.refreshed = True
                if case == "lost_refresh": raise helper.ControlError("rpc_timeout")
                return {}
            pytest.fail(method)

    class Guard:
        def __init__(self, client, server, expected_count):
            self.client = client
            assert server == "sql" and expected_count == 2
            events.append("group_bound")
            self.members = [(10, "a"), (11, "b")]
            self.replacements = [(12, "c"), (13, "d")]
            self.signals_sent = self.stops_confirmed = 0
            if case == "binding": raise helper.ControlError("target_process_count_mismatch")
        def stop(self):
            events.append("stop")
            self.signals_sent = 2
            if case == "partial_stop":
                self.stops_confirmed = 1
                raise helper.ControlError("target_stop_unconfirmed")
            self.stops_confirmed = 2
        def replaced(self): return case != "not_replaced"
        def current_members(self): return self.replacements if self.client.refreshed else self.members
        def verify_consumers(self, pids, members): helper.verify_consumer_pids(pids, members)
        def close(self): events.append("guard_close")

    try:
        report = helper.run([path], "current", "sql", action=action, all_loaded_targets=True,
                            allow_host_wide=True, connection="test", factory=Fake, group_guard_factory=Guard)
        assert report.get("reason") == reason
        assert report["process_scope"] == "all_matching_target_children"
        assert report["thread_process_mapping"] == "unverified"
        assert report["model_tool_visibility"] == "unverified"
        assert events.count("config/mcpServer/reload") <= 1
        if case in {"ok", "bad_after", "not_replaced", "lost_refresh", "after_thread_drift"}:
            assert events.index("stop") < events.index("config/mcpServer/reload")
        if case in {"busy", "different_workspace", "disconnected", "thread_drift", "bad_before", "binding", "partial_stop", "probe", "verify"}:
            assert not report["reload_attempted"]
        if case in {"busy", "different_workspace", "disconnected", "thread_drift", "bad_before", "binding", "probe", "verify"}:
            assert not report["process_stop_attempted"]
        if case == "ok":
            assert before_reads == after_reads == ["current", "other"]
            assert report["process_restart_verified"] and report["read_probe_verified_thread_count"] == 2
            assert report["status"] == "connection_verified"
        if case == "probe":
            assert before_reads == after_reads == []
            assert not report["process_binding_verified"] and not report["read_probe_verified"]
        if case == "verify":
            assert after_reads == ["current", "other"]
            assert not report["process_restart_verified"]
        if case == "partial_stop":
            assert report["process_signals_sent"] == 2 and report["process_stops_confirmed"] == 1
            assert report["status"] == "process_stop_unconfirmed"
        if case == "lost_refresh":
            assert report["status"] == "reload_outcome_unconfirmed"
            assert not report["reload_accepted"]
        assert events[-1] == "client_close"
    finally:
        sock.close()


def test_group_mode_does_not_silently_enable_or_expand_refresh(tmp_path):
    def forbidden(*args): pytest.fail("Must not connect")
    r = helper.run([], "current", "sql", action="restart", all_loaded_targets=True, factory=forbidden)
    assert r["reason"] == "host_wide_consent_required"
    r = helper.run([], "current", "sql", action="refresh", all_loaded_targets=True, factory=forbidden)
    assert r["reason"] == "target_group_not_applicable_to_refresh"


def test_default_restart_still_rejects_multiple_loaded_threads(tmp_path):
    path = tmp_path / "control.sock"
    sock = socket.socket(socket.AF_UNIX); sock.bind(str(path))
    class Fake:
        def __init__(self, *args): pass
        def close(self): pass
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            if method == "initialize": return {}
            if method == "thread/loaded/list": return {"data": ["current", "other"]}
            if method == "thread/read": return {"thread": {"status": {"type": "idle"}}}
            if method == "mcpServerStatus/list": return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            if method == "mcpServer/tool/call": return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1}]}}
            pytest.fail(method)
    def forbidden(*args): pytest.fail("Must not bind or stop a group implicitly")
    try:
        r = helper.run([path], "current", "sql", action="restart", allow_host_wide=True, connection="test",
                       factory=Fake, guard_factory=forbidden, group_guard_factory=forbidden)
        assert r["reason"] == "single_loaded_thread_required_for_process_restart"
        assert not r["process_stop_attempted"] and not r["reload_attempted"]
    finally: sock.close()


@pytest.mark.parametrize("case", ["ok", "drift", "count", "alias", "alias_drift", "configuration", "partial_replacement"])
def test_group_pidfds_bind_only_owned_exact_children(tmp_path, monkeypatch, case):
    if not hasattr(os, "pidfd_open"): pytest.skip("Linux pidfd required")
    args = ["-c", "import time; time.sleep(35)"]
    owned = []
    def spawn(target=True):
        p = subprocess.Popen([sys.executable, *(args if target else ["-c", "import time; time.sleep(36)"])], cwd=tmp_path)
        owned.append(p)
        return p
    targets = [spawn(), spawn()]
    unrelated = spawn(False)
    config = {"sql": {"command": sys.executable, "args": args, "cwd": str(tmp_path)}}
    if case == "alias": config["different-server"] = dict(config["sql"])
    class Fake:
        path = tmp_path / "unused"
        def call(self, method, params, *, timeout=None):
            assert method == "config/read"
            return {"config": {"mcp_servers": config}}
    monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
    guard = None
    try:
        if case in {"count", "alias"}:
            reason = "target_process_count_mismatch" if case == "count" else "ambiguous_server_launch_configuration"
            with pytest.raises(helper.ControlError, match=reason):
                helper.ProcessGroupGuard(Fake(), "sql", 1 if case == "count" else 2)
        else:
            guard = helper.ProcessGroupGuard(Fake(), "sql", 2)
            assert {pid for pid, _ in guard.members} == {p.pid for p in targets}
            assert all(p.poll() is None for p in owned)  # Binding sends no signal.
            guard.verify_consumers([p.pid for p in targets], guard.current_members())
            if case == "drift":
                spawn()
                with pytest.raises(helper.ControlError, match="target_process_count_mismatch"):
                    guard.stop()
                assert guard.signals_sent == 0 and all(p.poll() is None for p in owned)
            elif case == "configuration":
                config["sql"]["args"] = ["-c", "changed"]
                with pytest.raises(helper.ControlError, match="target_configuration_changed"):
                    guard.stop()
                assert guard.signals_sent == 0 and all(p.poll() is None for p in owned)
            elif case == "alias_drift":
                config["different-server"] = dict(config["sql"])
                with pytest.raises(helper.ControlError, match="ambiguous_server_launch_configuration"):
                    guard.stop()
                assert guard.signals_sent == 0 and all(p.poll() is None for p in owned)
            elif case == "partial_replacement":
                targets[0].terminate(); targets[0].wait(timeout=2)
                spawn()
                assert not guard.replaced()  # An original member survives.
                assert unrelated.poll() is None and targets[1].poll() is None
            else:
                guard.stop()
                for p in targets: p.wait(timeout=2)
                assert guard.signals_sent == guard.stops_confirmed == 2
                assert unrelated.poll() is None
                spawn(); spawn()
                assert guard.replaced()
                assert unrelated.poll() is None
    finally:
        if guard is not None: guard.close()
        for p in owned:
            if p.poll() is None: p.terminate()
            p.wait(timeout=2)


def test_group_never_signals_identical_launcher_under_another_parent(tmp_path, monkeypatch):
    args = ["-c", "import time; time.sleep(35)"]
    targets = [subprocess.Popen([sys.executable, *args], cwd=tmp_path) for _ in range(2)]
    parent_code = (
        "import subprocess,sys\n"
        f"p=subprocess.Popen({[sys.executable, *args]!r})\n"
        "try:\n print(p.pid,flush=True)\n sys.stdin.readline()\n"
        "finally:\n p.terminate()\n p.wait(timeout=2)\n"
    )
    other_parent = subprocess.Popen([sys.executable, "-c", parent_code], cwd=tmp_path,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    guard = None
    try:
        other_pid = int(other_parent.stdout.readline())
        class Fake:
            path = tmp_path / "unused"
            def call(self, method, params, *, timeout=None):
                return {"config": {"mcp_servers": {"sql": {
                    "command": sys.executable, "args": args, "cwd": str(tmp_path)}}}}
        monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
        guard = helper.ProcessGroupGuard(Fake(), "sql", 2)
        assert {pid for pid, _ in guard.members} == {p.pid for p in targets}
        guard.verify_consumers([p.pid for p in targets], guard.current_members())
        guard.stop()
        for p in targets: p.wait(timeout=2)
        os.kill(other_pid, 0)
        assert helper.process_state(other_pid)[0] == other_parent.pid
    finally:
        if guard is not None: guard.close()
        for p in targets:
            if p.poll() is None: p.terminate()
            p.wait(timeout=2)
        other_parent.communicate("done\n", timeout=3)
