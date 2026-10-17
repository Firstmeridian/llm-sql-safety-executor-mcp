"""SQLite plans retain native syntax, indirect scope, and no execution effects."""
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import analyze_sql, analyze_sqlite_trigger
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.authorizer import SQLiteReadGuard
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from tests.test_v38_config import bundle as bundle


PLAN_BODIES = [
    'WITH chosen(n) AS (SELECT 99) REPLACE INTO orders SELECT n FROM chosen',
    'WITH seed(n) AS (SELECT 99), chosen(n) AS (SELECT n FROM seed) REPLACE INTO orders SELECT n FROM chosen RETURNING n',
    'WITH chosen(n) AS (WITH seed(n) AS (SELECT 99) SELECT n FROM seed) REPLACE INTO orders SELECT n FROM chosen',
    'WITH RECURSIVE chosen(n) AS (SELECT 99) /* main */ REPLACE INTO orders DEFAULT VALUES',
    "WITH replace(n) AS (SELECT length(replace('REPLACE','R','r'))) REPLACE INTO orders SELECT n FROM replace",
    *['UPDATE OR '+choice+' orders SET n=99' for choice in ['ROLLBACK','ABORT','FAIL','IGNORE','REPLACE']],
    *['WITH chosen(n) AS (SELECT 99) UPDATE OR '+choice+' orders SET n=(SELECT n FROM chosen)' for choice in ['ROLLBACK','ABORT','FAIL','IGNORE','REPLACE']],
]


