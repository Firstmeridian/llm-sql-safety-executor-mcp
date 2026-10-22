# Owner-restarted native supplement — October 22, 2026

The actual SQL MCP tools in the current Codex session pass **6/6 frozen checks** after the owner reports restarting. Text and structured results agree for every call.

| Connection / operation | Observed result |
| --- | --- |
| MySQL connection check | connected |
| MySQL SELECT 7 AS n | one row, n=7 |
| MySQL SELECT SLEEP(1) | expensive_function_denied |
| MySQL UPDATE film SET title=title WHERE 1=0 | read_only_required |
| SQLite SELECT 7 AS n | one row, n=7 |
| SQLite SELECT SLEEP(1) | expensive_function_denied |

No configured confirmed write or runtime/configuration/grant change. All77 on-disk resources still match the frozen normal installation; three private TOMLs are unchanged. This does not attest every in-memory resource, prove the internal analysis-mismatch branch through the native interface, or establish actual native confirmed-write outcomes. Those contracts retain their separate source/package and isolated real-database evidence. No new build, full-suite, model, speed or token result, and no confirmed cache root cause.

The three stabilization gates were agreed and their first two tasks completed. A [finite execution plan](../../V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md) now fixes16 contract families, the remaining order and stop conditions. S0 is complete within its stated scope; S1–S4 remain to be audited/executed/accepted. No background job or release date is scheduled.

All83 prior certified seals/2785 file records are fully rechecked;126 prior manifest-file digests remain unchanged (a different count). The [parent source/package report](../../V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md) and its pending checkpoint remain byte-for-byte unchanged. This supplement is separately sealed. Later acceptance must append another checkpoint.

- [Actual tool result packets](native_calls.json.gz): application-visible packets, not complete wire frames or model usage.
- [Checks](checks.json.gz), [baseline and prior seal references](before.json.gz), [verification script](verify.py.gz).
- [Manifest](manifest.json): encoded and decoded hashes for this supplement.

No further restart is needed for these documentation-only updates. Keep the prior model failures and measured cost limitations. The English grouped commit draft still covers the work; nothing is staged or committed by this supplement.
