# SQL Safety Checker - MCP Service Implementation

English | [中文](README_ZH.md)

A Python-based tool that enables Large Language Models (LLMs) to safely execute read-only SQL queries through a standardized MCP (Model Context Protocol) service interface.

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

### AutoGen Multi-Agent Example
```bash
# Run the AutoGen multi-agent SQL query system
# Requires: GEMINI_API_KEY, OPENAI_API_KEY, or USE_OLLAMA=true
python autogen_sql_agent.py

# Or run with a specific task
python autogen_sql_agent.py "List all tables and describe their structure"
```

The `autogen_sql_agent.py` demonstrates how to use Microsoft AutoGen framework with a multi-agent team (PlanningAgent, SQLExecutorAgent, AnalystAgent) to interact with the MCP server.

### Configure MCP Client
Add the server to your MCP-compatible client configuration (e.g., VS Code, Claude Desktop, or other MCP clients):

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["start_server.py"],
      "cwd": "/path/to/vibe-coding-gemini-llm-execute-sql-tools"
    }
  }
}
```

- Replace `/path/to/` with your actual project path.
- The server loads credentials from `.env` file in the working directory.
- For virtual environments, use the full path to the Python interpreter.

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
ENABLE_SCHEMA_TOOLS=1  # Controls sample() tool

# Security Configuration (Recommended for Production)
QUERY_TIMEOUT_SECONDS=30   # Query timeout in seconds (P0 security)
CONNECT_TIMEOUT_SECONDS=10 # Connection timeout in seconds

# Table Allowlist (comma-separated, case-insensitive)
# Only allow access to specific tables - leave empty to allow all
ALLOWED_TABLES=products,orders,customers

# UNION Query Policy (0=disabled/safer, 1=enabled with table allowlist)
# When disabled: LLM executes separate queries (more secure, more tool calls)
# When enabled: UNION allowed but ALL tables must be in allowlist
ALLOW_UNION=0

# Token Optimization: Limit result size to prevent context overflow
MAX_RESULT_ROWS=50    # Max rows returned per query
MAX_RESULT_CHARS=8000 # Max characters in response
```

### MCP Client Integration
See `mcp_config.json` for a complete client configuration example.

## What Changed

### v2.0 Refactoring (December 2025) - Current Branch: `feature/v2.0-mcp-server-refactoring`

Major improvements following FastMCP best practices:

- **Extended SQL Support**: Now supports multiple read-only statement types
  - `SELECT`: Standard data retrieval
  - `SHOW`: Database metadata (SHOW TABLES, SHOW COLUMNS, etc.)
  - `DESCRIBE`: Table structure information
  - `EXPLAIN`: Query execution plan analysis
- **Tool Consolidation**: Reduced from 6 tools to 5, then expanded to 7 with new optimization tools
  - `validate_sql_query` + `execute_safe_sql` → merged into `query` (automatic validation)
  - Added new `list_tables` tool for database discovery
  - Renamed tools for clarity: `check_connection`, `describe_table`, `sample`
  - **New (Dec 23)**: Added `get_full_schema` and `get_table_summary` for token optimization
- **Optimized Server Instructions**: Reduced LLM's "exploratory behavior" (unnecessary tool calls)
  - Clear tool priority: `query` first, others only on error
  - Expected reduction: 4-5 tool calls → 1-2 per query
- **Security Enhancements (December 23, 2025)**:
  - Query timeout protection (P0 security)
  - Table allowlist support (`ALLOWED_TABLES`)
  - Configurable UNION policy (`ALLOW_UNION`)
  - Result truncation to prevent token explosion
- **Code Quality**: ~40% code reduction (~460 → ~280 lines) while maintaining functionality
- **Enhanced Metadata**: Added `ToolAnnotations` for better LLM tool selection
- **Lifespan Management**: Proper async resource lifecycle (FastMCP best practice)
- **SQL Injection Prevention**: Added identifier validation for dynamic table names

See [REFACTORING_LOG.md](REFACTORING_LOG.md) for detailed changes.

### v1.0 - MCP Service Architecture

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
- Ensure only read-only statements are allowed (SELECT, SHOW, DESCRIBE, EXPLAIN)
- Provide consistent interface across different AI platforms
- Maintain high performance and reliability
- Support multiple concurrent AI model connections

## Solution

### v2.0 - Optimized Tool Design (December 2025)

The v2.0 refactoring focuses on reducing LLM's "exploratory behavior" through:

```
Before (v1.0):                          After (v2.0):
LLM calls 4-5 tools per query           LLM calls 1-2 tools per query

check_connection                        query (PRIMARY)
    ↓                                      ↓
list_tables                             [only on error]
    ↓                                      ↓
describe_table                          list_tables / describe_table
    ↓
query
```

**Key Optimizations:**
- Clear tool priority in server instructions
- Explicit "when NOT to use" guidance
- Correct/Wrong usage examples for LLM guidance
- Following Microsoft/OpenAI prompt engineering best practices

### v1.0 - MCP Service Architecture

Our solution implements a Model Context Protocol (MCP) server that provides standardized database access:

```
Traditional Approach:        MCP Service Approach:
LLM → Direct Function       LLM → MCP Client → MCP Server → Database
```

### Key Components

1. `start_server.py`: Server startup and environment validation
2. `mcp_sql_server.py`: Core MCP tool definitions and functionality (refactored v2.0)
3. `sql_safety_checker.py`: Original validation and execution logic (unchanged)
4. `test_mcp_functions.py`: Internal function tests
5. `test_mcp_client.py`: MCP protocol tests

