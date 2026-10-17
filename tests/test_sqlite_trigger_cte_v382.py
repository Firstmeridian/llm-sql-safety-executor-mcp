"""Trigger-local CTE counts preserve native plans and independent grants."""
import json
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.database.authorizer import SQLiteReadGuard
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle


BASE = ('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n);'
        'CREATE TABLE hidden(n); INSERT INTO hidden VALUES(17);'
        'CREATE VIEW normal_view AS SELECT n FROM hidden;')


def count_cte(body='SELECT 7', hint='MATERIALIZED', name='chosen'):
    return f'WITH {name}(n) AS {hint} ({body}) SELECT COUNT(*) FROM {name}'


def trigger(body, when='', name='log_orders', event='INSERT'):
    return f'CREATE TRIGGER {name} AFTER {event} ON orders {when} BEGIN {body}; END;'


POSITIVE = [
    *[(f'{hint or "implicit"}_{body}', 'INSERT INTO orders VALUES(99)',
       trigger(f'INSERT INTO audit_log SELECT ({count_cte(body,hint)})'))
      for hint in ['MATERIALIZED','','NOT MATERIALIZED']
      for body in ['SELECT 7','SELECT n FROM orders','SELECT n FROM normal_view']],
    ('nested', 'INSERT INTO orders VALUES(99)', trigger(f'INSERT INTO audit_log SELECT ({count_cte("WITH inner_choice(n) AS MATERIALIZED (SELECT 7) SELECT n FROM inner_choice")})')),
    ('recursive', 'INSERT INTO orders VALUES(99)', trigger('INSERT INTO audit_log SELECT (WITH RECURSIVE chosen(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM chosen WHERE n<3) SELECT COUNT(*) FROM chosen)')),
    ('when', 'INSERT INTO orders VALUES(99)', trigger('INSERT INTO audit_log VALUES(NEW.n)', f'WHEN ({count_cte()})>0')),
    ('select_only', 'INSERT INTO orders VALUES(99)', trigger(f'SELECT ({count_cte()})')),
    ('same_name_fragments', 'INSERT INTO orders VALUES(99)', trigger(f'INSERT INTO audit_log SELECT ({count_cte()}); INSERT INTO audit_log SELECT ({count_cte("SELECT n FROM orders")})')),
    ('same_name_scopes', 'INSERT INTO orders VALUES(99)', trigger('INSERT INTO audit_log SELECT (WITH chosen(n) AS (SELECT 7) SELECT (WITH chosen(n) AS MATERIALIZED (SELECT 13) SELECT COUNT(*) FROM chosen))')),
    ('nested_trigger', 'INSERT INTO orders VALUES(99)', trigger('INSERT INTO audit_log VALUES(NEW.n)')+'CREATE TRIGGER log_audit AFTER INSERT ON audit_log BEGIN SELECT ('+count_cte()+'); END;'),
    ('update_old_new', 'UPDATE orders SET n=99', trigger(f'INSERT INTO audit_log SELECT ({count_cte("SELECT OLD.n+NEW.n")})',event='UPDATE')),
    ('delete_old', 'DELETE FROM orders', trigger(f'SELECT ({count_cte("SELECT OLD.n")})',event='DELETE')),
    ('quoted_unicode', 'INSERT INTO orders VALUES(99)', trigger(f'SELECT ({count_cte(name=chr(34)+" f K "+chr(34))})',name='" log.K "')),
    ('two_trigger_same_label', 'INSERT INTO orders VALUES(99)', trigger(f'SELECT ({count_cte()})')+trigger(f'SELECT ({count_cte("SELECT n FROM orders")})',name='another_log')),
    ('two_trigger_nested_label', 'INSERT INTO orders VALUES(99)', trigger(f'SELECT ({count_cte("WITH seed(n) AS (SELECT 7) SELECT n FROM seed")})')+trigger(f'SELECT ({count_cte("WITH seed(n) AS (SELECT 13) SELECT n FROM seed")})',name='another_log')),
]


