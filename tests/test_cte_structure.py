"""CTE classification, physical scope and Skill readiness share lexical structure."""
import sqlite3
from types import SimpleNamespace

from fastmcp import Client
import pytest
import sqlparse

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import _extract_relation_references, _validate_sql_query_policy
from sql_safety_executor.core.structure import parse_with_clause
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.relations import RelationReference
from tests.test_v38_config import bundle as bundle

NAMES = ["data", "summary", "result", "rollup", "replace", "with", "like", "regexp", "monthly_sales", "unıon", "offſet", "订单汇总"]
QUOTES = ["{}", '"{}"', "`{}`", "[{}]"]


def fixture_truth(sql):
    with sqlite3.connect(":memory:") as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7);")
        return db.execute(sql).fetchall()


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("quote", QUOTES)
@pytest.mark.parametrize("columns", [False, True])
def test_contextual_cte_structure_keeps_only_real_dependencies(name, quote, columns):
    target = quote.format(name)
    sql = f"WITH {target}{'(n)' if columns else ''} AS (SELECT n FROM orders) SELECT n FROM {target}"
    assert fixture_truth(sql) == [(7,)]
    for policy in (ConnectionPolicy(allowed_tables=frozenset({"orders"})),
                   ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"}))):
        assert _validate_sql_query_policy(None, sql, policy).allowed
    assert _extract_relation_references(sql) == [RelationReference("orders")]


@pytest.mark.parametrize("hint", ["", "MATERIALIZED", "NOT MATERIALIZED"])
@pytest.mark.parametrize("header", ["data(n)", '"monthly_sales"(n)', '"SLEEP"(n)'])
@pytest.mark.parametrize("comment", ["/* ordinary AS comment */", "-- ordinary AS comment\n"])
def test_comments_and_materialization_preserve_body_and_output(header, hint, comment):
    target = header.split("(", 1)[0]
    sql = f"WITH {header} AS {comment} {hint} (SELECT n FROM orders) SELECT n FROM {target}"
    assert fixture_truth(sql) == [(7,)]
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).allowed
    clause = parse_with_clause(sqlparse.parse(sql)[0])
    assert clause is not None and clause.definitions[0].columns == ("n",)
    assert clause.definitions[0].materialization == (hint or None)
    assert clause.definitions[0].body.sql == "SELECT n FROM orders"


@pytest.mark.parametrize("call,code", [
    ("SLEEP(0)", "expensive_function_denied"),
    ("GET_LOCK('fixture',0)", "lock_function_denied"),
    ("LOAD_FILE(NULL)", "file_operation_denied"),
    ("USER()", "server_state_denied"),
])
@pytest.mark.parametrize("header", ["data(n)", '"monthly_sales"(n)', '"SLEEP"(n)'])
@pytest.mark.parametrize("hint", ["", "MATERIALIZED", "NOT MATERIALIZED"])
def test_newly_supported_headers_never_hide_reserved_body_calls(call, code, header, hint):
    target = header.split("(", 1)[0]
    sql = f"WITH {header} AS /* body */ {hint} (SELECT {call}) SELECT n FROM {target}"
    def unexpected_io():
        pytest.fail("Reserved CTE body reached capability I/O")
    adapter = SimpleNamespace(cte_case_sensitive=None, resolve_cte_case_sensitive=unexpected_io)
    for scope in ("all", "allowlist"):
        policy = ConnectionPolicy(read_mode=scope, allowed_tables=frozenset({"*"} if scope == "all" else {"orders"}), case_sensitive_tables=True)
        decision = _validate_sql_query_policy(None, sql, policy, adapter=adapter)
        assert not decision.allowed and decision.error_code == code


@pytest.mark.parametrize("sql,reference", [
    ('WITH "data"(n) AS (SELECT n FROM blocked) SELECT n FROM "data"', RelationReference("blocked")),
    ('WITH data AS MATERIALIZED (SELECT n FROM main.blocked) SELECT n FROM data', RelationReference("blocked", "main")),
    ('WITH data AS (SELECT n FROM blocked), blocked AS (SELECT n FROM orders) SELECT n FROM data', RelationReference("blocked")),
    ('WITH data AS (SELECT n FROM data) SELECT n FROM data', RelationReference("data")),
    ('WITH "main.orders"(n) AS (SELECT 7) SELECT n FROM main.orders', RelationReference("orders", "main")),
    ('WITH data AS (WITH "inner"(n) AS (SELECT n FROM blocked) SELECT n FROM "inner") SELECT n FROM data', RelationReference("blocked")),
    ('SELECT (WITH "data"(n) AS (SELECT n FROM blocked) SELECT n FROM "data")', RelationReference("blocked")),
])
def test_new_structure_preserves_physical_self_forward_nested_and_qualified_scope(sql, reference):
    assert reference in _extract_relation_references(sql)
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    assert not decision.allowed and decision.error_code == "table_access_denied"


@pytest.mark.parametrize("sql,code", [
    ("WITH data AS (SELECT 7) UPDATE orders SET n=99", "read_only_required"),
    ("WITH replace(n) AS (SELECT 7) DELETE FROM orders", "read_only_required"),
    ('WITH "SLEEP"(n) AS (SELECT 7) INSERT INTO orders VALUES(99)', "read_only_required"),
    ('WITH "data"(n) AS (DELETE FROM orders RETURNING n) SELECT n FROM "data"', "nested_write_denied"),
    ('WITH data AS MATERIALIZED (UPDATE orders SET n=99 RETURNING n) SELECT n FROM data', "nested_write_denied"),
    ('WITH data AS (SELECT (WITH x AS (DELETE FROM orders RETURNING n) SELECT n FROM x)) SELECT * FROM data', "nested_write_denied"),
])
def test_actual_body_and_main_writes_stay_refused(sql, code):
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    assert not decision.allowed and decision.error_code == code


