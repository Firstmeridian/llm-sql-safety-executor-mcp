Get a compact or full visible database schema overview in one call.

Use compact for exploring unknown databases, explaining table purposes, or
planning across tables. Compact columns are returned as [name, type] pairs;
tables with equal adapter-visible column metadata can share one group while
retaining every table and row estimate. This grouping does not establish
complete DDL, index, or constraint equivalence. Call compact directly instead
of list_tables when the task already needs broad columns. Use full only when
nullable, default, or key metadata is needed across several tables. The
parameter defaults to compact; request full explicitly when its additional
metadata is needed.

Results may be filtered by allowlist and truncated by MAX_SCHEMA_TABLES.

Works with both MySQL and SQLite databases.

Returns:
    Compact schema groups or full table schemas plus visible table counts