@pytest.mark.parametrize('mode',['auto','legacy'])
@pytest.mark.parametrize('prefix',['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('name,sql,ddl',POSITIVE,ids=[case[0] for case in POSITIVE])
async def test_trigger_cte_plans_match_native_without_evaluation(bundle,tmp_path,mode,prefix,name,sql,ddl):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log','normal_view']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+ddl)
        native.execute(prefix+' '+sql).fetchall()  # QUERY PLAN may validly be empty.
        before={table:native.execute('SELECT * FROM '+table).fetchall() for table in ['orders','audit_log','hidden']}
    server=create_server(load_config(save()))
    try:
        async with Client(server,mode=mode) as client:
            response=await client.call_tool('query',{'sql':prefix+' '+sql})
            payload=response.structured_content
            assert payload['success'],payload
            assert json.loads(next(item.text for item in response.content if item.type=='text'))==payload
            assert (await client.call_tool('query',{'sql':sql})).structured_content['error_code']=='read_only_required'
            assert (await client.call_tool('query',{'sql':'SELECT n FROM hidden'})).structured_content['error_code']=='table_access_denied'
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert {table:[tuple(row) for row in adapter.execute('SELECT * FROM '+table)] for table in before}==before
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


NEGATIVE = [
    ('ungranted_base', trigger(f'SELECT ({count_cte("SELECT n FROM hidden")})'), 'table_access_denied'),
    ('separate_count', trigger(f'SELECT ({count_cte()}); SELECT COUNT(*) FROM hidden'), 'table_access_denied'),
    ('same_label_other_fragment', trigger(f'SELECT ({count_cte()}); SELECT ({count_cte("SELECT n FROM hidden")})'), 'table_access_denied'),
    ('same_label_other_scope', trigger('SELECT (WITH chosen(n) AS (SELECT 7) SELECT (WITH chosen(n) AS MATERIALIZED (SELECT n FROM hidden) SELECT COUNT(*) FROM chosen))'), 'table_access_denied'),
    ('ungranted_target', trigger(f'INSERT INTO hidden SELECT ({count_cte()})'), 'table_access_denied'),
    ('qualified_collision', 'CREATE TABLE chosen(n); INSERT INTO chosen VALUES(99);'+trigger(f'SELECT ({count_cte("SELECT n FROM main.chosen")})'), 'table_access_denied'),
    ('source_collision', trigger(f'SELECT ({count_cte()})',name='chosen'), 'view_scope_unresolved'),
    ('expensive', trigger(f'SELECT ({count_cte("SELECT SLEEP(0)")})'), 'expensive_function_denied'),
    ('when_function', trigger('SELECT 7',f'WHEN ({count_cte("SELECT SLEEP(0)")})>0'), 'expensive_function_denied'),
]


@pytest.mark.parametrize('mode',['auto','legacy'])
@pytest.mark.parametrize('prefix',['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('name,ddl,code',NEGATIVE,ids=[case[0] for case in NEGATIVE])
async def test_trigger_cte_context_does_not_extend_grants(bundle,tmp_path,mode,prefix,name,ddl,code):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log','normal_view']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+ddl)
    server=create_server(load_config(save()))
    calls=[]
    try:
        async with Client(server,mode=mode) as client:
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.connect()
            with adapter._engine.connect() as connection:
                connection.connection.dbapi_connection.create_function('SLEEP',1,lambda _:calls.append(1) or 0)
            payload=(await client.call_tool('query',{'sql':prefix+' INSERT INTO orders VALUES(99)'})).structured_content
            assert payload['error_code']==code,payload
            assert not calls
            assert adapter.execute('SELECT n FROM orders')==[(7,)]
            assert adapter.execute('SELECT n FROM hidden')==[(17,)]
            assert adapter.execute('SELECT n FROM audit_log')==[]
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


def test_verified_trigger_cte_event_requires_exact_plan_and_source():
    guard=SQLiteReadGuard(ConnectionPolicy(allowed_tables=frozenset({'orders'})),'main')
    guard.trigger_cte_reads.add(('chosen','log_orders'))
    assert guard.authorize(sqlite3.SQLITE_READ,'chosen','',None,'log_orders')==sqlite3.SQLITE_DENY
    guard.explain_dml=True
    assert guard.authorize(sqlite3.SQLITE_READ,'chosen','',None,'log_orders')==sqlite3.SQLITE_OK
    for table,column,database,source in [('chosen','n',None,'log_orders'),('chosen','','temp','log_orders'),('chosen','',None,'other'),('other','',None,'log_orders')]:
        assert guard.authorize(sqlite3.SQLITE_READ,table,column,database,source)==sqlite3.SQLITE_DENY


def test_cte_preparation_deadline_and_catalog_budget_clean_up(bundle,tmp_path,monkeypatch):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger(f'SELECT ({count_cte()})'))
    server=create_server(load_config(save()))
    try:
        adapter=server.gateway_runtime.registry.get_adapter('demo')
        policy=server.gateway_runtime.registry.get_config('demo').policy
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy,timeout=0)
        assert denied.value.error_code=='query_timeout'
        from sql_safety_executor.database import sqlite as module
        original=module.build_read_guard
        def bounded(*args,**kwargs):
            kwargs['catalog_limit']=min(kwargs.get('catalog_limit',2048),1)
            return original(*args,**kwargs)
        monkeypatch.setattr(module,'build_read_guard',bounded)
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy)
        assert denied.value.error_code=='view_scope_unresolved'
        assert adapter._active_guard is None and adapter._read_request is None
        assert adapter.execute('SELECT n FROM orders')==[(7,)]
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('schema',['main','temp','aux'])
@pytest.mark.parametrize('granted',[False,True])
def test_trigger_cte_catalog_collision_keeps_independent_physical_grant(bundle,tmp_path,schema,granted):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']+([schema+'.chosen'] if granted else [])}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger(f'SELECT ({count_cte()})'))
    server=create_server(load_config(save()))
    try:
        adapter=server.gateway_runtime.registry.get_adapter('demo')
        policy=server.gateway_runtime.registry.get_config('demo').policy
        assert adapter.connect()
        with adapter._engine.connect() as connection:
            raw=connection.connection.dbapi_connection
            if schema=='aux':
                raw.execute("ATTACH ':memory:' AS aux")
            raw.executescript(f'CREATE TABLE {schema}.chosen(n); INSERT INTO {schema}.chosen VALUES(99);')
        for prefix in ['EXPLAIN','EXPLAIN QUERY PLAN']:
            if granted:
                adapter.execute_read(prefix+' INSERT INTO orders VALUES(99)',policy=policy)
            else:
                with pytest.raises(DatabaseQueryError) as denied:
                    adapter.execute_read(prefix+' INSERT INTO orders VALUES(99)',policy=policy)
                assert denied.value.error_code=='table_access_denied'
        assert adapter.execute(f'SELECT n FROM {schema}.chosen')==[(99,)]
        assert adapter.execute('SELECT n FROM orders')==[(7,)]
    finally:
        server.gateway_runtime.close()


def test_trigger_cte_rebuilds_after_catalog_change_and_never_queries_in_callback(bundle,tmp_path,monkeypatch):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log']}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript(BASE+trigger(f'SELECT ({count_cte()})'))
    server=create_server(load_config(save()))
    active=False
    trace=[]
    original=SQLiteReadGuard.authorize
    def observed(self,*args):
        nonlocal active
        assert not active
        active=True
        try:
            return original(self,*args)
        finally:
            active=False
    monkeypatch.setattr(SQLiteReadGuard,'authorize',observed)
    try:
        adapter=server.gateway_runtime.registry.get_adapter('demo')
        policy=server.gateway_runtime.registry.get_config('demo').policy
        assert adapter.connect()
        with adapter._engine.connect() as connection:
            raw=connection.connection.dbapi_connection
            raw.set_trace_callback(lambda sql:trace.append((sql,active)))
        adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy)
        raw.executescript('DROP TRIGGER log_orders;'+trigger(f'SELECT ({count_cte("SELECT n FROM hidden")})'))
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy)
        assert denied.value.error_code=='table_access_denied'
        assert trace and not any(inside for _,inside in trace)
        assert adapter.execute_read('SELECT n FROM orders',policy=policy)==[(7,)]
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()
