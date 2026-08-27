# MCP SQL Server Refactoring Log

**Date:** December 2, 2025 (Updated: August 28, 2026)
**Author:** Code Refactoring Session

## Overview

This document records the major refactoring changes made to `mcp_sql_server.py` to follow FastMCP best practices and improve the overall design.

---

## Update v3.7.1 - Opaque Preview Handles and Agent Workflow Efficiency (August 28, 2026)

The mutation protocol keeps the public `preview_token` field but replaces the
self-describing HMAC envelope with a random 256-bit opaque bearer handle. The
bounded process-local Store now owns expiry, exact request binding, preview-time
execution state, and atomic conditional consumption. A mismatched execute
request does not consume the valid record; a matching execute consumes it once
before dynamic validation and writes.

Preview responses no longer duplicate `preview_token_expires_in_seconds`, an
execution hint, or the Skill's nested `requires_confirmation` value. The legacy
`MUTATION_PREVIEW_TOKEN_SECRET` input is ignored with a value-free warning.
Existing v3.6-v3.7 entries below remain historical records of the released HMAC
format rather than the current runtime contract.

`get_skill_detail()` now accepts `execution` and `full` projections. Omitting
the field retains the existing full response; the execution projection limits
Agent-facing output to invocation fields, resolved connection/DB type, any
disabled reason, and the next action. Catalog guidance no longer recommends a
detail call after `list_skills(detail_level="full")` or when parameters are
already known.

Connection guidance now distinguishes an exact alias, a uniquely matched DB
type, and a purpose/role that cannot be inferred safely. The global
`sql_assistant` prompt is target-neutral for UNION because it has no
`connection_id` argument: callers inspect `list_connections()` and the raw/query
Skill paths enforce the selected connection's policy. Module-load UNION logs
are explicitly labeled as the default-connection summary, and missing-allowlist
errors refer to the selected connection's policy. The standalone
`sql_safety_checker.execute_sql()` helper remains a compatibility statement-
shape gate, not the full MCP `ALLOW_UNION`/`ALLOWED_TABLES` policy.

After a handle has been consumed, a dynamic-validation exception before
mutation execution explicitly reports that no database write was attempted.
Once mutation execution starts, an exception may leave the write result unknown
and directs the caller to verify current database state before another preview
or mutation. This does not make memory-store consumption and database
commit/response delivery atomic. A durable operation ledger and reconnect
status API remain deferred until a real product workflow requires them.

The 2026-08-28 default suite passed with 466 tests and 3 skipped; the explicit
root legacy smoke passed 2 tests. A restarted configured MCP service also passed
a reversible v3.7.1 opaque-handle mutation flow on 2026-08-26. On 2026-08-28,
a fresh stdio subprocess completed the approval-host flow: literal `APPROVE`
returned exit code 0 with `rowcount=1`, while `NO` returned exit code 3 and did
not call execute. A separate fresh subprocess temporarily enabled UNION only
for `analytics_demo_sqlite`; both a raw query and a Query Skill harness returned
a real two-row UNION there while the default MySQL target remained denied by its
target policy. The configured MySQL was later checked successfully with
read-only `SELECT 1` and `COUNT(*)`; an earlier same-day timeout remains a
negative environment observation. Full timings, payload summaries, and evidence
boundaries are in `RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`.

## Update v3.7.0 - Scoped Skills, Approval Host, and SQL Hardening (August 22, 2026)

v3.7.0 is an incremental Skills release. It adds optional connection binding in
Skill metadata, a portable demo/test reset mutation, an explicit stdio approval
host, and supported-dialect SQL hardening without changing the
v3.6 preview-token format/store, general write protocol, environment-variable
schema, or routing behavior of documented-schema Skills that omit the
new field. Previously ignored unknown/duplicate frontmatter is the intentional
fail-closed compatibility tightening. Release details
are in `RELEASE_NOTES/RELEASE_NOTES_v3_7.md`.

### Optional `connection_ids` frontmatter

`SkillMetadata` now accepts an optional plural list:

```yaml
databases: [mysql]
connection_ids: [orders_primary, orders_reporting]
```

Unknown top-level fields and duplicate YAML mapping keys fail discovery so a
security-relevant typo such as `connections_ids` cannot silently turn a scoped
Skill into an unrestricted one. The singular `connection_id` field is therefore
rejected together with other unsupported fields so metadata is not
mistaken for the per-call routing argument. A declared value must be a non-empty
YAML list of non-empty strings matching `^[a-z][a-z0-9_]{0,63}$` after lowercase
normalization. Normalized duplicates, wildcards, DSNs, paths, and scalars fail
discovery. Values are sorted for deterministic output; order never implies a
default or failover sequence. The loader performs syntax-only validation and
does not add a direct dependency on `db_adapter`; it already reaches runtime
configuration indirectly through the SQL safety module. It therefore locally
mirrors the connection-id regex; future syntax changes
must update both definitions and their tests. Runtime availability uses the
startup connection registry, like the rest of current configuration, so alias
or DB-type changes require a server restart.

The known metadata vocabulary is strict in both name and value. Declared
`enabled`, `idempotent`, and `requires_confirmation` values must be YAML
booleans; `triggers` and `related_skills` must be lists of strings; and
`category` must be a non-empty string. Each parameter schema accepts only
`type`, `required`, `min`, `max`, `enum`, and `description`. Constraint values
must match the declared parameter type, enum must be a non-empty list, and
numeric bounds must be ordered. This completes the repository's lightweight
DSL rather than replacing it with JSON Schema.

Omission is represented by `None` and preserves the prior unrestricted-by-Skill
behavior. A list with one member provides direct binding; multiple members
support reuse. Runtime tool arguments remain singular. When a call omits
`connection_id`, the normal global default is resolved first and then checked;
the server never auto-routes to the only/first metadata member.

The MCP execution paths enforce the first two checks before adapter construction:

```text
target ∈ connection_ids (if declared)
AND target.db_type ∈ databases (if declared)
THEN every existing profile/schema/table/query/mutation policy passes before
query execution or database writes
```

Metadata only restricts—it never creates a connection or grants a read/write
permission. Unconfigured declared aliases remain portable metadata but are
reported unavailable with a startup warning. A configured alias whose DB type
conflicts with `databases` fails closed for that target and emits a startup
error; other valid aliases on the same reusable Skill remain available. This
per-target compromise is intentional: globally disabling the Skill would break
the intersection/reuse model without improving the rejected target's safety.

`list_skills()` and `get_skill_detail()` expose declared/configured/unconfigured
ids, per-target scope state, and type conflicts at summary/full detail. Search
includes declared aliases. `available_only` uses the scope state to reduce model
selection errors but is not authorization; both query and mutation execution
repeat the check. The query and mutation paths share the same resolver so scope
rejection occurs before `get_adapter()`. Mutation policy remains a separate,
additional deny-by-default layer, and preview tokens continue to bind exactly
one resolved connection.

Direct Python calls to `skill_loader` or a Mutation class bypass MCP routing and
must enforce equivalent target policy in the embedding application. Built-in
Skills contain commented alias examples only; v3.7 does not silently bind demo
Skills to deployment-specific names. Documentation recommends semantic aliases
such as `orders_primary`/`trade_analysis_mysql`/`analytics_demo_sqlite`;
`mysql` and `sqlite` remain legal but
are easy to confuse with `databases` type values.

### One-shot manual approval host

`examples/manual_mutation_approval.py` is deliberately outside the AutoGen demo
and adds no dependency. It launches `start_server.py` with `sys.executable`, so
the current venv is preserved, explicitly inherits the operator's complete
process environment so exported DB/policy configuration is not replaced by a
different `.env`, and keeps preview and execute in one stdio Client context and
server subprocess as required by the process-local store. A canonical finite-JSON
parameter snapshot is used for both calls. The workflow fingerprints the approval
view and fails closed if a custom provider changes displayed params or preview
data before returning its decision. If the original request omits a target, execute
is pinned to the resolved `connection_id` returned by preview rather than
resolving the default again.

The host strictly requires a successful preview with matching Skill, valid
resolved alias/DB type/business preview, boolean idempotency, non-empty token,
and timezone-aware expiry. It derives approval timeout from the smaller of the
CLI timeout and remaining token lifetime minus a safety margin, and the workflow
itself enforces that monotonic deadline instead of trusting the UI provider. A
custom provider must cooperate with async cancellation; hostile-provider hard
termination would require process isolation. The approval
view excludes the bearer token and displays the exact Skill, params, resolved
connection, DB type, preview, expiry, and idempotency. Only literal `APPROVE`
executes; denial, blank/other input, timeout, EOF, cancellation, malformed
preview, or UI error fails closed. A daemon input thread avoids leaving
`asyncio.run()` waiting for a non-cancellable `input()` executor task after a
timeout; this is intentionally a one-shot CLI and does not reuse stdin.

Execute is attempted once. Exceptions/timeouts are classified as an unknown
write outcome and never retried because token consumption and database commit
may already have occurred. Returned output removes the `preview_token` field and
redacts the exact bearer value if an abnormal server echoes it elsewhere.
`--params-file` avoids putting business params in shell history, but the file,
rendered params/preview, and printed execute result may contain sensitive
business data; operators
must protect the file, terminal, screen sharing, and terminal capture/history.

The example is not proof of an authenticated human approval. Any other MCP
client can bypass it. Denial does not revoke the server-side token record or
create a server denial audit; the record consumes one bounded entry until
expiry/lazy cleanup and only normal preview audit exists. Token bytes necessarily
pass through FastMCP/client memory, Python cannot guarantee secure erasure, and
external payload/debug logging can still disclose them. A real multi-user or
compliance workflow needs product-owned approver authentication, role policy,
durable audit, and possibly an explicit cancellation protocol. These are not
v3.7 HTTP capabilities. Passing `env=dict(os.environ)` is an intentional
trusted-local-host compromise: it preserves the exact operator database/policy
configuration but also places every exported secret and Python control variable
inside the child/Skill trust boundary. A productized host should forward a
maintained project-specific allowlist instead.

### SQL safety and portable demo reset mutation

The shared SQL gate accepts exactly one statement. The full MCP policy rejects
raw `SHOW` and directs metadata discovery to `list_tables()`/`describe_table()`;
adds `sys` to blocked system schemas; preserves schema qualification during
allowlist checks; and extracts comma joins, nested queries, CTEs, ordinary
comment-separated targets, and EXPLAIN child tables without treating keywords
as tables. Non-ANALYZE EXPLAIN/DESCRIBE/DESC of
`UPDATE`/`INSERT`/`REPLACE`/`DELETE` remains supported; restrictive allowlists
check the DML target, all read sources, CTE aliases, and multi-table
`DELETE ... USING` source tables. Ambiguous targets fail
closed under a
restrictive allowlist. MySQL executable comments (`/*! ... */`), optimizer hints
(`/*+ ... */`), MariaDB executable comments (`/*M! ... */`), non-whitespace
double-dash forms, executing ANALYZE explain, and nested write DML are rejected.
These are conservative statement-shape/application-policy guards, not a claim
of comprehensive SQL semantics or database authorization.

`reset-demo-order-to-pending` is a deliberately low-freedom mutation example.
It requires the caller to state the exact non-pending status expected after a
preceding test, while reviewed code fixes the target to `pending`. It performs a
second read for the visible preview, binds that displayed source state into the
one-time token, and repeats it in the optimistic-lock predicate. The portable
SQL supports `databases: [mysql, sqlite]`; optional `connection_ids` remains
commented so deployments can bind it to their own dedicated demo aliases.

This is both a mutation-path exercise and a compensating cleanup call, not a
transactional rollback or production order-reopening operation. Supported
schemas must enforce `orders.id` as `PRIMARY KEY` or `UNIQUE`; the Skill's
read-side cardinality check is diagnostic only. Because the reset deliberately
permits `pending -> X -> pending`, it makes the status-only ABA limitation in
DRR-2026-046 reachable through bundled demo Skills. Live scenarios should use
dedicated records, avoid overlapping previews, and preferably start a fresh
stdio process per scenario.

### Files and validation

| File | Change |
|------|--------|
| `skills/_lib/skill_loader.py` | Parses, normalizes, caches, and discloses optional `connection_ids` without adding a direct connection-module dependency |
| `mcp_sql_server.py` | Evaluates discovery availability on the resolved target and rechecks scope/type before adapter creation in query and mutation execution paths |
| `examples/manual_mutation_approval.py` | Adds the stdio-only explicit approval reference host |
| `sql_safety_checker.py`, `mcp_sql_server.py`, `tests/test_sql_policy.py` | Enforce one-statement/raw-SHOW/comment/system-schema boundaries and token-aware table scope, including EXPLAIN-family DML targets/read sources/CTE aliases and multi-table `DELETE ... USING` sources, while preserving ordinary comments/strings and non-ANALYZE plan inspection |
| `skills/reset-demo-order-to-pending/` | Adds the MySQL/SQLite demo reset with explicit expected source state and fixed `pending` target |
| `tests/test_skill_loader.py` | Covers omission, one/many normalization, malformed metadata rejection, and parser/runtime alias-grammar parity |
| `tests/test_multi_connection_v35.py` | Covers query scope, default behavior, disclosure, pre-adapter denial, and real-frontmatter per-target type-conflict isolation |
| `tests/test_mutation_multi_connection_v36_design.py` | Covers mutation scope, pre-adapter denial, policy intersection, target isolation, and token non-consumption before scope acceptance |
| `tests/test_manual_mutation_approval.py` | Covers approval state, enforced deadlines, expiry, malformed results, finite-JSON snapshots, approval-view mutation rejection, resolved-target pinning, environment propagation, non-retry, and token non-output/redaction |
| README/safety/design/guide/risk/release documents | Record v3.7 contracts, limits, compatibility, and best-practice rationale |

Validation results:

- Final default repository suite after adversarial SQL/Skill/mutation hardening:
  462 passed, 3 skipped.
- The August 22 portable reset follow-up retained 462 passed, 3 skipped; its
  focused mutation/token/discovery selection passed 94 tests and the explicit
  root regression smoke passed 2 tests. A real MySQL reset and reset-specific
  subprocess stdio live run remain unclaimed.
- Focused SQL/query/SQLite suites: 115 passed.
- The root legacy smoke is outside default `pytest.ini` collection and was run
  explicitly: `test_bug_fixes.py` passed 2 tests.
- `git diff --check`, EN/ZH risk-register parity, and tracked Markdown
  relative-link checks passed.
- The approval workflow passed a real FastMCP `Client(module.mcp)` in-memory
  contract test and changed a disposable SQLite order exactly once.
- The 2026-08-13 and 2026-08-19/20 subprocess stdio attempts reached server
  startup but did not complete MCP initialize before the client timeout. They
  failed closed with no preview, audit, or DB write and remain historical
  environment observations. A 2026-08-21 follow-up subsequently completed the
  approval, denial, minimal-echo, `start_server.py`, and full-server subprocess
  stdio checks; details are recorded in
  `RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`.

---

## Update v3.6.1 - Preview-Token Store and Execution Hardening (August 10, 2026)

This v3.6.1 maintenance update belongs to the v3.6 release family and continues
to use `RELEASE_NOTES/RELEASE_NOTES_v3_6.md`. It closes DRR-2026-003,
DRR-2026-035, DRR-2026-037, DRR-2026-038, DRR-2026-039, DRR-2026-041,
DRR-2026-045, and DRR-2026-047.

The final architecture uses one bounded, locked, process-local memory store.
The recommended deployment is stdio, where preview and execute stay in the same
client-launched MCP process. Conditional HTTP mutation use is limited to one
mutation-enabled process in a trusted private boundary; multi-user authenticated
HTTP mutation is not a v3.6.1 deployment target. The application cannot enforce
worker/replica counts. Restart invalidates outstanding tokens even with a fixed
signing secret; callers must preview again.

