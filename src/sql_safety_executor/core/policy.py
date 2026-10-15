from __future__ import annotations
import re
import logging
import sqlparse
from collections.abc import Callable
from sqlparse import tokens as sql_tokens
from sqlparse.sql import Function, Identifier, IdentifierList, Parenthesis, TokenList, Where
from typing import Any
from sql_safety_executor.core.sql import (
    classify_sql_statement,
    has_unsafe_mysql_comment_semantics,
    sql_token_upper,
)
from .decisions import PolicyDecision
from .structure import cte_declaration_token_ids, decode_identifier, parse_with_clause
from .structure import membership_relation_targets as _membership_relation_targets, relation_targets as _relation_targets
from .structure import significant_sql_tokens as _significant_sql_tokens
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.base import DatabaseAdapter
from sql_safety_executor.database.identifiers import ascii_identifier_lower as _ascii_identifier_lower
from sql_safety_executor.database.relations import RelationReference

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import (
    _EXPLAIN_UPDATE_MODIFIERS,
    _EXPLAIN_INSERT_MODIFIERS,
    _EXPLAIN_REPLACE_MODIFIERS,
    _EXPLAIN_DELETE_MODIFIERS,
)


def _effective_policy(
    runtime, policy: ConnectionPolicy | None = None
) -> ConnectionPolicy:
    """Return the explicit policy or the default connection policy."""
    return policy or runtime.registry.get_config().policy


def _is_table_allowed(
    runtime, table_name: str, policy: ConnectionPolicy | None = None, *,
    schema: str | None = None,
) -> bool:
    """
    Check if a table is in the allowlist.

    Args:
        table_name: Name of the table to check

    Returns:
        True if table is allowed (or no allowlist configured), False otherwise
    """
    allowed_tables = _effective_policy(runtime, policy).allowed_tables
    if allowed_tables is None:
        return True  # No allowlist - allow all
    return _effective_policy(runtime, policy).allows_metadata_table(table_name, schema)


def _normalize_sql_identifier(identifier: str) -> str:
    """Remove common SQL identifier quoting without treating it as authorization."""
    # sqlparse has already separated token whitespace. Decoded quoted names
    # can contain significant leading/trailing spaces: do not erase identity.
    return decode_identifier(identifier)


def _identifier_name_parts(token_list: TokenList) -> tuple[str | None, str]:
    """Decode lexical identifier components once, preserving quoted contents.

    sqlparse get_real_name() already removes a quote layer but leaves doubled
    delimiters encoded. Reinterpreting that decoded string as SQL quoting can
    turn a physical name such as "[f]" into f. Work from the original tokens.
    """
    parts = _significant_sql_tokens(token_list)
    if not parts:
        raise ValueError("Identifier has no name")
    schema = None
    target = parts[0]
    if len(parts) >= 3 and parts[1].value == ".":
        if any(part.value == "." for part in parts[3:]):
            raise ValueError("Unsupported multi-component qualification")
        schema = _normalize_sql_identifier(target.value)
        target = parts[2]
    if isinstance(target, (Identifier, Function)):
        nested_schema, name = _identifier_name_parts(target)
        if nested_schema is not None:
            raise ValueError("Unsupported nested qualification")
    else:
        name = _normalize_sql_identifier(target.value)
    return schema, name


def _cte_names(statement: TokenList, fold: Callable[[str], str] = _ascii_identifier_lower) -> set[str]:
    """Collect top-level CTE aliases so they are not treated as base tables."""
    clause = parse_with_clause(statement)
    return {fold(entry.name) for entry in clause.definitions} if clause is not None else set()


