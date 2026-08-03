# Release Notes v3.6 — Mutation Preview Tokens and Named Write Policy

Date: 2026-05-30

## Summary

v3.6 adds mandatory preview-token binding and opt-in mutation routing across
configured named connections. Without the new target allowlist, mutation Skills
remain limited to the default connection for compatibility.

## Highlights

- `execute_mutation_skill(confirm=false)` returns an opaque `preview_token` plus
  `preview_token_expires_at` and `preview_token_expires_in_seconds`.
- `execute_mutation_skill(confirm=true)` now requires the matching
  `preview_token` returned by preview.
- Missing, expired, tampered, or mismatched tokens fail closed before the write
  path runs.
- The token binds skill name, skill version, canonical params hash, resolved
  `connection_id`, `db_type`, issue time, expiry, and a hash of minimal
  preview-time execution state.
- Tokens include a random `jti`, are registered in a bounded process-local
  store, and are atomically consumed before dynamic validation/write. Sequential
  and concurrent replay fail closed.
- Consumption remains terminal after validation, database, timeout, audit, or
  response failure. Static request/policy/HMAC rejection does not consume the
  matching valid token.
- The bundled order mutation now executes its optimistic lock against the status
  shown during preview rather than re-binding to a later status.
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

## Known Limits

- The token store is process-local and bounded. The current deployment boundary
  is stdio or a single HTTP/SSE worker; multi-worker or multi-replica execution
  requires a shared atomic store and has no stateless fallback.
- Restart invalidates outstanding tokens even when
  `MUTATION_PREVIEW_TOKEN_SECRET` is fixed, because the one-time store state is
  not persisted.
- Token consumption is terminal after dynamic validation, database, timeout,
  audit, or response failure. An uncertain write result requires a new preview;
  the old token is not automatically retried.
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

## Configuration

```env
MUTATION_PREVIEW_TOKEN_TTL_SECONDS=300
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES=10000
# MUTATION_PREVIEW_TOKEN_SECRET=change_me_and_keep_private

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

- Focused v3.6 mutation regression suite: 27 passed.
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
- `MCP_AGENTS_SKILLS_DESIGN.md`
- `skills/SAFETY.md`
- `.env.example` and local configuration guidance
- `RELEASE_NOTES/GUIDE/V3_5_V3_6_SKILLS_GUIDE_ZH.md`
- `RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36_ZH.md`