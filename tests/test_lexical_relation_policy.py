"""Native SQL truth for contextual names, lexer folding and reserved calls."""
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import _extract_relation_references, _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle
from tests.test_query_skill_static_policy import policy_server as policy_server


NAMES = ("window", "offset", "lock", "lımıt", "offſet", "wındow",
         "unıon", "ınsert", "deſcribe", "ſhow", "ſelect")


@pytest.mark.parametrize("name", ["lımıt", "unıon"])
def test_split_where_membership_preserves_authorized_and_unauthorized_identity(name):
    sql = f"SELECT 7 AS n WHERE 7 IN {name}"
    quoted = f'SELECT 7 AS n WHERE 7 IN "{name}"'
    with sqlite3.connect(":memory:") as db:
        db.executescript(f'CREATE TABLE "{name}"(n);INSERT INTO "{name}" VALUES(7);')
        assert db.execute(sql).fetchall() == db.execute(quoted).fetchall() == [(7,)]
    policy = ConnectionPolicy(allowed_tables=frozenset({name}))
    # The optional WHERE group can stop before this operand. Shared block
    # analysis must retain the name and authorize it, not report empty scope.
    assert _validate_sql_query_policy(None, sql, policy).allowed
    assert _validate_sql_query_policy(None, quoted, policy).allowed
    denied = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    assert not denied.allowed and denied.error_code == "table_access_denied"


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("shape", ["from", "join", "comma", "in", "qualified"])
def test_contextual_and_unicode_targets_never_disappear_from_authorization(name, shape):
    queries = {
        "from": f"SELECT n FROM {name}",
        "join": f"SELECT n FROM orders JOIN {name} USING(n)",
        "comma": f"SELECT t.n FROM orders, {name} AS t",
        "in": f'SELECT 7 AS n WHERE 7 IN "{name}"',
        "qualified": f'SELECT n FROM main."{name}"',
    }
    sql = queries[shape]
    with sqlite3.connect(":memory:") as db:
        db.executescript(f'CREATE TABLE orders(n);INSERT INTO orders VALUES(7);'
                         f'CREATE TABLE "{name}"(n);INSERT INTO "{name}" VALUES(7);')
        assert db.execute(sql).fetchall() == [(7,)]
    references = _extract_relation_references(sql)
    assert any(r.name == name for r in references)
    denied = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    assert not denied.allowed and denied.error_code == "table_access_denied"
    allowed = _validate_sql_query_policy(None, sql, ConnectionPolicy(
        allowed_tables=frozenset({"orders", name, f"main.{name}"})))
    assert allowed.allowed


@pytest.mark.parametrize("name", ["load_fıle", "uſer", "ſleep", "benchmarK"])
@pytest.mark.parametrize("quote", ["{}", '"{}"', "`{}`", "[{}]"])
def test_unicode_function_identity_matches_native_business_udf(name, quote):
    sql = f"SELECT {quote.format(name)}(1)"
    with sqlite3.connect(":memory:") as db:
        db.create_function(name, 1, lambda _: 7)
        assert db.execute(sql).fetchall() == [(7,)]
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}))).allowed


@pytest.mark.parametrize("name", ["load_file", "user", "current_user", "session_user", "system_user", "current_role"])
@pytest.mark.parametrize("quote", ["{}", '"{}"', "`{}`", "[{}]"])
def test_actual_reserved_calls_deny_all_standard_identifier_quotes(name, quote):
    sql = f"SELECT {quote.format(name)}(1)"
    # Harmless stand-ins establish call syntax, without touching server/file state.
    with sqlite3.connect(":memory:") as db:
        db.create_function(name, 1, lambda _: 7)
        assert db.execute(sql).fetchall() == [(7,)]
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"})))
    expected = "file_operation_denied" if name == "load_file" else "server_state_denied"
    assert not decision.allowed and decision.error_code == expected


