"""Fresh-process peak RSS/import cost of adding the isolated candidate."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
code = """
import json,resource,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
started=time.perf_counter_ns()
import sql_safety_executor.core.policy
base_ms=(time.perf_counter_ns()-started)/1e6
base_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
sys.path.insert(0,'/tmp/v381-sqlglot-probe')
sys.path.insert(0,sys.argv[2])
started=time.perf_counter_ns()
import sqlglot_candidate
extra_ms=(time.perf_counter_ns()-started)/1e6
rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'project_import_ms':base_ms,'candidate_import_ms':extra_ms,
    'project_peak_rss_kib':base_rss,'with_candidate_peak_rss_kib':rss,
    'peak_rss_increment_kib':rss-base_rss}))
"""
samples = [json.loads(subprocess.check_output(
    [sys.executable,"-c",code,str(ROOT/"src"),str(Path(__file__).parent)],
    text=True,timeout=45)) for _ in range(5)]
out=ROOT/"docs/validation/v3.8/phase123_2026_10_14/sqlglot_imports.json"
out.write_text(json.dumps({"samples":samples,
    "scope":"Five fresh processes import current project first, then isolated SQLGlot/candidate; Linux peak RSS, not live RSS or total MCP startup",
    "runtime_integrated":False},indent=2)+"\n")
print("Five fresh-process candidate import measurements complete")
