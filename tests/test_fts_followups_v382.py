"""FTS cached external-content checks and explicitly granted schema bindings."""
import pytest
from fastmcp import Client

from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.relations import RelationReference
from tests.test_external_read_review_v382 import review_server as review_server
from tests.test_v38_config import bundle as bundle
from tests.test_sqlite_virtual_reads_v382 import virtual_adapter as virtual_adapter


RESTRICTED = [
    ("SLEEP", "expensive_function_denied"),
    ("BENCHMARK", "expensive_function_denied"),
    ("GET_LOCK", "lock_function_denied"),
    ("USER", "server_state_denied"),
    ("LOAD_FILE", "file_operation_denied"),
    ("pragma_database_list", "server_state_denied"),
]


def content_fixture(adapter, function):
    called = []
    with adapter._engine.begin() as db:
        raw = db.connection.dbapi_connection
        raw.create_function(function, 1, lambda n: called.append(n) or "Hello world")
        raw.executescript(
            f'CREATE VIEW content_view AS SELECT id,"{function}"(0) AS title,body FROM docs;'
            "CREATE VIRTUAL TABLE view_fts USING fts5(title,body,content='content_view',content_rowid='id');"
            "INSERT INTO view_fts(rowid,title,body) VALUES(1,'Hello world','alpha');"
        )
    return called


def warm_content(adapter, warm):
    if warm == "columns":
        adapter.get_columns("view_fts")
    elif warm == "trusted_projection":
        assert adapter.execute("SELECT title FROM view_fts WHERE view_fts MATCH 'hello'") == [("Hello world",)]


@pytest.mark.parametrize("function,code", RESTRICTED)
@pytest.mark.parametrize("warm", ["none", "columns", "trusted_projection"])
def test_external_content_reserved_functions_before_cached_module_evaluation(virtual_adapter, function, code, warm):
    adapter = virtual_adapter
    called = content_fixture(adapter, function)
    warm_content(adapter, warm)
    before = len(called)
    policy = ConnectionPolicy(allowed_tables=frozenset({"view_fts"}), default_schema="main")
    for sql in (
        "SELECT title FROM view_fts WHERE view_fts MATCH 'hello'",
        "SELECT title FROM view_fts('hello')",
        "SELECT COUNT(*) FROM view_fts",
    ):
        with pytest.raises(DatabaseQueryError) as error:
            adapter.execute_read(sql, policy=policy)
        assert error.value.error_code == code
        assert len(called) == before
        assert adapter._active_guard is None and adapter._read_request is None
    assert adapter.execute_read("SELECT 7", policy=policy) == [(7,)]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("warm", ["none", "columns", "trusted_projection"])
