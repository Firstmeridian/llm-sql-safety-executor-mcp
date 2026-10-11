from __future__ import annotations
import re
import logging
import sqlparse
from collections.abc import Callable
from sqlparse import tokens as sql_tokens
from sqlparse.sql import Function, Identifier, IdentifierList, Parenthesis, TokenList
from typing import Any
from sql_safety_executor.core.sql import is_sql_safe, has_unsafe_mysql_comment_semantics
from sql_safety_executor.database.models import ConnectionPolicy

logger = logging.getLogger(__name__)

from sql_safety_executor.core.constants import (
    _EXPLAIN_UPDATE_MODIFIERS,
    _EXPLAIN_INSERT_MODIFIERS,
    _EXPLAIN_REPLACE_MODIFIERS,
    _EXPLAIN_DELETE_MODIFIERS,
    MYSQL_FILE_OPERATION_PATTERNS,
)


def _effective_policy(
    runtime, policy: ConnectionPolicy | None = None
) -> ConnectionPolicy:
    """Return the explicit policy or the default connection policy."""
    return policy or runtime.registry.get_config().policy


def _is_table_allowed(
    runtime, table_name: str, policy: ConnectionPolicy | None = None
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
    return _effective_policy(runtime, policy).allows_table(table_name)


def _normalize_sql_identifier(identifier: str) -> str:
    """Remove common SQL identifier quoting without treating it as authorization."""
    value = identifier.strip()
    if len(value) >= 2:
        if value[0] == "`" and value[-1] == "`":
            return value[1:-1].replace("``", "`")
        if value[0] == '"' and value[-1] == '"':
            return value[1:-1].replace('""', '"')
        if value[0] == "[" and value[-1] == "]":
            return value[1:-1].replace("]]", "]")
    return value


def _significant_sql_tokens(token_list: TokenList) -> list[Any]:
    """Return non-whitespace, non-comment children of one parsed token list."""
    return [
        token
        for token in token_list.tokens
        if not token.is_whitespace and token.ttype not in sql_tokens.Comment
    ]


def _cte_names(statement: TokenList, fold: Callable[[str], str] = str.lower) -> set[str]:
    """Collect top-level CTE aliases so they are not treated as base tables."""
    tokens = _significant_sql_tokens(statement)
    with_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if token.ttype in sql_tokens.Keyword.CTE
            and token.normalized.upper() == "WITH"
        ),
        None,
    )
    if with_index is None:
        return set()

    index = with_index + 1
    if index < len(tokens) and tokens[index].normalized.upper() == "RECURSIVE":
        index += 1
    if index >= len(tokens):
        raise ValueError("Incomplete WITH clause")

    definitions = tokens[index]
    identifiers = (
        list(definitions.get_identifiers())
        if isinstance(definitions, IdentifierList)
        else [definitions]
    )
    names: set[str] = set()
    for identifier in identifiers:
        if not isinstance(identifier, Identifier):
            raise ValueError("Unsupported WITH clause")
        name = identifier.get_real_name()
        if not name:
            raise ValueError("Unnamed CTE")
        names.add(fold(_normalize_sql_identifier(name)))
    return names


def _table_references_from_target(
    token: Any,
    cte_names: set[str],
    *,
    allow_column_list: bool = False,
    fold: Callable[[str], str] = str.lower,
) -> list[str]:
    """Extract complete table references from one FROM/JOIN target token."""
    if isinstance(token, IdentifierList):
        references: list[str] = []
        for identifier in token.get_identifiers():
            references.extend(
                _table_references_from_target(
                    identifier,
                    cte_names,
                    allow_column_list=allow_column_list,
                    fold=fold,
                )
            )
        return references

    if isinstance(token, Identifier):
        # Derived tables are rejected by the extended policy. Refuse other
        # parenthesized/function-shaped targets here rather than guessing which
        # object an allowlist should authorize.
        if any(isinstance(child, Parenthesis) for child in token.tokens) or (
            not allow_column_list
            and any(isinstance(child, Function) for child in token.tokens)
        ):
            raise ValueError("Parenthesized table target is unsupported")
        table_name = token.get_real_name()
        if not table_name:
            raise ValueError("Table target has no resolvable name")
        table_name = _normalize_sql_identifier(table_name)
        schema_name = token.get_parent_name()
        if schema_name:
            schema_name = _normalize_sql_identifier(schema_name)
            return [fold(f"{schema_name}.{table_name}")]
        if fold(table_name) in cte_names:
            return []
        return [fold(table_name)]

    if isinstance(token, Function) and allow_column_list:
        table_name = token.get_real_name()
        if not table_name:
            raise ValueError("DML table target has no resolvable name")
        return [fold(_normalize_sql_identifier(table_name))]

    if token.ttype in sql_tokens.Name:
        table_name = _normalize_sql_identifier(token.value)
        if fold(table_name) in cte_names:
            return []
        return [fold(table_name)]

    raise ValueError(f"Unsupported table target: {token.value!r}")


