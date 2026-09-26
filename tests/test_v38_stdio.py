"""Actual stdio negotiations, sealed continuation and denial before database I/O."""

import sys
import time
from dataclasses import replace
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.types import ElicitResult, InputRequiredResult
from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.queries import query
from sql_safety_executor.core.schema import list_tables
from sql_safety_executor.core.types import NullContext, OperationError
from tests.test_v38_mrtr import status, SKILL, PARAMS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,version", [("auto", "2026-07-28"), ("legacy", "2025-11-25")]
)
async def test_stdio_protocols_and_residual_dotenv(bundle, tmp_path, mode, version):
    _, conns, _, save = bundle
    conns["connections"]["demo"]["read"] = {"mode": "all"}
    path = save()
    # This would break Pydantic settings if FastMCP tried reading the .env file.
    (tmp_path / ".env").write_text(
        "FASTMCP_STRICT_INPUT_VALIDATION=invalid_boolean\nDB_TYPE=mysql\n"
    )
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "sql_safety_executor", "serve", "--config", str(path)],
        cwd=str(tmp_path),
    )
    async with Client(transport, mode=mode) as client:
        assert client.protocol_version == version
        names = {t.name for t in await client.list_tools()}
        assert "execute_mutation_skill" not in names
        assert "request_mutation_approval" not in names
        assert (await client.call_tool("list_connections", {})).structured_content[
            "default_connection_id"
        ] == "demo"
        assert (
            await client.call_tool("query", {"sql": "SELECT 1 AS one"})
        ).structured_content["data"] == [{"one": 1}]
        assert "connection_id" in str(await client.get_prompt("sql_assistant"))


@pytest.mark.asyncio
async def test_real_stdio_mrtr(mrtr_server, tmp_path):
    approved = []

    async def human(message, *args):
        assert status(mrtr_server) == "pending"
        approved.append(message)
        return {"approve": True}

    path = mrtr_server.gateway_runtime.config.path
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "sql_safety_executor", "serve", "--config", str(path)],
        cwd=str(tmp_path),
    )
    async with Client(transport, elicitation_handler=human) as client:
        result = await client.call_tool(
            "request_mutation_approval", {"skill_name": SKILL, "params": PARAMS}
        )
        assert result.structured_content["execution_outcome"] == "committed"
    assert len(approved) == 1 and status(mrtr_server) == "confirmed"


@pytest.mark.asyncio
async def test_wire_state_is_sealed_and_tampering_cannot_execute(mrtr_server):
    async def human(*args):
        return {"approve": True}

    async with Client(mrtr_server, elicitation_handler=human) as client:
        args = {"skill_name": SKILL, "params": PARAMS, "connection_id": "demo"}
        first = await client.session.call_tool(
            name="request_mutation_approval", arguments=args, allow_input_required=True
        )
        assert isinstance(first, InputRequiredResult)
        assert "preview_token" not in first.request_state
        assert status(mrtr_server) == "pending"
        yes = {"approval": ElicitResult(action="accept", content={"approve": True})}
        changed = first.request_state[:-2] + "XX"
        from mcp.shared.exceptions import MCPError

        with pytest.raises(MCPError, match="requestState"):
            invalid = await client.session.call_tool(
                name="request_mutation_approval",
                arguments=args,
                input_responses=yes,
                request_state=changed,
                allow_input_required=True,
            )
        assert status(mrtr_server) == "pending"
        final = await client.session.call_tool(
            name="request_mutation_approval",
            arguments=args,
            input_responses=yes,
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert final.structured_content["execution_outcome"] == "committed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "approve_after,expected", [(1199, "confirmed"), (1201, "pending")]
)
async def test_wire_ttl_matches_config_and_reasking_does_not_extend_proposal(
    mrtr_server, monkeypatch, approve_after, expected
):
    config = mrtr_server.gateway_runtime.config
    mutation = config.skills.mutation
    config = replace(
        config,
        skills=config.skills.model_copy(
            update={
                "mutation": mutation.model_copy(
                    update={
                        "preview": mutation.preview.model_copy(
                            update={"ttl_seconds": 1200}
                        )
                    }
                )
            }
        ),
    )
    server = create_server(config)
    started = time.time()
    now = started
    monkeypatch.setattr("time.time", lambda: now)

    async def human(*args):
        return {"approve": True}

    try:
        async with Client(server, elicitation_handler=human) as client:
            args = {"skill_name": SKILL, "params": PARAMS, "connection_id": "demo"}
            first = await client.session.call_tool(
                name="request_mutation_approval",
                arguments=args,
                allow_input_required=True,
            )
            assert isinstance(first, InputRequiredResult)
            # Beyond the SDK's default 600-second envelope lifetime, still within
            # the configured approval window. Missing answers must reuse the review.
            now = started + 601
            again = await client.session.call_tool(
                name="request_mutation_approval",
                arguments=args,
                request_state=first.request_state,
                allow_input_required=True,
            )
            assert isinstance(again, InputRequiredResult)
            assert again.input_requests == first.input_requests
            now = started + approve_after
            final = await client.session.call_tool(
                name="request_mutation_approval",
                arguments=args,
                request_state=again.request_state,
                allow_input_required=True,
                input_responses={
                    "approval": ElicitResult(action="accept", content={"approve": True})
                },
            )
            assert not isinstance(final, InputRequiredResult)
            assert final.is_error is (expected == "pending")
            assert status(server) == expected
            assert len(server.gateway_runtime.tokens) == 0
    finally:
        server.gateway_runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read", [{"mode": "deny"}, {"mode": "allowlist", "tables": []}]
)
async def test_no_read_grant_blocks_queries_and_schema_without_io(bundle, read):
    _, conns, _, save = bundle
    conns["connections"]["demo"]["read"] = read
    path = save()
    server = create_server(load_config(path))
    r = server.gateway_runtime
    try:
        result = await query(r, "SELECT 1", NullContext())
        assert not result.structured_content["success"]
        with pytest.raises(OperationError):
            await list_tables(r, NullContext())
        assert not path.with_name("db.sqlite").exists()
    finally:
        r.close()


@pytest.mark.asyncio
async def test_two_instances_config_catalog_tokens_and_adapters_are_isolated(
    mrtr_server,
):
    other = create_server(mrtr_server.gateway_runtime.config)
    a, b = mrtr_server.gateway_runtime, other.gateway_runtime
    try:
        assert a.catalog is not b.catalog
        assert (
            a.catalog.get_skills_cache()[SKILL]
            is not b.catalog.get_skills_cache()[SKILL]
        )
        assert a.tokens is not b.tokens
        assert a.diagnostics is not b.diagnostics
        assert a.registry.get_adapter() is not b.registry.get_adapter()
        assert a.registry.get_adapter()._engine is None
        a.registry.get_adapter().execute("SELECT 1")
        a.close()
        assert not a.registry._adapters
        assert b.registry.get_adapter().execute("SELECT 1")
    finally:
        b.close()


from tests.test_v38_config import bundle as bundle
from tests.test_v38_mrtr import mrtr_server as mrtr_server
