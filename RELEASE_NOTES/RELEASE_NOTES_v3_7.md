# Release Notes v3.7 — Scoped Skills and v3.7.2 Maintenance

- Release family: v3.7
- Initial release: v3.7.0 (2026-08-22)
- Current maintenance update: v3.7.2 (2026-09-10)

## v3.7.2 — Write Transactions and Uncertain Results

v3.7.2 moves exact affected-row enforcement into `execute_write()` before
COMMIT and makes the mutation outcome machine-readable. Its rule is: roll back
errors proved before COMMIT; report `unknown` when a COMMIT acknowledgement is
lost; never let post-COMMIT cleanup, audit, or response preparation claim that
the write rolled back. The design follows SQLAlchemy's explicit
`Connection.begin()`/`Transaction.commit()` boundary and Microsoft's documented
commit-failure ambiguity: a COMMIT exception can mean either server-side abort
or successful commit with a lost acknowledgement. A later rollback attempt is
cleanup, not proof that the earlier COMMIT failed.

### Adapter and built-in Skill changes

- `DatabaseAdapter.execute_write()` and both adapters accept keyword-only
  `expected_rowcount: int | None = None`. `None` preserves legal batch writes;
  any specified value must be a non-negative integer, and booleans are rejected
  before connection acquisition.
- Statement execution is followed by the row-count check and only then COMMIT.
  Mismatch raises `ExpectedRowcountMismatchError`; a confirmed rollback carries
  `rolled_back`, while rollback failure carries `unknown`.
- Rollback confirmation also requires an active transaction and a valid
  SQLAlchemy/DBAPI connection before rollback and a valid connection afterward.
  An invalidated/closed connection or an inactive transaction can make rollback
  a local no-op; this remains `unknown` with `rollback_failed`, even when the
  method returns normally. Inspection must not reconnect to a different session.
- `WriteExecutionResult`, `WriteExecutionError`, `WriteExecutionPhase`, and
  `WriteExecutionOutcome` preserve phase/outcome evidence internally while the
  public successful result remains the compatible
  `{"success": true, "rowcount": N}` mapping.
- MySQL retains `innodb_lock_wait_timeout`; SQLite retains its progress handler.
  Every exception/cancellation path attempts transaction, handler, and
  connection cleanup, and neither adapter retries SQL.
- `update-order-status` and `reset-demo-order-to-pending` now pass
  `expected_rowcount=1`; their old post-COMMIT `rowcount == 0` checks were
  removed. Zero rows therefore roll back a stale-preview update, and more than
  one row rolls back an unsafe target-cardinality update.
- Precise whole-Skill success and rollback evidence is intentionally enabled
  only for these two built-in single-statement Skills. They preserve the
  adapter's typed `WriteExecutionResult` while keeping its public dict shape;
  `MutationBase` and the MCP boundary independently require that evidence before
  they can emit `committed`.
  Custom Skills keep the existing dict interface, but an ordinary successful
  return is conservatively `success=true, execution_outcome=unknown`. Neither
  success nor statement-local rollback evidence is promoted to a whole-Skill
  transaction claim, because custom code may have issued other writes or
  external side effects. No general multi-statement framework was added.

### MCP contract

Every structured `execute_mutation_skill()` result now includes
`execution_outcome`:

| Value | Meaning |
|---|---|
| `not_executed` | No business write was attempted. |
| `rolled_back` | The supported transaction was confirmed rolled back. |
| `committed` | Database COMMIT was confirmed. |
| `unknown` | The final business-write state could not be confirmed. |

`success` describes tool handling, not database state. A normal built-in execute
with adapter COMMIT evidence returns `success=true,
execution_outcome=committed`; a custom Skill's normal completion without
whole-operation evidence returns `success=true, execution_outcome=unknown`. A
recoverable execution failure returns `success=false`, a stable `error_code`,
and a sanitized `error` instead of raising `ToolError`. Static parameter,
permission, Skill loading, and preview-token rejection still raise `ToolError`.
Preview and dynamic-validation results use `not_executed`.

Stable failure codes are `validation_failed`, `preview_failed`,
`expected_rowcount_mismatch`, `database_execution_failed`, `rollback_failed`,
`commit_outcome_unknown`, `execution_outcome_unknown`, and
`response_preparation_failed`; custom/exact-Skill contract violations use
`invalid_skill_result` and `missing_commit_evidence`. `outputSchema`,
`ToolResult.meta`, and JSONL audit entries carry the corresponding outcome/code.
Business failures set metadata
`success=false`; every structured validation, preview, or transaction failure
is submitted to the best-effort audit path as a business failure, with
`audit_logged` reporting whether persistence succeeded. If response preparation
fails after confirmed COMMIT and a fallback can still be delivered, it returns
`success=false, execution_outcome=committed`; for a custom success lacking
COMMIT evidence, the fallback preserves `unknown` rather than upgrading it. The
already-written success audit is retained and no contradictory “database
execution failed” audit is added.
If the transport loses the entire response, the client can only classify the
result as unknown.

This is a compatibility change: callers must inspect both `success` and
`execution_outcome`; “the tool did not raise” no longer proves a mutation
succeeded. The tool annotation remains `idempotentHint=false`.

### Approval host and retry rule

The reference host validates `mode`, `skill_name`, resolved `connection_id`,
and `db_type` before interpreting an outcome. It maps unknown enums, missing or
contradictory fields, malformed responses, identity mismatch, exceptions, and
timeouts to terminal `execute_unknown`. A valid `success=true,
execution_outcome=unknown` custom-Skill response is also terminal unknown rather
than a contradictory response. `committed` is terminal even when
`success=false`; `rolled_back` and `not_executed` are also terminal. The current
workflow performs at most one execute and never automatically re-previews,
re-executes, changes server instance, or switches connection after any execute
result.

