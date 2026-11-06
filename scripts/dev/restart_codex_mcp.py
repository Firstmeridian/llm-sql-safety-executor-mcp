#!/usr/bin/env python3
"""Refresh an existing Codex Host and verify its thread-bound SQL MCP.

Defaults to a read-only probe. Restart stops a uniquely verified child, or
an explicitly selected whole-target group, using Linux pidfds, then asks
the existing Host to reconnect.
Shared-Host mode stops only the current thread's exclusive consumer, while
observing the other idle consumers across the global refresh.
Requires explicit Host-wide refresh consent; verified Codex 0.165/0.166 have no per-server
reload operation. Never starts a Host/thread or retries an uncertain reload.
Explicit recreate temporarily toggles one enabled key through the Host, with
separate consent and a recovery journal. Other modes do not change configuration.
Use refresh for config refresh without process replacement.
Mutating helper calls on one bound Host endpoint are serialized with a
nonblocking file lock. Receipts add next-action guidance and local timings;
neither changes consent, retries or the existing execution budgets.
Requires websockets >= 15 (already supplied by the development environment).
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import time
import tomllib


class ControlError(Exception):
    """A safe diagnostic code, without Host messages or credentials."""

    def __init__(self, code, *, cause=None):
        super().__init__(code)
        self.error_details = error_details(cause)


class HostMaintenanceLock:
    """Nonblocking cooperation between helpers on one bound Host endpoint.

    Keep the lock file: unlinking it on release would let another helper lock
    a different inode. The kernel releases flock on process exit, even on a
    crash; no PID file, stale-lock deletion or background wait is needed.
    """

    def __init__(self, path, *, root=None):
        import fcntl  # Only the Linux maintenance path needs this Unix module.

        root = Path(root) if root is not None else Path("/tmp") / f"codex-mcp-maintenance-{os.getuid()}"
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ControlError("maintenance_lock_directory_unverified")
        # The key excludes server and thread names: reload is Host-wide.
        key = hashlib.sha256(os.fsencode(Path(path).resolve())).hexdigest()
        fd = os.open(root / f"{key}.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ControlError("maintenance_lock_file_unverified")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ControlError("host_maintenance_in_progress") from None
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def close(self):
        os.close(self.fd)


class ReportTimings:
    """Local monotonic windows, including a failed window's elapsed time."""

    def __init__(self, report):
        self.report = report
        self.started = time.monotonic()
        report["timings_ms"] = {}
        self.verification_started = None

    @contextmanager
    def measure(self, name):
        started = time.monotonic()
        try:
            yield
        finally:
            values = self.report["timings_ms"]
            values[name] = round(values.get(name, 0) + (time.monotonic() - started) * 1000, 3)

    def verification(self):
        if self.verification_started is None:
            self.verification_started = time.monotonic()

    def end_verification(self):
        if self.verification_started is not None:
            self.report["timings_ms"]["consumer_verification"] = round(
                (time.monotonic() - self.verification_started) * 1000, 3)
            self.verification_started = None

    def finish(self):
        self.report["timings_ms"]["total"] = round((time.monotonic() - self.started) * 1000, 3)


def add_next_action(report):
    """Explain an existing outcome without performing or authorizing recovery."""
    reason = report.get("reason", "")
    if report.get("config_restore_error") or report.get("manual_recovery_required"):
        action, message = "reconcile_config_and_runtime", (
            "Inspect the recovery journal and current configuration version; reconcile runtime manually. "
            "Restored configuration does not prove runtime recovery. Do not automatically refresh again.")
    elif report.get("reload_attempted") or report.get("refresh_attempts", 0):
        if report["status"] == "connection_verified":
            action, message = "verify_intended_behavior", (
                "The caller must verify the intended definition or behavior through its actual native tool channel.")
        else:
            action, message = "verify_runtime_read_only", (
                "A refresh may have been sent. Use read-only probe/verify to inspect runtime; "
                "do not infer recovery or automatically repeat the refresh.")
    elif report.get("process_stop_attempted"):
        action, message = "inspect_target_read_only", (
            "Inspect the original target identity and consumer state read-only. A stop attempt does not prove exit; "
            "do not stop another process or automatically retry.")
    elif reason == "host_maintenance_in_progress":
        action, message = "wait_for_other_maintenance", (
            "Another helper holds this Host's maintenance lock. Let it finish, then run a read-only probe; "
            "this command does not wait or retry.")
    elif reason.startswith("maintenance_lock_"):
        action, message = "inspect_lock_storage", (
            "Check the ownership and permissions of local maintenance-lock storage; do not remove an active lock file.")
    elif reason in {"current_host_not_verified", "ambiguous_host_binding", "control_directory_unavailable"}:
        action, message = "verify_existing_host_binding", (
            "Check the existing Host endpoint and current loaded thread with a read-only probe. "
            "Use manual reconnect if binding cannot be proved; do not start or migrate a Host.")
    elif reason in {"other_thread_not_idle", "loaded_threads_changed", "loaded_threads_changed_after_refresh",
                    "loaded_thread_workspace_mismatch", "single_loaded_thread_required_for_refresh",
                    "single_loaded_thread_required_for_process_restart", "explicit_loaded_target_scope_required"}:
        action, message = "resolve_maintenance_scope", (
            "Confirm the loaded-chat scope and absence of in-flight or unconfirmed writes, then re-probe. "
            "Do not automatically widen scope.")
    elif reason:
        action, message = "inspect_failure_before_retry", (
            "Inspect phase, reason and any last_rpc in this receipt; resolve the observed failure before new maintenance. "
            "No retry or scope escalation was performed.")
    elif report["status"] == "recreate_plan_verified":
        action, message = "review_recreate_plan", (
            "This was a read-only plan, not a restart. Confirm scope and explicit configuration-toggle consent before execution.")
    elif report["status"] == "binding_verified":
        action, message = "verify_consumer_read_only", (
            "Host binding alone does not prove consumer readiness or a restart; use read-only verify for the selected test connection.")
    else:
        action, message = "verify_intended_behavior", (
            "The caller must verify the intended behavior in its actual native tool channel; read-only verify does not prove a restart.")
    report["next_action"] = {"action": action, "message": message}


def error_details(exc):
    # Exact built-in classes only: custom class names and exception text may
    # contain paths, credentials or other Host-controlled data.
    allowed = (OSError, PermissionError, FileNotFoundError, TimeoutError,
               ConnectionRefusedError, ConnectionResetError,
               ConnectionAbortedError, BrokenPipeError)
    details = {}
    if type(exc) in allowed:
        details["exception_type"] = type(exc).__name__
    if isinstance(exc, OSError) and type(exc.errno) is int and exc.errno in errno.errorcode:
        details["errno"] = exc.errno
    return details


