# v3.8.0 — FastMCP 4, explicit TOML, instance state and managed MRTR

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

See [the validation record](../validation/V3_8_VALIDATION_ZH.md) and [subsequent live review](../validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md). Earlier local runs recorded 744 passed / 4 skipped and a later focused 66 passed. The submitted `1be44b4` then failed CI on a stale description assertion; later steps were skipped. [September 27 review fixes](../validation/V3_8_REVIEW_FIXES_2026_09_27_ZH.md) record the corrective tests and complete local CI-equivalent checks separately from the pending remote rerun. Reference FastMCP modern MRTR and legacy preview/execute are automated.

After fixing the saved Codex launch entry and reconnecting, the current IDE Host completed 23 native calls, including a controlled SQLite preview/execute/compensation cycle with the fixture restored. Three isolated GPT-6 Luna agents completed 18 routing rounds with 22 native calls and no observed wrong-target access. Real MySQL connectivity/basic reads passed; the four optional MySQL integration tests remain skipped, and MySQL writes/failure recovery remain unverified.

The earlier native MRTR dispatch was blocked by Host policy; subsequent local tests kept MRTR disabled. Neither native MRTR nor a human approval UI is claimed as passed. Copilot interactive behavior remains unverified, and a successful remote CI rerun remains pending. Native subagent token usage and negotiated protocol were not exposed; reference Client versions are not substituted for them. Historical failures, including one rejected-and-corrected UNION in the earlier CLI trials, remain in the evidence.

## Independent review corrections (September 27)

Profile exclusions now trim, lowercase and deduplicate strictly typed strings;
blank entries fail startup. Tableless Query Skill availability follows read
admission. Configuration errors preserve safe semantic codes. MRTR waiting and
repeat requests retain their validated target in telemetry; absent identity
remains null and decline/cancel phases are preserved. Both reference Host flows
share approval deadlines, review fingerprints and expiry rechecks. The server's
token consumption and trusted-Host boundary remain unchanged. See the linked
review record for regressions and deferred task-scope/catalog/tracing work.

Historical releases and failed trials retain their original versions and conclusions under `docs/`.
