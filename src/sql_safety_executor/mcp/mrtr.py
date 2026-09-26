"""Managed-only MRTR guard, sharing the ordinary mutation execution boundary."""

import json
import time
from typing import Annotated, Any

from .context import ToolContext
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ToolAnnotations,
)
from pydantic import Field

from sql_safety_executor.core.mutation_service import MutationService
from sql_safety_executor.core.proposals import (
    _canonical_json,
    _mutation_preview_request_binding_json,
    _preview_token_digest,
)
from sql_safety_executor.core.types import OperationError
from sql_safety_executor.skills.access import (
    _resolve_skill_connection,
    _mutation_connection_policy_state,
    _ensure_skill_profile_allowed,
)
from sql_safety_executor.skills.catalog import validate_name, validate_params


def _require_capabilities(ctx):
    request = ctx.request_context
    capabilities = ctx.session.client_capabilities
    if request is None or request.protocol_version != "2026-07-28":
        raise OperationError(
            "MRTR requires MCP 2026-07-28; use preview/execute with trusted Host approval."
        )
    if (
        capabilities is None
        or capabilities.elicitation is None
        or capabilities.elicitation.form is None
    ):
        raise OperationError(
            "MRTR requires client form elicitation; use preview/execute with trusted Host approval."
        )


def _ask(record, state):
    return InputRequiredResult(
        result_type="input_required",
        input_requests={
            "approval": ElicitRequest(
                method="elicitation/create",
                params=ElicitRequestFormParams(
                    message="Approve this exact database mutation?\n"
                    + record.review_json,
                    requested_schema={
                        "type": "object",
                        "properties": {
                            "approve": {
                                "type": "boolean",
                                "title": "Approve this mutation",
                            }
                        },
                        "required": ["approve"],
                        "additionalProperties": False,
                    },
                ),
            )
        },
        request_state=state,
    )


async def request_approval(runtime, skill_name, params, ctx, connection_id=None):
    _require_capabilities(ctx)
    validate_name(skill_name)
    meta = runtime.catalog.get_skills_cache().get(skill_name)
    if meta is None or meta.type != "mutation" or meta._managed_mutation_plan is None:
        raise OperationError(
            "MRTR supports only an enabled managed single-statement mutation Skill."
        )
    connection = _resolve_skill_connection(runtime, meta, connection_id)
    _, allowed, reason = _mutation_connection_policy_state(runtime, meta, connection)
    if not allowed:
        raise OperationError(reason or "Mutation is not authorized")
    _ensure_skill_profile_allowed(runtime, meta)
    normalized = validate_params(params, meta.params)
    binding = _mutation_preview_request_binding_json(
        skill_name=skill_name,
        skill_version=meta.version,
        params=normalized,
        connection=connection,
    )
    responses = ctx.input_responses
    state = ctx.request_state
    service = MutationService(runtime)
    operation_context = ToolContext(ctx)
    if state is None:
        if responses is not None:
            raise OperationError(
                "Approval responses require the original proposal state."
            )
        result = await service.prepare(
            skill_name, normalized, operation_context, connection.connection_id
        )
        payload = result.structured_content
        if not payload.get("success"):
            result.meta["tool_name"] = "request_mutation_approval"
            return ToolResult(structured_content=payload, meta=result.meta)
        token = payload["preview_token"]
        digest = _preview_token_digest(token)
        try:
            review = _canonical_json(
                {
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                    "skill_name": skill_name,
                    "params": normalized,
                    "preview": payload["preview"],
                    "expires_at": payload["preview_token_expires_at"],
                    "guarantee": "One framework-managed SQL statement; approval is collected by the trusted Host.",
                }
            )
            if not runtime.tokens.attach_review(
                digest, binding, review, now=int(time.time())
            ):
                raise OperationError(
                    "MRTR review exceeds 64 KiB or proposal is unavailable; no write was attempted. Use manual preview/execute."
                )
        except BaseException:
            runtime.tokens.consume_if_matches(digest, binding, now=int(time.time()))
            raise
        state = _canonical_json(
            {"flow": "managed_mutation_approval_v1", "preview_token": token}
        )
    else:
        try:
            decoded = json.loads(state)
            if (
                set(decoded) != {"flow", "preview_token"}
                or decoded["flow"] != "managed_mutation_approval_v1"
            ):
                raise ValueError()
            token = decoded["preview_token"]
            if not isinstance(token, str) or not 1 <= len(token) <= 128:
                raise ValueError()
            digest = _preview_token_digest(token)
        except (ValueError, TypeError, KeyError):
            raise OperationError("Invalid mutation approval state") from None
    status, record = runtime.tokens.inspect_if_matches(
        digest, binding, now=int(time.time())
    )
    if status != "pending" or record is None or record.review_json is None:
        raise OperationError(
            "Mutation proposal unavailable, expired, consumed, or mismatched. Do not infer a previous write outcome or automatically retry."
        )
    if responses is None or "approval" not in responses:
        return _ask(record, state)
    answer = responses["approval"]
    if not isinstance(answer, ElicitResult):
        raise OperationError("Invalid approval response type")
    if answer.action in ("decline", "cancel") or (
        answer.action == "accept"
        and isinstance(answer.content, dict)
        and answer.content.get("approve") is False
    ):
        consumed, _ = runtime.tokens.consume_if_matches(
            digest, binding, now=int(time.time())
        )
        if consumed != "consumed":
            raise OperationError(
                "Proposal is no longer pending; its previous execution outcome must be reconciled."
            )
        code = (
            "approval_cancelled" if answer.action == "cancel" else "approval_declined"
        )
        return ToolResult(
            structured_content={
                "success": False,
                "skill_name": skill_name,
                "mode": "execute",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
                "execution_outcome": "not_executed",
                "error_code": code,
            },
            meta={
                "tool_name": "request_mutation_approval",
                "success": False,
                "phase": code,
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            },
        )
    if (
        answer.action != "accept"
        or not isinstance(answer.content, dict)
        or answer.content.get("approve") is not True
    ):
        # Re-ask the same proposal; never turn strings or numbers into approval.
        return _ask(record, state)
    result = await service.execute(
        skill_name, normalized, operation_context, token, connection.connection_id
    )
    result.meta["tool_name"] = "request_mutation_approval"
    return ToolResult(structured_content=result.structured_content, meta=result.meta)


def register_mrtr(server, runtime):
    @server.tool(
        name="request_mutation_approval",
        timeout=runtime.tool_timeout,
        description="Prepare a managed single-statement mutation and ask the trusted Host for human approval. Requires MCP 2026-07-28 form elicitation. Keep the target and parameters unchanged; never automatically retry an uncertain write.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    async def request_mutation_approval(
        skill_name: str,
        params: dict[str, Any],
        ctx: Context,
        connection_id: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
    ) -> ToolResult | InputRequiredResult:
        try:
            return await request_approval(
                runtime, skill_name, params, ctx, connection_id
            )
        except (OperationError, ValueError, TypeError) as exc:
            if isinstance(exc, OperationError):
                raise ToolError(str(exc)) from None
            raise ToolError("Invalid mutation approval request") from None
