# Gemini Project Context

## Project Overview

This project is a Python-based tool designed to allow Large Language Models (LLMs) to execute conservatively filtered read-only SQL queries against the supported MySQL and SQLite adapters. The full MCP policy accepts one `SELECT`, `DESCRIBE`, or non-ANALYZE `EXPLAIN` statement and directs metadata discovery to dedicated tools instead of raw `SHOW`. It rejects nested write DML and `EXPLAIN ANALYZE`, and does not claim comprehensive semantic analysis for arbitrary SQL dialects.

**MCP Service Implementation** - The project includes a Model Context Protocol (MCP) service that wraps the original functionality, providing a standardized interface for AI models to interact with the SQL safety checker.

The primary technologies used are:
- **Python** as the programming language.
- **sqlparse** for SQL query validation.
- **SQLAlchemy** for database connection and execution, using a connection pool.
- **PyMySQL** as the database driver for MySQL.
- **python-dotenv** for managing database credentials through a `.env` file.
- **fastMCP** for creating the MCP service implementation.

## Key Files

*   `sql_safety_checker.py`: The core logic of the project resides here. It contains:
    *   `is_sql_safe(sql_query)`: Provides the low-level statement-shape compatibility check (`SELECT` / `SHOW` / `DESCRIBE` / non-ANALYZE `EXPLAIN`). The MCP server adds the authoritative full policy, including one-statement enforcement, table scope, and rejection of raw `SHOW`.
    *   `execute_sql(sql_query)`: Validates the query using `is_sql_safe` and then executes it against the database.
*   `mcp_sql_server.py`: MCP (Model Context Protocol) server implementation that wraps the SQL safety checker functionality (refactored December 2025):
    *   `query(sql)`: Primary MCP tool for executing read-only SQL queries (with automatic validation)
    *   `check_connection()`: MCP tool for testing database connectivity
    *   `list_tables()`: MCP tool for listing visible/allowed tables with estimated row counts; output may be truncated
    *   `describe_table(table_name)`: MCP tool for retrieving table column info and query recommendations
    *   `get_full_schema()`: MCP tool for getting a visible schema overview in one call; output may be truncated
    *   `get_table_summary(table_name)`: **Optional** MCP tool for getting table statistics (controlled by `ENABLE_TABLE_SUMMARY`, default disabled)
    *   `sample(table_name, limit)`: **Optional** MCP tool for retrieving sample data (controlled by `ENABLE_SCHEMA_TOOLS`, default enabled)
    *   `sql_assistant()`: MCP prompt for SQL query assistance
