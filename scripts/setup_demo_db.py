#!/usr/bin/env python3
"""Create the MySQL demo table required by bundled demo Skills.

The bundled demo Skills use an `orders` table:
- monthly-sales-report reads `order_date` and `amount`
- update-order-status reads and updates `status`

This script is intentionally MySQL-only. It reads the normal project `.env`
database settings through `db_adapter.py` and refuses to modify an existing
`orders` table unless an explicit flag is provided.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


VALID_STATUSES = (
    "pending",
    "confirmed",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
)

CREATE_ORDERS_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id INT NOT NULL PRIMARY KEY,
    order_date DATETIME NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    total_amount DECIMAL(12, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_orders_order_date (order_date),
    INDEX idx_orders_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

SEED_ROWS = [
    {
        "id": 1,
        "order_date": "2026-05-01 10:15:00",
        "amount": 100.00,
        "total_amount": 100.00,
        "status": "pending",
    },
    {
        "id": 2,
        "order_date": "2026-05-01 14:30:00",
        "amount": 250.00,
        "total_amount": 250.00,
        "status": "confirmed",
    },
    {
        "id": 3,
        "order_date": "2026-05-02 09:20:00",
        "amount": 75.50,
        "total_amount": 75.50,
        "status": "shipped",
    },
    {
        "id": 4,
        "order_date": "2026-05-15 16:45:00",
        "amount": 300.00,
        "total_amount": 300.00,
        "status": "delivered",
    },
    {
        "id": 5,
        "order_date": "2026-04-20 11:00:00",
        "amount": 450.00,
        "total_amount": 450.00,
        "status": "cancelled",
    },
    {
        "id": 6,
        "order_date": "2024-01-15 10:00:00",
        "amount": 100.00,
        "total_amount": 100.00,
        "status": "pending",
    },
    {
        "id": 7,
        "order_date": "2024-01-20 14:00:00",
        "amount": 250.00,
        "total_amount": 250.00,
        "status": "confirmed",
    },
    {
        "id": 8,
        "order_date": "2024-02-10 09:00:00",
        "amount": 75.50,
        "total_amount": 75.50,
        "status": "shipped",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and seed the MySQL orders table used by demo Skills.",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop an existing orders table before creating the demo table.",
    )
    parser.add_argument(
        "--seed-existing",
        action="store_true",
        help=(
            "Seed an existing compatible orders table. Use only for demo tables "
            "because rows with ids 1-8 are upserted."
        ),
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Create the table without inserting demo rows.",
    )
    return parser.parse_args()


def table_exists(conn, database_name: str, table_name: str) -> bool:
    from sqlalchemy import text

    result = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = :database_name
              AND TABLE_NAME = :table_name
            """
        ),
        {"database_name": database_name, "table_name": table_name},
    ).scalar_one()
    return bool(result)


def seed_orders(conn) -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            """
            INSERT INTO orders (id, order_date, amount, total_amount, status)
            VALUES (:id, :order_date, :amount, :total_amount, :status)
            ON DUPLICATE KEY UPDATE
                order_date = VALUES(order_date),
                amount = VALUES(amount),
                total_amount = VALUES(total_amount),
                status = VALUES(status)
            """
        ),
        SEED_ROWS,
    )


def setup_demo_db(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    import db_adapter

    if db_adapter.DB_TYPE != "mysql":
        print(
            "This script is MySQL-only. Set DB_TYPE=mysql in .env before running.",
            file=sys.stderr,
        )
        return 2

    adapter = None
    try:
        adapter = db_adapter.create_adapter("mysql")
        database_name = adapter.get_database_name()
        if not database_name:
            print("Could not determine the current MySQL database name.", file=sys.stderr)
            return 1

        engine = getattr(adapter, "_engine", None)
        if engine is None:
            print("MySQL adapter did not initialize an engine.", file=sys.stderr)
            return 1

        with engine.begin() as conn:
            exists = table_exists(conn, database_name, "orders")
            if exists and args.drop_existing:
                conn.execute(text("DROP TABLE orders"))
                exists = False

            if exists and not args.seed_existing:
                print(
                    "Table 'orders' already exists. Refusing to modify it. "
                    "Use --drop-existing for a fresh demo table or --seed-existing "
                    "for a compatible demo table.",
                    file=sys.stderr,
                )
                return 2

            if not exists:
                conn.execute(text(CREATE_ORDERS_SQL))

            if not args.no_seed:
                seed_orders(conn)

        seeded = 0 if args.no_seed else len(SEED_ROWS)
        print(
            f"Demo table ready: {database_name}.orders "
            f"({seeded} seed rows inserted/upserted)."
        )
        print("Try monthly-sales-report with params: {'year': 2026, 'month': 5}")
        print("Try update-order-status dry-run with order_id=1, new_status='confirmed'")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if adapter is not None:
            adapter.close()


def main() -> int:
    args = parse_args()
    return setup_demo_db(args)


if __name__ == "__main__":
    raise SystemExit(main())