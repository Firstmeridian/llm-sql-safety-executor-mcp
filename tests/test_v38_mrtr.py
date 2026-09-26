"""MRTR state-machine and real FastMCP protocol tests against temporary SQLite."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult as HostAnswer
from mcp.types import ElicitResult, InputRequiredResult

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.types import NullContext, OperationError
from sql_safety_executor.mcp.mrtr import request_approval

SKILL = "sample-update-order-status"
PARAMS = {"order_id": 1, "new_status": "confirmed"}


@pytest.fixture
def mrtr_server(bundle):
    _, connections, _, save = bundle
    target = connections["connections"]["demo"]
    target["read"] = {"mode": "allowlist", "tables": ["orders"]}
    target["mutation"] = {"enabled": True, "skills": [SKILL]}
    cfg = load_config(save(use_skills=True))
    with sqlite3.connect(cfg.connections["demo"].sqlite_database_path) as db:
        db.execute(
            "CREATE TABLE orders(id INTEGER PRIMARY KEY, order_date TEXT, amount REAL, total_amount REAL, status TEXT)"
        )
        db.execute("INSERT INTO orders VALUES(1,'2026-01-15',10,10,'pending')")
    server = create_server(cfg)
    yield server
    server.gateway_runtime.close()


class Context(NullContext):
    def __init__(self, state=None, answer=None, protocol="2026-07-28", form=True):
        self.request_context = SimpleNamespace(protocol_version=protocol)
        self.session = SimpleNamespace(
            client_capabilities=SimpleNamespace(
                elicitation=SimpleNamespace(form={} if form else None)
            )
        )
        self.request_state = state
        self.input_responses = answer


def status(server):
    with sqlite3.connect(
        server.gateway_runtime.config.connections["demo"].sqlite_database_path
    ) as db:
        return db.execute("SELECT status FROM orders WHERE id=1").fetchone()[0]


async def request(server, ctx=None, params=None, connection_id="demo"):
    return await request_approval(
        server.gateway_runtime,
        SKILL,
        PARAMS if params is None else params,
        ctx or Context(),
        connection_id,
    )


@pytest.mark.asyncio
async def test_prepare_reask_same_snapshot_and_atomic_once(mrtr_server, monkeypatch):
    server = mrtr_server
    first = await request(server)
    assert isinstance(first, InputRequiredResult)
    assert status(server) == "pending"
    assert len(server.gateway_runtime.tokens) == 1
    review = first.input_requests["approval"].params.message
    raw_token = json.loads(first.request_state)["preview_token"]
    assert raw_token not in review
    # Waiting leaves no row lock / transaction behind.
    with sqlite3.connect(
        server.gateway_runtime.config.connections["demo"].sqlite_database_path,
        timeout=0.1,
    ) as db:
        db.execute("UPDATE orders SET amount=20 WHERE id=1")
    meta = server.gateway_runtime.catalog.get_skills_cache()[SKILL]
    monkeypatch.setattr(
        meta._mutation_class,
        "preview",
        lambda *_: pytest.fail("continuation re-ran preview"),
    )
    again = await request(server, Context(first.request_state))
    assert again.input_requests["approval"].params.message == review
    assert len(server.gateway_runtime.tokens) == 1
    answer = {"approval": ElicitResult(action="accept", content={"approve": True})}
    results = await asyncio.gather(
        request(server, Context(first.request_state, answer)),
        request(server, Context(first.request_state, answer)),
        return_exceptions=True,
    )
    assert sum(not isinstance(x, Exception) for x in results) == 1
    winner = next(x for x in results if not isinstance(x, Exception))
    assert winner.structured_content["execution_outcome"] == "committed"
    assert status(server) == "confirmed"
    assert len(server.gateway_runtime.tokens) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,content",
    [("decline", None), ("cancel", None), ("accept", {"approve": False})],
)
async def test_decline_cancel_close_proposal(mrtr_server, action, content):
    first = await request(mrtr_server)
    ctx = Context(
        first.request_state, {"approval": ElicitResult(action=action, content=content)}
    )
    result = await request(mrtr_server, ctx)
    assert result.structured_content["execution_outcome"] == "not_executed"
    assert status(mrtr_server) == "pending"
    with pytest.raises(OperationError):
        await request(mrtr_server, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["true", 1, None, {}, []])
async def test_approval_boolean_is_strict(mrtr_server, value):
    first = await request(mrtr_server)
    again = await request(
        mrtr_server,
        Context(
            first.request_state,
            {
                "approval": ElicitResult.model_construct(
                    action="accept", content={"approve": value}
                )
            },
        ),
    )
    assert isinstance(again, InputRequiredResult)
    assert again.request_state == first.request_state
    assert status(mrtr_server) == "pending"


@pytest.mark.asyncio
async def test_tampered_params_target_expiry_restart_and_unsolicited(
    mrtr_server, monkeypatch
):
    first = await request(mrtr_server)
    yes = {"approval": ElicitResult(action="accept", content={"approve": True})}
    for ctx, params, alias in [
        (Context(None, yes), PARAMS, "demo"),
        (Context(first.request_state, yes), {**PARAMS, "order_id": 2}, "demo"),
        (Context(first.request_state, yes), PARAMS, "unknown"),
        (Context("tampered", yes), PARAMS, "demo"),
    ]:
        with pytest.raises(OperationError):
            await request(mrtr_server, ctx, params, alias)
    other = create_server(mrtr_server.gateway_runtime.config)
    try:
        with pytest.raises(OperationError):
            await request(other, Context(first.request_state, yes))
    finally:
        other.gateway_runtime.close()
    import time

    future = time.time() + 1000
    monkeypatch.setattr("sql_safety_executor.mcp.mrtr.time.time", lambda: future)
    with pytest.raises(OperationError):
        await request(mrtr_server, Context(first.request_state, yes))
    assert status(mrtr_server) == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,form", [("2025-11-25", True), ("2026-07-28", False)])
async def test_unsupported_client_rejected_before_preview(mrtr_server, protocol, form):
    with pytest.raises(OperationError):
        await request(mrtr_server, Context(protocol=protocol, form=form))
    assert not len(mrtr_server.gateway_runtime.tokens)
    assert status(mrtr_server) == "pending"


@pytest.mark.asyncio
async def test_oversize_review_rejects_and_revokes(mrtr_server, monkeypatch):
    meta = mrtr_server.gateway_runtime.catalog.get_skills_cache()[SKILL]
    original = meta._mutation_class.preview

    def large(self, params):
        return {**original(self, params), "extra": "中" * 23000}

    monkeypatch.setattr(meta._mutation_class, "preview", large)
    with pytest.raises(OperationError, match="64 KiB"):
        await request(mrtr_server)
    assert len(mrtr_server.gateway_runtime.tokens) == 0
    assert status(mrtr_server) == "pending"


@pytest.mark.asyncio
async def test_imperative_rejected(mrtr_server, monkeypatch):
    monkeypatch.setattr(
        mrtr_server.gateway_runtime.catalog.get_skills_cache()[SKILL],
        "_managed_mutation_plan",
        None,
    )
    with pytest.raises(OperationError, match="managed"):
        await request(mrtr_server)
    assert not len(mrtr_server.gateway_runtime.tokens)


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_reference_host_real_mrtr_roundtrip(mrtr_server, approve):
    seen = []

    async def handler(message, response_type, params, context):
        assert status(mrtr_server) == "pending"
        seen.append(message)
        return HostAnswer(action="accept", content={"approve": approve})

    async with Client(mrtr_server, elicitation_handler=handler) as client:
        assert client.protocol_version == "2026-07-28"
        result = await client.call_tool(
            "request_mutation_approval", {"skill_name": SKILL, "params": PARAMS}
        )
        assert result.structured_content["execution_outcome"] == (
            "committed" if approve else "not_executed"
        )
    assert len(seen) == 1
    assert status(mrtr_server) == ("confirmed" if approve else "pending")


@pytest.mark.asyncio
async def test_legacy_host_retains_preview_execute_and_refuses_mrtr(mrtr_server):
    async with Client(mrtr_server, mode="legacy") as client:
        assert client.protocol_version == "2025-11-25"
        result = await client.call_tool(
            "request_mutation_approval",
            {"skill_name": SKILL, "params": PARAMS},
            raise_on_error=False,
        )
        assert result.is_error
        preview = await client.call_tool(
            "execute_mutation_skill", {"skill_name": SKILL, "params": PARAMS}
        )
        token = preview.structured_content["preview_token"]
        result = await client.call_tool(
            "execute_mutation_skill",
            {
                "skill_name": SKILL,
                "params": PARAMS,
                "confirm": True,
                "preview_token": token,
            },
        )
        assert result.structured_content["execution_outcome"] == "committed"


@pytest.mark.asyncio
async def test_waiting_telemetry_is_not_business_success(mrtr_server, tmp_path):
    from dataclasses import replace
    from sql_safety_executor.observability.telemetry import ToolTelemetryMiddleware

    runtime = mrtr_server.gateway_runtime
    telemetry = runtime.config.server.observability.telemetry.model_copy(
        update={"enabled": True, "path": str(tmp_path / "events.jsonl")}
    )
    runtime.config = replace(
        runtime.config,
        server=runtime.config.server.model_copy(
            update={
                "observability": runtime.config.server.observability.model_copy(
                    update={"telemetry": telemetry}
                )
            }
        ),
    )
    mrtr_server.add_middleware(ToolTelemetryMiddleware(runtime))

    async def human(*args):
        return {"approve": False}

    async with Client(mrtr_server, elicitation_handler=human) as client:
        await client.call_tool(
            "request_mutation_approval", {"skill_name": SKILL, "params": PARAMS}
        )
    records = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert len(records) == 2
    assert records[0]["phase"] == "awaiting_approval" and records[0]["success"] is None
    assert records[1]["success"] is False
    for record in records:
        assert (
            not {"params", "sql", "preview_token", "request_state", "preview_token_id"}
            & record.keys()
        )

from tests.test_v38_config import bundle as bundle