def _explained_dml_table_references(
    top_level: list[Any],
    cte_names: set[str],
    fold: Callable[[str], str] = str.lower,
) -> list[str]:
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

    command = top_level[dml_index].normalized.upper()
    if command == "DELETE":
        # MySQL's second multi-table form is:
        # DELETE [modifiers] FROM target_list USING table_references ...
        # Restrict USING-as-tables to this primary DELETE context so ordinary
        # SELECT/JOIN ... USING(column) is never interpreted as a table list.
        from_index = dml_index + 1
        while (
            from_index < len(top_level)
            and top_level[from_index].normalized.upper() in _EXPLAIN_DELETE_MODIFIERS
        ):
            from_index += 1
        if (
            from_index >= len(top_level)
            or top_level[from_index].normalized.upper() != "FROM"
        ):
            return []
        using_index = next(
            (
                index
                for index in range(from_index + 1, len(top_level))
                if top_level[index].ttype in sql_tokens.Keyword
                and top_level[index].normalized.upper() == "USING"
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
            fold=fold,
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
        and top_level[target_index].normalized.upper() in modifiers
    ):
        target_index += 1
    if (
        command in {"INSERT", "REPLACE"}
        and target_index < len(top_level)
        and top_level[target_index].normalized.upper() == "INTO"
    ):
        target_index += 1
    if target_index >= len(top_level):
        raise ValueError(f"EXPLAIN {command} has no table target")

    return _table_references_from_target(
        top_level[target_index],
        cte_names,
        allow_column_list=command in {"INSERT", "REPLACE"},
        fold=fold,
    )


def _collect_table_references(
    token_list: TokenList,
    cte_names: set[str],
    *,
    strict: bool,
    fold: Callable[[str], str] = str.lower,
) -> list[str]:
    """Walk parsed SQL and collect every FROM/JOIN base-table reference."""
    references: list[str] = []
    tokens = _significant_sql_tokens(token_list)
    with_index = next(
        (index for index, token in enumerate(tokens)
         if token.ttype in sql_tokens.Keyword.CTE
         and token.normalized.upper() == "WITH"),
        None,
    )
    if with_index is not None:
        # A later CTE is not visible inside an earlier definition in MySQL.
        # Without RECURSIVE, a definition's own name can resolve to a physical
        # table. Passing every alias to every body silently authorized those
        # base tables. Keep the scope local and grow it in declaration order.
        definition_index = with_index + 1
        recursive = (
            definition_index < len(tokens)
            and tokens[definition_index].normalized.upper() == "RECURSIVE"
        )
        if recursive:
            definition_index += 1
        try:
            _cte_names(token_list, fold)  # Validate the supported WITH shape.
            definitions = tokens[definition_index]
            entries = (
                list(definitions.get_identifiers())
                if isinstance(definitions, IdentifierList) else [definitions]
            )
            visible = set(cte_names)
            for entry in entries:
                if not isinstance(entry, Identifier) or not entry.get_real_name():
                    raise ValueError("Unsupported CTE definition")
                name = fold(_normalize_sql_identifier(entry.get_real_name()))
                bodies = [child for child in entry.tokens if isinstance(child, Parenthesis)]
                if len(bodies) != 1:
                    raise ValueError("Unsupported CTE body")
                body_scope = visible | {name} if recursive else set(visible)
                references.extend(_collect_table_references(
                    bodies[0], body_scope, strict=strict, fold=fold,
                ))
                visible.add(name)
            cte_names = visible
            # Bodies were traversed once with their own scopes, not again with
            # the final scope belonging to the outer SELECT.
            tokens = [token for token in tokens if token is not definitions]
        except (AttributeError, IndexError, TypeError, ValueError):
            if strict:
                raise ValueError("Could not safely resolve CTE scope") from None
            # Structural system-schema checks still inspect unambiguous FROM
            # references when restrictive allowlist extraction will reject.
    for target in _relation_targets(tokens):
        try:
            references.extend(_table_references_from_target(target, cte_names, fold=fold))
        except ValueError:
            if strict:
                raise
    for token in tokens:
        if isinstance(token, TokenList):
            references.extend(
                _collect_table_references(
                    token, cte_names, strict=strict, fold=fold
                )
            )
    return references


def _extract_tables_from_sql(
    sql: str, *, strict: bool = True, case_sensitive: bool = False
) -> list[str]:
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
    fold: Callable[[str], str] = (lambda name: name) if case_sensitive else str.lower
    try:
        cte_names = _cte_names(statement, fold)
    except ValueError:
        if strict:
            raise
        cte_names = set()
    references = _collect_table_references(
        statement,
        set(),
        strict=strict,
        fold=fold,
    )
    top_level = _significant_sql_tokens(statement)

    if top_level:
        command = top_level[0].normalized.upper()
        has_explained_dml = command in {"EXPLAIN", "DESCRIBE", "DESC"} and any(
            token.ttype is sql_tokens.DML for token in top_level[1:]
        )
        if has_explained_dml:
            try:
                references.extend(
                    _explained_dml_table_references(top_level, cte_names, fold)
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
                            top_level[1], cte_names, fold=fold
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
                            top_level[1], cte_names, fold=fold
                        )
                    )
                except ValueError:
                    if strict:
                        raise

    return sorted(set(references))