# Never echo arbitrary ControlError text from a candidate into diagnostics.
BINDING_REASONS = frozenset({
    "unix_socket_control_required", "not_owned_control_socket",
    "websockets_dependency_missing", "websocket_connect_failed",
    "rpc_timeout", "rpc_error", "invalid_protocol_message",
    "invalid_protocol_result", "message_budget_exceeded",
    "transport_or_protocol_failed", "invalid_thread_list",
    "thread_budget_exceeded", "invalid_server_catalog",
    "target_server_not_observed", "query_tool_not_observed", "operation_timeout",
})


class Client:
    def __init__(self, path: Path, timeout: float):
        try:
            from websockets.sync.client import unix_connect
            from websockets.exceptions import InvalidHandshake
        except ImportError:
            raise ControlError("websockets_dependency_missing") from None
        self.timeout = timeout
        self.path = path
        self.deadline = time.monotonic() + 60
        self.serial = 0
        self.context = None
        try:
            self.context = unix_connect(
                str(path), uri="ws://localhost", open_timeout=timeout,
                close_timeout=1, max_size=8 * 1024 * 1024,
            )
            self.connection = self.context.__enter__()
        except Exception as exc:
            # unix_connect cleans up handshake failures; also close a context
            # that was returned but failed during entry.
            self.close()
            failure = ControlError("websocket_connect_failed", cause=exc)
            if isinstance(exc, InvalidHandshake):
                failure.error_details["exception_type"] = "InvalidHandshake"
            raise failure from None

    def send(self, message):
        self.connection.send(json.dumps(message))

    def call(self, method, params, *, timeout=None):
        self.serial += 1
        started = time.monotonic()
        deadline = min(started + (self.timeout if timeout is None else timeout), self.deadline)
        self.last_rpc = {"method": method, "request_sent": False,
                         "timeout_sec": max(0, deadline - started)}
        try:
            # Check before sending: an expired budget must not issue an edit
            # or refresh and then merely report that its response timed out.
            if deadline <= started:
                raise ControlError("rpc_timeout")
            self.last_rpc["request_sent"] = True
            self.send({"id": self.serial, "method": method, "params": params})
            for _ in range(512):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ControlError("rpc_timeout")
                message = json.loads(self.connection.recv(timeout=remaining))
                if not isinstance(message, dict):
                    raise ControlError("invalid_protocol_message")
                if "method" in message and "id" in message:
                    # Never approve an unsolicited Host request or elicit credentials.
                    self.send({"id": message["id"], "error": {
                        "code": -32601, "message": "Unsupported by MCP restart helper"}})
                    continue
                if message.get("id") != self.serial:
                    continue
                if "error" in message:
                    raise ControlError("rpc_error")
                if not isinstance(message.get("result"), dict):
                    raise ControlError("invalid_protocol_result")
                return message["result"]
            raise ControlError("message_budget_exceeded")
        except ControlError:
            raise
        except TimeoutError:
            raise ControlError("rpc_timeout") from None
        except Exception:
            raise ControlError("transport_or_protocol_failed") from None
        finally:
            self.last_rpc["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)

    def close(self):
        if self.context is not None:
            context, self.context = self.context, None
            try:
                context.__exit__(None, None, None)
            except Exception:
                pass  # Cleanup must not replace the original safe failure.


def owned_socket(path: Path):
    if not hasattr(os, "getuid"):
        raise ControlError("unix_socket_control_required")
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ControlError("not_owned_control_socket")


def discover_sockets():
    """Only the current Linux UID's conventional daemon directory; no new daemon."""
    if not hasattr(os, "getuid"):
        raise ControlError("unix_socket_control_required")
    root = Path("/tmp") / f"codex-daemon-{os.getuid()}"
    try:
        paths = sorted(root.iterdir())
    except OSError:
        raise ControlError("control_directory_unavailable") from None
    candidates = []
    for path in paths:
        try:
            owned_socket(path)
        except (OSError, ControlError):
            continue
        candidates.append(path)
    if len(candidates) > 16:
        raise ControlError("endpoint_budget_exceeded")
    return candidates


def loaded_threads(client):
    cursor = None
    threads = set()
    for _ in range(8):
        page = client.call("thread/loaded/list", {"limit": 100, "cursor": cursor})
        data = page.get("data")
        if not isinstance(data, list) or any(not isinstance(t, str) for t in data):
            raise ControlError("invalid_thread_list")
        threads.update(data)
        cursor = page.get("nextCursor")
        if not cursor:
            return threads
    raise ControlError("thread_budget_exceeded")


def server_status(client, thread_id, server, *, timeout=None):
    page = client.call("mcpServerStatus/list", {
        "threadId": thread_id, "serverName": server,
        "detail": "toolsAndAuthOnly", "limit": 100,
    }, **({"timeout": timeout} if timeout is not None else {}))
    data = page.get("data")
    if not isinstance(data, list) or any(not isinstance(s, dict) for s in data):
        raise ControlError("invalid_server_catalog")
    matches = [s for s in data if s.get("name") == server]
    if len(matches) != 1 or page.get("nextCursor"):
        raise ControlError("target_server_not_observed")
    return matches[0]


def catalog(client, thread_id, server, *, require_connected=False):
    observed = server_status(client, thread_id, server)
    if require_connected and observed.get("runtimeStatus") != "connected":
        raise ControlError("target_server_not_connected")
    tools = observed.get("tools")
    if not isinstance(tools, dict) or "query" not in tools:
        raise ControlError("query_tool_not_observed")
    return tools


def ready_catalog(client, thread_id, server, deadline, report):
    """Wait only for transient startup states; never reissue a timed-out RPC."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControlError("consumer_readiness_timeout")
        observed = server_status(client, thread_id, server, timeout=remaining)
        status = observed.get("runtimeStatus")
        report["consumer_catalog_checks"] = report.get("consumer_catalog_checks", 0) + 1
        report["last_observed_runtime_status"] = status
        if time.monotonic() >= deadline:
            raise ControlError("consumer_readiness_timeout")
        if status == "connected":
            tools = observed.get("tools")
            if not isinstance(tools, dict) or "query" not in tools:
                raise ControlError("query_tool_not_observed")
            return tools
        # Exact 0.165 schema: null means unavailable/configuration changed.
        # After acknowledged restore, allow publication/startup to settle;
        # a persistent disabled/null status still times out without a refresh.
        if status not in {None, "notStarted", "starting", "disabled"}:
            raise ControlError("target_server_not_connected")
        time.sleep(min(.1, max(0, deadline - time.monotonic())))


def fingerprint(tools):
    return hashlib.sha256(json.dumps(
        tools, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode()).hexdigest()


def connect_bound(paths, thread_id, server, timeout, factory=Client, deadline=None,
                  require_catalog=True, *, diagnostics=None):
    # One terminal record per candidate (at most 16), plus final uniqueness.
    # Only a complete thread inventory permits a membership claim.
    diagnostics = [] if diagnostics is None else diagnostics
    if len(paths) > 16:
        diagnostics.append({"phase": "endpoint_validation", "reason": "endpoint_budget_exceeded"})
        raise ControlError("endpoint_budget_exceeded")
    if deadline is None:
        deadline = time.monotonic() + 60

    def remaining_budget():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControlError("operation_timeout")
        return remaining

    matches = []
    membership_matches = 0
    try:
        for index, path in enumerate(paths, 1):
            diagnostic = {"endpoint": f"candidate-{index}", "phase": "endpoint_validation"}
            diagnostics.append(diagnostic)
            client = None
            try:
                remaining_budget()
                owned_socket(path)
                diagnostic["phase"] = "connect"
                client = factory(path, min(timeout, remaining_budget()))
                client.path = path
                client.deadline = deadline
                diagnostic["phase"] = "initialize"
                remaining_budget()
                client.call("initialize", {
                    "clientInfo": {"name": "sql_mcp_restart_helper", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                })
                remaining_budget()
                client.send({"method": "initialized"})
                diagnostic["phase"] = "thread_list"
                remaining_budget()
                threads = loaded_threads(client)
                diagnostic.update(phase="thread_binding", loaded_thread_count=len(threads),
                                  current_thread_loaded=thread_id in threads)
                remaining_budget()
                if thread_id not in threads:
                    diagnostic["reason"] = "current_thread_not_loaded"
                    continue
                # Host identity depends on thread membership, not whether its
                # MCP catalog happens to respond. A failed catalog must not
                # make another Host with the same thread appear unique.
                membership_matches += 1
                tools = {}
                if require_catalog:
                    diagnostic["phase"] = "catalog"
                    remaining_budget()
                    tools = catalog(client, thread_id, server)
                remaining_budget()
                diagnostic.update(reason="candidate_matched", catalog_checked=require_catalog)
                matches.append((client, tools, threads))
                client = None
            except (OSError, ControlError) as exc:
                code = str(exc) if isinstance(exc, ControlError) else "endpoint_unavailable"
                diagnostic["reason"] = code if code in BINDING_REASONS or code == "endpoint_unavailable" else "control_operation_failed"
                diagnostic.update(exc.error_details if isinstance(exc, ControlError) else error_details(exc))
                if code == "operation_timeout":
                    raise
                continue
            finally:
                if client is not None:
                    client.close()
        reason = ("ambiguous_host_binding" if membership_matches > 1 else
                  "unique_host_binding" if len(matches) == 1 else "current_host_not_verified")
        summary = {"phase": "uniqueness", "matched_candidate_count": membership_matches,
                   "catalog_ready_candidate_count": len(matches), "reason": reason}
        diagnostics.append(summary)
        try:
            remaining_budget()
        except ControlError:
            summary["reason"] = "operation_timeout"
            raise
        if membership_matches != 1 or len(matches) != 1:
            raise ControlError(reason)
        return matches.pop()
    finally:
        for client, _, _ in matches:
            client.close()


def read_canary(client, thread_id, server, connection, *, require_process=False,
                timeout=None):
    result = client.call("mcpServer/tool/call", {
        "threadId": thread_id, "server": server, "tool": "query",
        "arguments": {"connection_id": connection,
                      "sql": "SELECT 1 AS codex_mcp_restart_canary"},
    }, **({"timeout": timeout} if timeout is not None else {}))
    if result.get("isError"):
        raise ControlError("canary_tool_error")
    payload = result.get("structuredContent")
    if payload is None:
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    payload = json.loads(item.get("text", ""))
                except (ValueError, TypeError):
                    continue
                break
    if (not isinstance(payload, dict) or payload.get("success") is not True
            or payload.get("data") != [{"codex_mcp_restart_canary": 1}]):
        raise ControlError("canary_result_unverified")
    meta = result.get("_meta")
    pid = meta.get("server_pid") if isinstance(meta, dict) else None
    if require_process and (type(pid) is not int or pid <= 0):
        raise ControlError("consumer_process_identity_missing")
    return pid


def verify_consumer_pids(pids, members):
    # Observed through the actual thread/server tool call, not disk config.
    if (len(pids) != len(members) or any(type(pid) is not int for pid in pids)
            or set(pids) != {pid for pid, _ in members}):
        raise ControlError("consumer_process_identity_mismatch")


def process_state(pid):
    root = Path("/proc") / str(pid)
    if root.stat().st_uid != os.getuid():
        raise ControlError("process_owner_changed")
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[1]), fields[19]


def socket_owner(path):
    """Map the already bound listener, not every socket with a similar name."""
    owned_socket(path)
    inodes = set()
    for line in Path("/proc/net/unix").read_text().splitlines()[1:]:
        parts = line.split(maxsplit=7)
        if (len(parts) == 8 and parts[7] == str(path)
                and int(parts[3], 16) & 0x10000):
            inodes.add(f"socket:[{parts[6]}]")
    owners = set()
    for root in Path("/proc").iterdir():
        if not root.name.isdigit():
            continue
        try:
            if root.stat().st_uid != os.getuid():
                continue
            for fd in (root / "fd").iterdir():
                try:
                    if os.readlink(fd) in inodes:
                        owners.add(int(root.name))
                except OSError:
                    continue
        except OSError:
            continue
    if len(owners) != 1:
        raise ControlError("host_process_not_unique")
    return owners.pop()


def find_matching_children(host_pid, command, args, cwd):
    if not Path(command).is_absolute() or not Path(cwd).is_absolute():
        raise ControlError("absolute_process_configuration_required")
    expected = [command, *args]
    matches = []
    for root in Path("/proc").iterdir():
        if not root.name.isdigit():
            continue
        try:
            if root.stat().st_uid != os.getuid():
                continue
            parent, start = process_state(int(root.name))
            if parent != host_pid or Path(os.readlink(root / "cwd")).resolve() != Path(cwd).resolve():
                continue
            argv = (root / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
            direct = (len(argv) == len(expected) and argv[1:] == args
                      and Path(argv[0]).resolve() == Path(command).resolve())
            script = False
            if len(argv) == len(expected) + 1 and argv[1:] == expected:
                with Path(command).open("rb") as stream:
                    first = stream.readline(512).decode().strip()
                interpreter = first[2:] if first.startswith("#!") else ""
                script = (interpreter.startswith("/") and " " not in interpreter
                          and Path(interpreter).resolve() == Path(argv[0]).resolve()
                          and Path(os.readlink(root / "exe")).resolve() == Path(interpreter).resolve())
            if direct or script:
                matches.append((int(root.name), start))
        except (OSError, UnicodeError):
            continue
    return sorted(matches)


def matching_children(host_pid, command, args, cwd):
    matches = find_matching_children(host_pid, command, args, cwd)
    if len(matches) != 1:
        raise ControlError("target_process_not_unique")
    return matches[0]


def process_configuration(client, server):
    config = client.call("config/read", {"cwd": str(Path.cwd()), "includeLayers": False})
    servers = config.get("config", {}).get("mcp_servers", {})
    spec = servers.get(server, {})
    command, args, cwd = spec.get("command"), spec.get("args", []), spec.get("cwd")
    if (not isinstance(command, str) or not isinstance(cwd, str)
            or not isinstance(args, list) or any(not isinstance(a, str) for a in args)):
        raise ControlError("local_stdio_process_configuration_required")
    if not Path(command).is_absolute() or not Path(cwd).is_absolute():
        raise ControlError("absolute_process_configuration_required")
    return servers, command, args, cwd


def reject_launch_aliases(servers, server, command, args, cwd):
    # Identical launch definitions cannot be distinguished by /proc, even if
    # their environment differs. Do not infer server identity from a filename.
    for name, spec in servers.items():
        if name == server or not isinstance(spec, dict):
            continue
        other_command, other_cwd = spec.get("command"), spec.get("cwd")
        if (isinstance(other_command, str) and isinstance(other_cwd, str)
                and Path(other_command).resolve() == Path(command).resolve()
                and Path(other_cwd).resolve() == Path(cwd).resolve()
                and spec.get("args", []) == args):
            raise ControlError("ambiguous_server_launch_configuration")


class ProcessGuard:
    """Pin a local candidate; consumer PID verification is required to signal it."""
    def __init__(self, client, server):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ControlError("linux_pidfd_required")
        self.host_pid = socket_owner(client.path)
        self.host_start = process_state(self.host_pid)[1]
        self.client, self.server = client, server
        servers, self.command, self.args, self.cwd = process_configuration(client, server)
        reject_launch_aliases(servers, server, self.command, self.args, self.cwd)
        self.pid, self.start = self.current()
        self.consumers_verified = False
        self.fd = os.pidfd_open(self.pid)
        try:
            if process_state(self.pid) != (self.host_pid, self.start):
                raise ControlError("target_process_changed")
        except BaseException:
            os.close(self.fd)
            raise

    def current(self):
        if process_state(self.host_pid)[1] != self.host_start:
            raise ControlError("host_process_changed")
        return matching_children(self.host_pid, self.command, self.args, self.cwd)

    def stop(self):
        if not self.consumers_verified:
            raise ControlError("consumer_process_identity_unverified")
        servers, command, args, cwd = process_configuration(self.client, self.server)
        if (command, args, cwd) != (self.command, self.args, self.cwd):
            raise ControlError("target_configuration_changed")
        reject_launch_aliases(servers, self.server, command, args, cwd)
        if self.current() != (self.pid, self.start):
            raise ControlError("target_process_changed")
        signal.pidfd_send_signal(self.fd, signal.SIGTERM)
        if not select.select([self.fd], [], [], 10)[0]:
            raise ControlError("target_stop_unconfirmed")

    def replaced(self):
        return self.current() != (self.pid, self.start)

    def current_members(self):
        return [self.current()]

    def verify_consumers(self, pids, members):
        verify_consumer_pids(pids, members)
        if self.current_members() != members:
            raise ControlError("target_process_changed")
        self.consumers_verified = members == [(self.pid, self.start)]

    def close(self):
        os.close(self.fd)


class ProcessGroupGuard:
    """Explicit whole-target scope; never claim a thread-to-PID mapping."""
    def __init__(self, client, server, expected_count):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ControlError("linux_pidfd_required")
        self.host_pid = socket_owner(client.path)
        self.host_start = process_state(self.host_pid)[1]
        if not 1 <= expected_count <= 8:
            raise ControlError("target_group_thread_budget_exceeded")
        self.client, self.server = client, server
        servers, self.command, self.args, self.cwd = process_configuration(client, server)
        reject_launch_aliases(servers, server, self.command, self.args, self.cwd)
        self.expected_count = expected_count
        self.members = self.current()
        self.consumers_verified = False
        self.fds = []
        self.signals_sent = 0
        self.stops_confirmed = 0
        try:
            for pid, start in self.members:
                fd = os.pidfd_open(pid)
                self.fds.append(fd)
                if process_state(pid) != (self.host_pid, start):
                    raise ControlError("target_process_changed")
            if self.current() != self.members:
                raise ControlError("target_process_group_changed")
        except BaseException:
            self.close()
            raise

    def current(self):
        if process_state(self.host_pid)[1] != self.host_start:
            raise ControlError("host_process_changed")
        members = find_matching_children(self.host_pid, self.command, self.args, self.cwd)
        if len(members) != self.expected_count:
            raise ControlError("target_process_count_mismatch")
        return members

    def stop(self):
        if not self.consumers_verified:
            raise ControlError("consumer_process_identity_unverified")
        servers, command, args, cwd = process_configuration(self.client, self.server)
        if (command, args, cwd) != (self.command, self.args, self.cwd):
            raise ControlError("target_configuration_changed")
        reject_launch_aliases(servers, self.server, command, args, cwd)
        if self.current() != self.members:
            raise ControlError("target_process_group_changed")
        for (pid, start), fd in zip(self.members, self.fds, strict=True):
            if process_state(pid) != (self.host_pid, start):
                raise ControlError("target_process_changed")
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            self.signals_sent += 1
        # One shared deadline, independent of the number of target children.
        deadline = time.monotonic() + 10
        for fd in self.fds:
            if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
                raise ControlError("target_stop_unconfirmed")
            self.stops_confirmed += 1
        if find_matching_children(self.host_pid, self.command, self.args, self.cwd):
            raise ControlError("target_process_group_changed_after_stop")

    def replaced(self):
        self.replacements = self.current()
        return not set(self.members).intersection(self.replacements)

    def current_members(self):
        return self.current()

    def verify_consumers(self, pids, members):
        verify_consumer_pids(pids, members)
        if self.current() != members:
            raise ControlError("target_process_group_changed")
        self.consumers_verified = members == self.members

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds.clear()


class SharedHostGuard(ProcessGroupGuard):
    """Observe every consumer; signal only the current thread's pinned child."""
    def __init__(self, client, server, threads, thread_id):
        self.threads = sorted(threads)
        self.thread_id = thread_id
        self.before = None
        self.observed = None
        super().__init__(client, server, len(threads))

    def verify_consumers(self, pids, members):
        # The exact set and cardinality prove one exclusive process per thread.
        # A shared PID or an old consumer under different launch config fails.
        super().verify_consumers(pids, members)
        identities = dict(members)
        self.observed = {thread: (pid, identities[pid])
                         for thread, pid in zip(self.threads, pids, strict=True)}
        self.observed_members = members
        if self.before is None:
            self.before = dict(self.observed)

    def stop(self, *, scope_check):
        if not self.consumers_verified or self.before is None:
            raise ControlError("consumer_process_identity_unverified")
        servers, command, args, cwd = process_configuration(self.client, self.server)
        if (command, args, cwd) != (self.command, self.args, self.cwd):
            raise ControlError("target_configuration_changed")
        reject_launch_aliases(servers, self.server, command, args, cwd)
        if self.current() != self.members:
            raise ControlError("target_process_group_changed")
        pid, start = self.before[self.thread_id]
        if process_state(pid) != (self.host_pid, start):
            raise ControlError("target_process_changed")
        fd = self.fds[self.members.index((pid, start))]
        scope_check()
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        self.signals_sent += 1
        if not select.select([fd], [], [], 10)[0]:
            raise ControlError("target_stop_unconfirmed")
        self.stops_confirmed += 1

    def replaced(self):
        if self.before is None or self.observed is None:
            return False
        if self.current() != self.observed_members:
            raise ControlError("target_process_group_changed")
        return self.observed[self.thread_id] not in self.members

    def observations(self):
        if self.before is None or self.observed is None:
            return []
        return [{"thread_sha256": hashlib.sha256(thread.encode()).hexdigest()[:16],
                 "current_thread": thread == self.thread_id,
                 "before": self.before[thread], "after": self.observed[thread],
                 "process_replaced": self.before[thread] != self.observed[thread]}
                for thread in self.threads]


def other_threads_idle(client, threads, thread_id, *, workspace=None):
    checked = threads if workspace is not None else threads - {thread_id}
    for other in sorted(checked):
        state = client.call("thread/read", {"threadId": other, "includeTurns": False})
        metadata = state.get("thread", {})
        if workspace is not None:
            cwd = metadata.get("cwd")
            if (not isinstance(cwd, str) or not Path(cwd).is_absolute()
                    or Path(cwd).resolve() != workspace.resolve()):
                raise ControlError("loaded_thread_workspace_mismatch")
        if other != thread_id and metadata.get("status", {}).get("type") != "idle":
            raise ControlError("other_thread_not_idle")


def owned_children(host_pid):
    """Snapshot identities only, without inferring which service owns a child."""
    children = set()
    for root in Path("/proc").iterdir():
        if root.name.isdigit():
            try:
                if root.stat().st_uid != os.getuid():
                    continue
                parent, start = process_state(int(root.name))
                if parent == host_pid:
                    children.add((int(root.name), start))
            except OSError:
                continue
    return children


class ConfigToggle:
    """Two version-checked edits of one user-config key; never overwrite a file."""
    def __init__(self, client, server):
        if not server or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in server):
            raise ControlError("unsupported_config_server_name")
        self.client = client
        self.key = f"mcp_servers.{server}.enabled"
        result = client.call("config/read", {"cwd": str(Path.cwd()), "includeLayers": True})
        config = result.get("config", {})
        self.servers = config.get("mcp_servers", {})
        self.spec = self.servers.get(server, {})
        origins = result.get("origins", {})
        origin = origins.get(self.key, origins.get(f"mcp_servers.{server}.command", {}))
        name = origin.get("name", {})
        path = name.get("file")
        if name.get("type") != "user" or not isinstance(path, str) or not Path(path).is_absolute():
            raise ControlError("user_config_origin_required")
        self.path = Path(path)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ControlError("owned_regular_user_config_required")
        self.original_bytes = self.path.read_bytes()
        raw = tomllib.loads(self.original_bytes.decode())
        raw_spec = raw.get("mcp_servers", {}).get(server, {})
        self.original = raw_spec.get("enabled")
        if self.original is not None and self.original is not True:
            raise ControlError("target_initially_disabled_or_invalid")
        if self.spec.get("enabled", True) is not True or not raw_spec:
            raise ControlError("target_user_config_mismatch")
        self.version = origin.get("version")
        if not isinstance(self.version, str):
            raise ControlError("config_version_required")
        self.disabled_version = None
        self.restored = False

    def write(self, value, version):
        result = self.client.call("config/batchWrite", {
            "filePath": str(self.path), "expectedVersion": version,
            "reloadUserConfig": False,
            "edits": [{"keyPath": self.key, "value": value, "mergeStrategy": "replace"}],
        })
        if result.get("status") != "ok" or not isinstance(result.get("version"), str):
            raise ControlError("config_write_unconfirmed")
        return result["version"]

    def disable(self):
        self.disabled_version = self.write(False, self.version)

    def restore(self):
        if self.disabled_version is None:
            raise ControlError("disable_write_unconfirmed_manual_check_required")
        self.write(self.original, self.disabled_version)
        self.restored = True
        return self.path.read_bytes() == self.original_bytes


