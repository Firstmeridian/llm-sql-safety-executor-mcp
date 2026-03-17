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
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator
from pydantic import Field
from mcp.types import ToolAnnotations
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from sql_safety_checker import is_sql_safe, execute_sql
from db_adapter import get_adapter, DB_TYPE

logger = logging.getLogger(__name__)

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
MAX_SCHEMA_TABLES = int(os.getenv("MAX_SCHEMA_TABLES", "50"))  # Max tables in get_full_schema
MAX_OVERVIEW_TABLES = int(os.getenv("MAX_OVERVIEW_TABLES", "100"))  # Max tables in list_tables

# UNION Query Policy (P2 Security: Configurable UNION handling)
# Reference: OWASP Defense-in-Depth - block UNION by default for safety
# Reference: OpenAI "minimize tool calls" - allow UNION for efficiency when needed
# When disabled (default): LLM uses multiple queries (safer, more calls)
# When enabled: UNION allowed but requires table allowlist for validation
ALLOW_UNION = os.getenv("ALLOW_UNION", "0") == "1"

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

# Skills directory path (relative to project root or absolute)
SKILLS_DIR = os.getenv("SKILLS_DIR", "skills/")

# =============================================================================
# Table Allowlist Configuration (P1 Security: Restrict table access)
# Reference: Microsoft "Least Privilege Principle" - only allow access to necessary tables
# Reference: Anthropic MCP Security - "Implement proper access controls"
# =============================================================================

def _parse_table_allowlist() -> set[str] | None:
    """
    Parse ALLOWED_TABLES environment variable into a set.
    
    Format: Comma-separated table names (case-insensitive)
    Special value: "*" means allow all tables (explicit opt-in for UNION)
    Example: ALLOWED_TABLES=products,orders,customers
    
    Returns:
        Set of allowed table names (lowercase), None if not configured,
        or {"*"} if explicitly set to allow all
    """
    allowed_tables_env = os.getenv("ALLOWED_TABLES", "").strip()
    if not allowed_tables_env:
        return None  # No allowlist configured - allow all tables
    
    # Special case: "*" means explicitly allow all tables
    if allowed_tables_env == "*":
        logger.info("Table allowlist set to '*' - all tables allowed (explicit)")
        return {"*"}  # Special marker for "allow all"
    
    # Parse comma-separated list, normalize to lowercase
    tables = {t.strip().lower() for t in allowed_tables_env.split(",") if t.strip()}
    if tables:
        logger.info(f"Table allowlist enabled: {len(tables)} tables allowed")
    return tables if tables else None


# Load allowlist at startup
ALLOWED_TABLES: set[str] | None = _parse_table_allowlist()

# Log security configuration at module load
if ALLOW_UNION:
    if ALLOWED_TABLES:
        logger.info(f"UNION queries enabled with table allowlist: {sorted(ALLOWED_TABLES)}")
    else:
        logger.warning("ALLOW_UNION=1 but no ALLOWED_TABLES configured - UNION will be blocked")
else:
    logger.info("UNION queries disabled (default safe mode)")


def _is_table_allowed(table_name: str) -> bool:
    """
    Check if a table is in the allowlist.
    
    Args:
        table_name: Name of the table to check
        
    Returns:
        True if table is allowed (or no allowlist configured), False otherwise
    """
    if ALLOWED_TABLES is None:
        return True  # No allowlist - allow all
    if "*" in ALLOWED_TABLES:
        return True  # Explicit "allow all" via ALLOWED_TABLES=*
    return table_name.lower() in ALLOWED_TABLES


def _extract_tables_from_sql(sql: str) -> list[str]:
    """
    Extract table names from a SQL query.
    
    Handles common patterns:
    - FROM table_name
    - JOIN table_name
    - UPDATE table_name (blocked by safety check, but included for completeness)
    - INTO table_name
    
    Args:
        sql: SQL query string
        
    Returns:
        List of table names found in the query
    """
    tables = []
    
    # Pattern for FROM/JOIN clauses
    # Handles: FROM table, FROM `table`, FROM schema.table, FROM `schema`.`table`
    # Reference: MySQL identifier syntax - captures only the table name (after optional schema.)
    from_join_pattern = r'(?:FROM|JOIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
    matches = re.findall(from_join_pattern, sql, re.IGNORECASE)
    tables.extend(matches)
    
    # Pattern for table in DESCRIBE/EXPLAIN (also handles schema.table)
    describe_pattern = r'(?:DESCRIBE|DESC|EXPLAIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
    matches = re.findall(describe_pattern, sql, re.IGNORECASE)
    tables.extend(matches)
    
    return list(set(tables))  # Remove duplicates


