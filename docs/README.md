# Documentation

English | [中文](README_ZH.md)

Start with the project [README](../README.md) for the motivation, design, quick start and tool examples. This index groups the detailed guides, decisions and evidence by purpose.

## Configuration and operation

- [Configuration examples](../config/examples/README.md): SQLite, MySQL, multiple connections and controlled mutations.
- [TOML configuration and migration (Chinese)](guides/CONFIGURATION_ZH.md): fields, defaults, secret sources, permissions, extension imports and cutover/rollback.
- [MCP client guide](guides/TEST_MCP_CLIENT_GUIDE.md): offline checks, protocol inspection and preview/MRTR approval examples.
- [AutoGen examples](../examples/autogen/README.md): separate dependency environment and validation scope.

## Design and reusable guides

- [Portable sentinels and dependency-aware release gates](validation/v3.8/V3_8_2_PORTABLE_RELEASE_GATES_2026_10_22_ZH.md) — ordinary pytest, explicit live acceptance and environment-bound evidence; [reusable commands](../scripts/validation/README.md).

- [v3.8.2 bounded stabilization acceptance](validation/v3.8/V3_8_2_STABILIZATION_2026_10_22_ZH.md) —16 frozen contract families and three scoped gates pass;254 selected regressions, source/wheel each332 application calls, independent oracles and sentinels. [Plan and stop conditions](validation/v3.8/V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md).
- [v3.8.2 MySQL binding and real InnoDB write gate](validation/v3.8/V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md) — exact-source check, native failure truth and unknown/token lifecycle; source/package passed, [owner-restarted native6/6](validation/v3.8/v382_mysql_write_contracts_2026_10_22/resident_restart/README.md) separately sealed.
- [v3.8.2 SQLite physical write transactions and completed row counts](validation/v3.8/V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md) — WITH/semicolon rollback, RETURNING and private source/package lifecycle proof; [post-restart12/12 and stability assessment](validation/v3.8/V3_8_2_WRITE_RESTART_AND_STABILIZATION_2026_10_22_ZH.md) separately preserve scope and remaining work.

- [v3.8.2 latest complete Agent tasks and actual costs](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md) — native12/12; fifteen paired tasks pass, tokens+3.85%, calls+4.63%; three natural-cancel probes retain interpretation failures.
- [v3.8.2 actual PRIMARY identity and ordered members](validation/v3.8/V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md) — shared SQLite/MySQL contract, native truth and costs; latest native12/12; earlier7/12 mismatch preserved; MariaDB is not required.
- [v3.8.2 SQLite declared-type repair](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_REPAIR_2026_10_21_ZH.md) — preserve native empty types;9/9 scoped native checks pass after owner restart, plus144 adjacent calls per source/wheel.
- [v3.8.2 SQLite declared-type assessment](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_ASSESSMENT_2026_10_21_ZH.md) — confirmed old P3, empty types shown as TEXT; historical assessment before the approved repair.

- [v3.8.2 FTS catalog, statistics sources and external-content rowid repair](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md) — source/package verified; all10 frozen existing-alias native checks pass after the owner restart, with special fixtures scoped separately.

