# DRR-141 resident-channel checkpoint: not closed

2026-10-21, after the owner reported a restart. [Current report](../../V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md).

| Channel | Frozen checks | Outcome |
| --- | ---: | --- |
| Native tools in this session | 12 | 7 pass;5 describe/full cases omit actual PRIMARY positions |
| Fresh configured CLI/stdin-stdout auto | 12 | All pass against the same plan and independent native metadata |

- `native_results.json.gz` preserves actual failures; `fresh_cli_results.json.gz` is an independent fresh process, not a substitute for resident acceptance.
- `verification.json` checks complete column projections, PRIMARY positions/index members, compact/full tables and totals, text/structured parity, values and continued denials. SQLite6 tables and Sakila16 tables/89 columns agree with re-observed native catalogs.
- `process_diagnostics.json`, `exec_ancestry.json`:4 same-entry MCP processes,3 predating source changes and1 newer. Parent IDs do not identify the exact native client/process binding. Cache/startup/binding root cause remains unconfirmed; no process attached, stopped or modified, no environment or credentials read.
- `before.json.gz`, `current_native_catalogs.json.gz`, tool definitions, scripts and logs retain scope and provenance.77 disk resources,3 private TOMLs, the SQLite file and73 old manifests/2279 records remain unchanged.
- `documentation_checks.json` and `manifest.json` seal this pending checkpoint. Keep the parent pending seal and these failures; append reconnection results separately.

The owner chose to reconnect later and view the report first. MySQL is the server/dialect validation target; MariaDB is not an acceptance requirement. SQLite native validation remains. No runtime/configuration/grant change, new build/full regression/model/token/latency claim was made in this supplement. The earlier3373 regressions and source/wheel matrix retain their own scope.
