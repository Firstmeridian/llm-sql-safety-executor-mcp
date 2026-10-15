"""Regression boundaries from the v3.8.1 read-policy review."""

import sqlite3
from types import SimpleNamespace

from fastmcp import Client
import pytest
from sql_safety_executor.database.relations import ReadRelation, RelationReference

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import (
    _SQLITE_PRAGMA_OBJECTS,
    _validate_sql_query_policy,
)
from sql_safety_executor.core.types import ConnectionContext
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.registry import ConnectionRegistry
from sql_safety_executor.prompts import render
from sql_safety_executor.skills.access import (
    _get_skill_schema_snapshot,
    _skill_availability_state,
)
from sql_safety_executor.skills.catalog import SkillMetadata
from tests.support import write_toml


def _config(directory, *, read_mode="all", union=False):
    directory.mkdir(exist_ok=True)
    read = {"mode": read_mode, "allow_union": union}
    if read_mode == "allowlist":
        read["tables"] = ["orders", "pragma_orders"]
    write_toml(directory / "server.toml", {
        "schema_version": 1,
        "files": {"connections": "connections.toml"},
        "server": {"default_connection": "analytics"},
    })
    write_toml(directory / "connections.toml", {
        "schema_version": 1,
        "connections": {"analytics": {
            "type": "sqlite", "sqlite": {"path": "fixture.sqlite"}, "read": read,
        }},
    })
    return load_config(directory / "server.toml")


PRAGMA_QUERIES = [
    f"SELECT file FROM {name}{suffix}"
    for name in [
        "pragma_database_list", '"pragma_database_list"',
        "'pragma_database_list'", "`pragma_database_list`", "[pragma_database_list]",
    ]
    for suffix in ["", "()"]
] + [
    'SELECT p.file FROM orders JOIN "pragma_database_list" AS p',
    "SELECT p.file FROM orders, 'pragma_database_list' AS p",
    'SELECT p.file FROM orders JOIN ("pragma_database_list") AS p',
    'SELECT file FROM main."pragma_database_list"',
    "SELECT file FROM main.'pragma_database_list' AS p",
    "SELECT file FROM orders JOIN ('main'.'pragma_database_list') AS p",
    "SELECT file FROM orders JOIN 'main'.'pragma_database_list' AS p",
    "SELECT file FROM orders, 'main'.'pragma_database_list' AS p",
    "SELECT file FROM orders, (pragma_database_list AS p)",
    'SELECT file FROM (orders, "pragma_database_list")',
    'SELECT file FROM ((("pragma_database_list")))',
    'SELECT file FROM orders JOIN ((("pragma_database_list")))',
    'SELECT file FROM orders JOIN (orders AS o, "pragma_database_list")',
    'SELECT file FROM orders JOIN ((orders AS o JOIN "pragma_database_list"))',
    'SELECT name FROM "pragma_table_info"(\'orders\')',
    'SELECT 1 WHERE EXISTS (SELECT file FROM "pragma_database_list")',
    'WITH p AS (SELECT file FROM "pragma_database_list") SELECT * FROM p',
]

# These deeper relation groups crashed SQLite 3.45.1 in an isolated native
# probe. Exercise the policy and the before-execute sentinel only, never run
# them against the test process's database engine.
NESTED_PRAGMA_QUERIES = [
    'SELECT file FROM orders JOIN (orders AS o JOIN (orders AS p, "pragma_database_list"))',
    'SELECT file FROM orders JOIN (orders AS o JOIN (orders AS p JOIN "pragma_database_list"))',
]


@pytest.mark.parametrize("sql", PRAGMA_QUERIES)
def test_actual_pragma_relations_rejected_for_all_quote_forms(sql):
    policy = ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))
    # Confirm these are real SQLite access paths, not invalid SQL test strings.
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE orders(id INTEGER)")
        db.execute(sql).fetchall()
    decision = _validate_sql_query_policy(None, sql, policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and "PRAGMA" in error


@pytest.mark.parametrize("sql", [
    "SELECT pragma_note FROM orders",
    "SELECT `pragma_note` FROM orders",
    'SELECT "pragma_note" FROM orders',
    "SELECT id AS pragma_alias FROM orders",
    "SELECT id AS pragma_database_list FROM orders",
    "SELECT pragma_database_list.id FROM orders AS pragma_database_list",
    "SELECT id FROM pragma_orders",
    'SELECT id FROM "pragma_orders"',
    "SELECT 'pragma_database_list', 'pragma_table_info(orders)' FROM orders",
    "WITH pragma_orders AS (SELECT id FROM orders) SELECT * FROM pragma_orders",
])
@pytest.mark.parametrize("case_sensitive", [False, True])
def test_ordinary_pragma_prefix_names_remain_readable(sql, case_sensitive):
    policy = ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}),
        case_sensitive_tables=case_sensitive,
    )
    assert _validate_sql_query_policy(None, sql, policy).allowed


