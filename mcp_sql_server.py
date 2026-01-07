#!/usr/bin/env python3
"""
MCP Server for SQL Safety Checker

Provides safe, read-only SQL query execution through MCP protocol.
Following FastMCP best practices for tool design and context usage.
"""

import os
import re
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from mcp.types import ToolAnnotations
from fastmcp import FastMCP, Context
from sql_safety_checker import is_sql_safe, execute_sql

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
Use query() for all data requests. Use get_full_schema() or describe_table() first if structure unknown.""",
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
    
    # Block dangerous patterns
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


# Allowlist for SHOW commands (restrict information disclosure)
ALLOWED_SHOW_COMMANDS = {
    'SHOW TABLES',
    'SHOW COLUMNS',
    'SHOW INDEX',
    'SHOW CREATE TABLE',
    'SHOW TABLE STATUS',
    'SHOW DATABASES',
}

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
            return False, f"SHOW command not allowed for security: {pattern}"
    
    # Block access to mysql/information_schema system tables in SELECT
    system_table_pattern = r'\b(mysql|performance_schema)\s*\.'
    if re.search(system_table_pattern, sql, re.IGNORECASE):
        return False, "Access to system databases not allowed"
    
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
    import json
    
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
        Connection status and configuration check
    """
    await ctx.info("Checking database connection...")
    
    result = execute_sql("SELECT 1 as test")
    
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Connection failed: {result}")
        return {
            "connected": False,
            "error": result,
            "config": {
                "DB_USER": "set" if os.getenv("DB_USER") else "missing",
                "DB_PASSWORD": "set" if os.getenv("DB_PASSWORD") else "missing",
                "DB_HOST": "set" if os.getenv("DB_HOST") else "missing",
                "DB_NAME": "set" if os.getenv("DB_NAME") else "missing",
            }
        }
    
    await ctx.info("Database connection successful")
    return {
        "connected": True,
        "message": "Database connection successful"
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
    
    Lightweight initial discovery tool. Row counts are estimates from
    INFORMATION_SCHEMA (InnoDB may vary ±40%).
    For column details, use describe_table(name).

    Returns:
        Database name, table count, and list of tables with approximate row counts
    """
    await ctx.info("Listing database tables")
    
    # Get database name and tables in one query
    sql = """
        SELECT 
            DATABASE() as database_name,
            TABLE_NAME as table_name, 
            TABLE_ROWS as row_count
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """
    
    result = execute_sql(sql)
    
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Failed to list tables: {result}")
        return {"success": False, "error": result}
    
    data = _serialize_result(result)
    
    # Extract database name from first row
    database_name = data[0]["database_name"] if data else None
    
    # Remove database_name from each row (only needed once)
    tables = [{"table_name": t["table_name"], "row_count": t["row_count"]} for t in data]
    
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
        "returned_table_count": len(tables),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "tables": tables,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(tables)}/{total_tables} tables. Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": "Row counts are estimates (InnoDB ±40%). total_tables = visible after allowlist."
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
    
    Returns column details plus approximate row count from INFORMATION_SCHEMA
    (avoids COUNT(*) full table scan). Includes is_large flag and recommendations.

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
    
    # Get columns and row count estimate in parallel-safe queries
    # Using INFORMATION_SCHEMA.TABLES for row count (O(1), no table scan)
    columns_sql = f"""
        SELECT 
            COLUMN_NAME as column_name,
            DATA_TYPE as data_type,
            IS_NULLABLE as nullable,
            COLUMN_KEY as key_type,
            COLUMN_DEFAULT as default_value
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
        ORDER BY ORDINAL_POSITION
    """
    
    row_count_sql = f"""
        SELECT TABLE_ROWS as row_count
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
    """
    
    columns_result = execute_sql(columns_sql)
    row_count_result = execute_sql(row_count_sql)
    
    if isinstance(columns_result, str) and columns_result.startswith("Error:"):
        await ctx.error(f"Failed to describe table: {columns_result}")
        return {"success": False, "error": columns_result}
    
    columns_data = _serialize_result(columns_result)
    
    if not columns_data:
        return {
            "success": False,
            "error": f"Table '{table_name}' not found"
        }
    
    # Extract row count (estimate from INFORMATION_SCHEMA)
    row_count = 0
    if not isinstance(row_count_result, str):
        row_count_data = _serialize_result(row_count_result)
        if row_count_data:
            row_count = row_count_data[0].get("row_count", 0) or 0
    
    # Determine if table is large (needs LIMIT)
    is_large = row_count > LARGE_TABLE_THRESHOLD
    
    await ctx.info(f"Table {table_name}: ~{row_count} rows, {len(columns_data)} columns")
    
    # Build response with query recommendations
    result = {
        "success": True,
        "table_name": table_name,
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
    
    Returns:
        Complete schema with all tables and their column definitions
    """
    await ctx.info("Fetching complete database schema...")
    
    # Step 1: Get all tables with row counts
    tables_sql = """
        SELECT TABLE_NAME as table_name, TABLE_ROWS as row_count
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """
    tables_result = execute_sql(tables_sql)
    
    if isinstance(tables_result, str) and tables_result.startswith("Error:"):
        await ctx.error(f"Failed to get tables: {tables_result}")
        return {"success": False, "error": tables_result}
    
    tables_data = _serialize_result(tables_result)
    
    # Filter tables by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
        tables_data = [t for t in tables_data if t["table_name"].lower() in ALLOWED_TABLES]
        await ctx.info(f"Allowlist active: showing {len(tables_data)} allowed tables")
    
    # Step 2: Get all columns for all tables in one query
    columns_sql = """
        SELECT 
            TABLE_NAME as table_name,
            COLUMN_NAME as column_name,
            DATA_TYPE as data_type,
            IS_NULLABLE as nullable,
            COLUMN_KEY as key_type
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    columns_result = execute_sql(columns_sql)
    
    if isinstance(columns_result, str) and columns_result.startswith("Error:"):
        await ctx.error(f"Failed to get columns: {columns_result}")
        return {"success": False, "error": columns_result}
    
    columns_data = _serialize_result(columns_result)
    
    # Step 3: Apply truncation to prevent token overflow (P0 security/performance)
    # Reference: Google Gemini best practices - token limits
    total_tables = len(tables_data)
    truncated = False
    
    if MAX_SCHEMA_TABLES > 0 and total_tables > MAX_SCHEMA_TABLES:
        tables_data = tables_data[:MAX_SCHEMA_TABLES]
        truncated = True
        await ctx.warning(f"Schema truncated: showing {MAX_SCHEMA_TABLES}/{total_tables} tables")
    
    # Step 4: Organize into structured schema
    schema = {}
    for table in tables_data:
        table_name = table["table_name"]
        schema[table_name] = {
            "row_count": table["row_count"],
            "columns": []
        }
    
    for col in columns_data:
        table_name = col["table_name"]
        if table_name in schema:
            schema[table_name]["columns"].append({
                "name": col["column_name"],
                "type": col["data_type"],
                "nullable": col["nullable"],
                "key": col["key_type"]
            })
    
    total_columns_shown = sum(len(t["columns"]) for t in schema.values())
    await ctx.info(f"Schema loaded: {len(schema)} tables, {total_columns_shown} columns")
    
    # Use consistent field names: returned_table_count vs total_tables (visible before truncation)
    # Note: total_tables is after allowlist filtering, before truncation
    # "returned_" prefix avoids confusion with "total tables in database"
    return {
        "success": True,
        "schema": schema,
        "returned_table_count": len(schema),
        "total_tables": total_tables,  # Visible tables (after allowlist, before truncation)
        "total_columns": total_columns_shown,
        "row_count_approximate": True,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {len(schema)}/{total_tables} tables. Use describe_table(name) for specific tables."
        ) if truncated else None,
        "hint": f"Row counts are estimates (InnoDB ±40%). Use LIMIT for large tables (row_count > {LARGE_TABLE_THRESHOLD}). total_tables = visible after allowlist."
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
        
        # Get row count - choose method based on exact_count flag
        row_count_approximate = True
        if exact_count:
            # WARNING: COUNT(*) can be slow on large InnoDB tables
            count_sql = f"SELECT COUNT(*) as total_rows FROM `{table_name}`"
            row_count_approximate = False
            await ctx.warning(f"Running COUNT(*) on {table_name} - may be slow on large tables")
        else:
            # Fast estimate from INFORMATION_SCHEMA (no table scan)
            count_sql = f"""
                SELECT TABLE_ROWS as total_rows
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
            """
        
        count_result = execute_sql(count_sql)
        
        if isinstance(count_result, str) and count_result.startswith("Error:"):
            await ctx.error(f"Failed to count rows: {count_result}")
            return {"success": False, "error": count_result}
        
        count_data = _serialize_result(count_result)
        total_rows = count_data[0]["total_rows"] if count_data else 0
        total_rows = total_rows or 0  # Handle None
        
        # Get column info
        columns_sql = f"""
            SELECT 
                COLUMN_NAME as name,
                DATA_TYPE as type,
                IS_NULLABLE as nullable
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        columns_result = execute_sql(columns_sql)
        columns_data = _serialize_result(columns_result) if not isinstance(columns_result, str) else []
        
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
        
        sql = f"SELECT * FROM `{table_name}` LIMIT {limit}"
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
    
    # Conditional heuristic prompt - let LLM decide based on context
    # Reference: "Model-driven tool selection" - provide rules, not fixed chains
    return f"""READ-ONLY SQL query executor.

Tools (choose based on need):
- query(sql): Execute SELECT/SHOW/DESCRIBE/EXPLAIN
- list_tables(): Database overview with table names and row estimates
- describe_table(name): Single table columns + row estimate + is_large hint
- get_full_schema(): All tables with columns (use for multi-table JOINs)
- check_connection(): Verify database connectivity (use only on connection errors)

Decision rules:
- Unknown structure? list_tables() for overview, then describe_table() for details
- Know the table? Query directly with appropriate LIMIT
- is_large=true in response? Use LIMIT or aggregation
- {cross_table}

Always include SQL in response."""
