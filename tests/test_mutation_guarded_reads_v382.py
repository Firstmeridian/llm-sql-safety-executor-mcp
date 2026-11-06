"""Reviewed Mutation reads keep write-only previews and controlled sessions."""

import importlib.util
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sql_safety_executor.core.policy import _prepare_sql_read
from sql_safety_executor.core.types import OperationError
from sql_safety_executor.database.authorizer import SQLiteReadGuard
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.execution import operation_analysis, operation_kind
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.mysql import MySQLAdapter
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.sqlite import SQLiteAdapter
from sql_safety_executor.skills.mutation import resolve_managed_plan_values


DEMOS = [
    ("sample-update-order-status", {"order_id": 2, "new_status": "shipped"}, "shipped"),
    ("sample-reset-order-to-pending", {"order_id": 2, "expected_status": "confirmed"}, "pending"),
]


def load_demo(adapter, name=DEMOS[0][0]):
    path = Path(__file__).resolve().parents[1] / "skills" / name / "mutation.py"
    spec = importlib.util.spec_from_file_location(f"guarded_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Mutation(adapter, Mock())


@pytest.fixture
def adapter(tmp_path):
    path = tmp_path / "orders.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT);
            INSERT INTO orders VALUES (1, 'pending'), (2, 'confirmed'), (3, 'cancelled');
            CREATE TABLE secrets(id INTEGER PRIMARY KEY, status TEXT);
            INSERT INTO secrets VALUES (2, 'secret');
            CREATE TABLE "other.orders"(id INTEGER PRIMARY KEY, status TEXT);
            INSERT INTO "other.orders" VALUES (2, 'literal dotted name');
        """)
    value = SQLiteAdapter(config=DatabaseConfig(
        "fixture", "sqlite", 5, 5,
        ConnectionPolicy(read_mode="deny", allow_mutations=True),
        sqlite_database_path=str(path),
    ))
    yield value
    value.close()


@pytest.mark.parametrize("name,params,new_status", DEMOS)
@pytest.mark.parametrize("read_mode", ["deny", "allowlist"])
def test_write_only_demo_preview_uses_fresh_guarded_scope(
    adapter, monkeypatch, name, params, new_status, read_mode,
):
    adapter._config = replace(adapter._config, policy=ConnectionPolicy(
        read_mode=read_mode, allow_mutations=True, mutation_skills=frozenset({name}),
    ))
    ordinary_policy = adapter._config.policy
    sql = "SELECT status FROM orders WHERE id = :order_id"
    assert _prepare_sql_read(None, sql, ordinary_policy, adapter=adapter).decision.error_code == "read_disabled"
    with pytest.raises(DatabaseQueryError, match="Reading is disabled"):
        adapter.execute_read(sql, params=params, policy=ordinary_policy)

    reads = Mock(wraps=adapter.execute_read)
    monkeypatch.setattr(adapter, "execute_read", reads)
    monkeypatch.setattr(adapter, "execute_write", lambda *a, **kw: pytest.fail("preview wrote"))
    callbacks = []
    authorize = SQLiteReadGuard.authorize

    def record_authorization(self, action, first, second, database, source):
        callbacks.append((action, first, database, operation_kind()))
        return authorize(self, action, first, second, database, source)

    monkeypatch.setattr(SQLiteReadGuard, "authorize", record_authorization)
    mutation = load_demo(adapter, name)
    validation = mutation.validate(params)
    preview = mutation.preview(params)
    binding = mutation.build_execution_binding(params, validation, preview)
    bound, result = resolve_managed_plan_values(
        mutation.managed_plan, params=params, execution_binding=binding,
    )
    assert validation["valid"] is True
    assert preview["current_status"] == "confirmed"
    assert preview["requires_confirmation"] is True
    assert "preview_sql" not in preview and "bound_params" not in preview
    assert binding == {"expected_status": "confirmed"}
    assert bound == {"order_id": 2, "expected_status": "confirmed", "new_status": new_status}
    assert result == {"previous_status": "confirmed", "new_status": new_status}
    assert reads.call_count == 2
    policies = [call.kwargs["policy"] for call in reads.call_args_list]
    assert policies[0] is not policies[1]
    for call in reads.call_args_list:
        policy, analysis = call.kwargs["policy"], call.kwargs["analysis"]
        assert policy is not ordinary_policy
        assert policy.allowed_relations == frozenset({RelationReference("orders", "main")})
        assert analysis.source_sql == call.args[0]
        assert analysis.context_key == adapter.analysis_context.fingerprint
        assert call.kwargs["params"] == {"order_id": 2}
    assert (sqlite3.SQLITE_READ, "orders", "main", "read") in callbacks
    assert not any(action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
                   for action, *_ in callbacks)
    assert adapter._config.policy is ordinary_policy
    assert _prepare_sql_read(None, sql, ordinary_policy, adapter=adapter).decision.error_code == "read_disabled"
    with sqlite3.connect(adapter._config.sqlite_database_path) as connection:
        assert connection.execute("SELECT status FROM orders WHERE id=2").fetchone() == ("confirmed",)


@pytest.mark.parametrize("sql", [
    "UPDATE orders SET status='shipped'",
    "DELETE FROM orders",
    "SELECT status FROM orders; DELETE FROM orders",
    "SELECT sleep(0) FROM orders",
    "SELECT benchmark(1, 1) FROM orders",
    "SELECT load_file('/tmp/private') FROM orders",
    "SELECT get_lock('preview', 0) FROM orders",
    "SELECT current_user() FROM orders",
    "SELECT * FROM pragma_table_info('orders')",
    "SELECT status FROM secrets",
    "SELECT status FROM orders WHERE EXISTS (SELECT 1 FROM secrets)",
    "WITH q AS (SELECT status FROM secrets) SELECT * FROM q",
    "SELECT status FROM other.orders",
    'SELECT status FROM "other.orders"',
    "SELECT status FROM orders UNION SELECT status FROM orders",
])
def test_shared_policy_blocks_unreviewed_operations_before_execution(adapter, monkeypatch, sql):
    # A broad ordinary query grant must not widen the reviewed Skill scope.
    adapter._config = replace(adapter._config, policy=ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}), allow_union=True,
    ))
    executor = Mock(side_effect=AssertionError("rejected SQL reached the adapter"))
    monkeypatch.setattr(adapter, "execute_read", executor)
    with pytest.raises((OperationError, DatabaseQueryError)):
        load_demo(adapter)._execute_read(sql, tables=("orders",))
    executor.assert_not_called()


def test_reviewed_names_preserve_structural_identity(adapter):
    mutation = load_demo(adapter)
    assert mutation._execute_read(
        'SELECT status FROM "other.orders" WHERE id=:id',
        tables=("other.orders",), params={"id": 2},
    )[0].status == "literal dotted name"
    with pytest.raises(OperationError, match="Access denied to table"):
        mutation._execute_read("SELECT status FROM other.orders", tables=("other.orders",))


@pytest.mark.parametrize("tables", [(), ("*",), ("",), ("orders\x00",)])
def test_reviewed_scope_must_be_explicit(adapter, monkeypatch, tables):
    executor = Mock()
    monkeypatch.setattr(adapter, "execute_read", executor)
    with pytest.raises(ValueError, match="explicit reviewed table names"):
        load_demo(adapter)._execute_read("SELECT status FROM orders", tables=tables)
    executor.assert_not_called()


def test_missing_read_protocol_never_falls_back_to_trusted_execute(adapter):
    trusted = Mock()
    incomplete = SimpleNamespace(
        analysis_context=adapter.analysis_context,
        resolve_analysis_context=adapter.resolve_analysis_context, execute=trusted,
    )
    with pytest.raises(AttributeError, match="execute_read"):
        load_demo(incomplete).validate(DEMOS[0][1])
    trusted.assert_not_called()


@pytest.mark.parametrize("context", [None, SimpleNamespace(default_schema="main")])
def test_invalid_adapter_context_is_not_guessed(adapter, monkeypatch, context):
    monkeypatch.setattr(adapter, "resolve_analysis_context", lambda: context)
    executor = Mock()
    monkeypatch.setattr(adapter, "execute_read", executor)
    with pytest.raises(DatabaseQueryError) as failure:
        load_demo(adapter).validate(DEMOS[0][1])
    assert failure.value.error_code == "session_semantics_unavailable"
    executor.assert_not_called()


def test_sqlite_resolved_temp_shadow_is_not_granted(adapter):
    assert adapter.connect()
    with adapter._engine.connect() as connection:
        connection.exec_driver_sql("CREATE TEMP TABLE orders(id INTEGER, status TEXT)")
        connection.exec_driver_sql("INSERT INTO temp.orders VALUES(2, 'secret shadow')")
        connection.commit()
    mutation = load_demo(adapter)
    with pytest.raises(DatabaseQueryError) as failure:
        mutation.validate(DEMOS[0][1])
    assert failure.value.error_code == "table_access_denied"
    assert mutation._execute_read(
        "SELECT status FROM main.orders WHERE id=:id", tables=("orders",), params={"id": 2},
    )[0].status == "confirmed"


def test_sqlite_view_cannot_invoke_reserved_function(adapter):
    assert adapter.connect()
    invocations = []
    with adapter._engine.connect() as connection:
        raw = connection.connection.dbapi_connection
        raw.create_function("sleep", 1, lambda delay: invocations.append(delay) or "confirmed")
        connection.exec_driver_sql("ALTER TABLE orders RENAME TO original_orders")
        connection.exec_driver_sql("CREATE VIEW orders AS SELECT id, sleep(0) AS status FROM original_orders")
        connection.commit()
    with pytest.raises(DatabaseQueryError) as failure:
        load_demo(adapter).validate(DEMOS[0][1])
    assert failure.value.error_code == "expensive_function_denied"
    assert invocations == []


@pytest.mark.parametrize("name,params,new_status", DEMOS)
def test_mysql_demo_reads_reuse_session_but_trusted_callbacks_retire(
    monkeypatch, name, params, new_status,
):
    adapter = MySQLAdapter(DatabaseConfig(
        "fixture", "mysql", 5, 5,
        ConnectionPolicy(read_mode="deny", allow_mutations=True),
        mysql_database="business", mysql_sql_mode=("ANSI_QUOTES", "NO_BACKSLASH_ESCAPES"),
    ))
    events = []

    class Connection:
        def __enter__(self):
            events.append(("checkout", operation_kind()))
            return self

        def __exit__(self, *args):
            events.append(("return", operation_kind()))

        def execute(self, statement, parameters=None):
            events.append(("execute", operation_kind(), str(statement), parameters, operation_analysis()))
            return SimpleNamespace(fetchall=lambda: [SimpleNamespace(id=2, status="confirmed")])

        def invalidate(self):
            events.append(("invalidate", operation_kind()))

    monkeypatch.setattr(adapter, "_engine", SimpleNamespace(connect=Connection))
    monkeypatch.setattr(adapter, "connect", lambda: pytest.fail("attempted a real MySQL connection"))
    mutation = load_demo(adapter, name)
    validation, preview = mutation.validate(params), mutation.preview(params)
    assert validation["valid"] is True and preview["current_status"] == "confirmed"
    assert mutation.build_execution_binding(params, validation, preview) == {"expected_status": "confirmed"}
    reads = [event for event in events if event[0] == "execute" and event[2].startswith("SELECT")]
    assert len(reads) == 2
    for _, kind, sql, bindings, analysis in reads:
        assert kind == "read"
        assert bindings == {"order_id": 2}
        assert analysis.source_sql == sql
        assert analysis.context_key == adapter.resolve_analysis_context().fingerprint
    assert not any(event[0] == "invalidate" for event in events)
    assert operation_kind() == "trusted" and operation_analysis() is None

    # Even an arbitrary trusted SELECT retains the existing retirement rule.
    adapter.execute("SELECT status FROM orders WHERE id=:order_id", params={"order_id": 2})
    adapter.execute("SET SESSION sql_mode = ''")
    assert [event for event in events if event[0] == "invalidate"] == [
        ("invalidate", "trusted"), ("invalidate", "trusted"),
    ]


def test_mysql_helper_uses_resolved_sql_mode_and_exact_relation_scope(monkeypatch):
    adapter = MySQLAdapter(DatabaseConfig(
        "fixture", "mysql", 5, 5, ConnectionPolicy(read_mode="deny"),
        mysql_database="business", mysql_sql_mode=(),
    ))
    resolved = replace(adapter.analysis_context, sql_modes=frozenset({"ANSI_QUOTES"}))
    monkeypatch.setattr(adapter, "resolve_analysis_context", lambda: resolved)
    executor = Mock(return_value=[])
    monkeypatch.setattr(adapter, "execute_read", executor)
    mutation = load_demo(adapter)
    sql = 'SELECT status FROM "orders" WHERE id=:id'
    mutation._execute_read(sql, tables=("orders",), params={"id": 2})
    assert executor.call_args.kwargs["analysis"].context_key == resolved.fingerprint
    assert executor.call_args.kwargs["policy"].allowed_relations == frozenset({RelationReference("orders", "business")})
    for denied in ("SELECT status FROM Orders", "SELECT status FROM another.orders"):
        with pytest.raises(OperationError, match="Access denied to table"):
            mutation._execute_read(denied, tables=("orders",))
    assert executor.call_count == 1
