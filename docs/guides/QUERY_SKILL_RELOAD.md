# Controlled Query Skill reload

[中文](QUERY_SKILL_RELOAD_ZH.md)

After deploying Query Skill files, explicitly call `reload_skills()` to publish a
validated catalog snapshot without restarting for supported definition updates.
Ordinary business calls continue to use the published definitions.

## Scope and prerequisites

- Enable `skills.enabled=true` and deploy files to the configured Skill directory.
  The default is `skill_type="query"`; the tool accepts no path, SQL or grant arguments.
- Initial installation of the reload implementation requires restarting/recreating
  the service process, then refreshing the Host tool catalog and checking the
  actual consumer. Configuration refresh alone may reuse a healthy old process;
  an installed reload implementation does not require restart for each definition update.
- Publication affects only the receiving server instance. Hosts/subprocesses can
  load the same directory into independent catalogs, without broadcast or snapshot
  synchronization. A parent session's success does not prove child visibility;
  publish and confirm separately in each relevant instance.

## Usage

1. Deploy `skill_def.md` and the `.sql` file named by its `source` field.
2. In the instance that needs the new definitions, call:

   ```text
   reload_skills()
   ```

   Query is the default. Use explicit [Mutation publication](MUTATION_SKILL_RELOAD.md)
   when updating trusted Mutation entries.
3. Check the change receipt and affected definitions as described below. When the
   task requires execution, use the new parameters for an authorized read.
   Explicitly pass the same target `connection_id` to discovery/detail and execution;
   setting it on a canary does not make later calls inherit it.

Reuse relevant detail or business calls for confirmation. Ordinary queries gain no
mandatory management step.

## Calling Agent confirmation

Verify the intended update in the actual consuming session before reporting
completion; acceptance or a statement that refresh occurred is insufficient.

| Stage | Evidence to check | Supported conclusion |
| --- | --- | --- |
| Publication | `success=true`, expected `revision` and `added/changed/removed`; no-op revisions stay unchanged | Definitions published in the receiving instance |
| Consumer visibility | Same target `connection_id`, affected details and expected parameters/scope; discovery for additions and exact absence checks for removals as needed | This consumer sees the intended update |
| Business validation | When the task needs execution, use the new parameters for an authorized read and check its result | This business check passes |

Publication alone does not establish database readiness, authorization or correct
business results. Definition-only deployment does not require executing every Skill
or probing other targets. Report missing evidence as unverified. No generic
confirmation tool is required, and the server cannot guarantee arbitrary models
comply with these caller obligations. Handle failures and lost responses below.

## Publication contract

### Candidate validation

- Reuse definition, parameter and startup SQL checks. Invalid definitions,
  missing/empty SQL sources, escaping paths or detected file changes reject the
  whole candidate; the previous catalog remains active.
- A missing root is an error; an empty root can intentionally remove all Queries.
  Removing a whole Skill directory or setting `enabled=false` removes the Query;
  retaining an old Skill directory without its definition is an error.
- Reject active Query paths replaced by regular files, dangling/loop symlinks or
  unverifiable directories. Detected disappearance or directory identity change
  during the scan also rejects the batch, even if the name returns. Failures keep
  the catalog, `revision` and previews. Real deletion and valid directory symlinks
  resolving within the configured root remain supported.

### Atomic publication and request snapshots

Publish once after validation. Each MCP request retains one snapshot across awaits;
new requests use the new one. In-flight references keep old snapshots, and removal
does not immediately revoke admitted work. Ordinary calls perform no new file or
database probe.

Return process-local `revision`, `added/changed/removed`, preserved mutations and
ignored new mutations. Identical definitions retain revision and caches.
Parameter/scope/SQL changes count; Markdown not projected by the existing loader
does not become runtime instructions.

### Failures and lost responses

| Situation | Result or action |
| --- | --- |
| Candidate validation or publication failure | Return `query_reload_failed` with a safe reason and keep the old catalog; do not report success |
| Concurrent reload | Return reason `reload_in_progress` |
| Lost response | Inspect loaded details first; do not assume publication failed or retry automatically |

## Boundaries and costs

