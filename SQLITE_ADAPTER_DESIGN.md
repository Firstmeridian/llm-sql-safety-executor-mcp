# SQLite Adapter Design Document

**Version:** 2.2  
**Date:** January 15, 2026  
**Related:** [REFACTORING_LOG.md](REFACTORING_LOG.md) - v2.2 Update

---

## Table of Contents

1. [Design Decisions & Conventions](#design-decisions--conventions)
2. [Compromises & Trade-offs](#compromises--trade-offs)
3. [Potential Issues & Limitations](#potential-issues--limitations)
4. [Environment Variables](#environment-variables)
5. [Implementation Details](#implementation-details)
6. [Backward Compatibility](#backward-compatibility)
7. [Files Changed](#files-changed)
8. [Test Coverage](#test-coverage)
9. [Migration Guide](#migration-guide)

---

## Design Decisions & Conventions

### 1. ABC Base Class for Extensibility

**Decision:** Use Abstract Base Class pattern instead of Protocol or duck typing.

**Rationale:**
- Enforces interface contract at class definition time (not runtime)
- Clear extension point for future databases (PostgreSQL, MariaDB)
- IDE autocompletion and type checking support
- Explicit `@abstractmethod` documentation

**Convention:** All new database adapters MUST inherit from `DatabaseAdapter` and implement all 8 abstract methods plus the `db_type` property:

```python
from abc import ABC, abstractmethod

class DatabaseAdapter(ABC):
    @abstractmethod
    def connect(self) -> bool: ...
    
    @abstractmethod
    def execute(self, sql: str, timeout: int | None = None) -> list | str: ...
    
    @abstractmethod
    def get_tables(self) -> list[dict[str, Any]]: ...
    
    @abstractmethod
    def get_columns(self, table_name: str) -> list[dict[str, Any]]: ...
    
    @abstractmethod
    def get_row_estimate(self, table_name: str) -> int: ...
    
    @abstractmethod
    def check_connection(self) -> tuple[bool, str]: ...
    
    @abstractmethod
    def get_database_name(self) -> str | None: ...
    
    @abstractmethod
    def close(self) -> None: ...
    
    @property
    @abstractmethod
    def db_type(self) -> str: ...
```

### 2. Query Timeout Implementation

| Database | Mechanism | Implementation |
|----------|-----------|----------------|
| MySQL | `MAX_EXECUTION_TIME` | Session variable in milliseconds |
| SQLite | `set_progress_handler()` | Callback every N VM instructions |

**SQLite Timeout Details:**
```python
def timeout_handler():
    if time.time() - start_time > timeout:
        return 1  # Interrupt query
    return 0  # Continue

raw_conn.set_progress_handler(timeout_handler, SQLITE_PROGRESS_HANDLER_INTERVAL)
```

**Convention:** `SQLITE_PROGRESS_HANDLER_INTERVAL` controls the check frequency:
- Default: 100 (recommended balance)
- Lower value (e.g., 10) = more responsive, higher CPU overhead
- Higher value (e.g., 1000) = less overhead, less responsive

### 3. Connection Pooling Strategy

| Database | Pool Type | Reason |
|----------|-----------|--------|
| MySQL | QueuePool | Supports concurrent connections |
| SQLite | StaticPool | Single connection avoids file locking |

**SQLite StaticPool Convention:**
```python
self._engine = create_engine(
    database_url,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False}
)
```

**`check_same_thread=False`:** Required because SQLAlchemy may access the connection from different threads. StaticPool ensures single connection, but thread safety is managed by SQLAlchemy.

### 4. Metadata Query Mapping

SQLite lacks MySQL's `INFORMATION_SCHEMA` and `SHOW/DESCRIBE` commands:

| MySQL | SQLite Equivalent |
|-------|-------------------|
| `SHOW TABLES` | `SELECT name FROM sqlite_master WHERE type='table'` |
| `DESCRIBE table` | `PRAGMA table_info(table)` |
| `INFORMATION_SCHEMA.COLUMNS` | `PRAGMA table_info(table)` |
| `INFORMATION_SCHEMA.TABLES` | `sqlite_master` + sampling |

**Column Mapping Convention (PRAGMA table_info → Adapter format):**
```python
# PRAGMA returns: (cid, name, type, notnull, dflt_value, pk)
{
    "column_name": row[1],
    "data_type": row[2] or "TEXT",  # SQLite allows empty type
    "nullable": "NO" if row[3] else "YES",
    "key_type": "PRI" if row[5] else "",
    "default_value": row[4]
}
```

### 5. Row Count Estimation Strategy (SQLite)

MySQL has `INFORMATION_SCHEMA.TABLES.TABLE_ROWS` for row count estimates, but **SQLite has no equivalent**. We implement a two-tier fallback strategy:

**Multi-tier approach:**

```
┌─────────────────────────────────────────────────────────────┐
│                 SQLITE ROW ESTIMATION STRATEGY              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: Check sqlite_stat1 exists?                         │
│         ├── YES → Query stat for table                      │
│         │         └── Parse "row_count ..." format          │
│         └── NO → Fallback to Step 2                         │
│                                                             │
│  Step 2: Sample-based estimation                            │
│         ├── SELECT COUNT(*) FROM (SELECT 1 FROM t LIMIT 10000)│
│         │                                                   │
│         └── If sample < 10000 → Return sample (exact)       │
│             If sample = 10000 → Full COUNT(*) query         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### What is sqlite_stat1?

`sqlite_stat1` is SQLite's **internal statistics table**, populated when the user runs the `ANALYZE` command:

```sql
-- Generate statistics for a specific table
ANALYZE users;

-- Or for the entire database
ANALYZE;
```

After running `ANALYZE`, `sqlite_stat1` contains data like:

| tbl | idx | stat |
|-----|-----|------|
| users | users_pkey | 1500 1 |
| users | idx_email | 1500 1500 |

The `stat` field format is: `row_count col1_distinct col2_distinct ...`

The **first number is the estimated row count**.

#### Why is the Sampling Strategy Needed?

- `sqlite_stat1` only exists if the user has **manually run ANALYZE**
- Many SQLite databases have never had ANALYZE run
- The sampling strategy serves as a **fallback** that works even without statistics

#### Implementation Code

```python
def get_row_estimate(self, table_name: str) -> int:
    # Step 1: Try sqlite_stat1
    check_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
    if sqlite_stat1_exists:
        stat_sql = f"SELECT stat FROM sqlite_stat1 WHERE tbl = '{table_name}'"
        # Parse "1500 1 1500" format, take first number
        row_count = int(stat_str.split()[0])
        return row_count
    
    # Step 2: Sampling strategy
    sample_sql = f"SELECT COUNT(*) FROM (SELECT 1 FROM {table_name} LIMIT 10000)"
    if sample_count < 10000:
        return sample_count  # Exact value
    else:
        return execute(f"SELECT COUNT(*) FROM {table_name}")  # Full count
```

#### Accuracy Comparison

| Method | Accuracy | Performance | Condition |
|--------|----------|-------------|----------|
| sqlite_stat1 | Estimate (may be stale) | Very fast | Requires ANALYZE |
| Sampling < 10000 rows | Exact | Fast | Small tables |
| Full COUNT(*) | Exact | May be slow | Large tables |

**Convention:** `sqlite_stat1` is populated by running `ANALYZE table_name`. If users want accurate estimates, they should run ANALYZE periodically.

---

## Compromises & Trade-offs

### 1. Synchronous SQLite (Not aiosqlite)

**Compromise:** Using synchronous `sqlite3` instead of `aiosqlite`.

**Reason:**
- `set_progress_handler()` is a native sqlite3 feature, simpler to implement
- `aiosqlite` is a wrapper that may complicate progress handler integration
- MCP tool calls are already async at the FastMCP level

**Future Improvement:** Consider aiosqlite if async performance becomes critical.

### 2. SHOW/DESCRIBE Pass-through Limitation

**Compromise:** SQLite does not support `SHOW TABLES` or `DESCRIBE table` SQL syntax.

**Handling:**
- MCP tools (`list_tables`, `describe_table`) use adapter methods (work correctly)
- Direct `query("SHOW TABLES")` on SQLite will fail with syntax error

**Convention:** Users should use MCP tools for schema discovery, not raw SQL.

### 3. Row Count Accuracy vs Performance

**Compromise:** SQLite row estimates may be less accurate than MySQL's `INFORMATION_SCHEMA.TABLES.TABLE_ROWS`.

**Mitigation:**
- Use `sqlite_stat1` when available (run `ANALYZE`)
- Sample-based fallback for tables < 10000 rows (exact)
- Full COUNT(*) for larger tables (accurate but slower)

### 4. No Catalog/Schema Separation in SQLite

**Compromise:** SQLite has no schema concept like MySQL's `DATABASE()`.

**Convention:** 
- `get_database_name()` returns file path (or `:memory:`)
- All tables are in the single "main" schema

---

## Potential Issues & Limitations

### 1. Thread Safety with StaticPool

**Issue:** StaticPool uses a single connection shared across threads.

**Mitigation:** 
- `check_same_thread=False` allows cross-thread usage
- SQLAlchemy handles connection lifecycle
- MCP server typically handles one request at a time

**Risk Level:** Low for typical MCP usage patterns.

### 2. Progress Handler Performance Overhead

**Issue:** `set_progress_handler()` callback has CPU overhead.

**Mitigation:**
- Configurable interval via `SQLITE_PROGRESS_HANDLER_INTERVAL`
- Handler is removed after each query (`set_progress_handler(None, 0)`)
- Default interval 100 provides ~10μs overhead per check

**Tuning Guidance:**
```env
# Fast timeout response (higher CPU)
SQLITE_PROGRESS_HANDLER_INTERVAL=10

# Lower CPU (slower timeout response)
SQLITE_PROGRESS_HANDLER_INTERVAL=1000
```

### 3. Large Database File Locking

**Issue:** SQLite uses file-level locking for writes.

**Mitigation:**
- This MCP server is READ-ONLY (no writes)
- StaticPool prevents connection contention

**Risk Level:** Minimal for read-only workloads.

### 4. No Connection Pooling Benefits for SQLite

**Issue:** StaticPool maintains single connection, no concurrent query benefits.

**Rationale:** SQLite's file locking model doesn't benefit from connection pooling. Multiple connections to same file would cause lock contention.

### 5. Empty Data Type Handling

**Issue:** SQLite allows columns without explicit type (`CREATE TABLE t(x)`).

**Convention:** Default to `"TEXT"` when type is empty:
```python
"data_type": row[2] or "TEXT"
```

---

## Environment Variables

### New Variables for SQLite Support

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_TYPE` | `mysql` | Database type: `mysql` or `sqlite` |
| `SQLITE_DATABASE_PATH` | `:memory:` | SQLite file path or `:memory:` |
| `SQLITE_PROGRESS_HANDLER_INTERVAL` | `100` | VM ops between timeout checks |

### Example .env Configuration

```env
# =============================================================================
# Database Type Selection
# =============================================================================
# Options: mysql, sqlite
DB_TYPE=sqlite

# =============================================================================
# SQLite Configuration (only when DB_TYPE=sqlite)
# =============================================================================
# Path to SQLite database file, or :memory: for in-memory database
SQLITE_DATABASE_PATH=./my_database.db

# Progress handler interval for query timeout (lower = more responsive, higher CPU)
# Recommended: 100-1000
SQLITE_PROGRESS_HANDLER_INTERVAL=100
```

---

## Implementation Details

### New Tool Response Field

All MCP tools now include `db_type` in responses:
```json
{
  "success": true,
  "db_type": "sqlite",
  "data": [...]
}
```

**Convention:** LLM agents can use `db_type` to adjust their SQL dialect.

### Adapter Factory Pattern
```python
def create_adapter(db_type: str | None = None) -> DatabaseAdapter:
    db_type = (db_type or DB_TYPE).lower()
    
    if db_type == "mysql":
        adapter = MySQLAdapter()
    elif db_type == "sqlite":
        adapter = SQLiteAdapter(SQLITE_DATABASE_PATH)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
    
    adapter.connect()
    return adapter
```

### Global Adapter with Lazy Initialization
```python
_adapter: DatabaseAdapter | None = None

def get_adapter() -> DatabaseAdapter:
    global _adapter
    if _adapter is None:
        _adapter = create_adapter()
    return _adapter

def reset_adapter() -> None:
    """Reset for testing or reconfiguration."""
    global _adapter
    if _adapter is not None:
        _adapter.close()
        _adapter = None
```

### SQLite Timeout Handler
```python
def execute(self, sql: str, timeout: int | None = None) -> list | str:
    with self._engine.connect() as connection:
        raw_conn = connection.connection.dbapi_connection
        start_time = time.time()
        
        def timeout_handler():
            if time.time() - start_time > timeout:
                return 1  # Interrupt
            return 0
        
        raw_conn.set_progress_handler(timeout_handler, SQLITE_PROGRESS_HANDLER_INTERVAL)
        try:
            result = connection.execute(text(sql))
            return result.fetchall()
        finally:
            raw_conn.set_progress_handler(None, 0)  # Always cleanup
```

### Error Message Sanitization

Both adapters sanitize error messages for security:

```python
# MySQL error handling
def _handle_error(self, e: Exception, timeout: int) -> str:
    error_str = str(e)
    if "Access denied" in error_str:
        return "Error: Access denied"
    elif "doesn't exist" in error_str:
        return "Error: Table or column not found"
    elif "timeout" in error_str.lower():
        return f"Error: Query timeout exceeded ({timeout}s limit)"
    else:
        return "Error: Database query failed"

# SQLite error handling
def _handle_error(self, e: Exception) -> str:
    error_str = str(e)
    if "no such table" in error_str.lower():
        return "Error: Table or column not found"
    elif "syntax error" in error_str.lower():
        return "Error: SQL syntax error"
    elif "database is locked" in error_str.lower():
        return "Error: Database is locked"
    else:
        return "Error: Database query failed"
```

---

## Backward Compatibility

| Aspect | Status | Notes |
|--------|--------|-------|
| Existing MySQL config | ✅ Works | No changes needed |
| `execute_sql()` signature | ✅ Unchanged | Same parameters, same return format |
| `is_sql_safe()` function | ✅ Unchanged | Database-agnostic validation |
| MCP tool names | ✅ Unchanged | All tools work with both databases |
| `.env` file | ✅ Compatible | New vars are optional, defaults to MySQL |

### Breaking Changes

None. All existing MySQL configurations continue to work without modification.

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | **NEW** (749 lines) | Database adapter abstraction layer |
| `sql_safety_checker.py` | Modified | Now uses adapter; removed MySQL-specific code |
| `mcp_sql_server.py` | Modified | Uses adapter methods; adds `db_type` to responses |
| `.env.example` | Modified | Added SQLite configuration section |
| `.env` | Modified | Added SQLite configuration section |
| `README.md` | Modified | v2.2 changelog, SQLite config docs |
| `README_ZH.md` | Modified | v2.2 changelog, SQLite config docs |
| `tests/conftest.py` | **NEW** (318 lines) | Pytest fixtures for SQLite/MySQL tests |
| `tests/test_db_adapter.py` | **NEW** | Unit tests for adapters |
| `tests/test_sqlite_integration.py` | **NEW** | SQLite integration tests |
| `requirements.txt` | Modified | Added `pytest` dependency |

---

## Test Coverage

```
tests/
├── conftest.py              # Shared fixtures
├── test_db_adapter.py       # Adapter unit tests (26 tests)
│   ├── SQLite connection
│   ├── MySQL connection (mocked)
│   ├── execute() with timeout
│   ├── get_tables()
│   ├── get_columns()
│   └── Error handling
└── test_sqlite_integration.py  # Integration tests (27 tests)
    ├── MCP tool integration
    ├── Safety checker compatibility
    └── End-to-end workflows
```

**Total:** 53 new tests for SQLite support.

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run SQLite-only tests
pytest tests/test_sqlite_integration.py -v

# Run adapter tests
pytest tests/test_db_adapter.py -v

# Run with coverage
pytest tests/ --cov=db_adapter --cov-report=html
```

---

## Migration Guide

### For Existing MySQL Users
No action required. Default behavior unchanged.

### For New SQLite Users
```env
# .env
DB_TYPE=sqlite
SQLITE_DATABASE_PATH=/path/to/database.db
# or for in-memory database
SQLITE_DATABASE_PATH=:memory:
```

### Switching Between Databases

Simply change `DB_TYPE` in `.env`:
```env
# Use MySQL
DB_TYPE=mysql

# Use SQLite
DB_TYPE=sqlite
```

Restart the MCP server after changing database type.

---

## References

- [SQLAlchemy Pool Types](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [SQLite set_progress_handler](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_progress_handler)
- [aiosqlite (for future async)](https://github.com/omnilib/aiosqlite)
- [SQLite PRAGMA statements](https://www.sqlite.org/pragma.html)