A shared external token backend was evaluated because it could coordinate state
across workers. It is intentionally deferred: the repository primarily
documents stdio/single-process use and does not yet define or validate a
complete remote multi-replica profile. External services and persistence layers
move rather than eliminate transaction, cleanup, failure, and operational
complexity. The current design therefore requires no external token service,
token table, or token file.

The main token-store work and final-review follow-up were:

1. **DRR-2026-045 deployment scope:** retained the v3.6 bounded memory store,
   formalized a stdio-first same-process contract, and deferred shared external
   state until a concrete remote mutation requirement exists.
2. **DRR-2026-041 test signal:** completed signing-secret rotation with a real
   reload/rejection assertion, replaced the tautological sanitization check,
   and covered terminal token consumption after a database write exception.
3. **DRR-2026-038 preview provenance:** `update-order-status` now builds its
   binding from the status returned by the same query that produced the visible
   preview. A preview carrying an `error` or reporting `success=false` returns a
   failed result and receives no token, including empty/null error values.
4. **DRR-2026-037 one write path:** the public unbound `execute()` method now
   raises `ToolError`; all order-status writes go through
   `execute_with_binding()` and the preview-derived optimistic-lock value.
5. **DRR-2026-039 test isolation:** default pytest disables `.env` loading,
   installs a safe SQLite/config baseline before application imports, and
   requires explicit opt-in before the MySQL fixture can connect.
6. **DRR-2026-035 fixture cleanup:** reverified that `sample_data/demo.db`
   matches its tracked baseline and retained the rule that write tests use
   disposable databases.
7. **DRR-2026-003 dead helper cleanup:** removed two unreferenced availability
   wrappers so `_skill_availability_state()` remains the only policy source.
8. **Post-consume audit completeness:** dynamic validation rejection after
   atomic token consumption now attempts a best-effort execute audit and reports
   the actual `audit_logged` result without weakening terminal consumption. A
   response-stage failure after a committed write preserves the existing
   success audit instead of appending a contradictory execute failure.
9. **Configuration bounds and visibility:** capped process-local capacity at
   100000 entries, added generated/configured signing-key diagnostics without
   logging key material, and summarized candidate and policy-enabled mutation
   routing at startup without calling it final Skill/schema authorization.
10. **Dead named SQLite alias:** removed the unreachable
    `DB_<ID>_DATABASE_PATH` fallback; `DB_<ID>_SQLITE_DATABASE_PATH` remains the
    only named SQLite path setting.

The memory store preserves random `jti`, HMAC and execution-state binding,
bounded issuance, expiry cleanup, atomic one-time consume, sequential/concurrent
replay rejection, and terminal consumption. It does not support cross-worker
preview/execute, mutation horizontal scaling, restart-surviving token state, or
cross-process global capacity. Named database connections are unaffected;
read-only scaling requires a separate read-only endpoint, profile, or pool.

### Files and Configuration

| File | Change |
|------|--------|
| `preview_token_store.py` | Extracted the v3.6 bounded, locked memory-store behavior into a focused module with a minimal token record |
| `mcp_sql_server.py` | Registers/consumes preview tokens in one process, bounds TTL at 86400 seconds and capacity at 100000 entries, audits post-consume validation rejection, reports safe startup policy diagnostics, rejects every declared preview failure, and accurately describes optional mutation capability |
| `db_adapter.py` | Keeps `DB_<ID>_SQLITE_DATABASE_PATH` as the sole named SQLite path and removes an unreachable alias fallback |
| `skills/update-order-status/mutation.py` | Binds execution to the displayed preview read and disables direct unbound execution |
| `tests/test_preview_token_store.py` | Covers memory capacity, expiry, mismatch, and concurrent one-winner semantics |
| `tests/test_mutation_multi_connection_v36_design.py`, `tests/test_mutation_skills.py` | Cover DRR-2026-037/038/041/045, strict preview failures, TTL bounds, and tool-level concurrent replay with exactly one database write |
| `tests/conftest.py` | Makes default pytest independent of local `.env` and gates optional live MySQL integration behind explicit opt-in |
| `requirements.txt` | Requires `python-dotenv>=1.2.0`, the first release that implements the test suite's `.env` disable switch |

The retained token settings are:

```env
MUTATION_PREVIEW_TOKEN_TTL_SECONDS=300
# Valid range: 1-100000; invalid values fall back to 10000.
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES=10000
# MUTATION_PREVIEW_TOKEN_SECRET=replace_with_at_least_32_random_bytes
```

### Validation

- Syntax checks passed for the store, MCP server, and focused test modules.
- Focused mutation/store regression:
  `.venv/bin/python -m pytest -q tests/test_preview_token_store.py tests/test_mutation_multi_connection_v36_design.py tests/test_mutation_skills.py`
  -> 67 passed.
- Full repository suite: `.venv/bin/python -m pytest -q` -> 289 passed,
  3 skipped.
- `git diff --check` passed. Runtime Python, environment examples, and base
  requirements contain no external token-store dependency or configuration.

---

## Post-v3.6 Test Isolation and Documentation Follow-up (August 2, 2026)

### Test Isolation

The local live `.env` intentionally enables the v3.6 strict named-write policy
with `SKILLS_ALLOW_MUTATION_CONNECTIONS=mysql,analytics`. The v3.5 regression
fixture instead registers `default,analytics`. Because `db_adapter.py` calls
`load_dotenv()` during module import, an unisolated test process could restore
the local allowlist and fail during `mcp_sql_server` import by looking for an
unconfigured `mysql` fixture connection.

`tests/test_multi_connection_v35.py::_reload_server()` now explicitly sets
`SKILLS_ALLOW_MUTATION_CONNECTIONS` to an empty value before re-importing the
server modules. Empty, rather than deleting the variable, is deliberate:
`load_dotenv()` does not override an existing empty environment value, so the
live `.env` cannot reintroduce the `mysql,analytics` allowlist. This is a test
fixture isolation fix; the live `.env` must not be changed to accommodate the
v3.5 test aliases.

### Documentation Follow-up

- Added `V3_5-V3_7_SKILLS_GUIDE_ZH.md` (originally the v3.5-v3.6 guide), an explanatory Chinese guide covering
    named connections, per-connection policy, Skill metadata, strict mutation
    routing, preview-token binding, state drift, and MutationBase contracts.
- Updated `skills/SAFETY.md` for the implemented v3.6 server-side
    preview-token model, corrected the concrete `Mutation.execute()` write
    constraint, and clarified that stdio/SSE is not itself a rate-limit boundary.
- Added Chinese explanations to the local `.env` for connection routing,
    timeout scope, token lifecycle, audit behavior, default limits, and the
    test-isolation boundary. No effective live configuration values were changed.

### Validation

- `.venv/bin/python -m pytest -q tests/test_multi_connection_v35.py` → 6 passed.
- `.venv/bin/python -m pytest -q tests/test_mutation_multi_connection_v36_design.py` → 27 passed.
- `git diff --check` for the changed test and documentation files produced no output.

## Project-wide Pylance Type-Safety Follow-up (August 2, 2026)

### Findings and Root Cause

A workspace-wide Pylance scan found five severity-1 diagnostics outside the
previously fixed v3.5/v3.6 regression files. They had the same underlying
pattern: optional or loosely typed values were allowed to cross a helper or
test-double boundary without an explicit contract or runtime narrowing.

- `test_mcp_client.py` passed `None` to a parameter declared as `str`.
- `tests/test_annotations_consistency.py` declared FastMCP tools as
    `object`, then accessed their `annotations` member; a second access path
    also used an optional annotation without checking it.
- `tests/test_db_adapter.py` assigned lightweight `DummyEngine` instances to
    the production `Engine | None` attribute without documenting the test-only
    structural substitution.
- `tests/test_skills_disclosure.py` accessed `openWorldHint` on an optional
    `ToolAnnotations` value.

### Remediation

- Marked the client helper's `note` parameter as `str | None`.
- Typed the annotation test's tool collection as `dict[str, Tool]` and added
    explicit `None` assertions before reading optional annotations.
- Used narrow `cast(Engine, ...)` expressions only at the three test-double
    assignments; production adapter typing remains unchanged.
- Added an explicit annotation-presence assertion before reading
    `openWorldHint` in the Skills disclosure test.
- Extended pytest environment isolation to include
    `SKILLS_ALLOW_MUTATION_CONNECTIONS`, and made the named-connection policy
    test explicitly disable MySQL mutations so local `.env` values cannot alter
    its expected baseline.

The preferred rule is to fix uncertainty at the producer or helper boundary,
then use a runtime assertion when the test is intentionally validating that
the value exists. Broad `Any` annotations and scattered `# type: ignore`
directives are not appropriate substitutes for these contracts.

### Validation

- Workspace Pylance diagnostics: no severity-1 findings remain. Severity-4
    unused-symbol notices are informational and were left outside this fix.
- `.venv/bin/python -m pytest -q tests/test_annotations_consistency.py
    tests/test_db_adapter.py tests/test_skills_disclosure.py` -> 70 passed,
    3 skipped.

---

## Update v3.6 (May 30, 2026) - Mutation Preview Tokens and Named Write Policy

### Overview

Closed the v3.5 compromise that kept mutation Skills on the default connection
only. v3.6 introduces one consistent high-impact write protocol: every
`execute_mutation_skill(confirm=true)` call must present the one-time
`preview_token` returned by the matching `confirm=false` preview, including on
the default connection. Named write targets are opt-in and require three
independent policy layers before a write is considered.

The token is HMAC-signed and bound to skill name, skill version, canonical
params hash, resolved `connection_id`, `db_type`, issue/expiry timestamps, a
random `jti`, and a hash of the minimal preview-time execution binding. It is
registered in a bounded process-local store and atomically consumed before
dynamic validation and the write, so replay fails closed. Consumption is
terminal: after a later validation, database, timeout, audit, or response
failure the caller must preview again rather than retry the old token.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `PreviewTokenRecord`, `InMemoryPreviewTokenStore` (bounded, locked, lazy-expiring), token payload/signature/verify/consume helpers, `MUTATION_PREVIEW_TOKEN_*` configuration, `SKILLS_ALLOW_MUTATION_CONNECTIONS` strict-mode parsing with startup validation of each listed id, `_mutation_connection_policy_state()` shared by discovery and execution, and optional `connection_id` plus required `preview_token` on `execute_mutation_skill` |
| `mcp_sql_server.py` Skills paths | Modified | `list_skills` / `get_skill_detail` now report `mutation_connection_supported` and `mutation_policy_allowed`; unauthorized mutation Skills are non-executable in discovery and rejected at execution with the same policy result |
| `db_adapter.py` | Modified | Extended `ConnectionPolicy` with `allow_mutations` and `mutation_skills`; added `DB_<ID>_ALLOW_MUTATIONS` / `DB_<ID>_MUTATION_SKILLS` parsing with skill-name validation and explicit `*` wildcard; omitted per-target values deny writes |
| `skills/_lib/mutation_base.py` | Modified | Added `build_execution_binding()` and `execute_with_binding()`; `run_execute()` now routes through the binding path, forwards `client_id` / `connection_id` / `db_type` to audit, and returns the real `_audit_logged` outcome. A non-empty binding is rejected rather than silently ignored |
| `skills/update-order-status/mutation.py` | Modified | Captures `expected_status` during preview and applies the optimistic lock against that previewed value via `_execute_with_expected_status()` instead of re-binding to a later status |
| `skills/update-order-status/skill_def.md` | Modified | Documented the token workflow, one-time replay protection, preview-state binding, and best-effort audit semantics |
| `tests/test_mutation_multi_connection_v36_design.py` | Added | 27 tests covering routing, token binding/tampering/expiry, all three denial layers, one-time replay, concurrent consumption, capacity and lazy expiry, restart invalidation, static-rejection non-consumption, terminal failure semantics, preview-state drift, and full-token exclusion from meta/audit |
| `.env.example` | Modified | Documented `MUTATION_PREVIEW_TOKEN_TTL_SECONDS`, `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES`, `MUTATION_PREVIEW_TOKEN_SECRET`, `SKILLS_ALLOW_MUTATION_CONNECTIONS`, and the per-connection write variables |
| `README.md`, `README_ZH.md`, `MCP_AGENTS_SKILLS_DESIGN.md`, `skills/SAFETY.md`, `DESIGN_RISK_REGISTER.md`, `DESIGN_RISK_REGISTER_ZH.md` | Modified | Documented the two-call migration requirement, the strict write policy layers, token lifecycle and limits, and DRR-2026-030 / DRR-2026-034 |
| `RELEASE_NOTES/RELEASE_NOTES_v3_6.md` | Added | Release notes for the preview-token core and named write policy |

### Write Authorization Layers

A mutation write is attempted only when all of the following hold. They are
independent switches, not alternatives:

1. `ENABLE_SKILLS=1`
2. `SKILLS_ALLOW_MUTATIONS=1`
3. Target `connection_id` listed in `SKILLS_ALLOW_MUTATION_CONNECTIONS`
   (omitting the variable keeps v3.5-compatible default-connection-only scope)
4. `DB_<ID>_ALLOW_MUTATIONS=1`
5. Skill listed in `DB_<ID>_MUTATION_SKILLS` (or the explicit `*` wildcard)
6. DB type compatibility and schema readiness for the resolved connection
7. Parameter schema validation plus the Skill's own `validate()`
8. A valid, unexpired, unconsumed `preview_token` matching this exact request

Query `ALLOWED_TABLES` is deliberately not reused as write authorization: a
readable table is not a writable table.

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Token scope | Required for every mutation execute, including the default connection | Require tokens only for non-default connections | One protocol avoids a weaker legacy path and makes preview/execute target binding explicit everywhere |
| Token binding fields | skill name, version, canonical params hash, `connection_id`, `db_type`, `iat`/`exp`, `jti`, execution-binding hash | Sign only skill name and params | Prevents preview-on-A/execute-on-B, param substitution, and executing v2 logic against a v1 preview |
| Replay protection | Bounded process-local store consumed atomically before validation/write | Rely on HMAC expiry alone, or consume only after successful commit | HMAC alone is replayable until expiry; consuming after commit reopens the race. Consuming first is conservative for uncertain write outcomes |
| Capacity behavior | Fail closed when the store is full; never evict valid tokens | LRU eviction | Eviction would silently invalidate a legitimate reviewed preview |
| Preview-state binding | Opt-in per Skill via `build_execution_binding()` / `execute_with_binding()`; non-empty bindings must be handled | Always re-read state during execute | Re-reading lets execute act on state the reviewer never saw; explicit opt-in avoids silently ignored bindings |
| Named write policy | Global target allowlist plus per-connection switch plus per-connection skill allowlist | Single global switch, or reuse read allowlists | Deny-by-default with separate operator-controlled layers; read policy and write authorization stay distinct |
| Discovery/execution parity | `_mutation_connection_policy_state()` used by both | Filter in discovery only | Keeps `available_only` an ergonomic filter while execution stays authoritative |

### Compatibility Notes

- **Breaking for direct execute callers.** Clients that previously called
    `execute_mutation_skill(confirm=true)` in one step must now call
    `confirm=false` first and pass the returned `preview_token`.
- Omitting `SKILLS_ALLOW_MUTATION_CONNECTIONS` preserves the v3.5
    default-connection-only mutation scope. Setting it enables strict mode and
    does not by itself grant write permission.
- The token store is process-local. Preview and execute must reach the same
    server process. Client-owned stdio is the recommended deployment. If an
    integrator conditionally exposes mutation over HTTP, it must use one process
    in a trusted private boundary; multi-user authenticated HTTP mutation is not
    supported. Restart invalidates outstanding tokens even when
    `MUTATION_PREVIEW_TOKEN_SECRET` is fixed, because store state is not
    persisted. The application does not enforce worker/replica counts. A future
    multi-worker design requires shared atomic state and must not fall back to
    stateless HMAC acceptance.
