# MCP Client Test - Usage Guide

**Updated:** August 4, 2026 (v3.6)

## Purpose

`test_mcp_client.py` tests the SQL Safety Checker MCP server via the MCP protocol using FastMCP's Client API.

**Supported Databases:** MySQL, SQLite (v2.2+), configured named connections (v3.5+)

This is a manual/live smoke script, not part of the default pytest suite.
`pytest.ini` limits default pytest collection to `tests/`, so `python -m pytest`
does not start the MCP server against the current `.env`. Run this script only
against a safe development or fixture database because it can list tables,
execute count queries, describe tables, and print sampled rows.

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

For the default hermetic automated suite, run:

```bash
python -m pytest -q
```

For the live MCP protocol smoke check, continue with the setup below and run the
script explicitly.

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

  **Optional named connections (v3.5):**
  ```bash
  DB_CONNECTIONS=mysql,analytics
  DEFAULT_DB_CONNECTION=mysql

  DB_MYSQL_TYPE=mysql
  DB_MYSQL_USER=your_db_user
  DB_MYSQL_PASSWORD=your_db_password
  DB_MYSQL_HOST=your_db_host
  DB_MYSQL_NAME=your_db_name

  DB_ANALYTICS_TYPE=sqlite
  DB_ANALYTICS_SQLITE_DATABASE_PATH=./sample_data/demo.db
  DB_ANALYTICS_ALLOWED_TABLES=orders

  # Optional strict mutation routing (all three layers are required)
  SKILLS_ALLOW_MUTATION_CONNECTIONS=mysql,analytics
  DB_MYSQL_ALLOW_MUTATIONS=1
  DB_MYSQL_MUTATION_SKILLS=update-order-status
  DB_ANALYTICS_ALLOW_MUTATIONS=1
  DB_ANALYTICS_MUTATION_SKILLS=update-order-status
  ```

  Core read-only tools and query Skills accept optional `connection_id`.
  Omitting it uses the default connection. Tools and models cannot pass
  arbitrary DSNs; only configured aliases are accepted. If `DB_CONNECTIONS` is
  unset or empty, legacy mode ignores both `DB_<ID>_*` variables and
  `DEFAULT_DB_CONNECTION`.

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

### Client Parsing and Env Overrides

- Skill tools accept `params` as an MCP object/dict, not a JSON string.
- When reading FastMCP client results, prefer `result.structured_content` before
  `result.data`; skill payloads have their own `data` field.
- For stdio checks that must override startup env vars, such as telemetry tests,
  construct `StdioTransport` explicitly with `env=...` and the current Python
  executable instead of relying on the path-shortcut `Client(str(start_server))`.

### Sample Output

```
======================================================================
MCP CLIENT TEST - SQL Safety Checker MCP Server
======================================================================
Server script: /path/to/start_server.py
Schema tools enabled: True
Table summary enabled: False

✓ Successfully connected to MCP server

Available tools: ['query', 'check_connection', 'list_connections', 'list_tables', 'describe_table', 'get_full_schema', 'sample', 'list_skills', 'get_skill_detail', 'execute_query_skill', 'execute_mutation_skill']

----------------------------------------------------------------------
TEST 0: list_connections
----------------------------------------------------------------------
{
  "success": true,
  "default_connection_id": "mysql",
  "connection_count": 2,
  "connections": [
    {"connection_id": "mysql", "db_type": "mysql", "is_default": true},
    {"connection_id": "analytics", "db_type": "sqlite", "is_default": false}
  ]
}

----------------------------------------------------------------------
TEST 1: check_connection
----------------------------------------------------------------------
{
  "connected": true,
  "message": "Database connection successful",
  "connection_id": "mysql",
  "db_type": "mysql"
}

----------------------------------------------------------------------
TEST 2: list_tables
----------------------------------------------------------------------
{
  "success": true,
  "connection_id": "mysql",
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
  "connection_id": "mysql",
  "db_type": "mysql",
  "data": [{"test": 1}],
  "row_count": 1,
  "query": "SELECT 1 as test"
}
📝 Verify: 'data' field is [{'test': 1}] not [[1]]
```

## Test Coverage

The script tests the following tools:

1. ✅ `list_connections` - Configured connection discovery without DSNs, hosts, users, passwords, or SQLite paths
2. ✅ `check_connection` - Database connectivity test (includes `connection_id` and `db_type` fields)
3. ✅ `list_tables` - Database overview with new fields (`returned_table_count`, `total_tables`, `truncated`, `connection_id`, `db_type`)
4. ✅ `query` - SQL execution (Primary Tool):
   - Simple SELECT query
   - COUNT query
   - Unsafe query rejection