def test_reserved_pragma_names_cover_runtime_sqlite_builtins():
    # Fail visibly on a SQLite upgrade that introduces another table-valued
    # PRAGMA, rather than silently claiming the static reservation covers it.
    with sqlite3.connect(":memory:") as db:
        names = [row[0] for row in db.execute("PRAGMA pragma_list")]
        for name in names:
            try:
                db.execute(f'SELECT * FROM "pragma_{name}" LIMIT 0')
            except sqlite3.DatabaseError:
                continue  # Not every PRAGMA exposes a table-valued interface.
            assert "pragma_" + name in _SQLITE_PRAGMA_OBJECTS


@pytest.mark.parametrize("read_mode", ["all", "allowlist"])
async def test_query_rejects_pragma_before_adapter_execution(tmp_path, monkeypatch, read_mode):
    config = _config(tmp_path, read_mode=read_mode)
    with sqlite3.connect(tmp_path / "fixture.sqlite") as db:
        db.execute("CREATE TABLE orders(id INTEGER, pragma_note TEXT)")
        db.execute("INSERT INTO orders VALUES(1, 'business value')")
        db.execute("CREATE TABLE pragma_orders(id INTEGER)")
        db.execute("INSERT INTO pragma_orders VALUES(2)")
    server = create_server(config)
    async with Client(server) as client:
        for sql in ["SELECT pragma_note FROM orders", "SELECT id FROM pragma_orders"]:
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["success"] is True

        def unexpected_execute(*args, **kwargs):
            pytest.fail("Denied PRAGMA reference reached adapter.execute")

        adapter = server.gateway_runtime.registry.get_adapter("analytics")
        monkeypatch.setattr(adapter, "execute", unexpected_execute)
        for sql in PRAGMA_QUERIES + NESTED_PRAGMA_QUERIES:
            result = await client.call_tool("query", {"sql": sql})
            assert result.structured_content["success"] is False
            assert "PRAGMA" in result.structured_content["error"]


async def test_same_alias_prompt_isolation_without_adapter_access(tmp_path, monkeypatch):
    configs = [_config(tmp_path / "a", union=True), _config(tmp_path / "b", union=False)]

    def unexpected_adapter(*args, **kwargs):
        pytest.fail("Policy guidance must not obtain or construct an adapter")

    monkeypatch.setattr(ConnectionRegistry, "get_adapter", unexpected_adapter)
    monkeypatch.setattr("sql_safety_executor.database.registry.create_adapter", unexpected_adapter)
    servers = []
    try:
        for config in configs:
            for renderer in [render.connection_policies, render.read_policy, render.instructions, render.assistant]:
                assert renderer(config)
            servers.append(create_server(config))
        # Keep both runtimes alive while rereading A after B.
        async with Client(servers[0]) as a, Client(servers[1]) as b:
            for index, client in [(0, a), (1, b), (0, a)]:
                line = "- analytics (sqlite): reads all tables; UNION " + (
                    "allowed" if index == 0 else "disabled"
                )
                assert line in servers[index].instructions
                prompt = await client.get_prompt("sql_assistant")
                assert line in str(prompt)
                assert not servers[index].gateway_runtime.registry._adapters
                assert servers[index].gateway_runtime.default_connection_id() == "analytics"
                prompts = await client.list_prompts()
                assert next(p for p in prompts if p.name == "sql_assistant").arguments in (None, [])
    finally:
        for server in servers:
            server.gateway_runtime.close()
    assert not list(tmp_path.rglob("*.sqlite"))


