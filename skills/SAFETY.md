# Skills Extension — Security Governance

This document defines the security policies and constraints for the
Skills extension layer. All skill authors and code reviewers should
read this before creating or approving skills.

## 1. Template/Script as Whitelist

Only execution files explicitly declared via the `source` field in
`skill_def.md` are loaded and executed. There is no free-form SQL input
path — the skill template IS the whitelist. The `source` filename is
validated by `_validate_source_filename()` for path traversal prevention,
hidden file rejection, safe character set, and suffix enforcement
(query → `.sql`, mutation → `.py`).

## 2. Parameterized Queries

All parameters are bound via SQLAlchemy `text()` + parameter dict
(`connection.execute(text(sql), params)`). Direct string interpolation
is **never** used. This prevents SQL injection by design.

## 3. Dry-Run Default

`confirm=False` is the default for mutation skills. Agents must preview
the operation before confirming execution with `confirm=True`.

Every `confirm=True` mutation execute must include the `preview_token` returned
by the matching preview call. It is a random 256-bit opaque bearer handle. Its
server-side Store record is bound to the skill name, skill version, canonical
params hash, resolved `connection_id`, DB type, expiry, and minimal preview-time
execution state. Missing, expired, unknown, consumed, or mismatched handles fail
closed before the write path runs.

Preview handles are registered in a bounded atomic store and conditionally
consumed only when their request binding matches. Consumption happens before
dynamic business validation and database writes and is terminal after every
later outcome, including validation, database, timeout, audit, or response
failure. Static request/policy rejection and request-binding mismatch happen
without consuming the valid record. The
memory store is process-local and loses outstanding tokens on restart. The
recommended mutation deployment is the client-owned stdio MCP process. If an
integrator exposes mutations through an HTTP transport, the current design supports only a
trusted single-operator/private boundary with exactly one mutation-enabled
process. It does not define a multi-user authenticated HTTP mutation service.
The application does not detect worker or replica counts; deployment
configuration must enforce this boundary. Do not place mutation-enabled memory
workers behind a normal load balancer. Requests that reach another process fail
closed, and the server never falls back to stateless token acceptance. Read-only
capacity may scale only through a separate read-only endpoint, profile, or pool.

State-sensitive mutation Skills should override `build_execution_binding()` and
`execute_with_binding()` so execution uses the state shown during preview. A
non-empty binding is rejected by default rather than silently ignored.

## 4. Dual-Layer Switches

- `ENABLE_SKILLS` — Master switch. When `0` (default), no skills tools
  are registered and the entire extension is invisible.
- `SKILLS_ALLOW_MUTATIONS` — Second switch. When `0` (default), only
  read-only query skills are available; `execute_mutation_skill` is not
  registered as an MCP tool.

## 5. Timeout Protection

Skills inherit `QUERY_TIMEOUT_SECONDS` from the resolved `DatabaseConfig` in
`db_adapter.py`. Query skills use the selected connection's read timeout. MySQL mutation skills set session
`innodb_lock_wait_timeout` through `execute_write()` so InnoDB row-lock
waits use the same seconds value. This does not make MySQL
`MAX_EXECUTION_TIME` a write timeout, and it does not guarantee that all
long-running DML CPU/IO work stops at that boundary; keep driver and
deployment-side statement controls in scope for production. The MCP
server also applies `MCP_TOOL_TIMEOUT_SECONDS` to foreground tool
execution so non-database stalls do not leave client requests running
indefinitely.

## 6. Idempotency

Mutation authors should prefer idempotent write patterns:
- `INSERT OR IGNORE` / `ON DUPLICATE KEY UPDATE`
- Optimistic locking (`WHERE status = :expected`)
- Conditional updates (`WHERE updated_at = :expected_ts`)

These patterns reduce duplicate effects when a workflow has independently
established that retry is safe. They do not authorize an Agent to retry after a
timeout, disconnect, or other ambiguous mutation result.

## 7. Script Trust Boundary

