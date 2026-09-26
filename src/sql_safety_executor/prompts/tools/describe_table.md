Get one selected table's full adapter-visible column metadata and row count
estimate. This is not complete DDL: indexes, foreign keys, checks, and other
backend-specific properties may be absent.

Do not call repeatedly to survey many tables. Use get_full_schema with
detail_level="compact" for broad columns, or detail_level="full" when full
adapter-visible column metadata is needed across several tables.

Returns column details plus approximate row count:
- MySQL: from INFORMATION_SCHEMA (InnoDB is a rough estimate)
- SQLite: from sqlite_stat1 or bounded sampling

If the backend cannot provide an estimate, row_count,
row_count_approximate, and is_large are null. Null means unknown, not an
empty or small table.

Includes is_large flag and recommendations for large tables.

Args:
    table_name: Name of the table to describe

Example arguments (replace the table and alias with the selected target):
    {"table_name": "orders", "connection_id": "analytics_demo_sqlite"}
    
Returns:
    Table structure with columns, row count, and query recommendations