@pytest.mark.parametrize("case_sensitive,required,ready", [
    (True, "Orders", True), (True, "orders", False), (False, "orders", True),
])
def test_skill_readiness_uses_connection_table_identity(case_sensitive, required, ready):
    policy = ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}),
        case_sensitive_tables=case_sensitive,
    )
    config = DatabaseConfig(
        connection_id="analytics", db_type="mysql" if case_sensitive else "sqlite",
        query_timeout_seconds=30, connect_timeout_seconds=10, policy=policy,
        mysql_database="business" if case_sensitive else None,
    )
    connection = ConnectionContext(
        "analytics", config,
        SimpleNamespace(get_read_relations=lambda: [ReadRelation(RelationReference("Orders", "business" if case_sensitive else "main"), "table")]), policy,
    )
    runtime = SimpleNamespace(config=SimpleNamespace(
        skills=SimpleNamespace(
            readiness=SimpleNamespace(check_schema=True),
            policy=SimpleNamespace(exclude_profiles=[]),
            mutation=SimpleNamespace(enabled=False),
        ), connections={"analytics": config},
    ))
    meta = SkillMetadata(
        name="read-orders", type="query", source="query.sql", risk="low",
        description="", tables=[required], _sql_template=f"SELECT * FROM {required}",
    )
    snapshot = _get_skill_schema_snapshot(runtime, connection)
    state = _skill_availability_state(runtime, meta, snapshot, connection)
    assert state["schema_ready"] is ready
    assert state["executable"] is ready
    assert state["missing_tables"] == ([] if ready else [required])


