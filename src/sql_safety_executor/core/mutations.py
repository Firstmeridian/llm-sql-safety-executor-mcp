from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Any
from pydantic import Field
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    OperationContext as Context,
    OperationResult as ToolResult,
)
from sql_safety_executor.skills.catalog import validate_name, validate_params
from sql_safety_executor.skills.mutation import (
    MutationBase,
    MutationExecutionError,
    MutationExecutionResult,
    resolve_managed_plan_values,
    run_managed_mutation,
    validate_managed_preview,
)

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import (
    _CONNECTION_ID_FIELD,
    _MUTATION_PREVIEW_TOKEN_FIELD,
)

from sql_safety_executor.core.proposals import (
    _consume_mutation_preview_token,
    _create_mutation_preview_token,
    _execution_binding_json,
    _preview_token_id,
    _register_mutation_preview_token,
)
from sql_safety_executor.core.results import (
    _context_client_id,
    _require_boolean,
    _skill_tool_result,
)
from sql_safety_executor.skills.access import (
    _ensure_skill_profile_allowed,
    _ensure_skill_schema_ready,
    _mutation_connection_policy_state,
    _resolve_skill_connection,
)


async def execute_mutation_skill(
    runtime,
    skill_name: Annotated[
        str, Field(description="Name of the mutation skill to execute")
    ],
    params: Annotated[
        dict[str, Any],
        Field(description="Parameters for the skill (must match skill_def.md schema)"),
    ],
    ctx: Context,
    confirm: Annotated[
        bool, Field(description="False=preview (default), True=execute")
    ] = False,
    preview_token: Annotated[str | None, _MUTATION_PREVIEW_TOKEN_FIELD] = None,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Execute a pre-defined mutation (write) skill."""
    try:
        resolved_confirm = _require_boolean(confirm, "confirm")
    except ValueError as exc:
        await ctx.warning(f"Mutation skill parameter error: {exc}")
        raise ToolError(str(exc)) from exc

    mode = "execute" if resolved_confirm else "preview"
    await ctx.info(f"Mutation skill '{skill_name}' mode={mode}")
    start_time = time.perf_counter()

    try:
        validate_name(skill_name)

        # Load + validate params against frontmatter schema
        skills = runtime.catalog.get_skills_cache()
        if skill_name not in skills:
            raise FileNotFoundError(f"Skill '{skill_name}' not found")
        meta = skills[skill_name]
        if meta.type != "mutation":
            raise TypeError(
                f"Skill '{skill_name}' is type '{meta.type}', expected 'mutation'"
            )
        # Resolve the ordinary explicit/default target, then enforce
        # connection_ids and databases before adapter construction.
        # Skill metadata only narrows scope; it never grants writes.
        connection = _resolve_skill_connection(runtime, meta, connection_id)
        _, mutation_policy_allowed, mutation_policy_reason = (
            _mutation_connection_policy_state(runtime, meta, connection)
        )
        if not mutation_policy_allowed:
            raise ToolError(
                mutation_policy_reason
                or "Mutation is not authorized by target connection policy."
            )
        validated_params = validate_params(params, meta.params)

        _ensure_skill_profile_allowed(runtime, meta)
        _ensure_skill_schema_ready(runtime, meta, connection)

        adapter = connection.adapter
        # Managed confirmation consumes only the immutable plan cached at
        # discovery. Do not even instantiate application Skill Python on
        # that path; preview and imperative execution still need an
        # instance for their documented callbacks.
        mutation = (
            runtime.catalog.load_mutation(skill_name, adapter, runtime.audit)
            if not resolved_confirm or meta._managed_mutation_plan is None
            else None
        )
        client_id = _context_client_id(ctx)

    except (
        ValueError,
        TypeError,
        FileNotFoundError,
        AttributeError,
        ImportError,
        SyntaxError,
        ToolError,
    ) as e:
        await ctx.warning(f"Mutation skill setup error: {e}")
        if isinstance(e, ToolError):
            raise
        raise ToolError(str(e)) from e

    if not resolved_confirm:
        # Phase 1: validate + preview (no writes)
        try:
            if mutation is None:
                raise RuntimeError(
                    "Mutation framework did not instantiate the preview Skill."
                )
            validation = mutation.validate(validated_params)
            if not validation.get("valid", False):
                errors = validation.get("errors", ["Validation failed"])
                await ctx.warning(f"Validation failed: {errors}")
                audit_logged = runtime.audit.log(
                    skill_name=skill_name,
                    params=validated_params,
                    mode="preview",
                    result={
                        "success": False,
                        "error": "Validation failed for mutation.",
                        "execution_outcome": "not_executed",
                        "error_code": "validation_failed",
                    },
                    client_id=client_id,
                    connection_id=connection.connection_id,
                    db_type=connection.db_type,
                )
                payload = {
                    "success": False,
                    "skill_name": skill_name,
                    "mode": "preview",
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                    "execution_outcome": "not_executed",
                    "error_code": "validation_failed",
                    "error": "Validation failed for mutation.",
                    "validation": validation,
                }
                return _skill_tool_result(
                    payload,
                    meta,
                    mode="preview",
                    start_time=start_time,
                    connection=connection,
                    audit_logged=audit_logged,
                    preview_token_required=False,
                    preview_token_validated=False,
                    preview_token_consumed=False,
                )

            preview_result = mutation.preview(validated_params)
            if not isinstance(preview_result, dict):
                raise ToolError(
                    "Mutation preview returned an invalid result; no "
                    "preview token was issued."
                )
            if meta._managed_mutation_plan is not None:
                validate_managed_preview(preview_result)
            if "error" in preview_result or (
                "success" in preview_result and preview_result["success"] is not True
            ):
                raw_preview_error = preview_result.get("error")
                preview_error = (
                    str(raw_preview_error).strip()
                    if raw_preview_error is not None
                    else ""
                )
                if not preview_error:
                    preview_error = "Mutation preview reported failure."
                await ctx.warning(f"Preview failed: {preview_error}")
                audit_logged = runtime.audit.log(
                    skill_name=skill_name,
                    params=validated_params,
                    mode="preview",
                    result={
                        "success": False,
                        "preview": False,
                        "error": preview_error,
                        "execution_outcome": "not_executed",
                        "error_code": "preview_failed",
                    },
                    client_id=client_id,
                    connection_id=connection.connection_id,
                    db_type=connection.db_type,
                )
                payload = {
                    "success": False,
                    "skill_name": skill_name,
                    "mode": "preview",
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                    "execution_outcome": "not_executed",
                    "error_code": "preview_failed",
                    "preview": preview_result,
                    "error": preview_error,
                }
                return _skill_tool_result(
                    payload,
                    meta,
                    mode="preview",
                    start_time=start_time,
                    connection=connection,
                    audit_logged=audit_logged,
                    preview_token_required=False,
                    preview_token_validated=False,
                    preview_token_consumed=False,
                )
            execution_binding = mutation.build_execution_binding(
                validated_params,
                validation,
                preview_result,
            )
            binding_json = _execution_binding_json(execution_binding)
            if meta._managed_mutation_plan is not None:
                # A binding callback may mutate the preview. Check again,
                # then resolve the exact JSON state stored with the token.
                validate_managed_preview(preview_result)
                try:
                    statement_params, _ = resolve_managed_plan_values(
                        meta._managed_mutation_plan,
                        params=validated_params,
                        execution_binding=json.loads(binding_json),
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise ToolError(
                        "Managed mutation plan values could not be resolved; "
                        "no preview token was issued and no write was attempted."
                    ) from error
                preview_result = {
                    **preview_result,
                    "preview_sql": meta._managed_mutation_plan.sql,
                    "bound_params": statement_params,
                }

            generated_token, expires_at, request_binding_json = (
                _create_mutation_preview_token(
                    runtime,
                    skill_name=skill_name,
                    skill_version=meta.version,
                    params=validated_params,
                    connection=connection,
                )
            )
            _register_mutation_preview_token(
                runtime,
                generated_token,
                expires_at,
                request_binding_json,
                binding_json,
            )
            token_id = _preview_token_id(generated_token)

            # Audit the preview without recording the full token.
            audit_logged = runtime.audit.log(
                skill_name=skill_name,
                params=validated_params,
                mode="preview",
                result={
                    "success": True,
                    "preview": True,
                    "execution_outcome": "not_executed",
                },
                client_id=client_id,
                connection_id=connection.connection_id,
                db_type=connection.db_type,
            )

            await ctx.info(f"Preview completed for '{skill_name}'")
            payload = {
                "success": True,
                "skill_name": skill_name,
                "mode": "preview",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
                "execution_outcome": "not_executed",
                "preview": {
                    key: value
                    for key, value in preview_result.items()
                    if key != "requires_confirmation"
                },
                "preview_token": generated_token,
                "preview_token_expires_at": datetime.fromtimestamp(
                    expires_at,
                    timezone.utc,
                ).isoformat(),
                "idempotent": meta.idempotent,
            }
            return _skill_tool_result(
                payload,
                meta,
                mode="preview",
                start_time=start_time,
                connection=connection,
                row_count=preview_result.get("affected_rows_estimate"),
                audit_logged=audit_logged,
                preview_token_required=True,
                preview_token_validated=False,
                preview_token_consumed=False,
                preview_token_id=token_id,
            )
        except ToolError:
            raise
        except Exception as e:
            sanitized = adapter._handle_error(e)
            raise ToolError(sanitized) from e
    else:
        # Phase 2: consume, then use the managed plan or imperative callback
        try:
            execution_binding = _consume_mutation_preview_token(
                runtime,
                preview_token,
                skill_name=skill_name,
                skill_version=meta.version,
                params=validated_params,
                connection=connection,
            )
            token_id = _preview_token_id(preview_token or "")
        except ToolError:
            # Parameter/setup checks happened earlier; token rejection
            # remains an MCP ToolError and never becomes a business
            # execution result.
            raise

        # Imperative callbacks retain their legacy execute-time
        # re-validation. A managed Skill does not run any Skill Python
        # after token consumption; its SQL predicate and expected row
        # count enforce the previewed state atomically.
        validation: dict[str, Any] = {"valid": True}
        if meta._managed_mutation_plan is None:
            if mutation is None:
                raise RuntimeError(
                    "Mutation framework did not instantiate the imperative Skill."
                )
            try:
                validation = mutation.validate(validated_params)
            except ToolError as validation_error:
                validation = {
                    "valid": False,
                    "errors": [str(validation_error)],
                }
            except Exception as validation_error:
                validation = {
                    "valid": False,
                    "errors": [adapter._handle_error(validation_error)],
                }

            if not isinstance(validation, dict):
                validation = {
                    "valid": False,
                    "errors": ["Mutation validation returned an invalid result."],
                }

        if not validation.get("valid", False):
            errors = validation.get("errors", ["Validation failed"])
            try:
                await ctx.warning(f"Validation failed: {errors}")
            except Exception as notification_error:
                logger.warning(
                    "Mutation validation notification failed: %s",
                    notification_error.__class__.__name__,
                )
            audit_logged = runtime.audit.log(
                skill_name=skill_name,
                params=validated_params,
                mode="execute",
                result={
                    "success": False,
                    "error": "Validation failed for mutation.",
                    "execution_outcome": "not_executed",
                    "error_code": "validation_failed",
                },
                client_id=client_id,
                connection_id=connection.connection_id,
                db_type=connection.db_type,
            )
            payload = {
                "success": False,
                "skill_name": skill_name,
                "mode": "execute",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
                "execution_outcome": "not_executed",
                "error_code": "validation_failed",
                "error": "Validation failed for mutation.",
                "validation": validation,
            }
            return _skill_tool_result(
                payload,
                meta,
                mode="execute",
                start_time=start_time,
                connection=connection,
                audit_logged=audit_logged,
                preview_token_required=True,
                preview_token_validated=True,
                preview_token_consumed=True,
                preview_token_id=token_id,
            )

        try:
            if meta._managed_mutation_plan is not None:
                result = run_managed_mutation(
                    plan=meta._managed_mutation_plan,
                    adapter=adapter,
                    audit_logger=runtime.audit,
                    params=validated_params,
                    execution_binding=execution_binding,
                    skill_name=skill_name,
                    mode="execute",
                    client_id=client_id,
                    connection_id=connection.connection_id,
                    db_type=connection.db_type,
                )
            else:
                # Invoke the framework method directly instead of using
                # virtual dispatch through the custom Skill instance.
                if mutation is None:
                    raise RuntimeError(
                        "Mutation framework did not instantiate the imperative Skill."
                    )
                result = MutationBase.run_execute(
                    mutation,
                    validated_params,
                    skill_name=skill_name,
                    mode="execute",
                    client_id=client_id,
                    connection_id=connection.connection_id,
                    db_type=connection.db_type,
                    execution_binding=execution_binding,
                )
            # The framework runners own result validation and outcome
            # classification. Keep only a narrow protocol-boundary guard
            # for framework tampering or regressions.
            expected_success_outcome = (
                "committed" if meta._managed_mutation_plan is not None else "unknown"
            )
            if (
                not isinstance(result, MutationExecutionResult)
                or result.get("success") is not True
                or result.execution_outcome != expected_success_outcome
            ):
                raise RuntimeError(
                    "Mutation framework returned an invalid execution result."
                )
            result_outcome = result.execution_outcome
        except Exception as execution_error:
            if isinstance(execution_error, MutationExecutionError):
                execution_failure = execution_error
            else:
                # The loader rejects wrapper overrides and the call above
                # bypasses subclass dispatch. This final guard covers a
                # framework fault or base-level runtime tampering; after
                # a write, neither can justify a rollback claim.
                sanitized = adapter._handle_error(execution_error)
                try:
                    failure_audit_logged = runtime.audit.log(
                        skill_name=skill_name,
                        params=validated_params,
                        mode="execute",
                        result={
                            "success": False,
                            "error": sanitized,
                            "execution_outcome": "unknown",
                            "error_code": "execution_outcome_unknown",
                        },
                        client_id=client_id,
                        connection_id=connection.connection_id,
                        db_type=connection.db_type,
                    )
                except Exception as audit_error:
                    logger.warning(
                        "Mutation fallback failure audit failed: %s",
                        audit_error.__class__.__name__,
                    )
                    failure_audit_logged = False
                execution_failure = MutationExecutionError(
                    sanitized,
                    execution_outcome="unknown",
                    error_code="execution_outcome_unknown",
                    audit_logged=failure_audit_logged,
                )
            payload = {
                "success": False,
                "skill_name": skill_name,
                "mode": "execute",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
                "execution_outcome": execution_failure.execution_outcome,
                "error_code": execution_failure.error_code,
                "error": str(execution_failure),
                "idempotent": meta.idempotent,
            }
            return _skill_tool_result(
                payload,
                meta,
                mode="execute",
                start_time=start_time,
                connection=connection,
                audit_logged=execution_failure.audit_logged,
                preview_token_required=True,
                preview_token_validated=True,
                preview_token_consumed=True,
                preview_token_id=token_id,
            )

        # The selected framework runner has already validated the result
        # and classified managed-statement or imperative evidence.
        audit_marker = result.pop("_audit_logged", None)
        if isinstance(audit_marker, bool):
            audit_logged = audit_marker
        else:
            # Missing framework bookkeeping is unexpected, but audit is
            # still best-effort and cannot change a known DB outcome.
            try:
                audit_logged = runtime.audit.log(
                    skill_name=skill_name,
                    params=validated_params,
                    mode="execute",
                    result={**result, "execution_outcome": result_outcome},
                    client_id=client_id,
                    connection_id=connection.connection_id,
                    db_type=connection.db_type,
                )
            except Exception as audit_error:
                logger.warning(
                    "Mutation fallback success audit failed: %s",
                    audit_error.__class__.__name__,
                )
                audit_logged = False
        payload = {
            "success": True,
            "skill_name": skill_name,
            "mode": "execute",
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
            "execution_outcome": result_outcome,
            "result": result,
            "idempotent": meta.idempotent,
        }
        try:
            await ctx.info(
                f"Mutation '{skill_name}' handler completed: "
                f"outcome={result_outcome}, rowcount={result.get('rowcount')}"
            )
            return _skill_tool_result(
                payload,
                meta,
                mode="execute",
                start_time=start_time,
                connection=connection,
                row_count=result.get("rowcount"),
                audit_logged=audit_logged,
                preview_token_required=True,
                preview_token_validated=True,
                preview_token_consumed=True,
                preview_token_id=token_id,
            )
        except Exception as response_error:
            logger.error(
                "Mutation response handling failed after Skill outcome %s: %s",
                result_outcome,
                response_error.__class__.__name__,
            )
            fallback_payload = {
                **payload,
                "success": False,
                "execution_outcome": result_outcome,
                "error_code": "response_preparation_failed",
                "error": (
                    "Mutation handling completed, but response preparation "
                    "did not complete normally; the database outcome shown "
                    "in execution_outcome has not been upgraded."
                ),
            }
            # The original result may itself be unserializable. Keep
            # only a bounded scalar summary in the fallback response.
            fallback_rowcount = result.get("rowcount")
            if type(fallback_rowcount) is not int:
                fallback_rowcount = None
            fallback_payload["result"] = (
                {"rowcount": fallback_rowcount} if fallback_rowcount is not None else {}
            )
            return _skill_tool_result(
                fallback_payload,
                meta,
                mode="execute",
                start_time=start_time,
                connection=connection,
                row_count=fallback_rowcount,
                audit_logged=audit_logged,
                preview_token_required=True,
                preview_token_validated=True,
                preview_token_consumed=True,
                preview_token_id=token_id,
            )
