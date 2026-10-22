"""Physical SQLite transaction, completed DML count and cursor lifetime proof."""
from __future__ import annotations

import asyncio
import gc
import sqlite3

import pytest
from sqlalchemy import event

from sql_safety_executor.database.outcomes import (
    ExpectedRowcountMismatchError, WriteExecutionError, WriteExecutionOutcome,
)
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.sqlite import _sqlite_dml_needs_count
from tests.support_adapters import SQLiteAdapter


@pytest.fixture
def file_adapter(tmp_path):
    path = tmp_path / "private.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY,n INTEGER UNIQUE);"
                         "INSERT INTO orders VALUES(1,7),(2,8);")
    adapter = SQLiteAdapter(str(path))
    assert adapter.connect()
    trace = []
    with adapter._engine.connect() as connection:
        connection.connection.dbapi_connection.set_trace_callback(trace.append)

    def observed():
        with sqlite3.connect(path) as db:
            return db.execute("SELECT id,n FROM orders ORDER BY id").fetchall()

    yield adapter, observed, trace, path
    adapter.close()


PREFIXES = ["", "WITH chosen AS(SELECT 1) ", "WITH RECURSIVE chosen(n) AS(SELECT 1) ",
            ";", ";;", "/*prefix*/ ;\n", "/*prefix*/ ", "--prefix\n"]
DML = [
    ("UPDATE orders SET n=99 WHERE id=1", [(1,99),(2,8)]),
    ("INSERT INTO orders VALUES(3,99)", [(1,7),(2,8),(3,99)]),
    ("DELETE FROM orders WHERE id=1", [(2,8)]),
]


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("sql,committed", DML)
@pytest.mark.parametrize("returning", [False, True])
def test_one_row_dml_commits_after_completed_count(file_adapter, prefix, sql, committed, returning):
    adapter, observed, trace, _ = file_adapter
    original = prefix + sql + (" RETURNING n" if returning else "")
    result = adapter.execute_write(original, {}, expected_rowcount=1)
    assert result == {"success": True, "rowcount": 1}
    assert result.execution_outcome is WriteExecutionOutcome.COMMITTED
    assert observed() == committed
    assert any(s.strip() == "BEGIN" for s in trace)
    assert "COMMIT" in trace
    assert original in trace  # Original SQL, including prefixes, reaches SQLite.
    assert adapter.execute("SELECT COUNT(*) FROM orders")[0][0] == len(committed)


@pytest.mark.parametrize("prefix", PREFIXES[:6])
@pytest.mark.parametrize("returning", [False, True])
@pytest.mark.parametrize("actual", [0, 1, 2])
def test_mismatch_proves_rollback_after_cleanup(file_adapter, prefix, returning, actual):
    adapter, observed, trace, _ = file_adapter
    where = {0:"id=999", 1:"id=1", 2:"id IN(1,2)"}[actual]
    sql = prefix + "UPDATE orders SET n=n+100 WHERE " + where + (" RETURNING n" if returning else "")
    before = observed()
    with pytest.raises(ExpectedRowcountMismatchError) as raised:
        adapter.execute_write(sql, {}, expected_rowcount=3)
    assert raised.value.actual_rowcount == actual
    assert raised.value.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
    assert raised.value.error_code == "expected_rowcount_mismatch"
    assert observed() == before
    assert adapter.execute("SELECT n FROM orders ORDER BY id")[0][0] == 7
    # Dropping frames / closing the adapter must not finalize a hidden write.
    del raised
    gc.collect()
    adapter.close()
    assert observed() == before
    assert any(s.strip() == "BEGIN" for s in trace) and "ROLLBACK" in trace
    assert "COMMIT" not in trace


@pytest.mark.parametrize("returning", [False, True])
@pytest.mark.parametrize("prefix", ["", PREFIXES[1], ";"])
def test_zero_noop_and_unconstrained_batch_counts(file_adapter, prefix, returning):
    adapter, observed, _, _ = file_adapter
    tail = " RETURNING n" if returning else ""
    assert adapter.execute_write(prefix+"UPDATE orders SET n=99 WHERE id=999"+tail, {}, expected_rowcount=0)["rowcount"] == 0
    # A matched row counts even when its stored value already equals the input.
    assert adapter.execute_write(prefix+"UPDATE orders SET n=7 WHERE id=1"+tail, {}, expected_rowcount=1)["rowcount"] == 1
    assert adapter.execute_write(prefix+"UPDATE orders SET n=n+100"+tail, {})["rowcount"] == 2
    assert observed() == [(1,107),(2,108)]


