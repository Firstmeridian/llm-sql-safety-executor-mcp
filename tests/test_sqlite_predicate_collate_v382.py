"""Completed SQLite predicates preserve postfix/operator semantics and read scope."""
import json
import sqlite3

from fastmcp import Client
import pytest
from sqlglot import exp

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import _tokens, analyze_sql
from sql_safety_executor.database.semantics import DialectContext
from tests.test_sqlite_collate_v382 import prepare
from tests.test_v38_config import bundle as bundle

FORMS = ["NULL ISNULL", "7 NOTNULL", "7 NOT NULL", "7 IN (7)", "7 NOT IN (8)"]
POSITIVE = [
    *(f"SELECT {term} COLLATE {collation} AS n"
      for term in FORMS for collation in ("BINARY", "NOCASE", "RTRIM")),
    *(f"SELECT 7 AS n WHERE {term} COLLATE {collation}"
      for term in FORMS for collation in ("BINARY", "NOCASE", "RTRIM")),
    *(f"SELECT ({term}) COLLATE NOCASE AS n" for term in FORMS),
    *(f"SELECT 7 AS n WHERE ({term}) COLLATE NOCASE" for term in FORMS),
    "SELECT 'A' IN ('a') COLLATE NOCASE AS n",
    "SELECT ('A' IN ('a')) COLLATE NOCASE AS n",
    "SELECT 'A' COLLATE NOCASE IN ('a') AS n",
    "SELECT 'A' NOT IN ('a') COLLATE NOCASE AS n",
    "SELECT 7 IN (SELECT 7) COLLATE NOCASE AS n",
    "SELECT 7 IN () COLLATE NOCASE AS n",
    "SELECT (7,8) IN ((7,8)) COLLATE NOCASE AS n",
    "SELECT NULL NOT IN (7,NULL) COLLATE NOCASE AS n",
    "SELECT 7 IN (7) COLLATE NOCASE IN (1) AS n",
    "SELECT 7 NOT IN (8) COLLATE NOCASE NOT IN (0) AS n",
    "SELECT 7 IN (7) COLLATE BINARY COLLATE NOCASE AS n",
    "SELECT NULL ISNULL COLLATE NOCASE + 1 * 2 AS n",
    "SELECT 7 NOTNULL + 1 AS n",
    "SELECT 7 NOT NULL * 2 AS n",
    "SELECT 7 IN (7) + 1 AS n",
    "SELECT 7 NOT IN (8) * 2 AS n",
    "SELECT 7 IN (7) COLLATE NOCASE * 2 + 1 << 1 AS n",
    "SELECT 7 IN (7) COLLATE NOCASE || 2 AS n",
    "SELECT 7 IN (7) COLLATE NOCASE -> '$' AS n",
    "SELECT 7 IN (7) COLLATE NOCASE ->> '$' AS n",
    "SELECT NULL ISNULL COLLATE NOCASE + 1 IN (2) AS n",
    "SELECT id IN audit_log COLLATE NOCASE AS n FROM orders ORDER BY id",
    "WITH chosen AS (SELECT n FROM orders) SELECT id AS n FROM orders WHERE n IN chosen COLLATE NOCASE ORDER BY id",
    "SELECT id AS n FROM orders WHERE n ISNULL COLLATE NOCASE OR n NOT IN (7) COLLATE BINARY ORDER BY id",
    "SELECT CASE WHEN n NOTNULL COLLATE NOCASE THEN 1 ELSE 0 END AS n FROM orders ORDER BY id",
    # The upstream SQL generator can omit grouping here. Production executes
    # the original SQL; verify these existing accepted forms independently.
    "SELECT 7 NOTNULL IN (0,1,2) AS n",
    "SELECT 7 NOTNULL NOTNULL AS n",
    "SELECT NULL NOTNULL IN (0,1,2) AS n",
    "SELECT NULL NOTNULL NOTNULL AS n",
    "SELECT 7 NOT NULL NOTNULL AS n",
    "SELECT NULL NOT NULL NOTNULL AS n",
    "SELECT 7 NOT IN (8) NOTNULL AS n",
]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("sql", POSITIVE)
async def test_predicate_collate_reads_match_native(bundle, tmp_path, mode, sql):
    save = prepare(bundle, tmp_path)
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.row_factory = sqlite3.Row
        expected = [dict(r) for r in db.execute(sql)]
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            response = await client.call_tool("query", {"sql": sql})
            body = response.structured_content
            assert body["success"], body
            assert body["data"] == expected and body["query"] == sql
            assert json.loads(response.content[0].text) == body
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("term", FORMS + ["7 IN (SELECT 7)", "(7,8) IN ((7,8))"])
def test_collate_wraps_complete_predicate(term):
    sql = f"SELECT {term} COLLATE NOCASE AS n"
    dialect, tokens = _tokens(sql, DialectContext("sqlite"))
    tree = dialect.parser().parse(tokens, sql)[0]
    expression = tree.expressions[0].this
    assert isinstance(expression, exp.Collate)
    assert isinstance(expression.this.unnest(), (exp.In, exp.Is, exp.Not))
    assert expression.expression.name.upper() == "NOCASE"
    assert analyze_sql(sql, DialectContext("sqlite")).complete