- `preview_token` is returned in the structured payload only. Applicable tool
    metadata carries a short `preview_token_id` correlation hint. Audit and
    telemetry persist neither the full token nor that short identifier.
- `destructiveHint` and `requires_confirmation` remain advisory client hints.
    `confirm=true` proves the client requested execution; it does not prove a
    human approved it. Deployments needing human approval require a separate
    client or external workflow.

### Validation

- `.venv/bin/python -m pytest -q tests/test_mutation_multi_connection_v36_design.py` → 27 passed.
- Full repository test suite after the v3.6 change set: `.venv/bin/python -m pytest -q` → 259 passed, 3 skipped.
- Live MCP stdio smoke on MySQL and SQLite fixtures verified preview token
    issuance, execute with the matching token, one-time replay rejection,
    cross-connection token rejection without consuming the valid token, and
    `pending -> confirmed` writes with `rowcount=1`. Details and cleanup
    evidence are in `RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`.

---

## Update v3.5 (May 30, 2026) - Named Multi-Connection Read Tools and Query Skills

### Overview

Implemented configured named database connections while preserving the legacy
single-default-connection path. The core invariant is now explicit in code and
docs: resolve the target `ConnectionContext` first, then run SQL policy, schema
readiness checks, dialect-specific helper SQL, execution, metadata, audit, and
telemetry against that same connection. Unknown connection ids fail closed and
never fall back to the default.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | Modified | Added `ConnectionPolicy` and `DatabaseConfig`, named connection env parsing, `get_default_connection_id()`, `get_connection_config()`, `list_connection_configs()`, and an adapter cache keyed by `connection_id`; direct constructors and no-arg `get_adapter()` remain compatible with legacy callers; `DB_<ID>_*` and `DEFAULT_DB_CONNECTION` are ignored unless `DB_CONNECTIONS` is explicitly set |
| `sql_safety_checker.py` | Modified | Added optional `connection_id` to `execute_sql()` and now resolves the selected adapter/config before SQL safety policy or execution while preserving existing two-argument behavior |
| `mcp_sql_server.py` | Modified | Added `ConnectionContext`, `_resolve_connection_context()`, `list_connections()`, optional `connection_id` on read-only core tools, connection-aware policy/schema helpers, connection-aware ToolResult metadata/telemetry, quoted-identifier table allowlist extraction, and SQLite public database display aliases (`sqlite:<connection_id>`) |
| `mcp_sql_server.py` Skills paths | Modified | `list_skills`, `get_skill_detail`, and `execute_query_skill` now evaluate DB compatibility, schema readiness, allowlists, execution, metadata, optional query audit, and telemetry against the target connection; mutation Skills are marked non-executable on non-default connections in v3.5 |
| `skills/_lib/audit.py`, `skills/_lib/mutation_base.py` | Modified | Audit records can include safe `connection_id` and actual `db_type` without logging DSNs, credentials, SQL params, or returned rows |
| `start_server.py` | Modified | Startup validation imports server code only after environment validation and now validates the configured connection registry |
| `.env.example` | Modified | Added optional `DB_CONNECTIONS`, `DEFAULT_DB_CONNECTION`, and `DB_<ID>_*` examples, including the legacy-mode rule that per-connection variables and default selection are inactive until `DB_CONNECTIONS` is set |
| `README.md`, `README_ZH.md`, `MCP_AGENTS_SKILLS_DESIGN.md`, `SQLITE_ADAPTER_DESIGN.md`, `skills/SAFETY.md`, `TEST_MCP_CLIENT_GUIDE.md`, `DESIGN_RISK_REGISTER.md`, `DESIGN_RISK_REGISTER_ZH.md` | Modified | Documented v3.5 behavior, invariants, compatibility, compromises, telemetry/audit privacy, deferred multi-connection mutation risk, the `DB_CONNECTIONS` feature gate, runtime allowlist checks for quoted identifiers, SQLite path sanitization in public payloads, and the distinction between local pytest guardrails and actual CI enforcement |
| `tests/test_multi_connection_v35.py` | Added | Covers registry parsing, unknown connection fail-closed behavior, same-connection policy/execution, Skills availability/execution consistency, and mutation default-only scope |
| `tests/conftest.py`, `tests/test_db_adapter.py`, `tests/test_v342_meta_and_schema.py`, `tests/test_audit.py`, `tests/test_skills_disclosure.py`, `tests/test_annotations_consistency.py` | Modified | Expanded assertions for registry reset behavior, legacy-mode isolation from local named `.env` variables, connection metadata, audit fields, tool surface, and disclosure consistency |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Connection identity | Server-configured `connection_id` aliases only | Allow tools/models to pass DSNs | Prevents credential disclosure and keeps routing under operator control |
| Resolve-first invariant | Resolve `ConnectionContext` before policy, readiness, helper SQL, execution, metadata, audit, and telemetry | Let each helper read global adapter/config state | Prevents cross-connection mismatches and fixes the historical quote-on-one-adapter/execute-on-default risk |
| Default compatibility | Omitted `connection_id` uses the default connection and legacy env vars still work when `DB_CONNECTIONS` is unset | Require all callers to pass connection ids | Preserves existing behavior and minimizes migration cost |
| Query Skill runtime policy | Startup validation checks read-only/structural safety; runtime enforces target connection policy | Validate every skill against every configured connection at startup | Per-connection allowlists differ by deployment, so runtime is the authoritative policy point |
| Table allowlist parsing | Normalize common quoted and schema-qualified identifiers before comparison | Continue matching only bare identifiers | Prevents `"table"`, `[table]`, and `schema."table"` forms from bypassing per-connection allowlists |
| Mutation scope | Default-connection only in v3.5 | Enable multi-connection writes immediately | Avoids preview/execute target drift and missing per-connection write permissions until a dedicated write policy exists |
| Metadata privacy | Include `connection_id` and `db_type`; exclude DSNs, hosts, users, passwords, SQLite paths, SQL params, and returned rows; display SQLite databases as `sqlite:<connection_id>` in public payloads | Include connection internals for debugging | Gives operators enough correlation without leaking sensitive connection material |

### Compatibility Notes

- Existing `.env` files that set only `DB_TYPE`, MySQL credentials, or
    `SQLITE_DATABASE_PATH` continue to work. `DB_CONNECTIONS` is optional.
- `DB_<ID>_*` variables are treated as named-connection config only when
    `DB_CONNECTIONS` is explicitly set. If `DB_CONNECTIONS` is unset or empty,
    legacy mode ignores those variables so local smoke configuration cannot
    silently override `DB_TYPE`/`SQLITE_DATABASE_PATH`.
- `DEFAULT_DB_CONNECTION` is also ignored in legacy mode; it only selects a
    default among ids listed in `DB_CONNECTIONS`.
- Existing MCP calls keep working when they omit `connection_id`; the default
    connection is selected.
- `SkillMetadata.databases` still describes DB type compatibility (`mysql`,
    `sqlite`, or omitted), not connection ids.
- Query Skills are now connection-scoped for listing, detail, and execution.
    Their visible executability should match the target connection used for
    execution.
- Mutation Skills intentionally remain default-connection only in v3.5. This is
    a documented compromise, not a missing parameter.
- Result-size caps (`MAX_RESULT_ROWS`, `MAX_RESULT_CHARS`, schema/table overview
    caps) remain process-wide; per-connection policy currently covers allowlist,
    UNION, query timeout, connect timeout, and SQLite progress interval.

### Validation

- Syntax check: `.venv/bin/python -m py_compile db_adapter.py sql_safety_checker.py mcp_sql_server.py start_server.py skills/_lib/audit.py skills/_lib/mutation_base.py tests/test_multi_connection_v35.py tests/test_db_adapter.py tests/test_v342_meta_and_schema.py tests/test_audit.py`
- Focused v3.5/regression suite after the latest follow-up: `.venv/bin/python -m pytest -q tests/test_sql_policy.py tests/test_multi_connection_v35.py tests/test_db_adapter.py::TestGlobalAdapter tests/test_v342_meta_and_schema.py tests/test_audit.py tests/test_skills_disclosure.py::test_mysql_database_hides_sqlite_skill_by_default tests/test_annotations_consistency.py` → 44 passed.
- Full repository test suite: `.venv/bin/python -m pytest -q` → 231 passed.
- Patch whitespace and syntax: `git --no-pager diff --check && .venv/bin/python -m py_compile db_adapter.py mcp_sql_server.py sql_safety_checker.py tests/test_sql_policy.py tests/test_db_adapter.py tests/test_multi_connection_v35.py` produced no output.
- VS Code diagnostics: no errors found for the changed Python files.
- Live MCP smoke on the local `.env` after adding `DB_CONNECTIONS=mysql,analytics`: `list_connections()` reported `mysql` (MySQL, selected as the default) and `analytics` (SQLite); `check_connection()` and `query(..., "SELECT 1 AS smoke_test")` succeeded on both connections. `list_tables(connection_id="analytics")` returned only `orders` under the analytics allowlist. `list_skills(connection_id="analytics", available_only=false)` showed `monthly-sales-report-sqlite` executable and `update-order-status` non-executable with `disabled_reason="Mutation skills are limited to the default connection in v3.5."`; `execute_query_skill(connection_id="analytics", skill_name="monthly-sales-report-sqlite", params={"year": 2024, "month": 1})` succeeded with zero rows and no truncation.

---

## Update v3.4.3 (May 24, 2026) - Bounded SQLite Estimates and Tool-Surface Wording

### Overview

Kept the release scope focused on removing an avoidable large-table scan and
making model-facing descriptions more conservative. The SQLite row-estimate
fallback no longer upgrades metadata discovery into a full `COUNT(*)`; when
`sqlite_stat1` is unavailable and a table reaches the 10,000-row sampling cap,
the adapter returns the cap as a lower-bound estimate. Exact counts remain
explicit through user SQL or `get_table_summary(exact_count=True)`.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | Modified | `SQLiteAdapter.get_row_estimate()` now prefers `sqlite_stat1`, then uses bounded 10,000-row sampling without a full `COUNT(*)` fallback for larger tables; tightened typing around SQLAlchemy engines/results and classifies SQLAlchemy-wrapped SQLite `interrupted` errors as query timeouts |
| `tests/test_db_adapter.py` | Modified | Added regression coverage that large SQLite tables without `sqlite_stat1` return the sampling cap and do not execute full `COUNT(*)`; added coverage that `ANALYZE`/`sqlite_stat1` is still preferred; added SQLite timeout interruption coverage |
| `mcp_sql_server.py` | Modified | Clarified query/skill truncation notes: truncation limits returned payload only, while `WHERE`/`LIMIT`/`ORDER BY` must be used to limit database work and stabilize ordering; updated `list_tables()` / `get_full_schema()` descriptions to visible/truncated semantics |
| `test_mcp_client.py` | Modified | MCP smoke test now uses assertions, dict parameters for skill calls, `structured_content`-first result parsing, and an explicit skip only when the configured database is unavailable under pytest |
| `README.md`, `README_ZH.md`, `TEST_MCP_CLIENT_GUIDE.md`, `MCP_AGENTS_SKILLS_DESIGN.md`, `PROMPT_ENGINEERING_BEST_PRACTICES.md`, `SQLITE_ADAPTER_DESIGN.md`, `.env.example`, `GEMINI.md`, `agent_examples/` | Modified | Updated safety wording, SQLite estimate behavior, optional exact-count guidance, visible/truncated schema language, tool-count wording, SQLite write-lock wording, and prompt guidance so `get_table_summary()` is not treated as a default planning step |
| `DESIGN_RISK_REGISTER.md`, `DESIGN_RISK_REGISTER_ZH.md` | Added/Modified | Long-term design risk register records completed V343-001 through V343-005, closes V343-006 through V343-008 as documentation/operations guidance, and leaves V343-009 through V343-014 as accepted/deferred items |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| SQLite large-table estimates | Return the 10,000-row sample cap as a lower-bound estimate when `sqlite_stat1` is absent | Run full `COUNT(*)` after the sample cap | Keeps metadata tools bounded and consistent with their estimate contract; exact counts are still available when explicitly requested |
| Query truncation wording | Clarify payload-only truncation | Let users infer execution limits from `MAX_RESULT_ROWS` | Prevents agents from mistaking returned-row limits for database work limits |
| Generic SQL pagination | Keep pagination in user SQL | Add `limit`/`offset` or cursor-token params to `query()` | Arbitrary SQL result stability depends on query semantics and ordering; generic wrappers would be misleading |
| Tool/schema descriptions | Use visible/truncated wording | Say "all tables" / "complete schema" | FastMCP and function-calling guidance rewards precise descriptions because models choose tools from them |

### Compatibility Notes

- SQLite `row_count` for large tables without `ANALYZE` may now be lower than
    before because it is a bounded lower-bound estimate rather than an exact
    count. This affects metadata helpers only; explicit `COUNT(*)` queries are
    unchanged.
- `query()` and `execute_query_skill()` still execute through the existing
    adapter path and truncate after fetching. v3.4.3 only clarifies this
    contract; adapter-level streaming/fetch limiting remains a separate design
    decision.
- FastMCP client helpers should read `structured_content` before `data` because
    skill payloads themselves contain a `data` field. Skill tool params are MCP
    objects/dicts, not JSON strings.
- V343-006 through V343-008 are intentionally documented rather than implemented
    as new runtime controls in this release: raw SQL echo remains compatible,
    audit params are treated as business audit data rather than secrets, and
    JSONL rotation/retention is delegated to deployment tooling.

### Validation

- Full repository test suite: `.venv/bin/python -m pytest -q` → 183 passed.
- VS Code diagnostics: no errors found.
- Patch whitespace: `git --no-pager diff --check` produced no output.
- Direct MCP stdio verification covered `check_connection`, `list_tables`,
  safe/unsafe `query`, `get_full_schema`, `list_skills`, `get_skill_detail`,
  `execute_query_skill`, `execute_mutation_skill(confirm=false)`, and opt-in
  telemetry JSONL. Telemetry records contained only sanitized fields and no SQL,
  params, rows, or returned data.

---

## Update v3.4.2 (May 21, 2026) - Unified ToolResult, Output Schemas, and Optional Telemetry

### Overview

Closed the asymmetry from v3.4.1 by giving every MCP tool the same return
shape, declared MCP `outputSchema` on the two skill execution tools, and
introduced an opt-in middleware that records sanitized per-call telemetry.
Also formalized the pytest-level annotation-consistency check.

### Post-merge polish (same release, after code review)

- **B1 fix**: telemetry middleware now distinguishes transport-level outcome
    (`call_completed`, whether `call_next` returned without raising) from
    business-level outcome (`success`, which honors the tool's own
    `ToolResult.meta.success` when present). Previously a tool returning
    `meta.success=False` without raising (e.g. an unsafe-SQL veto by `query`)
    was mis-logged as `success=true`.
- **C1 schema refinement**: `execute_mutation_skill` `outputSchema` rewritten
    to reflect the real payload branches — `preview` object for preview mode,
    `result` object for execute mode, `validation` object for the
    validation-failure branch, `idempotent`/`hint` on the success branches.
    `mode` is now required and bound by the existing `preview`/`execute` enum.
- **3b sampling**: new `TOOL_TELEMETRY_SAMPLE_RATE` env var (float 0.0–1.0,
    default 1.0) gates JSONL writes for high-throughput deployments; values
    are clamped, invalid strings fall back to 1.0.
- **Test coverage** (`tests/test_v342_meta_and_schema.py`): direct meta
    assertions on every base tool, `outputSchema` registration check via real
    `Client.list_tools()`, and an end-to-end telemetry check that drives the
    middleware through `Client.call_tool()` covering both success and
    business-level-rejection branches.