def _table_references_from_target(
    token: Any,
    cte_names: set[str],
    *,
    allow_column_list: bool = False,
    allow_table_function: bool = False,
    fold: Callable[[str], str] = _ascii_identifier_lower,
    cte_fold: Callable[[str], str] | None = None,
) -> list[RelationReference]:
    """Extract complete table references from one FROM/JOIN target token."""
    cte_fold = cte_fold or fold
    if isinstance(token, IdentifierList):
        references: list[RelationReference] = []
        for identifier in token.get_identifiers():
            references.extend(
                _table_references_from_target(
                    identifier,
                    cte_names,
                    allow_column_list=allow_column_list,
                    allow_table_function=allow_table_function,
                    fold=fold, cte_fold=cte_fold,
                )
            )
        return references

    if isinstance(token, Identifier):
        # Derived tables are rejected by the extended policy. Refuse other
        # parenthesized/function-shaped targets here rather than guessing which
        # object an allowlist should authorize.
        if any(isinstance(child, Parenthesis) for child in token.tokens) or (
            not (allow_column_list or allow_table_function)
            and any(isinstance(child, Function) for child in token.tokens)
        ):
            raise ValueError("Parenthesized table target is unsupported")
        table_name = token.get_real_name()
        if not table_name:
            raise ValueError("Table target has no resolvable name")
        schema_name, table_name = _identifier_name_parts(token)
        if schema_name is not None:
            return [RelationReference(fold(table_name), fold(schema_name))]
        if (
            not any(isinstance(child, Function) for child in token.tokens)
            and cte_fold(table_name) in cte_names
        ):
            return []
        return [RelationReference(fold(table_name))]

    if isinstance(token, Function) and (allow_column_list or allow_table_function):
        table_name = token.get_real_name()
        if not table_name:
            raise ValueError("DML table target has no resolvable name")
        return [RelationReference(fold(_identifier_name_parts(token)[1]))]

    if token.ttype in sql_tokens.Name or (
        (token.ttype in sql_tokens.Keyword or token.ttype in sql_tokens.Operator.Comparison)
        and token.value.isidentifier()
    ):
        # Contextual names such as window/offset are legal SQLite targets.
        # The lexer also labels Unicode lookalikes as keywords. They must
        # still produce an authorized relation, never disappear as syntax.
        table_name = _normalize_sql_identifier(token.value)
        if cte_fold(table_name) in cte_names:
            return []
        return [RelationReference(fold(table_name))]

    raise ValueError(f"Unsupported table target: {token.value!r}")


def _explained_dml_table_references(
    top_level: list[Any],
    cte_names: set[str],
    fold: Callable[[str], str] = _ascii_identifier_lower,
    cte_fold: Callable[[str], str] | None = None,
) -> list[RelationReference]:
    """Extract a write target from non-executing MySQL EXPLAIN-family SQL."""
    dml_index = next(
        (
            index
            for index, token in enumerate(top_level[1:], start=1)
            if token.ttype is sql_tokens.DML
        ),
        None,
    )
    if dml_index is None:
        return []

    command = sql_token_upper(top_level[dml_index])
    if command == "DELETE":
        # MySQL's second multi-table form is:
        # DELETE [modifiers] FROM target_list USING table_references ...
        # Restrict USING-as-tables to this primary DELETE context so ordinary
        # SELECT/JOIN ... USING(column) is never interpreted as a table list.
        from_index = dml_index + 1
        while (
            from_index < len(top_level)
            and sql_token_upper(top_level[from_index]) in _EXPLAIN_DELETE_MODIFIERS
        ):
            from_index += 1
        if (
            from_index >= len(top_level)
            or sql_token_upper(top_level[from_index]) != "FROM"
        ):
            return []
        using_index = next(
            (
                index
                for index in range(from_index + 1, len(top_level))
                if top_level[index].ttype in sql_tokens.Keyword
                and sql_token_upper(top_level[index]) == "USING"
            ),
            None,
        )
        if using_index is None:
            return []
        if using_index + 1 >= len(top_level):
            raise ValueError("EXPLAIN DELETE USING has no table target")
        return _table_references_from_target(
            top_level[using_index + 1],
            cte_names,
            fold=fold, cte_fold=cte_fold,
        )

    modifiers_by_command = {
        "UPDATE": _EXPLAIN_UPDATE_MODIFIERS,
        "INSERT": _EXPLAIN_INSERT_MODIFIERS,
        "REPLACE": _EXPLAIN_REPLACE_MODIFIERS,
    }
    if command not in modifiers_by_command:
        # SELECT sources and DELETE ... FROM targets are collected by the
        # normal FROM/JOIN traversal.
        return []

    target_index = dml_index + 1
    modifiers = modifiers_by_command[command]
    while (
        target_index < len(top_level)
        and sql_token_upper(top_level[target_index]) in modifiers
    ):
        target_index += 1
    if (
        command in {"INSERT", "REPLACE"}
        and target_index < len(top_level)
        and sql_token_upper(top_level[target_index]) == "INTO"
    ):
        target_index += 1
    if target_index >= len(top_level):
        raise ValueError(f"EXPLAIN {command} has no table target")

    return _table_references_from_target(
        top_level[target_index],
        cte_names,
        allow_column_list=command in {"INSERT", "REPLACE"},
        fold=fold, cte_fold=cte_fold,
    )


