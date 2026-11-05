# Documentation

English | [中文](README_ZH.md)

Start with the project [README](../README.md) for the motivation, design, quick start and tool examples. This index groups the detailed guides, decisions and evidence by purpose.

## Usage entry points

- [Configuration examples](../config/examples/README.md): SQLite, MySQL, multiple connections and controlled mutations.
- [TOML configuration and migration (Chinese)](guides/CONFIGURATION_ZH.md): fields, defaults, secret sources, permissions, extension imports and cutover/rollback.
- [MCP client guide](guides/TEST_MCP_CLIENT_GUIDE.md): offline checks, protocol inspection and preview/MRTR approval examples.
- [Controlled Query Skill reload](guides/QUERY_SKILL_RELOAD.md): explicitly publish validated per-instance Query snapshots; preserve Mutation plans/tokens and distinguish this from a Host restart.
- [Mutation Skill publication](guides/MUTATION_SKILL_RELOAD.md): per-definition generations, affected-preview invalidation, pinned admitted execution, trusted entry scope and actual-consumer confirmation.
- [Codex restart and reconnect helper](guides/CODEX_MCP_RESTART.md): bind the current Host and unique local stdio process; separate config refresh from verified replacement. Current automatic maintenance may affect only the current chat; VS Code Codex reconnection remains manual.
- [AutoGen examples](../examples/autogen/README.md): separate dependency environment and validation scope.

## Design and safety

- [v3.8 security boundaries](security/V3_8_SECURITY.md): trusted Python/Host, MRTR, single-process state, audit and uncertain outcomes.
- [Design risk register](security/DESIGN_RISK_REGISTER.md) / [中文](security/DESIGN_RISK_REGISTER_ZH.md).
- [Skills security policy](security/SAFETY.md): original extension governance, with its version notice and current-contract links.
- [Dialect/session semantics, SQLGlot and SQLite authorizer](architecture/V3_8_2_SQL_SEMANTICS_ZH.md).
- [v3.8 implementation decisions (Chinese)](architecture/V3_8_IMPLEMENTATION_ZH.md): package structure, instance state and reference-plan review.
- Architecture background: [Skills](architecture/MCP_AGENTS_SKILLS_DESIGN.md), [SQLite adapter](architecture/SQLITE_ADAPTER_DESIGN.md), [LLM-to-MCP feasibility](architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md).
- [Tool contracts and evaluation](guides/PROMPT_ENGINEERING_BEST_PRACTICES.md): schemas, descriptions, prompts and behavior checks.
- [Agent behavior validation (Chinese)](guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md): reusable routing, disclosure and cost evaluation methods.
- [Named connections, Skills and approval (v3.5–v3.7, Chinese)](guides/V3_5-V3_7_SKILLS_GUIDE_ZH.md).
- [Unified connection diagnostics](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md) / [中文](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN_ZH.md).
- [Connection routing remediation (v3.7.3, Chinese)](guides/V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md).
- [Earlier client guide (v3.7)](guides/TEST_MCP_CLIENT_GUIDE_v3_7.md): original response examples and checks for that version.

Guides stay under `docs/guides/` even when their titles identify an earlier version. Their version notices and dated sections define applicability; old scripts, environment settings and test counts are not current deployment instructions. Use the v3.8 configuration and client guides for the installed package.

## Acceptance by topic

Dated records retain their original acceptance scope, failures and then-pending status; pending items in old records are not a current task list.

### Skill publication and full workflows

- Query Skill: [Engineering acceptance](validation/v3.8/V3_8_2_QUERY_RELOAD_2026_10_28_ZH.md), [native14/14 and partial Luna tasks](validation/v3.8/V3_8_2_QUERY_RELOAD_RESTART_2026_10_28_ZH.md).
- [Native Mutation workflows](validation/v3.8/V3_8_2_MUTATION_RELOAD_NATIVE_2026_10_29_ZH.md): three two-round tasks3/3, independent rows/triggers agree; exact configs restored, both original consumers/caller confirm unload, owned DB removed; snapshot/audit retained.
- [New-turn full Agent acceptance](validation/v3.8/V3_8_2_NEW_TURN_BUSINESS_ACCEPTANCE_2026_10_29_REVISED_ZH.md):3/3 two-round workflows and all core query results complete; strict whole-task 2/3 retains one percentage-rounding error.13 business calls/693,155 tokens; no A/B or universal Host claim. [Separate single-child probe](validation/v3.8/V3_8_2_NEW_TURN_CHILD_PROBE_2026_10_29_ZH.md); earlier failures remain historical.

