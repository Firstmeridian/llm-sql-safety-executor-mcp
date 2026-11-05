"""Binding behavior with synthetic endpoints only; never contact a real Host."""

import errno
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix/pidfd helper")


@pytest.fixture
def helper(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "binding_helper", Path(__file__).resolve().parents[1] / "scripts/dev/restart_codex_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected real connection, process operation or config edit")

    import websockets.sync.client
    monkeypatch.setattr(websockets.sync.client, "unix_connect", forbidden)
    monkeypatch.setattr(module.signal, "pidfd_send_signal", forbidden)
    monkeypatch.setattr(module, "socket_owner", forbidden)
    monkeypatch.setattr(module.ConfigToggle, "write", forbidden)
    return module


@pytest.fixture
def rig(helper, monkeypatch):
    endpoints = {}
    opened = []
    # Endpoint validation itself has separate tests below. No OS socket is
    # needed to test candidate selection, RPC order, cleanup or CLI provenance.
    monkeypatch.setattr(helper, "owned_socket", lambda path: None)

    class Endpoint:
        def __init__(self, name, *, threads=None):
            self.path = Path("/synthetic-private") / name
            self.threads = ["current-secret"] if threads is None else threads
            self.calls = []
            self.sent = []
            self.closed = 0
            self.failures = {}
            self.pages = None
            self.servers = [{"name": "sql", "tools": {"query": {"description": "private-tool"}}}]
            self.config_result = None
            endpoints[self.path] = self

        def call(self, method, params, **kwargs):
            self.calls.append((method, params))
            if method in self.failures:
                raise self.failures[method]
            if method == "initialize":
                return {}
            if method == "thread/loaded/list":
                return next(self.pages) if self.pages is not None else {"data": self.threads}
            if method == "mcpServerStatus/list":
                assert params["threadId"] == "current-secret"
                return {"data": self.servers}
            if method == "mcpServer/tool/call":
                assert params["threadId"] == "current-secret"
                assert params["arguments"]["sql"] == "SELECT 1 AS codex_mcp_restart_canary"
                return {"structuredContent": {
                    "success": True, "data": [{"codex_mcp_restart_canary": 1}]}}
            if self.config_result is not None:
                if method == "thread/read":
                    assert params == {"threadId": "current-secret", "includeTurns": False}
                    return {"thread": {"cwd": str(Path.cwd())}}
                if method == "config/read":
                    return self.config_result
            pytest.fail(f"Unexpected RPC: {method}")

        def send(self, message):
            self.sent.append(message)
            assert message == {"method": "initialized"}

        def close(self):
            self.closed += 1

        def methods(self):
            return [method for method, _ in self.calls]

    def factory(path, timeout):
        opened.append((path, timeout))
        endpoint = endpoints[path]
        if isinstance(endpoint, Exception):
            raise endpoint
        return endpoint

    return SimpleNamespace(Endpoint=Endpoint, endpoints=endpoints, factory=factory, opened=opened)


def assert_private(report):
    encoded = json.dumps(report)
    for secret in ("/synthetic-private", "current-secret", "other-secret", "private-tool", "credential-secret"):
        assert secret not in encoded


@pytest.mark.parametrize("action,all_loaded_targets", [
    ("probe", False), ("probe", True), ("refresh", False),
    ("restart", False), ("restart", True), ("recreate", False), ("recreate", True),
])
def test_unloaded_thread_has_no_side_effects(helper, rig, action, all_loaded_targets):
    endpoint = rig.Endpoint("wrong", threads=["other-secret"])
    options = dict(factory=rig.factory, connection="test", allow_host_wide=True,
                   all_loaded_targets=all_loaded_targets)
    if action == "recreate":
        report = helper.run_recreate([endpoint.path], "current-secret", "sql", dry_run=True, **options)
    else:
        report = helper.run([endpoint.path], "current-secret", "sql", action=action, **options)
        assert not report["reload_attempted"] and not report["process_stop_attempted"]
    assert report["reason"] == "current_host_not_verified"
    assert report["binding_verified"] is False
    assert endpoint.methods() == ["initialize", "thread/loaded/list"]
    assert endpoint.closed == 1
    candidate = report["binding_diagnostics"][0]
    assert candidate["phase"] == "thread_binding"
    assert candidate["reason"] == "current_thread_not_loaded"
    assert candidate["current_thread_loaded"] is False and candidate["loaded_thread_count"] == 1
    assert_private(report)


