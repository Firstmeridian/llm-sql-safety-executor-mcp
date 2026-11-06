"""B34: denial guidance describes the enforced scope without changing targets."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.core.queries import query
from sql_safety_executor.core.types import NullContext
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.skills.catalog import SkillMetadata
from sql_safety_executor.skills.tools import execute_query_skill


def adapter_for(context, resolved=None):
    return SimpleNamespace(
        analysis_context=context,
        resolve_analysis_context=Mock(return_value=resolved or context),
        cte_case_sensitive=False,
    )


def assert_target_recovery(hint):
    assert "intended data target and authorization" in hint
    assert "only if it is the correct target and already authorized" in hint
    assert "ask the user" in hint
    assert "do not automatically choose an alias or substitute tables" in hint
    assert "schema qualification or table/CTE case" in hint
    assert "Keep the same connection" not in hint


@pytest.mark.parametrize("read_mode,allowed_tables", [
    ("all", frozenset({"*"})),
    ("allowlist", frozenset({"*"})),  # Legacy wildcard follows the same scope.
    ("all", None),  # Legacy unrestricted declaration is also schema-bound.
])
@pytest.mark.parametrize("path", ["mysql_static", "mysql_resolved", "sqlite"])
def test_wildcard_denial_reports_actual_schema_not_an_allowlist(path, read_mode, allowed_tables):
    context = DialectContext("sqlite" if path == "sqlite" else "mysql", default_schema="ActualSchema")
    resolved = replace(context, default_schema="ResolvedSchema", sql_modes=frozenset({"ANSI_QUOTES"})) if path == "mysql_resolved" else context
    adapter = adapter_for(context, resolved)
    sql = 'SELECT n FROM "Other"."Orders"' if path == "mysql_resolved" else "SELECT n FROM Other.Orders"
    policy = ConnectionPolicy(
        read_mode=read_mode, allowed_tables=allowed_tables,
        case_sensitive_tables=True, default_schema="PolicyFallback",
    )

    decision = _validate_sql_query_policy(None, sql, policy, adapter=adapter)

    assert not decision.allowed and decision.error_code == "table_access_denied"
    assert "Access denied to table(s): Other.Orders." in decision.message
    expected_schema = "ResolvedSchema" if path == "mysql_resolved" else "ActualSchema"
    assert f"default schema '{expected_schema}'" in decision.message
    assert "other schemas are outside its read scope" in decision.message
    assert "PolicyFallback" not in decision.message
    assert "allowlist" not in decision.message and "*" not in decision.message
    assert_target_recovery(decision.hint)
    if path == "mysql_static":
        adapter.resolve_analysis_context.assert_not_called()
    else:
        adapter.resolve_analysis_context.assert_called_once_with()


@pytest.mark.parametrize("use_adapter,policy_schema,case_sensitive,expected_schema", [
    (True, "PolicySchema", True, "PolicySchema"),
    (False, "PolicySchema", True, "PolicySchema"),
    (False, None, False, "main"),
])
def test_default_schema_fallback_matches_permission_check(use_adapter, policy_schema, case_sensitive, expected_schema):
    policy = ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}),
        default_schema=policy_schema, case_sensitive_tables=case_sensitive,
    )
    adapter = adapter_for(DialectContext("mysql", default_schema=None)) if use_adapter else None
    decision = _validate_sql_query_policy(None, "SELECT n FROM Other.Orders", policy, adapter=adapter)

    assert not decision.allowed and decision.error_code == "table_access_denied"
    assert f"default schema '{expected_schema}'" in decision.message
    assert "None" not in decision.message and "*" not in decision.message
    assert _validate_sql_query_policy(None, f"SELECT n FROM {expected_schema}.Orders", policy, adapter=adapter).allowed


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("policy_schema,context_schema,grant_schema", [
    (None, "ActualSchema", "ActualSchema"),
    ("FixedSchema", "ActualSchema", "FixedSchema"),
    ("FixedSchema", None, "FixedSchema"),
])
def test_allowlist_shows_bound_grants_and_keeps_case(structured, policy_schema, context_schema, grant_schema):
    policy = ConnectionPolicy(
        allowed_tables=frozenset({"LegacyDisplay"} if structured else {"Orders", "Elsewhere.Report"}),
        allowed_relations=frozenset({RelationReference("Orders"), RelationReference("Report", "Elsewhere")}) if structured else None,
        case_sensitive_tables=True, default_schema=policy_schema,
    )
    adapter = adapter_for(DialectContext("mysql", default_schema=context_schema))
    denied = _validate_sql_query_policy(None, f"SELECT n FROM {grant_schema}.orders", policy, adapter=adapter)

    assert not denied.allowed and denied.error_code == "table_access_denied"
    assert f"Access denied to table(s): {grant_schema}.orders." in denied.message
    assert "table allowlist permits:" in denied.message
    assert f"{grant_schema}.Orders" in denied.message and "Elsewhere.Report" in denied.message
    assert "LegacyDisplay" not in denied.message
    assert "all tables" not in denied.message
    assert_target_recovery(denied.hint)
    for target in (f"{grant_schema}.Orders", "Elsewhere.Report"):
        assert _validate_sql_query_policy(None, f"SELECT n FROM {target}", policy, adapter=adapter).allowed
    assert _validate_sql_query_policy(None, "SELECT n FROM Other.Orders", policy, adapter=adapter).error_code == "table_access_denied"


@pytest.mark.parametrize("name,sql_name,display", [
    ("Sales.Orders", "`Sales.Orders`", '"Sales.Orders"'),
    ("*", "`*`", '"*"'),
    ('A"B', '`A"B`', 'A"B'),
])
def test_structured_literal_names_are_not_reparsed_as_grants(name, sql_name, display):
    policy = ConnectionPolicy(
        allowed_tables=frozenset({f'Target.{display}'}),
        allowed_relations=frozenset({RelationReference(name, "Target")}),
        default_schema="Target", case_sensitive_tables=True,
    )
    adapter = adapter_for(DialectContext("mysql", default_schema="Target"))

    assert _validate_sql_query_policy(None, f"SELECT n FROM Target.{sql_name}", policy, adapter=adapter).allowed
    denied = _validate_sql_query_policy(None, "SELECT n FROM Target.Orders", policy, adapter=adapter)
    assert not denied.allowed and denied.error_code == "table_access_denied"
    assert f"table allowlist permits: Target.{display}." in denied.message
    assert "all tables" not in denied.message
    blocked = _validate_sql_query_policy(None, 'SELECT n FROM Other.`Sales.Orders`', policy, adapter=adapter)
    assert 'Access denied to table(s): Other."Sales.Orders".' in blocked.message


def test_empty_structured_grants_do_not_advertise_stale_display_names():
    policy = ConnectionPolicy(
        allowed_tables=frozenset({"LegacyDisplay"}), allowed_relations=frozenset(),
        default_schema="Target", case_sensitive_tables=True,
    )
    decision = _validate_sql_query_policy(None, "SELECT n FROM Target.LegacyDisplay", policy)
    assert not decision.allowed and decision.error_code == "table_access_denied"
    assert decision.message.endswith("table allowlist permits: (none).")


@pytest.mark.parametrize("requested_connection", [None, "target"])
@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
async def test_query_and_query_skill_preserve_resolved_target_without_io(requested_connection, read_mode):
    policy = ConnectionPolicy(
        read_mode=read_mode, allowed_tables=frozenset({"*"} if read_mode == "all" else {"Orders"}),
        case_sensitive_tables=True, default_schema="TargetSchema",
    )
    configs = {
        alias: DatabaseConfig(alias, "mysql", 5, 5, policy, mysql_database=schema)
        for alias, schema in (("target", "TargetSchema"), ("elsewhere", "Other"))
    }
    adapter = adapter_for(DialectContext("mysql", default_schema="TargetSchema"))
    adapter.resolve_analysis_context.side_effect = AssertionError("Definite denial must not open a session")
    adapter.execute_read = Mock(side_effect=AssertionError("Denied SQL reached execution"))
    registry = SimpleNamespace(
        get_config=Mock(side_effect=lambda alias=None: configs[alias or "target"]),
        get_adapter=Mock(return_value=adapter),
    )
    sql = "SELECT n FROM Other.Orders"
    meta = SkillMetadata("scope-report", "query", "query.sql", "low", "Scope guidance regression", _sql_template=sql)
    runtime = SimpleNamespace(
        registry=registry,
        config=SimpleNamespace(
            server=SimpleNamespace(limits=SimpleNamespace(sql_chars=0)),
            skills=SimpleNamespace(policy=SimpleNamespace(exclude_profiles=()), audit=SimpleNamespace(queries=False)),
        ),
        catalog=SimpleNamespace(
            get_skills_cache=Mock(return_value={meta.name: meta}),
            load_query=Mock(return_value=(sql, {})),
        ),
    )

    raw = await query(runtime, sql, NullContext(), connection_id=requested_connection)
    skill = await execute_query_skill(runtime, meta.name, {}, NullContext(), connection_id=requested_connection)

    for result, source in ((raw, "query"), (skill, "skill_name")):
        payload = result.structured_content
        assert not payload["success"] and payload["error_code"] == "table_access_denied"
        assert payload["connection_id"] == result.meta["connection_id"] == "target"
        assert payload["db_type"] == "mysql"
        assert set(payload) == {"success", "error_code", "error", "hint", "connection_id", "db_type", source}
        assert "Other.Orders" in payload["error"] and "TargetSchema" in payload["error"]
        assert_target_recovery(payload["hint"])
    assert raw.structured_content["error"] == skill.structured_content["error"]
    assert raw.structured_content["hint"] == skill.structured_content["hint"]
    assert registry.get_config.call_args_list == [call(requested_connection), call(requested_connection)]
    assert registry.get_adapter.call_args_list == [call("target"), call("target")]
    adapter.resolve_analysis_context.assert_not_called()
    adapter.execute_read.assert_not_called()
