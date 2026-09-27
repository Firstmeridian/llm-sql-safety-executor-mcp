"""Regressions from the independent review of 1be44b4, using production paths."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import ElicitResult, InputRequiredResult

from examples.manual_mutation_approval import (
    ApprovalDecision,
    MRTRApprovalProvider,
    MutationRequest,
)
from sql_safety_executor import create_server, load_config
from sql_safety_executor.config.loader import ConfigError
from tests.support import ROOT
from tests.test_v38_config import bundle as bundle

MUTATION = "sample-update-order-status"
QUERY = "tableless-query"
PARAMS = {"order_id": 1, "new_status": "confirmed"}


@pytest.fixture
def reviewed_server(bundle, tmp_path):
    main, connections, skills, save = bundle
    directory = tmp_path / "skills"
    shutil.copytree(ROOT / "skills", directory)
    query = directory / QUERY
    query.mkdir()
    (query / "skill_def.md").write_text(
        "---\nname: tableless-query\nversion: '1.0'\n"
        "description: Tableless query policy probe\ntype: query\n"
        "source: query.sql\nrisk: low\nprofiles: [demo]\nparams: {}\n---\n",
        encoding="utf-8",
    )
    (query / "query.sql").write_text("SELECT 1 AS value", encoding="utf-8")
    skills["skills"]["directory"] = str(directory)
    skills["skills"]["readiness"] = {"check_schema": False}
    target = connections["connections"]["demo"]
    target["read"] = {"mode": "all"}
    target["mutation"] = {"enabled": True, "skills": [MUTATION]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT)")
        db.execute("INSERT INTO orders VALUES(1, 'pending')")
    servers = []

    def build(*, profiles=(), read=None, telemetry=False):
        skills["skills"]["policy"] = {"exclude_profiles": list(profiles)}
        if read is not None:
            target["read"] = read
        if telemetry:
            # The default must never be contacted or used as a fallback identity.
            main["server"]["default_connection"] = "primary"
            connections["connections"]["primary"] = {
                "type": "mysql",
                "mysql": {
                    "host": "unused.invalid", "user": "unused", "database": "unused",
                    "password": {"value": "test-only"},
                },
            }
            main["observability"] = {
                "telemetry": {"enabled": True, "path": "events.jsonl"}
            }
        server = create_server(load_config(save(use_skills=True)))
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.gateway_runtime.close()


def _status(server):
    with sqlite3.connect(
        server.gateway_runtime.config.connections["demo"].sqlite_database_path
    ) as db:
        return db.execute("SELECT status FROM orders WHERE id=1").fetchone()[0]


@pytest.mark.parametrize("profiles", [["DEMO"], [" demo "], ["Demo", "demo", " DEMO "]])
async def test_profile_policy_is_normalized_and_enforced(reviewed_server, profiles):
    server = reviewed_server(profiles=profiles)
    assert server.gateway_runtime.config.skills.policy.exclude_profiles == ("demo",)
    async with Client(server, elicitation_handler=lambda *a: None) as client:
        visible = await client.call_tool("list_skills", {"available_only": True})
        assert visible.structured_content["skills"] == []
        full = await client.call_tool("list_skills", {"available_only": False})
        assert full.structured_content["skills"]
        assert all(not s["profile_allowed"] for s in full.structured_content["skills"])
        for skill in (QUERY, MUTATION):
            detail = await client.call_tool("get_skill_detail", {"skill_name": skill})
            assert detail.structured_content["skill"]["executable"] is False
            assert "exclude_profiles" in detail.structured_content["usage_hint"]
        for tool, args in [
            ("execute_query_skill", {"skill_name": QUERY, "params": {}}),
            ("execute_mutation_skill", {"skill_name": MUTATION, "params": PARAMS}),
            ("execute_mutation_skill", {
                "skill_name": MUTATION, "params": PARAMS,
                "confirm": True, "preview_token": "unissued-token",
            }),
            ("request_mutation_approval", {"skill_name": MUTATION, "params": PARAMS}),
        ]:
            result = await client.call_tool(tool, args, raise_on_error=False)
            assert result.is_error or result.structured_content["success"] is False
            assert "exclude_profiles" in str(result)
    assert _status(server) == "pending"
    assert len(server.gateway_runtime.tokens) == 0


@pytest.mark.parametrize("profiles", [[""], [" \t"], [1], [True]])
def test_invalid_profile_entries_fail_in_production_loader(bundle, profiles):
    _, _, skills, save = bundle
    skills["skills"]["policy"] = {"exclude_profiles": profiles}
    with pytest.raises(ConfigError, match="exclude_profiles"):
        load_config(save(use_skills=True))


@pytest.mark.parametrize("read,allowed", [
    ({"mode": "deny"}, False),
    ({"mode": "allowlist", "tables": []}, False),
    ({"mode": "allowlist", "tables": ["orders"]}, True),
    ({"mode": "all"}, True),
])
async def test_tableless_query_discovery_matches_execution(reviewed_server, read, allowed, monkeypatch):
    server = reviewed_server(read=read)
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    monkeypatch.setattr(adapter, "get_tables", lambda: pytest.fail("unexpected metadata I/O"))
    if not allowed:
        monkeypatch.setattr(adapter, "execute", lambda *a, **k: pytest.fail("denied SQL ran"))
    async with Client(server) as client:
        visible = await client.call_tool("list_skills", {"available_only": True, "search": QUERY})
        assert bool(visible.structured_content["skills"]) is allowed
        full = await client.call_tool("list_skills", {"available_only": False, "search": QUERY})
        row = full.structured_content["skills"][0]
        assert row["executable"] is allowed and row["policy_allowed"] is allowed
        detail = await client.call_tool("get_skill_detail", {"skill_name": QUERY})
        assert detail.structured_content["skill"]["executable"] is allowed
        if not allowed:
            assert "read policy" in detail.structured_content["usage_hint"]
        result = await client.call_tool(
            "execute_query_skill", {"skill_name": QUERY, "params": {}}, raise_on_error=False
        )
        assert result.is_error is not allowed
        # Independent explicit write gates still authorize this Mutation Skill.
        mutation = await client.call_tool("get_skill_detail", {"skill_name": MUTATION})
        assert mutation.structured_content["skill"]["executable"] is True


@pytest.mark.parametrize("command", ["check", "explain"])
@pytest.mark.parametrize("case,code", [
    ("secret", "exactly_one_secret_source_required"),
    ("tables", "tables_require_allowlist_mode"),
    ("union", "union_requires_explicit_table_scope"),
    ("backend", "sqlite_settings_required_mysql_forbidden"),
    ("mrtr", "mrtr_requires_skills_and_mutations"),
])
def test_cli_reports_safe_semantic_error_codes(bundle, command, case, code):
    _, connections, skills, save = bundle
    target = connections["connections"]["demo"]
    marker = "SENSITIVE_VALUE_MUST_NOT_APPEAR"
    mysql = {"host": "db", "user": "u", "database": "db", "password": {"value": marker}}
    if case == "secret":
        mysql["password"]["env"] = marker
        target.clear()
        target.update(type="mysql", mysql=mysql)
    elif case == "tables":
        target["read"] = {"mode": "deny", "tables": [marker]}
    elif case == "union":
        target["read"] = {"mode": "deny", "allow_union": True}
    elif case == "backend":
        target["mysql"] = mysql
    else:
        skills["skills"]["enabled"] = False
    path = save(use_skills=True)
    result = subprocess.run(
        [sys.executable, "-m", "sql_safety_executor", "config", command, "--config", str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert code in output
    assert marker not in output and "Traceback" not in output


@pytest.mark.parametrize("action,approve,phase", [
    ("accept", True, "complete"), ("accept", False, "approval_declined"),
    ("decline", None, "approval_declined"), ("cancel", None, "approval_cancelled"),
])
async def test_real_mrtr_telemetry_tracks_nondefault_target(reviewed_server, tmp_path, action, approve, phase):
    server = reviewed_server(telemetry=True)
    args = {"skill_name": MUTATION, "params": PARAMS, "connection_id": "demo"}
    async with Client(server, elicitation_handler=lambda *a: None) as client:
        first = await client.session.call_tool("request_mutation_approval", args, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        again = await client.session.call_tool(
            "request_mutation_approval", args, request_state=first.request_state, allow_input_required=True
        )
        assert isinstance(again, InputRequiredResult)
        assert again.input_requests == first.input_requests
        result = await client.session.call_tool(
            "request_mutation_approval", args, request_state=again.request_state,
            input_responses={"approval": ElicitResult(action=action, content={"approve": approve} if action == "accept" else None)},
            allow_input_required=True,
        )
        assert not result.is_error
        replay = await client.session.call_tool(
            "request_mutation_approval", args, request_state=again.request_state,
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
            allow_input_required=True,
        )
        assert replay.is_error
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(records) == 4
    assert records[-1]["connection_id"] is None and records[-1]["db_type"] is None
    assert records[-1]["success"] is False
    for row in records[:3]:
        assert (row["connection_id"], row["db_type"]) == ("demo", "sqlite")
        assert not {"sql", "params", "request_state", "preview_token", "preview_token_id"} & row.keys()
    assert [(r["phase"], r["success"]) for r in records[:3]] == [
        ("awaiting_approval", None), ("awaiting_approval", None), (phase, approve is True)
    ]
    assert _status(server) == ("confirmed" if approve is True else "pending")


@pytest.mark.parametrize("target", ["missing", "", 123])
async def test_invalid_mrtr_target_does_not_fabricate_default_identity(reviewed_server, tmp_path, target):
    server = reviewed_server(telemetry=True)
    async with Client(server, elicitation_handler=lambda *a: None) as client:
        result = await client.call_tool("request_mutation_approval", {
            "skill_name": MUTATION, "params": PARAMS, "connection_id": target,
        }, raise_on_error=False)
        assert result.is_error
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert records and all(r.get("connection_id") is None and r.get("db_type") is None for r in records)
    assert _status(server) == "pending"


@pytest.mark.parametrize("failure", ["params", "state", "unsolicited", "expired"])
async def test_invalid_mrtr_continuation_has_no_fallback_identity(reviewed_server, tmp_path, failure, monkeypatch):
    server = reviewed_server(telemetry=True)
    args = {"skill_name": MUTATION, "params": PARAMS, "connection_id": "demo"}
    async with Client(server, elicitation_handler=lambda *a: None) as client:
        first = await client.session.call_tool("request_mutation_approval", args, allow_input_required=True)
        state = first.request_state
        if failure == "params":
            args["params"] = {**PARAMS, "order_id": 2}
        elif failure == "state":
            state = "tampered"
        elif failure == "unsolicited":
            state = None
        else:
            # Expire the server-side record without expiring the SDK's seal.
            import sql_safety_executor.mcp.mrtr as mrtr
            from types import SimpleNamespace
            monkeypatch.setattr(mrtr, "time", SimpleNamespace(time=lambda: time.time() + 1000))
        async def resume():
            return await client.session.call_tool(
                "request_mutation_approval", args, request_state=state,
                input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
                allow_input_required=True,
            )

        if failure in ("params", "state"):
            # The real SDK rejects a modified sealed request before middleware.
            with pytest.raises(MCPError, match="requestState"):
                await resume()
        else:
            assert (await resume()).is_error
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert records[0]["connection_id"] == "demo"
    if failure in ("params", "state"):
        assert len(records) == 1
    else:
        assert len(records) == 2
        assert records[1]["connection_id"] is None and records[1]["db_type"] is None
    assert _status(server) == "pending"


@pytest.mark.parametrize("behavior", ["slow", "suppress_cancel", "blocking", "params", "preview", "expires", "exception", "invalid"])
async def test_reference_mrtr_host_fails_closed(reviewed_server, behavior, monkeypatch):
    server = reviewed_server()
    clock = [datetime.now(timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr("examples.manual_mutation_approval.datetime", Clock)

    class Provider:
        async def decide(self, view, timeout_seconds):
            if behavior == "slow":
                await asyncio.sleep(0.05)
            elif behavior == "suppress_cancel":
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    pass
            elif behavior == "blocking":
                time.sleep(0.05)
            elif behavior == "params":
                view.params["order_id"] = 999
            elif behavior == "preview":
                view.preview["warnings"].append("Nested review content changed")
            elif behavior == "expires":
                clock[0] = view.expires_at + timedelta(seconds=1)
            elif behavior == "exception":
                raise RuntimeError("UI failure")
            elif behavior == "invalid":
                return "approve"
            return ApprovalDecision.APPROVE

    handler = MRTRApprovalProvider(
        MutationRequest(MUTATION, PARAMS, "demo"), 0.01, Provider()
    )
    async with Client(server, elicitation_handler=handler) as client:
        result = await client.call_tool("request_mutation_approval", {
            "skill_name": MUTATION, "params": PARAMS, "connection_id": "demo",
        })
        assert result.structured_content["execution_outcome"] == "not_executed"
    assert not handler.approved
    assert _status(server) == "pending"
    assert len(server.gateway_runtime.tokens) == 0


@pytest.mark.parametrize("decision", [ApprovalDecision.APPROVE, ApprovalDecision.DENY])
async def test_reference_mrtr_host_accepts_timely_unchanged_decision(reviewed_server, decision):
    server = reviewed_server()

    class Provider:
        async def decide(self, view, timeout_seconds):
            assert _status(server) == "pending"
            return decision

    handler = MRTRApprovalProvider(MutationRequest(MUTATION, PARAMS, "demo"), 5, Provider())
    async with Client(server, elicitation_handler=handler) as client:
        result = await client.call_tool("request_mutation_approval", {
            "skill_name": MUTATION, "params": PARAMS, "connection_id": "demo",
        })
        assert result.structured_content["execution_outcome"] == (
            "committed" if decision is ApprovalDecision.APPROVE else "not_executed"
        )
    assert handler.approved is (decision is ApprovalDecision.APPROVE)
    assert _status(server) == ("confirmed" if handler.approved else "pending")
