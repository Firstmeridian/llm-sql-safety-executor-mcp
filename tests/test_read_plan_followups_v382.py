"""Single-read trivia and actual managed bindings retain independent gates."""
from dataclasses import replace
import sqlite3
from types import SimpleNamespace

from fastmcp import Client
import pytest

from sql_safety_executor.core import policy as policy_module
from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.core.managed_sql import check_managed_sql
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.transport import named_parameters, statement_text
from sql_safety_executor.skills.mutation import ManagedMutationPlan, ManagedMutationValue, validate_managed_mutation_plan
from tests.test_managed_parser_v382 import managed_server as managed_server, UPDATE, PARAMS
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize('dialect', ['sqlite', 'mysql'])
@pytest.mark.parametrize('base', ['SELECT 7 AS n', 'WITH chosen AS (SELECT 7 AS n) SELECT n FROM chosen',
                                 'EXPLAIN SELECT n FROM orders', 'EXPLAIN UPDATE orders SET n=99'])
@pytest.mark.parametrize('tail', [';', '; /* tail */', '; -- tail\n', ' /* before */; /* after */',
                                 '; /* semicolon ; and keyword SELECT */\n-- tail\n'])
def test_one_executable_read_with_trailing_comment(dialect, base, tail):
    sql = base + tail
    analysis = analyze_sql(sql, DialectContext(dialect))
    assert policy_module._analysis_decision(analysis, ConnectionPolicy(allowed_tables=frozenset({'orders'}))).allowed
    assert analysis.source_sql == sql
    if dialect == 'sqlite':
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE orders(n);INSERT INTO orders VALUES(7);')
            assert db.execute(sql).fetchall()
            assert db.execute('SELECT n FROM orders').fetchall() == [(7,)]


@pytest.mark.parametrize('sql', [
    'SELECT 7; SELECT 99', 'SELECT 7; /* tail */ SELECT 99',
    'SELECT 7; -- tail\n DELETE FROM orders',
    'SELECT 7; /*! +1 */', 'SELECT 7; /*+ SET_VAR(sql_mode=\'ANSI_QUOTES\') */',
    'SELECT 7; /*+ UNKNOWN_HINT(orders) */',
])
def test_comments_do_not_hide_real_mysql_statements_or_directives(sql):
    analysis = analyze_sql(sql, DialectContext('mysql'))
    assert not policy_module._analysis_decision(analysis, ConnectionPolicy(allowed_tables=frozenset({'*'}))).allowed


def test_hint_trivia_does_not_change_shape_or_real_targets():
    context = DialectContext('mysql')
    for sql in ['SELECT 7 AS n; /*+ NO_ICP(orders) */', '/*+ NO_ICP(orders) */ SELECT 7 AS n; /* tail */']:
        assert analyze_sql(sql, context).complete
        assert policy_module._analysis_decision(analyze_sql(sql, context), ConnectionPolicy()).allowed
    analysis = analyze_sql('/*+ NO_ICP(orders) */ SELECT ? AS n', context)
    assert policy_module.classify_analysis(analysis).error_code == 'parameter_binding_unsupported'
    policy = ConnectionPolicy(allowed_tables=frozenset({'orders'}), case_sensitive_tables=True)
    assert policy_module._validate_sql_query_policy(None, 'SELECT /*+ NO_ICP(orders) */ * FROM secret; /* tail */', policy).error_code == 'table_access_denied'
    assert policy_module._analysis_decision(analyze_sql('SELECT SLEEP(0); /* tail */', context), policy).error_code == 'expensive_function_denied'


@pytest.mark.parametrize('parser', ['sqlglot', 'sqlparse'])
@pytest.mark.parametrize('context', [DialectContext('sqlite'), DialectContext('mysql', frozenset({'ANSI_QUOTES'}))])
@pytest.mark.parametrize('sql', ["UPDATE orders SET note=':business', n=:n",
                                'UPDATE /* :comment */ orders SET n=:n',
                                'UPDATE orders SET ":business"=:n',
                                "UPDATE orders SET note='\\:business', n=:n"])
def test_plan_bindings_use_the_execution_transport(sql, parser, context):
    plan = ManagedMutationPlan(sql, (ManagedMutationValue.constant('n', 7),), 1)
    assert validate_managed_mutation_plan(plan, parser=parser, context=context) is plan
    assert named_parameters(sql, context) == frozenset({'n'})
    assert set(statement_text(sql, context).compile().params) == {'n'}
    for parameters in [(), (ManagedMutationValue.constant('ghost', 7),),
                       (*plan.parameters, ManagedMutationValue.constant('ghost', 7))]:
        with pytest.raises(TypeError, match='exactly match SQL named binds'):
            validate_managed_mutation_plan(replace(plan, parameters=parameters), parser=parser, context=context)


def test_binding_names_are_part_of_runtime_pure_cache_identity(managed_server):
    runtime = managed_server().gateway_runtime
    sql = 'UPDATE orders SET n=:n'
    context = DialectContext('sqlite')
    good = runtime.classify_managed_plan(sql, context, 'sqlglot', frozenset({'n'}))
    assert good.allowed
    assert runtime.classify_managed_plan(sql, context, 'sqlglot', frozenset({'n'})) is good
    assert not runtime.classify_managed_plan(sql, context, 'sqlglot', frozenset({'ghost'})).allowed
    assert runtime.classify_managed_plan.cache_info().currsize == 2


