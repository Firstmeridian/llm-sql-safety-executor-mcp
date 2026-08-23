# Release Notes v3.7 — Scoped Skills, Approval Host, and SQL Hardening

- Version: v3.7.0
- Release date: 2026-08-22
- Last implementation review: 2026-08-22
- Last live validation update: 2026-08-21
- Status: implemented

v3.7.0 adds an optional, deployment-aware connection scope to `skill_def.md`,
a portable demo/test reset mutation, a dependency-light stdio example for explicit
host-side mutation approval, and supported-dialect SQL policy hardening.
It is an incremental release: existing Skills that use the documented
frontmatter schema and omit the new field retain their v3.6.1 routing behavior,
and the mutation preview-token format, TTL,
capacity, execution binding, and existing write-authorization protocol do not
change. Raw SQL grammar and malformed Skill metadata are intentionally tightened
as described below.

## 1. Optional `connection_ids` Skill Scope

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
portable SQL shape on SQLite and the MySQL/SQLite metadata contract. A real
MySQL reset and a reset-specific subprocess stdio live run have not yet been
performed and are not claimed here.
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
