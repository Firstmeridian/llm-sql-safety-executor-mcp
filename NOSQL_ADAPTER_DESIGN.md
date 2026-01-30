# NoSQL Adapter Design Document

## Overview

This document describes the architecture and implementation of NoSQL database support for the MCP SQL Server. The design follows a modular approach with separate adapters for each NoSQL database type.

## Architecture

```
               ┌─────────────────────────────────────┐
               │         MCP SQL Server              │
               │     (mcp_sql_server.py)             │
               └─────────────────────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
  ┌──────┴──────┐       ┌───────┴────────┐     ┌───────┴────────┐
  │  SQL Tools  │       │ MongoDB Tools  │     │  Redis Tools   │
  │   (query)   │       │(nosql_tools.py)│     │(nosql_tools.py)│
  └──────┬──────┘       └───────┬────────┘     └───────┬────────┘
         │                      │                      │
  ┌──────┴────────┐     ┌───────┴─────────┐    ┌───────┴───────┐
  │DatabaseAdapter│     │ MongoDBAdapter  │    │ RedisAdapter  │
  │(db_adapter.py)│     │(mongodb_adapter)│    │(redis_adapter)│
  └───────────────┘     └─────────────────┘    └───────────────┘
         │                      │                      │
  ┌──────┴──────┐       ┌───────┴───────┐      ┌───────┴───────┐
  │MySQL/SQLite │       │    PyMongo    │      │   redis-py    │
  └─────────────┘       └───────────────┘      └───────────────┘
```

## Design Principles

### 1. Separation of Concerns

- **NoSQL adapters are completely separate from SQL adapters**
- No shared inheritance between SQL and NoSQL (avoids leaky abstractions)
- Each adapter type has its own base class in `nosql_adapter.py`

#### Why NoSQL Adapters Don't Inherit from DatabaseAdapter

SQL and NoSQL databases have fundamentally different concepts:

| SQL Concept | MongoDB | Redis |
|-------------|---------|-------|
| Table | Collection | ❌ N/A |
| Row | Document | ❌ N/A |
| Column | Field (dynamic) | ❌ N/A |
| SQL Query | BSON Query/Aggregation Pipeline | Commands (GET, HGETALL...) |
| Schema | Schema-less | Data types (string, hash, list...) |

If we forced MongoDB to inherit `DatabaseAdapter`:

```python
# ❌ BAD DESIGN - Leaky Abstraction
class MongoDBAdapter(DatabaseAdapter):
    def execute_query(self, sql: str):
        # MongoDB doesn't use SQL!
        # Option 1: Raise NotImplementedError - violates Liskov Substitution
        # Option 2: SQL parser conversion - complex and incomplete
        # Option 3: Ignore parameter - interface deception
        raise NotImplementedError("MongoDB doesn't use SQL")
    
    def get_columns(self, table: str):
        # MongoDB is schema-less!
        # Each document can have different fields
        # This method is conceptually wrong
        ???
```

Following the **Interface Segregation Principle (ISP)**, each database type has its own dedicated interface:

```python
# ✅ CORRECT DESIGN - Separated Interfaces
class DocumentStoreAdapter(ABC):
    """Designed specifically for document databases"""
    def find(self, filter, projection, ...) -> ...
    def aggregate(self, pipeline) -> ...
    def list_collections(self) -> ...

class KeyValueStoreAdapter(ABC):
    """Designed specifically for key-value stores"""
    def get(self, key) -> ...
    def scan(self, pattern) -> ...
    def type(self, key) -> ...
```

