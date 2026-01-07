# SQL Safety Checker - MCP Service Implementation

English | [中文](README_ZH.md)

A Python-based tool that enables Large Language Models (LLMs) to safely execute read-only SQL queries through a standardized MCP (Model Context Protocol) service interface.

## Quick Start

### Use with VS Code (Quick Start)

Quickly integrate via `mcp.json` in VS Code to directly use this project's SQL tools within GitHub Copilot Chat, empowering it with database capabilities. [You can also use it in other MCP-supported AI assistants.](#configure-mcp-client)

#### 1. Preparation
*   Ensure VS Code is updated to the latest version.
*   Install the **GitHub Copilot Chat** extension.
*   Ensure project dependencies are installed (run `pip install -r requirements.txt` in the project path).
*   Configure environment: `cp .env.example .env` and edit `.env` with your database credentials. [See Configuration](#configuration)

#### 2. Create Configuration File
Create a `.vscode` folder in the project root (if it doesn't exist), and create a file named `mcp.json` inside it.

#### 3. Fill Configuration (Critical Step)
Copy the following content into `mcp.json` (if `mcp.json` already exists, append the configuration). **Make sure to modify it to your actual absolute paths**:

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/python", 
      "args": ["/absolute/path/to/start_server.py"],
      "cwd": "/absolute/path/to/project_root"
    }
  }
}
```

**Configuration Details:**
*   `command`: **Must** point to the absolute path of the Python interpreter in your virtual environment (e.g., `.venv/bin/python`), do not use the system `python` directly.
*   `args`: Absolute path to `start_server.py`.
*   `cwd`: Absolute path to the project root directory, ensuring `.env` can be read.

**Alternative: Configure via VS Code UI (Recommended)**

1. Complete "1. Preparation".
2. Open VS Code Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
3. Type and select `MCP: Add Server`. ![MCP: Add Server](readme_pic/MCP:AddServer.png)
4. Follow the prompts to add the details above (modify paths accordingly).

Both methods achieve the same result by generating the `mcp.json` file. Ensure `.vscode/mcp.json` contains the configuration above.

#### 4. Verification and Usage
1.  Restart VS Code or reload the window.
2.  Open GitHub Copilot Chat.
3.  Click the **Tools icon** near the model selection box.
4.  You should see `sql-safety-executor` and its tools (e.g., `query`, `list_tables`). Ensure they are checked. ![Add tools](readme_pic/Addtools.png)
5.  Ask directly in the chat: "List all tables" or "Query the first 5 rows of users table". ![ask](readme_pic/ask.png)![answer](readme_pic/answer.png)

*Note: Although tool usage is optimized, it is recommended to use lightweight models (e.g., GPT-5 mini) in GitHub Copilot Chat to avoid excessive request costs.*

#### Common Issues
*   **Tools not found?** Check the `Output` panel and switch to "GitHub Copilot" to see any errors.
*   **Path errors**: Windows users must escape backslashes in JSON (e.g., `C:\\Users\\...`).

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
ENABLE_SCHEMA_TOOLS=1    # Controls sample() tool
ENABLE_TABLE_SUMMARY=0   # Controls get_table_summary() tool (default: disabled)
                         # describe_table() already provides estimated row counts

# Large table threshold for is_large flag and query recommendations
# Tables exceeding this row count trigger LIMIT/aggregation hints
LARGE_TABLE_THRESHOLD=1000

# Security Configuration (Recommended for Production)
QUERY_TIMEOUT_SECONDS=30   # Query timeout in seconds (P0 security)
CONNECT_TIMEOUT_SECONDS=10 # Connection timeout in seconds

# Table Allowlist (comma-separated, case-insensitive)
# Only allow access to specific tables - leave empty to allow all
# Use "*" to explicitly allow all tables (required for UNION with all tables)
ALLOWED_TABLES=products,orders,customers

# UNION Query Policy
# IMPORTANT: UNION requires DUAL configuration to enable:
#   1. ALLOW_UNION=1
#   2. ALLOWED_TABLES=table1,table2 OR ALLOWED_TABLES=*
# If ALLOW_UNION=1 but ALLOWED_TABLES is empty, UNION will still be blocked.
ALLOW_UNION=0

# Token Optimization: Limit result size to prevent context overflow
# Set to 0 to disable truncation (for data export scenarios)
MAX_RESULT_ROWS=100      # Max rows returned per query (0=unlimited)
MAX_RESULT_CHARS=16000   # Max characters in response (0=unlimited)
MAX_SCHEMA_TABLES=50     # Max tables in get_full_schema (0=unlimited)
MAX_OVERVIEW_TABLES=100  # Max tables in list_tables (0=unlimited)
```

