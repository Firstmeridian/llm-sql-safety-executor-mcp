# Design Risk Register

English | [中文](DESIGN_RISK_REGISTER_ZH.md)

Date opened: 2026-05-24  
Last reviewed: 2026-05-26  
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

## Register

| ID | Status | Area | Risk or concern | Plan? | Modification logic | Current result | Next action |
|---|---|---|---|---|---|---|---|
| V343-001 | Implemented | SQLite row estimates | Metadata discovery previously upgraded from a 10,000-row sample to full `COUNT(*)` on larger SQLite tables. | Yes | Prefer `sqlite_stat1`; when the sample cap is reached, return the cap as a lower-bound estimate. Keep exact counts opt-in. | Completed 2026-05-24 in `db_adapter.py`; tests added in `tests/test_db_adapter.py`; docs updated. | Monitor user expectations around lower-bound estimates; recommend `ANALYZE` or explicit count when precision is required. |
| V343-002 | Implemented | Query result truncation | `query()` and `execute_query_skill()` fetch full adapter results before truncating returned payload. | Documentation only for v3.4.3 | Clarify that truncation limits returned payload only; users should add `WHERE`/`LIMIT`/`ORDER BY` to limit database work and stabilize order. | Tool messages and docs updated. Adapter-level streaming remains deferred. | Revisit `fetchmany()` or streaming only with compatibility tests. |
| V343-003 | Implemented | Tool descriptions | `list_tables()` and `get_full_schema()` overclaimed by saying all/complete despite allowlist and truncation. | Yes | Use visible/truncated wording and clarify returned counts. | Tool-facing descriptions and docs updated. | Keep future tool descriptions precise and conservative. |
| V343-004 | Implemented | Security wording | Some docs overclaimed comprehensive SQL analysis or universal `validate_name()`/`validate_params()` coverage. | Yes | Describe sqlparse as statement-type allowlist plus MCP-layer checks; distinguish Skills validators from base SQL/table validators. | README and design docs updated. | Avoid expanding security claims without matching enforcement. |
| V343-005 | Implemented | Prompt guide | `get_table_summary()` was treated as a default planning step although disabled by default and exact count is opt-in. | Yes | Prefer `describe_table()` estimates; use explicit `COUNT(*)` or `get_table_summary(exact_count=True)` only when precision is required. | Prompt guide updated; no runtime test needed. | Keep prompt examples aligned with default-enabled tools. |
| V343-006 | Policy Required | Raw SQL echo/log visibility | Raw `query(sql)` logs full SQL to context and returns SQL in structured payloads; literals may contain sensitive values. | Undecided | Options: keep echo for transparency, add stronger docs, or add an opt-in `ECHO_SQL_IN_RESULTS=0` control. | Pending. | Decide compatibility/privacy policy before changing payloads. |
| V343-007 | Policy Required | Skills audit parameter logging | Audit records params after length truncation only; no key/value redaction policy. | Undecided | Consider sensitive-key patterns, per-skill redaction metadata, or documented no-secrets-in-params policy. | Pending. | Define audit redaction policy before runtime changes. |
| V343-008 | Operational Decision | Append-only JSONL logs | Audit and telemetry logs are append-only local files without built-in rotation or retention. | Not server logic for v3.4.3 | Prefer external log rotation and retention guidance. Avoid in-process log management until deployment needs are concrete. | Pending docs/ops decision. | Document recommended rotation/retention for production deployments. |
| V343-009 | Accepted | `ToolResult.meta` visibility | `_meta` includes runtime stats and may be surfaced by some clients. | No behavior change | Keep metadata non-sensitive; do not add SQL, params, rows, credentials, or user identities. | Accepted compromise. | Re-check whenever new meta fields are added. |
| V343-010 | Deferred | Base-tool output schemas | Strict output schemas for arbitrary SQL rows would be misleading or too broad. | Not planned as blanket change | Keep schemas only where envelopes are stable. | Deferred intentionally. | Reconsider stable tools individually if needed. |
| V343-011 | Not Planned | Generic SQL pagination params | `limit`, `offset`, `page`, or cursor tokens on arbitrary SQL duplicate SQL semantics and can be wrong without stable ordering. | No | Keep pagination in user SQL; use domain-specific skills if explicit ordering keys exist. | Not implemented. | Do not add generic `query(limit, offset)` without a new design review. |
| V343-012 | Deferred | Telemetry stats tool | In-process p50/p95 aggregation or a model-visible stats tool can expose operational usage patterns and needs bounded state. | Deferred beyond v3.4.3 | Keep telemetry as opt-in JSONL; compute aggregates externally. | Deferred intentionally. | Revisit only with a bounded, non-model-visible design. |
| V343-013 | Deferred | Session schema cache | Session schema caches can stale after DDL and affect safety/readiness decisions. | Deferred beyond v3.4.3 | Keep execution-time checks authoritative. | Deferred intentionally. | Reconsider only with explicit invalidation strategy. |
| V343-014 | Deferred | `db://schema` resource | A schema resource would add a duplicate schema access path and extra model-visible context surface. | Deferred beyond v3.4.3 | Keep explicit `get_full_schema()` for now. | Deferred intentionally. | Revisit only if client resource support becomes a concrete need. |

## Initial v3.4.3 Review Batch Status

1. V343-001 implemented as the only runtime behavior change in this group.
2. V343-002 implemented as wording/message cleanup only; adapter-level query
   streaming remains deferred.
3. V343-003 through V343-005 implemented as documentation/tool-description
   cleanup.
4. V343-006 through V343-008 remain policy or operations decisions.

## Explicit Non-Goals For Now

- Generic `query(limit, offset)` or cursor-token pagination for arbitrary SQL.
- In-process p50/p95 aggregation or a model-visible stats tool/resource.
- Blanket strict output schemas for all base tools.
- Session schema cache without invalidation.
- `db://schema` resource before a concrete client need exists.

## Update Procedure

When a row is implemented, rejected, or re-scoped:

1. Update `Status`, `Plan?`, `Modification logic`, `Current result`, and
   `Last reviewed`.
2. For behavior changes, add or update tests and name the test file in the row.
3. For documentation-only changes, record the edited docs and why no runtime
   test was needed.
4. For policy rows, record the chosen compatibility/security compromise before
   changing runtime behavior.
5. Keep historical rows instead of deleting them unless the row was created in
   error; mark old rows as `Accepted`, `Deferred`, or `Not Planned`.

## Review Checklist

- Does the change add a model-visible tool, resource, prompt, schema, or meta
  field?
- Does it log SQL, params, rows, user identifiers, credentials, or operational
  usage patterns?
- Does it add in-memory or session state that can grow without bounds or stale?
- Does it make an expensive database operation look like lightweight metadata?
- Does it claim validation, completeness, exactness, or ordering that the code
  cannot guarantee?
- Does the test suite cover both the intended path and the rejected failure mode?