def run_recreate(paths, thread_id, server, *, allow_host_wide=False,
                 allow_config_toggle=False, connection=None, timeout=10,
                 factory=Client, all_loaded_targets=False, dry_run=False,
                 state_file=None, thread_id_source="argument", endpoint_source="argument",
                 lock_factory=HostMaintenanceLock):
    report = {
        "action": "recreate", "phase": "preflight", "status": "unverified",
        "reload_scope": "all_mcp_servers_on_all_loaded_host_threads",
        "process_scope": "host_managed_target_service", "dry_run": dry_run,
        "binding_verified": False, "config_restored": False,
        "process_restart_verified": False, "previous_target_exit_verified": False,
        "read_probe_verified": False, "model_tool_visibility": "unverified",
        "process_signals_sent": 0, "refresh_attempts": 0, "refreshes_accepted": 0,
        "disable_write_attempted": False, "restore_write_attempted": False,
        "target_disabled_verified": False,
        "thread_id_source": thread_id_source, "endpoint_source": endpoint_source,
        "binding_diagnostics": [],
        "maintenance_lock_acquired": False,
    }
    timings = ReportTimings(report)
    client = None
    maintenance_lock = None
    toggle = None
    journal = None
    restore_deadline = None

    def persist():
        if journal is not None:
            journal.seek(0)
            json.dump(report, journal, sort_keys=True)
            journal.truncate()
            journal.flush()
            os.fsync(journal.fileno())

    def scope():
        if loaded_threads(client) != threads:
            raise ControlError("loaded_threads_changed")
        other_threads_idle(client, threads, thread_id, workspace=Path.cwd())
        if process_state(host_pid)[1] != host_start:
            raise ControlError("host_process_changed")
        # Metadata RPCs can change the loaded set; observe it last as well.
        if loaded_threads(client) != threads:
            raise ControlError("loaded_threads_changed")

    def refresh():
        report["refresh_attempts"] += 1
        persist()  # A lost response consumes this phase's budget.
        try:
            scope()
        except (ControlError, OSError, ValueError):
            # The journal records intent before any possible send. A known
            # refusal can correct that intent in the final recovery record.
            report["refresh_attempts"] -= 1
            raise
        with timings.measure("host_refresh"):
            client.call("config/mcpServer/reload", None)
        report["refreshes_accepted"] += 1

    try:
        if not thread_id or not connection:
            raise ControlError("explicit_thread_and_test_connection_required")
        if not dry_run and not (allow_host_wide and allow_config_toggle):
            raise ControlError("host_wide_and_config_toggle_consent_required")
        if not dry_run and state_file is None:
            raise ControlError("recovery_journal_required")
        report["phase"] = "host_binding"
        with timings.measure("host_binding"):
            client, _, threads = connect_bound(paths, thread_id, server, timeout, factory,
                                               timings.started + 60, require_catalog=False,
                                               diagnostics=report["binding_diagnostics"])
        if not dry_run:
            report["phase"] = "maintenance_lock"
            maintenance_lock = lock_factory(client.path)
            report["maintenance_lock_acquired"] = True
        report["phase"] = "target_preflight"
        if not 1 <= len(threads) <= 8 or (not all_loaded_targets and len(threads) != 1):
            raise ControlError("explicit_loaded_target_scope_required")
        host_pid = socket_owner(client.path)
        host_start = process_state(host_pid)[1]
        scope()
        toggle = ConfigToggle(client, server)
        _, command, args, cwd = process_configuration(client, server)
        reject_launch_aliases(toggle.servers, server, command, args, cwd)
        report.update(binding_verified=True, loaded_thread_count=len(threads),
                      config_path=str(toggle.path), original_enabled=toggle.original,
                      config_version_before=toggle.version, target_server=server,
                      configured_server_names=sorted(toggle.servers),
                      planned_refreshes=2, preexisting_child_count=len(owned_children(host_pid)))
        if dry_run:
            report.update(phase="complete", status="recreate_plan_verified")
            return report
        # Reserve one RPC window inside the original total budget for restoring
        # an acknowledged disable. Never extend the total deadline or retry an
        # uncertain restoration, even when a prior phase times out.
        restore_deadline = client.deadline
        client.deadline -= timeout
        if client.deadline <= time.monotonic():
            raise ControlError("insufficient_config_restore_budget")
        journal = Path(state_file).open("x", encoding="utf-8")
        baseline = owned_children(host_pid)
        report["preexisting_child_processes"] = sorted(baseline)
        report["phase"] = "disable_config"
        report["disable_write_attempted"] = True
        persist()
        try:
            scope()
        except (ControlError, OSError, ValueError):
            report["disable_write_attempted"] = False
            raise
        toggle.disable()
        report["disabled_config_version"] = toggle.disabled_version
        report["phase"] = "disable_refresh"
        refresh()
        report["phase"] = "disabled_barrier"
        for target in sorted(threads):
            deadline = min(time.monotonic() + 10, client.deadline)
            while True:
                observed = client.call("mcpServerStatus/list", {
                    "threadId": target, "serverName": server,
                    "detail": "toolsAndAuthOnly", "limit": 100,
                })
                data = observed.get("data", [])
                if (not observed.get("nextCursor") and len(data) == 1
                        and data[0].get("name") == server
                        and data[0].get("runtimeStatus") == "disabled"
                        and not data[0].get("tools")):
                    break
                if time.monotonic() >= deadline:
                    raise ControlError("target_disabled_not_verified")
                time.sleep(.1)
        report["target_disabled_verified"] = True
        scope()
        report["phase"] = "restore_config"
        persist()
        client.deadline = restore_deadline
        report["restore_write_attempted"] = True
        report["config_bytes_restored"] = toggle.restore()
        report["config_restored"] = True
        report["phase"] = "restore_refresh"
        refresh()
        scope()
        report["phase"] = "consumer_verification"
        timings.verification()
        readiness_started = time.monotonic()
        readiness_deadline = min(readiness_started + 30, client.deadline)
        report["consumer_readiness_budget_sec"] = max(0, readiness_deadline - readiness_started)
        observed_pids = []
        for target in sorted(threads):
            report["consumer_verification_step"] = "catalog"
            ready_catalog(client, target, server, readiness_deadline, report)
            report["consumer_verification_step"] = "canary"
            remaining = readiness_deadline - time.monotonic()
            if remaining <= 0:
                raise ControlError("consumer_readiness_timeout")
            # One read per consumer, sharing the same readiness deadline.
            observed_pids.append(read_canary(client, target, server, connection,
                                            require_process=True, timeout=remaining))
        if time.monotonic() >= readiness_deadline:
            raise ControlError("consumer_readiness_timeout")
        report["consumer_verification_elapsed_ms"] = round(
            (time.monotonic() - readiness_started) * 1000, 3)
        report["consumer_verification_step"] = "scope"
        scope()
        report["consumer_verification_step"] = "process_identity"
        if len(set(observed_pids)) != len(threads):
            raise ControlError("consumer_process_identity_mismatch")
        matching = set(find_matching_children(host_pid, command, args, cwd))
        identities = {identity for identity in matching if identity[0] in observed_pids}
        if len(identities) != len(threads) or identities.intersection(baseline):
            raise ControlError("fresh_consumer_process_not_verified")
        report.update(status="connection_verified", phase="complete",
                      process_restart_verified=True, read_probe_verified=True,
                      read_probe_verified_thread_count=len(threads),
                      target_processes_after=sorted(identities))
    except (ControlError, OSError, ValueError) as exc:
        report["reason"] = (str(exc) if isinstance(exc, ControlError) else
                            "maintenance_lock_unavailable" if report["phase"] == "maintenance_lock" else
                            "local_operation_failed")
        if isinstance(getattr(client, "last_rpc", None), dict):
            report["last_rpc"] = dict(client.last_rpc)
    finally:
        timings.end_verification()
        # Restore only an acknowledged edit, once, at its exact returned version.
        # Never overwrite concurrent edits or retry an uncertain write/refresh.
        if toggle is not None and toggle.disabled_version is not None and not toggle.restored and not report["restore_write_attempted"]:
            client.deadline = restore_deadline
            report["restore_write_attempted"] = True
            try:
                with timings.measure("config_cleanup"):
                    report["config_bytes_restored"] = toggle.restore()
                    report["config_restored"] = True
            except (ControlError, OSError, ValueError):
                report["config_restore_error"] = "manual_config_reconciliation_required"
        if report["status"] not in {"connection_verified", "recreate_plan_verified"}:
            report["manual_recovery_required"] = report["disable_write_attempted"]
        try:
            if client is not None:
                client.close()
            timings.finish()
            add_next_action(report)
            try:
                persist()
            except OSError:
                report["journal_error"] = "journal_update_failed"
        finally:
            try:
                if journal is not None:
                    journal.close()
            finally:
                if maintenance_lock is not None:
                    maintenance_lock.close()
    return report