@pytest.mark.parametrize('parser', ['sqlglot', 'sqlparse'])
def test_startup_candidate_cannot_replace_actual_mode_binding_identity(parser):
    # Both statements are syntactically valid, but backslash quoting changes
    # whether :ghost is data or a real placeholder. Startup must try the next
    # candidate if only its syntax passed; execution must use its actual mode.
    sql = "UPDATE orders SET n='\\' OR :ghost -- '"
    empty = ManagedMutationPlan(sql, (), 1)
    ghost = replace(empty, parameters=(ManagedMutationValue.constant('ghost', 7),))
    assert validate_managed_mutation_plan(empty, parser=parser) is empty
    assert validate_managed_mutation_plan(ghost, parser=parser) is ghost
    for context in [DialectContext('sqlite'), DialectContext('mysql', frozenset({'NO_BACKSLASH_ESCAPES'}))]:
        assert validate_managed_mutation_plan(ghost, parser=parser, context=context) is ghost
        with pytest.raises(TypeError, match='exactly match SQL named binds'):
            validate_managed_mutation_plan(empty, parser=parser, context=context)
    assert validate_managed_mutation_plan(empty, parser=parser, context=DialectContext('mysql')) is empty
    with pytest.raises(TypeError, match='exactly match SQL named binds'):
        validate_managed_mutation_plan(ghost, parser=parser, context=DialectContext('mysql'))


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('parser', ['sqlglot', 'sqlparse'])
async def test_commented_mutation_full_lifecycle_preserves_literal_and_token(managed_server, mode, parser):
    sql = "UPDATE /* :comment */ orders SET status=:new_status,note=':business' WHERE id=:order_id AND status=:expected_status"
    # The explicit legacy classifier retains its old comment-only-statement
    # limitation. Exercise its binding fix without inventing AST equivalence.
    if parser == 'sqlglot':
        sql += '; /* tail */'
    server = managed_server(parser=parser, sql=sql)
    runtime = server.gateway_runtime
    assert UPDATE in runtime.catalog.get_skills_cache()
    async with Client(server, mode=mode) as client:
        listed = (await client.call_tool('list_skills', {'search': UPDATE, 'detail_level': 'full'})).structured_content
        assert next(item for item in listed['skills'] if item['name'] == UPDATE)['executable']
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success'] and preview['preview']['preview_sql'] == sql
        assert set(preview['preview']['bound_params']) == {'order_id', 'new_status', 'expected_status'}
        args = {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': preview['preview_token']}
        result = (await client.call_tool('execute_mutation_skill', args)).structured_content
        assert result['success'] and result['execution_outcome'] == 'committed'
        assert (await client.call_tool('execute_mutation_skill', args, raise_on_error=False)).is_error
    with sqlite3.connect(runtime.config.connections['demo'].sqlite_database_path) as db:
        assert db.execute('SELECT status,note FROM orders').fetchall() == [('confirmed', ':business')]


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_tail_query_skill_load_discovery_detail_execution(managed_server, tmp_path, mode):
    directory = tmp_path / 'skills/tail-read'
    directory.mkdir()
    sql = "SELECT n,':business' AS note FROM main.orders; /* :not_a_bind */"
    (directory / 'skill_def.md').write_text('---\nname: tail-read\ntype: query\nsource: query.sql\nrisk: low\ndescription: Tail read\ndatabases: [sqlite]\ntables: [main.orders]\nparams: {}\n---\n')
    (directory / 'query.sql').write_text(sql)
    server = managed_server()
    async with Client(server, mode=mode) as client:
        listed = (await client.call_tool('list_skills', {'search': 'tail-read', 'detail_level': 'full'})).structured_content
        assert [value['name'] for value in listed['skills']] == ['tail-read']
        assert listed['skills'][0]['executable']
        detail = (await client.call_tool('get_skill_detail', {'skill_name': 'tail-read'})).structured_content
        assert detail['skill']['executable']
        for tool, arguments in [('query', {'sql': sql}), ('execute_query_skill', {'skill_name': 'tail-read', 'params': {}})]:
            result = (await client.call_tool(tool, arguments)).structured_content
            assert result['success'] and result['data'] == [{'n': 7, 'note': ':business'}]


def test_startup_stops_on_allow_and_preserves_first_refusal(monkeypatch):
    runtime = SimpleNamespace(registry=SimpleNamespace(get_config=lambda: SimpleNamespace(policy=ConnectionPolicy(allowed_tables=frozenset({'*'})))))
    original = policy_module.analyze_sql
    calls = []
    def counted(sql, context):
        calls.append(context)
        return original(sql, context)
    monkeypatch.setattr(policy_module, 'analyze_sql', counted)
    assert policy_module._validate_sql_template_startup_policy(runtime, 'SELECT 7').allowed
    assert len(calls) == 1
    calls.clear()
    result = policy_module._validate_sql_template_startup_policy(runtime, 'DELETE FROM orders')
    assert result.error_code == 'read_only_required' and len(calls) == 5
