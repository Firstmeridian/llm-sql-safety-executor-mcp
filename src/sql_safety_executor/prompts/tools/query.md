Execute one policy-approved read-only SQL statement on the database.

This is the primary tool for free-form read-only SQL. Use metadata tools
for schema discovery and reviewed Query Skills for defined workflows.
Safety validation is automatic - only read-only statements are allowed.
Supported: SELECT, DESCRIBE, and non-ANALYZE EXPLAIN. Use list_tables()
and describe_table() instead of raw SHOW statements.

Args:
    sql: One SELECT, DESCRIBE, or non-ANALYZE EXPLAIN statement
    
Returns:
    Query rows on success. SQL/policy failures return success=false,
    error_code and a safe error; a hint may suggest recovery on the same
    connection. Follow the hint without bypassing policy or write approval.
    
Examples:
    query("SELECT * FROM users LIMIT 10")
    query("SELECT name, email FROM users WHERE active = 1")
    query("SELECT COUNT(*) as total FROM orders")
    query("DESCRIBE users")
    query("EXPLAIN SELECT * FROM products WHERE id = 1")
