"""Review regressions using synthetic endpoints and the existing fake config Host."""

import errno
import json
import sys
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_binding import helper, rig  # noqa: F401
from tests.test_codex_mcp_readiness import fake_time
from tests.test_codex_mcp_recreate import host  # noqa: F401
from tests.test_codex_mcp_restart import helper as recreate_helper

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix helper")

# The host fixture blocks Client construction. Keep only the real RPC method so
# budget tests exercise its send/receive deadlines without opening a connection.
CLIENT_CALL = recreate_helper.Client.call


@pytest.mark.parametrize("catalog_failure", ["timeout", "missing"])
@pytest.mark.parametrize("failed_first", [False, True])
def test_duplicate_loaded_thread_remains_ambiguous_after_catalog_failure(
        helper, rig, catalog_failure, failed_first):
    failed = rig.Endpoint("failed")
    healthy = rig.Endpoint("healthy")
    if catalog_failure == "timeout":
        failed.failures["mcpServerStatus/list"] = helper.ControlError("rpc_timeout")
    else:
        failed.servers = []
    endpoints = [failed, healthy] if failed_first else [healthy, failed]

    report = helper.run([endpoint.path for endpoint in endpoints], "current-secret", "sql",
                        factory=rig.factory)

    assert report.get("reason") == "ambiguous_host_binding"
    assert not report["binding_verified"] and not report["reload_attempted"]
    assert not report["process_stop_attempted"]
    for endpoint in endpoints:
        assert endpoint.closed == 1
        assert "thread/loaded/list" in endpoint.methods()
        assert set(endpoint.methods()) <= {"initialize", "thread/loaded/list", "mcpServerStatus/list"}


@pytest.mark.parametrize("enabled", [None, True])
def test_third_journal_fsync_failure_still_restores_confirmed_version_once(
        host, monkeypatch, enabled):
    host.configure(enabled)
    phases = []

    def fsync(_fd):
        phases.append(json.loads(host.journal.read_text())["phase"])
        if len(phases) == 3:
            assert phases[-1] == "restore_config"
            raise OSError(errno.ENOSPC, "synthetic recovery-journal failure")

    monkeypatch.setattr(recreate_helper.os, "fsync", fsync)
    report = host.run()

    assert phases[:3] == ["disable_config", "disable_refresh", "restore_config"]
    assert report["reason"] == "local_operation_failed"
    assert report["phase"] == "restore_config" and report["manual_recovery_required"]
    assert report["restore_write_attempted"] and report["config_restored"]
    assert report["config_bytes_restored"] and host.config.read_bytes() == host.original_bytes
    assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
    assert [write["edits"][0]["value"] for write in host.writes] == [False, enabled]
    assert host.refreshes == report["refresh_attempts"] == report["refreshes_accepted"] == 1
    assert "mcpServer/tool/call" not in host.methods()
    assert host.closed == 1
    assert json.loads(host.journal.read_text())["config_restored"] is True


