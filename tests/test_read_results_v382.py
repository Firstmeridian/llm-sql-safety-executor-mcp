"""Faithful read values, shared limits and scoped conditional dependencies."""
from dataclasses import replace
from types import SimpleNamespace
from decimal import Decimal
from datetime import datetime, timedelta
import json

import pytest
from fastmcp import Client
from pydantic import ValidationError
from pydantic_core import to_json
from sql_safety_executor.config.models import Limits
from sql_safety_executor.core.results import _prepare_read_result, _serialize_result, ReadResultError
from sql_safety_executor.database.outcomes import MetadataQueryError
from tests.test_external_read_review_v382 import review_server, bundle


def runtime(chars=16000, rows=100):
    return SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(limits=Limits(result_chars=chars,result_rows=rows))))


@pytest.mark.parametrize('mode',['auto','legacy'])
@pytest.mark.parametrize('sql,expected',[
    ('SELECT 7 AS n,99 AS n','duplicate_result_columns'),
    ('SELECT 7 AS n,99 AS N',[{'n':7,'N':99}]),
    ("SELECT X'00FF' AS payload",[{'payload':{'$type':'binary','encoding':'base64','data':'AP8='}}]),
    ("SELECT X'616263' AS payload",[{'payload':{'$type':'binary','encoding':'base64','data':'YWJj'}}]),
    ("SELECT X'' AS payload",[{'payload':{'$type':'binary','encoding':'base64','data':''}}]),
    ('SELECT 1e999 AS n,NULL AS missing',[{'n':{'$type':'float','value':'Infinity'},'missing':None}]),
    ('SELECT -1e999 AS n',[{'n':{'$type':'float','value':'-Infinity'}}]),
])
async def test_query_and_skill_result_contract(review_server,mode,sql,expected):
    server=review_server(sql)
    async with Client(server,mode=mode) as client:
        for tool,args in [('query',{'sql':sql}),('execute_query_skill',{'skill_name':'review-probe','params':{}})]:
            result=await client.call_tool(tool,args)
            payload=result.structured_content
            assert not result.is_error
            if isinstance(expected,str):
                assert not payload['success'] and payload['error_code']==expected
                assert 'unique AS' in payload['hint']
            else:
                assert payload['success'] and payload['data']==expected
                assert json.loads(result.content[0].text)['data']==expected


@pytest.mark.parametrize('mode',['auto','legacy'])
async def test_all_read_entries_limit_wide_first_row(review_server,mode):
    server=review_server('SELECT payload FROM wide',ddl="CREATE TABLE wide(payload);INSERT INTO wide VALUES(printf('%.*c',20000,'x'));",
                         read={'mode':'allowlist','tables':['wide']})
    async with Client(server,mode=mode) as client:
        for tool,args in [('query',{'sql':'SELECT payload FROM wide'}),
                          ('execute_query_skill',{'skill_name':'review-probe','params':{}}),
                          ('sample',{'table_name':'wide','limit':1})]:
            payload=(await client.call_tool(tool,args)).structured_content
            assert payload['success'] and payload['data']==[]
            assert payload['row_count']==0 and payload['total_rows']==1
            assert payload['truncated'] and payload['truncation_reason']=='char_limit'
            assert 'first row exceeds' in payload['truncation_note']
            assert 'fewer columns' in payload['truncation_note']


@pytest.mark.parametrize('mode',['auto','legacy'])
async def test_sample_encodes_binary_and_keeps_empty_result(review_server,mode):
    server=review_server('SELECT payload FROM blobs',ddl="CREATE TABLE blobs(payload);INSERT INTO blobs VALUES(X'00FF');CREATE TABLE empty(n);",
                         read={'mode':'allowlist','tables':['blobs','empty']})
    async with Client(server,mode=mode) as client:
        payload=(await client.call_tool('sample',{'table_name':'blobs','limit':1})).structured_content
        assert payload['data']==[{'payload':{'$type':'binary','encoding':'base64','data':'AP8='}}]
        empty=(await client.call_tool('sample',{'table_name':'empty'})).structured_content
        assert empty['data']==[] and empty['total_rows']==empty['row_count']==0 and not empty['truncated']


@pytest.mark.parametrize('chars',[0,2,9,10,11,15,28,50])
@pytest.mark.parametrize('rows',[0,1,2,100])
def test_encoded_compact_size_and_row_prefix(chars,rows):
    data=[{'n':'中\\\n"'},{'n':'small'},{'n':{'$type':'binary','encoding':'base64','data':'AP8='}}]
    result=_prepare_read_result(runtime(chars,rows),data)
    assert result['data']==data[:result['row_count']]
    assert result['row_count']<=len(data) and result['total_rows']==len(data)
    if chars:assert len(json.dumps(result['data'],ensure_ascii=False,separators=(',',':')))<=chars
    if rows:assert result['row_count']<=rows
    assert result['truncated']==(result['row_count']<len(data))


