"""
Tests for Query Skills — End-to-end SQL template loading and execution

Covers:
- execute() with params for parameterized read-only queries (#18)
- execute() without params backward compatibility (#19)
- SQL injection safety in params (#2 — partial, adapter-level)

Uses SQLite in-memory database for fast, isolated testing.

Usage:
    pytest tests/test_query_skills.py -v
"""

import sys
import pytest
from pathlib import Path

# Add project root and _lib to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "_lib"))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def adapter_with_orders():
    """
    Create a SQLiteAdapter with an orders table containing test data.

    Returns a connected adapter with orders table:
    - id, order_date, amount, status
    """
    from db_adapter import SQLiteAdapter
    from sqlalchemy import text

    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    assert adapter._engine is not None

    with adapter._engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    order_date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
            """))
            conn.execute(text("""
                INSERT INTO orders (id, order_date, amount, status) VALUES
                (1, '2024-01-15', 100.00, 'pending'),
                (2, '2024-01-20', 250.00, 'confirmed'),
                (3, '2024-02-10', 75.50, 'shipped'),
                (4, '2024-01-25', 300.00, 'pending'),
                (5, '2024-03-01', 450.00, 'delivered')
            """))

    yield adapter
    adapter.close()


# =============================================================================
# test_execute_with_params_readonly (#18)
# =============================================================================

class TestExecuteWithParams:
    """Tests for adapter.execute() with the new params parameter."""

    def test_monthly_sales_report_sqlite_template_executes(self):
        """The SQLite example skill query runs against the demo-style schema."""
        from db_adapter import SQLiteAdapter
        from sqlalchemy import text
        from skill_loader import discover, load_query, validate_params

        discover(PROJECT_ROOT / "skills")
        sql_template, param_schema = load_query("monthly-sales-report-sqlite")
        params = validate_params({"year": 2024, "month": 1}, param_schema)

        adapter = SQLiteAdapter(":memory:")
        adapter.connect()
        assert adapter._engine is not None

        try:
            with adapter._engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("""
                        CREATE TABLE orders (
                            id INTEGER PRIMARY KEY,
                            order_date TEXT NOT NULL,
                            total_amount REAL
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO orders (id, order_date, total_amount) VALUES
                        (1, '2024-01-15 10:00:00', 100.00),
                        (2, '2024-01-15 14:00:00', 250.00),
                        (3, '2024-01-20 09:00:00', 300.00),
                        (4, '2024-02-01 09:00:00', 999.00)
                    """))

            result = adapter.execute(sql_template, params=params)
        finally:
            adapter.close()

        assert not isinstance(result, str)
        assert len(result) == 2
        assert result[0].date == "2024-01-15"
        assert result[0].order_count == 2
        assert result[0].revenue == pytest.approx(350.0)
        assert result[0].avg_order_value == pytest.approx(175.0)
        assert result[1].date == "2024-01-20"
        assert result[1].order_count == 1

    def test_execute_with_params_readonly(self, adapter_with_orders):
        """#18: Parameterized read-only query returns correct results."""
        result = adapter_with_orders.execute(
            "SELECT id, amount FROM orders WHERE status = :status ORDER BY id",
            params={"status": "pending"},
        )

        assert not isinstance(result, str)
        assert len(result) == 2
        # Rows for order_id 1 and 4 (both 'pending')
        assert result[0].id == 1
        assert result[1].id == 4

    def test_params_multiple_parameters(self, adapter_with_orders):
        """Multiple params bind correctly."""
        result = adapter_with_orders.execute(
            "SELECT id FROM orders WHERE status = :status AND amount > :min_amount",
            params={"status": "pending", "min_amount": 200},
        )

        assert not isinstance(result, str)
        assert len(result) == 1
        assert result[0].id == 4

    def test_params_no_results(self, adapter_with_orders):
        """Parameterized query with no matching rows returns empty list."""
        result = adapter_with_orders.execute(
            "SELECT id FROM orders WHERE status = :status",
            params={"status": "nonexistent"},
        )

        assert not isinstance(result, str)
        assert len(result) == 0


# =============================================================================
# test_execute_without_params_unchanged (#19)
# =============================================================================

class TestExecuteWithoutParams:
    """Tests for backward compatibility — execute() without params."""

    def test_execute_without_params_unchanged(self, adapter_with_orders):
        """#19: execute(sql) without params works exactly as before."""
        result = adapter_with_orders.execute(
            "SELECT COUNT(*) AS count FROM orders"
        )

        assert not isinstance(result, str)
        assert len(result) == 1
        assert result[0].count == 5

    def test_execute_with_timeout_no_params(self, adapter_with_orders):
        """execute(sql, timeout=N) still works."""
        result = adapter_with_orders.execute(
            "SELECT id FROM orders ORDER BY id LIMIT 2",
            timeout=10,
        )

        assert not isinstance(result, str)
        assert len(result) == 2


# =============================================================================
# test_execute_write_basic (#1) + test_execute_write_injection_safe (#2) +
# test_execute_write_exception_propagates (#17)
# =============================================================================

class TestExecuteWrite:
    """Tests for adapter.execute_write() — parameterized write operations."""

    def test_execute_write_basic(self, adapter_with_orders):
        """#1: execute_write() binds params and writes data."""
        result = adapter_with_orders.execute_write(
            "UPDATE orders SET status = :new_status WHERE id = :order_id",
            params={"new_status": "shipped", "order_id": 1},
        )

        assert result["success"] is True
        assert result["rowcount"] == 1

        # Verify the write persisted
        verify = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 1},
        )
        assert verify[0].status == "shipped"

    def test_execute_write_injection_safe(self, adapter_with_orders):
        """#2: SQL injection attempt in params is safely bound."""
        result = adapter_with_orders.execute_write(
            "UPDATE orders SET status = :new_status WHERE id = :order_id",
            params={
                "new_status": "'; DROP TABLE orders; --",
                "order_id": 1,
            },
        )

        assert result["success"] is True
        assert result["rowcount"] == 1

        # Table should still exist and have all rows
        verify = adapter_with_orders.execute("SELECT COUNT(*) AS count FROM orders")
        assert verify[0].count == 5

        # The status should be the literal injection string, not executed
        verify2 = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 1},
        )
        assert verify2[0].status == "'; DROP TABLE orders; --"

    def test_execute_write_no_matching_rows(self, adapter_with_orders):
        """execute_write() with no matching rows returns rowcount=0."""
        result = adapter_with_orders.execute_write(
            "UPDATE orders SET status = :new_status WHERE id = :order_id",
            params={"new_status": "shipped", "order_id": 999},
        )

        assert result["success"] is True
        assert result["rowcount"] == 0

    def test_execute_write_exception_propagates(self, adapter_with_orders):
        """#17: execute_write() on invalid SQL propagates exception."""
        with pytest.raises(Exception):
            adapter_with_orders.execute_write(
                "UPDATE nonexistent_table SET x = :val",
                params={"val": 1},
            )
