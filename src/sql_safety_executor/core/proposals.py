from __future__ import annotations
import json
import hashlib
import logging
import secrets
import time
from typing import Any
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    ConnectionContext,
)

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import MUTATION_PREVIEW_BINDING_MAX_BYTES


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except TypeError as exc:
        raise ToolError(
            "Mutation params must be JSON-serializable for preview token binding."
        ) from exc


def _mutation_params_hash(params: dict[str, Any]) -> str:
    canonical = _canonical_json(params).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _execution_binding_json(execution_binding: Any) -> str:
    if not isinstance(execution_binding, dict):
        raise ToolError("Mutation execution binding must be a JSON object.")
    canonical = _canonical_json(execution_binding)
    if len(canonical.encode("utf-8")) > MUTATION_PREVIEW_BINDING_MAX_BYTES:
        raise ToolError(
            "Mutation execution binding exceeds "
            f"the {MUTATION_PREVIEW_BINDING_MAX_BYTES}-byte limit."
        )
    return canonical


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mutation_preview_request_binding_json(
    *,
    skill_name: str,
    skill_version: str,
    params: dict[str, Any],
    connection: ConnectionContext,
) -> str:
    return _canonical_json(
        {
            "v": 1,
            "skill_name": skill_name,
            "skill_version": skill_version,
            "params_hash": _mutation_params_hash(params),
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }
    )


def _create_mutation_preview_token(
    runtime,
    *,
    skill_name: str,
    skill_version: str,
    params: dict[str, Any],
    connection: ConnectionContext,
) -> tuple[str, int, str]:
    request_binding_json = _mutation_preview_request_binding_json(
        skill_name=skill_name,
        skill_version=skill_version,
        params=params,
        connection=connection,
    )
    expires_at = int(time.time()) + runtime.config.skills.mutation.preview.ttl_seconds
    return secrets.token_urlsafe(32), expires_at, request_binding_json


def _preview_token_id(preview_token: str) -> str:
    return _preview_token_digest(preview_token)[:16]


def _preview_token_digest(preview_token: str) -> str:
    return _sha256_hex(preview_token)


def _register_mutation_preview_token(
    runtime,
    preview_token: str,
    expires_at: int,
    request_binding_json: str,
    execution_binding_json: str,
) -> None:
    now = int(time.time())
    issued = runtime.tokens.issue(
        _preview_token_digest(preview_token),
        expires_at,
        request_binding_json,
        execution_binding_json,
        now=now,
    )
    if not issued:
        raise ToolError(
            "Mutation preview token could not be registered; retry preview later."
        )


def _consume_mutation_preview_token(
    runtime,
    preview_token: str | None,
    *,
    skill_name: str,
    skill_version: str,
    params: dict[str, Any],
    connection: ConnectionContext,
) -> dict[str, Any]:
    if not preview_token:
        raise ToolError(
            "preview_token is required for mutation execute; run "
            "execute_mutation_skill with confirm=false first."
        )

    request_binding_json = _mutation_preview_request_binding_json(
        skill_name=skill_name,
        skill_version=skill_version,
        params=params,
        connection=connection,
    )
    status, record = runtime.tokens.consume_if_matches(
        _preview_token_digest(preview_token),
        request_binding_json,
        now=int(time.time()),
    )
    if status == "expired":
        raise ToolError("Expired preview_token; run preview again.")
    if status == "mismatch":
        raise ToolError(
            "preview_token does not match this mutation request; run preview again."
        )
    if status == "not_found" or record is None:
        raise ToolError(
            "Invalid preview_token, has already been used, or was not issued "
            "by this server process; run preview again."
        )

    try:
        execution_binding = json.loads(record.execution_binding_json)
    except Exception as exc:
        raise ToolError(
            "Invalid preview_token execution binding; run preview again."
        ) from exc
    if not isinstance(execution_binding, dict):
        raise ToolError("Invalid preview_token execution binding; run preview again.")
    return execution_binding
