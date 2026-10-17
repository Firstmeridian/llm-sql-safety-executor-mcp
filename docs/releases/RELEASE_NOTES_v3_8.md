# v3.8.2 — Dialect/session semantics and execution authorization (October 16, 2026)

### Why

Quoted spelling, physical object names, CTE scope and database session state have different semantics. Repeated token parsers and a connection-independent dialect setting could disagree across raw queries, Skills, readiness and metadata. SQLite additionally resolves temp/attached objects and view sources during compilation.

### Decision and contract

- Use pinned SQLGlot 30.22.0 for one shared structured read analysis with explicit dialect/session context, original lexical names, scopes, physical references, call identity and completeness. Delete the replaced CTE parser; retain independent managed-write plan checks. Execute original SQL/parameters, never regenerated AST SQL; partial analysis cannot imply zero dependencies.
- Preserve component-based RelationReference and independent grants. Add strict `read.relations` and Skill `relations` maps. SQLite supports forward/implicit-recursive CTE visibility; MySQL preserves ordered/explicit-recursion rules. Metadata uses dialect name envelopes and component quoting, with a separate SQLAlchemy literal-colon transport layer. Offline config explain serializes structured declarations.
- Initialize/verify a complete MySQL sql_mode contract for every physical connection before dialect inspection. Configure expanded individual modes or inherit the first initialized full set. Support ANSI_QUOTES/NO_BACKSLASH_ESCAPES/PIPES_AS_CONCAT interpretation; explicitly refuse HIGH_NOT_PRECEDENCE. Arbitrary trusted operations and full writes retire their sessions; normal reads/metadata reuse controlled sessions.
- SQLite authorizer checks actual compiled objects/operations and known view/CTE source edges throughout result consumption. Exclusive adapter ownership covers reads, metadata and full write transactions. Disable DBAPI statement caching; refresh per-request view dependency edges, including external schema changes. Fixed internal metadata/write operations remain trusted. A view grant does not grant direct base reads.

### Compromises and costs

SQLGlot parsing is not native syntax/catalog proof. Unsupported relation forms and ambiguous view source labels remain explicit refusals. View preparation is bounded (2048 lookups, 128 views, 1024 edges). SQLite serialization/callbacks/catalog preparation and disabled statement caching add work; MySQL trusted operations add reconnection costs. Schema/UDF/Python extensions remain trusted; MySQL has no corresponding authorizer. No additional required Agent tool call or automatic grant expansion. Model usage and timing claims need their own evidence; metadata characters are not tokens.

### Validation

The baseline is owner commit 3323f9c (1750 passed/four skipped). Final regression, type/prompt, native SQLite/MySQL mode matrix, pool lifecycle, wheel/stdio checks, measured costs, the completed initial Host/Luna batch and final native/three-trial CTE-count supplement (with model failures retained) are tracked separately in the [v3.8.2 report](../validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md). Historical v3.8.1 statements below retain their original scope. Decisions: DRR-2026-100–106 and [implementation contract](../architecture/V3_8_2_SQL_SEMANTICS_ZH.md).

### October 17 read-boundary review repair

Later review reopened DRR-108 for trigger READ, WITH REPLACE and UPDATE OR gaps. The [follow-up](../validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md) records 101 new regressions/2067 full passes, real stdio/Skill parity and serial costs. Actual schema/name checks and bounded outside-callback preparation restore plans while keeping direct-base, function and real-DML refusals. Original SQL/parameters remain intact; no new configuration, dependency or required Agent step. Final package/resident status is tracked separately; the previous batch below retains its own scope.

Trigger-local CTE count callbacks exposed one further P2 boundary. The [CTE supplement](../validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md) records 129 new regressions, 2196 full passes/four skips and 340 installed stdio calls. SELECT/DML source preparation and scoped CTE proofs cover WHEN, select-only and repeated trigger-local names without new grants. Scoped post-restart acceptance passes 57 checks with unchanged data; 12 exploratory expectation mismatches are retained separately. Repeated labels in independent outer-query subqueries remain conservatively refused, with verified distinct-label recovery. Retain prior native attribution and measured catalog/compile costs.

The [later adjacent audit](../validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md) reopens DRR-108 for a trigger-WHEN begin-column false refusal; previous scoped checks remain historical evidence. Three current-source complete two-turn Luna trials pass 2/3; retain one correct-name Host unavailable error without a cache root-cause claim. This review changes no runtime code; final acceptance awaits the P2 repair.

Subsequent [WHEN repair](../validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md): consume the true expression before BEGIN, preserve original SQL and all dependency/function checks. Add 79 regressions, 2275 full passes/four skips and 394 installed targeted calls. After the maintainer restart, 57/57 scoped native checks pass. Three new canary-conditioned complete two-turn sales trials reach correct outcomes, retaining one initial unsupported-query refusal and recovery; prior 2/3 business evidence remains unchanged. Exact WHEN trigger scenarios retain source/package attribution. DRR-108 closes within these stated limits. Host catalog/client mismatch logs and close/resume recovery remain separate from the original business failure and unproven underlying cause.

Sample/exact counts and SQLite data-based estimates use the controlled read boundary; fixed catalogs/statistics remain trusted. A denied estimate is unknown, while columns/indexes remain usable. Verify all analyzed roots before accepting extra source-less view-count events. Non-executing SQLite DML/REPLACE plans keep authorizer checks for actual targets/functions and bind their analysis to original SQL/context; real writes and EXPLAIN PRAGMA/DDL/ATTACH remain refused. Added analysis/catalog work does not add a required Agent step or justify a zero-overhead claim. Seventy new regressions bring final validation to 1966 passes/four skips; package, live checks and completed scoped native acceptance are recorded in the [repair report](../validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md). Earlier model/cost records retain their scope. Decisions: DRR-2026-107/108.

---

# v3.8.0 — FastMCP 4, explicit TOML, instance state and managed MRTR

> **Latest v3.8.1 follow-up (October 13–14, 2026):** structured read decisions, typed query failures and SQLite IN relation checks. See [acceptance and decisions](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md).

