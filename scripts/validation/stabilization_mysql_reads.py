"""Bounded real-MySQL read contracts in a newly owned disposable schema.

Requires the same explicit fixture authorization as mysql_writes.py. Uses its
ownership/cleanup helper, not its assertions or a project value-encoding oracle.
No configured business tables, grants, global settings or private TOMLs change.
"""
import argparse
import asyncio
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from mysql_writes import Fixture


def native_value(value):
    if isinstance(value, bytes):
        return {'$type': 'binary', 'encoding': 'base64', 'data': base64.b64encode(value).decode('ascii')}
    return value


async def exercise(fixture, args, output):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    from sql_safety_executor import create_server, load_config
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    names = ['orders', 'facts', 'blobs', 'wide', 'order.data', 'order data']
    with fixture.connect(autocommit=True) as db:
        with db.cursor() as cur:
            cur.execute('CREATE TABLE facts(b INT,a INT,n INT,doubled INT GENERATED ALWAYS AS(n*2) STORED,shifted INT GENERATED ALWAYS AS(n+3) VIRTUAL,PRIMARY KEY(a,b)) ENGINE=InnoDB')
            cur.execute('INSERT INTO facts(b,a,n) VALUES(2,1,7)')
            cur.execute('CREATE TABLE blobs(id INT PRIMARY KEY,payload BLOB) ENGINE=InnoDB')
            cur.execute("INSERT INTO blobs VALUES(1,X'00FF')")
            cur.execute('CREATE TABLE wide(payload LONGTEXT) ENGINE=InnoDB')
            cur.execute("INSERT INTO wide VALUES(REPEAT('x',20000))")
            for name, value in [('order.data', 13), ('order data', 17)]:
                cur.execute('CREATE TABLE `' + name + '`(n INT) ENGINE=InnoDB')
                cur.execute('INSERT INTO `' + name + '` VALUES(%s)', (value,))

    sqls = {
        'ordinary': 'SELECT n FROM facts',
        'cte': 'WITH chosen AS(SELECT n FROM facts) SELECT n FROM chosen',
        'generated': 'SELECT b,a,n,doubled,shifted FROM facts',
        'binary': 'SELECT payload FROM blobs',
        'empty': 'SELECT payload FROM blobs WHERE id<0',
        'literal-dot': 'SELECT n FROM `order.data`',
        'literal-space': 'SELECT n FROM `order data`',
        'duplicate': 'SELECT 7 AS n,99 AS n',
        'oversize': 'SELECT payload FROM wide',
    }
    oracle = {}
    with fixture.connect(autocommit=True) as db:
        with db.cursor() as cur:
            for name, sql in sqls.items():
                cur.execute(sql)
                labels = [c[0] for c in cur.description]
                rows = cur.fetchall()
                if name == 'duplicate':
                    assert labels == ['n', 'n'] and rows == ((7, 99),)
                    oracle[name] = {'error_code': 'duplicate_result_columns'}
                elif name == 'oversize':
                    assert len(rows) == 1 and len(rows[0][0]) == 20000
                    oracle[name] = {'data': [], 'row_count': 0, 'total_rows': 1, 'truncated': True, 'truncation_reason': 'char_limit'}
                else:
                    assert len(set(labels)) == len(labels)
                    oracle[name] = {'data': [dict(zip(labels, map(native_value, row))) for row in rows]}
            cur.execute('SELECT COLUMN_NAME,DATA_TYPE,IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION', (fixture.schema, 'facts'))
            columns = [list(r) for r in cur.fetchall()]
            cur.execute("SELECT COLUMN_NAME,ORDINAL_POSITION FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME='PRIMARY' ORDER BY ORDINAL_POSITION", (fixture.schema, 'facts'))
            positions = dict(cur.fetchall())
            assert positions == {'a': 1, 'b': 2}
    output['oracle'] = {'queries': oracle, 'columns': columns, 'primary_positions': positions}
    before = fixture.observe()
    for transport_kind in ('inprocess', 'stdio'):
        for mode in ('auto', 'legacy'):
            with tempfile.TemporaryDirectory(prefix='stabilization-mysql-read-') as directory:
                root = Path(directory)
                (root/'server.toml').write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="fixture"\n[tools]\ntable_summary=true\n')
                mysql = fixture.config
                declarations = ','.join('{name='+json.dumps(name)+'}' for name in names)
                private = ('schema_version=1\n[connections.fixture]\ntype="mysql"\nread.mode="allowlist"\nread.relations=['+declarations+']\n'+
                           '\n'.join('mysql.'+k+'='+json.dumps(v) for k,v in {'host':mysql.mysql_host,'user':mysql.mysql_user,'database':fixture.schema}.items())+'\n'+
                           'mysql.password={value='+json.dumps(mysql.mysql_password.get_secret_value() if mysql.mysql_password else '')+'}\n')
                (root/'connections.toml').write_text(private); (root/'connections.toml').chmod(0o600)
                (root/'skills.toml').write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
                for name, sql in sqls.items():
                    skill = root/'skills'/('probe-'+name); skill.mkdir(parents=True)
                    (skill/'skill_def.md').write_text('---\nname: probe-'+name+'\ntype: query\nsource: query.sql\nrisk: low\ndescription: Isolated read-contract fixture\nparams: {}\n---\n')
                    (skill/'query.sql').write_text(sql)
                server = None
                if transport_kind == 'inprocess':
                    server = create_server(load_config(root/'server.toml')); transport = server
                else:
                    environment = os.environ.copy(); environment.pop('PYTHONPATH', None)
                    if args.source: environment['PYTHONPATH'] = str(args.source.resolve())
                    transport = StdioTransport(command=sys.executable, args=['-m','sql_safety_executor','serve','--config',str(root/'server.toml')], cwd=str(root), env=environment)
                try:
                    async with Client(transport, mode=mode, init_timeout=30, timeout=30) as client:
                        async def call(tool, arguments):
                            result = await client.call_tool(tool, {'connection_id':'fixture', **arguments}, raise_on_error=False)
                            assert not result.is_error, (tool, 'unexpected generic tool error')
                            value = result.structured_content
                            assert isinstance(value, dict)
                            for block in result.content:
                                if getattr(block, 'type', None) == 'text': assert json.loads(block.text) == value
                            output['calls'].append({'transport':transport_kind,'mode':mode,'tool':tool,'arguments':arguments,'result':value,'text_structured_agree':True})
                            return value
                        listed = await call('list_skills', {'detail_level':'full'})
                        assert len(listed['skills']) == len(sqls) and all(s['executable'] and s['schema_ready'] for s in listed['skills'])
                        for name, sql in sqls.items():
                            for tool, arguments in [('query', {'sql':sql}), ('execute_query_skill', {'skill_name':'probe-'+name,'params':{}})]:
                                value = await call(tool, arguments)
                                expected = oracle[name]
                                for key, wanted in expected.items(): assert value.get(key) == wanted, (name, tool, key)
                                assert value['success'] is (name != 'duplicate')
                        for name in ['binary', 'literal-dot']:
                            state = (await call('get_skill_detail', {'skill_name':'probe-'+name}))['skill']
                            assert state['schema_ready'] and state['executable']
                        for table, expected in [('blobs', [{'id':1,'payload':native_value(b'\x00\xff')}]), ('order.data',[{'n':13}]), ('order data',[{'n':17}])]:
                            value = await call('sample', {'table_name':table,'limit':1})
                            assert value['success'] and value['data'] == expected
                        summary = await call('get_table_summary', {'table_name':'facts','exact_count':True})
                        assert summary['success'] and summary['row_count'] == 1
                        described = await call('describe_table', {'table_name':'facts'})
                        assert described['success'] and len(described['columns']) == len(columns)
                        assert [[c['column_name'],c['data_type'],c['nullable']] for c in described['columns']] == columns
                        assert {c['column_name']:c['primary_key_position'] for c in described['columns'] if 'primary_key_position' in c} == positions
                        catalog = await call('list_tables', {})
                        assert {t['table_name'] for t in catalog['tables']} == set(names)
                        full = await call('get_full_schema', {'detail_level':'full'})
                        assert set(full['schema']) == set(names)
                        compact = await call('get_full_schema', {'detail_level':'compact'})
                        actual = {t['name']:g for g in compact['schema_groups'] for t in g['tables']}
                        assert set(actual) == set(names)
                        assert actual['facts']['primary_key'] == ['a','b']
                        for sql, code in [('SELECT n FROM audit_log','table_access_denied'),('SELECT SLEEP(0)','expensive_function_denied'),('UPDATE orders SET n=99','read_only_required')]:
                            assert (await call('query', {'sql':sql}))['error_code'] == code
                finally:
                    if server is not None: server.gateway_runtime.close()
    assert fixture.observe() == before
    output['transactional_business_truth_unchanged'] = True


