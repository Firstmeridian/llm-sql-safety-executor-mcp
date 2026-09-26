Visible database overview: list allowed tables with approximate row counts.

Use this lightweight tool when table names, counts, and approximate row
counts are enough. If broad columns or multi-table planning are needed,
call get_full_schema(detail_level="compact") directly; it already includes
returned table names and row estimates. Results may be truncated by
MAX_OVERVIEW_TABLES. Row counts are estimates:
- MySQL: from INFORMATION_SCHEMA (InnoDB is a rough estimate)
- SQLite: from sqlite_stat1 or bounded sampling

An individual row_count is null when the adapter cannot safely provide an
estimate; null does not mean that the table is empty.

Use describe_table(table_name=...) for full adapter-visible column metadata of one
selected table, not complete DDL.

Returns:
    Database name, visible table counts, and returned table rows