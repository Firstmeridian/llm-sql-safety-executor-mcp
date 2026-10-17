"""Real child-stdio trigger-CTE checks in both Client protocols, private DBs only.

Decoded application results are not complete JSON-RPC frames or model trials.
Use --source for current/frozen source, or an independent installed interpreter.
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

BASE=('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n);'
      'CREATE TABLE hidden(n); INSERT INTO hidden VALUES(17); CREATE VIEW normal_view AS SELECT n FROM hidden;')


def count(body='SELECT 7',hint='MATERIALIZED',name='chosen'):
    return f'WITH {name}(n) AS {hint} ({body}) SELECT COUNT(*) FROM {name}'


def trigger(body,when='',name='log_orders'):
    return f'CREATE TRIGGER {name} AFTER INSERT ON orders {when} BEGIN {body}; END;'


CASES={
    'constant':(trigger(f'INSERT INTO audit_log SELECT ({count()})'),None),
    'physical':(trigger(f'INSERT INTO audit_log SELECT ({count("SELECT n FROM orders")})'),None),
    'implicit':(trigger(f'SELECT ({count(hint="")})'),None),
    'not_materialized':(trigger(f'SELECT ({count(hint="NOT MATERIALIZED")})'),None),
    'view_source':(trigger(f'SELECT ({count("SELECT n FROM normal_view")})'),None),
    'nested':(trigger(f'SELECT ({count("WITH inner_choice(n) AS MATERIALIZED (SELECT 7) SELECT n FROM inner_choice")})'),None),
    'when':(trigger('INSERT INTO audit_log VALUES(NEW.n)',f'WHEN ({count()})>0'),None),
    'select_only':(trigger(f'SELECT ({count()})'),None),
    'same_fragments':(trigger(f'SELECT ({count()}); SELECT ({count("SELECT n FROM orders")})'),None),
    'nested_trigger':(trigger('INSERT INTO audit_log VALUES(NEW.n)')+f'CREATE TRIGGER log_audit AFTER INSERT ON audit_log BEGIN SELECT ({count()}); END;',None),
    'two_trigger_labels':(trigger(f'SELECT ({count()})')+trigger(f'SELECT ({count("SELECT n FROM orders")})',name='other_log'),None),
    'bad_source':(trigger(f'SELECT ({count("SELECT n FROM hidden")})'),'table_access_denied'),
    'bad_target':(trigger(f'INSERT INTO hidden SELECT ({count()})'),'table_access_denied'),
    'bad_other_fragment':(trigger(f'SELECT ({count()}); SELECT COUNT(*) FROM hidden'),'table_access_denied'),
    'bad_function':(trigger(f'SELECT ({count("SELECT SLEEP(0)")})'),'expensive_function_denied'),
    'source_collision':(trigger(f'SELECT ({count()})',name='chosen'),'view_scope_unresolved'),
    'when_begin':('ALTER TABLE orders ADD COLUMN "begin";'+trigger('INSERT INTO audit_log VALUES(NEW.n)','WHEN NEW.begin IS NULL'),None),
    'when_begin_case':('ALTER TABLE orders ADD COLUMN "begin";'+trigger('SELECT 7','WHEN (CASE WHEN NEW.n>0 THEN NEW.begin ELSE 0 END) IS NULL'),None),
    'when_begin_subquery':('ALTER TABLE orders ADD COLUMN "begin"; ALTER TABLE audit_log ADD COLUMN "begin";'+trigger('SELECT 7','WHEN EXISTS(SELECT begin FROM audit_log)'),None),
    'when_begin_denied':('ALTER TABLE orders ADD COLUMN "begin";'+trigger('SELECT 7','WHEN COALESCE(NEW.begin,(SELECT n FROM hidden)) IS NULL'),'table_access_denied'),
}


def insert_body(name):
    return 'INSERT INTO orders(n) VALUES(99)' if name.startswith('when_') else 'INSERT INTO orders VALUES(99)'


async def check(args):
    if args.source:
        sys.path.insert(0,str(args.source))
    import sql_safety_executor
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    package=Path(sql_safety_executor.__file__).parent
    assert package.is_relative_to(args.source) if args.source else 'site-packages' in str(package)
    records=[]
    with tempfile.TemporaryDirectory(prefix='v382-trigger-cte-') as temporary:
        root=Path(temporary)
        snapshots={}
        for name,(ddl,_) in CASES.items():
            with sqlite3.connect(root/(name+'.sqlite')) as native:
                native.create_function('SLEEP',1,lambda _:0)
                native.executescript(BASE+ddl)
                for prefix in ['EXPLAIN','EXPLAIN QUERY PLAN']:
                    native.execute(prefix+' '+insert_body(name)).fetchall()
                snapshots[name]={table:native.execute('SELECT * FROM '+table).fetchall() for table in ['orders','audit_log','hidden']}
        (root/'server.toml').write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="constant"\n')
        connections='schema_version=1\n'
        for name in CASES:
            connections+=f'[connections.{name}]\ntype="sqlite"\nsqlite.path="{name}.sqlite"\nread.mode="allowlist"\nread.tables=["orders","audit_log","normal_view"]\n'
        (root/'connections.toml').write_text(connections)
        (root/'skills.toml').write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        skill=root/'skills'/'trigger-cte-plan'
        skill.mkdir(parents=True)
        (skill/'skill_def.md').write_text('---\nname: trigger-cte-plan\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private trigger CTE plan\nconnection_ids: [constant]\nparams:\n  value:\n    type: int\n    required: true\n---\n')
        (skill/'query.sql').write_text('EXPLAIN INSERT INTO orders VALUES(:value)')
        when_skill=root/'skills'/'when-begin-plan'
        when_skill.mkdir(parents=True)
        (when_skill/'skill_def.md').write_text('---\nname: when-begin-plan\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private WHEN begin-column plan\nconnection_ids: [when_begin]\nparams:\n  value:\n    type: int\n    required: true\n---\n')
        (when_skill/'query.sql').write_text('EXPLAIN INSERT INTO orders(n) VALUES(:value)')
        source_line=f'import sys; sys.path.insert(0,{str(args.source)!r})\n' if args.source else ''
        launcher=root/'launcher.py'
        launcher.write_text(source_line+'from sql_safety_executor import create_server,load_config\n'
            'server=create_server(load_config("server.toml"))\ncalls=[]\n'
            f'for name in {list(CASES)!r}:\n'
            ' adapter=server.gateway_runtime.registry.get_adapter(name)\n assert adapter.connect()\n'
            ' with adapter._engine.connect() as connection:\n'
            '  raw=connection.connection.dbapi_connection\n'
            '  raw.create_function("SLEEP",1,lambda _:calls.append(1) or 0)\n'
            '  raw.create_function("validation_calls",0,lambda:len(calls))\n'
            '  raw.create_function("validation_changes",0,lambda c=raw:c.total_changes)\n'
            'server.run(transport="stdio",show_banner=False)\n')
        for mode in ['auto','legacy']:
            async with Client(StdioTransport(command=sys.executable,args=[str(launcher)],cwd=str(root)),mode=mode) as client:
                async def call(tool,arguments,connection='constant'):
                    arguments={**arguments,'connection_id':connection}
                    response=await client.call_tool(tool,arguments,raise_on_error=False)
                    payload=response.structured_content
                    assert not response.is_error and isinstance(payload,dict),response
                    content=[item.text for item in response.content if item.type=='text']
                    assert len(content)==1 and json.loads(content[0])==payload
                    records.append(dict(mode=mode,protocol=client.protocol_version,tool=tool,arguments=arguments,
                        structured=payload,isError=response.is_error,content=[item.model_dump(mode='json',exclude_none=True) for item in response.content]))
                    return payload
                before={name:(await call('query',{'sql':'SELECT validation_changes() AS n'},name))['data'] for name in CASES}
                for name,(_,error) in CASES.items():
                    for prefix in ['EXPLAIN','EXPLAIN QUERY PLAN']:
                        payload=await call('query',{'sql':prefix+' '+insert_body(name)},name)
                        assert payload['success'] is (error is None),payload
                        if error:
                            assert payload['error_code']==error,payload
                    assert (await call('query',{'sql':insert_body(name)},name))['error_code']=='read_only_required'
                discovered=await call('list_skills',{'detail_level':'full'})
                assert len(discovered['skills'])==1 and discovered['skills'][0]['executable'],discovered
                detail=await call('get_skill_detail',{'skill_name':'trigger-cte-plan','detail_level':'full'})
                assert detail['skill']['schema_ready'] and detail['skill']['inferred_tables']==['orders'],detail
                assert (await call('execute_query_skill',{'skill_name':'trigger-cte-plan','params':{'value':99}}))['success']
                when_discovered=await call('list_skills',{'detail_level':'full'},'when_begin')
                assert len(when_discovered['skills'])==1 and when_discovered['skills'][0]['executable'],when_discovered
                when_detail=await call('get_skill_detail',{'skill_name':'when-begin-plan','detail_level':'full'},'when_begin')
                assert when_detail['skill']['schema_ready'],when_detail
                assert (await call('execute_query_skill',{'skill_name':'when-begin-plan','params':{'value':99}},'when_begin'))['success']
                assert (await call('query',{'sql':'SELECT validation_calls() AS n'}))['data']==[{'n':0}]
                for name in CASES:
                    assert (await call('query',{'sql':'SELECT validation_changes() AS n'},name))['data']==before[name]
                    assert (await call('query',{'sql':'SELECT n FROM hidden'},name))['error_code']=='table_access_denied'
        for name,before in snapshots.items():
            with sqlite3.connect(root/(name+'.sqlite')) as native:
                assert {table:native.execute('SELECT * FROM '+table).fetchall() for table in before}==before
    output=dict(version=sql_safety_executor.__version__,calls=len(records),records=records,
        data_unchanged=True,restricted_function_calls=0,
        source_sha256={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in {'.py','.md'}},
        scope=__doc__)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(gzip.compress((json.dumps(output,ensure_ascii=False,indent=2)+'\n').encode(),mtime=0))
    print(json.dumps(dict(version=output['version'],calls=len(records),passed=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.source=args.source.resolve() if args.source else None
    args.output=args.output.resolve()
    if args.output.exists():
        parser.error('Output exists; choose a fresh path')
    os.chdir(tempfile.gettempdir())
    asyncio.run(check(args))
