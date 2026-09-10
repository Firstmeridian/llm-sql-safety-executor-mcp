"""v3.7.2 transaction invariants, fault classification, and MySQL opt-in proof."""

from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def write_adapter():
    from db_adapter import SQLiteAdapter

    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    adapter.execute_write(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT NOT NULL)",
        {},
    )
    adapter.execute_write(
        "INSERT INTO orders (id, status) VALUES (1, 'pending'), (2, 'confirmed')",
        {},
    )
    yield adapter
    adapter.close()


def test_expected_rowcount_match_commits(write_adapter) -> None:
    from db_adapter import WriteExecutionOutcome

    result = write_adapter.execute_write(
        "UPDATE orders SET status = :status WHERE id = :id",
        {"status": "confirmed", "id": 1},
        expected_rowcount=1,
    )
    assert result == {"success": True, "rowcount": 1}
    assert result.execution_outcome is WriteExecutionOutcome.COMMITTED
    assert write_adapter.execute(
        "SELECT status FROM orders WHERE id = 1"
    )[0].status == "confirmed"


@pytest.mark.parametrize("actual", [0, 2])
def test_expected_rowcount_mismatch_rolls_back_real_sqlite_data(
    write_adapter,
    actual: int,
) -> None:
    from db_adapter import ExpectedRowcountMismatchError, WriteExecutionOutcome

    where = "id = 999" if actual == 0 else "id IN (1, 2)"
    before = [
        row.status
        for row in write_adapter.execute(
            "SELECT status FROM orders WHERE id IN (1, 2) ORDER BY id"
        )
    ]

    with pytest.raises(ExpectedRowcountMismatchError) as raised:
        write_adapter.execute_write(
            f"UPDATE orders SET status = :status WHERE {where}",
            {"status": "cancelled"},
            expected_rowcount=1,
        )

    assert raised.value.actual_rowcount == actual
    assert raised.value.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
    after = [
        row.status
        for row in write_adapter.execute(
            "SELECT status FROM orders WHERE id IN (1, 2) ORDER BY id"
        )
    ]
    assert after == before


def test_omitted_expected_rowcount_preserves_legal_batch_write(
    write_adapter,
) -> None:
    result = write_adapter.execute_write(
        "UPDATE orders SET status = :status WHERE id IN (1, 2)",
        {"status": "cancelled"},
    )
    assert result["rowcount"] == 2
    assert [
        row.status
        for row in write_adapter.execute(
            "SELECT status FROM orders WHERE id IN (1, 2) ORDER BY id"
        )
    ] == ["cancelled", "cancelled"]


@pytest.mark.parametrize("invalid", [True, False, -1, 1.0, "1"])
def test_expected_rowcount_rejects_invalid_values_before_connect(invalid) -> None:
    from db_adapter import SQLiteAdapter

    adapter = SQLiteAdapter(":memory:")
    with pytest.raises((TypeError, ValueError), match="expected_rowcount"):
        adapter.execute_write("UPDATE t SET x = 1", {}, expected_rowcount=invalid)
    assert adapter._engine is None


class _FakeRawSQLite:
    def __init__(self) -> None:
        self.handlers: list[object | None] = []

    def set_progress_handler(self, handler, _interval: int) -> None:
        self.handlers.append(handler)


class _FakeTransaction:
    def __init__(self, *, commit_error=None, rollback_error=None) -> None:
        self.is_active = True
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.rollback_error:
            raise self.rollback_error


class _FakeConnection:
    def __init__(
        self,
        *,
        execute_error=None,
        commit_error=None,
        rollback_error=None,
        close_error=None,
        rowcount=1,
    ) -> None:
        self.raw = _FakeRawSQLite()
        self.connection = SimpleNamespace(dbapi_connection=self.raw, is_valid=True)
        self.transaction = _FakeTransaction(
            commit_error=commit_error,
            rollback_error=rollback_error,
        )
        self.execute_error = execute_error
        self.close_error = close_error
        self.rowcount = rowcount
        self.closed = False
        self.invalidated = False

    def begin(self):
        return self.transaction

    def execute(self, _statement, _params):
        if self.execute_error:
            raise self.execute_error
        return SimpleNamespace(rowcount=self.rowcount)

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise self.close_error


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self):
        return self.connection


