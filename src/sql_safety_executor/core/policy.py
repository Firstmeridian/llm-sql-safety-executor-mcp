from __future__ import annotations
import re
import logging
import sqlparse
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
    if "*" in allowed_tables:
        return True  # Explicit "allow all" via read.mode=all
    return table_name.lower() in allowed_tables


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


def _cte_names(statement: TokenList) -> set[str]:
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
        names.add(_normalize_sql_identifier(name).lower())
    return names


def _table_references_from_target(
    token: Any,
    cte_names: set[str],
    *,
    allow_column_list: bool = False,
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
            return [f"{schema_name}.{table_name}".lower()]
        if table_name.lower() in cte_names:
            return []
        return [table_name.lower()]

    if isinstance(token, Function) and allow_column_list:
        table_name = token.get_real_name()
        if not table_name:
            raise ValueError("DML table target has no resolvable name")
        return [_normalize_sql_identifier(table_name).lower()]

    if token.ttype in sql_tokens.Name:
        table_name = _normalize_sql_identifier(token.value)
        if table_name.lower() in cte_names:
            return []
        return [table_name.lower()]

    raise ValueError(f"Unsupported table target: {token.value!r}")


def _explained_dml_table_references(
    top_level: list[Any],
    cte_names: set[str],
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
    )


def _collect_table_references(
    token_list: TokenList,
    cte_names: set[str],
    *,
    strict: bool,
) -> list[str]:
    """Walk parsed SQL and collect every FROM/JOIN base-table reference."""
    references: list[str] = []
    tokens = _significant_sql_tokens(token_list)
    for index, token in enumerate(tokens):
        normalized = token.normalized.upper()
        if token.ttype in sql_tokens.Keyword and (
            normalized == "FROM" or normalized == "JOIN" or normalized.endswith(" JOIN")
        ):
            if index + 1 >= len(tokens):
                if strict:
                    raise ValueError(f"{normalized} has no table target")
                continue
            try:
                references.extend(
                    _table_references_from_target(tokens[index + 1], cte_names)
                )
            except ValueError:
                if strict:
                    raise

        if isinstance(token, TokenList):
            references.extend(
                _collect_table_references(token, cte_names, strict=strict)
            )
    return references


def _extract_tables_from_sql(sql: str, *, strict: bool = True) -> list[str]:
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
    try:
        cte_names = _cte_names(statement)
    except ValueError:
        if strict:
            raise
        cte_names = set()
    references = _collect_table_references(
        statement,
        cte_names,
        strict=strict,
    )
    top_level = _significant_sql_tokens(statement)

    if top_level:
        command = top_level[0].normalized.upper()
        has_explained_dml = command in {"EXPLAIN", "DESCRIBE", "DESC"} and any(
            token.ttype is sql_tokens.DML for token in top_level[1:]
        )
        if has_explained_dml:
            try:
                references.extend(_explained_dml_table_references(top_level, cte_names))
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
                        _table_references_from_target(top_level[1], cte_names)
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
                        _table_references_from_target(top_level[1], cte_names)
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
    allowed_tables = _effective_policy(runtime, policy).allowed_tables
    if allowed_tables is None:
        return True, None  # No allowlist configured
    if "*" in allowed_tables:
        return True, None  # Explicit allow-all; structural policy still applies

    try:
        tables = _extract_tables_from_sql(sql)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.info("Table allowlist rejected ambiguous SQL shape: %s", exc)
        return False, (
            "Table allowlist could not safely determine every referenced table"
        )
    blocked_tables = [t for t in tables if not _is_table_allowed(runtime, t, policy)]

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
            "Use list_tables() or describe_table() instead."
        )

    # Block MySQL server-side file reads/writes. These are SELECT-shaped but can
    # touch files if the DB account has FILE privilege.
    for pattern in MYSQL_FILE_OPERATION_PATTERNS:
        if re.search(pattern, normalized_sql, re.IGNORECASE):
            return False, "MySQL server-side file operations are not allowed"

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
            "Access to system databases not allowed. Use list_tables() or describe_table() instead.",
        )

    # UNION handling: Configurable based on ALLOW_UNION setting
    # Reference: OWASP - UNION is common SQL injection vector
    # Reference: OpenAI - minimize tool calls for efficiency
    if re.search(r"\bUNION\b", normalized_sql, re.IGNORECASE):
        if not require_union_allowlist:
            logger.info("UNION in query skill template will be checked at runtime")
        elif not effective_policy.allow_union:
            # Default: Block UNION, guide LLM to use multiple queries
            return False, (
                "UNION queries disabled for security. "
                "Execute separate queries for each table and combine results in your response."
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