For old servers, only a fully identified `success=true`, `mode=execute` response
with an object `result` is accepted as executed. An old failure without explicit
transaction evidence is `execute_unknown`. This deliberately retained legacy
success classification is compatibility behavior, not new COMMIT evidence: an
old server cannot distinguish a custom handler return from a confirmed commit.
Upgrade the server before relying on the v3.7.2 outcome guarantee.

### Verification, compromises, and remaining risks

- Review regressions use real SQLAlchemy RootTransaction objects to cover
  connection invalidation during execution or rollback and already-closed
  connections. Both adapter control flows are exercised with isolated SQLite
  engines; these are SQLAlchemy evidence tests, not MySQL network-failure proof.
- Custom `run_execute()` overrides that raise ordinary exceptions or ToolError
  now return sanitized `unknown` and attempt one failure audit. A previously
  committed statement cannot be reclassified from a later statement's rollback.
  Fallback audit exceptions report `audit_logged=false`; cancellation still
  propagates. Host array/object/boolean/numeric outcomes remain terminal unknown.
- If response serialization fails, the fallback discards the original result
  and includes only an integer rowcount when available. It retains the known
  outcome and the existing execution audit, without reusing unserializable
  result values or issuing another write.
- SQLite tests prove exact match commit, zero/multi-row mismatch rollback using
  actual persisted data, and unrestricted batch behavior when the invariant is
  omitted. Fault doubles cover pre-write/setup failure, execution failure,
  rollback failure, ambiguous COMMIT, post-COMMIT connection cleanup, progress
  handler cleanup, execution cancellation, COMMIT cancellation on both adapters,
  audit failure, and response failure. COMMIT cancellation is converted to
  `commit_outcome_unknown` if server execution can still prepare a result.
- Host tests cover all four outcomes, strict legacy success, legacy failure,
  identity mismatch, malformed fields, unknown enum, timeout, and the invariant
  of no calls after the single execute. Token tests retain atomic one-time
  consumption, terminal consumption after failure/cancellation, restart
  invalidation, and same-process limits.
- Success-evidence regressions cover a custom-style handler that really writes
  but still receives `unknown`, an exact Skill missing typed COMMIT evidence,
  malformed/explicit-failure custom returns, an overridden base wrapper with
  lookalike evidence, response-failure preservation, truthful fallback audit
  status, metadata/audit propagation, and the host's terminal interpretation of
  `success=true, unknown`.
- `test_mysql_stale_conditional_updates_allow_at_most_one_commit` is isolated
  behind `RUN_MYSQL_INTEGRATION_TESTS=1` and uses independent pooled
  connections. Default pytest does not contact MySQL; a skipped test is not
  evidence of MySQL concurrency behavior, and SQLite/mock results do not replace
  that proof.
- The initial 2026-09-10 default verification completed with `561 passed, 4 skipped`.
  The skips are environment/opt-in cases, including the new real-MySQL race;
  no live MySQL concurrency conclusion is claimed from that run. Protocol tests
  route Skill audit output to a temporary path, so validation does not append
  generated records to the repository's example audit file.
- After the review fixes, the default suite completed with `583 passed, 4 skipped`.
  Targeted Pyright checking of the seven edited Python paths reported `0 errors`
  and 35 unresolved third-party-import warnings; `git diff --check` also passed.
- Targeted Pyright checking of the changed Python paths reported `0 errors` and
  39 unresolved third-party-import warnings. The virtualenv executes those
  imports in pytest, but the Pyright resolver in this workspace does not locate
  them; this is recorded as a tooling/configuration warning rather than claimed
  as a warning-free static-analysis result.
- MySQL rollback guarantees are limited to DML on transactional InnoDB tables.
  Nontransactional tables are not undone, and MySQL documents statements that
  implicitly commit; external side effects are also outside the transaction.
- No operation table, receipt, result-query API, Redis dependency, durable state
  machine, or background worker was added. Those remain the future direction
  for resolving unknown commits. There is no generic request deduplication, no
  ABA protection for state cycles, no recovery of unknown operations after
  restart, and no expansion of multi-replica HTTP mutation support.
- Conditional UPDATEs and database constraints still protect only the business
  invariants they explicitly encode. The project cannot force arbitrary
  third-party Agents to obey “unknown means do not retry”; manual database or
  business-state inspection is the accepted recovery cost.
- `asyncio.CancelledError` during COMMIT is handled as typed `unknown`, but
  pre-COMMIT cancellation still propagates after cleanup so shutdown/timeout
  cancellation is not silently defeated. `KeyboardInterrupt`, `SystemExit`, and
  other process-control `BaseException` values also propagate after cleanup.
  When propagation or transport loss prevents a response, the client necessarily
  classifies the call as unknown even if the server had stronger local evidence.

Primary references reviewed for this design:

