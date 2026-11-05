"""Recreate scope boundaries use the existing fake Host and in-memory RPCs."""

import copy
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_recreate import host  # noqa: F401
from tests.test_codex_mcp_review_boundaries import CLIENT_CALL
from tests.test_codex_mcp_restart import helper

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix helper")


@pytest.fixture(autouse=True)
def memory_host_only(tmp_path, monkeypatch):
    """Adapt the fake Host's socket scaffold without binding an OS socket."""
    bound = set()

    def forbid(*args, **kwargs):
        pytest.fail("Real Host, discovery or process signal operation forbidden")

    class MemorySocket:
        def __init__(self, family):
            assert family == socket.AF_UNIX

        def bind(self, path):
            assert Path(path) == tmp_path / "control.sock"
            bound.add(Path(path))

        connect = forbid

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def owned_socket(path):
        assert Path(path) in bound

    import websockets.sync.client

    monkeypatch.setattr(socket, "socket", MemorySocket)
    monkeypatch.setattr(helper, "owned_socket", owned_socket)
    monkeypatch.setattr(websockets.sync.client, "unix_connect", forbid)
    monkeypatch.setattr(helper, "discover_sockets", forbid)
    monkeypatch.setattr(helper.os, "kill", forbid)
    monkeypatch.setattr(helper.os, "pidfd_open", forbid)
    monkeypatch.setattr(helper.signal, "pidfd_send_signal", forbid)
    monkeypatch.setattr(helper.signal, "raise_signal", forbid)
    monkeypatch.setattr(helper.signal, "pthread_kill", forbid)


@pytest.fixture
def rpc(host, monkeypatch):
    """Exercise real Client.call bookkeeping with fake sends and responses."""
    raw_call, raw_fsync = host.call, helper.os.fsync
    trace = SimpleNamespace(sent=[], snapshots=[], syncs=[],
                            after_rpc=lambda method, params: None,
                            after_fsync=lambda saved: None)
    wire = SimpleNamespace(timeout=10, deadline=host.deadline, serial=0)

    def send(request):
        trace.sent.append(copy.deepcopy(request))
        trace.snapshots.append({
            "method": request["method"], "threads": list(host.threads),
            "journal": json.loads(host.journal.read_text()) if host.journal.exists() else None,
        })

    def recv(*, timeout):
        request = trace.sent[-1]
        result = raw_call(request["method"], request["params"])
        trace.after_rpc(request["method"], request["params"])
        return json.dumps({"id": request["id"], "result": result})

    def call(method, params, *, timeout=None):
        wire.deadline = host.deadline
        try:
            return CLIENT_CALL(wire, method, params, timeout=timeout)
        finally:
            host.last_rpc = dict(wire.last_rpc)

    def fsync(fd):
        saved = json.loads(host.journal.read_text())
        trace.syncs.append(saved)
        raw_fsync(fd)
        trace.after_fsync(saved)

    wire.send = send
    wire.connection = SimpleNamespace(recv=recv)
    monkeypatch.setattr(host, "call", call)
    monkeypatch.setattr(helper.os, "fsync", fsync)
    return trace


def effects(rpc):
    return [request["method"] for request in rpc.sent if request["method"] in {
        "config/batchWrite", "config/mcpServer/reload",
        "mcpServerStatus/list", "mcpServer/tool/call",
    }]


POINTS = [
    "control", "initial_scope", "toggle_config_read", "preflight_config_read",
    "persist_disable_config", "disable_rpc", "persist_disable_refresh",
    "persist_restore_config", "restore_rpc", "persist_restore_refresh",
]