### Codex maintenance

- Codex restart: [Native acceptance](validation/v3.8/V3_8_2_CODEX_MCP_RESTART_2026_10_28_ZH.md).
- [November5 scope/catalog repair](validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md): pre-effect recreate scope checks and strict active-directory validation; isolated regression and installed-wheel evidence, no new live restart.
- [Final pre-commit review: November 1](validation/v3.8/V3_8_2_FINAL_REVIEW_2026_11_01_ZH.md): four helper boundaries repaired and verified in isolation; this batch's helper and installed-wheel checks pass. Full regression remains a pre-repair baseline; new live restart and the resident admission update remain unverified.
- [Mutation admission and Host binding diagnostics: October31](validation/v3.8/V3_8_2_MUTATION_ADMISSION_HOST_BINDING_2026_10_31_ZH.md): token checks precede trusted construction, re-validation outcomes remain conservative, and binding failures retain their exact stage. Current0.166 read-only checks pass; historical mapping and resident-update limits remain explicit.
- [Bounded post-restart verification](validation/v3.8/V3_8_2_CODEX_MCP_READINESS_2026_10_29_ZH.md): shared startup-read budget, no expired-budget sends;97 helper tests/five scoped comparisons pass, revised actual recovery and caller-native confirmation pass in the declared scope.
- [Host-managed bootstrap and recovery](validation/v3.8/V3_8_2_CODEX_MCP_HOST_RECREATE_2026_10_29_ZH.md): explicit recreate, version-checked config restore and fresh consumer identity;78 helper tests/five isolated workflows pass; actual recovery and later read-only/native checks pass, with the first final-verification timeout retained.
- [Restart identity and early-refusal repair](validation/v3.8/V3_8_2_RESTART_IDENTITY_REFUSAL_REPAIR_2026_10_29_ZH.md):110 focused passes,16 installed stdio calls; runtime PID binding replaces config-only identity inference. Bootstrap was pending at that checkpoint; subsequent Host-managed recovery above confirms native PID binding and early-refusal behavior. Resident verification of the October31 admission repair remains separately open.

### Result interpretation and Agent costs

