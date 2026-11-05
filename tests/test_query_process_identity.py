"""Query metadata identifies its serving process in both protocol modes."""
import os

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_query_reports_process_identity_without_changing_data(bundle, mode):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            result = await client.call_tool("query", {
                "sql": "SELECT 1 AS codex_mcp_restart_canary", "connection_id": "demo",
            })
            assert result.structured_content["success"]
            assert result.structured_content["data"] == [{"codex_mcp_restart_canary": 1}]
            assert result.meta["server_pid"] == os.getpid()
    finally:
        server.gateway_runtime.close()
