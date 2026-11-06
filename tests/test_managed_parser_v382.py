"""Managed SQL classification, real target semantics, preview/token/write rules."""
from dataclasses import replace
import shutil
import sqlite3
import subprocess
import sys
import textwrap

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.config.loader import ConfigError, explain_config
from sql_safety_executor.core.managed_sql import check_managed_sql
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.skills.mutation import (
    ManagedMutationPlan, ManagedMutationValue, validate_managed_mutation_plan,
)
from tests.support import ROOT
from tests.test_v38_config import bundle as bundle


UPDATE = 'sample-update-order-status'
RESET = 'sample-reset-order-to-pending'
PARAMS = {'order_id': 1, 'new_status': 'confirmed'}


@pytest.fixture
def managed_server(bundle, tmp_path):
    main, connections, skills, save = bundle
    with sqlite3.connect(tmp_path / 'db.sqlite') as db:
        db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY,status TEXT,n INTEGER,note TEXT);INSERT INTO orders VALUES(1,'pending',7,'alpha');")
    directory = tmp_path / 'skills'
    for name in (UPDATE, RESET):
        shutil.copytree(ROOT / 'skills' / name, directory / name)
    skills['skills']['directory'] = str(directory)
    skills['skills']['mutation']['mrtr']['enabled'] = False
    skills['skills']['readiness'] = {'check_schema': False}
    connections['connections']['demo']['read'] = {'mode': 'all'}
    connections['connections']['demo']['mutation'] = {'enabled': True, 'skills': [UPDATE, RESET]}
    servers = []

    def build(sql=None):
        if sql is not None:
            path = directory / UPDATE / 'mutation.py'
            original = path.read_text()
            start = original.index('        sql=(')
            end = original.index('        parameters=', start)
            path.write_text(original[:start] + '        sql=' + repr(sql) + ',\n' + original[end:])
        config = load_config(save(use_skills=True))
        server = create_server(config)
        servers.append(server)
        return server

    yield build
    for server in servers:
        server.gateway_runtime.close()


@pytest.mark.parametrize('sql', [
    'INSERT INTO orders(n) VALUES(:n)', 'UPDATE orders SET n=:n', 'DELETE FROM orders WHERE n=:n',
    'WITH chosen AS (SELECT :n AS n) UPDATE orders SET n=(SELECT n FROM chosen)',
    'INSERT OR REPLACE INTO orders(n) VALUES(:n)',
    'WITH replace(n) AS (SELECT :n) INSERT OR REPLACE INTO orders(n) SELECT n FROM replace',
])
def test_known_dml_and_named_bind_contract(sql):
    plan = ManagedMutationPlan(sql, (ManagedMutationValue.constant('n', 7),), 1)
    assert validate_managed_mutation_plan(plan, context=DialectContext('sqlite')) is plan
    with pytest.raises(TypeError, match='exactly match SQL named binds'):
        validate_managed_mutation_plan(replace(plan, parameters=()))


@pytest.mark.parametrize('sql,code', [
    ('REPLACE INTO orders(n) VALUES(7)', 'managed_plan_statement_invalid'),
    ('WITH chosen(n) AS (SELECT 7) REPLACE INTO orders(n) SELECT n FROM chosen', 'managed_plan_statement_invalid'),
    ('SELECT 7', 'managed_plan_statement_invalid'),
    ('EXPLAIN UPDATE orders SET n=7', 'managed_plan_sql_parse_failed'),
    ('UPDATE orders SET n=7; DELETE FROM orders', 'managed_plan_statement_invalid'),
    ('CREATE TABLE probe(n)', 'managed_plan_statement_invalid'),
])
def test_nonplan_types_and_bare_replace_remain_refused(sql, code):
    decision = check_managed_sql(sql, DialectContext('sqlite'))
    assert not decision.allowed and decision.error_code == code


@pytest.mark.parametrize('sql', [
    'UPDATE orders SET n=7; /* tail */',
    'WITH "insert"(n) AS (SELECT 7) INSERT INTO orders(n) SELECT n FROM "insert"',
    'WITH offſet(n) AS (SELECT 7) INSERT INTO orders(n) SELECT n FROM offſet',
    'UPDATE orders SET note=replace(note,\'a\',\'b\')',
])
def test_ast_classification_keeps_native_valid_cases_and_original_sql(sql):
    assert check_managed_sql(sql, DialectContext('sqlite')).allowed
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE orders(n,note)')
        db.execute('EXPLAIN ' + sql).fetchall()
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone() == (0,)


