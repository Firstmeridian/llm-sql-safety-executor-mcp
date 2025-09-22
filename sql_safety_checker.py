
import sqlparse
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Load environment variables from .env file
load_dotenv()

# Create a database engine. The engine is created once when the module is loaded.
# The connection string can be adapted for other databases like PostgreSQL.
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}?charset=utf8mb4"

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
except ImportError:
    print("Error: mysql-connector-python is not installed. Please install it using: pip install mysql-connector-python")
    engine = None

def execute_sql(sql_query: str) -> list | str:
    """
    Executes a SQL query after checking if it is safe, using SQLAlchemy for connection pooling.

    Args:
        sql_query: The SQL query to execute.

    Returns:
        A list of tuples representing the rows of the result, or an error message string.
    """
    if not engine:
        return "Error: Database engine could not be initialized. Please check your installation."

    if not is_sql_safe(sql_query):
        return "Error: Only SELECT queries are allowed."

    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql_query))
            rows = result.fetchall()
            # The result object is a cursor-like object, so we can get column names from its keys.
            # column_names = result.keys()
            # result_dicts = [dict(zip(column_names, row)) for row in rows]
            return rows
    except SQLAlchemyError as e:
        return f"Database Error: {e}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

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
    # Note: To run this example, you need to have a MySQL database running
    # and have the .env file configured with your database credentials.
    # You also need to install the required libraries:
    # pip install sqlalchemy mysql-connector-python python-dotenv

    if not engine:
        exit()

    safe_query = "SELECT * FROM test_users LIMIT 1"
    unsafe_query = "DELETE FROM test_users WHERE id = 1"

    print(f"Is '{safe_query}' safe? {is_sql_safe(safe_query)}")
    print(f"Is '{unsafe_query}' safe? {is_sql_safe(unsafe_query)}")

    print("\n--- Testing SQL Execution ---")
    # Create a dummy 'test_users' table for testing if it doesn't exist
    try:
        with engine.connect() as connection:
            with connection.begin(): # Start a single transaction for setup
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS test_users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255)
                    )
                """))
                # Check if table is empty before inserting
                result = connection.execute(text("SELECT COUNT(*) FROM test_users"))
                if result.scalar_one() == 0:
                    connection.execute(text("INSERT INTO test_users (name) VALUES ('Alice'), ('Bob')"))
    except SQLAlchemyError as e:
        print(f"Database setup for example failed: {e}")
        print("Please ensure your database is running and .env is configured correctly.")
        exit()

    print(f"\nExecuting safe query: '{safe_query}'")
    result = execute_sql(safe_query)
    print(f"Result: {result}")

    print(f"\nExecuting unsafe query: '{unsafe_query}'")
    result = execute_sql(unsafe_query)
    print(f"Result: {result}")

