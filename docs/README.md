# Documentation

English | [中文](README_ZH.md)

Start with the project [README](../README.md) for the motivation, design, quick start and tool examples. This index groups the detailed guides, decisions and evidence by purpose.

## Configuration and operation

- [Configuration examples](../config/examples/README.md): SQLite, MySQL, multiple connections and controlled mutations.
- [TOML configuration and migration (Chinese)](guides/CONFIGURATION_ZH.md): fields, defaults, secret sources, permissions, extension imports and cutover/rollback.
- [MCP client guide](guides/TEST_MCP_CLIENT_GUIDE.md): offline checks, protocol inspection and preview/MRTR approval examples.
- [AutoGen examples](../examples/autogen/README.md): separate dependency environment and validation scope.

## Design and reusable guides

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