def _collect_table_references(
    token_list: TokenList,
    cte_names: set[str],
    *,
    strict: bool,
    fold: Callable[[str], str] = _ascii_identifier_lower,
    cte_fold: Callable[[str], str] | None = None,
) -> list[RelationReference]:
    """Walk parsed SQL and collect every FROM/JOIN base-table reference."""
    cte_fold = cte_fold or fold
    references: list[RelationReference] = []
    tokens = _significant_sql_tokens(token_list)
    try:
        clause = parse_with_clause(token_list)
    except ValueError:
        if strict:
            raise
        clause = None
    if clause is not None:
        # A later CTE is not visible inside an earlier definition in MySQL.
        # Without RECURSIVE, a definition's own name can resolve to a physical
        # table. Passing every alias to every body silently authorized those
        # base tables. Keep the scope local and grow it in declaration order.
        try:
            visible = set(cte_names)
            for entry in clause.definitions:
                name = cte_fold(entry.name)
                body_scope = visible | {name} if clause.recursive else set(visible)
                references.extend(_collect_table_references(
                    entry.body.parse(), body_scope, strict=strict, fold=fold, cte_fold=cte_fold,
                ))
                visible.add(name)
            references.extend(_collect_table_references(
                clause.query.parse(), visible, strict=strict, fold=fold, cte_fold=cte_fold,
            ))
            return references
        except (AttributeError, IndexError, TypeError, ValueError):
            if strict:
                raise ValueError("Could not safely resolve CTE scope") from None
            # Structural system-schema checks still inspect unambiguous FROM
            # references when restrictive allowlist extraction will reject.
    membership_targets = {id(target) for target in _membership_relation_targets(tokens)}
    for target in _relation_targets(tokens):
        try:
            references.extend(_table_references_from_target(
                target, cte_names, fold=fold, cte_fold=cte_fold,
                allow_table_function=id(target) in membership_targets,
            ))
        except ValueError:
            if strict:
                raise
    for token in tokens:
        if isinstance(token, TokenList):
            references.extend(
                _collect_table_references(
                    token, cte_names, strict=strict, fold=fold, cte_fold=cte_fold
                )
            )
    return references


