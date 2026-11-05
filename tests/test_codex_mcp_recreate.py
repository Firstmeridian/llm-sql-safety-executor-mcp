"""Reconstruction uses owned config and fake Host RPC, never a live service."""

import copy
import json
import os
from pathlib import Path
import socket
import sys
import tomllib
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_restart import helper

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix helper")


def test_owned_children_excludes_foreign_processes_before_identity_read(monkeypatch):
    foreign = SimpleNamespace(name="7", stat=lambda: SimpleNamespace(st_uid=os.getuid() + 1))
    own = SimpleNamespace(name="8", stat=lambda: SimpleNamespace(st_uid=os.getuid()))
    observed = []
    monkeypatch.setattr(helper.Path, "iterdir", lambda self: iter([foreign, own]))
    def state(pid):
        observed.append(pid)
        assert pid == 8
        return 100, "start"
    monkeypatch.setattr(helper, "process_state", state)
    assert helper.owned_children(100) == {(8, "start")}
    assert observed == [8]


@pytest.fixture
def host(tmp_path, monkeypatch):
    class Host:
        def __init__(self):
            self.path = tmp_path / "control.sock"
            self.config = tmp_path / "config.toml"
            self.journal = tmp_path / "recovery.json"
            self.original = None
            self.version = "v0"
            self.origin = "user"
            self.threads = ["current"]
            self.calls = []
            self.writes = []
            self.refreshes = 0
            self.closed = 0
            self.deadline = float("inf")
            self.failure = None
            self.old_service = "absent"
            self.baseline = {(10, "old")}
            self.identities = {(20, "new")}
            self.configure(None)

        def configure(self, enabled):
            self.original = enabled
            flag = "" if enabled is None else f"enabled = {str(enabled).lower()}\n"
            self.original_bytes = (
                '# Preserve unrelated settings and comments.\nmodel = "test"\n'
                '[mcp_servers.sql]\ncommand = "/fake/sql"\n'
                f'args = ["--stdio"]\ncwd = {json.dumps(str(tmp_path))}\n{flag}'
            ).encode()
            self.config.write_bytes(self.original_bytes)

        def factory(self, path, timeout):
            assert path == self.path
            return self

        def send(self, message):
            assert message == {"method": "initialized"}

        def close(self):
            self.closed += 1

        def call(self, method, params, *, timeout=None):
            if timeout is not None:
                assert 0 < timeout <= 30
            self.calls.append((method, copy.deepcopy(params)))
            if method == "initialize":
                return {}
            if method == "thread/loaded/list":
                return {"data": list(self.threads)}
            if method == "thread/read":
                assert params == {"threadId": params["threadId"], "includeTurns": False}
                assert params["threadId"] in self.threads
                return {"thread": {"cwd": str(Path.cwd()), "status": {"type": "idle"}}}
            if method == "config/read":
                assert set(params) == {"cwd", "includeLayers"}
                assert params["cwd"] == str(Path.cwd())
                assert type(params["includeLayers"]) is bool
                config = tomllib.loads(self.config.read_text())
                return {"config": config, "origins": {
                    "mcp_servers.sql.command": {
                        "name": {"type": self.origin, "file": str(self.config)},
                        "version": self.version,
                    }}}
            if method == "config/batchWrite":
                self.writes.append(copy.deepcopy(params))
                assert params["filePath"] == str(self.config)
                assert params["reloadUserConfig"] is False
                assert params["edits"] == [{
                    "keyPath": "mcp_servers.sql.enabled",
                    "value": params["edits"][0]["value"], "mergeStrategy": "replace",
                }]
                if params["expectedVersion"] != self.version:
                    raise helper.ControlError("config_version_conflict")
                value = params["edits"][0]["value"]
                if value is False:
                    original_lines = self.original_bytes.decode().splitlines(keepends=True)
                    self.config.write_text("".join(
                        line for line in original_lines if not line.startswith("enabled =")
                    ) + "enabled = false\n")
                else:
                    assert value is self.original
                    self.config.write_bytes(self.original_bytes)
                self.version = f"v{len(self.writes)}"
                return {"status": "ok", "version": self.version}
            if method == "config/mcpServer/reload":
                assert params is None
                self.refreshes += 1
                if self.failure == f"refresh_{self.refreshes}":
                    raise helper.ControlError("rpc_timeout")
                if self.failure == "restore_conflict" and self.refreshes == 1:
                    self.config.write_bytes(self.config.read_bytes() + b'# concurrent edit\n')
                    self.version = "concurrent"
                return {}
            if method == "mcpServerStatus/list":
                assert params == {"threadId": params["threadId"], "serverName": "sql",
                                  "detail": "toolsAndAuthOnly", "limit": 100}
                assert params["threadId"] in self.threads
                if not self.refreshes:
                    # Neither old catalog availability nor a working old canary
                    # is a prerequisite for reconstruction.
                    pytest.fail("Old service catalog must not be queried")
                if self.refreshes == 1:
                    if self.failure == "barrier":
                        return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
                    return {"data": [{"name": "sql", "runtimeStatus": "disabled", "tools": {}}]}
                return {"data": [{"name": "sql", "runtimeStatus": "connected", "tools": {"query": {}}}]}
            if method == "mcpServer/tool/call":
                assert params == {"threadId": params["threadId"], "server": "sql", "tool": "query",
                                  "arguments": {"connection_id": "test",
                                                "sql": "SELECT 1 AS codex_mcp_restart_canary"}}
                if not self.refreshes:
                    if self.old_service == "error":
                        return {"isError": True}
                    pytest.fail("Absent old service must not be called")
                assert self.refreshes == 2
                if self.failure == "postread":
                    return {"isError": True}
                pid = sorted(self.identities)[self.threads.index(params["threadId"])][0]
                return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1}]},
                        "_meta": {"server_pid": pid}}
            pytest.fail(f"Unexpected RPC: {method}")

        def run(self, **kwargs):
            options = dict(allow_host_wide=True, allow_config_toggle=True,
                           connection="test", state_file=self.journal, factory=self.factory)
            options.update(kwargs)
            report = helper.run_recreate([self.path], "current", "sql", **options)
            assert report["process_signals_sent"] == 0
            assert report["previous_target_exit_verified"] is False
            assert report["model_tool_visibility"] == "unverified"
            return report

        def methods(self):
            return [method for method, _ in self.calls]

    fake = Host()
    monkeypatch.setattr(helper, "socket_owner", lambda path: 100)
    monkeypatch.setattr(helper, "process_state", lambda pid: (1, "host-start") if pid == 100 else pytest.fail("Unexpected PID"))
    monkeypatch.setattr(helper, "owned_children", lambda pid: set(fake.baseline) if pid == 100 else pytest.fail("Unexpected parent"))

    def matching(pid, command, args, cwd):
        assert (pid, command, args, cwd) == (100, "/fake/sql", ["--stdio"], str(tmp_path))
        return list(fake.identities)

    monkeypatch.setattr(helper, "find_matching_children", matching)
    # Even regressions must never send a signal or open a real Host connection.
    monkeypatch.setattr(helper.signal, "pidfd_send_signal", lambda *args: pytest.fail("Unexpected signal"))
    monkeypatch.setattr(helper, "Client", lambda *args: pytest.fail("Unexpected real Host connection"))
    with socket.socket(socket.AF_UNIX) as control:
        control.bind(str(fake.path))
        yield fake


