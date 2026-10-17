"""Source-selectable, real child-stdio checks for SQLite explanation plans.

Private fixtures only. --expect before selects the frozen pre-follow-up v3.8.2
behavior. Without --source, use an independently installed wheel interpreter.
"""
from __future__ import annotations
import argparse
import asyncio
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

BASE = ('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE plain(n); INSERT INTO plain VALUES(11);'
        'CREATE TABLE audit_log(n); CREATE TABLE lookup_values(n); INSERT INTO lookup_values VALUES(13);'
        'CREATE TABLE hidden(n); INSERT INTO hidden VALUES(17); CREATE VIEW normal_view AS SELECT n FROM hidden;')
FIXTURES = {
    'trigger_reads': 'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN NEW.n>0 BEGIN INSERT INTO audit_log VALUES(NEW.n); INSERT INTO audit_log SELECT COUNT(*) FROM lookup_values; INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; END; CREATE TRIGGER update_orders AFTER UPDATE ON orders BEGIN INSERT INTO audit_log VALUES(OLD.n+NEW.n); END; CREATE TRIGGER delete_orders AFTER DELETE ON orders BEGIN INSERT INTO audit_log VALUES(OLD.n); END;',
    'bad_read': 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT n FROM hidden; END;',
    'bad_write': 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO hidden VALUES(99); END;',
    'bad_function': 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log VALUES(SLEEP(0)); END;',
    'mixed_count': 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; INSERT INTO audit_log SELECT COUNT(*) FROM hidden; END;',
    'when_count': 'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN (SELECT COUNT(*) FROM hidden)>0 BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; END;',
    'shadow': '',
    'attached': '',
}
SESSIONS = {
    'shadow':'CREATE TEMP TABLE orders(n); INSERT INTO temp.orders VALUES(99);',
    'attached':"ATTACH ':memory:' AS aux; CREATE TABLE aux.extra(n); INSERT INTO aux.extra VALUES(23); CREATE TEMP TRIGGER log_orders AFTER INSERT ON main.orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM aux.extra; END;",
}