def _adapter_with_fake_connection(connection: _FakeConnection) -> Any:
    from db_adapter import SQLiteAdapter

    adapter = SQLiteAdapter(":memory:")
    adapter._engine = _FakeEngine(connection)  # type: ignore[assignment]
    return adapter


def _mysql_adapter_with_fake_connection(connection: _FakeConnection) -> Any:
    from db_adapter import MySQLAdapter

    adapter = MySQLAdapter()
    adapter._engine = _FakeEngine(connection)  # type: ignore[assignment]
    return adapter


def test_execute_failure_and_successful_rollback_is_rolled_back() -> None:
    from db_adapter import WriteExecutionError, WriteExecutionOutcome, WriteExecutionPhase

    connection = _FakeConnection(execute_error=RuntimeError("execute disconnected"))
    adapter = _adapter_with_fake_connection(connection)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE t SET x = 1", {})
    assert raised.value.phase is WriteExecutionPhase.EXECUTE
    assert raised.value.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
    assert connection.transaction.rollback_calls == 1
    assert connection.raw.handlers[-1] is None
    assert connection.closed is True


def test_rollback_failure_makes_execution_outcome_unknown() -> None:
    from db_adapter import WriteExecutionError, WriteExecutionOutcome

    connection = _FakeConnection(
        execute_error=RuntimeError("execute disconnected"),
        rollback_error=RuntimeError("rollback disconnected"),
    )
    adapter = _adapter_with_fake_connection(connection)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE t SET x = 1", {})
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "rollback_failed"


@pytest.mark.parametrize("db_type", ["sqlite", "mysql"])
@pytest.mark.parametrize("disconnect_at", ["execute", "rollback", "closed"])
def test_real_sqlalchemy_local_rollback_is_not_confirmation(
    write_adapter, monkeypatch, db_type, disconnect_at,
) -> None:
    """A real RootTransaction may return without calling DBAPI rollback."""
    from sqlalchemy import event
    from sqlalchemy.exc import SAWarning
    from db_adapter import MySQLAdapter, WriteExecutionError, WriteExecutionOutcome

    engine = write_adapter._engine
    adapter = write_adapter
    if db_type == "mysql":
        # Exercise the MySQL adapter's control flow using an isolated SQLite
        # engine; this checks SQLAlchemy behavior, not MySQL network behavior.
        adapter = MySQLAdapter()
        adapter._engine = engine

        @event.listens_for(engine, "before_cursor_execute", retval=True)
        def substitute_session_setting(conn, cursor, statement, params, ctx, many):
            if statement.startswith("SET SESSION"):
                return "SELECT 1", ()
            return statement, params

    rollback_calls = []
    checkouts = []
    original_rollback = engine.dialect.do_rollback

    def count_rollback(connection):
        rollback_calls.append(True)
        return original_rollback(connection)

    monkeypatch.setattr(engine.dialect, "do_rollback", count_rollback)
    event.listen(engine, "checkout", lambda *args: checkouts.append(True))

    @event.listens_for(engine, "after_cursor_execute")
    def interrupt_write(connection, cursor, statement, params, ctx, many):
        if not statement.startswith("UPDATE orders"):
            return
        if disconnect_at == "execute":
            connection.invalidate()
            raise RuntimeError("simulated execution disconnect")
        if disconnect_at == "closed":
            connection.close()
            raise RuntimeError("simulated closed connection")

    if disconnect_at == "rollback":
        event.listen(engine, "rollback", lambda connection: connection.invalidate())

    warning_context = (
        pytest.warns(SAWarning, match="transaction already deassociated")
        if disconnect_at == "closed"
        else nullcontext()
    )
    with warning_context, pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write(
            "UPDATE orders SET status = 'cancelled'",
            {},
            expected_rowcount=1,
        )

    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "rollback_failed"
    # Closing the connection can already have resolved the transaction, but a
    # subsequent no-op rollback cannot independently certify that resolution.
    assert len(rollback_calls) == (1 if disconnect_at == "closed" else 0)
    assert len(checkouts) == 1


def test_commit_failure_stays_unknown_even_when_rollback_returns() -> None:
    from db_adapter import WriteExecutionError, WriteExecutionOutcome, WriteExecutionPhase

    connection = _FakeConnection(commit_error=RuntimeError("ack lost"))
    adapter = _adapter_with_fake_connection(connection)
    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE t SET x = 1", {})
    assert raised.value.phase is WriteExecutionPhase.COMMIT
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "commit_outcome_unknown"
    assert connection.transaction.rollback_calls == 1


