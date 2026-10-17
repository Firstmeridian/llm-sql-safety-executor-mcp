"""Native object identity, scoped readiness and post-token validation failures."""

import sqlite3
from types import SimpleNamespace

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.types import ConnectionContext
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.relations import ReadRelation, RelationReference
from sql_safety_executor.skills.access import _get_skill_schema_snapshot, _skill_availability_state
from sql_safety_executor.skills.catalog import SkillMetadata
from tests.test_v38_config import bundle as bundle


@pytest.fixture
def relation_server(bundle, tmp_path):
    _, connections, skills, save = bundle
    servers = []

    def build(sql, *, grant="main.orders", ordinary=True, literal=True, declared=False):
        with sqlite3.connect(tmp_path / "db.sqlite") as db:
            if ordinary:
                db.execute("CREATE TABLE IF NOT EXISTS orders(n INTEGER)")
                db.execute("INSERT INTO orders VALUES(7)")
            if literal:
                db.execute('CREATE TABLE IF NOT EXISTS "main.orders"(n INTEGER)')
                db.execute('INSERT INTO "main.orders" VALUES(99)')
                db.execute('CREATE TABLE IF NOT EXISTS "information_schema.orders"(n INTEGER)')
                db.execute('INSERT INTO "information_schema.orders" VALUES(13)')
        directory = tmp_path / "skills" / "relation-probe"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "skill_def.md").write_text(
            "---\nname: relation-probe\ntype: query\nsource: query.sql\nrisk: low\n"
            "description: Relation identity review\nparams: {}\n"
            + (f"tables: [{grant}]\n" if declared else "") + "---\n")
        (directory / "query.sql").write_text(sql)
        connections["connections"]["demo"]["read"] = (
            {"mode": "all"} if grant == "*" else {"mode": "allowlist", "tables": [grant]}
        )
        skills["skills"] = {"enabled": True, "directory": str(directory.parent),
            "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
        server = create_server(load_config(save(use_skills=True)))
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("sql,grant,allowed,value", [
    ("SELECT n FROM main.orders", "main.orders", True, 7),
    ('SELECT n FROM "main"."orders"', "main.orders", True, 7),
    ("SELECT n FROM [main].[orders]", "main.orders", True, 7),
    ("SELECT n FROM `main`.`orders`", "main.orders", True, 7),
    ('SELECT n FROM "main.orders"', "main.orders", False, 99),
    ("SELECT n FROM [main.orders]", "main.orders", False, 99),
    ("SELECT n FROM `main.orders`", "main.orders", False, 99),
    ('SELECT n FROM main."main.orders"', "main.orders", False, 99),
    ('SELECT n FROM main."main.orders"', "main.main.orders", True, 99),
    ('WITH "main.orders" AS (SELECT 7 AS n) SELECT n FROM "main.orders"', "main.orders", True, 7),
    ('WITH c AS (SELECT n FROM "main.orders") SELECT n FROM c', "main.orders", False, 99),
    ("SELECT 7 IN main.orders AS n", "main.orders", True, 1),
    ('SELECT 7 IN "main.orders" AS n', "main.orders", False, 0),
])
async def test_sqlite_relation_boundaries_native_and_gateway(relation_server, mode, sql, grant, allowed, value):
    server = relation_server(sql, grant=grant)
    path = server.gateway_runtime.config.connections["demo"].sqlite_database_path
    with sqlite3.connect(path) as db:
        assert db.execute(sql).fetchall() == [(value,)]
    async with Client(server, mode=mode) as client:
        result = await client.call_tool("query", {"sql": sql, "connection_id": "demo"})
        assert result.structured_content["success"] is allowed
        if allowed:
            assert result.structured_content["data"] == [{"n": value}]
        else:
            assert result.structured_content["error_code"] == "table_access_denied"
        listed = await client.call_tool("list_skills", {"available_only": False, "detail_level": "full"})
        assert listed.structured_content["skills"][0]["policy_allowed"] is allowed
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}}, raise_on_error=False)
        assert not executed.is_error
        assert executed.structured_content["success"] is allowed
        if allowed:
            assert executed.structured_content["data"] == [{"n": value}]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("declared", [False, True])