- **Doc consistency**: removed v3.4.1-era "scope: only 2 skill tools" notes
    from `README.md`, `README_ZH.md`, `TEST_MCP_CLIENT_GUIDE.md`, and
    `MCP_AGENTS_SKILLS_DESIGN.md` that contradicted the v3.4.2 uniform
    `ToolResult` rollout.
- **Review follow-up**: `_skill_tool_result()` now includes the same common
    `tool_name` and `success` metadata fields as base tools. The `success`
    value is derived from the stable structured payload, so a mutation
    validation failure that returns normally with `structuredContent.success=false`
    is logged as business-failed telemetry instead of being mistaken for
    success merely because no exception escaped `call_next()`.
- **Telemetry parser hardening**: `TOOL_TELEMETRY_SAMPLE_RATE` now rejects
    non-finite floats (`nan`, `inf`, `-inf`) by falling back to 1.0. Finite
    out-of-range values remain clamped to the nearest bound. This keeps a typo
    from silently disabling all telemetry records.
- **Configuration/docs parity**: `.env.example` now documents the telemetry
    feature flags, including the security compromise that tool usage timing is
    sanitized but still operationally sensitive. Client response examples were
    corrected to show `mode="query"`, real mutation preview/execute payload
    keys, and the uniform `_meta.tool_name` / `_meta.success` fields.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added module-level `_tool_result()` helper; converted `query`, `check_connection`, `list_tables`, `describe_table`, `get_full_schema`, `get_table_summary`, `sample`, `list_skills`, `get_skill_detail` to return `ToolResult` with runtime metadata; added uniform `tool_name`/`success` meta to Skills execution results; added `output_schema` to `execute_query_skill` and `execute_mutation_skill`; added opt-in `_ToolTelemetryMiddleware` (env `ENABLE_TOOL_TELEMETRY` / `TOOL_TELEMETRY_LOG_PATH` / `TOOL_TELEMETRY_SAMPLE_RATE`) |
| `tests/test_annotations_consistency.py` | Added | Pytest lint that fails local/default test runs if any registered tool's `ToolAnnotations` drift from the documented closed-world / read-only intent; add a CI workflow before describing this as CI enforcement |
| `tests/test_tool_telemetry.py` | Added/Modified | Verifies the telemetry middleware writes sanitized JSONL records on success, exception, and business-failure paths; covers sample-rate clamping including non-finite values; never logs SQL/params/rows |
| `tests/test_v342_meta_and_schema.py` | Added | Verifies base and skill tool meta contracts, outputSchema registration, and end-to-end telemetry via real FastMCP `Client.call_tool()` |
| `.env.example` | Modified | Documents opt-in tool telemetry configuration and sampling controls |
| `README.md`, `README_ZH.md`, `TEST_MCP_CLIENT_GUIDE.md`, `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | New v3.4.2 changelog entry, version badge bumped, scope/visibility notes updated, examples aligned with actual payload/meta contract |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Unify return type across all tools | Wrap every tool in `ToolResult` | Keep skill tools special-cased | Removes the v3.4.1 direct-call asymmetry and makes observability symmetric across the whole tool surface; existing clients still read `structuredContent` unchanged |
| Telemetry transport | FastMCP middleware writing local JSONL | Always-on logging or external sink | Opt-in (`ENABLE_TOOL_TELEMETRY=1`) keeps default behavior unchanged; local JSONL avoids new dependencies and remains greppable for operators |
| Telemetry payload | `timestamp`, `tool_name`, `execution_ms`, `call_completed`, `success`, `error_class`, `db_type` only | Include SQL, params, rows for richer analytics | Honors SAFETY constraints (no SQL/params/rows/credentials) and the spirit of `mask_error_details=True`; separates transport completion from business success so validation/safety rejections are not misclassified |
| Telemetry aggregation | Local JSONL plus optional sampling only | In-process p50/p95 stats tool/resource | Keeps the MCP server stateless and dependency-free; avoids exposing sensitive usage patterns to model-visible tools. Operators can compute percentiles externally over JSONL if needed |
| Output schema strictness | Object with required success/skill_name and `additionalProperties: true` | Strict closed schema | Tolerates incremental payload evolution (preview vs execute mode in mutations) while still giving clients a usable validation contract |
| Annotation consistency | Pytest test rather than startup assertion | Fail server startup if drift detected | Keeps server resilient to local edits while catching drift in local/default test runs; add repository CI before calling it CI enforcement |

### Compatibility Notes

- The `structuredContent` payload of every tool is byte-for-byte identical to
    v3.4.1. Adding `ToolResult.meta` and `outputSchema` is additive only.
- Direct Python callers should use
    `getattr(result, "structured_content", result)` to unwrap. The pattern is
    already in `tests/test_skills_disclosure.py::run_tool`.
- The telemetry feature is **disabled by default**. When enabled it writes to
    `logs/tool_calls.jsonl` (configurable via `TOOL_TELEMETRY_LOG_PATH`). The
    middleware never reads tool arguments, SQL, params, rows, or result data —
    it inspects tool name, timing, exception class, and the non-sensitive
    `ToolResult.meta.success` bit. The resulting log still reveals tool usage
    patterns and timings, so keep it on trusted local storage.
- Per MCP spec `_meta` remains OPTIONAL; clients MAY ignore it. The VS Code
    MCP UI still does not display `_meta`, so treat it as a server-side
    observability channel.

---

## Update v3.4.1 (May 19, 2026) - ToolResult Metadata and Closed-World Annotations

### Overview

Implemented the previously deferred runtime metadata decision for Skills
execution tools and normalized MCP tool safety annotations. The change keeps
the existing structured payload contract intact while adding FastMCP
`ToolResult.meta` for non-sensitive diagnostics.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `ToolResult` wrappers for `execute_query_skill` and `execute_mutation_skill`; attached runtime metadata such as `execution_ms`, row counts, truncation state, mode, db type, idempotency, and skill version; set `openWorldHint=false` on all MCP tool annotations |
| `tests/test_skills_disclosure.py` | Modified | Added coverage for `ToolResult.meta` on query skills and verified every listed MCP tool exposes `openWorldHint=false` |
| `README.md`, `README_ZH.md` | Modified | Documented closed-world tool hints and Skills runtime metadata conventions |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Updated ToolAnnotations matrix, moved ToolResult metadata from deferred/future work to implemented design, and documented metadata exclusions |
| `TEST_MCP_CLIENT_GUIDE.md` | Modified | Added client-facing note that Skills execution payloads remain structured while runtime diagnostics live in `meta` |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Skills execution response wrapper | Return `ToolResult(structured_content=payload, meta=...)` | Add diagnostic fields directly into the existing payload | Keeps business results stable and separates diagnostics from model-facing data |
| Metadata scope | Include timing/count/version/mode/truncation/audit flags | Include SQL, params, or returned data | Improves observability without expanding sensitive data exposure |
| Tool world hint | Set `openWorldHint=false` on all MCP tools | Leave FastMCP default/open hint | Tools operate against configured database/server boundaries, not arbitrary external entities; hints are advisory only |

### Compatibility Notes

- Existing MCP clients that read structured payloads continue to receive the
    same result object via `structuredContent` / client `.data`.
- `ToolResult.meta` is additional runtime metadata. It is not an authorization
    boundary and should not be treated as an audit log.
- **Historical v3.4.1 scope**: In v3.4.1, `ToolResult` was used only by
    `execute_query_skill` and `execute_mutation_skill`; the remaining nine MCP
    tools still returned plain `dict`. That mixed direct-call shape was an
    intentional narrow rollout at the time. v3.4.2 resolves it by making all 11
    tools return `ToolResult` with uniform common `meta` fields — see the latest
    section above.
- **Client visibility caveat**: Per MCP spec the `_meta` field is OPTIONAL and
    clients MAY ignore it. Verified during v3.4.1 testing: server-side
    middleware and MCP Inspector can read `_meta`, but VS Code's MCP UI does
    not currently surface it. Treat `ToolResult.meta` primarily as a
    server-side observability hook and an opt-in client signal.
- Query skill audit behavior is unchanged: `SKILLS_AUDIT_QUERIES=0` remains the
    default to avoid surprising parameter logs.

---

## Update v3.4 (May 14, 2026) - MCP Hardening and Skills Profile Policy

### Overview

Reviewed ten proposed hardening items and implemented the
low-risk changes that improve security or test signal without changing the
default Skills execution model. Runtime SQL/Python source loading remains
unchanged: executable skill artifacts are still validated and cached at startup.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Enabled FastMCP `mask_error_details=True`; added configurable MCP tool timeouts; added `MAX_SQL_LENGTH` schema/runtime guard for raw `query(sql)`; added `SKILLS_EXCLUDE_PROFILES`; added optional query skill audit logging |
| `skills/_lib/audit.py` | Modified | Generalized audit wording from mutation-only to skill operations and records optional query metadata such as `total_rows` and `truncated` without logging returned data |
| `test_bug_fixes.py` | Modified | Refactored source-based checks so pytest tests assert instead of returning booleans |
| `tests/test_skills_disclosure.py` | Modified | Added coverage for profile exclusion, direct execution blocking, query skill audit, raw query MCP schema length metadata, and runtime raw SQL length rejection |
| `.env.example` | Modified | Documented `MCP_TOOL_TIMEOUT_SECONDS`, `MAX_SQL_LENGTH`, `SKILLS_EXCLUDE_PROFILES`, and `SKILLS_AUDIT_QUERIES` |
| `README.md` | Modified | Documented the new hardening controls and deferred decisions |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Recorded the profile policy, optional query audit, tool timeout, raw SQL length decision, and deferred v3.4.B3/v3.4.B4/v3.4.C1 choices |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Pytest warnings | Convert boolean-returning tests to assert wrappers | Leave source-verification script unchanged | Removes noisy pytest warnings while preserving direct script execution |
| Error masking | `mask_error_details=True` | Depend only on local sanitization | Masks unexpected exceptions while explicit `ToolError` messages continue to expose sanitized guidance |
| Raw SQL length | `MAX_SQL_LENGTH=20000` for `query(sql)` | Apply length caps to skill SQL templates | Free-form Agent SQL is untrusted input; reviewed skill templates are code artifacts validated at startup |
| Profile policy | `SKILLS_EXCLUDE_PROFILES` marks matching skills non-executable | Delete bundled demo skills from production branches | Keeps examples useful but gives production deployments an explicit guardrail |
| Query audit | `SKILLS_AUDIT_QUERIES=0` opt-in | Audit all query skills by default | Avoids surprising parameter logs; compliance-oriented deployments can enable it |
| Tool timeout | FastMCP `timeout` via `MCP_TOOL_TIMEOUT_SECONDS` | Only DB-level timeout | Covers non-DB stalls and foreground request hangs; default is conservative for schema tools |
| v3.4.B3 ToolResult metadata | Deferred decision | Wrap current dict returns in `ToolResult` | Would alter client-facing response contracts without a current need |
| v3.4.B4 Session schema cache | Deferred decision | Cache table names in `ctx.set_state()` | Reduces repeated metadata reads but can stale after DDL; table-readiness checks are lightweight |
| v3.4.C1 Schema resource | Deferred decision | Add `db://schema` MCP resource | Existing schema tool is explicit and broadly supported; resource path can be added later without blocking current workflows |

### Compatibility Notes

- All new runtime behavior is controlled by environment variables or preserves old defaults.
- `SKILLS_EXCLUDE_PROFILES` defaults to empty, so existing Skills catalogs are unchanged unless explicitly configured.
- `SKILLS_AUDIT_QUERIES` defaults to `0`; mutation auditing behavior is unchanged.
- `MAX_SQL_LENGTH` affects only raw `query(sql)` input, not reviewed query skill templates.
- `ToolError` messages remain visible by design under FastMCP error masking.

### Testing

- `.venv/bin/python -m pytest test_bug_fixes.py tests/test_skills_disclosure.py tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py -q` - 99 passed
- `.venv/bin/python -m pytest -q -k 'not test_mcp_server'` - 160 passed, 1 deselected

---

## Update v3.3 (May 14, 2026) - Skills Availability Filtering and SQLite Example

### Overview