Files under `skills/` are in the **same trust boundary** as source code.
Changes must go through code review. `skill_loader.py` only loads from
a fixed directory path — `..` traversal and dynamic registration are
rejected. In production, consider making the skills directory read-only.

## 8. Least-Privilege Deployment

Production recommendations:
- Use a dedicated database account with INSERT/UPDATE permissions only
  on tables that skills actually need
- For SQLite: use a separate database file for writes if possible
- Grant only the minimum permissions required by each skill's SQL

## 9. Server-Side Preview Token

Server-side preview-token protection, including the bounded process-local
memory store, was introduced in v3.6. Since v3.7.1, the implementation uses a
random 256-bit opaque handle and keeps authorization state only in that Store. The
`destructiveHint` annotation remains only a client-facing hint and does not
replace server-side authorization or token validation.

Every `confirm=true` mutation execution must include the `preview_token`
returned by the matching `confirm=false` preview. The Store record binds the
Skill name, Skill version, canonical parameter hash, resolved `connection_id`,
database type, expiry, and minimal preview-time execution binding. Missing,
expired, unknown, consumed, or mismatched handles fail closed before the write
path. An exact request-binding mismatch does not consume the valid record.

The handle is API-opaque and contains no client-readable authorization state:
clients must not parse it or depend on its format. It necessarily passes through the authorized client and
may enter model context. Until it is consumed or expires, bearer confidentiality
still matters: clients should minimize durable retention and logging, protect
access to context and logs, and never expose the token to an unauthorized party.
Short TTL, exact request/state binding, and atomic one-time consumption limit the
impact of disclosure; they do not make disclosure harmless.

The handle is registered in a bounded atomic store and consumed before dynamic
validation and database writes. A consumed handle cannot be reused, including
after a later validation, database, timeout, audit, or response failure. When
the write outcome is uncertain, the caller must inspect current business state
before deciding whether a new preview/mutation is appropriate; it must not
blindly retry. Static request or policy rejection and a request-
binding mismatch do not consume the matching valid record. A preview result
containing `error` or reporting `success=false` fails and does not receive a
handle.

The database transaction cannot make Store consumption, database commit, audit,
and MCP response delivery one atomic event. Fully queryable retry semantics
would require a durable operation/idempotency record committed with the business
write plus an authenticated status lookup after reconnect; v3.7.1 does not add
that product-level protocol.

This mechanism proves that the execute request matches a server-issued preview
and prevents replay. It does not prove that a human personally clicked an
approval button: `confirm=true` may be produced by an Agent or client. A
separate human approval workflow is required when that policy is mandatory.

The memory store is process-local, so restart invalidates outstanding handles.
The supported baseline is stdio in one client-owned process. Conditional HTTP
mutation use is limited to a trusted private boundary and one mutation-enabled
process; multi-user authenticated HTTP mutation is outside the current design.
Preview and execute must reach that same process. The application does not
enforce worker or replica counts.
Requests reaching the wrong process fail closed and require a new preview.
Read-only capacity may scale only through a separate read-only endpoint,
profile, or pool. The server never falls back to stateless token acceptance.

### v3.7 host-side approval example

`examples/manual_mutation_approval.py` demonstrates a one-shot stdio host that
keeps preview and execute in one Client context and the same server subprocess,
explicitly passes the operator's complete process environment to that subprocess,
and displays the exact Skill, finite-JSON parameter snapshot, resolved connection
alias, DB type, business preview,
expiry, and idempotency flag, and executes only after the literal response
`APPROVE`. The bearer token is kept out of the approval view and the example's
terminal output. Execute exceptions and timeouts are never retried because the
token may already be consumed and the write result may be unknown.

