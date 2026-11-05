"""Control probing never reloads a Host or creates/loads a thread."""

import importlib.util
from pathlib import Path
import socket
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Codex Unix helper")


spec = importlib.util.spec_from_file_location(
    "codex_probe", Path(__file__).resolve().parents[1] / "scripts/dev/probe_codex_mcp.py")
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize("case", ["matched", "wrong_thread", "missing_server", "timeout"])
def test_probe_reports_binding_separately_from_readiness(tmp_path, case):
    path = tmp_path / "control.sock"
    control = socket.socket(socket.AF_UNIX)
    control.bind(str(path))
    methods = []
    closed = []
    class FakeProxy:
        def __init__(self, *args): pass
        def call(self, method, params):
            methods.append(method)
            if case == "timeout": raise probe.ProbeError("timeout")
            if method == "initialize": return {}
            if method == "thread/loaded/list": return {"data": ["other" if case == "wrong_thread" else "current"]}
            if method == "mcpServerStatus/list":
                assert params["threadId"] == "current"
                return {"data": [] if case == "missing_server" else [{"name": "sql", "tools": {"query": {}}}]}
            pytest.fail(f"Unexpected control method {method}")
        def send(self, message): assert message == {"method": "initialized"}
        def close(self): closed.append(True)
    try:
        result = probe.probe(str(path), "current", "sql", factory=FakeProxy)
        assert result["binding_verified"] is (case == "matched")
        assert result["client_readiness"] == "unverified"
        assert result["restart_verified"] is False and result["reload_requested"] is False
        assert closed == [True]
        assert set(methods) <= {"initialize", "thread/loaded/list", "mcpServerStatus/list"}
    finally:
        control.close()


def test_missing_endpoint_does_not_start_proxy(tmp_path):
    def forbidden(*args): pytest.fail("Must not start a proxy without an owned socket")
    result = probe.probe(str(tmp_path / "missing"), "current", "sql", factory=forbidden)
    assert result["reason"] == "current_host_not_verified"
    assert not result["binding_verified"]
