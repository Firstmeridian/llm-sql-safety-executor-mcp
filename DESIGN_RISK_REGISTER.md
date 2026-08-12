# Design Risk Register

English | [中文](DESIGN_RISK_REGISTER_ZH.md)

Date opened: 2026-05-24
Last reviewed: 2026-08-10

Document status: Living design and operations risk register.  
Initial review batch: v3.4.3.

This document records design concerns, trade-offs, rejected designs, and follow-up
decisions for this MCP SQL safety gateway. It is intentionally broader than a
single release: historical IDs are kept for traceability, and future rows can use
release-specific IDs or a `DRR-YYYY-NNN` format.

## Scope

Use this register for risks and design choices that affect tool behavior,
model-visible surfaces, database workload, security claims, logs, caches,
telemetry, resources, schemas, or operational reliability.

This document is not a replacement for tests, release notes, or a vulnerability
advisory. When a row changes runtime behavior, add tests and record the test file
in the result column.

## Status Legend

| Status | Meaning |
|---|---|
| Implemented | Code or documentation change has been completed and recorded. |
| Accepted | Current behavior is an intentional compromise; no immediate change planned. |
| Policy Required | A compatibility, privacy, or audit decision is needed before changing behavior. |
| Operational Decision | Prefer deployment or operations guidance over server logic for now. |
| Deferred | Valid idea, but not enough need or design clarity for the current release. |
| Not Planned | Explicitly rejected for the current architecture unless requirements change. |

## Risk Level Legend

| Risk level | Meaning |
|---|---|
| High | Security boundary, sensitive logging/audit, live database, or write-path risk that can affect production safety, privacy, or compliance. |
| Medium | Reliability, operability, governance, maintainability, or misleading-claim risk with meaningful but bounded impact. |
| Low | Compatibility, naming, documentation precision, or cleanup risk with limited runtime or security impact. |

`Date first registered` records the earliest known date the row was entered in
this register or its review batch.

## Review Cadence

- Review open rows before each minor release and after any tool-surface change.
- Re-check rows touching logs, caches, telemetry, raw SQL, or model-visible
  resources after security reviews.
- Update `Last reviewed` whenever the register is materially changed.

## External Best-Practice Anchors

