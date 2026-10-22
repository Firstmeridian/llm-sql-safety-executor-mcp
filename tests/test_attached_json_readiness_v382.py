"""Attached JSON-name readiness follows observed bindings, never assumed main."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastmcp import Client

from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.core.types import ConnectionContext
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.skills.access import _conditional_skill_relations, _get_skill_schema_snapshot
from tests.test_external_read_review_v382 import review_server, bundle


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def attach(adapter, schema, names=(), value="hello aux"):
    with adapter._engine.begin() as db:
        if schema not in {"main", "temp"}:
            db.exec_driver_sql("ATTACH ':memory:' AS " + quoted(schema))
        for name in names:
            target = quoted(schema) + "." + quoted(name)
            db.exec_driver_sql(f"CREATE VIRTUAL TABLE {target} USING fts5(value)")
            db.exec_driver_sql(f"INSERT INTO {target} VALUES(?)", (value,))


def context(server):
    runtime = server.gateway_runtime
    config = runtime.registry.get_config("demo")
    adapter = runtime.registry.get_adapter("demo")
    adapter.connect()
    return runtime, ConnectionContext("demo", config, adapter, config.policy)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", ["json_each", "json_tree"])
@pytest.mark.parametrize("form", ["from", "quoted", "upper", "join", "in", "cte"])
async def test_attached_binding_shared_by_skill_discovery_detail_and_precheck(review_server, mode, name, form):
    source = f"{name}(" + repr('"hello"') + ")"
    sql = {
        "from": f"SELECT value FROM {source}",
        "quoted": f"SELECT value FROM {quoted(name)}('\"hello\"')",
        "upper": f"SELECT value FROM {name.upper()}('\"hello\"')",
        "join": f"SELECT j.value FROM orders JOIN {source} AS j ON orders.n=7",
        "in": f"SELECT 7 AS n WHERE 'hello aux' IN {source}",
        "cte": f"WITH found AS (SELECT value FROM {source}) SELECT value FROM found",
    }[form]
    server = review_server(sql, read={"mode": "allowlist", "relations": [
        {"schema": "main", "name": "orders"}, {"schema": "aux", "name": name}]})
    _, connection = context(server)
    attach(connection.adapter, "aux", [name])
    async with Client(server, mode=mode) as client:
        raw = (await client.call_tool("query", {"sql": sql})).structured_content
        assert raw["success"] and raw["data"] == ([{"n": 7}] if form == "in" else [{"value": "hello aux"}])
        detail = (await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})).structured_content["skill"]
        listing = (await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})).structured_content["skills"][0]
        for state in [detail, listing]:
            assert f"aux.{name}" in state["inferred_tables"]
            assert state["unverified_tables"] == [f"aux.{name}"]
            assert not state["schema_ready"] and not state["executable"]
            assert state["conditional_dependencies"] == [{"relation": f"aux.{name}", "state": "stored"}]
        assert (await client.call_tool("list_skills", {})).structured_content["skills"] == []
        result = await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}}, raise_on_error=False)
        assert result.is_error and "could not verify" in result.content[0].text


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("name", ["json_each", "json_tree"])
@pytest.mark.parametrize("schemas,chosen", [
    (["first", "second"], "first"),
    (["second", "first"], "second"),
    (["aux", "main"], "main"),
    (["aux", "main", "temp"], "temp"),
    (['a."ux:with.dot'], 'a."ux:with.dot'),
])
async def test_json_lookup_order_and_component_identity(review_server, mode, name, schemas, chosen):
    sql = f"SELECT value FROM {name}('\"hello\"')"
    server = review_server(sql, read={"mode": "allowlist", "relations": [
        {"schema": schema, "name": name} for schema in schemas]})
    runtime, connection = context(server)
    for schema in schemas:
        attach(connection.adapter, schema, [name], "hello " + schema)
    observation = connection.adapter.get_json_name_observation()
    assert observation.complete
    assert observation.relations[0] == RelationReference(name, chosen)
    async with Client(server, mode=mode) as client:
        data = (await client.call_tool("query", {"sql": sql})).structured_content
        assert data["data"] == [{"value": "hello " + chosen}]
        state = (await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})).structured_content["skill"]
        expected = RelationReference(name, chosen).display_name
        assert state["inferred_tables"] == [expected]
        assert state["schema_ready"] is (chosen == "main")


@pytest.mark.parametrize("failure", ["directory_list", "temp", "aux", "budget", "deadline"])
@pytest.mark.parametrize("sql,ready", [
    ("SELECT value FROM json_each('[7]')", False),
    ("SELECT value FROM main.json_each('[7]')", True),
    ("SELECT n FROM orders", True),
])
async def test_incomplete_json_observation_does_not_poison_known_default_scope(review_server, monkeypatch, failure, sql, ready):
    from sql_safety_executor.database import sqlite as module
    server = review_server(sql)
    runtime, connection = context(server)
    adapter = connection.adapter
    attach(adapter, "aux")
    original = adapter.execute
    if failure == "budget":
        monkeypatch.setattr(module, "_JSON_NAME_SCHEMA_LIMIT", 2)
    elif failure == "deadline":
        observe = adapter.get_json_name_observation
        def expired_observation():
            clock = iter([10.0, 1000.0])
            with monkeypatch.context() as scope:
                scope.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(clock, 1000.0)))
                return observe()
        monkeypatch.setattr(adapter, "get_json_name_observation", expired_observation)
    else:
        def execute(statement, *args, **kwargs):
            if (failure == "directory_list" and statement == "PRAGMA database_list"
                    or failure in {"temp", "aux"} and f'FROM "{failure}"."sqlite_master"' in statement):
                raise DatabaseQueryError()
            return original(statement, *args, **kwargs)
        monkeypatch.setattr(adapter, "execute", execute)
    async with Client(server) as client:
        state = (await client.call_tool("get_skill_detail", {"skill_name": "review-probe"})).structured_content["skill"]
        assert state["schema_ready"] is ready
        if not ready:
            assert state["unverified_tables"] == ["json_each"] and state["missing_tables"] == []
        else:
            assert state["unverified_tables"] == []


def test_partial_prefix_match_remains_known_without_claiming_other_name_absent(review_server, monkeypatch):
    server = review_server("SELECT value FROM json_each('[7]')")
    runtime, connection = context(server)
    attach(connection.adapter, "temp", ["json_each"])
    original = connection.adapter.execute
    def execute(statement, *args, **kwargs):
        if 'FROM "main"."sqlite_master"' in statement:
            raise DatabaseQueryError()
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(connection.adapter, "execute", execute)
    snapshot = _get_skill_schema_snapshot(runtime, connection)
    assert not snapshot.json_name_observation.complete
    assert snapshot.json_name_observation.searched_schemas == ("temp",)
    for name, state in [("json_each", "stored"), ("json_tree", "unverified")]:
        analysis = analyze_sql(f"SELECT value FROM {name}('[7]')", connection.adapter.analysis_context)
        conditional = _conditional_skill_relations(analysis, connection, snapshot)
        assert list(conditional.values()) == [state]


def test_database_list_table_shadow_does_not_replace_catalog_discovery(review_server):
    server = review_server("SELECT value FROM json_each('[7]')",
                           ddl="CREATE TABLE pragma_database_list(name);INSERT INTO pragma_database_list VALUES('wrong');")
    runtime, connection = context(server)
    attach(connection.adapter, "aux", ["json_each"])
    snapshot = _get_skill_schema_snapshot(runtime, connection)
    assert snapshot.json_name_observation.complete
    assert snapshot.json_name_observation.relations == (RelationReference("json_each", "aux"),)


@pytest.mark.parametrize("schema", ["aux", "temp"])
@pytest.mark.parametrize("name", ["json_each", "json_tree"])
def test_explicit_and_resolved_calls_share_observed_stored_identity(review_server, schema, name):
    server = review_server(f"SELECT value FROM {name}('[7]')")
    runtime, connection = context(server)
    attach(connection.adapter, schema, [name])
    snapshot = _get_skill_schema_snapshot(runtime, connection)
    states = [_conditional_skill_relations(
        analyze_sql(f"SELECT value FROM {prefix}{name}('[7]')", connection.adapter.analysis_context),
        connection, snapshot) for prefix in ["", schema + "."]]
    assert states[0] == states[1] == {RelationReference(name, schema): "stored"}


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_live_binding_grants_and_readiness_disable_keep_execution_guard(review_server, mode, monkeypatch):
    server = review_server("SELECT value FROM json_each('\"hello\"')", read={
        "mode": "allowlist", "relations": [{"schema": "main", "name": "orders"}, {"schema": "aux", "name": "json_each"}]})
    runtime, connection = context(server)
    async with Client(server, mode=mode) as client:
        detail = lambda: client.call_tool("get_skill_detail", {"skill_name": "review-probe"})
        initial = (await detail()).structured_content["skill"]
        assert initial["inferred_tables"] == [] and initial["executable"]
        attach(connection.adapter, "aux", ["json_each"])
        attached = (await detail()).structured_content["skill"]
        assert attached["inferred_tables"] == ["aux.json_each"] and not attached["executable"]
        with connection.adapter._engine.connect() as db:
            db.exec_driver_sql("DETACH DATABASE aux")
        assert (await detail()).structured_content["skill"]["executable"]
        attach(connection.adapter, "aux", ["json_each"])
        runtime.config = replace(runtime.config, skills=runtime.config.skills.model_copy(update={
            "readiness": runtime.config.skills.readiness.model_copy(update={"check_schema": False})}))
        monkeypatch.setattr(connection.adapter, "get_json_name_observation", lambda: pytest.fail("readiness disabled must not probe"))
        result = (await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})).structured_content
        assert result["data"] == [{"value": "hello aux"}]
        config = runtime.registry.get_config("demo")
        revoked = replace(config.policy, allowed_tables=frozenset({"main.orders"}),
                          allowed_relations=frozenset({RelationReference("orders", "main")}))
        runtime.registry.configs = {**runtime.registry.configs, "demo": replace(config, policy=revoked)}
        denied = (await client.call_tool("execute_query_skill", {"skill_name": "review-probe", "params": {}})).structured_content
        assert not denied["success"] and denied["error_code"] == "view_scope_unresolved"