- [v3.8.2 relation-call identity, JSON-name binding and SQLite generated columns (Chinese)](validation/v3.8/V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md).
- [v3.8.2 complete Agent tasks: actual tokens, calls, interpretation and configuration (Chinese)](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_20_ZH.md).
- [v3.8.2 trailing-comment/binding repairs, column batches and read-analysis reuse study (Chinese)](validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md).
- [Earlier v3.8.2 audit: findings and optimization prototypes before repair (Chinese)](validation/v3.8/V3_8_2_FINAL_AUDIT_2026_10_20_ZH.md).
- [v3.8.2 dialect comments, bounded MySQL plan hints and NOT precedence (Chinese)](validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md).
- [v3.8.2 readiness separation and bounded managed classification reuse (Chinese)](validation/v3.8/V3_8_2_MANAGED_CLASSIFICATION_REUSE_2026_10_20_ZH.md).
- [v3.8.2 managed-plan SQLGlot migration, temporary rollback and dialect validation (Chinese)](validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).
- [v3.8.2 read-capability, scope and JSON/FTS repair (Chinese)](validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md).
- [v3.8.2 post-repair audit: MySQL metadata costs and historical FTS findings (Chinese)](validation/v3.8/V3_8_2_POSTREPAIR_AUDIT_2026_10_20_ZH.md)。
- [v3.8.2 SQLite metadata regression: measurements and optimization priorities (Chinese)](validation/v3.8/V3_8_2_SQLITE_METADATA_COST_2026_10_20_ZH.md).
- [v3.8.2 FTS cached-content functions and qualified root repair (Chinese)](validation/v3.8/V3_8_2_FTS_FOLLOWUPS_2026_10_20_ZH.md).
- [v3.8.2 metadata optimization: implementation, matched costs and restart status (Chinese)](validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md).
- [Refactoring log](../REFACTORING_LOG.md) / [中文](../REFACTORING_LOG_ZH.md): actively maintained changes, decisions, trade-offs and validation, including v3.8.
- [v3.8 implementation decisions (Chinese)](architecture/V3_8_IMPLEMENTATION_ZH.md): package structure, instance state and reference-plan review.
- [Tool contracts and evaluation](guides/PROMPT_ENGINEERING_BEST_PRACTICES.md): schemas, descriptions, prompts and behavior checks.
- [Agent behavior validation (Chinese)](guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md): reusable routing, disclosure and cost evaluation methods.
- [Named connections, Skills and approval (v3.5–v3.7, Chinese)](guides/V3_5-V3_7_SKILLS_GUIDE_ZH.md).
- [Unified connection diagnostics](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md) / [中文](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN_ZH.md).
- [Connection routing remediation (v3.7.3, Chinese)](guides/V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md).
- [Earlier client guide (v3.7)](guides/TEST_MCP_CLIENT_GUIDE_v3_7.md): original response examples and checks for that version.
- Architecture background: [Skills](architecture/MCP_AGENTS_SKILLS_DESIGN.md), [SQLite adapter](architecture/SQLITE_ADAPTER_DESIGN.md), [LLM-to-MCP feasibility](architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md).

Guides stay under `docs/guides/` even when their titles identify an earlier version. Their version notices and dated sections define applicability; old scripts, environment settings and test counts are not current deployment instructions. Use the v3.8 configuration and client guides for the installed package.

## Security

- [v3.8 security boundaries](security/V3_8_SECURITY.md): trusted Python/Host, MRTR, single-process state, audit and uncertain outcomes.
- [Design risk register](security/DESIGN_RISK_REGISTER.md) / [中文](security/DESIGN_RISK_REGISTER_ZH.md).
- [Skills security policy](security/SAFETY.md): original extension governance, with its version notice and current-contract links.

## Releases and validation

- [Dialect/session semantics, SQLGlot and SQLite authorizer](architecture/V3_8_2_SQL_SEMANTICS_ZH.md).
- [v3.8.2 验收、成本与限制](validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md).
- [v3.8.2 view reads and non-executing plans](validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md).
- [v3.8.2 trigger, WITH REPLACE and UPDATE OR plan follow-up](validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md).