- [SQLAlchemy explicit transaction management](https://docs.sqlalchemy.org/en/20/core/connections.html#using-transactions)
- [Microsoft: handling transaction commit failures](https://learn.microsoft.com/en-us/ef/ef6/fundamentals/connection-resiliency/commit-failures)
- [MySQL: statements that cause an implicit commit](https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html)
- [MySQL: rollback failure for nontransactional tables](https://dev.mysql.com/doc/refman/8.0/en/nontransactional-tables.html)
- [MCP tools: structured content and output schemas](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [FastMCP ToolResult and output schemas](https://gofastmcp.com/servers/tools)

The Microsoft operation-table approach was reviewed but deliberately deferred:
it is the right family of solution for queryable commit resolution, but would
add the durable operation protocol explicitly excluded from v3.7.2. SQLAlchemy
context managers remain good ordinary transaction practice; this path uses
explicit commit because it must distinguish pre-COMMIT failure from uncertain
COMMIT acknowledgement.
- Last implementation review: 2026-09-10
- Latest default regression validation: 2026-09-10 (`583 passed, 4 skipped`)
- Latest successful MySQL read-only data-plane validation: 2026-09-03
- Status: implemented

## v3.7.1 Maintenance Follow-up — Tool Contract Clarity

Agent-visible contracts now state the limits and role boundaries already
enforced by the implementation:

- FastMCP runs with `strict_input_validation=True`, so wrong-type MCP scalar
  inputs are rejected against the published JSON Schema instead of being
  compatibly coerced. Protocol regressions cover string boolean and integer
  values. Direct Python calls bypass protocol validation, so
  `group_identical`, `exact_count`, `available_only`, and the mutation-critical
  `confirm` flag share an exact boolean handler check.
- `sample.limit` exposes JSON Schema `minimum=1`, `maximum=20`, and default 5.
  Out-of-range MCP inputs are rejected during FastMCP validation before the
  handler or SQL execution. Valid inputs and omission are unchanged. Direct
  Python calls now apply the same explicit rejection instead of silently
  clamping invalid values.
- Schema and Skill projection parameters use shared non-null `Literal` types
  through configuration parsing, function signatures, and handler validation.
  This fixes the static type mismatch on the startup-derived
  `SKILLS_LIST_DEFAULT_DETAIL`. Direct calls no longer reinterpret `None`,
  case variants, whitespace variants, or non-boolean availability values;
  omission still uses each declared default.
- Table discovery preserves an unavailable row estimate as `row_count=null`
  instead of reporting zero. This covers SQLite names that can be discovered
  but cannot be used in conservatively generated metadata SQL, as well as a
  nullable MySQL `TABLE_ROWS` estimate. `describe_table()` and the approximate
  path of `get_table_summary()` also preserve that MySQL value: `row_count`,
  `row_count_approximate`, and `is_large` are null, so an unavailable estimate
  is not presented as an empty or small table. Detailed schema projection
  retains its explicit `unsupported_metadata_identifier` failure. A SQLite
  table dropped between discovery and bounded sampling likewise produces an
  unknown estimate instead of a false zero-row result. A missing MySQL
  single-table metadata row has the same unknown semantics; a returned numeric
  zero remains zero.
- `get_table_summary.exact_count` has a machine-visible parameter warning that
  `SELECT COUNT(*)` may require a full scan, be slow on large tables, and encounter
  MySQL metadata-lock contention. Its execution behavior is unchanged.
- `query` is described as the primary free-form read-only SQL tool rather than
  the primary tool for every database task. Metadata tools remain responsible
  for schema discovery and reviewed Query Skills for defined workflows.
- `describe_table` and related hints now promise full *adapter-visible column
  metadata*, not complete DDL, indexes, foreign keys, checks, or other
  backend-specific properties.
- `list_connections` states that alias discovery does not authorize writes.
  Mutation Skills retain the default-alias compatibility mode; non-default
  aliases require strict named-write policy to authorize the connection and
  Skill. Its no-argument description and the `sql_assistant` prompt no longer
  instruct callers to omit a nonexistent `connection_id` parameter.
- The `sql_assistant` prompt and maintained Agent example include
  `connection_id` in the `list_skills` signature.
- The maintained AutoGen example now lists all six core tools, uses compact
  discovery without mandatory redundant chains, requests exact counts only
  when precision is needed, and carries the returned preview token plus the
  same params/connection into mutation execution.
- README examples now distinguish pre-truncation `total_tables` from returned
  tables, include adapter defaults and required mutation `source`, keep
  `is_large` examples internally consistent, and state the sanitized metadata
  failure contract for affected schema tools.

This is a small contract correction, not a new abstraction: no tool, database
operation, backend, or configuration was added. It applies FastMCP's documented
Python-signature, `Literal`, default, and `Annotated`/`Field` patterns and MCP's
use of tool descriptions plus `inputSchema` as the model-callable contract.

The focused adapter/schema/Skills/multi-connection contract suites passed `203
passed, 3 skipped`, and the default suite reported `521 passed, 3 skipped`.
Pyright 1.1.411 reported `0 errors, 0 warnings` across all eight currently
modified Python files when configured against the project virtual environment.
A disposable SQLite FastMCP Client
verified the exact schema, pre-handler rejection of limits 0 and 21, and
successful endpoints 1 and 20; direct-call tests verify the same rejection and
strict projection/filter values. Adapter and core-tool regressions preserve
unknown row estimates as null, including the single-table paths. A fresh stdio
server also passed the maintained read-only
MySQL client smoke and exposed the revised core descriptions and row-estimate
hint. The configured deployment did not register the optional tools, so their
MCP parameter contract was verified in the isolated protocol probe rather than
inferred from that Host.

A separate fresh FastMCP 3.0.2 stdio probe exposed `detail_level=compact` and
`group_identical=true` as concrete schema defaults, rejected the string boolean
`"false"`, and returned the configured read-only MySQL schema as 8 tables, 272
columns, and 4 compact groups without truncation. A previously connected VS
Code Host initially continued to expose its cached old schema. After tool
rediscovery, that Host exposed the concrete compact and boolean defaults and
its direct default call reproduced the 8-table, 272-column, 4-group result.
Restarting only the server process is still insufficient evidence that a
long-running Host refreshed its model-visible definitions; verify its own
`tools/list` before Agent behavior testing.

- [FastMCP tool parameter metadata](https://gofastmcp.com/servers/tools)
- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [Google Vertex AI function-calling guidance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling)
- [Anthropic tool-definition guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [MySQL `INFORMATION_SCHEMA.TABLES` reference](https://dev.mysql.com/doc/refman/8.4/en/information-schema-tables-table.html)

## v3.7.1 Maintenance Follow-up — Progressive Schema Projection

`get_full_schema()` now accepts `detail_level="compact"` or `"full"`.
Its non-null machine-visible default is `"compact"`; omission is equivalent to
explicit compact with `group_identical=true`, so the default response uses
`schema_groups`. Callers request full explicitly for nullable/default/key
metadata across multiple tables. Server and prompt guidance likewise use
compact for broad schema explanations and multi-table planning. Compact output
retains every returned table name, approximate row count, column count,
`[name, type]` pairs, and primary key. With `group_identical=true`, tables share
one group only when their complete current adapter-visible column metadata and
column order are equal. This does not establish complete DDL, index, or
constraint equivalence; compact responses state the basis in `grouping_basis`.
`describe_table()` remains the full single-table drill-down.

Adapter metadata failures no longer collapse into successful empty discovery,
empty schema, missing-table, or zero-row results. Table, column, statistics, and
bounded row-sampling failures raise a sanitized adapter signal; schema tools
return `success=false` with `error_code="metadata_query_failed"` and no partial
projection. Legitimately empty databases and missing tables remain distinct.
Database-discovered names outside the schema tools' conservative identifier
grammar fail separately as `unsupported_metadata_identifier`.

Skills readiness now preserves metadata availability as a separate state. With
`SKILLS_CHECK_SCHEMA_ON_LIST=1`, a sanitized metadata failure yields
`schema_check_available=false`; table-dependent Skills report
`schema_ready=false` without inventing `missing_tables`, are hidden by
`available_only=true`, and fail closed at execution before query SQL, mutation
preview, token issuance, or database writes. `available_only=false` still
returns the developer catalog and disabled reason. Unexpected programming
exceptions are no longer swallowed by the readiness helper.

A live MySQL fixture with 8 visible tables and 272 columns produced a
pre-change Host-rendered full result of 36,676 characters / 9,270
`o200k_base` tokens. After the Agent-guidance refinement, grouped compact output
measured 8,732 / 2,068 in a fresh process; its projection and grouping semantics
were also reproduced through the direct MCP Host. This is a 76.2% character and
77.7% token reduction. Minified payloads fell from 18,404 / 5,314 to 3,728 /
1,128 (79.7% / 78.8%). Current full output, which now also retains adapter
defaults, measured 44,300 / 10,946; compact saved 80.3% / 81.1% against that
richer response. Ungrouped compact measured 20,125 / 4,660, so grouping five
`va_*` tables whose adapter-visible column metadata and order were verified
equal saved another 56.6% / 55.6%.
One 41-column `describe_table()` response measured about 1,094 tokens,
explaining why Host truncation followed by repeated drill-downs can push a broad
overview task into the reported 13,500–15,000-token range. These are fixture-,
Host-, serialization-, and tokenizer-specific measurements, not protocol
guarantees.

The reloaded Host accepted explicit `full`, grouped `compact`, and ungrouped
`compact` calls. A separate low-context `MCP Runner`, given only a broad schema
overview goal and the exact alias, independently chose
`list_tables -> get_full_schema(compact, group_identical=true)`. Because compact
already includes table names and row estimates, that trace motivated a further
description refinement: use `list_tables` only when names/counts are enough and
call compact directly when broad columns are already required. Fresh-process
tool-contract tests pass. After the MCP service restart, three independent
low-context runs under the same task conditions selected direct grouped compact
in `2/3` cases; one run retained the leading `list_tables` call. All three
completed correctly without truncation, full schema, `describe_table`, or SQL.
They made four calls in total (1.33 per run). Based on the measured pretty
payloads, the average schema result was about 2,191 tokens: 5.9% above the
all-direct 2,068-token floor and 77.3% below the approximately 9,638-token old
`list_tables + pre-change full` path. This is a small, non-randomized,
payload-only observation, not a guarantee across models or Hosts.

Post-fix validation completed with `69 passed, 3 skipped` for the focused
adapter/schema suite. The Skills readiness follow-up completed with `83 passed`
for its focused disclosure/mutation suite. After finalizing the compact default
and non-null Skills defaults, the focused schema/Skills suite passed `56` tests
and the default repository suite passed `485 passed, 3 skipped`. A 2026-09-02
fresh stdio registration confirmed the non-null `compact|full` enum with
default `compact`; its configured MySQL connectivity check then returned the
sanitized database failure and the smoke skipped before schema or SQL calls.
At that validation point, the latest successful MySQL read-only data-plane
projection was the 2026-09-01 run. The later tool-contract smoke above passed
against MySQL on 2026-09-02. No mutation or database write was attempted.

The design applies Anthropic's general recommendation to filter and aggregate
large tool results before model context, but does so in the MCP server because
Anthropic's current programmatic tool-calling documentation excludes tools from
MCP connectors. MCP `structuredContent` keeps the projection machine-readable;
an `outputSchema` would improve validation but does not itself compress results,
so no large result schema was added in this follow-up.

- [Anthropic programmatic tool calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling)
- [Anthropic tool-definition guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [FastMCP tool parameter metadata](https://gofastmcp.com/servers/tools)
- [Google Vertex AI function-calling guidance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling)
- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

## v3.7.1 Maintenance Update — Opaque Preview Handles and Agent Workflow Efficiency

v3.7.1 keeps the public `preview_token` field and two-call mutation workflow,
but replaces the client-visible self-describing HMAC envelope with a random
256-bit opaque bearer handle. The authoritative bounded process-local Store now
owns expiry, exact request binding, preview-time execution state, and atomic
conditional consumption. A request-binding mismatch preserves the valid record;
a matching request consumes it once before dynamic validation and database
writes. TTL, default capacity, write authorization, optimistic locking, terminal
consumption, and the same-process deployment boundary are unchanged.

### Why the opaque handle

The v3.7.1 handle is a new server-side-state design, not a truncated form of
the old envelope:

| Aspect | v3.7.0 HMAC envelope | v3.7.1 opaque handle |
|---|---|---|
| Client-visible value | Signed JSON payload containing request metadata | 32 random bytes encoded as a URL-safe value; currently 43 characters |
| State location | The token carried part of the signed state while the Store remained necessary for one-time use and preview-time execution state | Request binding, execution binding, expiry, and consumption state are all authoritative in the Store |
| Lookup and validation | Verify and parse the HMAC payload, then consult the Store | Hash the handle, look up its digest, and atomically compare the request binding and consume the record under one lock |
| One-time consumption | Preserved | Preserved |
| Skill/params/connection binding | Preserved | Preserved, recomputed from the execute request and compared with the Store record |
| Replay and concurrent-use rejection | Preserved | Preserved |
| Multi-worker or restart continuity | Not supported because the authoritative Store was process-local | Still not supported; a missing process-local record fails closed and requires a new preview |

This follows the general opaque-identifier pattern: the client receives a
high-entropy, non-descriptive reference while the server keeps the associated
state. OWASP recommends unpredictable, meaningless client-side identifiers and
server-side storage of their associated application state; Python's `secrets`
module supplies the CSPRNG used by `token_urlsafe(32)`. RFC 7662 separately
illustrates that an unstructured token can be resolved through a server-side
data-store lookup. These are design analogies, not claims that a preview handle
is a web session, OAuth token, authenticated human approval, or complete
authorization boundary. Connection write policy and Skill allowlists remain
separate runtime checks.

The Store retains only the handle digest, not the complete bearer value. This
supports lookup without persisting the credential itself and is consistent
with OWASP guidance not to record session identifiers or access tokens directly
in logs. The handle must nevertheless be treated as a bearer secret: disclosure
can permit the one matching mutation before consumption or expiry. Shortening
the value reduces model context, copy errors, and client-visible internal state;
it does not make disclosure harmless.

The stateful design also keeps its existing costs. Store loss or process restart
invalidates outstanding handles; workers or replicas cannot share them; repeated
preview-only calls can fill the bounded Store until expiry; and a disconnect
after consumption can still leave the database outcome unknown. TTL, the
capacity limit, fail-closed issuance, same-process deployment, and the no-blind-
retry rule remain necessary.

- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [Python `secrets` documentation](https://docs.python.org/3/library/secrets.html)
- [RFC 7662: OAuth 2.0 Token Introspection](https://datatracker.ietf.org/doc/html/rfc7662)

The maintenance update also adds
`get_skill_detail(detail_level="execution")` as a compact invocation projection.
`full` remains the `get_skill_detail` default. Its input and the two configured
`list_skills` defaults are now represented by concrete non-null enum/boolean
defaults in the MCP input schema rather than by misleading `null` defaults.
Agent guidance now skips a
redundant detail call after `list_skills(detail_level="full")` and whenever the
Skill parameters are already known. Exact aliases are preserved, a unique DB
type match may be selected only after `list_connections()`, and purpose-only
descriptions never authorize guessing an alias.

The generic `sql_assistant` prompt no longer reports the default connection's
UNION configuration as if it applied to every alias. It directs callers to the
selected alias's non-sensitive policy summary from `list_connections()`; raw
queries and Query Skills continue to enforce the resolved target policy at
runtime. Startup logs now label their legacy/default-policy UNION summary with
the default alias, and a missing UNION allowlist now directs operators to the
selected connection's policy rather than implying a global setting. The
standalone `sql_safety_checker.execute_sql()` compatibility
helper remains only a statement-shape gate and does not enforce
`ALLOW_UNION`/`ALLOWED_TABLES`; callers needing the full connection policy must
use the MCP tools. This boundary is recorded in the design risk register rather
than duplicated through a circular server import.

### Compatibility and migration

- `preview_token` remains an API-opaque bearer value; clients that treated it as
  opaque continue to pass it unchanged. Its length and internal format are not
  a compatibility contract.
- `MUTATION_PREVIEW_TOKEN_SECRET` is obsolete and ignored. If it remains set,
  startup emits a value-free warning; remove it from active configuration.
- Preview keeps `preview_token_expires_at`. To reduce duplicate Agent context,
  v3.7.1 removes `preview_token_expires_in_seconds`, the top-level preview
  `hint`, and nested `preview.requires_confirmation`. Clients that consumed
  these convenience fields must migrate to the absolute expiry and the
  tool/Skill-detail contract rather than depend on those duplicated fields.
- `get_full_schema()` now defaults to grouped compact output. Callers that need
  the table-keyed full projection must pass `detail_level="full"` explicitly.
- The `get_skill_detail` input accepts `detail_level="execution"`; its non-null
  machine default remains `full`. `list_skills.detail_level` and
  `list_skills.available_only` expose the server's startup-resolved defaults.
- Tool names, mutation request arguments, two-phase preview/execute behavior,
  TTL/capacity settings, connection policy, and database-write semantics remain
  unchanged. A process restart during upgrade invalidates all outstanding
  preview values because the Store is intentionally process-local.
- Once a handle has been consumed, an exception or disconnect can leave the
  caller unable to determine whether the database committed. The caller must
  inspect current business state before another preview or mutation; it must not
  blindly retry. Durable operation records and a reconnect status API remain a
  future product-level design, not part of v3.7.1.

### v3.7.1 validation

On 2026-08-28, the default repository suite passed with 468 tests and 3 skipped;
the explicit root legacy smoke passed 2 tests. Focused connection, Skills,
mutation, and disclosure regressions also passed, and `git diff --check` found
no whitespace errors. This includes opposite default/target UNION policies,
per-alias disclosure, and a target-neutral prompt.

On 2026-08-26, a restarted configured MCP service completed a reversible
`live_test_sqlite` mutation flow with the v3.7.1 opaque handle: request mismatch
preserved the handle, the matching request consumed it, replay failed, and the
fixture was restored. On 2026-08-28, a fresh stdio subprocess also completed the
approval-host flow: literal `APPROVE` returned exit code 0 with `rowcount=1`,
while `NO` returned exit code 3 and did not call execute. A separate fresh
subprocess temporarily enabled UNION only for `analytics_demo_sqlite`; both a
raw query and a Query Skill harness returned a real two-row UNION there while
the default MySQL target remained denied.
The current configured MySQL was later checked successfully with read-only
`SELECT 1` and `COUNT(*)`; an earlier same-day timeout remains recorded as a
negative environment observation. Full timings, payload summaries, and
evidence boundaries are in `LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`.

## v3.7.0 Initial Release — Historical Baseline

The remaining sections describe v3.7.0. At that release, v3.7.0 added an
optional, deployment-aware connection scope to `skill_def.md`,
a portable demo/test reset mutation, a dependency-light stdio example for explicit
host-side mutation approval, and supported-dialect SQL policy hardening.
It is an incremental release: existing Skills that use the documented
frontmatter schema and omit the new field retain their v3.6.1 routing behavior,
and the mutation preview-token format, TTL,
capacity, execution binding, and existing write-authorization protocol do not
change. Raw SQL grammar and malformed Skill metadata are intentionally tightened
as described below.

## 1. Optional `connection_ids` Skill Scope (v3.7.0)

Skill authors may now restrict a Skill to one or more valid connection-alias
identifiers. Only members configured in the current deployment can execute:

```yaml
databases: [mysql]
connection_ids: [orders_primary, orders_reporting]
```

`databases` and `connection_ids` have different meanings:

- `databases` declares compatible DB types/dialects such as `mysql` or
  `sqlite`.
- `connection_ids` declares server alias identifiers on which the Skill may
  run. One item expresses exact binding; multiple items intentionally support
  reuse. Portable unconfigured members remain metadata and are reported
  unavailable rather than failing discovery.
- Omitting `connection_ids` means no additional Skill-level alias restriction,
  preserving prior behavior.

The parser accepts only a non-empty YAML list. Entries are normalized to
lowercase, syntax-checked with the same safe alias shape, checked for duplicates,
and sorted for deterministic disclosure. Empty/non-string values, normalized
duplicates, DSNs, paths, wildcards, and the singular `connection_id` field fail
Skill discovery. Unknown top-level fields and duplicate YAML mapping keys also
fail closed, so a typo such as `connections_ids` cannot silently remove the
intended restriction. Sorting is not routing: an omitted runtime `connection_id`
continues to resolve the global default and is then checked against the Skill
scope; the server never chooses the only/first list member automatically.
The loader mirrors the safe alias regex locally instead of adding a direct
dependency on `db_adapter`; it already reaches runtime configuration indirectly
through the SQL safety module. The mirrored definitions and tests must remain
aligned. Scope availability is based on the startup connection
registry, so connection aliases/types require a server restart to change.

The effective target is an intersection:

```text
configured target
  ∩ Skill connection_ids (when present)
  ∩ Skill databases (when present)
  ∩ profile/schema/table/query policy
  ∩ mutation target/switch/Skill allowlist (for writes)
```

`connection_ids` can only narrow access. It does not create a connection,
select credentials, or grant read/write authorization. Execution rechecks
`connection_ids` and `databases` before adapter construction; existing
profile/schema/table/query/mutation gates remain independent and run before
query execution or writes. Discovery filtering is not treated as an
authorization boundary. Preview tokens still bind the one resolved target.

Portable Skills may mention aliases not configured in a deployment. Those
aliases are reported as unavailable and produce a startup warning rather than
creating a dynamic target. If a configured alias has a DB type incompatible
with `databases`, that target fails closed and produces a startup error; other
valid members of the same list remain usable. This per-target behavior preserves
multi-target reuse and the intersection model without weakening any target.

Known metadata values now fail closed as well. Declared boolean fields must be
YAML booleans, catalog lists must be lists of strings, and category must be a
non-empty string. Each parameter declaration accepts only
`type`/`required`/`min`/`max`/`enum`/`description`; constraint values must match
the parameter type, enum must be a non-empty list, and numeric bounds must be
ordered. This completes the existing lightweight Skill DSL rather than adding
a second JSON Schema implementation.

Prefer semantic aliases such as `orders_primary`, `trade_analysis_mysql`, or
`analytics_demo_sqlite`.
`mysql` and `sqlite` remain legal aliases but can be confused with DB-type
values. Direct Python use of `skill_loader` or a Mutation class bypasses the MCP
routing layer, so an embedding application must enforce an equivalent target
policy itself.

## 2. Manual Mutation Approval Host Example

`examples/manual_mutation_approval.py` is a one-shot, stdio-only reference host.
It uses the active Python interpreter (`sys.executable`, so the current venv is
preserved), explicitly passes the operator's complete process environment to
the local server subprocess, and keeps preview and execute inside one FastMCP
client context and one server process, as required by the process-local store.
Explicit inheritance prevents exported `DB_*` and Skill policy from silently
being replaced by a different project `.env`. The server script is fixed to
this trusted repository rather than accepted as a CLI argument.

The host:

1. canonicalizes a finite-JSON request snapshot and calls `confirm=false`;
2. strictly validates the preview result and expiry;
3. separates the bearer token from an `ApprovalView` that contains only the
   exact Skill, params, resolved alias, DB type, business preview, expiry, and
   idempotency flag;
4. accepts only the literal input `APPROVE` before a workflow-enforced monotonic
   deadline bounded by the token's remaining lifetime (with a safety margin);
5. verifies that a custom approval provider did not modify the displayed params
   or preview, then executes once with the snapshot and preview-resolved alias;
   and
6. never automatically retries an execute error/timeout because the token may
   be consumed and the write result may be unknown.

Use a JSON `--params-file` instead of inline JSON so business parameters do not
enter shell history. The example does not output or persist the full token, and
its returned outcome removes the token field and redacts the exact bearer value
if an abnormal server echoes it in another returned string. It cannot prevent
FastMCP/protocol payload logging outside the example and cannot securely erase
Python objects from memory.
The rendered params/preview, printed execute result, and JSON params file may
contain sensitive business data even though the token is hidden; protect the
file, terminal, screen sharing, and terminal/session capture. Complete process
environment inheritance is an explicit trusted-local-host compromise: it also
forwards unrelated exported secrets and Python control variables into the
server/Skill subprocess trust boundary. A productized host should maintain a
project-specific environment allowlist instead of inheriting everything.

This example is confirmation-ready host behavior, not proof of human identity.
The MCP server still cannot tell whether a particular human reviewed the
preview, and another client may bypass this host. Denial, timeout, EOF, or
cancellation does not call execute and does not notify the server to revoke the
unused token; its bounded store entry remains until expiry/lazy cleanup, while
the server records only its normal preview audit. Deployments needing approver
authentication, separation of duties, durable denial audit, or multi-user
remote approval require a product-owned approval service. v3.7 does not add
multi-user authenticated HTTP mutation.

Example invocation:

```bash
.venv/bin/python examples/manual_mutation_approval.py \
  --skill update-order-status \
  --params-file /path/to/update-order.json \
  --connection-id orders_primary
```

## 3. Portable Demo Reset Mutation and SQL Policy Hardening

The new `reset-demo-order-to-pending` Skill demonstrates a low-freedom write:
the caller supplies `order_id` plus the exact non-pending `expected_status`
produced by a preceding test, while reviewed code fixes the target to `pending`.
The displayed source state is bound into the token and repeated in the
transactional optimistic-lock predicate. The parameterized SQL is compatible
with MySQL and SQLite, so `databases: [mysql, sqlite]` declares both types. The
commented multi-alias `connection_ids` line is an optional deployment example,
not an active permission or hidden route.

This Skill is a demo/test compensating operation, not a production order reopen
or a transactional rollback. It lets a live test both assert the state produced
by an earlier mutation and restore a reusable fixture. `orders.id` must be
`PRIMARY KEY` or `UNIQUE`; a read-side cardinality check diagnoses an already
malformed fixture, but portable SQL cannot replace the database constraint or
atomically protect an unconstrained schema from a concurrent duplicate insert.
The deliberate `pending -> X -> pending` cycle also broadens the accepted ABA
boundary recorded in DRR-2026-046. Use dedicated demo/test data, avoid
overlapping previews for one order, and prefer a fresh stdio server process per
live-test scenario.

The shared SQL gate now rejects:

- more than one non-empty SQL statement;
- all raw `SHOW` forms in the full MCP policy; callers use
  `list_tables()`/`describe_table()` for metadata discovery;
- `EXPLAIN`/`DESCRIBE`/`DESC ... ANALYZE` forms that can execute their child
  statement on supported MySQL versions;
- `EXPLAIN [FORMAT=...] FOR CONNECTION` and corresponding DESCRIBE forms that
  can inspect another server session;
- nested write-DML tokens inside SELECT-shaped statements;
- MySQL executable comments (`/*! ... */`), optimizer hints (`/*+ ... */`),
  and MariaDB executable comments (`/*M! ... */`); and
- `--` forms without the whitespace/control character MySQL requires for a
  comment, because generic comment stripping could otherwise hide executable
  text from file-operation and system-schema checks.

With a restrictive `ALLOWED_TABLES`, token-aware extraction covers FROM/JOIN,
comma joins, nested subqueries, CTE source tables, ordinary comment-separated
syntax, and the child query of EXPLAIN. Qualified `schema.table` remains
qualified: a basename entry does not authorize the same table in another
schema, and only an exact qualified allowlist entry permits it. System schemas
(`mysql`, `information_schema`, `performance_schema`, and `sys`) are checked as
parsed table targets without mistaking the same text inside a string literal
for a table. Ambiguous table-valued or derived targets fail closed;
`ALLOWED_TABLES=*` remains the explicit allow-all mode.

Non-ANALYZE EXPLAIN-family inspection of `INSERT`, `UPDATE`, `DELETE`, and
`REPLACE` remains supported, including common modifiers and CTE forms. Under a
restrictive allowlist, the policy checks both the explained DML target and every
read source, resolves CTE aliases to their underlying tables, includes
multi-table `DELETE ... USING` source tables, and fails closed when it cannot
identify the target reliably. ANALYZE and FOR CONNECTION forms remain rejected.

Ordinary comments, comment-like string data, and non-ANALYZE plan inspection
remain available. This is a conservative statement-shape/application-policy
gate for Oracle MySQL and SQLite behavior, not comprehensive SQL parsing or a
database authorization boundary. MariaDB is not a separately supported/tested
dialect; its executable comment marker is rejected conservatively because a
`DB_TYPE=mysql` connection may otherwise point at MariaDB.

Database grants remain authoritative. An outer SELECT can call a MySQL stored
function or `GET_LOCK()` whose effects are not apparent from statement type.
Production read aliases should have object-level `SELECT` only and no
unnecessary `EXECUTE`, `FILE`, `PROCESS`, administrative, or cross-schema
privileges; use separate read/write credentials where practical. Expanding a
function denylist is not a substitute for least privilege.

## 4. Compatibility and Non-Goals

- Existing `skill_def.md` files that use the documented fields remain valid
  without `connection_ids`. Previously ignored unknown/duplicate fields now
  fail discovery by design.
- Runtime tool arguments remain singular: each call targets one
  `connection_id`.
- No environment variable, database schema, token backend, token format, or
  dependency was added. The portable reset Skill uses the existing demo
  `orders` schema and requires its `id` uniqueness contract.
- The bundled Skills contain commented examples only; they are not silently
  bound to deployment-specific aliases.
- The new mutation is deliberately a demo-profile compensating operation for
  MySQL/SQLite fixtures; it does not claim to model a production order lifecycle
  or guarantee cleanup after an earlier committed call.
- The approval example does not add MCP Elicitation, server-side user identity,
  HTTP auth, a cancellation endpoint, or guaranteed approval audit.

## 5. Test Coverage

- strict `connection_ids` parsing, parser/runtime grammar parity, normalization,
  disclosure, portable aliases, and per-target DB-type conflict isolation;
- query target scope, omitted-default behavior, real-frontmatter execution, and
  pre-adapter rejection;
- mutation scope, server-policy intersection, explicit non-default execution,
  and non-consumption of a valid token after a pre-token scope rejection;
- approval, denial, workflow-enforced timeout/EOF/cancel, malformed/expired
  previews, resolved-target pinning, finite-JSON params, approval-view mutation
  rejection, complete stdio environment propagation, exact-token output
  redaction, and no execute retry;
- portable reset expected-state validation, preview binding, compensation,
  stale-state/cardinality rejection, and direct unbound execution rejection;
- single-statement enforcement, raw SHOW rejection, `sys` blocking, strict
  qualified names, comma/nested/CTE table extraction, EXPLAIN child tables,
  EXPLAIN/DESCRIBE/DESC `UPDATE`/`INSERT`/`REPLACE`/`DELETE` targets and CTE
  aliases, multi-table `DELETE ... USING` sources, and ambiguous
  restrictive-allowlist targets;
- MySQL executable/optimizer comments, MariaDB executable comments, and
  dash-comment mismatch cases while preserving ordinary comments and strings;
- the existing v3.5/v3.6.1 connection, mutation, token, audit, telemetry, and SQL
  safety regressions.

Final post-hardening validation completed with the default repository suite at
462 passed, 3 skipped; the focused SQL/query/SQLite suites passed 115 tests. Because
the default `pytest.ini` intentionally limits
collection to `tests/`, the retained root legacy smoke was also run explicitly:
`test_bug_fixes.py` passed 2 tests. `git diff --check`, risk-register parity,
and tracked Markdown relative-link checks passed. A real in-memory FastMCP
Client contract test executed against disposable SQLite.

The August 22 reset refactor retained the full `462 passed, 3 skipped` baseline;
the focused mutation/token/discovery selection passed 94 tests and the explicit
root regression smoke passed 2 tests. These automated results cover the
portable SQL shape on SQLite and the MySQL/SQLite metadata contract. As of
August 22, neither a real MySQL reset nor a reset-specific subprocess stdio live
run had been performed. The v3.7.1 follow-up later validated SQLite reset in
direct MCP and fresh-stdio flows; a real MySQL reset remains unclaimed.
The August 13 and August 19/20 subprocess stdio attempts stopped at initialize
and are recorded as historical blocked attempts, not passes, in
`LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`.

### v3.7.0 Live Validation (2026-08-21)

Using the repository `.venv`, the live environment was confirmed as Python
3.12.3, FastMCP 3.0.2, and MCP 1.26.0. A disposable SQLite database was
created with `orders(id=1, status=pending)` and a JSON parameter file requested
`pending -> confirmed`. The subprocess received only the temporary `env -i`
configuration, with `PYTHON_DOTENV_DISABLED=1`, the `stdio_test_sqlite`
connection, an `orders` allowlist, and the `update-order-status` mutation
allowlist.

- The explicit `APPROVE` flow completed MCP initialize, displayed an approval
  view without the bearer token, executed once on the preview-resolved
  `stdio_test_sqlite` connection, changed the row to `confirmed`, and wrote
  separate preview/execute audit records.
- A second run with non-`APPROVE` input returned `deny`, performed preview only,
  left the row `pending`, wrote no execute audit record, and did not retry.
- The full token was absent from stdout, stderr, the approval view, and audit;
  only the expiry field name was rendered in the preview output.
- The in-memory contract passed, the focused approval module passed 46 tests,
  and subprocess stdio passed for the minimal FastMCP echo server,
  `start_server.py`, and the complete `mcp_sql_server` entrypoint.
- A direct call through the currently connected `mcp_sql-safety-ex_*` tools also
  passed the current named SQLite Skill path: discovery, detail, the SQLite
  query Skill, mutation preview/execute, state verification, and replay
  rejection. The existing `sample_data/demo.db` fixture was restored unchanged.

This validation records **in-memory contract passed** and **subprocess stdio
passed**. The earlier initialize blocks remain historical environment
observations and are not rewritten as passes. The live record preserves the
environment, key calls, exit outcomes, final fixture state, audit counts, and
the historical failure distinction in
[`LIVE_MCP_TEST_V36-V37_ZH.md`](LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md).
Temporary stdout/stderr/audit files were intentionally not retained. The direct
MCP Skill smoke is documented there separately from subprocess stdio and the
approval-host workflow.

## 6. Best-Practice Basis

- MCP asks clients to show tool inputs for sensitive operations and provide a
  way for a human to deny invocations; the protocol does not make a preview
  token proof of human approval: [MCP Tools — user interaction model](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
- Anthropic describes manual tool-use loops for human-in-the-loop control:
  [Anthropic tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner).
- Microsoft places approval in the application execution flow rather than
  treating a server flag as human identity: [Microsoft Agent Framework tool approval](https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval).
- Google recommends clear schemas, enums, and valid constraints for function
  inputs: [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling).
- FastMCP documents stdio as a client-managed subprocess transport and supports
  in-memory clients for deterministic tests: [FastMCP client transports](https://gofastmcp.com/clients/transports).
- MySQL documents executable comments and the whitespace requirement for
  double-dash comments: [MySQL comments](https://dev.mysql.com/doc/refman/8.4/en/comments.html),
  [MySQL comment differences](https://dev.mysql.com/doc/refman/8.4/en/ansi-diff-comments.html).
- MySQL documents that stored functions may modify tables and named locks are
  session state, which is why the outer SELECT shape is not an authorization
  proof: [Stored program restrictions](https://dev.mysql.com/doc/refman/8.4/en/stored-program-restrictions.html),
  [Locking functions](https://dev.mysql.com/doc/refman/8.4/en/locking-functions.html).
- OWASP recommends deny-by-default authorization and validation on every
  request, as well as minimum database privileges and views/object grants:
  [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
  [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html).

These sources support the design direction; they do not prescribe this exact
frontmatter field or local CLI implementation. The per-target intersection and
same-process token handling are project-specific decisions reviewed against the
existing architecture.
