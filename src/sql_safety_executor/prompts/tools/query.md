Execute one policy-approved read-only SQL statement on the database.

This is the primary tool for free-form read-only SQL. Use metadata tools
for schema discovery and reviewed Query Skills for defined workflows.
Safety validation is automatic - only read-only statements are allowed.
Supported: SELECT, DESCRIBE, and non-ANALYZE EXPLAIN. Use list_tables()
and describe_table() instead of raw SHOW statements.
Returned payloads may be truncated for context safety; truncation does not
limit database work. Add WHERE/LIMIT/ORDER BY in SQL when needed.

Args:
    sql: One SELECT, DESCRIBE, or non-ANALYZE EXPLAIN statement
    
Returns:
    Query results with data rows, or error message if query fails
    
Examples:
    query("SELECT * FROM users LIMIT 10")
    query("SELECT name, email FROM users WHERE active = 1")
    query("SELECT COUNT(*) as total FROM orders")
    query("DESCRIBE users")
    query("EXPLAIN SELECT * FROM products WHERE id = 1")