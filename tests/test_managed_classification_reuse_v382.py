"""Readiness isolation and managed classification reuse keep execution gates fresh."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor.core.types import ConnectionContext, OperationError
from sql_safety_executor.core.managed_sql import check_managed_sql
from sql_safety_executor.database.errors import DatabaseQueryError
from sql_safety_executor.database.outcomes import MetadataQueryError
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.skills import access
from tests.test_managed_parser_v382 import managed_server as managed_server, PARAMS, UPDATE
from tests.test_v38_config import bundle as bundle


def enable_readiness(runtime):
    runtime.config = replace(runtime.config, skills=runtime.config.skills.model_copy(
        update={'readiness': runtime.config.skills.readiness.model_copy(update={'check_schema': True})},
    ))


@pytest.mark.parametrize('required,expected', [
    ('main.orders', None), ('main.absent', 'not found'), ('aux.orders', 'could not verify'),
])
def test_schema_guard_never_evaluates_managed_plan(managed_server, monkeypatch, required, expected):
    runtime = managed_server().gateway_runtime
    enable_readiness(runtime)
    meta = replace(runtime.catalog.get_skills_cache()[UPDATE], tables=[required])
    config = runtime.config.connections['demo']
    connection = ConnectionContext('demo', config, runtime.registry.get_adapter('demo'), config.policy)
    monkeypatch.setattr(access, '_managed_plan_policy_decision', lambda *a: pytest.fail('readiness ran plan policy'))
    if expected:
        with pytest.raises(OperationError, match=expected):
            access._ensure_skill_schema_ready(runtime, meta, connection)
    else:
        access._ensure_skill_schema_ready(runtime, meta, connection)


def test_schema_guard_keeps_metadata_failure_and_disabled_behavior(managed_server, monkeypatch):
    runtime = managed_server().gateway_runtime
    meta = runtime.catalog.get_skills_cache()[UPDATE]
    config = runtime.config.connections['demo']
    adapter = runtime.registry.get_adapter('demo')
    connection = ConnectionContext('demo', config, adapter, config.policy)
    def unavailable():
        raise MetadataQueryError('testing readiness')
    monkeypatch.setattr(adapter, 'get_read_relations', unavailable)
    # Disabled checks must not access metadata or classify a managed plan.
    access._ensure_skill_schema_ready(runtime, meta, connection)
    enable_readiness(runtime)
    with pytest.raises(OperationError, match='database metadata is unavailable'):
        access._ensure_skill_schema_ready(runtime, meta, connection)


def test_readiness_still_refuses_incomplete_query_dependencies(managed_server):
    runtime = managed_server().gateway_runtime
    enable_readiness(runtime)
    meta = replace(runtime.catalog.get_skills_cache()[UPDATE], type='query',
                   _sql_template='SELECT * FROM', _managed_mutation_plan=None)
    config = runtime.config.connections['demo']
    connection = ConnectionContext('demo', config, runtime.registry.get_adapter('demo'), config.policy)
    with pytest.raises(ValueError, match='dependency analysis is incomplete'):
        access._ensure_skill_schema_ready(runtime, meta, connection)


def test_reuse_keys_exact_sql_full_context_and_parser(managed_server):
    runtime = managed_server().gateway_runtime
    classify = runtime.classify_managed_plan
    sql = 'UPDATE orders SET n=7'
    context = DialectContext('sqlite', default_schema='main')
    variants = [
        (sql, context, 'sqlglot'),
        (sql + ' ', context, 'sqlglot'),
        ('UPDATE " f " SET n=7', context, 'sqlglot'),
        ('UPDATE "  f  " SET n=7', context, 'sqlglot'),
        ('UPDATE main.orders SET n=7', context, 'sqlglot'),
        ('UPDATE "main.orders" SET n=7', context, 'sqlglot'),
        (sql, replace(context, default_schema='aux'), 'sqlglot'),
        (sql, replace(context, cte_case_sensitive=True), 'sqlglot'),
        (sql, DialectContext('mysql'), 'sqlglot'),
        (sql, DialectContext('mysql', frozenset({'ANSI_QUOTES'})), 'sqlglot'),
        (sql, DialectContext('mysql', frozenset({'HIGH_NOT_PRECEDENCE'})), 'sqlglot'),
        (sql, context, 'sqlparse'),
    ]
    for args in variants:
        expected = check_managed_sql(*args)
        first = classify(*args)
        assert first == expected
        assert classify(*args) is first
    info = classify.cache_info()
    assert info.misses == info.hits == len(variants)
    assert info.currsize == len(variants)


def test_reuse_is_bounded_isolated_and_cleared_on_close(managed_server, monkeypatch):
    first = managed_server().gateway_runtime
    second = managed_server().gateway_runtime
    classify = first.classify_managed_plan
    context = DialectContext('sqlite')
    for n in range(129):
        assert classify(f'UPDATE orders SET n={n}', context, 'sqlglot').allowed
    assert classify.cache_info().maxsize == classify.cache_info().currsize == 128
    classify('UPDATE orders SET n=0', context, 'sqlglot')
    assert classify.cache_info().misses == 130  # Oldest entry was evicted.
    assert second.classify_managed_plan.cache_info().currsize == 0
    # A connection cleanup error must not retain classification entries.
    close = first.registry.close
    def broken_close():
        close()
        raise RuntimeError('fixture close failure')
    with monkeypatch.context() as patch:
        patch.setattr(first.registry, 'close', broken_close)
        with pytest.raises(RuntimeError, match='fixture close failure'):
            first.close()
    assert classify.cache_info().currsize == 0


def test_classifier_exceptions_are_not_cached(managed_server, monkeypatch):
    import sql_safety_executor.core.runtime as runtime_module
    calls = []
    def transient(sql, context, parser):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError('temporary classifier failure')
        return check_managed_sql(sql, context, parser)
    monkeypatch.setattr(runtime_module, 'check_managed_sql', transient)
    classify = managed_server().gateway_runtime.classify_managed_plan
    args = ('DELETE FROM orders', DialectContext('sqlite'), 'sqlglot')
    with pytest.raises(RuntimeError, match='temporary classifier failure'):
        classify(*args)
    assert classify(*args).allowed and classify(*args).allowed
    assert len(calls) == 2 and classify.cache_info().currsize == 1


def test_parallel_pure_checks_remain_coherent(managed_server):
    classify = managed_server().gateway_runtime.classify_managed_plan
    context = DialectContext('sqlite')
    inputs = [f'UPDATE orders SET n={n % 8}' for n in range(160)]
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda sql: classify(sql, context, 'sqlglot'), inputs))
    assert all(result.allowed for result in results)
    assert classify.cache_info().currsize == 8
    # Concurrent misses may compute twice; no single-flight promise is needed.


def test_target_resolution_failure_is_never_a_cached_decision(managed_server, monkeypatch):
    runtime = managed_server().gateway_runtime
    config = runtime.config.connections['demo']
    adapter = runtime.registry.get_adapter('demo')
    connection = ConnectionContext('demo', config, adapter, config.policy)
    meta = runtime.catalog.get_skills_cache()[UPDATE]
    assert access._managed_plan_policy_decision(runtime, meta, connection).allowed
    before = runtime.classify_managed_plan.cache_info()
    def unavailable():
        raise DatabaseQueryError('session_semantics_unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(adapter, 'resolve_analysis_context', unavailable)
        assert access._managed_plan_policy_decision(runtime, meta, connection).error_code == 'session_semantics_unavailable'
    assert runtime.classify_managed_plan.cache_info() == before
    assert access._managed_plan_policy_decision(runtime, meta, connection).allowed
    assert runtime.classify_managed_plan.cache_info().hits == before.hits + 1


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('gate', ['mutation_policy', 'profile', 'alias', 'params', 'readiness'])
async def test_warm_classification_does_not_reuse_execution_permission(managed_server, monkeypatch, mode, gate):
    server = managed_server()
    runtime = server.gateway_runtime
    adapter = runtime.registry.get_adapter('demo')
    async with Client(server, mode=mode) as client:
        response = await client.call_tool('get_skill_detail', {'skill_name': UPDATE})
        assert response.structured_content['skill']['executable']
        assert runtime.classify_managed_plan.cache_info().currsize == 1
        config = runtime.config.connections['demo']
        params = PARAMS
        if gate == 'mutation_policy':
            changed = replace(config, policy=replace(config.policy, allow_mutations=False))
            monkeypatch.setattr(runtime.registry, 'get_config', lambda *a: changed)
        elif gate == 'profile':
            runtime.config = replace(runtime.config, skills=runtime.config.skills.model_copy(update={
                'policy': runtime.config.skills.policy.model_copy(update={'exclude_profiles': ('demo',)}),
            }))
        elif gate == 'alias':
            runtime.config = replace(runtime.config, skills=runtime.config.skills.model_copy(update={
                'mutation': runtime.config.skills.mutation.model_copy(update={'allowed_connections': ()}),
            }))
        elif gate == 'params':
            params = {**PARAMS, 'unexpected': True}
        else:
            enable_readiness(runtime)
            with sqlite3.connect(config.sqlite_database_path) as db:
                db.execute('DROP TABLE orders')
        monkeypatch.setattr(adapter, 'execute_write', lambda *a, **kw: pytest.fail('denied operation wrote'))
        refused = await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': params}, raise_on_error=False)
        assert refused.is_error


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('failure', ['changed_context', 'unavailable_context'])
async def test_consumed_confirmation_resolves_target_even_when_warm(managed_server, monkeypatch, mode, failure):
    server = managed_server(sql='UPDATE OR IGNORE orders SET status=:new_status WHERE id=:order_id AND status=:expected_status')
    runtime = server.gateway_runtime
    adapter = runtime.registry.get_adapter('demo')
    resolutions = []
    original = adapter.resolve_analysis_context
    def resolve():
        resolutions.append(True)
        return original()
    monkeypatch.setattr(adapter, 'resolve_analysis_context', resolve)
    async with Client(server, mode=mode) as client:
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success'] and len(resolutions) == 1
        assert runtime.classify_managed_plan.cache_info().currsize == 1
        def unavailable():
            raise DatabaseQueryError('session_semantics_unavailable')
        monkeypatch.setattr(adapter, 'resolve_analysis_context', unavailable if failure == 'unavailable_context' else lambda: DialectContext('mysql'))
        monkeypatch.setattr(adapter, 'execute_write', lambda *a, **kw: pytest.fail('unverified target wrote'))
        args = {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': preview['preview_token']}
        result = await client.call_tool('execute_mutation_skill', args)
        payload = result.structured_content
        assert not payload['success'] and payload['execution_outcome'] == 'not_executed'
        assert payload['error_code'] == 'managed_plan_validation_failed' and result.meta['preview_token_consumed']
        if failure == 'unavailable_context':
            assert runtime.classify_managed_plan.cache_info().currsize == 1
        replay = await client.call_tool('execute_mutation_skill', args, raise_on_error=False)
        assert replay.is_error and 'before execution' in replay.content[0].text
    with sqlite3.connect(runtime.config.connections['demo'].sqlite_database_path) as db:
        assert db.execute('SELECT status FROM orders').fetchall() == [('pending',)]
