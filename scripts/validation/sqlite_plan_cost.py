"""Serial A/B/A policy-and-adapter timings for SQLite explanation plans.

No MCP/Host/model timing or tokens. Failed-before/successful-after workloads are
functional comparisons, not equal-work overhead measurements. Private DB only.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time


def main(args):
    sys.path.insert(0,str(args.source))
    logging.disable(logging.CRITICAL)
    began=time.perf_counter()
    import sql_safety_executor
    from sql_safety_executor.core.policy import _prepare_sql_read
    from sql_safety_executor.database.errors import DatabaseQueryError
    from sql_safety_executor.database.models import ConnectionPolicy,DatabaseConfig
    import sql_safety_executor.database.sqlite as module
    startup_ms=(time.perf_counter()-began)*1000
    original=module.build_read_guard
    builds=0
    def counted(*a,**kw):
        nonlocal builds
        builds+=1
        return original(*a,**kw)
    module.build_read_guard=counted
    queries={
        'ordinary_read':'SELECT n FROM orders',
        'ordinary_plan':'EXPLAIN UPDATE orders SET n=99',
        'trigger_view_count':'EXPLAIN INSERT INTO orders VALUES(99)',
        'trigger_cte_count':'EXPLAIN INSERT INTO cte_orders VALUES(99)',
        'with_replace':'EXPLAIN WITH chosen(n) AS (SELECT 99) REPLACE INTO orders SELECT n FROM chosen',
        'update_or':'EXPLAIN UPDATE OR IGNORE orders SET n=99',
    }
    with tempfile.TemporaryDirectory(prefix='v382-plan-cost-') as temporary:
        path=Path(temporary)/'fixture.sqlite'
        with sqlite3.connect(path) as db:
            db.executescript('CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE audit_log(n); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13); CREATE VIEW normal_view AS SELECT n FROM hidden; CREATE TRIGGER log_orders AFTER INSERT ON orders BEGIN INSERT INTO audit_log SELECT COUNT(*) FROM normal_view; END;')
            db.executescript('CREATE TABLE cte_orders(n); INSERT INTO cte_orders VALUES(7); CREATE TRIGGER cte_log AFTER INSERT ON cte_orders BEGIN INSERT INTO audit_log SELECT (WITH chosen(n) AS MATERIALIZED (SELECT n FROM normal_view) SELECT COUNT(*) FROM chosen); END;')
        policy=ConnectionPolicy(allowed_tables=frozenset(['orders','cte_orders','audit_log','normal_view']))
        adapter=module.SQLiteAdapter(config=DatabaseConfig('probe','sqlite',5,5,policy,sqlite_database_path=str(path)))
        assert adapter.connect()
        statements=[]
        with adapter._engine.connect() as db:
            db.connection.dbapi_connection.set_trace_callback(statements.append)
        samples={key:[] for key in queries}
        try:
            for iteration in range(44):
                for name,sql in queries.items():
                    statements.clear();builds=0
                    began=time.perf_counter_ns()
                    plan=_prepare_sql_read(None,sql,policy,adapter=adapter)
                    status=plan.decision.error_code
                    rows=[]
                    if plan.decision.allowed:
                        try:
                            rows=adapter.execute_read(sql,policy=policy,analysis=plan.analysis)
                        except DatabaseQueryError as error:
                            status=error.error_code
                    elapsed_ms=(time.perf_counter_ns()-began)/1e6
                    if iteration>=3:
                        samples[name].append(dict(ms=elapsed_ms,status=status,row_count=len(rows),
                            prepare_attempts=builds,catalog_statements=sum('sqlite_master' in value or value=='PRAGMA database_list' for value in statements)))
            assert adapter.execute('SELECT n FROM orders')==[(7,)]
            assert adapter.execute('SELECT n FROM hidden')==[(13,)]
            assert adapter.execute('SELECT n FROM audit_log')==[]
        finally:
            adapter.close()
    package=Path(sql_safety_executor.__file__).parent
    summary={name:dict(median_ms=statistics.median(row['ms'] for row in values),p95_ms=sorted(row['ms'] for row in values)[38],
        statuses=sorted({row['status'] or 'success' for row in values}),prepare_attempts=sorted({row['prepare_attempts'] for row in values}),
        catalog_statements=sorted({row['catalog_statements'] for row in values})) for name,values in samples.items()}
    output=dict(stage=args.stage,source=str(args.source),startup_ms=startup_ms,queries=queries,samples=samples,summary=summary,
        source_sha256={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in {'.py','.md'}},
        data_unchanged=True,scope=__doc__)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(gzip.compress((json.dumps(output,ensure_ascii=False,indent=2)+'\n').encode(),mtime=0))
    print(json.dumps(dict(stage=args.stage,summary=summary)))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--stage',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.source=args.source.resolve();args.output=args.output.resolve()
    if args.output.exists():
        parser.error('Output exists; choose a fresh batch')
    main(args)
