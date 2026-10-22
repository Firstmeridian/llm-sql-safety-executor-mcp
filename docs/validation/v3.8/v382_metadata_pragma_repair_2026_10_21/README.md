# v3.8.2 metadata PRAGMA repair evidence

October 21, 2026. DRR-136 is repaired in source and the normal installed wheel.
**One combined maintainer restart with DRR-135 remains pending.**

- [Repair, costs and limits](../V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md).
- [Final checks](evidence/final-checks.json): full regression, matching final application frames, runtime/configuration identity and preserved prior seals.
- [Metadata source](evidence/source-final-metadata-retry.json.gz) and [installed](evidence/installed-final-metadata.json.gz): each 192 calls, six fixtures, in-process/child-stdio auto/legacy; compare generated columns/index attributes and read-value recovery against native SQLite truth.
- [Readiness source](evidence/source-final-readiness-retry.json.gz) and [installed](evidence/installed-final-readiness-retry.json.gz): each 296 calls, including 64 expected non-default-Skill ToolErrors.
- [Dynamic source](evidence/source-final-dynamic.json.gz) and [installed](evidence/installed-final-dynamic.json.gz): each 36 calls, including four expected non-default-Skill ToolErrors.
- [Costs](evidence/cost-summary.json), [preparation failures](evidence/preparation_notes.json), [wheel provenance](evidence/installed_resources-final.json) and [pending native plan](evidence/native_plan.json).

Application records include text and structured results, not complete protocol
frames/notifications. Each source/wheel total is 524 calls, **not 524 successful
executions**. Preparation negotiation failures are retained separately and are
not cache-root-cause evidence or model trials. No new complete model task,
provider-token, full-readiness-all-schemas or universal speed claim.

Use manifest hashes for the stored files and decoded gzip bytes. Source/package
validation uses disposable fixtures, not configured database writes or new
grants. Append resident evidence separately after the owner restart; keep this
pending checkpoint and all prior seals unchanged.
