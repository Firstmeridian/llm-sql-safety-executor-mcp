#!/usr/bin/env python3
"""
Bug Fix Verification Tests (Source-based)
Directly read the source code to verify the fix and avoid issues caused by the FastMCP decorator
"""

import re
from pathlib import Path

# Use relative path from script location
SCRIPT_DIR = Path(__file__).parent
MCP_SERVER_FILE = SCRIPT_DIR / "mcp_sql_server.py"


def read_source_file():
    """Read the mcp_sql_server.py source file."""
    with open(MCP_SERVER_FILE, 'r') as f:
        return f.read()


def _verify_sql_assistant_prompt_fix():
    """Verify sql_assistant does not present the default UNION policy globally."""
    print("\n" + "=" * 60)
    print("TEST 2: sql_assistant prompt fix verification")
    print("=" * 60)
    
    source = read_source_file()
    match = re.search(r'def sql_assistant\(\).*?return f""".*?"""', source, re.DOTALL)
    if not match:
        print("❌ FAIL: Could not extract sql_assistant function")
        return False

    func_code = match.group(0)

    # sql_assistant() has no connection_id argument. It must direct callers to
    # the selected connection's policy instead of projecting the default
    # connection's ALLOW_UNION/ALLOWED_TABLES values as server-wide truth.
    checks = [
        (
            "UNION policy is connection-specific" in func_code,
            "UNION guidance is connection-specific",
        ),
        (
            "selected alias in " in func_code and "list_connections();" in func_code,
            "Prompt directs callers to the selected alias",
        ),
        (
            "query() and Query Skills enforce that target's policy" in func_code,
            "Prompt identifies target-runtime enforcement",
        ),
        (
            "if ALLOW_UNION" not in func_code and "ALLOWED_TABLES" not in func_code,
            "Prompt does not derive global guidance from default policy globals",
        ),
        ('cross_table' in func_code, 'cross_table variable used in prompt'),
    ]
    
    all_passed = True
    for condition, desc in checks:
        if condition:
            print(f"✅ PASS: {desc}")
        else:
            print(f"❌ FAIL: {desc}")
            all_passed = False
    
    # Extract the relevant code section
    print(f"\n📋 Extracted sql_assistant function:\n{'-' * 40}")
    # Show just the relevant part
    for line in func_code.split('\n')[:20]:
        print(f"   {line}")
    print("   ...")
    
    print()
    if all_passed:
        print("🎉 P2 PROMPT FIX VERIFIED!")
    else:
        print("❌ P2 fix incomplete")
    
    return all_passed


def test_sql_assistant_prompt_fix():
    """Pytest wrapper for the sql_assistant prompt verification."""
    assert _verify_sql_assistant_prompt_fix()


def _verify_get_full_schema_truncation():
    """Verify get_full_schema has truncation logic and correct field names."""
    print("\n" + "=" * 60)
    print("TEST 3: get_full_schema truncation & field naming verification")
    print("=" * 60)
    
    source = read_source_file()
    
    # Extract get_full_schema function
    match = re.search(r'async def get_full_schema\(.*?\n(?:async def |@mcp\.|# =====)', source, re.DOTALL)
    if match:
        func_source = match.group(0)
    else:
        func_source = source
    
    checks = [
        ("MAX_SCHEMA_TABLES" in func_source, "MAX_SCHEMA_TABLES constant used"),
        ("truncated = False" in func_source or "truncated = True" in func_source, "truncated flag variable"),
        ("truncation_note" in func_source, "truncation_note in output"),
        ("await ctx.warning" in func_source, "Warning logged when truncated"),
        ("tables_data[:MAX_SCHEMA_TABLES]" in func_source, "Tables list is sliced for truncation"),
        ("returned_table_count" in func_source, "returned_table_count field (renamed from table_count)"),
        ("total_tables" in func_source, "total_tables field for visible tables count"),
    ]
    
    all_passed = True
    for condition, desc in checks:
        if condition:
            print(f"✅ PASS: {desc}")
        else:
            print(f"❌ FAIL: {desc}")
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 P0 TRUNCATION FIX VERIFIED!")
    else:
        print("❌ P0 fix incomplete")
    
    return all_passed


def test_get_full_schema_truncation():
    """Pytest wrapper for get_full_schema truncation verification."""
    assert _verify_get_full_schema_truncation()


def check_syntax():
    """Verify the modified file has no syntax errors."""
    print("\n" + "=" * 60)
    print("TEST 4: Python syntax check")
    print("=" * 60)
    
    import py_compile
    try:
        py_compile.compile(str(MCP_SERVER_FILE), doraise=True)
        print("✅ PASS: No syntax errors in mcp_sql_server.py")
        return True
    except py_compile.PyCompileError as e:
        print(f"❌ FAIL: Syntax error: {e}")
        return False


if __name__ == "__main__":
    print("\n🔍 BUG FIX VERIFICATION FOR mcp_sql_server.py\n")
    
    results = []
    
    results.append(("P2: Prompt fix", _verify_sql_assistant_prompt_fix()))
    results.append(("P0: Truncation fix", _verify_get_full_schema_truncation()))
    results.append(("Syntax check", check_syntax()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = all(r[1] for r in results)
    for name, passed in results:
        status = "✅ FIXED" if passed else "❌ FAILED"
        print(f"   {name}: {status}")
    
    print()
    if all_passed:
        print("🎉 ALL BUG FIXES VERIFIED SUCCESSFULLY!")
    else:
        print("⚠️ Some fixes need attention")
    
    print("\nDone!")