@pytest.mark.parametrize("group", [False, True], ids=["single", "group"])
@pytest.mark.parametrize("point", POINTS)
def test_recreate_rechecks_scope_at_each_effect_boundary(host, rpc, point, group):
    host.configure(True if group else None)
    if group:
        host.threads.append("other")
        host.identities.add((21, "also-new"))
    initial_threads = list(host.threads)
    injections = []

    def inject(where):
        if point == where and not injections:
            injections.append(len(rpc.sent))
            host.threads.append("late-chat")

    def after_rpc(method, params):
        if method == "thread/loaded/list" and len(rpc.sent) == 2:
            inject("initial_scope")
        if method == "config/read":
            inject("toggle_config_read" if params["includeLayers"] else "preflight_config_read")
        if method == "config/batchWrite":
            inject("disable_rpc" if params["edits"][0]["value"] is False else "restore_rpc")

    rpc.after_rpc = after_rpc
    rpc.after_fsync = lambda saved: inject("persist_" + saved["phase"])
    report = host.run(all_loaded_targets=group)

    assert host.config.read_bytes() == host.original_bytes
    assert host.closed == 1
    assert report["previous_target_exit_verified"] is False
    assert report["process_signals_sent"] == 0
    assert report["refresh_attempts"] == report["refreshes_accepted"] == host.refreshes
    assert host.refreshes == effects(rpc).count("config/mcpServer/reload")
    if host.journal.exists():
        assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))

    prefix = ["config/batchWrite", "config/mcpServer/reload"]
    barrier = ["mcpServerStatus/list"] * len(initial_threads)
    if point == "control":
        assert not injections and report["status"] == "connection_verified"
        assert report["process_restart_verified"] and report["read_probe_verified"]
        assert report["read_probe_verified_thread_count"] == len(initial_threads)
        assert effects(rpc) == prefix + barrier + prefix + [
            method for _ in initial_threads for method in ["mcpServerStatus/list", "mcpServer/tool/call"]
        ]
        assert report["refresh_attempts"] == 2
        # Each send retains durable intent before the effect can be uncertain.
        reloads = [s for s in rpc.snapshots if s["method"] == "config/mcpServer/reload"]
        for index, snapshot in enumerate(reloads, 1):
            assert snapshot["journal"]["refresh_attempts"] == index
        disable = next(s for s in rpc.snapshots if s["method"] == "config/batchWrite")
        assert disable["journal"]["disable_write_attempted"]
    else:
        assert len(injections) == 1
        assert report["reason"] == "loaded_threads_changed"
        assert report["status"] == "unverified"
        assert not report["process_restart_verified"] and not report["read_probe_verified"]
        assert "mcpServer/tool/call" not in effects(rpc)
        later = rpc.sent[injections[0]:]
        assert "config/mcpServer/reload" not in [r["method"] for r in later]
        if point in {"initial_scope", "toggle_config_read", "preflight_config_read", "persist_disable_config"}:
            assert effects(rpc) == []
            assert not report["disable_write_attempted"]
            assert not report["restore_write_attempted"]
            assert not report["manual_recovery_required"]
            assert not report["config_restored"]
            assert host.refreshes == 0
            assert host.journal.exists() is (point != "initial_scope")
            if rpc.syncs:
                assert rpc.syncs[0]["disable_write_attempted"]
                assert not rpc.syncs[-1]["disable_write_attempted"]
            return
        expected = ["config/batchWrite"] if point in {"disable_rpc", "persist_disable_refresh"} else prefix + barrier
        assert effects(rpc) == expected + ["config/batchWrite"]
        assert report["manual_recovery_required"]
        assert report["last_rpc"]["method"] == "thread/loaded/list"
        # Durable intent remains conservative until the guard refuses the send.
        assert rpc.syncs[-2]["refresh_attempts"] == host.refreshes + 1
        assert rpc.syncs[-1]["refresh_attempts"] == host.refreshes

    assert len(host.writes) == 2
    assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
    assert [write["edits"][0]["value"] for write in host.writes] == [False, host.original]
    assert report["restore_write_attempted"] and report["config_restored"]
    assert report["config_bytes_restored"]


