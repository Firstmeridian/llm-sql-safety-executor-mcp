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
mcp = FastMCP(
    name="sql-db",
    instructions="""You are a database query assistant with READ-ONLY access.
Use the query tool for most operations. Only SELECT statements are allowed.
Use list_tables first if you don't know the database structure.""",
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
    """Validate table/column name to prevent SQL injection."""
    # Allow alphanumeric, underscore, and Chinese characters
    return bool(re.match(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff]*$', name))


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
    Safety validation is automatic - only SELECT statements are allowed.
    
    Args:
        sql: A SQL SELECT query to execute
        
    Returns:
        Query results with data rows, or error message if query fails
        
    Examples:
        query("SELECT * FROM users LIMIT 10")
        query("SELECT name, email FROM users WHERE active = 1")
        query("SELECT COUNT(*) as total FROM orders")
        query("SELECT * FROM products WHERE name LIKE '%phone%'")
    """
    await ctx.info(f"Executing query: {sql}")
    
    # Validate safety
    if not is_sql_safe(sql):
        await ctx.warning(f"Rejected unsafe query: {sql}")
        return {
            "success": False,
            "error": "Only SELECT queries are allowed",
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
    
    # Success
    data = _serialize_result(result)
    row_count = len(result) if isinstance(result, list) else 0
    await ctx.info(f"Query returned {row_count} rows")
    
    return {
        "success": True,
        "data": data,
        "row_count": row_count,
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
    
    Use this FIRST if you don't know the database structure.
    
    Returns:
        List of tables with their names and approximate row counts
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
    Get column information for a specific table.
    
    Use this to understand table structure before writing queries.
    
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
    return """You are a database query assistant with READ-ONLY access.

TOOL USAGE (in order of preference):
1. query(sql) - Execute any SELECT query. This is your PRIMARY tool.
2. list_tables() - See available tables (use first if unsure)
3. describe_table(name) - See table columns before complex queries
4. sample(table, limit) - Preview table data

WORKFLOW:
- For simple queries: Use query() directly
- For unknown tables: list_tables() -> describe_table() -> query()
- Always show the SQL you executed in your response

RULES:
- Only SELECT statements allowed (enforced automatically)
- Be helpful and explain results clearly
- Format results in readable tables when appropriate"""
