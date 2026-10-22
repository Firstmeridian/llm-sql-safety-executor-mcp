"""Fixed SQLite metadata PRAGMAs keep business-name collisions harmless."""
from fastmcp import Client
import pytest

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.support_adapters import SQLiteAdapter
from tests.test_external_read_review_v382 import review_server, bundle


NAMES = ["pragma_table_xinfo", "pragma_table_info", "pragma_index_list", "pragma_index_xinfo"]


def quote(name):
    return '"' + name.replace('"', '""') + '"'


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("schema", ["main", "temp", "aux"])
@pytest.mark.parametrize("kind", ["table", "view"])
@pytest.mark.parametrize("name", NAMES)
async def test_catalog_collisions_do_not_break_columns_indexes_or_schema(review_server, mode, schema, kind, name):
    server = review_server("SELECT z,s FROM main.widgets", ddl="""
        CREATE TABLE widgets(id INTEGER PRIMARY KEY, x TEXT UNIQUE, y INTEGER,
            z TEXT AS (upper(x)) VIRTUAL, s INTEGER AS (y*2) STORED);
        INSERT INTO widgets(id,x,y) VALUES(1,'hello',3);
        CREATE INDEX ix_mixed ON widgets(x COLLATE NOCASE DESC, y ASC);
        CREATE INDEX ix_expression ON widgets(lower(x));
        """, read={"mode": "allowlist", "tables": ["widgets"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    columns = adapter.get_columns("widgets")
    indexes = adapter.get_indexes("widgets")
    with adapter._engine.begin() as db:
        if schema == "aux":
            db.exec_driver_sql("ATTACH ':memory:' AS aux")
        target = quote(schema) + "." + quote(name)
        db.exec_driver_sql(f"CREATE TABLE {target}(name)" if kind == "table"
                           else f"CREATE VIEW {target} AS SELECT 7 AS name")
        # Unrelated same-name tables/indexes must not replace main metadata.
        if schema != "main":
            db.exec_driver_sql(f"CREATE TABLE {quote(schema)}.widgets(secret)")
            db.exec_driver_sql(f"CREATE INDEX {quote(schema)}.ix_mixed ON widgets(secret)")
    async with Client(server, mode=mode) as client:
        result = (await client.call_tool("query", {"sql": "SELECT z,s FROM main.widgets"})).structured_content
        assert result["data"] == [{"z": "HELLO", "s": 6}]
        result = (await client.call_tool("describe_table", {"table_name": "widgets"})).structured_content
        assert result["success"] and result["column_count"] == 5 and result["indexes_status"] == "complete"
        assert result["columns"] == columns and result["indexes"] == indexes
        by_name = {i["name"]: i for i in result["indexes"]}
        assert by_name["ix_mixed"]["key_parts"][0] == {
            "column": "x", "sort_order": "desc", "collation": "NOCASE"}
        assert by_name["ix_expression"]["has_expression"]
        assert [i for i in result["indexes"] if i["primary"]][0]["columns"] == ["id"]
        for level in ["compact", "full"]:
            schema_result = (await client.call_tool("get_full_schema", {"detail_level": level})).structured_content
            assert schema_result["success"] and schema_result["total_columns"] == 5
            assert schema_result["returned_table_count"] == 1


@pytest.mark.parametrize("name", ["normal", "O'Reilly", 'monthly "group":2026.data', " f ", "  f  "])
def test_pragma_target_and_index_literals_preserve_business_names(name):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        index = "idx '" + name + '":quarterly.report'
        with adapter._engine.begin() as db:
            db.exec_driver_sql(f"CREATE TABLE {quote(name)}(x TEXT)")
            db.exec_driver_sql(f"CREATE INDEX {quote(index)} ON {quote(name)}(x COLLATE NOCASE DESC)")
        assert [c["column_name"] for c in adapter.get_columns(name)] == ["x"]
        found = adapter.get_indexes(name)
        assert len(found) == 1 and found[0]["name"] == index
        assert found[0]["key_parts"] == [{"column": "x", "sort_order": "desc", "collation": "NOCASE"}]
    finally:
        adapter.close()


def test_private_fetch_bound_returns_overflow_sentinel_and_releases_cursor():
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE t(n)")
            db.exec_driver_sql("INSERT INTO t VALUES(1),(2),(3),(4)")
        rows = adapter.execute("SELECT n FROM t", _fetch_limit=2)
        assert [row[0] for row in rows] == [1, 2, 3]
        # Normal calls still fetch the complete result and need no new option.
        assert len(adapter.execute("SELECT n FROM t")) == 4
        assert adapter.get_columns("t")[0]["column_name"] == "n"
    finally:
        adapter.close()


def test_pragma_overflow_is_unavailable_and_does_not_change_later_reads(monkeypatch):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE t(a,b,c)")
        original = adapter.execute
        limits = []
        def execute(sql, **kwargs):
            limits.append(kwargs.get("_fetch_limit"))
            return original(sql, **kwargs)
        monkeypatch.setattr(adapter, "execute", execute)
        with pytest.raises(MetadataQueryError):
            adapter._metadata_pragma("reading table columns", "table_xinfo", "t", row_limit=1)
        assert limits == [1]
        assert len(adapter.get_columns("t")) == 3
    finally:
        adapter.close()


def test_metadata_failures_do_not_escape_as_raw_driver_errors(monkeypatch):
    adapter = SQLiteAdapter(":memory:")
    def execute(*args, **kwargs):
        raise DatabaseQueryError("database_access_denied")
    monkeypatch.setattr(adapter, "execute", execute)
    for read in [adapter.get_columns, adapter.get_indexes]:
        with pytest.raises(MetadataQueryError):
            read("t")
    adapter.close()


def test_without_rowid_auxiliary_columns_are_not_public_key_parts():
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE t(a,b,c,PRIMARY KEY(a,b)) WITHOUT ROWID")
            db.exec_driver_sql("CREATE INDEX ix_c ON t(c DESC)")
        indexes = adapter.get_indexes("t")
        ordinary = next(i for i in indexes if i["name"] == "ix_c")
        assert ordinary["columns"] == ["c"] and len(ordinary["key_parts"]) == 1
        assert next(i for i in indexes if i["primary"])["columns"] == ["a", "b"]
    finally:
        adapter.close()

