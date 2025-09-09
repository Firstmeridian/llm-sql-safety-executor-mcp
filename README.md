# SQL Safety Checker - MCP Service

A Python-based tool that allows Large Language Models (LLMs) to safely execute SQL queries, now available as an MCP (Model Context Protocol) service.

## Features

- **SQL Query Validation**: Ensures only `SELECT` statements are allowed
- **Safe Query Execution**: Executes validated queries against a MySQL database
- **MCP Protocol Support**: Standardized interface for AI model integration
- **Connection Pooling**: Efficient database connection management via SQLAlchemy
- **Docker Support**: Easy containerized deployment

## Quick Start

### Traditional Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Run example
python sql_safety_checker.py
```

### MCP Service

```bash
# Install dependencies (including fastMCP)
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Run MCP server
python mcp_sql_server.py

# Test functionality
python test_mcp_functions.py
```

### Docker Deployment

```bash
docker build -t sql-safety-checker-mcp .
docker run --env-file .env sql-safety-checker-mcp
```

## MCP Tools Available

- **`validate_sql_query`**: Validate SQL queries for safety
- **`execute_safe_sql`**: Execute validated SELECT queries
- **`get_server_info`**: Get server capabilities and information
- **`check_database_connection`**: Test database connectivity

## Configuration

### Environment Variables

```bash
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
DB_NAME=your_database_name
```

### MCP Client Configuration

```json
{
  "mcpServers": {
    "sql-safety-checker": {
      "command": "python",
      "args": ["mcp_sql_server.py"],
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

## Safety Features

- Only `SELECT` statements are allowed for query execution
- SQL parsing validation using `sqlparse`
- Connection pooling with automatic reconnection
- Comprehensive error handling and reporting
- Environment-based configuration for security

## Requirements

- Python 3.12+
- MySQL database
- Dependencies listed in `requirements.txt`

## License

This project is part of the vibe-coding-gemini-llm-execute-sql-tools repository.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

For issues and questions, please refer to the GitHub repository issues section.