def test_one_failed_candidate_does_not_hide_the_unique_match(helper, rig):
    broken = Path("/synthetic-private/broken")
    rig.endpoints[broken] = helper.ControlError(
        "websocket_connect_failed", cause=ConnectionRefusedError(errno.ECONNREFUSED, "credential-secret"))
    matched = rig.Endpoint("matched")
    report = helper.run([broken, matched.path], "current-secret", "sql", factory=rig.factory,
                        action="verify", connection="test")
    assert report["status"] == "connection_verified" and report["read_probe_verified"]
    failed, success, unique = report["binding_diagnostics"]
    assert failed["phase"] == "connect" and failed["reason"] == "websocket_connect_failed"
    assert failed["exception_type"] == "ConnectionRefusedError" and failed["errno"] == errno.ECONNREFUSED
    assert success["reason"] == "candidate_matched" and success["current_thread_loaded"]
    assert unique["phase"] == "uniqueness" and unique["matched_candidate_count"] == 1
    assert len(rig.opened) == 2 and matched.closed == 1
    assert matched.methods() == ["initialize", "thread/loaded/list", "mcpServerStatus/list", "mcpServer/tool/call"]
    assert_private(report)


@pytest.mark.parametrize("recreate", [False, True])
def test_two_matching_hosts_refuse_before_any_operation(helper, rig, recreate):
    endpoints = [rig.Endpoint("one"), rig.Endpoint("two")]
    paths = [endpoint.path for endpoint in endpoints]
    if recreate:
        report = helper.run_recreate(paths, "current-secret", "sql", factory=rig.factory,
                                     connection="test", dry_run=True)
    else:
        report = helper.run(paths, "current-secret", "sql", factory=rig.factory,
                            action="restart", connection="test", allow_host_wide=True)
    assert report["reason"] == "ambiguous_host_binding" and not report["binding_verified"]
    assert report["binding_diagnostics"][-1]["matched_candidate_count"] == 2
    for endpoint in endpoints:
        assert endpoint.closed == 1
        assert set(endpoint.methods()) <= {"initialize", "thread/loaded/list", "mcpServerStatus/list"}
        assert ("mcpServerStatus/list" in endpoint.methods()) is not recreate
    assert_private(report)


@pytest.mark.parametrize("case,reason", [
    ("missing", "target_server_not_observed"), ("invalid", "invalid_server_catalog"),
    ("no_query", "query_tool_not_observed"), ("rpc", "rpc_error"),
])
def test_catalog_failure_keeps_successful_thread_membership(helper, rig, case, reason):
    endpoint = rig.Endpoint("catalog")
    endpoint.servers = {"missing": [], "invalid": None, "no_query": [{"name": "sql", "tools": {}}]}.get(case)
    if case == "rpc":
        endpoint.failures["mcpServerStatus/list"] = helper.ControlError("rpc_error")
    report = helper.run([endpoint.path], "current-secret", "sql", factory=rig.factory,
                        action="restart", allow_host_wide=True, connection="test")
    assert report["reason"] == "current_host_not_verified" and not report["process_stop_attempted"]
    candidate = report["binding_diagnostics"][0]
    assert candidate["phase"] == "catalog" and candidate["reason"] == reason
    assert candidate["current_thread_loaded"] is True
    assert endpoint.closed == 1 and "mcpServer/tool/call" not in endpoint.methods()
    assert_private(report)


@pytest.fixture
def recreatable(helper, rig, tmp_path, monkeypatch):
    endpoint = rig.Endpoint("recreatable")
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.sql]\ncommand = "/fake/sql"\nargs = []\ncwd = "/fake/workspace"\n')
    endpoint.config_result = {
        "config": {"mcp_servers": {"sql": {"command": "/fake/sql", "args": [], "cwd": "/fake/workspace"}}},
        "origins": {"mcp_servers.sql.command": {
            "name": {"type": "user", "file": str(config)}, "version": "v1"}},
    }
    monkeypatch.setattr(helper, "socket_owner", lambda path: 123)
    monkeypatch.setattr(helper, "process_state", lambda pid: (1, "host-start"))
    monkeypatch.setattr(helper, "owned_children", lambda pid: set())
    return endpoint, config