#### Complete Class Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COMPLETELY INDEPENDENT CLASS HIERARCHIES                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SQL World                           NoSQL World                            │
│  ─────────                           ──────────                             │
│                                                                             │
│  DatabaseAdapter (ABC)               DocumentStoreAdapter (ABC)             │
│       │                                   │                                 │
│       ├── MySQLAdapter                   MongoDBAdapter                     │
│       │                                                                     │
│       └── SQLiteAdapter              KeyValueStoreAdapter (ABC)             │
│                                           │                                 │
│                                          RedisAdapter                       │
│                                                                             │
│                                      SearchEngineAdapter (ABC)              │
│                                           │                                 │
│                                          (future: Elasticsearch)            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Detailed Adapter Architecture (v2.3)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      COMPLETE ADAPTER ARCHITECTURE v2.3                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────┐     ┌─────────────────────────────┐        │
│  │   DatabaseAdapter (ABC)     │     │  DocumentStoreAdapter (ABC) │        │
│  │   (db_adapter.py)           │     │  (nosql_adapter.py)         │        │
│  ├─────────────────────────────┤     ├─────────────────────────────┤        │
│  │ + connect()                 │     │ + find()                    │        │
│  │ + execute()                 │     │ + aggregate()               │        │
│  │ + get_tables()              │     │ + count_documents()         │        │
│  │ + get_columns()             │     │ + list_databases()          │        │
│  │ + get_row_estimate()        │     │ + list_collections()        │        │
│  │ + check_connection()        │     │ + get_collection_schema()   │        │
│  │ + get_database_name()       │     │ + check_connection()        │        │
│  │ + close()                   │     │ + close()                   │        │
│  │ + db_type (property)        │     └──────────────┬──────────────┘        │
│  └──────────────┬──────────────┘                    │                       │
│                 │                                   │                       │
│     ┌───────────┴───────────┐              ┌────────▼────────┐              │
│     │                       │              │  MongoDBAdapter │              │
│ ┌───▼────────┐    ┌─────────▼───┐          │  (PyMongo)      │              │
│ │MySQLAdapter│    │SQLiteAdapter│          └─────────────────┘              │
│ │            │    │             │                                           │
│ │- SQLAlchemy│    │- SQLAlchemy │     ┌─────────────────────────────┐       │
│ │- PyMySQL   │    │- sqlite3    │     │  KeyValueStoreAdapter (ABC) │       │
│ │- QueuePool │    │- StaticPool │     │  (nosql_adapter.py)         │       │
│ │- MAX_EXEC  │    │- progress   │     ├─────────────────────────────┤       │
│ │  _TIME     │    │  _handler   │     │ + get() / mget()            │       │
│ └────────────┘    └─────────────┘     │ + hgetall()                 │       │
│                                       │ + lrange()                  │       │
│  ⚠️ Note: No SQLAdapter middle       │ + smembers() / zrange()     │       │
│    layer yet (Rule of Three)          │ + scan() / type() / exists()│       │
│                                       │ + ttl() / dbsize() / info() │       │
│                                       │ + check_connection()        │       │
│                                       │ + close()                   │       │
│                                       └──────────────┬──────────────┘       │
│                                                      │                      │
│                                             ┌────────▼────────┐             │
│                                             │  RedisAdapter   │             │
│                                             │  (redis-py)     │             │
│                                             └─────────────────┘             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        AdapterManager                               │    │
│  │  (adapter_manager.py) - Thread-safe Singleton                       │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  + get_sql_adapter() → DatabaseAdapter                              │    │
│  │  + get_mongodb_adapter() → MongoDBAdapter                           │    │
│  │  + get_redis_adapter() → RedisAdapter                               │    │
│  │  + is_datasource_enabled(name) → bool                               │    │
│  │  - Double-checked locking for thread safety                         │    │
│  │  - Lazy initialization                                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────┐  ┌──────────────────────────────────────┐     │
│  │  sql_safety_checker.py   │  │  nosql_safety_checker.py             │     │
│  ├──────────────────────────┤  ├──────────────────────────────────────┤     │
│  │  is_sql_safe()           │  │  MongoDBSafetyChecker                │     │
│  │  - sqlparse validation   │  │  - Block: $out, $merge, $where       │     │
│  │  - SELECT/SHOW/DESCRIBE  │  │  - Block: $function, $accumulator    │     │
│  │    /EXPLAIN only         │  │                                      │     │
│  │                          │  │  RedisSafetyChecker                  │     │
│  │                          │  │  - Command allowlist (READ-ONLY)     │     │
│  │                          │  │  - Block: SET, DEL, FLUSHALL, etc.   │     │
│  └──────────────────────────┘  └──────────────────────────────────────┘     │
│           ↑                                     ↑                           │
│           │                                     │                           │
│    (Completely Independent - Different validation mechanisms)               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Rule of Three

Following Martin Fowler's advice: "The first time you do something, you just do it. The second time you do something similar, you wince at the duplication, but you do the duplicate thing anyway. The third time you do something similar, you refactor."

- Current: 2 SQL adapters (MySQL, SQLite) - no SQLAdapter abstraction yet
- Future: When adding PostgreSQL, introduce SQLAdapter abstraction
- NoSQL: 2 adapters (MongoDB, Redis) with room for Elasticsearch

#### Why No SQLAdapter Intermediate Layer Yet

Even MySQL and SQLite, both "SQL" databases, have significant differences:

| Aspect | MySQL | SQLite |
|--------|-------|--------|
| Timeout Mechanism | `MAX_EXECUTION_TIME` hint | `progress_handler` callback |
| Connection Pool | `QueuePool` | `StaticPool` |
| Row Estimation | `INFORMATION_SCHEMA` | `sqlite_stat1` or sampling |
| Transaction Isolation | Multiple levels | Simple file locking |

With only 2 implementations, the "commonality" is not yet clear. Adding an intermediate layer now risks:
- Abstracting the wrong commonalities
- Limiting future flexibility
- Creating empty methods with no real value

#### Current vs Future Architecture

