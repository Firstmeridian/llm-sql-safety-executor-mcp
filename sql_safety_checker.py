
import sqlparse

def is_sql_safe(sql_query: str) -> bool:
    """
    Checks if a given SQL query is safe by ensuring it only contains SELECT statements.

    Args:
        sql_query: The SQL query to check.

    Returns:
        True if the query is safe, False otherwise.
    """
    if not sql_query:
        return True

    try:
        parsed = sqlparse.parse(sql_query)
        for statement in parsed:
            if statement.get_type() != 'SELECT':
                return False
    except Exception:
        # In case of a parsing error, we can consider it unsafe
        return False

    return True

# Example usage:
if __name__ == '__main__':
    safe_query = "SELECT * FROM users WHERE id = 1"
    unsafe_query = "DELETE FROM users WHERE id = 1"
    malformed_query = "SELECT * FROM"

    print(f"Is '{safe_query}' safe? {is_sql_safe(safe_query)}")
    print(f"Is '{unsafe_query}' safe? {is_sql_safe(unsafe_query)}")
    print(f"Is '{malformed_query}' safe? {is_sql_safe(malformed_query)}")
