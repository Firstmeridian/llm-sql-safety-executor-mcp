# Release Notes v3.6 — Mutation Preview Tokens and Named Write Policy

- Release family: v3.6
- Initial release: v3.6 (2026-05-30)
- Current maintenance update: v3.6.1 (2026-08-10)

This file contains the v3.6 baseline and subsequent v3.6.x maintenance updates.

## v3.6 Release Family Summary

The v3.6 baseline adds mandatory preview-token binding and opt-in mutation
routing across configured named connections. Without the new target allowlist,
mutation Skills remain limited to the default connection for compatibility.
Its token core already includes random `jti`, a bounded process-local memory
store, atomic one-time consumption, and preview-state execution binding.

## v3.6.1 Maintenance Update

v3.6.1 retains the bounded process-local memory store introduced in v3.6 and
hardens its one-time mutation preview protocol. The recommended deployment is
stdio, where preview and execute stay in the same client-launched process.
Conditional HTTP mutation use is limited to a trusted private boundary with one
mutation-enabled process; multi-user authenticated HTTP mutation is not part of
this release. Restart invalidates outstanding tokens and requires a new preview,
even when the signing secret is fixed.

The maintenance update closes DRR-2026-037/038/041/045: failed previews receive
no token, bindings use the state actually displayed by preview, direct unbound
order mutation execution fails closed, weak regression cases are corrected,
and the deployment boundary is deliberately limited to one mutation worker.

A shared external token backend is intentionally deferred because cross-host
mutation replicas are not a common or fully designed project baseline. v3.6.1
adds no external token service or persistence layer. Future multi-replica
mutation support requires a separate end-to-end remote deployment design rather
than a token-store-only extension.

## Highlights

- `execute_mutation_skill(confirm=false)` returns an API-opaque, signed but
  unencrypted bearer `preview_token` plus `preview_token_expires_at` and
  `preview_token_expires_in_seconds`.
- `execute_mutation_skill(confirm=true)` now requires the matching
  `preview_token` returned by preview.
- Missing, expired, tampered, or mismatched tokens fail closed before the write
  path runs.
- The token binds skill name, skill version, canonical params hash, resolved
  `connection_id`, `db_type`, issue time, expiry, and a hash of minimal
  preview-time execution state.
- Tokens include a random `jti`, are registered in a bounded process-local
  atomic store, and are consumed before dynamic validation/write. Sequential
  and concurrent replay in the issuing process fail closed.
- Consumption remains terminal after validation, database, timeout, audit, or
  response failure. Static request/policy/HMAC rejection does not consume the
  matching valid token.
- The bundled order mutation now executes its optimistic lock against the status
  shown during preview rather than re-binding to a later status.
- Preview results containing `error` or reporting `success=false` fail closed
  without issuing a token, including empty or null error values.
- `execute_mutation_skill` accepts optional `connection_id` for targets that
  pass strict server-side mutation policy.
- Discovery and execution use the same policy checks, so unauthorized mutation
  Skills are marked non-executable and direct calls fail closed.

## Security And Compatibility Fixes

- Mutation execute is now a consistent two-call protocol for both the default
  and named connections: preview with `confirm=false`, then execute with the
  matching `preview_token` and `confirm=true`.
- Omitting `SKILLS_ALLOW_MUTATION_CONNECTIONS` preserves the v3.5-compatible
  default-connection-only mutation scope. Setting it enables strict named-write
  mode; it does not by itself grant write permission.
- Every named mutation target must be present in `DB_CONNECTIONS`, enabled by
  `DB_<ID>_ALLOW_MUTATIONS=1`, and authorized by `DB_<ID>_MUTATION_SKILLS`.
- Read table allowlists and mutation authorization remain separate. A table in
  `DB_<ID>_ALLOWED_TABLES` does not grant permission to mutate it.
- `connection_id` remains a server-configured alias. Tools and models cannot
  provide arbitrary DSNs, database URLs, hosts, credentials, or file paths.
- `destructiveHint` and `requires_confirmation` are advisory/client-facing
  signals; they do not replace server-side policy or preview-token checks.
- Default pytest now disables `.env` loading and installs a safe SQLite/config
  baseline before application imports. Live MySQL integration requires the
  explicit `RUN_MYSQL_INTEGRATION_TESTS=1` gate plus exported credentials;
  `python-dotenv>=1.2.0` guarantees support for the disable switch.
- Post-consume dynamic validation rejection now attempts a best-effort execute
  audit while preserving terminal token consumption. Preview validation
  failures return explicit false token-state metadata.
- A context or response-construction failure after a committed write no longer
  appends a contradictory execute-failure audit. The success audit remains, and
  the client is told to verify database state before another mutation.
- Outstanding-token capacity is constrained to `1-100000`; invalid values fall
  back to `10000`. Startup diagnostics report process-local/generated versus
  configured signing mode and mutation routing policy without logging secrets,
  DSNs, or credentials.
- The unreachable `DB_<ID>_DATABASE_PATH` fallback was removed;
  `DB_<ID>_SQLITE_DATABASE_PATH` remains the sole named SQLite path setting.
