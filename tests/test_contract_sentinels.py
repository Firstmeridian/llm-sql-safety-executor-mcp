"""Portable target-specific sentinels; no archive, old checkout or DB server.

Only private function objects are altered. A compilation error, unrelated
exception or missed branch fails the test; it never counts as defect detection.
"""
import ast
import inspect
import json
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from sql_safety_executor.core import results


def result_variant(kind):
    functions = (results._serialize_result, results._truncate_result, results._prepare_read_result)
    tree = ast.parse('\n\n'.join(inspect.getsource(function) for function in functions))

    class Change(ast.NodeTransformer):
        hits = 0

        def visit_If(self, node):
            self.generic_visit(node)
            if kind == 'duplicate' and ast.unparse(node.test) == 'len(set(labels)) != len(labels)':
                self.hits += 1
                return []
            if kind == 'oversize' and ast.unparse(node.test) == 'candidate > char_limit':
                self.hits += 1
                node.test = ast.BoolOp(op=ast.And(), values=[node.test, ast.Compare(
                    left=ast.Name(id='returned_rows', ctx=ast.Load()),
                    ops=[ast.Gt()], comparators=[ast.Constant(value=0)],
                )])
            return node

    change = Change()
    tree = ast.fix_missing_locations(change.visit(tree))
    assert change.hits == 1, 'Sentinel must change exactly the intended branch'
    namespace = dict(vars(results))
    exec(compile(tree, '<private-contract-sentinel>', 'exec'), namespace)
    return namespace['_prepare_read_result']


@pytest.mark.parametrize('kind', ['duplicate', 'oversize'])
def test_result_contract_detects_target_variant_and_preserves_control(kind):
    runtime = SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(
        limits=SimpleNamespace(result_rows=100, result_chars=16000))))
    sql = ('SELECT 7 AS n,99 AS n' if kind == 'duplicate' else
           "SELECT printf('%.*c',20000,'x') AS payload")
    # Expectations come from the native driver, not the project result encoder.
    with sqlite3.connect(':memory:') as native:
        cursor = native.execute(sql)
        labels = [column[0] for column in cursor.description]
        truth = cursor.fetchall()
    engine = create_engine('sqlite:///:memory:')
    try:
        with engine.connect() as db:
            rows = db.exec_driver_sql(sql).fetchall()
            control = db.exec_driver_sql('SELECT 7 AS n').fetchall()
        variant = result_variant(kind)
        actual_control = results._prepare_read_result(runtime, control)
        assert actual_control == variant(runtime, control)
        assert actual_control['data'] == [{'n': 7}]
        if kind == 'duplicate':
            assert labels == ['n', 'n'] and truth == [(7, 99)]
            with pytest.raises(results.ReadResultError) as raised:
                results._prepare_read_result(runtime, rows)
            assert raised.value.error_code == 'duplicate_result_columns'
            broken = variant(runtime, rows)
            assert broken['data'] == [{'n': 99}]  # Concrete loss of the first value.
        else:
            assert labels == ['payload'] and len(truth[0][0]) == 20000
            current = results._prepare_read_result(runtime, rows)
            broken = variant(runtime, rows)
            assert current['data'] == [] and current['truncation_reason'] == 'char_limit'
            assert len(json.dumps(current['data'])) <= 16000
            assert len(broken['data']) == 1
            assert len(json.dumps(broken['data'], separators=(',', ':'))) > 16000
    finally:
        engine.dispose()


def test_missing_variant_target_is_a_failure():
    with pytest.raises(AssertionError, match='exactly the intended branch'):
        result_variant('nonexistent')
