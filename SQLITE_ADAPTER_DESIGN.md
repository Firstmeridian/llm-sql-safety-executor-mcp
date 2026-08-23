# SQLite Adapter Design Document

**Version:** 3.7.0
**Date:** August 22, 2026
**Related:** [REFACTORING_LOG.md](REFACTORING_LOG.md) - v2.2 SQLite support, v3.5 named connections, and the v3.7 portable demo reset mutation

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

**Convention:** All new database adapters MUST inherit from `DatabaseAdapter` and implement the abstract methods plus the `db_type` property. v3.5 also standardizes configured adapter creation through `DatabaseConfig` and named `connection_id` aliases; direct adapter construction remains supported for tests and backward compatibility.

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

### 2. Read Query Timeout Implementation

| Database | Mechanism | Implementation |
|----------|-----------|----------------|
| MySQL read queries | `MAX_EXECUTION_TIME` | Session variable in milliseconds |
| SQLite | `set_progress_handler()` | Callback every N VM instructions |

MySQL write operations do not rely on `MAX_EXECUTION_TIME`: `execute_write()`
sets session `innodb_lock_wait_timeout` for InnoDB row-lock waits and keeps
PyMySQL socket timeouts as connection-level I/O controls. Long-running DML that
is not waiting on row locks may still require deployment-side statement limits.

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
| SQLite | StaticPool per configured connection | Single process-local connection per `connection_id`; SQLite file-level write locks still apply |

**SQLite StaticPool Convention:**
```python
self._engine = create_engine(
    database_url,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False}
)
```

**`check_same_thread=False`:** Required because SQLAlchemy may access the connection from different threads. StaticPool ensures single connection, but thread safety is managed by SQLAlchemy.

In v3.5 the adapter cache is keyed by configured `connection_id`. Two SQLite
connection ids that point to the same database file will each get their own
`StaticPool`/Engine, so SQLite's file-level locking is still the deployment's
write-concurrency boundary. This is acceptable for read-heavy MCP usage and is
documented as a risk for mutation-heavy SQLite deployments.

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

MySQL has `INFORMATION_SCHEMA.TABLES.TABLE_ROWS` for row count estimates, but **SQLite has no equivalent**. We implement a bounded estimate strategy:

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
│             If sample = 10000 → Return 10000 lower bound    │
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
        return sample_count  # Lower-bound estimate; exact COUNT(*) is opt-in
