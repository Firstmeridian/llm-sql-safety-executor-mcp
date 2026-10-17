"""Trigger WHEN expression roles cannot be confused with its BEGIN marker."""
import json
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import analyze_sqlite_trigger
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from tests.test_v38_config import bundle as bundle


BASE = ('CREATE TABLE orders(n,"begin"); INSERT INTO orders VALUES(7,NULL);'
        'CREATE TABLE audit_log(n,"begin"); INSERT INTO audit_log VALUES(13,NULL);'
        'CREATE TABLE hidden(n); INSERT INTO hidden VALUES(17);')

CASES = [
    ('new', 'INSERT', 'NEW.begin IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
    ('old_update', 'UPDATE', 'OLD.begin IS NULL', 'UPDATE orders SET n=99'),
    ('old_delete', 'DELETE', 'OLD.begin IS NULL', 'DELETE FROM orders'),
    ('case', 'INSERT', '(CASE WHEN NEW.n>0 THEN NEW.begin ELSE 0 END) IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
    ('function', 'INSERT', 'COALESCE(NEW.begin,0)=0', 'INSERT INTO orders(n) VALUES(99)'),
    ('subquery', 'INSERT', 'EXISTS(SELECT begin FROM audit_log)', 'INSERT INTO orders(n) VALUES(99)'),
    ('cte_name', 'INSERT', 'EXISTS(WITH begin(n) AS (SELECT 7) SELECT n FROM begin)', 'INSERT INTO orders(n) VALUES(99)'),
    ('quoted', 'INSERT', 'NEW."begin" IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
    ('bracket', 'INSERT', 'NEW.[begin] IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
    ('backtick', 'INSERT', 'NEW.`begin` IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
    ('string_comment', 'INSERT', "NEW.n>length('BEGIN;END') /* BEGIN; */", 'INSERT INTO orders(n) VALUES(99)'),
    ('materialized', 'INSERT', '(WITH chosen(n) AS MATERIALIZED (SELECT 7) SELECT COUNT(*) FROM chosen)>0 AND NEW.begin IS NULL', 'INSERT INTO orders(n) VALUES(99)'),
]


def trigger(event='INSERT', when='NEW.begin IS NULL', body='INSERT INTO audit_log(n) VALUES(99)', row=True):
    return ('CREATE TRIGGER log_orders AFTER '+event+' ON main.orders '+('FOR EACH ROW ' if row else '')+
            'WHEN '+when+' BEGIN '+body+'; END;')


@pytest.mark.parametrize('mode', ['auto','legacy'])
@pytest.mark.parametrize('prefix', ['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('name,event,when,body', CASES, ids=[case[0] for case in CASES])
async def test_when_identifier_plans_match_native_and_preserve_rows(bundle,tmp_path,mode,prefix,name,event,when,body):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger(event,when,row=name!='new'))
        native.execute(prefix+' '+body).fetchall()  # An empty QUERY PLAN is valid.
        before={t:native.execute('SELECT * FROM '+t).fetchall() for t in ['orders','audit_log','hidden']}
    server=create_server(load_config(save()))
    try:
        async with Client(server,mode=mode) as client:
            response=await client.call_tool('query',{'sql':prefix+' '+body})
            payload=response.structured_content
            assert payload['success'],payload
            assert json.loads(next(x.text for x in response.content if x.type=='text'))==payload
            assert (await client.call_tool('query',{'sql':body})).structured_content['error_code']=='read_only_required'
            assert (await client.call_tool('query',{'sql':'SELECT n FROM hidden'})).structured_content['error_code']=='table_access_denied'
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert {t:[tuple(r) for r in adapter.execute('SELECT * FROM '+t)] for t in before}==before
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('mode', ['auto','legacy'])
@pytest.mark.parametrize('prefix', ['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('when,body,code', [
    ('COALESCE(NEW.begin,(SELECT n FROM hidden)) IS NULL','INSERT INTO audit_log(n) VALUES(99)','table_access_denied'),
    ('NEW.begin IS NULL','INSERT INTO audit_log(n) SELECT COUNT(*) FROM hidden','table_access_denied'),
    ('NEW.begin IS NULL','INSERT INTO hidden VALUES(99)','table_access_denied'),
    ('COALESCE(NEW.begin,SLEEP(0))=0','INSERT INTO audit_log(n) VALUES(99)','expensive_function_denied'),
    ('NEW.begin IS NULL','INSERT INTO audit_log(n) VALUES(SLEEP(0))','expensive_function_denied'),
])
async def test_when_boundary_retains_dependency_and_function_refusals(bundle,tmp_path,mode,prefix,when,body,code):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger(when=when,body=body))
    server=create_server(load_config(save()));calls=[]
    try:
        async with Client(server,mode=mode) as client:
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.connect()
            with adapter._engine.connect() as db:
                db.connection.dbapi_connection.create_function('SLEEP',1,lambda _:calls.append(1) or 0)
            payload=(await client.call_tool('query',{'sql':prefix+' INSERT INTO orders(n) VALUES(99)'})).structured_content
            assert not payload['success'] and payload['error_code']==code,payload
            assert not calls
            assert adapter.execute('SELECT n FROM orders')==[(7,)]
            assert adapter.execute('SELECT n FROM audit_log')==[(13,)]
            assert adapter.execute('SELECT n FROM hidden')==[(17,)]
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('row',[False,True])
def test_when_region_analysis_keeps_original_expression_and_body(row):
    sql=trigger(when='NEW.begin IS NULL AND EXISTS(SELECT begin FROM audit_log)',row=row)
    results=analyze_sqlite_trigger(sql,DialectContext('sqlite'))
    assert results is not None and len(results)==2
    assert 'NEW.begin IS NULL' in results[0].source_sql
    assert {r for item in results for r in item.relations}=={RelationReference('audit_log')}
    assert results[1].source_sql=='INSERT INTO audit_log(n) VALUES(99)'


@pytest.mark.parametrize('invalid', [
    'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN BEGIN SELECT 7; END;',
    'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN NEW.begin IS NULL SELECT 7; END;',
    'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN NEW.begin IS NULL BEGIN VACUUM; END;',
    'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN NEW.begin IS NULL BEGIN SELECT 7 END;',
    'CREATE TRIGGER log_orders AFTER INSERT ON orders FOR "EACH" ROW WHEN NEW.n>0 BEGIN SELECT 7; END;',
])
def test_when_region_rejects_incomplete_or_unsupported_definitions(invalid):
    assert analyze_sqlite_trigger(invalid,DialectContext('sqlite')) is None


@pytest.mark.parametrize('mode',['auto','legacy'])
@pytest.mark.parametrize('prefix',['EXPLAIN','EXPLAIN QUERY PLAN'])
async def test_when_plan_skill_discovery_readiness_and_bound_execution(bundle,tmp_path,mode,prefix):
    _,connections,skills,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']}
    directory=tmp_path/'skills';skill=directory/'when-plan';skill.mkdir(parents=True)
    (skill/'skill_def.md').write_text('---\nname: when-plan\ntype: query\nsource: query.sql\nrisk: low\ndescription: Private WHEN plan\nconnection_ids: [demo]\nparams:\n  value:\n    type: int\n    required: true\n---\n')
    (skill/'query.sql').write_text(prefix+' INSERT INTO orders(n) VALUES(:value)')
    skills['skills']['directory']=str(directory)
    skills['skills']['readiness']={'check_schema':True}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger())
    server=create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server,mode=mode) as client:
            found=(await client.call_tool('list_skills',{'detail_level':'full'})).structured_content
            assert found['skills'][0]['executable'],found
            detail=(await client.call_tool('get_skill_detail',{'skill_name':'when-plan','detail_level':'full'})).structured_content
            assert detail['skill']['schema_ready'],detail
            result=(await client.call_tool('execute_query_skill',{'skill_name':'when-plan','params':{'value':99}})).structured_content
            assert result['success'],result
            assert (await client.call_tool('query',{'sql':'INSERT INTO orders(n) SELECT 99 WHERE 0'})).structured_content['error_code']=='read_only_required'
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.execute('SELECT n FROM orders')==[(7,)]
            assert adapter.execute('SELECT n FROM audit_log')==[(13,)]
    finally:
        server.gateway_runtime.close()
