#!/usr/bin/env python3
"""Validation-only transparent stdio bridge recording metadata, never SQL/params.

This is instrumentation, not a protocol implementation. Bytes are forwarded
unchanged. Use only with an isolated validation deployment, not as a service.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


async def main(args):
    process = await asyncio.create_subprocess_exec(
        args.python,
        "-m",
        "sql_safety_executor",
        "serve",
        "--config",
        str(args.config),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )

    def record(raw, direction):
        try:
            value = json.loads(raw)
            params = value.get("params") or {}
            result = value.get("result") or {}
            item = {
                "direction": direction,
                "method": value.get("method"),
                "request_id": value.get("id"),
            }
            if value.get("method") in ("initialize", "server/discover"):
                item["protocol_version"] = params.get("protocolVersion")
                item["elicitation"] = params.get("capabilities", {}).get("elicitation")
            if result.get("protocolVersion"):
                item["protocol_version"] = result["protocolVersion"]
            if value.get("method") == "tools/call":
                item["tool_name"] = params.get("name")
                item["connection_id"] = params.get("arguments", {}).get("connection_id")
                item["continuation"] = "requestState" in params
            if "tools" in result:
                item["tools"] = [t["name"] for t in result["tools"]]
            if "resultType" in result:
                item["result_type"] = result["resultType"]
            if "isError" in result:
                item["is_error"] = result["isError"]
            with args.record.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item) + "\n")
        except (ValueError, AttributeError, TypeError, KeyError):
            pass

    async def incoming():
        # Thread-backed reads allow all responses/notifications to flow meanwhile.
        while line := await asyncio.to_thread(sys.stdin.buffer.readline):
            record(line, "host_to_server")
            process.stdin.write(line)
            await process.stdin.drain()
        process.stdin.close()

    async def outgoing():
        while line := await process.stdout.readline():
            record(line, "server_to_host")
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    try:
        await asyncio.gather(incoming(), outgoing())
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