def _check_table_allowlist(sql: str) -> tuple[bool, str | None]:
    """
    Check if all tables in a SQL query are in the allowlist.
    
    Args:
        sql: SQL query to check
        
    Returns:
        (is_allowed, error_message) - True if all tables allowed, False with error otherwise
    """
    if ALLOWED_TABLES is None:
        return True, None  # No allowlist configured
    
    tables = _extract_tables_from_sql(sql)
    blocked_tables = [t for t in tables if not _is_table_allowed(t)]
    
    if blocked_tables:
        return False, f"Access denied to table(s): {', '.join(blocked_tables)}. Only allowed tables: {', '.join(sorted(ALLOWED_TABLES))}"
    
    return True, None


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
# Reference: Google/Anthropic best practices - server instructions should describe capabilities,
# not prescribe workflow (let LLM decide based on task context)
mcp = FastMCP(
    name="sql-safety-executor",
    instructions="""Database query assistant with READ-ONLY access.
Use query() for all data requests. Use describe_table() or get_full_schema() first if structure unknown.
For single-table queries, if schema/columns unknown, call describe_table(table_name) before query().""",
    lifespan=lifespan,
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
    Validate table/column name to prevent SQL injection.
    
    Security measures:
    - Only allow ASCII alphanumeric and underscore (stricter than before)
    - Block quotes and special characters
    - Length limit to prevent buffer issues
    - Reject MySQL reserved words that could be exploited
    """
    if not name or len(name) > 64:  # MySQL identifier max length
        return False
    
    # Strict ASCII pattern: letters, digits, underscore only
    # Chinese characters are allowed but validated separately
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


# Blocked SHOW commands that leak sensitive info
BLOCKED_SHOW_PATTERNS = [
    r'SHOW\s+VARIABLES',
    r'SHOW\s+GRANTS',
    r'SHOW\s+PROCESSLIST',
    r'SHOW\s+MASTER',
    r'SHOW\s+SLAVE',
    r'SHOW\s+BINARY',
    r'SHOW\s+ENGINE',
    r'SHOW\s+PLUGINS',
    r'SHOW\s+PRIVILEGES',
    r'SHOW\s+STATUS',  # Can leak sensitive metrics
]


def _is_query_safe_extended(sql: str) -> tuple[bool, str | None]:
    """
    Extended safety check beyond basic statement type validation.
    
    Returns:
        (is_safe, error_message)
    """
    sql_upper = sql.upper().strip()
    
    # Check blocked SHOW commands
    for pattern in BLOCKED_SHOW_PATTERNS:
        if re.match(pattern, sql_upper, re.IGNORECASE):
            return False, "This SHOW command is not allowed for security reasons"
    
    # Block access to system databases in SELECT
    # Includes INFORMATION_SCHEMA to prevent ALLOWED_TABLES bypass
    # (users could query INFORMATION_SCHEMA.TABLES to see all table names)
    system_table_pattern = r'\b(mysql|performance_schema|information_schema)\s*\.'
    if re.search(system_table_pattern, sql, re.IGNORECASE):
        return False, "Access to system databases not allowed. Use list_tables() or describe_table() instead."
    
    # UNION handling: Configurable based on ALLOW_UNION setting
    # Reference: OWASP - UNION is common SQL injection vector
    # Reference: OpenAI - minimize tool calls for efficiency
    if re.search(r'\bUNION\b', sql, re.IGNORECASE):
        if not ALLOW_UNION:
            # Default: Block UNION, guide LLM to use multiple queries
            return False, (
                "UNION queries disabled for security. "
                "Execute separate queries for each table and combine results in your response."
            )
        # UNION enabled: Require table allowlist for validation
        if ALLOWED_TABLES is None:
            return False, (
                "UNION requires ALLOWED_TABLES. "
                "Set ALLOWED_TABLES=table1,table2 or ALLOWED_TABLES=* to enable."
            )
        # UNION will be validated by _check_table_allowlist() which extracts all tables
        logger.info("UNION query allowed - validating tables")
    
    # Block subqueries in FROM clause (potential info disclosure)
    # Allow subqueries in WHERE for legitimate use
    if re.search(r'FROM\s*\(', sql, re.IGNORECASE):
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


# =============================================================================
# MCP Tools (Following FastMCP Best Practices)
# =============================================================================

@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute SQL Query",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def query(sql: str, ctx: Context) -> dict[str, Any]:
    """
    Execute a SQL SELECT query on the database.
    
    This is the PRIMARY tool for all database queries.
    Safety validation is automatic - only read-only statements are allowed.
    Supported: SELECT, SHOW, DESCRIBE, EXPLAIN.
    
    Args:
        sql: A SQL SELECT query to execute
        
    Returns:
        Query results with data rows, or error message if query fails
        
    Examples:
        query("SELECT * FROM users LIMIT 10")
        query("SELECT name, email FROM users WHERE active = 1")
        query("SELECT COUNT(*) as total FROM orders")
        query("SHOW TABLES")
        query("DESCRIBE users")
        query("EXPLAIN SELECT * FROM products WHERE id = 1")
    """
    await ctx.info(f"Executing query: {sql}")
    
    # Validate safety - basic check
    if not is_sql_safe(sql):
        await ctx.warning(f"Rejected unsafe query: {sql}")
        return {
            "success": False,
            "error": "Only read-only queries allowed (SELECT, SHOW, DESCRIBE, EXPLAIN)",
            "query": sql
        }
    
    # Extended safety check - block dangerous patterns
    is_safe, error_msg = _is_query_safe_extended(sql)
    if not is_safe:
        await ctx.warning(f"Rejected query (extended check): {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "query": sql
        }
    
    # Table allowlist check (P1 Security)
    # Reference: Microsoft "Least Privilege Principle"
    is_allowed, allowlist_error = _check_table_allowlist(sql)
    if not is_allowed:
        await ctx.warning(f"Table access denied: {allowlist_error}")
        return {
            "success": False,
            "error": allowlist_error,
            "query": sql
        }
    
    # Execute query
    result = execute_sql(sql)
    
    # Handle error
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Query failed: {result}")
        return {
            "success": False,
            "error": result,
            "query": sql
        }
    
    # Success - Apply token optimization with truncation
    # Best practice: Limit response size to prevent context overflow
    # Reference: Google Gemini - "Token limits: function descriptions and parameters count toward input token limits"
    data = _serialize_result(result)
    total_rows = len(result) if isinstance(result, list) else 0
    
    # Apply truncation to prevent token explosion (root cause of 454K token issue)
    truncation_result = _truncate_result(data, total_rows)
    
    if truncation_result["truncated"]:
        await ctx.warning(
            f"Truncated: {truncation_result['returned_rows']}/{total_rows} rows. "
            f"Add LIMIT to your query for precise control."
        )
    else:
        await ctx.info(f"Query returned {total_rows} rows")
    
    return {
        "success": True,
        "data": truncation_result["data"],
        "row_count": truncation_result["returned_rows"],
        "total_rows": total_rows,
        "truncated": truncation_result["truncated"],
        "truncation_note": (
            f"Showing {truncation_result['returned_rows']}/{total_rows} rows. "
            f"Use LIMIT clause for full control."
        ) if truncation_result["truncated"] else None,
        "query": sql
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check Database Connection",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def check_connection(ctx: Context) -> dict[str, Any]:
    """
    Check if the database connection is working.

    Use this to verify database connectivity before running queries.

    Returns:
        Connection status, database type, and configuration check
    """
    await ctx.info("Checking database connection...")
    
    adapter = get_adapter()
    success, message = adapter.check_connection()
    
    if not success:
        await ctx.error(f"Connection failed: {message}")
        
        # Return appropriate config hints based on database type
        if DB_TYPE == "sqlite":
            return {
                "connected": False,
                "error": message,
                "db_type": "sqlite",
                "config": {
                    "SQLITE_DATABASE_PATH": "set" if os.getenv("SQLITE_DATABASE_PATH") else "missing (using :memory:)",
                }
            }
        else:  # mysql
            return {
                "connected": False,
                "error": message,
                "db_type": "mysql",
                "config": {
                    "DB_USER": "set" if os.getenv("DB_USER") else "missing",
                    "DB_PASSWORD": "set" if os.getenv("DB_PASSWORD") else "missing",
                    "DB_HOST": "set" if os.getenv("DB_HOST") else "missing",
                    "DB_NAME": "set" if os.getenv("DB_NAME") else "missing",
                }
            }
    
    await ctx.info(f"Database connection successful ({DB_TYPE})")
    return {
        "connected": True,
        "message": message,
        "db_type": DB_TYPE,
        "database_name": adapter.get_database_name()
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Database Tables",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def list_tables(ctx: Context) -> dict[str, Any]:
    """
    Database overview: list all tables with names and approximate row counts.
    
    Lightweight initial discovery tool. Row counts are estimates:
    - MySQL: from INFORMATION_SCHEMA (InnoDB may vary ±40%)
    - SQLite: from sqlite_stat1 or sampling
    
    For column details, use describe_table(name).

    Returns:
        Database name, table count, and list of tables with approximate row counts
    """
    await ctx.info("Listing database tables")
    
    adapter = get_adapter()
    database_name = adapter.get_database_name()
    
    # Use adapter method for cross-database compatibility
    tables = adapter.get_tables()
    
    if not tables:
        await ctx.info(f"No tables found in {database_name}")
        return {
            "success": True,
            "database_name": database_name,
            "db_type": DB_TYPE,
            "returned_table_count": 0,
            "total_tables": 0,
            "tables": [],
            "row_count_approximate": True,
            "truncated": False,
            "truncation_note": None,
            "hint": "No tables found in database."
        }
    
    # Filter by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
        original_count = len(tables)
        tables = [t for t in tables if t["table_name"].lower() in ALLOWED_TABLES]
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
    return {
        "success": True,
        "database_name": database_name,
        "db_type": DB_TYPE,
        "returned_table_count": len(tables),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "tables": tables,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(tables)}/{total_tables} tables. Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": f"Row counts are estimates. total_tables = visible after allowlist. DB type: {DB_TYPE}"
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Describe Table Structure",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def describe_table(table_name: str, ctx: Context) -> dict[str, Any]:
    """
    Get table structure: columns, row count estimate, and query hints.
    
    Returns column details plus approximate row count:
    - MySQL: from INFORMATION_SCHEMA (InnoDB ±40% variance)
    - SQLite: from sqlite_stat1 or sampling
    
    Includes is_large flag and recommendations for large tables.

    Args:
        table_name: Name of the table to describe
        
    Returns:
        Table structure with columns, row count, and query recommendations
    """
    # Validate table name to prevent SQL injection
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return {
            "success": False,
            "error": f"Invalid table name: {table_name}"
        }
    
    # Check table allowlist (P1 Security)
    if not _is_table_allowed(table_name):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return {
            "success": False,
            "error": f"Access denied to table: {table_name}"
        }
    
    await ctx.info(f"Describing table: {table_name}")
    
    # Use adapter methods for cross-database compatibility
    adapter = get_adapter()
    
    columns_data = adapter.get_columns(table_name)
    row_count = adapter.get_row_estimate(table_name)
    
    if not columns_data:
        await ctx.error(f"Table not found: {table_name}")
        return {
            "success": False,
            "error": f"Table '{table_name}' not found"
        }
    
    # Determine if table is large (needs LIMIT)
    is_large = row_count > LARGE_TABLE_THRESHOLD
    
    await ctx.info(f"Table {table_name}: ~{row_count} rows, {len(columns_data)} columns")
    
    # Build response with query recommendations
    result = {
        "success": True,
        "table_name": table_name,
        "db_type": DB_TYPE,
        "row_count": row_count,
        "row_count_approximate": True,
        "column_count": len(columns_data),
        "columns": columns_data,
        "is_large": is_large,
    }
    
    # Add recommendation only for large tables (reduce token overhead)
    if is_large:
        result["recommendation"] = (
            f"Large table (~{row_count} rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
        )
    
    return result


# =============================================================================
# Schema Caching Tools (Microsoft Best Practices: Reduce repeated tool calls)
# Reference: "Too many tools in the same agent can have negative effect on agent quality"
# =============================================================================

@mcp.tool(
    annotations=ToolAnnotations(
        title="Get Full Database Schema",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_full_schema(ctx: Context) -> dict[str, Any]:
    """
    Get complete database schema (all tables and columns) in one call.
    
    Best for: exploring unknown databases, multi-table queries, or complex JOINs.
    
    Works with both MySQL and SQLite databases.

    Returns:
        Complete schema with all tables and their column definitions
    """
    await ctx.info("Fetching complete database schema...")
    
    adapter = get_adapter()
    
    # Step 1: Get all tables with row counts using adapter
    tables_data = adapter.get_tables()
    
    if not tables_data:
        await ctx.info("No tables found in database")
        return {
            "success": True,
            "schema": {},
            "db_type": DB_TYPE,
            "returned_table_count": 0,
            "total_tables": 0,
            "total_columns": 0,
            "row_count_approximate": True,
            "truncated": False,
            "truncation_note": None,
            "hint": "No tables found in database."
        }
    
    # Filter tables by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
        tables_data = [t for t in tables_data if t["table_name"].lower() in ALLOWED_TABLES]
        await ctx.info(f"Allowlist active: showing {len(tables_data)} allowed tables")
    
    # Step 2: Apply truncation to prevent token overflow (P0 security/performance)
    # Reference: Google Gemini best practices - token limits
    total_tables = len(tables_data)
    truncated = False
    
    if MAX_SCHEMA_TABLES > 0 and total_tables > MAX_SCHEMA_TABLES:
        tables_data = tables_data[:MAX_SCHEMA_TABLES]
        truncated = True
        await ctx.warning(f"Schema truncated: showing {MAX_SCHEMA_TABLES}/{total_tables} tables")
    
    # Step 3: Get columns for each table and organize into structured schema
    schema = {}
    for table in tables_data:
        table_name = table["table_name"]
        columns_data = adapter.get_columns(table_name)
        
        schema[table_name] = {
            "row_count": table["row_count"],
            "columns": [
                {
                    "name": col["column_name"],
                    "type": col["data_type"],
                    "nullable": col["nullable"],
                    "key": col["key_type"]
                }
                for col in columns_data
            ]
        }
    
    total_columns_shown = sum(len(t["columns"]) for t in schema.values())
    await ctx.info(f"Schema loaded: {len(schema)} tables, {total_columns_shown} columns")
    
    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    return {
        "success": True,
        "schema": schema,
        "db_type": DB_TYPE,
        "returned_table_count": len(schema),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "total_columns": total_columns_shown,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(schema)}/{total_tables} tables. Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": f"Row counts are estimates. Use LIMIT for large tables (row_count > {LARGE_TABLE_THRESHOLD}). total_tables = visible after allowlist. DB type: {DB_TYPE}"
    }


# Optional tool: get_table_summary with exact COUNT(*) option
# Default: disabled - describe_table already provides estimated row_count
# Enable via ENABLE_TABLE_SUMMARY=1 when exact counts are needed
if TABLE_SUMMARY_ENABLED:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Table Summary with Exact Count",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def get_table_summary(
        table_name: str, 
        ctx: Context, 
        exact_count: bool = False
    ) -> dict[str, Any]:
        """
        Table statistics with optional exact row count.
        
        WARNING: exact_count=True runs COUNT(*) which may be slow on large InnoDB tables
        (full table scan, potential MDL contention). Use only when precision is required.
        
        Default: Uses INFORMATION_SCHEMA estimate (fast, ~40% variance for InnoDB).
        
        Args:
            table_name: Name of the table
            exact_count: If True, run COUNT(*) for precise count (slow on large tables)
            
        Returns:
            Table statistics with row count, columns, and query hints
        """
        # Validate table name
        if not _is_valid_identifier(table_name):
            await ctx.warning(f"Invalid table name rejected: {table_name}")
            return {"success": False, "error": f"Invalid table name: {table_name}"}
        
        # Check table allowlist (P1 Security)
        if not _is_table_allowed(table_name):
            await ctx.warning(f"Table access denied by allowlist: {table_name}")
            return {"success": False, "error": f"Access denied to table: {table_name}"}
        
        await ctx.info(f"Getting summary for table: {table_name} (exact_count={exact_count})")
        
        adapter = get_adapter()
        
        # Get row count — use adapter for cross-database compatibility
        row_count_approximate = True
        if exact_count:
            # WARNING: COUNT(*) can be slow on large InnoDB tables
            row_count_approximate = False
            await ctx.warning(f"Running COUNT(*) on {table_name} - may be slow on large tables")
            quote = '`' if adapter.db_type == 'mysql' else '"'
            count_sql = f"SELECT COUNT(*) as total_rows FROM {quote}{table_name}{quote}"
            count_result = execute_sql(count_sql)
            if isinstance(count_result, str) and count_result.startswith("Error:"):
                await ctx.error(f"Failed to count rows: {count_result}")
                return {"success": False, "error": count_result}
            count_data = _serialize_result(count_result)
            total_rows = count_data[0]["total_rows"] if count_data else 0
            total_rows = total_rows or 0
        else:
            # Fast estimate via adapter (uses INFORMATION_SCHEMA or sqlite_stat1)
            total_rows = adapter.get_row_estimate(table_name)
        
        # Get column info via adapter (cross-database)
        columns_data = adapter.get_columns(table_name)
        
        # Determine if table is large
        is_large = total_rows > LARGE_TABLE_THRESHOLD
        
        await ctx.info(f"Table {table_name}: {'~' if row_count_approximate else ''}{total_rows} rows, {len(columns_data)} columns")
        
        result = {
            "success": True,
            "table_name": table_name,
            "row_count": total_rows,
            "row_count_approximate": row_count_approximate,
            "column_count": len(columns_data),
            "columns": columns_data,
            "is_large": is_large,
        }
        
        if is_large:
            result["recommendation"] = (
                f"Large table ({'~' if row_count_approximate else ''}{total_rows} rows). "
                "Use LIMIT or aggregation (COUNT/GROUP BY)."
            )
        
        return result


# Optional tool: Only register if enabled
if SCHEMA_TOOLS_ENABLED:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Sample Table Data",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def sample(table_name: str, ctx: Context, limit: int = 5) -> dict[str, Any]:
        """
        Get sample rows from a table to preview its data.
        
        Args:
            table_name: Name of the table to sample
            limit: Number of rows to return (max 20)
            
        Returns:
            Sample rows from the table
        """
        # Validate inputs
        if not _is_valid_identifier(table_name):
            await ctx.warning(f"Invalid table name rejected: {table_name}")
            return {
                "success": False,
                "error": f"Invalid table name: {table_name}"
            }
        
        # Check table allowlist (P1 Security)
        if not _is_table_allowed(table_name):
            await ctx.warning(f"Table access denied by allowlist: {table_name}")
            return {
                "success": False,
                "error": f"Access denied to table: {table_name}"
            }
        
        limit = min(max(1, limit), 20)  # Clamp between 1-20
        
        await ctx.info(f"Sampling {limit} rows from: {table_name}")
        
        # Use adapter-compatible quoting (backticks for MySQL, double-quotes for SQLite)
        adapter = get_adapter()
        quote = '`' if adapter.db_type == 'mysql' else '"'
        sql = f"SELECT * FROM {quote}{table_name}{quote} LIMIT {limit}"
        result = execute_sql(sql)
        
        if isinstance(result, str) and result.startswith("Error:"):
            await ctx.error(f"Failed to sample table: {result}")
            return {"success": False, "error": result}
        
        data = _serialize_result(result)
        
        return {
            "success": True,
            "table_name": table_name,
            "data": data,
            "row_count": len(data),
            "query": sql
        }


# =============================================================================
# Skills Extension Layer (v3.0) — Conditional registration
# Reference: FastMCP Component Visibility — disabled tools don't appear in list_tools
# Reference: Google Gemini — keep effective tool set within 10-20
# =============================================================================

# Pre-initialize path variables so Pylance sees them as always-bound.
# Values are only meaningful when SKILLS_ENABLED=True.
_project_root = Path(__file__).parent.resolve()
_skills_dir = _project_root / SKILLS_DIR

if SKILLS_ENABLED:
    # Resolve skills directory with path safety check
    _skills_dir = Path(SKILLS_DIR)
    if not _skills_dir.is_absolute():
        _skills_dir = _project_root / _skills_dir
    _skills_dir = _skills_dir.resolve()

    # Security: SKILLS_DIR must be within project root (prevent .env poisoning)
    # Reference: SAFETY.md #15
    if not str(_skills_dir).startswith(str(_project_root)):
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
    _discovered_skills = discover(_skills_dir)
    _audit_logger = AuditLogger()

    # Generate SKILLS.md overview for human review
    if _discovered_skills:
        generate_skills_md(_discovered_skills, _skills_dir / "SKILLS.md")

    logger.info(
        f"Skills extension enabled: {len(_discovered_skills)} skill(s) discovered"
    )

    # ── list_skills ──
    @mcp.tool(
        annotations=ToolAnnotations(
            title="List Available Skills",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def list_skills(ctx: Context) -> dict[str, Any]:
        """
        List all available pre-defined skills (query and mutation).

        Returns skill metadata for progressive disclosure:
        Level 1 (this tool) — name, type, risk, description, triggers.
        Level 2 — Read skill's skill_def.md for full documentation.
        Level 3 — skill source file (code review, declared in skill_def.md 'source' field).

        Returns:
            Dict with skills list and count
        """
        await ctx.info("Listing available skills")

        skills = get_skills_cache()
        skills_list = []
        for name in sorted(skills.keys()):
            meta = skills[name]
            skill_info = {
                "name": meta.name,
                "type": meta.type,
                "source": meta.source,
                "risk": meta.risk,
                "description": meta.description,
                "triggers": meta.triggers,
                "category": meta.category,
                "idempotent": meta.idempotent,
            }
            if meta.related_skills:
                skill_info["related_skills"] = meta.related_skills
            skills_list.append(skill_info)

        query_count = sum(1 for s in skills.values() if s.type == "query")
        mutation_count = sum(1 for s in skills.values() if s.type == "mutation")

        await ctx.info(
            f"Found {len(skills_list)} skill(s): "
            f"{query_count} query, {mutation_count} mutation"
        )

        return {
            "success": True,
            "skills": skills_list,
            "total_skills": len(skills_list),
            "query_skills": query_count,
            "mutation_skills": mutation_count,
            "mutations_enabled": SKILLS_ALLOW_MUTATIONS,
        }

    # ── execute_query_skill ──
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Execute Query Skill",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def execute_query_skill(
        skill_name: Annotated[str, Field(description="Name of the query skill to execute")],
        params: Annotated[dict[str, Any], Field(description="Parameters for the skill (must match skill_def.md schema)")],
        ctx: Context,
    ) -> dict[str, Any]:
        """
        Execute a pre-defined query skill with parameterized SQL.

        Skills are pre-audited SQL templates — bypasses runtime is_sql_safe() and
        ALLOWED_TABLES checks (security comes from code review, see SAFETY.md #1 & #14).

        Uses named parameters (:param_name) via SQLAlchemy text() for SQL injection prevention.

        Args:
            skill_name: The skill name (e.g., "monthly-sales-report")
            params: Parameter dict matching the skill's frontmatter schema

        Returns:
            Query results (same format as query() tool, plus skill_name)
        """
        await ctx.info(f"Executing query skill: {skill_name}")

        try:
            validate_name(skill_name)
            sql_template, param_schema = load_query(skill_name)
            validated_params = validate_params(params, param_schema)
        except (ValueError, TypeError, FileNotFoundError) as e:
            await ctx.warning(f"Query skill error: {e}")
            raise ToolError(str(e)) from e

        # Execute parameterized query via adapter (Step 3a: params support)
        adapter = get_adapter()
        result = adapter.execute(sql_template, params=validated_params)

        # Handle error (adapter returns error string on failure)
        if isinstance(result, str) and result.startswith("Error:"):
            await ctx.error(f"Query skill failed: {result}")
            raise ToolError(result)

        # Success — serialize and truncate (reuse existing helpers)
        data = _serialize_result(result)
        total_rows = len(result) if isinstance(result, list) else 0

        truncation_result = _truncate_result(data, total_rows)

        if truncation_result["truncated"]:
            await ctx.warning(
                f"Truncated: {truncation_result['returned_rows']}/{total_rows} rows."
            )
        else:
            await ctx.info(f"Query skill returned {total_rows} rows")

        return {
            "success": True,
            "skill_name": skill_name,
            "data": truncation_result["data"],
            "row_count": truncation_result["returned_rows"],
            "total_rows": total_rows,
            "truncated": truncation_result["truncated"],
            "truncation_note": (
                f"Showing {truncation_result['returned_rows']}/{total_rows} rows. "
                f"Use LIMIT clause for full control."
            ) if truncation_result["truncated"] else None,
        }

    # ── execute_mutation_skill (second switch) ──
    if SKILLS_ALLOW_MUTATIONS:
        @mcp.tool(
            annotations=ToolAnnotations(
                title="Execute Mutation Skill",
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,  # Conservative default; per-skill idempotent
                                       # info is conveyed via list_skills() and result dict
            )
        )
        async def execute_mutation_skill(
            skill_name: Annotated[str, Field(description="Name of the mutation skill to execute")],
            params: Annotated[dict[str, Any], Field(description="Parameters for the skill (must match skill_def.md schema)")],
            ctx: Context,
            confirm: Annotated[bool, Field(description="False=preview (default), True=execute")] = False,
        ) -> dict[str, Any]:
            """
            Execute a pre-defined mutation (write) skill.

            Two-phase workflow (Anthropic plan-validate-execute pattern):
            1. confirm=false (default) — validate + preview, no database changes
            2. confirm=true — validate + execute, commits changes in a transaction

            Args:
                skill_name: The mutation skill name (e.g., "update-order-status")
                params: Parameter dict matching the skill's frontmatter schema
                confirm: False=dry-run preview (default), True=actual execution

            Returns:
                Preview result (confirm=false) or execution result (confirm=true)
            """
            mode = "execute" if confirm else "preview"
            await ctx.info(f"Mutation skill '{skill_name}' mode={mode}")

            # Get client_id for audit logging (FastMCP Context provides this)
            client_id = None
            try:
                client_id = ctx.client_id
            except Exception:
                pass  # client_id is optional, fall back to env var in AuditLogger

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
                validated_params = validate_params(params, meta.params)

                # Load mutation module
                adapter = get_adapter()
                mutation = load_mutation(skill_name, adapter, _audit_logger)

            except (ValueError, TypeError, FileNotFoundError, AttributeError,
                    ImportError, SyntaxError) as e:
                await ctx.warning(f"Mutation skill setup error: {e}")
                raise ToolError(str(e)) from e

            if not confirm:
                # Phase 1: validate + preview (no writes)
                try:
                    validation = mutation.validate(validated_params)
                    if not validation.get("valid", False):
                        errors = validation.get("errors", ["Validation failed"])
                        await ctx.warning(f"Validation failed: {errors}")
                        return {
                            "success": False,
                            "skill_name": skill_name,
                            "mode": "preview",
                            "validation": validation,
                        }

                    preview_result = mutation.preview(validated_params)

                    # Audit the preview
                    _audit_logger.log(
                        skill_name=skill_name,
                        params=validated_params,
                        mode="preview",
                        result={"success": True, "preview": True},
                        client_id=client_id,
                    )

                    await ctx.info(f"Preview completed for '{skill_name}'")
                    return {
                        "success": True,
                        "skill_name": skill_name,
                        "mode": "preview",
                        "preview": preview_result,
                        "idempotent": meta.idempotent,
                        "hint": "Set confirm=true to execute this operation.",
                    }
                except ToolError:
                    raise
                except Exception as e:
                    sanitized = adapter._handle_error(e)
                    raise ToolError(sanitized) from e
            else:
                # Phase 2: validate + execute (commits to database)
                try:
                    validation = mutation.validate(validated_params)
                    if not validation.get("valid", False):
                        errors = validation.get("errors", ["Validation failed"])
                        await ctx.warning(f"Validation failed: {errors}")
                        return {
                            "success": False,
                            "skill_name": skill_name,
                            "mode": "execute",
                            "validation": validation,
                        }

                    result = mutation.run_execute(
                        validated_params,
                        skill_name=skill_name,
                        mode="execute",
                    )

                    await ctx.info(
                        f"Mutation '{skill_name}' executed: rowcount={result.get('rowcount')}"
                    )
                    return {
                        "success": True,
                        "skill_name": skill_name,
                        "mode": "execute",
                        "result": result,
                        "idempotent": meta.idempotent,
                    }
                except ToolError:
                    raise
                except Exception as e:
                    sanitized = adapter._handle_error(e)
                    _audit_logger.log(
                        skill_name=skill_name,
                        params=validated_params,
                        mode="execute",
                        result={"success": False, "error": sanitized},
                        client_id=client_id,
                    )
                    raise ToolError(sanitized) from e

        logger.info("Mutation skills enabled (SKILLS_ALLOW_MUTATIONS=1)")
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
    # Build dynamic prompt based on configuration
    # Reference: Microsoft prompt engineering - clear, structured, avoid unnecessary steps
    # Reference: MCP spec - model-driven tool selection, provide decision rules not fixed paths
    if ALLOW_UNION and ALLOWED_TABLES:
        if "*" in ALLOWED_TABLES:
            cross_table = "UNION supported for combining results."
        else:
            tables_desc = ', '.join(sorted(ALLOWED_TABLES))
            cross_table = f"UNION allowed for: {tables_desc}."
    else:
        cross_table = "Query tables separately."

    # Skills extension info for prompt
    skills_info = ""
    if SKILLS_ENABLED:
        skills_info = """
- list_skills(): List pre-defined query/mutation skills
- execute_query_skill(name, params): Execute a query skill with parameters
"""
        if SKILLS_ALLOW_MUTATIONS:
            skills_info += "- execute_mutation_skill(name, params, confirm): Execute a mutation skill (confirm=false for preview)\n"

    # Conditional heuristic prompt - let LLM decide based on context
    # Reference: "Model-driven tool selection" - provide rules, not fixed chains
    return f"""Database query assistant.

Tools (choose based on need):
- query(sql): Execute SELECT/SHOW/DESCRIBE/EXPLAIN
- list_tables(): Database overview with table names and row estimates
- describe_table(name): Single table columns + row estimate + is_large hint
- get_full_schema(): All tables with columns (use for multi-table JOINs)
- check_connection(): Verify database connectivity (use only on connection errors)
{skills_info}
Decision rules:
- Unknown structure? list_tables() for overview, then describe_table() for details
- For single-table queries, if schema/columns unknown, call describe_table(table_name) before query().
- Know the table? Query directly with appropriate LIMIT
- is_large=true in response? Use LIMIT or aggregation
- {cross_table}

Always include SQL in response."""
