#!/usr/bin/env python3
"""Read-only alias; use restart_codex_mcp.py for the complete helper."""

import argparse
import json
import os
from pathlib import Path

try:  # Direct script invocation versus repository test import.
    from restart_codex_mcp import Client, ControlError, run
except ModuleNotFoundError:
    from scripts.dev.restart_codex_mcp import Client, ControlError, run

ProbeError = ControlError


def probe(socket_path, thread_id, server_name, timeout=5, factory=Client):
    report = run([Path(socket_path)], thread_id, server_name, timeout=timeout, factory=factory)
    report.update(reload_requested=False, restart_verified=False, client_readiness="unverified")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--server", default="sql-safety-executor-mcp")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    if not args.thread_id or not 0 < args.timeout <= 30:
        parser.error("An exact thread ID and a timeout in (0, 30] are required")
    report = probe(args.socket, args.thread_id, args.server, args.timeout)
    print(json.dumps(report))
    return 0 if report["binding_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
