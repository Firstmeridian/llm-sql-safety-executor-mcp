#!/usr/bin/env python3
"""
Test script to verify the MCP server functions work correctly.
"""

import os
import json
from sql_safety_checker import is_sql_safe, execute_sql
from typing import Any, Dict

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

def validate_sql_query(sql_query: str) -> Dict[str, Any]:
    """
    Validates if a SQL query is safe (contains only SELECT statements).
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
        return {
            "is_safe": False,
            "query": sql_query,
            "message": f"Validation error: {str(e)}",
            "error": str(e),
            "validation_passed": False
        }

def execute_safe_sql(sql_query: str) -> Dict[str, Any]:
    """
    Executes a SQL query after validating it is safe.
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
        return {
            "success": False,
            "query": sql_query,
            "message": f"Execution error: {str(e)}",
            "error": str(e),
            "data": None
        }

def get_server_info() -> Dict[str, Any]:
    """
    Returns information about the SQL Safety Checker MCP server.
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

def check_database_connection() -> Dict[str, Any]:
    """
    Checks if the database connection is properly configured and working.
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
        return {
            "connected": False,
            "message": f"Connection test failed: {str(e)}",
            "error": str(e)
        }

if __name__ == "__main__":
    print("Testing MCP Server Functions")
    print("=" * 50)
    
    # Test validation
    print("\n1. Testing SQL Validation")
    print("-" * 30)
    
    test_queries = [
        "SELECT * FROM users",
        "SELECT name, email FROM customers WHERE id > 10",
        "DELETE FROM users WHERE id = 1",
        "INSERT INTO users (name) VALUES ('Alice')",
        "UPDATE users SET name = 'Bob' WHERE id = 1",
        "DROP TABLE users",
        "",
        "SELECT COUNT(*) FROM orders; SELECT * FROM products"
    ]
    
    for query in test_queries:
        result = validate_sql_query(query)
        print(f"Query: {query[:50]}{'...' if len(query) > 50 else ''}")
        print(f"  Safe: {result['is_safe']}")
        print(f"  Message: {result['message']}")
        print()
    
    # Test server info
    print("2. Testing Server Info")
    print("-" * 30)
    info = get_server_info()
    print(json.dumps(info, indent=2))
    
    # Test connection (will fail without DB config)
    print("\n3. Testing Database Connection")
    print("-" * 30)
    conn_result = check_database_connection()
    print(json.dumps(conn_result, indent=2))
    
    # Test execution (will fail without DB config)
    print("\n4. Testing SQL Execution")
    print("-" * 30)
    exec_result = execute_safe_sql("SELECT 1 as test")
    print(json.dumps(exec_result, indent=2))