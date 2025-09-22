#!/usr/bin/env python3
"""
MCP Server for SQL Safety Checker

This module creates an MCP (Model Context Protocol) server that wraps the SQL safety checker
functionality, allowing AI models to safely validate and execute SQL queries through a
standardized protocol.
"""

import os
import logging
from typing import Any, Dict, List, Union
from fastmcp import FastMCP
from sql_safety_checker import is_sql_safe, execute_sql

# Set up logging
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the MCP server
mcp = FastMCP("SQL Safety Checker")

# 0918 Add system-level orchestration prompt
@mcp.prompt(
    name="system_orchestration",
    description="System-level orchestration: read-only policy and tool call order (validate → execute)"
)
def system_orchestration() -> str:
    # """System-level orchestration: read-only policy and tool call order (validate → execute)"""
    """System-level orchestration for safe SQL usage via MCP tools."""
    logger.info(f"[system_orchestration]: System orchestration initiated.")
    return (
        "You are a SQL safety assistant and must interact with the database exclusively via MCP tools.\n"
        "Rules:\n"
        "1) Read-only access (SELECT only).\n"
        "2) Before any execution, always call validate_sql_query to check the candidate SQL; if unsafe, return reasons and a safe alternative.\n"
        "3) Only if validation passes, call execute_safe_sql to run it.\n"
        "4) Optionally call check_database_connection first to verify connectivity.\n"
        "5) Never generate or execute any DML/DDL (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/TRUNCATE/GRANT/REVOKE, etc.).\n"
        "6) Available tools: validate_sql_query, execute_safe_sql, check_database_connection, get_server_info.\n"
        "When presenting query results, include a brief natural-language explanation and show the actual SQL executed."
    )
# 0917 Add prompt for generating safe SELECT statements
@mcp.prompt(
    name="generate_select_sql",
    description="Turn a natural language request into a single safe SELECT statement (no DML/DDL)"
)
def generate_select_sql(user_request: str, schema: str = "", dialect: str = "mysql") -> str:
    # """Turn a natural language request into a single safe SELECT statement (no DML/DDL)"""
    """Generate one safe, executable SELECT statement from a natural language request."""
    logger.info(f"[generate_select_sql]: Generating SELECT SQL for request: {user_request} with schema: {schema} and dialect: {dialect}")
    return (
        "Task: Generate a single safe, executable SELECT statement from the user request.\n"
        "Requirements:\n"
        "- SELECT only; strictly no DML/DDL;\n"
        "- Explicitly list required columns; avoid SELECT *;\n"
        f"- Use {dialect} syntax;\n"
        + (f"- Choose tables and columns based on the following schema:\n{schema}\n" if schema else "")
        + f"User request: {user_request}\n"
        "Output only the SQL statement itself, with no explanations."
    )

def serialize_result(data: Any) -> Any:
    """
    Convert SQLAlchemy Row objects and other non-serializable types to JSON-serializable format.
    """
    if data is None:
        return None
    
    if isinstance(data, list):
        return [serialize_result(item) for item in data]
    
    # Handle SQLAlchemy Row objects
    if hasattr(data, '_mapping'):
        return dict(data._mapping)
    
    if hasattr(data, '__dict__'):
        # Convert object to dict, excluding private attributes
        return {k: v for k, v in data.__dict__.items() if not k.startswith('_')}
    
    return data

# 0917 Internal helper functions - do not use @mcp.tool() decorator
def _validate_sql_query_internal(sql_query: str) -> Dict[str, Any]:
    """
    Internal validation function - not exposed as MCP tool
    """
    try:
        is_safe = is_sql_safe(sql_query)
        
        return {
            "is_safe": is_safe,
            "query": sql_query,
            "message": "Query is safe for execution" if is_safe else "Query contains unsafe operations (only SELECT statements are allowed)",
            "allowed_operations": ["SELECT"],
            "validation_passed": is_safe
        }
    except Exception as e:
        logger.error(f"Error validating SQL query: {e}")
        return {
            "is_safe": False,
            "query": sql_query,
            "message": f"Validation error: {str(e)}",
            "error": str(e),
            "validation_passed": False
        }
@mcp.tool()
def validate_sql_query(sql_query: str) -> Dict[str, Any]:
    """
    Validates if a SQL query is safe (contains only SELECT statements).
    
    Args:
        sql_query: The SQL query to validate
        
    Returns:
        Dictionary containing validation result and details
    """
    # try:
    #     is_safe = is_sql_safe(sql_query)
        
    #     return {
    #         "is_safe": is_safe,
    #         "query": sql_query,
    #         "message": "Query is safe for execution" if is_safe else "Query contains unsafe operations (only SELECT statements are allowed)",
    #         "allowed_operations": ["SELECT"],
    #         "validation_passed": is_safe
    #     }
    # except Exception as e:
    #     logger.error(f"Error validating SQL query: {e}")
    #     return {
    #         "is_safe": False,
    #         "query": sql_query,
    #         "message": f"Validation error: {str(e)}",
    #         "error": str(e),
    #         "validation_passed": False
    #     }

    logger.info(f"[validate_sql_query_internal]: validating SQL query: {sql_query}")
    return _validate_sql_query_internal(sql_query) # 0917 fix: use internal function to avoid issues

