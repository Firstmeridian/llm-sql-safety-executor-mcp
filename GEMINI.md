# Gemini Project Context

## Project Overview

This project is a Python-based tool designed to allow Large Language Models (LLMs) to safely execute SQL queries. It provides functions to first validate a given SQL query to ensure it is read-only (i.e., only `SELECT` statements are allowed) and then to execute the validated query against a database.

The primary technologies used are:
- **Python** as the programming language.
- **sqlparse** for SQL query validation.
- **SQLAlchemy** for database connection and execution, using a connection pool.
- **mysql-connector-python** as the database driver for MySQL.
- **python-dotenv** for managing database credentials through a `.env` file.

## Key Files

*   `sql_safety_checker.py`: The core logic of the project resides here. It contains:
    *   `is_sql_safe(sql_query)`: A function that checks if a SQL query contains only `SELECT` statements.
    *   `execute_sql(sql_query)`: A function that first validates the query using `is_sql_safe` and then executes it against the database.
*   `requirements.txt`: Lists all the necessary Python packages for this project.
*   `.gitignore`: A standard Python `.gitignore` file to exclude unnecessary files from version control.
*   `GEMINI.md`: This file, providing context for the Gemini CLI.

## Building and Running

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
    ```

3.  **Run the Example:**
    To run the example usage provided in the script, which includes setting up a test table and running safe and unsafe queries, execute:
    ```bash
    python sql_safety_checker.py
    ```

## Development Conventions

*   **Version Control:** The project is managed using Git.
*   **Branching:** The main development branch is `main`.
*   **Remote Repository:** The code is hosted on GitHub at `https://github.com/Firstmeridian/vibe-coding-gemini-llm-execute-sql-tools.git`.