async def test_qualified_skill_and_metadata_share_current_schema(relation_server, mode, declared):
    server = relation_server('SELECT n FROM "MAIN"."ORDERS"', declared=declared)
    async with Client(server, mode=mode) as client:
        raw = await client.call_tool("query", {"sql": 'SELECT n FROM "MAIN"."ORDERS"'})
        listed = await client.call_tool("list_skills", {"detail_level": "full"})
        detail = await client.call_tool("get_skill_detail", {"skill_name": "relation-probe"})
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}})
        assert raw.structured_content["data"] == executed.structured_content["data"] == [{"n": 7}]
        for state in [listed.structured_content["skills"][0], detail.structured_content["skill"]]:
            assert state["executable"] and state["schema_ready"] and state["schema_check_available"]
            assert state["missing_tables"] == state["unverified_tables"] == []
        tables = await client.call_tool("list_tables", {})
        assert [table["table_name"] for table in tables.structured_content["tables"]] == ["orders"]
        description = await client.call_tool("describe_table", {"table_name": "orders"})
        assert description.structured_content["success"]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_literal_dotted_table_cannot_satisfy_qualified_dependency(relation_server, mode):
    server = relation_server("SELECT n FROM main.orders", ordinary=False)
    async with Client(server, mode=mode) as client:
        raw = await client.call_tool("query", {"sql": "SELECT n FROM main.orders"})
        assert raw.structured_content["error_code"] == "unknown_table"
        full = await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})
        state = full.structured_content["skills"][0]
        assert state["missing_tables"] == ["main.orders"] and not state["schema_ready"]
        listed = await client.call_tool("list_skills", {})
        assert listed.structured_content["skills"] == []
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}}, raise_on_error=False)
        assert executed.is_error


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_all_scope_preserves_literal_dotted_dependency(relation_server, mode):
    server = relation_server('SELECT n FROM "main.orders"', grant="*", ordinary=False)
    async with Client(server, mode=mode) as client:
        listed = await client.call_tool("list_skills", {"detail_level": "full"})
        state = listed.structured_content["skills"][0]
        assert state["inferred_tables"] == ['"main.orders"'] and state["schema_ready"]
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}})
        assert executed.structured_content["data"] == [{"n": 99}]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("qualified", [False, True])
async def test_dots_inside_business_names_are_not_system_schema(relation_server, mode, qualified):
    sql = 'SELECT n FROM main."information_schema.orders"' if qualified else 'SELECT n FROM "information_schema.orders"'
    server = relation_server(sql, grant="*")
    async with Client(server, mode=mode) as client:
        raw = await client.call_tool("query", {"sql": sql})
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}})
        assert raw.structured_content["data"] == executed.structured_content["data"] == [{"n": 13}]
    policy = ConnectionPolicy(allowed_tables=frozenset({"*"}), read_mode="all")
    assert _validate_sql_query_policy(None, "SELECT n FROM information_schema.orders", policy).error_code == "system_schema_denied"


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_attached_schema_is_unverified_not_missing(relation_server, mode):
    server = relation_server("SELECT n FROM aux.orders", grant="aux.orders")
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    assert adapter.connect()
    with adapter._engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS aux")
        db.exec_driver_sql("CREATE TABLE aux.orders(n INTEGER)")
        db.exec_driver_sql("INSERT INTO aux.orders VALUES(123)")
    async with Client(server, mode=mode) as client:
        raw = await client.call_tool("query", {"sql": "SELECT n FROM aux.orders"})
        assert raw.structured_content["data"] == [{"n": 123}]
        full = await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})
        state = full.structured_content["skills"][0]
        assert state["policy_allowed"] and not state["schema_check_available"]
        assert state["missing_tables"] == [] and state["unverified_tables"] == ["aux.orders"]
        executed = await client.call_tool("execute_query_skill", {"skill_name": "relation-probe", "params": {}}, raise_on_error=False)
        assert executed.is_error


