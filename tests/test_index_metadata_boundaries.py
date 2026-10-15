"""Index metadata identity, semantic fidelity and all-or-unavailable budgets."""

import sqlite3
from types import SimpleNamespace

import pytest
from sql_safety_executor.database.errors import DatabaseQueryError
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.database import indexes as budget_module
from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.support_adapters import MySQLAdapter, SQLiteAdapter
from tests.test_v38_config import bundle as bundle


@pytest.fixture
def adapter():
    adapter = SQLiteAdapter(":memory:")
    assert adapter.connect()
    yield adapter
    adapter.close()


def ddl(adapter, *statements):
    with adapter._engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def test_sqlite_metadata_uses_main_despite_temp_table_and_index_shadows(adapter):
    ddl(adapter,
        "CREATE TABLE allowed(x TEXT)",
        "INSERT INTO allowed VALUES ('main'), ('main2')",
        "CREATE INDEX idx_same ON allowed(x)",
        "CREATE TEMP TABLE unrelated(secret_col TEXT)",
        "CREATE INDEX temp.idx_same ON unrelated(secret_col)",
    )
    # An index can be shadowed without the allowed table itself being shadowed.
    assert adapter.get_indexes("allowed")[0]["columns"] == ["x"]
    ddl(adapter,
        "CREATE TEMP TABLE allowed(secret_data INTEGER PRIMARY KEY)",
        "INSERT INTO temp.allowed VALUES (1)",
    )
    assert [column["column_name"] for column in adapter.get_columns("allowed")] == ["x"]
    assert adapter.get_row_estimate("allowed") == 2
    assert adapter.get_tables() == [{"table_name": "allowed", "row_count": 2}]
    assert adapter.get_indexes("allowed")[0]["columns"] == ["x"]
    assert not adapter.get_indexes("allowed")[0]["primary"]


def test_sqlite_direction_and_collation_are_preserved(adapter, monkeypatch):
    ddl(adapter,
        "CREATE TABLE t(x TEXT, y TEXT)",
        "CREATE INDEX ix_mixed ON t(x COLLATE NOCASE DESC, y COLLATE BINARY ASC)",
    )
    queries = []
    original = adapter.execute

    def record(sql, **kwargs):
        queries.append(sql)
        return original(sql, **kwargs)

    monkeypatch.setattr(adapter, "execute", record)
    result = adapter.get_indexes("t")
    assert len(queries) == 2
    assert result[0]["key_parts"] == [
        {"column": "x", "sort_order": "desc", "collation": "NOCASE"},
        {"column": "y", "sort_order": "asc", "collation": "BINARY"},
    ]


@pytest.mark.parametrize("count", [128, 129])
def test_sqlite_index_count_budget_is_all_or_unavailable(adapter, count):
    ddl(adapter, "CREATE TABLE t(x TEXT)", *(
        f"CREATE INDEX ix_{i:03d} ON t(x)" for i in range(count)
    ))
    if count == 128:
        assert len(adapter.get_indexes("t")) == 128
    else:
        with pytest.raises(MetadataQueryError):
            adapter.get_indexes("t")


def test_sqlite_key_part_overflow_stops_before_second_query(adapter, monkeypatch):
    ddl(adapter, "CREATE TABLE t(x TEXT)")
    # Two legal indexes together exceed the total key-part budget. LIMIT must
    # detect overflow rather than return a success with a half composite key.
    columns = ",".join(["x"] * 1025)
    ddl(adapter, f"CREATE INDEX ix_a ON t({columns})", f"CREATE INDEX ix_b ON t({columns})")
    calls = []
    original = adapter.execute

    def record(sql, **kwargs):
        calls.append(sql)
        return original(sql, **kwargs)

    monkeypatch.setattr(adapter, "execute", record)
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")
    assert len(calls) == 1


def test_sqlite_json_budget_counts_utf8_bytes_not_characters(adapter):
    # The character count is below 64 KiB, but UTF-8 output is larger.
    name = "测" * 22000
    ddl(adapter, "CREATE TABLE t(x TEXT)", f'CREATE INDEX "{name}" ON t(x)')
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")