async def check(args):
    if args.source:
        sys.path.insert(0,str(args.source))
    import sql_safety_executor
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    package=Path(sql_safety_executor.__file__).parent
    assert package.is_relative_to(args.source) if args.source else 'site-packages' in str(package)
    after=args.expect=='after'
    records=[]
    with tempfile.TemporaryDirectory(prefix='v382-sqlite-plans-') as temporary:
        root=Path(temporary)
        snapshots={}
        for name,ddl in FIXTURES.items():
            with sqlite3.connect(root/(name+'.sqlite')) as db:
                db.executescript(BASE+ddl)
                snapshots[name]={table:db.execute('SELECT * FROM '+table).fetchall() for table in ['orders','plain','audit_log','lookup_values','hidden']}
        (root/'server.toml').write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="trigger_reads"\n')
        connection_text='schema_version=1\n'
        grants=['orders','main.orders','plain','main.plain','audit_log','lookup_values','normal_view','aux.extra']
        for name in FIXTURES:
            connection_text+=f'[connections.{name}]\ntype="sqlite"\nsqlite.path="{name}.sqlite"\nread.mode="allowlist"\nread.tables='+json.dumps(grants)+'\n'
        (root/'connections.toml').write_text(connection_text)
        (root/'skills.toml').write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        for name,sql in {
            'with-replace-plan':'EXPLAIN WITH chosen(n) AS (SELECT :value) REPLACE INTO orders SELECT n FROM chosen',
            'update-or-plan':'EXPLAIN UPDATE OR IGNORE orders SET n=:value',
        }.items():
            skill=root/'skills'/name
            skill.mkdir(parents=True)
            (skill/'skill_def.md').write_text(f'---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private non-executing plan\nconnection_ids: [trigger_reads]\nparams:\n  value:\n    type: int\n    required: true\n---\n')
            (skill/'query.sql').write_text(sql)
        source_line=f'import sys; sys.path.insert(0,{str(args.source)!r})\n' if args.source else ''
        launcher=root/'launcher.py'
        launcher.write_text(source_line+'from sql_safety_executor import create_server,load_config\n'
            'server=create_server(load_config("server.toml"))\ncalls=[]\n'
            f'for name in {list(FIXTURES)!r}:\n'
            ' adapter=server.gateway_runtime.registry.get_adapter(name)\n assert adapter.connect()\n'
            ' with adapter._engine.connect() as connection:\n'
            '  raw=connection.connection.dbapi_connection\n'
            f'  raw.executescript({SESSIONS!r}.get(name,""))\n'
            '  raw.create_function("SLEEP",1,lambda _:calls.append(1) or 0)\n'
            '  raw.create_function("validation_calls",0,lambda:len(calls))\n'
            '  raw.create_function("validation_changes",0,lambda c=raw:c.total_changes)\n'
            'server.run(transport="stdio",show_banner=False)\n')
        for mode in ['auto','legacy']:
            async with Client(StdioTransport(command=sys.executable,args=[str(launcher)],cwd=str(root)),mode=mode) as client:
                async def call(tool,arguments,connection='trigger_reads'):
                    arguments={**arguments,'connection_id':connection}
                    response=await client.call_tool(tool,arguments,raise_on_error=False)
                    payload=response.structured_content
                    assert not response.is_error and isinstance(payload,dict),response
                    content=[item.text for item in response.content if item.type=='text']
                    assert len(content)==1 and json.loads(content[0])==payload
                    records.append(dict(mode=mode,protocol=client.protocol_version,tool=tool,arguments=arguments,
                        structured=payload,isError=response.is_error,content=[item.model_dump(mode='json',exclude_none=True) for item in response.content]))
                    return payload
                changes={name:(await call('query',{'sql':'SELECT validation_changes() AS n'},name))['data'] for name in FIXTURES}
                bodies=['INSERT INTO orders VALUES(99)','UPDATE orders SET n=99','DELETE FROM orders',
                    'WITH chosen(n) AS (SELECT 99) REPLACE INTO orders SELECT n FROM chosen',
                    'WITH first(n) AS (SELECT 99), chosen(n) AS (SELECT n FROM first) REPLACE INTO orders SELECT n FROM chosen RETURNING n',
                    "WITH replace(n) AS (SELECT length(replace('REPLACE','R','r'))) REPLACE INTO orders SELECT n FROM replace",
                    'WITH RECURSIVE chosen(n) AS (SELECT 99) REPLACE INTO orders DEFAULT VALUES',
                    *['UPDATE OR '+choice+' orders SET n=99' for choice in ['ROLLBACK','ABORT','FAIL','IGNORE','REPLACE']],
                    'WITH chosen(n) AS (SELECT 99) UPDATE OR IGNORE orders SET n=(SELECT n FROM chosen)']
                for prefix in ['EXPLAIN','EXPLAIN QUERY PLAN']:
                    for body in bodies:
                        payload=await call('query',{'sql':prefix+' '+body})
                        assert payload['success'] is after,payload
                        if not after:
                            assert payload['error_code'] in {'table_access_denied','view_scope_unresolved','sql_parse_failed'},payload
                    assert (await call('query',{'sql':prefix+' UPDATE plain SET n=99'}))['success']
                    assert (await call('query',{'sql':prefix+' INSERT INTO main.orders VALUES(99)'},'shadow'))['success']
                    assert (await call('query',{'sql':prefix+' INSERT INTO orders VALUES(99)'},'shadow'))['error_code']=='table_access_denied'
                    assert (await call('query',{'sql':prefix+' INSERT INTO main.orders VALUES(99)'},'attached'))['success'] is after
                    for name in ['bad_read','bad_write','bad_function','mixed_count','when_count']:
                        payload=await call('query',{'sql':prefix+' INSERT INTO orders VALUES(99)'},name)
                        assert not payload['success']
                        expected={'expensive_function_denied'} if name=='bad_function' else {'table_access_denied','view_scope_unresolved'}
                        assert payload['error_code'] in expected,payload
                for body in ['UPDATE orders SET n=99','INSERT INTO orders VALUES(99)','WITH chosen(n) AS (SELECT 99) REPLACE INTO orders SELECT n FROM chosen','UPDATE OR IGNORE orders SET n=99']:
                    payload=await call('query',{'sql':body})
                    assert not payload['success']
                    if after:
                        assert payload['error_code']=='read_only_required',payload
                discovered=await call('list_skills',{'detail_level':'full'})
                assert len(discovered['skills'])==(2 if after else 0),discovered
                if after:
                    assert all(item['executable'] and item['analysis_complete'] for item in discovered['skills'])
                    for name in ['with-replace-plan','update-or-plan']:
                        detail=await call('get_skill_detail',{'skill_name':name,'detail_level':'full'})
                        assert detail['skill']['schema_ready'] and detail['skill']['inferred_tables']==['orders'],detail
                        assert (await call('execute_query_skill',{'skill_name':name,'params':{'value':99}}))['success']
                assert (await call('query',{'sql':'SELECT validation_calls() AS n'}))['data']==[{'n':0}]
                for name in FIXTURES:
                    assert (await call('query',{'sql':'SELECT validation_changes() AS n'},name))['data']==changes[name]
        for name,before in snapshots.items():
            with sqlite3.connect(root/(name+'.sqlite')) as db:
                assert {table:db.execute('SELECT * FROM '+table).fetchall() for table in before}==before
    output=dict(version=sql_safety_executor.__version__,expected=args.expect,calls=len(records),records=records,
        data_unchanged=True,restricted_function_calls=0,source_sha256={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in {'.py','.md'}},
        scope='Private real child stdio, both negotiated protocols, decoded application results not full protocol frames. Persistent tables checked in full, serving connection total_changes unchanged for temp/attached fixtures. CLI/package/resource checks separate; no model tokens measured.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(gzip.compress((json.dumps(output,ensure_ascii=False,indent=2)+'\n').encode(),mtime=0))
    print(json.dumps(dict(version=output['version'],expected=args.expect,calls=len(records),passed=True)))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--expect',choices=['before','after'],default='after')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.source=args.source.resolve() if args.source else None
    args.output=args.output.resolve()
    if args.output.exists():
        parser.error('Output exists; select a fresh evidence path')
    os.chdir(tempfile.gettempdir())
    asyncio.run(check(args))
