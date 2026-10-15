"""Authorized metadata identity, view readiness and callback result boundaries."""

import json
import sqlite3

from fastmcp import Client
from pydantic_core import to_json
import pytest
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql, sqlite

from sql_safety_executor import create_server, load_config
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.mysql import MySQLAdapter
from sql_safety_executor.database.relations import RelationReference, render_relation_for_text
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("main_exists", [True, False])
@pytest.mark.parametrize("shadow", ["table", "view", "aux"])
async def test_internal_reads_remain_in_authorized_main(bundle, tmp_path, mode, main_exists, shadow):
    settings, connections, _, save = bundle
    settings["tools"] = {"schema": True, "table_summary": True}
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["main.orders"]}
    if main_exists:
        with sqlite3.connect(tmp_path / "db.sqlite") as db:
            db.executescript("CREATE TABLE orders(n INTEGER, main_label TEXT); INSERT INTO orders VALUES(7,'main');")
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            adapter = server.gateway_runtime.registry.get_adapter("demo")
            assert adapter.connect() and adapter._engine is not None
            with adapter._engine.begin() as db:
                if shadow == "aux":
                    db.exec_driver_sql("ATTACH ':memory:' AS aux")
                    db.exec_driver_sql("CREATE TABLE aux.orders(n INTEGER, shadow_label TEXT)")
                    db.exec_driver_sql("INSERT INTO aux.orders VALUES(99,'aux'),(100,'aux')")
                elif shadow == "view":
                    db.exec_driver_sql("CREATE TEMP TABLE hidden_values(n INTEGER, shadow_label TEXT)")
                    db.exec_driver_sql("INSERT INTO hidden_values VALUES(99,'temp'),(100,'temp')")
                    db.exec_driver_sql("CREATE TEMP VIEW orders AS SELECT * FROM hidden_values")
                else:
                    db.exec_driver_sql("CREATE TEMP TABLE orders(n INTEGER, shadow_label TEXT)")
                    db.exec_driver_sql("INSERT INTO temp.orders VALUES(99,'temp'),(100,'temp')")
                schema = "aux" if shadow == "aux" else "temp"
                assert db.exec_driver_sql(f"SELECT n FROM {schema}.orders").fetchall() == [(99,), (100,)]
            statements = []
            def capture(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(adapter._engine, "before_cursor_execute", capture)
            refused = await client.call_tool("query", {"sql": f"SELECT n FROM {schema}.orders"})
            assert refused.structured_content["error_code"] == "table_access_denied" and not statements
            sampled = await client.call_tool("sample", {"table_name": "orders"})
            exact = await client.call_tool("get_table_summary", {"table_name": "orders", "exact_count": True})
            estimate = await client.call_tool("get_table_summary", {"table_name": "orders"})
            if main_exists:
                assert sampled.structured_content["data"] == [{"n": 7, "main_label": "main"}]
                assert sampled.structured_content["query"] == 'SELECT * FROM "main"."orders" LIMIT 5'
                assert exact.structured_content["row_count"] == estimate.structured_content["row_count"] == 1
                assert [column["column_name"] for column in exact.structured_content["columns"]] == ["n", "main_label"]
            else:
                assert not sampled.structured_content["success"] and sampled.structured_content["error_code"] == "unknown_table"
                assert not exact.structured_content["success"] and exact.structured_content["error_code"] == "unknown_table"
                assert not estimate.structured_content["success"]
            assert 'SELECT * FROM "main"."orders" LIMIT 5' in statements
            assert 'SELECT COUNT(*) as total_rows FROM "main"."orders"' in statements
            assert all('FROM "orders"' not in sql for sql in statements)
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_bare_metadata_grant_is_still_bound_to_main(bundle, tmp_path, mode):
    settings, connections, _, save = bundle
    settings["tools"] = {"schema": True, "table_summary": True}
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["orders"]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n INTEGER); INSERT INTO orders VALUES(7);")
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            adapter = server.gateway_runtime.registry.get_adapter("demo")
            assert adapter.connect() and adapter._engine is not None
            with adapter._engine.begin() as db:
                db.exec_driver_sql("CREATE TEMP TABLE orders(n INTEGER)")
                db.exec_driver_sql("INSERT INTO temp.orders VALUES(99),(100)")
            raw = await client.call_tool("query", {"sql": "SELECT n FROM orders"})
            sampled = await client.call_tool("sample", {"table_name": "orders"})
            exact = await client.call_tool("get_table_summary", {"table_name": "orders", "exact_count": True})
            assert raw.structured_content["data"] == [{"n": 99}, {"n": 100}]
            assert sampled.structured_content["data"] == [{"n": 7}]
            assert exact.structured_content["row_count"] == 1
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("literal", [False, True])
async def test_readiness_observes_views_without_conflating_identity(bundle, tmp_path, mode, literal, monkeypatch):
    _, connections, skills, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["main.orders"]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute('CREATE VIEW "main.orders" AS SELECT 99 AS n' if literal else "CREATE VIEW orders AS SELECT 7 AS n")
    directory = tmp_path / "skills" / "view-read"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text("---\nname: view-read\ntype: query\nsource: query.sql\nrisk: low\ndescription: View readiness\nparams: {}\n---\n")
    (directory / "query.sql").write_text("SELECT n FROM main.orders")
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    monkeypatch.setattr(adapter, "get_row_estimate", lambda *_: pytest.fail("Readiness must not estimate rows"))
    try:
        async with Client(server, mode=mode) as client:
            relations = adapter.get_read_relations()
            assert [(r.reference, r.kind) for r in relations] == [(RelationReference("main.orders" if literal else "orders", "main"), "view")]
            listed = await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})
            detail = await client.call_tool("get_skill_detail", {"skill_name": "view-read"})
            default = await client.call_tool("list_skills", {})
            executed = await client.call_tool("execute_query_skill", {"skill_name": "view-read", "params": {}}, raise_on_error=False)
            for state in (listed.structured_content["skills"][0], detail.structured_content["skill"]):
                assert state["policy_allowed"]
                assert state["schema_ready"] is (not literal)
                assert state["missing_tables"] == (["main.orders"] if literal else [])
            if literal:
                assert executed.is_error and default.structured_content["skills"] == []
            else:
                raw = await client.call_tool("query", {"sql": "SELECT n FROM main.orders"})
                assert raw.structured_content["data"] == executed.structured_content["data"] == [{"n": 7}]
                assert not executed.is_error and len(default.structured_content["skills"]) == 1
            assert adapter.get_tables() == []  # Table discovery keeps its table-only contract.
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("stage", ["preview", "execute"])
@pytest.mark.parametrize("invalid", ["exception", "nonbool", "nonlist", "extra", "nondict", "cycle"])
async def test_invalid_validation_is_safe_before_and_after_token(bundle, tmp_path, mode, stage, invalid, monkeypatch):
    _, connections, skills, save = bundle
    directory = tmp_path / "skills" / "invalid-validation"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text("---\nname: invalid-validation\ntype: mutation\nsource: mutation.py\nrisk: low\ndescription: Callback contract\nparams: {}\n---\n")
    (directory / "mutation.py").write_text('''from sql_safety_executor.skills.mutation import MutationBase
from sql_safety_executor.database.errors import DatabaseQueryError
class Mutation(MutationBase):
    invalid = None
    executions = 0
    def validate(self, params):
        kind = type(self).invalid
        if kind == "exception": return {"valid": False, "errors": [DatabaseQueryError("unknown_table")]}
        if kind == "nonbool": return {"valid": "false"}
        if kind == "nonlist": return {"valid": False, "errors": "private_reason"}
        if kind == "extra": return {"valid": True, "private": object()}
        if kind == "nondict": return None
        if kind == "cycle":
            value = {"valid": False}
            value["private"] = value
            return value
        return {"valid": True, "business": {"n": 7}}
    def preview(self, params): return {"affected_rows_estimate": 1}
    def execute(self, params):
        type(self).executions += 1
        raise AssertionError("Must not execute")
''')
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    connections["connections"]["demo"]["mutation"] = {"enabled": True, "skills": ["invalid-validation"]}
    skills["skills"]["directory"] = str(directory.parent)
    skills["skills"]["readiness"] = {"check_schema": False}
    skills["skills"]["mutation"]["mrtr"] = {"enabled": False}
    server = create_server(load_config(save(use_skills=True)))
    cls = server.gateway_runtime.catalog.get_skills_cache()["invalid-validation"]._mutation_class
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    monkeypatch.setattr(adapter, "execute_write", lambda *_a, **_k: pytest.fail("No write may be attempted"))
    try:
        async with Client(server, mode=mode) as client:
            args = {"skill_name": "invalid-validation", "params": {}}
            if stage == "execute":
                preview = await client.call_tool("execute_mutation_skill", args)
                assert preview.structured_content["success"] and len(server.gateway_runtime.tokens) == 1
                args.update(confirm=True, preview_token=preview.structured_content["preview_token"])
            cls.invalid = invalid
            failed = await client.call_tool("execute_mutation_skill", args)
            assert not failed.is_error
            payload = failed.structured_content
            assert payload["success"] is False and payload["error_code"] == "validation_failed"
            assert payload["execution_outcome"] == "not_executed" and payload["mode"] == stage
            assert payload["validation"] == {"valid": False, "errors": ["Mutation validation returned an invalid result."]}
            assert "private" not in to_json(payload).decode()
            assert len(server.gateway_runtime.tokens) == cls.executions == 0
            assert failed.meta["preview_token_consumed"] is (stage == "execute")
            if stage == "execute":
                replay = await client.call_tool("execute_mutation_skill", args, raise_on_error=False)
                assert replay.is_error
            else:
                assert "preview_token" not in payload
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("db_type,schema,name", [
    ("sqlite", "main", "orders"), ("sqlite", 'a"b', 'main.orders'),
    ("mysql", "order-history", "orders"), ("mysql", "a`b", "orders"),
    ("mysql", ":database", "orders"),
])
def test_generated_relations_quote_components_and_preserve_colons(db_type, schema, name):
    sql = render_relation_for_text(RelationReference(name, schema), db_type)
    statement = text("SELECT * FROM " + sql)
    dialect = mysql.dialect() if db_type == "mysql" else sqlite.dialect()
    compiled = statement.compile(dialect=dialect)
    assert compiled.params == {}
    expected = dialect.identifier_preparer.quote_identifier(schema) + "." + dialect.identifier_preparer.quote_identifier(name)
    assert str(compiled) == "SELECT * FROM " + expected


