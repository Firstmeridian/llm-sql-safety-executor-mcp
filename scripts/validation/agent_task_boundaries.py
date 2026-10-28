"""Independent temporal/payment fixtures; never query configured databases.

This declared task convention is a half-open rental interval [start, return),
Payment participation, integer cents and month boundaries are also explicit
task conventions, not database policies or rewrite rules for business SQL.
"""
from __future__ import annotations

import json
import sqlite3

# Cents and [start, return) / [July 1, August 1) are declared fixture contracts.
# Zero and negative payments still establish payment participation.
JULY_START = "2005-07-01 00:00:00"
PAYMENT_RENTALS = (
    (1, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (2, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (3, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (4, 1, "2005-08-01 00:00:00", "2005-08-03 00:00:00"),
    (5, 1, "2005-07-28 00:00:00", "2005-08-01 00:00:00"),
    (6, 1, "2005-08-01 00:00:01", "2005-08-03 00:00:00"),
    (7, 2, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (8, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (9, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (10, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (11, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (12, 1, "2005-07-28 00:00:00", "2005-08-03 00:00:00"),
    (13, 1, "2005-07-28 00:00:00", None),
    (14, 1, "2005-07-28 00:00:00", "2005-08-01 00:00:01"),
)
PAYMENTS = (
    (1, "2005-07-15 00:00:00", 700),
    (2, "2005-08-02 00:00:00", 9900),
    (4, "2005-07-15 00:00:00", 300),
    (4, "2005-07-16 00:00:00", 200),
    (5, "2005-07-15 00:00:00", 1300),
    (6, "2005-07-15 00:00:00", 1700),
    (7, "2005-07-15 00:00:00", 1900),
    (8, "2005-07-15 00:00:00", 0),
    (9, "2005-07-15 00:00:00", -200),
    (10, "2005-07-15 00:00:00", 500),
    (10, "2005-08-02 00:00:00", 99900),
    (11, "2005-07-01 00:00:00", 101),
    (12, "2005-08-01 00:00:00", 202),
    (13, "2005-07-15 00:00:00", 700),
    (14, "2005-07-15 00:00:00", 50),
)
ACTIVE = "r.rental_date <= :cutoff AND (r.return_date IS NULL OR r.return_date > :cutoff)"
MONTH = "p.payment_date >= :july_start AND p.payment_date < :cutoff"
INNER_PAYMENT_QUERY = f"""SELECT COUNT(DISTINCT r.rental_id), SUM(p.amount_cents)
FROM rentals r JOIN payments p ON p.rental_id = r.rental_id
WHERE r.store_id = :store_id AND {ACTIVE} AND {MONTH}"""
LEFT_PAYMENT_QUERY = f"""SELECT COUNT(DISTINCT r.rental_id), SUM(p.amount_cents)
FROM rentals r LEFT JOIN payments p ON p.rental_id = r.rental_id AND {MONTH}
WHERE r.store_id = :store_id AND {ACTIVE} AND p.rental_id IS NOT NULL"""
EXISTS_PAYMENT_QUERY = f"""WITH eligible AS (
SELECT r.rental_id FROM rentals r WHERE r.store_id = :store_id AND {ACTIVE}
AND EXISTS (SELECT 1 FROM payments p WHERE p.rental_id = r.rental_id AND {MONTH}))
SELECT (SELECT COUNT(*) FROM eligible), SUM(p.amount_cents) FROM payments p
WHERE p.rental_id IN (SELECT rental_id FROM eligible) AND {MONTH}"""
PAYMENT_QUERIES = {
    "inner": INNER_PAYMENT_QUERY,
    "exists": EXISTS_PAYMENT_QUERY,
    "left_with_presence": LEFT_PAYMENT_QUERY,
}
PAYMENT_BAD_QUERIES = {
    "left_without_presence": LEFT_PAYMENT_QUERY.replace(" AND p.rental_id IS NOT NULL", ""),
    "count_payment_rows": INNER_PAYMENT_QUERY.replace("COUNT(DISTINCT r.rental_id)", "COUNT(*)"),
    "distinct_amounts": INNER_PAYMENT_QUERY.replace("SUM(p.amount_cents)", "SUM(DISTINCT p.amount_cents)"),
    "positive_only": INNER_PAYMENT_QUERY + " AND p.amount_cents > 0",
    "inclusive_return": INNER_PAYMENT_QUERY.replace("return_date >", "return_date >="),
    "exclusive_start": INNER_PAYMENT_QUERY.replace("rental_date <=", "rental_date <"),
    "inclusive_month_end": INNER_PAYMENT_QUERY.replace("p.payment_date < :cutoff", "p.payment_date <= :cutoff"),
    "exclusive_month_start": INNER_PAYMENT_QUERY.replace("p.payment_date >= :july_start", "p.payment_date > :july_start"),
}


CUTOFF = "2005-08-01 00:00:00"
REFERENCE = """SELECT rental_id FROM rentals
WHERE rental_date <= :cutoff
AND (return_date IS NULL OR return_date > :cutoff)
ORDER BY rental_id"""
ROWS = (
    (1, "2005-07-31 23:59:59", "2005-07-31 23:59:59"),
    (2, "2005-07-31 23:59:59", CUTOFF),
    (3, "2005-07-31 23:59:59", "2005-08-01 00:00:01"),
    (4, "2005-07-31 23:59:59", None),
    (5, CUTOFF, None),
    (6, "2005-08-01 00:00:01", None),
)


def check_query(sql):
    """Return native SQLite IDs for this fixed fixture and supplied predicate."""
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE rentals(rental_id INTEGER, rental_date TEXT, return_date TEXT)")
        db.executemany("INSERT INTO rentals VALUES(?, ?, ?)", ROWS)
        return [row[0] for row in db.execute(sql, {"cutoff": CUTOFF})]


def payment_truth(store_id=1):
    """Independent row-loop oracle; does not reuse any SQL or gateway analysis."""
    ids, unpaid, cents, payment_rows = [], [], 0, 0
    for rental_id, store, start, returned in PAYMENT_RENTALS:
        if store_id is not None and store != store_id:
            continue
        if start > CUTOFF or (returned is not None and returned <= CUTOFF):
            continue
        matching = [amount for rid, date, amount in PAYMENTS
                    if rid == rental_id and JULY_START <= date < CUTOFF]
        if not matching:
            unpaid.append(rental_id)
            continue
        ids.append(rental_id)
        cents += sum(matching)
        payment_rows += len(matching)
    return {"rental_ids": ids, "rental_count": len(ids), "amount_cents": cents,
            "payment_rows": payment_rows, "without_july_payment_ids": unpaid}


def check_payment_query(sql, store_id=1):
    """Native SQLite result, separately compared with the Python oracle."""
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE rentals(rental_id INTEGER, store_id INTEGER, rental_date TEXT, return_date TEXT)")
        db.execute("CREATE TABLE payments(rental_id INTEGER, payment_date TEXT, amount_cents INTEGER)")
        db.executemany("INSERT INTO rentals VALUES(?, ?, ?, ?)", PAYMENT_RENTALS)
        db.executemany("INSERT INTO payments VALUES(?, ?, ?)", PAYMENTS)
        return db.execute(sql, {"store_id": store_id, "july_start": JULY_START, "cutoff": CUTOFF}).fetchall()


def payment_fixture_cte():
    """Read-only constant fixture usable in SQLite/MySQL, without creating objects."""
    def literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, int):
            return str(value)
        return "'" + value.replace("'", "''") + "'"

    def relation(name, columns, rows):
        selects = ["SELECT " + ", ".join(literal(v) for v in row) for row in rows]
        return f"{name}({columns}) AS (" + " UNION ALL ".join(selects) + ")"

    return "WITH " + relation("rentals", "rental_id,store_id,rental_date,return_date", PAYMENT_RENTALS) + ",\n" + relation("payments", "rental_id,payment_date,amount_cents", PAYMENTS)


def payment_report():
    return {
        "scope": "Independent fixture; payment participation includes zero/refund, integer cents, no gateway business restriction.",
        "rentals": PAYMENT_RENTALS, "payments": PAYMENTS,
        "store_1": payment_truth(1), "store_2": payment_truth(2), "all_stores": payment_truth(None),
        "references": {name: check_payment_query(sql) for name, sql in PAYMENT_QUERIES.items()},
        "known_bad": {name: check_payment_query(sql) for name, sql in PAYMENT_BAD_QUERIES.items()},
    }


def report():
    return {
        "scope": "Independent in-memory fixture; explicit [start, return) task convention, not a gateway SQL rule.",
        "cutoff": CUTOFF, "rows": ROWS, "expected_ids": [3, 4, 5],
        "reference_ids": check_query(REFERENCE),
        "inclusive_return_ids": check_query(REFERENCE.replace("return_date >", "return_date >=")),
        "exclusive_start_ids": check_query(REFERENCE.replace("rental_date <=", "rental_date <")),
        "currency_checks": [
            {"unit_source": None, "allowed": "report amount without assuming a currency"},
            {"unit_source": "explicit trusted business contract", "allowed": "report that contract's currency"},
        ],
        "payment_scope": payment_report(),
    }


if __name__ == "__main__":
    print(json.dumps(report(), ensure_ascii=False, indent=2))
