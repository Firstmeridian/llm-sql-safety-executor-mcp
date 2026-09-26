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

- [v3.8 local live review (Chinese)](validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md): Host launch repair, database checks, nine Luna CLI trials, subsequent native reconnection and three six-turn agent trials, with failures and acceptance limits preserved.
- [v3.8 release notes](releases/RELEASE_NOTES_v3_8.md) and [validation / actual Host limitations (Chinese)](validation/V3_8_VALIDATION_ZH.md).
- [v3.7 releases](releases/RELEASE_NOTES_v3_7.md), [v3.6](releases/RELEASE_NOTES_v3_6.md), [v3.5](releases/RELEASE_NOTES_v3_5.md).
- [v3.7 validation records](validation/v3.7/) and [v3.8 evidence](validation/v3.8/). Original versions, failed trials and conclusions are preserved; earlier passes do not establish v3.8 acceptance.

## Archived snapshots

- [v3.7 README](history/README_v3.7.md) / [中文](history/README_v3.7_ZH.md).
- [Old public environment templates](history/config/): migration references only; the server no longer loads `.env`.

Root READMEs and refactoring logs remain maintained documents. SQL and business Skill definitions remain under the root `skills/` directory; the framework SDK lives in `src/sql_safety_executor/skills/`.
