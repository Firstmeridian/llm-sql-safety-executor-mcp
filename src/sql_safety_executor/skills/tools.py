from __future__ import annotations
import logging
import time
from typing import Annotated, Any
from pydantic import Field
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    OperationContext as Context,
    OperationResult as ToolResult,
)
from sql_safety_executor.skills.catalog import validate_name, validate_params

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import (
    SKILLS_SEARCH_MAX_LENGTH,
    SKILLS_CATEGORY_MAX_LENGTH,
    _CONNECTION_ID_FIELD,
    SkillListDetailLevel,
    SkillDetailProjection,
)

from sql_safety_executor.core.connections import _resolve_connection_context
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.core.results import (
    _context_client_id,
    _serialize_result,
    _skill_tool_result,
    _tool_result,
    _truncate_result,
)
from sql_safety_executor.skills.access import (
    _aggregate_skill_categories,
    _ensure_query_skill_policy_ready,
    _ensure_skill_profile_allowed,
    _ensure_skill_schema_ready,
    _get_skill_schema_snapshot,
    _normalize_optional_filter,
    _normalize_skill_detail_level,
    _normalize_skill_detail_projection,
    _project_skill_execution_meta,
    _project_skill_meta,
    _resolve_available_only,
    _resolve_skill_connection,
    _skill_availability_state,
    _skill_matches,
)