def _check_table_allowlist(
    runtime,
    sql: str,
    policy: ConnectionPolicy | None = None,
) -> tuple[bool, str | None]:
    """
    Check if all tables in a SQL query are in the allowlist.

    Args:
        sql: SQL query to check

    Returns:
        (is_allowed, error_message) - True if all tables allowed, False with error otherwise
    """
    effective = _effective_policy(runtime, policy)
    allowed_tables = effective.allowed_tables
    if allowed_tables is None:
        return True, None  # No allowlist configured
    if "*" in allowed_tables:
        return True, None  # Explicit allow-all; structural policy still applies

    try:
        tables = _extract_tables_from_sql(
            sql, case_sensitive=effective.case_sensitive_tables
        )
    except (AttributeError, TypeError, ValueError) as exc:
        logger.info("Table allowlist rejected ambiguous SQL shape: %s", exc)
        return False, (
            "Table allowlist could not safely determine every referenced table"
        )
    blocked_tables = [t for t in tables if not effective.allows_table(t)]

    if blocked_tables:
        return (
            False,
            f"Access denied to table(s): {', '.join(blocked_tables)}. Only allowed tables: {', '.join(sorted(allowed_tables))}",
        )

    return True, None


def _validate_sql_query_policy(
    runtime,
    sql: str,
    policy: ConnectionPolicy | None = None,
) -> tuple[bool, str | None]:
    """Apply the full read-query policy used by raw queries and query skills."""
    effective = _effective_policy(runtime, policy)
    if effective.read_mode == "deny" or (
        effective.read_mode == "allowlist" and not effective.allowed_tables
    ):
        return False, "Reading is disabled by the target connection read policy."
    if not is_sql_safe(sql):
        return False, (
            "Only read-only queries allowed (SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
        )

    is_safe, error_msg = _is_query_safe_extended(runtime, sql, policy)
    if not is_safe:
        return False, error_msg

    return _check_table_allowlist(runtime, sql, policy)