### Implementation Strategy

**v1.0 Architecture:**
- Backward Compatibility: Original functionality preserved without modification
- Incremental Adoption: Can run alongside existing direct-call implementations
- Minimal Dependencies: Uses FastMCP framework for simplified development
- Environment-Based Configuration: Secure credential management through `.env` files

**v2.0 Optimizations:**
- Tool Consolidation: Merged validation + execution into single `query` tool
- Prompt Engineering: Optimized server instructions following best practices
- Metadata Enhancement: Added `ToolAnnotations` for better LLM tool selection
- Defensive Programming: SQL injection prevention for dynamic identifiers

## MCP Tools Exposed

The service exposes seven standardized MCP tools (refactored December 2025):

### 1. `query` (Primary Tool)
Purpose: Executes read-only SQL queries with automatic safety validation

This is the primary tool for all database operations. Safety validation is automatic - only read-only statements are allowed (SELECT, SHOW, DESCRIBE, EXPLAIN).

Input:
```json
{
  "sql": "SELECT COUNT(*) as total FROM products"
}
```

Output:
```json
{
  "success": true,
  "query": "SELECT COUNT(*) as total FROM products",
  "data": [
    {"total": 150}
  ],
  "row_count": 1
}
```
Note: `data` is a JSON-serializable list (typically a list of objects). For this query it looks like `[{"total": 150}]`.

### 2. `check_connection`
Purpose: Tests database connectivity and configuration

Output:
```json
{
  "connected": true,
  "message": "Database connection successful"
}
```

### 3. `list_tables`
Purpose: Lists all tables in the database with row counts

Output:
```json
{
  "success": true,
  "data": [
    {"table_name": "users", "row_count": 150},
    {"table_name": "products", "row_count": 500}
  ],
  "table_count": 2
}
```

### 4. `describe_table`
Purpose: Retrieves column information for a specific table

Input:
```json
{
  "table_name": "users"
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI"},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": ""}
  ],
  "column_count": 2
}
```

### 5. `sample` (Optional)
Purpose: Retrieves sample data from a specified table

**Note**: This tool is controlled by the `ENABLE_SCHEMA_TOOLS` environment variable (default: enabled)

Input:
```json
{
  "table_name": "users",
  "limit": 5
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "data": [
    {"id": 1, "name": "Alice"},
    {"id": 2, "name": "Bob"}
  ],
  "row_count": 2,
  "query": "SELECT * FROM `users` LIMIT 5"
}
```

### 6. `get_full_schema` (New - December 2025)
Purpose: Gets complete database schema (all tables and columns) in ONE call

Use this FIRST instead of calling `describe_table()` multiple times. Reduces tool calls and provides complete context upfront.

Output:
```json
{
  "success": true,
  "schema": {
    "users": {
      "row_count": 150,
      "columns": [
        {"name": "id", "type": "int", "nullable": "NO", "key": "PRI"},
        {"name": "name", "type": "varchar", "nullable": "YES", "key": ""}
      ]
    }
  },
  "table_count": 1,
  "total_columns": 2
}
```

### 7. `get_table_summary` (New - December 2025)
Purpose: Gets summary statistics for a table WITHOUT fetching raw data

Use this for quick analysis instead of `SELECT *` queries.

Input:
```json
{
  "table_name": "users"
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "total_rows": 150,
  "column_count": 5,
  "columns": [...],
  "is_large": true,
  "recommendation": "Table has 150 rows. Use 'SELECT ... LIMIT 10' for samples."
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
- 🔗 Connection check (`check_connection`)
  - Failure modes (e.g., missing env vars, unreachable DB): Returns `connected: false` and includes `config` with missing variables.
  - Success: Executes `SELECT 1 as test` and returns `connected: true`.
- ▶️ Execution (`query`)
  - Unsafe queries: Blocked at validation with `success: false` and a clear message.
  - Safe queries:
    - With valid DB connectivity: Returns serialized rows (JSON-serializable) and `row_count`.
    - Without valid connectivity: Returns `success: false` with an error message.
- 📊 Table Discovery (`list_tables`, `describe_table`)
  - list_tables: Returns list of tables with row counts
  - describe_table: Returns detailed column information including types and constraints
- 📋 Sample Data (`sample`) - **Optional Feature**
  - Retrieves limited sample rows from specified tables
  - Enforces maximum limit of 20 rows for safety
  - Returns actual query executed for transparency
  - Can be disabled via `ENABLE_SCHEMA_TOOLS=0`
- 🧾 Response shape
  - Tools return structured dictionaries with stable keys (`is_safe`, `success`, `message`, `data`, etc.).
  - For MCP tools, `data` / `test_result` are JSON-serializable values (typically a list of objects, e.g., `[{"total": 150}]`).
  - If you call `sql_safety_checker.execute_sql` directly (bypassing MCP), you will get raw Row/tuple lists instead.

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
- [Refactoring Log](REFACTORING_LOG.md): December 2025 refactoring changes documentation
- [MCP Client Test Guide](TEST_MCP_CLIENT_GUIDE.md): Guide for testing MCP server via client
- [Prompt Engineering Best Practices](PROMPT_ENGINEERING_BEST_PRACTICES.md): Guidelines for MCP tool descriptions and prompts

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