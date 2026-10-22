"""Catalog identity and whole-table cardinality, with independent fixture truth."""
from dataclasses import replace
import time

from fastmcp import Client
import pytest

from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.authorizer import build_read_guard
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.outcomes import MetadataQueryError
from sql_safety_executor.database.relations import RelationReference
from tests.support_adapters import SQLiteAdapter
from tests.test_external_read_review_v382 import review_server, bundle


def q(name):
    return '"' + name.replace('"', '""') + '"'


def ddl(adapter, sql):
    with adapter._engine.begin() as db:
        db.exec_driver_sql(sql)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("schema", ["main", "temp", "aux"])
@pytest.mark.parametrize("kind", ["table", "view"])
async def test_fts_catalog_collision_across_raw_skill_and_metadata(review_server, mode, schema, kind):
    sql = "SELECT body FROM search_docs('hello')"
    server = review_server(sql, ddl="CREATE VIRTUAL TABLE search_docs USING fts5(body);"
        "INSERT INTO search_docs VALUES('hello');", read={"mode": "allowlist", "tables": ["search_docs"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    with adapter._engine.begin() as db:
        if schema == "aux":
            db.exec_driver_sql("ATTACH ':memory:' AS aux")
        target = q(schema) + ".pragma_table_list"
        db.exec_driver_sql(f"CREATE TABLE {target}(name)" if kind == "table"
                           else f"CREATE VIEW {target} AS SELECT 7 AS name")
        before = db.exec_driver_sql(sql).fetchall()
        changes = db.connection.dbapi_connection.total_changes
    async with Client(server, mode=mode) as client:
        for tool, args in [
            ("query", {"sql": sql}),
            ("query", {"sql": "SELECT body FROM search_docs WHERE search_docs MATCH 'hello'"}),
            ("execute_query_skill", {"skill_name": "review-probe", "params": {}}),
            ("sample", {"table_name": "search_docs"}),
        ]:
            result = (await client.call_tool(tool, args)).structured_content
            assert result["success"] and result["data"] == [{"body": "hello"}]
        for tool, args in [
            ("list_tables", {}), ("describe_table", {"table_name": "search_docs"}),
            ("get_full_schema", {"detail_level": "compact"}),
            ("get_full_schema", {"detail_level": "full"}),
            ("get_table_summary", {"table_name": "search_docs", "exact_count": True}),
        ]:
            assert (await client.call_tool(tool, args)).structured_content["success"]
        for sql in ["SELECT * FROM search_docs_data", "SELECT * FROM pragma_table_list"]:
            result = (await client.call_tool("query", {"sql": sql})).structured_content
            assert not result["success"] and result["error_code"] in {"table_access_denied", "server_state_denied"}
        with adapter._engine.connect() as db:
            assert before == [("hello",)] and db.connection.dbapi_connection.total_changes == changes


@pytest.mark.parametrize("schema", ["main", "temp", "aux", 'a."ux'])
@pytest.mark.parametrize("storage", ["internal", "contentless", "external"])
def test_actual_schema_and_quoted_root_own_only_verified_shadows(schema, storage):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    name = "Search 'Docs"
    target = q(schema) + "." + q(name)
    try:
        with adapter._engine.begin() as db:
            if schema not in {"main", "temp"}:
                db.exec_driver_sql("ATTACH ':memory:' AS " + q(schema))
            db.exec_driver_sql(f"CREATE TABLE {q(schema)}.content(id INTEGER PRIMARY KEY, body)")
            db.exec_driver_sql(f"INSERT INTO {q(schema)}.content VALUES(1,'hello')")
            option = ",content='content',content_rowid='id'" if storage == "external" else ",content=''" if storage == "contentless" else ""
            db.exec_driver_sql(f"CREATE VIRTUAL TABLE {target} USING fts5(body{option})")
            db.exec_driver_sql(f"INSERT INTO {target}(rowid,body) VALUES(1,'hello')")
            for collision in {schema, "main", "temp"}:
                db.exec_driver_sql(f"CREATE TABLE {q(collision)}.pragma_table_list(name)")
            raw = db.connection.dbapi_connection
        policy = replace(adapter._config.policy, read_mode="allowlist", allowed_tables=frozenset({name}),
                         allowed_relations=frozenset({RelationReference(name, schema)}), default_schema="main")
        sql = f"SELECT body FROM {target}('hello')"
        assert adapter.execute_read(sql, policy=policy) == [(None if storage == "contentless" else "hello",)]
        guard = build_read_guard(raw, policy, adapter.analysis_context, analyze_sql(sql, adapter.analysis_context))
        assert guard.module_roots == {RelationReference(name, schema).key(case_sensitive=False)}
        assert guard.module_reads and all(r.schema == schema.lower() for r in guard.module_reads)
        with pytest.raises(DatabaseQueryError):
            adapter.execute_read(f"SELECT * FROM {q(schema)}.{q(name + '_data')}", policy=policy)
    finally:
        adapter.close()


def test_each_fixed_fts_lookup_consumes_budget_and_deadline_and_preserves_type_checks():
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        ddl(adapter, "CREATE VIRTUAL TABLE docs USING fts5(body)")
        sql = "SELECT body FROM docs('hello')"
        analysis = analyze_sql(sql, adapter.analysis_context)
        with adapter._engine.connect() as db:
            raw = db.connection.dbapi_connection
        guard = build_read_guard(raw, adapter._config.policy, adapter.analysis_context, analysis)
        assert guard.catalog_lookups >= 6
        with pytest.raises(DatabaseQueryError) as error:
            build_read_guard(raw, adapter._config.policy, adapter.analysis_context, analysis,
                             catalog_limit=guard.catalog_lookups - 1)
        assert error.value.error_code == "view_scope_unresolved"
        with pytest.raises(DatabaseQueryError) as error:
            build_read_guard(raw, adapter._config.policy, adapter.analysis_context, analysis, deadline=time.monotonic() - 1)
        assert error.value.error_code == "query_timeout"
        # Simulate a catalog type mismatch; SQLite may itself classify a
        # recreated same-prefix table as shadow via the module's xShadowName.
        class MismatchCursor:
            def fetchmany(self, size):
                return [("main", "docs_data", "table", 2, 0, 0)]
            def close(self):
                pass
        class MismatchConnection:
            def execute(self, sql, *args):
                return MismatchCursor() if ".table_list(" in sql else raw.execute(sql, *args)
        with pytest.raises(DatabaseQueryError) as error:
            build_read_guard(MismatchConnection(), adapter._config.policy, adapter.analysis_context, analysis)
        assert error.value.error_code == "virtual_relation_unsupported"
    finally:
        adapter.close()


STAT_CASES = ["partial", "full", "full_partial", "partial_full", "without_rowid",
              "index_only", "no_stats", "large", "empty", "stale"]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("case", STAT_CASES)
async def test_table_estimates_use_table_or_full_index_sources(review_server, mode, case):
    server = review_server("SELECT COUNT(*) AS n FROM main.orders")
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    actual = 0 if case == "empty" else 15000 if case == "large" else 1500
    with adapter._engine.begin() as db:
        db.exec_driver_sql("DROP TABLE orders")
        db.exec_driver_sql("CREATE TABLE orders(n INTEGER PRIMARY KEY)" + (" WITHOUT ROWID" if case == "without_rowid" else ""))
        if actual:
            db.exec_driver_sql("INSERT INTO orders VALUES(?)", [(n,) for n in range(100 if case == "stale" else actual)])
        partial = "CREATE INDEX partial_orders ON orders(n) WHERE n<1"
        full = "CREATE INDEX full_orders ON orders(n)"
        if case in {"full", "full_partial"}:
            db.exec_driver_sql(full)
        if case in {"partial", "full_partial", "partial_full", "without_rowid", "index_only"}:
            db.exec_driver_sql(partial)
        if case == "partial_full":
            db.exec_driver_sql(full)
        if case not in {"no_stats", "large"}:
            db.exec_driver_sql("ANALYZE partial_orders" if case == "index_only" else "ANALYZE orders")
        if case == "stale":
            db.exec_driver_sql("INSERT INTO orders VALUES(?)", [(n,) for n in range(100, actual)])
        changes = db.connection.dbapi_connection.total_changes
    expected = 10000 if case == "large" else 100 if case == "stale" else actual
    async with Client(server, mode=mode) as client:
        assert (await client.call_tool("query", {"sql": "SELECT COUNT(*) AS n FROM main.orders"})).structured_content["data"] == [{"n": actual}]
        listed = (await client.call_tool("list_tables", {})).structured_content
        assert listed["tables"] == [{"table_name": "orders", "row_count": expected}]
        for tool in ["describe_table", "get_table_summary"]:
            result = (await client.call_tool(tool, {"table_name": "orders"})).structured_content
            assert result["success"] and result["row_count"] == expected and result["is_large"] is (expected >= 1000)
        for level in ["compact", "full"]:
            result = (await client.call_tool("get_full_schema", {"detail_level": level})).structured_content
            if level == "full":
                assert result["schema"]["orders"]["row_count"] == expected
            else:
                assert result["schema_groups"][0]["tables"][0]["row_count"] == expected
        exact = (await client.call_tool("get_table_summary", {"table_name": "orders", "exact_count": True})).structured_content
        assert exact["row_count"] == actual
        with adapter._engine.connect() as db:
            assert db.connection.dbapi_connection.total_changes == changes


@pytest.mark.parametrize("case", ["without_rowid", "full_only", "invalid_full", "orphan", "index_overflow"])
def test_verified_statistic_sources_and_bounded_fallback(monkeypatch, case):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        ddl(adapter, "CREATE TABLE orders(n PRIMARY KEY)" + (" WITHOUT ROWID" if case == "without_rowid" else ""))
        with adapter._engine.begin() as db:
            db.exec_driver_sql("INSERT INTO orders VALUES(?)", [(n,) for n in range(15000)])
            if case != "without_rowid":
                db.exec_driver_sql("CREATE INDEX full_orders ON orders(n)")
            db.exec_driver_sql("CREATE INDEX partial_orders ON orders(n) WHERE n<1")
            db.exec_driver_sql("ANALYZE orders")
            if case in {"invalid_full", "orphan", "index_overflow"}:
                db.exec_driver_sql("DELETE FROM sqlite_stat1 WHERE idx IS NULL")
                db.exec_driver_sql("UPDATE sqlite_stat1 SET stat='invalid' WHERE idx != 'partial_orders'")
            if case == "orphan":
                db.exec_driver_sql("INSERT INTO sqlite_stat1 VALUES('orders','gone','1 1')")
            if case == "index_overflow":
                for i in range(128):
                    db.exec_driver_sql(f"CREATE INDEX extra{i} ON orders(n) WHERE n<1")
        if case in {"without_rowid", "full_only"}:
            monkeypatch.setattr(adapter, "execute_read", lambda *a, **kw: pytest.fail("Verified full statistics must avoid data scans"))
        assert adapter.get_row_estimate("orders") == (15000 if case in {"without_rowid", "full_only"} else 10000)
        assert adapter._active_guard is None
    finally:
        adapter.close()


def test_statistic_verification_errors_are_typed_and_not_cached(monkeypatch):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        for sql in ["CREATE TABLE orders(n)", "CREATE INDEX full_orders ON orders(n)",
                    "INSERT INTO orders VALUES(7),(99)", "ANALYZE orders"]:
            ddl(adapter, sql)
        original = adapter.execute
        def failed(sql, *a, **kw):
            if "PRAGMA main.index_list" in sql:
                raise DatabaseQueryError("query_timeout")
            return original(sql, *a, **kw)
        monkeypatch.setattr(adapter, "execute", failed)
        with pytest.raises(MetadataQueryError):
            adapter.get_row_estimate("orders")
        monkeypatch.setattr(adapter, "execute", original)
        assert adapter.get_row_estimate("orders") == 2
        for sql in ["DROP INDEX full_orders", "CREATE INDEX full_orders ON orders(n) WHERE n<8", "ANALYZE full_orders"]:
            ddl(adapter, sql)
        assert adapter.get_row_estimate("orders") == 2
    finally:
        adapter.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("declaration", ["id INTEGER PRIMARY KEY", "id INTEGER PRIMARY KEY DESC", "id TEXT PRIMARY KEY"])
@pytest.mark.parametrize("rowid", [None, "rowid", "_rowid_", "oid", "id"])
async def test_external_content_rowid_identity_cold_warm_and_direct_grants(review_server, mode, declaration, rowid):
    option = "" if rowid is None else ",content_rowid='" + rowid + "'"
    sql = "SELECT body FROM search_docs('hello')"
    server = review_server(sql, ddl=f"CREATE TABLE docs({declaration},body TEXT);"
        "INSERT INTO docs(rowid,id,body) VALUES(1,1,'hello');"
        f"CREATE VIRTUAL TABLE search_docs USING fts5(body,content='docs'{option});"
        "INSERT INTO search_docs(rowid,body) VALUES(1,'hello');",
        read={"mode": "allowlist", "tables": ["search_docs"]})
    async with Client(server, mode=mode) as client:
        # No trusted warm query before the first guarded evaluation.
        for _ in range(2):
            result = (await client.call_tool("query", {"sql": sql})).structured_content
            assert result["success"] and result["data"] == [{"body": "hello"}]
        result = (await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})).structured_content
        assert result["data"] == [{"body": "hello"}]
        for sql in ["SELECT body FROM docs", "SELECT * FROM search_docs_data"]:
            assert (await client.call_tool("query", {"sql": sql})).structured_content["error_code"] == "table_access_denied"


@pytest.mark.parametrize("rowid", ["rowid", "_rowid_", "oid"])
def test_declared_rowid_spelling_wins_over_integer_pk_alias(rowid):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql(f"CREATE TABLE docs(id INTEGER PRIMARY KEY,{q(rowid)} INTEGER,body)")
            db.exec_driver_sql(f"INSERT INTO docs(id,{q(rowid)},body) VALUES(99,1,'hello')")
            db.exec_driver_sql(f"CREATE VIRTUAL TABLE search_docs USING fts5(body,content='docs',content_rowid='{rowid}')")
            db.exec_driver_sql("INSERT INTO search_docs(rowid,body) VALUES(1,'hello')")
        policy = replace(adapter._config.policy, read_mode="allowlist", allowed_tables=frozenset({"search_docs"}))
        assert adapter.execute_read("SELECT body FROM search_docs('hello')", policy=policy) == [("hello",)]
    finally:
        adapter.close()


@pytest.mark.parametrize("schema", ["main", "temp", "aux"])
@pytest.mark.parametrize("collision", ["pragma_index_list", "pragma_table_list"])
def test_statistic_verification_catalogs_cannot_be_shadowed(monkeypatch, schema, collision):
    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE orders(n PRIMARY KEY) WITHOUT ROWID")
            db.exec_driver_sql("INSERT INTO orders VALUES(?)", [(n,) for n in range(15000)])
            db.exec_driver_sql("CREATE INDEX partial_orders ON orders(n) WHERE n<1")
            db.exec_driver_sql("ANALYZE orders")
            if schema == "aux":
                db.exec_driver_sql("ATTACH ':memory:' AS aux")
            db.exec_driver_sql(f"CREATE TABLE {q(schema)}.{q(collision)}(name)")
        monkeypatch.setattr(adapter, "execute_read", lambda *a, **kw: pytest.fail("Verified primary-tree statistic should be used"))
        assert adapter.get_row_estimate("orders") == 15000
    finally:
        adapter.close()
