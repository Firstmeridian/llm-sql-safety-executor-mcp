# Post-restart native acceptance: relation calls and generated columns

Recorded at 2026-10-20 15:26:28 UTC; version remains 3.8.2. The owner restarted and reconnected the SQL MCP before these checks. All **12/12 frozen native checks passed** through the current Codex Host using existing connection aliases and grants.

| Check group | Observed result |
| --- | --- |
| SQLite and MySQL constants | Both return n=1 |
| Ordinary reads and scalar substr | Match the frozen independent expected rows |
| FTS call and table-form IN | Count 4; matching page IDs 11, 12, 13, 14 |
| Generated-column descriptor | pages has 10 columns; status is virtual; native column order matches |
| Compact and full schema | Both report 34 columns and retain the generated-column category |
| Default FTS projection | title/body only; hidden columns remain excluded |
| Restricted argument | SLEEP returns expensive_function_denied |
| Direct shadow-table read | Returns table_access_denied |

[Native application records](evidence/native_results.json) retain tool arguments, exposed content and structured results. They are not complete JSON-RPC frames, notifications, model-task or token evidence. [After-state checks](evidence/after_checks.json) verify the frozen expectations, all 77 runtime resources, unchanged SQLite/private TOML hashes, and preservation of 40 prior manifests covering 1129 file records. No credentials or private TOML contents are included.

No source, dependency, grant, configuration or database was changed during this acceptance. The pre-restart nine-column observation remains historical; its underlying cause is not established as a cache issue. Specially named FTS roots, JSON-name collisions and detailed Skill fixtures retain their separate source/installed coverage. No new model trial, regression run, build or performance study is claimed.

DRR-2026-129/130 are verified within this declared scope. The [current report](../../V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md) gives the complete change and cost limits. The parent checkpoint's pending status describes its earlier state; its sealed bytes remain unchanged. This supplement has its own manifest.
