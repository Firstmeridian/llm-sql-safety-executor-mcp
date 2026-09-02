#!/usr/bin/env python3
"""
MCP Client Test Script (FastMCP)

This script uses FastMCP's Client to test the SQL Safety Checker MCP server
via the MCP protocol. It connects to the server and calls various tools to 
verify their actual return structures match the documentation.

Usage:
    python test_mcp_client.py

This tests the MCP protocol communication. For direct function tests, 
use test_mcp_functions.py instead.
"""

import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if optional tools are enabled
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"
TABLE_SUMMARY_ENABLED = os.getenv("ENABLE_TABLE_SUMMARY", "0") == "1"
SKILLS_ENABLED = os.getenv("ENABLE_SKILLS", "0") == "1"

# Test configuration
TEST_SAMPLE_LIMIT = 3  # Number of sample rows to retrieve


def print_result(title: str, data: dict, note: str | None = None):
    """Helper function to print test results consistently."""
    print("-" * 70)
    print(title)
    print("-" * 70)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if note:
        print(f"\n📝 Note: {note}")
    print()


def parse_result(result) -> dict:
    """Parse MCP tool result to dictionary."""
    if hasattr(result, 'structured_content') and result.structured_content:
        return result.structured_content
    if hasattr(result, 'data') and result.data:
        return result.data
    if hasattr(result, 'content') and result.content:
        return json.loads(result.content[0].text)
    return {}


def maybe_skip_pytest(reason: str) -> bool:
    """Skip optional database-dependent smoke checks when running under pytest."""
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return False

    import pytest

    pytest.skip(reason)
    return True