@mcp.tool()
def execute_safe_sql(sql_query: str) -> Dict[str, Any]:
    """
    Executes a SQL query after validating it is safe.
    
    Args:
        sql_query: The SQL query to execute (must be a SELECT statement)
        
    Returns:
        Dictionary containing execution result and metadata
    """
    try:
        # First validate the query
        # 0917 fix: do not use decorator function
        # validation_result = validate_sql_query(sql_query)
        validation_result = _validate_sql_query_internal(sql_query)

        if not validation_result["is_safe"]:
            logger.warning(f"[execute_safe_sql]: SQL query validation failed: {sql_query}")
            return {
                "success": False,
                "query": sql_query,
                "message": validation_result["message"],
                "error": "Query validation failed",
                "data": None
            }
        
        # Execute the query
        result = execute_sql(sql_query)
        
        # Check if result is an error message (string) or actual data (list)
        if isinstance(result, str) and result.startswith("Error:"):
            logger.error(f"[execute_safe_sql]: SQL execution error: {result}")
            return {
                "success": False,
                "query": sql_query,
                "message": result,
                "error": result,
                "data": None
            }
        
        # Serialize the result for JSON compatibility
        serialized_data = serialize_result(result)

        logger.info(f"[execute_safe_sql]: SQL query executed successfully: {sql_query} with {len(serialized_data) if isinstance(serialized_data, list) else 0} rows returned.")
        return {
            "success": True,
            "query": sql_query,
            "message": "Query executed successfully",
            "data": serialized_data,
            "row_count": len(result) if isinstance(result, list) else 0
        }
        
    except Exception as e:
        logger.error(f"[execute_safe_sql]: Error executing SQL query: {e}")
        return {
            "success": False,
            "query": sql_query,
            "message": f"Execution error: {str(e)}",
            "error": str(e),
            "data": None
        }

@mcp.tool()
def get_server_info() -> Dict[str, Any]:
    """
    Returns information about the SQL Safety Checker MCP server.
    
    Returns:
        Dictionary containing server information and capabilities
    """
    logger.info(f"[get_server_info]: retrieving server information")
    return {
        "name": "SQL Safety Checker MCP Server",
        "version": "1.0.0",
        "description": "MCP server that provides safe SQL query validation and execution",
        "capabilities": [
            "SQL query validation (SELECT-only)",
            "Safe SQL query execution",
            "Database connection pooling via SQLAlchemy",
            "MySQL database support"
        ],
        "supported_databases": ["MySQL"],
        "safety_features": [
            "Only SELECT statements allowed",
            "SQL parsing validation",
            "Connection pooling",
            "Error handling and reporting"
        ],
        "required_environment": [
            "DB_USER",
            "DB_PASSWORD", 
            "DB_HOST",
            "DB_NAME"
        ]
    }

@mcp.tool()
def check_database_connection() -> Dict[str, Any]:
    """
    Checks if the database connection is properly configured and working.
    
    Returns:
        Dictionary containing connection status information
    """
    try:
        # Try a simple validation query first
        test_query = "SELECT 1 as test"
        # 0917 fix: do not use decorator function
        # validation_result = validate_sql_query(test_query)
        validation_result = _validate_sql_query_internal(test_query)

        if not validation_result["is_safe"]:
            logger.warning(f"[check_database_connection]: SQL query validation failed: {test_query}")
            return {
                "connected": False,
                "message": "Internal validation error",
                "error": "Test query validation failed"
            }
        
        # Try to execute a simple query to test connection
        result = execute_sql(test_query)
        
        if isinstance(result, str) and result.startswith("Error:"):
            logger.error(f"[check_database_connection]: Database connection test failed: {result}")
            return {
                "connected": False,
                "message": "Database connection failed",
                "error": result,
                "config_check": {
                    "DB_USER": "set" if os.getenv("DB_USER") else "missing",
                    "DB_PASSWORD": "set" if os.getenv("DB_PASSWORD") else "missing",
                    "DB_HOST": "set" if os.getenv("DB_HOST") else "missing",
                    "DB_NAME": "set" if os.getenv("DB_NAME") else "missing"
                }
            }
        
        # Serialize the result for JSON compatibility
        serialized_result = serialize_result(result)
        
        logger.info(f"[check_database_connection]: Database connection successful.")
        return {
            "connected": True,
            "message": "Database connection successful",
            "test_result": serialized_result
        }
        
    except Exception as e:
        logger.error(f"[check_database_connection]: Error checking database connection: {e}")
        return {
            "connected": False,
            "message": f"Connection test failed: {str(e)}",
            "error": str(e)
        }

# Note: Server startup is handled by start_server.py
# This module focuses on MCP tool definitions and functionality