def _extract_relation_references(
    sql: str, *, strict: bool = True, case_sensitive: bool = False,
    cte_case_sensitive: bool | None = None
) -> list[RelationReference]:
    """Extract complete base-table references for restrictive allowlists.

    This intentionally supports a conservative subset rather than pretending
    to be a validating SQL parser. Ambiguous table-valued functions or derived
    targets raise ``ValueError`` so a configured allowlist fails closed.
    Schema-qualified references remain qualified and therefore require an
    exact qualified allowlist entry; a basename cannot authorize another
    schema's table.
    """
    normalized_sql = _normalize_sql_for_policy(sql)
    statements = [
        statement
        for statement in sqlparse.parse(normalized_sql)
        if str(statement).strip(" \t\r\n;")
    ]
    if len(statements) != 1 and strict:
        raise ValueError("Expected exactly one SQL statement")
    if len(statements) != 1:
        return []

    statement = statements[0]
    fold: Callable[[str], str] = (lambda name: name) if case_sensitive else _ascii_identifier_lower
    cte_sensitive = case_sensitive if cte_case_sensitive is None else cte_case_sensitive
    cte_fold = (lambda name: name) if cte_sensitive else _ascii_identifier_lower
    try:
        cte_names = _cte_names(statement, cte_fold)
    except ValueError:
        if strict:
            raise
        cte_names = set()
    references = _collect_table_references(
        statement,
        set(),
        strict=strict,
        fold=fold, cte_fold=cte_fold,
    )
    top_level = _significant_sql_tokens(statement)

    if top_level:
        command = sql_token_upper(top_level[0])
        has_explained_dml = command in {"EXPLAIN", "DESCRIBE", "DESC"} and any(
            token.ttype is sql_tokens.DML for token in top_level[1:]
        )
        if has_explained_dml:
            try:
                references.extend(
                    _explained_dml_table_references(top_level, cte_names, fold, cte_fold)
                )
            except ValueError:
                if strict:
                    raise
        elif command in {"DESCRIBE", "DESC"}:
            if len(top_level) < 2:
                if strict:
                    raise ValueError(f"{command} has no table target")
            else:
                try:
                    references.extend(
                        _table_references_from_target(
                            top_level[1], cte_names, fold=fold, cte_fold=cte_fold
                        )
                    )
                except ValueError:
                    if strict:
                        raise
        elif command == "EXPLAIN":
            # MySQL also supports EXPLAIN tbl_name. EXPLAIN SELECT/DELETE/etc.
            # is already covered by the FROM/JOIN traversal and must not treat
            # SELECT itself as a table.
            if len(top_level) != 2 and strict:
                raise ValueError("Unsupported EXPLAIN table form")
            if len(top_level) == 2:
                try:
                    references.extend(
                        _table_references_from_target(
                            top_level[1], cte_names, fold=fold, cte_fold=cte_fold
                        )
                    )
                except ValueError:
                    if strict:
                        raise

    return sorted(set(references), key=lambda reference: reference.display_name)


def _extract_tables_from_sql(
    sql: str, *, strict: bool = True, case_sensitive: bool = False,
    cte_case_sensitive: bool | None = None,
) -> list[str]:
    """Display projection for diagnostics/matrices; never an authorization key."""
    return [relation.display_name for relation in _extract_relation_references(
        sql, strict=strict, case_sensitive=case_sensitive,
        cte_case_sensitive=cte_case_sensitive,
    )]


def _resolve_query_tables(
    sql: str, policy: ConnectionPolicy, *, adapter: DatabaseAdapter | None = None,
    strict: bool = True, probe: bool = False,
) -> list[RelationReference]:
    """Resolve CTE scope independently from physical table spelling/grants.

    Probe only a genuine exact-vs-insensitive ambiguity, and only when even
    the insensitive interpretation has no definitely unauthorized table.
    Static startup checks and metadata projections never initiate a probe.
    """
    if not policy.case_sensitive_tables:
        return _extract_relation_references(sql, strict=strict, case_sensitive=True, cte_case_sensitive=False)
    exact = _extract_relation_references(sql, strict=strict, case_sensitive=True, cte_case_sensitive=True)
    if adapter is None or "with" not in _ascii_identifier_lower(sql):
        return exact
    folded = _extract_relation_references(sql, strict=strict, case_sensitive=True, cte_case_sensitive=False)
    if exact == folded:
        return exact
    known = adapter.cte_case_sensitive
    if known is False:
        return folded
    if known is True or not probe:
        return exact
    if policy.read_mode != "all" and any(not policy.allows_relation(table) for table in folded):
        return exact
    return exact if adapter.resolve_cte_case_sensitive() else folded


def _check_table_allowlist(
    runtime, sql: str, policy: ConnectionPolicy | None = None, *,
    adapter: DatabaseAdapter | None = None,
) -> PolicyDecision:
    effective = _effective_policy(runtime, policy)
    allowed_tables = effective.allowed_tables
    if allowed_tables is None or "*" in allowed_tables:
        return PolicyDecision.allow()
    try:
        tables = _resolve_query_tables(sql, effective, adapter=adapter, probe=True)
    except (AttributeError, TypeError, ValueError):
        return PolicyDecision.deny(
            "relation_scope_unresolved", "Table allowlist could not safely determine every referenced table",
            "Use supported explicit relation references and CTEs; keep schema and name case aligned with the connection policy.",
        )
    blocked = [table.display_name for table in tables if not effective.allows_relation(table)]
    if blocked:
        return PolicyDecision.deny(
            "table_access_denied",
            f"Access denied to table(s): {', '.join(blocked)}. Only allowed tables: {', '.join(sorted(allowed_tables))}",
            "Keep the same connection and use authorized tables. If CTE name rules are unknown or case-sensitive, match the declaration's exact case.",
        )
    return PolicyDecision.allow()


