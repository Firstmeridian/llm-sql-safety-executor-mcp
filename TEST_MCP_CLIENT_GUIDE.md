# MCP Client Test - Usage Guide

**Updated:** May 14, 2026 (v3.4)

## Purpose

`test_mcp_client.py` tests the SQL Safety Checker MCP server via the MCP protocol using FastMCP's Client API.

**Supported Databases:** MySQL, SQLite (v2.2+)

## Test Configuration

```python
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"
TABLE_SUMMARY_ENABLED = os.getenv("ENABLE_TABLE_SUMMARY", "0") == "1"
SKILLS_ENABLED = os.getenv("ENABLE_SKILLS", "0") == "1"
TEST_SAMPLE_LIMIT = 3  # Sample data row limit
```

## Comparison with test_mcp_functions.py

| Feature | test_mcp_functions.py | test_mcp_client.py |
|---------|----------------------|-------------------|
| Test Method | Direct function calls | FastMCP Client via MCP protocol |
| Server Startup | Not required | Automatically managed by FastMCP |
| Data Serialization | Manual serialization | Automatic via FastMCP |
| Purpose | Validate business logic | Validate protocol communication |

## Usage

### Prerequisites

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables (`.env` file):

   **For MySQL:**
   ```bash
   DB_TYPE=mysql
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_HOST=your_db_host
   DB_NAME=your_db_name
   ENABLE_SCHEMA_TOOLS=1
   ```

   **For SQLite:**
   ```bash
   DB_TYPE=sqlite
   SQLITE_DATABASE_PATH=./my_database.db
   # or :memory: for in-memory database
   ENABLE_SCHEMA_TOOLS=1
   ```

    **Skills Extension (v3.0+):**
    ```bash
    ENABLE_SKILLS=1
    SKILLS_ALLOW_MUTATIONS=1   # Optional: enable mutation skills
    SKILLS_LIST_DEFAULT_DETAIL=summary
    SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1
    SKILLS_CHECK_SCHEMA_ON_LIST=1
    # SKILLS_EXCLUDE_PROFILES=demo  # Optional: hide bundled demo skills in production
    SKILLS_AUDIT_QUERIES=0          # Optional query skill audit
    SKILLS_DIR=skills/              # Default
    ```

    Restart the MCP server after changing environment variables. Live schema
    changes such as creating the demo `orders` table are picked up by the next
    schema-readiness check, but process-level settings are read at startup.

### Running the Test

```bash
python test_mcp_client.py
```

### Sample Output

```
======================================================================
MCP CLIENT TEST - SQL Safety Checker MCP Server
======================================================================
Server script: /path/to/start_server.py
Schema tools enabled: True
Table summary enabled: False

✓ Successfully connected to MCP server

Available tools: ['query', 'check_connection', 'list_tables', 'describe_table', 'get_full_schema', 'sample', 'list_skills', 'get_skill_detail', 'execute_query_skill', 'execute_mutation_skill']

----------------------------------------------------------------------
TEST 1: check_connection
----------------------------------------------------------------------
{
  "connected": true,
  "message": "Database connection successful",
  "db_type": "mysql"
}

----------------------------------------------------------------------
TEST 2: list_tables
----------------------------------------------------------------------
{
  "success": true,
  "db_type": "mysql",
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [
    {"table_name": "test_users", "row_count": 2},
    {"table_name": "products", "row_count": 100}
  ],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null
}
✓ All new fields present: returned_table_count=2, total_tables=2, db_type=mysql

----------------------------------------------------------------------
TEST 3: query (Primary Tool)
----------------------------------------------------------------------
Query 1: SELECT 1 as test
{
  "success": true,
  "db_type": "mysql",
  "data": [{"test": 1}],
  "row_count": 1,
  "query": "SELECT 1 as test"
}
📝 Verify: 'data' field is [{'test': 1}] not [[1]]
```

## Test Coverage

The script tests the following tools:

1. ✅ `check_connection` - Database connectivity test (includes `db_type` field)
2. ✅ `list_tables` - Database overview with new fields (`returned_table_count`, `total_tables`, `truncated`, `db_type`)
3. ✅ `query` - SQL execution (Primary Tool):
   - Simple SELECT query
   - COUNT query
   - Unsafe query rejection
