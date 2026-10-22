# Faithful read results and conditional dependencies: source/package checkpoint

Version remains 3.8.2. Source and independent installed-wheel checks pass;
**owner restart and the 16 frozen resident checks are pending**.
See the [contract, decisions, costs and limits](../V3_8_2_READ_RESULTS_2026_10_21_ZH.md).

- [Final summary and resource identity](evidence/final-checks.json): 3126 passes/four optional skips, 64 new cases, clean type/prompt checks and 77 matching runtime resources.
- [Source records](evidence/source-canonical.json.gz) and [installed records](evidence/installed-canonical.json.gz): 176 application calls each; in-process and independent child-stdio auto/legacy groups each contain 44 calls. All expectations pass, including 24 expected readiness ToolErrors per run and continued restricted-function/shadow refusals. Text and structured frames agree. These are not raw JSON-RPC/notification or model records.
- [Normal installed-wheel provenance](evidence/installed_resources-encoding-final.json): frozen dependencies and verified offline tool caches reused, without global installation or upgrades.
- [Serial local costs A1](evidence/cost-protocol-a1.json), [B](evidence/cost-protocol-b.json), [A2](evidence/cost-protocol-a2.json): unchanged ordinary data; readiness catalog statements 1/2/1. Encoding/checks and the TEMP probe have costs; phase drift prevents universal percentages or latency guarantees. These are components, not tool/model measurements.
- [Frozen native plan](evidence/native_plan.json) and [old resident observation](evidence/native_before.json): do not mark old duplicate-column output as accepted after repair.
- [Full regression](checks/full-encoding-final.log.gz), [types](checks/types-encoding-final.log.gz), [source prompts](checks/prompts.log.gz), [installed prompts](checks/installed-prompts.log.gz).
- [Earlier checkpoint preservation](evidence/preserved_seals.json) and [intermediate failures/attribution](evidence/preparation_notes.json).

No configured business database, grant or private TOML was changed. Fixture hashes
and cleanup were checked. No new complete Luna task, provider token comparison or
guidance ablation is claimed. The scoped earlier model/native results remain
historical evidence for their actual source. Subsequent restart evidence must be
appended in a separate supplement, preserving this manifest and its bytes.