def _validate_sql_query_policy(
    runtime, sql: str, policy: ConnectionPolicy | None = None, *,
    adapter: DatabaseAdapter | None = None,
) -> PolicyDecision:
    """Shared structured decision for raw queries and Query Skills."""
    effective = _effective_policy(runtime, policy)
    if effective.read_mode == "deny" or (
        effective.read_mode == "allowlist" and not effective.allowed_tables
    ):
        return PolicyDecision.deny("read_disabled", "Reading is disabled by the target connection read policy.")
    shape = classify_sql_statement(sql)
    if not shape.allowed:
        return shape
    extended = _is_query_safe_extended(runtime, sql, policy)
    if not extended.allowed:
        return extended
    # All-scope Skills also need correct inferred readiness dependencies.
    # Structural refusal must occur before even this constant metadata probe.
    if effective.read_mode == "all" and effective.case_sensitive_tables and adapter is not None and "with" in _ascii_identifier_lower(sql):
        _resolve_query_tables(sql, effective, adapter=adapter, strict=False, probe=True)
    return _check_table_allowlist(runtime, sql, policy, adapter=adapter)


def _validate_sql_template_startup_policy(runtime, sql: str) -> PolicyDecision:
    """Check structure at startup; connection authorization is checked at execution."""
    shape = classify_sql_statement(sql)
    if not shape.allowed:
        return shape
    return _is_query_safe_extended(
        runtime, sql, runtime.registry.get_config().policy,
        require_union_allowlist=False,
    )


def _is_valid_identifier(name: str) -> bool:
    """
    Validate a table/column name before it is used as an SQL identifier.

    Security measures:
    - Allow a conservative letter/digit/underscore/CJK grammar
    - Block quotes, comments, and other SQL syntax characters
    - Enforce the MySQL-compatible 64-character identifier limit

    Reserved words are not rejected here. Callers quote identifiers for the
    selected adapter; this helper limits identifier shape, not SQL vocabulary.
    """
    if not name or len(name) > 64:  # MySQL identifier max length
        return False

    # Conservative pattern: Latin letters, digits, underscores, and the
    # explicitly supported CJK range. The first character cannot be a digit.
    if not re.match(r"^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$", name):
        return False

    # Defense-in-depth: secondary check for dangerous patterns
    # (already blocked by the strict regex above, kept as safety net)
    dangerous_patterns = [
        r"[\'\"`;\\]",  # Quotes and escape chars
        r"--",  # SQL comment
        r"/\*",  # Block comment start
        r"\*/",  # Block comment end
        r"\x00",  # Null byte
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, name):
            return False

    return True


def _normalize_sql_for_policy(sql: str) -> str:
    """Normalize SQL tokens without changing quoted names or literal contents."""
    try:
        return sqlparse.format(sql, strip_comments=True, strip_whitespace=True).strip()
    except Exception:
        # Preserve the original identity; the downstream parser decides whether
        # this statement can be analyzed. Never fall back to whole-string regex.
        return sql.strip()


_ACCOUNT_FUNCTIONS = frozenset(
    {"user", "current_user", "session_user", "system_user", "current_role"}
)

# These names are reserved in both raw reads and Query Skills. This is a narrow
# call restriction, not a whitelist of all SQL functions or a cost estimator.
_LOCK_FUNCTIONS = frozenset({"get_lock", "release_lock", "release_all_locks"})
_EXPENSIVE_FUNCTIONS = frozenset({"sleep", "benchmark"})


def _cte_header_token_ids(token_list: TokenList) -> set[int]:
    """Exclude declaration names/column lists, which are not function calls."""
    return cte_declaration_token_ids(token_list)


