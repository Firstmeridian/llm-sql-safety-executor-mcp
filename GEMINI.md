# Gemini Project Context

## Project Overview

This project is a Python-based tool designed to allow Large Language Models (LLMs) to safely execute SQL queries. It has evolved from simple function calls to a complete **Model Context Protocol (MCP) server** architecture, providing standardized, secure, and scalable LLM integration.

The project provides:
1. **Core SQL Safety Functions**: Validation and execution of read-only SQL queries
2. **MCP Server**: Standardized protocol server exposing SQL tools to LLMs
3. **Configuration Management**: Flexible environment-based configuration
4. **Easy Deployment**: User-friendly server startup and management

The primary technologies used are:
- **Python** as the programming language
- **MCP (Model Context Protocol)** for standardized LLM tool integration
- **sqlparse** for SQL query validation
- **SQLAlchemy** for database connection and execution, using a connection pool
- **mysql-connector-python** as the database driver for MySQL
- **python-dotenv** for managing database credentials through a `.env` file

## Key Files

### Core Implementation
*   `sql_safety_checker.py`: The original core logic containing:
    *   `is_sql_safe(sql_query)`: A function that checks if a SQL query contains only `SELECT` statements
    *   `execute_sql(sql_query)`: A function that first validates the query using `is_sql_safe` and then executes it against the database

### MCP Server Architecture
*   `mcp_server.py`: **MCP server implementation** that exposes SQL tools via the Model Context Protocol:
    *   `is_sql_safe` tool: Validates SQL queries for safety
    *   `execute_sql` tool: Executes validated SQL queries with comprehensive error handling
    *   Full async/await support for concurrent operations
    *   Structured JSON responses with detailed error information

*   `server_config.py`: **Configuration management** for the MCP server:
    *   Environment variable loading
    *   Database connection configuration
    *   Server settings and logging configuration

*   `start_server.py`: **Easy deployment script** with:
    *   Dependency checking and validation
    *   Configuration verification
    *   User-friendly startup process and error handling

### Testing and Demonstration
*   `demo_mcp.py`: **Interactive demonstration** of MCP server features:
    *   Shows both safe and unsafe query examples
    *   Demonstrates tool registration and execution
    *   Performance testing scenarios

*   `test_mcp_server.py`: **Comprehensive testing** for MCP server functionality

### Project Configuration
*   `requirements.txt`: Lists all necessary Python packages including MCP dependencies
*   `.gitignore`: Standard Python `.gitignore` file to exclude unnecessary files from version control
*   `GEMINI.md`: This file, providing context for the Gemini CLI

## Building and Running

### Prerequisites
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment (Optional for testing):**
    Create a `.env` file in the root of the project with your database credentials:
    ```
    DB_USER=your_db_user
    DB_PASSWORD=your_db_password
    DB_HOST=your_db_host
    DB_NAME=your_db_name
    ```

### Running Options

#### Option 1: MCP Server (Recommended)
Start the standardized MCP server for LLM integration:
```bash
python start_server.py
```

This will:
- Check all dependencies
- Validate configuration
- Start the MCP server with stdio transport
- Provide status information and error handling

#### Option 2: Interactive Demonstration
Run the comprehensive demo showing all features:
```bash
python demo_mcp.py
```

This demonstrates:
- Tool registration and listing
- Safe query validation and execution
- Security enforcement for unsafe queries
- JSON response formatting

#### Option 3: Direct Function Usage (Legacy)
Use the original functions directly:
```bash
python sql_safety_checker.py
```

### Integration with LLM Platforms

The MCP server can be integrated with various LLM platforms:

**Claude Desktop Integration:**
Add to your `claude_desktop_config.json`:
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

**Custom Applications:**
Connect to the server via stdio transport using any MCP-compatible client.

## Development Conventions

*   **Version Control:** The project is managed using Git
*   **Branching:** The main development branch is `main`
*   **Remote Repository:** The code is hosted on GitHub at `https://github.com/Firstmeridian/vibe-coding-gemini-llm-execute-sql-tools.git`

## Architecture Overview

### MCP Server Design
The project follows the **Model Context Protocol (MCP)** specification, providing:

- **Standardized Tool Interface**: Two well-defined tools (`is_sql_safe`, `execute_sql`)
- **Async Operations**: Full async/await support for concurrent LLM interactions
- **Structured Responses**: JSON-formatted responses with comprehensive error handling
- **Security First**: Query validation before execution with detailed safety reporting
- **Connection Pooling**: Efficient database connections via SQLAlchemy

### Tool Specifications

**`is_sql_safe` Tool:**
- **Purpose**: Validates SQL queries for safety (SELECT-only operations)
- **Input**: `{"sql_query": "SQL statement"}`
- **Output**: `{"safe": boolean, "message": "description", "query": "original_query"}`

**`execute_sql` Tool:**
- **Purpose**: Executes validated SQL queries with full error handling
- **Input**: `{"sql_query": "SQL statement"}`
- **Output**: `{"success": boolean, "data": [...], "row_count": number, "query": "original_query"}`

### Security Features

1. **Query Validation**: All queries are parsed and validated before execution
2. **Read-Only Enforcement**: Only SELECT statements are allowed
3. **Error Isolation**: Database errors are caught and safely returned
4. **Input Sanitization**: Proper handling of SQL query strings

### Backward Compatibility

The original function-based API remains fully functional:
```python
from sql_safety_checker import is_sql_safe, execute_sql
# Existing code continues to work unchanged
```