def test_limits_and_unknown_types_are_explicit():
    with pytest.raises(ValidationError):Limits(result_chars=1)
    for value in (object(),{1:'unsupported key'},'\ud800',{'\ud800':7}):
        with pytest.raises(ReadResultError) as caught:_prepare_read_result(runtime(),[{'n':value}])
        assert caught.value.error_payload()['error_code']=='result_encoding_failed'
    assert _serialize_result(bytearray(b'\xff'))==_serialize_result(memoryview(b'\xff'))
    assert _serialize_result(memoryview(b'abc')[::2])['data']=='YWM='
    assert _serialize_result(float('nan'))=={'$type':'float','value':'NaN'}
    assert _serialize_result(Decimal('1.2300'))=='1.2300'
    assert _serialize_result(datetime(2026,10,21,1,2,3))=='2026-10-21T01:02:03'
    assert _serialize_result(timedelta(seconds=5))=='PT5S'


@pytest.mark.parametrize('value',[1e30,1e-7,'中\\\n"'])
def test_limit_uses_actual_protocol_number_and_escape_encoding(value):
    data=[{'n':value}]
    size=len(to_json(data).decode('utf-8'))
    assert _prepare_read_result(runtime(size),data)['data']==data
    result=_prepare_read_result(runtime(size-1),data)
    assert result['data']==[] and result['truncation_reason']=='char_limit'


@pytest.mark.parametrize('mode',['auto','legacy'])
@pytest.mark.parametrize('schema',['aux','temp'])
@pytest.mark.parametrize('name',['json_each','json_tree'])
async def test_nondefault_json_skill_dependencies_are_unverified(review_server,mode,schema,name):
    server=review_server(f"SELECT value FROM {schema}.{name}('hello')",
                         read={'mode':'allowlist','relations':[{'schema':schema,'name':name}]})
    adapter=server.gateway_runtime.registry.get_adapter('demo');adapter.connect()
    with adapter._engine.begin() as db:
        if schema=='aux':db.exec_driver_sql("ATTACH ':memory:' AS aux")
        db.exec_driver_sql(f'CREATE VIRTUAL TABLE {schema}.{name} USING fts5(value)')
        db.exec_driver_sql(f"INSERT INTO {schema}.{name} VALUES('hello')")
    async with Client(server,mode=mode) as client:
        raw=await client.call_tool('query',{'sql':f"SELECT value FROM {schema}.{name}('hello')"})
        assert raw.structured_content['data']==[{'value':'hello'}]
        for tool,args in [('get_skill_detail',{'skill_name':'review-probe'}),('list_skills',{'detail_level':'full','available_only':False})]:
            payload=(await client.call_tool(tool,args)).structured_content
            state=payload['skill'] if tool=='get_skill_detail' else payload['skills'][0]
            assert state['inferred_tables']==[f'{schema}.{name}']
            assert state['unverified_tables']==[f'{schema}.{name}'] and not state['schema_ready']
            assert not state['executable'] and not state['schema_check_available']
        listed=(await client.call_tool('list_skills',{})).structured_content
        assert listed['skills']==[]
        executed=await client.call_tool('execute_query_skill',{'skill_name':'review-probe','params':{}},raise_on_error=False)
        assert executed.is_error and 'could not verify' in executed.content[0].text


@pytest.mark.parametrize('mode',['auto','legacy'])
async def test_json_temp_binding_metadata_failure_and_disabled_readiness(review_server,mode,monkeypatch):
    server=review_server("SELECT value FROM json_each('[7]')")
    adapter=server.gateway_runtime.registry.get_adapter('demo')
    async with Client(server,mode=mode) as client:
        initial=(await client.call_tool('get_skill_detail',{'skill_name':'review-probe'})).structured_content['skill']
        assert initial['executable'] and initial['inferred_tables']==[]
        assert initial['conditional_dependencies']==[{'relation':'main.json_each','state':'builtin'}]
        with adapter._engine.begin() as db:
            db.exec_driver_sql('CREATE VIRTUAL TABLE temp.json_each USING fts5(value)')
        state=(await client.call_tool('get_skill_detail',{'skill_name':'review-probe'})).structured_content['skill']
        assert state['inferred_tables']==['temp.json_each'] and not state['executable']
        with adapter._engine.begin() as db:db.exec_driver_sql('DROP TABLE temp.json_each')
        def unavailable():raise MetadataQueryError('test metadata failure')
        monkeypatch.setattr(adapter,'get_read_relations',unavailable)
        state=(await client.call_tool('get_skill_detail',{'skill_name':'review-probe'})).structured_content['skill']
        assert not state['schema_ready'] and state['unverified_tables']==['json_each']
        executed=await client.call_tool('execute_query_skill',{'skill_name':'review-probe','params':{}},raise_on_error=False)
        assert executed.is_error
        runtime=server.gateway_runtime
        runtime.config=replace(runtime.config,skills=runtime.config.skills.model_copy(update={
            'readiness':runtime.config.skills.readiness.model_copy(update={'check_schema':False})}))
        monkeypatch.setattr(adapter,'get_json_name_observation',lambda:pytest.fail('readiness off must not probe'))
        result=await client.call_tool('execute_query_skill',{'skill_name':'review-probe','params':{}})
        assert result.structured_content['data']==[{'value':7}]