def run(args):
    if args.source: sys.path.insert(0, str(args.source.resolve()))
    import sql_safety_executor
    from sql_safety_executor import load_config
    package = Path(sql_safety_executor.__file__).resolve().parent
    assert package == args.source.resolve()/'sql_safety_executor' if args.source else package.is_relative_to(Path(sys.prefix))
    assert not args.output.exists()
    output = {'passed':False, 'scope':'owned disposable MySQL schema only; real Client application packets, not full wire frames/model usage', 'calls':[]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Fixture(load_config(args.config).connections[args.alias]) as fixture:
            asyncio.run(exercise(fixture, args, output))
        output['disposable_schema_removed'] = True
        output['passed'] = True
    except BaseException as error:
        output['failure_class'] = type(error).__name__
        raise
    finally:
        output['resources'] = {str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*') if p.is_file() and p.suffix in {'.py','.md'}}
        args.output.write_bytes(gzip.compress(json.dumps(output, ensure_ascii=False, indent=2).encode(), mtime=0))
    print(json.dumps({'passed':True,'calls':len(output['calls']),'schema_removed':True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--alias', required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except BaseException as error:
        print(json.dumps({'passed':False,'failure_class':type(error).__name__,'note':'sanitized evidence retained; no automatic retry'}))
        raise SystemExit(1) from None