async def test_external_content_guard_is_shared_across_public_entries(review_server, mode, warm):
    server = review_server("SELECT title FROM view_fts('hello')",
        ddl="CREATE TABLE docs(id INTEGER PRIMARY KEY,title,body); INSERT INTO docs VALUES(1,'Hello world','alpha');",
        read={"mode": "allowlist", "tables": ["view_fts"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    called = content_fixture(adapter, "SLEEP")
    warm_content(adapter, warm)
    before = len(called)
    async with Client(server, mode=mode) as client:
        for tool, args in [
            ("query", {"sql": "SELECT title FROM view_fts('hello')"}),
            ("execute_query_skill", {"skill_name": "review-probe", "params": {}}),
            ("sample", {"table_name": "view_fts"}),
            ("get_table_summary", {"table_name": "view_fts", "exact_count": True}),
            ("describe_table", {"table_name": "view_fts"}),
        ]:
            result = await client.call_tool(tool, args, raise_on_error=False)
            assert not result.is_error
            payload = result.structured_content
            # Metadata can retain unavailable estimates instead of failing the
            # complete descriptor. In every case the function stays unevaluated.
            if tool == "describe_table":
                assert payload["row_count"] is None
            else:
                assert payload["success"] is False
            assert len(called) == before


@pytest.mark.parametrize("warm", [False, True])
def test_safe_nested_derived_content_keeps_indirect_grants(virtual_adapter, warm):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE VIEW content_inner AS SELECT id,lower(title) AS title,body FROM docs")
        db.exec_driver_sql("CREATE VIEW content_view AS SELECT * FROM (SELECT * FROM content_inner)")
        db.exec_driver_sql("CREATE VIRTUAL TABLE view_fts USING fts5(title,body,content='content_view',content_rowid='id')")
        db.exec_driver_sql("INSERT INTO view_fts(rowid,title,body) VALUES(1,'hello world','alpha')")
    if warm:
        adapter.execute("SELECT title FROM view_fts WHERE view_fts MATCH 'hello'")
    policy = ConnectionPolicy(allowed_tables=frozenset({"view_fts"}), default_schema="main")
    assert adapter.execute_read("SELECT title FROM view_fts('hello')", policy=policy) == [("hello world",)]
    for source in ("docs", "content_inner", "content_view", "view_fts_idx"):
        with pytest.raises(DatabaseQueryError) as error:
            adapter.execute_read("SELECT * FROM " + source, policy=policy)
        assert error.value.error_code == "table_access_denied"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("schema", ["aux", "temp"])
@pytest.mark.parametrize("warm", [False, True])
async def test_explicit_named_fts_grants_work_in_actual_schema(review_server, mode, schema, warm):
    server = review_server("SELECT n FROM orders", read={"mode": "allowlist",
        "relations": [{"schema": schema, "name": "search.root"}], "tables": ["orders"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    adapter.connect()
    with adapter._engine.begin() as db:
        if schema == "aux":
            db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql(f'CREATE VIRTUAL TABLE {schema}."search.root" USING fts5(title)')
        db.exec_driver_sql(f'INSERT INTO {schema}."search.root" VALUES(\'Hello world\')')
        if warm:
            db.exec_driver_sql(f'SELECT title FROM {schema}."search.root"(\'hello\')').fetchall()
    async with Client(server, mode=mode) as client:
        for sql, data in [
            (f'SELECT title FROM {schema}."search.root" WHERE "search.root" MATCH \'hello\'', [{"title": "Hello world"}]),
            (f'SELECT title FROM {schema}."search.root"(\'hello\')', [{"title": "Hello world"}]),
            (f'SELECT \'Hello world\' IN {schema}."search.root"(\'hello\') AS n', [{"n": 1}]),
        ]:
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["data"] == data
        for sql, code in [
            (f'SELECT * FROM {schema}."search.root_idx"', "table_access_denied"),
            ('SELECT title FROM main."search.root"(\'hello\')', "table_access_denied"),
            (f"SELECT * FROM {schema}.json_each('[7]')", "relation_scope_unresolved"),
            (f'SELECT orders.n FROM orders,{schema}."search.root"(\'hello\')', None),
        ]:
            result = await client.call_tool("query", {"sql": sql}, raise_on_error=False)
            assert not result.is_error
            if code:
                assert result.structured_content["error_code"] == code
            else:
                assert result.structured_content["data"] == [{"n": 7}]


def test_nondefault_named_fts_does_not_expand_all_or_other_grants(virtual_adapter):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql("CREATE VIRTUAL TABLE aux.docs_fts USING fts5(title)")
        db.exec_driver_sql("INSERT INTO aux.docs_fts VALUES('Hello world')")
    for policy in (
        adapter._config.policy,
        ConnectionPolicy(allowed_tables=frozenset({"*"}), read_mode="all", default_schema="main"),
    ):
        with pytest.raises(DatabaseQueryError) as error:
            adapter.execute_read("SELECT title FROM aux.docs_fts('hello')", policy=policy)
        assert error.value.error_code == "table_access_denied"
    aux_policy = ConnectionPolicy(allowed_tables=frozenset({"aux.docs_fts"}),
        allowed_relations=frozenset({RelationReference("docs_fts", "aux")}), default_schema="main")
    assert adapter.execute_read("SELECT title FROM aux.docs_fts('hello')", policy=aux_policy) == [("Hello world",)]


@pytest.mark.parametrize("warm", [False, True])
def test_external_content_pragma_relation_cannot_borrow_module_abilities(virtual_adapter, warm):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        db.exec_driver_sql("CREATE VIEW content_view AS SELECT id,(SELECT name FROM pragma_database_list LIMIT 1) AS title,body FROM docs")
        db.exec_driver_sql("CREATE VIRTUAL TABLE view_fts USING fts5(title,body,content='content_view',content_rowid='id')")
        db.exec_driver_sql("INSERT INTO view_fts(rowid,title,body) VALUES(1,'hello','alpha')")
    if warm:
        assert adapter.execute("SELECT title FROM view_fts WHERE view_fts MATCH 'hello'") == [("main",)]
    policy = ConnectionPolicy(allowed_tables=frozenset({"view_fts"}), default_schema="main")
    with pytest.raises(DatabaseQueryError) as error:
        adapter.execute_read("SELECT title FROM view_fts('hello')", policy=policy)
    assert error.value.error_code == "server_state_denied"


def test_view_function_check_is_definition_wide_and_uses_ascii_names(virtual_adapter):
    adapter = virtual_adapter
    calls = content_fixture(adapter, "SLEEP")
    policy = ConnectionPolicy(allowed_tables=frozenset({"content_view"}), default_schema="main")
    # Conservative definition-wide behavior is deliberate even if SQLite could
    # prune the restricted output column or satisfy a count without evaluating it.
    for sql in ("SELECT body FROM content_view", "SELECT COUNT(*) FROM content_view"):
        with pytest.raises(DatabaseQueryError) as error:
            adapter.execute_read(sql, policy=policy)
        assert error.value.error_code == "expensive_function_denied"
    assert not calls
    with adapter._engine.begin() as db:
        raw = db.connection.dbapi_connection
        raw.create_function("ſleep", 1, lambda _: "Hello world")
        db.exec_driver_sql('CREATE VIEW ordinary AS SELECT "ſleep"(0) AS title,body AS "sleep",body AS "pragma_database_list" FROM docs')
    policy = ConnectionPolicy(allowed_tables=frozenset({"ordinary"}), default_schema="main")
    assert adapter.execute_read('SELECT title,"sleep","pragma_database_list" FROM ordinary LIMIT 1', policy=policy) == [("Hello world", "alpha", "alpha")]


@pytest.mark.parametrize("warm", [False, True])
def test_fts_content_definition_changes_are_checked_on_each_read(virtual_adapter, warm):
    adapter = virtual_adapter
    calls = content_fixture(adapter, "SLEEP")
    with adapter._engine.begin() as db:
        db.exec_driver_sql("DROP VIEW content_view")
        db.exec_driver_sql("CREATE VIEW content_view AS SELECT id,title,body FROM docs")
    policy = ConnectionPolicy(allowed_tables=frozenset({"view_fts"}), default_schema="main")
    assert adapter.execute_read("SELECT title FROM view_fts('hello')", policy=policy) == [("Hello world",)]
    with adapter._engine.begin() as db:
        db.exec_driver_sql("DROP VIEW content_view")
        db.exec_driver_sql("CREATE VIEW content_view AS SELECT id,SLEEP(0) AS title,body FROM docs")
    if warm:
        warm_content(adapter, "trusted_projection")
    before = len(calls)
    with pytest.raises(DatabaseQueryError) as error:
        adapter.execute_read("SELECT title FROM view_fts('hello')", policy=policy)
    assert error.value.error_code == "expensive_function_denied" and len(calls) == before
