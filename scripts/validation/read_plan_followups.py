"""Trailing reads, literal binding identity and schema projections over SQLite stdio.

Both configured classifiers and both Client modes use the same built-in plans.
Records are application results, not complete JSON-RPC frames or model usage.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


async def run(args):
    if args.source:
        sys.path.insert(0, str(args.source))
    import sql_safety_executor
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    package = Path(sql_safety_executor.__file__).resolve().parent
    assert package == args.source / 'sql_safety_executor' if args.source else 'site-packages' in str(package)
    assert not args.output.exists()
    records, inventories = [], []
    update, reset = 'sample-update-order-status', 'sample-reset-order-to-pending'
    for parser in ('sqlglot', 'sqlparse'):
        for mode in ('auto', 'legacy'):
            with tempfile.TemporaryDirectory(prefix='managed-parser-') as directory:
                root = Path(directory)
                database = root / 'fixture.sqlite'
                with sqlite3.connect(database) as db:
                    db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY,status TEXT,note TEXT);INSERT INTO orders VALUES(1,'pending',':business');")
                for name in (update, reset):
                    shutil.copytree(args.skills / name, root / 'skills' / name)
                update_source = root / 'skills' / update / 'mutation.py'
                original_source = update_source.read_text()
                needle = 'UPDATE orders SET status = :new_status '
                assert original_source.count(needle) == 1
                update_source.write_text(original_source.replace(needle,
                    "UPDATE /* :comment */ orders SET note=':business', status = :new_status "))
                reviewed = root / 'skills' / 'comment-read'
                reviewed.mkdir()
                (reviewed / 'skill_def.md').write_text(
                    '---\nname: comment-read\ntype: query\nsource: query.sql\nrisk: low\n'
                    'description: SQLite comment readiness\ndatabases: [sqlite]\n'
                    'tables: [main.orders]\nparams: {}\n---\n')
                reviewed_sql = "SELECT id,status,':business' AS marker FROM main.orders WHERE id=1; /* :tail */"
                (reviewed / 'query.sql').write_text(reviewed_sql)
                broken = root / 'skills' / 'rowcount-check'
                shutil.copytree(args.skills / update, broken)
                definition = broken / 'skill_def.md'
                definition.write_text(definition.read_text().replace('name: '+update, 'name: rowcount-check'))
                source = broken / 'mutation.py'
                source.write_text(source.read_text().replace('AND status = :expected_status"', 'AND status = :expected_status AND id=999"'))
                (root / 'server.toml').write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="fixture"\n')
                (root / 'connections.toml').write_text(
                    'schema_version=1\n[connections.fixture]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\n'
                    'read.mode="allowlist"\nread.tables=["orders"]\nmutation.enabled=true\nmutation.skills=["'+update+'","'+reset+'","rowcount-check"]\n')
                (root / 'skills.toml').write_text(
                    'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
                    '[skills.readiness]\ncheck_schema=true\n[skills.mutation]\nenabled=true\n'
                    'allowed_connections=["fixture"]\nmanaged_plan_parser="'+parser+'"\n'
                    '[skills.mutation.mrtr]\nenabled=false\n[skills.audit]\npath="audit.jsonl"\n')
                environment = os.environ.copy()
                if args.source:
                    environment['PYTHONPATH'] = str(args.source)
                transport = StdioTransport(command=sys.executable,
                    args=['-m', 'sql_safety_executor', 'serve', '--config', str(root / 'server.toml')], cwd=str(root), env=environment)
                async with Client(transport, mode=mode) as client:
                    inventories.append({'parser': parser, 'mode': mode, 'protocol': client.protocol_version,
                        'tools': [tool.model_dump(mode='json', exclude_none=True) for tool in await client.list_tools()]})

                    async def call(tool, arguments, *, outcome=None, error=False):
                        arguments = {'connection_id': 'fixture', **arguments}
                        response = await client.call_tool(tool, arguments, raise_on_error=False)
                        payload = response.structured_content
                        records.append({'parser': parser, 'mode': mode, 'tool': tool, 'arguments': arguments,
                            'isError': response.is_error, 'structured': payload, 'meta': response.meta,
                            'content': [block.model_dump(mode='json', exclude_none=True) for block in response.content]})
                        assert response.is_error is error, records[-1]
                        if outcome:
                            assert payload['execution_outcome'] == outcome, records[-1]
                        return payload

                    listed = await call('list_skills', {'detail_level': 'full'})
                    assert len(listed['skills']) == 4
                    query_state = next(value for value in listed['skills'] if value['name'] == 'comment-read')
                    assert query_state['executable'] and query_state['schema_ready'] and not query_state['missing_tables']
                    query_detail = await call('get_skill_detail', {'skill_name': 'comment-read', 'detail_level': 'execution'})
                    assert query_detail['skill']['executable']
                    query_result = await call('execute_query_skill', {'skill_name': 'comment-read', 'params': {}})
                    assert query_result['data'] == [{'id': 1, 'status': 'pending', 'marker': ':business'}]
                    raw = await call('query', {'sql': reviewed_sql})
                    assert raw['query'] == reviewed_sql and raw['data'] == query_result['data']
                    for sql in ['SELECT 7 AS n; /* tail */', 'WITH chosen AS (SELECT 7 AS n) SELECT n FROM chosen; -- tail\n']:
                        assert (await call('query', {'sql': sql}))['data'] == [{'n': 7}]
                    for level in ('compact', 'full'):
                        schema = await call('get_full_schema', {'detail_level': level})
                        assert schema['success'] and schema['returned_table_count'] == 1 and schema['total_columns'] == 3
                    detail = await call('get_skill_detail', {'skill_name': update})
                    assert detail['skill']['executable']
                    params = {'order_id': 1, 'new_status': 'confirmed'}
                    preview = await call('execute_mutation_skill', {'skill_name': update, 'params': params}, outcome='not_executed')
                    assert "/* :comment */" in preview['preview']['preview_sql'] and "note=':business'" in preview['preview']['preview_sql']
                    with sqlite3.connect(database) as db:
                        assert db.execute('SELECT status FROM orders').fetchone() == ('pending',)
                    confirm = {'skill_name': update, 'params': params, 'confirm': True, 'preview_token': preview['preview_token']}
                    executed = await call('execute_mutation_skill', confirm, outcome='committed')
                    assert executed['success'] and executed['result']['rowcount'] == 1
                    await call('execute_mutation_skill', confirm, error=True)
                    reset_params = {'order_id': 1, 'expected_status': 'confirmed'}
                    reset_preview = await call('execute_mutation_skill', {'skill_name': reset, 'params': reset_params}, outcome='not_executed')
                    restored = await call('execute_mutation_skill', {'skill_name': reset, 'params': reset_params,
                        'confirm': True, 'preview_token': reset_preview['preview_token']}, outcome='committed')
                    assert restored['result']['new_status'] == 'pending'
                    bad_preview = await call('execute_mutation_skill', {'skill_name': 'rowcount-check', 'params': params}, outcome='not_executed')
                    failed = await call('execute_mutation_skill', {'skill_name': 'rowcount-check', 'params': params,
                        'confirm': True, 'preview_token': bad_preview['preview_token']}, outcome='rolled_back')
                    assert not failed['success']
                    read = await call('query', {'sql': 'SELECT id,status FROM orders'})
                    assert read['data'] == [{'id': 1, 'status': 'pending'}]
                    for sql, code in [
                        ('SELECT /*+ NO_ICP(orders) */ * FROM secret', 'table_access_denied'),
                        ('SELECT /*+ NO_ICP(orders) */ SLEEP(0)', 'expensive_function_denied'),
                        ("UPDATE orders SET status='shipped'", 'read_only_required'),
                        ('SELECT 7; /* tail */ SELECT 99', 'multiple_statements'),
                    ]:
                        denied = await call('query', {'sql': sql})
                        assert not denied['success'] and denied['error_code'] == code
                with sqlite3.connect(database) as db:
                    assert db.execute('SELECT id,status,note FROM orders').fetchall() == [(1, 'pending', ':business')]
                audit = [json.loads(line) for line in (root / 'audit.jsonl').read_text().splitlines()]
                assert audit
    result = {'scope': __doc__, 'package': str(package), 'records': records, 'inventories': inventories,
        'resource_sha256': {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in package.rglob('*') if p.is_file() and p.suffix in {'.py', '.md'}}, 'passed': True}
    handles = []
    for record in records:
        handle = (record.get('structured') or {}).get('preview_token')
        if isinstance(handle, str) and handle not in handles:
            handles.append(handle)
    def redact(value):
        if isinstance(value, str):
            for index, handle in enumerate(handles):
                value = value.replace(handle, f'[REDACTED_FIXTURE_HANDLE_{index + 1}]')
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value
    result = redact(result)
    result['redacted_preview_handles'] = len(handles)
    result['scope'] += ' Bearer handles consistently redacted before disk export; temporary child-server fixtures only.'
    args.output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False, indent=2).encode(), mtime=0))
    print(json.dumps({'calls': len(records), 'runs': len(inventories), 'passed': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=lambda value: Path(value).resolve())
    parser.add_argument('--skills', type=lambda value: Path(value).resolve(), required=True, help='Repository built-in skills directory, also used with wheel.')
    parser.add_argument('--output', type=lambda value: Path(value).resolve(), required=True)
    asyncio.run(run(parser.parse_args()))
