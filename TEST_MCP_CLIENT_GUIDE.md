# MCP Client Test - Usage Guide

## Purpose

`test_mcp_client.py` is a test script that uses FastMCP's simplified client to verify the SQL Safety Checker MCP server via the MCP protocol.

## Test Configuration

The script includes configurable parameters at the top:
```python
TEST_TABLE_NAME = "information_schema.TABLES"  # Table for testing
TEST_SAMPLE_LIMIT = 3  # Sample data row limit
```

## Comparison with test_mcp_functions.py

| Feature | test_mcp_functions.py | test_mcp_client.py |
|---------|----------------------|-------------------|
| Test Method | Direct internal function calls | FastMCP Client via MCP protocol |
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
MCP CLIENT TEST - SQL Safety Checker MCP Server (FastMCP)
======================================================================
Server script: c:\path\to\start_server.py
Schema tools enabled: True

✓ Successfully connected to MCP server

Available tools: ['validate_sql_query', 'execute_safe_sql', 'get_server_info', ...]

----------------------------------------------------------------------
TEST 3: execute_safe_sql
----------------------------------------------------------------------
Query 1: List all tables in current database
Found 2 tables:
{
  "success": true,
  "query": "SELECT TABLE_NAME, TABLE_ROWS, TABLE_COMMENT FROM ...",
  "data": [
    {"TABLE_NAME": "test_users", "TABLE_ROWS": 2, "TABLE_COMMENT": ""},
    {"TABLE_NAME": "products", "TABLE_ROWS": 100, "TABLE_COMMENT": ""}
  ],
  "row_count": 2
}

Query 2: SELECT 1 as test
{
  "success": true,
  "query": "SELECT 1 as test",
  "data": [{"test": 1}],
  "row_count": 1
}
📝 Verify: 'data' field is [{'test': 1}] not [[1]]
```

## Test Coverage

The script tests the following tools:

1. ✅ `get_server_info` - Server information and capabilities
2. ✅ `check_database_connection` - Database connectivity test
3. ✅ `execute_safe_sql` - SQL execution with 3 queries:
   - List all tables in current database
   - Simple SELECT query (`SELECT 1 as test`)
   - COUNT query on configured table
4. ✅ `get_table_schema` - Table structure information (optional)
5. ✅ `get_sample_data` - Sample data retrieval (optional)

**Note**: SQL validation tests are covered in `test_mcp_functions.py` to avoid duplication.

## Key Validation Points

### Data Structure Consistency

- ❌ Incorrect: `"data": [[1]]` (2D array)
- ✅ Correct: `"data": [{"test": 1}]` (array of objects)

### test_result Format

- ❌ Incorrect: `"test_result": [[1]]`
- ✅ Correct: `"test_result": [{"test": 1}]`

## Troubleshooting

### Error: "fastmcp package not found"
```bash
pip install fastmcp
```

### Error: "Server script not found"
Ensure `start_server.py` is in the same directory.

### Connection Timeout
Check:
1. `.env` file is configured correctly
2. Database service is accessible
3. Firewall is not blocking connections

### Tools Unavailable
If `get_table_schema` or `get_sample_data` are not available:
```bash
# Set in .env file
ENABLE_SCHEMA_TOOLS=1
```

## Development Workflow

After modifying MCP tools:

1. Run internal tests:
   ```bash
   python test_mcp_functions.py
   ```

2. Run client tests:
   ```bash
   python test_mcp_client.py
   ```

3. Compare output with README documentation
4. Update documentation examples (if there are differences)

## Extending Tests

To add new test cases, edit `test_mcp_client.py` and add:

```python
# New test
print("-" * 70)
print("TEST N: your_new_tool")
print("-" * 70)
result = await client.call_tool("your_new_tool", {
    "param": "value"
})
content = json.loads(result.content[0].text) if hasattr(result.content[0], 'text') else result.content[0]
print(json.dumps(content, indent=2, ensure_ascii=False))
print()
```

## Test Configuration

Modify test parameters at the top of `test_mcp_client.py`:

```python
TEST_TABLE_NAME = "your_table_name"  # Change target table
TEST_SAMPLE_LIMIT = 5  # Change sample size
```

## Reference Documentation

- [README.md](README.md) - Complete project documentation
- [PROMPTS.md](PROMPTS.md) - Prompt templates usage guide
- [MCP Protocol Documentation](https://modelcontextprotocol.io) - Official protocol specification