def _read_function_decision(statements: tuple[TokenList, ...]) -> PolicyDecision:
    """Recognize actual calls, including quoted names, without joining literals."""
    for statement in statements:
        excluded = _cte_header_token_ids(statement)
        tokens = list(statement.flatten())
        significant = [t for t in tokens if not t.is_whitespace and t.ttype not in sql_tokens.Comment]
        for current, following in zip(significant, significant[1:]):
            if id(current) in excluded or following.value != "(":
                continue
            if current.ttype in sql_tokens.String.Single:
                continue
            name = _ascii_identifier_lower(_normalize_sql_identifier(current.value))
            if name == "load_file":
                return PolicyDecision.deny("file_operation_denied", "MySQL server-side file operations are not allowed")
            if name in _ACCOUNT_FUNCTIONS:
                return PolicyDecision.deny("server_state_denied", "Account and role functions are not allowed in queries.")
            if name in _LOCK_FUNCTIONS:
                return PolicyDecision.deny("lock_function_denied", f"Lock function {name.upper()}() is not allowed in read queries.",
                    "Keep the same connection and use ordinary reads. Lock coordination requires a trusted operation managing acquisition and release on one connection.")
            if name in _EXPENSIVE_FUNCTIONS:
                return PolicyDecision.deny("expensive_function_denied", f"Delay or benchmark function {name.upper()}() is not allowed in read queries.",
                    "Keep the same connection and use ordinary SQL expressions, filters and aggregates; remove deliberate sleeps and benchmarking calls.")
    return PolicyDecision.allow()

# Reserve SQLite's documented built-in PRAGMA object names on every backend.
# Do not reserve the entire prefix: business columns, aliases, and tables such
# as pragma_orders are ordinary data. Keeping this list explicit also avoids
# opening a database while validating a Skill template or rendering a prompt.
# https://sqlite.org/pragma.html#pragma_list
_SQLITE_PRAGMA_OBJECTS = frozenset(
    "pragma_" + name
    for name in """
    analysis_limit application_id auto_vacuum automatic_index busy_timeout
    cache_size cache_spill case_sensitive_like cell_size_check checkpoint_fullfsync
    collation_list compile_options count_changes data_store_directory data_version
    database_list default_cache_size defer_foreign_keys empty_result_callbacks
    encoding foreign_key_check foreign_key_list foreign_keys freelist_count
    full_column_names fullfsync function_list hard_heap_limit ignore_check_constraints
    incremental_vacuum index_info index_list index_xinfo integrity_check journal_mode
    journal_size_limit legacy_alter_table legacy_file_format locking_mode max_page_count
    mmap_size module_list optimize page_count page_size pragma_list query_only quick_check
    read_uncommitted recursive_triggers reverse_unordered_selects schema_version
    secure_delete short_column_names shrink_memory soft_heap_limit stats synchronous
    table_info table_list table_xinfo temp_store temp_store_directory threads
    trusted_schema user_version vdbe_addoptrace vdbe_debug vdbe_listing vdbe_trace
    wal_autocheckpoint wal_checkpoint writable_schema
    """.split()
)


def _relation_object_names(token: Any) -> list[str]:
    """Read object names only in a FROM/JOIN target, including SQLite quoting.

    sqlparse represents double-quoted function names as an Identifier followed
    by a Parenthesis, and SQLite also accepts single quotes in table positions.
    Those tokens are identifiers here, but remain data in SELECT expressions.
    """
    if isinstance(token, IdentifierList):
        return [
            name
            for item in token.get_identifiers()
            for name in _relation_object_names(item)
        ]
    if isinstance(token, Parenthesis):
        inner = _significant_sql_tokens(token)[1:-1]
        if len(inner) >= 3 and inner[1].value == ".":
            return _relation_object_names(inner[2])
        return _relation_object_names(inner[0]) if inner else []
    if isinstance(token, Identifier):
        parts = _significant_sql_tokens(token)
        if not parts:
            return []
        # get_real_name() can return the alias for SQLite's single-quoted or
        # parenthesized table forms. Read the target before the alias instead.
        target = parts[0]
        if len(parts) >= 3 and parts[1].value == ".":
            target = parts[2]
        return _relation_object_names(target)
    if isinstance(token, Function):
        return [_ascii_identifier_lower(_identifier_name_parts(token)[1])]
    elif token.ttype in sql_tokens.Name or token.ttype in sql_tokens.String:
        name = token.value
    else:
        return []
    if not name:
        return []
    if len(name) >= 2 and name[0] == name[-1] == "'":
        name = name[1:-1].replace("''", "'")
    # These ASCII built-in spellings must not absorb distinct Unicode names.
    return [_ascii_identifier_lower(_normalize_sql_identifier(name))]



