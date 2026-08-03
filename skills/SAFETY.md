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
by the matching preview call. The token is HMAC-signed and bound to the skill
name, skill version, canonical params hash, resolved `connection_id`, DB type,
issue time, expiry, and a hash of minimal preview-time execution state. Missing,
expired, tampered, or mismatched tokens fail closed before the write path runs.

Preview tokens are registered in a bounded process-local store and atomically
consumed before dynamic business validation and database writes. Consumption is
terminal after every later outcome, including validation, database, timeout,
audit, or response failure. Static request/policy/HMAC rejection happens before
consumption. Process restart invalidates every outstanding token even when the
HMAC key is fixed. Multi-worker deployments require a future shared atomic
backend; they must not fall back to stateless token acceptance.

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

This prevents duplicate effects when agents retry operations.

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

## 9. Server-Side Preview Token (v3.6)

Server-side preview-token protection is implemented in v3.6. The
`destructiveHint` annotation remains only a client-facing hint and does not
replace server-side authorization or token validation.

Every `confirm=true` mutation execution must include the `preview_token`
returned by the matching `confirm=false` preview. The token is HMAC-signed and
binds the Skill name, Skill version, canonical parameter hash, resolved
`connection_id`, database type, issue/expiry timestamps, and a hash of the
minimal preview-time execution binding. Missing, expired, tampered, or
mismatched tokens fail closed before the write path.

The token is registered in a bounded process-local store and atomically
consumed before dynamic validation and database writes. A consumed token cannot
be retried, including after a later validation, database, timeout, audit, or
response failure; the caller must preview again. Static request, policy, or
HMAC rejection does not consume a matching valid token.

This mechanism proves that the execute request matches a server-issued preview
and prevents replay. It does not prove that a human personally clicked an
approval button: `confirm=true` may be produced by an Agent or client. A
separate human approval workflow is required when that policy is mandatory.

The store is process-local. Restart invalidates outstanding tokens, and
multi-worker or multi-replica deployments require a future shared atomic
backend; the server must not silently fall back to stateless HMAC acceptance.

## 10. Audit Log

Mutation preview/execute paths attempt best-effort JSONL audit logging via `audit.py`:
- **who**: `ctx.client_id` or `AGENT_ID` env var (fallback: "unknown")
- **what**: skill_name, params, mode (preview/execute), plus safe `connection_id` and actual `db_type` when available
- **when**: ISO 8601 timestamp
- **result**: success/failure and details

Log path: `SKILLS_AUDIT_LOG` env var (default: `skills/_audit.jsonl`).

Audit write failures are logged by the server but do not block the mutation
operation or roll back already completed data changes. Validation failures and
audit write failures can return normal tool metadata with `audit_logged=false`.
Treat the audit file as a visibility aid, not as a fail-closed transaction
control.

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

Concrete `Mutation.execute()` implementations should perform writes only
through `self.adapter.execute_write()`; `MutationBase.execute()` itself is the
abstract method contract, not the concrete implementation. Direct file I/O,
network requests, or subprocess calls are prohibited. Code reviewers must
verify that `mutation.py` uses only the base class API
(`self.adapter.execute()`, `self.adapter.execute_write()`).

## 12. Error Sanitization

`MutationBase.run_execute()` catches exceptions and sanitizes them via
`adapter._handle_error()` before raising `ToolError`. This prevents
leaking connection strings, table schemas, or internal details to the
LLM agent.

## 13. Rate Limiting

The server does not currently implement explicit per-skill, per-client, or
global rate limiting. The stdio/SSE transport choice is not a server-side
rate-limit or authorization boundary by itself. If the service is exposed via
HTTP or to untrusted callers, enforce appropriate limits at ingress and/or add
per-skill or global rate limiting (per MCP Spec §7).

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

## 17. Connection Scope (v3.5-v3.6)

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

`SkillMetadata.databases` is a DB type compatibility field, not a connection id
allowlist. Query skills must be listed, detailed, and executed against the same
target connection so the Agent's visible availability matches executability.

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
