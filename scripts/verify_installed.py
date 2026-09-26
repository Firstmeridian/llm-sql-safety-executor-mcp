#!/usr/bin/env python3
"""Run with an isolated wheel interpreter; validate imports/prompts/stdio from /tmp."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


async def check(directory):
    from sql_safety_executor.mcp.bootstrap import prepare_framework

    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    import sql_safety_executor

    assert "site-packages" in sql_safety_executor.__file__, sql_safety_executor.__file__
    config = directory / "server.toml"
    config.write_text(
        'schema_version=1\n[files]\nconnections="connections.toml"\n[server]\ndefault_connection="test"\n'
    )
    (directory / "connections.toml").write_text(
        'schema_version=1\n[connections.test]\ntype="sqlite"\nsqlite.path=":memory:"\nread.mode="all"\n'
    )
    (directory / ".env").write_text("FASTMCP_STRICT_INPUT_VALIDATION=invalid\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sql_safety_executor",
            "config",
            "check",
            "--config",
            str(config),
        ],
        check=True,
        cwd=directory,
    )
    for mode, protocol in [("auto", "2026-07-28"), ("legacy", "2025-11-25")]:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "sql_safety_executor", "serve", "--config", str(config)],
            cwd=str(directory),
        )
        async with Client(transport, mode=mode) as client:
            assert client.protocol_version == protocol
            assert "connection_id" in str(await client.get_prompt("sql_assistant"))
            result = await client.call_tool("query", {"sql": "SELECT 1 AS value"})
            assert result.structured_content["data"] == [{"value": 1}]
    print(
        json.dumps(
            {
                "wheel": sql_safety_executor.__version__,
                "outside_repository": True,
                "protocols": ["2026-07-28", "2025-11-25"],
                "packaged_prompts": True,
            }
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sql-wheel-") as folder:
        os.chdir(folder)
        asyncio.run(check(Path(folder)))