@pytest.mark.parametrize("enabled", [None, True])
def test_config_toggle_round_trip_preserves_original_flag_and_bytes(host, enabled):
    host.configure(enabled)
    toggle = helper.ConfigToggle(host, "sql")
    assert toggle.original is enabled
    assert toggle.version == "v0"
    toggle.disable()
    assert tomllib.loads(host.config.read_text())["mcp_servers"]["sql"]["enabled"] is False
    assert toggle.disabled_version == "v1"
    assert toggle.restore() is True
    assert toggle.restored and host.config.read_bytes() == host.original_bytes
    assert [write["expectedVersion"] for write in host.writes] == ["v0", "v1"]
    assert [write["edits"][0]["value"] for write in host.writes] == [False, enabled]
    assert host.refreshes == 0


@pytest.mark.parametrize("multiple,enabled,old_service", [(False, None, "absent"), (True, True, "error")])
def test_recreate_verifies_default_and_explicit_multi_scope(host, multiple, enabled, old_service):
    host.configure(enabled)
    host.old_service = old_service
    if multiple:
        host.threads.append("other")
        host.identities.add((21, "also-new"))
    report = host.run(all_loaded_targets=multiple)
    assert report["status"] == "connection_verified"
    assert report["phase"] == "complete"
    assert "reason" not in report
    assert report["process_restart_verified"] and report["read_probe_verified"]
    assert report["preexisting_child_processes"] == sorted(host.baseline)
    assert report["consumer_verification_step"] == "process_identity"
    assert report["read_probe_verified_thread_count"] == len(host.threads)
    assert report["target_disabled_verified"] and report["config_restored"]
    assert report["config_bytes_restored"] and host.config.read_bytes() == host.original_bytes
    assert report["refresh_attempts"] == report["refreshes_accepted"] == host.refreshes == 2
    assert len(host.writes) == 2 and host.closed == 1
    assert json.loads(host.journal.read_text()) == json.loads(json.dumps(report))
    events = [method for method in host.methods() if method in {
        "config/batchWrite", "config/mcpServer/reload", "mcpServerStatus/list", "mcpServer/tool/call"}]
    assert events[:2] == ["config/batchWrite", "config/mcpServer/reload"]
    assert events[2:2 + len(host.threads)] == ["mcpServerStatus/list"] * len(host.threads)
    assert events[2 + len(host.threads):4 + len(host.threads)] == ["config/batchWrite", "config/mcpServer/reload"]
    assert [params["threadId"] for method, params in host.calls if method == "mcpServer/tool/call"] == sorted(host.threads)


