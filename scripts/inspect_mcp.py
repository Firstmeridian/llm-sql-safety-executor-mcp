#!/usr/bin/env python3
"""Inspect protocol, registered tools, prompts and configured targets (no DB I/O)."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
from sql_safety_executor.mcp.bootstrap import prepare_framework

prepare_framework()
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def inspect(config, mode):
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "sql_safety_executor", "serve", "--config", str(config.resolve())],
    )
    async with Client(transport, mode=mode) as client:
        tools = await client.list_tools()
        result = await client.call_tool("list_connections", {})
        print(
            json.dumps(
                {
                    "protocol_version": client.protocol_version,
                    "tools": [
                        tool.model_dump(mode="json", by_alias=True) for tool in tools
                    ],
                    "connections": result.structured_content,
                    "instructions": client.instructions,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--mode", choices=["auto", "legacy"], default="auto")
    args = parser.parse_args()
    asyncio.run(inspect(args.config, args.mode))
