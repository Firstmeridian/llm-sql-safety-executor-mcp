"""SQLite relation-call names, actual modules and visible generated columns."""
from dataclasses import replace

import pytest
from fastmcp import Client

from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from tests.test_external_read_review_v382 import review_server, bundle
from tests.test_sqlite_virtual_reads_v382 import virtual_adapter


NAMES = ["substr", "ifnull", "char", "random", "iif", "replace", "strftime",
         "sleep", "get_lock", "load_file", "current_user", "json_each", "json_tree",
         "ſubstr", "ıif", " fts ", "a.b", 'a"b']


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def queries(name):
    spellings = [quoted(name), "main." + quoted(name),
                 '`' + name.replace('`', '``') + '`']
    if name.isidentifier():
        spellings.append(name)
    for target in spellings:
        yield f"SELECT body FROM {target}('hello')", [{"body": "hello"}]
        yield f"SELECT f.body FROM orders JOIN {target}('hello') AS f ON orders.n=7", [{"body": "hello"}]
        yield f"SELECT 'hello' IN {target}('hello') AS n", [{"n": 1}]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", NAMES)
async def test_relation_call_roles_names_and_skill_dependencies(review_server, mode, name):
    source = quoted(name)
    server = review_server(f"SELECT body FROM {source}('hello')",
        ddl=f"CREATE VIRTUAL TABLE {source} USING fts5(body);INSERT INTO {source} VALUES('hello');",
        read={"mode": "allowlist", "relations": [{"schema": "main", "name": name}], "tables": ["orders"]})
    async with Client(server, mode=mode) as client:
        for sql, data in queries(name):
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content.get("data") == data, (sql, result)
        for tool, arguments in [("list_skills", {"detail_level": "full"}),
                                ("get_skill_detail", {"skill_name": "review-probe"})]:
            result = await client.call_tool(tool, arguments)
            payload = result.structured_content
            state = payload["skills"][0] if tool == "list_skills" else payload["skill"]
            assert state["executable"] and state["schema_ready"]
            assert state["missing_tables"] == []
            assert len(state["inferred_tables"]) == 1
        result = await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})
        assert result.structured_content["data"] == [{"body": "hello"}]


@pytest.mark.parametrize("name", ["substr", "iif", "sleep", "ſubstr", " fts ", "a.b"])
def test_relation_analysis_preserves_occurrences_and_argument_checks(name):
    context = DialectContext("sqlite", default_schema="main")
    sql = f"SELECT * FROM main.{quoted(name)}(SLEEP(0))"
    result = analyze_sql(sql, context)
    assert result.complete
    assert result.relations == (RelationReference(name, "main"),)
    assert result.functions == frozenset({"sleep"})
    assert [(n.name, n.raw, n.quote) for n in result.names if n.role == "relation"] == [(name, quoted(name), '"')]
    assert result.source_sql == sql


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_relation_head_does_not_hide_restricted_arguments_or_grants(review_server, mode):
    server = review_server("SELECT body FROM substr('hello')",
        ddl="CREATE VIRTUAL TABLE substr USING fts5(body);INSERT INTO substr VALUES('hello');",
        read={"mode": "allowlist", "tables": ["substr"]})
    async with Client(server, mode=mode) as client:
        for sql, code in [
            ("SELECT * FROM substr(SLEEP(0))", "expensive_function_denied"),
            ("SELECT * FROM substr(GET_LOCK('x',0))", "lock_function_denied"),
            ("SELECT * FROM substr(LOAD_FILE('x'))", "file_operation_denied"),
            ("SELECT * FROM substr((SELECT n FROM orders))", "table_access_denied"),
            ("SELECT * FROM substr_idx", "table_access_denied"),
            ("SELECT * FROM temp.substr('hello')", "table_access_denied"),
        ]:
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["error_code"] == code


