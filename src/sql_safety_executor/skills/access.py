from __future__ import annotations
from sql_safety_executor.core.decisions import PolicyDecision
import logging
from typing import Any
from sql_safety_executor.core.types import (
    OperationError as ToolError,
    ConnectionContext,
    SkillSchemaSnapshot as _SkillSchemaSnapshot,
)
from sql_safety_executor.database.models import DatabaseConfig
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.outcomes import MetadataQueryError
from sql_safety_executor.core.connections import read_access_enabled
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.skills.catalog import SkillMetadata

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import (
    _SKILL_DETAIL_PROJECTION_LEVELS,
    _SKILLS_DETAIL_LEVELS,
    SkillListDetailLevel,
    SkillDetailProjection,
)

from sql_safety_executor.core.results import _require_boolean


def _normalize_skill_detail_level(
    detail_level: SkillListDetailLevel,
) -> SkillListDetailLevel:
    """Validate the already non-null list_skills projection argument."""
    if detail_level not in _SKILLS_DETAIL_LEVELS:
        allowed = ", ".join(sorted(_SKILLS_DETAIL_LEVELS))
        raise ValueError(
            f"Invalid detail_level '{detail_level}'. Allowed values: {allowed}"
        )
    return detail_level


def _normalize_skill_detail_projection(
    detail_level: SkillDetailProjection,
) -> SkillDetailProjection:
    """Validate the already non-null get_skill_detail projection argument."""
    if detail_level not in _SKILL_DETAIL_PROJECTION_LEVELS:
        allowed = ", ".join(sorted(_SKILL_DETAIL_PROJECTION_LEVELS))
        raise ValueError(
            f"Invalid detail_level '{detail_level}'. Allowed values: {allowed}"
        )
    return detail_level


def _resolve_available_only(available_only: bool) -> bool:
    """Validate the already non-null list_skills availability filter."""
    return _require_boolean(available_only, "available_only")


