"""SQLite metadata preserves native types without inventing TEXT affinity."""
import sqlite3

from fastmcp import Client
import pytest

from tests.support_adapters import SQLiteAdapter
from tests.test_external_read_review_v382 import review_server, bundle


@pytest.mark.parametrize('declaration,native_type,storage,equals_text', [
    ('', '', 'integer', 0),
    ('TEXT', 'TEXT', 'text', 1),
    ('BLOB', 'BLOB', 'integer', 0),
    ('INTEGER', 'INTEGER', 'integer', 1),
    ('NUMERIC', 'NUMERIC', 'integer', 1),
    ('""', '', 'integer', 1),
    ('" "', ' ', 'integer', 1),
    ('STRING', 'STRING', 'integer', 1),
    ('ANY', 'ANY', 'integer', 1),
])
def test_declared_type_matches_native_catalog_without_extra_queries(
        declaration, native_type, storage, equals_text, monkeypatch):
    adapter = SQLiteAdapter(':memory:')
    assert adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql(f'CREATE TABLE chosen(n {declaration})')
            db.exec_driver_sql('INSERT INTO chosen VALUES(7)')
            assert db.exec_driver_sql("PRAGMA main.table_xinfo('chosen')").fetchone()[2] == native_type
            assert tuple(db.exec_driver_sql("SELECT typeof(n), n='7' FROM chosen").fetchone()) == (storage, equals_text)
        original = adapter.execute
        queries = []

        def execute(sql, **kwargs):
            queries.append(sql)
            return original(sql, **kwargs)

        monkeypatch.setattr(adapter, 'execute', execute)
        assert adapter.get_columns('chosen') == [{
            'column_name': 'n', 'data_type': native_type, 'nullable': 'YES',
            'key_type': '', 'default_value': None}]
        assert queries == ["PRAGMA main.table_xinfo('chosen')"]
    finally:
        adapter.close()


DDL = """
CREATE TABLE untyped(n);
INSERT INTO untyped VALUES(7);
CREATE TABLE typed_text(n TEXT);
INSERT INTO typed_text VALUES(7);
CREATE TABLE generated(base INTEGER,n AS(base) VIRTUAL);
INSERT INTO generated(base) VALUES(7);
CREATE TABLE generated_text(base INTEGER,n TEXT AS(base) VIRTUAL);
INSERT INTO generated_text(base) VALUES(7);
CREATE TABLE generated_stored(base INTEGER,n AS(base) STORED);
INSERT INTO generated_stored(base) VALUES(7);
CREATE VIRTUAL TABLE searchable USING fts5(n);
INSERT INTO searchable VALUES(7);
CREATE VIEW expression_view AS SELECT 7 AS n;
CREATE TABLE secret(n TEXT);
INSERT INTO secret VALUES('private');
"""
TABLES = ['untyped', 'typed_text', 'generated', 'generated_text', 'generated_stored', 'searchable']


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_types_all_projections_groups_and_read_semantics(review_server, tmp_path, mode):
    server = review_server("SELECT n,typeof(n) AS storage,n='7' AS equals_text FROM main.untyped",
        ddl=DDL, read={'mode': 'allowlist', 'tables': TABLES + ['expression_view']})
    truth = {}
    with sqlite3.connect(tmp_path / 'db.sqlite') as db:
        for name in TABLES + ['expression_view']:
            rows = list(db.execute(f"PRAGMA main.table_xinfo('{name}')"))
            truth[name] = [r for r in rows if r[6] != 1]
    async with Client(server, mode=mode) as client:
        for name, columns in truth.items():
            for tool in ['describe_table', 'get_table_summary']:
                payload = (await client.call_tool(tool, {'table_name': name})).structured_content
                assert payload['success'] and payload['column_count'] == len(columns)
                assert [c['data_type'] for c in payload['columns']] == [r[2] for r in columns]
                assert [c.get('generation_type') for c in payload['columns']] == [
                    {2: 'virtual', 3: 'stored'}.get(r[6]) for r in columns]
        for grouped in [False, True]:
            compact = (await client.call_tool('get_full_schema', {
                'detail_level': 'compact', 'group_identical': grouped})).structured_content
            groups = compact['schema_groups']
            lookup = {t['name']: g for g in groups for t in g['tables']}
            assert set(lookup) == set(TABLES)
            assert compact['total_columns'] == 9
            assert compact['schema_group_count'] == (5 if grouped else 6)
            assert lookup['untyped']['columns'] == [['n', '']]
            assert lookup['typed_text']['columns'] == [['n', 'TEXT']]
            assert lookup['generated']['columns'] == [['base', 'INTEGER'], ['n', '']]
            assert lookup['generated_text']['columns'] == [['base', 'INTEGER'], ['n', 'TEXT']]
        full = (await client.call_tool('get_full_schema', {'detail_level': 'full'})).structured_content
        assert set(full['schema']) == set(TABLES) and full['total_columns'] == 9
        for name in TABLES:
            assert [c['type'] for c in full['schema'][name]['columns']] == [r[2] for r in truth[name]]
        for name, expected in [('untyped', [7, 'integer', 0]), ('typed_text', ['7', 'text', 1]),
                               ('searchable', [7, 'integer', 0]), ('expression_view', [7, 'integer', 0])]:
            payload = (await client.call_tool('query', {
                'sql': f"SELECT n,typeof(n) AS storage,n='7' AS equals_text FROM main.{name}"})).structured_content
            assert payload['data'] == [dict(zip(['n', 'storage', 'equals_text'], expected))]
        detail = (await client.call_tool('get_skill_detail', {'skill_name': 'review-probe'})).structured_content
        assert detail['skill']['executable'] and detail['skill']['schema_ready']
        executed = (await client.call_tool('execute_query_skill', {
            'skill_name': 'review-probe', 'params': {}})).structured_content
        assert executed['data'] == [{'n': 7, 'storage': 'integer', 'equals_text': 0}]
        denied = (await client.call_tool('query', {'sql': 'SELECT n FROM secret'})).structured_content
        assert denied['error_code'] == 'table_access_denied'


def test_empty_generated_and_view_types_do_not_require_expression_evaluation():
    adapter = SQLiteAdapter(':memory:')
    assert adapter.connect()
    calls = []
    try:
        with adapter._engine.begin() as db:
            db.connection.dbapi_connection.create_function('marker', 1, lambda value: calls.append(value) or value, deterministic=True)
            db.exec_driver_sql('CREATE TABLE generated(base NOT NULL DEFAULT 7,n AS(marker(base)) VIRTUAL)')
            db.exec_driver_sql('INSERT INTO generated DEFAULT VALUES')
            db.exec_driver_sql('CREATE VIEW expression_view AS SELECT marker(7) AS n')
        calls.clear()
        columns = adapter.get_columns('generated')
        assert [c['data_type'] for c in columns] == ['', '']
        assert columns[0]['nullable'] == 'NO' and columns[0]['default_value'] == '7'
        assert columns[1]['generation_type'] == 'virtual'
        assert adapter.get_columns('expression_view')[0]['data_type'] == ''
        assert calls == []
    finally:
        adapter.close()


def test_strict_any_is_preserved_without_claiming_a_value_storage_type():
    adapter = SQLiteAdapter(':memory:')
    assert adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql('CREATE TABLE chosen(n ANY) STRICT')
            db.exec_driver_sql("INSERT INTO chosen VALUES('0007')")
            assert tuple(db.exec_driver_sql('SELECT n,typeof(n) FROM chosen').fetchone()) == ('0007', 'text')
        assert adapter.get_columns('chosen')[0]['data_type'] == 'ANY'
    finally:
        adapter.close()