> **v3.8.1 maintenance (October 1, 2026):** see [Skill rejection recovery clue](#v381--skill-rejection-recovery-clue-october-1-2026). Configuration, authorization, token and execution semantics are unchanged.

This is a deliberate pre-release breaking refactor from baseline `582822b`.

## Delivered behavior

- Installed `src/sql_safety_executor` package with console/module entry points; no root `mcp_sql_server.py` / `start_server.py` launch path. Long prompts and descriptions are UTF-8 package resources.
- FastMCP 4.0.10 / MCP SDK 2.2.0 with framework-owned modern and legacy negotiation. Modern calls avoid deprecated legacy logging notifications. Tasks and application result caching remain disabled.
- Three strict TOMLs, explicit references and default target, immutable loaded snapshots, declared-file-relative paths, explicit secret sources and offline `config check/explain`. Invalid configuration fails startup. Old dotenv / ambient database configuration and default-only write grants are removed.
- Per-instance adapters, catalog, proposal store and diagnostics; lazy database connections, lifecycle cleanup, no deployment side effects on basic import. Full read policy is the execution entry point; weak `execute_sql()` compatibility execution is removed.
- Optional default-off `request_mutation_approval` for managed single-statement mutations. Immutable review ≤64 KiB, sealed continuation references, server-side binding, strict boolean approval, one-time atomic consumption and no transaction while waiting. Legacy preview/execute is preserved.
- Trusted external Skill directories with resolved containment, public package SDK imports, migrated bundled Skills, reference approval Host `--config` / `--flow`, separate AutoGen dependency environment.
- Lockfile, CI, migrated regression tests, TOML/MRTR/stdio/lifecycle coverage and installed-wheel verification outside the repository.
- Maintained root [refactoring log](../../REFACTORING_LOG.md) / [Chinese edition](../../REFACTORING_LOG_ZH.md), bilingual [documentation indexes](../README.md) and [configuration example guides](../../config/examples/README.md). Reusable/versioned guides live under `docs/guides/`; historical evidence retains its original scope.

## Migration and guarantees

Use [the field-by-field guide](../guides/CONFIGURATION_ZH.md) before switching. `read` defaults to deny; empty allowlists grant nothing; explicit `all` does not implicitly grant UNION. Read scopes do not universally authorize/restrict mutations. All five write gates must pass.

The server trusts the Host's approval decision. It does not independently authenticate a human. Python Skills remain trusted code; audit remains best-effort. A write can be committed despite `success=false`; `execution_outcome` and subsequent business reconciliation determine retry safety. Restart invalidates unused proposals. Durable/distributed recovery and multi-user authorization remain deferred.

Update the Host's actual saved command/args as well as the repository template, then stop the old process before starting the checked TOML deployment. A saved `start_server.py` entry cannot start v3.8; verify tool discovery/calls after reconnecting. See the [Host migration steps](../guides/TEST_MCP_CLIENT_GUIDE.md#update-the-actual-host-launch-entry). Rollback must restore code, dependencies and matching configuration together. Existing private `.env` files are not removed.

## Validation limits

See [the validation record](../validation/v3.8/V3_8_VALIDATION_ZH.md) and [subsequent live review](../validation/v3.8/V3_8_LIVE_REVIEW_2026_09_26_ZH.md). Earlier local runs recorded 744 passed / 4 skipped and a later focused 66 passed. The submitted `1be44b4` then failed CI on a stale description assertion; later steps were skipped. [September 27 review fixes](../validation/v3.8/V3_8_REVIEW_FIXES_2026_09_27_ZH.md) preserve that history. Remote [run 36330541822 for `139d53a`](https://github.com/Firstmeridian/llm-sql-safety-executor-mcp/actions/runs/36330541822) subsequently passed all steps with 786 passed / 4 skipped. Reference FastMCP modern MRTR and legacy preview/execute are automated.

After fixing the saved Codex launch entry and reconnecting, the current IDE Host completed 23 native calls, including a controlled SQLite preview/execute/compensation cycle with the fixture restored. Three isolated GPT-6 Luna agents completed 18 routing rounds with 22 native calls and no observed wrong-target access. Real MySQL connectivity/basic reads passed; the four optional MySQL integration tests remain skipped, and MySQL writes/failure recovery remain unverified.

The earlier native MRTR dispatch was blocked by Host policy; subsequent September 26 local tests kept MRTR disabled. Later September 30–October 1 Codex IDE tests verified human-approved commit and cancellation; after adding the required boolean field's standard `default=false` hint, the user confirmed unchecked submission and the server returned refusal without a write. [Later native tests](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md) observed framework rejection of a delayed approval and unchanged database state. A separate real-process restart regression passed in the focused 131-test suite, including new-process fresh-approval success. Business-TTL checks have simulated-clock coverage; their native UI acceptance and the native restart case remain pending; two earlier approved trials committed real test updates, and no compensating write was performed. See the [dated refactoring log](../../REFACTORING_LOG.md#v380-mrtr-approval-form-default-october-1-2026). A user-supplied Copilot trial was rejected by the MCP 2026-07-28 requirement before a form appeared; interactive MRTR remains unverified. Subsequent session-log inspection identified VS Code 1.140.0 / Copilot 0.68.0; the actual MCP request protocol, capabilities and harness remain unknown. The installed SDK version list alone does not prove the session used that path. Native subagent token usage and negotiated protocol were not exposed; reference Client versions are not substituted for them. Historical failures, including one rejected-and-corrected UNION in the earlier CLI trials, remain in the evidence.

## Independent review corrections (September 27)

Profile exclusions now trim, lowercase and deduplicate strictly typed strings;
blank entries fail startup. Tableless Query Skill availability follows read
admission. Configuration errors preserve safe semantic codes. MRTR waiting and
repeat requests retain their validated target in telemetry; absent identity
remains null and decline/cancel phases are preserved. Both reference Host flows
share approval deadlines, review fingerprints and expiry rechecks. The server's
token consumption and trusted-Host boundary remain unchanged. See the linked
review record for regressions and deferred task-scope/catalog/tracing work.

## Follow-up review (September 28)

The previous findings are closed with confirmed remote CI evidence. A further
Query Skill discovery mismatch is fixed: cached SQL is preflighted with the
execution path's full static policy for the selected connection, including
UNION and parsed table scope. Templates remain available to other authorized
targets; no authorization verdict cache is introduced. Discovery adds parsing
work, and enabled schema readiness may still access database metadata.

Six new regressions cover modern/legacy UNION decisions, quoted tables and
missing SQL snapshots. Clean-copy local validation recorded 792 passed / 4
skipped, clean type checks, build and installed-wheel verification. This new
patch still awaits remote CI. See the [follow-up record](../validation/v3.8/V3_8_REREVIEW_2026_09_28_ZH.md)
for evidence and unchanged native Host acceptance limits.

Historical releases and failed trials retain their original versions and conclusions under `docs/`.

### Approval trust clarification (October 1)

Preview/execute remains the recommended deployment default; MRTR stays
disabled by default and opt-in for a verified Host. The tested Codex IDE and
Copilot paths show uneven support, not universal incompatibility. Enabling
MRTR is not permission to switch write paths automatically after a refusal,
cancellation, timeout or uncertain result. The [acceptance audit](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)
lists remaining native cases and evidence gaps; its focused revalidation
passed 131 tests with one existing logging deprecation warning. This is not a
new full-suite or remote CI result.

Legacy preview/execute collects human approval in the Host, not through a
server-requested form. MRTR enforces an accepting protocol response but still
trusts its Host; neither flow independently authenticates a human. The MRTR
switch leaves legacy mutation access intact, so it is not a global mandatory
human-approval policy. DRR-2026-050 records this accepted boundary and the future
need for independent, unbypassable authorization if an Agent must not approve
its own writes. See the [flow comparison](../security/V3_8_SECURITY.md#where-approval-is-enforced).

### MRTR review readability follow-up (October 1)

Approval reviews now show indented JSON with readable Unicode while retaining every field and the reference Host parsing contract. First asks and re-asks use the same saved snapshot. Focused regressions after the change: 131 passed, one existing deprecation warning. After a user restart, a native Codex IDE screenshot confirmed multiline rendering; the close-button test returned `approval_cancelled` and independent reads showed no change. Other Host rendering remains unverified; see the [current acceptance matrix](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Final local verification (October 1)

Version remains **3.8.0**. All pending code was checked in a clean copy with
new environments and frozen dependencies: **793 passed, 4 skipped, 3 existing
legacy logging warnings**; Pyright reported zero errors/warnings. Source and
wheel builds and an isolated installed-wheel check outside the repository
passed, including packaged prompts and both protocol generations. The four
MySQL integration tests remain skipped. This local result does not claim a
new remote CI pass or close the documented native UI gaps. See the
[pre-commit record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

## v3.8.1 — Skill rejection recovery clue (October 1, 2026)

A backward-compatible maintenance release. Package, lockfile project entry and
MCP server version are **3.8.1**. No configuration, migration, authorization,
token or execution change is required.

**Why.** After a rejected `delivered → shipped` transition, a Copilot Agent
concluded that an administrator was needed, although the executable
`sample-reset-order-to-pending` already provided an approved demo restoration
path. The metadata was discoverable; the Agent skipped discovery. Subagent
trials also showed prompt rules alone were unreliable.

**Contract additions**

- `execute_mutation_skill` may add `related_available_skills` (string array) to
  `validation_failed` payloads in preview or execute mode. It lists names from
  the rejected Skill's own `related_skills` that are mutation Skills and are
  currently executable on the same resolved connection, using the same
  availability predicate as `list_skills` (profile, connection scope, database
  type, all mutation grants and schema readiness).
- Names only: no parameters, ordering advice, authorization, approval or token.
  Each alternative still needs its own preview, approval and execute. The field
  is omitted when nothing qualifies or the lookup fails; the lookup never changes
  `success`, `error_code` or `execution_outcome`. Other failure codes do not
  include it. MRTR's first round shares this preview path.
- The output schema declares the optional field. Clients must continue to accept
  unknown additive fields.
- The update Skill describes its forward lifecycle and backward-transition
  rejection and links the reset Skill. Its status rules document a non-atomic,
  separately approved demo restoration. The mutation tool description forbids
  bypassing a rejection or changing targets, asks callers to inspect related
  Skills before declaring no path, and states that only execute decides token
  validity.

**Compromises and limits**

- The clue is advisory. It depends on author-declared relationships; an
  undeclared alternative is not found, and a declared one may not suit the
  user's goal. An Agent can still ignore or misuse it.
- Computing it adds one schema-readiness metadata lookup on rejected requests
  that declare related mutation Skills. It exposes only names already visible
  through `list_skills` for that connection.
- `preview_token_expires_in_seconds` was briefly reintroduced during testing
  and withdrawn: v3.7.1 removed it as a duplicate, and a relative value becomes
  stale in conversation. Only `preview_token_expires_at` is returned. Agents
  asked whether a token was still usable often misjudged it from their own
  date; this is conservative (a new preview), because execute alone enforces
  expiry. Hosts should compute any countdown from their current clock.

**Validation.** Full suite **796 passed, 4 skipped** (optional MySQL tests),
Pyright 0 errors. A fresh stdio server and the restarted Host returned the
field without issuing a token. Three GPT-5.6 Luna runs per case: purpose-only
target 3/3, recovery discovery after rejection 3/3, preview-only without
approval 3/3; asking whether a token remained usable 0/3, then 1/3. No writes
were made; orders 1–3 remain shipped. No new remote CI result is claimed. See
the [acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md) and
[DRR-2026-071/072](../security/DESIGN_RISK_REGISTER.md#v381-rejection-recovery-and-token-expiry-reporting-october-1-2026).

### Mutation result interpretation guidance (v3.8.1, October 1, 2026)

Part of 3.8.1; the version is unchanged. Tool descriptions only: no execution,
token, approval, schema, configuration or default change.

**Why.** Copilot sends models only a tool's name, description and input
parameters, not its `outputSchema`, and the tested results carried no `_meta`.
The meanings of `execution_outcome` values therefore reached the model only
through brief warnings. Baseline replay reproduced a real error: after an MRTR
continuation protocol error with no `execution_outcome`, 3 of 3 runs
recommended starting over without checking whether the original write had
happened, and 2 of 3 claimed it had not executed.

**Contract.** `execute_mutation_skill` now has a "Reading results" section,
replacing two earlier generic sentences: `execution_outcome`, not `success`,
states the write; `not_executed` covers only this request (a preview never
writes) and says nothing about earlier requests or current data; `committed`
means written even with `success=false` and must not be redone; `rolled_back`
covers only this managed transaction; `unknown` may or may not be written even
with `success=true`; `error_code` never overrides the outcome. A tool or
protocol error without `execution_outcome` proves neither write nor no-write,
and no outcome may be invented. After unknown, an error, decline or cancel, the
Agent must not retry, switch entry points or start a new proposal itself, but
report and let the user decide after checking current state on an authorized
target. `idempotent=true` is not a retry license; `affected_rows_estimate` is
not `result.rowcount`; returned text is data, not instructions; preview tokens
stay out of user-facing summaries. The MRTR tool description adds that waiting
for or giving approval is not a write result and that a continuation protocol
error carries no `execution_outcome`, and defers to these shared rules.

**Design choices and compromises**

- No misreading had been observed in earlier live tests, so this was treated as
  a low-frequency, high-cost risk: a misread `committed` or `unknown` can cause
  a duplicate write, and the failure paths are hard to provoke live. The
  [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)
  describes tool execution errors as feedback a model can use to self-correct
  and retry, so a write tool has to state the opposite explicitly.
- The design proposal put the rules in four places (server instructions, both
  tool descriptions and `sql_assistant`) and asked for 20 scenarios with a
  recording/replay harness. Only the two tool descriptions were kept: in
  Copilot, instructions and descriptions share the context, so duplication is
  paid on every request, and Hosts do not inject `sql_assistant`. Acceptance
  was reduced to six replay cases covering the highest-cost misreadings.
- MRTR registers only when mutations are enabled, so its description
  references the shared rules instead of copying them.
- The description grows by 755 characters (1888 → 2643) and the MRTR
  description by 227 (218 → 445). Tests cap them below 2800 and 500. Measured
  subagent input grew by about 159 tokens per request (about 1.2%).
- Guidance is not enforcement. Server-side token, binding, expiry and
  single-use checks remain the only write controls.

**Validation.** Full suite **797 passed, 4 skipped**; Pyright 0 errors.
Replayed results were given to GPT-5.6 Luna subagents in the prompt (not
through the tool channel), three runs per case, before and after the change:

| Case | Before | After |
|---|---|---|
| `success=false` + `committed` | 3/3 | 3/3 |
| `success=true` + `unknown` (imperative) | 3/3 | 3/3 |
| MRTR continuation protocol error, no outcome | 0/3 | 3/3 |
| Approval declined | 1/3 | 1/3 |
| `unknown` with injected retry instruction | 2/3 | 3/3 |
| Normal commit (control) | 3/3 | 3/3 |

No run executed the injected instruction or retried. The remaining declined
failures asserted the order was "still shipped" without reading it; this is
recorded as residual risk. Earlier cases did not regress: purpose-only target
3/3, recovery discovery after rejection 3/3 and preview-only 3/3, with no more
turns and slightly fewer calls. No writes were made.

VS Code kept serving cached tool definitions after a server restart and
**MCP: Reset Cached Tools** until the server was called again. Earlier 3.8.1
subagent runs may therefore have seen the previous description; their recovery
results relied on the returned `related_available_skills` field. See
[DRR-2026-073](../security/DESIGN_RISK_REGISTER.md#v381-rejection-recovery-and-token-expiry-reporting-october-1-2026)
and the [acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Per-connection read policy guidance (v3.8.1, October 1, 2026)

Part of 3.8.1; the version is unchanged. Authorization and SQL validation are
unchanged; only always-loaded guidance and one rejection message change.

**Why.** Models learned a connection's UNION policy only after a rejection.
On a MySQL connection with UNION disabled, a five-table count task first tried
`UNION ALL` in 3/3 runs, then made 11–15 calls (58k–78k input tokens). The
rejection told the model to "combine results in your response"; one run then
fetched raw rows that were truncated at 100. On a SQLite connection with UNION
allowed, 3/3 first queries were rejected because UNION was placed in a
`FROM (...)` subquery, which every connection rejects.

**Delivery choice.** The design proposal added an optional `connection_id`
argument to the `sql_assistant` MCP Prompt and kept server instructions
connection-neutral. Its intent was adopted: guidance derived from the loaded
configuration, no authorization change or database access, per-connection
wording rather than a global rule, "UNION disabled" not meaning single-table
queries, and a corrected merge fallback. Its delivery was not. The MCP
specification describes Prompts as
[user-controlled](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts#user-interaction-model),
and in Copilot they are slash commands the model cannot fetch, so most of the
measured gain would not appear. Server instructions were verified to reach the
main Agent and subagents without an extra call. `list_connections()` already
reported `allow_union`, but with a known target the routing rules send the
model straight to `query()`, so it was not consulted. `sql_assistant` stays
parameterless and includes the same text; a parameterized Prompt is deferred
until a Host lets models fetch Prompts.

**Contract**

- At startup, `render.connection_policies(config)` writes one line per
  connection from the loaded `ConnectionPolicy`: alias, database type, reads
  disabled or scope type (all, or an allowlist with a table count), and UNION
  allowed/disabled. It uses `read_access_enabled()`, performs no database or
  adapter I/O, and lists no table names, hosts or paths. Beyond 12 connections
  it adds a count and points to `list_connections()`.
- A shared `read_policy.md` adds: this is configuration, not proof of
  connectivity or table existence; subqueries in FROM are rejected on every
  connection, so use a CTE; where UNION is disabled, do not try UNION and use
  one permitted query that keeps the task's meaning; UNION allowed does not
  widen table scope or allow cross-connection queries.
- The UNION rejection keeps its `UNION queries disabled` prefix but no longer
  suggests merging separate results in the reply. It recommends scalar
  subqueries, EXISTS/NOT EXISTS, JOIN or a CTE, and asks to aggregate in SQL and
  check truncation, duplicates and ordering if separate queries are needed.

**Compromises and limits**

- Instructions grow by 833 characters with four connections (3,582 → 4,415);
  measured fixed input grew about 184 tokens per request. Larger deployments
  pay up to 12 lines plus a summary.
- Guidance is generated at startup. Configuration changes need a server restart
  and a Host tool refresh. Hosts that ignore server instructions do not benefit;
  `list_connections()` and execution checks remain authoritative.
- Aliases, database types and policy modes were already exposed by
  parameterless `list_connections()`; table counts reveal scope size, not names.
  Aliases must match `[a-z][a-z0-9_]{0,63}` and database types are a closed
  set, so configuration cannot place free text in the instructions.
- The FROM-subquery rejection is an existing text check (`FROM (`), not a new
  rule; it is stated now because it caused the UNION-allowed rejections.

**Validation.** Full suite **799 passed, 4 skipped**; Pyright 0 errors; prompt
contract script passes. A local-only test database (`local_data/union-test.db`,
three 240-row quarterly tables plus an unlisted table) and a read-only
`union_test_sqlite` connection with UNION allowed were added for testing. Three
GPT-5.6 Luna runs per case, identical prompts before and after:

| Task | Before | After |
|---|---|---|
| UNION disabled (MySQL, 5 tables) | 3/3 correct; 3/3 rejected first; 11–15 calls; 58k–78k tokens | 3/3 correct; no rejection; 2 calls; ~44.0k tokens |
| UNION allowed (SQLite, 3 tables) | 3/3 correct; 3/3 rejected first (FROM subquery); 2–4 calls; ~42.0k tokens | 3/3 correct; no rejection; 1 call (CTE + UNION ALL); ~27.9k tokens |

A control that told the model "UNION is disabled" in the task took 2 calls and
~43.5k tokens, matching the new result: the gain comes from knowing the policy
before writing SQL. In the UNION-disabled baseline, one run followed the old
advice and fetched raw rows truncated at 100 (actual 151–288) before switching
to `DISTINCT` queries; its answer was still correct. Regression runs kept
routing 3/3, recovery discovery 3/3, preview-only 3/3, MRTR protocol-error
interpretation 3/3 and normal-commit control 3/3. Call counts were unchanged
except preview-only (1.7 → 2.0: one run first passed a wrong parameter name and
corrected itself, unrelated to this change). No writes were made. See [DRR-2026-074](../security/DESIGN_RISK_REGISTER.md#v381-rejection-recovery-and-token-expiry-reporting-october-1-2026)
and the [acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Real tool-channel result check and token-rejection wording (v3.8.1, October 1, 2026)

Part of 3.8.1 and of the same change set as the read policy guidance; the
version is unchanged.

**Why.** The result-interpretation guidance above was evaluated only with
replayed results written into prompts. This check used real tool results on a
richer local SQLite database: `local_data/mutation-rich.db` (24 customers, 80
orders in all six statuses, 204 items; orders 1–12 are fixtures) behind a
local-only `rich_mutation_sqlite` connection with the two sample Skills. Both
are managed Skills, so success returns `committed`. Each execute was approved
by the maintainer per write, then run by a fresh GPT-5.6 Luna subagent; three
runs per case.

| Case | Real result | Before fix | After fix |
|---|---|---|---|
| Normal commit | `committed`, rowcount 1 | 3/3 correct | — |
| Execute with a consumed token | tool error, no `execution_outcome` | 3/3 no retry; 0/3 clearly "this request wrote nothing"; 1/3 advised a new preview | 3/3 no retry and clearly "this request wrote nothing"; 3/3 advised a new preview with approval |
| Row changed after preview | `rolled_back`, `expected_rowcount_mismatch` | 3/3 correct, no retry | — |
| Declined preview, row changed later | no execute | 0/3: preview-time status reported as current, no read | 0/3 with a trial sentence (removed) |

Calls and turns were stable (1 call and 2 turns per execute run; first request
about 13,750 input tokens, matching the measured fixed cost). The normal commit
matches the replay control (3/3); the declined case is below the replay (1/3)
and, because the data had changed, the misstatement was factually wrong.
`success=false` + `committed`, `unknown` and MRTR protocol errors cannot be
produced with the sample Skills and remain covered only by replay.

**Fix (scope clarified October 3).** Token rejection precedes the framework write
boundary. Imperative Skill construction/readiness may run earlier; trusted
extensions must not write there. The five
rejection messages ended with "run preview again", conflicting with the rule
against self-initiated new proposals while the description said an error
without `execution_outcome` proves nothing. They now end with "rejected before
execution, so this request wrote nothing. Check the current state and let the
user decide whether to preview again." The description adds "A rejected
preview_token means this request wrote nothing." Rejections remain tool errors
with unchanged conditions and token semantics. A second trial sentence ("Preview
fields such as current_status are preview-time state, not now.") had no
measurable effect and was removed with the maintainer's agreement. Final
description: 2,643 → 2,706 characters; both trial sentences together measured
+28 input tokens per request.

**Limits.** Agents still recommend a new preview without first mentioning a
state check; a new preview re-reads state and needs its own approval, so the
risk is low. Reporting preview-time state as current after a decline remains a
residual risk (DRR-2026-073); structural options are a Skill version that names
the field as preview-time state or a Host re-read. Writes touched only the
local test database: orders 1–3 were committed after approval; the maintainer
side changed orders 4–6 and 10–12 to `returned` directly to simulate other
writers. `live_test_sqlite` was untouched. Full suite **799 passed, 4
skipped**; Pyright 0 errors.

### Server-state reads and MySQL table-name case (v3.8.1, October 3, 2026)

Part of 3.8.1; the version is unchanged. Two read-policy gaps found while
evaluating a raw SHOW proposal (see the next section). Full suite after this
and the next section: **820 passed, 4 skipped**.

**Server, account and file-path state (DRR-2026-075).** Raw SHOW and system
schemas were already rejected, but SELECT could still read server state. On
the MySQL 8.0.25 test server, `@@hostname`, `@@datadir`, `@@secure_file_priv`,
`@@version_compile_os` and `CURRENT_USER()` were readable (values were not
recorded); on SQLite with `read.mode="all"`, `pragma_database_list` returns the
database file path. The shared read policy, used by `query()` and by Query
Skill startup and runtime checks, now rejects `@@` system variables, the
account and role functions `USER`, `CURRENT_USER`, `SESSION_USER`,
`SYSTEM_USER` and `CURRENT_ROLE`, and `pragma_*` table-valued functions. The
check uses SQL tokens, so string literals, quoted identifiers, a plain column
named `user` and user variables (`@x`) are unaffected. `VERSION()` and
`sqlite_version()` stay allowed for dialect checks. This is a denylist:
`DATABASE()`, `CONNECTION_ID()`, `UUID()`, `SLEEP()`, `BENCHMARK()` and
named-lock functions remain allowed and are left for separate review.

**MySQL table-name case (DRR-2026-076).** Allowlist entries and table
references were lowercased. On MySQL with `lower_case_table_names=0` (the Linux
default), `Orders` and `orders` are different tables, so allowing `orders` also
authorized `Orders` in queries and exposed it through `list_tables()` and
`get_full_schema()`. MySQL connections now keep the configured case and match
table references exactly everywhere the allowlist applies; CTE names are also
matched exactly, so a differently cased reference is checked as a table.
SQLite stays case-insensitive. **Behavior change:** on case-insensitive MySQL
servers (`lower_case_table_names=1/2`), queries or allowlist entries whose case
differs from the stored table name are now rejected or hidden. Configure MySQL
allowlist entries with the stored names. `read.mode="all"` is unaffected.

No database I/O was added. Live checks after restart: `SELECT @@hostname`,
`SELECT CURRENT_USER()` and `pragma_index_list('orders')` were rejected with
their reasons; `VERSION()` and SQLite `FROM Orders` still worked. The MySQL
case change could not be exercised live (the test server is case-insensitive
and its connection uses `read.mode="all"`); unit tests cover it.

### Structured index metadata in describe_table() (v3.8.1, October 3, 2026)

Part of 3.8.1 and of the same change set; the version is unchanged.
This section records the October 3 implementation and measurements. Current
key-part fields, the visibility capability probe and collection budgets are
described in the October 12 review below.

**Why.** Agents could not list a table's indexes. With identical prompts and
three runs each, a MySQL task (one `va_*` table) failed 3/3 with 2–3 calls and
43.6k–59.4k input tokens, and a SQLite task (two tables with composite,
unique, partial and expression indexes) failed 3/3 with 4–5 calls and
59.2k–93.5k tokens. They tried `information_schema`, `sqlite_schema` and
`pragma_*`, all rejected; none tried `SHOW INDEX`. `describe_table()` only
exposed per-column `PRI`/`MUL`, so a composite unique key
`uk_code_date(code, source_file)` appeared as a non-unique `code`.

**Decision.** A proposal to allow limited raw `SHOW INDEX`/`SHOW COLUMNS` in
`query()` was not adopted. The need is index metadata, not SHOW syntax; raw
SHOW would add a parser, per-connection switches, Query Skill isolation and a
WARNINGS contract, would serve MySQL only, and `MAX_EXECUTION_TIME` does not
apply to SHOW. Raw SHOW is not a planned follow-up; it will be evaluated
separately only if a concrete compatibility need appears. Kept from that
proposal: one resolved target for checks and execution, authorization before
metadata access, explicit completeness and bounded resources. The newer v2
design deliberately enables index collection by default; it adds metadata work
and disclosure on already-authorized tables, without opening raw SHOW. Fixed
collection budgets were added during the October 3–12 review documented below.

**Contract.** A successful `describe_table()` adds `indexes_status`
(`complete` or `unavailable`) and `indexes`. Each index has `name`, `primary`,
`unique` and ordered key `columns` (`null` for an expression key part, then
`has_expression: true`); MySQL adds `type` only for non-BTREE indexes; SQLite
always adds `partial` (an early version emitted it only when true and 2/3 runs
reported the others as unknown). SQLite's implicit rowid primary key, which has
no index entry, is synthesized with `name: null`. Primary key first, then by
name. If only index metadata fails, the call still succeeds with
`indexes_status="unavailable"`, `indexes=null` and a fixed error text, so a
failure never looks like "no indexes". Rejections of raw SHOW, system schemas
and `pragma_*` now add that `describe_table()` also returns indexes.

**Implementation.** MySQL runs one parameterized
`INFORMATION_SCHEMA.STATISTICS` SELECT (`TABLE_SCHEMA = DATABASE()`) under the
existing read timeout and does not select `CARDINALITY`, which can refresh
cached statistics. SQLite uses `pragma_index_list`, `pragma_index_xinfo` and
`pragma_table_info` with bound parameters inside the adapter. These internal
metadata reads do not pass through `query()`; agents still cannot query
system tables or PRAGMA functions. Existing read-access, identifier and
allowlist checks (now case-exact for MySQL) run first.

**Disclosure and limits.** No new switch: the object scope is unchanged and
indexes belong to the table structure already exposed. Index names, key
columns, uniqueness, type and partial/expression flags are now visible for
allowlisted tables; comments, expressions, partial predicates and cardinality
are not. `get_full_schema()` is unchanged. Foreign keys, checks and triggers
remain absent. Agents asked for expressions correctly reported them as
unavailable; one run then tried `sqlite_master` and was rejected.

**Validation.** Full suite **820 passed, 4 skipped**; Pyright 0 errors. Adapter
output matched native `SHOW INDEX` (MySQL) and PRAGMA (SQLite, three tables)
exactly. Three runs per case, same prompts as the baseline:

| Task | Before | After |
|---|---|---|
| MySQL indexes | 0/3; 2–3 calls; 3–4 turns; 43.6k–59.4k tokens | 3/3 complete; 1 call; 2 turns; ~28.9k tokens |
| SQLite indexes | 0/3; 4–5 calls; 4–6 turns; 59.2k–93.5k tokens | 3/3 correct with explicit `partial`; 2 calls (2/3) or 3 calls (1/3, rejected `sqlite_master` attempt); 2–3 turns; 28.4k–43.4k tokens |

The longer `describe_table` description (1,065 → 1,369 characters) adds about
68 input tokens per request. Regression: purpose-only routing 2/2 asked for the
alias with one call (~28.3k tokens, previously ~28.0k with four connections);
the UNION-disabled MySQL task 2/2 correct with 2 calls (~44.4k, previously
~44.0k). No writes were made. See DRR-2026-077 and the
[acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).


### Five-commit review completion (October 12, 2026)

**Why.** Review of `f50b010` through `09c3b9a`, four external reports and the earlier uncommitted fixes found incomplete standalone MRTR result guidance, relation/CTE scope omissions, metadata identity mismatches and missing index attributes/budgets. GPT-6 Luna replays also found invented rowcounts and malformed-field misinterpretation.

**Decision.** Keep version 3.8.1 and the later approved automatic-index design, without a new switch or raw SHOW. Render one packaged result resource independently into each write tool. Put result validity before outcome and give explicit missing-rowcount wording. SQL scope extraction remains a conservative supported subset; execution grants, token/transaction semantics, configuration and production MRTR enablement are unchanged by this review.

**Contract and implementation.** Quoted built-in PRAGMA objects are checked in relation position while ordinary business names are allowed. CTEs obey definition order and explicit recursion; unsupported relation groups, single-quoted objects, ODBC wrappers and TABLE expressions fail before database access. MySQL readiness uses exact table identity. SQLite metadata uses main; `columns` is retained and `key_parts` adds direction/collation or prefix length, with MySQL optimizer `visible` true/false/null. Visibility capability errors are not weakened into a retry. Whole-index collection is limited to 128 indexes, 2048 key parts and 64 KiB UTF-8; unavailable indexes preserve columns.

**Compromises.** Automatic indexes add default metadata work and disclosure within authorized table scope. Expression text and partial predicates remain unavailable. Collection deadlines are cooperative and cover the index stage; SQLite forward/implicit-recursive CTEs and some equivalent MySQL case variants can be rejected. Final write descriptions are 3,546/2,642 characters (budgets 3,600/2,700); a Host loading both pays both copies of common text. Historical +159-token results do not measure this wording. Guidance remains fallible; no new durable result ledger or authenticated human approval is provided. See DRR-2026-073/075–079.

**Validation.** Final full suite **941 passed, 4 skipped, 6 legacy logging warnings**, Pyright zero errors/warnings, prompt-resource check, sdist/wheel build and outside-repository installed-wheel stdio on modern and legacy protocols passed. The explicit MySQL adapter subset passed 15 tests, including existing real connection checks; other cases use test doubles. Live MySQL 8.0.25/SQLite index comparisons passed and isolated fixtures were removed. Three GPT-6 Luna native runs each completed index, aggregation and preview-only recovery tasks without writing existing rows. Final independent malformed-field replays passed 3/3 ordinary and 3/3 simulated MRTR; earlier failures are retained. There is no matched historical performance comparison or new remote CI result.

After the maintainer restart, the resident Host description matched final source. Malformed-field and missing-rowcount replays using current metadata passed 3/3 each; native index/preview tasks passed 3/3 with no execute. Complete recovery routes were correct 2/3; the omitted confirmed step and later correction are retained, and an actual preview rejected the invalid jump. The new combined-task costs are recorded without a historical performance guarantee. Source was unchanged, so no full-suite rerun was needed. Native MRTR UI gaps remain separate. See the [complete evidence](../validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md).

## v3.8.1 Review follow-up (October 13)

**Why:** external review exposed SQLite IN relation omissions, literal keyword false positives and generic database failures.

**Decision:** adopt structured PolicyDecision and typed DatabaseQueryError, keeping version 3.8.1. The project is unreleased; old dotenv/launch/SDK migration and hypothetical historical callers are outside scope. Current callers are updated directly; better designs are reported with their effects and evidence.

**Contract:** authorized membership relations retain SQL semantics; table/PRAGMA scope includes IN/NOT IN RHS. Token checks distinguish real operators from data. Query Skill inferred dependencies share scoped parsing and policy rejects before readiness. Read adapters return rows or raise typed failures; Query Skill SQL/policy failures become structured business success=false with error_code/error/hint, with a matching conditional output schema. Parameter/target/scope/readiness errors may still be ToolErrors. Transaction outcomes remain independent.

**Compromises:** MySQL exact CTE matching is retained with a case hint; other vendor/settings need live validation. Unsupported SQL shapes still fail closed. Error mapping is intentionally fixed and incomplete; raw exceptions are never echoed. Native authorizer and an AST replacement need separate design evidence. This adds description/error payload context; no blanket token or latency improvement is claimed.

**Validation:** see [current acceptance matrix](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md), including frozen af3420f baseline, regressions, installed wheel, live databases, retained Luna baseline trials and completed native Host acceptance (three identical-prompt trials passed; MCP calls 4→3 each; measured input mean +2.7%, median +5.4%, without a cost guarantee). DRR-2026-080–082 record the new contracts and residual limits.

**October 13 supplemental checks and then-open issue:** four opt-in live MySQL tests passed without skips, including a conditional-update race; only a unique new table was written and its removal independently verified. Twenty Client calls on both protocols/read scopes reproduced a still-unfixed SQLite F/f CTE false dependency in Skill discovery/execution, even with explicit tables declared; all-mode readiness also fails. DRR-2026-081 remains open for this boundary. Isolated authorizer cache/view/count probes and fixed-metadata/response measurements are supplemental design evidence, not production implementations or a model-cost guarantee. Existing JSON is retained; new evidence is indexed, metadata deduplicated and raw logs compressed.

### CTE dependency and name-rule follow-up (October 14)

**Decision and contract:** fix the reproduced Skill boundary, retaining version 3.8.1. Declared dependencies stay separate from inference selected for each connection; discovery, table search, readiness and execution use the same required set. Full Query Skill results add declared_tables/inferred_tables alongside the combined tables field; static SKILLS.md lists declarations. Physical names retain spelling and significant quoted whitespace. SQLite identity folds ASCII only, preventing Python Unicode folding from authorizing a distinct object.

**MySQL rules and compromises:** measure ASCII CTE duplicate-name behavior using constants without any FROM clause. Probe only a genuine ambiguity after definitely unauthorized dependencies/structural refusals; cache success per adapter, reset on close, and keep exact matching on unknown failure with a 30-second retry backoff. Cold ambiguity can add one trusted constant query; startup remains offline and business SQL waits for authorization. Physical MySQL grants and qualified/self/forward checks remain independent. Non-ASCII compatibility and independent 0/2/MariaDB live matrices remain limited. Lock/delay restrictions, authorizer and AST are not implemented in this follow-up.

**Validation and evidence:** [latest dated checks](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md#cte-依赖与实际名称规则修复2026-10-14) distinguish the current full regression/type/install checks, four separately opted-in MySQL tests, 34 actual Client calls and ten completed resident-Host checks from October 13 model evidence. Existing records are retained; new recording profiles explicitly identify collected public results, metadata references and omitted transport/model information. DRR-2026-081 records closure of the dependency boundary; 083/084 cover measured CTE rules and faithful identifier identity.

### v3.8.1 — CTE matrix, read-function restrictions and SQLGlot experiment (October 14, 2026)

**Why/decision:** reserve real lock/delay calls in raw reads and Query Skills to avoid session effects and deliberate resource occupation. Preserve data/column/CTE names; startup skips unsafe templates and runtime independently refuses before I/O. Fixed lock_function_denied and expensive_function_denied carry same-connection recovery hints. No new bypass configuration or write approval change.

**Evidence/compromises:** 52 native/policy cases on current SQLite/MySQL, serial A/B/A fixed costs, 1089 passed/4 skipped, clean Pyright/prompt checks and 12 installed-wheel stdio calls. SQLGlot 30.22.0 is an isolated candidate requiring scope/IN/opaque-command adapters; production AST/authorizer work is deferred. Other server variants remain untested; native required CLI A/B passed but does not establish billing savings or complete IDE cost. After the maintainer restart, 13 primary Host native checks passed, covering the new refusals and ordinary queries/Skill behavior. See [decisions and recording scope](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md).

## v3.8.1 complete pre-commit review (October 14, 2026)

Whole-string whitespace normalization and repeated identifier quote decoding could confuse physical objects with CTEs/grants or create false dependencies. Policy now formats whitespace tokens and decodes original name components once, preserving exact grants and qualified identity. Native SQLite truth, 25 new regressions, 1114 full passes/four skips and 22 outside-repository installed stdio calls support this last repair. Historical adapter/Skill API snippets and collaboration guidance are clarified. Version/dependencies are unchanged; final resident acceptance passed 11/11 native checks after the maintainer restart, and earlier Luna/cost results remain dated. See [the final evidence and complete change table](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md#提交前完整复核与补修2026-10-14).


## v3.8.1 relation identity and mutation revalidation follow-up (October 15, 2026)

Three reproduced review findings are repaired: qualified and single-component dotted names no longer share a grant; post-token validation exceptions serialize into validation_failed/not_executed with consumed-token evidence; qualified Query Skill dependencies match their actual default-schema snapshot. Metadata can use a qualified current-schema grant, and other schemas are explicitly unverified. Configuration declarations split at their first dot; SQL preserves lexical components and execution text.

48 new regressions; 1162 passed/four skipped, clean Pyright/prompt contract, 69 package files matched in a non-editable wheel install, 36 two-mode stdio calls and 12 real MySQL read-only calls. Final resident acceptance passed 18/18 native read-only checks after the maintainer restart; source hashes still match the regression/install snapshot. Full disclosure adds scope flags/arrays and return bytes; no model-cost guarantee, new runtime dependency or production AST/authorizer. [Evidence and declaration examples](../validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md) retain old/failed trials and distinguish reported earlier restart results from new acceptance.

## v3.8.1 Internal schema binding and view readiness follow-up (October 15, 2026)

### Why / Decision / Contract / Compromises / Validation

| Area | Result |
| --- | --- |
| Why | Metadata authorization selected main.orders, but sample/exact SQL could read a shadowing temp object; view Skills falsely failed a table-only readiness snapshot; invalid callback result fields could still fail JSON encoding. |
| Decision / Contract | Authorize/render one structured metadata identity; bind MySQL metadata to configured schema. Observe tables/views without estimates for readiness. Validate mutation returns before preview/token or imperative execution; reject malformed results with fixed validation_failed/not_executed and accurate token semantics. |
| Compromises | Table discovery stays table-only; readiness is not full view semantics or writeability. New adapters implement explicit metadata scope/relation observation. MySQL temp lifecycle and production AST/authorizer remain separate. No new Agent step/dependency; no model-token or latency guarantee. |
| Validation | 48 new regressions, 1210 full passes/four skips, clean type/prompt checks, 60 installed stdio calls and 18 real MySQL read-only calls; 20/20 configured-tool native checks passed after the maintainer restart. |

DRR-2026-091–093; [source-attributed evidence and boundaries](../validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md). Earlier batches remain dated; version stays 3.8.1.

## v3.8.1 Literal SQLite internal-name prefix (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | NOT LIKE sqlite_% treats underscore as a wildcard and hides legitimate sqliteX... tables/views, causing false Skill missing-table refusals. Current sampling guides also overstated MySQL temporary-object isolation. |
| Contract | Both SQLite directories share literal seven-character sqlite_ comparison with ASCII NOCASE; internal objects remain excluded. SQLite main isolation and MySQL configured-database binding/same-session temporary-table limitation are documented separately. |
| Compromises | No grant/identifier/API/dependency change; table discovery stays table-only. Session isolation and production AST/authorizer remain separate. |
| Validation | 12 new cases; 1222 full passes/four skips; clean type/prompt checks, 72 matching before/after Client calls per snapshot, 84 installed CLI/stdio calls. After the maintainer restart, 16/16 configured-tool native checks passed; the special prefix fixture remains isolated-test evidence, and earlier native evidence keeps its source attribution. |

DRR-2026-094; [evidence](../validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md). Version remains 3.8.1.

## v3.8.1 Complete Agent business-task acceptance (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | Single-call smoke and deterministic regressions do not establish that an Agent can finish a realistic business task across discovery, queries, changing scope, failures and previews. |
| Method | Freeze four scripts and independent truth; fresh native GPT-6 Luna medium contexts, three trials per script. Record final outcomes, scope and efficiency separately. |
| Validation | 12 complete trials, 36 user turns, 110 observable MCP returns, 161 model responses; business and scope checks pass. Seven SQLite table fingerprints and MySQL aggregate checks remain unchanged. |
| Observations | Retain floating-point self-checks, category/type confusion, seven empty searches, three early additional previews, repeated/truncated tool discovery and conservative readiness wording. |
| Limits | Read-only and preview/cancellation only; actual writes, rollback/conflicts/expiry/MRTR, anomalous financial fixtures, broader samples and matched historical cost comparisons remain separate. No production source or configuration change; version stays 3.8.1. |

See [task scripts, measured usage and public evidence](../validation/v3.8/V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md).

## v3.8.1 Unicode reserved-name correction and documentation navigation (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | Unicode lowercasing mapped Kelvin-sign business table names to reserved PRAGMA spellings; uppercasing also mapped a long-s business column to CURRENT_USER. Raw reads failed and legitimate Query Skills were skipped. |
| Contract | Reuse ASCII identifier folding for both PRAGMA branches, account names and internal parser defaults. Actual ASCII reserved names remain rejected; read grants, metadata identifier syntax, APIs, dependencies and prompts are unchanged. |
| Documentation | Remove dated review notices from README/index headers. Keep short changelog summaries, decisions in refactoring logs and dated records under the validation index; preserve historical evidence. |
| Validation | 56 new regressions, 1278 full passes/four skips, clean final type/prompt checks, 26 matching-input Client calls per stage and 26 installed CLI/stdio checks. After the maintainer restart, the same three corrected native probes, two genuine-reservation controls and an existing Query Skill passed 6/6; the prior refusal is retained without a cache root-cause claim. |
| Limits | Function-name classification does not guarantee an ordinary table is callable or a custom function exists. No new MySQL Unicode/model-cost result or AST/authorizer scope. Earlier Agent trials retain their source attribution. |

DRR-2026-095; [decisions, retained failed attempts and evidence](../validation/v3.8/V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md). Version remains 3.8.1.

## v3.8.1 Lexical relation boundaries and quoted reserved calls (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | Contextual table names and Unicode lookalikes could disappear from relation authorization. Unicode-normalized token values also caused false refusals, while quoted file/account calls escaped existing reservations. |
| Contract | Resolve relation target positions before clause boundaries; retain structured identities. Compare SQL vocabulary from original spellings with ASCII folding and share actual-call recognition across standard quotes. Existing grants and reserved function categories remain unchanged. |
| Validation | 107 new cases; 1385 full passes/four skips, clean type/prompt checks, 68 identical-input Client calls per stage, 68 installed CLI/stdio calls and 12 current-source real MySQL checks. A 97-name/542-case native audit finds no further unapproved scope miss. |
| Limits | Eighteen unquoted forms remain conservatively rejected, with 18 verified standard-quote recoveries; quoted CTE column lists remain limited. No complete dialect/AST/authorizer or model-cost claim. After the maintainer restart, the same four probes and positive controls passed 10/10 natively; previous patch's 6/6 acceptance stays separate. |

DRR-2026-096; [findings, source attribution and evidence](../validation/v3.8/V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md). Version remains 3.8.1.

## v3.8.1 CTE declaration exclusions retain body checks (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | A quoted CTE column list can group with AS/body inside one Identifier. Excluding the container hid real calls under all scope. Lock/delay rules already had the omission; the previous shared-scanner consolidation extended it to file/account calls. |
| Contract | Exclude only original name/column leaves before the declaration-level AS, tracking parentheses. Body calls retain existing restrictions; malformed boundaries do not enlarge the exclusion. No new function category, dependency, tool step or production AST/authorizer. |
| Validation | 132 new cases; 1517 full passes/four skips, clean type/prompt; 80 matching-input Client calls per stage, 80 installed CLI/stdio and 12 real MySQL checks. All 96 prior allowances in 576 harmless-UDF cases close; 1000 further relation-context cases and the repeated 542-case matrix show no further scope omission. |
| Limits | Existing quoted-CTE relation/readiness and MATERIALIZED classification limits remain separate. Native all-scope reproduction is not claimed for current aliases; previous patch's 10/10 native result remains dated. After the maintainer restart, identical native probes and positive controls passed 10/10; preceding refusals remain recorded without a cache root-cause claim. |

DRR-2026-097; [origin comparison, evidence and remaining limits](../validation/v3.8/V3_8_1_CTE_HEADER_2026_10_15_ZH.md). Version remains 3.8.1.

## v3.8.1 Ambiguous WITH recovery and open CTE limits (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | Some legal SQLite unquoted CTE names are classified UNKNOWN and received read_only_required with conditional write guidance. Hash-verified earlier classifiers reproduce this existing functional limitation; native before-change results match source. |
| Contract | Unclassified WITH remains denied, now as sql_parse_failed with same-connection quoting/simplification guidance. Known writes keep their rejection and explicit approval path. No WITH-prefix allowance, SQL rewriting or new dependency/tool step. |
| Validation | 43 new cases; 1560 full passes/four skips, clean type/prompt, 76 matching-input calls per stage, 76 installed CLI/stdio and 12 current-source MySQL checks. Forty-seven cases show unchanged acceptance; 38 have native read truth. |
| Compromises | Unquoted-name support remains open for shared analysis/AST, including separate materialization/readiness limits. Consistent quoting recovers the tested simple cases, not all CTE grammar. |
| Native scope | After the maintainer restart, eight identical inputs plus reserved-call/normal-Skill controls match the new diagnostics, 10/10, with matching text/structured results. Keep old observations and model usage source-attributed; bare-name support remains open. |
| Follow-up assessment | 314 candidates/304 native-valid reads, 56 private Client observations and nine native spot observations confirm common business-name, quoted-column-list/readiness and specific comment/declaration false refusals. Recommend a bounded shared-analysis repair soon; no additional production change or workload failure-rate claim. Observed tool errors and the corrected comment-position expectation are retained. |

DRR-2026-098; [findings, remaining support gap and evidence](../validation/v3.8/V3_8_1_CTE_CLASSIFICATION_2026_10_15_ZH.md). Version remains 3.8.1.

## v3.8.1 Shared CTE structure and functional support (October 15, 2026)

| Area | Decision / Result |
| --- | --- |
| Why | Common business/Unicode CTE names, quoted declaration columns, specific comments and materialization forms failed classification or created false Skill dependencies. Adjacent lexer grouping also affected like/regexp/replace and Unicode WHERE membership. |
| Decision | Share original-leaf WITH structure and relation-target selection across classification, authorization and dependency analysis. Preserve identifiers, declaration order, connection-specific case and explicit recursion; analyze fragments without rewriting executed SQL. No full production AST/authorizer or new dependency/tool step. |
| Contract | Known main/body writes and reserved calls remain denied; declaration exclusions include name/column leaves only. Malformed or unresolved WITH gets read-query recovery. Database dialect validity is distinct from structural acceptance; SQLite syntax is not a MySQL guarantee. |
| Validation | 1750 full passes/four skips, clean type/prompt; 56 matching-input Client checks, 96 installed CLI/stdio checks/70 resource hashes, 24 real MySQL checks. All 300 native-valid functional cases pass both scopes; all four unauthorized controls remain denied. Adjacent 542 name/1000 context cases show no scope misses or approved refusals; 576 harmless reserved-call fixtures remain denied. |
| Costs / limits | Local serial policy A/B/A p95: 13.12/17.71/16.15 ms, including baseline drift and added parsing. No speedup, unchanged latency or model-token claim. Preserve sandbox interruption, obsolete test expectations and prior source-specific native/model evidence. |
| Native scope | After the maintainer restart, 20/20 native checks pass with matching text/structured results: ten exact baseline inputs and ten adjacent/refusal/MySQL/ordinary-Skill controls. Keep the old refusal checkpoint and prior diagnostic/model evidence separate; full CTE Skill readiness remains private Client/installed evidence. |

DRR-2026-099 repairs the reproduced functional gap in 098; [implementation, costs and evidence](../validation/v3.8/V3_8_1_CTE_ANALYSIS_2026_10_15_ZH.md). Version remains 3.8.1.
