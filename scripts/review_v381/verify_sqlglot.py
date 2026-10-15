"""Compare an isolated SQLGlot projection with current policy/native evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from corpus import cases

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/validation/v3.8/phase123_2026_10_14"
sys.path.insert(0, "/tmp/v381-sqlglot-probe")
start = time.perf_counter_ns()
import sqlglot
from sqlglot_candidate import projection
import_ms = (time.perf_counter_ns()-start)/1e6
records = []
baseline = json.loads((OUTPUT/"baseline_policy_matrix.json").read_text())
for old in baseline["matrix"]:
    try:
        new = projection(old["sql"], old["dialect"])
        records.append({**old, "candidate":new,
            "physical_dependency_agreement":old["current_dependencies"] == new["physical_tables"]})
    except Exception as error:
        records.append({**old,"candidate_error":type(error).__name__})
# Native-informed assertions, independent of agreement with the old parser.
expected = {
    "cte_ascii_case": [], "cte_column_list": [], "cte_ordered_dependencies":["orders"],
    "cte_physical_shadow":[], "cte_nested_shadow":[], "cte_recursive":[],
    "cte_quoted_space_alias":[], "cte_quoted_space_physical":[" f "],
    "cte_unicode_identity":["K"], "cte_qualified_physical":["main.f"],
    "sqlite_in_table":["f"], "sqlite_not_in_table":["f"],
}
verified = 0
for row in records:
    if row["case"] in expected:
        assert row["candidate"]["physical_tables"] == expected[row["case"]], row
        verified += 1
    if row["case"] == "cte_forward":
        assert row["candidate"]["physical_tables"] == ([] if row["dialect"]=="sqlite" else ["orders"])
    if row["case"] == "cte_recursive_implicit":
        assert row["candidate"]["physical_tables"] == ([] if row["dialect"]=="sqlite" else ["f"])
    if row["case"].startswith("function_"):
        assert row["candidate"]["functions"]
extra = [
    ('WITH SLEEP(n) AS (SELECT 7) SELECT n FROM SLEEP',"sqlite",[],[]),
    ('SELECT "SLEEP"(0)',"sqlite",[],["sleep"]),
    ('SELECT ſleep(0)',"sqlite",[],["ſleep"]),
    ('WITH F AS (SELECT 7) SELECT * FROM f',"mysql",["f"],[]),
    ('SELECT 7 IN main.f',"sqlite",["main.f"],[]),
    ('SELECT 7 IN pragma_table_info(\'orders\')',"sqlite",[],["pragma_table_info"]),
    ('EXPLAIN SELECT COUNT(*) FROM orders',"mysql",["orders"],["count"]),
    ('EXPLAIN FORMAT=JSON SELECT * FROM orders',"mysql",["orders"],[]),
    ('DESCRIBE orders',"mysql",["orders"],[]),
    ('SELECT CAST(7 AS SIGNED) AS n',"mysql",[],["cast"]),
    ('SELECT :value AS n',"mysql",[],[]),
]
extras = []
for sql,dialect,tables,funcs in extra:
    item = projection(sql,dialect,cte_exact=sql.startswith("WITH F") and dialect=="mysql")
    assert item["physical_tables"]==tables and item["functions"]==funcs, (sql,item)
    extras.append({"sql":sql,"dialect":dialect,"candidate":item})
timings=[]
for name,sql in cases("sqlite"):
    if name not in {"cte_ascii_case","cte_ordered_dependencies","ordinary_function","literal_function_names","function_sleep","cte_qualified_physical"}:
        continue
    values=[]
    projection(sql,"sqlite")
    for _ in range(80):
        start=time.perf_counter_ns();projection(sql,"sqlite");values.append((time.perf_counter_ns()-start)/1e6)
    timings.append({"sql":sql,"raw_ms":values,"median_ms":statistics.median(values),
        "p95_ms":sorted(values)[75]})
record={"sqlglot_version":sqlglot.__version__,"runtime_integrated":False,"import_ms":import_ms,
    "peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"cases":records,"extras":extras,
    "native_informed_dependency_assertions":verified,"timings":timings,
    "limits":["No production authorization decision or SQL rewriting",
        "SQLite EXPLAIN falls back to an opaque Command; MySQL Explain/Describe is structured",
        "SQLite forward/implicit recursion semantics require project scope rules",
        "Only the measured MySQL CTE rule is used here; no vendor-version generalization",
        "Virtual relations require policy/object semantics, not a Table-only grant check",
        "No full schema-dependent name resolution, alias cycle validation or server syntax guarantee"]}
(OUTPUT/"sqlglot_probe.json").write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"version":sqlglot.__version__,"cases":len(records),"extras":len(extras),
    "verified":verified,"opaque":sum("opaque_command" in r.get("candidate",{}).get("unsupported",[]) for r in records)}))