def run(paths, thread_id, server, *, action="probe", allow_host_wide=False,
        connection=None, timeout=10, factory=Client, guard_factory=ProcessGuard,
        check_process=False, all_loaded_targets=False, group_guard_factory=ProcessGroupGuard,
        allow_shared_host=False, shared_guard_factory=SharedHostGuard,
        thread_id_source="argument", endpoint_source="argument", lock_factory=HostMaintenanceLock):
    report = {
        "action": action, "status": "unverified", "binding_verified": False,
        "reload_scope": "all_mcp_servers_on_all_loaded_host_threads",
        "reload_attempted": False, "reload_accepted": False,
        "read_probe_verified": False, "process_restart_verified": False,
        "model_tool_visibility": "unverified", "phase": "preflight",
        "process_stop_attempted": False,
        "process_binding_verified": False,
        "process_scope": "all_matching_target_children" if all_loaded_targets else "single_target_child",
        "thread_process_mapping": "unverified",
        "thread_id_source": thread_id_source, "endpoint_source": endpoint_source,
        "binding_diagnostics": [],
        "maintenance_lock_acquired": False,
    }
    timings = ReportTimings(report)
    if allow_shared_host:
        report.update(process_scope="current_thread_exclusive_child",
                      shared_host_mode=True, other_chat_refresh_impact="possible")
    client = None
    guard = None
    maintenance_lock = None
    readiness_deadline = None
    try:
        if action not in {"probe", "refresh", "restart", "verify"} or not thread_id:
            raise ControlError("invalid_action_or_thread")
        if allow_shared_host and (all_loaded_targets or
                not (action == "restart" or (action == "verify" and check_process))):
            raise ControlError("shared_host_requires_restart_or_process_verify")
        if all_loaded_targets and action == "refresh":
            raise ControlError("target_group_not_applicable_to_refresh")
        if action in {"restart", "refresh"} and not allow_host_wide:
            raise ControlError("host_wide_consent_required")
        if action != "probe" and not connection:
            raise ControlError("explicit_test_connection_required")
        report["phase"] = "host_binding"
        with timings.measure("host_binding"):
            client, tools, threads = connect_bound(
                paths, thread_id, server, timeout, factory, timings.started + 60,
                diagnostics=report["binding_diagnostics"])
        report.update(binding_verified=True, loaded_thread_count=len(threads),
                      tool_count=len(tools), catalog_sha256_before=fingerprint(tools))
        if action in {"restart", "refresh"}:
            report["phase"] = "maintenance_lock"
            maintenance_lock = lock_factory(client.path)
            report["maintenance_lock_acquired"] = True
        report["phase"] = "target_preflight"
        if action == "refresh" and len(threads) != 1:
            raise ControlError("single_loaded_thread_required_for_refresh")
        if all_loaded_targets or allow_shared_host:
            if not 1 <= len(threads) <= 8:
                raise ControlError("target_group_thread_budget_exceeded")
            report["phase"] = "shared_host_preflight" if allow_shared_host else "target_group_preflight"
            other_threads_idle(client, threads, thread_id, workspace=Path.cwd())
            for target in sorted(threads):
                catalog(client, target, server, require_connected=True)
            guard = (shared_guard_factory(client, server, threads, thread_id) if allow_shared_host
                     else group_guard_factory(client, server, len(threads)))
            report.update(target_process_count=1 if allow_shared_host else len(guard.members),
                          observed_processes_before=guard.members)
            if all_loaded_targets:
                report["target_processes_before"] = guard.members
            if loaded_threads(client) != threads:
                raise ControlError("loaded_threads_changed")
        if check_process or action == "restart":
            if not (all_loaded_targets or allow_shared_host) and len(threads) != 1:
                raise ControlError("single_loaded_thread_required_for_process_restart")
            if guard is None:
                report["phase"] = "process_binding"
                guard = guard_factory(client, server)
        targets = sorted(threads) if all_loaded_targets or allow_shared_host else [thread_id]

        def shared_scope():
            if loaded_threads(client) != threads:
                raise ControlError("loaded_threads_changed")
            other_threads_idle(client, threads, thread_id, workspace=Path.cwd())
            if loaded_threads(client) != threads:
                raise ControlError("loaded_threads_changed")

        if action in {"restart", "refresh"}:
            report["phase"] = "before_read_probe"
            members = guard.current_members() if guard is not None else None
            pids = []
            for target in targets:
                pids.append(read_canary(client, target, server, connection,
                                       require_process=guard is not None))
            if guard is not None:
                guard.verify_consumers(pids, members)
                report["process_binding_verified"] = True
                if allow_shared_host:
                    report["thread_process_mapping"] = "consumer_pid_verified"
            report["read_probe_before_verified"] = True
            # Scope is Host-wide. Reject other active or unobservable threads;
            # the current agent turn may remain active while invoking this helper.
            report["phase"] = "other_thread_status"
            other_threads_idle(client, threads, thread_id,
                               workspace=Path.cwd() if all_loaded_targets else None)
            if action == "restart":
                if not (all_loaded_targets or allow_shared_host) and len(threads) != 1:
                    raise ControlError("single_loaded_thread_required_for_process_restart")
                report["phase"] = "process_binding"
                if guard is None:
                    guard = guard_factory(client, server)
                if loaded_threads(client) != threads:
                    raise ControlError("loaded_threads_changed")
                report["phase"] = "process_stop"
                report["process_stop_attempted"] = True
                report["status"] = "process_stop_unconfirmed"
                with timings.measure("process_stop"):
                    if allow_shared_host:
                        guard.stop(scope_check=shared_scope)
                    else:
                        guard.stop()
                report["status"] = "process_stopped_refresh_pending"
            if loaded_threads(client) != threads:
                raise ControlError("loaded_threads_changed")
            if allow_shared_host:
                shared_scope()
            report["reload_attempted"] = True
            report["status"] = "reload_outcome_unconfirmed"
            report["phase"] = "host_refresh"
            with timings.measure("host_refresh"):
                client.call("config/mcpServer/reload", None)
            report["reload_accepted"] = True
            report["status"] = "reload_accepted_verification_pending"
            report["phase"] = "after_catalog"
            timings.verification()
            readiness_started = time.monotonic()
            readiness_deadline = min(readiness_started + 30, client.deadline)
            report["consumer_readiness_budget_sec"] = max(0, readiness_deadline - readiness_started)
            if (all_loaded_targets or allow_shared_host) and loaded_threads(client) != threads:
                raise ControlError("loaded_threads_changed_after_refresh")
            for target in targets:
                report["consumer_verification_step"] = "catalog"
                observed = ready_catalog(client, target, server, readiness_deadline, report)
                if target == thread_id:
                    tools = observed
        if action != "probe":
            report["phase"] = "after_read_probe"
            timings.verification()
            members = guard.current_members() if guard is not None else None
            pids = []
            for target in targets:
                remaining = None if readiness_deadline is None else readiness_deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise ControlError("consumer_readiness_timeout")
                report["consumer_verification_step"] = "canary"
                pids.append(read_canary(client, target, server, connection,
                                       require_process=guard is not None, timeout=remaining))
            if readiness_deadline is not None:
                if time.monotonic() >= readiness_deadline:
                    raise ControlError("consumer_readiness_timeout")
                report["consumer_verification_elapsed_ms"] = round(
                    (time.monotonic() - readiness_started) * 1000, 3)
                report["consumer_verification_step"] = "scope"
                if loaded_threads(client) != threads:
                    raise ControlError("loaded_threads_changed_after_refresh")
            if guard is not None:
                guard.verify_consumers(pids, members)
                report["process_binding_verified"] = True
                if allow_shared_host:
                    report["thread_process_mapping"] = "consumer_pid_verified"
                    report["consumer_process_observations"] = guard.observations()
            report["read_probe_verified"] = True
            report["read_probe_verified_thread_count"] = len(targets)
        if guard is not None and action == "restart":
            report["phase"] = "new_process_verification"
            report["process_restart_verified"] = guard.replaced()
            if not report["process_restart_verified"]:
                raise ControlError("process_replacement_not_verified")
            if all_loaded_targets:
                report["target_processes_after"] = guard.replacements
        report.update(status="binding_verified" if action == "probe" else "connection_verified",
                      catalog_sha256_after=fingerprint(tools), phase="complete")
    except (ControlError, OSError) as exc:
        report["reason"] = (str(exc) if isinstance(exc, ControlError) else
                            "maintenance_lock_unavailable" if report["phase"] == "maintenance_lock" else
                            "endpoint_unavailable")
        if isinstance(getattr(client, "last_rpc", None), dict):
            report["last_rpc"] = dict(client.last_rpc)
    finally:
        timings.end_verification()
        try:
            if guard is not None:
                if all_loaded_targets or allow_shared_host:
                    report.update(process_signals_sent=guard.signals_sent,
                                  process_stops_confirmed=guard.stops_confirmed)
                guard.close()
            if client is not None:
                client.close()
            timings.finish()
            add_next_action(report)
        finally:
            if maintenance_lock is not None:
                maintenance_lock.close()
    return report


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "refresh", "restart", "verify", "recreate"], nargs="?", default="probe")
    parser.add_argument("--socket", type=Path, help="Existing owned WebSocket socket; otherwise bounded discovery")
    parser.add_argument("--thread-id")
    parser.add_argument("--server", default="sql-safety-executor-mcp", help="Exact Codex configuration name")
    parser.add_argument("--connection", help="Explicit existing test alias for the constant read-only canary")
    parser.add_argument("--allow-host-wide", action="store_true", help="Consent to the actual global refresh scope")
    parser.add_argument("--check-process", action="store_true", help="Inspect the local candidate; verify also checks its consumer-reported PID")
    parser.add_argument("--all-loaded-targets", action="store_true",
                        help="Explicit whole-target group scope across loaded idle threads; no per-thread PID mapping")
    parser.add_argument("--allow-shared-host", action="store_true",
                        help="Opt in to current-consumer restart with global refresh of other idle threads")
    parser.add_argument("--allow-config-toggle", action="store_true", help="Consent to temporary target enabled-key changes for recreate")
    parser.add_argument("--dry-run", action="store_true", help="Read-only recreate plan; no writes, SQL, signals or refresh")
    parser.add_argument("--state-file", type=Path, help="New recovery journal required for actual recreate")
    parser.add_argument("--timeout", type=float, default=10,
                        help="Ordinary RPC timeout (default 10), in (0, 30]; post-refresh reads share up to 30 seconds")
    args = parser.parse_args()
    thread_id_source = "--thread-id" if args.thread_id is not None else "CODEX_THREAD_ID"
    thread_id = args.thread_id if args.thread_id is not None else os.environ.get("CODEX_THREAD_ID")
    endpoint_source = "--socket" if args.socket is not None else "discovery"
    if not thread_id or not 0 < args.timeout <= 30:
        parser.error("An exact thread ID and a timeout in (0, 30] are required")
    try:
        paths = [args.socket] if args.socket else discover_sockets()
        if args.action == "recreate":
            if args.check_process or args.allow_shared_host:
                parser.error("Process verification and shared-Host options do not apply to recreate")
            report = run_recreate(paths, thread_id, args.server,
                                 allow_host_wide=args.allow_host_wide,
                                 allow_config_toggle=args.allow_config_toggle,
                                 connection=args.connection, timeout=args.timeout,
                                 all_loaded_targets=args.all_loaded_targets,
                                 dry_run=args.dry_run, state_file=args.state_file,
                                 thread_id_source=thread_id_source, endpoint_source=endpoint_source)
        else:
            if args.allow_config_toggle or args.dry_run or args.state_file:
                parser.error("Config toggle, dry-run and state-file options apply only to recreate")
            report = run(paths, thread_id, args.server, action=args.action,
                     allow_host_wide=args.allow_host_wide, connection=args.connection,
                     timeout=args.timeout, check_process=args.check_process,
                     all_loaded_targets=args.all_loaded_targets,
                     allow_shared_host=args.allow_shared_host,
                     thread_id_source=thread_id_source, endpoint_source=endpoint_source)
    except ControlError as exc:
        report = {"status": "unverified", "reason": str(exc), "reload_attempted": False,
                  "binding_verified": False, "phase": "host_binding",
                  "thread_id_source": thread_id_source, "endpoint_source": endpoint_source,
                  "binding_diagnostics": [{"phase": "endpoint_discovery", "reason": str(exc)}],
                  "timings_ms": {"total": round((time.monotonic() - started) * 1000, 3)}}
        add_next_action(report)
    print(json.dumps(report))
    return 0 if report["status"] in {"binding_verified", "connection_verified", "recreate_plan_verified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
