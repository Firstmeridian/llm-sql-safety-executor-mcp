# Relation calls and generated columns: source/package checkpoint

Source and independent wheel checks pass; **resident Host restart is pending**.
See the [formal record](../V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md).

- [Summary, resource hashes and JSON byte changes](evidence/final-checks.json): 3062 passed/four skipped, 57 new regressions, 77 matching runtime resources.
- [Source application records](evidence/source-canonical.json.gz) and [installed records](evidence/installed-canonical.json.gz): 538 child-stdio calls each, auto/legacy, 420 truth comparisons each; structured frames agree. These are application records, not raw JSON-RPC frames, notifications or model tasks.
- [Local component A/B/A samples](evidence/costs.json.gz): large phase drift prevents a speed or stable regression claim; ordinary-column payloads agree. Not stdio/Host/model latency.
- [Installed-wheel provenance](evidence/installed_resources.json): independent normal installation with existing frozen dependencies; temporary build paths are not persistent tools.
- [Frozen read-only native plan](evidence/native_plan.json) and [pre-restart resident results](evidence/native_before.json): current pages descriptor omits status; do not label it final acceptance.
- [Complete regression](checks/full-final.log), [types](checks/types-final.log) and [prompt contract](checks/prompts.log).

Reuse [the validation driver](../../../../scripts/validation/relation_calls_columns.py)
with a fresh `--output` path, or run
`python -m pytest -q tests/test_relation_calls_columns_v382.py`.
The driver creates/cleans disposable SQLite and TOML fixtures, not configured
databases. `--scope installed` labels the independent wheel run; resource hashes
and the actual package path establish its provenance.

The local batch retains the pre-repair working-source snapshot, original review
failures, intermediate test/runner/environment failures, complete logs and build
recipes. Only the selected final runs define this checkpoint. Earlier complete
Luna/model-cost records retain their earlier source scope. Append later resident
evidence independently; preserve this checkpoint's bytes.