def _normalize_optional_filter(
    value: str | None,
    field_name: str,
    max_length: int,
) -> str | None:
    """Normalize optional list_skills filters and reject abusive lengths."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(
            f"{field_name} is too long; maximum length is {max_length} characters"
        )
    return normalized


def _skill_category(meta: SkillMetadata) -> str:
    """Return the normalized display category for a skill."""
    return meta.category or "uncategorized"


def _skill_excluded_profiles(runtime, meta: SkillMetadata) -> list[str]:
    """Return skill profiles blocked by the current profile policy."""
    if not runtime.config.skills.policy.exclude_profiles:
        return []
    return [
        profile
        for profile in meta.profiles
        if profile.lower() in runtime.config.skills.policy.exclude_profiles
    ]


def _skill_connection_scope_state(
    runtime,
    meta: SkillMetadata,
    connection: ConnectionContext,
) -> dict[str, Any]:
    """Return the restrictive Skill metadata scope for one target.

    This metadata never grants access. It is evaluated in addition to DB
    type compatibility and all query/mutation server policies.
    """
    _configured_skill_connection_types = {
        key: value.db_type for key, value in runtime.config.connections.items()
    }
    declared = meta.connection_ids
    configured_ids = (
        [
            connection_id
            for connection_id in declared
            if connection_id in _configured_skill_connection_types
        ]
        if declared is not None
        else []
    )
    unconfigured_ids = (
        [
            connection_id
            for connection_id in declared
            if connection_id not in _configured_skill_connection_types
        ]
        if declared is not None
        else []
    )
    type_conflicts = (
        [
            {
                "connection_id": connection_id,
                "actual_db_type": _configured_skill_connection_types[connection_id],
                "supported_db_types": list(meta.databases),
            }
            for connection_id in configured_ids
            if meta.databases
            and _configured_skill_connection_types[connection_id] not in meta.databases
        ]
        if declared is not None
        else []
    )
    return {
        "connection_scope_allowed": (
            declared is None or connection.connection_id in declared
        ),
        "configured_connection_ids": configured_ids,
        "unconfigured_connection_ids": unconfigured_ids,
        "connection_type_conflicts": type_conflicts,
    }


def _ensure_skill_connection_allowed(
    meta: SkillMetadata,
    config: DatabaseConfig,
) -> None:
    """Fail closed unless target alias and DB type satisfy Skill metadata."""
    if (
        meta.connection_ids is not None
        and config.connection_id not in meta.connection_ids
    ):
        raise ToolError(
            f"Skill '{meta.name}' cannot run on connection "
            f"'{config.connection_id}'; allowed connection_ids: "
            f"{meta.connection_ids}. Pass an allowed configured connection_id."
        )
    if meta.databases and config.db_type not in meta.databases:
        raise ToolError(
            f"Skill '{meta.name}' is not compatible with target connection "
            f"database type '{config.db_type}'. Supported: {meta.databases}"
        )


def _resolve_skill_connection(
    runtime,
    meta: SkillMetadata,
    requested_connection_id: str | None,
) -> ConnectionContext:
    """Apply Skill scope before creating or accessing a database adapter."""
    try:
        config = runtime.registry.get_config(requested_connection_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    _ensure_skill_connection_allowed(meta, config)
    return ConnectionContext(
        connection_id=config.connection_id,
        config=config,
        adapter=runtime.registry.get_adapter(config.connection_id),
        policy=config.policy,
    )


def _get_skill_schema_snapshot(
    runtime,
    connection: ConnectionContext,
) -> _SkillSchemaSnapshot:
    """Return an explicit Skills schema-readiness observation."""
    if not runtime.config.skills.readiness.check_schema:
        return _SkillSchemaSnapshot(
            enabled=False,
            available=False,
            table_names=frozenset(),
        )

    try:
        relations = connection.adapter.get_read_relations()
    except MetadataQueryError as exc:
        logger.warning("Skills schema readiness check unavailable: %s", exc)
        return _SkillSchemaSnapshot(
            enabled=True,
            available=False,
            table_names=frozenset(),
        )

    return _SkillSchemaSnapshot(
        enabled=True,
        available=connection.default_schema is not None,
        table_names=frozenset(
            connection.policy.relation_key(relation.reference)
            for relation in relations
        ),
        schema_name=connection.default_schema,
    )


def _query_skill_blocked_tables(
    meta: SkillMetadata,
    connection: ConnectionContext,
) -> list[str]:
    """Return required query-skill tables blocked by target allowlist."""
    if meta.type != "query" or not meta.tables:
        return []
    allowed_tables = connection.policy.allowed_tables
    if allowed_tables is None or "*" in allowed_tables:
        return []
    return [table for table in meta.tables if not connection.policy.allows_table(table)]


def _inferred_skill_relations(meta: SkillMetadata, connection: ConnectionContext) -> list[RelationReference]:
    """Keep independently inferred dependencies distinct from declarations."""
    if meta.type == "query" and meta._sql_template is not None:
        from sql_safety_executor.skills.catalog import _extract_table_references
        sensitive = connection.policy.case_sensitive_tables
        if sensitive and "WITH" in meta._sql_template.upper():
            sensitive = connection.adapter.cte_case_sensitive is not False
        if sensitive not in meta._inferred_tables:
            meta._inferred_tables[sensitive] = _extract_table_references(
                meta._sql_template, cte_case_sensitive=sensitive,
            )
        return meta._inferred_tables[sensitive]
    return []


def _required_skill_relations(meta: SkillMetadata, connection: ConnectionContext) -> list[RelationReference]:
    """Resolve inference for this target, without changing declared restrictions."""
    inferred = _inferred_skill_relations(meta, connection)
    required: dict[RelationReference, RelationReference] = {}
    declared = [RelationReference.from_declaration(table) for table in meta.tables]
    for table in [*declared, *inferred]:
        required.setdefault(connection.policy.relation_key(table), table)
    return list(required.values())


def _inferred_skill_tables(meta: SkillMetadata, connection: ConnectionContext) -> list[str]:
    return [table.display_name for table in _inferred_skill_relations(meta, connection)]


def _required_skill_tables(meta: SkillMetadata, connection: ConnectionContext) -> list[str]:
    return [table.display_name for table in _required_skill_relations(meta, connection)]


def _mutation_connection_policy_state(
    runtime,
    meta: SkillMetadata,
    connection: ConnectionContext,
) -> tuple[bool, bool, str | None]:
    """Return connection support, policy result, and rejection reason."""
    if meta.type != "mutation":
        return True, True, None

    if not runtime.config.skills.enabled or not runtime.config.skills.mutation.enabled:
        return (
            False,
            False,
            "Mutation skills require skills.enabled and skills.mutation.enabled.",
        )

    connection_supported = (
        connection.connection_id in runtime.config.skills.mutation.allowed_connections
    )
    if not connection_supported:
        return (
            False,
            False,
            "Target connection is not authorized by skills.mutation.allowed_connections.",
        )

    if not connection.policy.allow_mutations:
        return (
            True,
            False,
            "Mutation writes are disabled by the target connection policy.",
        )

    mutation_skills = connection.policy.mutation_skills
    if "*" not in mutation_skills and meta.name not in mutation_skills:
        return (
            True,
            False,
            f"Mutation skill '{meta.name}' is not authorized by the target "
            "connection policy.",
        )

    return True, True, None


def _skill_availability_state(
    runtime,
    meta: SkillMetadata,
    schema_snapshot: _SkillSchemaSnapshot,
    connection: ConnectionContext,
) -> dict[str, Any]:
    """Describe whether a discovered skill can execute in the current state."""
    reasons: list[str] = []
    missing_tables: list[str] = []
    unverified_tables: list[str] = []
    blocked_tables: list[str] = []
    excluded_profiles = _skill_excluded_profiles(runtime, meta)
    connection_scope = _skill_connection_scope_state(runtime, meta, connection)
    db_compatible = not meta.databases or connection.db_type in meta.databases
    mutation_enabled = meta.type != "mutation" or runtime.config.skills.mutation.enabled
    (
        mutation_connection_supported,
        mutation_policy_allowed,
        mutation_policy_reason,
    ) = _mutation_connection_policy_state(
        runtime,
        meta,
        connection,
    )
    profile_allowed = not excluded_profiles
    schema_ready = True
    policy_allowed = True

    if excluded_profiles:
        reasons.append(
            "Skill profile(s) are excluded by skills.policy.exclude_profiles: "
            f"{excluded_profiles}."
        )

    if not connection_scope["connection_scope_allowed"]:
        reasons.append(
            f"Target connection '{connection.connection_id}' is outside "
            f"the Skill connection_ids scope: {meta.connection_ids}."
        )

    if meta.databases and connection.db_type not in meta.databases:
        reasons.append(
            f"Target connection database type '{connection.db_type}' is not compatible; "
            f"supported: {meta.databases}."
        )
    if meta.type == "mutation" and not runtime.config.skills.mutation.enabled:
        reasons.append("Mutation skills are disabled (skills.mutation.enabled=false).")
    if mutation_policy_reason:
        reasons.append(mutation_policy_reason)
        policy_allowed = False

    blocked_tables = _query_skill_blocked_tables(meta, connection)
    if meta.type == "query":
        if meta._sql_template is None:
            policy_allowed = False
            reasons.append("Query skill SQL template is not cached (internal error).")
        else:
            decision = _query_skill_policy_decision(meta, connection)
            if decision.allowed:
                decision = _validate_sql_query_policy(
                    runtime, meta._sql_template, connection.policy,
                    adapter=connection.adapter if profile_allowed and db_compatible and connection_scope["connection_scope_allowed"] else None,
                )
            if not decision.allowed:
                policy_allowed = False
                reasons.append(f"Skill '{meta.name}' failed SQL safety policy: {decision.message}")

    required_relations = _required_skill_relations(meta, connection)
    required_tables = [table.display_name for table in required_relations]
    if schema_snapshot.enabled and required_tables:
        if not schema_snapshot.available:
            schema_ready = False
            reasons.append(
                "Required table readiness could not be verified because "
                "database metadata is unavailable for the target connection."
            )
        else:
            scope = connection.policy.table_key(schema_snapshot.schema_name) if schema_snapshot.schema_name is not None else None
            unverified_relations = [
                table for table in required_relations
                if table.schema is not None
                and connection.policy.relation_key(table).schema != scope
            ]
            unverified_tables = [table.display_name for table in unverified_relations]
            if unverified_tables:
                schema_ready = False
                reasons.append(
                    "Schema readiness does not cover required table(s): "
                    f"{unverified_tables}."
                )
            missing_tables = [
                table.display_name
                for table in required_relations
                if table not in unverified_relations
                and connection.policy.relation_key(table.in_schema(schema_snapshot.schema_name))
                not in schema_snapshot.table_names
            ]
            if missing_tables:
                schema_ready = False
                reasons.append(
                    "Required table(s) are missing from the current database "
                    f"schema: {missing_tables}."
                )

    executable = not reasons
    return {
        "executable": executable,
        "disabled_reason": " ".join(reasons) if reasons else None,
        "db_compatible": db_compatible,
        **connection_scope,
        "mutation_enabled": mutation_enabled,
        "mutation_connection_supported": mutation_connection_supported,
        "mutation_policy_allowed": mutation_policy_allowed,
        "profile_allowed": profile_allowed,
        "excluded_profiles": excluded_profiles,
        "policy_allowed": policy_allowed,
        "blocked_tables": blocked_tables,
        "schema_ready": schema_ready,
        "schema_check_enabled": schema_snapshot.enabled,
        "schema_check_available": schema_snapshot.available and not unverified_tables,
        "missing_tables": missing_tables,
        "unverified_tables": unverified_tables,
        "required_tables": required_tables,
        "declared_tables": list(meta.tables),
        "inferred_tables": list(_inferred_skill_tables(meta, connection)),
    }


def _related_available_skill_names(
    runtime,
    meta: SkillMetadata,
    connection: ConnectionContext,
) -> list[str]:
    """Return declared related mutation Skills executable on this connection."""
    skills = runtime.catalog.get_skills_cache()
    related = [
        skills[name]
        for name in meta.related_skills
        if name != meta.name
        and name in skills
        and skills[name].type == "mutation"
    ]
    if not related:
        return []
    schema_snapshot = _get_skill_schema_snapshot(runtime, connection)
    return [
        related_meta.name
        for related_meta in related
        if _skill_availability_state(
            runtime, related_meta, schema_snapshot, connection
        )["executable"]
    ]


def _ensure_skill_schema_ready(
    runtime, meta: SkillMetadata, connection: ConnectionContext
) -> None:
    """Raise a ToolError if the current database is missing required tables."""
    if not runtime.config.skills.readiness.check_schema or not _required_skill_tables(meta, connection):
        return

    schema_snapshot = _get_skill_schema_snapshot(runtime, connection)
    if not schema_snapshot.available:
        raise ToolError(
            f"Skill '{meta.name}' schema readiness could not be verified "
            "because database metadata is unavailable for the target connection."
        )

    availability = _skill_availability_state(runtime, meta, schema_snapshot, connection)
    if availability["unverified_tables"]:
        raise ToolError(
            f"Skill '{meta.name}' schema readiness could not verify table(s): "
            f"{availability['unverified_tables']}"
        )
    if availability["missing_tables"]:
        raise ToolError(
            f"Skill '{meta.name}' requires table(s) not found in the "
            f"target connection schema: {availability['missing_tables']}"
        )


def _query_skill_policy_decision(meta: SkillMetadata, connection: ConnectionContext) -> PolicyDecision:
    """Declared dependencies constrain execution independently of SQL references."""
    if not read_access_enabled(connection.policy):
        return PolicyDecision.deny("read_disabled", "Reading is disabled by the target connection read policy.")
    blocked = _query_skill_blocked_tables(meta, connection)
    if blocked:
        return PolicyDecision.deny(
            "table_access_denied",
            f"Skill '{meta.name}' requires table(s) blocked by target connection policy: {blocked}",
            "Use a Skill whose declared dependencies are authorized on the same connection.",
        )
    return PolicyDecision.allow()


def _ensure_skill_profile_allowed(runtime, meta: SkillMetadata) -> None:
    """Raise a ToolError if the skill is excluded by profile policy."""
    excluded_profiles = _skill_excluded_profiles(runtime, meta)
    if excluded_profiles:
        raise ToolError(
            f"Skill '{meta.name}' is excluded by skills.policy.exclude_profiles: "
            f"{excluded_profiles}"
        )


def _skill_matches(
    meta: SkillMetadata,
    search: str | None,
    category: str | None,
    *, required_tables: list[str] | None = None,
) -> bool:
    """Case-insensitive deterministic matching for skill discovery."""
    if category and _skill_category(meta).lower() != category.lower():
        return False

    if not search:
        return True

    haystack_parts = [
        meta.name,
        meta.type,
        meta.risk,
        meta.description,
        _skill_category(meta),
        *meta.profiles,
        *(meta.tables if required_tables is None else required_tables),
        *meta.triggers,
        *meta.related_skills,
    ]
    if meta.databases:
        haystack_parts.extend(meta.databases)
    if meta.connection_ids:
        haystack_parts.extend(meta.connection_ids)
    haystack = "\n".join(str(part).lower() for part in haystack_parts if part)
    return search.lower() in haystack


def _project_skill_meta(
    meta: SkillMetadata,
    detail_level: str,
    availability: dict[str, Any],
) -> dict[str, Any]:
    """Project cached SkillMetadata into an Agent-facing disclosure shape."""
    projected: dict[str, Any] = {
        "name": meta.name,
        "type": meta.type,
        "description": meta.description,
        "risk": meta.risk,
        "category": _skill_category(meta),
        "executable": availability["executable"],
        "profile_allowed": availability["profile_allowed"],
        "db_compatible": availability["db_compatible"],
        "connection_scope_allowed": availability["connection_scope_allowed"],
        "policy_allowed": availability["policy_allowed"],
        "schema_ready": availability["schema_ready"],
    }
    if meta.type == "mutation":
        projected["mutation_connection_supported"] = availability[
            "mutation_connection_supported"
        ]
        projected["mutation_policy_allowed"] = availability["mutation_policy_allowed"]
    if availability["disabled_reason"]:
        projected["disabled_reason"] = availability["disabled_reason"]
    if availability["excluded_profiles"]:
        projected["excluded_profiles"] = availability["excluded_profiles"]
    if availability["missing_tables"]:
        projected["missing_tables"] = availability["missing_tables"]
    if availability["unverified_tables"]:
        projected["unverified_tables"] = availability["unverified_tables"]
    if availability["blocked_tables"]:
        projected["blocked_tables"] = availability["blocked_tables"]
    if detail_level in {"summary", "full"}:
        # Keep the summary shape close to the historical list_skills()
        # response so existing clients can continue to reason from it.
        projected.update(
            {
                "source": meta.source,
                "triggers": meta.triggers,
                "idempotent": meta.idempotent,
                "databases": meta.databases,
                "connection_ids": meta.connection_ids,
                "configured_connection_ids": availability["configured_connection_ids"],
                "unconfigured_connection_ids": availability[
                    "unconfigured_connection_ids"
                ],
                "connection_type_conflicts": availability["connection_type_conflicts"],
                "profiles": meta.profiles,
            }
        )
        if meta.related_skills:
            projected["related_skills"] = meta.related_skills

    if detail_level == "full":
        projected.update(
            {
                "params": meta.params,
                "version": meta.version,
                "requires_confirmation": meta.requires_confirmation,
                "related_skills": meta.related_skills,
                "tables": availability["required_tables"],
                "schema_check_enabled": availability["schema_check_enabled"],
                "schema_check_available": availability["schema_check_available"],
                "missing_tables": availability["missing_tables"],
                "unverified_tables": availability["unverified_tables"],
            }
        )
        if meta.type == "query":
            projected.update({
                "declared_tables": availability["declared_tables"],
                "inferred_tables": availability["inferred_tables"],
            })

    return projected


def _project_skill_execution_meta(
    meta: SkillMetadata,
    availability: dict[str, Any],
) -> dict[str, Any]:
    """Project only fields needed to choose and invoke one Skill."""
    projected = {
        "name": meta.name,
        "type": meta.type,
        "params": meta.params,
        "executable": availability["executable"],
        "requires_confirmation": meta.requires_confirmation,
    }
    if availability["disabled_reason"]:
        projected["disabled_reason"] = availability["disabled_reason"]
    return projected


def _aggregate_skill_categories(skills: list[SkillMetadata]) -> list[dict[str, Any]]:
    """Aggregate category counts for the currently matched skill set."""
    counts: dict[str, int] = {}
    for meta in skills:
        category = _skill_category(meta)
        counts[category] = counts.get(category, 0) + 1
    return [
        {"category": category, "count": counts[category]} for category in sorted(counts)
    ]
