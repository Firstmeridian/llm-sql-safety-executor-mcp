Get one selected table's full adapter-visible column metadata, indexes and
row count estimate. Each index lists name, primary, unique and ordered key
columns (null for an expression part); SQLite adds partial, and its implicit
rowid primary key has name null. This is not complete DDL: foreign
keys, checks, index comments and expressions are absent.

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
    Table structure with columns, indexes, row count, and query recommendations.
    indexes_status is "unavailable" (indexes null) when index metadata could
    not be read; that does not mean the table has no indexes.