```

#### Accuracy Comparison

| Method | Accuracy | Performance | Condition |
|--------|----------|-------------|----------|
| sqlite_stat1 | Estimate (may be stale) | Very fast | Requires ANALYZE |
| Sampling < 10000 rows | Exact | Fast | Small tables |
| Sampling cap reached | Lower-bound estimate (`>= 10000`) | Fast and bounded | Large tables without ANALYZE |
| Explicit COUNT(*) | Exact | May be slow | Opt-in user SQL or `get_table_summary(exact_count=True)` |

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

### 2. Raw SHOW/DESCRIBE Limitation

**Compromise:** SQLite does not support `SHOW TABLES` or `DESCRIBE table` SQL syntax.

**Handling:**
- MCP tools (`list_tables`, `describe_table`) use adapter methods (work correctly)
- The v3.7 full MCP policy rejects raw `SHOW` for every adapter and directs
  schema discovery to those tools.
- A raw SQLite `DESCRIBE` form is not portable SQLite syntax and may fail at the
  adapter; prefer the dedicated tool.

**Convention:** Users should use MCP tools for schema discovery, not raw SQL.

### 3. Row Count Accuracy vs Performance

**Compromise:** SQLite row estimates may be less accurate than MySQL's `INFORMATION_SCHEMA.TABLES.TABLE_ROWS`.

**Mitigation:**
- Use `sqlite_stat1` when available (run `ANALYZE`)
- Sample-based fallback for tables < 10000 rows (exact)
- Return the 10000-row sample cap for larger tables as a lower-bound estimate
- Keep exact COUNT(*) as an explicit opt-in operation

### 4. No Catalog/Schema Separation in SQLite

**Compromise:** SQLite has no schema concept like MySQL's `DATABASE()`.

**Convention:** 
- `SQLiteAdapter.get_database_name()` returns the file path (or `:memory:`) for
    internal adapter compatibility
- MCP tool payloads and logs must not expose that path; public database display
    values use the safe alias `sqlite:<connection_id>`
- All tables are in the single "main" schema

### 5. Named Connection Registry Scope (v3.5)

**Compromise:** v3.5 supports multiple configured SQLite/MySQL connections, but
the registry is process-local and lazy. It does not implement credential refresh,
adapter LRU eviction, or per-request engine construction.

**Reason:** The existing server lifecycle already expects one long-lived adapter.
Extending that model to one long-lived adapter per configured `connection_id`
preserves compatibility while preventing cross-connection execution drift.

**Convention:** Tools resolve the target connection first and then use that same
adapter for quoting, schema discovery, SQL policy, execution, metadata, audit,
and telemetry. Unknown connection ids fail closed.

---

## Potential Issues & Limitations

### 1. Thread Safety with StaticPool

**Issue:** StaticPool uses a single connection shared across threads.

**Mitigation:** 
- `check_same_thread=False` allows cross-thread usage
- SQLAlchemy handles connection lifecycle
- MCP clients, including one stdio client, may issue concurrent calls. Do not
  infer serialization from the transport; mutation-heavy deployments must
  serialize writes at the application/deployment boundary.

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
- Core SQL tools remain read-only. Optional mutation skills can write only when `ENABLE_SKILLS=1` and `SKILLS_ALLOW_MUTATIONS=1` are enabled.
- StaticPool prevents connection contention within the process.
- For mutation-heavy or concurrent write workloads, prefer MySQL/PostgreSQL or serialize SQLite writes at the deployment boundary.

**Risk Level:** Minimal for read-only workloads; operationally relevant when mutation skills are enabled.

With named connections, this risk is per SQLite database file, not just per
connection id. If two configured SQLite aliases point at the same file, write
contention still occurs at the SQLite file-lock layer. v3.6 can authorize
non-default SQLite mutation targets, so deployments must review aliases that
share a file and should serialize writes or use a server database when write
concurrency is expected.

The v3.7 `reset-demo-order-to-pending` demo is portable across MySQL and SQLite
and assumes one business order per `orders.id`; supported schemas must enforce
that with `PRIMARY KEY` or `UNIQUE`. Its read-side cardinality check diagnoses
an already malformed fixture, but it is not an atomic replacement for the
constraint or a generic schema migration framework. The reset is a second
committed demo/test mutation, not a transactional rollback.

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

### Named Connection Variables (v3.5)

The legacy single-connection variables remain valid. Named connection variables
are gated by `DB_CONNECTIONS`: when it is unset or empty, both `DB_<ID>_*`
variables and `DEFAULT_DB_CONNECTION` are ignored so legacy `DB_TYPE` /
`SQLITE_DATABASE_PATH` settings keep their historical behavior. When
`DB_CONNECTIONS` is set, each listed connection id can define per-connection
SQLite settings:

| Variable | Example | Description |
|----------|---------|-------------|
| `DB_CONNECTIONS` | `trade_analysis_mysql,analytics_demo_sqlite` | Comma-separated configured connection ids |
| `DEFAULT_DB_CONNECTION` | `trade_analysis_mysql` | Default target when tool calls omit `connection_id` (active only when `DB_CONNECTIONS` is set) |
| `DB_<ID>_TYPE` | `DB_ANALYTICS_DEMO_SQLITE_TYPE=sqlite` | DB type for a named connection |
| `DB_<ID>_SQLITE_DATABASE_PATH` | `DB_ANALYTICS_DEMO_SQLITE_SQLITE_DATABASE_PATH=./sample_data/demo.db` | SQLite file path or `:memory:` for that connection |
| `DB_<ID>_QUERY_TIMEOUT_SECONDS` | `DB_ANALYTICS_DEMO_SQLITE_QUERY_TIMEOUT_SECONDS=30` | Per-connection read-query timeout |
| `DB_<ID>_CONNECT_TIMEOUT_SECONDS` | `DB_ANALYTICS_DEMO_SQLITE_CONNECT_TIMEOUT_SECONDS=10` | Per-connection connection timeout |
| `DB_<ID>_SQLITE_PROGRESS_HANDLER_INTERVAL` | `DB_ANALYTICS_DEMO_SQLITE_SQLITE_PROGRESS_HANDLER_INTERVAL=100` | Per-connection timeout check interval |
| `DB_<ID>_ALLOWED_TABLES` | `DB_ANALYTICS_DEMO_SQLITE_ALLOWED_TABLES=orders` | Per-connection allowlist |
| `DB_<ID>_ALLOW_UNION` | `DB_ANALYTICS_DEMO_SQLITE_ALLOW_UNION=0` | Per-connection UNION policy |

`connection_id` values must match `^[a-z][a-z0-9_]{0,63}$`. Tools and models
cannot pass arbitrary DSNs; they can only select configured aliases.
Use semantic aliases such as `trade_analysis_mysql`, `analytics_demo_sqlite`,
or `orders_primary`. Bare `mysql`/`sqlite` are legal but are easy to confuse
with database type values. Avoid `default` unless it is meaningful in the
deployment, because `DEFAULT_DB_CONNECTION` already selects the actual default.

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

### Tool Response Fields

All database-targeted MCP tools include `db_type`; v3.5 also includes the safe
`connection_id` alias in `ToolResult.meta` and many structured payloads:
```json
{
  "success": true,
  "connection_id": "analytics_demo_sqlite",
  "db_type": "sqlite",
  "data": [...]
}
```

**Convention:** LLM agents can use `db_type` to adjust their SQL dialect and
`connection_id` to confirm which configured target was used. Responses and logs
must not include DSNs, hosts, usernames, passwords, or SQLite file paths. If a
public payload needs `database_name` for SQLite, use `sqlite:<connection_id>`.

### Adapter Factory Pattern
```python
def create_adapter(db_type: str | None = None, *, config=None, connection_id=None) -> DatabaseAdapter:
    config = config or get_connection_config(connection_id)
    db_type = (db_type or config.db_type).lower()
    
    if db_type == "mysql":
        adapter = MySQLAdapter()
    elif db_type == "sqlite":
        adapter = SQLiteAdapter(config=config)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
    
    adapter.connect()
    return adapter