@pytest.mark.parametrize("schema,expected", [("business", True), ("another", False)])
def test_mysql_readiness_keeps_configured_database_scope(relation_server, schema, expected):
    server = relation_server("SELECT n FROM main.orders")
    policy = ConnectionPolicy(allowed_tables=frozenset({f"{schema}.orders"}), case_sensitive_tables=True)
    config = DatabaseConfig(connection_id="demo", db_type="mysql", policy=policy,
        query_timeout_seconds=10, connect_timeout_seconds=5, mysql_database="business")
    adapter = SimpleNamespace(analysis_context=DialectContext("mysql", default_schema="business"), resolve_analysis_context=lambda: DialectContext("mysql", default_schema="business"), get_read_relations=lambda: [ReadRelation(RelationReference("orders", "business"), "table")], cte_case_sensitive=None)
    connection = ConnectionContext("demo", config, adapter, policy)
    meta = SkillMetadata(name="mysql-probe", type="query", source="query.sql", risk="low", description="Readiness",
        _sql_template=f"SELECT n FROM {schema}.orders")
    snapshot = _get_skill_schema_snapshot(server.gateway_runtime, connection)
    state = _skill_availability_state(server.gateway_runtime, meta, snapshot, connection)
    assert state["schema_ready"] is expected
    assert state["missing_tables"] == []
    assert state["unverified_tables"] == ([] if expected else ["another.orders"])


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("failure", ["typed", "generic", "adapter"])
async def test_imperative_revalidation_failure_returns_serializable_outcome(bundle, tmp_path, mode, failure, monkeypatch):
    _, connections, skills, save = bundle
    name = "revalidation-probe"
    directory = tmp_path / "skills" / name
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: mutation\nsource: mutation.py\nrisk: low\n"
        "description: Execution validation failure\nparams: {}\n---\n")
    (directory / "mutation.py").write_text('''from sql_safety_executor.skills.mutation import MutationBase
from sql_safety_executor.database.errors import DatabaseQueryError
class Mutation(MutationBase):
    failure = None
    executions = 0
    def validate(self, params):
        if type(self).failure == "typed":
            raise DatabaseQueryError("unknown_table")
        if type(self).failure == "generic":
            raise RuntimeError("fixture_private_sql")
        if type(self).failure == "adapter":
            self.adapter.execute("SELECT * FROM fixture_private_sql")
        return {"valid": True}
    def preview(self, params):
        return {"affected_rows_estimate": 1}
    def execute(self, params):
        type(self).executions += 1
        raise AssertionError("Execution must not be reached")
''')
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    connections["connections"]["demo"]["mutation"] = {"enabled": True, "skills": [name]}
    skills["skills"]["directory"] = str(directory.parent)
    skills["skills"]["readiness"] = {"check_schema": False}
    skills["skills"]["mutation"]["mrtr"] = {"enabled": False}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute("CREATE TABLE marker(n INTEGER)")
        db.execute("INSERT INTO marker VALUES(7)")
    server = create_server(load_config(save(use_skills=True)))
    cls = server.gateway_runtime.catalog.get_skills_cache()[name]._mutation_class
    adapter = server.gateway_runtime.registry.get_adapter("demo")
    writes = []
    def forbid_write(*args, **kwargs):
        writes.append(True)
        raise AssertionError("Adapter write must not be reached")
    monkeypatch.setattr(adapter, "execute_write", forbid_write)
    try:
        async with Client(server, mode=mode) as client:
            preview = await client.call_tool("execute_mutation_skill", {"skill_name": name, "params": {}})
            assert preview.structured_content["success"] and len(server.gateway_runtime.tokens) == 1
            token = preview.structured_content["preview_token"]
            cls.failure = failure
            arguments = {"skill_name": name, "params": {}, "confirm": True, "preview_token": token}
            result = await client.call_tool("execute_mutation_skill", arguments)
            assert not result.is_error
            payload = result.structured_content
            assert payload["success"] is False and payload["error_code"] == "validation_failed"
            assert payload["execution_outcome"] == "not_executed"
            expected = "Database query failed." if failure == "generic" else "Table not found."
            assert payload["validation"] == {"valid": False, "errors": [expected]}
            assert result.meta["preview_token_validated"] and result.meta["preview_token_consumed"]
            assert len(server.gateway_runtime.tokens) == cls.executions == len(writes) == 0
            replay = await client.call_tool("execute_mutation_skill", arguments, raise_on_error=False)
            assert replay.is_error
            with sqlite3.connect(tmp_path / "db.sqlite") as db:
                assert db.execute("SELECT n FROM marker").fetchall() == [(7,)]
    finally:
        server.gateway_runtime.close()
