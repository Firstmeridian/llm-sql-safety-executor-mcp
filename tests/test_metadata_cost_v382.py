"""Metadata projection work stays bounded without bypassing guarded data reads."""
from dataclasses import replace
import sqlite3

from fastmcp import Client
import pytest
from sqlalchemy.dialects import sqlite

from sql_safety_executor import create_server, load_config
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.outcomes import MetadataQueryError
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.transport import statement_text
from tests.support_adapters import SQLiteAdapter
from tests.test_v38_config import bundle as bundle


def ddl(adapter, sql):
    assert adapter.connect()
    with adapter._engine.begin() as db:
        db.exec_driver_sql(sql)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("analyzed", [False, True])
@pytest.mark.parametrize("tool,args", [
    ("list_tables", {}),
    ("get_full_schema", {"detail_level": "compact"}),
    ("get_full_schema", {"detail_level": "full"}),
])
async def test_projection_precedes_estimates(bundle, tmp_path, monkeypatch, mode, analyzed, tool, args):
    settings, connections, _, save = bundle
    settings["limits"] = {"overview_tables": 2, "schema_tables": 2}
    connections["connections"]["demo"]["read"] = {
        "mode": "allowlist", "tables": ["main.t02", "main.t04", "main.t06"]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        for index in range(7):
            db.execute(f"CREATE TABLE t{index:02}(n INTEGER)")
            db.executemany(f"INSERT INTO t{index:02} VALUES(?)", [(7,)] * (index + 1))
        if analyzed:
            db.execute("ANALYZE")
    server = create_server(load_config(save()))
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    original_read = adapter.execute_read
    reads = []

    def read(sql, *a, **kw):
        reads.append(sql)
        assert '"main"."t02"' in sql or '"main"."t04"' in sql
        return original_read(sql, *a, **kw)

    monkeypatch.setattr(adapter, "execute_read", read)
    assert adapter.connect()
    with adapter._engine.connect() as db:
        raw = db.connection.dbapi_connection
    trace = []
    raw.set_trace_callback(trace.append)
    try:
        async with Client(server, mode=mode) as client:
            payload = (await client.call_tool(tool, args)).structured_content
        assert payload["success"] and payload["truncated"]
        assert payload["total_tables"] == 3 and payload["returned_table_count"] == 2
        if tool == "list_tables":
            assert payload["tables"] == [
                {"table_name": "t02", "row_count": 3},
                {"table_name": "t04", "row_count": 5}]
        elif args["detail_level"] == "full":
            assert list(payload["schema"]) == ["t02", "t04"]
            assert [entry["row_count"] for entry in payload["schema"].values()] == [3, 5]
        else:
            assert [t["name"] for group in payload["schema_groups"] for t in group["tables"]] == ["t02", "t04"]
        assert len(reads) == (0 if analyzed else 2)
        assert sum("name='sqlite_stat1'" in sql for sql in trace) == 1
        assert sum("FROM main.sqlite_stat1" in sql for sql in trace) == int(analyzed)
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


def test_discovery_does_not_read_data_and_empty_projection_does_not_read_stats(monkeypatch):
    adapter = SQLiteAdapter(":memory:")
    ddl(adapter, "CREATE TABLE orders(n)")
    ddl(adapter, "INSERT INTO orders VALUES(7)")
    monkeypatch.setattr(adapter, "execute_read", lambda *a, **kw: pytest.fail("Directory must not evaluate data"))
    assert adapter.get_table_directory() == [{"table_name": "orders", "row_count": None}]
    monkeypatch.setattr(adapter, "_execute_metadata", lambda *a, **kw: pytest.fail("Empty projection needs no statistics"))
    assert adapter.enrich_row_estimates([]) == []
    adapter.close()


@pytest.mark.parametrize("invalid", ["garbage", "-9", "", sqlite3.Binary(b"bad")])
def test_statistics_partial_invalid_and_refreshed_each_call(tmp_path, invalid):
    path = tmp_path / "stats.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE a(n); CREATE TABLE b(n); CREATE TABLE c(n);"
                        "INSERT INTO a VALUES(1); INSERT INTO b VALUES(1),(2);"
                        "INSERT INTO c VALUES(1),(2),(3); ANALYZE;")
        db.execute("UPDATE sqlite_stat1 SET stat=? WHERE tbl='b'", (invalid,))
        db.execute("DELETE FROM sqlite_stat1 WHERE tbl='c'")
    adapter = SQLiteAdapter(path)
    try:
        assert adapter.get_tables() == [
            {"table_name": "a", "row_count": 1},
            {"table_name": "b", "row_count": 2},
            {"table_name": "c", "row_count": 3}]
        with sqlite3.connect(path) as db:
            db.executescript("INSERT INTO a VALUES(2); ANALYZE;")
        assert adapter.get_row_estimate("a") == 2
        with sqlite3.connect(path) as db:
            db.executescript("DROP TABLE sqlite_stat1; INSERT INTO a VALUES(3);")
        assert adapter.get_row_estimate("a") == 3
    finally:
        adapter.close()


