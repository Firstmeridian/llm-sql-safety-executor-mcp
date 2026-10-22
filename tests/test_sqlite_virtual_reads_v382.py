"""FTS root permissions, cold/warm state and cross-entry evaluation guards."""
from dataclasses import replace
import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.sqlite import SQLiteAdapter
from tests.test_external_read_review_v382 import review_server as review_server
from tests.test_v38_config import bundle as bundle


def fts_ddl(storage):
    option = ", content='docs', content_rowid='id'" if storage == "external" else ", content=''" if storage == "contentless" else ""
    return (
        "CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT, body TEXT);"
        "INSERT INTO docs VALUES(1,'Hello world','alpha'),(2,'Other title','beta');"
        f"CREATE VIRTUAL TABLE docs_fts USING fts5(title, body{option});"
        "INSERT INTO docs_fts(rowid,title,body) SELECT id,title,body FROM docs;"
    )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("storage", ["internal", "external", "contentless"])
@pytest.mark.parametrize("prewarm", [False, True])
async def test_fts_root_only_is_stable_before_after_metadata_and_reconnect(review_server, mode, storage, prewarm):
    sql = "SELECT COUNT(*) AS n FROM docs_fts WHERE docs_fts MATCH 'hello'"
    server = review_server(sql, ddl=fts_ddl(storage), read={"mode": "allowlist", "tables": ["docs_fts"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    async with Client(server, mode=mode) as client:
        if prewarm:
            result = await client.call_tool("describe_table", {"table_name": "docs_fts"})
            assert result.structured_content["row_count"] == 2
        for _ in range(2):
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["data"] == [{"n": 1}]
        for expression in ("docs_fts WHERE docs_fts MATCH 'hello'", "docs_fts('hello')"):
            result = await client.call_tool("query", {"sql": "SELECT title FROM " + expression})
            assert result.structured_content["data"] == [{"title": None if storage == "contentless" else "Hello world"}]
        result = await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})
        assert result.structured_content["data"] == [{"n": 1}]
        for tool, arguments in [
            ("sample", {"table_name": "docs_fts"}),
            ("get_table_summary", {"table_name": "docs_fts", "exact_count": True}),
            ("get_table_summary", {"table_name": "docs_fts"}),
        ]:
            result = await client.call_tool(tool, arguments)
            assert result.structured_content["row_count"] == 2
        for source in ("docs", "docs_fts_idx", "docs_fts_data", "pragma_data_version"):
            result = await client.call_tool("query", {"sql": f"SELECT * FROM {source} LIMIT 1"})
            assert result.structured_content["error_code"] == ("server_state_denied" if source.startswith("pragma_") else "table_access_denied")
        mixed = await client.call_tool("query", {"sql": "SELECT docs.title FROM docs JOIN docs_fts ON docs.id=docs_fts.rowid"})
        assert mixed.structured_content["error_code"] == "table_access_denied"
        adapter.close()
        result = await client.call_tool("query", {"sql": sql})
        assert result.structured_content["data"] == [{"n": 1}]


@pytest.fixture
def virtual_adapter(tmp_path):
    path = tmp_path / "virtual.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(fts_ddl("external"))
    adapter = SQLiteAdapter(config=DatabaseConfig("virtual", "sqlite", 5, 5,
        ConnectionPolicy(allowed_tables=frozenset({"docs_fts"}), default_schema="main"),
        sqlite_database_path=str(path)))
    adapter.connect()
    yield adapter
    adapter.close()


def test_fts_guard_checks_direct_roots_even_without_frontend_policy(virtual_adapter):
    adapter = virtual_adapter
    policy = adapter._config.policy
    assert adapter.execute_read("SELECT title FROM docs_fts('hello')", policy=policy) == [("Hello world",)]
    for sql, code in [
        ("SELECT title FROM docs", "table_access_denied"),
        ("SELECT docs.title FROM docs, docs_fts('hello')", "table_access_denied"),
        ("SELECT pgno FROM docs_fts_idx, docs_fts('hello')", "table_access_denied"),
        ("SELECT * FROM pragma_data_version, docs_fts('hello')", "server_state_denied"),
        ("PRAGMA main.data_version", "server_state_denied"),
    ]:
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read(sql, policy=policy)
        assert denied.value.error_code == code
        assert adapter._active_guard is None and adapter._read_request is None


def test_fts_external_view_functions_stay_denied_before_execution(virtual_adapter):
    adapter = virtual_adapter
    called = []
    with adapter._engine.begin() as db:
        raw = db.connection.dbapi_connection
        raw.create_function("SLEEP", 1, lambda x: called.append(x) or "Hello world")
        db.exec_driver_sql("CREATE VIEW content_view AS SELECT id,SLEEP(0) AS title,body FROM docs")
        db.exec_driver_sql("CREATE VIRTUAL TABLE view_fts USING fts5(title,body,content='content_view',content_rowid='id')")
        db.exec_driver_sql("INSERT INTO view_fts(rowid,title,body) VALUES(1,'Hello world','alpha')")
    policy = ConnectionPolicy(allowed_tables=frozenset({"view_fts"}), default_schema="main")
    for sql in ("SELECT title FROM view_fts WHERE view_fts MATCH 'hello'", "SELECT * FROM view_fts"):
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read(sql, policy=policy)
        assert denied.value.error_code == "expensive_function_denied"
    assert called == []


def test_fts_schema_replacement_does_not_reuse_permissions(virtual_adapter):
    adapter = virtual_adapter
    policy = adapter._config.policy
    assert adapter.execute_read("SELECT title FROM docs_fts('hello')", policy=policy) == [("Hello world",)]
    with adapter._engine.begin() as db:
        db.exec_driver_sql("DROP TABLE docs_fts")
        db.exec_driver_sql("CREATE VIRTUAL TABLE docs_fts USING fts5(title,body)")
        db.exec_driver_sql("INSERT INTO docs_fts VALUES('Hello new','new')")
    assert adapter.execute_read("SELECT title FROM docs_fts('hello')", policy=policy) == [("Hello new",)]
    denied_policy = replace(policy, allowed_tables=frozenset({"docs"}))
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT title FROM docs_fts('hello')", policy=denied_policy)
    assert denied.value.error_code == "table_access_denied"


@pytest.mark.parametrize("name", ["json_each", "json_tree"])
def test_business_table_cannot_impersonate_builtin_json_module(virtual_adapter, name):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql(f"CREATE TABLE {name}(value)")
        db.exec_driver_sql(f"INSERT INTO {name} VALUES(99)")
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read(f"SELECT value FROM {name}('[1]')", policy=adapter._config.policy)
    assert denied.value.error_code == "view_scope_unresolved"


@pytest.mark.parametrize("name", ["FTSRoot", " fts ", "fts.dot", "索引", "K"])
def test_fts_business_names_keep_sqlite_identity_and_shadow_ownership(virtual_adapter, name):
    adapter = virtual_adapter
    quoted = '"' + name.replace('"', '""') + '"'
    with adapter._engine.begin() as db:
        db.exec_driver_sql(f"CREATE VIRTUAL TABLE {quoted} USING fts5(title)")
        db.exec_driver_sql(f"INSERT INTO {quoted} VALUES('Hello world')")
    from sql_safety_executor.database.relations import RelationReference
    policy = ConnectionPolicy(allowed_tables=frozenset({name}),
        allowed_relations=frozenset({RelationReference(name, "main")}), default_schema="main")
    assert adapter.execute_read(f"SELECT title FROM {quoted}('hello')", policy=policy) == [("Hello world",)]
    assert adapter.execute_read(f"SELECT 'Hello world' IN main.{quoted}('hello')", policy=policy) == [(1,)]


def test_unknown_named_virtual_module_does_not_gain_fts_internal_abilities(virtual_adapter):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE VIRTUAL TABLE spatial USING rtree(id,x1,x2)")
        db.exec_driver_sql("INSERT INTO spatial VALUES(1,0,1)")
    policy = ConnectionPolicy(allowed_tables=frozenset({"spatial"}), default_schema="main")
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT * FROM spatial(1)", policy=policy)
    assert denied.value.error_code == "virtual_relation_unsupported"
    all_policy = ConnectionPolicy(allowed_tables=frozenset({"*"}), read_mode="all", default_schema="main")
    assert adapter.execute_read("SELECT id FROM spatial", policy=all_policy) == [(1,)]


@pytest.mark.parametrize("schema", ["temp", "aux"])
def test_json_module_inside_nondefault_view_uses_actual_main_binding(virtual_adapter, schema):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        if schema == "aux":
            db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql(f"CREATE VIEW {schema}.json_view AS SELECT value AS n FROM json_each('[7]')")
    policy = ConnectionPolicy(allowed_tables=frozenset({f"{schema}.json_view"}), default_schema="main")
    assert adapter.execute_read(f"SELECT n FROM {schema}.json_view", policy=policy) == [(7,)]


@pytest.mark.parametrize("prefix", ["EXPLAIN", "EXPLAIN QUERY PLAN"])
@pytest.mark.parametrize("expression", [
    "SELECT COUNT(*) FROM json_each('[7,8]')",
    "SELECT (WITH chosen AS MATERIALIZED (SELECT value FROM json_each('[7,8]')) SELECT COUNT(*) FROM chosen)",
    "SELECT COUNT(*) FROM docs_fts('hello')",
])
def test_nonexecuting_trigger_plans_keep_virtual_dependency_context(virtual_adapter, prefix, expression):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE orders(n)")
        db.exec_driver_sql("CREATE TABLE audit_log(n)")
        db.exec_driver_sql(f"CREATE TRIGGER probe AFTER INSERT ON orders BEGIN INSERT INTO audit_log {expression}; END")
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders", "audit_log", "docs_fts"}), default_schema="main")
    sql = prefix + " INSERT INTO orders VALUES(99)"
    truth = adapter.execute(sql)
    assert adapter.execute_read(sql, policy=policy) == truth
    assert adapter.execute("SELECT COUNT(*) FROM orders") == [(0,)]
    assert adapter.execute("SELECT COUNT(*) FROM audit_log") == [(0,)]


@pytest.mark.parametrize("warm", [False, True])
def test_temp_fts_cannot_masquerade_as_unqualified_json_builtin(virtual_adapter, warm):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE VIRTUAL TABLE temp.json_each USING fts5(value)")
        db.exec_driver_sql("INSERT INTO temp.json_each VALUES('hidden text')")
        if warm:
            db.exec_driver_sql("SELECT * FROM temp.json_each('hidden')").fetchall()
    with pytest.raises(DatabaseQueryError) as denied:
        adapter.execute_read("SELECT COUNT(*) FROM json_each('hidden')", policy=adapter._config.policy)
    assert denied.value.error_code == "view_scope_unresolved"
    assert adapter.execute_read("SELECT value FROM main.json_each('[7]')", policy=adapter._config.policy) == [(7,)]
