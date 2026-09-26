#!/usr/bin/env python3
"""Create one disposable demo DB. Refuse to overwrite existing data."""

import argparse
from pathlib import Path
import sqlite3


def create(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive file creation prevents silently seeding an existing database.
    with path.open("xb"):
        pass
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE orders(id INTEGER PRIMARY KEY, order_date TEXT NOT NULL, amount REAL, total_amount REAL, status TEXT)"
        )
        db.execute("INSERT INTO orders VALUES(1,'2026-01-15',100,100,'pending')")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    create(parser.parse_args().output)