def test_recreate_dry_run_needs_neither_old_catalog_nor_old_pid(helper, rig, recreatable):
    endpoint, config = recreatable
    original = config.read_bytes()
    endpoint.failures["mcpServerStatus/list"] = helper.ControlError("rpc_error")
    journal = config.parent / "never-created.json"
    report = helper.run_recreate([endpoint.path], "current-secret", "sql", factory=rig.factory,
                                 connection="test", dry_run=True, state_file=journal)
    assert report["status"] == "recreate_plan_verified" and report["binding_verified"]
    assert report["binding_diagnostics"][0]["catalog_checked"] is False
    assert not report["disable_write_attempted"] and report["refresh_attempts"] == report["process_signals_sent"] == 0
    assert "mcpServerStatus/list" not in endpoint.methods() and "mcpServer/tool/call" not in endpoint.methods()
    assert config.read_bytes() == original and not journal.exists() and endpoint.closed == 1


def test_normal_process_failure_retains_binding_diagnostics(helper, rig):
    endpoint = rig.Endpoint("no-process")
    guards = []

    def guard(*args):
        guards.append(True)
        raise helper.ControlError("target_process_not_unique")

    report = helper.run([endpoint.path], "current-secret", "sql", action="restart",
                        factory=rig.factory, guard_factory=guard, allow_host_wide=True, connection="test")
    assert report["binding_verified"] and report["reason"] == "target_process_not_unique"
    assert report["phase"] == "process_binding" and report["binding_diagnostics"][-1]["reason"] == "unique_host_binding"
    assert guards == [True] and endpoint.closed == 1
    assert not report["process_stop_attempted"] and not report["reload_attempted"]


@pytest.mark.parametrize("method,phase,reason", [
    ("initialize", "initialize", "rpc_timeout"),
    ("thread/loaded/list", "thread_list", "rpc_error"),
])
def test_rpc_failures_are_not_reported_as_thread_mismatches(helper, rig, method, phase, reason):
    endpoint = rig.Endpoint("rpc")
    endpoint.failures[method] = helper.ControlError(reason)
    report = helper.run([endpoint.path], "current-secret", "sql", factory=rig.factory)
    candidate = report["binding_diagnostics"][0]
    assert candidate["phase"] == phase and candidate["reason"] == reason
    assert "current_thread_loaded" not in candidate and "loaded_thread_count" not in candidate
    assert endpoint.closed == 1 and report["reason"] == "current_host_not_verified"


@pytest.mark.parametrize("incomplete", [False, True])
def test_thread_inventory_is_complete_and_bounded_before_membership(helper, rig, incomplete):
    endpoint = rig.Endpoint("pages")
    if incomplete:
        endpoint.pages = iter([{"data": ["current-secret"], "nextCursor": "private-cursor"}] * 8)
    else:
        endpoint.pages = iter([{"data": ["other-secret"], "nextCursor": "private-cursor"},
                               {"data": ["current-secret", "other-secret"]}])
    report = helper.run([endpoint.path], "current-secret", "sql", factory=rig.factory)
    assert endpoint.methods().count("thread/loaded/list") == (8 if incomplete else 2)
    candidate = report["binding_diagnostics"][0]
    if incomplete:
        assert candidate["reason"] == "thread_budget_exceeded" and candidate["phase"] == "thread_list"
        assert "current_thread_loaded" not in candidate and not report["binding_verified"]
    else:
        assert report["binding_verified"] and candidate["loaded_thread_count"] == 2
    assert endpoint.closed == 1 and "private-cursor" not in json.dumps(report)
    assert_private(report)