def test_disappearing_statistics_falls_back_but_database_failures_do_not(monkeypatch):
    adapter = SQLiteAdapter(":memory:")
    ddl(adapter, "CREATE TABLE orders(n)")
    ddl(adapter, "INSERT INTO orders VALUES(7)")
    ddl(adapter, "ANALYZE")
    original = adapter.execute
    error = "unknown_table"

    def execute(sql, *a, **kw):
        if "FROM main.sqlite_stat1" in sql:
            raise DatabaseQueryError(error)
        return original(sql, *a, **kw)

    monkeypatch.setattr(adapter, "execute", execute)
    try:
        assert adapter.get_row_estimate("orders") == 1
        error = "query_timeout"
        with pytest.raises(MetadataQueryError):
            adapter.get_row_estimate("orders")
    finally:
        adapter.close()


def test_batch_statistics_bind_quoted_names_and_do_not_sample_ungranted(monkeypatch):
    names = ['a:b', 'a"b', "a'b", "Korders", "korders", " f ", "  f  "]
    adapter = SQLiteAdapter(":memory:")
    for i, name in enumerate(names):
        quoted = '"' + name.replace('"', '""') + '"'
        ddl(adapter, f"CREATE TABLE {quoted}(n)")
        for _ in range(i + 1):
            ddl(adapter, f"INSERT INTO {quoted} VALUES(7)")
    ddl(adapter, "ANALYZE")
    # Chunk the bind list: SQLite builds may have a low variable limit.
    for i in range(205):
        ddl(adapter, f"CREATE TABLE t{i:03}(n)")
    ddl(adapter, "ANALYZE")
    try:
        with adapter._engine.connect() as db:
            # Force a portable low bind budget so a single oversized batch
            # would fail, rather than relying on this SQLite build's high cap.
            db.connection.dbapi_connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 200)
        rows = adapter.get_tables()
        assert {r["table_name"]:r["row_count"] for r in rows if r["table_name"] in names} == {
            name:i + 1 for i,name in enumerate(names)}
        policy = replace(adapter._config.policy, allowed_tables=frozenset({"main.korders"}),
                         read_mode="allowlist", default_schema="main")
        adapter._config = replace(adapter._config, policy=policy)
        monkeypatch.setattr(adapter, "execute_read", lambda *a, **kw: pytest.fail("Statistics cover the only granted table"))
        result = adapter.get_tables()
        assert next(r for r in result if r["table_name"] == "korders")["row_count"] == 5
        assert all(r["row_count"] is None for r in result if r["table_name"] != "korders")
    finally:
        adapter.close()


def test_partial_index_statistics_do_not_replace_table_cardinality():
    adapter = SQLiteAdapter(":memory:")
    for sql in (
        "CREATE TABLE orders(n)",
        "CREATE INDEX partial_orders ON orders(n) WHERE n=1",
        "INSERT INTO orders VALUES(1),(2),(3)",
        "ANALYZE",
    ):
        ddl(adapter, sql)
    try:
        expected = 3  # Independent fixture truth, not an arbitrary stat1 row.
        assert adapter.get_row_estimate("orders") == expected
        assert adapter.get_tables() == [{"table_name":"orders", "row_count":expected}]
    finally:
        adapter.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("tool", ["list_tables", "get_full_schema"])
async def test_enrichment_failure_remains_metadata_failure(bundle, tmp_path, monkeypatch, mode, tool):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute("CREATE TABLE orders(n)")
    bundle[1]["connections"]["demo"]["read"] = {"mode":"allowlist", "tables":["orders"]}
    server = create_server(load_config(bundle[3]()))
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    def fail(_tables):
        raise MetadataQueryError("estimating table rows")
    monkeypatch.setattr(adapter, "enrich_row_estimates", fail)
    try:
        async with Client(server, mode=mode) as client:
            body = (await client.call_tool(tool, {})).structured_content
            assert not body["success"] and body["error_code"] == "metadata_query_failed"
    finally:
        server.gateway_runtime.close()


def test_no_colon_transport_skips_tokenizer(monkeypatch):
    import sql_safety_executor.core.analysis as analysis
    monkeypatch.setattr(analysis, "_tokens", lambda *a: pytest.fail("No colon means no text bind"))
    statement = statement_text("SELECT 7 AS n", DialectContext("sqlite"))
    assert str(statement.compile(dialect=sqlite.dialect())) == "SELECT 7 AS n"


@pytest.mark.parametrize("sql,params,expected", [
    ("SELECT ':literal' AS n", None, ":literal"),
    ('SELECT :value AS n', {"value": "bound"}, "bound"),
    ('SELECT 7 AS "a:b"', None, 7),
    ("SELECT 'back\\:slash' AS n", None, "back\\:slash"),
    ("SELECT :value AS n /* :comment */", {"value": "bound"}, "bound"),
])
def test_transport_colons_keep_values_and_bindings(sql, params, expected):
    adapter = SQLiteAdapter(":memory:")
    try:
        assert adapter.execute(sql, params=params)[0][0] == expected
    finally:
        adapter.close()
