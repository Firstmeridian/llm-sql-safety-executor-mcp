# SQL Safety MCP Server

This repository has been enhanced with **Model Context Protocol (MCP)** server functionality, allowing Large Language Models to safely interact with SQL databases through a standardized protocol.

## 🔄 Conversion from Direct LLM Calls to MCP Server

### What Changed

The original project provided Python functions that LLMs could call directly:
- `is_sql_safe(sql_query)` - Check if SQL is safe
- `execute_sql(sql_query)` - Execute validated SQL queries

**Now available as MCP Server:**
- Standardized MCP protocol interface
- Two MCP tools: `is_sql_safe` and `execute_sql`
- Better security and resource management
- Support for multiple concurrent LLM clients

### Benefits of MCP Conversion

1. **🛡️ Enhanced Security**: Isolated server environment
2. **📊 Standardized Interface**: Industry-standard protocol for LLM-tool interaction
3. **⚡ Better Performance**: Centralized connection pooling and resource management
4. **🔌 Universal Compatibility**: Works with any MCP-compatible LLM platform
5. **📈 Scalability**: Supports multiple concurrent clients

## 🚀 Quick Start

### Prerequisites

```bash
pip install -r requirements.txt
```

### Configuration

Create a `.env` file for database connection (optional):
```bash
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=your_db_host
DB_NAME=your_db_name
```

### Running the MCP Server

```bash
python mcp_server.py
```

### Testing the Server

```bash
# Run the demonstration
python demo_mcp.py

# Or run the basic test
python test_mcp_server.py
```

## 🛠️ Available MCP Tools

### 1. `is_sql_safe`
**Description**: Check if a SQL query is safe (read-only SELECT statements only)

**Input**:
```json
{
  "sql_query": "SELECT * FROM users WHERE id = 1"
}
```

**Output**:
```json
{
  "safe": true,
  "query": "SELECT * FROM users WHERE id = 1",
  "message": "Query is safe"
}
```

### 2. `execute_sql`
**Description**: Execute a safe SQL query after validation

**Input**:
```json
{
  "sql_query": "SELECT name, email FROM users LIMIT 5"
}
```

**Output** (Success):
```json
{
  "success": true,
  "data": [
    {"name": "Alice", "email": "alice@example.com"},
    {"name": "Bob", "email": "bob@example.com"}
  ],
  "row_count": 2,
  "query": "SELECT name, email FROM users LIMIT 5"
}
```

**Output** (Error):
```json
{
  "success": false,
  "error": "Only SELECT queries are allowed.",
  "query": "DELETE FROM users"
}
```

## 🔒 Security Features

- **SQL Injection Protection**: Only SELECT statements allowed
- **Query Validation**: Uses sqlparse for comprehensive SQL analysis
- **Error Isolation**: Database errors don't crash the server
- **Connection Pooling**: Managed database connections via SQLAlchemy

## 📁 File Structure

```
├── sql_safety_checker.py    # Original SQL functions (still available)
├── mcp_server.py            # MCP Server implementation
├── server_config.py         # Server configuration management
├── demo_mcp.py              # Interactive demonstration
├── test_mcp_server.py       # Testing utilities
├── requirements.txt         # Updated dependencies (includes MCP)
└── README.md                # This documentation
```

## 🔄 Backward Compatibility

The original functions are still available for direct import:

```python
from sql_safety_checker import is_sql_safe, execute_sql

# Direct function calls still work
is_safe = is_sql_safe("SELECT * FROM users")
result = execute_sql("SELECT * FROM users LIMIT 1")
```

## 🌐 Integration with LLM Platforms

The MCP server can be integrated with:
- **Claude Desktop** (Anthropic)
- **ChatGPT** (OpenAI) with MCP plugins
- **Custom LLM applications** using MCP client libraries
- **Any MCP-compatible tool**

Example MCP client configuration:
```json
{
  "mcpServers": {
    "sql-safety": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/project"
    }
  }
}
```

## 🧪 Example Usage

See the demonstration in action:

```bash
python demo_mcp.py
```

This will show:
- ✅ Safe SELECT queries being validated and executed
- ❌ Unsafe queries (DELETE, INSERT, UPDATE, DROP) being blocked
- 🛡️ Security enforcement in action
- 📊 Structured JSON responses

## 📊 Performance Considerations

- **Connection Pooling**: SQLAlchemy manages database connections efficiently
- **Async Operations**: Full async/await support for concurrent requests
- **Memory Management**: Proper resource cleanup and error handling
- **Logging**: Comprehensive logging for monitoring and debugging

## 🤝 Contributing

The MCP server maintains full compatibility with the original codebase while adding modern LLM integration capabilities. Both the original function-based approach and the new MCP server approach are supported.

## 📄 License

Same license as the original project.