@pytest.mark.parametrize("mode", ["regular", "symlink", "foreign", "permission", "missing"])
def test_endpoint_validation_never_opens_invalid_candidates(helper, monkeypatch, mode):
    def lstat(path):
        if mode == "permission":
            raise PermissionError(errno.EACCES, "credential-secret", "/synthetic-private/socket")
        if mode == "missing":
            raise FileNotFoundError(errno.ENOENT, "credential-secret", "/synthetic-private/socket")
        return SimpleNamespace(st_mode={"regular": stat.S_IFREG, "symlink": stat.S_IFLNK,
                                        "foreign": stat.S_IFSOCK}[mode],
                               st_uid=os.getuid() + (mode == "foreign"))

    monkeypatch.setattr(helper.Path, "lstat", lstat)

    def forbidden(*args):
        pytest.fail("Invalid endpoints must not connect")

    report = helper.run([Path("/synthetic-private/socket")], "current-secret", "sql", factory=forbidden)
    assert report["reason"] == "current_host_not_verified"
    candidate = report["binding_diagnostics"][0]
    assert candidate["phase"] == "endpoint_validation"
    assert candidate["reason"] == ("endpoint_unavailable" if mode in {"permission", "missing"} else "not_owned_control_socket")
    assert_private(report)


@pytest.mark.parametrize("exception,expected", [
    (ConnectionRefusedError(errno.ECONNREFUSED, "credential-secret"), "ConnectionRefusedError"),
    (PermissionError(errno.EACCES, "credential-secret"), "PermissionError"),
    (TimeoutError("credential-secret"), "TimeoutError"),
    (RuntimeError("credential-secret"), None),
])
@pytest.mark.parametrize("enter_fails", [False, True])
def test_client_connect_errors_are_allowlisted_and_enter_failure_is_closed(
        helper, monkeypatch, exception, expected, enter_fails):
    closed = []

    class Context:
        def __enter__(self):
            raise exception

        def __exit__(self, *args):
            closed.append(True)
            raise RuntimeError("credential-secret during cleanup")

    def connect(*args, **kwargs):
        if enter_fails:
            return Context()
        raise exception

    monkeypatch.setattr("websockets.sync.client.unix_connect", connect)
    with pytest.raises(helper.ControlError) as failure:
        helper.Client(Path("/synthetic-private/socket"), 1)
    assert str(failure.value) == "websocket_connect_failed"
    details = failure.value.error_details
    assert details.get("exception_type") == expected
    assert details.get("errno") == getattr(exception, "errno", None)
    assert "credential-secret" not in json.dumps(details)
    assert closed == ([True] if enter_fails else [])


def test_arbitrary_control_error_text_is_redacted(helper, rig):
    endpoint = rig.Endpoint("error")
    endpoint.failures["initialize"] = helper.ControlError("credential-secret /synthetic-private")
    report = helper.run([endpoint.path], "current-secret", "sql", factory=rig.factory)
    assert report["binding_diagnostics"][0]["reason"] == "control_operation_failed"
    assert_private(report)


@pytest.mark.parametrize("count", [16, 17])
def test_candidate_and_diagnostic_count_are_bounded(helper, rig, count):
    endpoints = [rig.Endpoint(str(index), threads=[]) for index in range(count)]
    report = helper.run([endpoint.path for endpoint in endpoints], "current-secret", "sql", factory=rig.factory)
    assert len(report["binding_diagnostics"]) <= 17
    assert len(rig.opened) == (16 if count == 16 else 0)
    assert report["reason"] == ("current_host_not_verified" if count == 16 else "endpoint_budget_exceeded")
    assert all(endpoint.closed == (1 if count == 16 else 0) for endpoint in endpoints)


def test_exhausted_budget_never_validates_or_connects_an_endpoint(helper, rig, monkeypatch):
    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=lambda: 10))
    diagnostics = []
    with pytest.raises(helper.ControlError, match="operation_timeout"):
        helper.connect_bound([Path("/synthetic-private/socket")], "current-secret", "sql", 10,
                             rig.factory, deadline=10, diagnostics=diagnostics)
    assert not rig.opened and diagnostics[0]["phase"] == "endpoint_validation"


