"""Project read policy over shared dialect analysis; grants stay independent."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .analysis import SQLAnalysis, analyze_sql
from .decisions import PolicyDecision
from .read_rules import restricted_function_code, _ACCOUNT_FUNCTIONS, _SQLITE_PRAGMA_OBJECTS
from sql_safety_executor.database.base import DatabaseAdapter
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.identifiers import ascii_identifier_lower
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext


@dataclass(frozen=True)
class ReadPlan:
    decision: PolicyDecision
    analysis: SQLAnalysis


def _effective_policy(runtime, policy=None) -> ConnectionPolicy:
    return policy or runtime.registry.get_config().policy


def classify_analysis(analysis: SQLAnalysis) -> PolicyDecision:
    codes = {
        "empty": ("empty_sql", "SQL query is empty."),
        "unsafe_comment": ("unsafe_comment", "Unsupported, ambiguous or executable comment syntax is not allowed"),
        "executing_explain": ("executing_explain_denied", "EXPLAIN ANALYZE is not allowed."),
        "session_inspection": ("session_inspection_denied", "Inspecting another database session is not allowed."),
        "pragma": ("pragma_statement_denied", "Raw PRAGMA statements are not allowed; use metadata tools."),
        "unsupported_binding": ("parameter_binding_unsupported", "Positional parameter markers are not supported by this read interface."),
    }
    if analysis.statement_kind in codes:
        code, message = codes[analysis.statement_kind]
        hint = ("Use list_tables() or describe_table(); describe_table() also returns indexes." if code == "pragma_statement_denied"
                else "Use EXPLAIN without ANALYZE." if code == "executing_explain_denied"
                else "Use a reviewed Query Skill with named parameters; query() has no positional binding argument." if code == "parameter_binding_unsupported"
                else None)
        return PolicyDecision.deny(code, message, hint)
    if analysis.status == "failed" or analysis.statement_kind == "unknown" or "cte_body" in analysis.unsupported:
        code = "multiple_statements" if "multiple_statements" in analysis.unsupported else "sql_parse_failed"
        message = "Exactly one SQL statement is allowed per call." if code == "multiple_statements" else "SQL could not be completely analyzed for this connection."
        if analysis.statement_kind == "with" or "cte_body" in analysis.unsupported:
            message = "Could not safely analyze this WITH statement."
        return PolicyDecision.deny(code, message, "Keep the same connection. Check CTE declarations and supported read syntax, or simplify to one read statement.")
    if analysis.statement_kind not in {"select", "explain", "show"}:
        return PolicyDecision.deny("read_only_required", "Only read-only queries allowed (SELECT, DESCRIBE, non-ANALYZE EXPLAIN)", "For an intended write, discover reviewed mutation Skills with list_skills(); preview and obtain explicit approval before execution. Discovery does not authorize a write.")
    if analysis.has_nested_write:
        return PolicyDecision.deny("nested_write_denied", "Write statements inside a read query are not allowed.")
    return PolicyDecision.allow()


def _analysis_decision(analysis: SQLAnalysis, policy: ConnectionPolicy, *, require_union=True) -> PolicyDecision:
    if "sql_mode_not_supported" in analysis.unsupported:
        return PolicyDecision.deny("sql_mode_unsupported", "The connection SQL mode includes a parsing feature not supported by this version.", "Keep the same connection; ask the maintainer to review its SQL mode configuration.")
    if "odbc_relation" in analysis.unsupported:
        return PolicyDecision.deny("relation_quoting_unsupported", "ODBC relation wrappers are not supported; use explicit FROM/JOIN targets.")
    shape = classify_analysis(analysis)
    if not shape.allowed:
        return shape
    if analysis.statement_kind == "show":
        return PolicyDecision.deny("show_statement_denied", "SHOW statements are not allowed in raw queries.", "Use list_tables() or describe_table(); describe_table() also returns indexes.")
    function_code = restricted_function_code(analysis.functions)
    if function_code == "file_operation_denied" or analysis.has_file_output:
        return PolicyDecision.deny("file_operation_denied", "MySQL server-side file operations are not allowed")
    if analysis.has_session_assignment:
        return PolicyDecision.deny("session_assignment_denied", "Assigning session variables is not allowed in read queries.", "Keep the same connection; return values as query columns instead of assigning session variables.")
    if analysis.has_locking_read and analysis.statement_kind != "explain":
        return PolicyDecision.deny("locking_read_denied", "Locking reads are not allowed through the ordinary read interface.", "Keep the same connection and use an ordinary SELECT. Transaction lock coordination requires a reviewed operation owning acquisition and release.")
    if function_code == "lock_function_denied":
        return PolicyDecision.deny("lock_function_denied", "Lock functions are not allowed in read queries.", "Keep the same connection and use ordinary reads. Lock coordination requires a trusted operation managing acquisition and release on one connection.")
    if function_code == "expensive_function_denied":
        return PolicyDecision.deny("expensive_function_denied", "Delay or benchmark functions are not allowed in read queries.", "Keep the same connection and use ordinary SQL expressions, filters and aggregates; remove deliberate sleeps and benchmarking calls.")
    if analysis.has_system_variable:
        return PolicyDecision.deny("server_state_denied", "System variable access is not allowed in read queries.", "Keep the same connection; remove the system-variable expression and query authorized business data.")
    if function_code == "server_state_denied" and analysis.functions & _ACCOUNT_FUNCTIONS:
        return PolicyDecision.deny("server_state_denied", "Account and role functions are not allowed in read queries.", "Keep the same connection; use authorized business data without account or role inspection.")
    if function_code == "server_state_denied" or any(ascii_identifier_lower(ref.name) in _SQLITE_PRAGMA_OBJECTS for ref in analysis.relations):
        return PolicyDecision.deny("server_state_denied", "SQLite PRAGMA state access is not allowed through query SQL.", "Use list_tables() or describe_table() for supported metadata on the same connection.")
    if analysis.has_derived_relation:
        return PolicyDecision.deny("relation_group_unsupported", "Parenthesized FROM/JOIN targets and subqueries in FROM are not allowed; use a CTE instead.")
    if "relation_quoting_unsupported" in analysis.unsupported:
        return PolicyDecision.deny("relation_quoting_unsupported", "Use standard identifier quoting for the selected connection's SQL mode.")
    if any(ref.schema is not None and ascii_identifier_lower(ref.schema) in {"mysql", "performance_schema", "information_schema", "sys"} for ref in analysis.relations):
        return PolicyDecision.deny("system_schema_denied", "Access to system databases not allowed.", "Use list_tables() or describe_table(); describe_table() also returns indexes.")
    default_schema = analysis.context_key[3] if len(analysis.context_key) > 3 else None
    if any(use.kind == "builtin" and use.schema is not None and default_schema is not None
           and policy.table_key(use.schema) != policy.table_key(default_schema)
           for use in analysis.virtual_relations):
        return PolicyDecision.deny("relation_scope_unresolved", "Builtin table functions are supported only in the default schema.", "Keep the same connection and use an unqualified builtin table function.")
    if not analysis.complete:
        if "table_query_expression" in analysis.unsupported:
            return PolicyDecision.deny("relation_scope_unresolved", "TABLE query expressions are not supported; use SELECT with an explicit FROM target.")
        return PolicyDecision.deny("relation_scope_unresolved", "Table allowlist could not safely determine every referenced table or supported SQL construct.", "Keep the same connection and use supported explicit relation references and CTEs.")
    if require_union and analysis.has_union and not policy.allow_union:
        return PolicyDecision.deny("union_disabled", "UNION queries disabled for security on this connection.", "Prefer one permitted query without UNION (scalar subqueries, EXISTS/NOT EXISTS, JOIN or a CTE) when it keeps the task's meaning. If you run separate queries, aggregate in SQL and check truncation, duplicates and ordering before combining; do not switch connections.")
    if require_union and analysis.has_union and policy.allowed_tables is None:
        return PolicyDecision.deny("union_scope_required", "UNION requires an explicit table allowlist on the selected connection.")
    return PolicyDecision.allow()


def _blocked_relations_decision(blocked, policy):
    return PolicyDecision.deny("table_access_denied", f"Access denied to table(s): {', '.join(ref.display_name for ref in blocked)}. Only allowed tables: {', '.join(sorted(policy.allowed_tables or ())) }", "Keep the same connection and use authorized tables; preserve the connection's CTE name rules and explicit schema scope.")


def _prepare_sql_read(runtime, sql: str, policy=None, *, adapter: DatabaseAdapter | None = None) -> ReadPlan:
    effective = _effective_policy(runtime, policy)
    if effective.read_mode == "deny" or effective.read_mode == "allowlist" and not effective.allowed_tables:
        return ReadPlan(PolicyDecision.deny("read_disabled", "Reading is disabled by the target connection read policy."), SQLAnalysis("failed", "unknown"))
    context = adapter.analysis_context if adapter is not None else DialectContext("mysql" if effective.case_sensitive_tables else "sqlite", cte_case_sensitive=effective.case_sensitive_tables, default_schema=effective.default_schema or (None if effective.case_sensitive_tables else "main"))
    if not isinstance(context, DialectContext):
        return ReadPlan(PolicyDecision.deny("session_semantics_unavailable", "The adapter did not provide a valid SQL interpretation context."), SQLAnalysis("failed", "unknown"))
    analysis = analyze_sql(sql, context)
    decision = _analysis_decision(analysis, effective)
    # A rejection whose interpretation is mode-independent needs no connection.
    if not decision.allowed and (context.dialect == "sqlite" or '"' not in sql and "\\" not in sql):
        return ReadPlan(decision, analysis)
    if decision.allowed and context.dialect == "mysql" and '"' not in sql and "\\" not in sql:
        # An unavoidable physical dependency does not need a connection just
        # to learn its mode. For unknown CTE case, only reject the intersection
        # of exact/folded dependencies; never treat later/self CTEs as visible.
        possible = analyze_sql(sql, replace(context, cte_case_sensitive=False)) if analysis.ctes and adapter is not None and adapter.cte_case_sensitive is None else analysis
        if possible.complete:
            definite = [ref for ref in analysis.relations if ref in possible.relations and not effective.allows_relation(ref, default_schema=context.default_schema)]
            if definite:
                return ReadPlan(_blocked_relations_decision(definite, effective), analysis)
    if adapter is not None:
        try:
            resolved = adapter.resolve_analysis_context()
        except DatabaseQueryError as error:
            return ReadPlan(PolicyDecision.deny(error.error_code, str(error)), analysis)
        if resolved != context:
            context = resolved
            analysis = analyze_sql(sql, context)
            decision = _analysis_decision(analysis, effective)
    if not decision.allowed:
        return ReadPlan(decision, analysis)
    if analysis.ctes and effective.case_sensitive_tables and adapter is not None and adapter.cte_case_sensitive is None:
        folded = analyze_sql(sql, replace(context, cte_case_sensitive=False))
        if folded.complete and analysis.relations != folded.relations and all(effective.allows_relation(ref, default_schema=context.default_schema) for ref in folded.relations):
            if not adapter.resolve_cte_case_sensitive():
                analysis = folded
    blocked = [ref for ref in analysis.relations if not effective.allows_relation(ref, default_schema=context.default_schema)]
    if blocked:
        decision = _blocked_relations_decision(blocked, effective)
    return ReadPlan(decision, analysis)


def _validate_sql_query_policy(runtime, sql, policy=None, *, adapter=None) -> PolicyDecision:
    return _prepare_sql_read(runtime, sql, policy, adapter=adapter).decision


def _validate_sql_template_startup_policy(runtime, sql: str) -> PolicyDecision:
    # A template is not yet bound to a target. These are explicit candidate
    # interpretation contexts, never execution fallbacks or additional grants.
    contexts = [DialectContext("sqlite"), *[DialectContext("mysql", frozenset(modes)) for modes in [(), ("ANSI_QUOTES",), ("NO_BACKSLASH_ESCAPES",), ("ANSI_QUOTES", "NO_BACKSLASH_ESCAPES")]]]
    policy = _effective_policy(runtime)
    first = _analysis_decision(analyze_sql(sql, contexts[0]), policy, require_union=False)
    if first.allowed:
        return first
    for context in contexts[1:]:
        decision = _analysis_decision(analyze_sql(sql, context), policy, require_union=False)
        if decision.allowed:
            return decision
    return first


def _resolve_query_tables(sql, policy, *, adapter=None, strict=True, probe=False):
    context = adapter.analysis_context if adapter is not None else DialectContext("sqlite", cte_case_sensitive=policy.case_sensitive_tables)
    analysis = analyze_sql(sql, context)
    if analysis.ctes and policy.case_sensitive_tables and adapter is not None and adapter.cte_case_sensitive is None:
        folded = analyze_sql(sql, replace(context, cte_case_sensitive=False))
        if folded.complete and folded.relations != analysis.relations and probe and all(policy.allows_relation(ref, default_schema=context.default_schema) for ref in folded.relations):
            if not adapter.resolve_cte_case_sensitive():
                analysis = folded
    if not analysis.complete:
        raise ValueError("SQL dependency analysis is incomplete")
    return list(analysis.relations)


def _extract_relation_references(sql, *, strict=True, case_sensitive=False, cte_case_sensitive=None, context=None):
    context = context or DialectContext("sqlite", cte_case_sensitive=case_sensitive if cte_case_sensitive is None else cte_case_sensitive)
    analysis = analyze_sql(sql, context)
    if not analysis.complete:
        raise ValueError("SQL dependency analysis is incomplete")
    return list(analysis.relations if case_sensitive else [ref.key(case_sensitive=False) for ref in analysis.relations])


def _extract_tables_from_sql(sql, **kwargs):
    return [ref.display_name for ref in _extract_relation_references(sql, **kwargs)]


def _is_query_safe_extended(runtime, sql, policy=None, *, require_union_allowlist=True):
    return _analysis_decision(analyze_sql(sql, DialectContext("sqlite")), _effective_policy(runtime, policy), require_union=require_union_allowlist)


def _server_state_reference_error(sql):
    decision = _analysis_decision(analyze_sql(sql, DialectContext("sqlite")), ConnectionPolicy(allowed_tables=frozenset({"*"})))
    return decision.message if decision.error_code == "server_state_denied" else None


def _is_table_allowed(runtime, table_name, policy=None, *, schema=None):
    return _effective_policy(runtime, policy).allows_metadata_table(table_name, schema)