Added Agent-facing availability filtering for Skills discovery and introduced a
SQLite-specific monthly sales report example. The availability check now includes
DB compatibility, mutation switch state, and optional table-level schema
readiness. This change keeps startup discovery, SQL validation, mutation class
loading, and execution-time checks eager and unchanged as the security boundary.
`available_only` only changes which cached skill metadata is returned by
`list_skills()`.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` and `SKILLS_CHECK_SCHEMA_ON_LIST`; added `list_skills(..., available_only)`; included current `DB_TYPE`, mutation switch, and schema readiness in skill executability metadata; default Agent-facing catalog hides currently non-executable skills |
| `skills/monthly-sales-report-sqlite/` | Added | Added SQLite query skill using the sample SQLite schema (`orders.order_date`, `orders.total_amount`) |
| `skills/_lib/skill_loader.py` | Modified | Added `profiles` and declarative `tables` frontmatter support; query tables are merged from reviewed SQL extraction and declared tables |
| `skills/monthly-sales-report/skill_def.md` | Modified | Linked to the SQLite counterpart via `related_skills`, kept `databases: [mysql]`, and marked the bundled example as `profiles: [demo]` |
| `skills/update-order-status/skill_def.md` | Modified | Linked to both monthly report examples, marked the skill as `profiles: [demo]`, and declared `tables: [orders]` |
| `skills/SKILLS.md` | Modified | Regenerated/updated catalog to include databases, profiles, and table dependencies |
| `tests/test_skills_disclosure.py` | Modified | Added coverage for default availability filtering, schema readiness, explicit full catalog listing, env default override, DB-specific visibility, and MCP `list_tools()` schemas |
| `.env.example` | Modified | Documented `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1` and `SKILLS_CHECK_SCHEMA_ON_LIST=1` |
| `README.md` / `README_ZH.md` | Modified | Documented `available_only`, schema readiness, demo profiles, the new default behavior, full catalog override, and SQLite skill example |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Documented conditional availability filtering, related design decisions, and external practice references |
| `TEST_MCP_CLIENT_GUIDE.md` | Modified | Updated Skills smoke examples and config hints |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Availability filtering | `available_only` on `list_skills()` | Separate developer/admin listing tool | Keeps the MCP surface small and matches existing discovery workflow; developers can pass `available_only=false` |
| Default availability | `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1` | Preserve full catalog as no-arg default | The tool is Agent-facing, so default discovery should not suggest skills that will fail under the current `DB_TYPE` or mutation switch |
| Schema readiness | `SKILLS_CHECK_SCHEMA_ON_LIST=1` table-existence check | Do no live schema check, or validate every column/type | Catches wrong-schema demo/production mismatches with low overhead while leaving precise validation to execution |
| Security boundary | Keep execution-time compatibility checks | Treat filtering as enforcement | Tool filtering is advisory/ergonomic; callers can still name hidden skills, so execution must remain authoritative |
| SQLite example | Separate `monthly-sales-report-sqlite` skill | One SQL template with dialect branches | Separate skills keep SQL review, startup validation, and Agent selection deterministic |
| Demo profiles | Mark bundled examples with `profiles: [demo]` | Disable examples by default | Keeps examples discoverable for sample databases while making their intended schema explicit |
| Missing `databases` | Keep meaning as all supported DBs | Require every skill to declare databases | Preserves compatibility for portable skills such as `update-order-status` |

### Compatibility Notes

- `ENABLE_SKILLS=0` still registers no Skills tools.
- `list_skills(available_only=false)` restores the full discovered catalog.
- `get_skill_detail(skill_name)` remains available for hidden incompatible or schema-unready skills and includes `executable=false` plus a `disabled_reason`.
- Execution checks still reject database-incompatible or schema-unready skills even if a caller bypasses discovery and directly calls an execution tool.

### External Practice Review

- OpenAI Tool Search supports deferred/client-executed discovery when available tools depend on project or system state; `available_only` is this project's in-MCP analog.
- Anthropic Agent Skills and MCP code-execution guidance emphasize progressive disclosure and loading only relevant definitions.
- Google Gemini function calling best practices recommend keeping the provided tool set relevant and small to reduce selection errors.
- FastMCP annotations and visibility features are useful for presentation and tool surfaces, but annotations are advisory.
- Microsoft function calling guidance emphasizes validating function calls and not relying only on omitted tool definitions as a security control.

### Testing

- `.venv/bin/python -m pytest tests/test_skills_disclosure.py -q` - 19 passed
- `.venv/bin/python -m pytest tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py tests/test_skills_disclosure.py -q` - 92 passed
- `.venv/bin/python -m pytest tests/test_skills_disclosure.py tests/test_skill_loader.py -q` - 74 passed
- `.venv/bin/python -m pytest -q -k 'not test_mcp_server'` - 156 passed, 1 deselected; warning cleanup was completed in v3.4

---

## Update v3.2 (May 12, 2026) - Skills Metadata On-Demand Disclosure

### Overview

Added MCP-level on-demand metadata disclosure for the Skills layer. This change
does **not** lazy-load executable artifacts: `discover()` still validates SQL and
pre-loads mutation classes at startup, and runtime execution still uses the
in-memory cache. Only the Agent-facing metadata projection changed.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `SKILLS_LIST_DEFAULT_DETAIL`; extended `list_skills(search, category, detail_level)`; added `get_skill_detail(skill_name)`; added compact/summary/full metadata projections and category aggregation |
| `skills/_lib/skill_loader.py` | Modified | Added optional `databases` metadata parsing/validation and included supported database types in generated `SKILLS.md` |
| `skills/monthly-sales-report/skill_def.md` | Modified | Declared `databases: [mysql]` because the example SQL uses MySQL-specific date functions |
| `tests/test_skills_disclosure.py` | Added | Tests for default summary disclosure, compact/full projections, search, category filtering, categories aggregation, overlong search rejection, and `get_skill_detail` errors |
| `tests/test_skill_loader.py` | Modified | Added coverage for omitted, scalar, multiple, case-insensitive, empty, and invalid `databases` values |
| `tests/conftest.py` | Modified | Added an engine assertion for SQLite fixture typing/analysis safety |
| `.env.example` | Modified | Added `SKILLS_LIST_DEFAULT_DETAIL=summary` documentation |
| `README.md` / `README_ZH.md` | Modified | Documented `get_skill_detail`, list projection levels, search/category filters, and the new workflow |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Documented metadata disclosure levels and clarified that executable artifacts remain eager-loaded for TOCTOU protection |
| `agent_examples/autogen_sql_agent_new.py` | Modified | Added `get_skill_detail` capability detection and prompt guidance |
| `TEST_MCP_CLIENT_GUIDE.md` | Modified | Updated Skills tool list and configuration example |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Disclosure levels | `compact`, `summary`, `full` | `names` alias or custom field lists | Three stable levels cover discovery, compatibility-oriented metadata, and execution planning without exposing raw source |
| Default detail | `summary` via `SKILLS_LIST_DEFAULT_DETAIL` | Default `full` | Keeps the default useful while reducing unnecessary parameter-schema disclosure; per-call `detail_level` can override |
| Search | Case-insensitive substring | Regex/BM25 | Deterministic, dependency-free, avoids ReDoS and model-generated regex fragility |
| Category handling | Missing category maps to `uncategorized` | Omit category | Gives Agents a stable grouping key and supports category aggregation |
| Detail tool | Add `get_skill_detail(skill_name)` | Add `search_skills` or per-skill tools | One extra read-only tool enables on-demand params without tool explosion |
| Artifact loading | Keep startup eager validation/cache | Runtime disk reads | Preserves TOCTOU protection and existing security model |
| Database compatibility | Optional `databases` field | No DB type declaration | Prevents execution of DB-specific skills on incompatible adapters; omitted field means all supported DB types |

### Compatibility Notes

- `ENABLE_SKILLS=0` remains zero-overhead: no Skills tools are registered.
- Existing execution tools are unchanged.
- `list_skills()` now returns additive metadata fields such as `detail_level`,
  `matched_skills`, `categories`, and `hint`. Clients that need maximum detail
  can call `list_skills(detail_level="full")` or `get_skill_detail(skill_name)`.

### Testing

- `pytest tests/test_skills_disclosure.py -q` - 13 passed
- `pytest tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py tests/test_skills_disclosure.py -q` - 85 passed

---

## Update v3.1 (March 17, 2026) - Explicit Source Declaration

### Overview

Added a mandatory `source` field to `skill_def.md` YAML frontmatter. Each skill must now explicitly declare its execution file (e.g. `source: query.sql`, `source: mutation.py`), replacing the previous convention-based implicit file association (hardcoded `query.sql` and `mutation.py` filenames).

This follows the **Explicit Configuration** principle — the same approach used by GitHub Actions (`action.yml` `main` field), npm (`package.json` `main` field), and Python (`pyproject.toml` entry points).

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `skills/_lib/skill_loader.py` | Modified | Added `source: str` field to `SkillMetadata`; new `_validate_source_filename()` function with security checks (path traversal, hidden files, suffix enforcement); `_parse_skill_md()` extracts and validates `source`; `discover()` uses `metadata.source` instead of hardcoded filenames |
| `skills/monthly-sales-report/skill_def.md` | Modified | Added `source: query.sql` to YAML frontmatter |
| `skills/update-order-status/skill_def.md` | Modified | Added `source: mutation.py` to YAML frontmatter |
| `tests/test_skill_loader.py` | Modified | All fixtures updated with `source` field; 9 new tests added (TestSourceField class): missing source, path traversal, backslash traversal, wrong suffix, mutation wrong suffix, hidden file, custom filename, source stored in metadata |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Section 4: added `source` to YAML schema example; added 5th design rationale (Explicit Configuration principle with industry comparison table); Section 10: added design decision entry |
| `README.md` | Modified | Updated skill_def.md examples and "Adding Custom Skills" section |
| `README_ZH.md` | Modified | Updated skill_def.md examples and "如何添加自定义 Skill" section |
| `REFACTORING_LOG.md` | Modified | This entry |
| `skills/SAFETY.md` | Modified | Updated item #1 to reference explicit `source` field |

### Key Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Field name | `source` | `main`, `entry_point`, `file` | Consistent with web conventions; short and descriptive |
| Mandatory | Required, no default | Optional with convention fallback | User's explicit requirement; prevents ambiguity about file association |
| Suffix enforcement | query→.sql, mutation→.py | No enforcement | Prevents misconfiguration; catches type/file mismatch early |
| Filename validation | Regex + path traversal + hidden file checks | Path-only check | Defense-in-depth: `_validate_source_filename()` enforces safe character set, no path separators, no leading dots |
| Custom filenames | Allowed (e.g. `daily-revenue.sql`) | Fixed names only | Enables descriptive naming while maintaining security through validation |

### Source Filename Validation (`_validate_source_filename()`)

Security checks performed on the `source` field value:
1. Must not be empty
2. Max 128 characters
3. No path separators (`/` or `\\`) — prevents directory traversal
4. Must not start with `.` — prevents hidden files and `..` traversal
5. Must match regex `^[a-zA-Z0-9][a-zA-Z0-9._-]*$` — safe character set
6. Suffix must match skill type: `query` → `.sql`, `mutation` → `.py`
7. Resolved path must stay within skill directory — prevents symlink escape

### Testing

- **125 total tests, 0 failures** — all internal examples and tests migrated; external custom skills require adding `source` field (schema-breaking change)
- 9 new tests in `TestSourceField` class covering all validation paths
- All existing 38 skill_loader tests updated with `source` field and passing

---

## Update v3.0 (March 1, 2026) - Skills Extension Layer

### Overview

Added an optional Skills extension layer for pre-defined, parameterized SQL operations. Skills provide structured Agent interactions with query and mutation support, following Anthropic Agent Skills best practices for progressive disclosure.

**Backward Compatible**: `ENABLE_SKILLS=0` (default) — zero overhead, no tools registered.

### System Architecture (v3.0)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                          LLM / MCP Client (Agent)                            │
└────────────────────────────────┬──────────────────────────────────────────────┘
                                 │  MCP Protocol (stdio / SSE)
                                 ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          mcp_sql_server.py                                   │
│                          (FastMCP v3.0 Server)                               │
│                                                                              │
│   ┌─────── Core Tools (always on) ──────┐  ┌── Skills Tools (opt-in) ──────┐ │
│   │ query()           list_tables()     │  │ list_skills()               │ │
│   │ describe_table()  get_full_schema() │  │ execute_query_skill()       │ │
│   │ check_connection()                  │  │ execute_mutation_skill()    │ │
│   │ [sample()]  [get_table_summary()]   │  │                             │ │
│   │  ↑ ENABLE_SCHEMA_TOOLS opt-in      │  │  ↑ ENABLE_SKILLS opt-in     │ │
│   └──────────────┬──────────────────────┘  └──────────┬─────────────────┘ │
│                  │                                    │                    │
│   ┌──────────────▼────────────────┐    ┌──────────────▼──────────────────┐ │
│   │   sql_safety_checker.py      │    │       skills/_lib/              │ │
│   │   ─────────────────────      │    │   ┌──────────────────────────┐  │ │
│   │   is_sql_safe()  (allowlist) │    │   │ skill_loader.py          │  │ │
│   │   execute_sql()  (runtime)   │    │   │  discover() / load_*()   │  │ │
│   │                              │    │   ├──────────────────────────┤  │ │
│   │   + _is_query_safe_extended()│    │   │ mutation_base.py         │  │ │
│   │   + _check_table_allowlist() │    │   │  MutationBase (ABC)      │  │ │
│   │     (in mcp_sql_server.py)   │    │   ├──────────────────────────┤  │ │
│   └──────────────┬───────────────┘    │   │ audit.py                 │  │ │
│                  │                    │   │  AuditLogger → JSONL     │  │ │
│                  │                    │   └──────────┬───────────────┘  │ │
│                  │                    └──────────────┼──────────────────┘ │
│                  │                                   │                    │
│   ┌──────────────▼───────────────────────────────────▼──────────────────┐ │
│   │                       db_adapter.py                                │ │
│   │                    DatabaseAdapter (ABC)                           │ │
│   │   ┌────────────────────────┐  ┌────────────────────────┐          │ │
│   │   │    MySQLAdapter        │  │    SQLiteAdapter       │          │ │
│   │   │  execute() / execute   │  │  execute() / execute   │          │ │
│   │   │  _write() / get_*()   │  │  _write() / get_*()   │          │ │
│   │   └───────────┬────────────┘  └───────────┬────────────┘          │ │
│   └───────────────┼───────────────────────────┼────────────────────────┘ │
└───────────────────┼───────────────────────────┼──────────────────────────┘
                    │                           │
                    ▼                           ▼
              ┌──────────┐               ┌──────────────┐
              │  MySQL   │               │   SQLite     │
              │ (remote) │               │  (local file)│
              └──────────┘               └──────────────┘
```

### Skills Execution Flow

```
                          ┌─────────────────────────┐
                          │  Server Startup          │
                          └────────────┬─────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │  discover(_skills_dir)   │
                          │  - Scan skill_def.md     │
                          │  - Parse YAML frontmatter│
                          │  - Validate SQL safety   │
                          │  - Cache SkillMetadata   │
                          └────────────┬─────────────┘
                                       ▼
         ┌────────────────────────────────────────────────────────┐
         │                                                        │
  ┌──────▼──────┐       ┌──────────────────┐       ┌─────────────▼─────────────┐
  │ list_skills │       │execute_query_skill│       │  execute_mutation_skill   │
  │             │       │                  │       │                           │
  │ Return:     │       │ 1. validate_name │       │ confirm=false (preview):  │
  │  metadata   │       │ 2. load_query    │       │  1. validate_name         │
  │  (cached)   │       │ 3. validate_params│      │  2. load_mutation         │
  │             │       │ 4. adapter       │       │  3. validate_params       │
  │             │       │    .execute(     │       │  4. mutation.validate()   │
  │             │       │      sql, params)│       │  5. mutation.preview()    │
  └─────────────┘       └──────────────────┘       │  6. audit.log()          │
                                                   │                           │
                                                   │ confirm=true (execute):   │
                                                   │  1-3. (same as above)     │
                                                   │  4. mutation.validate()   │
                                                   │  5. mutation.run_execute()│
                                                   │     → adapter.execute     │
                                                   │       _write(sql, params) │
                                                   │  6. audit.log()          │
                                                   └───────────────────────────┘
```

### Architecture: Skills Directory Convention

```
skills/
├── SAFETY.md                          # Security governance
├── SKILLS.md                          # Auto-generated overview (by discover())
├── _lib/                              # Shared infrastructure
│   ├── __init__.py
│   ├── skill_loader.py                # Discovery, loading, validation (~550 lines)
│   ├── mutation_base.py               # ABC for write operations (~170 lines)
│   └── audit.py                       # JSONL audit logger (~120 lines)
├── monthly-sales-report/              # Example query skill
│   ├── skill_def.md                   # YAML frontmatter + documentation
│   └── query.sql                      # Parameterized SQL template
└── update-order-status/               # Example mutation skill
    ├── skill_def.md                   # YAML frontmatter + documentation
    ├── mutation.py                    # validate/preview/execute logic
    └── references/
        └── status-transitions.md      # State machine documentation
```

### Naming: `skill_def.md` (not `SKILL.md`)

Skill definition files are named `skill_def.md` instead of `SKILL.md` to avoid conflicts with GitHub Copilot / FastMCP's built-in `SKILL.md` skill file format. VS Code's Copilot extension validates `SKILL.md` files against its own schema (expecting attributes like `argument-hint`, `compatibility`, `user-invokable` etc.), which produces false lint errors on our custom YAML frontmatter attributes (`type`, `risk`, `params`, `triggers` etc.).

### New Files

| File | Lines | Description |
|------|-------|-------------|
| `skills/_lib/skill_loader.py` | ~550 | Skill discovery, YAML parsing, SQL safety validation at startup, in-memory caching |
| `skills/_lib/mutation_base.py` | ~170 | ABC for mutations: validate → preview → execute pattern with audit logging |
| `skills/_lib/audit.py` | ~120 | Thread-safe JSONL audit logger with parameter sanitization |
| `skills/SAFETY.md` | — | 16-item security governance document for skill authors |
| `skills/monthly-sales-report/` | — | Example query skill (parameterized SQL) |
| `skills/update-order-status/` | — | Example mutation skill (state machine with optimistic locking) |
| `MCP_AGENTS_SKILLS_DESIGN.md` | ~270 | Design document: architecture, security model, decisions |
| `tests/test_skill_loader.py` | 30 tests | Discovery, parsing, validation, name checks, edge cases |
| `tests/test_query_skills.py` | 8 tests | Parameterized read, write, injection safety |
| `tests/test_mutation_skills.py` | 8 tests | Dry-run, confirm, idempotent, error sanitization |
| `tests/test_audit.py` | 7 tests | JSONL logging, sanitization, directory creation |
| `pyrightconfig.json` | — | Pyright/Pylance config: adds `skills/_lib` to `extraPaths` for import resolution, sets `reportMissingImports` to warning |