@pytest.mark.parametrize("expires_during", ["connect", "initialize", "catalog", "second_connect"])
def test_shared_budget_caps_handshakes_and_cleans_up_without_further_rpcs(
        helper, rig, monkeypatch, expires_during):
    clock = [55.0]
    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    first, second = rig.Endpoint("first"), rig.Endpoint("second")
    original = first.call

    def call(method, params, **kwargs):
        result = original(method, params, **kwargs)
        if method == {"initialize": "initialize", "catalog": "mcpServerStatus/list"}.get(expires_during):
            clock[0] = 60
        return result

    first.call = call

    def factory(path, timeout):
        endpoint = rig.factory(path, timeout)
        if expires_during == "connect" or (expires_during == "second_connect" and path == second.path):
            clock[0] = 60
        return endpoint

    diagnostics = []
    with pytest.raises(helper.ControlError, match="operation_timeout"):
        helper.connect_bound([first.path, second.path], "current-secret", "sql", 10,
                             factory, deadline=60, diagnostics=diagnostics)
    assert all(timeout == 5 for _, timeout in rig.opened)
    assert first.closed == 1
    if expires_during == "second_connect":
        assert second.closed == 1 and second.calls == []
    else:
        assert len(rig.opened) == 1 and second.closed == 0
    if expires_during == "connect":
        assert first.calls == []
    if expires_during == "initialize":
        assert first.methods() == ["initialize"] and first.sent == []
    assert diagnostics[-1]["reason"] == "operation_timeout"


def test_rpc_message_budget_remains_bounded_and_has_no_membership_claim(helper, rig):
    endpoint = rig.Endpoint("wire")
    client = helper.Client.__new__(helper.Client)
    client.path, client.timeout, client.deadline, client.serial = endpoint.path, 10, float("inf"), 0
    client.close = endpoint.close
    client.send = lambda message: None
    replies = []

    def recv(**kwargs):
        replies.append(True)
        return json.dumps({"method": "notification", "params": {"secret": "credential-secret"}})

    client.connection = SimpleNamespace(recv=recv)
    report = helper.run([endpoint.path], "current-secret", "sql", factory=lambda *args: client)
    assert len(replies) == 512 and endpoint.closed == 1
    assert report["binding_diagnostics"][0]["reason"] == "message_budget_exceeded"
    assert "current_thread_loaded" not in report["binding_diagnostics"][0]
    assert_private(report)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("same_value", [False, True])
@pytest.mark.parametrize("explicit_socket", [False, True])
@pytest.mark.parametrize("recreate", [False, True])
def test_main_sources_follow_argument_presence_even_when_values_equal(
        helper, rig, recreatable, monkeypatch, capsys, explicit, same_value, explicit_socket, recreate):
    endpoint, _ = recreatable
    monkeypatch.setenv("CODEX_THREAD_ID", "current-secret" if same_value else "environment-secret")
    argv = ["helper", "recreate" if recreate else "probe", "--server", "sql"]
    if recreate:
        argv += ["--dry-run", "--connection", "test"]
    if explicit:
        argv += ["--thread-id", "current-secret"]
    if explicit_socket:
        argv += ["--socket", str(endpoint.path)]

        def forbidden():
            pytest.fail("An explicit endpoint must not trigger discovery")

        monkeypatch.setattr(helper, "discover_sockets", forbidden)
    else:
        monkeypatch.setattr(helper, "discover_sockets", lambda: [endpoint.path])
    # A distinct environment ID must fail membership instead of silently
    # selecting the one available thread. Explicit arguments take precedence.
    expected_success = explicit or same_value
    monkeypatch.setattr(sys, "argv", argv)
    name = "run_recreate" if recreate else "run"
    run = getattr(helper, name)
    monkeypatch.setattr(helper, name, lambda *args, **kwargs: run(*args, factory=rig.factory, **kwargs))
    assert helper.main() == (0 if expected_success else 2)
    report = json.loads(capsys.readouterr().out)
    assert report["thread_id_source"] == ("--thread-id" if explicit else "CODEX_THREAD_ID")
    assert report["endpoint_source"] == ("--socket" if explicit_socket else "discovery")
    assert report["binding_verified"] is expected_success
    assert endpoint.closed == 1


def test_main_discovery_failure_keeps_sources_and_json_failure(helper, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_THREAD_ID", "current-secret")
    monkeypatch.setattr(sys, "argv", ["helper"])

    def unavailable():
        raise helper.ControlError("control_directory_unavailable")

    monkeypatch.setattr(helper, "discover_sockets", unavailable)
    assert helper.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "control_directory_unavailable" and not report["binding_verified"]
    assert report["thread_id_source"] == "CODEX_THREAD_ID" and report["endpoint_source"] == "discovery"
    assert report["binding_diagnostics"][0]["phase"] == "endpoint_discovery"
    assert_private(report)
