#!/usr/bin/env python3
"""One-shot, stdio-only host example for explicit mutation approval.

This example deliberately keeps the preview and execute calls in one FastMCP
client context because preview-token state is process-local.  It is a host-side
approval workflow, not proof that the server authenticated a human approver.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
from typing import Any, Callable, Mapping, Protocol, TextIO


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVER_SCRIPT = PROJECT_ROOT / "start_server.py"
_EXPIRY_SAFETY_MARGIN_SECONDS = 1.0
_CONNECTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ApprovalDecision(str, Enum):
    """Decisions understood by the approval workflow."""

    APPROVE = "approve"
    DENY = "deny"
    TIMEOUT = "timeout"
    EOF = "eof"
    CANCEL = "cancel"


@dataclass(frozen=True)
class MutationRequest:
    """One requested mutation; params are snapshotted before preview."""

    skill_name: str
    params: Mapping[str, Any]
    connection_id: str | None = None


@dataclass(frozen=True)
class ApprovalView:
    """Information shown to the approver.  It never contains the bearer token."""

    skill_name: str
    params: Mapping[str, Any]
    connection_id: str
    db_type: str
    preview: Mapping[str, Any]
    expires_at: datetime
    idempotent: bool


@dataclass(frozen=True)
class MutationOutcome:
    """Workflow outcome with this preview token removed from terminal output."""

    status: str
    message: str
    payload: Mapping[str, Any] | None = None


class ApprovalProvider(Protocol):
    """Host-owned approval UI boundary."""

    async def decide(
        self,
        view: ApprovalView,
        timeout_seconds: float,
    ) -> ApprovalDecision: ...


class MutationClient(Protocol):
    """Minimal FastMCP Client surface used by the state machine."""

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any: ...


class ConsoleApprovalProvider:
    """Render an exact preview and accept only the literal word ``APPROVE``.

    Input is read by a daemon thread so an approval timeout does not leave
    ``asyncio.run()`` waiting for a non-cancellable executor task.  This is a
    one-shot CLI; after timeout it exits instead of trying to reuse stdin.
    """

    def __init__(
        self,
        *,
        input_func: Callable[[], str] = input,
        output: TextIO = sys.stdout,
    ) -> None:
        self._input_func = input_func
        self._output = output

    def _render(self, view: ApprovalView, timeout_seconds: float) -> None:
        document = {
            "skill_name": view.skill_name,
            "params": dict(view.params),
            "resolved_connection_id": view.connection_id,
            "db_type": view.db_type,
            "preview": dict(view.preview),
            "preview_token_expires_at": view.expires_at.isoformat(),
            "idempotent": view.idempotent,
        }
        print("Mutation preview requiring approval:", file=self._output)
        print(
            json.dumps(document, indent=2, ensure_ascii=False, default=str),
            file=self._output,
        )
        print(
            f"Type exactly APPROVE within {timeout_seconds:.1f}s; "
            "any other input denies execution.",
            file=self._output,
            flush=True,
        )

    async def decide(
        self,
        view: ApprovalView,
        timeout_seconds: float,
    ) -> ApprovalDecision:
        self._render(view, timeout_seconds)
        values: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=1)

        def read_once() -> None:
            try:
                values.put(("value", self._input_func()))
            except EOFError:
                values.put(("eof", None))
            except KeyboardInterrupt:
                values.put(("cancel", None))
            except Exception:
                values.put(("cancel", None))

        threading.Thread(target=read_once, daemon=True).start()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            try:
                kind, value = values.get_nowait()
                break
            except queue.Empty:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return ApprovalDecision.TIMEOUT
                # Poll the daemon reader without blocking FastMCP/client tasks
                # or putting a non-cancellable input() call in an executor.
                await asyncio.sleep(min(0.05, remaining))

        if kind == "eof":
            return ApprovalDecision.EOF
        if kind == "cancel":
            return ApprovalDecision.CANCEL
        if value == "APPROVE":
            return ApprovalDecision.APPROVE
        return ApprovalDecision.DENY


class ApprovalWorkflowError(ValueError):
    """Raised when a tool response does not satisfy the expected contract."""


def _json_object_snapshot(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Return the exact JSON-compatible object that MCP can transport."""
    raw = dict(value)

    def require_string_keys(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ApprovalWorkflowError(
                        f"{label} contains a non-string JSON key at {path}"
                    )
                require_string_keys(child, f"{path}.{key}")
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                require_string_keys(child, f"{path}[{index}]")

    require_string_keys(raw, "$")
    try:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        snapshot = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ApprovalWorkflowError(f"{label} must be a finite JSON object") from exc
    if not isinstance(snapshot, dict):
        raise ApprovalWorkflowError(f"{label} must be a JSON object")
    return snapshot


def _normalize_connection_id(connection_id: str | None) -> str | None:
    if connection_id is None:
        return None
    if not isinstance(connection_id, str):
        raise ApprovalWorkflowError("connection_id must be a string")
    normalized = connection_id.strip().lower()
    if not _CONNECTION_ID_PATTERN.fullmatch(normalized):
        raise ApprovalWorkflowError(
            "connection_id must use 1-64 lowercase letters, digits, or "
            "underscores and start with a letter"
        )
    return normalized


def _approval_view_fingerprint(view: ApprovalView) -> str:
    """Canonical approval content used to detect a buggy provider's mutation."""
    document = {
        "skill_name": view.skill_name,
        "params": _json_object_snapshot(view.params, "Approval params"),
        "connection_id": view.connection_id,
        "db_type": view.db_type,
        "preview": _json_object_snapshot(view.preview, "Approval preview"),
        "expires_at": view.expires_at.isoformat(),
        "idempotent": view.idempotent,
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _parse_tool_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = result
    else:
        payload = getattr(result, "structured_content", None)
        if payload is None:
            payload = getattr(result, "data", None)
        if payload is None:
            content = getattr(result, "content", None)
            if content:
                text = getattr(content[0], "text", None)
                if isinstance(text, str):
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise ApprovalWorkflowError(
                            "Tool result text is not valid JSON"
                        ) from exc
    if not isinstance(payload, dict):
        raise ApprovalWorkflowError("Tool result must contain a JSON object")
    return payload


def _parse_expiry(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise ApprovalWorkflowError("Preview expiry is missing or invalid")
    try:
        expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalWorkflowError("Preview expiry is not valid ISO 8601") from exc
    if expiry.tzinfo is None:
        raise ApprovalWorkflowError("Preview expiry must include a timezone")
    return expiry.astimezone(timezone.utc)


def _redact_token_fields(value: Any, preview_token: str) -> Any:
    """Copy a result while removing this workflow's bearer token."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "preview_token":
                continue
            safe_key = (
                key.replace(preview_token, "[REDACTED_PREVIEW_TOKEN]")
                if isinstance(key, str)
                else copy.deepcopy(key)
            )
            redacted[safe_key] = _redact_token_fields(item, preview_token)
        return redacted
    if isinstance(value, list):
        return [_redact_token_fields(item, preview_token) for item in value]
    if isinstance(value, str):
        return value.replace(preview_token, "[REDACTED_PREVIEW_TOKEN]")
    return copy.deepcopy(value)


def _validate_timeouts(
    approval_timeout_seconds: float,
    tool_timeout_seconds: float,
) -> None:
    if (
        not math.isfinite(approval_timeout_seconds)
        or approval_timeout_seconds <= 0
        or not math.isfinite(tool_timeout_seconds)
        or tool_timeout_seconds <= 0
    ):
        raise ValueError("Timeouts must be finite and positive")


def _validated_preview(
    payload: dict[str, Any],
    request: MutationRequest,
    params_snapshot: dict[str, Any],
) -> tuple[str, ApprovalView]:
    if payload.get("success") is not True or payload.get("mode") != "preview":
        raise ApprovalWorkflowError("Server did not return a successful preview")
    if payload.get("skill_name") != request.skill_name:
        raise ApprovalWorkflowError("Preview skill_name does not match the request")
    if (
        "execution_outcome" in payload
        and payload.get("execution_outcome") != "not_executed"
    ):
        raise ApprovalWorkflowError("Preview execution_outcome is invalid")

    connection_id = payload.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id:
        raise ApprovalWorkflowError("Preview did not resolve a connection_id")
    if request.connection_id is not None and connection_id != request.connection_id:
        raise ApprovalWorkflowError("Preview resolved a different connection_id")

    db_type = payload.get("db_type")
    preview = payload.get("preview")
    token = payload.get("preview_token")
    idempotent = payload.get("idempotent")
    if not isinstance(db_type, str) or not db_type:
        raise ApprovalWorkflowError("Preview did not return a database type")
    if not isinstance(preview, dict):
        raise ApprovalWorkflowError("Preview details must be a JSON object")
    if not isinstance(token, str) or not token:
        raise ApprovalWorkflowError("Preview token is missing or invalid")
    if not isinstance(idempotent, bool):
        raise ApprovalWorkflowError("Preview idempotent flag is missing or invalid")

    expires_at = _parse_expiry(payload.get("preview_token_expires_at"))
    view = ApprovalView(
        skill_name=request.skill_name,
        params=_json_object_snapshot(params_snapshot, "Approval params"),
        connection_id=connection_id,
        db_type=db_type,
        preview=_json_object_snapshot(preview, "Approval preview"),
        expires_at=expires_at,
        idempotent=idempotent,
    )
    return token, view


def _interpret_execute_payload(
    payload: dict[str, Any],
    request: MutationRequest,
    view: ApprovalView,
) -> tuple[str, str]:
    """Validate identity first, then classify new or legacy execute results."""
    if (
        payload.get("mode") != "execute"
        or payload.get("skill_name") != request.skill_name
        or payload.get("connection_id") != view.connection_id
        or payload.get("db_type") != view.db_type
    ):
        return (
            "execute_unknown",
            "Execute response identity was missing or mismatched; it was not retried.",
        )

    success = payload.get("success")
    if not isinstance(success, bool):
        return (
            "execute_unknown",
            "Execute response success flag was malformed; it was not retried.",
        )

    if "execution_outcome" not in payload:
        # Compatibility with old servers is deliberately narrow: only a fully
        # identified success with an object result is treated as executed.
        if success is True and isinstance(payload.get("result"), dict):
            return (
                "executed",
                "Mutation executed after explicit host-side approval (legacy response).",
            )
        return (
            "execute_unknown",
            "Legacy execute failure lacked transaction evidence; it was not retried.",
        )

    execution_outcome = payload.get("execution_outcome")
    if not isinstance(execution_outcome, str) or execution_outcome not in {
        "not_executed",
        "rolled_back",
        "committed",
        "unknown",
    }:
        return (
            "execute_unknown",
            "Execute response outcome was missing or unknown; it was not retried.",
        )

    if execution_outcome == "committed":
        if not isinstance(payload.get("result"), dict):
            return (
                "execute_unknown",
                "Committed response omitted its result object; it was not retried.",
            )
        if success:
            return (
                "executed",
                "Mutation committed after explicit host-side approval.",
            )
        if not (
            isinstance(payload.get("error_code"), str)
            and payload.get("error_code")
            and isinstance(payload.get("error"), str)
            and payload.get("error")
        ):
            return (
                "execute_unknown",
                "Committed failure response was malformed; it was not retried.",
            )
        return (
            "execute_committed",
            "Database COMMIT was confirmed despite a tool-handling failure; it was not retried.",
        )

    if success is True and execution_outcome == "unknown":
        return (
            "execute_unknown",
            "The Skill handler completed without whole-operation COMMIT evidence; "
            "it was not retried.",
        )
    if success is True:
        return (
            "execute_unknown",
            "Execute response contained contradictory success/outcome fields; it was not retried.",
        )
    if not (
        isinstance(payload.get("error_code"), str)
        and payload.get("error_code")
        and isinstance(payload.get("error"), str)
        and payload.get("error")
    ):
        return (
            "execute_unknown",
            "Execute failure response was malformed; it was not retried.",
        )
    if execution_outcome == "rolled_back":
        return (
            "execute_rolled_back",
            "The supported database transaction was confirmed rolled back; it was not retried.",
        )
    if execution_outcome == "not_executed":
        return (
            "execute_not_executed",
            "The server reported that no business write was attempted; it was not retried.",
        )
    return (
        "execute_unknown",
        "The server could not confirm the database outcome; it was not retried.",
    )


async def run_approved_mutation(
    client: MutationClient,
    request: MutationRequest,
    approver: ApprovalProvider,
    *,
    approval_timeout_seconds: float = 60.0,
    tool_timeout_seconds: float = 120.0,
    now: Callable[[], datetime] | None = None,
) -> MutationOutcome:
    """Preview, request explicit approval, then execute once in one client.

    Execute exceptions are never retried: the token may already be consumed and
    the database outcome may be unknown.
    """
    _validate_timeouts(approval_timeout_seconds, tool_timeout_seconds)
    if not isinstance(request.params, Mapping):
        raise TypeError("Mutation params must be a JSON object")

    params_snapshot = _json_object_snapshot(request.params, "Mutation params")
    normalized_connection_id = _normalize_connection_id(request.connection_id)
    normalized_request = MutationRequest(
        skill_name=request.skill_name,
        params=params_snapshot,
        connection_id=normalized_connection_id,
    )
    preview_arguments: dict[str, Any] = {
        "skill_name": request.skill_name,
        "params": copy.deepcopy(params_snapshot),
        "confirm": False,
    }
    if normalized_connection_id is not None:
        preview_arguments["connection_id"] = normalized_connection_id

    try:
        preview_result = await client.call_tool(
            "execute_mutation_skill",
            preview_arguments,
            timeout=tool_timeout_seconds,
        )
        preview_payload = _parse_tool_payload(preview_result)
        preview_token, view = _validated_preview(
            preview_payload,
            normalized_request,
            params_snapshot,
        )
    except Exception as exc:
        return MutationOutcome(
            status="preview_failed",
            message=f"Preview failed closed ({type(exc).__name__}).",
        )

    now_fn = now or (lambda: datetime.now(timezone.utc))
    try:
        current_time = now_fn()
        if current_time.tzinfo is None:
            raise ValueError("now() must return a timezone-aware datetime")
        remaining = (
            view.expires_at - current_time.astimezone(timezone.utc)
        ).total_seconds()
        effective_timeout = min(
            approval_timeout_seconds,
            remaining - _EXPIRY_SAFETY_MARGIN_SECONDS,
        )
        if effective_timeout <= 0:
            return MutationOutcome(
                status="preview_expired",
                message=(
                    "Preview token expired or is too close to expiry; "
                    "preview again."
                ),
            )

        approval_loop = asyncio.get_running_loop()
        approval_deadline = approval_loop.time() + effective_timeout
        approval_fingerprint = _approval_view_fingerprint(view)
        try:
            decision = await asyncio.wait_for(
                approver.decide(view, effective_timeout),
                timeout=effective_timeout,
            )
        except TimeoutError:
            decision = ApprovalDecision.TIMEOUT
        except EOFError:
            decision = ApprovalDecision.EOF
        except KeyboardInterrupt:
            decision = ApprovalDecision.CANCEL
        except Exception as exc:
            return MutationOutcome(
                status="approval_failed",
                message=f"Approval UI failed closed ({type(exc).__name__}).",
            )

        try:
            view_unchanged = (
                _approval_view_fingerprint(view) == approval_fingerprint
            )
        except Exception:
            view_unchanged = False
        if not view_unchanged:
            return MutationOutcome(
                status="approval_failed",
                message="Approval UI changed the displayed request; failed closed.",
            )

        # A cooperative provider is cancelled by wait_for(). The deadline
        # check also rejects a provider that catches cancellation and returns
        # a late APPROVE; an actively hostile provider still needs process
        # isolation to guarantee termination.
        if approval_loop.time() >= approval_deadline:
            decision = ApprovalDecision.TIMEOUT
        if not isinstance(decision, ApprovalDecision):
            return MutationOutcome(
                status="approval_failed",
                message="Approval UI returned an unsupported decision; failed closed.",
            )
        if decision is not ApprovalDecision.APPROVE:
            return MutationOutcome(
                status=decision.value,
                message="Mutation was not approved; execute was not called.",
            )

        approved_at = now_fn()
        if approved_at.tzinfo is None:
            raise ValueError("now() must return a timezone-aware datetime")
        if (
            view.expires_at - approved_at.astimezone(timezone.utc)
        ).total_seconds() <= _EXPIRY_SAFETY_MARGIN_SECONDS:
            return MutationOutcome(
                status="preview_expired",
                message="Preview expired before execute; execute was not called.",
            )

        execute_arguments = {
            "skill_name": normalized_request.skill_name,
            "params": copy.deepcopy(params_snapshot),
            "confirm": True,
            "preview_token": preview_token,
            # Always pin execute to the alias returned by preview.  This is
            # important when the original request omitted connection_id.
            "connection_id": view.connection_id,
        }
        try:
            execute_result = await client.call_tool(
                "execute_mutation_skill",
                execute_arguments,
                timeout=tool_timeout_seconds,
            )
            execute_payload = _parse_tool_payload(execute_result)
        except Exception as exc:
            return MutationOutcome(
                status="execute_unknown",
                message=(
                    "Execute did not return a usable result and was not retried; "
                    "the token may be consumed and the write outcome may be "
                    f"unknown ({type(exc).__name__})."
                ),
            )

        safe_payload = _redact_token_fields(execute_payload, preview_token)
        outcome_status, outcome_message = _interpret_execute_payload(
            execute_payload,
            normalized_request,
            view,
        )
        return MutationOutcome(
            status=outcome_status,
            message=outcome_message,
            payload=safe_payload,
        )
    finally:
        # Python cannot guarantee secure memory erasure.  This only drops the
        # workflow's reference and must not be described as cryptographic wipe.
        preview_token = ""


def _load_params(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("--params-file must contain a JSON object")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview a mutation over stdio and require an exact APPROVE response "
            "before executing it."
        )
    )
    parser.add_argument("--skill", required=True, help="Mutation Skill name")
    parser.add_argument(
        "--params-file",
        required=True,
        type=Path,
        help="JSON object file (avoids putting business parameters in shell history)",
    )
    parser.add_argument(
        "--connection-id",
        help="Optional configured connection alias; omitted means server default",
    )
    parser.add_argument("--approval-timeout", type=float, default=60.0)
    parser.add_argument("--tool-timeout", type=float, default=120.0)
    return parser


async def _run_cli(args: argparse.Namespace) -> MutationOutcome:
    from fastmcp import Client

    _validate_timeouts(args.approval_timeout, args.tool_timeout)
    params = _load_params(args.params_file)
    server_script = DEFAULT_SERVER_SCRIPT.resolve()
    if not server_script.is_file():
        raise FileNotFoundError(f"Server script not found: {server_script}")

    transport = _build_stdio_transport()
    request = MutationRequest(
        skill_name=args.skill,
        params=params,
        connection_id=args.connection_id,
    )
    async with Client(
        transport,
        timeout=args.tool_timeout,
        init_timeout=args.tool_timeout,
    ) as client:
        return await run_approved_mutation(
            client,
            request,
            ConsoleApprovalProvider(),
            approval_timeout_seconds=args.approval_timeout,
            tool_timeout_seconds=args.tool_timeout,
        )


def _build_stdio_transport() -> Any:
    """Build the local transport with the caller's complete configuration."""
    from fastmcp.client.transports import StdioTransport

    return StdioTransport(
        command=sys.executable,
        args=[str(DEFAULT_SERVER_SCRIPT)],
        # MCP's stdio transport otherwise inherits only a small safe system
        # subset. This local host must preserve the exact DB_*/Skill policy
        # environment that the operator reviewed instead of silently falling
        # back to a different project .env configuration. The server path is
        # fixed to this trusted repository rather than accepted from CLI input.
        env=dict(os.environ),
        cwd=str(PROJECT_ROOT),
        keep_alive=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        outcome = asyncio.run(_run_cli(args))
    except KeyboardInterrupt:
        print(
            "Approval host interrupted; execute was not retried and its "
            "outcome may be unknown.",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Approval host failed closed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # A third-party client exception could include request payloads. Keep
        # this reference CLI's unexpected-error output to the exception class.
        print(
            f"Approval host failed closed ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(asdict(outcome), indent=2, ensure_ascii=False, default=str))
    return 0 if outcome.status == "executed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
