# Gemini Project Context

## Project Overview

This project is a Python-based tool designed to allow Large Language Models (LLMs) to safely execute SQL queries. It provides functions to first validate a given SQL query to ensure it is read-only (i.e., only `SELECT` statements are allowed) and then to execute the validated query against a database.

**NEW: MCP Service Implementation** - The project now includes a Model Context Protocol (MCP) service that wraps the original functionality, providing a standardized interface for AI models to interact with the SQL safety checker.

The primary technologies used are:
- **Python** as the programming language.
- **sqlparse** for SQL query validation.
- **SQLAlchemy** for database connection and execution, using a connection pool.
- **PyMySQL** as the database driver for MySQL.
- **python-dotenv** for managing database credentials through a `.env` file.
- **fastMCP** for creating the MCP service implementation.

## Key Files

*   `sql_safety_checker.py`: The core logic of the project resides here. It contains:
    *   `is_sql_safe(sql_query)`: A function that checks if a SQL query contains only `SELECT` statements.
    *   `execute_sql(sql_query)`: A function that first validates the query using `is_sql_safe` and then executes it against the database.
*   `mcp_sql_server.py`: MCP (Model Context Protocol) server implementation that wraps the SQL safety checker functionality (refactored December 2025):
    *   `query(sql)`: Primary MCP tool for executing SELECT queries (with automatic validation)
    *   `check_connection()`: MCP tool for testing database connectivity
    *   `list_tables()`: MCP tool for listing all tables with row counts
    *   `describe_table(table_name)`: MCP tool for retrieving table column information
    *   `sample(table_name, limit)`: **Optional** MCP tool for retrieving sample data (controlled by `ENABLE_SCHEMA_TOOLS`)
    *   `sql_assistant()`: MCP prompt for SQL query assistance
*   `test_mcp_functions.py`: **NEW** - Test script to verify MCP functions work correctly (internal tests)
*   `test_mcp_client.py`: **NEW** - MCP client test script that simulates real client connections
*   `mcp_config.json`: **NEW** - Configuration file for MCP client integration
*   `TEST_MCP_CLIENT_GUIDE.md`: **NEW** - Usage guide for the MCP client test script
*   `PROMPT_ENGINEERING_BEST_PRACTICES.md`: **NEW** - Guidelines for MCP tool descriptions and prompts
*   `REFACTORING_LOG.md`: **NEW** - December 2025 refactoring changes documentation
*   `Dockerfile`: **NEW** - Docker configuration for containerized deployment
*   `.env.example`: **NEW** - Example environment configuration file
*   `requirements.txt`: Lists all the necessary Python packages for this project (now includes fastMCP).
*   `.gitignore`: A standard Python `.gitignore` file to exclude unnecessary files from version control.
*   `GEMINI.md`: This file, providing context for the Gemini CLI.

## Building and Running

### Traditional Usage (Original)

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment:**
    Create a `.env` file in the root of the project with the following content, replacing the placeholders with your actual database credentials:
    ```
    DB_USER=your_db_user
    DB_PASSWORD=your_db_password
    DB_HOST=your_db_host
    DB_NAME=your_db_name
    
    # Optional: Feature toggles (1=enabled, 0=disabled)
    ENABLE_SCHEMA_TOOLS=1
    ```

3.  **Run the Example:**
    To run the example usage provided in the script, which includes setting up a test table and running safe and unsafe queries, execute:
    ```bash
    python sql_safety_checker.py
    ```

### MCP Service Usage (New)

The project now supports running as an MCP (Model Context Protocol) service, which provides a standardized way for AI models to interact with the SQL safety checker.

1.  **Install Dependencies (including fastMCP):**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment:**
    Copy the example environment file and configure it:
    ```bash
    cp .env.example .env
    # Edit .env with your actual database credentials
    ```

3.  **Run the MCP Server:**
    ```bash
    python start_server.py
    ```

4.  **Test MCP Functions:**
    ```bash
    # Test internal functions
    python test_mcp_functions.py
    
    # Test via MCP client (simulates real client)
    python test_mcp_client.py
    ```

5.  **Docker Deployment:**
    ```bash
    docker build -t sql-safety-checker-mcp .
    docker run --env-file .env sql-safety-checker-mcp
    ```

### MCP Client Integration

To integrate with an MCP-compatible AI system (e.g., VS Code, Claude Desktop), use the provided configuration:

```json
{
  "mcpServers": {
    "sql-safety-checker": {
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

## MCP Conversion: Feasibility and Benefits

### Feasibility Assessment

The conversion of this SQL safety checker tool to an MCP (Model Context Protocol) service has been successfully implemented and is **highly feasible**. The implementation leverages:

1. **FastMCP Framework**: Provides a simple, decorator-based approach to creating MCP services
2. **Existing Codebase**: Minimal changes required to the original SQL safety checker logic
3. **Standardized Protocol**: MCP provides a well-defined interface for AI-tool interaction
4. **Python Ecosystem**: Full compatibility with existing Python dependencies

### Key Benefits of MCP Implementation

#### 1. **Standardized Interface**
- Provides a consistent API for AI models to interact with SQL tools
- Follows MCP protocol specifications for reliable integration
- Supports multiple transport mechanisms (STDIO, HTTP, SSE)

#### 2. **Enhanced Security**
- Clear separation between AI model and database operations
- Structured error handling and validation
- Controlled access through MCP tool permissions

#### 3. **Improved Scalability**
- Can be deployed as a standalone service
- Supports multiple concurrent AI model connections
- Container-ready with Docker support

#### 4. **Better Integration**
- Compatible with MCP-enabled AI platforms and tools
- Easy to integrate into existing AI workflows
- Supports configuration through standard MCP client configs

#### 5. **Maintainability**
- Clean separation of concerns between business logic and protocol handling
- Structured tool definitions with proper typing
- Comprehensive error handling and logging

#### 6. **Extensibility**
- Easy to add new SQL-related tools to the MCP server
- Supports additional database types through simple configuration
- Can be extended with more sophisticated validation rules

### Available MCP Tools

The MCP service provides five main tools (refactored December 2025 for simplicity):

1. **`query`**: Primary tool - Executes SELECT queries with automatic safety validation
2. **`check_connection`**: Tests database connectivity and configuration
3. **`list_tables`**: Lists all tables in the database with row counts
4. **`describe_table`**: Retrieves table column information (similar to SQL DESCRIBE)
5. **`sample`**: **Optional** - Retrieves sample data from tables (controlled by `ENABLE_SCHEMA_TOOLS`)

### Available MCP Prompts

The MCP service provides one prompt template:

1. **`sql_assistant`**: Workflow guidance for SQL query assistance

### Deployment Options

- **Development**: Direct Python execution with STDIO transport
- **Production**: Docker container with environment variable configuration
- **Cloud**: Containerized deployment on cloud platforms
- **Local**: Integration with local AI development environments

### Recommendation

The MCP conversion is **highly recommended** for organizations wanting to:
- Integrate SQL safety checking into AI workflows
- Provide secure database access for AI applications
- Scale SQL validation across multiple AI models
- Maintain consistent interfaces for database operations

The implementation preserves all original functionality while adding the benefits of a standardized AI-tool interaction protocol.

## Development Conventions

*   **Version Control:** The project is managed using Git.
*   **Branching:** The main development branch is `main`.
*   **Remote Repository:** The code is hosted on GitHub at `https://github.com/Firstmeridian/vibe-coding-gemini-llm-execute-sql-tools.git`.
*   **Language:** Unless otherwise specified, all code, comments, and documentation in this project should be written in English.