#!/usr/bin/env python3
"""
MCP Server for SQL Safety Checker (v3.0)

Provides safe SQL query execution through MCP protocol.
Following FastMCP best practices for tool design and context usage.

v3.0 — Skills Extension Layer:
- Optional Skills system (ENABLE_SKILLS=1) for pre-defined query/mutation operations
- Query skills: parameterized SQL templates via skill_def.md + source SQL file
- Mutation skills: validate→preview→execute pattern via source Python module
- Backward compatible: ENABLE_SKILLS=0 (default) = zero code path changes

Supported Databases:
- MySQL (default): Full INFORMATION_SCHEMA support
- SQLite: Uses sqlite_master and PRAGMA for metadata

Configuration:
- Set DB_TYPE environment variable to 'mysql' or 'sqlite'
- MySQL: Configure DB_USER, DB_PASSWORD, DB_HOST, DB_NAME
- SQLite: Configure SQLITE_DATABASE_PATH
- Skills: Set ENABLE_SKILLS=1 to activate (SKILLS_ALLOW_MUTATIONS=1 for writes)

Backward Compatibility:
- Default DB_TYPE=mysql maintains existing behavior
- All existing environment variables continue to work
- ENABLE_SKILLS=0 (default) means zero impact on existing tools
"""

import os
import re
import sys
import json
import hashlib
import logging
import math
import secrets
import time
import sqlparse
from sqlparse import tokens as sql_tokens
from sqlparse.sql import Function, Identifier, IdentifierList, Parenthesis, TokenList
from dataclasses import dataclass
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal
from pydantic import Field
from mcp.types import ToolAnnotations
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import ToolResult
from sql_safety_checker import (
    execute_sql,
    has_unsafe_mysql_comment_semantics,
    is_sql_safe,
)
from db_adapter import (
    ConnectionPolicy,
    DatabaseAdapter,
    DatabaseConfig,
    MetadataQueryError,
    get_adapter,
    get_connection_config,
    get_default_connection_id,
    list_connection_configs,
    DB_TYPE,
)
from preview_token_store import InMemoryPreviewTokenStore

logger = logging.getLogger(__name__)


SchemaDetailLevel = Literal["compact", "full"]
SkillListDetailLevel = Literal["compact", "summary", "full"]
SkillDetailProjection = Literal["execution", "full"]


@dataclass(frozen=True)
class ConnectionContext:
    """Per-tool target connection resolved before policy/readiness/execution."""

    connection_id: str
    config: DatabaseConfig
    adapter: DatabaseAdapter
    policy: ConnectionPolicy

    @property
    def db_type(self) -> str:
        return self.config.db_type


@dataclass(frozen=True)
class _SkillSchemaSnapshot:
    """Distinguish disabled, successful, and unavailable readiness checks."""

    enabled: bool
    available: bool
    table_names: frozenset[str]


def _parse_env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable with a conservative fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    logger.warning(
        "Invalid %s=%r; falling back to %s. Allowed values: 1/0, true/false, yes/no, on/off",
        name,
        raw,
        default,
    )
    return default