```
CURRENT (2 SQL adapters):                 FUTURE (3+ SQL adapters):
                                          
┌─────────────────┐                       ┌─────────────────┐
│ DatabaseAdapter │                       │ DatabaseAdapter │
└────────┬────────┘                       └────────┬────────┘
         │                                         │
    ┌────┴────┐                               ┌────┴────┐
    │         │                               │         │
  MySQL    SQLite                         SQLAdapter  NoSQLAdapter
                                              │            │
                                         ┌────┼────┐   ┌───┴───┐
                                         │    │    │   │       │
                                       MySQL SQLite PostgreSQL ...
```

When PostgreSQL is added:
1. We'll have 3 concrete instances to observe **real commonality**
2. Can more accurately abstract `SQLAdapter`
3. Refactoring cost is amortized across 3 classes

### 3. Dynamic Tool Registration

Tools are registered based on `ENABLED_DATASOURCES` environment variable:

```python
# Only registers if datasource is enabled
if is_datasource_enabled("mongodb"):
    register_mongodb_tools(mcp)
```

### 4. Security by Design

- **READ-ONLY operations only**
- Allowlist + Blocklist dual strategy
- Query validation before execution
- Result size limits for token protection

## Components

### 1. nosql_adapter.py

Base classes defining interfaces:

- `DocumentStoreAdapter` - For document databases (MongoDB)
- `KeyValueStoreAdapter` - For key-value stores (Redis)
- `SearchEngineAdapter` - For search engines (future Elasticsearch)

Configuration via environment variables with sensible defaults.

### 2. mongodb_adapter.py

MongoDB implementation using PyMongo:

**Features:**
- Connection pooling with `MongoClient` pool management
- Unified timeout via `timeoutMS` (PyMongo 4.2+)
- Document serialization (ObjectId → string)
- Schema inference by document sampling

**Methods:**
- `find()` - Query documents with filter
- `aggregate()` - Run aggregation pipeline
- `count_documents()` - Count documents
- `list_databases()` - List databases
- `list_collections()` - List collections
- `get_collection_schema()` - Infer schema from samples

### 3. redis_adapter.py

Redis implementation using redis-py:

**Features:**
- ConnectionPool for connection reuse
- Socket timeout for command timeout
- Support for all Redis data types
- SCAN-based iteration (non-blocking)

**Methods:**
- `get()`, `mget()` - String operations
- `hgetall()` - Hash operations
- `lrange()` - List operations
- `smembers()` - Set operations
- `zrange()` - Sorted set operations
- `scan()` - Key iteration
- `type()`, `exists()`, `ttl()` - Key inspection
- `dbsize()`, `info()` - Server info

### 4. nosql_safety_checker.py

Security validation for NoSQL operations:

**MongoDBSafetyChecker:**
- Blocks dangerous aggregation stages: `$out`, `$merge`
- Blocks server-side JavaScript: `$where`, `$function`, `$accumulator`
- Validates operator usage in queries

**RedisSafetyChecker:**
- Strict command allowlist (READ-ONLY only)
- Blocks: SET, DEL, FLUSHALL, CONFIG, DEBUG, SCRIPT, etc.

### 5. adapter_manager.py

Manages multiple database adapters:

- Lazy initialization (adapters created on first access)
- Singleton pattern for adapter instances
- **Thread-safe adapter creation** using double-checked locking
- Connection health checking
- Graceful cleanup on shutdown

### 6. nosql_tools.py

MCP tool definitions for NoSQL operations:

**Security Features:**
- **MongoDB identifier validation**: Validates database/collection names against injection attacks
- **Redis key validation**: Validates keys for empty values, length limits, and control characters
- **Sort parameter conversion**: Safely converts dict to list format for PyMongo compatibility

**MongoDB Tools:**
- `mongo_find` - Query documents
- `mongo_aggregate` - Aggregation pipeline
- `mongo_count` - Count documents
- `mongo_list_databases` - List databases
- `mongo_list_collections` - List collections
- `mongo_get_schema` - Infer collection schema

**Redis Tools:**
- `redis_get`, `redis_mget` - String values
- `redis_hgetall` - Hash values
- `redis_lrange` - List values
- `redis_smembers` - Set members
- `redis_zrange` - Sorted set values
- `redis_scan` - Key discovery
- `redis_type`, `redis_exists`, `redis_ttl` - Key info
- `redis_dbsize`, `redis_info` - Database info

## Configuration

### Environment Variables

```bash
# Datasource Selection
ENABLED_DATASOURCES=mysql,mongodb,redis  # Comma-separated list

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DEFAULT_DB=test
MONGODB_TIMEOUT_MS=5000
MONGODB_MAX_POOL_SIZE=10

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_SOCKET_TIMEOUT=5
REDIS_CONNECT_TIMEOUT=2

# Result Limits
MAX_RESULT_DOCS=1000      # MongoDB document limit
MAX_RESULT_KEYS=1000      # Redis key limit
```

