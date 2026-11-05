"""Running consumer identity, rather than current configuration, permits stop."""
import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_codex_mcp_restart import helper

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd helper")


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("duplicate_alias", [False, True])
def test_stale_configuration_cannot_bind_another_service(tmp_path, monkeypatch, group, duplicate_alias):
    target_args = ["-c", "import time; time.sleep(30)"]
    other_args = ["-c", "import time; time.sleep(31)"]
    target = subprocess.Popen([sys.executable, *target_args], cwd=tmp_path)
    other = subprocess.Popen([sys.executable, *other_args], cwd=tmp_path)
    # The real target still runs with target_args. Disk config points elsewhere;
    # the other's alias may have disappeared while its process remains alive.
    config = {"sql": {"command": sys.executable, "args": other_args, "cwd": str(tmp_path)}}
    if duplicate_alias:
        config["other"] = copy.deepcopy(config["sql"])
    class Fake:
        path = tmp_path / "unused"
        def call(self, method, params, *, timeout=None):
            assert method == "config/read"
            return {"config": {"mcp_servers": copy.deepcopy(config)}}
    monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
    signals = []
    # Do not send signals even if the implementation regresses.
    monkeypatch.setattr(helper.signal, "pidfd_send_signal", lambda *args: signals.append(args))
    guard = None
    try:
        if duplicate_alias:
            with pytest.raises(helper.ControlError, match="ambiguous_server_launch_configuration"):
                helper.ProcessGroupGuard(Fake(), "sql", 1) if group else helper.ProcessGuard(Fake(), "sql")
        else:
            guard = helper.ProcessGroupGuard(Fake(), "sql", 1) if group else helper.ProcessGuard(Fake(), "sql")
            assert guard.current_members()[0][0] == other.pid  # Candidate alone is insufficient.
            with pytest.raises(helper.ControlError, match="consumer_process_identity_mismatch"):
                guard.verify_consumers([target.pid], guard.current_members())
            with pytest.raises(helper.ControlError, match="consumer_process_identity_unverified"):
                guard.stop()
        assert signals == [] and target.poll() is None and other.poll() is None
    finally:
        if guard is not None:
            guard.close()
        for p in (target, other):
            p.terminate()
            p.wait(timeout=2)


@pytest.mark.parametrize("change", ["config", "alias"])
def test_single_target_rechecks_launch_configuration_before_stop(tmp_path, monkeypatch, change):
    args = ["-c", "import time; time.sleep(30)"]
    child = subprocess.Popen([sys.executable, *args], cwd=tmp_path)
    config = {"sql": {"command": sys.executable, "args": args, "cwd": str(tmp_path)}}
    class Fake:
        path = tmp_path / "unused"
        def call(self, method, params, *, timeout=None):
            assert method == "config/read"
            return {"config": {"mcp_servers": copy.deepcopy(config)}}
    monkeypatch.setattr(helper, "socket_owner", lambda path: os.getpid())
    signals = []
    monkeypatch.setattr(helper.signal, "pidfd_send_signal", lambda *args: signals.append(args))
    guard = None
    try:
        guard = helper.ProcessGuard(Fake(), "sql")
        guard.verify_consumers([child.pid], guard.current_members())
        if change == "config":
            config["sql"]["args"] = ["-c", "changed"]
            reason = "target_configuration_changed"
        else:
            config["other"] = copy.deepcopy(config["sql"])
            reason = "ambiguous_server_launch_configuration"
        with pytest.raises(helper.ControlError, match=reason):
            guard.stop()
        assert not signals and child.poll() is None
    finally:
        if guard is not None:
            guard.close()
        child.terminate()
        child.wait(timeout=2)


@pytest.mark.parametrize("meta", [None, {}, {"server_pid": True}, {"server_pid": "7"}, {"server_pid": -1}])
def test_stop_requires_a_valid_consumer_pid(meta):
    class Fake:
        def call(self, method, params, *, timeout=None):
            return {"structuredContent": {"success": True, "data": [{"codex_mcp_restart_canary": 1}]}, "_meta": meta}
    with pytest.raises(helper.ControlError, match="consumer_process_identity_missing"):
        helper.read_canary(Fake(), "thread", "sql", "demo", require_process=True)
    # Read-only verification without process stopping still supports this reply.
    helper.read_canary(Fake(), "thread", "sql", "demo")


def test_pid_set_does_not_accept_duplicate_consumers():
    with pytest.raises(helper.ControlError, match="consumer_process_identity_mismatch"):
        helper.verify_consumer_pids([7, 7], [(7, "a"), (8, "b")])
