"""PRIMARY identity and ordered members are independent of display key flags."""
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from tests.support_adapters import SQLiteAdapter
from tests.test_mysql_sessions_v382 import adapter as mysql_adapter
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize('definition,expected', [
    ('a INTEGER NOT NULL,b INTEGER NOT NULL,PRIMARY KEY(a,b)', {'a': 1, 'b': 2}),
    ('a INTEGER NOT NULL,b INTEGER NOT NULL,PRIMARY KEY(b,a)', {'b': 1, 'a': 2}),
    ('a INTEGER,b INTEGER,PRIMARY KEY(b DESC,a ASC)', {'b': 1, 'a': 2}),
    ('a INTEGER,b INTEGER,PRIMARY KEY(b,a,b)', {'b': 1, 'a': 2}),
    ('a INTEGER,b INTEGER,c INTEGER,PRIMARY KEY(b,a,b,c)', {'b': 1, 'a': 2, 'c': 4}),
    ('a INTEGER PRIMARY KEY,b INTEGER', {'a': 1}),
    ('a INTEGER PRIMARY KEY DESC,b INTEGER', {'a': 1}),
    ('a INTEGER NOT NULL UNIQUE,b INTEGER', {}),
    ('a INTEGER NOT NULL,b INTEGER NOT NULL,UNIQUE(b,a)', {}),
    ('a INTEGER UNIQUE,b INTEGER', {}),
    ('a INTEGER,b INTEGER', {}),
    ('a INTEGER,b AS(a+1) VIRTUAL', {}),
])
def test_sqlite_positions_follow_native_constraint_not_column_order(tmp_path, definition, expected):
    path = tmp_path / 'fixture.sqlite'
    with sqlite3.connect(path) as db:
        db.execute(f'CREATE TABLE chosen({definition})')
        native = list(db.execute("PRAGMA main.table_xinfo('chosen')"))
    adapter = SQLiteAdapter(path)
    try:
        columns = adapter.get_columns('chosen')
        assert [c['column_name'] for c in columns] == [r[1] for r in native]
        positions = {c['column_name']: c['primary_key_position'] for c in columns if 'primary_key_position' in c}
        assert positions == expected
    finally:
        adapter.close()


def test_sqlite_positions_reuse_single_column_pragma(monkeypatch):
    adapter = SQLiteAdapter(':memory:')
    adapter.connect()
    try:
        with adapter._engine.begin() as db:
            db.exec_driver_sql('CREATE TABLE chosen(a INTEGER,b INTEGER,PRIMARY KEY(b,a)) WITHOUT ROWID')
        original = adapter.execute
        statements = []
        def execute(sql, **kwargs):
            statements.append(sql)
            return original(sql, **kwargs)
        monkeypatch.setattr(adapter, 'execute', execute)
        assert [c['primary_key_position'] for c in adapter.get_columns('chosen')] == [2, 1]
        assert statements == ["PRAGMA main.table_xinfo('chosen')"]
    finally:
        adapter.close()


@pytest.mark.parametrize('batched', [False, True])
def test_mysql_uses_actual_primary_constraint_preserving_native_key_flags(monkeypatch, batched):
    adapter = mysql_adapter()
    calls = []
    def metadata(sql, operation, *, params):
        calls.append(params)
        assert 'KEY_COLUMN_USAGE AS pk' in sql and "pk.CONSTRAINT_NAME = 'PRIMARY'" in sql
        for component in ['TABLE_SCHEMA', 'TABLE_NAME', 'COLUMN_NAME']:
            assert f'BINARY pk.{component} = BINARY c.{component}' in sql
        # The first two columns have reversed PRIMARY order; the third has a
        # native PRI display flag but no PRIMARY constraint (a different table
        # in the batch). No guessed positions may be derived from the flag.
        rows = [('a', 'int', 'NO', 'PRI', None, 2), ('b', 'int', 'NO', 'PRI', None, 1)]
        return [('chosen', *r) for r in rows] + [('unique_only', 'n', 'int', 'NO', 'PRI', None, None)] if batched else rows
    monkeypatch.setattr(adapter, '_execute_metadata', metadata)
    result = adapter.get_columns_batch(['chosen', 'unique_only']) if batched else {'chosen': adapter.get_columns('chosen')}
    assert [c['column_name'] for c in result['chosen']] == ['a', 'b']
    assert [c['primary_key_position'] for c in result['chosen']] == [2, 1]
    assert all(c['key_type'] == 'PRI' for c in result['chosen'])
    if batched:
        assert result['unique_only'] == [dict(column_name='n', data_type='int', nullable='NO', key_type='PRI', default_value=None)]
    assert len(calls) == 1


def test_mysql_nonprimary_unique_display_flag_has_no_primary_position(monkeypatch):
    adapter = mysql_adapter()
    monkeypatch.setattr(adapter, '_execute_metadata', lambda *_a, **_k: [('n', 'int', 'NO', 'PRI', None, None)])
    assert 'primary_key_position' not in adapter.get_columns('unique_only')[0]


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('grouped', [False, True])
async def test_primary_members_order_grouping_and_full_projection(bundle, tmp_path, monkeypatch, mode, grouped):
    main, connections, _, save = bundle
    names = ['key_ab', 'key_ba', 'without_rowid', 'repeated_pk', 'unique_only']
    connections['connections']['demo']['read'] = {'mode': 'allowlist', 'tables': names}
    with sqlite3.connect(tmp_path / 'db.sqlite') as db:
        for name in names:
            key = 'UNIQUE(a,b)' if name == 'unique_only' else 'PRIMARY KEY(a,b)' if name == 'key_ab' else 'PRIMARY KEY(b,a,b)' if name == 'repeated_pk' else 'PRIMARY KEY(b,a)'
            suffix = ' WITHOUT ROWID' if name == 'without_rowid' else ''
            db.execute(f'CREATE TABLE {name}(a INTEGER NOT NULL,b INTEGER NOT NULL,{key}){suffix}')
            db.execute(f'INSERT INTO {name} VALUES(7,99)')
    server = create_server(load_config(save()))
    adapter = server.gateway_runtime.registry.get_adapter('demo')
    # Compact must not turn batch collection into one index query per table.
    monkeypatch.setattr(adapter, 'get_indexes', lambda *_: pytest.fail('schema must reuse column positions'))
    expected = {n: [] if n == 'unique_only' else ['a', 'b'] if n == 'key_ab' else ['b', 'a'] for n in names}
    try:
        async with Client(server, mode=mode) as client:
            result = (await client.call_tool('get_full_schema', {'group_identical': grouped})).structured_content
            assert result['success'] and result['total_columns'] == 10
            groups = result['schema_groups']
            assert result['schema_group_count'] == (3 if grouped else 5)
            assert {t['name']: g['primary_key'] for g in groups for t in g['tables']} == expected
            full = (await client.call_tool('get_full_schema', {'detail_level': 'full'})).structured_content
            for name, table in full['schema'].items():
                assert [c.get('primary_key_position') for c in table['columns']] == (
                    [None, None] if name == 'unique_only' else [1, 2] if name == 'key_ab' else [2, 1])
            assert (await client.call_tool('query', {'sql': 'SELECT a,b FROM key_ba'})).structured_content['data'] == [{'a': 7, 'b': 99}]
    finally:
        server.gateway_runtime.close()
