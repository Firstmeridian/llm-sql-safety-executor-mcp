"""Bound read-only startup waiting; never retry config changes or canaries."""
import json
import sys
from types import SimpleNamespace

import pytest

from tests.test_codex_mcp_restart import helper
from tests.test_codex_mcp_recreate import host  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix helper")


def fake_time(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(helper, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    return clock


def assert_one_recovery(host):
    assert host.refreshes == 2 and len(host.writes) == 2
    assert host.config.read_bytes() == host.original_bytes


def test_slow_catalog_and_single_canary_share_startup_window(host, monkeypatch):
    clock = fake_time(monkeypatch)
    original = host.call
    waits = []

    def call(method, params, *, timeout=None):
        if host.refreshes == 2 and method in {"mcpServerStatus/list", "mcpServer/tool/call"}:
            waits.append(timeout)
            clock[0] += 12 if method == "mcpServerStatus/list" else 7
        return original(method, params, timeout=timeout)

    monkeypatch.setattr(host, "call", call)
    report = host.run(timeout=1)
    assert report["phase"] == "complete" and report["process_restart_verified"]
    assert waits == [30, 18]
    assert report["consumer_verification_elapsed_ms"] == 19000
    assert host.methods().count("mcpServer/tool/call") == 1
    assert_one_recovery(host)


def test_transient_catalog_waits_without_another_refresh_or_query(host, monkeypatch):
    fake_time(monkeypatch)
    original = host.call
    statuses = iter([None, "notStarted", "starting", "disabled"])

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "mcpServerStatus/list" and host.refreshes == 2:
            state = next(statuses, "connected")
            result["data"][0].update(runtimeStatus=state, tools={"query": {}} if state == "connected" else {})
        return result

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["process_restart_verified"] and report["consumer_catalog_checks"] == 5
    assert host.methods().count("mcpServer/tool/call") == 1
    assert_one_recovery(host)


@pytest.mark.parametrize("state", ["failed", "cancelled", "authenticationRequired", "unknown", "connected"])
def test_terminal_or_incomplete_catalog_stops_without_canary(host, monkeypatch, state):
    fake_time(monkeypatch)
    original = host.call

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "mcpServerStatus/list" and host.refreshes == 2:
            result["data"][0].update(runtimeStatus=state, tools={})
        return result

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["phase"] == "consumer_verification"
    assert report["consumer_verification_step"] == "catalog"
    assert report["reason"] == ("query_tool_not_observed" if state == "connected" else "target_server_not_connected")
    assert report["consumer_catalog_checks"] == 1 and not report["process_restart_verified"]
    assert "mcpServer/tool/call" not in host.methods()
    assert_one_recovery(host)


def test_starting_catalog_has_bounded_wait_and_keeps_restored_config(host, monkeypatch):
    clock = fake_time(monkeypatch)
    monkeypatch.setattr(helper.time, "sleep", lambda _: clock.__setitem__(0, clock[0] + 10))
    original = host.call

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "mcpServerStatus/list" and host.refreshes == 2:
            result["data"][0].update(runtimeStatus="starting", tools={})
        return result

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["reason"] == "consumer_readiness_timeout"
    assert clock[0] == 30 and report["consumer_catalog_checks"] == 3
    assert not report["process_restart_verified"]
    assert "mcpServer/tool/call" not in host.methods()
    assert_one_recovery(host)


@pytest.mark.parametrize("failing_method,step", [
    ("mcpServerStatus/list", "catalog"), ("mcpServer/tool/call", "canary"),
])
def test_timed_out_read_is_not_reissued_and_identifies_failed_step(host, monkeypatch, failing_method, step):
    fake_time(monkeypatch)
    original = host.call
    attempts = []

    def call(method, params, *, timeout=None):
        if host.refreshes == 2 and method == failing_method:
            attempts.append(method)
            host.last_rpc = {"method": method, "request_sent": True, "timeout_sec": timeout,
                             "elapsed_ms": timeout * 1000}
            raise helper.ControlError("rpc_timeout")
        return original(method, params, timeout=timeout)

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["reason"] == "rpc_timeout" and report["consumer_verification_step"] == step
    assert report["last_rpc"]["method"] == failing_method and attempts == [failing_method]
    assert not report["process_restart_verified"]
    assert_one_recovery(host)


def test_group_consumers_share_one_budget(host, monkeypatch):
    clock = fake_time(monkeypatch)
    host.threads.append("second")
    host.identities.add((21, "another-new"))
    original = host.call
    timeouts = []

    def call(method, params, *, timeout=None):
        if method == "mcpServerStatus/list" and host.refreshes == 2:
            timeouts.append(timeout)
            if params["threadId"] == "second":
                clock[0] += timeout
                raise helper.ControlError("rpc_timeout")
        if method == "mcpServer/tool/call":
            clock[0] += 22
        return original(method, params, timeout=timeout)

    monkeypatch.setattr(host, "call", call)
    report = host.run(all_loaded_targets=True)
    assert report["reason"] == "rpc_timeout" and timeouts == [30, 8]
    assert clock[0] == 30 and not report["process_restart_verified"]
    assert host.methods().count("mcpServer/tool/call") == 1
    assert_one_recovery(host)


def test_global_deadline_caps_readiness_window(host, monkeypatch):
    clock = fake_time(monkeypatch)
    original = host.call
    waits = []

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "config/mcpServer/reload" and host.refreshes == 2:
            clock[0] = 55
        if method == "mcpServerStatus/list" and host.refreshes == 2:
            waits.append(timeout)
        return result

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["consumer_readiness_budget_sec"] == 5 and waits == [5]
    assert report["process_restart_verified"]
    assert_one_recovery(host)


def test_scope_change_during_startup_cannot_be_reported_as_complete(host, monkeypatch):
    fake_time(monkeypatch)
    original = host.call

    def call(method, params, *, timeout=None):
        result = original(method, params, timeout=timeout)
        if method == "mcpServer/tool/call":
            host.threads.append("new-unapproved-thread")
        return result

    monkeypatch.setattr(host, "call", call)
    report = host.run()
    assert report["reason"] == "loaded_threads_changed"
    assert report["consumer_verification_step"] == "scope" and not report["process_restart_verified"]
    assert host.methods().count("mcpServer/tool/call") == 1
    assert_one_recovery(host)


def bare_client(monkeypatch, *, deadline=60):
    clock = fake_time(monkeypatch)
    client = helper.Client.__new__(helper.Client)
    client.timeout, client.deadline, client.serial = 10, deadline, 0
    sent = []
    client.send = sent.append
    return client, clock, sent


@pytest.mark.parametrize("method", ["config/batchWrite", "config/mcpServer/reload"])
def test_expired_budget_never_sends_a_mutating_rpc(monkeypatch, method):
    client, _, sent = bare_client(monkeypatch, deadline=0)
    with pytest.raises(helper.ControlError, match="rpc_timeout"):
        client.call(method, {})
    assert not sent and client.last_rpc["request_sent"] is False


@pytest.mark.parametrize("delay,deadline,succeeds", [(12, 60, True), (31, 60, False), (12, 8, False)])
def test_readiness_rpc_uses_explicit_timeout_bounded_by_total(monkeypatch, delay, deadline, succeeds):
    client, clock, sent = bare_client(monkeypatch, deadline=deadline)
    observed = []

    def recv(*, timeout):
        observed.append(timeout)
        clock[0] += min(delay, timeout)
        if delay > timeout:
            raise TimeoutError
        return json.dumps({"id": 1, "result": {"ok": True}})

    client.connection = SimpleNamespace(recv=recv)
    if succeeds:
        assert client.call("mcpServerStatus/list", {}, timeout=30) == {"ok": True}
    else:
        with pytest.raises(helper.ControlError, match="rpc_timeout"):
            client.call("mcpServerStatus/list", {}, timeout=30)
    assert observed == [min(30, deadline)] and len(sent) == 1
    assert client.last_rpc["method"] == "mcpServerStatus/list"
    assert client.last_rpc["elapsed_ms"] == min(delay, 30, deadline) * 1000


def test_late_response_is_ignored_by_next_read_without_replaying_old_rpc(monkeypatch):
    client, clock, sent = bare_client(monkeypatch)
    replies = iter([TimeoutError(), {"id": 1, "result": {"late": True}},
                    {"id": 2, "result": {"data": []}}])

    def recv(*, timeout):
        reply = next(replies)
        if isinstance(reply, Exception):
            clock[0] += timeout
            raise reply
        return json.dumps(reply)

    client.connection = SimpleNamespace(recv=recv)
    with pytest.raises(helper.ControlError, match="rpc_timeout"):
        client.call("mcpServerStatus/list", {})
    assert client.call("thread/loaded/list", {}) == {"data": []}
    assert [request["method"] for request in sent] == ["mcpServerStatus/list", "thread/loaded/list"]