@pytest.mark.parametrize("sql", [
    "SELECT 'LOAD_FILE(1), USER(1)' AS n",
    'SELECT "current_user" AS n FROM orders',
    "WITH load_file(n) AS (SELECT 7) SELECT n FROM load_file",
    "WITH user(n) AS (SELECT 7) SELECT n FROM user",
])
def test_reserved_call_recognition_preserves_literals_columns_and_cte_headers(sql):
    with sqlite3.connect(":memory:") as db:
        db.executescript("CREATE TABLE orders(current_user);INSERT INTO orders VALUES(7);")
        assert db.execute(sql).fetchall()
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}))).allowed


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("admitted", [False, True])
async def test_lexical_names_share_raw_discovery_detail_readiness_execution(bundle, tmp_path, monkeypatch, mode, admitted):
    _, connections, skills, save = bundle
    names = ("window", "offſet", "unıon", "ınsert")
    with sqlite3.connect(tmp_path/"db.sqlite") as db:
        for name in ("orders", *names):
            db.execute(f'CREATE TABLE "{name}"(n)')
            db.execute(f'INSERT INTO "{name}" VALUES(7)')
    for i, name in enumerate(names):
        directory = tmp_path/"skills"/f"lexical-{i}"
        directory.mkdir(parents=True)
        (directory/"skill_def.md").write_text(f"---\nname: lexical-{i}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Lexical scope\nparams: {{}}\n---\n")
        (directory/"query.sql").write_text(f"SELECT n FROM {name}")
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["orders", *names] if admitted else ["orders"]}
    skills["skills"] = {"enabled": True, "directory": str(tmp_path/"skills"),
                        "readiness": {"check_schema": True}, "audit": {"path": str(tmp_path/"audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            all_skills = await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})
            default_skills = await client.call_tool("list_skills", {"detail_level": "full"})
            assert len(all_skills.structured_content["skills"]) == 4
            assert len(default_skills.structured_content["skills"]) == (4 if admitted else 0)
            for i, name in enumerate(names):
                detail = await client.call_tool("get_skill_detail", {"skill_name": f"lexical-{i}", "detail_level": "full"})
                with monkeypatch.context() as denied_io:
                    if not admitted:
                        def unexpected_io(*args, **kwargs):
                            pytest.fail("Unapproved relation execution reached database I/O")
                        adapter = server.gateway_runtime.registry.get_adapter("demo")
                        for method in ("execute", "connect", "get_read_relations"):
                            denied_io.setattr(adapter, method, unexpected_io)
                    raw = await client.call_tool("query", {"sql": f"SELECT n FROM {name}"})
                    executed = await client.call_tool("execute_query_skill", {"skill_name": f"lexical-{i}", "params": {}})
                for r in (raw, executed):
                    assert not r.is_error and r.structured_content["success"] is admitted
                    if admitted:
                        assert r.structured_content["data"] == [{"n": 7}]
                    else:
                        assert r.structured_content["error_code"] == "table_access_denied"
                state = detail.structured_content["skill"]
                assert state["policy_allowed"] is admitted
                assert state["schema_ready"] is True
                assert state["executable"] is admitted
                assert state["inferred_tables"] == [name]
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_quoted_reserved_calls_remain_denied_for_cached_skill_before_io(policy_server, monkeypatch, mode):
    server = policy_server("SELECT 7 AS value", {"mode": "all"}, {"mode": "all"})
    def unexpected_io(*args, **kwargs):
        pytest.fail("Reserved call reached database I/O")
    for alias in ("denied", "allowed"):
        adapter = server.gateway_runtime.registry.get_adapter(alias)
        for method in ("execute", "connect", "get_read_relations"):
            monkeypatch.setattr(adapter, method, unexpected_io)
    async with Client(server, mode=mode) as client:
        for sql, code in [('SELECT "load_file"(1)', "file_operation_denied"),
                          ('SELECT [user](1)', "server_state_denied")]:
            server.gateway_runtime.catalog.get_skills_cache()["static-policy-probe"]._sql_template = sql
            for tool, args in [("query", {"sql": sql}), ("execute_query_skill", {"skill_name": "static-policy-probe", "params": {}})]:
                r = await client.call_tool(tool, {**args, "connection_id": "allowed"}, raise_on_error=False)
                assert not r.is_error and r.structured_content["error_code"] == code