async def list_skills(
    runtime,
    ctx: Context,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring search over skill names, "
                "descriptions, triggers, category, type, risk, profiles, "
                "tables, connection_ids, and related skills."
            ),
            max_length=SKILLS_SEARCH_MAX_LENGTH,
        ),
    ] = None,
    category: Annotated[
        str | None,
        Field(
            description=(
                "Optional exact category filter. Skills without a category are "
                "grouped as 'uncategorized'."
            ),
            max_length=SKILLS_CATEGORY_MAX_LENGTH,
        ),
    ] = None,
    detail_level: Annotated[
        SkillListDetailLevel,
        Field(
            description=(
                "Metadata projection: compact, summary, or full. Full "
                "includes params and needs no get_skill_detail() follow-up. "
                "The default is the server's skills.discovery.default_detail "
                "TOML startup setting."
            )
        ),
    ] = "summary",
    available_only: Annotated[
        bool,
        Field(
            description=(
                "When true, return only skills executable for the target "
                "connection, including Skill connection_ids scope, DB "
                "compatibility, mutation switch, connection policy, and "
                "schema readiness. Pass false to inspect the full catalog. "
                "The default is the server's "
                "skills.discovery.available_only TOML startup setting."
            ),
        ),
    ] = True,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """List all available pre-defined skills (query and mutation)."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    try:
        resolved_detail_level = _normalize_skill_detail_level(detail_level)
        resolved_available_only = _resolve_available_only(available_only)
        normalized_search = _normalize_optional_filter(
            search,
            "search",
            SKILLS_SEARCH_MAX_LENGTH,
        )
        normalized_category = _normalize_optional_filter(
            category,
            "category",
            SKILLS_CATEGORY_MAX_LENGTH,
        )
    except ValueError as e:
        await ctx.warning(f"Skill listing parameter error: {e}")
        raise ToolError(str(e)) from e

    await ctx.info(
        "Listing available skills "
        f"for connection={connection.connection_id}, "
        f"(detail_level={resolved_detail_level}, "
        f"available_only={resolved_available_only}, "
        f"search={normalized_search!r}, category={normalized_category!r})"
    )

    skills = runtime.catalog.get_skills_cache()
    schema_snapshot = _get_skill_schema_snapshot(runtime, connection)
    matched_catalog = [
        meta
        for name, meta in sorted(skills.items())
        if _skill_matches(meta, normalized_search, normalized_category)
    ]
    availability_by_name = {
        meta.name: _skill_availability_state(runtime, meta, schema_snapshot, connection)
        for meta in matched_catalog
    }
    available_count = sum(
        1 for meta in matched_catalog if availability_by_name[meta.name]["executable"]
    )
    unavailable_count = len(matched_catalog) - available_count
    schema_unready_count = sum(
        1
        for meta in matched_catalog
        if not availability_by_name[meta.name]["schema_ready"]
    )
    profile_excluded_count = sum(
        1
        for meta in matched_catalog
        if not availability_by_name[meta.name]["profile_allowed"]
    )
    policy_blocked_count = sum(
        1
        for meta in matched_catalog
        if not availability_by_name[meta.name]["policy_allowed"]
    )
    connection_scope_blocked_count = sum(
        1
        for meta in matched_catalog
        if not availability_by_name[meta.name]["connection_scope_allowed"]
    )
    connection_type_conflict_count = sum(
        1
        for meta in matched_catalog
        if any(
            conflict["connection_id"] == connection.connection_id
            for conflict in availability_by_name[meta.name]["connection_type_conflicts"]
        )
    )
    matched = [
        meta
        for meta in matched_catalog
        if not resolved_available_only or availability_by_name[meta.name]["executable"]
    ]
    skills_list = [
        _project_skill_meta(
            meta,
            resolved_detail_level,
            availability_by_name[meta.name],
        )
        for meta in matched
    ]

    query_count = sum(1 for meta in matched if meta.type == "query")
    mutation_count = sum(1 for meta in matched if meta.type == "mutation")

    await ctx.info(
        f"Found {len(skills_list)} skill(s): "
        f"{query_count} query, {mutation_count} mutation"
    )

    result: dict[str, Any] = {
        "success": True,
        "skills": skills_list,
        "total_skills": len(skills),
        "matched_skills": len(skills_list),
        "matched_catalog_skills": len(matched_catalog),
        "available_skills": available_count,
        "unavailable_skills": unavailable_count,
        "filtered_unavailable_skills": unavailable_count
        if resolved_available_only
        else 0,
        "schema_unready_skills": schema_unready_count,
        "policy_blocked_skills": policy_blocked_count,
        "connection_scope_blocked_skills": connection_scope_blocked_count,
        "connection_type_conflict_skills": connection_type_conflict_count,
        "profile_excluded_skills": profile_excluded_count,
        "query_skills": query_count,
        "mutation_skills": mutation_count,
        "mutations_enabled": runtime.config.skills.mutation.enabled,
        "schema_check_enabled": schema_snapshot.enabled,
        "schema_check_available": schema_snapshot.available,
        "excluded_profiles": sorted(runtime.config.skills.policy.exclude_profiles),
        "detail_level": resolved_detail_level,
        "available_only": resolved_available_only,
        "current_database_type": connection.db_type,
        "connection_id": connection.connection_id,
        "search": normalized_search,
        "category": normalized_category,
        "categories": _aggregate_skill_categories(matched),
    }
    if resolved_detail_level != "full":
        result["hint"] = (
            "If params are not already known, call get_skill_detail("
            "skill_name, connection_id, detail_level='execution') with the "
            "same target connection before execution."
        )
    return _tool_result(
        runtime,
        result,
        tool_name="list_skills",
        start_time=start_time,
        success=True,
        connection=connection,
        matched_skills=len(skills_list),
        available_skills=available_count,
        total_skills=len(skills),
    )


async def get_skill_detail(
    runtime,
    skill_name: Annotated[str, Field(description="Name of the skill to inspect")],
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    detail_level: Annotated[
        SkillDetailProjection,
        Field(
            description=(
                "Use execution (recommended) for params/schema and the next "
                "action. Use full only when catalog or readiness diagnostics "
                "are explicitly needed. Defaults to full."
            )
        ),
    ] = "full",
) -> ToolResult:
    """Return cached execution fields or full metadata for one Skill."""
    start_time = time.perf_counter()
    connection = _resolve_connection_context(runtime, connection_id)
    await ctx.info(
        "Getting skill detail for connection "
        f"'{connection.connection_id}': {skill_name}"
    )

    try:
        validate_name(skill_name)
        resolved_detail_level = _normalize_skill_detail_projection(detail_level)
    except ValueError as e:
        await ctx.warning(f"Skill detail parameter error: {e}")
        raise ToolError(str(e)) from e

    skills = runtime.catalog.get_skills_cache()
    if skill_name not in skills:
        msg = f"Skill '{skill_name}' not found"
        await ctx.warning(msg)
        raise ToolError(msg)

    meta = skills[skill_name]
    schema_snapshot = _get_skill_schema_snapshot(runtime, connection)
    availability = _skill_availability_state(runtime, meta, schema_snapshot, connection)
    if meta.type == "query" and availability["executable"]:
        usage_hint = (
            "Call execute_query_skill(skill_name, params, connection_id) "
            "with this same target connection and params matching the schema."
        )
    elif availability["executable"]:
        usage_hint = (
            "Call execute_mutation_skill(skill_name, params, confirm=false, "
            "connection_id=connection_id) "
            "to preview, then pass the returned preview_token with "
            "confirm=true on the same connection."
        )
    else:
        usage_hint = (
            availability["disabled_reason"]
            or "Skill execution is unavailable on this connection."
        )

    if resolved_detail_level == "execution":
        projected_skill = _project_skill_execution_meta(meta, availability)
    else:
        projected_skill = _project_skill_meta(meta, "full", availability)

    result: dict[str, Any] = {
        "success": True,
        "skill": projected_skill,
        "connection_id": connection.connection_id,
        "current_database_type": connection.db_type,
        "usage_hint": usage_hint,
    }
    if resolved_detail_level == "full":
        result.update(
            {
                "mutations_enabled": runtime.config.skills.mutation.enabled,
                "schema_check_enabled": schema_snapshot.enabled,
                "schema_check_available": schema_snapshot.available,
            }
        )

    return _tool_result(
        runtime,
        result,
        tool_name="get_skill_detail",
        start_time=start_time,
        success=True,
        connection=connection,
        skill_name=skill_name,
        skill_type=meta.type,
    )


async def execute_query_skill(
    runtime,
    skill_name: Annotated[str, Field(description="Name of the query skill to execute")],
    params: Annotated[
        dict[str, Any],
        Field(description="Parameters for the skill (must match skill_def.md schema)"),
    ],
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """Execute a pre-defined query skill with parameterized SQL."""
    start_time = time.perf_counter()

    try:
        validate_name(skill_name)
        meta = runtime.catalog.get_skills_cache().get(skill_name)
        if meta is None:
            raise FileNotFoundError(f"Skill '{skill_name}' not found")
        if meta.type != "query":
            raise TypeError(
                f"Skill '{skill_name}' is type '{meta.type}', expected 'query'"
            )
        # Preserve the global default-connection contract when omitted,
        # then fail closed against the Skill metadata scope before adapter
        # construction or any database access.
        connection = _resolve_skill_connection(runtime, meta, connection_id)
        sql_template, param_schema = runtime.catalog.load_query(skill_name)
        validated_params = validate_params(params, param_schema)
    except (ValueError, TypeError, FileNotFoundError, ToolError) as e:
        await ctx.warning(f"Query skill error: {e}")
        if isinstance(e, ToolError):
            raise
        raise ToolError(str(e)) from e

    await ctx.info(
        f"Executing query skill on connection "
        f"'{connection.connection_id}': {skill_name}"
    )
    client_id = _context_client_id(ctx)

    try:
        _ensure_skill_profile_allowed(runtime, meta)
        _ensure_skill_schema_ready(runtime, meta, connection)
        _ensure_query_skill_policy_ready(meta, connection)
    except ToolError as e:
        await ctx.warning(str(e))
        raise

    is_safe, safety_error = _validate_sql_query_policy(
        runtime, sql_template, connection.policy
    )
    if not is_safe:
        msg = f"Skill '{skill_name}' failed SQL safety policy: {safety_error}"
        await ctx.warning(msg)
        raise ToolError(msg)

    # Execute parameterized query via adapter (Step 3a: params support)
    adapter = connection.adapter
    result = adapter.execute(sql_template, params=validated_params)

    # Handle error (adapter returns error string on failure)
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Query skill failed: {result}")
        if runtime.config.skills.audit.queries:
            runtime.audit.log(
                skill_name=skill_name,
                params=validated_params,
                mode="query",
                result={"success": False, "error": result},
                client_id=client_id,
                connection_id=connection.connection_id,
                db_type=connection.db_type,
            )
        raise ToolError(result)

    # Success — serialize and truncate (reuse existing helpers)
    data = _serialize_result(result)
    total_rows = len(result) if isinstance(result, list) else 0

    truncation_result = _truncate_result(runtime, data, total_rows)

    if truncation_result["truncated"]:
        await ctx.warning(
            f"Truncated returned payload: {truncation_result['returned_rows']}/{total_rows} rows shown. "
            f"Add WHERE/LIMIT/ORDER BY to limit database work and stabilize ordering."
        )
    else:
        await ctx.info(f"Query skill returned {total_rows} rows")

    audit_logged = False
    if runtime.config.skills.audit.queries:
        audit_logged = runtime.audit.log(
            skill_name=skill_name,
            params=validated_params,
            mode="query",
            result={
                "success": True,
                "rowcount": truncation_result["returned_rows"],
                "total_rows": total_rows,
                "truncated": truncation_result["truncated"],
            },
            client_id=client_id,
            connection_id=connection.connection_id,
            db_type=connection.db_type,
        )

    payload = {
        "success": True,
        "skill_name": skill_name,
        "connection_id": connection.connection_id,
        "db_type": connection.db_type,
        "data": truncation_result["data"],
        "row_count": truncation_result["returned_rows"],
        "total_rows": total_rows,
        "truncated": truncation_result["truncated"],
        "truncation_note": (
            f"Showing {truncation_result['returned_rows']}/{total_rows} fetched rows. "
            f"Truncation limits the returned payload only; add WHERE/LIMIT/ORDER BY "
            f"to limit database work and stabilize ordering."
        )
        if truncation_result["truncated"]
        else None,
    }
    return _skill_tool_result(
        payload,
        meta,
        mode="query",
        start_time=start_time,
        connection=connection,
        row_count=truncation_result["returned_rows"],
        total_rows=total_rows,
        truncated=truncation_result["truncated"],
        audit_logged=audit_logged,
    )
