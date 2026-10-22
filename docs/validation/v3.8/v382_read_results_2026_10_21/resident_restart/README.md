# Post-restart native acceptance: faithful read results

Recorded at 2026-10-20 18:11:43 UTC (October 21 locally); version remains 3.8.2.
After the owner-confirmed SQL MCP restart, all **16/16 frozen native query checks
pass** through the current Codex Host using the existing two test aliases.

| Check group | Checks | Observed result |
| --- | --- | --- |
| SQLite/MySQL constants and unique labels | 4 | Expected data and distinct labels |
| Duplicate labels on both databases | 2 | duplicate_result_columns with same-connection unique-AS recovery |
| UTF-8 and non-UTF-8 BLOBs on both databases | 4 | Tagged binary/base64 values for both contents |
| Oversized first row on both databases | 2 | Zero returned rows, one fetched row, char_limit and projection guidance |
| SQLite positive/negative infinity | 2 | Tagged float values; SQL NULL stays null |
| SQLite restricted function and FTS shadow | 2 | expensive_function_denied and table_access_denied |

[Exposed application records](evidence/native_results.json) retain arguments,
content, structuredContent and isError. All text/structured results agree and
isError is false; expected refusals use application success=false/error_code.
These are not complete JSON-RPC frames, notifications or model-task records.
The [frozen plan](../evidence/native_plan.json) was not changed after restart.

[Integrity checks](evidence/integrity.json) confirm 77 unchanged disk runtime
resources, three unchanged private TOMLs, an unchanged configured SQLite file
and preservation of 45 earlier manifests/1329 file records. Disk hashes do not
prove resident in-memory code identity; behavior supports the declared cases.
No private TOML contents or credentials are included.

The sealed parent pending checkpoint, old duplicate-label observation and
intermediate failures remain untouched. Success after restart does not establish
a cache root cause. This supplement has its own manifest. Source/package
coverage for special aux/TEMP Skills, unavailable metadata and sample is not
relabeled as native Skill/sample acceptance. No new model/token comparison,
guidance ablation, performance study, full regression run or build is claimed.

The [current contract and acceptance report](../../V3_8_2_READ_RESULTS_2026_10_21_ZH.md)
records DRR-131–134 and their specific scope. No new source, dependency,
configuration, grant or database changes were needed for this acceptance.