def _parse_env_csv_set(name: str) -> set[str]:
    """Parse a comma-separated environment variable into lowercase tokens."""
    raw = os.getenv(name, "")
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def _parse_env_int(
    name: str,
    default: int,
    *,
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    """Parse a bounded integer environment variable with a safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %s", name, raw, default)
        return default

    if value < min_value:
        logger.warning(
            "Invalid %s=%r; must be >= %s. Falling back to %s",
            name,
            raw,
            min_value,
            default,
        )
        return default
    if max_value is not None and value > max_value:
        logger.warning(
            "Invalid %s=%r; must be <= %s. Falling back to %s",
            name,
            raw,
            max_value,
            default,
        )
        return default
    return value


# =============================================================================
# Configuration
# =============================================================================

SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"

# Enable get_table_summary tool (with exact COUNT(*) option)
# Default: disabled - describe_table already provides row_count (estimated)
# Enable when exact counts are needed for specific workflows
TABLE_SUMMARY_ENABLED = os.getenv("ENABLE_TABLE_SUMMARY", "0") == "1"

# Large table threshold for is_large flag and query recommendations
# Reference: MySQL InnoDB full table scan cost considerations
LARGE_TABLE_THRESHOLD = int(os.getenv("LARGE_TABLE_THRESHOLD", "1000"))

# Token optimization: Limit result size to prevent context overflow
# Reference: Google Gemini best practices - "Token limits: function descriptions and parameters count toward input token limits"
# Reference: MCP Security best practices - "Sanitize tool outputs"
# Set to 0 to disable truncation (for data export scenarios)
MAX_RESULT_ROWS = int(os.getenv("MAX_RESULT_ROWS", "100"))  # Max rows (0=unlimited)
MAX_RESULT_CHARS = int(os.getenv("MAX_RESULT_CHARS", "16000"))  # Max chars (0=unlimited)
MAX_SQL_LENGTH = int(os.getenv("MAX_SQL_LENGTH", "20000"))  # Max input SQL chars (0=unlimited)
MAX_SCHEMA_TABLES = int(os.getenv("MAX_SCHEMA_TABLES", "50"))  # Max tables in get_full_schema
MAX_OVERVIEW_TABLES = int(os.getenv("MAX_OVERVIEW_TABLES", "100"))  # Max tables in list_tables
_SCHEMA_DETAIL_LEVELS: tuple[SchemaDetailLevel, ...] = ("compact", "full")

# FastMCP foreground tool timeout. This is intentionally higher than the DB
# query timeout because schema tools may perform multiple metadata reads.
MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "120"))
_MCP_TOOL_TIMEOUT = MCP_TOOL_TIMEOUT_SECONDS if MCP_TOOL_TIMEOUT_SECONDS > 0 else None

if MAX_SQL_LENGTH > 0:
    _SQL_QUERY_FIELD = Field(
        description=(
            "Read-only SQL query to execute (SELECT, DESCRIBE, or "
            "non-ANALYZE EXPLAIN)."
        ),
        min_length=1,
        max_length=MAX_SQL_LENGTH,
    )
else:
    _SQL_QUERY_FIELD = Field(
        description=(
            "Read-only SQL query to execute (SELECT, DESCRIBE, or "
            "non-ANALYZE EXPLAIN)."
        ),
        min_length=1,
    )

# UNION Query Policy (P2 Security: Configurable UNION handling)
# Reference: OWASP Defense-in-Depth - block UNION by default for safety
# Reference: OpenAI "minimize tool calls" - allow UNION for efficiency when needed
# When disabled (default): LLM uses multiple queries (safer, more calls)
# When enabled: UNION allowed but requires table allowlist for validation
_DEFAULT_CONNECTION_CONFIG = get_connection_config()
_DEFAULT_CONNECTION_POLICY = _DEFAULT_CONNECTION_CONFIG.policy
ALLOW_UNION = _DEFAULT_CONNECTION_POLICY.allow_union

# =============================================================================
# Skills Extension Layer Configuration (v3.0)
# =============================================================================

# Master switch: enable/disable the entire Skills extension
# Default: disabled — existing tools are completely unaffected
SKILLS_ENABLED = os.getenv("ENABLE_SKILLS", "0") == "1"

# Second switch: allow mutation (write) skills
# Only effective when ENABLE_SKILLS=1
# Default: disabled — only query skills are available
SKILLS_ALLOW_MUTATIONS = os.getenv("SKILLS_ALLOW_MUTATIONS", "0") == "1"

# Every mutation execute requires a preview token registered in this process.
# The bounded memory store intentionally fails closed across process restarts.
MUTATION_PREVIEW_TOKEN_TTL_MAX_SECONDS = 86400
MUTATION_PREVIEW_TOKEN_TTL_SECONDS = _parse_env_int(
    "MUTATION_PREVIEW_TOKEN_TTL_SECONDS",
    300,
    min_value=1,
    max_value=MUTATION_PREVIEW_TOKEN_TTL_MAX_SECONDS,
)
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES_MAX = 100_000
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES = _parse_env_int(
    "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES",
    10000,
    min_value=1,
    max_value=MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES_MAX,
)
MUTATION_PREVIEW_BINDING_MAX_BYTES = 4096
_MUTATION_PREVIEW_TOKEN_STORE = InMemoryPreviewTokenStore(
    MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES
)

_mutation_connection_allowlist_raw = os.getenv(
    "SKILLS_ALLOW_MUTATION_CONNECTIONS",
    "",
).strip()
MUTATION_CONNECTION_POLICY_EXPLICIT = bool(_mutation_connection_allowlist_raw)
if MUTATION_CONNECTION_POLICY_EXPLICIT:
    _mutation_connection_allowlist = frozenset(
        _parse_env_csv_set("SKILLS_ALLOW_MUTATION_CONNECTIONS")
    )
    if not _mutation_connection_allowlist:
        raise ValueError(
            "SKILLS_ALLOW_MUTATION_CONNECTIONS is set but contains no "
            "connection ids"
        )
    for _mutation_connection_id in _mutation_connection_allowlist:
        get_connection_config(_mutation_connection_id)
else:
    _mutation_connection_allowlist = frozenset({get_default_connection_id()})


def _mutation_routing_startup_summary() -> tuple[str, str, str, str]:
    """Return a deterministic, non-sensitive mutation-policy summary."""
    mode = "strict" if MUTATION_CONNECTION_POLICY_EXPLICIT else "default-only"
    candidate_targets = sorted(_mutation_connection_allowlist)
    policy_enabled_targets: list[str] = []
    target_policy: list[str] = []

    for connection_id in candidate_targets:
        if not MUTATION_CONNECTION_POLICY_EXPLICIT:
            policy_enabled_targets.append(connection_id)
            target_policy.append(f"{connection_id}=compatibility-default")
            continue

        policy = get_connection_config(connection_id).policy
        if not policy.allow_mutations:
            target_policy.append(f"{connection_id}=disabled")
            continue
        if not policy.mutation_skills:
            target_policy.append(f"{connection_id}=deny-all")
            continue

        policy_enabled_targets.append(connection_id)
        if "*" in policy.mutation_skills:
            target_policy.append(f"{connection_id}=explicit-all")
        else:
            skills = ",".join(sorted(policy.mutation_skills))
            target_policy.append(f"{connection_id}=allowlist({skills})")

    return (
        mode,
        ",".join(candidate_targets) or "none",
        ",".join(policy_enabled_targets) or "none",
        ";".join(target_policy) or "none",
    )


def _log_mutation_security_startup() -> None:
    """Log mutation security posture without token material or database DSNs."""
    mode, candidates, policy_enabled_targets, target_policy = (
        _mutation_routing_startup_summary()
    )
    logger.info(
        "Mutation routing policy: mode=%s; candidate_targets=%s; "
        "policy_enabled_targets=%s; target_policy=%s",
        mode,
        candidates,
        policy_enabled_targets,
        target_policy,
    )
    logger.info(
        "Mutation preview tokens: 256-bit opaque handles with process-local "
        "one-time state"
    )
    if os.getenv("MUTATION_PREVIEW_TOKEN_SECRET") is not None:
        logger.warning(
            "MUTATION_PREVIEW_TOKEN_SECRET is obsolete and ignored; mutation "
            "preview tokens use process-local opaque handles"
        )

# Skills directory path (relative to project root or absolute)
SKILLS_DIR = os.getenv("SKILLS_DIR", "skills/")

# Default metadata projection for list_skills(). This controls only what is
# disclosed to the Agent; startup discovery, SQL validation, and in-memory
# execution caches remain eager for TOCTOU protection.
_SKILLS_DETAIL_LEVELS: tuple[SkillListDetailLevel, ...] = (
    "compact",
    "summary",
    "full",
)
_SKILL_DETAIL_PROJECTION_LEVELS: tuple[SkillDetailProjection, ...] = (
    "execution",
    "full",
)


def _parse_skills_list_default_detail() -> SkillListDetailLevel:
    """Parse the startup default while preserving its finite static type."""
    raw = os.getenv("SKILLS_LIST_DEFAULT_DETAIL", "summary").strip().lower()
    if raw == "compact":
        return "compact"
    if raw == "summary":
        return "summary"
    if raw == "full":
        return "full"
    logger.warning(
        "Invalid SKILLS_LIST_DEFAULT_DETAIL=%r; falling back to 'summary'. "
        "Allowed values: compact, summary, full",
        raw,
    )
    return "summary"


SKILLS_LIST_DEFAULT_DETAIL: SkillListDetailLevel = (
    _parse_skills_list_default_detail()
)

# Agent-facing default for list_skills(). When enabled, discovery hides skills
# that cannot execute in the current server state (for example wrong DB_TYPE or
# mutation skills when SKILLS_ALLOW_MUTATIONS=0). Developers can still request
# the full discovered catalog with available_only=false.
SKILLS_LIST_AVAILABLE_ONLY_DEFAULT = _parse_env_bool(
    "SKILLS_LIST_AVAILABLE_ONLY_DEFAULT",
    True,
)

# When enabled, list_skills()/get_skill_detail() also consider whether a skill's
# declared/derived tables exist in the current database schema. An unavailable
# metadata check marks table-dependent Skills non-executable; execution repeats
# the same fail-closed readiness guard.
SKILLS_CHECK_SCHEMA_ON_LIST = _parse_env_bool(
    "SKILLS_CHECK_SCHEMA_ON_LIST",
    True,
)

# Optional profile policy. Matching profiles make skills non-executable and
# hidden from default Agent discovery, while available_only=false can still show
# the catalog entry for developer review.
SKILLS_EXCLUDE_PROFILES = _parse_env_csv_set("SKILLS_EXCLUDE_PROFILES")

# Optional audit trail for read-only query skills. Mutation audit is best-effort;
# pre-token parameter/validation rejection may have no JSONL record.
SKILLS_AUDIT_QUERIES = _parse_env_bool("SKILLS_AUDIT_QUERIES", False)

SKILLS_SEARCH_MAX_LENGTH = 128
SKILLS_CATEGORY_MAX_LENGTH = 64

# Optional opt-in telemetry: write per-tool-call runtime metadata to a JSONL log.
# Disabled by default. Captures only non-sensitive fields from ToolResult._meta —
# never SQL text, parameter values, returned rows, or credentials.
ENABLE_TOOL_TELEMETRY = _parse_env_bool("ENABLE_TOOL_TELEMETRY", False)
TOOL_TELEMETRY_LOG_PATH = os.getenv(
    "TOOL_TELEMETRY_LOG_PATH",
    str(Path(__file__).parent / "logs" / "tool_calls.jsonl"),
)


def _parse_telemetry_sample_rate(raw: str | None) -> float:
    """Clamp TOOL_TELEMETRY_SAMPLE_RATE to [0.0, 1.0]. Defaults to 1.0."""
    if raw is None or raw == "":
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    if not math.isfinite(value):
        return 1.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


TOOL_TELEMETRY_SAMPLE_RATE = _parse_telemetry_sample_rate(
    os.getenv("TOOL_TELEMETRY_SAMPLE_RATE")
)

# Load allowlist at startup for the default connection. Per-call tools use the
# selected ConnectionContext policy instead of this legacy module-level value.
ALLOWED_TABLES: set[str] | None = (
    set(_DEFAULT_CONNECTION_POLICY.allowed_tables)
    if _DEFAULT_CONNECTION_POLICY.allowed_tables is not None
    else None
)

# Log the compatibility/default policy at module load. Runtime tools resolve
# and enforce the selected connection's policy independently.
_default_connection_id = _DEFAULT_CONNECTION_CONFIG.connection_id
if ALLOW_UNION:
    if ALLOWED_TABLES:
        logger.info(
            "Default connection '%s': UNION queries enabled with table "
            "allowlist: %s",
            _default_connection_id,
            sorted(ALLOWED_TABLES),
        )
    else:
        logger.warning(
            "Default connection '%s': ALLOW_UNION=1 but no ALLOWED_TABLES "
            "configured; UNION will be blocked",
            _default_connection_id,
        )
else:
    logger.info(
        "Default connection '%s': UNION queries disabled (safe mode)",
        _default_connection_id,
    )


def _effective_policy(policy: ConnectionPolicy | None = None) -> ConnectionPolicy:
    """Return the explicit policy or the default connection policy."""
    return policy or _DEFAULT_CONNECTION_POLICY


def _is_table_allowed(table_name: str, policy: ConnectionPolicy | None = None) -> bool:
    """
    Check if a table is in the allowlist.
    
    Args:
        table_name: Name of the table to check
        
    Returns:
        True if table is allowed (or no allowlist configured), False otherwise
    """
    allowed_tables = _effective_policy(policy).allowed_tables
    if allowed_tables is None:
        return True  # No allowlist - allow all
    if "*" in allowed_tables:
        return True  # Explicit "allow all" via ALLOWED_TABLES=*
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


_EXPLAIN_UPDATE_MODIFIERS = {"LOW_PRIORITY", "IGNORE"}
_EXPLAIN_INSERT_MODIFIERS = {
    "LOW_PRIORITY",
    "DELAYED",
    "HIGH_PRIORITY",
    "IGNORE",
}
_EXPLAIN_REPLACE_MODIFIERS = {"LOW_PRIORITY", "DELAYED"}
_EXPLAIN_DELETE_MODIFIERS = {"LOW_PRIORITY", "QUICK", "IGNORE"}


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
            and top_level[from_index].normalized.upper()
            in _EXPLAIN_DELETE_MODIFIERS
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
        has_explained_dml = (
            command in {"EXPLAIN", "DESCRIBE", "DESC"}
            and any(token.ttype is sql_tokens.DML for token in top_level[1:])
        )
        if has_explained_dml:
            try:
                references.extend(
                    _explained_dml_table_references(top_level, cte_names)
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
    allowed_tables = _effective_policy(policy).allowed_tables
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
    blocked_tables = [t for t in tables if not _is_table_allowed(t, policy)]
    
    if blocked_tables:
        return False, f"Access denied to table(s): {', '.join(blocked_tables)}. Only allowed tables: {', '.join(sorted(allowed_tables))}"
    
    return True, None


def _validate_sql_query_policy(
    sql: str,
    policy: ConnectionPolicy | None = None,
) -> tuple[bool, str | None]:
    """Apply the full read-query policy used by raw queries and query skills."""
    if not is_sql_safe(sql):
        return False, (
            "Only read-only queries allowed "
            "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
        )

    is_safe, error_msg = _is_query_safe_extended(sql, policy)
    if not is_safe:
        return False, error_msg

    return _check_table_allowlist(sql, policy)


def _validate_sql_template_startup_policy(sql: str) -> tuple[bool, str | None]:
    """Validate query skill templates before any target connection is selected.

    v3.5 moves table allowlists to per-connection policy. Startup validation
    therefore checks read-only shape and structural deny rules, while runtime
    execution re-applies the full policy for the resolved target connection.
    """
    if not is_sql_safe(sql):
        return False, (
            "Only read-only queries allowed "
            "(SELECT, DESCRIBE, non-ANALYZE EXPLAIN)"
        )
    return _is_query_safe_extended(sql, _DEFAULT_CONNECTION_POLICY, require_union_allowlist=False)


# =============================================================================
# Lifespan Management (Best Practice: manage resources properly)
# =============================================================================

@asynccontextmanager
async def lifespan(mcp_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """
    Server lifespan context manager.
    Initialize resources on startup, cleanup on shutdown.
    """
    logger.info("SQL Safety Checker MCP Server starting...")
    # Future: Initialize database connection pool here
    yield {"initialized": True}
    logger.info("SQL Safety Checker MCP Server shutting down...")
    # Future: Cleanup database connections here


# Create MCP server with lifespan
# Server instructions carry cross-tool capabilities and safety-critical routing
# invariants; per-tool descriptions remain local and concise.
_CONNECTION_ROUTING_GUIDANCE = """Connection routing:
- If the user provides an exact configured connection alias, pass it unchanged as connection_id.
- If the user specifies only a database type, call list_connections(). Use the only matching connection when exactly one has that db_type; otherwise ask for an exact alias.
- If the user describes only a purpose or role, do not infer a connection from alias names; ask for an exact alias.
- If the user asks which aliases are available or says they do not know the alias, call list_connections() and ask them to choose an exact alias.
- Omitting connection_id selects only the configured default; it never means all connections.
- For read-only requests across all connections, call list_connections() and invoke the requested tool once per connection_id. Never broadcast mutations."""

mcp = FastMCP(
    name="sql-safety-executor",
    instructions=f"""Database safety gateway with read-only core SQL tools and configured connection routing.
Use query() for free-form reads. If structure is unknown, use list_tables() when names/counts are enough; use get_full_schema(detail_level="compact") directly when broad columns or multi-table planning are needed.
Optional Skills provide reviewed queries and, when enabled, controlled mutations that require preview plus a matching one-time token.
{_CONNECTION_ROUTING_GUIDANCE}""",
    lifespan=lifespan,
    mask_error_details=True,
    strict_input_validation=True,
)


# =============================================================================
# Optional Tool Telemetry Middleware (opt-in via ENABLE_TOOL_TELEMETRY=1)
# Logs per-call runtime metadata (tool_name, execution_ms, db_type, success)
# to a JSONL file for offline observability. NEVER logs SQL/params/rows.
# Reference: MCP spec — _meta is OPTIONAL diagnostic; keep logs sanitized.
# =============================================================================
if ENABLE_TOOL_TELEMETRY:
    from fastmcp.server.middleware import Middleware, MiddlewareContext
    import random as _random

    class _ToolTelemetryMiddleware(Middleware):
        """Append a sanitized JSONL record for each tools/call invocation.

        Records reflect both transport-level outcome (no exception escaped
        ``call_next``) and business-level outcome (``ToolResult.meta.success``
        when present). ``call_completed`` captures the former, ``success``
        captures the latter so operators can tell e.g. a safety rejection
        (``call_completed=True``, ``success=False``) apart from a crash
        (``call_completed=False``, ``success=False``).
        """

        def __init__(self, log_path: str, sample_rate: float = 1.0) -> None:
            self._log_path: Path | None = Path(log_path)
            self._sample_rate = sample_rate
            try:
                assert self._log_path is not None
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - filesystem edge case
                logger.warning(f"Tool telemetry disabled (mkdir failed): {exc}")
                self._log_path = None

        async def on_call_tool(self, context: MiddlewareContext[Any], call_next):  # type: ignore[override]
            tool_name = getattr(context.message, "name", None) or "unknown"
            started = time.perf_counter()
            call_completed = True
            error_class: str | None = None
            success: bool = True
            result_db_type = DB_TYPE
            result_connection_id = get_default_connection_id()
            try:
                result = await call_next(context)
                meta = getattr(result, "meta", None) or {}
                meta_success = meta.get("success") if isinstance(meta, dict) else None
                if isinstance(meta_success, bool):
                    success = meta_success
                if isinstance(meta, dict):
                    if isinstance(meta.get("db_type"), str):
                        result_db_type = meta["db_type"]
                    if isinstance(meta.get("connection_id"), str):
                        result_connection_id = meta["connection_id"]
                return result
            except BaseException as exc:
                call_completed = False
                success = False
                error_class = type(exc).__name__
                raise
            finally:
                if self._log_path is not None and (
                    self._sample_rate >= 1.0 or _random.random() < self._sample_rate
                ):
                    record = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tool_name": tool_name,
                        "execution_ms": round((time.perf_counter() - started) * 1000, 3),
                        "call_completed": call_completed,
                        "success": success,
                        "error_class": error_class,
                        "db_type": result_db_type,
                        "connection_id": result_connection_id,
                    }
                    try:
                        with self._log_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    except OSError as exc:  # pragma: no cover - filesystem edge case
                        logger.warning(f"Tool telemetry write failed: {exc}")

    mcp.add_middleware(
        _ToolTelemetryMiddleware(TOOL_TELEMETRY_LOG_PATH, TOOL_TELEMETRY_SAMPLE_RATE)
    )
    logger.info(
        f"Tool telemetry middleware enabled → {TOOL_TELEMETRY_LOG_PATH} "
        f"(sample_rate={TOOL_TELEMETRY_SAMPLE_RATE})"
    )


# =============================================================================
# Helper Functions (Internal)
# =============================================================================

def _serialize_result(data: Any) -> Any:
    """Convert SQLAlchemy Row objects to JSON-serializable format."""
    if data is None:
        return None
    if isinstance(data, list):
        return [_serialize_result(item) for item in data]
    if hasattr(data, '_mapping'):
        return dict(data._mapping)
    if hasattr(data, '__dict__'):
        return {k: v for k, v in data.__dict__.items() if not k.startswith('_')}
    return data


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
    if not re.match(r'^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$', name):
        return False
    
    # Defense-in-depth: secondary check for dangerous patterns
    # (already blocked by the strict regex above, kept as safety net)
    dangerous_patterns = [
        r'[\'\"`;\\]',  # Quotes and escape chars
        r'--',          # SQL comment
        r'/\*',         # Block comment start
        r'\*/',         # Block comment end
        r'\x00',        # Null byte
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, name):
            return False
    
    return True


MYSQL_FILE_OPERATION_PATTERNS = [
    r'\bINTO\s+(?:OUTFILE|DUMPFILE)\b',
    r'\bLOAD_FILE\s*\(',
]


def _normalize_sql_for_policy(sql: str) -> str:
    """Strip comments and collapse whitespace before regex policy checks."""
    try:
        sql = sqlparse.format(sql, strip_comments=True)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', sql).strip()


def _is_query_safe_extended(
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
    effective_policy = _effective_policy(policy)
    
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
        "." in reference
        and reference.split(".", 1)[0].lower() in system_schemas
        for reference in table_references
    ):
        return False, "Access to system databases not allowed. Use list_tables() or describe_table() instead."
    
    # UNION handling: Configurable based on ALLOW_UNION setting
    # Reference: OWASP - UNION is common SQL injection vector
    # Reference: OpenAI - minimize tool calls for efficiency
    if re.search(r'\bUNION\b', normalized_sql, re.IGNORECASE):
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
                "connection. Configure that connection's ALLOWED_TABLES policy "
                "with table names or * to enable."
            )
        # UNION will be validated by _check_table_allowlist() which extracts all tables
        logger.info("UNION query allowed - validating tables")
    
    # Block subqueries in FROM clause (potential info disclosure)
    # Allow subqueries in WHERE for legitimate use
    if re.search(r'FROM\s*\(', normalized_sql, re.IGNORECASE):
        return False, "Subqueries in FROM clause not allowed"
    
    return True, None


def _truncate_result(data: list, total_rows: int) -> dict[str, Any]:
    """
    Truncate query results to prevent token explosion.
    
    Set MAX_RESULT_ROWS=0 or MAX_RESULT_CHARS=0 to disable respective limits.
    
    Returns:
        Dict with truncated data and metadata
    """
    
    truncated = False
    truncation_reason = None
    returned_rows = len(data)
    
    # Step 1: Limit by row count (0 = disabled)
    if MAX_RESULT_ROWS > 0 and len(data) > MAX_RESULT_ROWS:
        data = data[:MAX_RESULT_ROWS]
        truncated = True
        truncation_reason = f"row_limit ({MAX_RESULT_ROWS})"
        returned_rows = MAX_RESULT_ROWS
    
    # Step 2: Limit by character count (0 = disabled)
    if MAX_RESULT_CHARS > 0:
        try:
            json_str = json.dumps(data, ensure_ascii=False, default=str)
            if len(json_str) > MAX_RESULT_CHARS:
                # Binary search for optimal row count within char limit
                low, high = 1, len(data)
                while low < high:
                    mid = (low + high + 1) // 2
                    test_str = json.dumps(data[:mid], ensure_ascii=False, default=str)
                    if len(test_str) <= MAX_RESULT_CHARS:
                        low = mid
                    else:
                        high = mid - 1
                data = data[:low]
                truncated = True
                truncation_reason = f"char_limit ({MAX_RESULT_CHARS})"
                returned_rows = low
        except (TypeError, ValueError):
            pass  # If JSON encoding fails, skip char limit check
    
    return {
        "data": data,
        "returned_rows": returned_rows,
        "total_rows": total_rows,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
    }


def _elapsed_ms_from(start_time: float) -> float:
    """Return elapsed milliseconds rounded for stable runtime metadata."""
    return round((time.perf_counter() - start_time) * 1000, 3)


_CONNECTION_ID_FIELD = Field(
    description=(
        "Connection alias. Pass exact aliases unchanged; omit only for default. "
        "Omission never means all connections. Use "
        "list_connections() to discover aliases or match a database type."
    ),
    min_length=1,
    max_length=64,
)

_MUTATION_PREVIEW_TOKEN_FIELD = Field(
    description=(
        "API-opaque one-time bearer handle returned by "
        "execute_mutation_skill(confirm=false). Required when confirm=true; "
        "do not parse it or depend on its internal format."
    ),
    min_length=1,
    max_length=128,
)


def _resolve_connection_context(connection_id: str | None = None) -> ConnectionContext:
    """Resolve the target connection before policy, schema, or execution."""
    try:
        config = get_connection_config(connection_id)
        adapter = get_adapter(config.connection_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ConnectionContext(
        connection_id=config.connection_id,
        config=config,
        adapter=adapter,
        policy=config.policy,
    )


def _policy_summary(policy: ConnectionPolicy) -> dict[str, Any]:
    """Return a non-sensitive summary of connection policy."""
    allowed_tables = policy.allowed_tables
    if allowed_tables is None:
        mode = "unrestricted"
        values: list[str] | None = None
    elif "*" in allowed_tables:
        mode = "explicit_all"
        values = ["*"]
    else:
        mode = "allowlist"
        values = sorted(allowed_tables)
    mutation_skills = policy.mutation_skills
    if "*" in mutation_skills:
        mutation_skills_mode = "explicit_all"
        mutation_skill_values = ["*"]
    elif mutation_skills:
        mutation_skills_mode = "allowlist"
        mutation_skill_values = sorted(mutation_skills)
    else:
        mutation_skills_mode = "deny_all"
        mutation_skill_values = []

    return {
        "allow_union": policy.allow_union,
        "allowed_tables_mode": mode,
        "allowed_tables": values,
        "allowed_tables_count": len(allowed_tables) if allowed_tables is not None else None,
        "allow_mutations": policy.allow_mutations,
        "mutation_skills_mode": mutation_skills_mode,
        "mutation_skills": mutation_skill_values,
        "mutation_skills_count": len(mutation_skills),
    }


def _config_status(config: DatabaseConfig) -> dict[str, str]:
    """Return set/missing status for required connection fields without values."""
    if config.db_type == "sqlite":
        return {
            "SQLITE_DATABASE_PATH": "set" if config.sqlite_database_path else "missing (using :memory:)",
        }
    return {
        "DB_USER": "set" if config.mysql_user else "missing",
        "DB_PASSWORD": "set" if config.mysql_password else "missing",
        "DB_HOST": "set" if config.mysql_host else "missing",
        "DB_NAME": "set" if config.mysql_database else "missing",
    }


def _public_database_name(connection: ConnectionContext) -> str | None:
    """Return a non-sensitive database display name for tool payloads/logs."""
    if connection.db_type == "sqlite":
        return f"sqlite:{connection.connection_id}"
    return connection.adapter.get_database_name()


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
    return _canonical_json({
        "v": 1,
        "skill_name": skill_name,
        "skill_version": skill_version,
        "params_hash": _mutation_params_hash(params),
        "connection_id": connection.connection_id,
        "db_type": connection.db_type,
    })


def _create_mutation_preview_token(
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
    expires_at = int(time.time()) + MUTATION_PREVIEW_TOKEN_TTL_SECONDS
    return secrets.token_urlsafe(32), expires_at, request_binding_json


def _preview_token_id(preview_token: str) -> str:
    return _preview_token_digest(preview_token)[:16]


def _preview_token_digest(preview_token: str) -> str:
    return _sha256_hex(preview_token)


def _register_mutation_preview_token(
    preview_token: str,
    expires_at: int,
    request_binding_json: str,
    execution_binding_json: str,
) -> None:
    now = int(time.time())
    issued = _MUTATION_PREVIEW_TOKEN_STORE.issue(
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
    status, record = _MUTATION_PREVIEW_TOKEN_STORE.consume_if_matches(
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


def _tool_result(
    payload: dict[str, Any],
    *,
    tool_name: str,
    start_time: float,
    connection: ConnectionContext | None = None,
    **meta_extras: Any,
) -> ToolResult:
    """
    Wrap a dict-shaped tool response in ``ToolResult`` and attach runtime metadata.

    ``_meta`` always carries ``tool_name``, ``db_type``, and ``execution_ms``;
    callers may add tool-specific fields via ``**meta_extras`` (None values are
    dropped). Metadata is non-sensitive diagnostics only — never raw SQL,
    returned rows, parameter values, or credentials.

    Per MCP spec the ``_meta`` field is OPTIONAL: clients MAY ignore it. This
    helper is primarily a server-side observability hook.
    """
    db_type = connection.db_type if connection is not None else DB_TYPE
    connection_id = (
        connection.connection_id if connection is not None else get_default_connection_id()
    )
    runtime_meta: dict[str, Any] = {
        "tool_name": tool_name,
        "db_type": db_type,
        "connection_id": connection_id,
        "execution_ms": _elapsed_ms_from(start_time),
    }
    runtime_meta.update({k: v for k, v in meta_extras.items() if v is not None})
    return ToolResult(structured_content=payload, meta=runtime_meta)


def _normalize_schema_detail_level(
    detail_level: SchemaDetailLevel,
) -> SchemaDetailLevel:
    """Validate the already non-null schema projection argument."""
    if detail_level not in _SCHEMA_DETAIL_LEVELS:
        allowed = ", ".join(sorted(_SCHEMA_DETAIL_LEVELS))
        raise ValueError(
            f"Invalid detail_level '{detail_level}'. Allowed values: {allowed}"
        )
    return detail_level


def _require_boolean(value: bool, parameter_name: str) -> bool:
    """Reject Python values that do not match an MCP boolean schema."""
    if type(value) is not bool:
        raise ValueError(f"{parameter_name} must be a boolean")
    return value


def _schema_metadata_signature(columns: list[dict[str, Any]]) -> str:
    """Return an order-sensitive signature over adapter-visible column metadata."""
    return json.dumps(
        columns,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


async def _metadata_failure_result(
    *,
    ctx: Context,
    tool_name: str,
    start_time: float,
    connection: ConnectionContext,
    error: Exception,
    error_code: str = "metadata_query_failed",
) -> ToolResult:
    """Return a stable, sanitized failure instead of an empty metadata result."""
    await ctx.error(str(error))
    return _tool_result(
        {
            "success": False,
            "error": str(error),
            "error_code": error_code,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        },
        tool_name=tool_name,
        start_time=start_time,
        connection=connection,
        success=False,
    )


# =============================================================================
# MCP Tools (Following FastMCP Best Practices)
# =============================================================================

@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="List Configured Database Connections",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_connections(ctx: Context) -> ToolResult:
    """
    List configured database connection ids and non-sensitive policy metadata.

    This tool never returns DSNs, credentials, host names, passwords, or SQLite
    file paths. A returned alias may be passed to read-only tools and Query
    Skills, subject to their policies and Skill scope. Mutation Skills may use
    the default alias in compatibility mode; non-default aliases require the
    strict named-write policy to authorize that connection and Skill. Discovery
    itself never authorizes writes. This tool takes no arguments.
    """
    start_time = time.perf_counter()
    await ctx.info("Listing configured database connections")

    default_connection_id = get_default_connection_id()
    connections = []
    for config in list_connection_configs():
        connections.append({
            "connection_id": config.connection_id,
            "db_type": config.db_type,
            "is_default": config.connection_id == default_connection_id,
            "query_timeout_seconds": config.query_timeout_seconds,
            "connect_timeout_seconds": config.connect_timeout_seconds,
            "policy": _policy_summary(config.policy),
        })

    payload = {
        "success": True,
        "default_connection_id": default_connection_id,
        "connection_count": len(connections),
        "connections": connections,
    }
    return _tool_result(
        payload,
        tool_name="list_connections",
        start_time=start_time,
        success=True,
        connection_count=len(connections),
    )

@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="Execute SQL Query",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def query(
    sql: Annotated[str, _SQL_QUERY_FIELD],
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """
    Execute one policy-approved read-only SQL statement on the database.

    This is the primary tool for free-form read-only SQL. Use metadata tools
    for schema discovery and reviewed Query Skills for defined workflows.
    Safety validation is automatic - only read-only statements are allowed.
    Supported: SELECT, DESCRIBE, and non-ANALYZE EXPLAIN. Use list_tables()
    and describe_table() instead of raw SHOW statements.
    Returned payloads may be truncated for context safety; truncation does not
    limit database work. Add WHERE/LIMIT/ORDER BY in SQL when needed.
    
    Args:
        sql: One SELECT, DESCRIBE, or non-ANALYZE EXPLAIN statement
        
    Returns:
        Query results with data rows, or error message if query fails
        
    Examples:
        query("SELECT * FROM users LIMIT 10")
        query("SELECT name, email FROM users WHERE active = 1")
        query("SELECT COUNT(*) as total FROM orders")
        query("DESCRIBE users")
        query("EXPLAIN SELECT * FROM products WHERE id = 1")
    """
    start_time = time.perf_counter()
    connection = _resolve_connection_context(connection_id)
    if MAX_SQL_LENGTH > 0 and len(sql) > MAX_SQL_LENGTH:
        await ctx.warning(
            f"Rejected overlong SQL query: {len(sql)} characters "
            f"(max {MAX_SQL_LENGTH})"
        )
        return _tool_result({
            "success": False,
            "error": (
                "SQL query is too long; maximum length is "
                f"{MAX_SQL_LENGTH} characters"
            ),
            "query_length": len(sql),
            "max_sql_length": MAX_SQL_LENGTH,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="query", start_time=start_time, connection=connection, success=False)

    await ctx.info(f"Executing query on connection '{connection.connection_id}': {sql}")
    
    # Validate the shared read-query policy used by raw queries and query skills.
    is_safe, error_msg = _validate_sql_query_policy(sql, connection.policy)
    if not is_safe:
        await ctx.warning(f"Rejected query: {error_msg}")
        return _tool_result({
            "success": False,
            "error": error_msg,
            "query": sql,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="query", start_time=start_time, connection=connection, success=False)
    
    # Execute query
    result = execute_sql(sql, connection_id=connection.connection_id)
    
    # Handle error
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Query failed: {result}")
        return _tool_result({
            "success": False,
            "error": result,
            "query": sql,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="query", start_time=start_time, connection=connection, success=False)
    
    # Success - Apply token optimization with truncation
    # Best practice: Limit response size to prevent context overflow
    # Reference: Google Gemini - "Token limits: function descriptions and parameters count toward input token limits"
    data = _serialize_result(result)
    total_rows = len(result) if isinstance(result, list) else 0
    
    # Apply truncation to prevent token explosion (root cause of 454K token issue)
    truncation_result = _truncate_result(data, total_rows)
    
    if truncation_result["truncated"]:
        await ctx.warning(
            f"Truncated returned payload: {truncation_result['returned_rows']}/{total_rows} rows shown. "
            f"Add WHERE/LIMIT/ORDER BY to limit database work and stabilize ordering."
        )
    else:
        await ctx.info(f"Query returned {total_rows} rows")
    
    payload = {
        "success": True,
        "data": truncation_result["data"],
        "row_count": truncation_result["returned_rows"],
        "total_rows": total_rows,
        "truncated": truncation_result["truncated"],
        "truncation_note": (
            f"Showing {truncation_result['returned_rows']}/{total_rows} fetched rows. "
            f"Truncation limits the returned payload only; add WHERE/LIMIT/ORDER BY "
            f"to limit database work and stabilize ordering."
        ) if truncation_result["truncated"] else None,
        "query": sql,
        "connection_id": connection.connection_id,
        "db_type": connection.db_type,
    }
    return _tool_result(
        payload,
        tool_name="query",
        start_time=start_time,
        connection=connection,
        success=True,
        row_count=truncation_result["returned_rows"],
        total_rows=total_rows,
        truncated=truncation_result["truncated"],
    )


@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="Check Database Connection",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def check_connection(
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """
    Check if the database connection is working.

    Use this only when the user requests a connectivity check or after a
    database operation reports a connection failure. Do not call it as a
    routine prerequisite before queries.

    Returns:
        Connection status, database type, and configuration check
    """
    start_time = time.perf_counter()
    connection = _resolve_connection_context(connection_id)
    await ctx.info(f"Checking database connection '{connection.connection_id}'...")
    
    adapter = connection.adapter
    success, message = adapter.check_connection()
    
    if not success:
        await ctx.error(f"Connection failed: {message}")
        payload = {
            "connected": False,
            "error": message,
            "db_type": connection.db_type,
            "connection_id": connection.connection_id,
            "config": _config_status(connection.config),
        }
        return _tool_result(
            payload, tool_name="check_connection", start_time=start_time,
            connection=connection, success=False,
        )
    
    await ctx.info(f"Database connection successful ({connection.db_type})")
    payload = {
        "connected": True,
        "message": message,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "database_name": _public_database_name(connection),
    }
    return _tool_result(
        payload, tool_name="check_connection", start_time=start_time,
        connection=connection, success=True,
    )


@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="List Visible Database Tables",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_tables(
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """
    Visible database overview: list allowed tables with approximate row counts.
    
    Use this lightweight tool when table names, counts, and approximate row
    counts are enough. If broad columns or multi-table planning are needed,
    call get_full_schema(detail_level="compact") directly; it already includes
    returned table names and row estimates. Results may be truncated by
    MAX_OVERVIEW_TABLES. Row counts are estimates:
    - MySQL: from INFORMATION_SCHEMA (InnoDB is a rough estimate)
    - SQLite: from sqlite_stat1 or bounded sampling

    An individual row_count is null when the adapter cannot safely provide an
    estimate; null does not mean that the table is empty.
    
    Use describe_table(name) for full adapter-visible column metadata of one
    selected table, not complete DDL.

    Returns:
        Database name, visible table counts, and returned table rows
    """
    start_time = time.perf_counter()
    connection = _resolve_connection_context(connection_id)
    await ctx.info(f"Listing database tables on connection '{connection.connection_id}'")
    
    adapter = connection.adapter
    database_name = _public_database_name(connection)
    
    # Use adapter method for cross-database compatibility
    try:
        tables = adapter.get_tables()
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            ctx=ctx,
            tool_name="list_tables",
            start_time=start_time,
            connection=connection,
            error=exc,
        )
    
    if not tables:
        await ctx.info(f"No tables found in {database_name}")
        return _tool_result({
            "success": True,
            "database_name": database_name,
            "db_type": connection.db_type,
            "connection_id": connection.connection_id,
            "returned_table_count": 0,
            "total_tables": 0,
            "tables": [],
            "row_count_approximate": True,
            "truncated": False,
            "truncation_note": None,
            "hint": "No tables found in database."
        }, tool_name="list_tables", start_time=start_time, connection=connection, success=True,
           returned_table_count=0, total_tables=0, truncated=False)
    
    # Filter by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    allowed_tables = connection.policy.allowed_tables
    if allowed_tables is not None and "*" not in allowed_tables:
        original_count = len(tables)
        tables = [t for t in tables if t["table_name"].lower() in allowed_tables]
        if len(tables) < original_count:
            await ctx.info(f"Filtered {original_count - len(tables)} tables by allowlist")
    
    # Apply truncation to prevent token overflow (consistent with get_full_schema)
    total_tables = len(tables)
    truncated = False
    if MAX_OVERVIEW_TABLES > 0 and total_tables > MAX_OVERVIEW_TABLES:
        tables = tables[:MAX_OVERVIEW_TABLES]
        truncated = True
        await ctx.warning(f"Overview truncated: showing {MAX_OVERVIEW_TABLES}/{total_tables} tables")
    
    await ctx.info(f"Found {len(tables)} tables in {database_name}")
    
    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    payload = {
        "success": True,
        "database_name": database_name,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "returned_table_count": len(tables),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "tables": tables,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(tables)}/{total_tables} tables. Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": (
            "Row counts are estimates; null means an estimate is unavailable, "
            "not that the table is empty. For broad columns, call "
            "get_full_schema(detail_level='compact') directly; for one selected "
            "table's full adapter-visible column metadata, use "
            "describe_table(name). This is not complete DDL. total_tables = "
            f"visible after allowlist. DB type: {connection.db_type}"
        )
    }
    return _tool_result(
        payload, tool_name="list_tables", start_time=start_time, success=True,
        connection=connection,
        returned_table_count=len(tables), total_tables=total_tables, truncated=truncated,
    )


@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="Describe Table Structure",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def describe_table(
    table_name: str,
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
) -> ToolResult:
    """
    Get one selected table's full adapter-visible column metadata and row count
    estimate. This is not complete DDL: indexes, foreign keys, checks, and other
    backend-specific properties may be absent.

    Do not call repeatedly to survey many tables. Use get_full_schema with
    detail_level="compact" for broad columns, or detail_level="full" when full
    adapter-visible column metadata is needed across several tables.
    
    Returns column details plus approximate row count:
    - MySQL: from INFORMATION_SCHEMA (InnoDB is a rough estimate)
    - SQLite: from sqlite_stat1 or bounded sampling

    If the backend cannot provide an estimate, row_count,
    row_count_approximate, and is_large are null. Null means unknown, not an
    empty or small table.
    
    Includes is_large flag and recommendations for large tables.

    Args:
        table_name: Name of the table to describe
        
    Returns:
        Table structure with columns, row count, and query recommendations
    """
    start_time = time.perf_counter()
    connection = _resolve_connection_context(connection_id)
    # Validate table name to prevent SQL injection
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return _tool_result({
            "success": False,
            "error": f"Invalid table name: {table_name}",
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="describe_table", start_time=start_time, connection=connection, success=False)
    
    # Check table allowlist (P1 Security)
    if not _is_table_allowed(table_name, connection.policy):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return _tool_result({
            "success": False,
            "error": f"Access denied to table: {table_name}",
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="describe_table", start_time=start_time, connection=connection, success=False)
    
    await ctx.info(f"Describing table on connection '{connection.connection_id}': {table_name}")
    
    # Use adapter methods for cross-database compatibility
    adapter = connection.adapter
    
    try:
        columns_data = adapter.get_columns(table_name)
        row_count = adapter.get_row_estimate(table_name)
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            ctx=ctx,
            tool_name="describe_table",
            start_time=start_time,
            connection=connection,
            error=exc,
        )
    
    if not columns_data:
        await ctx.error(f"Table not found: {table_name}")
        return _tool_result({
            "success": False,
            "error": f"Table '{table_name}' not found",
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="describe_table", start_time=start_time, connection=connection, success=False)
    
    # Do not turn an unavailable estimate into a false "small table" signal.
    row_count_approximate = True if row_count is not None else None
    is_large = (
        row_count > LARGE_TABLE_THRESHOLD
        if row_count is not None
        else None
    )
    displayed_row_count = f"~{row_count}" if row_count is not None else "unknown"

    await ctx.info(
        f"Table {table_name}: {displayed_row_count} rows, "
        f"{len(columns_data)} columns"
    )
    
    # Build response with query recommendations
    result_payload = {
        "success": True,
        "table_name": table_name,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "row_count": row_count,
        "row_count_approximate": row_count_approximate,
        "column_count": len(columns_data),
        "columns": columns_data,
        "is_large": is_large,
    }
    
    # Add recommendation only for large tables (reduce token overhead)
    if is_large is True:
        result_payload["recommendation"] = (
            f"Large table (~{row_count} rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
        )
    
    return _tool_result(
        result_payload, tool_name="describe_table", start_time=start_time,
        connection=connection, success=True,
        row_count=row_count, is_large=is_large,
    )


# =============================================================================
# Schema Caching Tools (Microsoft Best Practices: Reduce repeated tool calls)
# Reference: "Too many tools in the same agent can have negative effect on agent quality"
# =============================================================================

@mcp.tool(
    timeout=_MCP_TOOL_TIMEOUT,
    annotations=ToolAnnotations(
        title="Get Visible Database Schema",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_full_schema(
    ctx: Context,
    connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    detail_level: Annotated[
        SchemaDetailLevel,
        Field(
            description=(
                "Use compact for table discovery, broad schema explanation, or "
                "multi-table planning. Use full for nullable, default, and key "
                "metadata. Defaults to compact."
            )
        ),
    ] = "compact",
    group_identical: Annotated[
        bool,
        Field(
            description=(
                "Compact mode only; defaults to true. Group tables when their "
                "complete current adapter-visible column metadata and column "
                "order are equal. This is not proof of full DDL, index, or "
                "constraint equivalence. Ignored in full mode."
            )
        ),
    ] = True,
) -> ToolResult:
    """
    Get a compact or full visible database schema overview in one call.
    
    Use compact for exploring unknown databases, explaining table purposes, or
    planning across tables. Compact columns are returned as [name, type] pairs;
    tables with equal adapter-visible column metadata can share one group while
    retaining every table and row estimate. This grouping does not establish
    complete DDL, index, or constraint equivalence. Call compact directly instead
    of list_tables when the task already needs broad columns. Use full only when
    nullable, default, or key metadata is needed across several tables. The
    parameter defaults to compact; request full explicitly when its additional
    metadata is needed.

    Results may be filtered by allowlist and truncated by MAX_SCHEMA_TABLES.
    
    Works with both MySQL and SQLite databases.

    Returns:
        Compact schema groups or full table schemas plus visible table counts
    """
    start_time = time.perf_counter()
    connection = _resolve_connection_context(connection_id)
    try:
        resolved_detail_level = _normalize_schema_detail_level(detail_level)
        resolved_group_identical = _require_boolean(
            group_identical,
            "group_identical",
        )
    except ValueError as exc:
        await ctx.warning(f"Schema projection parameter error: {exc}")
        raise ToolError(str(exc)) from exc

    await ctx.info(
        "Fetching visible database schema for connection "
        f"'{connection.connection_id}' (detail_level={resolved_detail_level}, "
        f"group_identical={resolved_group_identical})..."
    )
    
    adapter = connection.adapter
    
    # Step 1: Get all tables with row counts using adapter
    try:
        tables_data = adapter.get_tables()
    except MetadataQueryError as exc:
        return await _metadata_failure_result(
            ctx=ctx,
            tool_name="get_full_schema",
            start_time=start_time,
            connection=connection,
            error=exc,
        )
    
    if not tables_data:
        await ctx.info("No tables found in database")
        empty_projection = (
            {
                "schema_groups": [],
                "schema_group_count": 0,
                "grouped_by_schema": resolved_group_identical,
                "grouping_basis": (
                    "adapter_visible_column_metadata_and_order"
                    if resolved_group_identical
                    else "none"
                ),
            }
            if resolved_detail_level == "compact"
            else {"schema": {}}
        )
        return _tool_result({
            "success": True,
            **empty_projection,
            "db_type": connection.db_type,
            "connection_id": connection.connection_id,
            "detail_level": resolved_detail_level,
            "returned_table_count": 0,
            "total_tables": 0,
            "total_columns": 0,
            "row_count_approximate": True,
            "truncated": False,
            "truncation_note": None,
            "hint": "No tables found in database."
        }, tool_name="get_full_schema", start_time=start_time, connection=connection, success=True,
           returned_table_count=0, total_tables=0, truncated=False,
           detail_level=resolved_detail_level)
    
    # Filter tables by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    allowed_tables = connection.policy.allowed_tables
    if allowed_tables is not None and "*" not in allowed_tables:
        tables_data = [t for t in tables_data if t["table_name"].lower() in allowed_tables]
        await ctx.info(f"Allowlist active: showing {len(tables_data)} allowed tables")
    
    # Step 2: Apply truncation to prevent token overflow (P0 security/performance)
    # Reference: Google Gemini best practices - token limits
    total_tables = len(tables_data)
    truncated = False
    
    if MAX_SCHEMA_TABLES > 0 and total_tables > MAX_SCHEMA_TABLES:
        tables_data = tables_data[:MAX_SCHEMA_TABLES]
        truncated = True
        await ctx.warning(f"Schema truncated: showing {MAX_SCHEMA_TABLES}/{total_tables} tables")
    
    # Step 3: Read each table once, then project the same metadata for either mode.
    table_metadata = []
    for table in tables_data:
        table_name = table["table_name"]
        if not _is_valid_identifier(table_name):
            return await _metadata_failure_result(
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=ValueError(
                    "Database contains a table name that schema tools cannot "
                    "safely describe."
                ),
                error_code="unsupported_metadata_identifier",
            )
        try:
            columns_data = adapter.get_columns(table_name)
        except MetadataQueryError as exc:
            return await _metadata_failure_result(
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=exc,
            )
        if not columns_data:
            return await _metadata_failure_result(
                ctx=ctx,
                tool_name="get_full_schema",
                start_time=start_time,
                connection=connection,
                error=MetadataQueryError(
                    "reading columns for a table returned by table discovery"
                ),
            )
        table_metadata.append((table, columns_data))

    total_columns_shown = sum(len(columns) for _, columns in table_metadata)
    if resolved_detail_level == "compact":
        groups_by_signature: dict[str, dict[str, Any]] = {}
        for index, (table, columns_data) in enumerate(table_metadata):
            signature = (
                _schema_metadata_signature(columns_data)
                if resolved_group_identical
                else f"table:{index}"
            )
            group = groups_by_signature.get(signature)
            if group is None:
                group = {
                    "tables": [],
                    "column_count": len(columns_data),
                    "columns": [
                        [column["column_name"], column["data_type"]]
                        for column in columns_data
                    ],
                    "primary_key": [
                        column["column_name"]
                        for column in columns_data
                        if column["key_type"] == "PRI"
                    ],
                }
                groups_by_signature[signature] = group
            group["tables"].append({
                "name": table["table_name"],
                "row_count": table["row_count"],
            })
        schema_groups = list(groups_by_signature.values())
        projection = {
            "schema_groups": schema_groups,
            "schema_group_count": len(schema_groups),
            "grouped_by_schema": resolved_group_identical,
            "grouping_basis": (
                "adapter_visible_column_metadata_and_order"
                if resolved_group_identical
                else "none"
            ),
        }
        hint = (
            "Columns are [name, type] pairs. Tables in one group have identical "
            "current adapter-visible column metadata and order; this does not "
            "prove full DDL, index, or constraint equivalence. Use "
            "describe_table(name) for one table's nullable, default, and "
            "non-primary key details, or get_full_schema(detail_level='full') "
            "when those fields are needed across several tables."
        )
    else:
        schema = {
            table["table_name"]: {
                "row_count": table["row_count"],
                "columns": [
                    {
                        "name": column["column_name"],
                        "type": column["data_type"],
                        "nullable": column["nullable"],
                        "key": column["key_type"],
                        "default": column["default_value"],
                    }
                    for column in columns_data
                ],
            }
            for table, columns_data in table_metadata
        }
        projection = {"schema": schema}
        hint = (
            "Full adapter column metadata is shown. Use LIMIT for large tables "
            f"(row_count > {LARGE_TABLE_THRESHOLD})."
        )

    returned_table_count = len(table_metadata)
    await ctx.info(
        f"Schema loaded: {returned_table_count} tables, "
        f"{total_columns_shown} columns ({resolved_detail_level})"
    )
    
    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    payload = {
        "success": True,
        **projection,
        "db_type": connection.db_type,
        "connection_id": connection.connection_id,
        "detail_level": resolved_detail_level,
        "returned_table_count": returned_table_count,
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "total_columns": total_columns_shown,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {returned_table_count}/{total_tables} tables. "
            "Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": (
            f"Row counts are estimates; null means unavailable, not empty. "
            f"{hint} total_tables = visible after "
            f"allowlist. DB type: {connection.db_type}"
        ),
    }
    return _tool_result(
        payload, tool_name="get_full_schema", start_time=start_time, success=True,
        connection=connection,
        returned_table_count=returned_table_count, total_tables=total_tables,
        truncated=truncated, detail_level=resolved_detail_level,
    )


# Optional tool: get_table_summary with exact COUNT(*) option
# Default: disabled - describe_table already provides estimated row_count
# Enable via ENABLE_TABLE_SUMMARY=1 when exact counts are needed
if TABLE_SUMMARY_ENABLED:
    @mcp.tool(
        timeout=_MCP_TOOL_TIMEOUT,
        annotations=ToolAnnotations(
            title="Get Table Summary with Exact Count",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def get_table_summary(
        table_name: str, 
        ctx: Context, 
        exact_count: Annotated[
            bool,
            Field(
                description=(
                    "When true, execute SELECT COUNT(*) for an exact row count. "
                    "This may require a full scan, be slow on large tables, and "
                    "encounter MySQL metadata-lock contention. Use only when "
                    "precision is required. Defaults to false."
                )
            ),
        ] = False,
        connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    ) -> ToolResult:
        """
        Table statistics with optional exact row count.
        
        WARNING: exact_count=True runs COUNT(*) which may be slow on large tables
        (full scan; MySQL can also see MDL contention). Use only when precision is required.
        
        Default: Uses adapter estimates (INFORMATION_SCHEMA for MySQL;
        sqlite_stat1 or bounded sampling for SQLite).

        If an approximate estimate is unavailable, row_count,
        row_count_approximate, and is_large are null. Exact counts retain
        their ordinary integer/false/boolean values.
        
        Args:
            table_name: Name of the table
            exact_count: If True, run COUNT(*) for precise count (slow on large tables)
            
        Returns:
            Table statistics with row count, columns, and query hints
        """
        start_time = time.perf_counter()
        try:
            resolved_exact_count = _require_boolean(exact_count, "exact_count")
        except ValueError as exc:
            await ctx.warning(f"Table summary parameter error: {exc}")
            raise ToolError(str(exc)) from exc
        connection = _resolve_connection_context(connection_id)
        # Validate table name
        if not _is_valid_identifier(table_name):
            await ctx.warning(f"Invalid table name rejected: {table_name}")
            return _tool_result(
                {
                    "success": False,
                    "error": f"Invalid table name: {table_name}",
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                },
                tool_name="get_table_summary", start_time=start_time,
                connection=connection, success=False,
            )
        
        # Check table allowlist (P1 Security)
        if not _is_table_allowed(table_name, connection.policy):
            await ctx.warning(f"Table access denied by allowlist: {table_name}")
            return _tool_result(
                {
                    "success": False,
                    "error": f"Access denied to table: {table_name}",
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                },
                tool_name="get_table_summary", start_time=start_time,
                connection=connection, success=False,
            )
        
        await ctx.info(
            f"Getting summary for table on connection '{connection.connection_id}': "
            f"{table_name} (exact_count={resolved_exact_count})"
        )
        
        adapter = connection.adapter
        
        # Get row count — use adapter for cross-database compatibility
        if resolved_exact_count:
            # WARNING: COUNT(*) can be slow on large tables
            row_count_approximate = False
            await ctx.warning(f"Running COUNT(*) on {table_name} - may be slow on large tables")
            quote = '`' if adapter.db_type == 'mysql' else '"'
            count_sql = f"SELECT COUNT(*) as total_rows FROM {quote}{table_name}{quote}"
            count_result = adapter.execute(count_sql)
            if isinstance(count_result, str) and count_result.startswith("Error:"):
                await ctx.error(f"Failed to count rows: {count_result}")
                return _tool_result(
                    {
                        "success": False,
                        "error": count_result,
                        "connection_id": connection.connection_id,
                        "db_type": connection.db_type,
                    },
                    tool_name="get_table_summary", start_time=start_time,
                    connection=connection, success=False,
                )
            count_data = _serialize_result(count_result)
            total_rows = count_data[0]["total_rows"] if count_data else 0
            total_rows = total_rows or 0
        else:
            # Fast estimate via adapter (uses INFORMATION_SCHEMA or sqlite_stat1)
            try:
                total_rows = adapter.get_row_estimate(table_name)
            except MetadataQueryError as exc:
                return await _metadata_failure_result(
                    ctx=ctx,
                    tool_name="get_table_summary",
                    start_time=start_time,
                    connection=connection,
                    error=exc,
                )
            row_count_approximate = True if total_rows is not None else None
        
        # Get column info via adapter (cross-database)
        try:
            columns_data = adapter.get_columns(table_name)
        except MetadataQueryError as exc:
            return await _metadata_failure_result(
                ctx=ctx,
                tool_name="get_table_summary",
                start_time=start_time,
                connection=connection,
                error=exc,
            )

        if not columns_data:
            await ctx.error(f"Table not found: {table_name}")
            return _tool_result(
                {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                },
                tool_name="get_table_summary",
                start_time=start_time,
                connection=connection,
                success=False,
            )
        
        # An unavailable estimate is not evidence that the table is small.
        is_large = (
            total_rows > LARGE_TABLE_THRESHOLD
            if total_rows is not None
            else None
        )
        if total_rows is None:
            displayed_row_count = "unknown"
        elif row_count_approximate:
            displayed_row_count = f"~{total_rows}"
        else:
            displayed_row_count = str(total_rows)

        await ctx.info(
            f"Table {table_name}: {displayed_row_count} rows, "
            f"{len(columns_data)} columns"
        )
        
        result_payload = {
            "success": True,
            "table_name": table_name,
            "db_type": connection.db_type,
            "connection_id": connection.connection_id,
            "row_count": total_rows,
            "row_count_approximate": row_count_approximate,
            "column_count": len(columns_data),
            "columns": columns_data,
            "is_large": is_large,
        }
        
        if is_large is True:
            result_payload["recommendation"] = (
                f"Large table ({'~' if row_count_approximate else ''}{total_rows} rows). "
                "Use LIMIT or aggregation (COUNT/GROUP BY)."
            )
        
        return _tool_result(
            result_payload, tool_name="get_table_summary", start_time=start_time, success=True,
            connection=connection,
            row_count=total_rows, is_large=is_large,
            exact_count=resolved_exact_count,
        )


# Optional tool: Only register if enabled
if SCHEMA_TOOLS_ENABLED:
    @mcp.tool(
        timeout=_MCP_TOOL_TIMEOUT,
        annotations=ToolAnnotations(
            title="Sample Table Data",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def sample(
        table_name: str,
        ctx: Context,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=20,
                description=(
                    "Number of sample rows to return, from 1 through 20. "
                    "Defaults to 5; out-of-range values are rejected."
                ),
            ),
        ] = 5,
        connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    ) -> ToolResult:
        """
        Get sample rows from a table to preview its data.
        
        Args:
            table_name: Name of the table to sample
            limit: Number of rows to return (1 through 20)
            
        Returns:
            Sample rows from the table
        """
        start_time = time.perf_counter()
        connection = _resolve_connection_context(connection_id)
        # Validate inputs
        if not _is_valid_identifier(table_name):
            await ctx.warning(f"Invalid table name rejected: {table_name}")
            return _tool_result({
                "success": False,
                "error": f"Invalid table name: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            }, tool_name="sample", start_time=start_time, connection=connection, success=False)
        
        # Check table allowlist (P1 Security)
        if not _is_table_allowed(table_name, connection.policy):
            await ctx.warning(f"Table access denied by allowlist: {table_name}")
            return _tool_result({
                "success": False,
                "error": f"Access denied to table: {table_name}",
                "connection_id": connection.connection_id,
                "db_type": connection.db_type,
            }, tool_name="sample", start_time=start_time, connection=connection, success=False)
        
        # FastMCP enforces the same range at the MCP boundary. Keep an explicit
        # handler check so direct Python callers receive the same rejection.
        if type(limit) is not int or not 1 <= limit <= 20:
            message = "limit must be an integer from 1 through 20"
            await ctx.warning(f"Sample parameter error: {message}")
            raise ToolError(message)
        
        await ctx.info(f"Sampling {limit} rows from connection '{connection.connection_id}': {table_name}")
        
        # Use adapter-compatible quoting (backticks for MySQL, double-quotes for SQLite)
        adapter = connection.adapter
        quote = '`' if adapter.db_type == 'mysql' else '"'
        sql = f"SELECT * FROM {quote}{table_name}{quote} LIMIT {limit}"
        result = adapter.execute(sql)
        
        if isinstance(result, str) and result.startswith("Error:"):
            await ctx.error(f"Failed to sample table: {result}")
            return _tool_result(
                {
                    "success": False,
                    "error": result,
                    "connection_id": connection.connection_id,
                    "db_type": connection.db_type,
                },
                tool_name="sample", start_time=start_time,
                connection=connection, success=False,
            )
        
        data = _serialize_result(result)
        
        return _tool_result({
            "success": True,
            "table_name": table_name,
            "data": data,
            "row_count": len(data),
            "query": sql,
            "connection_id": connection.connection_id,
            "db_type": connection.db_type,
        }, tool_name="sample", start_time=start_time, connection=connection, success=True, row_count=len(data))


# =============================================================================
# Skills Extension Layer (v3.0) — Conditional registration
# Reference: FastMCP Component Visibility — disabled tools don't appear in list_tools
# Reference: Google Gemini — keep effective tool set within 10-20
# =============================================================================

# Pre-initialize path variables so Pylance sees them as always-bound.
# Values are only meaningful when SKILLS_ENABLED=True.
_project_root = Path(__file__).parent.resolve()
_skills_dir = _project_root / SKILLS_DIR


def _is_path_within(child: Path, parent: Path) -> bool:
    """Return whether a resolved child path is contained by resolved parent."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

if SKILLS_ENABLED:
    # Resolve skills directory with path safety check
    _skills_dir = Path(SKILLS_DIR)
    if not _skills_dir.is_absolute():
        _skills_dir = _project_root / _skills_dir
    _skills_dir = _skills_dir.resolve()

    # Security: SKILLS_DIR must be within project root (prevent .env poisoning)
    # Reference: SAFETY.md #15
    if not _is_path_within(_skills_dir, _project_root):
        logger.error(
            f"SKILLS_DIR '{_skills_dir}' is outside project root '{_project_root}'. "
            "Refusing to load skills for security (SAFETY.md #15)."
        )
        SKILLS_ENABLED = False

if SKILLS_ENABLED:
    # Import skills infrastructure (only when enabled to avoid import errors
    # if skills/ directory doesn't exist yet)
    sys.path.insert(0, str(_project_root / "skills" / "_lib"))
    from skill_loader import (
        discover,
        generate_skills_md,
        validate_name,
        load_query,
        load_mutation,
        validate_params,
        get_skills_cache,
        SkillMetadata,
    )
    from audit import AuditLogger

    # Discover skills at module load time (synchronous, consistent with
    # existing ENABLE_SCHEMA_TOOLS conditional registration pattern)
    _discovered_skills = discover(
        _skills_dir,
        query_validator=_validate_sql_template_startup_policy,
    )
    _audit_logger = AuditLogger()

    _configured_skill_connection_types = {
        config.connection_id: config.db_type
        for config in list_connection_configs()
    }
    for _skill_meta in _discovered_skills.values():
        if _skill_meta.connection_ids is None:
            continue
        _unconfigured_scope_ids = [
            connection_id
            for connection_id in _skill_meta.connection_ids
            if connection_id not in _configured_skill_connection_types
        ]
        if _unconfigured_scope_ids:
            logger.warning(
                "Skill '%s' declares connection_ids not configured in this "
                "deployment: %s. They remain unavailable and no connection "
                "is created dynamically.",
                _skill_meta.name,
                _unconfigured_scope_ids,
            )
        if _skill_meta.databases:
            for _scope_connection_id in _skill_meta.connection_ids:
                _scope_db_type = _configured_skill_connection_types.get(
                    _scope_connection_id
                )
                if _scope_db_type and _scope_db_type not in _skill_meta.databases:
                    logger.error(
                        "Skill '%s' connection scope conflict: connection '%s' "
                        "has database type '%s', but the Skill supports %s. "
                        "That target will fail closed; other valid targets are "
                        "not disabled.",
                        _skill_meta.name,
                        _scope_connection_id,
                        _scope_db_type,
                        _skill_meta.databases,
                    )

    # Generate SKILLS.md overview for human review
    if _discovered_skills:
        generate_skills_md(_discovered_skills, _skills_dir / "SKILLS.md")

    logger.info(
        f"Skills extension enabled: {len(_discovered_skills)} skill(s) discovered"
    )

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


    def _skill_excluded_profiles(meta: SkillMetadata) -> list[str]:
        """Return skill profiles blocked by the current profile policy."""
        if not SKILLS_EXCLUDE_PROFILES:
            return []
        return [
            profile
            for profile in meta.profiles
            if profile.lower() in SKILLS_EXCLUDE_PROFILES
        ]


    def _skill_connection_scope_state(
        meta: SkillMetadata,
        connection: ConnectionContext,
    ) -> dict[str, Any]:
        """Return the restrictive Skill metadata scope for one target.

        This metadata never grants access. It is evaluated in addition to DB
        type compatibility and all query/mutation server policies.
        """
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
                and _configured_skill_connection_types[connection_id]
                not in meta.databases
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
        meta: SkillMetadata,
        requested_connection_id: str | None,
    ) -> ConnectionContext:
        """Apply Skill scope before creating or accessing a database adapter."""
        try:
            config = get_connection_config(requested_connection_id)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        _ensure_skill_connection_allowed(meta, config)
        return ConnectionContext(
            connection_id=config.connection_id,
            config=config,
            adapter=get_adapter(config.connection_id),
            policy=config.policy,
        )


    def _get_skill_schema_snapshot(
        connection: ConnectionContext,
    ) -> _SkillSchemaSnapshot:
        """Return an explicit Skills schema-readiness observation."""
        if not SKILLS_CHECK_SCHEMA_ON_LIST:
            return _SkillSchemaSnapshot(
                enabled=False,
                available=False,
                table_names=frozenset(),
            )

        try:
            tables = connection.adapter.get_tables()
        except MetadataQueryError as exc:
            logger.warning("Skills schema readiness check unavailable: %s", exc)
            return _SkillSchemaSnapshot(
                enabled=True,
                available=False,
                table_names=frozenset(),
            )

        return _SkillSchemaSnapshot(
            enabled=True,
            available=True,
            table_names=frozenset(
                str(table.get("table_name", "")).lower()
                for table in tables
                if table.get("table_name")
            ),
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
        return [
            table for table in meta.tables
            if table.lower() not in allowed_tables
        ]


    def _mutation_connection_policy_state(
        meta: SkillMetadata,
        connection: ConnectionContext,
    ) -> tuple[bool, bool, str | None]:
        """Return connection support, policy result, and rejection reason."""
        if meta.type != "mutation":
            return True, True, None

        connection_supported = (
            connection.connection_id in _mutation_connection_allowlist
        )
        if not connection_supported:
            if MUTATION_CONNECTION_POLICY_EXPLICIT:
                return (
                    False,
                    False,
                    "Target connection is not authorized by "
                    "SKILLS_ALLOW_MUTATION_CONNECTIONS.",
                )
            return (
                False,
                False,
                "Mutation skills are limited to the default connection unless "
                "v3.6 mutation connection policy is configured.",
            )

        if not MUTATION_CONNECTION_POLICY_EXPLICIT:
            return True, True, None

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
        meta: SkillMetadata,
        schema_snapshot: _SkillSchemaSnapshot,
        connection: ConnectionContext,
    ) -> dict[str, Any]:
        """Describe whether a discovered skill can execute in the current state."""
        reasons: list[str] = []
        missing_tables: list[str] = []
        blocked_tables: list[str] = []
        excluded_profiles = _skill_excluded_profiles(meta)
        connection_scope = _skill_connection_scope_state(meta, connection)
        db_compatible = not meta.databases or connection.db_type in meta.databases
        mutation_enabled = meta.type != "mutation" or SKILLS_ALLOW_MUTATIONS
        (
            mutation_connection_supported,
            mutation_policy_allowed,
            mutation_policy_reason,
        ) = _mutation_connection_policy_state(
            meta,
            connection,
        )
        profile_allowed = not excluded_profiles
        schema_ready = True
        policy_allowed = True

        if excluded_profiles:
            reasons.append(
                "Skill profile(s) are excluded by SKILLS_EXCLUDE_PROFILES: "
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
        if meta.type == "mutation" and not SKILLS_ALLOW_MUTATIONS:
            reasons.append("Mutation skills are disabled (SKILLS_ALLOW_MUTATIONS=0).")
        if mutation_policy_reason:
            reasons.append(mutation_policy_reason)
            policy_allowed = False

        blocked_tables = _query_skill_blocked_tables(meta, connection)
        if blocked_tables:
            policy_allowed = False
            reasons.append(
                "Required query skill table(s) are blocked by the target "
                f"connection allowlist: {blocked_tables}."
            )

        if schema_snapshot.enabled and meta.tables:
            if not schema_snapshot.available:
                schema_ready = False
                reasons.append(
                    "Required table readiness could not be verified because "
                    "database metadata is unavailable for the target connection."
                )
            else:
                missing_tables = [
                    table for table in meta.tables
                    if table.lower() not in schema_snapshot.table_names
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
            "schema_check_available": schema_snapshot.available,
            "missing_tables": missing_tables,
        }


    def _ensure_skill_schema_ready(meta: SkillMetadata, connection: ConnectionContext) -> None:
        """Raise a ToolError if the current database is missing required tables."""
        if not SKILLS_CHECK_SCHEMA_ON_LIST or not meta.tables:
            return

        schema_snapshot = _get_skill_schema_snapshot(connection)
        if not schema_snapshot.available:
            raise ToolError(
                f"Skill '{meta.name}' schema readiness could not be verified "
                "because database metadata is unavailable for the target connection."
            )

        availability = _skill_availability_state(meta, schema_snapshot, connection)
        if availability["missing_tables"]:
            raise ToolError(
                f"Skill '{meta.name}' requires table(s) not found in the "
                f"target connection schema: {availability['missing_tables']}"
            )


    def _ensure_query_skill_policy_ready(
        meta: SkillMetadata,
        connection: ConnectionContext,
    ) -> None:
        """Raise a ToolError if target connection policy blocks query skill tables."""
        blocked_tables = _query_skill_blocked_tables(meta, connection)
        if blocked_tables:
            raise ToolError(
                f"Skill '{meta.name}' requires table(s) blocked by target "
                f"connection policy: {blocked_tables}"
            )


    def _ensure_skill_profile_allowed(meta: SkillMetadata) -> None:
        """Raise a ToolError if the skill is excluded by profile policy."""
        excluded_profiles = _skill_excluded_profiles(meta)
        if excluded_profiles:
            raise ToolError(
                f"Skill '{meta.name}' is excluded by SKILLS_EXCLUDE_PROFILES: "
                f"{excluded_profiles}"
            )


    def _context_client_id(ctx: Context) -> str | None:
        """Return the optional MCP client id without failing direct tests."""
        try:
            return ctx.client_id
        except Exception:
            return None


    def _elapsed_ms(start_time: float) -> float:
        """Return elapsed milliseconds rounded for stable runtime metadata."""
        return round((time.perf_counter() - start_time) * 1000, 3)


    def _skill_tool_result(
        payload: dict[str, Any],
        meta: SkillMetadata,
        *,
        mode: str,
        start_time: float,
        connection: ConnectionContext,
        row_count: int | None = None,
        total_rows: int | None = None,
        truncated: bool | None = None,
        audit_logged: bool | None = None,
        preview_token_required: bool | None = None,
        preview_token_validated: bool | None = None,
        preview_token_consumed: bool | None = None,
        preview_token_id: str | None = None,
    ) -> ToolResult:
        """Attach runtime metadata without changing the structured payload."""
        payload_success = payload.get("success")
        tool_name = (
            "execute_mutation_skill"
            if meta.type == "mutation"
            else "execute_query_skill"
        )
        runtime_meta: dict[str, Any] = {
            "tool_name": tool_name,
            "skill_name": meta.name,
            "skill_type": meta.type,
            "skill_version": meta.version,
            "mode": mode,
            "db_type": connection.db_type,
            "connection_id": connection.connection_id,
            "execution_ms": _elapsed_ms(start_time),
            "success": payload_success if isinstance(payload_success, bool) else True,
            "idempotent": meta.idempotent,
        }
        optional_fields = {
            "row_count": row_count,
            "total_rows": total_rows,
            "truncated": truncated,
            "audit_logged": audit_logged,
            "preview_token_required": preview_token_required,
            "preview_token_validated": preview_token_validated,
            "preview_token_consumed": preview_token_consumed,
            "preview_token_id": preview_token_id,
        }
        runtime_meta.update(
            {key: value for key, value in optional_fields.items() if value is not None}
        )
        return ToolResult(structured_content=payload, meta=runtime_meta)


    def _skill_matches(
        meta: SkillMetadata,
        search: str | None,
        category: str | None,
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
            *meta.tables,
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
            "connection_scope_allowed": availability[
                "connection_scope_allowed"
            ],
            "policy_allowed": availability["policy_allowed"],
            "schema_ready": availability["schema_ready"],
        }
        if meta.type == "mutation":
            projected["mutation_connection_supported"] = availability[
                "mutation_connection_supported"
            ]
            projected["mutation_policy_allowed"] = availability[
                "mutation_policy_allowed"
            ]
        if availability["disabled_reason"]:
            projected["disabled_reason"] = availability["disabled_reason"]
        if availability["excluded_profiles"]:
            projected["excluded_profiles"] = availability["excluded_profiles"]
        if availability["missing_tables"]:
            projected["missing_tables"] = availability["missing_tables"]
        if availability["blocked_tables"]:
            projected["blocked_tables"] = availability["blocked_tables"]
        if detail_level in {"summary", "full"}:
            # Keep the summary shape close to the historical list_skills()
            # response so existing clients can continue to reason from it.
            projected.update({
                "source": meta.source,
                "triggers": meta.triggers,
                "idempotent": meta.idempotent,
                "databases": meta.databases,
                "connection_ids": meta.connection_ids,
                "configured_connection_ids": availability[
                    "configured_connection_ids"
                ],
                "unconfigured_connection_ids": availability[
                    "unconfigured_connection_ids"
                ],
                "connection_type_conflicts": availability[
                    "connection_type_conflicts"
                ],
                "profiles": meta.profiles,
            })
            if meta.related_skills:
                projected["related_skills"] = meta.related_skills

        if detail_level == "full":
            projected.update({
                "params": meta.params,
                "version": meta.version,
                "requires_confirmation": meta.requires_confirmation,
                "related_skills": meta.related_skills,
                "tables": meta.tables,
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
            {"category": category, "count": counts[category]}
            for category in sorted(counts)
        ]

    # ── list_skills ──
    @mcp.tool(
        timeout=_MCP_TOOL_TIMEOUT,
        annotations=ToolAnnotations(
            title="List Available Skills",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def list_skills(
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
                    "The default is the server's SKILLS_LIST_DEFAULT_DETAIL "
                    "startup setting."
                )
            ),
        ] = SKILLS_LIST_DEFAULT_DETAIL,
        available_only: Annotated[
            bool,
            Field(
                description=(
                    "When true, return only skills executable for the target "
                    "connection, including Skill connection_ids scope, DB "
                    "compatibility, mutation switch, connection policy, and "
                    "schema readiness. Pass false to inspect the full catalog. "
                    "The default is the server's "
                    "SKILLS_LIST_AVAILABLE_ONLY_DEFAULT startup setting."
                ),
            ),
        ] = SKILLS_LIST_AVAILABLE_ONLY_DEFAULT,
        connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    ) -> ToolResult:
        """
        List all available pre-defined skills (query and mutation).

        Supports MCP-level progressive disclosure:
        - compact: lightweight catalog for discovery
        - summary: compatibility-oriented metadata projection
        - full: full cached parameter schema for planning execution

        Omitting detail_level uses the startup-resolved
        SKILLS_LIST_DEFAULT_DETAIL setting.

        This tool never reads skill files at runtime. It only projects metadata
        from the startup-validated in-memory skill cache.

        Returns:
            Dict with skills list and count
        """
        start_time = time.perf_counter()
        connection = _resolve_connection_context(connection_id)
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

        skills = get_skills_cache()
        schema_snapshot = _get_skill_schema_snapshot(connection)
        matched_catalog = [
            meta
            for name, meta in sorted(skills.items())
            if _skill_matches(meta, normalized_search, normalized_category)
        ]
        availability_by_name = {
            meta.name: _skill_availability_state(meta, schema_snapshot, connection)
            for meta in matched_catalog
        }
        available_count = sum(
            1 for meta in matched_catalog
            if availability_by_name[meta.name]["executable"]
        )
        unavailable_count = len(matched_catalog) - available_count
        schema_unready_count = sum(
            1 for meta in matched_catalog
            if not availability_by_name[meta.name]["schema_ready"]
        )
        profile_excluded_count = sum(
            1 for meta in matched_catalog
            if not availability_by_name[meta.name]["profile_allowed"]
        )
        policy_blocked_count = sum(
            1 for meta in matched_catalog
            if not availability_by_name[meta.name]["policy_allowed"]
        )
        connection_scope_blocked_count = sum(
            1 for meta in matched_catalog
            if not availability_by_name[meta.name]["connection_scope_allowed"]
        )
        connection_type_conflict_count = sum(
            1 for meta in matched_catalog
            if any(
                conflict["connection_id"] == connection.connection_id
                for conflict in availability_by_name[meta.name][
                    "connection_type_conflicts"
                ]
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
            "filtered_unavailable_skills": unavailable_count if resolved_available_only else 0,
            "schema_unready_skills": schema_unready_count,
            "policy_blocked_skills": policy_blocked_count,
            "connection_scope_blocked_skills": connection_scope_blocked_count,
            "connection_type_conflict_skills": connection_type_conflict_count,
            "profile_excluded_skills": profile_excluded_count,
            "query_skills": query_count,
            "mutation_skills": mutation_count,
            "mutations_enabled": SKILLS_ALLOW_MUTATIONS,
            "schema_check_enabled": schema_snapshot.enabled,
            "schema_check_available": schema_snapshot.available,
            "excluded_profiles": sorted(SKILLS_EXCLUDE_PROFILES),
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
            result, tool_name="list_skills", start_time=start_time, success=True,
            connection=connection,
            matched_skills=len(skills_list), available_skills=available_count,
            total_skills=len(skills),
        )

    # ── get_skill_detail ──
    @mcp.tool(
        timeout=_MCP_TOOL_TIMEOUT,
        annotations=ToolAnnotations(
            title="Get Skill Detail",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def get_skill_detail(
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
        """
        Return cached execution fields or full metadata for one Skill.

        Call this directly when the Skill name is known but its params are not.
        Use detail_level="execution" for params/schema and the next action.
        Do not call it when list_skills(detail_level="full") already returned
        the params. Use full only for explicit catalog/readiness diagnostics.
        This tool does not read files at runtime or expose SQL or mutation source.
        """
        start_time = time.perf_counter()
        connection = _resolve_connection_context(connection_id)
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

        skills = get_skills_cache()
        if skill_name not in skills:
            msg = f"Skill '{skill_name}' not found"
            await ctx.warning(msg)
            raise ToolError(msg)

        meta = skills[skill_name]
        schema_snapshot = _get_skill_schema_snapshot(connection)
        availability = _skill_availability_state(meta, schema_snapshot, connection)
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
            result.update({
                "mutations_enabled": SKILLS_ALLOW_MUTATIONS,
                "schema_check_enabled": schema_snapshot.enabled,
                "schema_check_available": schema_snapshot.available,
            })

        return _tool_result(
            result, tool_name="get_skill_detail", start_time=start_time, success=True,
            connection=connection,
            skill_name=skill_name, skill_type=meta.type,
        )

    # ── execute_query_skill ──
    @mcp.tool(
        timeout=_MCP_TOOL_TIMEOUT,
        annotations=ToolAnnotations(
            title="Execute Query Skill",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "skill_name": {"type": "string"},
                "connection_id": {"type": "string"},
                "db_type": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "row_count": {"type": "integer", "minimum": 0},
                "total_rows": {"type": "integer", "minimum": 0},
                "truncated": {"type": "boolean"},
                "truncation_note": {"type": ["string", "null"]},
            },
            "required": ["success", "skill_name", "data", "row_count", "total_rows", "truncated"],
            "additionalProperties": True,
        },
    )
    async def execute_query_skill(
        skill_name: Annotated[str, Field(description="Name of the query skill to execute")],
        params: Annotated[dict[str, Any], Field(description="Parameters for the skill (must match skill_def.md schema)")],
        ctx: Context,
        connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
    ) -> ToolResult:
        """
        Execute a pre-defined query skill with parameterized SQL.

        Skills are pre-audited SQL templates and are checked against the same
        read-query policy used by the raw query(sql) tool at startup and runtime.

        Uses named parameters (:param_name) via SQLAlchemy text() for SQL injection prevention.

        Args:
            skill_name: The skill name (e.g., "monthly-sales-report")
            params: Parameter dict matching the skill's frontmatter schema

        Returns:
            Query results (same format as query() tool, plus skill_name)
        """
        start_time = time.perf_counter()

        try:
            validate_name(skill_name)
            meta = get_skills_cache().get(skill_name)
            if meta is None:
                raise FileNotFoundError(f"Skill '{skill_name}' not found")
            if meta.type != "query":
                raise TypeError(
                    f"Skill '{skill_name}' is type '{meta.type}', expected 'query'"
                )
            # Preserve the global default-connection contract when omitted,
            # then fail closed against the Skill metadata scope before adapter
            # construction or any database access.
            connection = _resolve_skill_connection(meta, connection_id)
            sql_template, param_schema = load_query(skill_name)
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
            _ensure_skill_profile_allowed(meta)
            _ensure_skill_schema_ready(meta, connection)
            _ensure_query_skill_policy_ready(meta, connection)
        except ToolError as e:
            await ctx.warning(str(e))
            raise

        is_safe, safety_error = _validate_sql_query_policy(sql_template, connection.policy)
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
            if SKILLS_AUDIT_QUERIES:
                _audit_logger.log(
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

        truncation_result = _truncate_result(data, total_rows)

        if truncation_result["truncated"]:
            await ctx.warning(
                f"Truncated returned payload: {truncation_result['returned_rows']}/{total_rows} rows shown. "
                f"Add WHERE/LIMIT/ORDER BY to limit database work and stabilize ordering."
            )
        else:
            await ctx.info(f"Query skill returned {total_rows} rows")

        audit_logged = False
        if SKILLS_AUDIT_QUERIES:
            audit_logged = _audit_logger.log(
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
            ) if truncation_result["truncated"] else None,
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

    # ── execute_mutation_skill (second switch) ──
    if SKILLS_ALLOW_MUTATIONS:
        @mcp.tool(
            timeout=_MCP_TOOL_TIMEOUT,
            annotations=ToolAnnotations(
                title="Execute Mutation Skill",
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,  # Conservative default; per-skill idempotent
                                       # info is conveyed via list_skills() and result dict
                openWorldHint=False,
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "skill_name": {"type": "string"},
                    "mode": {"type": "string", "enum": ["preview", "execute"]},
                    "connection_id": {"type": "string"},
                    "db_type": {"type": "string"},
                    # Preview branch (success=true, mode=preview)
                    "preview": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Preview details returned by mutation.preview(); shape is skill-defined.",
                    },
                    "preview_token": {
                        "type": "string",
                        "description": (
                            "API-opaque one-time bearer handle "
                            "returned by preview and required for execute."
                        ),
                    },
                    "preview_token_expires_at": {"type": "string"},
                    # Execute branch (success=true, mode=execute)
                    "result": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Execution result; typically includes 'rowcount'. Shape is skill-defined.",
                    },
                    # Validation-failure branch (success=false, either mode)
                    "validation": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Validation details when success=false (contains 'valid' and 'errors').",
                    },
                    # Common (both success branches)
                    "idempotent": {"type": "boolean"},
                },
                "required": ["success", "skill_name", "mode"],
                "additionalProperties": True,
            },
        )
        async def execute_mutation_skill(
            skill_name: Annotated[str, Field(description="Name of the mutation skill to execute")],
            params: Annotated[dict[str, Any], Field(description="Parameters for the skill (must match skill_def.md schema)")],
            ctx: Context,
            confirm: Annotated[bool, Field(description="False=preview (default), True=execute")] = False,
            preview_token: Annotated[str | None, _MUTATION_PREVIEW_TOKEN_FIELD] = None,
            connection_id: Annotated[str | None, _CONNECTION_ID_FIELD] = None,
        ) -> ToolResult:
            """
            Execute a pre-defined mutation (write) skill.

            Two-phase workflow (Anthropic plan-validate-execute pattern):
                1. confirm=false (default) — validate + preview, no database changes;
                    registers and returns a one-time preview_token
                2. confirm=true — verify and atomically consume preview_token,
                    re-validate + execute with preview-state binding, commits changes
                    in a transaction

            Args:
                skill_name: The mutation skill name (e.g., "update-order-status")
                params: Parameter dict matching the skill's frontmatter schema
                confirm: False=dry-run preview (default), True=actual execution
                preview_token: Required when confirm=True; returned by preview
                connection_id: Configured target connection; omit for the default

            Returns:
                Preview result (confirm=false) or execution result (confirm=true)
            """
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
                skills = get_skills_cache()
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
                connection = _resolve_skill_connection(meta, connection_id)
                _, mutation_policy_allowed, mutation_policy_reason = (
                    _mutation_connection_policy_state(meta, connection)
                )
                if not mutation_policy_allowed:
                    raise ToolError(
                        mutation_policy_reason
                        or "Mutation is not authorized by target connection policy."
                    )
                validated_params = validate_params(params, meta.params)

                _ensure_skill_profile_allowed(meta)
                _ensure_skill_schema_ready(meta, connection)

                # Load mutation module
                adapter = connection.adapter
                mutation = load_mutation(skill_name, adapter, _audit_logger)
                client_id = _context_client_id(ctx)

            except (ValueError, TypeError, FileNotFoundError, AttributeError,
                    ImportError, SyntaxError, ToolError) as e:
                await ctx.warning(f"Mutation skill setup error: {e}")
                if isinstance(e, ToolError):
                    raise
                raise ToolError(str(e)) from e

            if not resolved_confirm:
                # Phase 1: validate + preview (no writes)
                try:
                    validation = mutation.validate(validated_params)
                    if not validation.get("valid", False):
                        errors = validation.get("errors", ["Validation failed"])
                        await ctx.warning(f"Validation failed: {errors}")
                        payload = {
                            "success": False,
                            "skill_name": skill_name,
                            "mode": "preview",
                            "connection_id": connection.connection_id,
                            "db_type": connection.db_type,
                            "validation": validation,
                        }
                        return _skill_tool_result(
                            payload,
                            meta,
                            mode="preview",
                            start_time=start_time,
                            connection=connection,
                            audit_logged=False,
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
                    if (
                        "error" in preview_result
                        or (
                            "success" in preview_result
                            and preview_result["success"] is not True
                        )
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
                        audit_logged = _audit_logger.log(
                            skill_name=skill_name,
                            params=validated_params,
                            mode="preview",
                            result={
                                "success": False,
                                "preview": False,
                                "error": preview_error,
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

                    generated_token, expires_at, request_binding_json = (
                        _create_mutation_preview_token(
                            skill_name=skill_name,
                            skill_version=meta.version,
                            params=validated_params,
                            connection=connection,
                        )
                    )
                    _register_mutation_preview_token(
                        generated_token,
                        expires_at,
                        request_binding_json,
                        binding_json,
                    )
                    token_id = _preview_token_id(generated_token)

                    # Audit the preview without recording the full token.
                    audit_logged = _audit_logger.log(
                        skill_name=skill_name,
                        params=validated_params,
                        mode="preview",
                        result={
                            "success": True,
                            "preview": True,
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
                # Phase 2: validate + execute (commits to database)
                token_consumed = False
                execution_started = False
                write_completed = False
                try:
                    execution_binding = _consume_mutation_preview_token(
                        preview_token,
                        skill_name=skill_name,
                        skill_version=meta.version,
                        params=validated_params,
                        connection=connection,
                    )
                    token_id = _preview_token_id(preview_token or "")
                    token_consumed = True

                    try:
                        validation = mutation.validate(validated_params)
                    except ToolError as validation_error:
                        _audit_logger.log(
                            skill_name=skill_name,
                            params=validated_params,
                            mode="execute",
                            result={
                                "success": False,
                                "error": str(validation_error),
                            },
                            client_id=client_id,
                            connection_id=connection.connection_id,
                            db_type=connection.db_type,
                        )
                        raise
                    if not validation.get("valid", False):
                        errors = validation.get("errors", ["Validation failed"])
                        await ctx.warning(f"Validation failed: {errors}")
                        audit_logged = _audit_logger.log(
                            skill_name=skill_name,
                            params=validated_params,
                            mode="execute",
                            result={
                                "success": False,
                                "error": f"Validation failed: {errors}",
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

                    execution_started = True
                    result = mutation.run_execute(
                        validated_params,
                        skill_name=skill_name,
                        mode="execute",
                        client_id=client_id,
                        connection_id=connection.connection_id,
                        db_type=connection.db_type,
                        execution_binding=execution_binding,
                    )
                    write_completed = True
                    audit_logged = bool(result.pop("_audit_logged", True))

                    await ctx.info(
                        f"Mutation '{skill_name}' executed: rowcount={result.get('rowcount')}"
                    )
                    payload = {
                        "success": True,
                        "skill_name": skill_name,
                        "mode": "execute",
                        "connection_id": connection.connection_id,
                        "db_type": connection.db_type,
                        "result": result,
                        "idempotent": meta.idempotent,
                    }
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
                except ToolError as e:
                    if write_completed:
                        logger.error(
                            "Mutation response handling failed after a "
                            "successful write: %s",
                            e.__class__.__name__,
                        )
                        raise ToolError(
                            "Mutation execution completed, but the tool response "
                            "failed. The preview_token has been consumed; verify "
                            "the current database state before another mutation."
                        ) from e
                    if token_consumed:
                        if not execution_started:
                            raise ToolError(
                                f"{e} No database write was attempted. The "
                                "preview_token has been consumed; run preview "
                                "again before another mutation."
                            ) from e
                        raise ToolError(
                            f"{e} The preview_token has been consumed and the "
                            "write outcome may be unknown; verify the current "
                            "database state before another preview or mutation."
                        ) from e
                    raise
                except Exception as e:
                    if write_completed:
                        logger.error(
                            "Mutation response handling failed after a "
                            "successful write: %s",
                            e.__class__.__name__,
                        )
                        raise ToolError(
                            "Mutation execution completed, but the tool response "
                            "failed. The preview_token has been consumed; verify "
                            "the current database state before another mutation."
                        ) from e
                    sanitized = adapter._handle_error(e)
                    if token_consumed:
                        if not execution_started:
                            sanitized = (
                                f"{sanitized} No database write was attempted. "
                                "The preview_token has been consumed; run "
                                "preview again before another mutation."
                            )
                        else:
                            sanitized = (
                                f"{sanitized} The preview_token has been "
                                "consumed; the write outcome may be unknown. "
                                "Verify the current database state before "
                                "another preview or mutation."
                            )
                    _audit_logger.log(
                        skill_name=skill_name,
                        params=validated_params,
                        mode="execute",
                        result={"success": False, "error": sanitized},
                        client_id=client_id,
                        connection_id=connection.connection_id,
                        db_type=connection.db_type,
                    )
                    raise ToolError(sanitized) from e

        logger.info("Mutation skills enabled (SKILLS_ALLOW_MUTATIONS=1)")
        _log_mutation_security_startup()
    else:
        logger.info("Mutation skills disabled (SKILLS_ALLOW_MUTATIONS=0)")

else:
    logger.info("Skills extension disabled (ENABLE_SKILLS=0)")


# =============================================================================
# MCP Prompts
# =============================================================================

@mcp.prompt(name="sql_assistant")
def sql_assistant() -> str:
    """System prompt for SQL query assistance."""
    # The prompt has no target connection argument, so it must not present the
    # default connection's UNION policy as a server-wide rule. Each tool call
    # resolves and enforces the selected connection policy at runtime.
    # Reference: Microsoft prompt engineering - clear, structured, avoid unnecessary steps
    # Reference: MCP spec - model-driven tool selection, provide decision rules not fixed paths
    cross_table = (
        "UNION policy is connection-specific. Inspect the selected alias in "
        "list_connections(); query() and Query Skills enforce that target's policy."
    )

    # Skills extension info for prompt
    skills_info = ""
    if SKILLS_ENABLED:
        skills_info = """
- list_skills(search, category, detail_level, available_only, connection_id): Search pre-defined skills; full includes params
- get_skill_detail(skill_name, connection_id, detail_level): Get params/schema for one known Skill
- execute_query_skill(name, params, connection_id): Execute a query skill with parameters
"""
        if SKILLS_ALLOW_MUTATIONS:
            skills_info += "- execute_mutation_skill(name, params, confirm, preview_token, connection_id): Preview a mutation on an authorized configured connection, then execute on the same connection with confirm=true plus the returned preview_token\n"

    # Conditional heuristic prompt - let LLM decide based on context
    # Reference: "Model-driven tool selection" - provide rules, not fixed chains
    return f"""Database query assistant.

Tools (choose based on need):
- list_connections(): Show configured connection ids and their non-sensitive policies; takes no arguments
- query(sql, connection_id): Execute conservative free-form read-only SQL; EXPLAIN ANALYZE is rejected
- list_tables(connection_id): Visible table overview with row estimates; may be truncated
- describe_table(name, connection_id): Single-table adapter-visible column metadata + row estimate + is_large hint; not complete DDL
- get_full_schema(connection_id, detail_level, group_identical): Compact adapter-visible column groups or full adapter-visible column metadata; grouping is not full DDL equivalence
- check_connection(connection_id): Verify database connectivity (use only on connection errors)
{skills_info}
{_CONNECTION_ROUTING_GUIDANCE}

Decision rules:
- Unknown structure? Use list_tables() when names/counts are enough. If broad columns or multi-table planning are needed, call get_full_schema(detail_level="compact") directly; it already includes table names and row estimates.
- Need nullable, default, or key metadata? Use describe_table() for one selected table or get_full_schema(detail_level="full") across several tables.
- For single-table queries, if schema/columns unknown, call describe_table(table_name) before query().
- Know the table? Query directly with appropriate LIMIT
- is_large=true in response? Use LIMIT or aggregation
- Unknown Skill? Use targeted list_skills(..., detail_level="compact"), then get_skill_detail(..., detail_level="execution") only if params are unknown.
- Known Skill but unknown params? Call get_skill_detail(..., detail_level="execution") directly.
- Params already known, including from list_skills(detail_level="full")? Execute directly; for mutations, preview first with confirm=false.
- {cross_table}

For raw query() calls, include the executed SQL in the response. For Skills,
report the Skill name, params, and connection_id; do not invent SQL that was
not disclosed."""
