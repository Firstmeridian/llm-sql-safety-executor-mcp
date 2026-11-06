"""Bounded estimate batching keeps the same data targets and read guard."""
from dataclasses import replace
import sqlite3

import pytest

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.support_adapters import SQLiteAdapter


def test_estimate_batches_are_bounded_and_keep_main_identity(tmp_path, monkeypatch):
    path = tmp_path / "counts.db"
    with sqlite3.connect(path) as db:
        for index in range(35):
            db.execute(f'CREATE TABLE t{index:02}(n)')
            db.executemany(f'INSERT INTO t{index:02} VALUES(?)', [(7,)] * (index + 1))
    adapter = SQLiteAdapter(path)
    adapter.connect()
    reads = []
    original = adapter.execute_read

    def read(sql, *args, **kwargs):
        reads.append(sql)
        return original(sql, *args, **kwargs)

    monkeypatch.setattr(adapter, "execute_read", read)
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE TEMP TABLE t00(n)")
            db.exec_driver_sql("INSERT INTO temp.t00 VALUES(99),(100)")
        result = adapter.get_tables()
        assert {row["table_name"]: row["row_count"] for row in result} == {
            f"t{index:02}": index + 1 for index in range(35)
        }
        assert len(reads) == 2
        assert all(sql.count("LIMIT 10000") <= 32 for sql in reads)
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        adapter.close()


def test_counts_remain_per_source_bounded_and_names_are_data(tmp_path):
    names = ['a"b', "a.b", " f ", "  f  ", "Korders", "korders", "__mcp_row_estimate_0"]
    path = tmp_path / "names.db"
    with sqlite3.connect(path) as db:
        for index, name in enumerate(names):
            quoted = '"' + name.replace('"', '""') + '"'
            db.execute(f"CREATE TABLE {quoted}(n)")
            db.executemany(f"INSERT INTO {quoted} VALUES(?)", [(7,)] * (index + 1))
        db.execute("CREATE TABLE large(n)")
        db.executemany("INSERT INTO large VALUES(?)", [(7,)] * 10003)
    adapter = SQLiteAdapter(path)
    try:
        estimates = adapter._row_estimates([*names, "large"])
        assert estimates == {**{name: index + 1 for index, name in enumerate(names)}, "large": 10000}
    finally:
        adapter.close()


def test_denied_view_does_not_evaluate_functions_or_hide_other_counts(tmp_path):
    path = tmp_path / "views.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7),(8);"
                        "CREATE VIEW ordinary AS SELECT n FROM orders;"
                        "CREATE VIEW blocked AS SELECT SLEEP(n) AS n FROM orders;")
    adapter = SQLiteAdapter(path)
    adapter.connect()
    calls = []
    try:
        with adapter._engine.connect() as db:
            db.connection.dbapi_connection.create_function("SLEEP", 1, lambda n: calls.append(n) or n)
        assert adapter._row_estimates(["orders", "ordinary", "blocked"]) == {
            "orders": 2, "ordinary": 2, "blocked": None,
        }
        assert calls == []
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        adapter.close()


def test_only_authorized_projection_reaches_batch(tmp_path, monkeypatch):
    path = tmp_path / "grants.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE a(n); INSERT INTO a VALUES(7);"
                        "CREATE TABLE b(n); INSERT INTO b VALUES(8),(9);"
                        "CREATE TABLE secret(n); INSERT INTO secret VALUES(99);")
    adapter = SQLiteAdapter(path)
    adapter._config = replace(adapter._config, policy=ConnectionPolicy(
        read_mode="allowlist", allowed_tables=frozenset({"main.a", "main.b"}), default_schema="main"))
    original = adapter.execute_read

    def read(sql, *args, **kwargs):
        assert "secret" not in sql
        return original(sql, *args, **kwargs)

    monkeypatch.setattr(adapter, "execute_read", read)
    try:
        assert adapter._row_estimates(["a", "b", "secret"]) == {"a": 1, "b": 2, "secret": None}
    finally:
        adapter.close()


@pytest.mark.parametrize("code", ["query_timeout", "database_query_failed", "database_connection_failed"])
def test_runtime_failures_are_not_retried(tmp_path, monkeypatch, code):
    path = tmp_path / "failure.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE a(n); CREATE TABLE b(n);")
    adapter = SQLiteAdapter(path)
    calls = []

    def fail(sql, **kwargs):
        calls.append(sql)
        raise DatabaseQueryError(code)

    monkeypatch.setattr(adapter, "execute_read", fail)
    try:
        with pytest.raises(MetadataQueryError):
            adapter._row_estimates(["a", "b"])
        assert len(calls) == 1
    finally:
        adapter.close()


def test_fts_and_normal_sources_remain_guarded(tmp_path):
    path = tmp_path / "fts.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE VIRTUAL TABLE search_docs USING fts5(body);"
                        "INSERT INTO search_docs VALUES('hello'),('world');"
                        "CREATE TABLE ordinary(n); INSERT INTO ordinary VALUES(7);")
    adapter = SQLiteAdapter(path)
    adapter._config = replace(adapter._config, policy=ConnectionPolicy(
        read_mode="allowlist", allowed_tables=frozenset({"main.search_docs", "main.ordinary"}),
        default_schema="main"))
    try:
        assert adapter._row_estimates(["search_docs", "ordinary"]) == {"search_docs": 2, "ordinary": 1}
        with pytest.raises(DatabaseQueryError):
            adapter.execute_read("SELECT * FROM search_docs_data", policy=adapter._config.policy)
    finally:
        adapter.close()
