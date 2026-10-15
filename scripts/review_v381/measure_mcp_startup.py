"""Measure configured stdio readiness, no query or global service restart."""
import asyncio
import json
from pathlib import Path
import sys
import time
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"docs/validation/v3.8/phase123_2026_10_14"
async def main():
    samples=[]
    for _ in range(3):
        transport=StdioTransport(command=sys.executable,
            args=["-m","sql_safety_executor","serve","--config",str(ROOT/"config/server.toml")],
            cwd=str(ROOT),env={"PYTHONPATH":str(ROOT/"src")},keep_alive=False)
        started=time.perf_counter_ns()
        async with Client(transport,mode="auto") as client:
            ready=(time.perf_counter_ns()-started)/1e6
            tools=await client.list_tools()
            samples.append({"initialize_ms":ready,"initialize_and_tools_ms":(time.perf_counter_ns()-started)/1e6,
                "protocol":client.protocol_version,"tool_count":len(tools)})
    record={"samples":samples,"scope":"Three isolated current-source stdio instances, configuration only/no database query; resident not restarted",
        "documented_optional_grace_ms":1000,"causality":"Readiness exceeding optional grace is consistent with observed missing tools, not a direct trace of Codex internal scheduling"}
    (OUT/"mcp_startup.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(samples))
asyncio.run(main())
