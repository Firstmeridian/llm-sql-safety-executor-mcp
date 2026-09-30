"""Real process restart invalidates sealed approvals without disabling new ones."""

import json
import os
import sys
from datetime import datetime, timezone

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.shared.exceptions import MCPError
from mcp.types import ElicitResult, InputRequiredResult

from tests.test_v38_config import bundle as bundle
from tests.test_v38_mrtr import PARAMS, SKILL, mrtr_server as mrtr_server, status


@pytest.mark.skipif(os.name != "posix", reason="PID liveness check uses POSIX signal 0")
async def test_real_process_restart_rejects_old_approval_but_accepts_new(
    mrtr_server, tmp_path
):
    # Only record the child's PID, then run the unmodified production entry point.
    launcher = tmp_path / "record_pid.py"
    launcher.write_text(
        "import os, runpy, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv.pop(1)).write_text(str(os.getpid()))\n"
        "runpy.run_module('sql_safety_executor', run_name='__main__')\n",
        encoding="utf-8",
    )
    config = mrtr_server.gateway_runtime.config.path

    def transport(label):
        return StdioTransport(
            command=sys.executable,
            args=[str(launcher), str(tmp_path / f"{label}.pid"),
                  "serve", "--config", str(config)],
            cwd=str(tmp_path),
            keep_alive=False,
        )

    async def must_not_auto_approve(*args):
        pytest.fail("The test must explicitly submit each continuation")

    args = {"skill_name": SKILL, "params": PARAMS, "connection_id": "demo"}
    yes = {"approval": ElicitResult(action="accept", content={"approve": True})}
    async with Client(transport("before"), elicitation_handler=must_not_auto_approve) as client:
        assert client.protocol_version == "2026-07-28"
        first = await client.session.call_tool(
            "request_mutation_approval", args, allow_input_required=True
        )
        assert isinstance(first, InputRequiredResult)
        review = json.loads(first.input_requests["approval"].params.message.split("\n", 1)[1])
        expires = datetime.fromisoformat(review["expires_at"])
        old_pid = int((tmp_path / "before.pid").read_text())
        assert status(mrtr_server) == "pending"

    # Context exit must actually reap the process, not just open another session.
    with pytest.raises(ProcessLookupError):
        os.kill(old_pid, 0)

    async with Client(transport("after"), elicitation_handler=must_not_auto_approve) as client:
        new_pid = int((tmp_path / "after.pid").read_text())
        assert new_pid != old_pid
        assert client.protocol_version == "2026-07-28"
        assert datetime.now(timezone.utc) < expires, "Must reject before TTL expiry"
        with pytest.raises(MCPError, match="requestState"):
            await client.session.call_tool(
                "request_mutation_approval", args,
                request_state=first.request_state, input_responses=yes,
                allow_input_required=True,
            )
        assert datetime.now(timezone.utc) < expires
        assert status(mrtr_server) == "pending"

        fresh = await client.session.call_tool(
            "request_mutation_approval", args, allow_input_required=True
        )
        assert isinstance(fresh, InputRequiredResult)
        assert status(mrtr_server) == "pending"
        result = await client.session.call_tool(
            "request_mutation_approval", args,
            request_state=fresh.request_state, input_responses=yes,
            allow_input_required=True,
        )
        assert result.structured_content["execution_outcome"] == "committed"
        assert result.structured_content["result"]["rowcount"] == 1
        assert status(mrtr_server) == "confirmed"

    with pytest.raises(ProcessLookupError):
        os.kill(new_pid, 0)
