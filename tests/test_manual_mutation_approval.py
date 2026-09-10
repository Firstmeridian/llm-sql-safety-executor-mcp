"""Deterministic tests for the stdio-oriented manual approval host."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from datetime import datetime, timedelta, timezone
import importlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import threading
from typing import Any

import pytest

import examples.manual_mutation_approval as approval_host
from examples.manual_mutation_approval import (
    ApprovalDecision,
    ConsoleApprovalProvider,
    MutationOutcome,
    MutationRequest,
    _build_stdio_transport,
    _run_cli,
    run_approved_mutation,
)


TOKEN = "sentinel-preview-token-never-display"
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _preview(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": True,
        "skill_name": "update-order-status",
        "mode": "preview",
        "connection_id": "orders_primary",
        "db_type": "sqlite",
        "execution_outcome": "not_executed",
        "preview": {"order_id": 1, "current_status": "pending"},
        "preview_token": TOKEN,
        "preview_token_expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        "idempotent": False,
    }
    payload.update(overrides)
    return payload


def _execute(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": True,
        "skill_name": "update-order-status",
        "mode": "execute",
        "connection_id": "orders_primary",
        "db_type": "sqlite",
        "execution_outcome": "committed",
        "result": {"rowcount": 1},
    }
    payload.update(overrides)
    return payload


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any], float | None]] = []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append((name, arguments, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeApprover:
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.views = []
        self.timeouts: list[float] = []

    async def decide(self, view, timeout_seconds: float) -> ApprovalDecision:
        self.views.append(view)
        self.timeouts.append(timeout_seconds)
        return self.decision


def _run(client, approver, request=None) -> MutationOutcome:
    return asyncio.run(
        run_approved_mutation(
            client,
            request
            or MutationRequest(
                "update-order-status",
                {"order_id": 1, "new_status": "confirmed"},
            ),
            approver,
            now=lambda: NOW,
        )
    )


def test_approve_calls_preview_then_execute_with_resolved_connection() -> None:
    client = FakeClient([_preview(), _execute()])
    approver = FakeApprover(ApprovalDecision.APPROVE)

    outcome = _run(client, approver)

    assert outcome.status == "executed"
    assert len(client.calls) == 2
    preview_args = client.calls[0][1]
    execute_args = client.calls[1][1]
    assert "connection_id" not in preview_args
    assert execute_args["connection_id"] == "orders_primary"
    assert execute_args["preview_token"] == TOKEN
    assert execute_args["params"] == preview_args["params"]
    assert approver.views[0].connection_id == "orders_primary"
    assert TOKEN not in repr(approver.views[0])
    assert TOKEN not in repr(outcome)


@pytest.mark.parametrize(
    "decision",
    [
        ApprovalDecision.DENY,
        ApprovalDecision.TIMEOUT,
        ApprovalDecision.EOF,
        ApprovalDecision.CANCEL,
    ],
)
def test_non_approval_never_calls_execute(decision: ApprovalDecision) -> None:
    client = FakeClient([_preview()])
    outcome = _run(client, FakeApprover(decision))
    assert outcome.status == decision.value
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "preview_payload",
    [
        {"success": False, "mode": "preview"},
        _preview(mode="execute"),
        _preview(skill_name="other-skill"),
        _preview(connection_id=""),
        _preview(db_type=""),
        _preview(preview=[]),
        _preview(preview_token=""),
        _preview(preview_token_expires_at="not-a-date"),
        _preview(idempotent="false"),
        _preview(execution_outcome="committed"),
    ],
)
def test_malformed_or_failed_preview_fails_closed(preview_payload) -> None:
    client = FakeClient([preview_payload])
    approver = FakeApprover(ApprovalDecision.APPROVE)
    outcome = _run(client, approver)
    assert outcome.status == "preview_failed"
    assert len(client.calls) == 1
    assert approver.views == []
    assert TOKEN not in repr(outcome)


def test_explicit_connection_mismatch_fails_closed() -> None:
    client = FakeClient([_preview(connection_id="different")])
    request = MutationRequest(
        "update-order-status",
        {"order_id": 1, "new_status": "confirmed"},
        connection_id="orders_primary",
    )
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE), request)
    assert outcome.status == "preview_failed"
    assert len(client.calls) == 1


def test_expired_or_near_expiry_preview_never_reaches_approver() -> None:
    client = FakeClient(
        [_preview(preview_token_expires_at=(NOW + timedelta(seconds=1)).isoformat())]
    )
    approver = FakeApprover(ApprovalDecision.APPROVE)
    outcome = _run(client, approver)
    assert outcome.status == "preview_expired"
    assert approver.views == []
    assert len(client.calls) == 1


def test_approval_timeout_is_bounded_by_token_lifetime() -> None:
    client = FakeClient(
        [_preview(preview_token_expires_at=(NOW + timedelta(seconds=11)).isoformat())]
    )
    approver = FakeApprover(ApprovalDecision.DENY)
    _run(client, approver)
    assert approver.timeouts == [10.0]


def test_workflow_enforces_timeout_against_late_approval() -> None:
    class SlowApprover:
        async def decide(self, view, timeout_seconds: float) -> ApprovalDecision:
            await asyncio.sleep(0.05)
            return ApprovalDecision.APPROVE

    client = FakeClient([_preview()])
    outcome = asyncio.run(
        run_approved_mutation(
            client,
            MutationRequest("update-order-status", {"order_id": 1}),
            SlowApprover(),
            approval_timeout_seconds=0.01,
            now=lambda: NOW,
        )
    )
    assert outcome.status == "timeout"
    assert len(client.calls) == 1


def test_external_request_mutation_cannot_change_execute_snapshot() -> None:
    params = {"order_id": 1, "new_status": "confirmed"}

    class MutatingApprover(FakeApprover):
        async def decide(self, view, timeout_seconds: float) -> ApprovalDecision:
            params["order_id"] = 999
            return await super().decide(view, timeout_seconds)

    client = FakeClient([_preview(), _execute()])
    outcome = _run(
        client,
        MutatingApprover(ApprovalDecision.APPROVE),
        MutationRequest("update-order-status", params),
    )
    assert outcome.status == "executed"
    assert client.calls[1][1]["params"]["order_id"] == 1


def test_approval_provider_mutation_of_displayed_view_fails_closed() -> None:
    class MutatingApprover(FakeApprover):
        async def decide(self, view, timeout_seconds: float) -> ApprovalDecision:
            view.params["order_id"] = 888
            return await super().decide(view, timeout_seconds)

    client = FakeClient([_preview()])
    outcome = _run(client, MutatingApprover(ApprovalDecision.APPROVE))

    assert outcome.status == "approval_failed"
    assert len(client.calls) == 1


def test_explicit_connection_id_is_canonicalized_before_preview() -> None:
    client = FakeClient([_preview(), _execute()])
    request = MutationRequest(
        "update-order-status",
        {"order_id": 1, "new_status": "confirmed"},
        connection_id=" Orders_Primary ",
    )

    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE), request)

    assert outcome.status == "executed"
    assert client.calls[0][1]["connection_id"] == "orders_primary"
    assert client.calls[1][1]["connection_id"] == "orders_primary"


def test_non_json_params_are_rejected_before_preview() -> None:
    with pytest.raises(ValueError, match="finite JSON object"):
        _run(
            FakeClient([]),
            FakeApprover(ApprovalDecision.APPROVE),
            MutationRequest("update-order-status", {"order_id": float("nan")}),
        )


def test_non_string_json_keys_are_rejected_before_preview() -> None:
    invalid_params: Any = {1: "not-json-object-key"}
    with pytest.raises(ValueError, match="non-string JSON key"):
        _run(
            FakeClient([]),
            FakeApprover(ApprovalDecision.APPROVE),
            MutationRequest("update-order-status", invalid_params),
        )


def test_execute_exception_is_not_retried_and_reports_unknown_outcome() -> None:
    client = FakeClient([_preview(), TimeoutError("timed out")])
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))
    assert outcome.status == "execute_unknown"
    assert "not retried" in outcome.message
    assert len(client.calls) == 2
    assert TOKEN not in repr(outcome)


def test_execute_non_success_is_returned_without_token() -> None:
    client = FakeClient(
        [
            _preview(),
            _execute(
                success=False,
                error_code="response_preparation_failed",
                error=f"write rejected; echoed secret: {TOKEN}",
                preview_token=TOKEN,
            ),
        ]
    )
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))
    assert outcome.status == "execute_committed"
    assert outcome.payload is not None
    assert "preview_token" not in outcome.payload
    assert TOKEN not in repr(outcome)


def test_execute_result_redacts_token_from_abnormal_mapping_key() -> None:
    client = FakeClient(
        [
            _preview(),
            _execute(
                success=False,
                error_code="response_preparation_failed",
                error="response failed",
                **{f"echo-{TOKEN}": "bad"},
            ),
        ]
    )

    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))

    assert outcome.status == "execute_committed"
    assert TOKEN not in repr(outcome)


@pytest.mark.parametrize(
    "override",
    [
        {"mode": "preview"},
        {"skill_name": "other-skill"},
        {"connection_id": "other_connection"},
        {"db_type": "mysql"},
    ],
)
def test_execute_identity_mismatch_fails_closed(override) -> None:
    client = FakeClient([_preview(), _execute(**override)])
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))
    assert outcome.status == "execute_unknown"
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("execution_outcome", "expected_status"),
    [
        ("not_executed", "execute_not_executed"),
        ("rolled_back", "execute_rolled_back"),
        ("unknown", "execute_unknown"),
    ],
)
def test_host_interprets_non_committed_outcomes_without_retry(
    execution_outcome: str,
    expected_status: str,
) -> None:
    response = _execute(
        success=False,
        execution_outcome=execution_outcome,
        error_code="simulated_failure",
        error="sanitized failure",
    )
    client = FakeClient([_preview(), response])
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))
    assert outcome.status == expected_status
    assert len(client.calls) == 2


def test_successful_custom_skill_without_commit_evidence_is_terminal_unknown() -> None:
    response = _execute(success=True, execution_outcome="unknown")
    client = FakeClient([_preview(), response])

    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))

    assert outcome.status == "execute_unknown"
    assert "without whole-operation COMMIT evidence" in outcome.message
    assert len(client.calls) == 2


def test_strict_legacy_success_is_accepted_but_legacy_failure_is_unknown() -> None:
    old_success = _execute()
    old_success.pop("execution_outcome")
    success_client = FakeClient([_preview(), old_success])
    assert _run(
        success_client,
        FakeApprover(ApprovalDecision.APPROVE),
    ).status == "executed"

    old_failure = _execute(success=False, error="legacy failure")
    old_failure.pop("execution_outcome")
    failure_client = FakeClient([_preview(), old_failure])
    assert _run(
        failure_client,
        FakeApprover(ApprovalDecision.APPROVE),
    ).status == "execute_unknown"
    assert len(failure_client.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        _execute(execution_outcome="future_value"),
        _execute(execution_outcome=None),
        _execute(execution_outcome=[]),
        _execute(execution_outcome={}),
        _execute(execution_outcome=True),
        _execute(execution_outcome=1),
        _execute(success="true"),
        _execute(success=True, execution_outcome="rolled_back"),
        _execute(
            success=False,
            execution_outcome="unknown",
            error_code="",
            error="bad",
        ),
    ],
)
def test_malformed_execute_responses_are_unknown_and_terminal(response) -> None:
    client = FakeClient([_preview(), response])
    outcome = _run(client, FakeApprover(ApprovalDecision.APPROVE))
    assert outcome.status == "execute_unknown"
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("input_func", "expected"),
    [
        (lambda: "APPROVE", ApprovalDecision.APPROVE),
        (lambda: " APPROVE ", ApprovalDecision.DENY),
        (lambda: "approve", ApprovalDecision.DENY),
        (lambda: "", ApprovalDecision.DENY),
    ],
)
def test_console_provider_accepts_only_exact_approve(input_func, expected) -> None:
    output = io.StringIO()
    provider = ConsoleApprovalProvider(input_func=input_func, output=output)
    view = FakeApprover(ApprovalDecision.APPROVE)
    client = FakeClient([_preview()])
    _run(client, view)
    decision = asyncio.run(provider.decide(view.views[0], 1.0))
    assert decision is expected
    assert TOKEN not in output.getvalue()


def test_console_provider_maps_eof_without_displaying_token() -> None:
    def eof():
        raise EOFError

    output = io.StringIO()
    provider = ConsoleApprovalProvider(input_func=eof, output=output)
    approver = FakeApprover(ApprovalDecision.DENY)
    client = FakeClient([_preview()])
    _run(client, approver)
    assert (
        asyncio.run(provider.decide(approver.views[0], 1.0))
        is ApprovalDecision.EOF
    )
    assert TOKEN not in output.getvalue()


def test_console_provider_timeout_does_not_wait_for_blocked_input() -> None:
    def blocked_input() -> str:
        threading.Event().wait(1)
        return "APPROVE"

    output = io.StringIO()
    provider = ConsoleApprovalProvider(input_func=blocked_input, output=output)
    approver = FakeApprover(ApprovalDecision.DENY)
    client = FakeClient([_preview()])
    _run(client, approver)
    assert (
        asyncio.run(provider.decide(approver.views[0], 0.01))
        is ApprovalDecision.TIMEOUT
    )
    assert TOKEN not in output.getvalue()


def test_outcome_is_json_serializable() -> None:
    outcome = _run(
        FakeClient([_preview(), _execute()]),
        FakeApprover(ApprovalDecision.APPROVE),
    )
    assert "executed" in json.dumps(outcome.__dict__)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts_are_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        asyncio.run(
            run_approved_mutation(
                FakeClient([_preview()]),
                MutationRequest("update-order-status", {"order_id": 1}),
                FakeApprover(ApprovalDecision.APPROVE),
                approval_timeout_seconds=timeout,
            )
        )


def test_stdio_transport_inherits_complete_operator_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_TYPE", "sentinel-db-type")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("UNRELATED_CLOUD_SECRET", "sentinel-forwarded-secret")

    transport = _build_stdio_transport()

    assert transport.env["DB_TYPE"] == "sentinel-db-type"
    assert transport.env["PYTHON_DOTENV_DISABLED"] == "1"
    # Complete inheritance is an explicit trusted-local-host compromise.
    assert transport.env["UNRELATED_CLOUD_SECRET"] == "sentinel-forwarded-secret"
    assert transport.args == [
        str(Path(__file__).resolve().parent.parent / "start_server.py")
    ]


def test_cli_rejects_invalid_timeout_before_reading_params() -> None:
    args = Namespace(
        approval_timeout=0.0,
        tool_timeout=15.0,
        params_file=Path("/definitely/missing/params.json"),
        skill="update-order-status",
        connection_id=None,
    )
    with pytest.raises(ValueError, match="finite and positive"):
        asyncio.run(_run_cli(args))


def test_main_maps_keyboard_interrupt_to_safe_exit(monkeypatch, capsys) -> None:
    async def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(approval_host, "_run_cli", interrupted)
    exit_code = approval_host.main(
        [
            "--skill",
            "update-order-status",
            "--params-file",
            "/does/not/need/to/exist.json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 130
    assert "outcome may be unknown" in captured.err
    assert TOKEN not in captured.err


def test_expiry_is_rechecked_after_approval_before_execute() -> None:
    times = iter([NOW, NOW + timedelta(minutes=5)])
    client = FakeClient([_preview()])
    outcome = asyncio.run(
        run_approved_mutation(
            client,
            MutationRequest(
                "update-order-status",
                {"order_id": 1, "new_status": "confirmed"},
            ),
            FakeApprover(ApprovalDecision.APPROVE),
            now=lambda: next(times),
        )
    )
    assert outcome.status == "preview_expired"
    assert len(client.calls) == 1


def test_workflow_contract_via_in_memory_fastmcp_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Exercise the real tool/result contract without launching stdio in CI."""
    database = tmp_path / "approval.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT NOT NULL,
            total_amount REAL,
            amount REAL,
            status TEXT,
            source_label TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO orders VALUES (1, ?, 10, 10, 'pending', 'approval-test')",
        ("2026-08-19 12:00:00",),
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("DB_CONNECTIONS", "")
    monkeypatch.delenv("DEFAULT_DB_CONNECTION", raising=False)
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database))
    monkeypatch.setenv("ALLOWED_TABLES", "orders")
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "1")
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setenv("SKILLS_CHECK_SCHEMA_ON_LIST", "0")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    monkeypatch.setenv("SKILLS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

    project_root = Path(__file__).resolve().parent.parent
    skills_lib = project_root / "skills" / "_lib"
    monkeypatch.syspath_prepend(str(skills_lib))
    for name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(name, None)

    module = importlib.import_module("mcp_sql_server")
    try:
        from fastmcp import Client

        async def exercise() -> MutationOutcome:
            async with Client(module.mcp) as client:
                return await run_approved_mutation(
                    client,
                    MutationRequest(
                        "update-order-status",
                        {"order_id": 1, "new_status": "confirmed"},
                    ),
                    FakeApprover(ApprovalDecision.APPROVE),
                )

        outcome = asyncio.run(exercise())
        assert outcome.status == "executed"
        connection = sqlite3.connect(database)
        try:
            status = connection.execute(
                "SELECT status FROM orders WHERE id = 1"
            ).fetchone()
        finally:
            connection.close()
        assert status == ("confirmed",)
        assert "preview_token" not in repr(outcome)
    finally:
        db_adapter = sys.modules.get("db_adapter")
        if db_adapter is not None:
            db_adapter.reset_adapter()
        for name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(name, None)
