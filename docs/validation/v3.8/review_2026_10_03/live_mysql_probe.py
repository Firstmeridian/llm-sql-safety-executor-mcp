"""Explicit local review probe: creates/drops only a UUID-named test table.

Run from the repository with its configured disposable MySQL target. No
deployment configuration is changed, and no pre-existing table is written.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import uuid

from sql_safety_executor.config import load_config
from sql_safety_executor.config.models import Observability, Skills
from sql_safety_executor.database.registry import create_adapter
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.mcp.server import create_server
from fastmcp import Client
from sqlalchemy import text


async def main():
    config = load_config('config/server.toml')
    alias = 'trade_analysis_mysql'
    table = 'v381_review_' + uuid.uuid4().hex[:12]
    adapter = create_adapter(config=config.connections[alias])
    created = False
    evidence = {'target': alias, 'fixture': table, 'existing_data_written': False}
    try:
        assert adapter.connect()
        with adapter._engine.begin() as connection:
            evidence['mysql_version'] = connection.execute(text('SELECT VERSION()')).scalar_one()
            connection.execute(text(f'CREATE TABLE `{table}` (id INT PRIMARY KEY, code VARCHAR(40) NOT NULL, score INT NOT NULL, INDEX idx_prefix(code(4)), INDEX idx_desc(score DESC, code ASC) INVISIBLE, UNIQUE INDEX uq_code(code))'))
            created = True
            connection.execute(text(f'INSERT INTO `{table}` (id,code,score) VALUES (1,"alpha",10),(2,"bravo",30),(3,"charlie",20),(4,"delta",40)'))
            native_rows = [dict(row._mapping) for row in connection.execute(text(f'SHOW INDEX FROM `{table}`'))]
        isolated = replace(
            config,
            server=config.server.model_copy(update={'observability': Observability()}),
            skills=Skills(),
            connections={alias: replace(config.connections[alias], policy=ConnectionPolicy(
                read_mode='allowlist', allowed_tables=frozenset({table}), case_sensitive_tables=True))},
        )
        async with Client(create_server(isolated)) as client:
            result = (await client.call_tool('describe_table', {'connection_id': alias, 'table_name': table})).structured_content
            assert result['success'] and result['indexes_status'] == 'complete', result
            by_name = {index['name']: index for index in result['indexes']}
            for row in native_rows:
                index = by_name[row['Key_name']]
                key = index['key_parts'][row['Seq_in_index'] - 1]
                assert key['column'] == row['Column_name']
                assert key['prefix_length'] == row['Sub_part']
                assert key['sort_order'] == {'A': 'asc', 'D': 'desc'}.get(row['Collation'])
                assert index['visible'] is (row['Visible'] == 'YES')
            evidence['indexes'] = result['indexes']
            evidence['native_attribute_comparison_passed'] = True
            denied = (await client.call_tool('query', {'connection_id': alias, 'sql': 'WITH a AS (SELECT COUNT(*) n FROM orders), orders AS (SELECT 1) SELECT n FROM a'})).structured_content
            assert denied['success'] is False
            evidence['cte_unlisted_physical_table_denied'] = True
            read = (await client.call_tool('query', {'connection_id': alias, 'sql': f'SELECT COUNT(*) AS n FROM `{table}`'})).structured_content
            assert read['data'] == [{'n': 4}], read
            evidence['fixture_rows'] = 4
    finally:
        if created:
            with adapter._engine.begin() as connection:
                connection.execute(text(f'DROP TABLE `{table}`'))
                count = connection.execute(text('SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name'), {'name': table}).scalar_one()
                assert count == 0
                evidence['fixture_removed'] = True
        adapter.close()
        Path('/tmp/v381-live-mysql-result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
