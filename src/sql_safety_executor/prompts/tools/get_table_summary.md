Table statistics with optional exact row count.

WARNING: exact_count=True runs COUNT(*) which may be slow on large tables
(full scan; MySQL can also see MDL contention). Use only when precision is required.

Default: Uses adapter estimates (INFORMATION_SCHEMA for MySQL;
sqlite_stat1 or bounded sampling for SQLite).

If an approximate estimate is unavailable, row_count,
row_count_approximate, and is_large are null. Exact counts retain
their ordinary integer/false/boolean values.

Args:
    table_name: Name of the table
    exact_count: If True, run COUNT(*) for precise count (slow on large tables)
    
Returns:
    Table statistics with row count, columns, and query hints