def test_managed_validation_imports_and_runs_without_sqlparse():
    # A fresh interpreter catches imports even when the test process already
    # loaded dependencies. It does not require sqlparse to be installed.
    result = subprocess.run([sys.executable, '-c', textwrap.dedent('''
        import builtins
        original = builtins.__import__
        def without_sqlparse(name, *args, **kwargs):
            if name == 'sqlparse' or name.startswith('sqlparse.'):
                raise AssertionError('Removed dependency imported')
            return original(name, *args, **kwargs)
        builtins.__import__ = without_sqlparse
        from sql_safety_executor import create_server, load_config
        from sql_safety_executor.database.semantics import DialectContext
        from sql_safety_executor.skills.mutation import ManagedMutationPlan, validate_managed_mutation_plan
        plan = ManagedMutationPlan('DELETE FROM orders', (), 1)
        assert validate_managed_mutation_plan(plan) is plan
        for backend in ('sqlite', 'mysql'):
            assert validate_managed_mutation_plan(plan, context=DialectContext(backend)) is plan
    ''')], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_contextual_modes_and_dialects_are_checked_separately():
    sql = 'UPDATE OR IGNORE orders SET n=7'
    assert check_managed_sql(sql, DialectContext('sqlite')).allowed
    assert not check_managed_sql(sql, DialectContext('mysql')).allowed
    escaped = "UPDATE orders SET note='a\\\';DELETE FROM orders;-- ' WHERE id=1"
    assert check_managed_sql(escaped, DialectContext('mysql')).allowed
    assert not check_managed_sql(escaped, DialectContext('mysql', frozenset({'NO_BACKSLASH_ESCAPES'}))).allowed
    assert not check_managed_sql(sql, DialectContext('mysql', frozenset({'HIGH_NOT_PRECEDENCE'}))).allowed


@pytest.mark.parametrize('comment', ['/*! ,status=99 */', '/*M! ,status=99 */', '/*+ MAX_EXECUTION_TIME(1000) */', '--suffix'])
def test_directive_comments_are_not_an_invisible_extra_statement(comment):
    sql = 'UPDATE orders SET n=7 ' + comment
    assert check_managed_sql(sql, DialectContext('mysql')).error_code == 'managed_plan_comment_unsupported'


@pytest.mark.parametrize('value', ['/*! not a directive */', '/*M! string */', '/*+ string */', '--suffix'])
def test_comment_like_string_data_stays_usable(value):
    sql = "UPDATE orders SET note='" + value + "' /* ordinary comment */"
    assert check_managed_sql(sql, DialectContext('mysql')).allowed


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_preview_execute_replay_and_original_statement(managed_server, monkeypatch, mode):
    server = managed_server()
    runtime = server.gateway_runtime
    adapter = runtime.registry.get_adapter('demo')
    sql = runtime.catalog.get_skills_cache()[UPDATE]._managed_mutation_plan.sql
    calls = []
    execute = adapter.execute_write

    def capture(statement, parameters, **kwargs):
        calls.append((statement, dict(parameters), kwargs))
        return execute(statement, parameters, **kwargs)

    monkeypatch.setattr(adapter, 'execute_write', capture)
    async with Client(server, mode=mode) as client:
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success'] and preview['execution_outcome'] == 'not_executed'
        assert preview['preview']['preview_sql'] == sql and not calls
        token = preview['preview_token']
        result = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': token})).structured_content
        assert result['success'] and result['execution_outcome'] == 'committed'
        assert calls == [(sql, {'new_status': 'confirmed', 'order_id': 1, 'expected_status': 'pending'}, {'expected_rowcount': 1})]
        replay = await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': token}, raise_on_error=False)
        assert replay.is_error and 'before execution' in replay.content[0].text and len(calls) == 1


async def test_precommit_rowcount_failure_still_rolls_back(managed_server):
    sql = 'UPDATE orders SET status=:new_status WHERE id=:order_id AND status=:expected_status AND id=999'
    server = managed_server(sql=sql)
    async with Client(server) as client:
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success']
        executed = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': preview['preview_token']})).structured_content
        assert not executed['success'] and executed['execution_outcome'] == 'rolled_back'
    with sqlite3.connect(server.gateway_runtime.config.connections['demo'].sqlite_database_path) as db:
        assert db.execute('SELECT status FROM orders WHERE id=1').fetchone() == ('pending',)


async def test_preview_and_consumed_confirmation_recheck_actual_context(managed_server, monkeypatch):
    sql = 'UPDATE OR IGNORE orders SET status=:new_status WHERE id=:order_id AND status=:expected_status'
    server = managed_server(sql=sql)
    adapter = server.gateway_runtime.registry.get_adapter('demo')
    actual_context = adapter.resolve_analysis_context()
    async with Client(server) as client:
        monkeypatch.setattr(adapter, 'resolve_analysis_context', lambda: DialectContext('mysql'))
        refused = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert not refused['success'] and refused['execution_outcome'] == 'not_executed'
        assert 'preview_token' not in refused
        monkeypatch.setattr(adapter, 'resolve_analysis_context', lambda: actual_context)
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success']
        monkeypatch.setattr(adapter, 'resolve_analysis_context', lambda: DialectContext('mysql'))
        monkeypatch.setattr(adapter, 'execute_write', lambda *a, **kw: pytest.fail('invalid target wrote'))
        args = {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': preview['preview_token']}
        response = await client.call_tool('execute_mutation_skill', args)
        refused = response.structured_content
        assert not refused['success'] and refused['execution_outcome'] == 'not_executed'
        assert refused['error_code'] == 'managed_plan_validation_failed' and response.meta['preview_token_consumed'] is True
        replay = await client.call_tool('execute_mutation_skill', args, raise_on_error=False)
        assert replay.is_error and 'before execution' in replay.content[0].text


async def test_target_context_controls_discovery_and_detail(managed_server, monkeypatch):
    server = managed_server(sql='UPDATE OR IGNORE orders SET status=:new_status WHERE id=:order_id AND status=:expected_status')
    adapter = server.gateway_runtime.registry.get_adapter('demo')
    monkeypatch.setattr(adapter, 'resolve_analysis_context', lambda: DialectContext('mysql'))
    async with Client(server) as client:
        listing = (await client.call_tool('list_skills', {'detail_level': 'full'})).structured_content
        assert UPDATE not in {item['name'] for item in listing['skills']}
        detail = (await client.call_tool('get_skill_detail', {'skill_name': UPDATE})).structured_content
        assert detail['skill']['executable'] is False
        monkeypatch.setattr(adapter, 'resolve_analysis_context', lambda: DialectContext('sqlite'))
        listing = (await client.call_tool('list_skills', {'detail_level': 'full'})).structured_content
        assert UPDATE in {item['name'] for item in listing['skills']}


def test_configuration_schema_and_explain_have_no_parser_switch(bundle):
    from sql_safety_executor.config.models import Mutation
    _, _, _, save = bundle
    config = load_config(save(use_skills=True))
    assert 'managed_plan_parser' not in Mutation.model_fields
    assert 'managed_plan_parser' not in config.skills.mutation.model_dump()
    assert 'skills.mutation.managed_plan_parser' not in explain_config(config)


@pytest.mark.parametrize('value', ['sqlglot', 'sqlparse', True, False, None, 'auto', 'both', 'SQLGlot'])
def test_removed_parser_field_is_explicit_configuration_error(bundle, value):
    from pydantic import ValidationError
    from sql_safety_executor.config.models import Mutation
    _, _, skills, save = bundle
    with pytest.raises(ValidationError) as raised:
        Mutation(managed_plan_parser=value)
    assert [(error['loc'], error['type']) for error in raised.value.errors()] == [
        (('managed_plan_parser',), 'extra_forbidden'),
    ]
    # TOML has no null value; every serializable legacy setting must fail
    # through the real loader, including the former default value.
    if value is not None:
        skills['skills']['mutation']['managed_plan_parser'] = value
        with pytest.raises(ConfigError, match=r'managed_plan_parser.*extra_forbidden'):
            load_config(save(use_skills=True))