@pytest.mark.parametrize("rpc_timeout", [2, 10])
@pytest.mark.parametrize("lost_restore_response", [False, True])
def test_work_timeout_reserves_one_restore_inside_original_total_deadline(
        host, monkeypatch, rpc_timeout, lost_restore_response):
    clock = fake_time(monkeypatch)
    raw_call = host.call
    raw_restore = recreate_helper.ConfigToggle.restore
    restore_attempts = []

    def restore(toggle):
        restore_attempts.append(toggle.disabled_version)
        return raw_restore(toggle)

    monkeypatch.setattr(recreate_helper.ConfigToggle, "restore", restore)
    sent = []
    waits = []
    journal_syncs = []
    wire = SimpleNamespace(timeout=rpc_timeout, deadline=60, serial=0, send=sent.append)

    def fsync(_fd):
        phase = json.loads(host.journal.read_text())["phase"]
        journal_syncs.append(phase)
        if len(journal_syncs) == 2:
            assert phase == "disable_refresh" and len(host.writes) == 1
            # Spend local work time after acknowledged disable. No individual
            # fake RPC exceeds its receive allowance; the next read has 1s left.
            clock[0] = 60 - rpc_timeout - 1

    def recv(*, timeout):
        request = sent[-1]
        method, params = request["method"], request["params"]
        if method == "mcpServerStatus/list" and host.refreshes == 1:
            waits.append(("disabled_catalog", timeout))
            clock[0] += timeout
            raise TimeoutError
        restoring = method == "config/batchWrite" and params["edits"][0]["value"] is not False
        if restoring:
            waits.append(("restore", timeout))
            clock[0] += timeout
        result = raw_call(method, params)
        if restoring and lost_restore_response:
            # The edit executed, but its acknowledgement was lost. Retrying is
            # unsafe even though this fake lets us inspect the resulting file.
            raise TimeoutError
        return json.dumps({"id": request["id"], "result": result})

    wire.connection = SimpleNamespace(recv=recv)

    def call(method, params, *, timeout=None):
        wire.deadline = host.deadline
        try:
            return CLIENT_CALL(wire, method, params, timeout=timeout)
        finally:
            host.last_rpc = dict(wire.last_rpc)

    monkeypatch.setattr(recreate_helper.os, "fsync", fsync)
    monkeypatch.setattr(host, "call", call)
    report = host.run(timeout=rpc_timeout)

    assert restore_attempts == ["v1"]
    assert waits == [("disabled_catalog", 1), ("restore", rpc_timeout)]
    assert clock[0] == 60 and wire.deadline <= 60 and host.deadline <= 60
    assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
    assert [write["edits"][0]["value"] for write in host.writes] == [False, None]
    assert host.config.read_bytes() == host.original_bytes
    assert report["reason"] == "rpc_timeout" and report["manual_recovery_required"]
    assert report["restore_write_attempted"]
    assert report["config_restored"] is (not lost_restore_response)
    assert report["refresh_attempts"] == host.refreshes == 1
    assert [request["method"] for request in sent].count("mcpServerStatus/list") == 1
    assert [request["method"] for request in sent].count("config/batchWrite") == 2
    assert "mcpServer/tool/call" not in host.methods()
    assert host.closed == 1
    if lost_restore_response:
        assert report["config_restore_error"] == "manual_config_reconciliation_required"


@pytest.mark.parametrize("other_status", ["idle", "active"])
def test_refresh_rejects_other_loaded_chat_before_canary_or_reload(helper, rig, other_status):
    endpoint = rig.Endpoint("shared", threads=["current-secret", "other-secret"])
    raw_call = endpoint.call

    def call(method, params, **kwargs):
        if method == "thread/read":
            endpoint.calls.append((method, params))
            return {"thread": {"status": {"type": other_status}}}
        return raw_call(method, params, **kwargs)

    endpoint.call = call
    endpoint.failures["mcpServer/tool/call"] = helper.ControlError("unexpected_canary")
    endpoint.failures["config/mcpServer/reload"] = helper.ControlError("unexpected_reload")
    report = helper.run([endpoint.path], "current-secret", "sql", action="refresh",
                        allow_host_wide=True, connection="test", factory=rig.factory)

    assert report["reason"] == "single_loaded_thread_required_for_refresh"
    assert not report["reload_attempted"] and not report["process_stop_attempted"]
    assert not report.get("read_probe_before_verified", False)
    assert "mcpServer/tool/call" not in endpoint.methods()
    assert "config/mcpServer/reload" not in endpoint.methods()
    assert endpoint.closed == 1


@pytest.mark.parametrize("drift", ["added", "replaced"])
def test_refresh_rechecks_loaded_set_after_canary_before_sending_reload(helper, rig, drift):
    endpoint = rig.Endpoint("changed")
    raw_call = endpoint.call

    def call(method, params, **kwargs):
        result = raw_call(method, params, **kwargs)
        if method == "mcpServer/tool/call":
            endpoint.threads = (["current-secret", "other-secret"] if drift == "added"
                                else ["other-secret"])
        return result

    endpoint.call = call
    endpoint.failures["config/mcpServer/reload"] = helper.ControlError("unexpected_reload")
    report = helper.run([endpoint.path], "current-secret", "sql", action="refresh",
                        allow_host_wide=True, connection="test", factory=rig.factory)

    assert report["reason"] == "loaded_threads_changed"
    assert report["read_probe_before_verified"]
    assert endpoint.methods().count("mcpServer/tool/call") == 1
    assert endpoint.methods().count("thread/loaded/list") >= 2
    assert "config/mcpServer/reload" not in endpoint.methods()
    assert not report["reload_attempted"] and not report["process_stop_attempted"]
    assert endpoint.closed == 1
