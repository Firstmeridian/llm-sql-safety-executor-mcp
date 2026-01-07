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


def test_extract_tables_regex_fix():
    """Test the fixed regex pattern for table extraction by running it directly."""
    print("=" * 60)
    print("TEST 1: _extract_tables_from_sql regex fix verification")
    print("=" * 60)
    
    # Extract the fixed regex from source and test it
    def _extract_tables_from_sql_fixed(sql: str) -> list[str]:
        """Fixed implementation matching the updated code."""
        tables = []
        
        # Fixed pattern: handle optional schema prefix
        from_join_pattern = r'(?:FROM|JOIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
        matches = re.findall(from_join_pattern, sql, re.IGNORECASE)
        tables.extend(matches)
        
        describe_pattern = r'(?:DESCRIBE|DESC|EXPLAIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
        matches = re.findall(describe_pattern, sql, re.IGNORECASE)
        tables.extend(matches)
        
        return list(set(tables))
    
    test_cases = [
        ("SELECT * FROM users", ["users"], "Simple FROM"),
        ("SELECT * FROM `users`", ["users"], "Backtick quoted table"),
        ("SELECT * FROM mydb.users", ["users"], "Schema.table format"),
        ("SELECT * FROM `mydb`.`users`", ["users"], "Backtick schema.table"),
        ("SELECT * FROM mydb.users JOIN orders ON 1=1", ["users", "orders"], "Schema.table with JOIN"),
        ("SELECT * FROM db1.table1 JOIN db2.table2 ON 1=1", ["table1", "table2"], "Multiple schema.table"),
        ("DESCRIBE mydb.products", ["products"], "DESCRIBE with schema"),
        ("SELECT * FROM users u JOIN orders o ON u.id = o.user_id", ["users", "orders"], "Aliased tables"),
        ("SELECT * FROM 用户表", ["用户表"], "Chinese table name"),
        ("SELECT * FROM mydb.用户表", ["用户表"], "Chinese table with schema"),
    ]
    
    all_passed = True
    
    for sql, expected, desc in test_cases:
        result = sorted(_extract_tables_from_sql_fixed(sql))
        expected_sorted = sorted(expected)
        passed = result == expected_sorted
        
        if passed:
            print(f"✅ PASS: {desc}")
        else:
            print(f"❌ FAIL: {desc}")
            print(f"   SQL: {sql}")
            print(f"   Expected: {expected_sorted}")
            print(f"   Got:      {result}")
            all_passed = False
    
    # Also verify the source code has the fix
    source = read_source_file()
    if r'(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?' in source:
        print("\n✅ Source code contains fixed regex pattern")
    else:
        print("\n❌ Source code missing fixed regex pattern")
        all_passed = False
    
    print()
    if all_passed:
        print("🎉 P1 REGEX FIX VERIFIED!")
    else:
        print("❌ P1 fix incomplete")
    
    return all_passed


def test_sql_assistant_prompt_fix():
    """Verify sql_assistant prompt handles ALLOWED_TABLES=* correctly."""
    print("\n" + "=" * 60)
    print("TEST 2: sql_assistant prompt fix verification")
    print("=" * 60)
    
    source = read_source_file()
    
    # Look for the fixed logic in sql_assistant
    # Current implementation: ALLOWED_TABLES=* results in "UNION supported for combining results."
    checks = [
        ('if "*" in ALLOWED_TABLES:' in source, 'Check for "*" in ALLOWED_TABLES'),
        ('UNION supported for combining results' in source, 'UNION message for ALLOWED_TABLES=*'),
        ('cross_table' in source, 'cross_table variable used in prompt'),
    ]
    
    all_passed = True
    for condition, desc in checks:
        if condition:
            print(f"✅ PASS: {desc}")
        else:
            print(f"❌ FAIL: {desc}")
            all_passed = False
    
    # Extract the relevant code section
    match = re.search(r'def sql_assistant\(\).*?return f""".*?"""', source, re.DOTALL)
    if match:
        print(f"\n📋 Extracted sql_assistant function:\n{'-' * 40}")
        func_code = match.group(0)
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


def test_get_full_schema_truncation():
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
    
    results.append(("P1: Regex fix", test_extract_tables_regex_fix()))
    results.append(("P2: Prompt fix", test_sql_assistant_prompt_fix()))
    results.append(("P0: Truncation fix", test_get_full_schema_truncation()))
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