| Source | Relevant guidance used here |
|---|---|
| [FastMCP Tools docs](https://gofastmcp.com/servers/tools) | `ToolResult.meta` is runtime metadata; `output_schema` must match structured output; tool annotations are advisory hints; typed schemas and precise descriptions help clients choose tools. |
| [FastMCP Middleware docs](https://gofastmcp.com/servers/middleware) | Middleware can log or transform tool calls through `on_call_tool`; response limiting can break structured-output conformance; cache keys do not include user/session identity unless explicitly designed. |
| [Model Context Protocol docs](https://modelcontextprotocol.io/docs) / [Claude Code MCP docs](https://docs.anthropic.com/en/docs/claude-code/mcp) | MCP tool output can overwhelm context; resources and tools are model-visible surfaces; concise tool/server instructions and smaller surfaces reduce context and selection risk. |
| [Python importlib docs](https://docs.python.org/3/library/importlib.html) / [abc docs](https://docs.python.org/3/library/abc.html) | `exec_module()` executes module code during dynamic imports; ABCs and `issubclass()` are the appropriate structural checks for concrete mutation plugin contracts. |
| [Google Gemini Function Calling docs](https://ai.google.dev/gemini-api/docs/function-calling) | Use clear function and parameter descriptions, strong types/enums, a relevant tool set, robust error handling, and avoid exposing sensitive data through function calls. |
| [Microsoft Azure OpenAI structured outputs docs](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs) | Strict schemas are useful but constrained; arbitrary SQL row shapes are a poor fit for strict output schemas. |
| [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | Do not log secrets, access tokens, passwords, connection strings, or sensitive personal data directly; logs need access control, retention, rotation, and disk-exhaustion planning. |

## Current Snapshot

No generic SQL pagination tool or cursor-token mechanism is implemented. The
project also does not implement in-process telemetry percentiles, a model-visible
stats tool/resource, a session schema cache, or a `db://schema` resource.

The v3.4.3 runtime fix keeps SQLite row estimates bounded: when `sqlite_stat1`
is unavailable and the 10,000-row sample cap is reached,
`SQLiteAdapter.get_row_estimate()` now returns the cap as a lower-bound estimate
instead of running full `COUNT(*)`. Exact counts remain explicit through user SQL
or `get_table_summary(exact_count=True)`.

V343-006 through V343-008 were reviewed again on 2026-05-26. The current policy
is documentation and deployment guidance rather than new runtime controls: raw
SQL echo remains for compatibility and transparency, skill audit params remain
business audit data rather than a secret store, and JSONL rotation/retention is
delegated to the deployment environment.

A 2026-05-26 implementation overengineering review found no implemented generic
pagination, stats tool/resource, session schema cache, `db://schema` resource,
raw-SQL echo switch, audit redaction policy engine, or in-process log manager.
The main implementation cleanup candidate is startup-time generation of the
human `skills/SKILLS.md` overview; lower-priority cleanup candidates are tracked
below. No runtime changes have been made for these rows yet.

A follow-up review of non-AutoGen modules found additional maintainability and
security-boundary risks around import-time side effects, import-time config
freezing, adapter metadata identifier handling, and manual smoke scripts being
collected like regular tests. These are tracked as design risks first; broad
settings-object or test-suite reshuffles should not be introduced without a
concrete cleanup plan.

A subsequent security-boundary review found narrow SQL hardening gaps in the
MCP extended checks and local error logging. These are recorded as risks only;
the current change set does not modify runtime behavior.

On 2026-05-27, a skeptical read-only verification re-ran direct safety probes
without executing dangerous SQL against the live database. The review confirmed
DRR-2026-011, DRR-2026-012, and DRR-2026-015 as accurate, refined
DRR-2026-013 as a dialect/scope overclaim rather than a proven MySQL/SQLite
write path, and added missing workflow/SQLAlchemy hygiene risks below.

A later 2026-05-27 read-only pass covered the Skills loader/audit layer,
configuration/startup surfaces, adapter write semantics, and default test
collection. It found that some previously documented risks were understated:
local Skills code and metadata need their own boundary checks, query skills do
not yet share the free-form query tool's extended SQL checks, default pytest can
reach a live database through a root smoke test, dependency installs are not
reproducible, and MySQL mutation timeout wording currently relies on a
SELECT-oriented mechanism without a write-path proof.

On 2026-05-28, a focused hardening pass implemented the highest-priority SQL
policy and logging hygiene fixes without starting the multi-database work. Raw
queries and query skills now share one read-query policy, MySQL file operations
and quoted/comment-separated system metadata bypass forms are denied, Skills
directory containment uses path-aware checks, and adapter logs/SQLAlchemy engines
avoid exposing SQL parameter values.

The same 2026-05-28 hardening pass also closed the adapter metadata identifier
boundary tracked in DRR-2026-008 and DRR-2026-014. Adapter metadata methods now
accept only simple unqualified table names, bind table-name predicates where the
name is data, and quote SQLite identifiers where the name must remain an
identifier.

Later on 2026-05-28, DRR-2026-023 was closed by defining the default pytest
contract explicitly: `pytest.ini` limits default collection to `tests/`, while
root-level MCP smoke scripts remain manual/live checks run via their script
entrypoints against a safe development or fixture database.

On 2026-05-29, DRR-2026-020 was closed by tightening the lightweight Skills
parameter schema rather than replacing it with full JSON Schema. Unsupported
parameter type names now fail closed during discovery and validation, and bool
params accept only JSON booleans plus explicit `true`/`false` string literals.

Also on 2026-05-29, a multi-database readiness review concluded that the
earlier fix-first plan is substantially complete for design work: DRR-2026-011,
DRR-2026-012, DRR-2026-015, DRR-2026-017, DRR-2026-018, DRR-2026-019,
DRR-2026-023, and DRR-2026-025 are implemented, and the adapter-boundary work
in DRR-2026-008 and DRR-2026-014 is already in place. DRR-2026-024 remains
deferred but is not treated as a blocker because the observed conflict surface
is in optional AutoGen example dependencies rather than the core server runtime.
Multi-database work can therefore move into design-only planning, but not yet
straight into runtime implementation on the current process-global adapter and
`DB_TYPE` foundation.

On 2026-05-30, the first runtime multi-database slice was implemented as v3.5:
configured named connections, connection-aware read-only core tools,
connection-scoped query Skills, and safe `connection_id` metadata/audit/telemetry.
The implementation deliberately keeps mutation Skills on the default connection
only. The resolved-connection-first invariant is now part of the runtime design:
tools resolve `ConnectionContext` before SQL policy, schema readiness, helper
SQL, execution, metadata, audit, and telemetry. Unknown connection ids fail
closed and never fall back to the default.

A same-day external-docs-backed review closed several follow-up gaps: table
allowlists now normalize quoted and schema-qualified identifiers, public SQLite
payloads use `sqlite:<connection_id>` instead of file paths, legacy mode ignores
both `DB_<ID>_*` variables and `DEFAULT_DB_CONNECTION` unless `DB_CONNECTIONS`
is set, and the standalone `execute_sql()` compatibility helper resolves the
target connection before SQL policy checks.

The same review narrowed the v3.6 mutation multi-connection design direction:
mutation writes should use one consistent high-impact operation protocol. The
preview-token core and strict per-connection mutation policy are now
implemented. Read policy remains separate from write authorization; omitting
the new global mutation target allowlist preserves default-connection-only
routing.

On 2026-08-04, a pre-commit review of the combined v3.5/v3.6 change set ran the
default suite (259 passed, 3 skipped), re-probed the SQL policy without
executing destructive SQL, and compared the implementation against FastMCP 3.0.2
and the MCP 2025-06-18 tools specification. It confirmed the implemented
boundaries but recorded ten new rows below. The highest-impact ones at that time were the
sample-database fixture drift left by live mutation testing (DRR-2026-035), the
server-level `instructions` string that still advertises read-only access while
mutation tools can write (DRR-2026-036), and the incomplete default pytest
environment isolation that partially reopens DRR-2026-023 (DRR-2026-039). The
review also verified that no runtime behavior contradicts the implemented v3.5
and v3.6 rows, and that documentation drift is limited to stale v3.5-era
qualifiers tracked in DRR-2026-042.

On 2026-08-06, the v3.6.1 maintenance update closed DRR-2026-037,
DRR-2026-038, and DRR-2026-041 and extended the replay-protection work recorded
under DRR-2026-034. This remains part of the v3.6 release family.

The 2026-08-08 scope review closed DRR-2026-045 by selecting the bounded
process-local memory store and a stdio-first deployment. Conditional HTTP
mutation is limited to one process in a trusted private boundary; multi-user
authenticated HTTP and cross-host replicas are not v3.6.1 baselines. Read-only
capacity may scale only through a separate endpoint/profile/pool.

The 2026-08-10 follow-up closed DRR-2026-036, DRR-2026-040, and DRR-2026-042,
documented the accepted DRR-2026-043 asymmetry, bounded preview TTL at 86400
seconds, tightened the preview-failure contract, and replaced the duplicated
store concurrency check with a full-tool concurrent replay regression.

## Register

| ID | Status | Risk level | Date first registered | Area | Risk or concern | Plan? | Modification logic | Current result | Next action |
|---|---|---|---|---|---|---|---|---|---|
| V343-001 | Implemented | Medium | 2026-05-24 | SQLite row estimates | Metadata discovery previously upgraded from a 10,000-row sample to full `COUNT(*)` on larger SQLite tables. | Yes | Prefer `sqlite_stat1`; when the sample cap is reached, return the cap as a lower-bound estimate. Keep exact counts opt-in. | Completed 2026-05-24 in `db_adapter.py`; tests added in `tests/test_db_adapter.py`; docs updated. | Monitor user expectations around lower-bound estimates; recommend `ANALYZE` or explicit count when precision is required. |
| V343-002 | Implemented | Medium | 2026-05-24 | Query result truncation | `query()` and `execute_query_skill()` fetch full adapter results before truncating returned payload. | Documentation only for v3.4.3 | Clarify that truncation limits returned payload only; users should add `WHERE`/`LIMIT`/`ORDER BY` to limit database work and stabilize order. | Tool messages and docs updated. Adapter-level streaming remains deferred. | Revisit `fetchmany()` or streaming only with compatibility tests. |
| V343-003 | Implemented | Low | 2026-05-24 | Tool descriptions | `list_tables()` and `get_full_schema()` overclaimed by saying all/complete despite allowlist and truncation. | Yes | Use visible/truncated wording and clarify returned counts. | Tool-facing descriptions and docs updated. | Keep future tool descriptions precise and conservative. |
| V343-004 | Implemented | Medium | 2026-05-24 | Security wording | Some docs overclaimed comprehensive SQL analysis or universal `validate_name()`/`validate_params()` coverage. | Yes | Describe sqlparse as statement-type allowlist plus MCP-layer checks; distinguish Skills validators from base SQL/table validators. | README and design docs updated. | Avoid expanding security claims without matching enforcement. |
| V343-005 | Implemented | Low | 2026-05-24 | Prompt guide | `get_table_summary()` was treated as a default planning step although disabled by default and exact count is opt-in. | Yes | Prefer `describe_table()` estimates; use explicit `COUNT(*)` or `get_table_summary(exact_count=True)` only when precision is required. | Prompt guide updated; no runtime test needed. | Keep prompt examples aligned with default-enabled tools. |
| V343-006 | Accepted | High | 2026-05-26 | Raw SQL echo/log visibility | Raw `query(sql)` logs full SQL to context and returns SQL in structured payloads; literals may contain sensitive values. | Documentation only | Keep current echo behavior for compatibility and debugging transparency. Do not put secrets, tokens, or sensitive personal data in raw SQL literals. Prefer least-sensitive predicates, views, or reviewed skills for repeatable sensitive workflows. | Documented 2026-05-26 in README and this register. No runtime switch added to avoid premature compatibility churn. | Revisit an opt-out echo/log switch only if a privacy-sensitive deployment requires it. |
| V343-007 | Accepted | High | 2026-05-26 | Skills audit parameter logging | Audit records params after length truncation only; no key/value redaction policy. | Documentation only | Treat skill params as business audit data, not a place for secrets. Keep `SKILLS_AUDIT_QUERIES=0` by default; mutation audit is still attempted automatically for traceability, with completeness caveats in DRR-2026-022. | Documented 2026-05-26 in README, `skills/SAFETY.md`, `.env.example`, and this register. No runtime redaction layer added. | Revisit key-based redaction or per-skill redaction metadata if future skills need sensitive params. |
| V343-008 | Operational Decision | Medium | 2026-05-26 | Append-only JSONL logs | Audit, telemetry, and server logs are local files without built-in rotation or retention. | Documentation/deployment guidance | Prefer external log rotation, retention, access control, and disk monitoring over in-process log management. Audit/telemetry open files per write, so rename/create rotation works well. | Documented 2026-05-26 in README, `skills/SAFETY.md`, `.env.example`, and this register. | Use `logrotate`, platform logging, cron cleanup, or managed log sinks in production; revisit code only for constrained single-binary deployments. |
| V343-009 | Accepted | Low | 2026-05-24 | `ToolResult.meta` visibility | `_meta` includes runtime stats and may be surfaced by some clients. | No behavior change | Keep metadata non-sensitive; do not add SQL, params, rows, credentials, or user identities. | Accepted compromise. | Re-check whenever new meta fields are added. |
| V343-010 | Deferred | Low | 2026-05-24 | Base-tool output schemas | Strict output schemas for arbitrary SQL rows would be misleading or too broad. | Not planned as blanket change | Keep schemas only where envelopes are stable. | Deferred intentionally. | Reconsider stable tools individually if needed. |
| V343-011 | Not Planned | Low | 2026-05-24 | Generic SQL pagination params | `limit`, `offset`, `page`, or cursor tokens on arbitrary SQL duplicate SQL semantics and can be wrong without stable ordering. | No | Keep pagination in user SQL; use domain-specific skills if explicit ordering keys exist. | Not implemented. | Do not add generic `query(limit, offset)` without a new design review. |
| V343-012 | Deferred | Medium | 2026-05-24 | Telemetry stats tool | In-process p50/p95 aggregation or a model-visible stats tool can expose operational usage patterns and needs bounded state. | Deferred beyond v3.4.3 | Keep telemetry as opt-in JSONL; compute aggregates externally. | Deferred intentionally. | Revisit only with a bounded, non-model-visible design. |
| V343-013 | Deferred | Medium | 2026-05-24 | Session schema cache | Session schema caches can stale after DDL and affect safety/readiness decisions. | Deferred beyond v3.4.3 | Keep execution-time checks authoritative. | Deferred intentionally. | Reconsider only with explicit invalidation strategy. |
| V343-014 | Deferred | Medium | 2026-05-24 | `db://schema` resource | A schema resource would add a duplicate schema access path and extra model-visible context surface. | Deferred beyond v3.4.3 | Keep explicit `get_full_schema()` for now. | Deferred intentionally. | Revisit only if client resource support becomes a concrete need. |
| DRR-2026-001 | Deferred | Medium | 2026-05-26 | Startup side effects | When Skills are enabled, server import/startup currently discovers skills and writes the human `skills/SKILLS.md` overview. Runtime startup should ideally be read-only apart from logs/audit files. | Candidate code cleanup, not yet implemented | Keep eager in-memory skill discovery/cache for TOCTOU protection, but move human overview generation to an explicit maintenance command or script if this is changed. | Documented 2026-05-26 in this register; no runtime change yet. | Before editing code, decide whether `skills/SKILLS.md` remains a tracked generated artifact and add tests/docs for the explicit generation path. |
| DRR-2026-002 | Accepted | Low | 2026-05-26 | Display-oriented env defaults | `SKILLS_LIST_DEFAULT_DETAIL` and `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` are presentation defaults even though `list_skills()` already accepts per-call `detail_level` and `available_only`. Extra env defaults increase configuration and re-import test matrix. | No immediate behavior change | Treat these as compatibility defaults, not security controls. Per-call arguments remain the primary interface. | Accepted for compatibility. | Revisit only if there is no concrete client that needs environment-level list defaults, or in a breaking-change release. |
| DRR-2026-003 | Implemented | Low | 2026-05-26 | Skills availability helpers | `_skill_executable_state()` and `_skill_is_executable()` wrapped `_skill_availability_state()` but had no real callers. The extra names made availability policy look less centralized than it was. | Yes | Delete both wrappers and retain `_skill_availability_state()` as the single source of truth. | Implemented 2026-08-10 in `mcp_sql_server.py`; Skills disclosure and multi-connection regressions pass without the wrappers. | Keep availability decisions on `_skill_availability_state()` rather than adding convenience wrappers without consumers. |
| DRR-2026-004 | Accepted | Low | 2026-05-26 | Legacy feature-switch naming | `ENABLE_SCHEMA_TOOLS` is a legacy name that currently gates `sample()` rather than all schema tools. Renaming it could improve clarity but would create compatibility churn. | Documentation/compatibility only | Do not broaden the switch to cover unrelated schema tools. If clarity becomes necessary, add a compatible alias such as `ENABLE_SAMPLE_TOOL` rather than repurposing the legacy variable. | Accepted as a legacy naming compromise. | Keep docs precise that the current switch controls `sample()` only. |
| DRR-2026-005 | Accepted | Low | 2026-05-26 | Low-level SQLite tuning surface | `SQLITE_PROGRESS_HANDLER_INTERVAL` exposes SQLite VM progress-handler frequency. The timeout mechanism is valid, but this interval is a lower-level tuning knob than most deployments need. | No immediate behavior change | Keep `QUERY_TIMEOUT_SECONDS` as the user-facing timeout control. Avoid adding more low-level DB tuning env vars without measured deployment need. | Accepted for compatibility. | Revisit only if the interval causes measured CPU/latency issues or if a breaking cleanup release removes rarely used tuning knobs. |
| DRR-2026-006 | Deferred | Medium | 2026-05-26 | Import/startup side effects | `start_server.py` imports the server, loads `.env`, creates `logs/`, and installs a timestamped `FileHandler` at module import time, before environment validation. Simple imports or tool probes can therefore create files and freeze server configuration early. | Candidate code cleanup, not yet implemented | Prefer a read-only import path. Move logging setup and the `mcp_sql_server` import into `main()` or an explicit startup factory only when doing a focused startup cleanup. | Documented 2026-05-26 in this register; no runtime change yet. | Revisit with tests that import `start_server.py` without creating log files and still allow FastMCP `Client(str(start_server.py))` startup. |
| DRR-2026-007 | Deferred | Medium | 2026-05-26 | Import-time configuration freeze | `db_adapter.py` reads DB settings into module constants at import time, `sql_safety_checker.py` imports `QUERY_TIMEOUT_SECONDS` directly, and the adapter is cached globally. Tests must reload modules or clear `sys.modules` to change configuration. | No broad settings refactor now | Avoid a large settings-object rewrite without a concrete need. If this is cleaned up, prefer a narrow factory/config injection path that preserves the existing public API. | Documented 2026-05-26 in this register; no runtime change yet. Re-reviewed 2026-05-29 against the multi-database precondition plan: the earlier security/hardening items are largely complete, so this row is now the main foundation risk before runtime multi-database support. | Multi-database work may proceed to design-only planning now, but runtime implementation should first choose a narrow connection-aware adapter/config model (for example a per-call `connection_id` registry) instead of extending the current process-global `DB_TYPE` plus singleton adapter path. Revisit alongside DRR-2026-006 if startup/import cleanup becomes necessary. |
| DRR-2026-008 | Implemented | High | 2026-05-26 | Adapter metadata identifier handling | Adapter metadata methods built SQL/PRAGMA statements from `table_name` strings in both MySQL and SQLite paths. MCP tools validated identifiers before calling them, but the adapter is also a public internal API used by tests and scripts. | Yes | Centralized adapter metadata identifier validation for simple unqualified names. MySQL `INFORMATION_SCHEMA` table-name predicates now use parameter binding; SQLite metadata paths validate and quote identifiers before `PRAGMA` or bounded sample SQL. | Implemented 2026-05-28 in `db_adapter.py`; `tests/test_db_adapter.py` covers invalid names, schema-qualified names, quoted identifiers, MySQL binding, and SQLite bounded-sample quoting. | If future DB support needs schema-qualified names, add a structured `(schema, table)` API rather than accepting dotted or pre-quoted strings. |
| DRR-2026-009 | Deferred | Medium | 2026-05-26 | Smoke/manual test boundary | Root-level smoke scripts such as `test_mcp_client.py`, `test_mcp_functions.py`, and source-reading `test_bug_fixes.py` mix manual integration checks with pytest collection. Some depend on real DB/server state or assert source strings instead of behavior. | Test-suite cleanup candidate | Keep behavior regression tests under `tests/`; move manual smoke flows to explicit scripts or mark them as integration/manual. Avoid deleting useful coverage before replacing it with behavior tests. | Documented 2026-05-26 in this register; no runtime change yet. | Revisit after deciding the repo's default pytest boundary and CI expectations. |
| DRR-2026-010 | Accepted | Low | 2026-05-26 | Demo writes in runtime module | `sql_safety_checker.py` contains a `__main__` demo that can create and seed a `test_users` table. It is not an import-time side effect, but it puts write-oriented demo setup in a safety module. | No immediate behavior change | Prefer explicit demo/setup scripts for write examples. Do not add more write demos to runtime library modules. | Accepted as legacy demo code. | If cleaning examples, move the demo to `scripts/` or documentation and keep `sql_safety_checker.py` focused on validation/execution helpers. |
| DRR-2026-011 | Implemented | High | 2026-05-26 | MySQL SELECT file operations | The basic and extended SQL safety checks treated MySQL `SELECT ... INTO OUTFILE`, `SELECT ... INTO DUMPFILE`, and `LOAD_FILE(...)` as safe SELECT forms. If the DB account had `FILE` privilege, these could read or write server-side files; `DUMPFILE`/`LOAD_FILE` may not include table names, so table allowlists did not address the risk. | Yes | Added explicit MCP-layer rejection for MySQL server-side file operations after comment normalization. Kept this as a narrow denylist rather than a broad parser rewrite. | Implemented 2026-05-28 in `mcp_sql_server.py`; `tests/test_sql_policy.py` covers OUTFILE, DUMPFILE, LOAD_FILE, and comment-separated forms. | Continue relying on least-privilege DB accounts without `FILE`; add dialect-specific tests if new SQL backends are introduced. |
| DRR-2026-012 | Implemented | High | 2026-05-26 | SHOW/system schema bypass forms | The extended checks blocked plain `SHOW VARIABLES` and `information_schema.tables`, but comment-separated SHOW forms and backtick-quoted system schemas such as `` `information_schema`.`tables` `` or `` `mysql`.`user` `` were not blocked by the regexes. | Yes | Added comment stripping/whitespace normalization before denylist checks and expanded system-schema matching to quoted schema identifiers. Table allowlists remain defense in depth, not the only system-schema barrier. | Implemented 2026-05-28 in `mcp_sql_server.py`; `tests/test_sql_policy.py` covers comment-separated SHOW and quoted `mysql`/`performance_schema`/`information_schema` references. | Keep future metadata-access changes on the shared policy path; avoid adding separate weaker SQL checks. |
| DRR-2026-013 | Deferred | Medium | 2026-05-26 | SQL dialect safety overclaim | `is_sql_safe()` classifies statements by top-level `sqlparse` type and currently treats data-modifying CTE forms such as `WITH ... DELETE ... RETURNING ... SELECT ...` as safe. Direct probes also classify `EXPLAIN DELETE ...` as safe. Current MySQL/SQLite paths do not prove a destructive execution path for these forms, but the module docstring claims PostgreSQL-style dialect breadth. | Documentation or parser hardening, not yet implemented | Either narrow the stated guarantee to the supported MySQL/SQLite execution paths, or add explicit checks for DML tokens inside CTEs and other nested constructs. Avoid claiming comprehensive SQL analysis or treating `EXPLAIN` over DML as equivalent to executing DML without dialect evidence. | Documented 2026-05-26; re-verified 2026-05-27 as a safety-scope/claim precision issue, not yet a confirmed MySQL/SQLite write vulnerability. No runtime change yet. | Add tests for data-modifying CTEs, `EXPLAIN DELETE`, and nested DML-looking tokens before changing claims or checks. |
| DRR-2026-014 | Implemented | Medium | 2026-05-26 | Adapter metadata semantic injection | Direct SQLite adapter calls such as `get_row_estimate("users) --")` could change metadata SQL semantics, including bypassing the bounded sample `LIMIT` and falling back to a full count. MCP tools rejected those identifiers, but adapter methods remained a public internal boundary. | Yes | Same direction as DRR-2026-008: adapter metadata methods now validate first and quote SQLite identifiers for bounded sampling. Upstream MCP validation remains defense in depth, not the only guard. | Implemented 2026-05-28 in `db_adapter.py`; `tests/test_db_adapter.py` proves invalid identifiers do not reach `execute()` and valid sampling uses a quoted SQLite identifier. | Keep exact-count paths and future metadata helpers on the same adapter identifier policy. |
| DRR-2026-015 | Implemented | High | 2026-05-26 | Error log parameter exposure | Adapter `_handle_error()` logged `str(e)[:200]`. SQLAlchemy exception strings can include SQL text and bound parameter values before the sanitized client error is returned. This was local log exposure, not client response exposure. | Yes | Kept client errors sanitized, reduced adapter error logs to exception class names, and set SQLAlchemy engines to `hide_parameters=True` where engines are created. | Implemented 2026-05-28 in `db_adapter.py`; `tests/test_db_adapter.py` verifies adapter logs do not include SQL text or parameter values. | Keep audit payloads and tool telemetry under their separate documented policies; do not reintroduce raw exception logging in adapter paths. |
| DRR-2026-016 | Implemented | Medium | 2026-05-27 | CI guardrail overclaim | README/REFACTORING_LOG wording said annotation consistency regressions fail in CI, but the repository currently has a pytest guardrail without an accompanying CI workflow/config. This could mislead reviewers into assuming automatic enforcement that is not present in the repo. | Documentation cleanup | Weakened docs to say the guardrail fails under pytest/local/default test runs until CI is actually configured. Avoid security/process claims that exceed enforcement. | Updated 2026-05-30 in README, README_ZH, MCP_AGENTS_SKILLS_DESIGN, REFACTORING_LOG, and this register. No workflow added. | If the project later adds CI, update these docs again and record the workflow file. |
| DRR-2026-017 | Implemented | Medium | 2026-05-27 | SQLAlchemy URL construction hygiene | MySQL connection setup built a URL with an f-string containing raw username/password/host/database parts. Special characters in credentials could break parsing or produce confusing connection errors, and this sat near the existing parameter-logging concern. | Yes | Replaced f-string URL construction with SQLAlchemy `URL.create`, and paired engine creation with `hide_parameters=True` plus explicit logging names. This stayed narrower than a broad settings rewrite. | Implemented 2026-05-28 in `db_adapter.py`; `tests/test_db_adapter.py` covers credentials containing `@`, `:`, and `/` characters. | Revisit when the future multi-database registry introduces multiple URL builders or per-connection logging identifiers. |
| DRR-2026-018 | Implemented | High | 2026-05-27 | Skills directory containment | Skills startup checked an absolute `SKILLS_DIR` with string prefix comparison against the project root. A sibling path whose string begins with the project root path could pass this check, and mutation skills are imported with `exec_module()` during discovery. Local code execution is expected for trusted in-repo skills, but the containment check should not be weaker than the later loader-level path checks. | Yes | Replaced string-prefix containment with `Path.resolve().relative_to()` before discovery/import. Mutation skill code remains explicitly trusted local code; `SKILLS_DIR` is not a sandbox. | Implemented 2026-05-28 in `mcp_sql_server.py`; `tests/test_sql_policy.py` covers sibling-prefix path rejection. | Add symlink-specific containment tests if Skills path policy changes again. |
| DRR-2026-019 | Implemented | High | 2026-05-27 | Query skill safety parity | Query skill discovery pre-audited SQL templates with the base `is_sql_safe()` check but did not apply the MCP free-form query tool's extended checks or table allowlist. As a result, query skills could accept the same shapes tracked in DRR-2026-011 and DRR-2026-012 during startup even though `execute_query_skill()` later skipped runtime SQL safety checks and relied on discovery-time trust. | Yes | Added a shared read-query policy function and passed it into query skill discovery; `execute_query_skill()` also re-checks the cached SQL template at runtime before execution. | Implemented 2026-05-28 in `mcp_sql_server.py` and `skills/_lib/skill_loader.py`; tests cover policy injection plus the shared deny checks. | Keep raw query and query-skill validation on the same helper when adding multi-database `connection_id` support. |
| DRR-2026-020 | Implemented | Medium | 2026-05-27 | Skills parameter schema claims | `validate_params()` uses a small custom schema language rather than JSON Schema, and already rejected extra params, but it had weak edges: unknown type names passed through, and bool coercion via `bool(value)` made strings such as `"false"` truthy. This undercut docs or tool descriptions that imply strong structured validation comparable to strict function schemas. | Yes | Constrained the supported schema vocabulary to `int`, `float`, `str`, and `bool`; unsupported type names now fail closed. Bool params parse only native booleans plus explicit `"true"`/`"false"` string literals, not Python truthiness. The schema remains lightweight and is not described as full JSON Schema. | Implemented 2026-05-29 in `skills/_lib/skill_loader.py`; `tests/test_skill_loader.py` covers unknown types, `"false"`, `"0"`, numeric truthy values, extra params, and enum constraints. | Keep any future param types explicit and tested before adding them to the supported vocabulary. |
| DRR-2026-021 | Implemented | Medium | 2026-05-27 | Mutation skill type integrity | Mutation discovery previously checked only for a module-level `Mutation` attribute, and frontmatter names could diverge from directory identity. Because `mutation.py` is imported with `exec_module()` during discovery, malformed trusted-local plugins should fail before runtime tool paths cache or instantiate them. | Yes | Discovery now requires frontmatter `name` to be present, valid, and equal to the skill directory name. Mutation source modules must export a class named `Mutation` that is a concrete `MutationBase` subclass. Manual code review remains required for mutation body safety; this is not a sandbox for untrusted plugins. | Implemented 2026-05-29 in `skills/_lib/skill_loader.py`, `README.md`, `README_ZH.md`, `MCP_AGENTS_SKILLS_DESIGN.md`, and `skills/SAFETY.md`; `tests/test_skill_loader.py` covers missing, mismatched, and invalid names plus missing, non-class, non-subclass, and abstract `Mutation` exports. | If untrusted third-party plugins become a requirement, design process isolation or sandboxing separately instead of extending this loader invariant. |
| DRR-2026-022 | Implemented | High | 2026-05-27 | Skills audit completeness overclaim | `AuditLogger.log()` is best-effort; audit write failures and pre-token parameter/validation rejection can still leave no JSONL record. Older docs/config wording overstated completeness and could be read as fail-closed audit behavior. | Yes | Keep audit as best-effort observability rather than transaction control. Normal result metadata reports actual audit status. As v3.6.1 follow-ups, post-consume dynamic validation rejection attempts an execute-failure audit, while a response-stage failure after a committed write preserves the existing success audit instead of appending a contradictory failure. | Implemented in `skills/_lib/audit.py`, `skills/_lib/mutation_base.py`, `mcp_sql_server.py`, docs, and regressions. The 2026-08-10 follow-up covers dynamic validation returning invalid or raising `ToolError`, honest `audit_logged`, no-write/replay behavior, and a post-write response failure with exactly one successful execute audit. | If compliance ever requires guaranteed audit, design a transactional outbox or database-backed audit mechanism. Do not treat the JSONL file as fail-closed evidence, and do not weaken mutation rejection when logging fails. |
| DRR-2026-023 | Implemented | High | 2026-05-27 | Default pytest live database boundary | `test_mcp_client.py::test_mcp_server` was collected by default pytest. When the configured database was reachable, it started the MCP server against the current `.env`, listed tables, counted the first table, described it, sampled rows, and could execute a query skill. This could touch a live or production-like database and print sample data into captured test output or failure logs. | Yes | Limited default collection to `tests/`, kept root MCP smoke checks as explicit script entrypoints, and documented their live-data boundary. The DRR-2026-039 follow-up also disables `.env` loading in pytest, supplies safe SQLite/process defaults, and makes MySQL integration tests explicit opt-in. | Implemented in `pytest.ini`, `tests/conftest.py`, `README.md`, `README_ZH.md`, and `TEST_MCP_CLIENT_GUIDE.md`; default pytest excludes root smoke scripts and cannot inherit a developer `.env`. | Keep future live DB smoke checks outside default collection unless they have an explicit opt-in gate and non-sensitive output policy. |
| DRR-2026-024 | Deferred | Medium | 2026-05-27 | Dependency reproducibility | `requirements.txt` uses mostly unpinned or lower-bound-only dependencies, including FastMCP and SQLAlchemy APIs that this project uses directly. Without a lockfile, constraints file, or CI matrix, future installs can silently pick versions with behavior or compatibility changes, weakening claims that local/default tests represent release behavior. Dry-run evidence also shows the optional AutoGen chain is the current conflict surface, not the core server runtime path. | Packaging/workflow cleanup candidate, not yet implemented. AutoGen examples are not the program's mainline runtime. | If this is fixed later, split runtime/dev/optional AutoGen dependencies first, then add constraints or a documented tested version set for the paths the repo actually supports. Avoid presenting unconstrained installs as reproducible release inputs. | Documented 2026-05-27 after config/dependency review. On 2026-05-29, `.venv` `pip check` reported `autogen-core 0.7.5` requiring `protobuf~=5.29.3` while `protobuf 6.33.5` was installed. A clean requirements dry-run resolved `protobuf 5.29.6`; core-runtime-only resolution did not introduce `protobuf`. v3.6.1 adds only the narrow `python-dotenv>=1.2.0` lower bound required for `PYTHON_DOTENV_DISABLED`; it does not make the wider dependency set reproducible. | Keep the broader item deferred. Do not let optional AutoGen example dependencies define core runtime reproducibility claims, and do not describe the current unpinned set as a reproducible release input. |
| DRR-2026-025 | Implemented | High | 2026-05-27 | MySQL mutation timeout semantics | `MySQLAdapter.execute_write()` used `MAX_EXECUTION_TIME`, but MySQL documents this mechanism as SELECT/read-query oriented. Controlled MySQL validation confirmed the gap: `SELECT SLEEP(2)` under `timeout=1` stopped at about 1.079s, while `UPDATE ... SLEEP(2)` still committed after about 2.171s. | Yes | Removed write-path `MAX_EXECUTION_TIME`. MySQL `execute_write()` now sets session `innodb_lock_wait_timeout = max(1, timeout_seconds)` before the mutation and fails closed if that guard cannot be configured. Documentation now distinguishes read-query timeout, InnoDB row-lock wait timeout, PyMySQL socket timeouts, and deployment-side DML controls. | Implemented 2026-05-29 in `db_adapter.py`, `tests/test_db_adapter.py`, README/docs, and Skills safety docs. Controlled proof used database `trade_data_analysis`: old write path ignored `timeout=1`; a separate lock-wait scenario with `innodb_lock_wait_timeout=2` raised OperationalError 1205 after about 3.236s. | Remaining boundary: this is not a full wall-clock statement timeout for all MySQL DML CPU/IO work. Keep driver read/write timeouts and deployment-side statement controls in scope if production requires a hard mutation execution limit. |
| DRR-2026-026 | Implemented | High | 2026-05-30 | Multi-connection policy/execution cross-wire | Runtime multi-database support could resolve policy, quoting/schema helpers, adapter execution, metadata, audit, or telemetry from different connections, causing a tool to display or validate against one database while executing against another. | Yes | Introduced `ConnectionContext` and resolved it before policy, schema readiness, dialect-specific helper SQL, execution, metadata, audit, and telemetry. Internal helper queries in `sample()` and exact table counts execute directly on the selected adapter rather than via the legacy default execution wrapper. | Implemented 2026-05-30 in `db_adapter.py`, `sql_safety_checker.py`, and `mcp_sql_server.py`; `tests/test_multi_connection_v35.py` covers same-connection policy/execution and fail-closed unknown ids. | Keep new tools on the resolve-first pattern; add regression tests whenever a helper path quotes identifiers or executes internal SQL. |
| DRR-2026-027 | Implemented | High | 2026-05-30 | Skills display/execution mismatch | Skills discovery could show a skill as executable for one database type or schema while execution used another adapter, especially with named connections and per-connection allowlists. | Yes | Made `list_skills`, `get_skill_detail`, and `execute_query_skill` accept optional `connection_id` and evaluate DB compatibility, schema readiness, allowlists, metadata, optional audit, and telemetry against the same target connection. `SkillMetadata.databases` remains a DB type compatibility field, not a connection-id allowlist. | Implemented 2026-05-30 in `mcp_sql_server.py`; `tests/test_multi_connection_v35.py`, `tests/test_skills_disclosure.py`, and docs cover target-connection availability/execution consistency. | Keep `available_only` documented as discovery filtering, not authorization; execution checks remain mandatory. |
| DRR-2026-028 | Implemented | Medium | 2026-05-30 | Adapter registry lifecycle and resource bounds | Multiple named connections require multiple long-lived SQLAlchemy Engines. A registry can leak resources if reset/lifecycle behavior is unclear, and can complicate tests that reload environment state. | Yes | Added a process-local lazy adapter cache keyed by configured `connection_id`, plus `reset_adapter(connection_id=None)` to close one or all adapters in tests/reconfiguration. Kept connection definitions server-configured and import-time parsed for compatibility rather than adding dynamic per-request DSNs. | Implemented 2026-05-30 in `db_adapter.py`; `tests/test_db_adapter.py` and `tests/test_multi_connection_v35.py` cover registry behavior. | Deferred: no LRU/upper bound/credential refresh yet. Revisit if deployments configure many connections or require runtime config reload. |
| DRR-2026-029 | Implemented | Medium | 2026-05-30 | Connection identity in logs and metadata | Operators need to distinguish which configured connection handled a tool call, but exposing connection internals in `ToolResult.meta`, telemetry, audit, or structured payload display fields would leak sensitive DB details. | Yes | Added safe `connection_id` alias and actual `db_type` to result metadata, optional telemetry, and Skills audit. `list_connections()` returns aliases and policy summaries only. Public SQLite `database_name` display fields use `sqlite:<connection_id>` instead of file paths. DSNs, hosts, usernames, passwords, SQLite paths, SQL params, and returned rows remain excluded. | Implemented 2026-05-30 in `mcp_sql_server.py`, `skills/_lib/audit.py`, `skills/_lib/mutation_base.py`, docs, and tests; follow-up tests cover SQLite path non-exposure in `check_connection()` and `list_tables()`. | Re-check whenever new metadata/audit/payload fields are added; do not add connection internals without a privacy review. |
| DRR-2026-030 | Implemented | High | 2026-05-30 | Multi-connection mutation writes | Allowing mutation Skills to choose arbitrary configured connections requires per-connection write permissions, preview/execute target binding, audit semantics, and stronger operational guidance for SQLite file locks and MySQL write timeouts. | Yes | Require a global mutation target allowlist, per-connection write switch, per-connection skill allowlist, and an HMAC preview token bound to skill/version/params/connection/db type/expiry. Keep omitted global routing policy default-connection only. | Implemented in `db_adapter.py` and `mcp_sql_server.py`; discovery and execution share policy checks. `tests/test_mutation_multi_connection_v36_design.py` covers routing, token binding, target isolation, denial layers, exact expiry, tampering, skill-version changes, restart behavior, and full-token non-exposure; adapter tests cover config parsing and legacy isolation. | Replay and preview-state hardening are implemented in DRR-2026-034. Continue documenting SQLite lock and MySQL DML timeout boundaries for every authorized write target. |
| DRR-2026-031 | Implemented | High | 2026-05-30 | Quoted identifier allowlist bypass | The MCP table extractor used by allowlist checks did not handle common quoted identifiers consistently. Forms such as `FROM "forbidden"`, `FROM [forbidden]`, or `FROM main."forbidden"` could avoid or misdirect table comparison even though they referenced a disallowed table. | Yes | Added identifier normalization for backticks, double quotes, square brackets, and schema-qualified references before comparing table names with the target connection allowlist. Kept this as a focused extractor hardening rather than introducing a full SQL parser. | Implemented 2026-05-30 in `mcp_sql_server.py`; `tests/test_sql_policy.py` covers quoted and schema-qualified deny cases plus allowed quoted tables. | Keep future table-reference parsing changes on the shared policy path and add dialect examples before broadening syntax support. |
| DRR-2026-032 | Implemented | Medium | 2026-05-30 | Legacy named-env leakage | Local multi-connection `.env` values such as `DB_DEFAULT_*` and `DEFAULT_DB_CONNECTION` could affect legacy single-connection mode when `DB_CONNECTIONS` was unset or empty. This could break backward compatibility or make a legacy startup fail because a named default was not present. | Yes | Treat `DB_CONNECTIONS` as the sole feature gate for named connections. In legacy mode, ignore both `DB_<ID>_*` variables and `DEFAULT_DB_CONNECTION`; legacy `DB_TYPE` / `SQLITE_DATABASE_PATH` remain authoritative. | Implemented 2026-05-30 in `db_adapter.py`, `.env.example`, README/docs, and tests; `tests/test_db_adapter.py` covers ignored `DB_DEFAULT_*` and ignored default selection in legacy mode. | Preserve this gate when adding new per-connection settings; do not let named variables affect legacy mode without an explicit migration decision. |
| DRR-2026-033 | Implemented | Medium | 2026-05-30 | Compatibility helper resolve order | The standalone `sql_safety_checker.execute_sql(..., connection_id=...)` helper could run SQL safety checks before resolving the target connection. Unknown ids should fail closed before any target-specific policy or execution path is considered. | Yes | Resolve `connection_id` with `get_connection_config()` before `is_sql_safe()` and adapter execution, matching the MCP resolve-first invariant. | Implemented 2026-05-30 in `sql_safety_checker.py`; `tests/test_multi_connection_v35.py` covers unknown `connection_id` returning a connection error before SQL policy. | Keep compatibility helpers aligned with MCP tool ordering whenever connection-aware policy expands. |
| DRR-2026-034 | Implemented | High | 2026-05-30 | Preview-token replay and reviewed-state drift | A valid HMAC token could be replayed before expiry, and the bundled mutation previously re-read current state during execute instead of locking against the state shown in preview. Optimistic locking alone was not a generic replay or reviewed-state boundary. | Yes | Add random `jti`, bind a bounded execution-state hash, register digest/expiry/canonical binding in a bounded locked process-local memory store, and consume before dynamic validation/write. Consumption is terminal after later failures; never fall back to stateless HMAC acceptance. | Implemented in `mcp_sql_server.py`, `preview_token_store.py`, `MutationBase`, and `update-order-status`. Tests cover unique issuance, sequential replay, tool-level concurrent redemption with exactly one write, bounded capacity, lazy expiry, restart invalidation, static-rejection non-consumption, terminal outcomes, state drift, and rejected unbound execution. | Preview and execute must reach the same process. Client-owned stdio is recommended. Conditional HTTP mutation is limited to one process in a trusted private boundary; multi-user authenticated HTTP mutation is outside v3.6.1. Restart and cross-process requests invalidate outstanding tokens. Do not add a stateless fallback. |
| DRR-2026-035 | Implemented | Low | 2026-08-04 | Sample database fixture drift resolved | Live mutation smoke testing had made the tracked sample database appear to contain an uncommitted status change. That working-tree drift no longer exists. | Yes | Keep `sample_data/demo.db` at its tracked baseline and use disposable databases for tests that perform writes. | Reverified 2026-08-10: `git diff -- sample_data/demo.db` is empty, and both `HEAD` and the working copy record order `id=4` as `confirmed`. | Do not use the tracked sample database as a mutation-test fixture; create a temporary copy/database for future live write checks. |
| DRR-2026-036 | Implemented | Medium | 2026-08-04 | Server instructions overclaimed read-only | The FastMCP server-level `instructions` string said "Database query assistant with READ-ONLY access" even when optional mutation Skills could perform controlled writes. This model-facing mismatch could bias tool selection and misrepresent the safety boundary. | Yes | Describe read-only core SQL tools, configured connection routing, optional Skills, and controlled mutations protected by preview plus a one-time token. Keep the wording short. | Implemented 2026-08-10 in `mcp_sql_server.py`. A regression asserts that server instructions no longer claim universal read-only access and do describe optional controlled mutations. | Keep instructions synchronized with the registered tool surface and avoid implying that `confirm=true` proves human approval. |
| DRR-2026-037 | Implemented | Medium | 2026-08-04 | Mutation dual execution paths | `MutationBase` requires a concrete `execute()`, so `update-order-status` kept both `execute()` and `execute_with_binding()`. The public `execute()` path re-read current status and could write without preview-state binding, recreating the TOCTOU behavior DRR-2026-034 removed if called outside MCP. | Yes | Keep the abstract-method-compatible `execute()` method but make it fail closed with `ToolError`. The only authoritative write implementation is now `_execute_with_expected_status()`, reached through `execute_with_binding()` with server-held preview state. | Implemented 2026-08-06 in `skills/update-order-status/mutation.py`; `test_update_order_status_rejects_direct_unbound_execute` verifies direct invocation fails without changing the row. | Keep the ABC while only one Skill is binding-only so malformed Skills still fail during discovery. If multiple binding-only Skills justify a redesign, add a loader invariant requiring an override of at least `execute()` or `execute_with_binding()` before removing the abstract method. |
| DRR-2026-038 | Implemented | Medium | 2026-08-04 | Preview binding provenance and preview-failure tokens | `build_execution_binding()` in `update-order-status` read the first validation query, while `preview()` displayed a separate second query. A change between reads made the displayed and bound status differ; a failed second read could still report success and issue a token. | Yes | Return the preview read's `current_status` and build the execution binding from that exact field. Treat any preview containing `error`, declaring `success=false`, or supplying a non-boolean/non-true `success` value as failed; audit it and issue no token. | Implemented in `mcp_sql_server.py` and `skills/update-order-status/mutation.py`. Regressions interleave a state change and cover non-empty, empty, and null `error`, boolean false, and malformed non-true success values; every failed preview leaves the token store empty. | Custom mutation Skills should omit `success` on success or set it to boolean true; on failure, return an `error` field, return boolean `success=false`, or raise `ToolError`. Introduce a typed result only if more Skills make the dictionary contract hard to maintain. |
| DRR-2026-039 | Implemented | High | 2026-08-04 | Default pytest environment isolation gap | `tests/conftest.py` previously cleared only two routing variables while `db_adapter.py` loaded the developer's `.env`. Legacy database credentials, read policy, Skills, and telemetry settings could therefore alter default tests; the optional MySQL fixture could even connect to a live database. | Yes | Set `PYTHON_DOTENV_DISABLED=1` before application imports, install an explicit safe SQLite/config baseline for default pytest, clear legacy MySQL credentials unless live integration was explicitly requested, and require `RUN_MYSQL_INTEGRATION_TESTS=1` before the MySQL fixture can connect. | Implemented 2026-08-10 in `tests/conftest.py`; README/testing guidance states that `.env` is ignored and live MySQL requires an explicit shell opt-in plus exported credentials. Full pytest passes with the same three MySQL integration skips. | Keep `.env` disabled in default pytest. Any future live service/database fixture must have its own explicit opt-in gate and must not enter default collection accidentally. |
| DRR-2026-040 | Implemented | Low | 2026-08-04 | Unreachable configuration helper | `_parse_table_allowlist()` in `mcp_sql_server.py` was never called; live allowlist parsing already belonged to `db_adapter.py`. Keeping both paths invited edits to the wrong function. | Yes | Remove the dead helper and its divergent logging so allowlist parsing has one owner; also restore the missing trailing newline in `pytest.ini`. | Implemented 2026-08-10. Runtime policy still derives `ALLOWED_TABLES` from the resolved connection policy. SQL-policy and multi-connection regressions remain the evidence. | Keep allowlist parsing centralized in `db_adapter.py`. |
| DRR-2026-041 | Implemented | Medium | 2026-08-04 | Weak mutation regression assertions | The secret-rotation test stopped before rotation/assertion, one sanitization assertion was tautological, and no end-to-end test covered terminal token consumption when `adapter.execute_write()` raises. These weaknesses reduced confidence in the replay boundary. | Test-only hardening | Complete the reload with a different signing secret and assert rejection/no write; replace the tautology with a direct non-disclosure assertion; inject a database write failure and assert the already-consumed token cannot be reused. | Implemented in `tests/test_mutation_multi_connection_v36_design.py` and `tests/test_mutation_skills.py`. Evidence now includes secret rotation, non-disclosure, terminal database failure, store-level atomic consume, and two concurrent full-tool execute calls producing exactly one database write. | Keep these regressions mandatory evidence for future preview-token store or execution-path changes. |
| DRR-2026-042 | Implemented | Low | 2026-08-04 | Stale v3.5-era qualifiers after v3.6 | Several documents described the v3.5 default-connection compromise as current after v3.6 introduced explicit named-write policy. | Yes | Qualify default-only behavior with "when `SKILLS_ALLOW_MUTATION_CONNECTIONS` is omitted", align the Agent tool table and best-effort audit wording, and separate v3.5→v3.6 from v3.6→v3.6.1 history. | Implemented 2026-08-10 across the client guide, README, Skills guide, Agent guide, design document, and release notes. The last unconditional "limited to the default connection in v3.5" wording was corrected. | Keep version deltas separated in future maintenance releases instead of attaching baseline v3.6 features to v3.6.x fixes. |
| DRR-2026-043 | Accepted | Medium | 2026-08-04 | Read allowlist fail-open versus write allowlist fail-closed | An empty or omitted `DB_<ID>_ALLOWED_TABLES` means every visible table is readable, while an empty or omitted `DB_<ID>_MUTATION_SKILLS` denies all writes. Both defaults are intentional but point in opposite directions. | Documentation only | Keep the read default for backward compatibility and writes deny-by-default; state the asymmetry together and recommend a concrete production read allowlist. | Documented 2026-08-10 in both env examples and both README configuration/security sections. The behavior itself remains an accepted compatibility compromise. | Keep the warning beside both policy examples; reconsider the read default only in a breaking release. |
| DRR-2026-044 | Accepted | Low | 2026-08-04 | Preview-token store capacity self-denial | `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES` bounds outstanding unexpired tokens per process and fails closed when full rather than evicting valid entries. Repeated unused previews can fill the store until expiry; lazy expiry scans the bounded dictionary under a lock. | Partial hardening | Keep fail-closed capacity and lazy cleanup. Bound TTL to `1-86400` seconds and capacity to `1-100000`; invalid values fall back to `300` and `10000`. Do not add a heap/background cleanup service without measured load. | Defaults remain TTL 300 and capacity 10000. Tests cover no eviction, expiry recovery, and both configuration upper bounds. The capacity maximum is a misconfiguration guardrail, not a validated throughput claim; no per-client rate limiting exists. | Untrusted or multi-user HTTP mutation is unsupported in v3.6.1. Revisit quotas, rate limiting, and an indexed expiry structure only with a concrete remote/high-throughput requirement. |
| DRR-2026-045 | Implemented | Medium | 2026-08-08 | Shared token backend versus actual deployment scope | A shared backend could coordinate preview/execute across workers and replicas, but a production remote service also needs authentication, transport security, observability, replica-consistent configuration, and database governance. Adding only a token store would overstate deployment readiness. | Yes | Keep the bounded process-local store and recommend client-owned stdio. Conditional HTTP mutation is limited to one process in a trusted private boundary; multi-user authenticated HTTP and shared mutation replicas are outside v3.6.1. Scale reads only through a separate read-only endpoint/profile/pool. | Implemented: active documentation states the same-process boundary, accepted continuity losses, lack of runtime worker-count enforcement, and the absence of a multi-user HTTP security design. | Revisit shared state only with a concrete remote mutation requirement and a complete deployment profile. Never use stateless HMAC-only validation. |
| DRR-2026-046 | Accepted | Low | 2026-08-10 | Status-only optimistic lock and ABA changes | `update-order-status` binds and compares the displayed `status`. An external writer could theoretically change `pending -> X -> pending` within the token lifetime, leaving the same status at execute time while an intermediate change went undetected. | No v3.6.1 code change | The bundled state machine is acyclic and cannot restore a prior status through this Skill. Adding a revision/`updated_at` predicate would require a business-schema contract and cross-database migration for a path not currently exposed by the bundled Skill. | Accepted as a narrow external-writer limitation. Current protection still prevents writes whenever the execute-time status differs from the displayed preview status. | Bind a stable row revision/version when a real target schema provides one or when external writers can legitimately restore prior states. Do not invent a generic timestamp contract in the framework. |
| DRR-2026-047 | Implemented | Low | 2026-08-10 | Unreachable named SQLite path alias | The named SQLite branch contained a fallback to undocumented `DB_<ID>_DATABASE_PATH`, but the preceding canonical `DB_<ID>_SQLITE_DATABASE_PATH` lookup always supplied a string default, so the `None` guard and alias lookup were unreachable. Treating the alias as supported would create a duplicate configuration surface and precedence rules without compatibility benefit. | Yes | Remove the dead fallback. Keep `DB_<ID>_SQLITE_DATABASE_PATH` as the only named SQLite path setting; do not document, activate, or add test-fixture handling for the unreachable alias. | Implemented 2026-08-10 in `db_adapter.py`. Existing named SQLite and legacy isolation tests pass with no runtime behavior change. | Keep named connection settings explicit and canonical. If test-environment suffix drift becomes a real problem, isolate the project-owned `DB_*` namespace rather than legitimizing dead aliases. |

## Initial v3.4.3 Review Batch Status

1. V343-001 implemented as the only runtime behavior change in this group.
2. V343-002 implemented as wording/message cleanup only; adapter-level query
   streaming remains deferred.
3. V343-003 through V343-005 implemented as documentation/tool-description
   cleanup.
4. V343-006 through V343-008 were intentionally closed as documentation and
   operations guidance rather than runtime controls.

## Explicit Non-Goals For Now

- Generic `query(limit, offset)` or cursor-token pagination for arbitrary SQL.
- In-process p50/p95 aggregation or a model-visible stats tool/resource.
- Blanket strict output schemas for all base tools.
- Session schema cache without invalidation.
- `db://schema` resource before a concrete client need exists.
- In-process log rotation/retention before deployment requirements are concrete.
- Runtime raw-SQL echo switches or audit redaction policy engines without a
   privacy-sensitive deployment requirement.
- New runtime-generated human documentation artifacts on startup; existing
   `skills/SKILLS.md` startup generation is tracked in DRR-2026-001.
- New display-only environment defaults or low-level tuning knobs without a
   concrete client/deployment requirement.
- Additional import-time filesystem side effects or configuration reads that
   make tests require module reloads without a concrete startup need.
- Source-string regression tests for behavior that can be tested through
   public helpers or MCP tool calls.
- MySQL `SELECT` file read/write features (`OUTFILE`, `DUMPFILE`, `LOAD_FILE`)
   in the free-form `query(sql)` tool.
- Relying on regexes that only match unquoted or whitespace-separated system
   schema and SHOW forms when the SQL dialect treats comments/quotes as syntax.
- Local DB error logs that include SQLAlchemy parameter values.
- Claims that tests fail in CI unless the repository actually contains a CI
   workflow or the wording explicitly says local/default pytest.
- Hand-built SQLAlchemy database URLs from raw credential strings when a
   structured URL API is available.
- Treating a string-prefix path check as sufficient containment for trusted
   local Skills code.
- Claiming query skill SQL receives the same extended safety checks as the
   free-form query tool until validation is shared.
- Treating the lightweight Skills params schema as full JSON Schema or adding
   new param types without explicit validation tests.
- Treating best-effort audit writes as complete, fail-closed mutation audit.
- Running default pytest against live databases or printing sampled row data
   without an explicit integration-test opt-in.
- Treating lower-bound or unpinned dependency installs as reproducible release
   inputs.
- Relying on SELECT-oriented MySQL timeout settings as mutation/lock-wait
   protection without version-specific proof.
- Accepting arbitrary model-supplied DSNs or silently falling back to the default
   connection when `connection_id` is unknown.
- Letting Skills availability be computed for one target connection while
   execution uses another.
- Enabling multi-connection mutation writes before per-connection write policy,
   preview/execute target binding, and audit semantics are designed.
- Committing data changes to tracked sample fixture databases as a side effect
   of live write testing.
- Model-facing server instructions or tool descriptions that claim a narrower
   capability than the tool surface actually registered under the current
   configuration.
- Keeping a second, non-binding write path for a state-sensitive mutation Skill
   once preview-state binding is required.
- Regression assertions whose failure condition cannot be reached, or tests that
   set up a scenario without asserting its outcome.
- Describing the default pytest suite as hermetic while it still reads live
   database configuration from the developer's `.env`.

## Update Procedure

When a row is implemented, rejected, or re-scoped:

1. Update `Status`, `Risk level` if impact changed, `Plan?`,
   `Modification logic`, `Current result`, and `Last reviewed`.
2. For behavior changes, add or update tests and name the test file in the row.
3. For documentation-only changes, record the edited docs and why no runtime
   test was needed.
4. For policy rows, record the chosen compatibility/security compromise before
   changing runtime behavior.
5. For new rows, fill `Date first registered` with the date the risk first
   entered this register, not the latest review date.
6. Keep historical rows instead of deleting them unless the row was created in
   error; mark old rows as `Accepted`, `Deferred`, or `Not Planned`.

## Review Checklist

- Does the change add a model-visible tool, resource, prompt, schema, or meta
  field?
- Does it log SQL, params, rows, user identifiers, credentials, or operational
  usage patterns?
- Does it add in-memory or session state that can grow without bounds or stale?
- Does startup/import write generated human documentation or maintenance artifacts?
- Does startup/import create files, attach handlers, or freeze environment
   configuration before validation?
- Is a public internal boundary relying on upstream validation instead of doing
   its own minimal validation/quoting?
- Can a top-level read-only SQL type still perform file I/O, expose server files,
   or contain nested DML forms in the active SQL dialect?
- Do docs claim CI, production, or automated enforcement that the repository does
   not actually provide?
- Are database URLs and DB error logs constructed in ways that can expose or
   misparse credentials/parameters?
- Do logs contain raw SQL, bound params, secrets, or SQLAlchemy parameter dumps
   before the client-facing error is sanitized?
- Do Skills paths, frontmatter fields, mutation classes, and custom parameter
   schemas fail closed at the loader boundary?
- Do query skills and free-form query tools share the same SQL safety policy, or
   are their claims documented separately?
- Does default pytest remain hermetic, or can it contact a live database and
   print data unless explicitly opted into integration mode?
- Are dependency versions reproducible for the behavior and APIs being claimed?
- Is timeout wording backed by the actual database statement type being
   executed, especially for writes and lock waits?
- Does it make an expensive database operation look like lightweight metadata?
- Does it resolve `ConnectionContext` before policy, readiness, helper SQL,
   execution, metadata, audit, and telemetry?
- Do Skills listing/detail/execution use the same target connection and fail
   closed on unknown connection ids?
- Does any new log/meta/audit field expose connection strings, hosts, users,
   passwords, SQLite paths, SQL params, or returned rows?
- Does it claim validation, completeness, exactness, or ordering that the code
  cannot guarantee?
- Does the test suite cover both the intended path and the rejected failure mode?
- Does the diff modify a tracked binary or sample fixture as a side effect of
  live testing rather than as an intentional change?
- Do the server `instructions` and tool descriptions match the tool surface that
  is actually registered under the current feature switches?
- Does the default test suite isolate every configuration variable the code
  reads at import time, not just the ones that previously broke a fixture?
- Can every new assertion actually fail, and does every new test assert the
  behavior its name claims to cover?