@pytest.mark.parametrize('prefix', ['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('body', PLAN_BODIES)
def test_plan_dialect_forms_keep_native_target_and_original_sql(prefix, body):
    sql=prefix+' '+body
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7);')
        db.execute(sql).fetchall()
        assert db.execute('SELECT n FROM orders').fetchall()==[(7,)]
    result=analyze_sql(sql,DialectContext('sqlite'))
    assert result.complete, result
    assert result.statement_kind=='explain'
    assert result.explain_payload in {'insert','update'}
    assert result.relations==(RelationReference('orders'),)
    assert result.source_sql==sql


TRIGGERS = [
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log VALUES(NEW.n); END;'),
    ('UPDATE orders SET n=99', 'CREATE TRIGGER log_orders AFTER UPDATE ON orders BEGIN INSERT INTO audit_log VALUES(OLD.n+NEW.n); END;'),
    ('DELETE FROM orders', 'CREATE TRIGGER log_orders AFTER DELETE ON orders BEGIN INSERT INTO audit_log VALUES(OLD.n); END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders WHEN NEW.n>0 BEGIN INSERT INTO audit_log VALUES(99); END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT n FROM lookup_values; END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM lookup_values; END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT n FROM lookup_view; END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM lookup_view; END;'),
    ('INSERT INTO orders VALUES(99)', 'CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log VALUES(99); END; CREATE TRIGGER log_audit AFTER INSERT ON audit_log BEGIN INSERT INTO lookup_values VALUES(NEW.n); END;'),
    ('INSERT INTO orders_view VALUES(99)', 'CREATE TRIGGER log_orders INSTEAD OF INSERT ON orders_view BEGIN INSERT INTO orders VALUES(NEW.n); END;'),
]


@pytest.mark.parametrize('mode', ['auto','legacy'])
@pytest.mark.parametrize('prefix', ['EXPLAIN','EXPLAIN QUERY PLAN'])
@pytest.mark.parametrize('body,trigger', TRIGGERS)
async def test_authorized_trigger_plan_checks_reads_and_keeps_rows(bundle,tmp_path,mode,prefix,body,trigger):
    _,connections,_,save=bundle
    grants=['orders','audit_log','lookup_view','orders_view']
    # A view grant permits indirect reads, not direct reads of its source.
    if 'lookup_view' not in trigger:
        grants.append('lookup_values')
    connections['connections']['demo']['read']={'mode':'allowlist','tables':grants}
    with sqlite3.connect(tmp_path/'db.sqlite') as native:
        native.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n); CREATE TABLE lookup_values(n); INSERT INTO lookup_values VALUES(13); CREATE VIEW lookup_view AS SELECT n FROM lookup_values; CREATE VIEW orders_view AS SELECT n FROM orders;'+trigger)
        native.execute(prefix+' '+body).fetchall()
        before={table:native.execute('SELECT * FROM '+table).fetchall() for table in ['orders','audit_log','lookup_values']}
    server=create_server(load_config(save()))
    try:
        async with Client(server,mode=mode) as client:
            payload=(await client.call_tool('query',{'sql':prefix+' '+body})).structured_content
            assert payload['success'],payload
            assert (await client.call_tool('query',{'sql':body})).structured_content['error_code']=='read_only_required'
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert {table:[tuple(row) for row in adapter.execute('SELECT * FROM '+table)] for table in before}==before
            if 'lookup_values' not in grants:
                assert (await client.call_tool('query',{'sql':'SELECT n FROM lookup_values'})).structured_content['error_code']=='table_access_denied'
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('collision', [False, True])
async def test_plan_preparation_keeps_callbacks_sql_free_and_source_identity_distinct(bundle,tmp_path,monkeypatch,collision):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log','normal_view']}
    trigger_name='normal_view' if collision else 'log_orders'
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13); CREATE VIEW normal_view AS SELECT n FROM hidden; CREATE TRIGGER '+trigger_name+' AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; END;')
    server=create_server(load_config(save()))
    in_callback=False
    trace=[]
    original=SQLiteReadGuard.authorize
    def checked(self,*args):
        nonlocal in_callback
        assert not in_callback
        in_callback=True
        try:
            return original(self,*args)
        finally:
            in_callback=False
    monkeypatch.setattr(SQLiteReadGuard,'authorize',checked)
    try:
        adapter=server.gateway_runtime.registry.get_adapter('demo')
        policy=server.gateway_runtime.registry.get_config('demo').policy
        assert adapter.connect()
        with adapter._engine.connect() as db:
            db.connection.dbapi_connection.set_trace_callback(lambda sql:trace.append((sql,in_callback)))
        if collision:
            with pytest.raises(DatabaseQueryError) as denied:
                adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy)
            assert denied.value.error_code=='view_scope_unresolved'
        else:
            assert adapter.execute_read('EXPLAIN INSERT INTO orders VALUES(99)',policy=policy)
        assert trace and not any(active for _,active in trace)
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read('SELECT 7',policy=policy,timeout=0)
        assert denied.value.error_code=='query_timeout'
        assert adapter.execute('SELECT n FROM orders')==[(7,)]
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('body,code', [
    ('INSERT INTO audit_log SELECT COUNT(*) FROM hidden;', 'table_access_denied'),
    ('INSERT INTO audit_log SELECT n FROM hidden;', 'table_access_denied'),
    ('INSERT INTO hidden VALUES(99);', 'table_access_denied'),
    ('INSERT INTO audit_log VALUES(SLEEP(0));', 'expensive_function_denied'),
    ('INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; INSERT INTO audit_log SELECT COUNT(*) FROM hidden;', 'table_access_denied'),
])
@pytest.mark.parametrize('mode', ['auto','legacy'])
@pytest.mark.parametrize('prefix', ['EXPLAIN','EXPLAIN QUERY PLAN'])
async def test_trigger_plan_cannot_borrow_view_grants_or_evaluate_functions(bundle,tmp_path,body,code,mode,prefix):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log','normal_view']}
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13); CREATE VIEW normal_view AS SELECT n FROM hidden; CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN '+body+' END;')
    server=create_server(load_config(save()))
    calls=[]
    try:
        async with Client(server,mode=mode) as client:
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.connect()
            with adapter._engine.connect() as db:
                db.connection.dbapi_connection.create_function('SLEEP',1,lambda _:calls.append(True) or 0)
            payload=(await client.call_tool('query',{'sql':prefix+' INSERT INTO orders VALUES(99)'})).structured_content
            assert payload['error_code']==code,payload
            assert not calls
            assert adapter.execute('SELECT n FROM orders')==[(7,)]
            assert adapter.execute('SELECT n FROM hidden')==[(13,)]
            assert adapter.execute('SELECT n FROM audit_log')==[]
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('context', ['WHEN (SELECT COUNT(*) FROM hidden)>0', ''])
@pytest.mark.parametrize('cte_collision', [False,True])
async def test_ambiguous_count_cannot_hide_a_direct_trigger_or_when_dependency(bundle,tmp_path,context,cte_collision):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders','audit_log','normal_view']}
    body='INSERT INTO audit_log SELECT COUNT(*) FROM normal_view;'
    if not context:
        body+='INSERT INTO audit_log SELECT COUNT(*) FROM hidden;'
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13); CREATE VIEW normal_view AS SELECT n FROM hidden; CREATE TRIGGER log_orders AFTER INSERT ON orders '+context+' BEGIN '+body+' END;')
    server=create_server(load_config(save()))
    try:
        async with Client(server) as client:
            sql='EXPLAIN '+('WITH log_orders(n) AS (SELECT 99) ' if cte_collision else '')+'INSERT INTO orders VALUES(99)'
            result=(await client.call_tool('query',{'sql':sql})).structured_content
            assert not result['success'],result
            assert result['error_code'] in {'table_access_denied','view_scope_unresolved'}
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize('shadow', [False,True])
async def test_trigger_count_schema_is_proven_and_unknown_scope_refuses(bundle,tmp_path,shadow):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['main.orders','main.audit_log','aux.lookup_values']}
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n);')
    server=create_server(load_config(save()))
    try:
        async with Client(server) as client:
            adapter=server.gateway_runtime.registry.get_adapter('demo')
            assert adapter.connect()
            with adapter._engine.connect() as db:
                raw=db.connection.dbapi_connection
                raw.executescript("ATTACH ':memory:' AS aux; CREATE TABLE aux.lookup_values(n); INSERT INTO aux.lookup_values VALUES(13); CREATE TEMP TRIGGER log_orders AFTER INSERT ON main.orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM aux.lookup_values; END;")
                if shadow:
                    raw.executescript('CREATE TEMP TABLE lookup_values(n); INSERT INTO temp.lookup_values VALUES(17);')
            result=(await client.call_tool('query',{'sql':'EXPLAIN INSERT INTO main.orders VALUES(99)'})).structured_content
            # SQLite may provide an explicit aux database for this callback;
            # that identity remains valid even when a temp shadow exists.
            assert result['success'],result
            assert adapter.execute('SELECT n FROM main.orders')==[(7,)]
            assert adapter.execute('SELECT n FROM aux.lookup_values')==[(13,)]
            assert adapter.execute('SELECT n FROM main.audit_log')==[]
    finally:
        server.gateway_runtime.close()


