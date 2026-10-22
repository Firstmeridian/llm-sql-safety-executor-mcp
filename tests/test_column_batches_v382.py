"""Batch only the authorized, truncated metadata projection; preserve identity."""
from fastmcp import Client
import pytest
import sqlite3

from sql_safety_executor import create_server, load_config
from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.test_mysql_sessions_v382 import adapter as mysql_adapter
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize('count', [0, 1, 199, 200, 401])
def test_mysql_column_batch_budget_and_original_order(monkeypatch, count):
    adapter = mysql_adapter()
    names = [f't{index:03}' for index in range(count)]
    calls = []
    def metadata(sql, operation, *, params):
        assert params['schema_name'] == 'business' and len(params) <= 200
        assert 'TABLE_SCHEMA = :schema_name' in sql and 'ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION' in sql
        selected = [value for key, value in params.items() if key != 'schema_name']
        calls.append(selected)
        return [(name, column, 'int', 'YES', '', None, None) for name in selected for column in ['z', 'a']]
    monkeypatch.setattr(adapter, '_execute_metadata', metadata)
    result = adapter.get_columns_batch(names + names[:1])
    assert list(result) == names
    assert [name for batch in calls for name in batch] == names
    assert len(calls) == (count + 198) // 199
    assert all([column['column_name'] for column in columns] == ['z', 'a'] for columns in result.values())


def test_mysql_column_batches_keep_exact_names_and_reject_partial_failure(monkeypatch):
    adapter = mysql_adapter()
    names = ['Orders', 'orders', 'K', 'K', 'a.b', 'a`b', 'colon:name']
    def metadata(sql, operation, *, params):
        return [(name, 'n', 'int', 'YES', '', None, None) for name in [*names, 'ORDERS', 'secret']]
    monkeypatch.setattr(adapter, '_execute_metadata', metadata)
    result = adapter.get_columns_batch(names)
    assert list(result) == names and all(len(columns) == 1 for columns in result.values())
    calls = []
    def unavailable(sql, operation, *, params):
        calls.append(True)
        if len(calls) == 2:
            raise MetadataQueryError('reading table columns')
        return [('t000', 'n', 'int', 'YES', '', None, None)]
    monkeypatch.setattr(adapter, '_execute_metadata', unavailable)
    with pytest.raises(MetadataQueryError):
        adapter.get_columns_batch([f't{index:03}' for index in range(200)])
    assert len(calls) == 2


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('detail', ['compact', 'full'])
async def test_schema_batches_only_allowed_returned_names(bundle, tmp_path, monkeypatch, mode, detail):
    main, connections, _, save = bundle
    main['limits'] = {'schema_tables': 2}
    connections['connections']['demo']['read'] = {'mode': 'allowlist', 'tables': ['t1', 't3', 't4']}
    with sqlite3.connect(tmp_path / 'db.sqlite') as db:
        for name in ['secret', 't1', 't2', 't3', 't4']:
            db.execute(f'CREATE TABLE {name}(z INTEGER,a TEXT)')
    server = create_server(load_config(save()))
    adapter = server.gateway_runtime.registry.get_adapter('demo')
    original = adapter.get_columns_batch
    calls = []
    def batch(names):
        assert names == ['t1', 't3']
        calls.append(names)
        return original(names)
    monkeypatch.setattr(adapter, 'get_columns_batch', batch)
    try:
        async with Client(server, mode=mode) as client:
            result = (await client.call_tool('get_full_schema', {'detail_level': detail})).structured_content
        assert result['success'] and result['truncated'] and result['total_tables'] == 3
        assert result['returned_table_count'] == 2 and calls == [['t1', 't3']]
        if detail == 'full':
            assert list(result['schema']) == ['t1', 't3']
        else:
            assert result['schema_groups'][0]['columns'] == [['z', 'INTEGER'], ['a', 'TEXT']]
    finally:
        server.gateway_runtime.close()
