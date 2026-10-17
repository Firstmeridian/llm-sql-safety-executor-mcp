"""Physical-session initialization and isolation, without a live MySQL server."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.mysql import MySQLAdapter


def adapter(modes=None):
    return MySQLAdapter(DatabaseConfig(
        "fixture", "mysql", 5, 5, ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}), case_sensitive_tables=True),
        mysql_database="business", mysql_sql_mode=modes))


class Session:
    def __init__(self, modes, *, ignore_set=False):
        self.modes = modes
        self.ignore_set = ignore_set
        self.calls = []
        self.closed = False

    def cursor(self):
        return self

    def execute(self, sql, parameters=()):
        self.calls.append((sql, parameters))
        if sql.startswith("SET") and not self.ignore_set:
            self.modes = parameters[0]

    def fetchone(self):
        return (self.modes,)

    def close(self):
        self.closed = True


@pytest.mark.parametrize("configured", [None, (), ("ANSI_QUOTES", "STRICT_TRANS_TABLES"), ("NO_BACKSLASH_ESCAPES", "STRICT_TRANS_TABLES")])
def test_each_physical_session_uses_one_complete_contract(configured):
    value = adapter(configured)
    first = Session("ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES")
    record = SimpleNamespace(info={})
    value._initialize_session(first, record)
    expected = frozenset(configured) if configured is not None else frozenset({"ONLY_FULL_GROUP_BY", "STRICT_TRANS_TABLES"})
    assert value.analysis_context.sql_modes == expected
    assert record.info["sql_modes"] == expected
    assert first.closed
    second = Session("NO_ENGINE_SUBSTITUTION")
    second_record = SimpleNamespace(info={})
    value._initialize_session(second, second_record)
    assert frozenset(second.modes.split(",")) - {""} == expected
    assert second_record.info["sql_modes"] == expected
    assert second.closed
    assert any(sql.startswith("SET SESSION sql_mode") for sql, _ in second.calls)


def test_failed_verification_does_not_publish_a_session_profile():
    value = adapter(("ANSI_QUOTES",))
    session = Session("STRICT_TRANS_TABLES", ignore_set=True)
    with pytest.raises(DatabaseQueryError) as failure:
        value._initialize_session(session, SimpleNamespace(info={}))
    assert failure.value.error_code == "session_semantics_unavailable"
    assert value._session_modes is None
    assert session.closed


def test_explicit_context_is_available_without_connecting(monkeypatch):
    value = adapter(("ANSI_QUOTES", "STRICT_TRANS_TABLES"))
    monkeypatch.setattr(value, "connect", lambda: pytest.fail("Explicit context must not probe a session"))
    for _ in range(3):
        assert value.resolve_analysis_context().sql_modes == frozenset({"ANSI_QUOTES", "STRICT_TRANS_TABLES"})


def test_mode_order_is_not_a_semantic_difference():
    value = adapter(("ANSI_QUOTES", "STRICT_TRANS_TABLES"))
    session = Session("STRICT_TRANS_TABLES,ANSI_QUOTES")
    value._initialize_session(session, SimpleNamespace(info={}))
    assert all(not sql.startswith("SET") for sql, _ in session.calls)


def test_retiring_write_session_is_cleanup_not_outcome_reinterpretation():
    events = []
    connection = SimpleNamespace(invalidate=lambda: events.append("retire"), close=lambda: events.append("close"))
    adapter()._retire_write_connection(connection)
    assert events == ["retire", "close"]


def test_retirement_failure_still_closes_connection():
    events = []
    def fail():
        raise RuntimeError("private cleanup detail")
    connection = SimpleNamespace(invalidate=fail, close=lambda: events.append("close"))
    adapter()._retire_write_connection(connection)
    assert events == ["close"]


@pytest.mark.parametrize("sql", [
    "SELECT n FROM hidden",
    "WITH F AS (SELECT n FROM hidden) SELECT n FROM f",
    "WITH hidden AS (SELECT n FROM hidden) SELECT n FROM hidden",
    "WITH first_cte AS (SELECT n FROM hidden), hidden AS (SELECT 7 AS n) SELECT n FROM first_cte",
])
def test_definitely_denied_physical_target_does_not_initialize_a_session(monkeypatch, sql):
    from sql_safety_executor.core.policy import _validate_sql_query_policy
    value = adapter()  # Inherited sql_mode has not been discovered.
    monkeypatch.setattr(value, "connect", lambda: pytest.fail("A definite denial initialized a database session"))
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), case_sensitive_tables=True)
    assert _validate_sql_query_policy(None, sql, policy, adapter=value).error_code == "table_access_denied"
