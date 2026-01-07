# MCP Client Test - Usage Guide

## Purpose

`test_mcp_client.py` tests the SQL Safety Checker MCP server via the MCP protocol using FastMCP's Client API.

## Test Configuration

```python
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"
TABLE_SUMMARY_ENABLED = os.getenv("ENABLE_TABLE_SUMMARY", "0") == "1"
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
   ```bash
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_HOST=your_db_host
   DB_NAME=your_db_name
   ENABLE_SCHEMA_TOOLS=1
   ```

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

Available tools: ['query', 'check_connection', 'list_tables', 'describe_table', 'get_full_schema', 'sample']

----------------------------------------------------------------------
TEST 1: check_connection
----------------------------------------------------------------------
{
  "connected": true,
  "message": "Database connection successful"
}

----------------------------------------------------------------------
TEST 2: list_tables
----------------------------------------------------------------------
{
  "success": true,
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
✓ All new fields present: returned_table_count=2, total_tables=2

----------------------------------------------------------------------
TEST 3: query (Primary Tool)
----------------------------------------------------------------------
Query 1: SELECT 1 as test
{
  "success": true,
  "data": [{"test": 1}],
  "row_count": 1,
  "query": "SELECT 1 as test"
}
📝 Verify: 'data' field is [{'test': 1}] not [[1]]
```

## Test Coverage

The script tests the following tools:

1. ✅ `check_connection` - Database connectivity test
2. ✅ `list_tables` - Database overview with new fields (`returned_table_count`, `total_tables`, `truncated`)
3. ✅ `query` - SQL execution (Primary Tool):
   - Simple SELECT query
   - COUNT query
   - Unsafe query rejection
4. ✅ `describe_table` - Table structure with row count estimate and `is_large` hint
5. ✅ `get_full_schema` - Complete database schema in one call
6. ✅ `get_table_summary` - Table statistics with optional exact count (requires `ENABLE_TABLE_SUMMARY=1`)
7. ✅ `sample` - Sample data retrieval (requires `ENABLE_SCHEMA_TOOLS=1`)

**Note**: SQL validation tests are also covered in `test_mcp_functions.py`.

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
