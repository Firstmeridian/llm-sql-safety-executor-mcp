# Release Notes v3.5 — Named Multi-Connection Read Tools and Query Skills

Date: 2026-05-30

## Summary

v3.5 adds server-configured named database connections while preserving the
legacy single-connection path. Read-only core tools and query Skills can now
target a configured `connection_id`; mutation Skills intentionally remain bound
to the default connection until a dedicated multi-connection write policy exists.

The main runtime invariant is now explicit: resolve the target connection first,
then run SQL policy, schema readiness checks, helper SQL, execution, metadata,
audit, and telemetry against that same connection. Unknown connection ids fail
closed and never fall back to the default.

## Highlights

- Added a named connection registry in `db_adapter.py` with `ConnectionPolicy`,
  `DatabaseConfig`, `get_connection_config()`, `list_connection_configs()`, and
  an adapter cache keyed by `connection_id`.
- Added `list_connections()` and optional `connection_id` parameters to
  read-only core tools: `query`, `check_connection`, `list_tables`,
  `describe_table`, `get_full_schema`, optional `get_table_summary`, and
  optional `sample`.
- Made query Skills connection-scoped for discovery, detail, execution,
  per-connection allowlists, schema readiness, `ToolResult.meta`, optional
  query audit, and telemetry.
- Preserved legacy behavior when `DB_CONNECTIONS` is unset or empty. In legacy
  mode, `DB_<ID>_*` variables and `DEFAULT_DB_CONNECTION` are ignored.
- Kept `SkillMetadata.databases` as a DB type compatibility field, not a
  connection-id allowlist.
- Added safe `connection_id` metadata to `ToolResult.meta`, optional telemetry,
  and Skills audit records without exposing DSNs, hosts, users, passwords,
  SQLite paths, SQL params, or returned rows.

## Security And Compatibility Fixes

- Hardened table allowlists to normalize backtick, double-quote, square-bracket,
  and schema-qualified table references before comparison.
- Changed public SQLite database display values to `sqlite:<connection_id>` for
  tools such as `check_connection()` and `list_tables()`; the configured file
  path remains internal.
- Updated `sql_safety_checker.execute_sql()` to resolve `connection_id` before
  SQL safety checks so unknown targets fail closed before policy evaluation.
- Clarified that query Skill SQL is startup-validated for read-only/structural
  safety and re-checked at runtime against the resolved target connection.
- Replaced stale documentation claims about CI enforcement with pytest/local
  guardrail wording. The repository still does not add a CI workflow in v3.5.

## Known Limits

- Mutation Skills are default-connection only in v3.5. Non-default discovery
  marks them non-executable with an explicit limitation reason.
- Result-size limits such as `MAX_RESULT_ROWS`, `MAX_RESULT_CHARS`, and schema
  overview caps remain process-wide.
- The adapter registry is process-local and lazy. It does not implement runtime
  config reload, credential refresh, LRU eviction, or connection-count limits.
- Query truncation still limits returned payload only; users should use `WHERE`,
  `LIMIT`, and `ORDER BY` to limit database work and stabilize result order.
- Telemetry remains opt-in and local JSONL only. It is sanitized but still
  operationally sensitive and should be protected by deployment controls.

## Configuration Notes

```env
DB_CONNECTIONS=mysql,analytics
DEFAULT_DB_CONNECTION=mysql

DB_MYSQL_TYPE=mysql
DB_MYSQL_USER=your_database_user
DB_MYSQL_PASSWORD=your_database_password
DB_MYSQL_HOST=your_database_host
DB_MYSQL_NAME=your_database_name
DB_MYSQL_ALLOWED_TABLES=products,orders,customers
DB_MYSQL_ALLOW_UNION=0

DB_ANALYTICS_TYPE=sqlite
DB_ANALYTICS_SQLITE_DATABASE_PATH=./sample_data/demo.db
DB_ANALYTICS_ALLOWED_TABLES=orders
DB_ANALYTICS_QUERY_TIMEOUT_SECONDS=30
```

Only configured aliases are accepted. Tools and models cannot pass arbitrary
DSNs. Omitting `connection_id` uses `DEFAULT_DB_CONNECTION` when named
connections are enabled, or the legacy default connection otherwise.

## Validation

- Focused v3.5/policy regression suite: 44 passed.
- Full repository pytest suite: 231 passed.
- `git --no-pager diff --check`: no output.
- Python compile check for changed runtime/test files: no output.
- VS Code diagnostics for changed Python files: no errors found.

## Documentation Updated

- `README.md` and `README_ZH.md`
- `REFACTORING_LOG.md`
- `MCP_AGENTS_SKILLS_DESIGN.md`
- `SQLITE_ADAPTER_DESIGN.md`
- `skills/SAFETY.md`
- `TEST_MCP_CLIENT_GUIDE.md`
- `DESIGN_RISK_REGISTER.md` and `DESIGN_RISK_REGISTER_ZH.md`
- `.env.example`