def test_predicate_tail_precedence_and_right_operand_collation():
    sql = "SELECT 7 IN (7) COLLATE NOCASE + 2 * 3 AS n"
    dialect, tokens = _tokens(sql, DialectContext("sqlite"))
    value = dialect.parser().parse(tokens, sql)[0].expressions[0].this
    assert isinstance(value, exp.Add) and isinstance(value.this, exp.Collate)
    assert isinstance(value.this.this.unnest(), exp.In) and isinstance(value.expression, exp.Mul)
    sql = "SELECT 7 IN (7) COLLATE NOCASE || 'A' COLLATE RTRIM AS n"
    dialect, tokens = _tokens(sql, DialectContext("sqlite"))
    value = dialect.parser().parse(tokens, sql)[0].expressions[0].this
    assert isinstance(value, exp.DPipe)
    assert isinstance(value.this, exp.Collate) and isinstance(value.expression, exp.Collate)


NEGATIVE = [
    ("SELECT n FROM hidden WHERE n IN (7) COLLATE NOCASE", "table_access_denied"),
    ("SELECT n IN (SELECT n FROM hidden) COLLATE NOCASE FROM orders", "table_access_denied"),
    ("SELECT n IN hidden COLLATE NOCASE FROM orders", "table_access_denied"),
    ("SELECT n FROM orders WHERE n IN (7) COLLATE NOCASE + (SELECT n FROM hidden)", "table_access_denied"),
    ("SELECT n FROM orders WHERE n NOTNULL COLLATE NOCASE + SLEEP(0)", "expensive_function_denied"),
    ("SELECT n FROM orders WHERE n IN (7) COLLATE NOCASE AND SLEEP(0)=0", "expensive_function_denied"),
    ("SELECT n FROM orders WHERE n IN (7) COLLATE NOCASE + GET_LOCK('fixture',0)", "lock_function_denied"),
    ("SELECT n FROM orders WHERE n IN (7) COLLATE NOCASE + CURRENT_USER()", "server_state_denied"),
    ("SELECT n FROM orders WHERE n IN (7) COLLATE NOCASE + load_file('fixture')", "file_operation_denied"),
    ("UPDATE orders SET n=99 WHERE n IN (7) COLLATE NOCASE", "read_only_required"),
    ("SELECT 7 IN (7) COLLATE", "sql_parse_failed"),
    ("SELECT 7 IN (7) COLLATE NOCASE +", "sql_parse_failed"),
    ("SELECT 7 IN (7) COLLATE NOCASE; DELETE FROM orders", "multiple_statements"),
]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("sql,code", NEGATIVE)
async def test_predicate_tail_preserves_refusals_and_state(bundle, tmp_path, mode, sql, code):
    save = prepare(bundle, tmp_path)
    server = create_server(load_config(save()))
    calls = []
    try:
        adapter = server.gateway_runtime.registry.get_adapter("demo")
        assert adapter.connect()
        with adapter._engine.connect() as connection:
            db = connection.connection.dbapi_connection
            db.create_function("SLEEP", 1, lambda *_: calls.append("sleep") or 0)
            db.create_function("GET_LOCK", 2, lambda *_: calls.append("lock") or 0)
        before = adapter.execute("SELECT * FROM orders ORDER BY id")
        async with Client(server, mode=mode) as client:
            result = (await client.call_tool("query", {"sql": sql})).structured_content
            assert not result["success"] and result["error_code"] == code, result
        assert not calls and adapter.execute("SELECT * FROM orders ORDER BY id") == before
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_predicate_skills_discovery_readiness_bindings(bundle, tmp_path, mode):
    save = prepare(bundle, tmp_path)
    _, _, skills, _ = bundle
    sqls = {
        "isnull-direct": "SELECT id AS n FROM orders WHERE n ISNULL COLLATE NOCASE ORDER BY id",
        "notnull-direct": "SELECT id AS n FROM orders WHERE n NOTNULL COLLATE NOCASE ORDER BY id",
        "not-null-direct": "SELECT id AS n FROM orders WHERE n NOT NULL COLLATE NOCASE ORDER BY id",
        "in-direct": "SELECT id AS n FROM orders WHERE n IN (:value) COLLATE NOCASE ORDER BY id",
        "not-in-direct": "SELECT id AS n FROM orders WHERE n NOT IN (:value) COLLATE NOCASE ORDER BY id",
    }
    for name, sql in sqls.items():
        folder = tmp_path / "skills" / name
        folder.mkdir(parents=True)
        params = "params:\n  value:\n    type: int\n    required: true\n" if ":value" in sql else "params: {}\n"
        (folder / "skill_def.md").write_text(f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private complete predicate\n{params}---\n")
        (folder / "query.sql").write_text(sql)
    skills["skills"]["directory"] = str(tmp_path / "skills")
    skills["skills"]["readiness"] = {"check_schema": True}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            found = (await client.call_tool("list_skills", {"detail_level": "full"})).structured_content
            assert {s["name"] for s in found["skills"]} == set(sqls)
            for name, sql in sqls.items():
                detail = (await client.call_tool("get_skill_detail", {"skill_name": name, "detail_level": "full"})).structured_content
                assert detail["skill"]["analysis_complete"] and detail["skill"]["schema_ready"]
                assert detail["skill"]["inferred_tables"] == ["orders"]
                for value in [0,7]:
                    params = {"value": value} if ":value" in sql else {}
                    with sqlite3.connect(tmp_path / "db.sqlite") as db:
                        db.row_factory = sqlite3.Row
                        expected = [dict(r) for r in db.execute(sql, params)]
                    result = (await client.call_tool("execute_query_skill", {"skill_name": name, "params": params})).structured_content
                    assert result["success"] and result["data"] == expected, result
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("value", [None, 0, 7, 99])
def test_predicate_nullable_binding(bundle, tmp_path, value):
    save = prepare(bundle, tmp_path)
    sql = "SELECT id AS n FROM orders WHERE n IN (:value) COLLATE NOCASE ORDER BY id"
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        expected = db.execute(sql, {"value": value}).fetchall()
    server = create_server(load_config(save()))
    try:
        adapter = server.gateway_runtime.registry.get_adapter("demo")
        policy = server.gateway_runtime.registry.get_config("demo").policy
        assert [tuple(row) for row in adapter.execute_read(sql,params={"value":value},policy=policy)] == expected
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto","legacy"])
async def test_predicate_view_preserves_indirect_base_scope(bundle,tmp_path,mode):
    save = prepare(bundle,tmp_path,grants=("approved",),
        extra="CREATE VIEW approved AS SELECT id FROM orders WHERE n IN (7) COLLATE NOCASE;")
    server = create_server(load_config(save()))
    try:
        async with Client(server,mode=mode) as client:
            result = (await client.call_tool("query",{"sql":"SELECT id AS n FROM approved"})).structured_content
            assert result["success"] and result["data"] == [{"n":2}],result
            denied = (await client.call_tool("query",{"sql":"SELECT * FROM orders"})).structured_content
            assert denied["error_code"]=="table_access_denied"
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto","legacy"])
@pytest.mark.parametrize("prefix", ["EXPLAIN","EXPLAIN QUERY PLAN"])
async def test_predicate_trigger_when_nonexecuting_plan(bundle,tmp_path,mode,prefix):
    save = prepare(bundle,tmp_path,extra="CREATE TRIGGER log_orders AFTER INSERT ON orders "
        "WHEN NEW.n IN (7) COLLATE NOCASE BEGIN INSERT INTO audit_log VALUES(NEW.id); END;")
    sql = prefix+" INSERT INTO orders VALUES(99,7,'test')"
    with sqlite3.connect(tmp_path/"db.sqlite") as db:
        db.execute(sql).fetchall()
    server = create_server(load_config(save()))
    try:
        async with Client(server,mode=mode) as client:
            result=(await client.call_tool("query",{"sql":sql})).structured_content
            assert result["success"],result
        adapter=server.gateway_runtime.registry.get_adapter("demo")
        assert adapter.execute("SELECT COUNT(*) FROM orders")==[(3,)]
        assert adapter.execute("SELECT * FROM audit_log")==[]
    finally:
        server.gateway_runtime.close()
