"""Native quoted identities must survive policy and Skill dependency analysis."""
import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import (
    _extract_tables_from_sql, _normalize_sql_for_policy, _validate_sql_query_policy,
)
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle


def quote_name(name, delimiter='"'):
    return delimiter + name.replace(delimiter, delimiter * 2) + delimiter


@pytest.mark.parametrize("delimiter", ['"', '`'])
@pytest.mark.parametrize("name,other", [
    ("  f  ", " f "), ("a  b", "a b"), ("\tf\t", " f "),
    ("f\nx", "f x"), ("[f]", "f"), ("`f`", "f"),
    ('a"b', 'a""b'), ('a`b', 'a``b'), ("'f'", "f"),
])
def test_native_quoted_names_are_decoded_once(name, other, delimiter):
    quoted, shadow = quote_name(name, delimiter), quote_name(other, delimiter)
    with sqlite3.connect(":memory:") as conn:
        conn.execute(f"CREATE TABLE {quoted}(id INTEGER)")
        conn.execute(f"INSERT INTO {quoted} VALUES(999)")
        sql = f"WITH {shadow} AS (SELECT 7 AS id) SELECT id FROM {quoted}"
        assert conn.execute(sql).fetchall() == [(999,)]
        assert _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=False) == [name]
        denied = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({other})))
        assert not denied.allowed and denied.error_code == "table_access_denied"
        assert _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({name}))).allowed
        qualified = f"SELECT id FROM main.{quoted}"
        assert conn.execute(qualified).fetchall() == [(999,)]
        assert _extract_tables_from_sql(qualified, case_sensitive=True) == [f"main.{name}"]
        same_cte = f"WITH {quoted} AS (SELECT 7 AS id) SELECT id FROM {quoted}"
        assert conn.execute(same_cte).fetchall() == [(7,)]
        assert _extract_tables_from_sql(same_cte, case_sensitive=True, cte_case_sensitive=False) == []


def test_normalization_preserves_literal_and_identifier_whitespace():
    sql = 'SELECT\t\'a  b\tc\nd\' AS label FROM\n"  f  " -- ordinary comment\n'
    normalized = _normalize_sql_for_policy(sql)
    assert "'a  b\tc\nd'" in normalized and '"  f  "' in normalized
    assert "ordinary comment" not in normalized


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,other", [("  f  ", " f "), ("[f]", "f"), ('a"b', 'a""b')])
async def test_raw_skill_discovery_and_execution_preserve_identity(bundle, tmp_path, mode, name, other):
    _, connections, skills, save = bundle
    quoted, shadow = quote_name(name), quote_name(other)
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        conn.execute(f"CREATE TABLE {quoted}(id INTEGER)")
        conn.execute(f"INSERT INTO {quoted} VALUES(999)")
    directory = tmp_path / "skills" / "identity-probe"
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        '---\nname: identity-probe\ntype: query\nsource: query.sql\nrisk: low\n'
        'description: Quoted identity regression\nparams: {}\n---\n')
    sql = f"WITH {shadow} AS (SELECT 7 AS id) SELECT id FROM {quoted}"
    (directory / "query.sql").write_text(sql)
    skills["skills"] = {"enabled": True, "directory": str(directory.parent),
                        "readiness": {"check_schema": True},
                        "audit": {"path": str(tmp_path / "audit.jsonl")}}
    for grant, allowed in [(other, False), (name, True)]:
        connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": [grant]}
        server = create_server(load_config(save(use_skills=True)))
        try:
            async with Client(server, mode=mode) as client:
                raw = (await client.call_tool("query", {"sql": sql})).structured_content
                listed = (await client.call_tool("list_skills", {"detail_level": "full", "available_only": False})).structured_content
                row = listed["skills"][0]
                assert row["tables"] == row["inferred_tables"] == [name]
                assert row["declared_tables"] == [] and row["schema_ready"] is True
                assert row["policy_allowed"] is allowed and row["executable"] is allowed
                executed = (await client.call_tool("execute_query_skill", {"skill_name": "identity-probe", "params": {}})).structured_content
                assert raw["success"] is executed["success"] is allowed
                if allowed:
                    assert raw["data"] == executed["data"] == [{"id": 999}]
                else:
                    assert raw["error_code"] == executed["error_code"] == "table_access_denied"
        finally:
            server.gateway_runtime.close()
