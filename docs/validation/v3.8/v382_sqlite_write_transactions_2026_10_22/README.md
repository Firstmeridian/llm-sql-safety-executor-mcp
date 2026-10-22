# DRR-142/143: SQLite physical writes and completed counts

2026-10-22 source/package checkpoint. Resident restart and 12 limited existing-alias checks remain pending. Actual writes use disposable private files; no configured write was confirmed. Earlier failed assessments, model tasks and their costs remain separately scoped.

- [Contract, change table, costs and limits](../V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md).
- [Final source/package and old-evidence checks](final_checks.json.gz): 3493 full passes/four optional skips, 120 new regressions, clean types/prompts, 77 equal installed resources, three unchanged TOMLs and 77 prior seals/2478 records.
- [Source application records](source_client.json.gz) and [normal-wheel records](installed_client.json.gz): each432 calls/136 preview-confirm-replay flows over both classifiers, modes and transports, independent post-cleanup truth, token consumption and continued denials. Tokens redacted; these are application records, not complete protocol frames or provider tokens.
- [All serial A/B/A cost samples](cost.json.gz): immediate pre-repair frozen source versus final source; ordinary commit approximately9ms, mismatch rollback baseline drift retained. No CTE/RETURNING like-for-like speed claim or new full-model test.
- [Installation provenance and 77 resources](installed_resources.json.gz), [runtime versions](runtime_versions.json.gz), [pending resident plan](resident_plan.json.gz) and [pre-repair hashes](baseline.json.gz).

Logs retain initial fixture/argument/sandbox preparation errors plus final success; `.log.gz` files are compressed text. Compressed scripts and the new test preserve reproducibility; the normal wheel is stored in `distributions/`. Reuse the existing frozen dependencies and installed interpreter where available. No new runtime dependency, global installation, generic cache, parser framework or TOML switch.

`sqlite_writes.py.gz` is the repository validation script: source mode takes `--source /absolute/src --output /fresh/result.json.gz`; normal-wheel mode omits --source and asserts site-packages. It creates and deletes its own file database, Skills and TOMLs. `cost.py.gz` uses the exact private baseline tree, whose hashes are preserved; the two changed baseline modules are also provided. Other runtime resource identities match the normal wheel.

Each manifest declares stored SHA-256, byte count and decoded hashes for gzip entries. Historical seals remain unchanged. This checkpoint intentionally retains pending resident status; a later native supplement must not rewrite these bytes.
