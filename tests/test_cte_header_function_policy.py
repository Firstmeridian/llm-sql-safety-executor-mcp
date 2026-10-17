"""A declaration exclusion must never hide calls inside a CTE query body."""
import sqlite3
from types import SimpleNamespace

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle
from tests.test_query_skill_static_policy import policy_server as policy_server

CALLS = [
    ("SLEEP(0)", "expensive_function_denied"),
    ("BENCHMARK(0,1)", "expensive_function_denied"),
    ("GET_LOCK('fixture',0)", "lock_function_denied"),
    ("RELEASE_LOCK('fixture')", "lock_function_denied"),
    ("RELEASE_ALL_LOCKS()", "lock_function_denied"),
    ("LOAD_FILE(NULL)", "file_operation_denied"),
    ("USER()", "server_state_denied"),
    ("CURRENT_USER()", "server_state_denied"),
    ("SESSION_USER()", "server_state_denied"),
    ("SYSTEM_USER()", "server_state_denied"),
    ("CURRENT_ROLE()", "server_state_denied"),
]
QUOTES = ["{}", '"{}"', "`{}`", "[{}]"]


def native_truth(sql, call=None):
    with sqlite3.connect(":memory:") as db:
        if call:
            db.create_function(call.split("(")[0], -1, lambda *args: 7)
        assert db.execute(sql).fetchall() == [(7,)]


@pytest.mark.parametrize("call,code", CALLS)
@pytest.mark.parametrize("quote", QUOTES)
@pytest.mark.parametrize("all_scope", [False, True])
def test_cte_body_calls_rejected_for_each_header_quote_and_scope(call, code, quote, all_scope):
    name = quote.format("x")
    sql = f"WITH {name}(n) AS (SELECT {call}) SELECT n FROM {name}"
    native_truth(sql, call)
    def unexpected_probe():
        pytest.fail("Denied CTE call reached connection capability I/O")
    adapter = SimpleNamespace(analysis_context=DialectContext("sqlite"), cte_case_sensitive=None, resolve_cte_case_sensitive=unexpected_probe)
    policy = ConnectionPolicy(
        read_mode="all" if all_scope else "allowlist",
        allowed_tables=frozenset({"*"} if all_scope else {"orders"}),
        case_sensitive_tables=True,
    )
    decision = _validate_sql_query_policy(None, sql, policy, adapter=adapter)
    assert not decision.allowed and decision.error_code == code


@pytest.mark.parametrize("name", ["SLEEP", "USER", "LOAD_FILE", "BENCHMARK"])
@pytest.mark.parametrize("quote", QUOTES)
def test_reserved_spelling_in_cte_declaration_is_not_a_call(name, quote):
    target = quote.format(name)
    sql = f"WITH {target}(n) AS (SELECT 7) SELECT n FROM {target}"
    native_truth(sql)
    assert _validate_sql_query_policy(None, sql, ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"}))).allowed


@pytest.mark.parametrize("call,code", [CALLS[i] for i in (0, 2, 5, 6)])
@pytest.mark.parametrize("shape", ["later", "first", "scalar", "nested", "quoted_call"])
def test_cte_body_calls_remain_visible_across_nested_groups(call, code, shape):
    quoted_call = '"'+call.split("(")[0]+'"('+call.split("(", 1)[1]
    sql = {
        "later": f'WITH safe AS (SELECT 7), "x"(n) AS (SELECT {call}) SELECT n FROM "x"',
        "first": f'WITH "x"(n) AS (SELECT {call}), later AS (SELECT n FROM "x") SELECT n FROM later',
        "scalar": f'WITH "x"(n) AS (SELECT (SELECT {call})) SELECT n FROM "x"',
        "nested": f'WITH outer_cte AS (WITH "x"(n) AS (SELECT {call}) SELECT n FROM "x") SELECT n FROM outer_cte',
        "quoted_call": f'WITH "x"(n) AS (SELECT {quoted_call}) SELECT n FROM "x"',
    }[shape]
    native_truth(sql, call)
    decision = _validate_sql_query_policy(None, sql, ConnectionPolicy(
        read_mode="all", allowed_tables=frozenset({"*"})))
    assert not decision.allowed and decision.error_code == code


@pytest.mark.parametrize("call,code", [CALLS[i] for i in (0, 2, 5, 6)])
def test_unsafe_quoted_header_skill_is_quarantined_offline(policy_server, call, code):
    sql = f'WITH "x"(n) AS (SELECT {call}) SELECT n FROM "x"'
    server = policy_server(sql, {"mode": "all"}, {"mode": "all"})
    assert server.gateway_runtime.catalog.get_skills_cache() == {}
    for alias in ("denied", "allowed"):
        assert server.gateway_runtime.registry.get_adapter(alias)._engine is None


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("readiness", [False, True])
async def test_cached_cte_body_revalidation_denies_before_adapter_io(bundle, tmp_path, monkeypatch, mode, readiness):
    _, connections, skills, save = bundle
    directory = tmp_path/"skills"/"cte-body"
    directory.mkdir(parents=True)
    (directory/"skill_def.md").write_text(
        "---\nname: cte-body\ntype: query\nsource: query.sql\nrisk: low\ndescription: Cached CTE body\nparams: {}\n---\n")
    (directory/"query.sql").write_text("SELECT 7 AS n")
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
                        "readiness": {"check_schema": readiness},
                        "audit": {"path": str(tmp_path/"audit.jsonl")}}
    server = create_server(load_config(save(use_skills=True)))
    try:
        def unexpected_io(*args, **kwargs):
            pytest.fail("Denied CTE body reached database I/O")
        adapter = server.gateway_runtime.registry.get_adapter("demo")
        for method in ("execute", "connect", "get_read_relations"):
            monkeypatch.setattr(adapter, method, unexpected_io)
        async with Client(server, mode=mode) as client:
            for call, code in [CALLS[i] for i in (0, 2, 5, 6)]:
                sql = f'WITH "x"(n) AS (SELECT {call}) SELECT n FROM "x"'
                server.gateway_runtime.catalog.get_skills_cache()["cte-body"]._sql_template = sql
                for tool, args in [("query", {"sql": sql}), ("execute_query_skill", {"skill_name": "cte-body", "params": {}})]:
                    result = await client.call_tool(tool, args, raise_on_error=False)
                    assert not result.is_error and result.structured_content["error_code"] == code
    finally:
        server.gateway_runtime.close()
