#!/usr/bin/env python3
"""
Simple demonstration of the MCP Server functionality

This script shows how the MCP server tools work by calling them directly.
"""

import asyncio
import json

async def demo_mcp_tools():
    """Demonstrate MCP server tools functionality"""
    
    print("🔧 SQL MCP Server Tool Demonstration")
    print("=" * 60)
    
    # Import the handlers directly
    from mcp_server import handle_list_tools, handle_call_tool
    
    print("\n📋 Available Tools:")
    tools = await handle_list_tools()
    for i, tool in enumerate(tools, 1):
        print(f"   {i}. {tool.name}")
        print(f"      📝 {tool.description}")
        print()
    
    print("🧪 Testing Tools:")
    print("-" * 40)
    
    # Test cases
    test_cases = [
        ("SELECT * FROM users WHERE id = 1", "Safe SELECT query"),
        ("SELECT name, email FROM customers ORDER BY name", "Multi-column SELECT"),
        ("DELETE FROM users WHERE id = 1", "Unsafe DELETE query"),
        ("INSERT INTO logs (message) VALUES ('test')", "Unsafe INSERT query"),
        ("UPDATE users SET name = 'John' WHERE id = 1", "Unsafe UPDATE query"),
        ("DROP TABLE users", "Unsafe DROP query"),
    ]
    
    for sql_query, description in test_cases:
        print(f"\n🔍 {description}:")
        print(f"   Query: {sql_query}")
        
        # Test is_sql_safe
        result = await handle_call_tool("is_sql_safe", {"sql_query": sql_query})
        response_data = json.loads(result[0].text)
        safety_status = "✅ SAFE" if response_data.get("safe") else "❌ UNSAFE"
        print(f"   Safety: {safety_status}")
        
        # Test execute_sql (will show proper error handling without DB)
        exec_result = await handle_call_tool("execute_sql", {"sql_query": sql_query})
        exec_response = json.loads(exec_result[0].text)
        if exec_response.get("success"):
            print(f"   Execution: ✅ SUCCESS")
        else:
            error_msg = exec_response.get("error", "Unknown error")
            if "Only SELECT queries are allowed" in error_msg:
                print(f"   Execution: ❌ BLOCKED (Safety check)")
            else:
                print(f"   Execution: ❌ DB ERROR (Expected without database)")
    
    print("\n" + "=" * 60)
    print("✨ MCP Server demonstration completed!")
    print("\n💡 Key Features Demonstrated:")
    print("   • SQL safety validation using sqlparse")
    print("   • MCP protocol tool registration")
    print("   • Error handling and security enforcement")
    print("   • JSON-structured responses")
    print("   • Integration with existing SQL functionality")

if __name__ == "__main__":
    asyncio.run(demo_mcp_tools())