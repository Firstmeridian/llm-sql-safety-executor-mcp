"""Adapter boundaries bind supplied analysis to the exact original statement."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.base import DatabaseAdapter
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.mysql import MySQLAdapter
from sql_safety_executor.database.sqlite import SQLiteAdapter


def mysql():
    return MySQLAdapter(DatabaseConfig(
        "fixture", "mysql", 5, 5, ConnectionPolicy(read_mode="all"),
        mysql_database="fixture", mysql_sql_mode=(),
    ))


@pytest.mark.parametrize("sql", [
    "SELECT 99 AS n", "select 7 as n", "SELECT 7 AS n ",
    "SELECT 7 AS n /* different source */", "SELECT n FROM hidden",
])
def test_mysql_mismatched_source_never_reaches_executor(monkeypatch, sql):
    adapter = mysql()
    analysis = analyze_sql("SELECT 7 AS n", adapter.analysis_context)
    assert analysis.complete
    executor = Mock(return_value=[])
    monkeypatch.setattr(DatabaseAdapter, "execute_read", executor)
    with pytest.raises(DatabaseQueryError) as failure:
        adapter.execute_read(sql, policy=adapter._config.policy, analysis=analysis)
    assert failure.value.error_code == "session_semantics_unavailable"
    executor.assert_not_called()


@pytest.mark.parametrize("provided", [True, False])
def test_mysql_matching_source_preserves_original_and_bindings(monkeypatch, provided):
    adapter = mysql()
    sql = "SELECT :n AS n /* original source */"
    analysis = analyze_sql(sql, adapter.analysis_context) if provided else None
    executor = Mock(return_value=[(7,)])
    monkeypatch.setattr(DatabaseAdapter, "execute_read", executor)
    params = {"n": 7}
    assert adapter.execute_read(sql, 3, params, policy=adapter._config.policy, analysis=analysis) == [(7,)]
    args, kwargs = executor.call_args
    assert args == (sql, 3, params)
    assert kwargs["analysis"].source_sql == sql
    assert kwargs["analysis"].context_key == adapter.analysis_context.fingerprint
    assert kwargs["policy"] is adapter._config.policy


@pytest.mark.parametrize("fault", ["schema", "mode", "incomplete", "write"])
def test_mysql_other_analysis_preconditions_still_hold(monkeypatch, fault):
    adapter = mysql()
    sql = "UPDATE orders SET n=7" if fault == "write" else "SELECT 7 AS n"
    context = adapter.analysis_context
    if fault == "schema": context = replace(context, default_schema="another")
    if fault == "mode": context = replace(context, sql_modes=frozenset({"ANSI_QUOTES"}))
    analysis = analyze_sql(sql, context)
    if fault == "incomplete": analysis = replace(analysis, status="partial")
    executor = Mock(return_value=[])
    monkeypatch.setattr(DatabaseAdapter, "execute_read", executor)
    with pytest.raises(DatabaseQueryError) as failure:
        adapter.execute_read(sql, policy=adapter._config.policy, analysis=analysis)
    assert failure.value.error_code == ("read_only_required" if fault == "write" else "session_semantics_unavailable")
    executor.assert_not_called()


def test_sqlite_mismatched_source_retains_preconnect_rejection(tmp_path, monkeypatch):
    path = tmp_path / "must-not-open.db"
    policy = ConnectionPolicy(read_mode="all")
    adapter = SQLiteAdapter(config=DatabaseConfig(
        "fixture", "sqlite", 5, 5, policy, sqlite_database_path=str(path),
    ))
    monkeypatch.setattr(adapter, "connect", lambda: pytest.fail("mismatch reached database setup"))
    with pytest.raises(DatabaseQueryError) as failure:
        adapter.execute_read("SELECT 99 AS n", policy=policy,
                             analysis=analyze_sql("SELECT 7 AS n", adapter.analysis_context))
    assert failure.value.error_code == "session_semantics_unavailable"
    assert not path.exists()