@pytest.mark.parametrize("tail", [
    "SELECT replace.n FROM orders, replace",
    "SELECT replace.n FROM orders JOIN replace ON orders.n=replace.n",
    "SELECT n FROM replace WHERE n IN replace",
    "SELECT 7 IN replace AS n",
])
def test_contextual_dml_cte_names_at_relation_targets_remain_reads(tail):
    sql = "WITH replace(n) AS (SELECT n FROM orders) " + tail
    assert fixture_truth(sql) in ([(7,)], [(1,)])
    assert _extract_relation_references(sql) == [RelationReference("orders")]
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).allowed


@pytest.mark.parametrize("sql", [
    "WITH data AS (SELECT (DELETE FROM orders)) SELECT * FROM data",
    "WITH data AS (SELECT 7) SELECT 7, REPLACE INTO orders VALUES(99)",
    "WITH data AS (SELECT 7 IN fn(UPDATE orders SET n=99)) SELECT * FROM data",
])
def test_relation_name_exclusion_never_hides_whole_groups_or_other_writes(sql):
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(read_mode="all", allowed_tables=frozenset({"*"})))
    assert not decision.allowed and decision.error_code in {"nested_write_denied", "sql_parse_failed"}


@pytest.mark.parametrize("name", ["unıon", "lımıt", "offſet", "wındow"])
def test_where_group_boundary_preserves_keyword_like_membership_operands(name):
    sql = f"WITH {name}(n) AS (SELECT 7) SELECT n FROM orders WHERE n IN {name}"
    assert fixture_truth(sql) == [(7,)]
    assert _extract_relation_references(sql) == [RelationReference("orders")]
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).allowed
    physical = f"SELECT 7 AS n WHERE 7 IN {name}"
    denied = _validate_sql_query_policy(None, physical, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    allowed = _validate_sql_query_policy(None, physical, ConnectionPolicy(allowed_tables=frozenset({name})))
    assert not denied.allowed and denied.error_code == "table_access_denied"
    assert allowed.allowed


@pytest.mark.parametrize("sql", [
    "WITH data AS (SELECT 7)",
    "WITH data() AS (SELECT 7) SELECT * FROM data",
    "WITH data(n,) AS (SELECT 7) SELECT * FROM data",
    "WITH data(n+1) AS (SELECT 7) SELECT * FROM data",
    "WITH data AS NOT (SELECT 7) SELECT * FROM data",
    "WITH data AS MATERIALIZED SELECT 7 SELECT * FROM data",
    "WITH data AS () SELECT * FROM data",
    "WITH data AS (PRAGMA table_info(orders)) SELECT * FROM data",
    "WITH main.data AS (SELECT 7) SELECT * FROM main.data",
    "WITH data AS (SELECT 7), SELECT 7",
])
def test_incomplete_or_unsupported_with_is_not_guessed_into_a_read(sql):
    for scope in ("all", "allowlist"):
        policy = ConnectionPolicy(read_mode=scope, allowed_tables=frozenset({"*"} if scope == "all" else {"orders"}))
        decision = _validate_sql_query_policy(None, sql, policy)
        assert not decision.allowed and decision.error_code == "sql_parse_failed"
        assert "mutation" not in (decision.hint or "").lower()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("scope", ["all", "allowlist"])
async def test_cte_skill_raw_discovery_details_readiness_and_execution_agree(bundle, tmp_path, mode, scope):
    _, connections, skills, save = bundle
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7);")
    statements = [
        "WITH data AS (SELECT n FROM orders) SELECT n FROM data",
        'WITH "monthly_sales"(n) AS (SELECT n FROM orders) SELECT n FROM "monthly_sales"',
        "WITH base AS /* body */ (SELECT n FROM orders) SELECT n FROM base",
        "WITH replace(n) AS (SELECT n FROM orders) SELECT n FROM replace",
        "WITH data(n) AS MATERIALIZED (SELECT n FROM orders) SELECT n FROM data",
        "WITH like AS (SELECT n FROM orders) SELECT n FROM like",
    ]
    for i, sql in enumerate(statements):
        directory = tmp_path / "skills" / f"cte-{i}"
        directory.mkdir(parents=True)
        (directory / "skill_def.md").write_text(f"---\nname: cte-{i}\ntype: query\nsource: query.sql\nrisk: low\ndescription: CTE structure\nparams: {{}}\n---\n")
        (directory / "query.sql").write_text(sql)
    connections["connections"]["demo"]["read"] = {"mode": scope, "tables": ["orders"] if scope == "allowlist" else []}
    skills["skills"] = {"enabled": True, "directory": str(tmp_path / "skills"), "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path / "audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            for available_only in (False, True):
                listing = (await client.call_tool("list_skills", {"detail_level": "full", "available_only": available_only})).structured_content
                assert {s["name"] for s in listing["skills"]} == {f"cte-{i}" for i in range(len(statements))}
                assert all(s["executable"] and s["tables"] == ["orders"] and s["missing_tables"] == [] for s in listing["skills"])
            for i, sql in enumerate(statements):
                raw = (await client.call_tool("query", {"sql": sql})).structured_content
                detail = (await client.call_tool("get_skill_detail", {"skill_name": f"cte-{i}", "detail_level": "full"})).structured_content
                executed = (await client.call_tool("execute_query_skill", {"skill_name": f"cte-{i}", "params": {}})).structured_content
                assert detail["skill"]["executable"] and detail["skill"]["inferred_tables"] == ["orders"]
                assert raw["data"] == executed["data"] == [{"n": 7}]
    finally:
        server.gateway_runtime.close()