def _has_pragma_object_reference(token_list: TokenList) -> bool:
    tokens = _significant_sql_tokens(token_list)
    if any(
        name in _SQLITE_PRAGMA_OBJECTS
        for target in _relation_targets(tokens)
        for name in _relation_object_names(target)
    ):
        return True
    for token in tokens:
        if isinstance(token, TokenList) and _has_pragma_object_reference(token):
            return True
    return False


def _is_parenthesized_relation_target(token: Any) -> bool:
    if isinstance(token, Parenthesis):
        return True
    if isinstance(token, IdentifierList):
        return any(_is_parenthesized_relation_target(item) for item in token.get_identifiers())
    if isinstance(token, Identifier):
        parts = _significant_sql_tokens(token)
        return bool(parts and isinstance(parts[0], Parenthesis))
    return False


def _has_parenthesized_relation_target(token_list: TokenList) -> bool:
    """Fail closed for grouped JOIN targets, just as for derived FROM tables.

    The conservative table extractor does not resolve a bare table group such
    as JOIN (mysql.user). With all-table scope there is no restrictive allowlist
    fallback, so silently ignoring such a group would bypass system-schema
    checks. Function arguments are not relation groups and are not rejected by
    this guard; their existing policies still apply.
    """
    tokens = _significant_sql_tokens(token_list)
    if any(_is_parenthesized_relation_target(target) for target in _relation_targets(tokens)):
        return True
    for token in tokens:
        if isinstance(token, TokenList) and _has_parenthesized_relation_target(token):
            return True
    return False


def _nonstandard_relation_reference(token_list: TokenList) -> bool:
    """Reject relation quoting/wrappers the authorization extractor cannot map.

    SQLite's legacy single-quoted table names can be mistaken for aliases by
    sqlparse, and MySQL's ODBC braces hide an entire relation from extraction.
    Standard identifier quoting and ordinary quoted data remain supported.
    """
    tokens = _significant_sql_tokens(token_list)
    for target in _relation_targets(tokens, preserve_qualification=True):
        parts = _significant_sql_tokens(target) if isinstance(target, Identifier) else [target]
        if len(parts) >= 3 and parts[1].value == ".":
            parts = [parts[0], parts[2]]
        else:
            parts = parts[:1]
        if any(part.ttype in sql_tokens.String.Single or part.value == "{" for part in parts):
            return True
    return any(
        _nonstandard_relation_reference(token)
        for token in tokens if isinstance(token, TokenList)
    )


def _server_state_reference_error(sql: str) -> str | None:
    """Reject SELECT-shaped reads of server, account or database-file state.

    Such values (host names, data paths, file privileges, accounts) are not
    table data, so table scope cannot authorize them. Token-based so string
    literals and quoted identifiers are not misread as references.
    """
    try:
        statements = sqlparse.parse(sql)
    except Exception:
        return "Query could not be parsed for server-state checks"
    if any(_has_pragma_object_reference(statement) for statement in statements):
        return (
            "SQLite PRAGMA table-valued functions are not allowed in "
            "queries; use list_tables() or describe_table() instead "
            "(describe_table() also returns indexes)."
        )
    functions = _read_function_decision(statements)
    if functions.error_code == "server_state_denied":
        return functions.message
    tokens = [
        token
        for statement in statements
        for token in statement.flatten()
        if not token.is_whitespace and token.ttype not in sql_tokens.Comment
    ]
    for token in tokens:
        if token.ttype in sql_tokens.String:
            continue
        value = _ascii_identifier_lower(token.value)
        if token.ttype in sql_tokens.Keyword and value == "table":
            return "TABLE query expressions are not supported; use SELECT with FROM instead."
        if token.ttype in sql_tokens.Operator and value == "@@":
            return (
                "System variables (@@...) are not allowed in queries; they "
                "expose server configuration rather than table data."
            )
        if value == "current_user":
            return "Account and role functions are not allowed in queries."
    return None