The workflow, rather than only the UI provider, enforces the approval deadline
and rejects a late approval. It also fingerprints the displayed view and fails
closed if a custom provider changes params or preview data before returning its
decision. Custom providers must still cooperate with async
cancellation; an actively hostile provider requires process isolation for a
hard termination guarantee. The complete inherited environment is intentional
for this trusted local host so exported `DB_*` and Skill policy cannot be
silently replaced by a different project `.env`. The example fixes the child
path to this repository's trusted `start_server.py` and does not expose a CLI
override. This also forwards every exported secret and Python control variable
into the child/Skill trust boundary. A productized host should use a maintained
project-specific environment allowlist.

This is a reference host workflow, not a server-side identity or authorization
mechanism. A caller that bypasses the host can still call the MCP tool directly,
and the server cannot prove that a particular human reviewed the preview. Deny,
timeout, EOF, or cancellation does not revoke the server record: the unused
record occupies one bounded entry until token expiry/lazy cleanup, and only the
preview audit exists. The raw token necessarily passes through FastMCP/client
memory; Python cannot guarantee secure erasure, and payload-level protocol/debug
logging can still expose it. Do not enable such logging around real mutations.
The approval screen intentionally renders exact params and business preview,
and the CLI prints the execute result. All may be sensitive; use a trusted
terminal and protect parameter files, screen sharing, terminal capture, and
session retention.
Use a product-owned authenticated approval service and audit trail when approver
identity, role separation, durable denial records, or compliance evidence is
required. Multi-user HTTP approval remains outside this release.

## 10. Audit Log

Mutation preview/execute paths attempt best-effort JSONL audit logging via `audit.py`:
- **who**: `ctx.client_id` or `AGENT_ID` env var (fallback: "unknown")
- **what**: skill_name, params, mode (preview/execute), plus safe `connection_id` and actual `db_type` when available
- **when**: ISO 8601 timestamp
- **result**: success/failure and details

Log path: `SKILLS_AUDIT_LOG` env var (default: `skills/_audit.jsonl`).

Audit write failures are logged by the server but do not block the mutation
operation or roll back already completed data changes. Pre-token
parameter/validation rejection and audit write failures can return normal tool
metadata with `audit_logged=false`. Once execute atomically consumes a valid
token, a later dynamic validation rejection attempts a best-effort execute
audit. Treat the audit file as a visibility aid, not as a fail-closed
transaction control.

`MutationBase.run_execute()` owns the audit outcome for the database execution.
If the write commits and later context notification or response construction
fails, the server preserves the success audit rather than appending a
contradictory execute failure. The client receives an indeterminate-response
error and must verify current database state before attempting another mutation;
the consumed token is never restored.

The full `preview_token` is never written to audit or tool telemetry. A short
`preview_token_id` correlation hint is returned in applicable `ToolResult`
metadata for the client, but the current design does not persist that short
identifier in the audit or telemetry JSONL files.

Read-only query skills can be audited with `SKILLS_AUDIT_QUERIES=1`.
This records skill name, truncated params, row counts, success/failure,
errors, safe `connection_id`, and actual `db_type`. It does not log returned
result rows, DSNs, hosts, usernames, passwords, SQLite file paths, or SQL
templates.

For SQLite targets, public tool payloads use `sqlite:<connection_id>` as the
database display value instead of exposing the configured file path.

Audit params are truncated for log size, not key/value redacted. Do not
pass secrets, tokens, credentials, or sensitive personal data as skill
parameters. Treat the audit log as sensitive business data: restrict file
permissions and use external rotation/retention (for example `logrotate`,
platform logging, cron cleanup, or a managed log sink) in production.

## 11. mutation.py Execution Constraints

Discovery imports `mutation.py` as trusted local project code and requires it
to export a concrete `Mutation` class that subclasses `MutationBase`. This is
a structural loader invariant, not a sandbox for untrusted plugins.

Concrete write implementations should perform writes only through
`self.adapter.execute_write()`. `MutationBase.execute()` remains abstract so a
Skill that implements neither execution contract fails during discovery. A
state-sensitive Skill may satisfy that interface with an `execute()` method
that fails closed and place its only write path in `execute_with_binding()`.
Revisit the base-class shape only when multiple binding-only Skills justify a
loader invariant requiring an override of at least one execution method.
Direct file I/O, network requests, or subprocess calls are prohibited. Code
reviewers must verify that `mutation.py` uses only the base class API
(`self.adapter.execute()`, `self.adapter.execute_write()`).