def test_mysql_metadata_uses_configured_schema_for_every_observation(monkeypatch):
    config = DatabaseConfig(connection_id="demo", db_type="mysql", query_timeout_seconds=30,
        connect_timeout_seconds=5, mysql_database="fixed-schema", policy=ConnectionPolicy())
    adapter = MySQLAdapter(config)
    calls = []
    def execute(sql, **kwargs):
        params = kwargs.get("params", {})
        calls.append((sql, params))
        if "TABLE_SCHEMA = 'information_schema'" in sql:
            return []  # Visibility capability probe remains pinned to information_schema.
        assert "DATABASE()" not in sql and params["schema_name"] == "fixed-schema"
        if "TABLE_TYPE IN" in sql: return [("orders", "BASE TABLE"), ("report", "VIEW")]
        if "TABLE_TYPE = 'BASE TABLE'" in sql: return [("orders", 1)]
        if "INFORMATION_SCHEMA.COLUMNS" in sql: return [("n", "int", "YES", "", None)]
        if "INFORMATION_SCHEMA.STATISTICS" in sql: return []
        return [(1,)]
    monkeypatch.setattr(adapter, "execute", execute)
    assert adapter.get_tables() == [{"table_name": "orders", "row_count": 1}]
    assert [(r.reference.schema, r.kind) for r in adapter.get_read_relations()] == [("fixed-schema", "table"), ("fixed-schema", "view")]
    assert adapter.get_columns("orders")[0]["column_name"] == "n"
    assert adapter.get_indexes("orders") == [] and adapter.get_row_estimate("orders") == 1
    assert adapter.render_metadata_relation(RelationReference("orders", "fixed-schema")) == '`fixed-schema`.`orders`'
    with pytest.raises(ValueError):
        adapter.render_metadata_relation(RelationReference("orders", "other"))
