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

# Token optimization: Limit result size to prevent context overflow
# Reference: Google Gemini best practices - "Token limits: function descriptions and parameters count toward input token limits"
# Reference: MCP Security best practices - "Sanitize tool outputs"
# Set to 0 to disable truncation (for data export scenarios)
MAX_RESULT_ROWS = int(os.getenv("MAX_RESULT_ROWS", "100"))  # Max rows (0=unlimited)
MAX_RESULT_CHARS = int(os.getenv("MAX_RESULT_CHARS", "16000"))  # Max chars (0=unlimited)
MAX_SCHEMA_TABLES = int(os.getenv("MAX_SCHEMA_TABLES", "50"))  # Max tables in get_full_schema

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
    List all tables in the database with row counts.
    
    Lightweight option for table discovery. Returns names and row counts only.
    For columns, use get_full_schema() or describe_table().

    Returns:
        List of tables with names and approximate row counts
    """
    await ctx.info("Listing database tables")
    
    sql = """
        SELECT TABLE_NAME as table_name, TABLE_ROWS as row_count
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """
    
    result = execute_sql(sql)
    
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Failed to list tables: {result}")
        return {"success": False, "error": result}
    
    data = _serialize_result(result)
    
    # Filter by allowlist if configured (P1 Security)
    # Skip filtering if ALLOWED_TABLES=* (explicit allow all)
    if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
        original_count = len(data)
        data = [t for t in data if t["table_name"].lower() in ALLOWED_TABLES]
        if len(data) < original_count:
            await ctx.info(f"Filtered {original_count - len(data)} tables by allowlist")
    
    await ctx.info(f"Found {len(data)} tables")
    
    return {
        "success": True,
        "data": data,
        "table_count": len(data)
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
    Get column details for a single table.
    
    Best for: querying 1-2 specific tables where you know the names.
    Alternative: get_full_schema() returns all tables in one call.

    Args:
        table_name: Name of the table to describe
        
    Returns:
        List of columns with their data types and properties
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
    
    sql = f"""
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
    
    result = execute_sql(sql)
    
    if isinstance(result, str) and result.startswith("Error:"):
        await ctx.error(f"Failed to describe table: {result}")
        return {"success": False, "error": result}
    
    data = _serialize_result(result)
    
    if not data:
        return {
            "success": False,
            "error": f"Table '{table_name}' not found"
        }
    
    await ctx.info(f"Table {table_name} has {len(data)} columns")
    
    return {
        "success": True,
        "table_name": table_name,
        "columns": data,
        "column_count": len(data)
    }


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
    
    result = {
        "success": True,
        "schema": schema,
        "table_count": len(schema),
        "total_columns": total_columns_shown,
        "hint": "Use this schema info to construct queries. For large tables (row_count > 100), use LIMIT or aggregation."
    }
    
    # Add truncation notice if applicable
    if truncated:
        result["truncated"] = True
        result["truncation_note"] = f"Showing {MAX_SCHEMA_TABLES}/{total_tables} tables. Use describe_table(table_name) for specific tables not shown."
    
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get Table Summary Statistics",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_table_summary(table_name: str, ctx: Context) -> dict[str, Any]:
    """
    Quick table statistics without fetching data.
    
    Returns: row count, column list, and basic stats.
    Best for: checking table size before large queries.
    
    Args:
        table_name: Name of the table to summarize
        
    Returns:
        Table statistics including row count and column info
    """
    # Validate table name
    if not _is_valid_identifier(table_name):
        await ctx.warning(f"Invalid table name rejected: {table_name}")
        return {"success": False, "error": f"Invalid table name: {table_name}"}
    
    # Check table allowlist (P1 Security)
    if not _is_table_allowed(table_name):
        await ctx.warning(f"Table access denied by allowlist: {table_name}")
        return {"success": False, "error": f"Access denied to table: {table_name}"}
    
    await ctx.info(f"Getting summary for table: {table_name}")
    
    # Get row count
    count_sql = f"SELECT COUNT(*) as total_rows FROM `{table_name}`"
    count_result = execute_sql(count_sql)
    
    if isinstance(count_result, str) and count_result.startswith("Error:"):
        await ctx.error(f"Failed to count rows: {count_result}")
        return {"success": False, "error": count_result}
    
    count_data = _serialize_result(count_result)
    total_rows = count_data[0]["total_rows"] if count_data else 0
    
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
    
    # Determine if table is large (needs LIMIT)
    is_large = total_rows > 100
    
    await ctx.info(f"Table {table_name}: {total_rows} rows, {len(columns_data)} columns")
    
    return {
        "success": True,
        "table_name": table_name,
        "total_rows": total_rows,
        "column_count": len(columns_data),
        "columns": columns_data,
        "is_large": is_large,
        "recommendation": (
            f"Table has {total_rows} rows. Use 'SELECT ... LIMIT 10' for samples, "
            "or aggregation queries (COUNT, GROUP BY) for analysis."
        ) if is_large else f"Table has {total_rows} rows. Safe to query directly with LIMIT."
    }


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
    # Build dynamic prompt based on UNION policy
    # Reference: Anthropic/OpenAI best practices - provide clear guidance, let LLM decide
    if ALLOW_UNION and ALLOWED_TABLES:
        if "*" in ALLOWED_TABLES:
            cross_table = "UNION supported for combining results from multiple tables."
        else:
            tables_desc = ', '.join(sorted(ALLOWED_TABLES))
            cross_table = f"UNION supported (allowed tables: {tables_desc})."
    else:
        cross_table = "Query tables separately and combine results in response."
    
    return f"""READ-ONLY SQL assistant.

Start: get_full_schema() or describe_table() for unknown databases.
Query:
1. Query with LIMIT for large tables
2. Prefer COUNT/GROUP BY over SELECT *

Tools:
- query(sql): Execute SELECT, SHOW, DESCRIBE, EXPLAIN
- get_full_schema(): All tables and columns in one call
- describe_table(name): Single table details
- list_tables(): Table names and row counts only
- get_table_summary(name): Row count and columns for one table

Rules:
- {cross_table}
- Always show SQL in response."""