@pytest.mark.parametrize("prefix", ["", PREFIXES[1], ";"])
@pytest.mark.parametrize("trigger", [False, True])
def test_partial_failure_does_not_persist(file_adapter, prefix, trigger):
    adapter, observed, trace, path = file_adapter
    if trigger:
        with sqlite3.connect(path) as db:
            db.executescript("CREATE TRIGGER fail_change AFTER UPDATE ON orders BEGIN SELECT RAISE(FAIL,'fixture'); END;")
        sql = "UPDATE orders SET n=99 WHERE id=1"
    else:
        sql = "UPDATE OR FAIL orders SET n=99"
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write(prefix+sql, {}, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
    assert observed() == [(1,7),(2,8)]
    del raised
    gc.collect()
    adapter.close()
    assert observed() == [(1,7),(2,8)] and "ROLLBACK" in trace


@pytest.mark.parametrize("prefix", ["", PREFIXES[1]])
def test_engine_auto_rollback_is_not_misreported_as_explicit_ack(file_adapter, prefix):
    adapter, observed, _, _ = file_adapter
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write(prefix+"UPDATE OR ROLLBACK orders SET n=99", {}, expected_rowcount=1)
    assert observed() == [(1,7),(2,8)]
    # SQLite ended the transaction itself. Our subsequent no-op rollback is
    # not independent confirmation, even though this fixture proves unchanged.
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN


@pytest.mark.parametrize("prefix", ["", PREFIXES[1]])
def test_count_changes_result_is_consumed(file_adapter, prefix):
    adapter, observed, _, _ = file_adapter
    with adapter._engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA count_changes=ON").close()
    result = adapter.execute_write(prefix+"UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
    assert result["rowcount"] == 1 and observed() == [(1,99),(2,8)]


def test_unfinished_commit_is_unknown_and_connection_is_retired(file_adapter, monkeypatch):
    adapter, observed, _, _ = file_adapter
    monkeypatch.setattr(adapter._engine.dialect, "do_commit", lambda connection: None)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.phase.value == "commit"
    assert observed() == [(1,7),(2,8)]


def test_trigger_counts_are_direct_dml_only(file_adapter):
    adapter, observed, _, path = file_adapter
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE audit(n); CREATE TRIGGER audit_change AFTER UPDATE ON orders "
                         "BEGIN INSERT INTO audit VALUES(NEW.n); INSERT INTO audit VALUES(NEW.n); END;")
    for sql in ["WITH chosen AS(SELECT 1) UPDATE orders SET n=99 WHERE id=1 RETURNING n",
                "UPDATE orders SET n=100 WHERE id=1 RETURNING n"]:
        assert adapter.execute_write(sql, {}, expected_rowcount=1)["rowcount"] == 1
    assert observed() == [(1,100),(2,8)]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone() == (4,)


def test_foreign_key_cascade_is_not_added_to_direct_count(file_adapter):
    adapter, observed, _, path = file_adapter
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE child(id PRIMARY KEY,parent REFERENCES orders(id) ON DELETE CASCADE);"
                         "INSERT INTO child VALUES(10,1),(11,1),(12,2);")
    with adapter._engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON").close()
    result = adapter.execute_write("WITH chosen AS(SELECT 1) DELETE FROM orders WHERE id=1 RETURNING n", {}, expected_rowcount=1)
    assert result["rowcount"] == 1 and observed() == [(2,8)]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id,parent FROM child").fetchall() == [(12,2)]


def test_view_instead_of_trigger_retains_native_zero_count(file_adapter):
    adapter, observed, _, path = file_adapter
    with sqlite3.connect(path) as db:
        db.executescript("CREATE VIEW visible_orders AS SELECT id,n FROM orders;"
                         "CREATE TRIGGER through_view INSTEAD OF UPDATE ON visible_orders "
                         "BEGIN UPDATE orders SET n=NEW.n WHERE id=OLD.id; END;")
    with pytest.raises(ExpectedRowcountMismatchError) as raised:
        adapter.execute_write("UPDATE visible_orders SET n=99 WHERE id=1 RETURNING n", {}, expected_rowcount=1)
    assert raised.value.actual_rowcount == 0 and observed() == [(1,7),(2,8)]
    # RETURNING row count is not the direct DML count of a view mutation.
    assert adapter.execute_write("WITH chosen AS(SELECT 1) UPDATE visible_orders SET n=99 WHERE id=1 RETURNING n", {}, expected_rowcount=0)["rowcount"] == 0
    assert observed() == [(1,99),(2,8)]


@pytest.mark.parametrize("sql,expected", [
    (";WITH replace(n) AS(SELECT 7) UPDATE orders SET n=7", True),
    ("WITH replace(n) AS(SELECT 7), delete_me AS(SELECT 1) INSERT INTO orders SELECT 3,n FROM replace", True),
    ("WITH c AS(SELECT 1) SELECT(7) FROM replace", False),
    ("WITH c AS(SELECT 1) VALUES(7)", False),
    ("WITH c AS(SELECT 1) SELECT replace('a','a','b')", False),
    ("EXPLAIN UPDATE orders SET n=7", False),
    ("CREATE TABLE other AS SELECT * FROM orders", False),
])
def test_unknown_count_root_uses_roles_not_keyword_substrings(sql, expected):
    assert _sqlite_dml_needs_count(sql, DialectContext("sqlite")) is expected


