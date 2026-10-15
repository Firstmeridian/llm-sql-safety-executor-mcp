"""Public, table-free/MySQL-read-only cases for reproducible v3.8.1 probes."""
CASES = [
    ("cte_exact", "WITH F AS (SELECT 7 AS n) SELECT n FROM F", ["mysql", "sqlite"]),
    ("cte_ascii_case", "WITH F AS (SELECT 7 AS n) SELECT n FROM f", ["mysql", "sqlite"]),
    ("cte_column_list", "WITH F(n) AS (SELECT 7) SELECT n FROM f", ["mysql", "sqlite"]),
    ("cte_physical_shadow", "WITH orders AS (SELECT 7 AS n) SELECT n FROM orders", ["mysql", "sqlite"]),
    ("cte_nonrecursive_self", "WITH orders AS (SELECT COUNT(*) AS n FROM orders) SELECT n FROM orders", ["mysql", "sqlite"]),
    ("cte_forward", "WITH first_cte AS (SELECT COUNT(*) AS n FROM orders), orders AS (SELECT 7 AS n) SELECT n FROM first_cte", ["mysql", "sqlite"]),
    ("cte_nested_shadow", "WITH F AS (SELECT 7 AS n) SELECT (WITH F AS (SELECT 9 AS n) SELECT n FROM f) AS n FROM F", ["mysql", "sqlite"]),
    ("cte_recursive", "WITH RECURSIVE F(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM f WHERE n<3) SELECT MAX(n) AS n FROM F", ["mysql", "sqlite"]),
    ("cte_recursive_implicit", "WITH F(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM f WHERE n<3) SELECT MAX(n) AS n FROM F", ["mysql", "sqlite"]),
    ("cte_ordered_dependencies", "WITH first_cte AS (SELECT COUNT(*) AS n FROM orders), second_cte AS (SELECT n FROM first_cte) SELECT n FROM second_cte", ["mysql", "sqlite"]),
    ("cte_quoted_space_alias", 'WITH " F " AS (SELECT 7 AS n) SELECT n FROM " f "', ["sqlite"]),
    ("cte_quoted_space_physical", 'WITH F AS (SELECT 7 AS n) SELECT n FROM " f "', ["sqlite"]),
    ("cte_unicode_identity", 'WITH K AS (SELECT 7 AS n) SELECT n FROM "K"', ["sqlite"]),
    ("cte_qualified_physical", "WITH f AS (SELECT 7 AS n) SELECT n FROM main.f", ["sqlite"]),
    ("sqlite_in_table", "SELECT 7 IN f AS n", ["sqlite"]),
    ("sqlite_not_in_table", "SELECT 7 NOT IN f AS n", ["sqlite"]),
    ("sqlite_pragma_object", "SELECT COUNT(*) AS n FROM pragma_table_info('orders')", ["sqlite"]),
    ("literal_function_names", "SELECT 'GET_LOCK(1), SLEEP(9), BENCHMARK(2,3)' AS label", ["mysql", "sqlite"]),
    ("quoted_function_columns", 'SELECT "SLEEP", "BENCHMARK" FROM orders', ["sqlite"]),
    ("ordinary_function", "SELECT ABS(-7) AS n", ["mysql", "sqlite"]),
    ("comment_function_name", "SELECT 7 AS n /* SLEEP(99) */", ["mysql", "sqlite"]),
    ("function_sleep", "SELECT SLEEP(0) AS n", ["mysql", "sqlite"]),
    ("function_benchmark", "SELECT BENCHMARK(0, 1) AS n", ["mysql", "sqlite"]),
    ("function_get_lock", "SELECT GET_LOCK('probe', 0) AS n", ["mysql", "sqlite"]),
    ("function_release_lock", "SELECT RELEASE_LOCK('probe') AS n", ["mysql", "sqlite"]),
    ("function_release_all", "SELECT RELEASE_ALL_LOCKS() AS n", ["mysql", "sqlite"]),
    ("derived_from", "SELECT n FROM (SELECT 7 AS n) t", ["mysql", "sqlite"]),
    ("explain_read", "EXPLAIN SELECT COUNT(*) FROM orders", ["mysql", "sqlite"]),
    ("bound_parameter", "SELECT :value AS n", ["mysql", "sqlite"]),
    ("multiple_statements", "SELECT 1; SELECT 2", ["mysql", "sqlite"]),
]

def cases(dialect):
    return [(name, sql) for name, sql, targets in CASES if dialect in targets]

# These calls are analyzed only. Never acquire/release live locks, run sleeps or
# benchmarking functions through the independent native truth connection.
def native_safe(name):
    return not name.startswith("function_") and name != "multiple_statements"