def _validate_sql_template_startup_policy(runtime, sql: str) -> tuple[bool, str | None]:
    """Validate query skill templates before any target connection is selected.

    v3.5 moves table allowlists to per-connection policy. Startup validation
    therefore checks read-only shape and structural deny rules, while runtime
    execution re-applies the full policy for the resolved target connection.
    """
    if not is_sql_safe(sql):
        return False, (
            "Only read-only queries allowed (SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
        )
    return _is_query_safe_extended(
        runtime,
        sql,
        runtime.registry.get_config().policy,
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
    """Strip comments and collapse whitespace before regex policy checks."""
    try:
        sql = sqlparse.format(sql, strip_comments=True)
    except Exception:
        pass
    return re.sub(r"\s+", " ", sql).strip()


_ACCOUNT_FUNCTIONS = frozenset(
    {"USER", "CURRENT_USER", "SESSION_USER", "SYSTEM_USER", "CURRENT_ROLE"}
)

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
        name = token.get_real_name()
    elif token.ttype in sql_tokens.Name or token.ttype in sql_tokens.String:
        name = token.value
    else:
        return []
    if not name:
        return []
    if len(name) >= 2 and name[0] == name[-1] == "'":
        name = name[1:-1].replace("''", "'")
    return [_normalize_sql_identifier(name).lower()]


def _relation_targets(tokens: list[Any], *, preserve_qualification: bool = False) -> list[Any]:
    """Collect relation targets in this query block, including loose commas.

    sqlparse does not consistently group single-quoted qualified names or
    comma-separated parenthesized targets. Track the FROM clause explicitly
    instead of assuming every next target is one Identifier/List token.
    """
    targets: list[Any] = []
    in_from = False
    expect_target = False
    for index, token in enumerate(tokens):
        command = token.normalized.upper()
        if command.startswith("WHERE ") or command in {
            "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET",
            "UNION", "UNION ALL", "INTERSECT", "EXCEPT", "WINDOW", "FOR", "LOCK",
        }:
            in_from = False
            expect_target = False
        if token.ttype in sql_tokens.Keyword and (
            command in {"FROM", "JOIN", "STRAIGHT_JOIN"} or command.endswith(" JOIN")
        ):
            in_from = True
            expect_target = True
            continue
        if in_from and token.value == ",":
            expect_target = True
            continue
        if expect_target:
            items = list(token.get_identifiers()) if isinstance(token, IdentifierList) else [token]
            if index + 2 < len(tokens) and tokens[index + 1].value == ".":
                # Only the last item can be the schema prefix when sqlparse
                # grouped a preceding comma-separated table into this token.
                if preserve_qualification:
                    items.append(tokens[index + 2])
                else:
                    items[-1] = tokens[index + 2]
            targets.extend(items)
            expect_target = False
        elif in_from and isinstance(token, IdentifierList):
            # sqlparse may group an ON expression and the following table as
            # one IdentifierList: ON a.id=b.id, other_table. Only the first
            # member belongs to the expression; later members are relations.
            items = list(token.get_identifiers())[1:]
            if items and index + 2 < len(tokens) and tokens[index + 1].value == ".":
                if preserve_qualification:
                    items.append(tokens[index + 2])
                else:
                    items[-1] = tokens[index + 2]
            targets.extend(items)
    if expect_target and tokens:
        # Preserve an incomplete FROM/JOIN/comma as an unresolvable target so
        # strict authorization extraction fails closed instead of finding none.
        targets.append(tokens[-1])
    return targets


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
    tokens = [
        token
        for statement in statements
        for token in statement.flatten()
        if not token.is_whitespace and token.ttype not in sql_tokens.Comment
    ]
    for index, token in enumerate(tokens):
        if token.ttype in sql_tokens.String:
            continue
        value = token.value.upper()
        if token.ttype in sql_tokens.Keyword and value == "TABLE":
            return "TABLE query expressions are not supported; use SELECT with FROM instead."
        if token.ttype in sql_tokens.Operator and value == "@@":
            return (
                "System variables (@@...) are not allowed in queries; they "
                "expose server configuration rather than table data."
            )
        next_value = tokens[index + 1].value if index + 1 < len(tokens) else ""
        if value in _ACCOUNT_FUNCTIONS and (
            next_value == "(" or value == "CURRENT_USER"
        ):
            return "Account and role functions are not allowed in queries."
    return None


def _is_query_safe_extended(
    runtime,
    sql: str,
    policy: ConnectionPolicy | None = None,
    *,
    require_union_allowlist: bool = True,
) -> tuple[bool, str | None]:
    """
    Extended safety check beyond basic statement type validation.

    Returns:
        (is_safe, error_message)
    """
    if has_unsafe_mysql_comment_semantics(sql):
        return False, "Ambiguous or executable MySQL comment syntax is not allowed"

    normalized_sql = _normalize_sql_for_policy(sql)
    sql_upper = normalized_sql.upper().strip()
    effective_policy = _effective_policy(runtime, policy)

    # Raw SHOW has a large, privilege-dependent grammar. Several forms disclose
    # accounts, sessions, configuration, or tables outside ALLOWED_TABLES, and
    # safely filtering every result would duplicate the metadata tools. Keep
    # the raw gate small and fail closed; use list_tables()/describe_table().
    if re.match(r"^SHOW\b", sql_upper, re.IGNORECASE):
        return False, (
            "SHOW statements are not allowed in raw queries. "
            "Use list_tables() or describe_table() instead; describe_table() "
            "also returns indexes."
        )

    # Block MySQL server-side file reads/writes. These are SELECT-shaped but can
    # touch files if the DB account has FILE privilege.
    for pattern in MYSQL_FILE_OPERATION_PATTERNS:
        if re.search(pattern, normalized_sql, re.IGNORECASE):
            return False, "MySQL server-side file operations are not allowed"

    server_state_error = _server_state_reference_error(normalized_sql)
    if server_state_error:
        return False, server_state_error

    # The existing FROM restriction also applies to JOIN/commalist groups.
    # These shapes are outside the supported extractor even when read.mode=all.
    if any(
        _has_parenthesized_relation_target(statement)
        for statement in sqlparse.parse(normalized_sql)
    ):
        return False, "Parenthesized FROM/JOIN targets are not allowed; use a CTE instead."

    if any(
        _nonstandard_relation_reference(statement)
        for statement in sqlparse.parse(normalized_sql)
    ):
        return False, (
            "Single-quoted table names and ODBC relation wrappers are not supported; "
            "use standard identifier quoting and explicit FROM/JOIN targets."
        )

    # Block access to system schemas using parsed table targets, not a raw-text
    # regex that could mistake a string literal such as 'mysql.user' for a
    # table. Non-strict extraction keeps any unambiguous references even when
    # another FROM target is intentionally unsupported by the allowlist parser.
    system_schemas = {"mysql", "performance_schema", "information_schema", "sys"}
    table_references = _extract_tables_from_sql(normalized_sql, strict=False)
    if any(
        "." in reference and reference.split(".", 1)[0].lower() in system_schemas
        for reference in table_references
    ):
        return (
            False,
            "Access to system databases not allowed. Use list_tables() or "
            "describe_table() instead; describe_table() also returns indexes.",
        )

    # UNION handling: Configurable based on ALLOW_UNION setting
    # Reference: OWASP - UNION is common SQL injection vector
    # Reference: OpenAI - minimize tool calls for efficiency
    if re.search(r"\bUNION\b", normalized_sql, re.IGNORECASE):
        if not require_union_allowlist:
            logger.info("UNION in query skill template will be checked at runtime")
        elif not effective_policy.allow_union:
            # Default: block UNION and steer toward one permitted query.
            return False, (
                "UNION queries disabled for security on this connection. "
                "Prefer one permitted query without UNION (scalar "
                "subqueries, EXISTS/NOT EXISTS, JOIN or a CTE) when it "
                "keeps the task's meaning. If you run separate queries, "
                "aggregate in SQL and check truncation, duplicates and "
                "ordering before combining; do not switch connections."
            )
        # UNION enabled: Require table allowlist for validation
        elif effective_policy.allowed_tables is None:
            return False, (
                "UNION requires an explicit table allowlist on the selected "
                "connection. Configure that connection's read policy "
                "with an explicit allowlist or all scope to enable."
            )
        # UNION will be validated by _check_table_allowlist() which extracts all tables
        logger.info("UNION query allowed - validating tables")

    # Block subqueries in FROM clause (potential info disclosure)
    # Allow subqueries in WHERE for legitimate use
    if re.search(r"FROM\s*\(", normalized_sql, re.IGNORECASE):
        return False, "Subqueries in FROM clause not allowed"

    return True, None