4. ✅ `describe_table` - Table structure with row count estimate and `is_large` hint
5. ✅ `get_full_schema` - Complete database schema in one call
6. ✅ `get_table_summary` - Table statistics with optional exact count (requires `ENABLE_TABLE_SUMMARY=1`)
7. ✅ `sample` - Sample data retrieval (requires `ENABLE_SCHEMA_TOOLS=1`)
8. ✅ `list_skills` - List/search skills with `compact`/`summary`/`full` metadata, optional `available_only` filtering, and schema readiness fields (requires `ENABLE_SKILLS=1`)
9. ✅ `get_skill_detail` - Fetch one skill's cached parameter schema (requires `ENABLE_SKILLS=1`)
10. ✅ `execute_query_skill` - Execute a parameterized query skill (requires `ENABLE_SKILLS=1`)
11. ✅ `execute_mutation_skill` - Execute a mutation skill with dry-run/confirm (requires `ENABLE_SKILLS=1` + `SKILLS_ALLOW_MUTATIONS=1`)

**Note**: All tool responses include `db_type` field ("mysql" or "sqlite") since v2.2.

**Note**: Skills tools (8-11) only appear when `ENABLE_SKILLS=1` is set. Mutation skills additionally require `SKILLS_ALLOW_MUTATIONS=1`.

**Note**: SQL validation tests are also covered in `test_mcp_functions.py`.

### Skills Smoke Example

When Skills are enabled, a minimal progressive-disclosure check should follow this order. The bundled monthly report examples are demo-profile skills and require an `orders` table; with `SKILLS_CHECK_SCHEMA_ON_LIST=1`, `available_only=true` hides them when the current database does not have the demo schema.

To create the demo MySQL table used by `monthly-sales-report` and `update-order-status`, run:

```bash
.venv/bin/python scripts/setup_demo_db.py
```

The script refuses to modify an existing `orders` table unless `--drop-existing` or `--seed-existing` is passed explicitly.

```python
skills = await client.call_tool("list_skills", {"detail_level": "compact"})
detail = await client.call_tool("get_skill_detail", {"skill_name": "monthly-sales-report-sqlite"})
result = await client.call_tool(
  "execute_query_skill",
  {"skill_name": "monthly-sales-report-sqlite", "params": {"year": 2026, "month": 1}},
)
```

Use `list_skills(search=..., category=..., available_only=true)` for Agent-facing discovery and `get_skill_detail()` for params before execution when the list response is not `full`. Use `available_only=false` for developer catalog review, including skills that are currently incompatible with `DB_TYPE`, disabled by mutation switches, or marked `schema_ready=false` because required tables are missing.

## Key Validation Points

### Data Structure Consistency

- ❌ Incorrect: `"data": [[1]]` (2D array)
- ✅ Correct: `"data": [{"test": 1}]` (array of objects)

### Unsafe Query Rejection

```json
{
  "success": false,
  "error": "Only SELECT queries are allowed",
  "query": "DELETE FROM users"
}
```

## Troubleshooting

### Error: "fastmcp package not found"
```bash
pip install fastmcp
```

### Error: "Server script not found"
Ensure `start_server.py` is in the same directory.

### Tools Unavailable
If `sample` is not available:
```bash
# Set in .env file
ENABLE_SCHEMA_TOOLS=1
```

If Skills tools (`list_skills`, `get_skill_detail`, etc.) are not available:
```bash
# Set in .env file
ENABLE_SKILLS=1
SKILLS_ALLOW_MUTATIONS=1  # For mutation skills
```

## Development Workflow

After modifying MCP tools:

1. Run direct tests:
   ```bash
   python test_mcp_functions.py
   ```

2. Run protocol tests:
   ```bash
   python test_mcp_client.py
   ```

3. Compare output with README documentation

## Reference Documentation

- [README.md](README.md) - Complete project documentation
- [MCP Protocol Documentation](https://modelcontextprotocol.io) - Official protocol specification
