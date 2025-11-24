#!/usr/bin/env python3
"""
MCP Client Test Script (FastMCP)

This script uses FastMCP's simplified client to test the SQL Safety Checker MCP server.
It connects to the server and calls various tools to verify their actual return 
structures match the documentation.

Usage:
    python test_mcp_client.py
"""

import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if schema tools are enabled
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"

# Test configuration
TEST_TABLE_NAME = "information_schema.TABLES"  # Table to use for testing queries
TEST_SAMPLE_LIMIT = 3  # Number of sample rows to retrieve


def print_result(title: str, data: dict, note: str = None):
    """Helper function to print test results consistently."""
    print("-" * 70)
    print(title)
    print("-" * 70)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if note:
        print(f"\n📝 Note: {note}")
    print()


async def test_mcp_server():
    """Connect to the MCP server and test all available tools."""
    # Get the absolute path to start_server.py
    script_dir = Path(__file__).parent
    server_script = script_dir / "start_server.py"
    
    if not server_script.exists():
        print(f"Error: Server script not found at {server_script}")
        return
    
    print("=" * 70)
    print("MCP CLIENT TEST - SQL Safety Checker MCP Server (FastMCP)")
    print("=" * 70)
    print(f"Server script: {server_script}")
    print(f"Schema tools enabled: {SCHEMA_TOOLS_ENABLED}")
    print()
    
    try:
        async with Client(str(server_script)) as client:
            # Ping server to verify connection
            await client.ping()
            print("✓ Successfully connected to MCP server\n")
            
            # List available tools
            tools = await client.list_tools()
            print(f"Available tools: {[tool.name for tool in tools]}\n")
            
            # Test 1: Get Server Info
            result = await client.call_tool("get_server_info", {})
            # Extract content from CallToolResult
            content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
            print_result("TEST 1: get_server_info", content)
            
            # Test 2: Check Database Connection
            result = await client.call_tool("check_database_connection", {})
            content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
            print_result("TEST 2: check_database_connection", content)
            
            # Test 3: Execute Safe SQL
            print("-" * 70)
            print("TEST 3: execute_safe_sql")
            print("-" * 70)
            
            # Test listing all tables in current database
            list_tables_query = "SELECT TABLE_NAME, TABLE_ROWS, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
            print(f"Query 1: List all tables in current database")
            result = await client.call_tool("execute_safe_sql", {
                "sql_query": list_tables_query
            })
            content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
            if content.get('success') and isinstance(content.get('data'), list):
                print(f"Found {len(content['data'])} tables:")
                print(json.dumps(content, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(content, indent=2, ensure_ascii=False))
            
            # Test simple SELECT
            print("\nQuery 2: SELECT 1 as test")
            result = await client.call_tool("execute_safe_sql", {
                "sql_query": "SELECT 1 as test"
            })
            content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
            print(json.dumps(content, indent=2, ensure_ascii=False))
            print("📝 Verify: 'data' field is [{'test': 1}] not [[1]]")
            
            # Test COUNT query with configured table
            count_query = f"SELECT COUNT(*) as total FROM {TEST_TABLE_NAME}"
            print(f"\nQuery 3: {count_query}")
            result = await client.call_tool("execute_safe_sql", {
                "sql_query": count_query
            })
            content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
            print(json.dumps(content, indent=2, ensure_ascii=False))
            print("📝 Verify: 'data' field is [{'total': N}] not [[N]]")
            print()
            
            # Test 4-5: Schema tools (if enabled)
            if SCHEMA_TOOLS_ENABLED:
                # Test 4: Get Table Schema
                result = await client.call_tool("get_table_schema", {})
                content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
                # Limit output for readability
                print("-" * 70)
                print("TEST 4: get_table_schema (All Tables)")
                print("-" * 70)
                if isinstance(content, dict) and 'data' in content and isinstance(content['data'], list):
                    if len(content['data']) > 3:
                        print(f"Showing first 3 of {len(content['data'])} tables:")
                        content['data'] = content['data'][:3] + [{"...": "more tables"}]
                    print(json.dumps(content, indent=2, ensure_ascii=False))
                    print()
                else:
                    print(json.dumps(content, indent=2, ensure_ascii=False))
                    print()
                
                # Test 5: Get Sample Data
                print("-" * 70)
                print("TEST 5: get_sample_data")
                print("-" * 70)
                print(f"Table: {TEST_TABLE_NAME}, Limit: {TEST_SAMPLE_LIMIT}")
                result = await client.call_tool("get_sample_data", {
                    "table_name": TEST_TABLE_NAME,
                    "limit": TEST_SAMPLE_LIMIT
                })
                content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
                print(json.dumps(content, indent=2, ensure_ascii=False))
                print()
            else:
                print("-" * 70)
                print("TEST 4-5: Schema tools disabled (ENABLE_SCHEMA_TOOLS=0)")
                print("-" * 70)
                print()
            
            print("=" * 70)
            print("✓ All tests completed!")
            print("=" * 70)
            
    except Exception as e:
        print(f"\n❌ Failed to connect to MCP server: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure start_server.py exists and is executable")
        print("2. Check that all required environment variables are set in .env")
        print("3. Verify that 'fastmcp' package is installed: pip install fastmcp")


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
