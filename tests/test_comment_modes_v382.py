"""Dialect comments, bounded optimizer hints and actual-mode NOT semantics."""
from itertools import product
import sqlite3

import pytest
from fastmcp import Client
from sqlglot import exp

from sql_safety_executor.core.analysis import analyze_sql, _tokens
from sql_safety_executor.core.managed_sql import check_managed_sql
from sql_safety_executor.core.policy import _analysis_decision, _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext
from tests.test_managed_parser_v382 import managed_server as managed_server, PARAMS, UPDATE
from tests.test_v38_config import bundle as bundle

PLAN_HINTS = [
    'NO_ICP(orders)', 'NO_RANGE_OPTIMIZATION(orders PRIMARY, idx_n)',
    'QB_NAME(qb) JOIN_FIXED_ORDER()', 'BKA(orders) NO_BKA(other)',
    'SEMIJOIN(FIRSTMATCH, LOOSESCAN)', 'NO_ICP(orders@qb)',
    'NO_ICP(` f `)', 'NO_ICP(`  f  `)', 'NO_ICP(`main.orders`)',
]
BLOCKED_HINTS = [
    "SET_VAR(sql_mode='ANSI_QUOTES')", 'SET_VAR(foreign_key_checks=OFF)',
    'RESOURCE_GROUP(batch)', 'MAX_EXECUTION_TIME(0)', 'UNKNOWN_HINT(orders)',
    'NO_ICP(SLEEP(0))', 'NO_ICP(orders) SET_VAR(unique_checks=OFF)',
    'NO_ICP(orders),', 'NO_ICP(orders,,other)', 'NO_ICP(orders) --x',
    'NO_ICP(orders) /*! +1 */', 'NO_ICP(orders) ; SELECT 99', 'NO_ICP(orders',
]


@pytest.mark.parametrize('comment', ['/*+ ' + hint + ' */' for hint in PLAN_HINTS + BLOCKED_HINTS if '/*' not in hint] + [
    '/*! SLEEP(0) */', '/*M! SLEEP(0) */', '--suffix\n',
])
def test_sqlite_comments_match_native_without_hidden_calls(comment):
    sql = f'SELECT {comment} n FROM orders'
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE orders(n);INSERT INTO orders VALUES(7);')
        assert db.execute(sql).fetchall() == [(7,)]
    analysis = analyze_sql(sql, DialectContext('sqlite'))
    assert analysis.complete and analysis.relations == (RelationReference('orders'),)
    assert not analysis.functions
    assert _analysis_decision(analysis, ConnectionPolicy(allowed_tables=frozenset({'orders'}))).allowed
    assert check_managed_sql(f'UPDATE {comment} orders SET n=7', DialectContext('sqlite')).allowed


@pytest.mark.parametrize('hint', PLAN_HINTS)
@pytest.mark.parametrize('high_not', [False, True])
def test_mysql_plan_hints_do_not_become_dependencies_or_functions(hint, high_not):
    context = DialectContext('mysql', frozenset({'HIGH_NOT_PRECEDENCE'}) if high_not else frozenset())
    sql = f'SELECT /*+ {hint} */ n FROM orders'
    analysis = analyze_sql(sql, context)
    assert analysis.complete and analysis.relations == (RelationReference('orders'),)
    assert not analysis.functions
    assert _analysis_decision(analysis, ConnectionPolicy(allowed_tables=frozenset({'orders'}))).allowed
    assert check_managed_sql(f'UPDATE /*+ {hint} */ orders SET n=7', context).allowed


@pytest.mark.parametrize('hint', [hint for hint in BLOCKED_HINTS if '/*' not in hint])
def test_mysql_nonplan_or_incomplete_hints_stay_explicitly_unsupported(hint):
    context = DialectContext('mysql')
    assert analyze_sql(f'SELECT /*+ {hint} */ n FROM orders', context).statement_kind == 'unsafe_comment'
    assert check_managed_sql(f'UPDATE /*+ {hint} */ orders SET n=7', context).error_code == 'managed_plan_comment_unsupported'


@pytest.mark.parametrize('comment', [
    '/*+ NO_ICP(orders) */ /*+ SET_VAR(sql_mode=\'ANSI_QUOTES\') */',
    '/*+ NO_ICP(orders) */ /*! ,n=99 */',
    '/* ordinary */ /*M! ,n=99 */', '--suffix\n',
])
def test_every_mysql_comment_span_is_checked(comment):
    assert check_managed_sql(f'UPDATE {comment} orders SET n=7', DialectContext('mysql')).error_code == 'managed_plan_comment_unsupported'


@pytest.mark.parametrize('dialect', ['sqlite', 'mysql'])
def test_hint_text_inside_data_and_quoted_names_remains_business_data(dialect):
    context = DialectContext(dialect)
    assert analyze_sql("SELECT '/*+ SET_VAR(sql_mode=''x'') */' AS n", context).complete
    analysis = analyze_sql('SELECT n FROM `/*+ SET_VAR */`', context)
    assert analysis.complete and analysis.relations == (RelationReference('/*+ SET_VAR */'),)