def _is_query_safe_extended(
    runtime, sql: str, policy: ConnectionPolicy | None = None, *, require_union_allowlist: bool = True,
) -> PolicyDecision:
    """Structural checks share token semantics; literals are never keywords."""
    if has_unsafe_mysql_comment_semantics(sql):
        return PolicyDecision.deny("unsafe_comment", "Ambiguous or executable MySQL comment syntax is not allowed")
    normalized_sql = _normalize_sql_for_policy(sql)
    effective = _effective_policy(runtime, policy)
    try:
        statements = sqlparse.parse(normalized_sql)
        functions = _read_function_decision(statements)
        if not functions.allowed:
            return functions
        tokens = [token for statement in statements for token in statement.flatten()
                  if not token.is_whitespace and token.ttype not in sql_tokens.Comment]
        structural = [token for token in tokens if token.ttype not in sql_tokens.String]
        if structural and sql_token_upper(structural[0]) == "SHOW":
            return PolicyDecision.deny("show_statement_denied", "SHOW statements are not allowed in raw queries.",
                                       "Use list_tables() or describe_table(); describe_table() also returns indexes.")
        for index, token in enumerate(structural):
            command = sql_token_upper(token)
            following = sql_token_upper(structural[index + 1]) if index + 1 < len(structural) else ""
            if token.ttype in sql_tokens.Keyword and command == "INTO" and following in {"OUTFILE", "DUMPFILE"}:
                return PolicyDecision.deny("file_operation_denied", "MySQL server-side file operations are not allowed")
        server_state_error = _server_state_reference_error(normalized_sql)
        if server_state_error:
            return PolicyDecision.deny("server_state_denied", server_state_error)
        if any(_has_parenthesized_relation_target(statement) for statement in statements):
            return PolicyDecision.deny("relation_group_unsupported", "Parenthesized FROM/JOIN targets are not allowed; use a CTE instead.")
        if any(_nonstandard_relation_reference(statement) for statement in statements):
            return PolicyDecision.deny("relation_quoting_unsupported", "Single-quoted table names and ODBC relation wrappers are not supported; use standard identifier quoting and explicit FROM/JOIN targets.")
        references = _extract_relation_references(normalized_sql, strict=False)
        if any(reference.schema is not None and _ascii_identifier_lower(reference.schema) in {"mysql", "performance_schema", "information_schema", "sys"} for reference in references):
            return PolicyDecision.deny("system_schema_denied", "Access to system databases not allowed.", "Use list_tables() or describe_table(); describe_table() also returns indexes.")
        if any(token.ttype in sql_tokens.Keyword and sql_token_upper(token) in {"UNION", "UNION ALL"} for token in tokens):
            if require_union_allowlist and not effective.allow_union:
                return PolicyDecision.deny("union_disabled", "UNION queries disabled for security on this connection.",
                    "Prefer one permitted query without UNION (scalar subqueries, EXISTS/NOT EXISTS, JOIN or a CTE) when it keeps the task's meaning. If you run separate queries, aggregate in SQL and check truncation, duplicates and ordering before combining; do not switch connections.")
            if require_union_allowlist and effective.allowed_tables is None:
                return PolicyDecision.deny("union_scope_required", "UNION requires an explicit table allowlist on the selected connection.", "Configure that connection's read policy with an explicit allowlist or all scope to enable.")
    except (AttributeError, IndexError, TypeError, ValueError):
        return PolicyDecision.deny("sql_parse_failed", "Query could not be safely analyzed.", "Use one supported SQL statement with explicit relation targets.")
    return PolicyDecision.allow()
