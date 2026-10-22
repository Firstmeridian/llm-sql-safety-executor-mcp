# Combined post-restart native acceptance: DRR-135/136

October 21, 2026; version 3.8.2. After the maintainer-confirmed restart, the
current Codex channel completes **20/20 frozen native checks** on existing
SQLite/MySQL aliases. No source, dependency, configuration, grant or database
write was needed; no new build or full regression run was performed.

| Group | Checks | Result |
| --- | --- | --- |
| Read-result boundaries | 14 | Constants/unique labels, duplicate-label recovery, tagged UTF-8 and non-UTF-8 BLOBs, oversized first rows, SQLite infinity/NULL |
| Expected refusals | 2 | Restricted function and FTS shadow remain denied |
| Default readiness | 1 | Catalog available; all four sample Skills correctly remain unavailable on this alias without orders |
| Metadata consistency | 3 | pages: 10 columns/status virtual, complete indexes, compact/full: 6 tables / 34 columns, hidden FTS columns excluded |

[Application records](evidence/native_results.json.gz) contain arguments,
content, structuredContent and isError. Text and structured results agree for
every check. Expected refusals use application success=false/error_code with
isError=false. These are not complete protocol frames or model-task logs.

[Integrity and semantic checks](evidence/integrity.json) match independent
read-only sqlite3 column/index metadata, confirm 77 unchanged disk resources,
three private TOML hashes and the configured SQLite file, and preserve 53 earlier
manifests/1706 file records. Disk hashes do not prove resident in-memory code
identity. The [frozen plan](../evidence/native_plan.json) remains untouched.

Special metadata shadows, attached JSON-name FTS, partial observations and
budgets retain source/normal-wheel coverage. The native default-Skill catalog
does not exercise those attached-schema fixtures. No new model/token, guidance
ablation or performance claim is made. Keep both parent pending checkpoints and
preparation failures intact; success does not establish a cache root cause.

Current reports: [metadata repair](../../V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md)
and [ordered readiness repair](../../V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md).