5. ✅ `describe_table` - Table structure with row count estimate and `is_large` hint
6. ✅ `get_full_schema` - Visible schema overview in one call; may be truncated
7. ✅ `get_table_summary` - Table statistics with optional exact count (requires `ENABLE_TABLE_SUMMARY=1`)
8. ✅ `sample` - Sample data retrieval (requires `ENABLE_SCHEMA_TOOLS=1`)
9. ✅ `list_skills` - List/search skills with `compact`/`summary`/`full` metadata, optional `available_only` filtering, connection-scoped policy/readiness fields, and schema readiness fields (requires `ENABLE_SKILLS=1`)
10. ✅ `get_skill_detail` - Fetch one skill's cached parameter schema and target connection readiness (requires `ENABLE_SKILLS=1`)
11. ✅ `execute_query_skill` - Execute a parameterized query skill against the resolved target connection (requires `ENABLE_SKILLS=1`)
12. ✅ `execute_mutation_skill` - Preview or execute a mutation skill on an authorized configured connection (requires `ENABLE_SKILLS=1` + `SKILLS_ALLOW_MUTATIONS=1`; execute also requires `preview_token`)

**Note**: Database-targeted tool responses include `db_type` field ("mysql" or "sqlite") since v2.2 and `connection_id` since v3.5.

**Note**: Skills tools (9-12) only appear when `ENABLE_SKILLS=1` is set. Mutation skills additionally require `SKILLS_ALLOW_MUTATIONS=1`. Without `SKILLS_ALLOW_MUTATION_CONNECTIONS`, mutation routing remains default-connection only. Setting it enables strict named routing and also requires `DB_<ID>_ALLOW_MUTATIONS=1` plus `DB_<ID>_MUTATION_SKILLS` for every target.

**Note**: All MCP tools wrap their structured payload in FastMCP `ToolResult` and expose runtime `ToolResult.meta` for diagnostics. Metadata is for diagnostics only (for example `tool_name`, `connection_id`, `db_type`, `execution_ms`, `success`, plus tool-specific counters such as `row_count`, `total_rows`, `truncated`, `skill_version`, `mode`) and intentionally excludes raw SQL, returned rows, parameter values, DSNs, hosts, usernames, passwords, and SQLite file paths.

**Note**: Per MCP spec the `_meta` field is OPTIONAL and clients MAY ignore it. In practice this means:
- Servers and middleware always populate it (you can rely on it for server-side observability and structured logs).
- MCP Inspector, raw JSON-RPC tooling, and clients that explicitly surface `_meta` will display it.
- VS Code's MCP UI (verified during v3.4.1) does **not** currently render `_meta`; only `structuredContent` is shown to the user. If you need to see runtime metadata while testing, use MCP Inspector or capture the JSON-RPC frames directly.

**v3.5 update**: Uniform `ToolResult` now covers all registered tools in the full profile (up to 12: core SQL tools, optional schema/table-summary tools, `list_connections`, skill discovery/detail tools, and skill execution tools). Every database-targeted tool's `meta` carries `tool_name`, `execution_ms`, `connection_id`, `db_type`, and `success`; data-returning tools also add `row_count`, `total_rows`, and `truncated`. The skill execution tools declare an MCP `outputSchema` so clients can validate `structuredContent` programmatically. Opt-in tool telemetry via `ENABLE_TOOL_TELEMETRY=1` writes one JSONL line per `tools/call` to `TOOL_TELEMETRY_LOG_PATH` (default `logs/tool_calls.jsonl`) containing only `timestamp`, `tool_name`, `execution_ms`, `call_completed`, `success`, `error_class`, `connection_id`, and `db_type` — never SQL, parameters, returned rows, connection strings, or credentials. Sampling can be configured via `TOOL_TELEMETRY_SAMPLE_RATE` (0.0–1.0; default 1.0).

For SQLite targets, public tool payloads that need a database display name use
`sqlite:<connection_id>` rather than exposing the configured file path.

#### Skills `ToolResult.meta` Response Examples

The examples below show the JSON-RPC response shape clients see for the two
Skills execution tools. `structuredContent` is the business payload (stable
contract); `_meta` is runtime diagnostics added in v3.4.1 and made uniform
across all tools in v3.4.2.

**Query skill — `execute_query_skill(skill_name="monthly-sales-report", params={"year": 2024, "month": 1})`**

```jsonc
{
  "structuredContent": {
    "success": true,
    "skill_name": "monthly-sales-report",
    "data": [
      { "date": "2024-01-15", "order_count": 1, "revenue": "100.00", "avg_order_value": "100.00" },
      { "date": "2024-01-20", "order_count": 1, "revenue": "250.00", "avg_order_value": "250.00" }
    ],
    "row_count": 2,
    "total_rows": 2,
    "truncated": false,
    "truncation_note": null
  },
  "_meta": {
    "tool_name": "execute_query_skill",
    "success": true,
    "skill_name": "monthly-sales-report",
    "skill_type": "query",
    "skill_version": "1.0.0",
    "mode": "query",
    "execution_ms": 12.3,
    "row_count": 2,
    "total_rows": 2,
    "truncated": false,
    "audit_logged": false,
    "connection_id": "mysql",
    "db_type": "mysql",
    "idempotent": true
  }
}
```