async def _test_mcp_server_async():
    """Connect to the MCP server and test all available tools."""
    # Get the absolute path to start_server.py
    script_dir = Path(__file__).parent
    server_script = script_dir / "start_server.py"
    
    if not server_script.exists():
        raise FileNotFoundError(f"Server script not found at {server_script}")
    
    print("=" * 70)
    print("MCP CLIENT TEST - SQL Safety Checker MCP Server")
    print("=" * 70)
    print(f"Server script: {server_script}")
    print(f"Schema tools enabled: {SCHEMA_TOOLS_ENABLED}")
    print(f"Table summary enabled: {TABLE_SUMMARY_ENABLED}")
    print(f"Skills enabled: {SKILLS_ENABLED}")
    print()
    
    async with Client(str(server_script)) as client:
            # Ping server to verify connection
            await client.ping()
            print("✓ Successfully connected to MCP server\n")
            
            # List available tools
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]
            tools_by_name = {tool.name: tool for tool in tools}
            print(f"Available tools: {tool_names}\n")
            for expected_tool in [
                "list_connections",
                "check_connection",
                "query",
                "list_tables",
                "describe_table",
                "get_full_schema",
            ]:
                assert expected_tool in tool_names, (
                    f"Missing expected MCP tool: {expected_tool}"
                )

            schema_tool = tools_by_name["get_full_schema"]
            schema_properties = schema_tool.inputSchema["properties"]
            assert schema_properties["detail_level"]["enum"] == [
                "compact",
                "full",
            ]
            assert schema_properties["detail_level"]["default"] == "compact"
            assert "anyOf" not in schema_properties["detail_level"]

            normalized_descriptions = {
                name: " ".join((tool.description or "").split())
                for name, tool in tools_by_name.items()
            }
            assert "primary tool for free-form read-only SQL" in (
                normalized_descriptions["query"]
            )
            assert "not complete DDL" in normalized_descriptions["describe_table"]
            assert "strict named-write policy" in (
                normalized_descriptions["list_connections"]
            )

            if "sample" in tools_by_name:
                limit_schema = tools_by_name["sample"].inputSchema["properties"][
                    "limit"
                ]
                assert limit_schema["default"] == 5
                assert limit_schema["minimum"] == 1
                assert limit_schema["maximum"] == 20
                invalid_sample = await client.call_tool(
                    "sample",
                    {"table_name": "validation_only", "limit": 0},
                    raise_on_error=False,
                )
                assert invalid_sample.is_error is True

            if "get_table_summary" in tools_by_name:
                exact_count_schema = tools_by_name[
                    "get_table_summary"
                ].inputSchema["properties"]["exact_count"]
                assert exact_count_schema["default"] is False
                assert "SELECT COUNT(*)" in exact_count_schema["description"]
                assert "full scan" in exact_count_schema["description"]
            
            # Test 1: Check Database Connection
            result = await client.call_tool("check_connection", {})
            content = parse_result(result)
            print_result("TEST 1: check_connection", content)
            assert "connected" in content, "check_connection result missing connected field"
            
            db_connected = content.get("connected", False)
            if not db_connected:
                message = "Database not connected. Check .env for DB credentials."
                print(f"⚠️  {message}\n")
                if maybe_skip_pytest(message):
                    return
                return
            
            # Test 2: List Tables - verify new field structure
            result = await client.call_tool("list_tables", {})
            content = parse_result(result)
            print_result("TEST 2: list_tables", content)
            assert content.get("success") is True, f"list_tables failed: {content}"
            
            # Validate new fields (returned_table_count, total_tables, truncated)
            if content.get("success"):
                required_fields = ["returned_table_count", "total_tables", "truncated", "truncation_note"]
                missing = [f for f in required_fields if f not in content]
                assert not missing, f"Missing new list_tables fields: {missing}"
                print(f"✓ All new fields present: returned_table_count={content['returned_table_count']}, total_tables={content['total_tables']}")
            
            # Get first table name for later tests
            first_table = None
            if content.get("success") and content.get("tables"):
                first_table = content["tables"][0].get("table_name")

            # Test 2B: Default grouped-compact projection through fresh stdio
            result = await client.call_tool("get_full_schema", {})
            compact_schema = parse_result(result)
            assert compact_schema.get("success") is True, compact_schema
            assert compact_schema.get("detail_level") == "compact"
            assert compact_schema.get("grouping_basis") == (
                "adapter_visible_column_metadata_and_order"
            )
            assert "schema_groups" in compact_schema
            assert "schema" not in compact_schema
            print_result(
                "TEST 2B: get_full_schema(default compact)",
                {
                    "success": compact_schema["success"],
                    "detail_level": compact_schema["detail_level"],
                    "returned_table_count": compact_schema["returned_table_count"],
                    "schema_group_count": compact_schema["schema_group_count"],
                    "grouping_basis": compact_schema["grouping_basis"],
                    "truncated": compact_schema["truncated"],
                },
                note="Grouping compares adapter-visible column metadata, not complete DDL.",
            )
            
            # Test 3: Query Tool (Primary)
            print("-" * 70)
            print("TEST 3: query (Free-form Read Tool)")
            print("-" * 70)
            
            # Test simple SELECT
            print("Query 1: SELECT 1 as test")
            result = await client.call_tool("query", {"sql": "SELECT 1 as test"})
            content = parse_result(result)
            print(json.dumps(content, indent=2, ensure_ascii=False))
            assert content.get("success") is True, f"SELECT smoke query failed: {content}"
            assert content.get("data"), "SELECT smoke query returned no data"
            print("📝 Verify: 'data' field is [{'test': 1}] not [[1]]\n")
            
            # Test COUNT query
            if first_table:
                count_query = f"SELECT COUNT(*) as total FROM `{first_table}`"
                print(f"Query 2: {count_query}")
                result = await client.call_tool("query", {"sql": count_query})
                content = parse_result(result)
                print(json.dumps(content, indent=2, ensure_ascii=False))
                assert content.get("success") is True, f"COUNT smoke query failed: {content}"
                print("📝 Verify: 'data' field is [{'total': N}]\n")
            
            # Test unsafe query (should be blocked)
            print("Query 3: DELETE FROM users (should be blocked)")
            result = await client.call_tool("query", {"sql": "DELETE FROM users"})
            content = parse_result(result)
            print(json.dumps(content, indent=2, ensure_ascii=False))
            assert content.get("success") is False, f"Unsafe query was not rejected: {content}"
            print("📝 Verify: 'success' is false, query blocked\n")
            
            # Test 4: Describe Table
            if first_table:
                result = await client.call_tool("describe_table", {"table_name": first_table})
                content = parse_result(result)
                # Limit columns shown
                if content.get("columns") and len(content["columns"]) > 5:
                    content["columns"] = content["columns"][:5] + [{"...": "more columns"}]
                print_result(f"TEST 4: describe_table('{first_table}')", content)
                assert content.get("success") is True, f"describe_table failed: {content}"
            else:
                print("-" * 70)
                print("TEST 4: describe_table (skipped - no tables)")
                print("-" * 70)
                print()
            
            # Test 5: Sample Tool (if enabled and table exists)
            if SCHEMA_TOOLS_ENABLED and first_table and "sample" in tool_names:
                result = await client.call_tool("sample", {
                    "table_name": first_table,
                    "limit": TEST_SAMPLE_LIMIT
                })
                content = parse_result(result)
                print_result(f"TEST 5: sample('{first_table}', limit={TEST_SAMPLE_LIMIT})", content)
            else:
                print("-" * 70)
                print("TEST 5: sample (skipped - disabled or no tables)")
                print("-" * 70)
                print()
            
            # Test 6: List Skills (if enabled)
            if SKILLS_ENABLED and "list_skills" in tool_names:
                result = await client.call_tool("list_skills", {})
                content = parse_result(result)
                print_result("TEST 6: list_skills", content)
                assert content.get("success") is True, f"list_skills failed: {content}"
                
                # Get first skill name for later tests
                first_skill = None
                skills_list = content.get("skills", [])
                if skills_list:
                    first_skill = skills_list[0].get("name") if isinstance(skills_list[0], dict) else None
                skill_names = [
                    skill.get("name") for skill in skills_list
                    if isinstance(skill, dict) and skill.get("name")
                ]
                
                # Test 7: Execute Query Skill (if a query skill exists)
                query_skill = next(
                    (
                        skill_name for skill_name in (
                            "monthly-sales-report",
                            "monthly-sales-report-sqlite",
                        )
                        if skill_name in skill_names
                    ),
                    first_skill,
                )
                query_skill_params = (
                    {"year": 2026, "month": 1}
                    if query_skill in {"monthly-sales-report", "monthly-sales-report-sqlite"}
                    else {}
                )
                if query_skill:
                    print("-" * 70)
                    print(f"TEST 7: execute_query_skill('{query_skill}')")
                    print("-" * 70)
                    result = await client.call_tool("execute_query_skill", {
                        "skill_name": query_skill,
                        "params": query_skill_params,
                    })
                    content = parse_result(result)
                    print(json.dumps(content, indent=2, ensure_ascii=False))
                    if query_skill in {"monthly-sales-report", "monthly-sales-report-sqlite"}:
                        assert content.get("success") is True, f"execute_query_skill failed: {content}"
                    print()
                else:
                    print("-" * 70)
                    print("TEST 7: execute_query_skill (skipped - no skills found)")
                    print("-" * 70)
                    print()
                
                # Test 8: Execute Mutation Skill (dry-run, if enabled)
                if "execute_mutation_skill" in tool_names:
                    print("-" * 70)
                    print("TEST 8: execute_mutation_skill (dry-run with invalid skill)")
                    print("-" * 70)
                    try:
                        result = await client.call_tool("execute_mutation_skill", {
                            "skill_name": "nonexistent-skill",
                            "params": {},
                            "confirm": False,
                        })
                        content = parse_result(result)
                        print(json.dumps(content, indent=2, ensure_ascii=False))
                        raise AssertionError(f"Expected nonexistent mutation skill to fail: {content}")
                    except Exception as exc:
                        assert "not found" in str(exc).lower(), str(exc)
                        print(f"✓ Expected error for nonexistent skill: {exc}\n")
                else:
                    print("-" * 70)
                    print("TEST 8: execute_mutation_skill (skipped - SKILLS_ALLOW_MUTATIONS=0)")
                    print("-" * 70)
                    print()
            else:
                print("-" * 70)
                print("TEST 6-8: Skills tools (skipped - ENABLE_SKILLS=0)")
                print("-" * 70)
                print()
            
            print("=" * 70)
            print("✓ All MCP protocol tests completed!")
            print("=" * 70)


def test_mcp_server():
    """Pytest wrapper for the async MCP client smoke test."""
    asyncio.run(_test_mcp_server_async())


if __name__ == "__main__":
    asyncio.run(_test_mcp_server_async())