## 12. Error Sanitization

`MutationBase.run_execute()` catches exceptions and sanitizes them via
`adapter._handle_error()` before raising `ToolError`. This prevents
leaking connection strings, table schemas, or internal details to the
LLM agent.

## 13. Rate Limiting

The server does not currently implement explicit per-skill, per-client, or
global rate limiting. A transport choice is not a rate-limit or authorization
boundary by itself. v3.6.1-v3.7 do not support mutation HTTP exposure to untrusted
or multi-user callers. For future remote designs, enforce limits at ingress
and/or add per-principal, per-skill, and global quotas.

## 14. ALLOWED_TABLES Interaction

Query skill SQL templates are startup-validated as read-only templates and then
checked at runtime against the resolved target connection's `ALLOWED_TABLES`
policy. This v3.5 runtime check is necessary because allowlists are
connection-scoped. The runtime table extractor normalizes common quoted forms
(backticks, double quotes, square brackets, and schema-qualified references)
before comparing against the allowlist. Security still comes from code review
(template = whitelist, same trust boundary as source code), parameter
validation, and execution-time policy checks. `generate_skills_md()`
automatically extracts and lists table names used by each skill in `SKILLS.md`
for reviewer audit.

The SQL checker and table allowlist are application-layer guards, not the
database authorization boundary and not proof that every SELECT-shaped form
has no side effect. MySQL stored functions and functions such as `GET_LOCK()`
can have effects that are not visible from the outer statement type. Production
read connections should receive object-level `SELECT` only and should not have
unneeded `EXECUTE`, `FILE`, `PROCESS`, administrative, or cross-schema
privileges. Use separate read/write credentials where practical. Do not replace
database least privilege with an ever-growing SQL function denylist.

Mutation skill write policy is independent from query table policy. Without
`SKILLS_ALLOW_MUTATION_CONNECTIONS`, mutation skills remain default-connection
only for compatibility. Setting that variable enables strict named-write mode:
the target must be listed, `DB_<ID>_ALLOW_MUTATIONS=1`, and the skill must appear
in `DB_<ID>_MUTATION_SKILLS` (or the explicit `*` wildcard). Omitted per-target
values deny writes.

## 15. SKILLS_DIR Path Constraint

`SKILLS_DIR` is configurable via environment variable, but `discover()`
validates that the resolved absolute path is within the project root
(using path-aware `Path.resolve().relative_to()`, not string prefix matching).
This prevents `.env` file poisoning that could inject malicious `mutation.py`
from external paths.

## 16. Read/Write Method Convention

The separation between `execute()` (read) and `execute_write()` (write)
is **conventional**, not enforced at runtime. Security comes from:
- Calling convention: `execute_query_skill` → `execute()`,
  `execute_mutation_skill` → `execute_write()`
- Code review of skill implementations
- SQLAlchemy 2.0 implicit transactions: `execute()` path has no
  `commit()`, so accidental write SQL won't persist (auto-rollback)

## 17. Connection Scope (v3.5-v3.7)

Core read-only tools and query skills may accept optional `connection_id`, but
the server only accepts ids configured via `DB_CONNECTIONS` (or the legacy
default connection when `DB_CONNECTIONS` is unset). Tools and models cannot
provide arbitrary DSNs. The server resolves the target connection before SQL
policy, schema readiness, execution, result metadata, audit, and telemetry.
Unknown connection ids fail closed and do not fall back to the default.

When `DB_CONNECTIONS` is unset or empty, legacy mode ignores both `DB_<ID>_*`
variables and `DEFAULT_DB_CONNECTION`. This prevents local named-connection
settings from silently changing legacy `DB_TYPE` / `SQLITE_DATABASE_PATH`
behavior.