- [v3.8.2 trigger-local CTE plan repair](validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md).
- [v3.8.2 adjacent audit and current complete Agent trials](validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md).
- [v3.8.2 WHEN repair and Host readiness diagnosis](validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。
- [v3.8.2 committed-source final review and initial COLLATE P3 findings](validation/v3.8/V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md).
- [v3.8.2 SQLite operand COLLATE repair](validation/v3.8/V3_8_2_COLLATE_REPAIR_2026_10_18_ZH.md).
- [v3.8.2 complete-predicate COLLATE assessment and initial P3 findings](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md).
- [v3.8.2 complete-predicate COLLATE repair and scoped native acceptance](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)。
- [v3.8 validation reports and original evidence](validation/v3.8/).
- [Shared CTE analysis, functional repairs and adjacent checks](validation/v3.8/V3_8_1_CTE_ANALYSIS_2026_10_15_ZH.md).
- [Ambiguous WITH recovery and open CTE limits](validation/v3.8/V3_8_1_CTE_CLASSIFICATION_2026_10_15_ZH.md).
- [CTE declaration/body call boundary](validation/v3.8/V3_8_1_CTE_HEADER_2026_10_15_ZH.md).
- [Lexical relation boundaries and quoted reserved calls](validation/v3.8/V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md).
- [Unicode reserved-name correction](validation/v3.8/V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md).
- [Complete native Agent business tasks](validation/v3.8/V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md).
- [Literal SQLite directory prefix and dialect scope](validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md).
- [Internal schema binding and relation readiness](validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md).
- [Structured relation identity and mutation revalidation](validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md).
- [CTE/cost matrices, function policy and SQLGlot validation](validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md).

- [October 13 v3.8.1 follow-up (Chinese)](validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md): membership authorization, structured policy/query failures, review errata and current acceptance scope.
- [October 12 v3.8.1 review completion (Chinese)](validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md): final regressions, installed-wheel/live database checks, GPT-6 Luna traces, retained failures and completed resident-Host refresh checks with a recorded recovery-route misstatement.
- [October 3 v3.8.1 review (Chinese)](validation/v3.8/V3_8_1_REVIEW_2026_10_03_ZH.md): five-commit audit, query-policy fixes, bounded index metadata and actual validation limits.

- [October 1 native MRTR acceptance (Chinese)](validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md): actual commits, delayed-approval rejection, final fixture state and remaining TTL/restart boundaries.

- [v3.8 follow-up review (Chinese)](validation/v3.8/V3_8_REREVIEW_2026_09_28_ZH.md): confirmed green CI for `139d53a`, Query Skill static-policy discovery fix, regressions and remaining Host acceptance scope.
- [v3.8 independent review fixes (Chinese)](validation/v3.8/V3_8_REVIEW_FIXES_2026_09_27_ZH.md): confirmed findings, CI failure, production-path regressions and remaining acceptance limits.

- [v3.8 local live review (Chinese)](validation/v3.8/V3_8_LIVE_REVIEW_2026_09_26_ZH.md): Host launch repair, database checks, nine Luna CLI trials, subsequent native reconnection and three six-turn agent trials, with failures and acceptance limits preserved.
- [v3.8 release notes](releases/RELEASE_NOTES_v3_8.md) and [validation / actual Host limitations (Chinese)](validation/v3.8/V3_8_VALIDATION_ZH.md).
- [v3.7 releases](releases/RELEASE_NOTES_v3_7.md), [v3.6](releases/RELEASE_NOTES_v3_6.md), [v3.5](releases/RELEASE_NOTES_v3_5.md).
- [v3.7 validation records](validation/v3.7/) and [v3.8 evidence](validation/v3.8/). Original versions, failed trials and conclusions are preserved; earlier passes do not establish v3.8 acceptance.

## Archived snapshots

- [v3.7 README](history/README_v3.7.md) / [中文](history/README_v3.7_ZH.md).
- [Old public environment templates](history/config/): migration references only; the server no longer loads `.env`.

Root READMEs and refactoring logs remain maintained documents. SQL and business Skill definitions remain under the root `skills/` directory; the framework SDK lives in `src/sql_safety_executor/skills/`.

- [v3.8.2 faithful read results and conditional dependencies (2026-10-21)](validation/v3.8/V3_8_2_READ_RESULTS_2026_10_21_ZH.md) — shared encoding, limits and scoped readiness; source/package/native evidence stays separate.
- [v3.8.2 attached JSON-name readiness assessment (2026-10-21)](validation/v3.8/V3_8_2_ATTACHED_JSON_READINESS_2026_10_21_ZH.md) — historical assessment: 332 source calls, DRR-135 then open; subsequent repair follows.
- [v3.8.2 ordered attached-name repair (2026-10-21)](validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md) — DRR-135 implemented, 67 new regressions, original source/wheel each 332 calls; combined post-restart 20/20 passes, special fixtures retain source/package coverage.
- [v3.8.2 metadata-name collisions (2026-10-21)](validation/v3.8/V3_8_2_METADATA_NAME_COLLISIONS_2026_10_21_ZH.md) — historical independent old P2/DRR-136 assessment; subsequent repair follows.
- [v3.8.2 metadata PRAGMA repair (2026-10-21)](validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md) — DRR-136 implemented; collision/budget/value controls and serial costs; combined post-restart 20/20 verified; [separate supplement](validation/v3.8/v382_metadata_pragma_repair_2026_10_21/resident_restart/README.md).
- [v3.8.2 FTS catalog/statistics assessment (2026-10-21)](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_ASSESSMENT_2026_10_21_ZH.md) — historical open assessment: two P2s, 394 disposable Client calls; subsequent repair and scoped acceptance are linked above.
