# Design Risk Register

English | [中文](DESIGN_RISK_REGISTER_ZH.md)

Date opened: 2026-05-24
Last reviewed: 2026-08-04

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
boundaries but recorded ten new rows below. The highest-impact ones are the
sample-database fixture drift left by live mutation testing (DRR-2026-035), the
server-level `instructions` string that still advertises read-only access while
mutation tools can write (DRR-2026-036), and the incomplete default pytest
environment isolation that partially reopens DRR-2026-023 (DRR-2026-039). The
review also verified that no runtime behavior contradicts the implemented v3.5
and v3.6 rows, and that documentation drift is limited to stale v3.5-era
qualifiers tracked in DRR-2026-042.

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
| DRR-2026-003 | Deferred | Low | 2026-05-26 | Skills availability helpers | `_skill_executable_state()` and `_skill_is_executable()` wrap `_skill_availability_state()` but are not called. Small unused wrappers make the availability logic look more like a policy engine than it is. | Low-priority code cleanup | Delete unused wrappers when touching the Skills availability code; keep `_skill_availability_state()` as the single source of truth. | Documented 2026-05-26 in this register; no runtime change yet. Re-checked 2026-08-04: still unreferenced except by each other, and the v3.5 change set added a `connection` parameter to both instead of removing them, so the cleanup trigger was met but not acted on. | Delete both wrappers in the next Skills-availability edit and run `tests/test_skills_disclosure.py` plus `tests/test_multi_connection_v35.py`. |
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
| DRR-2026-022 | Implemented | High | 2026-05-27 | Skills audit completeness overclaim | `AuditLogger.log()` is best-effort and audit write failures or mutation validation failures can still leave no JSONL record. Older docs/config wording overstated completeness and could be read as fail-closed audit behavior. | Yes | Kept audit as best-effort observability instead of a fail-closed transaction control. `AuditLogger.log()` now returns write success/failure without raising; normal query/mutation tool results report `audit_logged` from the actual audit path, while validation failures explicitly return `audit_logged=false`. Docs now caveat audit write failures and validation failures. | Implemented 2026-05-29 in `skills/_lib/audit.py`, `skills/_lib/mutation_base.py`, `mcp_sql_server.py`, README/docs/Skills safety docs, and tests covering write failure, mutation success metadata, and validation-failure metadata. | If compliance ever requires guaranteed audit, design a separate transactional/outbox or database-backed audit mechanism; do not treat the JSONL best-effort file as fail-closed evidence. |
| DRR-2026-023 | Implemented | High | 2026-05-27 | Default pytest live database boundary | `test_mcp_client.py::test_mcp_server` was collected by default pytest. When the configured database was reachable, it started the MCP server against the current `.env`, listed tables, counted the first table, described it, sampled rows, and could execute a query skill. This could touch a live or production-like database and print sample data into captured test output or failure logs. | Yes | Made the default pytest suite hermetic by adding `pytest.ini` with `testpaths = tests`. Root-level MCP smoke checks remain explicit script entrypoints, and docs now warn to run them only against safe development or fixture databases. | Implemented 2026-05-28 in `pytest.ini`, `README.md`, `README_ZH.md`, and `TEST_MCP_CLIENT_GUIDE.md`; `python -m pytest --collect-only -q` now excludes root-level smoke scripts by default. | Keep future live DB smoke checks outside default collection unless they have an explicit opt-in gate and non-sensitive output policy. |
| DRR-2026-024 | Deferred | Medium | 2026-05-27 | Dependency reproducibility | `requirements.txt` uses mostly unpinned or lower-bound-only dependencies, including FastMCP and SQLAlchemy APIs that this project uses directly. Without a lockfile, constraints file, or CI matrix, future installs can silently pick versions with behavior or compatibility changes, weakening claims that local/default tests represent release behavior. Dry-run evidence also shows the optional AutoGen chain is the current conflict surface, not the core server runtime path. | Packaging/workflow cleanup candidate, not yet implemented. AutoGen examples are not the program's mainline runtime. | If this is fixed later, split runtime/dev/optional AutoGen dependencies first, then add constraints or a documented tested version set for the paths the repo actually supports. Avoid presenting unconstrained installs as reproducible release inputs. | Documented 2026-05-27 after config/dependency review. On 2026-05-29, `.venv` `pip check` still reported `autogen-core 0.7.5` requiring `protobuf~=5.29.3` while `protobuf 6.33.5` was installed. `pip install --dry-run --ignore-installed -r requirements.txt` resolved a clean set with `protobuf 5.29.6`; core-runtime-only dry-run resolved without `protobuf`; AutoGen-only dry-run pulled `protobuf 5.29.6`. In the existing `.venv`, `pip install --dry-run -r requirements.txt` would only install/downgrade `protobuf 5.29.6`. No dependency files or environment packages were changed; reports were written under `/tmp`. | Keep this deferred unless installation/docs are edited. Do not let optional AutoGen example dependencies define core runtime reproducibility claims. |
| DRR-2026-025 | Implemented | High | 2026-05-27 | MySQL mutation timeout semantics | `MySQLAdapter.execute_write()` used `MAX_EXECUTION_TIME`, but MySQL documents this mechanism as SELECT/read-query oriented. Controlled MySQL validation confirmed the gap: `SELECT SLEEP(2)` under `timeout=1` stopped at about 1.079s, while `UPDATE ... SLEEP(2)` still committed after about 2.171s. | Yes | Removed write-path `MAX_EXECUTION_TIME`. MySQL `execute_write()` now sets session `innodb_lock_wait_timeout = max(1, timeout_seconds)` before the mutation and fails closed if that guard cannot be configured. Documentation now distinguishes read-query timeout, InnoDB row-lock wait timeout, PyMySQL socket timeouts, and deployment-side DML controls. | Implemented 2026-05-29 in `db_adapter.py`, `tests/test_db_adapter.py`, README/docs, and Skills safety docs. Controlled proof used database `trade_data_analysis`: old write path ignored `timeout=1`; a separate lock-wait scenario with `innodb_lock_wait_timeout=2` raised OperationalError 1205 after about 3.236s. | Remaining boundary: this is not a full wall-clock statement timeout for all MySQL DML CPU/IO work. Keep driver read/write timeouts and deployment-side statement controls in scope if production requires a hard mutation execution limit. |
| DRR-2026-026 | Implemented | High | 2026-05-30 | Multi-connection policy/execution cross-wire | Runtime multi-database support could resolve policy, quoting/schema helpers, adapter execution, metadata, audit, or telemetry from different connections, causing a tool to display or validate against one database while executing against another. | Yes | Introduced `ConnectionContext` and resolved it before policy, schema readiness, dialect-specific helper SQL, execution, metadata, audit, and telemetry. Internal helper queries in `sample()` and exact table counts execute directly on the selected adapter rather than via the legacy default execution wrapper. | Implemented 2026-05-30 in `db_adapter.py`, `sql_safety_checker.py`, and `mcp_sql_server.py`; `tests/test_multi_connection_v35.py` covers same-connection policy/execution and fail-closed unknown ids. | Keep new tools on the resolve-first pattern; add regression tests whenever a helper path quotes identifiers or executes internal SQL. |
| DRR-2026-027 | Implemented | High | 2026-05-30 | Skills display/execution mismatch | Skills discovery could show a skill as executable for one database type or schema while execution used another adapter, especially with named connections and per-connection allowlists. | Yes | Made `list_skills`, `get_skill_detail`, and `execute_query_skill` accept optional `connection_id` and evaluate DB compatibility, schema readiness, allowlists, metadata, optional audit, and telemetry against the same target connection. `SkillMetadata.databases` remains a DB type compatibility field, not a connection-id allowlist. | Implemented 2026-05-30 in `mcp_sql_server.py`; `tests/test_multi_connection_v35.py`, `tests/test_skills_disclosure.py`, and docs cover target-connection availability/execution consistency. | Keep `available_only` documented as discovery filtering, not authorization; execution checks remain mandatory. |
| DRR-2026-028 | Implemented | Medium | 2026-05-30 | Adapter registry lifecycle and resource bounds | Multiple named connections require multiple long-lived SQLAlchemy Engines. A registry can leak resources if reset/lifecycle behavior is unclear, and can complicate tests that reload environment state. | Yes | Added a process-local lazy adapter cache keyed by configured `connection_id`, plus `reset_adapter(connection_id=None)` to close one or all adapters in tests/reconfiguration. Kept connection definitions server-configured and import-time parsed for compatibility rather than adding dynamic per-request DSNs. | Implemented 2026-05-30 in `db_adapter.py`; `tests/test_db_adapter.py` and `tests/test_multi_connection_v35.py` cover registry behavior. | Deferred: no LRU/upper bound/credential refresh yet. Revisit if deployments configure many connections or require runtime config reload. |
| DRR-2026-029 | Implemented | Medium | 2026-05-30 | Connection identity in logs and metadata | Operators need to distinguish which configured connection handled a tool call, but exposing connection internals in `ToolResult.meta`, telemetry, audit, or structured payload display fields would leak sensitive DB details. | Yes | Added safe `connection_id` alias and actual `db_type` to result metadata, optional telemetry, and Skills audit. `list_connections()` returns aliases and policy summaries only. Public SQLite `database_name` display fields use `sqlite:<connection_id>` instead of file paths. DSNs, hosts, usernames, passwords, SQLite paths, SQL params, and returned rows remain excluded. | Implemented 2026-05-30 in `mcp_sql_server.py`, `skills/_lib/audit.py`, `skills/_lib/mutation_base.py`, docs, and tests; follow-up tests cover SQLite path non-exposure in `check_connection()` and `list_tables()`. | Re-check whenever new metadata/audit/payload fields are added; do not add connection internals without a privacy review. |
| DRR-2026-030 | Implemented | High | 2026-05-30 | Multi-connection mutation writes | Allowing mutation Skills to choose arbitrary configured connections requires per-connection write permissions, preview/execute target binding, audit semantics, and stronger operational guidance for SQLite file locks and MySQL write timeouts. | Yes | Require a global mutation target allowlist, per-connection write switch, per-connection skill allowlist, and an HMAC preview token bound to skill/version/params/connection/db type/expiry. Keep omitted global routing policy default-connection only. | Implemented in `db_adapter.py` and `mcp_sql_server.py`; discovery and execution share policy checks. `tests/test_mutation_multi_connection_v36_design.py` covers routing, token binding, target isolation, denial layers, exact expiry, tampering, skill-version changes, restart behavior, and full-token non-exposure; adapter tests cover config parsing and legacy isolation. | Replay and preview-state hardening are implemented in DRR-2026-034. Continue documenting SQLite lock and MySQL DML timeout boundaries for every authorized write target. |
| DRR-2026-031 | Implemented | High | 2026-05-30 | Quoted identifier allowlist bypass | The MCP table extractor used by allowlist checks did not handle common quoted identifiers consistently. Forms such as `FROM "forbidden"`, `FROM [forbidden]`, or `FROM main."forbidden"` could avoid or misdirect table comparison even though they referenced a disallowed table. | Yes | Added identifier normalization for backticks, double quotes, square brackets, and schema-qualified references before comparing table names with the target connection allowlist. Kept this as a focused extractor hardening rather than introducing a full SQL parser. | Implemented 2026-05-30 in `mcp_sql_server.py`; `tests/test_sql_policy.py` covers quoted and schema-qualified deny cases plus allowed quoted tables. | Keep future table-reference parsing changes on the shared policy path and add dialect examples before broadening syntax support. |
| DRR-2026-032 | Implemented | Medium | 2026-05-30 | Legacy named-env leakage | Local multi-connection `.env` values such as `DB_DEFAULT_*` and `DEFAULT_DB_CONNECTION` could affect legacy single-connection mode when `DB_CONNECTIONS` was unset or empty. This could break backward compatibility or make a legacy startup fail because a named default was not present. | Yes | Treat `DB_CONNECTIONS` as the sole feature gate for named connections. In legacy mode, ignore both `DB_<ID>_*` variables and `DEFAULT_DB_CONNECTION`; legacy `DB_TYPE` / `SQLITE_DATABASE_PATH` remain authoritative. | Implemented 2026-05-30 in `db_adapter.py`, `.env.example`, README/docs, and tests; `tests/test_db_adapter.py` covers ignored `DB_DEFAULT_*` and ignored default selection in legacy mode. | Preserve this gate when adding new per-connection settings; do not let named variables affect legacy mode without an explicit migration decision. |
| DRR-2026-033 | Implemented | Medium | 2026-05-30 | Compatibility helper resolve order | The standalone `sql_safety_checker.execute_sql(..., connection_id=...)` helper could run SQL safety checks before resolving the target connection. Unknown ids should fail closed before any target-specific policy or execution path is considered. | Yes | Resolve `connection_id` with `get_connection_config()` before `is_sql_safe()` and adapter execution, matching the MCP resolve-first invariant. | Implemented 2026-05-30 in `sql_safety_checker.py`; `tests/test_multi_connection_v35.py` covers unknown `connection_id` returning a connection error before SQL policy. | Keep compatibility helpers aligned with MCP tool ordering whenever connection-aware policy expands. |
| DRR-2026-034 | Implemented | High | 2026-05-30 | Preview-token replay and reviewed-state drift | A valid HMAC token could be replayed before expiry, and the bundled mutation previously re-read current state during execute instead of locking against the state shown in preview. Optimistic locking alone was not a generic replay or reviewed-state boundary. | Yes | Add random `jti`, bind a bounded execution-state hash, register digest/expiry/canonical binding in a bounded locked memory store, and atomically consume before dynamic validation/write. Consumption is terminal after later failures. Require state-sensitive Skills to explicitly handle non-empty bindings. | Implemented in `mcp_sql_server.py`, `MutationBase`, and `update-order-status`. Tests cover unique issuance, sequential/concurrent replay, capacity and lazy expiry, restart invalidation, static-rejection non-consumption, terminal validation/write/audit outcomes, state drift, and rejection of ignored bindings. | Current memory backend is correct for single-process stdio/single-worker deployments. Multi-worker deployment remains unsupported until a shared atomic backend exists; do not add stateless fallback. |
| DRR-2026-035 | Deferred | Low | 2026-08-04 | Sample database fixture drift | Live v3.6 mutation smoke testing left a data change in the tracked `sample_data/demo.db`: order `id=4` moved from `pending` to `confirmed`. All tables and row counts are otherwise identical to `HEAD`, and the temporary order `990001` was removed. The live-test record documents only the `990001` cleanup, so the residual change looks intentional when it is not. | Maintainer decision pending | Sample fixtures should have a deterministic starting state so bundled demo Skills, `scripts/setup_demo_db.py`, and `profiles: [demo]` examples stay reproducible. Either revert the file or adopt the new state explicitly and say so in the fixture documentation. | Detected 2026-08-04 by comparing `git show HEAD:sample_data/demo.db` with the working tree. No file was changed by the review. | Decide before committing whether to revert `sample_data/demo.db` or record `confirmed` as the new documented baseline. Prefer disposable fixture databases over the tracked sample file for future live write smoke tests. |
| DRR-2026-036 | Deferred | Medium | 2026-08-04 | Server instructions overclaim read-only | The FastMCP server-level `instructions` string still says "Database query assistant with READ-ONLY access" and mentions only `query`, `describe_table`, and `get_full_schema`. When `ENABLE_SKILLS=1` and `SKILLS_ALLOW_MUTATIONS=1`, `execute_mutation_skill` performs real writes, and every core tool accepts `connection_id`. This is model-facing text, so an inaccurate capability claim can bias tool selection and misrepresent the server's safety profile. | Documentation/runtime wording fix, not yet implemented | Make `instructions` describe the actual registered surface: read-only core tools by default, optional Skills, optional controlled writes behind the preview-token protocol, and configured `connection_id` routing. Keep it short, because server instructions consume model context. | Documented 2026-08-04; no runtime change yet. FastMCP and MCP guidance both treat tool/server descriptions as selection inputs that should accurately represent behavior. | Rewrite `instructions` when the mutation surface changes again, and add a test that fails if mutation tools are registered while the instructions still claim read-only access. |
| DRR-2026-037 | Deferred | Medium | 2026-08-04 | Mutation dual execution paths | `MutationBase` requires a concrete `execute()`, so `update-order-status` keeps both `execute()` and `execute_with_binding()`. In the MCP path `run_execute()` always routes through the binding, and `build_execution_binding()` never returns empty, so `execute()` is unreachable there. It nonetheless remains a public, callable path that re-reads current status and writes without preview-state binding, which is exactly the TOCTOU behavior DRR-2026-034 removed. | Code cleanup, not yet implemented | For state-sensitive Skills, keep one authoritative write path. Either have `execute()` raise a `ToolError` directing callers to the binding path, or restructure the ABC so binding-aware Skills do not have to keep a weaker sibling implementation. | Documented 2026-08-04; no runtime change yet. Current behavior is not exploitable through MCP because the tool layer never calls `execute()` directly. | Decide the ABC contract before adding a second state-sensitive mutation Skill, and add a test asserting the unbound path cannot be reached from the tool layer. |
| DRR-2026-038 | Deferred | Medium | 2026-08-04 | Preview binding provenance and preview-failure tokens | `build_execution_binding()` in `update-order-status` reads `validation["current_status"]`, but `preview()` performs its own separate `SELECT` and displays the status from that second read. Docs and DRR-2026-034 describe the binding as "the state shown during preview". If the row changes between `validate()` and `preview()`, the displayed status and the bound status differ. In the narrower case where the row disappears between the two calls, `preview()` returns `{"preview_sql": "N/A", "error": ...}` while a token is still issued and the payload reports `success=true`. | Code and documentation correction, not yet implemented | Either build the binding from the same read that produced the displayed preview, or reword the guarantee to "state validated immediately before preview". Additionally, do not issue a preview token when the preview result reports an error. | Documented 2026-08-04; no runtime change yet. The window is narrow and the optimistic lock still prevents overwriting an unexpected state, so this is a correctness/claim-precision issue rather than a proven unsafe write. | Add regression tests that mutate the row between `validate()` and `preview()` and assert both the binding source and the no-token-on-failed-preview behavior. |
| DRR-2026-039 | Deferred | High | 2026-08-04 | Default pytest environment isolation gap | `tests/conftest.py` clears only `DB_CONNECTIONS` and `SKILLS_ALLOW_MUTATION_CONNECTIONS` at import time, but `db_adapter.py` calls `load_dotenv()` on import. Legacy `DB_TYPE`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_NAME`, `SQLITE_DATABASE_PATH`, `ALLOW_UNION`, `ALLOWED_TABLES`, and the Skills/telemetry switches still come from the developer's `.env`. The `mysql_adapter` fixture skips only when those legacy variables are missing or the server is unreachable, so a developer using the legacy variable style would run tests against a live MySQL server. This partially reopens DRR-2026-023, whose result claims the default suite is hermetic. | Test isolation fix, not yet implemented | Isolate the full set of configuration variables the code reads, not just the two that previously broke a fixture. Prefer an explicit allow/clear list in `conftest.py` plus an opt-in gate for any live-database fixture. | Documented 2026-08-04; no runtime change yet. The current local run skips MySQL only because this developer's `.env` migrated to `DB_MYSQL_*`, which makes hermeticity accidental rather than enforced. | Extend `conftest.py` isolation, add an explicit integration opt-in marker for `mysql_adapter`, and correct the DRR-2026-023 wording once the suite is hermetic by construction. |
| DRR-2026-040 | Deferred | Low | 2026-08-04 | Unreachable configuration helper | `_parse_table_allowlist()` in `mcp_sql_server.py` is defined but never called. The module-level `ALLOWED_TABLES` value is now derived from `_DEFAULT_CONNECTION_POLICY.allowed_tables`, so the legacy parser and its startup log lines are dead. Keeping a second, divergent allowlist parser near the live policy path invites future edits to the wrong function. | Low-priority code cleanup | Delete `_parse_table_allowlist()` together with the DRR-2026-003 wrappers so allowlist parsing has one owner in `db_adapter.py`. `pytest.ini` also currently lacks a trailing newline. | Documented 2026-08-04; no runtime change yet. | Remove in the next `mcp_sql_server.py` cleanup pass and re-run `tests/test_sql_policy.py` plus `tests/test_multi_connection_v35.py`. |
| DRR-2026-041 | Deferred | Medium | 2026-08-04 | Weak mutation regression assertions | Three test weaknesses reduce the signal of the v3.6 suite. The signing-secret rotation case in `tests/test_mutation_multi_connection_v36_design.py` obtains a preview and then returns without a second import, secret change, or assertion, so it passes even if rotation is broken. `tests/test_mutation_skills.py` contains `assert "sqlalchemy" not in error_msg.lower() or "Error:" in error_msg`, whose right operand is already guaranteed by the preceding assertion, making the sanitization check tautological. No test monkeypatches `adapter.execute_write()` to raise, so the terminal-token-consumption branch for database write failures is untested end to end. | Test hardening, not yet implemented | Assertions must be able to fail. Replace the tautology with a direct check, complete the rotation scenario, and add a write-failure case that asserts the token is consumed and the sanitized error mentions re-previewing. | Documented 2026-08-04; no runtime change yet. Other v3.6 branches (expiry, capacity, tampering, cross-connection, replay) do have real coverage. | Fix the three cases before relying on the v3.6 suite as evidence for a shared-store or multi-worker token backend. |
| DRR-2026-042 | Deferred | Low | 2026-08-04 | Stale v3.5-era qualifiers after v3.6 | Several documents still describe the v3.5 compromise as current. `MCP_AGENTS_SKILLS_DESIGN.md` security row 17 says mutation Skills execute only on the default connection "until multi-connection write policy is explicitly designed", which v3.6 implemented. `README.md` lists "v3.5 default-only mutation scope" as an unconditional availability filter reason. `TEST_MCP_CLIENT_GUIDE.md` is headed "(v3.5)" while its body documents the v3.6 `preview_token` protocol. `agent_examples/AGENT_DEVELOPMENT_ZH.md` omits `list_connections` and `get_skill_detail` and states that `execute_mutation_skill` needs only `SKILLS_ALLOW_MUTATIONS=1`. A comment above `SKILLS_AUDIT_QUERIES` still says mutation Skills are "audited unconditionally", which contradicts the best-effort semantics recorded in DRR-2026-022. | Documentation cleanup | Qualify every default-only statement with "when `SKILLS_ALLOW_MUTATION_CONNECTIONS` is omitted", refresh the guide header and Agent tool table, and align the audit comment with best-effort wording. | Documented 2026-08-04. Verified separately that env var names/defaults, tool-count claims, EN/ZH register parity, and relative markdown links are otherwise consistent with the code. | Sweep these files in the next documentation pass and re-check tool-registration conditions against `mcp_sql_server.py`. |
| DRR-2026-043 | Accepted | Medium | 2026-08-04 | Read allowlist fail-open versus write allowlist fail-closed | An empty or omitted `DB_<ID>_ALLOWED_TABLES` means every visible table is readable, while an empty or omitted `DB_<ID>_MUTATION_SKILLS` denies all writes. Both defaults are intentional, but they point in opposite directions and are documented in separate places, so an operator can reasonably assume that leaving a policy blank is always the restrictive choice. | Documentation only | Keep the read default for backward compatibility with the legacy `ALLOWED_TABLES` semantics, and keep writes deny-by-default. State the asymmetry in one place instead of leaving it implicit across two config sections. | Accepted 2026-08-04 as an intentional compatibility compromise. | Add an explicit note in `.env.example`, `.env.example_ZH`, and the README security section; recommend a concrete read allowlist for production deployments. |
| DRR-2026-044 | Accepted | Low | 2026-08-04 | Preview-token store capacity self-denial | `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES` bounds outstanding unexpired tokens and fails closed when full rather than evicting valid entries. A client that previews repeatedly without executing can therefore fill the store and block legitimate previews until entries expire, up to `MUTATION_PREVIEW_TOKEN_TTL_SECONDS`. | No behavior change | Failing closed is the correct trade-off: evicting a reviewed preview to make room for a new one would silently invalidate approved work. Availability of the preview path is a lower risk than losing replay protection. | Accepted 2026-08-04. Default capacity 10000 with a 300-second TTL makes this impractical to trigger accidentally. The server still implements no per-client rate limiting, which MCP lists as a server responsibility (`skills/SAFETY.md` §13). | Revisit together with rate limiting if the server is ever exposed over HTTP to untrusted callers. |

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