- The full bearer token is not written to audit or telemetry. A short
  `preview_token_id` remains client-facing metadata only and is not persisted in
  either JSONL stream.

## Known Limits

- The memory store is process-local and bounded. Use client-owned stdio by
  default. Conditional HTTP mutation is limited to one process in a trusted
  private boundary; multi-user authenticated HTTP mutation is outside v3.6.1.
  The application does not detect worker/replica counts. Restart invalidates
  outstanding tokens even when `MUTATION_PREVIEW_TOKEN_SECRET` is fixed.
- Cross-worker and cross-replica mutation execution are unsupported. Do not put
  multiple mutation-enabled workers behind ordinary load balancing. There is no
  stateless or shared-store fallback.
- Token consumption is terminal after dynamic validation, database, timeout,
  audit, or response failure. An uncertain write result requires a new preview;
  the old token is not automatically retried.
- The token is API-opaque but not encrypted. It must remain confidential until
  consumption or expiry. Clients should not parse its internal format and
  should minimize durable context/log retention.
- Preview-state binding is opt-in at the Skill implementation level. A
  state-sensitive Skill must implement `build_execution_binding()` and
  `execute_with_binding()`; the base class rejects a non-empty binding that
  would otherwise be ignored.
- The token does not prove that a human personally approved the operation.
  Deployments requiring human approval need a separate client or external
  approval workflow.
- Per-connection result-size limits are not implemented. Result, SQL-length,
  and schema/table overview caps remain process-wide.
- Configuration is loaded at startup; runtime config reload and credential
  refresh are not implemented.
- The bundled order mutation compares the previewed `status`, not a generic row
  revision. Its state machine is acyclic, but an external writer that changes a
  status away and back within the token lifetime creates an undetected ABA
  history. Bind a real row version when a production schema provides one.
- Lazy expiry scans the bounded in-memory dictionary. This is accepted for the
  current single-process workload; no heap or background cleanup service is
  included without a measured high-throughput requirement.

## Configuration

```env
MUTATION_PREVIEW_TOKEN_TTL_SECONDS=300 # valid range: 1-86400 seconds
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES=10000 # valid range: 1-100000
# MUTATION_PREVIEW_TOKEN_SECRET=replace_with_at_least_32_random_bytes

SKILLS_ALLOW_MUTATION_CONNECTIONS=mysql,analytics
DB_MYSQL_ALLOW_MUTATIONS=1
DB_MYSQL_MUTATION_SKILLS=update-order-status
DB_ANALYTICS_ALLOW_MUTATIONS=1
DB_ANALYTICS_MUTATION_SKILLS=update-order-status
```

Named connection registration remains the v3.5 configuration boundary:

```env
DB_CONNECTIONS=mysql,analytics
DEFAULT_DB_CONNECTION=mysql

DB_MYSQL_TYPE=mysql
DB_MYSQL_ALLOWED_TABLES=products,orders,customers
DB_MYSQL_ALLOW_UNION=0

DB_ANALYTICS_TYPE=sqlite
DB_ANALYTICS_SQLITE_DATABASE_PATH=./sample_data/demo.db
DB_ANALYTICS_ALLOWED_TABLES=orders
```

For MySQL credentials and other connection fields, see the v3.5 configuration
example. The default connection may also use the legacy fallback variables;
non-default connections should be configured explicitly.

Per-connection values take precedence. The default connection may use legacy
fallback variables for compatibility. If `DB_CONNECTIONS` is unset or empty,
named variables and `DEFAULT_DB_CONNECTION` are ignored and legacy
single-connection behavior remains active.

## Migration Note

Clients that previously called `execute_mutation_skill(confirm=true)` directly
must first call `execute_mutation_skill(confirm=false)` and pass the returned
`preview_token` into the execute call.

## Validation

- The focused mutation/store regression suite passes: 67 passed.
- The complete repository suite passes: 289 passed, 3 skipped.
- Syntax checks and `git diff --check` pass; runtime Python, environment
  examples, and base requirements contain no external token-store dependency
  or active configuration.
- `tests/test_mutation_multi_connection_v36_design.py` covers default and
  non-default token generation/execution, target and params binding, same-target
  writes, unknown connection ordering, all three policy rejection layers, exact
  expiry, tampering, skill-version changes, explicit/generated secret reload
  behavior, one-time replay, concurrent consumption, capacity/expiry cleanup,
  preview-state drift, terminal failure semantics, and full-token exclusion from
  metadata and audit logs.
- `tests/test_db_adapter.py` covers per-connection policy parsing and legacy-mode
  isolation.

## Documentation Updated

- `README.md` and `README_ZH.md`
- `REFACTORING_LOG.md`
- `DESIGN_RISK_REGISTER.md` and `DESIGN_RISK_REGISTER_ZH.md`
- `MCP_AGENTS_SKILLS_DESIGN.md`
- `TEST_MCP_CLIENT_GUIDE.md`
- `skills/SAFETY.md`
- `skills/update-order-status/skill_def.md`
- `.env.example`, `.env.example_ZH`, and local configuration guidance
- `RELEASE_NOTES/GUIDE/V3_5-V3_7_SKILLS_GUIDE_ZH.md` (renamed and extended in v3.7)
- `RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md`