*   `test_mcp_functions.py`: Test script to verify MCP functions work correctly (internal tests)
*   `test_mcp_client.py`: MCP client test script that simulates real client connections
*   `mcp_config.json`: Configuration file for MCP client integration
*   `TEST_MCP_CLIENT_GUIDE.md`: Usage guide for the MCP client test script
*   `PROMPT_ENGINEERING_BEST_PRACTICES.md`: Guidelines for MCP tool descriptions and prompts
*   `REFACTORING_LOG.md`: Refactoring and release-history documentation
*   `.env.example`: Example environment configuration file
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
    ENABLE_TABLE_SUMMARY=0
    
    # Optional: Security configuration
    QUERY_TIMEOUT_SECONDS=30
    CONNECT_TIMEOUT_SECONDS=10
    ALLOWED_TABLES=products,orders,customers
    ALLOW_UNION=0

    # Optional: Token protection / truncation
    MAX_RESULT_ROWS=100
    MAX_RESULT_CHARS=16000
    MAX_SCHEMA_TABLES=50
    MAX_OVERVIEW_TABLES=100

    # Optional: Large table threshold (for is_large hints)
    LARGE_TABLE_THRESHOLD=1000
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
    # Not documented in README.md.
    # If you need container deployment, add a Dockerfile and document it accordingly.
    ```

### MCP Client Integration

To integrate with an MCP-compatible AI system (e.g., VS Code, Claude Desktop), use the provided configuration:

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["start_server.py"],
      "cwd": "/path/to/llm-sql-safety-executor-mcp"
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
- Uses STDIO transport for broad MCP client compatibility

#### 2. **Enhanced Security**
- Clear separation between AI model and database operations
- Structured error handling and validation
- Controlled access through MCP tool permissions

#### 3. **Improved Scalability**
- Can be deployed as a standalone service
- Supports multiple concurrent AI model connections

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

The MCP service provides 6-12 tools (depending on configuration):

1. **`query`**: Primary tool - Executes read-only SQL queries with automatic safety validation
2. **`check_connection`**: Tests database connectivity and configuration
3. **`list_connections`**: Lists configured connection aliases and non-sensitive policy summaries (no DSNs/credentials/paths)
4. **`list_tables`**: Lists visible/allowed tables in the target connection with estimated row counts; output may be truncated
5. **`describe_table`**: Retrieves table column info and query recommendations
6. **`get_full_schema`**: Gets a visible schema overview in one call; output may be truncated
7. **`get_table_summary`**: **Optional** - Gets table statistics (controlled by `ENABLE_TABLE_SUMMARY`, default disabled)
8. **`sample`**: **Optional** - Retrieves sample data from tables (controlled by `ENABLE_SCHEMA_TOOLS`, default enabled)
9. **`list_skills`**: **Optional** - Lists available Skills for the target connection when `ENABLE_SKILLS=1`
10. **`get_skill_detail`**: **Optional** - Retrieves detailed metadata/readiness for one Skill when `ENABLE_SKILLS=1`
11. **`execute_query_skill`**: **Optional** - Executes a cached query Skill on the target connection when `ENABLE_SKILLS=1`
12. **`execute_mutation_skill`**: **Optional** - Previews a mutation Skill on an authorized configured connection and executes it only on the same connection with the returned `preview_token` when both `ENABLE_SKILLS=1` and `SKILLS_ALLOW_MUTATIONS=1`

v3.5 adds optional `connection_id` to read-only core tools and query Skills.
Omitting it preserves default-connection behavior. Tools cannot accept arbitrary
DSNs from the model. Mutation Skills use the default connection unless strict
named-write policy is configured with `SKILLS_ALLOW_MUTATION_CONNECTIONS` and
matching per-connection mutation settings.

v3.7 Skill frontmatter may optionally declare plural `connection_ids` to
restrict a Skill to valid business-alias identifiers. Only currently configured
members can execute; portable unconfigured members remain unavailable metadata.
This scope only narrows the existing DB-type and server policy intersection; it
never creates or authorizes a connection, and omission preserves prior behavior.
The release also includes
a one-shot stdio approval-host example. That client flow is not server-verifiable
human identity and does not add multi-user HTTP mutation support.

### Available MCP Prompts

The MCP service provides one prompt template:

1. **`sql_assistant`**: Guidance (heuristics) for SQL query assistance

### Deployment Options

- **Development**: Direct Python execution with STDIO transport
- **Local**: Integration with local AI development environments

### Recommendation

The MCP conversion is **highly recommended** for organizations wanting to:
- Integrate SQL safety checking into AI workflows
- Provide secure database access for AI applications
- Scale SQL validation across multiple AI models
- Maintain consistent interfaces for database operations

The implementation is incremental and largely compatible, but security
boundaries may intentionally narrow behavior. For example, v3.7 rejects raw
SHOW and multiple statements in the full MCP policy and validates known Skill
metadata values strictly. Do not describe compatibility more broadly than the
current release notes and tests support.

## Development Conventions

*   **Version Control:** The project is managed using Git.
*   **Branching:** The main development branch is `main`.
*   **Remote Repository:** The code is hosted on GitHub at `https://github.com/Firstmeridian/llm-sql-safety-executor-mcp.git`.
*   **Language:** Unless otherwise specified, all code, comments, and documentation in this project should be written in English.
*   **Virtual Environment:** Development is typically done in a Python virtual environment (venv). The venv is located at `.venv/` in the project root.
*   **Best Practices Reference:** Follow best practices from web and GitHub sources, especially:
    - **Microsoft** (primary reference): AutoGen framework patterns, Azure Logic Apps agent guidelines
    - **Anthropic**: MCP protocol specifications, tool design patterns
    - **Google**: Gemini API best practices, token optimization guidelines
    - **FastMCP**: Server implementation patterns, context management
