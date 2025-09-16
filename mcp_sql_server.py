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
from mcp.server.fastmcp import FastMCP
from sql_safety_checker import is_sql_safe, execute_sql

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the MCP server
mcp = FastMCP("SQL Safety Checker")

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

@mcp.tool()
def validate_sql_query(sql_query: str) -> Dict[str, Any]:
    """
    Validates if a SQL query is safe (contains only SELECT statements).
    
    Args:
        sql_query: The SQL query to validate
        
    Returns:
        Dictionary containing validation result and details
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
        validation_result = validate_sql_query(sql_query)
        
        if not validation_result["is_safe"]:
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
            return {
                "success": False,
                "query": sql_query,
                "message": result,
                "error": result,
                "data": None
            }
        
        # Serialize the result for JSON compatibility
        serialized_data = serialize_result(result)
        
        return {
            "success": True,
            "query": sql_query,
            "message": "Query executed successfully",
            "data": serialized_data,
            "row_count": len(result) if isinstance(result, list) else 0
        }
        
    except Exception as e:
        logger.error(f"Error executing SQL query: {e}")
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
        validation_result = validate_sql_query(test_query)
        
        if not validation_result["is_safe"]:
            return {
                "connected": False,
                "message": "Internal validation error",
                "error": "Test query validation failed"
            }
        
        # Try to execute a simple query to test connection
        result = execute_sql(test_query)
        
        if isinstance(result, str) and result.startswith("Error:"):
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
        
        return {
            "connected": True,
            "message": "Database connection successful",
            "test_result": serialized_result
        }
        
    except Exception as e:
        logger.error(f"Error checking database connection: {e}")
        return {
            "connected": False,
            "message": f"Connection test failed: {str(e)}",
            "error": str(e)
        }

# Note: Server startup is handled by start_server.py
# This module focuses on MCP tool definitions and functionality