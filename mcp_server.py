#!/usr/bin/env python3
"""
MCP Server for SQL Safety Checker and Executor

This module implements an MCP (Model Context Protocol) server that exposes
SQL safety checking and execution functions as tools for LLM interaction.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Sequence

from mcp import types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

from sql_safety_checker import is_sql_safe, execute_sql

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sql-mcp-server")

# Create the server instance
server = Server("sql-safety-server")

@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """List available SQL tools"""
    return [
        types.Tool(
            name="is_sql_safe",
            description="Check if a SQL query is safe (read-only SELECT statements only)",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "The SQL query to validate for safety"
                    }
                },
                "required": ["sql_query"]
            }
        ),
        types.Tool(
            name="execute_sql",
            description="Execute a safe SQL query after validation",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "The SQL query to validate and execute"
                    }
                },
                "required": ["sql_query"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: Dict[str, Any]
) -> Sequence[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    if name == "is_sql_safe":
        sql_query = arguments.get("sql_query", "")
        try:
            result = is_sql_safe(sql_query)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({
                        "safe": result,
                        "query": sql_query,
                        "message": "Query is safe" if result else "Query contains unsafe operations"
                    }, indent=2)
                )
            ]
        except Exception as e:
            logger.error(f"Error checking SQL safety: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": str(e),
                        "safe": False
                    }, indent=2)
                )
            ]
    
    elif name == "execute_sql":
        sql_query = arguments.get("sql_query", "")
        try:
            result = execute_sql(sql_query)
            
            # Format the response based on the result type
            if isinstance(result, str):  # Error message
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": result,
                            "query": sql_query
                        }, indent=2)
                    )
                ]
            else:  # Successful query results
                # Convert SQLAlchemy rows to serializable format
                if hasattr(result, '__iter__'):
                    rows_data = []
                    for row in result:
                        if hasattr(row, '_asdict'):
                            rows_data.append(row._asdict())
                        elif hasattr(row, '__dict__'):
                            rows_data.append(dict(row.__dict__))
                        else:
                            rows_data.append(list(row))
                else:
                    rows_data = result
                
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps({
                            "success": True,
                            "data": rows_data,
                            "row_count": len(rows_data) if isinstance(rows_data, list) else 1,
                            "query": sql_query
                        }, indent=2)
                    )
                ]
                
        except Exception as e:
            logger.error(f"Error executing SQL: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": str(e),
                        "query": sql_query
                    }, indent=2)
                )
            ]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main function to run the MCP server"""
    logger.info("Starting SQL MCP Server...")
    
    # Run the server using stdio transport
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            options=NotificationOptions()
        )

if __name__ == "__main__":
    asyncio.run(main())