### MCP Configuration Example

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "command": "python",
      "args": ["start_server.py"],
      "env": {
        "DB_TYPE": "mysql",
        "ENABLED_DATASOURCES": "mysql,mongodb,redis",
        "MONGODB_URI": "mongodb://localhost:27017",
        "REDIS_HOST": "localhost"
      }
    }
  }
}
```

## Security Model

### Defense in Depth

Multiple layers of security validation:

1. **Input Validation Layer** (nosql_tools.py)
   - MongoDB: Database/collection name validation
   - Redis: Key validation (empty, length, control characters)
   
2. **Query/Command Validation Layer** (nosql_safety_checker.py)
   - MongoDB: Operator blocklist, JavaScript detection
   - Redis: Command allowlist
   
3. **Adapter Layer** (mongodb_adapter.py, redis_adapter.py)
   - Connection security, timeout enforcement
   - Result size limits

### Thread Safety

AdapterManager uses **double-checked locking** pattern:
- Each adapter type has its own `threading.Lock`
- Prevents race conditions in multi-threaded environments
- Lazy initialization with thread-safe singleton creation

### MongoDB Security

1. **Input Validation:**
   - Database/collection names must be non-empty strings
   - Maximum length: 128 characters
   - Blocks dangerous characters: `$`, `.` (at start), `\x00`
   - Prevents MongoDB injection attacks

2. **Blocked Aggregation Stages:**
   - `$out` - Writes results to collection
   - `$merge` - Writes/merges to collection

2. **Blocked Query Operators:**
   - `$where` - Server-side JavaScript
   - `$function` - User-defined JavaScript
   - `$accumulator` - JavaScript in $group

3. **Pattern Detection:**
   - Rejects queries containing JavaScript patterns

### Redis Security

1. **Input Validation (Defense in Depth):**
   - Keys cannot be empty
   - Maximum key length: 512 characters
   - Blocks control characters (ASCII < 32)
   - Applied to all key-accepting tools

2. **Allowlist-Only Approach:**
   - Only explicitly allowed commands are permitted
   - All allowed commands are READ-ONLY

3. **Allowed Command Categories:**
   - String: GET, MGET, STRLEN
   - Hash: HGET, HGETALL, HKEYS, HVALS
   - List: LRANGE, LLEN, LINDEX
   - Set: SMEMBERS, SCARD, SISMEMBER
   - Sorted Set: ZRANGE, ZRANK, ZSCORE
   - Key: TYPE, EXISTS, TTL, SCAN
   - Server: DBSIZE, INFO, PING

4. **Blocked Commands (Examples):**
   - Write: SET, DEL, EXPIRE
   - Admin: FLUSHALL, CONFIG, DEBUG
   - Script: EVAL, SCRIPT, FUNCTION

## Tool Naming Convention

Following MCP best practices for tool naming:

- **SQL Tools:** `query`, `describe_table`, `list_tables` (existing)
- **MongoDB Tools:** `mongo_find`, `mongo_aggregate`, `mongo_count`
- **Redis Tools:** `redis_get`, `redis_hgetall`, `redis_scan`

Prefixes (`mongo_`, `redis_`) provide:
- Clear datasource identification
- Type safety for LLM tool selection
- Avoidance of tool name collisions

## Error Handling

All adapters follow consistent error handling:

1. **Connection Errors:** Return sanitized message without credentials
2. **Timeout Errors:** Include timeout value for context
3. **Permission Errors:** Generic "not authorized" message
4. **Validation Errors:** Specific message about what failed

## Future Extensibility

### Adding Elasticsearch

1. Create `elasticsearch_adapter.py` implementing `SearchEngineAdapter`
2. Add `ElasticsearchSafetyChecker` to `nosql_safety_checker.py`
3. Register `es_*` tools in `nosql_tools.py`
4. Add "elasticsearch" to `ENABLED_DATASOURCES` options

### Adding PostgreSQL

1. Create `postgres_adapter.py` implementing `DatabaseAdapter`
2. Consider introducing `SQLAdapter` intermediate layer (Rule of Three)
3. Add to `db_adapter.py` factory function

## Best Practices References

- [PyMongo Documentation](https://pymongo.readthedocs.io/)
- [redis-py Documentation](https://redis-py.readthedocs.io/)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/concepts/security)
- [MongoDB Security Checklist](https://www.mongodb.com/docs/manual/administration/security-checklist/)
- [Redis Security](https://redis.io/docs/management/security/)

## Version History

- **v3.0.0** - Initial NoSQL support (MongoDB + Redis)
- **v2.2.0** - SQLite support added
- **v2.0.0** - MySQL with enhanced security
