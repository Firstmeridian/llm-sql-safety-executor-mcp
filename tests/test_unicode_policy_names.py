"""Reserved ASCII names must not absorb SQLite's distinct Unicode entities."""
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.policy import _server_state_reference_error, _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize('name',['pragma_locKing_mode','PRAGMA_LOCKING_MODE'])
@pytest.mark.parametrize('quoting',['{}','"{}"','`{}`','[{}]'])
@pytest.mark.parametrize('qualified',[False,True])
@pytest.mark.parametrize('membership',[False,True])
def test_unicode_pragma_table_names_follow_native_sqlite_identity(name,quoting,qualified,membership):
    target=('main.' if qualified else '')+quoting.format(name)
    sql=f'SELECT 7 AS n WHERE 7 IN {target}' if membership else f'SELECT n FROM {target}'
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE "pragma_locKing_mode"(n);INSERT INTO "pragma_locKing_mode" VALUES(7);'
            'CREATE TABLE pragma_locking_mode(n);INSERT INTO pragma_locking_mode VALUES(99);')
        assert db.execute(sql).fetchall()==[(7,)]
        assert db.execute('SELECT n FROM pragma_locking_mode').fetchall()==[(99,)]
    policy=ConnectionPolicy(allowed_tables=frozenset({'main.pragma_locKing_mode','pragma_locKing_mode'}))
    assert _validate_sql_query_policy(None,sql,policy).allowed


@pytest.mark.parametrize('sql',[
    'SELECT * FROM pragma_locKing_mode()',
    'SELECT * FROM main.pragma_locKing_mode()',
    'SELECT 1 WHERE 1 IN pragma_locKing_mode()',
    'SELECT 1 WHERE 1 IN main.pragma_locKing_mode()',
    'SELECT uſer()', 'SELECT seßion_user()', 'SELECT sessıon_user()',
])
def test_unicode_function_spelling_is_not_reserved_ascii_state(sql):
    # Classification only: no claim that a business table is a table function,
    # or that an unregistered Unicode function executes successfully.
    assert _server_state_reference_error(sql) is None


@pytest.mark.parametrize('sql',[
    'SELECT current_uſer AS n FROM orders',
    'SELECT CURRENT_UſER AS n FROM orders',
    'SELECT o.current_uſer AS n FROM orders o',
    'SELECT "current_uſer" AS n FROM orders',
])
def test_unicode_account_like_column_remains_business_data(sql):
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE orders(current_uſer INTEGER,current_user INTEGER);INSERT INTO orders VALUES(7,99);')
        assert db.execute(sql).fetchall()==[(7,)]
    assert _validate_sql_query_policy(None,sql,ConnectionPolicy(allowed_tables=frozenset({'orders'}))).allowed


@pytest.mark.parametrize('sql',[
    'SELECT * FROM pragma_locking_mode',
    'SELECT * FROM PRAGMA_LOCKING_MODE()',
    'SELECT * FROM main."PrAgMa_LoCkInG_MoDe"',
    'SELECT 1 WHERE 1 IN pragma_locking_mode',
    'SELECT 1 WHERE 1 IN PRAGMA_LOCKING_MODE()',
    'SELECT USER()', 'SELECT SeSsIoN_UsEr()', 'SELECT SYSTEM_USER()',
    'SELECT CURRENT_USER()', 'SELECT current_user()', 'SELECT CURRENT_ROLE()',
])
def test_real_ascii_reserved_names_stay_denied_even_with_all_table_scope(sql):
    decision=_validate_sql_query_policy(None,sql,ConnectionPolicy(read_mode='all',allowed_tables=frozenset({'*'})))
    assert not decision.allowed and decision.error_code=='server_state_denied'


@pytest.mark.parametrize('mode',['legacy','auto'])
async def test_unicode_raw_and_skill_paths_both_protocols(bundle,tmp_path,monkeypatch,mode):
    _,connections,skills,save=bundle
    with sqlite3.connect(tmp_path/'db.sqlite') as db:
        db.executescript('CREATE TABLE "pragma_locKing_mode"(n INTEGER);INSERT INTO "pragma_locKing_mode" VALUES(7);'
            'CREATE TABLE pragma_locking_mode(n INTEGER);INSERT INTO pragma_locking_mode VALUES(99);'
            'CREATE TABLE orders(current_uſer INTEGER,current_user INTEGER);INSERT INTO orders VALUES(7,99);')
    sqls={
        'unicode-from':'SELECT n FROM main."pragma_locKing_mode"',
        'unicode-in':'SELECT 7 AS n WHERE 7 IN main."pragma_locKing_mode"',
        'unicode-account-column':'SELECT current_uſer AS n FROM main.orders',
        'ascii-account-column':'SELECT current_user AS n FROM main.orders',
        'reserved-pragma':'SELECT n FROM main.pragma_locking_mode',
        'reserved-account':'SELECT current_user() AS n FROM main.orders',
    }
    for name,sql in sqls.items():
        directory=tmp_path/'skills'/name;directory.mkdir(parents=True)
        (directory/'skill_def.md').write_text(f'---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\ndescription: Unicode names\nparams: {{}}\n---\n')
        (directory/'query.sql').write_text(sql)
    connections['connections']['demo']['read']={'mode':'allowlist','tables':['main.pragma_locKing_mode','main.pragma_locking_mode','main.orders']}
    skills['skills']={'enabled':True,'directory':str(tmp_path/'skills'),'readiness':{'check_schema':True},'audit':{'path':str(tmp_path/'audit.jsonl')}}
    server=create_server(load_config(save(use_skills=True)))
    try:
        async with Client(server,mode=mode) as client:
            listed=await client.call_tool('list_skills',{'detail_level':'full'})
            assert {s['name'] for s in listed.structured_content['skills']}==set(list(sqls)[:4])
            for name in list(sqls)[:4]:
                raw=await client.call_tool('query',{'sql':sqls[name]})
                detail=await client.call_tool('get_skill_detail',{'skill_name':name,'detail_level':'full'})
                executed=await client.call_tool('execute_query_skill',{'skill_name':name,'params':{}})
                assert raw.structured_content['data']==executed.structured_content['data']==[{'n':99 if name=='ascii-account-column' else 7}]
                state=detail.structured_content['skill']
                assert state['schema_ready'] and state['policy_allowed'] and state['executable']
                assert state['missing_tables']==state['unverified_tables']==[]
            def unexpected_execute(*args,**kwargs):
                pytest.fail('Reserved ASCII state reference reached adapter.execute')
            monkeypatch.setattr(server.gateway_runtime.registry.get_adapter('demo'),'execute',unexpected_execute)
            for sql in ['SELECT n FROM main.pragma_locking_mode','SELECT 1 WHERE 1 IN main.pragma_locking_mode','SELECT current_user() AS n FROM main.orders']:
                result=await client.call_tool('query',{'sql':sql})
                assert result.structured_content['error_code']=='server_state_denied'
    finally:server.gateway_runtime.close()