@pytest.mark.parametrize("phase", ["preflight", "disable_config", "disable_refresh", "disabled_barrier", "restore_refresh"])
@pytest.mark.parametrize("change", ["add", "remove"])
def test_group_metadata_read_cannot_hide_loaded_set_change(host, rpc, phase, change):
    host.threads.append("other")
    host.identities.add((21, "also-new"))
    injections = []

    def after_rpc(method, params):
        if method != "thread/read" or params["threadId"] != "other" or injections:
            return
        current_phase = json.loads(host.journal.read_text())["phase"] if host.journal.exists() else "preflight"
        if current_phase == "disable_refresh" and host.refreshes == 1:
            current_phase = "disabled_barrier"
        if current_phase == phase:
            injections.append(len(rpc.sent))
            if change == "add":
                host.threads.append("late-chat")
            else:
                host.threads.remove("other")

    rpc.after_rpc = after_rpc
    report = host.run(all_loaded_targets=True)

    assert len(injections) == 1
    assert report["reason"] == "loaded_threads_changed"
    assert report["status"] == "unverified"
    assert not report["process_restart_verified"] and not report["read_probe_verified"]
    later = rpc.sent[injections[0]:]
    assert later[0]["method"] == "thread/loaded/list"
    assert "config/mcpServer/reload" not in [r["method"] for r in later]
    assert "mcpServer/tool/call" not in effects(rpc)
    assert report["refresh_attempts"] == report["refreshes_accepted"] == host.refreshes
    assert host.config.read_bytes() == host.original_bytes and host.closed == 1
    expected = []
    if phase not in {"preflight", "disable_config"}:
        expected = ["config/batchWrite"]
        if phase != "disable_refresh":
            expected += ["config/mcpServer/reload"] + ["mcpServerStatus/list"] * 2
        expected += ["config/batchWrite"]
    assert effects(rpc) == expected
    if phase == "preflight":
        assert not host.writes and host.refreshes == 0 and not host.journal.exists()
        assert not report["manual_recovery_required"]
    elif phase == "disable_config":
        assert not host.writes and host.refreshes == 0
        assert not report["disable_write_attempted"] and not report["manual_recovery_required"]
    else:
        assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
        assert [write["edits"][0]["value"] for write in host.writes] == [False, host.original]
        assert report["config_restored"] and report["config_bytes_restored"]
        assert report["manual_recovery_required"]
        assert host.refreshes == (0 if phase == "disable_refresh" else 1)
    if host.journal.exists():
        assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))


@pytest.mark.parametrize("failure", ["version_conflict", "lost_response"])
def test_scope_refusal_never_retries_uncertain_exact_version_restore(host, rpc, failure):
    def after_rpc(method, params):
        if method != "config/batchWrite":
            return
        if params["edits"][0]["value"] is False:
            host.threads.append("late-chat")
            if failure == "version_conflict":
                host.config.write_bytes(host.config.read_bytes() + b"# concurrent edit\n")
                host.version = "concurrent"
        elif failure == "lost_response":
            # The fake Host restored the bytes, but the helper has no ack.
            raise TimeoutError

    rpc.after_rpc = after_rpc
    report = host.run()

    assert effects(rpc) == ["config/batchWrite", "config/batchWrite"]
    assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
    assert [write["edits"][0]["value"] for write in host.writes] == [False, host.original]
    assert report["reason"] == "loaded_threads_changed" and report["status"] == "unverified"
    assert report["restore_write_attempted"] and report["manual_recovery_required"]
    assert report["config_restore_error"] == "manual_config_reconciliation_required"
    assert not report["config_restored"]
    assert not report["process_restart_verified"] and not report["read_probe_verified"]
    assert report["refresh_attempts"] == report["refreshes_accepted"] == host.refreshes == 0
    assert host.closed == 1
    if failure == "version_conflict":
        assert host.version == "concurrent"
        assert host.config.read_bytes().endswith(b"enabled = false\n# concurrent edit\n")
    else:
        assert host.config.read_bytes() == host.original_bytes
    assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))