@pytest.mark.parametrize("sql", [
    "WITH a AS (SELECT * FROM secret), secret AS (SELECT 1) SELECT * FROM a",
    "WITH secret AS (SELECT * FROM secret) SELECT * FROM secret",
    "WITH a AS (SELECT * FROM secret), secret AS (SELECT * FROM allowed) SELECT * FROM a",
    "WITH allowed AS (SELECT 1) SELECT * FROM allowed WHERE EXISTS "
    "(WITH secret AS (SELECT * FROM secret) SELECT * FROM secret)",
    "EXPLAIN WITH a AS (SELECT * FROM secret), secret AS (SELECT 1) SELECT * FROM a",
])
def test_cte_names_do_not_authorize_invisible_base_tables(sql):
    policy = ConnectionPolicy(
        allowed_tables=frozenset({"allowed"}), case_sensitive_tables=True,
    )
    decision = _validate_sql_query_policy(None, sql, policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and "secret" in error


@pytest.mark.parametrize("sql", [
    "WITH a AS (SELECT * FROM allowed), b AS (SELECT * FROM a) SELECT * FROM b",
    "SELECT * FROM allowed WHERE EXISTS (WITH c AS (SELECT 1) SELECT * FROM c)",
    "WITH a AS (SELECT 1) SELECT * FROM a WHERE EXISTS "
    "(WITH b AS (SELECT * FROM a) SELECT * FROM b)",
    "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c WHERE n<3) SELECT * FROM c",
])
def test_visible_and_recursive_ctes_keep_working(sql):
    policy = ConnectionPolicy(
        allowed_tables=frozenset({"allowed"}), case_sensitive_tables=True,
        allow_union=True,
    )
    assert _validate_sql_query_policy(None, sql, policy).allowed


@pytest.mark.parametrize("target", [
    "(mysql.user)", "(mysql.user AS u)", "(mysql.user, orders AS o)",
    "((mysql.user))", '("mysql"."user")', "('mysql'.'user')",
    "(orders AS o JOIN mysql.user AS u)",
    "(orders AS o, (mysql.user))",
    "(SELECT * FROM mysql.user) AS hidden",
])
def test_grouped_join_cannot_hide_system_schema(target):
    # ATTACH belongs only to fixture setup. Raw query() cannot attach databases.
    # SQLite accepts the relation-group forms also supported by MySQL.
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE orders(id INTEGER)")
        db.execute("ATTACH DATABASE ':memory:' AS mysql")
        db.execute("CREATE TABLE mysql.user(secret TEXT)")
        db.execute(f"SELECT * FROM orders JOIN {target}").fetchall()
    policy = ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))
    decision = _validate_sql_query_policy(None, f"SELECT * FROM orders JOIN {target}", policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and "Parenthesized FROM/JOIN" in error


def test_plain_grouped_business_join_has_explicit_conservative_rejection():
    policy = ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))
    decision = _validate_sql_query_policy(None, "SELECT * FROM orders JOIN (orders AS o)", policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and "use a CTE" in error
    assert _validate_sql_query_policy(
        None, "SELECT * FROM orders JOIN orders AS o ON orders.id=o.id", policy,
    ).allowed
    assert _validate_sql_query_policy(
        None, "SELECT 'JOIN (mysql.user)' AS note FROM orders", policy,
    ).allowed


async def test_grouped_join_rejected_before_database_call(tmp_path, monkeypatch):
    server = create_server(_config(tmp_path))
    adapter = server.gateway_runtime.registry.get_adapter("analytics")
    calls = []

    def unexpected_execute(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Grouped target reached adapter.execute")

    monkeypatch.setattr(adapter, "execute", unexpected_execute)
    async with Client(server) as client:
        for target in ["(mysql.user)", "(mysql.user AS u)", "(mysql.user, orders AS o)"]:
            result = await client.call_tool("query", {"sql": f"SELECT * FROM orders JOIN {target}"})
            assert result.structured_content["success"] is False
            assert "Parenthesized FROM/JOIN" in result.structured_content["error"]
    assert not calls
    assert not (tmp_path / "fixture.sqlite").exists()


@pytest.mark.parametrize("sql", [
    "SELECT * FROM 'secret' AS allowed",
    "SELECT * FROM allowed WHERE EXISTS (SELECT * FROM 'secret' AS allowed)",
    "SELECT * FROM allowed, (secret)",
    "SELECT * FROM allowed AS a JOIN allowed AS b ON a.id=b.id, (secret)",
    "SELECT * FROM allowed AS a JOIN allowed AS b USING(id), (secret)",
    "SELECT * FROM allowed AS a JOIN allowed AS b ON a.id=b.id, secret",
    "SELECT * FROM allowed AS a JOIN allowed AS b USING(id), secret",
])
def test_sqlite_table_alias_and_loose_comma_cannot_hide_base_table(sql):
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE allowed(id INTEGER)")
        db.execute("CREATE TABLE secret(id INTEGER)")
        db.execute(sql).fetchall()
    policy = ConnectionPolicy(allowed_tables=frozenset({"allowed"}))
    decision = _validate_sql_query_policy(None, sql, policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and error


@pytest.mark.parametrize("sql,reason", [
    ("SELECT * FROM { OJ secret AS s LEFT OUTER JOIN allowed AS a ON 1=1 }", "ODBC"),
    ("SELECT EXISTS(TABLE secret)", "TABLE query expressions"),
    ("SELECT 1 UNION TABLE secret", "TABLE query expressions"),
    ("SELECT * FROM allowed STRAIGHT_JOIN secret", "Access denied"),
])
def test_mysql_alternative_relation_syntax_does_not_skip_authorization(sql, reason):
    policy = ConnectionPolicy(
        allowed_tables=frozenset({"allowed"}), allow_union=True, case_sensitive_tables=True,
    )
    decision = _validate_sql_query_policy(None, sql, policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and reason in error


def test_alternative_syntax_words_in_data_and_quoted_columns_are_not_commands():
    policy = ConnectionPolicy(allowed_tables=frozenset({"allowed"}))
    sql = "SELECT 'TABLE secret', '{ OJ secret }', `table` FROM allowed AS 'ordinary_alias'"
    assert _validate_sql_query_policy(None, sql, policy).allowed


@pytest.mark.parametrize("sql", [
    "SELECT * FROM 'mysql'.user", "SELECT * FROM 'mysql'.'user' AS u",
    "SELECT * FROM mysql.'user' AS u",
    "SELECT * FROM orders, 'mysql'.user",
    "SELECT * FROM { OJ mysql.user AS u LEFT OUTER JOIN orders AS o ON 1=1 }",
    "SELECT EXISTS(TABLE mysql.user)",
    "SELECT * FROM orders STRAIGHT_JOIN mysql.user",
    "SELECT * FROM orders AS a JOIN orders AS b ON a.id=b.id, mysql.user",
    "SELECT * FROM orders AS a JOIN orders AS b USING(id), mysql.user",
])
def test_alternative_relation_forms_cannot_hide_system_schema_in_all_scope(sql):
    policy = ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))
    decision = _validate_sql_query_policy(None, sql, policy)
    allowed = decision.allowed
    error = decision.message
    assert not allowed and error