def test_mysql_hints_do_not_grant_tables_or_hide_real_functions():
    policy = ConnectionPolicy(allowed_tables=frozenset({'orders'}), case_sensitive_tables=True)
    context = DialectContext('mysql')
    assert _validate_sql_query_policy(None, 'SELECT /*+ NO_ICP(orders) */ n FROM secret', policy).error_code == 'table_access_denied'
    assert _analysis_decision(analyze_sql('SELECT /*+ NO_ICP(secret) */ SLEEP(0) FROM orders', context), policy).error_code == 'expensive_function_denied'
    analysis = analyze_sql('SELECT /*+ NO_ICP(secret) */ n FROM orders', context)
    assert analysis.relations == (RelationReference('orders'),)
    assert _analysis_decision(analysis, policy).allowed


@pytest.mark.parametrize('dialect', ['sqlite', 'mysql'])
def test_nested_comment_with_extra_terminator_remains_rejected(dialect):
    sql = 'UPDATE /*+ NO_ICP(orders) /*! +1 */ */ orders SET n=7'
    assert not check_managed_sql(sql, DialectContext(dialect)).allowed
    if dialect == 'sqlite':
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE orders(n)')
            with pytest.raises(sqlite3.OperationalError):
                db.execute('EXPLAIN ' + sql)


@pytest.mark.parametrize('bits', list(product((False, True), repeat=4)))
@pytest.mark.parametrize('operator', ['NOT', '!'])
def test_mode_specific_prefix_not_grouping(bits, operator):
    names = ('ANSI_QUOTES', 'NO_BACKSLASH_ESCAPES', 'PIPES_AS_CONCAT', 'HIGH_NOT_PRECEDENCE')
    context = DialectContext('mysql', frozenset(name for name, on in zip(names, bits) if on))
    sql = f'SELECT {operator} 1 BETWEEN -5 AND 5'
    dialect, tokens = _tokens(sql, context)
    expression = dialect.parser().parse(tokens, sql)[0].expressions[0]
    tight = operator == '!' or bits[-1]
    assert isinstance(expression, exp.Between if tight else exp.Not)
    assert isinstance(expression.this, exp.Not if tight else exp.Between)
    assert analyze_sql(sql, context).complete
    assert check_managed_sql(f'UPDATE orders SET n=7 WHERE {operator} 1 BETWEEN -5 AND 5', context).allowed


@pytest.mark.parametrize('expression', [
    '1 NOT IN (2,3)', '1 NOT BETWEEN 2 AND 3', '1 IS NOT NULL',
    "'x' NOT LIKE 'y'", 'NOT EXISTS(SELECT 1)',
])
def test_high_not_does_not_replace_infix_not_grammar(expression):
    low = DialectContext('mysql')
    high = DialectContext('mysql', frozenset({'HIGH_NOT_PRECEDENCE'}))
    trees = []
    for context in (low, high):
        dialect, tokens = _tokens('SELECT ' + expression, context)
        trees.append(dialect.parser().parse(tokens, 'SELECT ' + expression)[0])
    assert trees[0] == trees[1]


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
@pytest.mark.parametrize('parser', ['sqlglot', 'sqlparse'])
async def test_commented_managed_plan_keeps_original_sql_and_binds(managed_server, monkeypatch, mode, parser):
    sql = 'UPDATE /*+ SET_VAR(sql_mode=\'literal only in SQLite\') SLEEP(0) */ orders SET status=:new_status WHERE id=:order_id AND status=:expected_status'
    server = managed_server(parser, sql)
    adapter = server.gateway_runtime.registry.get_adapter('demo')
    original = adapter.execute_write
    observed = []
    def capture(statement, params, **kwargs):
        observed.append((statement, dict(params)))
        return original(statement, params, **kwargs)
    monkeypatch.setattr(adapter, 'execute_write', capture)
    async with Client(server, mode=mode) as client:
        raw = (await client.call_tool('query', {'sql': 'SELECT /*+ SLEEP(0) */ n FROM orders'})).structured_content
        assert raw['success'] and raw['data'] == [{'n': 7}]
        preview = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS})).structured_content
        assert preview['success'] and preview['preview']['preview_sql'] == sql and not observed
        result = (await client.call_tool('execute_mutation_skill', {'skill_name': UPDATE, 'params': PARAMS, 'confirm': True, 'preview_token': preview['preview_token']})).structured_content
        assert result['success'] and result['execution_outcome'] == 'committed'
    assert observed == [(sql, {'new_status': 'confirmed', 'order_id': 1, 'expected_status': 'pending'})]


def test_explicit_sqlparse_rollback_does_not_silently_gain_new_rules():
    sql = 'UPDATE /*+ SET_VAR(foreign_key_checks=OFF) */ orders SET n=7'
    context = DialectContext('mysql')
    assert check_managed_sql(sql, context, 'sqlparse').allowed
    assert not check_managed_sql(sql, context, 'sqlglot').allowed