def test_non_dml_never_inherits_a_previous_count(file_adapter):
    adapter, _, _, _ = file_adapter
    adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
    assert adapter.execute_write("CREATE TABLE other(n)", {})["rowcount"] == -1
    assert adapter.execute_write("WITH c AS(SELECT 7) SELECT * FROM c", {})["rowcount"] == -1
    with pytest.raises(ExpectedRowcountMismatchError):
        adapter.execute_write("CREATE TABLE rolled_back(n)", {}, expected_rowcount=1)
    assert not adapter.execute("SELECT 1 FROM sqlite_schema WHERE name='rolled_back'")


@pytest.mark.parametrize("cancel", [False, True])
def test_fetch_failure_or_cancellation_rolls_back_and_closes(file_adapter, monkeypatch, cancel):
    from sqlalchemy.engine import CursorResult
    adapter, observed, _, _ = file_adapter
    original = CursorResult.fetchmany
    cursor_results = []

    def fail_fetch(result, size=None):
        if list(result.keys()) == ["n"]:
            cursor_results.append(result)
            raise asyncio.CancelledError() if cancel else RuntimeError("fixture fetch failure")
        return original(result, size)

    monkeypatch.setattr(CursorResult, "fetchmany", fail_fetch)
    with pytest.raises(asyncio.CancelledError if cancel else WriteExecutionError):
        adapter.execute_write(PREFIXES[1]+"UPDATE orders SET n=99 WHERE id=1 RETURNING n", {}, expected_rowcount=1)
    assert cursor_results and all(result.closed for result in cursor_results)
    assert observed() == [(1,7),(2,8)]
    gc.collect()
    assert observed() == [(1,7),(2,8)]


def test_failed_physical_begin_never_attempts_dml(file_adapter):
    adapter, observed, trace, _ = file_adapter

    @event.listens_for(adapter._engine, "before_cursor_execute")
    def fail_begin(connection, cursor, statement, params, context, many):
        if statement == "BEGIN":
            raise RuntimeError("fixture BEGIN failure")

    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE orders SET n=99", {}, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.NOT_EXECUTED
    assert observed() == [(1,7),(2,8)] and not any("UPDATE orders" in sql for sql in trace)


def test_logical_begin_without_physical_effect_is_rejected(file_adapter):
    adapter, observed, trace, _ = file_adapter

    @event.listens_for(adapter._engine, "before_cursor_execute", retval=True)
    def suppress_begin(connection, cursor, statement, params, context, many):
        return ("SELECT 1", ()) if statement == "BEGIN" else (statement, params)

    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.NOT_EXECUTED
    assert observed() == [(1,7),(2,8)] and not any("UPDATE orders" in sql for sql in trace)


def test_noop_rollback_is_unknown_and_connection_is_retired(file_adapter, monkeypatch):
    adapter, observed, _, _ = file_adapter
    engine = adapter._engine
    invalidated = []
    event.listen(engine, "invalidate", lambda *args: invalidated.append(True))
    monkeypatch.setattr(engine.dialect, "do_rollback", lambda connection: None)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("WITH c AS(SELECT 1) UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=2)
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "rollback_unconfirmed"
    assert invalidated == [True]
    assert observed() == [(1,7),(2,8)]


def test_result_close_failure_is_unknown_and_connection_is_retired(file_adapter, monkeypatch):
    from sqlalchemy.engine import CursorResult
    adapter, observed, _, _ = file_adapter
    original = CursorResult.close
    invalidated = []
    event.listen(adapter._engine, "invalidate", lambda *args: invalidated.append(True))

    def fail_close(result):
        if "RETURNING n" in result.context.statement:
            raise RuntimeError("fixture close failure")
        return original(result)

    monkeypatch.setattr(CursorResult, "close", fail_close)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("WITH c AS(SELECT 1) UPDATE orders SET n=99 WHERE id=1 RETURNING n", {}, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "rollback_unconfirmed" and invalidated == [True]
    assert observed() == [(1,7),(2,8)]
    assert adapter.execute("SELECT n FROM orders ORDER BY id")[0][0] == 7


def test_deadline_expiring_during_fetch_rolls_back(file_adapter, monkeypatch):
    from sqlalchemy.engine import CursorResult
    import sql_safety_executor.database.sqlite as sqlite_module
    adapter, observed, _, _ = file_adapter
    original = CursorResult.fetchmany
    clock = sqlite_module.time.monotonic
    jumped = [False]
    monkeypatch.setattr(sqlite_module.time, "monotonic", lambda: clock() + (10 if jumped[0] else 0))

    def advance_after_fetch(result, size=None):
        rows = original(result, size)
        if "RETURNING n" in result.context.statement:
            jumped[0] = True
        return rows

    monkeypatch.setattr(CursorResult, "fetchmany", advance_after_fetch)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("WITH c AS(SELECT 1) UPDATE orders SET n=99 WHERE id=1 RETURNING n", {}, timeout=1, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
    assert observed() == [(1,7),(2,8)]


def test_write_budget_includes_returned_result_consumption(file_adapter):
    adapter, observed, _, _ = file_adapter
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE orders SET n=99 WHERE id=1 RETURNING n", {}, timeout=0, expected_rowcount=1)
    assert raised.value.execution_outcome is WriteExecutionOutcome.NOT_EXECUTED
    assert observed() == [(1,7),(2,8)]
