# SQL Safety Checker - MCP Service Implementation

A Python-based tool that enables Large Language Models (LLMs) to safely execute SQL queries through a standardized MCP (Model Context Protocol) service interface.

## What Changed

This project has been transformed from a direct function-call approach to a standardized MCP service architecture, providing:

- Service-Oriented Architecture: Converted direct LLM function calls to a standalone MCP server
- Standardized Protocol: Implemented MCP tools for consistent AI model integration
- Enhanced Separation of Concerns: Split server startup logic into dedicated `start_server.py`
- Improved Scalability: Single server instance supports multiple concurrent LLM clients
- Better Security: Service isolation and controlled access through MCP protocol

## Problem Statement

### Original Challenge
Traditional LLM-database integrations face several limitations:
- Tight Coupling: Database logic intertwined with LLM interaction code
- Scalability Issues: Each LLM instance requires separate database connections
- Security Concerns: Direct access to database functions without proper isolation
- Maintenance Overhead: Changes require updates across multiple LLM implementations
- Limited Reusability: Platform-specific implementations difficult to share

### Core Requirements
- Enable safe SQL query execution for AI models
- Ensure only SELECT statements are allowed
- Provide consistent interface across different AI platforms
- Maintain high performance and reliability
- Support multiple concurrent AI model connections

## Solution

### MCP Service Architecture

Our solution implements a Model Context Protocol (MCP) server that provides standardized database access:

```
Traditional Approach:        MCP Service Approach:
LLM → Direct Function       LLM → MCP Client → MCP Server → Database
```

### Key Components

1. `start_server.py`: Server startup and environment validation
2. `mcp_sql_server.py`: Core MCP tool definitions and functionality
3. `sql_safety_checker.py`: Original validation and execution logic (unchanged)
4. `test_mcp_functions.py`: Comprehensive testing suite

### Implementation Strategy

- Backward Compatibility: Original functionality preserved without modification
- Incremental Adoption: Can run alongside existing direct-call implementations
- Minimal Dependencies: Uses FastMCP framework for simplified development
- Environment-Based Configuration: Secure credential management through `.env` files

## MCP Tools Exposed

The service exposes six standardized MCP tools:

### 1. `validate_sql_query`
Purpose: Validates SQL queries for safety (SELECT-only operations)

Input:
```json
{
  "sql_query": "SELECT name, email FROM users WHERE active = 1"
}
```

Output:
```json
{
  "is_safe": true,
  "query": "SELECT name, email FROM users WHERE active = 1",
  "message": "Query is safe for execution",
  "allowed_operations": ["SELECT"],
  "validation_passed": true
}
```

### 2. `execute_safe_sql`
Purpose: Executes validated SQL queries against the database

Safety behavior:
- Automatic SQL safety validation is performed before execution. Only SELECT statements are allowed.
- If the query contains any non-SELECT operation or mixed statements, the tool rejects it and returns `success: false` with an explanatory `message`.
- To pre-check without executing, use `validate_sql_query`.

Input:
```json
{
  "sql_query": "SELECT COUNT(*) as total FROM products"
}
```

Output:
```json
{
  "success": true,
  "query": "SELECT COUNT(*) as total FROM products",
  "message": "Query executed successfully",
  "data": [
    {"total": 150}
  ],
  "row_count": 1
}
```
Note: `data` is a JSON-serializable list (typically a list of objects). For this query it looks like `[{"total": 150}]`.

### 3. `get_server_info`
Purpose: Provides server capabilities and configuration information

Output:
```json
{
  "name": "SQL Safety Checker MCP Server",
  "version": "1.0.0",
  "capabilities": ["SQL query validation (SELECT-only)", "Safe SQL query execution"],
  "supported_databases": ["MySQL"],
  "safety_features": ["Only SELECT statements allowed", "SQL parsing validation"]
}
```

### 4. `check_database_connection`
Purpose: Tests database connectivity and configuration

Output:
```json
{
  "connected": true,
  "message": "Database connection successful",
  "test_result": [
    {"test": 1}
  ]
}
```

### 5. `get_table_schema` (Optional)
Purpose: Retrieves schema information for database tables

**Note**: This tool is controlled by the `ENABLE_SCHEMA_TOOLS` environment variable (default: enabled)

Input:
```json
{
  "table_name": "users"  // Optional - if empty, returns all tables
}
```

