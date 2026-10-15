"""Record native CTE truth and matched policy costs from an explicit source."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import statistics
import sys
import time
from corpus import cases, native_safe

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=ROOT / "src")
parser.add_argument("--stage", required=True)
parser.add_argument("--mysql", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(args.source))
began = time.perf_counter()
from sql_safety_executor import load_config
from sql_safety_executor.core.policy import _extract_tables_from_sql, _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.mysql import MySQLAdapter
import sql_safety_executor.core.policy as policy_module
import_ms = (time.perf_counter() - began) * 1000
assert Path(policy_module.__file__).is_relative_to(args.source)
OUTPUT = ROOT / "docs/validation/v3.8/phase123_2026_10_14"
policy = ConnectionPolicy(allowed_tables=frozenset({"orders"}), allow_union=True)
db = sqlite3.connect(":memory:")
db.executescript('CREATE TABLE orders(n INTEGER, SLEEP INTEGER, BENCHMARK INTEGER);'
                 'INSERT INTO orders VALUES(7,1,2),(8,3,4),(9,5,6);'
                 'CREATE TABLE f(n INTEGER);INSERT INTO f VALUES(999);'
                 'CREATE TABLE " f "(n INTEGER);INSERT INTO " f " VALUES(555);'
                 'CREATE TABLE "K"(n INTEGER);INSERT INTO "K" VALUES(777);')
matrix = []

def inspect_case(name, sql, dialect, native):
    p = ConnectionPolicy(allowed_tables=frozenset({"orders"}), allow_union=True,
                         case_sensitive_tables=dialect == "mysql")
    start = time.perf_counter()
    verdict = _validate_sql_query_policy(None, sql, p, adapter=native if dialect == "mysql" else None)
    item = {"case": name, "dialect": dialect, "sql": sql,
            "policy": asdict(verdict), "policy_ms": (time.perf_counter()-start)*1000}
    try:
        item["current_dependencies"] = _extract_tables_from_sql(sql, case_sensitive=True, cte_case_sensitive=False)
    except ValueError:
        item["current_dependencies"] = None
    if native_safe(name):
        try:
            if dialect == "sqlite":
                rows = db.execute(sql, {"value": 7}).fetchall()
            else:
                rows = [tuple(r) for r in native.execute(sql, params={"value": 7})]
            item["native"] = {"success": True, "rows": [[str(v) if not isinstance(v, (str,int,float,type(None))) else v for v in row] for row in rows]}
        except Exception as error:
            item["native"] = {"success": False, "error_class": type(error).__name__}
            # Only SQLite fixture errors, never server driver text.
            if dialect == "sqlite":
                item["native"]["error"] = str(error)
    else:
        item["native"] = {"executed": False, "reason": "No live lock/function side effects or multi-statement execution"}
    return item

for name, sql in cases("sqlite"):
    matrix.append(inspect_case(name, sql, "sqlite", db))
server = None
if args.mysql:
    config = load_config(ROOT / "config/server.toml").connections["trade_analysis_mysql"]
    server = MySQLAdapter(config)
    capability_start = time.perf_counter()
    capability = server.resolve_cte_case_sensitive()
    capability_ms = (time.perf_counter()-capability_start)*1000
    for name, sql in cases("mysql"):
        matrix.append(inspect_case(name, sql, "mysql", server))
    version, setting = tuple(server.execute("SELECT VERSION(), @@lower_case_table_names")[0])
    server.close()
queries = [sql for name, sql in cases("sqlite") if name in {
    "cte_ascii_case", "cte_ordered_dependencies", "ordinary_function",
    "literal_function_names", "function_sleep", "cte_qualified_physical"}]
samples = {sql: [] for sql in queries}
for sql in queries:
    _validate_sql_query_policy(None, sql, policy)
for repeat in range(80):
    for sql in queries:
        start = time.perf_counter_ns()
        _validate_sql_query_policy(None, sql, policy)
        samples[sql].append((time.perf_counter_ns()-start)/1e6)
timings = [{"sql": sql, "samples": len(values), "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[int(len(values)*.95)-1], "min_ms": min(values),
            "raw_ms": values} for sql, values in samples.items()]
record = {"stage": args.stage, "version": "3.8.1",
    "policy_source_sha256": hashlib.sha256(Path(policy_module.__file__).read_bytes()).hexdigest(),
    "sqlite_version": sqlite3.sqlite_version, "import_ms": import_ms,
    "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "matrix": matrix, "timings": timings,
    "not_measured": ["Independent MySQL settings 0/2 and MariaDB unavailable", "No protocol/model cost inferred from policy timings"],
    "database_changes": "Only private in-memory SQLite fixtures; MySQL reads existing orders, no writes"}
if args.mysql:
    record["mysql_cte_exact"] = capability
    record["mysql_version"] = version
    record["mysql_lower_case_table_names"] = setting
    record["mysql_cold_capability_ms"] = capability_ms
    record["mysql_identity"] = "Existing configured Oracle MySQL instance; no credentials/host/account exported"
(OUTPUT / (args.stage + "_policy_matrix.json")).write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n")
print(json.dumps({"stage": args.stage, "cases": len(matrix), "samples": sum(len(v) for v in samples.values())}))
db.close()
