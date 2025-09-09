#!/usr/bin/env python3
"""
Test script for SQL MCP Server

This script demonstrates how to test the MCP server functionality
without requiring a full MCP client setup.
"""

import asyncio
import json
from mcp_server import SQLMCPServer
from mcp import types

async def test_mcp_server():
    """Test the MCP server functionality"""
    
    print("Testing SQL MCP Server")
    print("=" * 50)
    
    # Create server instance
    server = SQLMCPServer()
    
    # Test the handlers directly (since we can't easily test the full MCP protocol without a client)
    print("\n1. Testing SQL Safety Functions:")
    
    # Test SQL safety validation
    from sql_safety_checker import is_sql_safe, execute_sql
    
    safe_query = "SELECT * FROM users WHERE id = 1"
    unsafe_query = "DELETE FROM users WHERE id = 1"
    
    print(f"   Safe query: '{safe_query}'")
    print(f"   Is safe: {is_sql_safe(safe_query)}")
    
    print(f"\n   Unsafe query: '{unsafe_query}'")
    print(f"   Is safe: {is_sql_safe(unsafe_query)}")
    
    print("\n2. Testing MCP Tool Registration:")
    
    # Test that tools are properly registered by accessing the handlers
    try:
        # Get the list_tools handler and call it
        list_tools_handler = None
        call_tool_handler = None
        
        for handler in server.app._handlers:
            if hasattr(handler, 'func') and hasattr(handler.func, '__name__'):
                if handler.func.__name__ == 'handle_list_tools':
                    list_tools_handler = handler.func
                elif handler.func.__name__ == 'handle_call_tool':
                    call_tool_handler = handler.func
        
        if list_tools_handler:
            tools = await list_tools_handler()
            print(f"   Registered {len(tools)} tools:")
            for tool in tools:
                print(f"     - {tool.name}: {tool.description}")
        else:
            print("   Could not find list_tools handler")
        
        if call_tool_handler:
            print("\n3. Testing Tool Calls:")
            
            # Test is_sql_safe tool
            result = await call_tool_handler("is_sql_safe", {"sql_query": safe_query})
            print(f"   is_sql_safe result: {result[0].text}")
            
            # Test with unsafe query
            result = await call_tool_handler("is_sql_safe", {"sql_query": unsafe_query})
            print(f"   is_sql_safe unsafe result: {result[0].text}")
            
            # Test execute_sql (will show error due to no DB connection)
            result = await call_tool_handler("execute_sql", {"sql_query": "SELECT 1"})
            print(f"   execute_sql result: {result[0].text}")
        else:
            print("   Could not find call_tool handler")
            
    except Exception as e:
        print(f"   Error testing handlers: {e}")
        # Fallback: test the underlying functions directly
        print("   Testing underlying functions directly:")
        print(f"   is_sql_safe('{safe_query}'): {is_sql_safe(safe_query)}")
        print(f"   is_sql_safe('{unsafe_query}'): {is_sql_safe(unsafe_query)}")
        print(f"   execute_sql('{safe_query}'): {execute_sql(safe_query)}")
    
    print("\n" + "=" * 50)
    print("MCP Server test completed!")

if __name__ == "__main__":
    asyncio.run(test_mcp_server())