Output (specific table):
```json
{
  "success": true,
  "table_name": "users",
  "message": "Schema retrieved successfully",
  "data": [
    {
      "COLUMN_NAME": "id",
      "DATA_TYPE": "int",
      "IS_NULLABLE": "NO",
      "COLUMN_DEFAULT": null,
      "COLUMN_KEY": "PRI",
      "EXTRA": "auto_increment"
    },
    {
      "COLUMN_NAME": "name",
      "DATA_TYPE": "varchar",
      "IS_NULLABLE": "YES",
      "COLUMN_DEFAULT": null,
      "COLUMN_KEY": "",
      "EXTRA": ""
    }
  ],
  "row_count": 2
}
```

Output (all tables):
```json
{
  "success": true,
  "table_name": "all_tables",
  "message": "Schema retrieved successfully",
  "data": [
    {
      "TABLE_NAME": "users",
      "TABLE_ROWS": 150,
      "TABLE_COMMENT": "User accounts"
    },
    {
      "TABLE_NAME": "products",
      "TABLE_ROWS": 500,
      "TABLE_COMMENT": "Product catalog"
    }
  ],
  "row_count": 2
}
```

### 6. `get_sample_data` (Optional)
Purpose: Retrieves sample data from a specified table

**Note**: This tool is controlled by the `ENABLE_SCHEMA_TOOLS` environment variable (default: enabled)

Input:
```json
{
  "table_name": "users",
  "limit": 5  // Optional - default: 5, max: 20
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "message": "Sample data retrieved successfully (limit: 5)",
  "data": [
    {"id": 1, "name": "Alice"},
    {"id": 2, "name": "Bob"},
    {"id": 3, "name": "Charlie"},
    {"id": 4, "name": "David"},
    {"id": 5, "name": "Eve"}
  ],
  "row_count": 5,
  "query_executed": "SELECT * FROM users LIMIT 5"
}
```

## Benefits Achieved

- 🔒 Enhanced security: Service isolation with SELECT-only enforcement (via SQL parsing)
- 🔌 Standardized integration: MCP tools provide a consistent interface for LLM clients
- 🧹 Maintainability: Clear separation of concerns (startup/env validation in `start_server.py`; tools isolated)
- ⚡ Performance: SQLAlchemy connection pooling reduces connection overhead
- 🧩 Compatibility: MySQL support; works with MCP-compatible clients (e.g., Claude Desktop) and custom apps; original direct-call functions preserved
- ⚙️ Configurability: Environment-based credentials and startup-time validation of required variables
- 🔍 Discoverability: Optional database introspection tools for exploring schemas and data

## Testing Results

Based on the included scripts and program behavior:

- ✅ Validation
  - SELECT queries: Reported as safe and eligible for execution.
  - Non-SELECT queries (DELETE/INSERT/UPDATE/DROP): Reported as unsafe and blocked.
  - Multiple statements: Allowed only if all statements are SELECT; any non-SELECT causes failure.
  - Empty query: Treated as safe by the current implementation.
- 🔗 Connection check (`check_database_connection`)
  - Failure modes (e.g., missing env vars, unreachable DB): Returns `connected: false` and includes `config_check` with missing variables.
  - Success: Executes `SELECT 1 as test` and returns `connected: true` with tuple-like result.
- ▶️ Execution (`execute_safe_sql`)
  - Unsafe queries: Blocked at validation with `success: false` and a clear message.
  - Safe queries:
    - With valid DB connectivity: Returns serialized rows (JSON-serializable) and `row_count`.
    - Without valid connectivity: Returns `success: false` with an error message.
- 📊 Schema Introspection (`get_table_schema`) - **Optional Feature**
  - All tables: Returns list of tables with row counts and comments
  - Specific table: Returns detailed column information including types and constraints
  - Can be disabled via `ENABLE_SCHEMA_TOOLS=0`
- 📋 Sample Data (`get_sample_data`) - **Optional Feature**
  - Retrieves limited sample rows from specified tables
  - Enforces maximum limit of 20 rows for safety
  - Returns actual query executed for transparency
  - Can be disabled via `ENABLE_SCHEMA_TOOLS=0`