@pytest.mark.parametrize("schema", ["main", "temp", "aux"])
@pytest.mark.parametrize("name", ["json_each", "json_tree"])
def test_json_spelling_binds_actual_authorized_fts_schema(virtual_adapter, schema, name):
    adapter = virtual_adapter
    with adapter._engine.begin() as db:
        if schema == "aux":
            db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql(f"CREATE VIRTUAL TABLE {schema}.{name} USING fts5(value)")
        db.exec_driver_sql(f"INSERT INTO {schema}.{name} VALUES('hello')")
        db.exec_driver_sql(f"CREATE VIEW {schema}.approved_search AS SELECT value FROM {name}('hello')")
    policy = replace(adapter._config.policy, allowed_tables=frozenset({f"{schema}.{name}"}),
                     allowed_relations=frozenset({RelationReference(name, schema)}))
    for sql in [f"SELECT value FROM {schema}.{name}('hello')",
                f"SELECT 'hello' IN {schema}.{name}('hello')"]:
        assert adapter.execute_read(sql, policy=policy) == ([("hello",)] if "SELECT value" in sql else [(1,)])
    view_policy = replace(policy, allowed_relations=frozenset({RelationReference("approved_search", schema)}))
    assert adapter.execute_read(f"SELECT value FROM {schema}.approved_search", policy=view_policy) == [("hello",)]
    with pytest.raises(DatabaseQueryError):
        adapter.execute_read(f"SELECT * FROM {schema}.{name}_idx", policy=policy)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_conditional_json_dependencies_use_fresh_readiness_snapshot(review_server, mode):
    server = review_server("SELECT value FROM json_each('[7]')", read={"mode": "allowlist", "tables": ["orders"]})
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    async with Client(server, mode=mode) as client:
        first = await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})
        assert first.structured_content["skill"]["inferred_tables"] == []
        with adapter._engine.begin() as db:
            db.exec_driver_sql("CREATE VIRTUAL TABLE json_each USING fts5(value)")
            db.exec_driver_sql("INSERT INTO json_each VALUES('hello')")
        second = await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})
        state = second.structured_content["skill"]
        assert state["inferred_tables"] == ["main.json_each"]
        assert not state["executable"] and not state["policy_allowed"]
        with adapter._engine.begin() as db:
            db.exec_driver_sql("DROP TABLE json_each")
        last = await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})
        assert last.structured_content["skill"]["executable"]
        assert last.structured_content["skill"]["inferred_tables"] == []


GENERATED_DDL = """
CREATE TABLE generated(id INTEGER PRIMARY KEY,base INTEGER NOT NULL,
  stored INTEGER AS (base*2) STORED, virtual INTEGER AS (base+3) VIRTUAL);
INSERT INTO generated(id,base) VALUES(1,7);
CREATE INDEX idx_generated ON generated(stored,virtual);
CREATE VIRTUAL TABLE searchable USING fts5(body);
INSERT INTO searchable VALUES('hello');
"""


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_generated_columns_all_metadata_projections_and_hidden_contract(review_server, mode):
    server = review_server("SELECT stored,virtual FROM generated", ddl=GENERATED_DDL,
        read={"mode": "allowlist", "tables": ["generated", "searchable"]})
    async with Client(server, mode=mode) as client:
        for tool in ["describe_table", "get_table_summary"]:
            result = await client.call_tool(tool, {"table_name": "generated"})
            payload = result.structured_content
            assert payload["column_count"] == 4
            assert [c["column_name"] for c in payload["columns"]] == ["id", "base", "stored", "virtual"]
            assert [c.get("generation_type") for c in payload["columns"]] == [None, None, "stored", "virtual"]
        for detail in ["compact", "full"]:
            result = await client.call_tool("get_full_schema", {"detail_level": detail})
            payload = result.structured_content
            assert payload["total_columns"] == 5
            if detail == "compact":
                group = next(g for g in payload["schema_groups"] if g["tables"][0]["name"] == "generated")
                assert group["column_count"] == 4
                assert group["generated_columns"] == {"stored": "stored", "virtual": "virtual"}
            else:
                assert payload["schema"]["generated"]["columns"][2]["generation_type"] == "stored"
        result = await client.call_tool("describe_table", {"table_name": "searchable"})
        assert [c["column_name"] for c in result.structured_content["columns"]] == ["body"]
        result = await client.call_tool("query", {"sql": "SELECT rank FROM searchable('hello')"})
        assert len(result.structured_content["data"]) == 1


def test_generated_metadata_does_not_evaluate_expressions(virtual_adapter):
    adapter = virtual_adapter
    called = []
    with adapter._engine.begin() as db:
        db.connection.dbapi_connection.create_function("marker", 1, lambda value: called.append(value) or value, deterministic=True)
        db.exec_driver_sql("CREATE TABLE generated(n,computed AS (marker(n)) VIRTUAL)")
        db.exec_driver_sql("INSERT INTO generated(n) VALUES(7)")
    called.clear()
    columns = adapter.get_columns("generated")
    assert [c["column_name"] for c in columns] == ["n", "computed"]
    assert called == []


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_generated_kind_distinguishes_otherwise_identical_compact_groups(review_server, mode):
    server = review_server("SELECT value FROM ordinary", ddl="""
        CREATE TABLE ordinary(base INT,value INT);
        CREATE TABLE computed_virtual(base INT,value INT AS (base+1) VIRTUAL);
        CREATE TABLE computed_stored(base INT,value INT AS (base+1) STORED);
        """, read={"mode": "allowlist", "tables": ["ordinary", "computed_virtual", "computed_stored"]})
    async with Client(server, mode=mode) as client:
        result = await client.call_tool("get_full_schema", {"detail_level": "compact"})
        payload = result.structured_content
        assert payload["schema_group_count"] == 3
        assert payload["total_columns"] == 6
        assert all(group["columns"] == [["base", "INT"], ["value", "INT"]] for group in payload["schema_groups"])