- [Current Agent-guidance overview by objective](../REFACTORING_LOG.md): natural result interpretation, useful exploration, weak-prompt state interpretation and latency attribution; implemented changes, measured effects, costs and open issues. The [release summary](releases/RELEASE_NOTES_v3_8.md) follows the same structure; dated evidence remains below.
- [Expiry-field report wording errata: October 28](validation/v3.8/V3_8_2_EXPIRY_FIELD_SCREEN_ERRATA_2026_10_28_ZH.md) — three waves with concurrency within each wave; six inputs per condition contain a deadline, but only five require reporting it. Keep1/5 and2/5, the original seals and the rejection decision.
- [Bounded expiry-field screening and stop decision: October 28](validation/v3.8/V3_8_2_EXPIRY_FIELD_SCREEN_2026_10_28_ZH.md) — six supplied-record sessions/24 answers; both conditions8/12, four held-out answers pass per condition. Reject the incomplete candidate, retain native5/6 and separate costs; no production change, conditional restart or new Host-root-cause result.
- [Public-trace review of P1's expiry-date claim: October 28](validation/v3.8/V3_8_2_EXPIRY_DATE_REVIEW_2026_10_28_ZH.md) — timezone normalization exposes an unsupported conclusion; mixed UTC/local dates remain a hypothesis, not a proven internal cause. Preserve5/6 and uncontrolled visibility differences; no new model trial or product edit.
- [Owner-restarted natural expiry/transition tasks: October 28](validation/v3.8/V3_8_2_EXPIRY_TRANSITION_RESTART_2026_10_28_ZH.md) — six fresh two-turn tasks closed: state/actions6/6, deadline reporting3/3, full interpretation5/6. Retain one unsupported validity inference despite publicly displayed guidance and one recovered bad-column query; no causal efficiency or resolved Host-latency claim.
- [Expiry field and demo transition sources: October 28](validation/v3.8/V3_8_2_EXPIRY_TRANSITION_GUIDANCE_2026_10_28_ZH.md) — two independently checked metadata edits,72 preview cases across both Client modes, unchanged execution rules. Original engineering checkpoint preserves its pending restart state; the separate native supplement above retains one interpretation failure. External omissions remain, with no model or performance improvement claim.
- [Post-restart preview routing: October 28](validation/v3.8/V3_8_2_PREVIEW_ROUTING_RESTART_2026_10_28_ZH.md) — routing3/3, business completion2/3, action boundaries/cancellation3/3. Retain one Host approval-review timeout and the unmet full completion gate; three independent read replays, mixed costs and no general improvement claim.
- [Skill discovery to actual preview: October 28](validation/v3.8/V3_8_2_PREVIEW_ROUTING_2026_10_28_ZH.md) — single description clarification, three frozen native baselines choose correctly,70 focused regressions and fresh package/metadata checks pass. Original pre-restart checkpoint; the separate native supplement above retains partial completion, without an omission-rate improvement claim.
- [Post-restart expiry/payment native tasks: October 28](validation/v3.8/V3_8_2_EXPIRY_SCOPE_RESTART_2026_10_28_ZH.md) — three closed two-turn tasks; business/interpretation2/3, full frozen protocol1/3, action boundaries3/3. One actual preview interprets expiry correctly; retain a missing preview, repeated definitions and noncausal costs. Refresh is closed.
- [Explicit expiry interpretation and payment-scope matrix: October 28](validation/v3.8/V3_8_2_EXPIRY_SCOPE_2026_10_28_ZH.md) — six supplied-record sessions tie at16/16 per condition; portable payment oracle and eight known-bad variants. Preserve the original pending checkpoint; native results are separate above, without a general improvement claim.
- [Reconnected native discovery A/B: October 28](validation/v3.8/V3_8_2_DISCOVERY_AB_RESTART_2026_10_28_ZH.md) —eight full tasks,24 independent SQL replays; current-data/actions8/8, complete interpretation4/8. Retain unsupported expiry claims, a post-hoc payment-scope gap and mixed costs; no product default change.
- [Original discovery A/B and child-readiness checkpoint](validation/v3.8/V3_8_2_DISCOVERY_AB_2026_10_28_ZH.md) —175 exact reconstruction checks and two failed child canaries retained; its eight pending tasks are covered by the separate continuation above.
- [Native units/expiry verification: October 28](validation/v3.8/V3_8_2_UNITS_EXPIRY_RESTART_2026_10_28_ZH.md) — two full business tasks plus a separate display probe; finance/CNY/70% pass, preview expiry/state-evidence gaps remain; strict business1/2 and actual costs retained.
- [Sourced units and preview-expiry presentation: October 27](validation/v3.8/V3_8_2_UNITS_EXPIRY_2026_10_27_ZH.md) — two local text clarifications, independent bounded replay screens and explicit context costs; original pre-native checkpoint retained.
- [Agent evidence: October 27 owner-restarted native supplement](validation/v3.8/V3_8_2_AGENT_EVIDENCE_RESTART_2026_10_27_ZH.md) — C wording and preview/cancellation verified; finance numbers/predicates pass, unsupported currency symbols remain; actual calls/tokens and limits retained.
- [Agent evidence follow-up: October 27](validation/v3.8/V3_8_2_AGENT_EVIDENCE_FOLLOWUP_2026_10_27_ZH.md) — reported-claim completeness, portable temporal/evidence checks, bounded replay and discovery/Host diagnostics; original pre-restart checkpoint retained.
- [Agent result interpretation: October 25 owner-restarted native tasks](validation/v3.8/V3_8_2_AGENT_INTERPRETATION_RESTART_2026_10_25_ZH.md) — six matched/two held-out business checks pass; mixed call/token costs, timestamp inversion and supplementary omissions retained.
- [Agent result interpretation, same-version A/A and collection boundaries](validation/v3.8/V3_8_2_AGENT_INTERPRETATION_2026_10_23_ZH.md) — original source/package and pre-restart checkpoint; later native evidence is separate.
- [v3.8.2 latest complete Agent tasks and actual costs](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md) — native12/12; fifteen paired tasks pass, tokens+3.85%, calls+4.63%; three natural-cancel probes retain interpretation failures.
- [v3.8.2 complete Agent tasks: actual tokens, calls, interpretation and configuration (Chinese)](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_20_ZH.md).
- [Complete native Agent business tasks](validation/v3.8/V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md).

### SQL semantics, policy and plans

- [v3.8.2 dialect comments, bounded MySQL plan hints and NOT precedence (Chinese)](validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md).
- [v3.8.2 managed-plan SQLGlot migration, temporary rollback and dialect validation (Chinese)](validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).
- [v3.8.2 view reads and non-executing plans](validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md).
- [v3.8.2 trigger, WITH REPLACE and UPDATE OR plan follow-up](validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md).
- [v3.8.2 trigger-local CTE plan repair](validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md).
- [v3.8.2 WHEN repair and Host readiness diagnosis](validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。
- [v3.8.2 SQLite operand COLLATE repair](validation/v3.8/V3_8_2_COLLATE_REPAIR_2026_10_18_ZH.md).
- [v3.8.2 complete-predicate COLLATE repair and scoped native acceptance](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)。
- [Shared CTE analysis, functional repairs and adjacent checks](validation/v3.8/V3_8_1_CTE_ANALYSIS_2026_10_15_ZH.md).
- [Ambiguous WITH recovery and open CTE limits](validation/v3.8/V3_8_1_CTE_CLASSIFICATION_2026_10_15_ZH.md).
- [CTE declaration/body call boundary](validation/v3.8/V3_8_1_CTE_HEADER_2026_10_15_ZH.md).
- [Lexical relation boundaries and quoted reserved calls](validation/v3.8/V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md).
- [Unicode reserved-name correction](validation/v3.8/V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md).
- [CTE/cost matrices, function policy and SQLGlot validation](validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md).

### Read results, readiness and metadata

- [v3.8.2 faithful read results and conditional dependencies (2026-10-21)](validation/v3.8/V3_8_2_READ_RESULTS_2026_10_21_ZH.md) — shared encoding, limits and scoped readiness; source/package/native evidence stays separate.
- [v3.8.2 attached JSON-name readiness assessment (2026-10-21)](validation/v3.8/V3_8_2_ATTACHED_JSON_READINESS_2026_10_21_ZH.md) — historical assessment: 332 source calls, DRR-135 then open; subsequent repair follows.
- [v3.8.2 ordered attached-name repair (2026-10-21)](validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md) — DRR-135 implemented, 67 new regressions, original source/wheel each 332 calls; combined post-restart 20/20 passes, special fixtures retain source/package coverage.
- [v3.8.2 metadata-name collisions (2026-10-21)](validation/v3.8/V3_8_2_METADATA_NAME_COLLISIONS_2026_10_21_ZH.md) — historical independent old P2/DRR-136 assessment; subsequent repair follows.
- [v3.8.2 metadata PRAGMA repair (2026-10-21)](validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md) — DRR-136 implemented; collision/budget/value controls and serial costs; combined post-restart 20/20 verified; [separate supplement](validation/v3.8/v382_metadata_pragma_repair_2026_10_21/resident_restart/README.md).
- [v3.8.2 actual PRIMARY identity and ordered members](validation/v3.8/V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md) — shared SQLite/MySQL contract, native truth and costs; latest native12/12; earlier7/12 mismatch preserved; MariaDB is not required.
- [v3.8.2 SQLite declared-type repair](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_REPAIR_2026_10_21_ZH.md) — preserve native empty types;9/9 scoped native checks pass after owner restart, plus144 adjacent calls per source/wheel.
- [v3.8.2 SQLite declared-type assessment](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_ASSESSMENT_2026_10_21_ZH.md) — confirmed old P3, empty types shown as TEXT; historical assessment before the approved repair.
- [v3.8.2 FTS catalog, statistics sources and external-content rowid repair](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md) — source/package verified; all10 frozen existing-alias native checks pass after the owner restart, with special fixtures scoped separately.
- [v3.8.2 FTS catalog/statistics assessment (2026-10-21)](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_ASSESSMENT_2026_10_21_ZH.md) — historical open assessment: two P2s, 394 disposable Client calls; subsequent repair and scoped acceptance are linked above.
- [v3.8.2 relation-call identity, JSON-name binding and SQLite generated columns (Chinese)](validation/v3.8/V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md).
- [v3.8.2 trailing-comment/binding repairs, column batches and read-analysis reuse study (Chinese)](validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md).
- [v3.8.2 readiness separation and bounded managed classification reuse (Chinese)](validation/v3.8/V3_8_2_MANAGED_CLASSIFICATION_REUSE_2026_10_20_ZH.md).
- [v3.8.2 read-capability, scope and JSON/FTS repair (Chinese)](validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md).
- [v3.8.2 SQLite metadata regression: measurements and optimization priorities (Chinese)](validation/v3.8/V3_8_2_SQLITE_METADATA_COST_2026_10_20_ZH.md).
- [v3.8.2 FTS cached-content functions and qualified root repair (Chinese)](validation/v3.8/V3_8_2_FTS_FOLLOWUPS_2026_10_20_ZH.md).
- [v3.8.2 metadata optimization: implementation, matched costs and restart status (Chinese)](validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md).
- [Literal SQLite directory prefix and dialect scope](validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md).
- [Internal schema binding and relation readiness](validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md).
- [Structured relation identity and mutation revalidation](validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md).

### Write transactions, MRTR and stabilization

- [v3.8.2 MySQL binding and real InnoDB write gate](validation/v3.8/V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md) — exact-source check, native failure truth and unknown/token lifecycle; source/package passed, [owner-restarted native6/6](validation/v3.8/v382_mysql_write_contracts_2026_10_22/resident_restart/README.md) separately sealed.
- [v3.8.2 SQLite physical write transactions and completed row counts](validation/v3.8/V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md) — WITH/semicolon rollback, RETURNING and private source/package lifecycle proof; [post-restart12/12 and stability assessment](validation/v3.8/V3_8_2_WRITE_RESTART_AND_STABILIZATION_2026_10_22_ZH.md) separately preserve scope and remaining work.
- [October 1 native MRTR acceptance (Chinese)](validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md): actual commits, delayed-approval rejection, final fixture state and remaining TTL/restart boundaries.
- [Portable sentinels and dependency-aware release gates](validation/v3.8/V3_8_2_PORTABLE_RELEASE_GATES_2026_10_22_ZH.md) — ordinary pytest, explicit live acceptance and environment-bound evidence; [reusable commands](../scripts/validation/README.md).
- [v3.8.2 bounded stabilization acceptance](validation/v3.8/V3_8_2_STABILIZATION_2026_10_22_ZH.md) —16 frozen contract families and three scoped gates pass;254 selected regressions, source/wheel each332 application calls, independent oracles and sentinels. [Plan and stop conditions](validation/v3.8/V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md).
- [v3.8.2 验收、成本与限制](validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md).

## Historical startup diagnostics and reviews

### Startup, handshake and Host diagnostics

- [Historical multi-thread restart acceptance](validation/v3.8/V3_8_2_CODEX_MCP_GROUP_RESTART_2026_10_29_ZH.md):49 focused checks and two-thread read-only preflight pass; whole matching target set; later approved live replacement/read checks pass2/2. Retained group capability and historical approvals do not authorize current group use; reusing it requires an explicit maintainer change to the current-chat-only scope decision.
- [Actual-consumer acceptance gate](validation/v3.8/V3_8_2_QUERY_RELOAD_CONSUMER_2026_10_28_ZH.md): validate fixtures before publication; preserve three failed child canaries, same-thread binding evidence and the decision not to run business tasks or repeat restarts.
- [Startup-gated full tasks](validation/v3.8/V3_8_2_QUERY_RELOAD_READY_2026_10_29_ZH.md): exact-child startup evidence, native readiness 2/3 and complete two-round1/3; preserve a handshake ID mismatch and a model's omitted connection argument without a Host root-cause claim.
- [Staged restart and bounded Agent acceptance](validation/v3.8/V3_8_2_LEGACY_RESTART_ACCEPTANCE_2026_10_29_ZH.md): parent replacement/native reads and six fixtures pass; all three exact child startups fail before business. Retain the Legacy setting, historical failures and captured-turn-config lead; that staged batch stopped before business; the later new-turn batch above supplies completed-workflow evidence.
- [Historical Legacy mitigation attempt and restoration](validation/v3.8/V3_8_2_LEGACY_MITIGATION_ATTEMPT_2026_10_29_ZH.md): process guard rejects a changed binding before signaling; original config bytes and reads restore. Four fake checks support staged writes; that batch stopped before retry or model trials. The later separately approved staged deployment is recorded above; its failures remain historical evidence.
- [Historical version-pinned fallback and startup analysis](validation/v3.8/V3_8_2_STARTUP_FALLBACK_2026_10_29_ZH.md): identify the10s discovery fallback; nine owned startups and separate legacy protocol-start control passes. One-key mitigation was pending at that checkpoint, with no full model trial in that batch; later approved deployment and new-turn acceptance are recorded above.
- [Handshake capture and restoration](validation/v3.8/V3_8_2_HANDSHAKE_CAPTURE_2026_10_29_ZH.md): a late discovery response arrives during initialization; deployment preflight fails and original config is restored, with no new model trials. Host fallback internals remain open. [Historical preparation](validation/v3.8/V3_8_2_HANDSHAKE_CAPTURE_PREP_2026_10_29_ZH.md).
- [Host request correlation and bounded diagnosis: October 28](validation/v3.8/V3_8_2_HOST_REQUEST_CORRELATION_2026_10_28_ZH.md): paired optional telemetry, opaque invocation keys and monotonic durations; reviewer association narrows the investigation, while Host root cause and resident activation remain separate.
- [Bounded Host/discovery follow-up: October 28](validation/v3.8/V3_8_2_HOST_DISCOVERY_FOLLOWUP_2026_10_28_ZH.md) — review deadline cause remains unresolved; nine archived tasks yield a15554-character exact-display counterfactual, preserving useful schema/parameter exploration. No new model trial, product change or token/speed claim.

### Historical reviews

- [Earlier v3.8.2 audit: findings and optimization prototypes before repair (Chinese)](validation/v3.8/V3_8_2_FINAL_AUDIT_2026_10_20_ZH.md).
- [v3.8.2 post-repair audit: MySQL metadata costs and historical FTS findings (Chinese)](validation/v3.8/V3_8_2_POSTREPAIR_AUDIT_2026_10_20_ZH.md)。
- [v3.8.2 adjacent audit and current complete Agent trials](validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md).
- [v3.8.2 committed-source final review and initial COLLATE P3 findings](validation/v3.8/V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md).
- [v3.8.2 complete-predicate COLLATE assessment and initial P3 findings](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md).
- [October 13 v3.8.1 follow-up (Chinese)](validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md): membership authorization, structured policy/query failures, review errata and current acceptance scope.
- [October 12 v3.8.1 review completion (Chinese)](validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md): final regressions, installed-wheel/live database checks, GPT-6 Luna traces, retained failures and completed resident-Host refresh checks with a recorded recovery-route misstatement.
- [October 3 v3.8.1 review (Chinese)](validation/v3.8/V3_8_1_REVIEW_2026_10_03_ZH.md): five-commit audit, query-policy fixes, bounded index metadata and actual validation limits.
- [v3.8 follow-up review (Chinese)](validation/v3.8/V3_8_REREVIEW_2026_09_28_ZH.md): confirmed green CI for `139d53a`, Query Skill static-policy discovery fix, regressions and remaining Host acceptance scope.
- [v3.8 independent review fixes (Chinese)](validation/v3.8/V3_8_REVIEW_FIXES_2026_09_27_ZH.md): confirmed findings, CI failure, production-path regressions and remaining acceptance limits.
- [v3.8 local live review (Chinese)](validation/v3.8/V3_8_LIVE_REVIEW_2026_09_26_ZH.md): Host launch repair, database checks, nine Luna CLI trials, subsequent native reconnection and three six-turn agent trials, with failures and acceptance limits preserved.

## Releases and validation

- [v3.8 release notes](releases/RELEASE_NOTES_v3_8.md) and [validation / actual Host limitations (Chinese)](validation/v3.8/V3_8_VALIDATION_ZH.md).
- [v3.7 releases](releases/RELEASE_NOTES_v3_7.md), [v3.6](releases/RELEASE_NOTES_v3_6.md), [v3.5](releases/RELEASE_NOTES_v3_5.md).
- [v3.8 validation reports and original evidence](validation/v3.8/).
- [Refactoring log](../REFACTORING_LOG.md) / [中文](../REFACTORING_LOG_ZH.md): actively maintained changes, decisions, trade-offs and validation, including v3.8.
- [v3.7 validation records](validation/v3.7/) and [v3.8 evidence](validation/v3.8/). Original versions, failed trials and conclusions are preserved; earlier passes do not establish v3.8 acceptance.

### Archived snapshots

- [v3.7 README](history/README_v3.7.md) / [中文](history/README_v3.7_ZH.md).
- [Old public environment templates](history/config/): migration references only; the server no longer loads `.env`.

Root READMEs and refactoring logs remain maintained documents. SQL and business Skill definitions remain under the root `skills/` directory; the framework SDK lives in `src/sql_safety_executor/skills/`.