- 🧾 Response shape
  - Tools return structured dictionaries with stable keys (`is_safe`, `success`, `message`, `data`, etc.).
  - For MCP tools, `data` / `test_result` are JSON-serializable values (typically a list of objects, e.g., `[{"total": 150}]`).
  - If you call `sql_safety_checker.execute_sql` directly (bypassing MCP), you will get raw Row/tuple lists instead.

## Quick Start

### Traditional Usage (Preserved)
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Run original implementation
python sql_safety_checker.py
```

### MCP Service Usage (Recommended)
```bash
# Install dependencies including MCP support
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Start MCP server
python start_server.py

# Test MCP functionality (internal functions)
python test_mcp_functions.py

# Test MCP server via client (simulates real MCP client)
python test_mcp_client.py
```

### Configure MCP Client
Add the server to your MCP-compatible client configuration (e.g., Claude Desktop or other MCP clients):

```json
{
  "mcpServers": {
    "sql-safety-checker": {
      "command": "python",
      "args": ["start_server.py"],
      "env": {
        "DB_USER": "${DB_USER}",
        "DB_PASSWORD": "${DB_PASSWORD}",
        "DB_HOST": "${DB_HOST}",
        "DB_NAME": "${DB_NAME}"
      }
    }
  }
}
```

- If your client loads `.env` automatically (e.g., via python-dotenv), the `env` block can be omitted.
- Ensure your client allows running local commands and passing environment variables.

## Migration Path

Existing users can continue using the original functions with no changes:

```python
from sql_safety_checker import is_sql_safe, execute_sql  # Still works exactly as before
```

## Configuration

### Required Environment Variables
```bash
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
DB_NAME=your_database_name
```

### Optional Environment Variables
```bash
# Feature Toggles (1=enabled, 0=disabled)
ENABLE_SCHEMA_TOOLS=1  # Controls get_table_schema and get_sample_data tools
```

### MCP Client Integration
See `mcp_config.json` for a complete client configuration example.

## Safety Features

- Query Restriction: Only SELECT statements allowed
- SQL Parsing Validation: Uses `sqlparse` for comprehensive query analysis
- Connection Security: Environment-based credential management
- Error Isolation: Comprehensive exception handling and reporting
- Access Control: MCP protocol-level permission management

## Requirements

- Python 3.12+
- MySQL database
- Dependencies: `sqlparse`, `SQLAlchemy`, `PyMySQL`, `fastMCP`, `python-dotenv`

## Testing

### Test Scripts

The project includes two complementary test scripts:

#### 1. `test_mcp_functions.py` - Internal Function Tests
Tests the underlying functions directly without going through the MCP protocol:
```bash
python test_mcp_functions.py
```

This script validates:
- SQL validation logic (safe and unsafe queries)
- Database connection
- Query execution
- Schema introspection (if enabled)
- Sample data retrieval (if enabled)

#### 2. `test_mcp_client.py` - MCP Protocol Tests
Uses FastMCP Client to test the server via the MCP protocol:
```bash
python test_mcp_client.py
```

This script:
- Connects to the MCP server using FastMCP's `Client` API
- Tests server info and database connectivity
- Executes multiple SQL queries (list tables, SELECT, COUNT)
- Tests optional schema tools (if enabled)
- Verifies data serialization format

**Key Features:**
- Configurable test parameters (`TEST_TABLE_NAME`, `TEST_SAMPLE_LIMIT`)
- Focuses on protocol communication and data format validation
- Complements `test_mcp_functions.py` by avoiding duplicate tests

**Use this to verify that:**
- `data` fields return `[{"key": value}]` (not `[[value]]`)
- MCP protocol communication works correctly
- All tool responses match the README documentation

## Additional Documentation

- [Feasibility Analysis](LLM_TO_MCP_FEASIBILITY_ANALYSIS.md): Detailed analysis of LLM to MCP conversion
- [Original Context](GEMINI.md): Project background and development guidelines
- [Prompt Templates](PROMPTS.md): Guide for using MCP prompt templates

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with proper testing
4. Add tests for new functionality
5. Update documentation as needed
6. Submit a pull request

## Support

For technical issues, feature requests, or questions:
- Create an issue in the GitHub repository
- Include relevant error messages and configuration details
- Provide steps to reproduce any problems

---

*This project demonstrates the successful conversion from direct LLM function calls to a standardized MCP service, providing improved scalability, security, and maintainability for AI-driven data workflows.*