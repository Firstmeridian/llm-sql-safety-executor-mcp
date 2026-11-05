"""Host control is scoped explicitly; uncertain mutations are never retried."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest
from websockets.sync.server import unix_serve

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix/pidfd helper")


spec = importlib.util.spec_from_file_location(
    "codex_restart", Path(__file__).resolve().parents[1] / "scripts/dev/restart_codex_mcp.py")
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.mark.parametrize("case,reason", [
    ("ok", None), ("wrong_thread", "current_host_not_verified"),
    ("no_consent", "host_wide_consent_required"),
    ("busy_other", "single_loaded_thread_required_for_refresh"),
    ("idle_other", "single_loaded_thread_required_for_refresh"),
    ("lost_reload", "rpc_timeout"), ("bad_canary", "canary_result_unverified"),
    ("tool_error", "canary_tool_error"), ("bad_after", "canary_result_unverified"),
])
def test_refresh_contract(tmp_path, case, reason):
    path = tmp_path / "control.sock"
    control = socket.socket(socket.AF_UNIX)
    control.bind(str(path))
    calls = []
    closed = []

    class Fake:
        def __init__(self, *args): self.reads = 0
        def send(self, message): assert message == {"method": "initialized"}
        def close(self): closed.append(True)
        def call(self, method, params, *, timeout=None):
            calls.append(method)
            if method == "initialize": return {}
            if method == "thread/loaded/list":
                threads = (["other"] if case == "wrong_thread" else
                           ["current", "other"] if case in {"busy_other", "idle_other"} else ["current"])
                return {"data": threads}
            if method == "thread/read":
                assert params == {"threadId": "other", "includeTurns": False}
                return {"thread": {"status": {"type": "active" if case == "busy_other" else "idle"}}}
            if method == "mcpServerStatus/list":
                assert params["threadId"] == "current"
                return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {"description": "read"}}}]}
            if method == "config/mcpServer/reload":
                assert params is None
                if case == "lost_reload": raise helper.ControlError("rpc_timeout")
                return {}
            if method == "mcpServer/tool/call":
                self.reads += 1
                assert params == {"threadId": "current", "server": "sql", "tool": "query",
                                  "arguments": {"connection_id": "test", "sql": "SELECT 1 AS codex_mcp_restart_canary"}}
                if case == "tool_error": return {"isError": True}
                valid = case != "bad_canary" and not (case == "bad_after" and self.reads == 2)
                return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1 if valid else 99}]}}
            pytest.fail(method)
    try:
        report = helper.run([path], "current", "sql", action="refresh", connection="test",
                            allow_host_wide=case != "no_consent", factory=Fake)
        assert report.get("reason") == reason
        assert report["read_probe_verified"] is (case == "ok")
        assert not report["process_restart_verified"]
        assert report["model_tool_visibility"] == "unverified"
        assert calls.count("config/mcpServer/reload") <= 1
        if case in {"wrong_thread", "no_consent", "busy_other", "idle_other", "bad_canary", "tool_error"}:
            assert not report["reload_attempted"]
        if case == "lost_reload":
            assert report["reload_attempted"] and not report["reload_accepted"]
            assert report["status"] == "reload_outcome_unconfirmed"
        assert len(closed) == (0 if case == "no_consent" else 1)
    finally:
        control.close()


def test_real_websocket_protocol_and_unsolicited_request(tmp_path):
    path = str(tmp_path / "ws.sock")
    received = []
    def handler(connection):
        request = json.loads(connection.recv())
        connection.send(json.dumps({"id": "approval", "method": "requestApproval", "params": {}}))
        received.append(json.loads(connection.recv()))
        connection.send(json.dumps({"method": "notification", "params": {}}))
        connection.send(json.dumps({"id": request["id"], "result": {"value": 7}}))
    with unix_serve(handler, path) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = helper.Client(Path(path), 1)
            try: assert client.call("test", {}) == {"value": 7}
            finally: client.close()
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert received[0]["id"] == "approval" and "error" in received[0]


def test_ambiguous_binding_closes_all_candidates(tmp_path):
    paths, controls, closed = [], [], []
    for i in range(2):
        path = tmp_path / str(i)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(path)); paths.append(path); controls.append(sock)
    class Fake:
        def __init__(self, *args): pass
        def close(self): closed.append(True)
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            if method == "thread/loaded/list": return {"data": ["current"]}
            if method == "mcpServerStatus/list": return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            return {}
    try:
        report = helper.run(paths, "current", "sql", factory=Fake)
        assert report["reason"] == "ambiguous_host_binding"
        assert closed == [True, True] and not report["reload_attempted"]
    finally:
        for sock in controls: sock.close()


def test_symlink_socket_and_missing_connection_never_connect(tmp_path):
    def forbidden(*args): pytest.fail("Unexpected connection")
    report = helper.run([], "current", "sql", action="restart", allow_host_wide=True, factory=forbidden)
    assert report["reason"] == "explicit_test_connection_required"
    original = tmp_path / "socket"
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(original))
    alias = tmp_path / "alias"; alias.symlink_to(original)
    try:
        report = helper.run([alias], "current", "sql", factory=forbidden)
        assert report["reason"] == "current_host_not_verified"
    finally: sock.close()


@pytest.mark.parametrize("action", ["probe", "verify"])
def test_read_only_actions_never_refresh(tmp_path, action):
    path = tmp_path / "control.sock"
    sock = socket.socket(socket.AF_UNIX); sock.bind(str(path))
    methods = []
    class Fake:
        def __init__(self, *args): pass
        def close(self): pass
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            methods.append(method)
            if method == "thread/loaded/list": return {"data": ["current"]}
            if method == "mcpServerStatus/list": return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            if method == "mcpServer/tool/call":
                return {"content": [{"type": "text", "text": json.dumps({"success": True, "data": [{"codex_mcp_restart_canary": 1}]})}]}
            assert method == "initialize"
            return {}
    try:
        report = helper.run([path], "current", "sql", action=action, connection="test", factory=Fake)
        assert not report["reload_attempted"] and "config/mcpServer/reload" not in methods
        assert report["status"] == ("binding_verified" if action == "probe" else "connection_verified")
    finally: sock.close()


def test_incomplete_thread_inventory_never_claims_binding(tmp_path):
    path = tmp_path / "socket"
    sock = socket.socket(socket.AF_UNIX); sock.bind(str(path))
    pages = []
    class Fake:
        def __init__(self, *args): pass
        def close(self): pass
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            if method == "initialize": return {}
            assert method == "thread/loaded/list"
            pages.append(params)
            return {"data": ["current"], "nextCursor": "never_finished"}
    try:
        report = helper.run([path], "current", "sql", factory=Fake)
        assert len(pages) == 8 and not report["binding_verified"]
        assert not report["reload_attempted"]
    finally: sock.close()


@pytest.mark.parametrize("case", ["ok", "binding_fails", "stop_fails", "not_replaced", "thread_changed"])
def test_process_restart_never_refreshes_before_verified_stop(tmp_path, case):
    path = tmp_path / "control.sock"
    sock = socket.socket(socket.AF_UNIX); sock.bind(str(path))
    events = []
    class Fake:
        def __init__(self, *args): self.lists = 0
        def close(self): events.append("client_close")
        def send(self, message): pass
        def call(self, method, params, *, timeout=None):
            events.append(method)
            if method == "thread/loaded/list":
                self.lists += 1
                return {"data": ["current", "new"] if case == "thread_changed" and self.lists > 1 else ["current"]}
            if method == "mcpServerStatus/list": return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            if method == "mcpServer/tool/call":
                return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1}]},
                        "_meta": {"server_pid": 10}}
            assert method in {"initialize", "config/mcpServer/reload"}
            return {}
    class Guard:
        def __init__(self, client, server):
            events.append("process_bound")
            if case == "binding_fails": raise helper.ControlError("target_process_not_unique")
        def stop(self):
            events.append("process_stop")
            if case == "stop_fails": raise helper.ControlError("target_stop_unconfirmed")
        def current_members(self): return [(10, "start")]
        def verify_consumers(self, pids, members): helper.verify_consumer_pids(pids, members)
        def replaced(self): return case != "not_replaced"
        def close(self): events.append("guard_close")
    try:
        report = helper.run([path], "current", "sql", action="restart", connection="test",
                            allow_host_wide=True, factory=Fake, guard_factory=Guard)
        assert report["process_restart_verified"] is (case == "ok")
        assert events.count("config/mcpServer/reload") == (1 if case in {"ok", "not_replaced"} else 0)
        if case in {"ok", "not_replaced"}:
            assert events.index("process_stop") < events.index("config/mcpServer/reload")
        if case == "ok": assert report["status"] == "connection_verified"
        if case == "stop_fails": assert report["status"] == "process_stop_unconfirmed"
        if case == "not_replaced": assert report["reason"] == "process_replacement_not_verified"
    finally: sock.close()


def test_pidfd_stops_only_the_exact_owned_child(tmp_path, monkeypatch):
    if not hasattr(os, "pidfd_open"):
        pytest.skip("Linux pidfd required")
    args = ["-c", "import time; time.sleep(30)"]
    child = subprocess.Popen([sys.executable, *args], cwd=tmp_path)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(31)"], cwd=tmp_path)
    replacement = None
    config = {"sql": {"command": sys.executable, "args": args, "cwd": str(tmp_path)}}
    class Fake:
        path = tmp_path / "unused"
        def call(self, method, params, *, timeout=None):
            assert method == "config/read"
            return {"config": {"mcp_servers": config}}
    monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
    guard = None
    try:
        guard = helper.ProcessGuard(Fake(), "sql")
        assert guard.pid == child.pid
        guard.verify_consumers([child.pid], guard.current_members())
        guard.stop(); child.wait(timeout=2)
        assert unrelated.poll() is None
        replacement = subprocess.Popen([sys.executable, *args], cwd=tmp_path)
        assert guard.replaced()
    finally:
        if guard is not None: guard.close()
        for owned in (child, unrelated, replacement):
            if owned is not None:
                owned.terminate(); owned.wait(timeout=2)