`SkillMetadata.databases` is a DB type compatibility field. Starting in v3.7,
optional `connection_ids` is a separate restrictive list of valid connection
alias identifiers; only members configured in the current deployment can run:

```yaml
databases: [mysql]
connection_ids: [orders_primary, orders_reporting]
```

Omitting `connection_ids` preserves v3.6.1 behavior. When present it must be a
non-empty YAML list of unique valid aliases; a scalar `connection_id`, wildcard,
DSN, URL, or path is rejected during discovery. Unknown top-level frontmatter
fields and duplicate YAML mapping keys are also rejected, so a typo cannot
silently remove a restriction. Multiple entries intentionally
support Skill reuse. Their order has no routing meaning: an omitted runtime
`connection_id` still resolves the global default and is then checked against
the list; the server never auto-selects the only/first member.

Known metadata values are strict as well: declared boolean fields must be YAML
booleans, catalog lists must be lists of strings, and category must be a
non-empty string. Parameter definitions accept only the documented
`type`/`required`/`min`/`max`/`enum`/`description` vocabulary; constraint values
must match the declared type, enum is a non-empty list, and numeric bounds must
be ordered. This is a deliberately small custom schema, not JSON Schema.

The effective target is the intersection of `connection_ids`, `databases`, and
all existing profile, schema, table, query, and mutation policies. Skill
metadata can only remove targets and never creates a connection or grants
permission. An alias declared by a portable Skill but absent in the current
deployment is reported as unavailable. A configured alias whose actual DB type
conflicts with `databases` fails closed for that target and produces a startup
diagnostic; other valid list members remain usable rather than disabling the
entire reusable Skill. Discovery filtering is only guidance. Query and mutation
execution repeat `connection_ids` and `databases` checks before adapter
construction; profile, schema, table, query, and mutation policy remains
independently enforced before query execution or writes. Query skills must still be listed, detailed, and executed against the
same target connection so visible availability matches executability.

Prefer semantic aliases such as `trade_analysis_mysql`,
`analytics_demo_sqlite`, and `orders_primary`.
`mysql`/`sqlite` are syntactically valid aliases but are easily confused with
the `databases` DB-type values. Direct Python consumers of `skill_loader` or a
Mutation class bypass the MCP routing layer and must enforce an equivalent
connection policy themselves.

The bundled `reset-demo-order-to-pending` demo supports MySQL and SQLite. It
requires an explicit non-pending `expected_status` while reviewed code fixes the
target to `pending`; its commented `connection_ids` example is inactive until
an operator enables it. Database type and alias metadata remain restrictions,
not permissions. This is a test compensation call, not a production order
reopen or an atomic rollback of an earlier call.

The demo requires `orders.id` to be `PRIMARY KEY`/`UNIQUE`. Its portable
read-side cardinality check diagnoses an already malformed fixture but cannot
replace the database constraint or close a concurrent duplicate-insert race.
The deliberate `pending -> X -> pending` cycle can make an older status-only
preview appear current again. Use dedicated demo/test data, avoid overlapping
previews for one order, and prefer a fresh stdio process per live-test scenario.

Mutation tools accept only configured `connection_id` aliases. If
`SKILLS_ALLOW_MUTATION_CONNECTIONS` is empty, only the default connection is a
mutation target. If it is set, discovery and execution enforce the same strict
three-layer write policy: global mutation switch, target connection allowlist,
and per-connection switch plus skill allowlist. Preview tokens additionally bind
the preview and execute calls to the same target, params, skill version, and DB
type. Query `ALLOWED_TABLES` is not reused as mutation authorization.

## 18. Profile Exclusion Policy

Profiles are descriptive metadata by default. Deployments can set
`SKILLS_EXCLUDE_PROFILES=demo` (or another comma-separated profile list)
to mark matching skills non-executable, hide them from default discovery,
and reject direct execution attempts. This is useful for keeping bundled
examples in the repository while preventing accidental use against a
production schema.