Existing Mutation metadata/classes/plans and preview tokens remain unchanged even
if their files changed/disappeared. Preserved Mutation names are skipped before
probing filesystem targets. New mutations are reported, not imported or activated
by Query publication. Type conversion still requires restart.

Query publication reloads no Mutation Python, shared dependency, connection, grant,
configuration or core code; no watcher or automatic revoke/write retry is added.
Existing connection/profile/readiness, read policy and authorizer checks remain
active. Loading is not an execution grant.

Explicit reload uses a worker thread; each MCP call adds a small context snapshot
scope. One management call and one tool definition are added; ordinary business
tasks need no extra mandatory call. No latency or model-token saving is claimed.

## Codex restart helper

For core-code, shared-dependency or deployment-configuration changes that require
a fresh process, see the [restart/reconnect helper](CODEX_MCP_RESTART.md). It
distinguishes configuration refresh from process replacement and requires actual
consumer confirmation. It manages existing Hosts only; current automatic
maintenance may affect only the current chat, and VS Code Codex reconnection
remains manual. Host-wide refresh needs explicit authorization. Query file
publication remains per receiving instance and preserves Mutation previews.

## Historical acceptance and diagnosis

These records retain their dates, failures and then-unverified states. Later
success does not rewrite earlier conclusions or replace future deployment checks.

### Engineering and additions after startup

[Engineering acceptance](../validation/v3.8/V3_8_2_QUERY_RELOAD_2026_10_28_ZH.md)
records source and installed-package checks. Additions after startup already have
the following direct evidence:

- `tests/test_query_skill_reload.py::test_same_client_add_change_disable_delete_and_policy`
  covers same-client addition/detail.
- The [stdio workflow](../../scripts/validation/query_reload.py) covers detail and
  execution of an added definition in both recorded source/package modes.
- The [14 parent-Agent native checks](../validation/v3.8/V3_8_2_QUERY_RELOAD_RESTART_2026_10_28_ZH.md)
  cover addition after startup, list discovery, detail, execution, changes,
  failed-candidate preservation and removal.

### Complete multi-session tasks

Validate fixtures first, then verify each actual consumer can call the service,
publish in that instance and confirm parameters before business rounds. Account
for deployment, preflight and business costs separately. A Host catalog entry alone
does not pass the gate. Preserve an unavailable first call and stop rather than
substituting parent success, replacement sessions or repeated restarts.

| Cohort | Result and scope |
| --- | --- |
| [Consumer acceptance, October 28, 2026](../validation/v3.8/V3_8_2_QUERY_RELOAD_CONSUMER_2026_10_28_ZH.md) | Retain three failed preflights |
| [Startup-gated batch, October 29, 2026](../validation/v3.8/V3_8_2_QUERY_RELOAD_READY_2026_10_29_ZH.md) | After exact-thread startup evidence, native readiness 2/3 and full two-round completion 1/3; preserve one handshake failure and one omitted model connection argument |
| [New-parent-turn full acceptance, October 29, 2026](../validation/v3.8/V3_8_2_NEW_TURN_BUSINESS_ACCEPTANCE_2026_10_29_REVISED_ZH.md) | Complete 3/3 two-round workflows, consumer parameter updates/removal and six core query results matching independent truth; strict whole-task 2/3 retains one model percentage-rounding error |

The latest three Luna tasks focus on parameter changes/removal; addition evidence
is listed above. Model results remain separate from scoped atomic-publication/restart
acceptance. The final batch adds no configuration edit/refresh and establishes no
universal Host fix or speed/token gain.

### Directory and restart boundary repairs

The [November 5, 2026 scope/catalog repair](../validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md)
records strict active-directory checks and isolated verification; it does not close
unverified resident-service checks. Earlier proxy initialization timeouts remain
historical evidence. The direct WebSocket path and actual Host restart at that time
are recorded in [separate acceptance, October 28, 2026](../validation/v3.8/V3_8_2_CODEX_MCP_RESTART_2026_10_28_ZH.md).
Their success does not establish the cause of earlier child-session availability failures.

## References

[Codex protocol](https://learn.chatgpt.com/docs/app-server),
[MCP tool updates](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
and [Python reload caveats](https://docs.python.org/3.12/library/importlib.html#importlib.reload).