@pytest.mark.parametrize("expired_after_first", [True, False])
def test_sqlite_collection_shares_deadline_and_stops_when_expired(monkeypatch, expired_after_first):
    clock = [0.0]
    monkeypatch.setattr(budget_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    adapter = SQLiteAdapter(":memory:")
    timeouts = []

    def execute(sql, *, timeout, params):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            clock[0] = 31.0 if expired_after_first else 20.0
            return [("ix", 0, "c", 0, 0, 0, "x", 0, "BINARY")]
        clock[0] = 31.0
        return []

    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")
    assert timeouts == ([30.0] if expired_after_first else [30.0, 10.0])


def test_mysql_legacy_visibility_is_unknown_without_an_error_fallback(monkeypatch):
    adapter = MySQLAdapter()
    calls = []

    def execute(sql, **kwargs):
        calls.append(sql)
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return []
        assert "NULL AS IS_VISIBLE" in sql
        return [("ix", 1, 1, "x", "BTREE", 8, "A", None)]

    monkeypatch.setattr(adapter, "execute", execute)
    result = adapter.get_indexes("t")
    assert result[0]["visible"] is None
    assert result[0]["key_parts"][0]["prefix_length"] == 8
    assert len(calls) == 2


@pytest.mark.parametrize("fail_probe", [True, False])
def test_mysql_metadata_errors_fail_closed_without_legacy_retry(monkeypatch, fail_probe):
    adapter = MySQLAdapter()
    calls = []

    def execute(sql, **kwargs):
        calls.append(sql)
        if len(calls) == 1 and not fail_probe:
            return [("IS_VISIBLE",)]
        raise DatabaseQueryError("database_access_denied")

    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")
    assert len(calls) == (1 if fail_probe else 2)


def test_mysql_key_part_limit_does_not_return_a_partial_composite_key(monkeypatch):
    adapter = MySQLAdapter()

    def execute(sql, **kwargs):
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return [("IS_VISIBLE",)]
        assert kwargs["params"]["row_limit"] == 2049
        return [("ix", 1, seq, "x", "BTREE", None, "A", "YES") for seq in range(2049)]

    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")


def test_mysql_expired_capability_probe_does_not_start_index_query(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(budget_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    adapter = MySQLAdapter()
    calls = []

    def execute(sql, **kwargs):
        calls.append(sql)
        clock[0] = 31.0
        return [("IS_VISIBLE",)]

    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(MetadataQueryError):
        adapter.get_indexes("t")
    assert len(calls) == 1


@pytest.fixture
def server(bundle, tmp_path):
    main, connections, _skills, save = bundle
    path = tmp_path / "indexes.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE widgets(id INTEGER PRIMARY KEY, name TEXT)")
        for index in range(129):
            db.execute(f"CREATE INDEX ix_{index:03d} ON widgets(name)")
    main["server"]["default_connection"] = "allowed"
    connections["connections"] = {
        alias: {"type": "sqlite", "sqlite": {"path": str(path)}, "read": read}
        for alias, read in (
            ("allowed", {"mode": "allowlist", "tables": ["widgets"]}),
            ("blocked", {"mode": "allowlist", "tables": ["other"]}),
            ("denied", {"mode": "deny"}),
        )
    }
    server = create_server(load_config(save()))
    yield server
    server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_index_budget_overflow_preserves_columns_over_mcp(server, mode):
    async with Client(server, mode=mode) as client:
        result = await client.call_tool("describe_table", {"table_name": "widgets"})
    payload = result.structured_content
    assert payload["success"] is True
    assert payload["connection_id"] == "allowed"
    assert payload["columns"]
    assert payload["indexes"] is None
    assert payload["indexes_status"] == "unavailable"
    assert payload["indexes_error"] == "Index metadata could not be read"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_index_metadata_authorization_precedes_any_io(server, mode, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Denied index metadata request reached database I/O")

    for alias in ("allowed", "blocked", "denied"):
        monkeypatch.setattr(server.gateway_runtime.registry.get_adapter(alias), "execute", unexpected)
    async with Client(server, mode=mode) as client:
        for alias in ("blocked", "denied", "missing"):
            result = await client.call_tool("describe_table", {
                "table_name": "widgets", "connection_id": alias,
            }, raise_on_error=False)
            assert result.is_error or result.structured_content["success"] is False


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_full_schema_never_collects_indexes(server, mode, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Broad schema output collected per-table indexes")

    adapter = server.gateway_runtime.registry.get_adapter("allowed")
    monkeypatch.setattr(adapter, "get_indexes", unexpected)
    async with Client(server, mode=mode) as client:
        for level, grouped in (("compact", True), ("compact", False), ("full", True)):
            result = await client.call_tool("get_full_schema", {
                "detail_level": level, "group_identical": grouped,
            })
            assert result.structured_content["success"] is True
