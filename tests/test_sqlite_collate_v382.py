"""SQLite IS operands retain COLLATE precedence, dependencies and bindings."""
import json
import sqlite3

from fastmcp import Client
import pytest
from sqlglot import exp

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import _tokens, analyze_sql
from sql_safety_executor.database.semantics import DialectContext
from tests.test_v38_config import bundle as bundle


BASE = ("CREATE TABLE orders(id INTEGER PRIMARY KEY,n,label);"
        "INSERT INTO orders VALUES(1,NULL,'A'),(2,7,'a'),(3,0,NULL);"
        "CREATE TABLE hidden(n); INSERT INTO hidden VALUES(99);"
        "CREATE TABLE audit_log(n);")

POSITIVE = [
    *[f'SELECT NULL {op} NULL COLLATE {collation} AS n'
      for op in ('IS', 'IS NOT') for collation in ('BINARY', 'NOCASE', 'RTRIM')],
    'SELECT 7 AS n WHERE NULL IS NULL COLLATE NOCASE;',
    'SELECT 7 AS n WHERE 0 IS NOT NULL COLLATE NOCASE;',
    'SELECT 7 AS n WHERE (NULL IS NULL) COLLATE NOCASE;',
    'SELECT 7 AS n WHERE NULL IS (NULL COLLATE NOCASE);',
    "SELECT 'A' IS 'a' COLLATE NOCASE AS n",
    "SELECT ('A' IS 'a') COLLATE NOCASE AS n",
    "SELECT 'a ' IS 'a' COLLATE RTRIM AS n",
    'SELECT id AS n FROM orders WHERE n IS NULL COLLATE NOCASE ORDER BY id',
    'SELECT id AS n FROM orders WHERE n IS NOT NULL COLLATE BINARY ORDER BY id',
    'SELECT CASE WHEN n IS NULL COLLATE NOCASE THEN 1 ELSE 0 END AS n FROM orders ORDER BY id',
    'SELECT NULL IS /* rhs */ NULL COLLATE "NOCASE" AS n',
    'SELECT NULL IS NOT NULL COLLATE NOCASE OR 1 AND 0 AS n',
    'SELECT 1 IS TRUE AS n',
    'SELECT NULL IS NOT DISTINCT FROM NULL COLLATE NOCASE AS n',
    'WITH chosen AS (SELECT id FROM orders WHERE n IS NULL COLLATE NOCASE) SELECT id AS n FROM chosen',
    'SELECT NULL IS NULL COLLATE NOCASE + (SELECT COUNT(*) FROM orders) AS n',
    "SELECT 'a' LIKE 'a' ESCAPE NULL COLLATE NOCASE AS n",
    "SELECT 'a' LIKE 'a' ESCAPE 'x' COLLATE BINARY AS n",
    "SELECT 'a_' LIKE 'ax_' ESCAPE 'x' COLLATE NOCASE AS n",
    "SELECT id AS n FROM orders WHERE label LIKE 'A' ESCAPE 'x' COLLATE RTRIM ORDER BY id",
]


def prepare(bundle, tmp_path, *, grants=('orders', 'audit_log'), extra=''):
    _, connections, _, save = bundle
    connections['connections']['demo']['read'] = {'mode': 'allowlist', 'tables': list(grants)}
    with sqlite3.connect(tmp_path / 'db.sqlite') as native:
        native.executescript(BASE + extra)
    return save


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('sql', POSITIVE)
async def test_collate_reads_match_native_sqlite(bundle, tmp_path, mode, sql):
    save = prepare(bundle, tmp_path)
    with sqlite3.connect(tmp_path / 'db.sqlite') as native:
        native.row_factory = sqlite3.Row
        expected = [dict(row) for row in native.execute(sql)]
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            response = await client.call_tool('query', {'sql': sql})
            result = response.structured_content
            assert result['success'], result
            assert result['data'] == expected
            assert result['query'] == sql
            assert json.loads(next(c.text for c in response.content if c.type == 'text')) == result
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('rhs', ['NULL', ':value'])
@pytest.mark.parametrize('op', ['IS', 'IS NOT'])
def test_collate_binds_to_right_operand_in_analysis_tree(rhs, op):
    sql = f'SELECT label {op} {rhs} COLLATE NOCASE AS n FROM orders'
    dialect, tokens = _tokens(sql, DialectContext('sqlite'))
    trees = dialect.parser().parse(tokens, sql)
    assert len(trees) == 1 and trees[0] is not None
    expression = trees[0].expressions[0].this
    if isinstance(expression, exp.Not):
        expression = expression.this
    assert isinstance(expression, exp.Is)
    assert isinstance(expression.expression, exp.Collate)
    assert isinstance(expression.expression.this, exp.Null if rhs == 'NULL' else exp.Placeholder)
    analysis = analyze_sql(sql, DialectContext('sqlite'))
    assert analysis.complete and analysis.source_sql == sql
    assert analysis.parameters == (frozenset() if rhs == 'NULL' else frozenset({'value'}))