def test_trigger_region_analysis_preserves_quotes_case_and_semicolons():
    definition='''CREATE TRIGGER "BEGIN.END" AFTER UPDATE OF "when" ON "orders" WHEN NEW.n>0 BEGIN
INSERT INTO "audit.log" SELECT CASE WHEN NEW.n>0 THEN length('BEGIN;END') ELSE 0 END;
INSERT INTO audit_log SELECT COUNT(*) FROM main." lookup "; END'''
    results=analyze_sqlite_trigger(definition,DialectContext('sqlite'))
    assert results is not None
    assert {ref for result in results for ref in result.relations}=={
        RelationReference('audit.log'),RelationReference('audit_log'),RelationReference(' lookup ','main')}
    for invalid in ['CREATE TRIGGER broken', 'CREATE VIEW x AS SELECT 1', definition.replace('INSERT INTO audit_log','VACUUM')]:
        assert analyze_sqlite_trigger(invalid,DialectContext('sqlite')) is None


@pytest.mark.parametrize('body', [
    'WITH chosen(n) AS (SELECT :value) REPLACE INTO orders SELECT n FROM chosen',
    'UPDATE OR IGNORE orders SET n=:value',
])
async def test_plan_parameter_binding_does_not_enable_actual_dml(bundle,tmp_path,body):
    _,connections,_,save=bundle
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['orders']}
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7);')
    server=create_server(load_config(save()))
    try:
        adapter=server.gateway_runtime.registry.get_adapter('demo')
        policy=server.gateway_runtime.registry.get_config('demo').policy
        assert adapter.execute_read('EXPLAIN '+body,params={'value':99},policy=policy)
        with pytest.raises(DatabaseQueryError) as denied:
            adapter.execute_read(body,params={'value':99},policy=policy)
        assert denied.value.error_code=='read_only_required'
        assert adapter.execute('SELECT n FROM orders')==[(7,)]
        assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()