def test_recreate_dry_run_never_writes_refreshes_or_queries(host):
    report = host.run(dry_run=True, allow_host_wide=False, allow_config_toggle=False)
    assert report["status"] == "recreate_plan_verified" and report["binding_verified"]
    assert not report["read_probe_verified"] and not report["process_restart_verified"]
    assert host.config.read_bytes() == host.original_bytes
    assert not host.writes and host.refreshes == 0 and not host.journal.exists()
    assert "mcpServer/tool/call" not in host.methods()
    assert "preexisting_child_processes" not in report


@pytest.mark.parametrize("options,reason", [
    ({"allow_config_toggle": False}, "host_wide_and_config_toggle_consent_required"),
    ({"state_file": None}, "recovery_journal_required"),
])
def test_recreate_requires_consent_and_journal_before_connecting(host, options, reason):
    report = host.run(**options)
    assert report["reason"] == reason
    assert not host.calls and not host.writes and host.refreshes == 0
    assert not host.journal.exists() and host.config.read_bytes() == host.original_bytes


@pytest.mark.parametrize("case,reason", [
    ("disabled", "target_initially_disabled_or_invalid"),
    ("overridden", "user_config_origin_required"),
])
def test_recreate_rejects_disabled_or_overridden_config_before_writes(host, case, reason):
    if case == "disabled":
        host.configure(False)
    else:
        host.origin = "project"
    report = host.run()
    assert report["reason"] == reason
    assert not host.writes and host.refreshes == 0 and not host.journal.exists()
    assert host.config.read_bytes() == host.original_bytes and host.closed == 1


def test_recreate_existing_journal_is_never_overwritten(host):
    host.journal.write_text("existing recovery evidence\n")
    report = host.run()
    assert report["reason"] == "local_operation_failed"
    assert not report["disable_write_attempted"]
    assert host.journal.read_text() == "existing recovery evidence\n"
    assert not host.writes and host.refreshes == 0
    assert host.config.read_bytes() == host.original_bytes


def test_recreate_disabled_barrier_failure_restores_disk_once_without_refresh(host, monkeypatch):
    # Exercise the actual disabled-state timeout without waiting ten seconds.
    clock = [0.0]

    def advance(_seconds):
        clock[0] += 11

    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=advance))
    host.failure = "barrier"
    report = host.run()
    assert report["reason"] == "target_disabled_not_verified"
    assert report["phase"] == "disabled_barrier" and not report["target_disabled_verified"]
    assert report["config_restored"] and report["config_bytes_restored"]
    assert report["manual_recovery_required"]
    assert host.config.read_bytes() == host.original_bytes
    assert len(host.writes) == 2 and host.refreshes == report["refresh_attempts"] == 1
    assert "mcpServer/tool/call" not in host.methods()


@pytest.mark.parametrize("lost_refresh", [1, 2])
def test_recreate_lost_refresh_response_is_never_retried(host, lost_refresh):
    host.failure = f"refresh_{lost_refresh}"
    report = host.run()
    assert report["reason"] == "rpc_timeout"
    assert report["refresh_attempts"] == host.refreshes == lost_refresh
    assert report["refreshes_accepted"] == lost_refresh - 1
    assert report["phase"] == ("disable_refresh" if lost_refresh == 1 else "restore_refresh")
    assert report["manual_recovery_required"] and report["config_restored"]
    assert not report["read_probe_verified"] and not report["process_restart_verified"]
    assert len(host.writes) == 2 and host.config.read_bytes() == host.original_bytes
    assert "mcpServer/tool/call" not in host.methods()
    saved = json.loads(host.journal.read_text())
    assert saved["refresh_attempts"] == lost_refresh and saved["manual_recovery_required"]


def test_recreate_restore_version_conflict_preserves_concurrent_config(host):
    host.failure = "restore_conflict"
    report = host.run()
    assert report["reason"] == "config_version_conflict"
    assert report["restore_write_attempted"] and report["manual_recovery_required"]
    assert not report["config_restored"] and not report["process_restart_verified"]
    assert len(host.writes) == 2 and host.writes[-1]["expectedVersion"] == "v1"
    assert host.refreshes == 1 and host.version == "concurrent"
    assert host.config.read_bytes().endswith(b"enabled = false\n# concurrent edit\n")
    assert "mcpServer/tool/call" not in host.methods()


def test_recreate_postread_failure_does_not_claim_verification(host):
    host.failure = "postread"
    report = host.run()
    assert report["reason"] == "canary_tool_error"
    assert report["config_restored"] and report["target_disabled_verified"]
    assert not report["read_probe_verified"] and not report["process_restart_verified"]
    assert report["status"] == "unverified" and report["manual_recovery_required"]
    assert host.refreshes == 2 and len(host.writes) == 2
    assert host.config.read_bytes() == host.original_bytes


def test_recreate_baseline_child_cannot_be_claimed_as_fresh(host):
    host.identities = set(host.baseline)
    report = host.run()
    assert report["reason"] == "fresh_consumer_process_not_verified"
    assert not report["process_restart_verified"] and not report["read_probe_verified"]
    assert report["config_restored"] and report["manual_recovery_required"]
    assert host.refreshes == 2 and len(host.writes) == 2