NEGATIVE = [
    ('SELECT n FROM hidden WHERE n IS NULL COLLATE NOCASE', 'table_access_denied'),
    ('SELECT NULL IS NULL COLLATE NOCASE + (SELECT n FROM hidden) AS n', 'table_access_denied'),
    ('SELECT id FROM orders WHERE n IS NULL COLLATE NOCASE AND SLEEP(0)=0', 'expensive_function_denied'),
    ("SELECT id FROM orders WHERE n IS NOT NULL COLLATE NOCASE OR GET_LOCK('fixture',0)=1", 'lock_function_denied'),
    ('SELECT NULL IS NULL COLLATE NOCASE AND CURRENT_USER()', 'server_state_denied'),
    ("SELECT NULL IS NULL COLLATE NOCASE AND load_file('fixture')", 'file_operation_denied'),
    ('UPDATE orders SET n=99 WHERE n IS NULL COLLATE NOCASE', 'read_only_required'),
    ('SELECT NULL IS NULL COLLATE', 'sql_parse_failed'),
    ('SELECT NULL IS NOT COLLATE NOCASE', 'sql_syntax_error'),
    ('SELECT NULL IS NULL COLLATE NOCASE; DELETE FROM orders', 'multiple_statements'),
    ("SELECT id FROM orders WHERE label LIKE 'A' ESCAPE (SELECT n FROM hidden) COLLATE NOCASE", 'table_access_denied'),
    ("SELECT id FROM orders WHERE label LIKE 'A' ESCAPE SLEEP(0) COLLATE NOCASE", 'expensive_function_denied'),
    ("SELECT id FROM orders WHERE label LIKE 'A' ESCAPE", 'sql_parse_failed'),
]


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('sql,code', NEGATIVE)
async def test_collate_does_not_hide_reads_calls_or_writes(bundle, tmp_path, mode, sql, code):
    save = prepare(bundle, tmp_path)
    server = create_server(load_config(save()))
    calls = []
    try:
        async with Client(server, mode=mode) as client:
            adapter = server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.connect()
            with adapter._engine.connect() as connection:
                connection.connection.dbapi_connection.create_function('SLEEP', 1, lambda _: calls.append(1) or 0)
                connection.connection.dbapi_connection.create_function('GET_LOCK', 2, lambda *_: calls.append(1) or 0)
            before = adapter.execute('SELECT * FROM orders ORDER BY id')
            result = (await client.call_tool('query', {'sql': sql})).structured_content
            assert result['success'] is False and result['error_code'] == code, result
            assert not calls
            assert adapter.execute('SELECT * FROM orders ORDER BY id') == before
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_collate_skill_discovery_readiness_and_parameter_values(bundle, tmp_path, mode):
    save = prepare(bundle, tmp_path)
    _, _, skills, _ = bundle
    directory = tmp_path / 'skills'
    skill = directory / 'collate-report'
    skill.mkdir(parents=True)
    (skill / 'skill_def.md').write_text('---\nname: collate-report\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private parameter collation\nparams:\n  value:\n    type: str\n    required: true\n---\n')
    sql = 'SELECT id AS n FROM orders WHERE label IS :value COLLATE NOCASE OR n IS NULL COLLATE BINARY ORDER BY id'
    (skill / 'query.sql').write_text(sql)
    skills['skills']['directory'] = str(directory)
    skills['skills']['readiness'] = {'check_schema': True}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            found = (await client.call_tool('list_skills', {'detail_level': 'full'})).structured_content
            assert len(found['skills']) == 1 and found['skills'][0]['executable'], found
            detail = (await client.call_tool('get_skill_detail', {'skill_name': 'collate-report', 'detail_level': 'full'})).structured_content
            assert detail['skill']['schema_ready'] and detail['skill']['analysis_complete']
            assert detail['skill']['inferred_tables'] == ['orders']
            for value in ['a', 'A', 'unknown']:
                with sqlite3.connect(tmp_path / 'db.sqlite') as native:
                    native.row_factory = sqlite3.Row
                    expected = [dict(row) for row in native.execute(sql, {'value': value})]
                result = (await client.call_tool('execute_query_skill', {'skill_name': 'collate-report', 'params': {'value': value}})).structured_content
                assert result['success'] and result['data'] == expected, result
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('value', [None, 'A', 'a', 'unknown'])
def test_collate_nullable_bound_operands_match_native(bundle, tmp_path, value):
    save = prepare(bundle, tmp_path)
    sql = 'SELECT id AS n FROM orders WHERE label IS :value COLLATE NOCASE ORDER BY id'
    with sqlite3.connect(tmp_path / 'db.sqlite') as native:
        expected = native.execute(sql, {'value': value}).fetchall()
    server = create_server(load_config(save()))
    try:
        adapter = server.gateway_runtime.registry.get_adapter('demo')
        policy = server.gateway_runtime.registry.get_config('demo').policy
        actual = adapter.execute_read(sql, params={'value': value}, policy=policy)
        assert [tuple(row) for row in actual] == expected
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_collate_inside_authorized_view_keeps_base_grant_independent(bundle, tmp_path, mode):
    save = prepare(bundle, tmp_path, grants=('approved',),
                   extra='CREATE VIEW approved AS SELECT id FROM orders WHERE n IS NULL COLLATE NOCASE;')
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            result = (await client.call_tool('query', {'sql': 'SELECT id AS n FROM approved'})).structured_content
            assert result['success'] and result['data'] == [{'n': 1}], result
            denied = (await client.call_tool('query', {'sql': 'SELECT id FROM orders'})).structured_content
            assert denied['error_code'] == 'table_access_denied'
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('prefix', ['EXPLAIN', 'EXPLAIN QUERY PLAN'])
async def test_collate_trigger_when_keeps_plan_nonexecuting(bundle, tmp_path, mode, prefix):
    save = prepare(bundle, tmp_path, extra='CREATE TRIGGER log_orders AFTER INSERT ON orders '
        'WHEN NEW.n IS NULL COLLATE NOCASE BEGIN INSERT INTO audit_log VALUES(NEW.id); END;')
    sql = prefix + " INSERT INTO orders VALUES(99,NULL,'test')"
    with sqlite3.connect(tmp_path / 'db.sqlite') as native:
        native.execute(sql).fetchall()
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            result = (await client.call_tool('query', {'sql': sql})).structured_content
            assert result['success'], result
            adapter = server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.execute('SELECT COUNT(*) FROM orders') == [(3,)]
            assert adapter.execute('SELECT * FROM audit_log') == []
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('rhs', ['NULL', ':escape', "'x'"])
def test_escape_collate_binds_to_escape_operand(rhs):
    sql = f"SELECT label LIKE 'A' ESCAPE {rhs} COLLATE NOCASE AS n FROM orders"
    dialect, tokens = _tokens(sql, DialectContext('sqlite'))
    trees = dialect.parser().parse(tokens, sql)
    assert trees[0] is not None
    expression = trees[0].expressions[0].this
    assert isinstance(expression, exp.Escape)
    assert isinstance(expression.expression, exp.Collate)
    assert analyze_sql(sql, DialectContext('sqlite')).complete


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_escape_skill_parameter_and_readiness(bundle, tmp_path, mode):
    save = prepare(bundle, tmp_path)
    _, _, skills, _ = bundle
    directory = tmp_path / 'skills'
    skill = directory / 'escape-report'
    skill.mkdir(parents=True)
    (skill / 'skill_def.md').write_text('---\nname: escape-report\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private ESCAPE operand\nparams:\n  escape:\n    type: str\n    required: true\n---\n')
    sql = "SELECT id AS n FROM orders WHERE label LIKE 'A' ESCAPE :escape COLLATE NOCASE ORDER BY id"
    (skill / 'query.sql').write_text(sql)
    skills['skills']['directory'] = str(directory)
    skills['skills']['readiness'] = {'check_schema': True}
    server = create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server, mode=mode) as client:
            found = (await client.call_tool('list_skills', {'detail_level': 'full'})).structured_content
            assert len(found['skills']) == 1 and found['skills'][0]['executable'], found
            detail = (await client.call_tool('get_skill_detail', {'skill_name': 'escape-report', 'detail_level': 'full'})).structured_content
            assert detail['skill']['schema_ready'] and detail['skill']['analysis_complete']
            for escape in ('x', 'y'):
                result = (await client.call_tool('execute_query_skill', {'skill_name': 'escape-report', 'params': {'escape': escape}})).structured_content
                assert result['success'] and result['data'] == [{'n': 1}, {'n': 2}], result
    finally:
        server.gateway_runtime.close()


def test_escape_nullable_bound_values_match_native(bundle, tmp_path):
    save = prepare(bundle, tmp_path)
    sql = "SELECT id AS n FROM orders WHERE label LIKE 'A' ESCAPE :escape COLLATE NOCASE ORDER BY id"
    server = create_server(load_config(save()))
    try:
        adapter = server.gateway_runtime.registry.get_adapter('demo')
        policy = server.gateway_runtime.registry.get_config('demo').policy
        for escape in (None, 'x', 'y'):
            with sqlite3.connect(tmp_path / 'db.sqlite') as native:
                expected = native.execute(sql, {'escape': escape}).fetchall()
            assert [tuple(r) for r in adapter.execute_read(sql, params={'escape': escape}, policy=policy)] == expected
    finally:
        server.gateway_runtime.close()