### Modified Files

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | v3.0 header, `ToolError` import, Skills config, 3 new MCP tools (`list_skills`, `execute_query_skill`, `execute_mutation_skill`), updated `sql_assistant` prompt |
| `db_adapter.py` | Modified | `execute()` accepts optional `params`, new `execute_write()` for transactions, unified `_handle_error(self, e, timeout=None)` |
| `start_server.py` | Modified | `validate_environment()` is now DB_TYPE-aware (MySQL vs SQLite) |
| `requirements.txt` | Modified | Added `pyyaml`, changed `SQLAlchemy` to `SQLAlchemy>=2.0` |
| `.env.example` | Modified | Added `ENABLE_SKILLS`, `SKILLS_ALLOW_MUTATIONS`, `SKILLS_DIR`, `SKILLS_AUDIT_LOG` |
| `README.md` | Modified | Version badge 3.0, v3.0 changelog, roadmap updated |
| `README_ZH.md` | Modified | Same updates in Chinese |

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tool architecture | 2-3 unified tools (list/query/mutation) | Prevents tool explosion (Google Gemini 10-20 rule) |
| Metadata format | `skill_def.md` YAML frontmatter | Anthropic Skills spec alignment, avoids VS Code conflict |
| SQL caching | discover() caches at startup | Eliminates TOCTOU (time-of-check-time-of-use) risks |
| Write safety | 3-stage validate/preview/execute | Anthropic "verifiable intermediate outputs" pattern |
| Error handling | ToolError propagation | FastMCP ToolError bypasses `mask_error_details` |
| Audit storage | JSONL file | Minimal dependency for MVP |

### Security Model (SAFETY.md)

1. Template = Whitelist — only pre-defined SQL/Python in `skills/` is executed
2. Parameterized queries via SQLAlchemy `text()` + named parameters
3. Dual switch: `ENABLE_SKILLS` (master) + `SKILLS_ALLOW_MUTATIONS` (second)
4. Startup SQL safety validation via `is_sql_safe()` (defense-in-depth)
5. Skill name regex `^[a-z0-9][a-z0-9-]*$` prevents path traversal
6. SKILLS_DIR constrained to project root
7. Error sanitization through `ToolError` (no internal detail leaks)

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SKILLS` | `0` | Master switch for skills extension |
| `SKILLS_ALLOW_MUTATIONS` | `0` | Enable mutation skills (requires `ENABLE_SKILLS=1`) |
| `SKILLS_DIR` | `skills/` | Skills directory path (must be under project root) |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | Audit log file path |

### Testing

- **64 new tests** across 4 files (all pass)
- **53 existing tests** unchanged (all pass)
- **117 total tests, 0 failures** — backward compatibility confirmed
- All tests use SQLite in-memory databases for speed and isolation
- Key finding: SQLAlchemy Row objects use attribute access (`.column_name`) not dict access (`["column_name"]`)

> **Design Documentation:** See [MCP_AGENTS_SKILLS_DESIGN.md](MCP_AGENTS_SKILLS_DESIGN.md) for full architecture details.

### Post-Implementation Audit (March 1, 2026)

Code review following MCP Spec §7, Anthropic, Google Gemini, and Microsoft best practices.

#### Issues Found & Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | P0 Security | `_is_query_safe_extended` leaked regex pattern in error message (`f"SHOW command not allowed for security: {pattern}"`) | Replaced with generic message: `"This SHOW command is not allowed for security reasons"` |
| 2 | P0 Security | `INFORMATION_SCHEMA` bypass: `query("SELECT * FROM INFORMATION_SCHEMA.TABLES")` could bypass `ALLOWED_TABLES` controls, exposing restricted table names | Added `information_schema` to blocked system databases pattern |
| 3 | P1 Logic | `sample()` tool used MySQL-specific backtick quoting (`\`table\``) — would fail on SQLite | Dynamic quoting: backtick for MySQL, double-quote for SQLite via `adapter.db_type` |
| 4 | P1 Logic | `get_table_summary()` bypassed adapter layer, used MySQL-only `INFORMATION_SCHEMA` SQL directly | Refactored to use `adapter.get_row_estimate()` and `adapter.get_columns()` |
| 5 | P2 Quality | `import json` inside `_truncate_result()` function body | Moved to module-level imports |
| 6 | P2 Quality | `ALLOWED_SHOW_COMMANDS` set was dead code (defined but never referenced) | Removed |
| 7 | P2 Quality | `_is_valid_identifier` had redundant `dangerous_patterns` check | Added comment noting it's defense-in-depth (kept) |
| 8 | P0 Type | Pylance reported `_project_root`/`_skills_dir`/`Field` possibly unbound in Skills conditional blocks | Moved `sys`, `Path`, `Annotated`, `Field` imports to module level; pre-initialized path variables |
| 9 | P1 Type | `DatabaseAdapter` ABC missing `_handle_error()` method — Pylance couldn't resolve calls on abstract type | Added `_handle_error()` as a concrete method in `DatabaseAdapter` (default: returns generic error string) |
| 10 | P1 Type | `skill_loader.py`: `importlib.util.spec_from_file_location()` returns `Optional[ModuleSpec]`, but `spec` and `spec.loader` used without None check | Added explicit `None` guard with clear `ImportError` message |
| 11 | P2 Type | `mutation.py`: SQLAlchemy `Row.status` attribute access unrecognized by Pylance (dynamic attribute) | Added `# type: ignore[union-attr]` annotations (3 locations) |
| 12 | P2 Type | `test_query_skills.py` / `test_mutation_skills.py`: `adapter._engine` could be `None` before `connect()` | Added `assert adapter._engine is not None` after `connect()` |
| 13 | P0 Bug | `execute_write()` fails on MySQL: `connection.begin()` conflicts with SQLAlchemy 2.0 autobegin — `SET SESSION MAX_EXECUTION_TIME` triggers autobegin, then explicit `begin()` raises `InvalidRequestError` | Replaced `engine.connect()` + `connection.begin()` with `engine.begin()` context manager (both MySQL and SQLite adapters) |
| 14 | P2 Perf | `load_mutation()` re-executes `exec_module()` on every call — disk I/O + module compilation per mutation invocation | Pre-load mutation module class in `discover()` at startup, cache in `SkillMetadata._mutation_class`; `load_mutation()` now only instantiates from cache |
| 15 | P2 Security | `validate_params()` silently ignores extra parameters not defined in schema — defense-in-depth gap | Added `unexpected = set(params) - set(schema)` check at start; raises `ValueError` listing unexpected keys |
| 16 | P3 Robustness | `AuditLogger.__init__` calls `mkdir()` without error handling — `PermissionError` crashes entire Skills initialization | Wrapped `mkdir()` in try-except `OSError`; logs warning but allows AuditLogger to construct |
| 17 | P1 Logic | `mutation.py execute()` returns `{"success": False}` on failure instead of raising exception — bypasses `run_execute()` error handling chain, causes semantic contradiction (`{"success": True, "result": {"success": False}}`) in MCP tool response, and `run_execute()` `except ToolError` path lacked audit logging | Changed `execute()` to `raise ToolError(...)` on order-not-found and optimistic lock failure; added audit logging to `run_execute()` `except ToolError` path before re-raising |
| 18 | P2 Type | `SkillMetadata._mutation_class: type \| None` — Pylance reports "Variable not allowed in type expression". Python 3.12 introduced `type` as a soft keyword for type alias statements (`type X = ...`), causing Pylance to misparse the built-in `type` in annotation context within a `@dataclass` | Added `from __future__ import annotations` (PEP 563) to `skill_loader.py` — defers all annotation evaluation to string form, bypassing the `type` soft keyword parsing conflict |
| 19 | P1 Semantics | MySQL `execute_write()` used `MAX_EXECUTION_TIME`, but MySQL documents that mechanism as SELECT/read-query oriented and live validation showed `UPDATE ... SLEEP(2)` still succeeded under `timeout=1` | Removed write-path `MAX_EXECUTION_TIME`; `execute_write()` now sets session `innodb_lock_wait_timeout` for InnoDB row-lock waits and fails closed if that guard cannot be configured. Remaining DML CPU/IO runtime limits are documented as driver/deployment scope. |

#### Noted (Not Fixed — Design Decisions)

| # | Topic | Note |
|---|-------|------|
| A | Error pattern inconsistency | Core tools return `{"success": False, "error": ...}`, Skills tools raise `ToolError`. MCP Spec §6 favors `isError: true` (which ToolError maps to), but changing core tools would break backward compatibility. |
| B | Rate limiting | Not implemented — acceptable for the current trusted single-operator/stdin-first mutation boundary. Any future remote or multi-user design must add ingress and/or per-principal limits rather than treating an HTTP transport as the control. |
| C | CTE/WITH bypass | `_is_query_safe_extended` blocks `FROM (subquery)` but not `WITH ... AS` (CTE). Low risk since `is_sql_safe()` already restricts statement types to SELECT. |
| D | Lifespan cleanup | `lifespan()` context manager doesn't call `reset_adapter()` on shutdown. Minor — Python process exit cleans up resources. |
| E | `query.sql` MySQL-only functions | `monthly-sales-report/query.sql` uses `YEAR()`/`MONTH()` — MySQL-specific, not supported by SQLite. Acceptable as an example skill for a MySQL-primary project. `skill_def.md` Notes already marks it MySQL-only. Cross-database compatibility is the skill author's responsibility. |
| F | `_extract_table_names()` ignores `schema.table` | `skill_loader.py`'s `_extract_table_names()` regex doesn't handle `schema.table` format, but this function is only used for generating the `SKILLS.md` overview document — not involved in security validation. The core security path `_extract_tables_from_sql()` in `mcp_sql_server.py` already handles `schema.table` correctly (fixed in Bug Fix 1). |
| G | Mutation `execute()` duplicate SELECT | Superseded in v3.6.1: the bundled state-sensitive Skill's unbound `execute()` fails closed. Preview displays and binds one state read; `execute_with_binding()` applies the optimistic lock to that bound value. |
| H | Mutation read-write transaction gap | Superseded by the v3.6 preview-state binding contract for the bundled Skill. The preview read and later write remain separate operations by design, while the final `WHERE status = :expected_status` rejects execute-time drift from the displayed state. The narrower external-writer ABA boundary is tracked in DRR-2026-046. |
| I | `execute_mutation_skill` double audit risk | Resolved in v3.6.1: `run_execute()` owns execution success/failure audit. After it returns successfully, the MCP layer marks the write complete; a later context/response failure no longer appends a contradictory execute-failure audit and instead tells the caller to verify current database state. |
| J | `_sanitize_params()` flat-only | `audit.py`'s `_sanitize_params()` only truncates top-level `str` values >500 chars, does not recurse into nested `dict`/`list`. No impact — current skill frontmatter schema only defines atomic types (`int`/`float`/`str`/`bool`). If future skills add complex parameter types, this should be revisited. |
| K | `_coerce_type()` bool conversion | Resolved: bool parameters accept native booleans and explicit `"true"`/`"false"` strings; other values fail validation instead of using Python truthiness. Regression coverage is tracked under DRR-2026-020. |

### Live Integration Test Report (March 1, 2026)

End-to-end functional verification against production MySQL database (`trade_data_analysis` on `192.168.1.113`).  
All 10 MCP tools tested via VS Code MCP Client → FastMCP 3.0.2 stdio transport.

#### Test Environment

| Item | Value |
|------|-------|
| Database | MySQL 8.x, `trade_data_analysis` |
| Production tables | 6 tables, largest `trade_data_analysis_log` (~138K rows, 57 columns, Chinese A-stock data) |
| Test tables | `orders` (5 rows), `test_users` (2 rows) — created for testing, cleaned up after |
| Skills config | `ENABLE_SKILLS=1`, `SKILLS_ALLOW_MUTATIONS=1` |
| Sample skills | `monthly-sales-report` (query), `update-order-status` (mutation) |

#### Phase 1: Core Tools — All Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 1 | `check_connection` | Connect to MySQL | ✅ `"MySQL connection successful"` |
| 2 | `list_tables` | List all tables | ✅ 7 tables returned (6 production + 1 test) with estimated row counts |
| 3 | `describe_table` | `test_users` (small table) | ✅ 2 columns (id, name), 2 rows |
| 4 | `describe_table` | `trade_data_analysis_log` (large table) | ✅ 57 columns, ~135K rows, `is_large=true` |
| 5 | `query` | `SELECT * FROM test_users` | ✅ Returns Alice, Bob |
| 6 | `query` | Aggregation: `COUNT(*)`, `COUNT(DISTINCT ...)`, `GROUP BY` on 138K rows | ✅ 138K records, 6408 stocks, 87 industries |
| 7 | `query` | `GROUP BY industry ORDER BY cnt DESC LIMIT 10` | ✅ Top 10 industries by stock count |
| 8 | `query` | **Security**: `DROP TABLE test_users` | ✅ **Blocked**: `"Only read-only queries allowed"` |
| 9 | `get_full_schema` | Full database schema dump | ✅ All 7 tables with columns, ~35KB response |

#### Phase 2: Skills Discovery — Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 10 | `list_skills` | Discover available skills | ✅ 2 skills found: `monthly-sales-report` (query/low), `update-order-status` (mutation/high) |

#### Phase 3: Query Skill — All Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 11 | `execute_query_skill` | `monthly-sales-report` (before test data) | ✅ Error correctly: `"Table or column not found"` (orders table didn't exist yet) |
| 12 | `execute_query_skill` | `monthly-sales-report` with `{year:2026, month:1}` (after creating orders) | ✅ **Success**: 5 daily rows with `order_count`, `revenue`, `avg_order_value` |
| 13 | `execute_query_skill` | `nonexistent-skill` | ✅ Error correctly: `"Skill not found"` |

#### Phase 4: Mutation Skill — Bug Found & Fixed

| # | Tool | Test | Result |
|---|------|------|--------|
| 14 | `execute_mutation_skill` | Dry-run (`confirm=false`): `{order_id:1, new_status:"confirmed"}` | ✅ Preview returned UPDATE SQL with optimistic locking |
| 15 | `execute_mutation_skill` | Execute (`confirm=true`) — **BEFORE FIX** | ❌ **FAILED**: `"Database query failed"` |
| 16 | (diagnosis) | Root cause analysis | 🔍 `InvalidRequestError: This connection has already initialized a Transaction() object via begin() or autobegin; can't call begin() here` |
| 17 | `execute_mutation_skill` | Execute (`confirm=true`) — **AFTER FIX** | ✅ **Success**: `pending` → `confirmed`, `rowcount: 1` |
| 18 | `execute_mutation_skill` | Chained transition: `confirmed` → `shipped` | ✅ **Success**: `rowcount: 1` |
| 19 | `execute_mutation_skill` | **Security**: illegal transition `shipped` → `pending` | ✅ **Blocked**: `"Transition from 'shipped' to 'pending' is not allowed. Allowed: ['delivered', 'returned']"` |

#### Bug #13: `execute_write()` SQLAlchemy autobegin conflict

**Symptom**: `execute_mutation_skill(confirm=true)` returns `"Error: Database query failed"` on MySQL.  
Dry-run (preview) works; confirm (execute) fails. Data unchanged.

**Root Cause**: In `MySQLAdapter.execute_write()`:

```python
# BEFORE (buggy)
with self._engine.connect() as connection:
    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
    # ↑ This triggers SQLAlchemy 2.0 autobegin (implicit transaction)
    
    with connection.begin():  # ← FAILS: autobegin already active
        result = connection.execute(text(sql), params)
```

SQLAlchemy 2.0 uses "autobegin" — any `execute()` call on a connection implicitly starts a transaction. The `SET SESSION MAX_EXECUTION_TIME` call activated autobegin, then the explicit `connection.begin()` raised `InvalidRequestError` because a transaction was already in progress.

**Why unit tests didn't catch it**: All 111 tests use SQLite in-memory with `StaticPool` (shared single connection), where the connection lifecycle differs. The timeout mechanism uses `set_progress_handler()` instead of `SET SESSION`, so the autobegin trigger path doesn't exist in SQLite tests.

**Fix**: Replace `engine.connect()` + `connection.begin()` with `engine.begin()`:

```python
# AFTER (fixed) — both MySQL and SQLite adapters
with self._engine.begin() as connection:  # explicit transaction from the start
    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
    result = connection.execute(text(sql), params)
    # auto-commit on context exit, auto-rollback on exception
```