### MCP Client Integration
See `mcp_config.json` for a complete client configuration example.

## What Changed

### v2.1 Tool Optimization (January 2026)

Focused improvements on tool design and output consistency:

- **`get_table_summary` Now Optional**: Disabled by default (`ENABLE_TABLE_SUMMARY=0`) since `describe_table()` already provides estimated row counts. Enable only when exact COUNT(*) is required.
- **Enhanced `describe_table`**: Now returns `row_count`, `row_count_approximate`, `is_large` flag, and `recommendation` for query planning hints.
- **Restructured `list_tables` Output**:
  - `data` → `tables` for clarity
  - Added `database_name`, `returned_table_count`, `total_tables`, `truncated`, `truncation_note`
- **Consistent Field Naming**: `returned_table_count` vs `total_tables` convention applied to both `list_tables` and `get_full_schema`
- **New Environment Variables**:
  - `ENABLE_TABLE_SUMMARY=0` - Control `get_table_summary()` tool
  - `LARGE_TABLE_THRESHOLD=1000` - Threshold for `is_large` flag
  - `MAX_OVERVIEW_TABLES=100` - Max tables in `list_tables()`
- **AutoGen Agent Prompts Updated**: Removed `get_table_summary()` references, updated workflow to `list_tables() → describe_table()` pattern

See [REFACTORING_LOG.md](REFACTORING_LOG.md) for detailed changes.

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

The service exposes 5-7 standardized MCP tools (depending on configuration):

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
Purpose: Database overview - lists all tables with names and approximate row counts

Lightweight discovery tool for initial exploration. Row counts are estimates from INFORMATION_SCHEMA (InnoDB may vary ±40%).

Output:
```json
{
  "success": true,
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [
    {"table_name": "users", "row_count": 150},
    {"table_name": "products", "row_count": 500}
  ],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null,
  "hint": "Row counts are estimates (InnoDB ±40%). total_tables = visible after allowlist."
}
```

### 4. `describe_table`
Purpose: Get table structure - columns, row count estimate, and query hints

Returns column details plus approximate row count from INFORMATION_SCHEMA (avoids COUNT(*) full table scan). Includes `is_large` flag for query planning.

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
  "row_count": 1500,
  "row_count_approximate": true,
  "column_count": 5,
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI"},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": ""}
  ],
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
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

### 6. `get_full_schema`
Purpose: Gets complete database schema (all tables and columns) in ONE call

Use for multi-table JOINs or when you need all table structures at once. For single tables, prefer `describe_table()`.

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
  "returned_table_count": 1,
  "total_tables": 1,
  "total_columns": 2,
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null,
  "hint": "Row counts are estimates (InnoDB ±40%). Use LIMIT for large tables (row_count > 1000). total_tables = visible after allowlist."
}
```

### 7. `get_table_summary` (Optional)
Purpose: Gets table statistics with optional exact row count via COUNT(*)

**Note**: This tool is controlled by `ENABLE_TABLE_SUMMARY` environment variable (default: **disabled**). The `describe_table()` tool already provides estimated row counts, so this tool is only needed when exact counts are required.

**Warning**: `exact_count=True` runs COUNT(*) which may be slow on large InnoDB tables (full table scan).

Input:
```json
{
  "table_name": "users",
  "exact_count": false
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "row_count": 150,
  "row_count_approximate": true,
  "column_count": 5,
  "columns": [...],
  "is_large": true,
  "recommendation": "Large table (~150 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
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