**Mutation skill (preview phase) — `execute_mutation_skill(skill_name="update-order-status", params={"order_id": 1, "new_status": "shipped"}, confirm=false)`**

```jsonc
{
  "structuredContent": {
    "success": true,
    "skill_name": "update-order-status",
    "mode": "preview",
    "preview": { /* before/after diff produced by the mutation class */ },
    "preview_token": "<opaque preview token>",
    "preview_token_expires_at": "2026-05-30T12:05:00+00:00",
    "preview_token_expires_in_seconds": 300,
    "idempotent": false,
    "hint": "Set confirm=true and pass preview_token to execute this operation."
  },
  "_meta": {
    "tool_name": "execute_mutation_skill",
    "success": true,
    "skill_name": "update-order-status",
    "skill_type": "mutation",
    "skill_version": "1.0.0",
    "mode": "preview",
    "execution_ms": 4.7,
    "row_count": 1,
    "audit_logged": true,
    "connection_id": "mysql",
    "db_type": "mysql",
    "idempotent": false,
    "preview_token_required": true,
    "preview_token_validated": false,
    "preview_token_consumed": false,
    "preview_token_id": "<token hash prefix>"
  }
}
```

**Mutation skill (confirm phase) — same call with `confirm=true` and the preview token**

```jsonc
{
  "structuredContent": {
    "success": true,
    "skill_name": "update-order-status",
    "mode": "execute",
    "result": { "success": true, "rowcount": 1, /* mutation-specific fields */ },
    "idempotent": false
  },
  "_meta": {
    "tool_name": "execute_mutation_skill",
    "success": true,
    "skill_name": "update-order-status",
    "skill_type": "mutation",
    "skill_version": "1.0.0",
    "mode": "execute",
    "execution_ms": 8.5,
    "audit_logged": true,
    "connection_id": "mysql",
    "db_type": "mysql",
    "idempotent": false,
    "preview_token_required": true,
    "preview_token_validated": true,
    "preview_token_consumed": true,
    "preview_token_id": "<token hash prefix>"
  }
}
```

Fields visible in `_meta` may vary by skill type and mode (for example
`row_count` / `total_rows` / `truncated` are populated only for query skills,
`row_count` is populated for mutation preview/execute only when the skill result
provides an affected-row estimate or rowcount). Mutation execute requires the
`preview_token` returned by the matching preview call; missing, expired,
tampered, mismatched, already-consumed, or process-restart-stale tokens fail
closed before writes. A valid execute atomically consumes the token before
dynamic validation/write; later failures require a new preview. The `_meta`
field `preview_token_consumed=true` makes this explicit for normal validation
failure results. `tool_name`,
`success`, `connection_id`, `db_type`, and `execution_ms` are present for
database-targeted tools. `call_completed` is not part of
tool `_meta`; it exists only in the optional telemetry JSONL record to separate
transport completion from business success.

**Note**: SQL validation tests are also covered in `test_mcp_functions.py`.

### Skills Smoke Example

When Skills are enabled, a minimal progressive-disclosure check should follow this order. The bundled monthly report examples are demo-profile skills and require an `orders` table; with `SKILLS_CHECK_SCHEMA_ON_LIST=1`, `available_only=true` hides them when the target connection does not have the demo schema.

To create the demo MySQL table used by `monthly-sales-report` and `update-order-status`, run:

```bash
.venv/bin/python scripts/setup_demo_db.py
```

The script refuses to modify an existing `orders` table unless `--drop-existing` or `--seed-existing` is passed explicitly.

```python
skills = await client.call_tool("list_skills", {"detail_level": "compact", "connection_id": "analytics"})
detail = await client.call_tool("get_skill_detail", {"skill_name": "monthly-sales-report-sqlite", "connection_id": "analytics"})
result = await client.call_tool(
  "execute_query_skill",
  {"skill_name": "monthly-sales-report-sqlite", "params": {"year": 2026, "month": 1}, "connection_id": "analytics"},
)
# FastMCP clients can inspect result.meta for runtime diagnostics.
```

Use `list_skills(search=..., category=..., available_only=true, connection_id=...)` for Agent-facing discovery and `get_skill_detail(..., connection_id=...)` for params before execution when the list response is not `full`. Use `available_only=false` for developer catalog review, including skills that are currently incompatible with the target connection's DB type, disabled by mutation switches, limited to the default connection in v3.5, blocked by connection policy, or marked `schema_ready=false` because required tables are missing. The discovery target should match the `connection_id` used for `execute_query_skill()`.

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