`engine.begin()` creates a connection with an explicit transaction from the start, avoiding the autobegin conflict. All subsequent `execute()` calls within this context operate within the same transaction.

**Verification**: After fix, mutation skill confirmed working (tests #17-19 above). 111 unit tests remain green.

#### Phase 5: Cleanup

| Action | Result |
|--------|--------|
| Drop `orders` table | ✅ Removed from production DB |
| Drop `test_users` table | ✅ Removed from production DB |
| Verify table count | ✅ 6 original tables remain |

#### Summary

| Category | Tests | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Core tools | 9 | 9 | 0 | Including security block |
| Skills discovery | 1 | 1 | 0 | |
| Query skill | 3 | 3 | 0 | Including error cases |
| Mutation skill | 6 | 5 | 1 | 1 failure → bug found → fixed → re-verified |
| **Total** | **19** | **18** | **1** | **Bug #13 found, fixed, verified** |

All 10 MCP tools verified functional. One P0 bug discovered and fixed during testing.  
111 unit tests pass after fix. Test environment cleaned up — no residual test data in production.

---

## Update (January 13, 2026) - GitHub Repository Rename

This update records a repository-level rename (no functional code changes).

- **Old repo name:** `vibe-coding-gemini-llm-execute-sql-tools`
- **New repo name:** `llm-sql-safety-executor-mcp`
- **New URL:** https://github.com/Firstmeridian/llm-sql-safety-executor-mcp

### Local Git Update

After renaming on GitHub, update your local `origin` remote to avoid relying on redirects:

```bash
git remote -v
git remote set-url origin https://github.com/Firstmeridian/llm-sql-safety-executor-mcp.git
git remote -v

# optional verification
git fetch origin --prune
```

---

## Update v2.2 (January 15, 2026) - SQLite Database Support

### Overview

Added SQLite database support while maintaining full backward compatibility with MySQL. This enables the MCP server to work with lightweight SQLite databases for development, testing, and embedded use cases.

### Architecture: Database Adapter Pattern

Introduced `db_adapter.py` implementing the Abstract Base Class (ABC) pattern:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE ADAPTER ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                          ┌─────────────────────┐                            │
│                          │  DatabaseAdapter    │ (ABC)                      │
│                          │  ─────────────────  │                            │
│                          │  + connect()        │                            │
│                          │  + execute()        │                            │
│                          │  + get_tables()     │                            │
│                          │  + get_columns()    │                            │
│                          │  + get_row_estimate()│                           │
│                          │  + check_connection()│                           │
│                          │  + get_database_name()│                          │
│                          │  + close()          │                            │
│                          │  + db_type (property)│                           │
│                          └─────────┬───────────┘                            │
│                                    │                                        │
│                    ┌───────────────┴───────────────┐                        │
│                    │                               │                        │
│           ┌────────▼────────┐             ┌───────▼────────┐                │
│           │   MySQLAdapter  │             │  SQLiteAdapter │                │
│           │  ─────────────  │             │  ────────────  │                │
│           │  - SQLAlchemy   │             │  - SQLAlchemy  │                │
│           │  - PyMySQL      │             │  - sqlite3     │                │
│           │  - QueuePool    │             │  - StaticPool  │                │
│           │  - MAX_EXEC_TIME│             │  - progress_   │                │
│           │                 │             │    handler     │                │
│           └─────────────────┘             └────────────────┘                │
│                                                                             │
│                          ┌─────────────────────┐                            │
│                          │  create_adapter()   │ (Factory)                  │
│                          │  ─────────────────  │                            │
│                          │  DB_TYPE → Adapter  │                            │
│                          └─────────────────────┘                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | **NEW** (749 lines) | Database adapter abstraction layer |
| `sql_safety_checker.py` | Modified | Now uses adapter; removed MySQL-specific code |
| `mcp_sql_server.py` | Modified | Uses adapter methods; adds `db_type` to responses |
| `.env.example` | Modified | Added SQLite configuration section |
| `.env` | Modified | Added SQLite configuration section |
| `README.md` | Modified | v2.2 changelog, SQLite config docs |
| `README_ZH.md` | Modified | v2.2 changelog, SQLite config docs |
| `tests/conftest.py` | **NEW** (318 lines) | Pytest fixtures for SQLite/MySQL tests |
| `tests/test_db_adapter.py` | **NEW** | Unit tests for adapters |
| `tests/test_sqlite_integration.py` | **NEW** | SQLite integration tests |
| `requirements.txt` | Modified | Added `pytest` dependency |

> **Detailed Design Documentation:** See [SQLITE_ADAPTER_DESIGN.md](SQLITE_ADAPTER_DESIGN.md) for design decisions, conventions, compromises, potential issues, and implementation details.

---

## Update v2.1 (January 4, 2026) - Tool Optimization & Field Naming

### Major Changes

#### 1. `get_table_summary` Now Optional (Default: Disabled)

**Rationale:** The `describe_table()` tool already provides estimated row counts from INFORMATION_SCHEMA. The `get_table_summary()` tool with its optional `COUNT(*)` feature is only needed when exact counts are required.

**Configuration:**
```env
# Default: disabled (describe_table provides estimates)
ENABLE_TABLE_SUMMARY=0

# Enable when exact counts via COUNT(*) are needed
ENABLE_TABLE_SUMMARY=1
```

**New Parameters:**
- `exact_count` (bool, default: False): When True, runs COUNT(*) for precise count (slow on large tables)

#### 2. `describe_table` Enhanced with Row Count and Hints

**New Output Fields:**
```json
{
  "row_count": 1500,
  "row_count_approximate": true,
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
}
```

**Benefits:**
- Eliminates need for separate `get_table_summary()` call in most cases
- Provides query planning hints based on `LARGE_TABLE_THRESHOLD`

#### 3. `list_tables` Output Restructured

**Before:**
```json
{
  "success": true,
  "data": [...],
  "table_count": 2
}
```

**After:**
```json
{
  "success": true,
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [...],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null
}
```

**Field Naming Convention:**
- `returned_table_count`: Number of tables in response (after truncation)
- `total_tables`: Visible tables (after allowlist filtering, before truncation)
- `tables`: Renamed from `data` for clarity

#### 4. `get_full_schema` Output Aligned

Same field naming convention applied:
- `returned_table_count` instead of `table_count`
- `total_tables` field added
- `truncated` and `truncation_note` always present

#### 5. New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TABLE_SUMMARY` | 0 | Enable `get_table_summary()` tool |
| `LARGE_TABLE_THRESHOLD` | 1000 | Rows threshold for `is_large` flag |
| `MAX_OVERVIEW_TABLES` | 100 | Max tables in `list_tables()` |

#### 6. AutoGen Agent Prompts Updated

Removed `get_table_summary()` references from agent prompts since:
- Tool is disabled by default
- `describe_table()` now provides equivalent functionality

Updated workflow guidance:
```
- For unknown tables: list_tables() → describe_table()
- For multi-table JOINs: get_full_schema()
- Check is_large flag in describe_table response
```

### Files Changed

| File | Changes |
|------|---------|
| `mcp_sql_server.py` | Tool restructuring, field naming, new env vars |
| `.env.example` | New environment variable documentation |
| `autogen_sql_agent.py` | Updated prompts, removed get_table_summary refs |
| `test_mcp_client.py` | Validate new field structure |
| `test_bug_fixes.py` | Updated tests for new fields |

---

## Previous Update (December 29, 2025) - Bug Fixes

### Bug Fix 1: Schema.table Regex Extraction (P1)

**Problem:** `_extract_tables_from_sql()` incorrectly extracted schema name instead of table name when using `schema.table` syntax (e.g., `SELECT * FROM mydb.users` extracted "mydb" instead of "users").

**Impact:** Table allowlist validation could incorrectly block/allow queries when using schema-qualified table names.

**Root Cause:****
```python
# Old regex - captures first identifier (schema)
from_join_pattern = r'(?:FROM|JOIN)\s+`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
```

**Fix:** Updated regex to handle optional schema prefix and capture only the table name:
```python
# Fixed regex - skips optional schema., captures table name
from_join_pattern = r'(?:FROM|JOIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
```

**Test Cases Verified:**
- `SELECT * FROM mydb.users` → extracts "users" ✅
- `SELECT * FROM \`mydb\`.\`users\`` → extracts "users" ✅
- `DESCRIBE mydb.products` → extracts "products" ✅

### Bug Fix 2: sql_assistant Prompt Display for ALLOWED_TABLES=* (P2)

**Problem:** When `ALLOWED_TABLES=*` was set, the prompt displayed "UNION enabled (tables: *)" which was unclear to LLMs.

**Fix:** Added special handling to display "all tables" instead of "*":
```python
# Before
cross_table = f"UNION enabled (tables: {', '.join(sorted(ALLOWED_TABLES))})"
# Output: "UNION enabled (tables: *)"

# After
if "*" in ALLOWED_TABLES:
    tables_desc = "all tables"
else:
    tables_desc = ', '.join(sorted(ALLOWED_TABLES))
cross_table = f"UNION enabled ({tables_desc})"
# Output: "UNION enabled (all tables)"
```

### Bug Fix 3: get_full_schema Truncation Protection (P0)

**Problem:** `get_full_schema()` could return extremely large responses for databases with many tables (100+ tables with 30+ columns each could exceed 200K+ characters), causing LLM context overflow.

**Fix:** Added truncation protection with `MAX_SCHEMA_TABLES = 50`:
```python
MAX_SCHEMA_TABLES = 50  # Reasonable limit for most LLM contexts
total_tables = len(tables_data)
truncated = False

if total_tables > MAX_SCHEMA_TABLES:
    tables_data = tables_data[:MAX_SCHEMA_TABLES]
    truncated = True
    await ctx.warning(f"Schema truncated: showing {MAX_SCHEMA_TABLES}/{total_tables} tables")

# ... (build schema) ...

if truncated:
    result["truncated"] = True
    result["truncation_note"] = f"Showing {MAX_SCHEMA_TABLES}/{total_tables} tables. Use describe_table(table_name) for specific tables not shown."
```

**Size Estimates:**
| Database Size | Tables | Estimated Chars | Truncated? |
|--------------|--------|-----------------|------------|
| Small | 10 | ~9K | No |
| Medium | 50 | ~88K | At limit |
| Large | 100 | ~260K | Yes → 50 |
| Very Large | 200 | ~860K | Yes → 50 |

---

### Previous Fix: ALLOWED_TABLES=* Filtering Issue

**Problem:** When `ALLOWED_TABLES=*` was set, `list_tables()` and `get_full_schema()` returned empty results because the filter logic checked if table names were literally in the set `{"*"}`.

**Root Cause:**
```python
# Buggy code
if ALLOWED_TABLES is not None:
    data = [t for t in data if t["table_name"].lower() in ALLOWED_TABLES]
    # ALLOWED_TABLES = {"*"}, no table name equals "*", so all filtered out!
```

**Fix:** Added check to skip filtering when `"*"` is in the allowlist:
```python
# Fixed code
if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
    data = [t for t in data if t["table_name"].lower() in ALLOWED_TABLES]
```

**Affected Functions:**
- `list_tables()` - Line ~552
- `get_full_schema()` - Line ~683

### Configuration Improvements & Truncation Optimization

This update relaxes default truncation limits, adds `ALLOWED_TABLES=*` support, and simplifies error messages.

#### 1. Relaxed Default Truncation Limits

| Setting | Before | After | Reason |
|---------|--------|-------|--------|
| `MAX_RESULT_ROWS` | 50 | 100 | More practical for analysis tasks |
| `MAX_RESULT_CHARS` | 8000 | 16000 | Reduces premature truncation |

#### 2. Disable Truncation Support

Set `MAX_RESULT_ROWS=0` or `MAX_RESULT_CHARS=0` to disable respective limits:

```env
# Disable all truncation (for data export scenarios)
MAX_RESULT_ROWS=0
MAX_RESULT_CHARS=0
```

#### 3. ALLOWED_TABLES=* Support

Added special value `*` to explicitly allow all tables (required for UNION with unrestricted access):

```env
# Enable UNION and allow all tables
ALLOW_UNION=1
ALLOWED_TABLES=*
```

**Behavior:**
- `ALLOWED_TABLES=` (empty): Allow all tables for normal queries, but UNION still blocked
- `ALLOWED_TABLES=*`: Explicitly allow all tables, enables UNION when `ALLOW_UNION=1`
- `ALLOWED_TABLES=t1,t2`: Only allow specified tables

#### 4. Simplified Truncation Messages

Reduced truncation note length to minimize token consumption:

| Before | After |
|--------|-------|
| `"Results truncated to 50 rows. Use 'SELECT ... LIMIT n' for precise control. Total available: 200 rows."` | `"Showing 100/200 rows. Use LIMIT clause for full control."` |

#### 5. Simplified UNION Error Message

| Before | After |
|--------|-------|
| `"UNION queries require ALLOWED_TABLES to be configured. Set ALLOWED_TABLES environment variable or use separate queries."` | `"UNION requires ALLOWED_TABLES. Set ALLOWED_TABLES=table1,table2 or ALLOWED_TABLES=* to enable."` |

#### Files Changed

| File | Change |
|------|--------|
| `mcp_sql_server.py` | Relaxed defaults, added `*` support, simplified messages |
| `.env.example` | Updated documentation and default values |

---

## Update (December 23, 2025)

### Security & Token Optimization

This update adds configurable UNION query policy, startup logging, and significant prompt optimization following OpenAI/Google best practices.

#### 1. ALLOW_UNION Configuration (P2 Security)

Added configurable UNION query handling for flexible security vs efficiency trade-off:

| Setting | Behavior | Use Case |
|---------|----------|----------|
| `ALLOW_UNION=0` (default) | Block UNION, guide LLM to multiple queries | Maximum security |
| `ALLOW_UNION=1` + `ALLOWED_TABLES` | Allow UNION with table validation | Efficiency mode |
| `ALLOW_UNION=1` without allowlist | Block UNION (requires allowlist) | Defense-in-depth |

**Configuration Example (.env):**
```env
# P2: UNION Query Policy (0=disabled/safer, 1=enabled with table allowlist)
ALLOW_UNION=0

# Required when ALLOW_UNION=1
ALLOWED_TABLES=customers,orders,products
```

#### 2. Startup Logging for Security Configuration

Added logging at module load to confirm security settings:

```python
# Log security configuration at module load
if ALLOW_UNION:
    if ALLOWED_TABLES:
        logger.info(f"UNION queries enabled with table allowlist: {sorted(ALLOWED_TABLES)}")
    else:
        logger.warning("ALLOW_UNION=1 but no ALLOWED_TABLES configured - UNION will be blocked")
else:
    logger.info("UNION queries disabled (default safe mode)")
```

#### 3. Prompt Token Optimization (69% Reduction)

Significantly reduced `sql_assistant` prompt size following OpenAI/Google best practices:

> **Google**: "Token limits: function descriptions and parameters count toward input token limits"
> **OpenAI**: "If you run into token limits, we suggest limiting the number of functions or the length of the descriptions"

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Characters | 1,224 | 376 | -69% |
| Tokens (approx) | ~306 | ~94 | -69% |

**Before (verbose):**
```python
"""Database query assistant with READ-ONLY access.

TOOLS:
1. query(sql) - PRIMARY. Execute SELECT, SHOW, DESCRIBE, or non-ANALYZE EXPLAIN. (Historical v2 wording; v3.7 full MCP policy rejects raw SHOW.)
2. list_tables() - List available tables (use if structure unknown)
3. describe_table(name) - Get single table columns
4. get_full_schema() - Get ALL tables and columns in ONE call (recommended first)
5. get_table_summary(name) - Get table statistics without raw data
6. sample(table, limit) - Preview table data

QUERY GUIDELINES:
- Use JOINs for combining related tables (INNER JOIN, LEFT JOIN)
- Use aggregation (COUNT, SUM, GROUP BY) instead of fetching all rows
- Always include LIMIT for large result sets

UNION QUERIES:
- UNION is enabled for combining results from multiple tables
- All tables in UNION must be in allowlist: customers, orders, products
- Example: SELECT id, name FROM products UNION SELECT id, title FROM categories

WORKFLOW (Token Optimized):
- Start with: get_full_schema() to understand database structure
- For large tables: get_table_summary() first, then query with LIMIT
- Prefer aggregation over raw data retrieval

Always show executed SQL in response. Format results as readable tables."""
```

**After (optimized):**
```python
"""READ-ONLY SQL assistant. Tools: query (primary), get_full_schema, list_tables, describe_table, get_table_summary, sample.

Workflow: get_full_schema() first → query with LIMIT for large tables.
Guidelines: Use aggregation (COUNT/GROUP BY) over raw data. UNION enabled (tables: customers, orders, products). Use JOINs for related data.
Always show SQL in response."""
```

**Key optimization principles applied:**
- Remove redundant tool descriptions (already in docstrings)
- Combine related guidelines into single sentences
- Remove examples (LLM can infer from context)
- Dynamic UNION guidance based on configuration

#### Files Changed

| File | Change |
|------|--------|
| `mcp_sql_server.py` | Added ALLOW_UNION config, startup logging, optimized prompt |
| `.env.example` | Added ALLOW_UNION=0 documentation |

#### References

- [OpenAI Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling)
- [Google Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [FastMCP Prompts Documentation](https://github.com/jlowin/fastmcp)

---

## Update (December 15, 2025)

### Extended SQL Statement Support

Added support for additional read-only SQL statement types beyond SELECT:

| Statement | Purpose | Example |
|-----------|---------|---------|
| `SELECT` | Data retrieval | `SELECT * FROM users` |
| `SHOW` | Database metadata | `SHOW TABLES`, `SHOW COLUMNS FROM users` |
| `DESCRIBE` | Table structure | `DESCRIBE users` |
| `EXPLAIN` | Query plan analysis | `EXPLAIN SELECT * FROM users` |

**Files Changed:**
- `sql_safety_checker.py`: Added `SAFE_SQL_TYPES` constant and updated `is_sql_safe()` function
- `mcp_sql_server.py`: Updated instructions, tool descriptions, and prompts
- `README.md`: Updated documentation to reflect new capabilities

**Server Instructions Updated:**
```python
instructions="""You are a database query assistant with READ-ONLY access.
Use the query tool for most operations. Safe statements: SELECT, SHOW,
DESCRIBE, and non-ANALYZE EXPLAIN. (Historical v2 wording; v3.7 full MCP policy rejects raw SHOW.)
Use list_tables first if you don't know the database structure.
If first time querying or unsure about columns: list_tables() -> describe_table() -> query()
If you already know the table structure: query directly"""
```

---

## Changes Summary (v2.0 vs. v1.0)

### 1. Code Reduction
- **Before:** ~460 lines
- **After:** ~280 lines
- **Reduction:** ~40% less code while maintaining functionality

### 2. Tool Consolidation

| Old Tools | New Tools | Reason |
|-----------|-----------|--------|
| `validate_sql_query` | *(removed)* | Validation is now automatic inside `query()` |
| `execute_safe_sql` | `query` | Renamed for clarity and brevity |
| `check_database_connection` | `check_connection` | Renamed, kept for backward compatibility |
| `get_table_schema` | `describe_table` | Matches SQL `DESCRIBE` command |
| `get_sample_data` | `sample` | Shorter, more intuitive name |
| `get_server_info` | *(removed)* | Rarely used, low value |
| *(new)* | `list_tables` | Essential for database discovery |
| *(new - Dec 23)* | `get_full_schema` | Token optimization: Get all tables/columns in ONE call |
| *(new - Dec 23)* | `get_table_summary` | Token optimization: Get table stats without raw data |

**Summary:**
- Original: 6 tools → Now: 7 tools
- 2 removed (`validate_sql_query`, `get_server_info`)
- 3 added (`list_tables`, `get_full_schema`, `get_table_summary`)
- 4 renamed

### Tool Migration Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOOL MIGRATION MAP                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   OLD TOOLS (6)                              NEW TOOLS (7)                  │
│   ═══════════                                ════════════                   │
│                                                                             │
│   ┌──────────────────────┐                                                  │
│   │  validate_sql_query  │ ──────┐                                          │
│   └──────────────────────┘       │  (merged)   ┌─────────────┐              │
│                                  ├───────────► │    query    │              │
│   ┌──────────────────────┐       │             └─────────────┘              │
│   │   execute_safe_sql   │ ──────┘                                          │
│   └──────────────────────┘                                                  │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │check_database_connection│ ─────────► │  check_connection │               │
│   └──────────────────────┘               └──────────────────┘               │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │   get_table_schema   │ ─────────────►│  describe_table  │               │
│   └──────────────────────┘               └──────────────────┘               │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │    get_sample_data   │ ─────────────►│      sample      │ [OPTIONAL]    │
│   └──────────────────────┘               └──────────────────┘               │
│                                          (requires ENABLE_SCHEMA_TOOLS=1)   │
│                                                                             │
│   ┌──────────────────────┐                                                  │
│   │    get_server_info   │ ─────────────► ✗ REMOVED                         │
│   └──────────────────────┘                                                  │
│                                                                             │
│                              (new)       ┌──────────────────┐               │
│                          ★ ─────────────►│   list_tables    │               │
│                                          └──────────────────┘               │
│                                                                             │
│                          ★ (new Dec 23)  ┌──────────────────┐               │
│                            ─────────────►│  get_full_schema │               │
│                                          └──────────────────┘               │
│                                                                             │
│                          ★ (new Dec 23)  ┌──────────────────┐               │
│                            ─────────────►│ get_table_summary│               │
│                                          └──────────────────┘               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Renamed (1:1 mapping)
  ──┬──────►  Merged (N:1 mapping)  
  ✗ REMOVED   Tool no longer exists
  ★           Newly added tool
```

### 3. Tool Count Optimization
- **Before:** 6 tools called per simple query
- **After:** 1-2 tools for most queries

---

## Detailed Changes (v2.0)

### A. Added Lifespan Management

```python
@asynccontextmanager
async def lifespan(mcp_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan context manager."""
    logger.info("SQL Safety Checker MCP Server starting...")
    yield {"initialized": True}
    logger.info("SQL Safety Checker MCP Server shutting down...")
```

**Reason:** FastMCP best practice for managing server lifecycle and resources (e.g., database connection pools).

### B. Added ToolAnnotations

```python
@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute SQL Query",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
```

**Reason:** Provides metadata to LLM clients about tool behavior:
- `readOnlyHint`: Indicates the tool doesn't modify data
- `destructiveHint`: Indicates the tool doesn't delete data
- `idempotentHint`: Indicates repeated calls have the same effect

### C. Added Context Injection

```python
async def query(sql: str, ctx: Context) -> dict[str, Any]:
    await ctx.info(f"Executing query: {sql}")
    # ...
    await ctx.warning(f"Rejected unsafe query: {sql}")
```

**Reason:** 
- Structured logging through MCP protocol
- Client can receive real-time progress updates
- Better debugging and monitoring capabilities

### D. Improved Server Instructions (Updated December 2025)

The server instructions were optimized following prompt engineering best practices to reduce LLM's "exploratory behavior" (making unnecessary tool calls).

**Original Instructions:**
```python
instructions="""You are a database query assistant with READ-ONLY access.
Use the query tool for most operations. Only SELECT statements are allowed.
Use list_tables first if you don't know the database structure."""
```

**Optimized Instructions (Updated December 15, 2025):**
```python
instructions="""Database query assistant with READ-ONLY access.

Tools: query (primary), list_tables, describe_table, check_connection

Workflow:
- Known table structure: query directly
- Unknown structure: list_tables first, then query

Safe statements: SELECT, SHOW, DESCRIBE, and non-ANALYZE EXPLAIN.
(Historical v2 wording; v3.7 full MCP policy rejects raw SHOW.)"""
```

**Design Rationale:**
- **Concise**: Reduced token count while preserving all essential information
- **Flexible**: Allows LLM to choose exploration when needed (per MCP design philosophy)
- **Clear priority**: `query (primary)` indicates main tool without being restrictive
- **Workflow guidance**: Provides both paths (known/unknown structure) without forcing either
- **Aligned with MCP spec**: Tools are "model-controlled" - LLM decides based on context

See [PROMPT_ENGINEERING_BEST_PRACTICES.md](PROMPT_ENGINEERING_BEST_PRACTICES.md) for detailed guidelines.

### E. Added SQL Injection Prevention

```python
def _is_valid_identifier(name: str) -> bool:
    """Validate table/column name to prevent SQL injection."""
    return bool(re.match(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff]*$', name))
```

**Reason:** Prevents SQL injection through table names while supporting Chinese characters.

### F. Conditional Tool Registration

```python
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"

if SCHEMA_TOOLS_ENABLED:
    @mcp.tool(...)
    async def sample(...):
        ...
```

**Reason:** Allows disabling optional tools via environment variables for production deployments.

---

## Tool Usage Guide (After Refactoring, v2.0)

### Primary Workflow
```
query("SELECT * FROM users LIMIT 10")  # Direct query - most common
```

### Discovery Workflow
```
list_tables()                          # Step 1: Find tables
describe_table("users")                # Step 2: Understand structure
query("SELECT name FROM users")        # Step 3: Execute query
```

### Utility Tools
```
check_connection()                     # Verify database connection
sample("users", limit=5)               # Preview table data
```

---

## Best Practices Applied

1. **Single Responsibility:** Each tool does one thing well
2. **Clear Naming:** Tool names match their purpose (e.g., `describe_table` ≈ SQL `DESCRIBE`)
3. **Consistent Return Format:** All tools return `{"success": bool, "data": ..., "error": ...}`
4. **Proper Async:** All tools are async with proper Context usage
5. **Defensive Programming:** Input validation, SQL injection prevention
6. **Graceful Degradation:** Clear error messages with context

---

## Backward Compatibility Notes

- `check_connection` (previously `check_database_connection`) was kept for compatibility
- Old tool names are no longer available - clients need to update their calls
- The functionality remains the same, only the interface has improved

---

## Files Modified (After Refactoring, v2.0)

| File | Change Type |
|------|-------------|
| `mcp_sql_server.py` | Complete rewrite |
| `test_mcp_client.py` | Updated tool names to match new API |
| `test_mcp_functions.py` | Removed mcp_sql_server imports, use raw SQL |
| `REFACTORING_LOG.md` | Created (this file) |

### test_mcp_client.py Changes

Updated all tool calls to use new names:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    test_mcp_client.py TOOL CALL UPDATES                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   OLD TOOL CALLS                             NEW TOOL CALLS                 │
│   ══════════════                             ══════════════                 │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │ check_database_connection│ ─────────────►│    check_connection      │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │    get_table_schema      │ ─────────────►│    describe_table        │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │     get_sample_data      │ ─────────────►│        sample            │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐                                              │
│   │    validate_sql_query    │ ─────────────► ✗ REMOVED (merged into query) │
│   └──────────────────────────┘                                              │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │     execute_safe_sql     │ ─────────────►│        query             │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐                                              │
│   │     get_server_info      │ ─────────────► ✗ REMOVED (low value)         │
│   └──────────────────────────┘                                              │
│                                                                             │
│                                  (new)       ┌──────────────────────────┐   │
│                              ★ ─────────────►│      list_tables         │   │
│                                              └──────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  REASON: Align test script with refactored mcp_sql_server.py API            │
│  IMPACT: Test logic unchanged - only tool names updated                     │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Tool name updated (1:1 mapping)
  ✗ REMOVED   Test case removed (tool no longer exists)
  ★           New test case added
```

### test_mcp_functions.py Changes

Removed dependency on `mcp_sql_server.py`, now uses raw SQL for schema tests:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   test_mcp_functions.py IMPORT UPDATES                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   BEFORE                                     AFTER                          │
│   ══════                                     ═════                          │
│                                                                             │
│   ┌──────────────────────────────────┐                                      │
│   │ from mcp_sql_server import       │                                      │
│   │     get_sample_data,             │ ─────────────► ✗ REMOVED             │
│   │     get_table_schema             │                                      │
│   └──────────────────────────────────┘                                      │
│                                                                             │
│   ┌──────────────────────────────────┐       ┌──────────────────────────┐   │
│   │ get_table_schema(table_name)     │ ─────►│ execute_safe_sql(        │   │
│   └──────────────────────────────────┘       │   "SELECT ... FROM       │   │
│                                              │   INFORMATION_SCHEMA..." │   │
│                                              │ )                        │   │
│                                              └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────────────┐       ┌──────────────────────────┐   │
│   │ get_sample_data(table, limit)    │ ─────►│ execute_safe_sql(        │   │
│   └──────────────────────────────────┘       │   "SELECT * FROM table   │   │
│                                              │    LIMIT n"              │   │
│                                              │ )                        │   │
│                                              └──────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  REASON: mcp_sql_server.py no longer exports these functions after refactor │
│  IMPACT: Test logic unchanged - only data retrieval method changed          │
│  BENEFIT: test_mcp_functions.py now only depends on sql_safety_checker.py   │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Implementation changed
  ✗ REMOVED   Import removed
```

---

## Why This Refactoring Follows Best Practices (v2.0)

### 1. Tool Design Simplification

| Aspect | Before | After | Why Better |
|--------|--------|-------|------------|
| Query execution | `validate_sql_query` + `execute_safe_sql` (2 calls) | `query()` with automatic validation (1 call) | MCP best practice: fewer tools = easier for LLM to choose correctly |
| Tool count | 6 tools | 5 tools with clearer responsibilities | Reduces cognitive load for LLM clients |

### 2. ToolAnnotations Usage

```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,      # Tells LLM this is a read-only operation
        destructiveHint=False,  # Tells LLM this is safe
        idempotentHint=True,    # Tells LLM this can be retried safely
    )
)
```

These annotations help LLM clients understand tool behavior without reading documentation, leading to better tool selection.

### 3. Async + Context Pattern

```python
# Before (synchronous, basic logging)
def execute_safe_sql(sql_query: str) -> Dict[str, Any]:
    logger.info(...)

# After (async, structured logging via Context)
async def query(sql: str, ctx: Context) -> dict[str, Any]:
    await ctx.info(f"Executing query: {sql}")
```

Using `Context` is the FastMCP recommended approach:
- Provides structured logging through MCP protocol
- Enables real-time progress reporting to clients
- Better observability and debugging

### 4. Lifespan Management

```python
@asynccontextmanager
async def lifespan(mcp_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    # Initialize resources on startup
    yield {"initialized": True}
    # Cleanup resources on shutdown
```

Proper resource lifecycle management:
- Prepares for future connection pooling
- Follows Python async best practices
- Enables graceful shutdown

### 5. Enhanced SQL Injection Protection

```python
def _is_valid_identifier(name: str) -> bool:
    """Validate table/column name to prevent SQL injection."""
    return bool(re.match(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff]*$', name))
```

New version explicitly validates dynamic table names, adding defense-in-depth security.

### 6. Simplified Prompts

| Before | After |
|--------|-------|
| Verbose `system_orchestration` prompt | Clean `sql_assistant` prompt |
| Complex `generate_select_sql` prompt | Removed (unnecessary) |

Simpler prompts are easier to maintain and less likely to confuse LLM clients.

### 7. Code Quality Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Lines of code | ~460 | ~280 | -40% |
| Cognitive complexity | High | Low | Easier to maintain |
| Test surface area | Large | Small | Easier to test |
| Type hints | Partial | Complete | Better IDE support |
