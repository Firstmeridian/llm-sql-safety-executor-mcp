"""
Tests for MCP SQL Server

Test Structure:
- conftest.py: Shared pytest fixtures (SQLite test DB, adapters)
- test_db_adapter.py: Unit tests for database adapters
- test_sqlite_integration.py: SQLite-specific integration tests
- test_sql_safety_checker.py: SQL safety validation tests (database-agnostic)

Usage:
    # Run all tests
    pytest tests/
    
    # Run with verbose output
    pytest tests/ -v
    
    # Run specific test file
    pytest tests/test_db_adapter.py
    
    # Run tests matching pattern
    pytest tests/ -k "sqlite"

Note:
    MySQL tests require a running MySQL server and proper .env configuration.
    SQLite tests use pytest's tmp_path fixture for isolation.
"""