@pytest.mark.parametrize(
    "adapter_factory",
    [_adapter_with_fake_connection, _mysql_adapter_with_fake_connection],
)
def test_commit_cancellation_becomes_typed_unknown(adapter_factory) -> None:
    from db_adapter import (
        WriteExecutionError,
        WriteExecutionOutcome,
        WriteExecutionPhase,
    )

    cancellation = asyncio.CancelledError()
    connection = _FakeConnection(commit_error=cancellation)
    adapter = adapter_factory(connection)

    with pytest.raises(WriteExecutionError) as raised:
        adapter.execute_write("UPDATE t SET x = 1", {})

    assert raised.value.phase is WriteExecutionPhase.COMMIT
    assert raised.value.execution_outcome is WriteExecutionOutcome.UNKNOWN
    assert raised.value.error_code == "commit_outcome_unknown"
    assert raised.value.original_error is cancellation
    assert connection.transaction.rollback_calls == 1
    assert connection.closed is True


def test_connection_cleanup_failure_does_not_downgrade_commit() -> None:
    from db_adapter import WriteExecutionOutcome

    connection = _FakeConnection(close_error=RuntimeError("pool cleanup failed"))
    result = _adapter_with_fake_connection(connection).execute_write(
        "UPDATE t SET x = 1",
        {},
        expected_rowcount=1,
    )
    assert result.execution_outcome is WriteExecutionOutcome.COMMITTED
    assert connection.transaction.commit_calls == 1


def test_cancellation_cleans_handler_transaction_and_connection() -> None:
    connection = _FakeConnection(execute_error=asyncio.CancelledError())
    adapter = _adapter_with_fake_connection(connection)
    with pytest.raises(asyncio.CancelledError):
        adapter.execute_write("UPDATE t SET x = 1", {})
    assert connection.transaction.rollback_calls == 1
    assert connection.raw.handlers[-1] is None
    assert connection.closed is True


def test_mysql_stale_conditional_updates_allow_at_most_one_commit(mysql_adapter) -> None:
    """Opt-in only: two independent pooled connections race one old state."""
    from db_adapter import ExpectedRowcountMismatchError, WriteExecutionOutcome
    from sqlalchemy import text

    engine = mysql_adapter._engine
    assert engine is not None
    table_name = f"mcp_v372_race_{uuid.uuid4().hex[:12]}"
    start = threading.Barrier(2)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE {table_name} ("
                "id INT PRIMARY KEY, status VARCHAR(32) NOT NULL"
                ") ENGINE=InnoDB"
            )
        )
        connection.execute(
            text(f"INSERT INTO {table_name} (id, status) VALUES (1, 'pending')")
        )

    # Keep two connections checked out while both previews observe the same old
    # state. Their requested next states differ, matching two separately
    # approved plans rather than replaying one plan twice.
    with (
        engine.connect() as preview_connection_a,
        engine.connect() as preview_connection_b,
    ):
        preview_a = {
            "expected_status": preview_connection_a.execute(
                text(f"SELECT status FROM {table_name} WHERE id = 1")
            ).scalar_one(),
            "new_status": "confirmed",
        }
        preview_b = {
            "expected_status": preview_connection_b.execute(
                text(f"SELECT status FROM {table_name} WHERE id = 1")
            ).scalar_one(),
            "new_status": "cancelled",
        }
    assert preview_a != preview_b
    assert preview_a["expected_status"] == preview_b["expected_status"] == "pending"

    def update(preview: dict[str, str]) -> str:
        start.wait(timeout=10)
        try:
            mysql_adapter.execute_write(
                f"UPDATE {table_name} SET status = :new_status "
                "WHERE id = 1 AND status = :expected_status",
                preview,
                expected_rowcount=1,
            )
            return "committed"
        except ExpectedRowcountMismatchError as error:
            assert error.execution_outcome is WriteExecutionOutcome.ROLLED_BACK
            return "rolled_back"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update, [preview_a, preview_b]))
        assert results.count("committed") == 1
        assert results.count("rolled_back") == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