```

### Adapter Registry with Lazy Initialization
```python
_adapters: dict[str, DatabaseAdapter] = {}

def get_adapter(connection_id: str | None = None) -> DatabaseAdapter:
    config = get_connection_config(connection_id)
    if config.connection_id not in _adapters:
        _adapters[config.connection_id] = create_adapter(config=config)
    return _adapters[config.connection_id]

def reset_adapter(connection_id: str | None = None) -> None:
    """Reset for testing or reconfiguration."""
    ...
```

The older one-slot adapter snippet is now a legacy mental model. Calling
`get_adapter()` with no argument still returns the default connection adapter,
so existing direct callers retain their behavior.

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
| Existing SQLite config | ✅ Works | No changes needed when `DB_CONNECTIONS` is unset |
| `execute_sql()` signature | ✅ Compatible | Existing two-argument calls still work; optional `connection_id` added |
| `is_sql_safe()` function | ✅ Unchanged | Database-agnostic validation |
| MCP tool names | ✅ Compatible | Existing tools keep names and add optional `connection_id`; v3.5 adds `list_connections` |
| `.env` file | ✅ Compatible | Named connection vars are optional, defaults to legacy single-connection behavior |

### Breaking Changes

None. All existing MySQL and SQLite single-connection configurations continue to
work without modification. Omitted `connection_id` uses the default connection.

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | Added in v2.2 | Database adapter abstraction layer |
| `sql_safety_checker.py` | Modified | Now uses adapter; removed MySQL-specific code |
| `mcp_sql_server.py` | Modified | Uses adapter methods; adds `db_type` to responses |
| `.env.example` | Modified | Added SQLite configuration section |
| `.env` | User-local | Copy from `.env.example`; not modified by repository changes |
| `README.md` | Modified | v2.2 changelog, SQLite config docs |
| `README_ZH.md` | Modified | v2.2 changelog, SQLite config docs |
| `tests/conftest.py` | Added in v2.2 | Pytest fixtures for SQLite/MySQL tests |
| `tests/test_db_adapter.py` | Added in v2.2 | Unit tests for adapters |
| `tests/test_sqlite_integration.py` | Added in v2.2 | SQLite integration tests |
| `requirements.txt` | Modified | Added `pytest` dependency |
| `tests/test_multi_connection_v35.py` | Added in v3.5 | Named connection registry and MCP/Skills consistency tests |

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

v3.5 adds focused multi-connection coverage for connection registry behavior,
fail-closed unknown ids, same-connection policy/execution, metadata/audit
connection identity, and Skills display/execution alignment.

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

### Adding a Second SQLite Connection

```env
DB_CONNECTIONS=trade_analysis_mysql,analytics_demo_sqlite
DEFAULT_DB_CONNECTION=trade_analysis_mysql

DB_TRADE_ANALYSIS_MYSQL_TYPE=mysql
DB_TRADE_ANALYSIS_MYSQL_USER=your_database_user
DB_TRADE_ANALYSIS_MYSQL_PASSWORD=your_database_password
DB_TRADE_ANALYSIS_MYSQL_HOST=your_database_host
DB_TRADE_ANALYSIS_MYSQL_NAME=your_database_name

DB_ANALYTICS_DEMO_SQLITE_TYPE=sqlite
DB_ANALYTICS_DEMO_SQLITE_SQLITE_DATABASE_PATH=./sample_data/demo.db
DB_ANALYTICS_DEMO_SQLITE_ALLOWED_TABLES=orders
DB_ANALYTICS_DEMO_SQLITE_QUERY_TIMEOUT_SECONDS=30

# Optional strict v3.6+ mutation routing
SKILLS_ALLOW_MUTATION_CONNECTIONS=trade_analysis_mysql,analytics_demo_sqlite
DB_TRADE_ANALYSIS_MYSQL_ALLOW_MUTATIONS=1
DB_TRADE_ANALYSIS_MYSQL_MUTATION_SKILLS=update-order-status
DB_ANALYTICS_DEMO_SQLITE_ALLOW_MUTATIONS=1
DB_ANALYTICS_DEMO_SQLITE_MUTATION_SKILLS=update-order-status,reset-demo-order-to-pending
```

Core read-only tools and query Skills can then pass
`connection_id="analytics_demo_sqlite"`.
Mutation Skills remain default-connection only when
`SKILLS_ALLOW_MUTATION_CONNECTIONS` is omitted. When it is set, every target
also requires its per-connection write switch and skill allowlist. Preview and
execute must use the same connection-bound `preview_token`.

---

## References

- [SQLAlchemy Pool Types](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [SQLite set_progress_handler](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_progress_handler)
- [aiosqlite (for future async)](https://github.com/omnilib/aiosqlite)
- [SQLite PRAGMA statements](https://www.sqlite.org/pragma.html)
