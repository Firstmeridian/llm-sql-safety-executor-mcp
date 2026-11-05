# Codex MCP refresh and reconnect helper

[中文](CODEX_MCP_RESTART_ZH.md)

Use [`scripts/dev/restart_codex_mcp.py`](../../scripts/dev/restart_codex_mcp.py)
to connect to an existing Codex Host. It adds no SQL MCP management tool.

## Choose an entry point

| Need | Entry point |
| --- | --- |
| Publish supported Query or Mutation definitions | Prefer [`reload_skills()` for Query](QUERY_SKILL_RELOAD.md) or [explicit Mutation publication](MUTATION_SKILL_RELOAD.md). |
| Inspect Host/catalog binding or verify an existing connection | Use read-only `probe` or `verify`. |
| Request configuration refresh | Use `refresh`; unchanged healthy clients may be reused. |
| Replace a process for core-code, shared-dependency or deployment-configuration changes | Use `restart` when the old actual consumer PID can be verified. |
| Bootstrap or recover when the old catalog, Query call or PID is unavailable | Independently select explicit `recreate`, subject to its prerequisites below. There is no automatic `restart` → `recreate` fallback. |
| Reconnect VS Code Codex, or handle an unverified scope | Use manual reconnection. Automatic extension restart is deferred. |

**Current use policy:** automatic maintenance may affect only the current chat.
If other conversations are loaded or the scope cannot be established, use manual
reconnection; idle conversations do not authorize global refresh or group mode.
Retained multi-thread options are documented separately at the end as historical
capabilities, not current authorization or workarounds for a single-chat refusal.
Reusing them requires an explicit maintainer change to this scope decision.

## Prerequisites

### Environment, binding and scope

Use a checkout with development dependencies installed (`websockets`, currently
locked at 17.1). Execute venv Python using its configured path; resolving its
symlink first can select system Python without the helper dependency.

The helper connects only to an existing Host's Unix WebSocket endpoint. It never
launches/replaces a Host or creates/resumes/migrates a conversation. Bounded
discovery examines only existing owned sockets in `/tmp/codex-daemon-UID/`, or use
`--socket`. Symlinks are rejected. `CODEX_THREAD_ID` or `--thread-id` must uniquely
match a loaded thread. The default `--server` is the exact configuration name
`sql-safety-executor-mcp`, not the normalized model-tool namespace.

Host uniqueness is based on loaded-thread membership, independently of MCP
catalog availability. If two endpoints load the current thread, a catalog failure
at one does not make the other Host unique; refuse the ambiguity. The ordinary
`probe`, `verify`, `refresh` and `restart` paths also require the target Query
catalog. This catalog requirement does not apply to the `recreate` recovery entry.

Codex 0.165 exposes only **Host-wide** `config/mcpServer/reload`, without a
server/thread selector. `--server` restricts verification, not refresh. The
maintenance scope must be authorized for all affected services/loaded threads,
with no writes in flight. Under the current policy, `restart`, `refresh` and
`recreate` require exactly one loaded thread; other chats are refused even when
idle. An existing test connection alias is required for calls beyond `probe`.
Inventory/PID rechecks are not atomic isolation and cannot guarantee zero
concurrent impact.

### `restart`: verify the old actual consumer PID

The default restart requires absolute command/cwd and a uniquely matching local
stdio child. Bind the listener owner and child by UID, parent, complete
command/arguments and cwd; wrappers, remote execution or ambiguity fail explicitly.

Disk configuration and matching argv/cwd identify only a **candidate**. Before
any signal, reuse the existing constant read in every selected consumer and
require its `_meta.server_pid` to match the fixed candidate PID set exactly;
recheck start identities, launch aliases and configuration before stopping.
Missing or mismatched identities are refused, including when another service's
alias was deleted but its old process is still running. Do not infer identity
from disk config or bypass this check with the old stop path.

Successful queries add one PID integer to existing optional `_meta`, without
changing business data or adding another database/network round trip. This is a
trusted local process check, not remote authentication or atomic isolation. If the
old process lacks this field, `restart` refuses. Independently select `recreate`
when its conditions apply; otherwise use maintainer action.

### `recreate`: independent bootstrap/recovery prerequisites

`recreate` binds the existing Host/thread and exact service in user configuration
without requiring a working old catalog, Query call or PID. A reachable control
endpoint alone is insufficient: recovery still requires unique current-thread
binding, supported launch configuration and permissions, and explicit
configuration-toggle/Host-wide scope authorization. Preflight checks the user
configuration source, enabled state, absolute stdio launch definition and thread
scope. Host lifecycle management handles the target; the helper sends no process
signals and never enters this mode automatically.

## Invocation

### Read-only inspection and verification

```bash
python scripts/dev/restart_codex_mcp.py probe
python scripts/dev/restart_codex_mcp.py probe --check-process
python scripts/dev/restart_codex_mcp.py verify --connection YOUR_TEST_ALIAS
```

The default is read-only probing. `probe --check-process` inspects a process
candidate without a signal or SQL and leaves `process_binding_verified=false`;
it does not establish consumer/process identity. Use `verify --check-process`
with the test connection to establish that binding read-only. `verify` requests
no reload and checks the catalog plus `SELECT 1 AS codex_mcp_restart_canary`.
The previous `probe_codex_mcp.py` entry point remains a read-only alias sharing
this transport.

### Replace a verified old process

```bash
python scripts/dev/restart_codex_mcp.py restart --allow-host-wide --connection YOUR_TEST_ALIAS
```

After the prerequisite binding and constant read, deliver SIGTERM through a Linux
pidfd to the fixed target, wait at most 10 seconds without escalating to SIGKILL,
send one Host refresh, retrieve the target catalog, check a constant read and
verify a replacement process. Recheck the loaded-thread set before sending the
refresh; the checks still do not provide atomic concurrency isolation.

### Request configuration refresh

```bash
python scripts/dev/restart_codex_mcp.py refresh --allow-host-wide --connection YOUR_TEST_ALIAS
```

`refresh` checks a constant read, rechecks the loaded-thread set and requests
configuration refresh without stopping the process. Configuration that has not
changed may reuse healthy clients, so successful refresh is not proof of restart.

### Explicit Host-managed recreation for bootstrap or failed calls

```bash
python scripts/dev/restart_codex_mcp.py recreate --dry-run --connection YOUR_TEST_ALIAS
# After scope approval; the journal must be a new file:
python scripts/dev/restart_codex_mcp.py recreate --allow-config-toggle --allow-host-wide --connection YOUR_TEST_ALIAS --state-file /tmp/sql-mcp-recreate-001.json
```

1. Read-only preflight checks the independent recovery prerequisites. A dry run
   performs no writes, SQL or refresh; exit 0 with `recreate_plan_verified` is only
   a plan, not successful recreation or tool availability.
2. Create a new recovery journal. Version-check an edit of only
   `mcp_servers.<name>.enabled` to false, stage without implicit reload, then
   refresh once. Require every original consumer to report disabled with no tools.
3. At the version returned by the disable write, restore the original value or
   omitted key and refresh once more. Never overwrite the whole configuration or
   concurrent edits. The edit is limited to that key; Host formatting may change,
   and `config_bytes_restored` reports actual byte equality rather than
   guaranteeing all TOML layouts.
4. Verify the original consumer catalogs, constant reads and fresh process
   identities using the success conditions below.

Before the first disable write and each Host-wide refresh, including the
post-restore refresh, recheck the pinned loaded-thread scope after the
corresponding journal write is flushed and `fsync`ed. A changed scope or failed
check stops that disable or refresh send. **Acknowledged-disable cleanup remains
required:** a scope failure does not suppress the one version-checked restoration
attempt described under failure recovery; it does not permit another refresh.
The journal contains phases, versions and the original flag, not config bodies,
credentials or business data.

## Confirm success

### Script result and bounded reads

Exit 0 must be interpreted with `status` and the verification fields:

| Result | What it establishes |
| --- | --- |
| `binding_verified` | Catalog binding only; `probe` does not prove successful tool use. |
| `connection_verified` | A real constant Query response. `reload_attempted`, `reload_accepted`, `read_probe_verified` and catalog hashes distinguish the stages. |
| Successful `restart` | Also requires `phase=complete`, `process_binding_verified`, `process_stop_attempted`, `process_restart_verified=true` and `read_probe_verified=true`. |
| Successful `recreate` | Requires `phase=complete`, `target_disabled_verified`, `config_restored`, `process_restart_verified` and `read_probe_verified`. Every original consumer must return a successful canary with a PID matching the Host/launcher and a process identity absent from the pre-operation child snapshot. |
| `recreate_plan_verified` | A dry-run plan only. |

An unchanged catalog hash does not prove no refresh occurred; neither hashes nor
`{}` prove process replacement. `refresh`/`verify` leave replacement unverified.
A fresh `recreate` consumer does not prove all old processes exited; without a
known old PID, `previous_target_exit_verified=false` remains.

Refresh acceptance can precede catalog publication and startup. Under the tested
0.165 schema, bounded observation permits `null`, `notStarted`, `starting` and an
old `disabled` state after restore; failed, cancelled, authentication-required or
unknown states stop. `connected` must include `query`.

Ordinary RPCs default to 10 seconds (maximum 30). After refresh, `restart`,
`refresh` and `recreate` share **up to 30 seconds** across all consumer catalog
and single-canary reads, capped by the original **60-second total RPC budget**
and the applicable work deadline after any recovery reserve. Each consumer gets
one post-refresh canary request. The window does not extend the total budget;
an exhausted budget prevents a new send. Inventory/notification counts remain
bounded. Connection/cleanup have their own timeouts.

### Calling Agent confirmation

Keep script verification separate from the calling Agent's verification. The
official [App Server documentation](https://learn.chatgpt.com/docs/app-server)
describes reload as reading configuration and queuing a refresh; request
acceptance alone does not prove process replacement.

1. Check all mode-specific success conditions above. `reload_accepted` confirms
   only acceptance, not completed recreation, replacement or model-tool visibility.
2. Verify a native tool call in the caller's actual session. A constant read
   establishes channel usability. For a code/dependency/tool-contract deployment,
   also check the changed read-only behavior or actually visible definition; a
   new PID and constant alone do not prove that change took effect. Reuse relevant
   task checks and do not execute writes merely to test deployment.
3. Report process replacement, connection usability and intended-change
   verification separately. Keep `model_tool_visibility=unverified` when
   model-visible definitions cannot be observed; a control-endpoint catalog is
   insufficient. If a new turn is needed to rebuild discovery, report the pending
   check and verify on that turn without an automatic refresh or retry.

Future purposeful restarts need checks matching their intended change; ordinary
business queries do not require restart or repeated discovery.

## Failure recovery and diagnostics

### Preserve uncertain outcomes and restore acknowledged disables

Exit 2 retains the failed `phase`. A lost refresh response is unconfirmed; a
stop attempt without completed refresh does not establish availability. Use
read-only `verify` first to inspect the current state. A failed catalog/read
check is failed acceptance even if refresh was accepted; `verify` itself does
not recover unavailable instances.

Do not automatically retry an RPC, canary, config edit or refresh after timeout
or an uncertain result. Do not automatically switch from `restart` to `recreate`,
widen to group mode, infer an earlier write did not execute, or replay Mutations.
Waiting longer alone does not establish that a startup cause has been repaired.

For `recreate`, after an acknowledged disable, failure cleanup attempts to restore
the flag **at most once at the exact returned version**, if restoration has not
already been attempted. This still applies after a scope change or a journal
failure before restoration. The scope gates on the first disable and each refresh
are not a blanket stop on version-controlled cleanup. Do not resend an attempted
or uncertain restoration, overwrite newer user edits, or add a recovery refresh.
Configuration restoration does not establish runtime recovery.

Recreation reserves one ordinary RPC window (`--timeout` seconds) inside the
original 60-second total budget to restore an acknowledged disable. Work phases
stop earlier; restoration never extends the total deadline. This reserve cannot
guarantee recovery from transport, disk or Host faults. Inspect the journal,
`reason`, `config_restored` and `manual_recovery_required`; conflicts and
unresolved failures require manual reconciliation.

### Read-verification diagnostics

Failures retain the verification substep and `last_rpc` method, actual timeout
allowance, monotonic duration and `request_sent`. This flag means a send was
attempted, not that the Host received it. No params or credentials are recorded.
Check the restoration state and specific failed step before drawing conclusions.

### Host and current-thread binding diagnostics

`probe` and other modes retain `binding_diagnostics`: a bounded candidate number
and terminal phase for endpoint validation, connection, initialization, thread
inventory/membership, server catalog and final uniqueness. Only allowlisted
exception categories and applicable errno values are reported, without socket
paths, thread lists or exception text. `thread_id_source` distinguishes
`--thread-id` from `CODEX_THREAD_ID`; `endpoint_source` distinguishes `--socket`
from discovery, even when explicit values equal environment values.

`current_thread_not_loaded` is used only after the complete inventory is obtained.
A catalog timeout retains `current_thread_loaded=true` and `phase=catalog`; the
top-level `current_host_not_verified` alone does not prove a missing thread.
Other candidates' handshake failures remain visible, and duplicate matches still
fail. Do not bypass membership, resume/create threads or guess ownership from
titles, workspace or tool names. Explicit socket/thread overrides require a
trusted mapping. The standalone helper loads current disk source without
restarting SQL MCP to obtain diagnostics.

## Limits

- Only verified local Linux Unix WebSocket control is covered. Stdio-only control,
  remote or differently authenticated Hosts and inaccessible endpoints may require
  maintainer action. A sandbox may need narrowly scoped socket access, not Full
  access. **VS Code Codex reconnection remains manual**; do not take over its
  private stdio pipes.
- Host config versions are opaque concurrency tokens. A `sha256:` prefix does not
  make them interchangeable with a file-content digest. Version checks prevent
  concurrent overwrites, not cross-Host isolation: other Hosts can observe the
  shared user-config toggle. Scope checks and RPC sends are not atomic.
- The default modes do not edit configuration; explicit `recreate` temporarily
  toggles one target enabled key. No grant changes, new or terminated Hosts/threads,
  signals to other services, business-table inspection or Mutation execution are
  added. Both recreation refreshes are Host-wide. No runtime dependency, SQL MCP
  management tool, ordinary-query step or general Host guarantee is added.
- Restart/recreation loses process-local previews, unlike Query publication. This
  does not prove an earlier write was never executed. Disabled catalogs and new
  consumer success do not prove all old processes exited. Host teardown may be
  asynchronous and use its own termination policy; `recreate` itself sends no
  process signals.
- Check the [OpenAI protocol](https://learn.chatgpt.com/docs/app-server) schema
  against the actual Host binary. The local PATH CLI 0.164 differs from the tested
  Host 0.165; these observations do not establish earlier proxy-timeout causes or
  a guarantee for all Host versions.

## Historical acceptance and startup investigations

The following records preserve their own dates, scopes, passes, failures and
unverified results. Later success does not replace an earlier incomplete command,
and historical one-time approvals do not authorize current maintenance.

### Single-thread restart and identity repair (October 28–29, 2026)

See [acceptance and retained failures](../validation/v3.8/V3_8_2_CODEX_MCP_RESTART_2026_10_28_ZH.md).
The distinction between refresh and physical restart was observed in native
acceptance. The [identity repair](../validation/v3.8/V3_8_2_RESTART_IDENTITY_REFUSAL_REPAIR_2026_10_29_ZH.md)
retains its historical manual-upgrade checkpoint; the subsequent recovery records
below do not rewrite that checkpoint.

### Initial recreation acceptance (October 29, 2026)

The [earlier scoped acceptance](../validation/v3.8/V3_8_2_CODEX_MCP_HOST_RECREATE_2026_10_29_ZH.md)
records **78 helper passes and five complete isolated Host workflows**. A
separately approved actual recovery restored config and refreshed twice; final
verification timed out. Later read-only binding and caller behavior checks pass
without another refresh; that historical first command remains incomplete.

### Readiness repair and complete actual recovery (October 29, 2026)

[Scoped evidence](../validation/v3.8/V3_8_2_CODEX_MCP_READINESS_2026_10_29_ZH.md):
**97 helper tests, two old-source defect sentinels and three complete new-source
isolated Host flows** pass. A separately approved actual recovery completes in
one command: config restoration, fresh consumer identity and reads pass;
caller-native constant also passes. That one-time approval is consumed. Preserve
the earlier real timeout; these counts are not merged with the initial batch.

### Budget and scope reviews (November 1 and 5, 2026)

The [final review](../validation/v3.8/V3_8_2_FINAL_REVIEW_2026_11_01_ZH.md)
records the recovery reserve inside the original total budget. The
[November 5 scope/catalog repair](../validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md)
records scope rechecks after journal flush/`fsync`, before the first disable and
each refresh. Neither record turns scope refusal into skipping acknowledged-disable
cleanup or makes checks and sends atomic.

### Historical multi-thread capability and acceptance (October 29, 2026; not currently recommended)

This section retains existing capability and historical acceptance; it is not a current maintenance recommendation. The current-chat-only policy above governs use.

This section describes PID-bound group `restart`. Host-managed `recreate` above uses the named service lifecycle, not direct process-set stops.

`--all-loaded-targets` is an opt-in scope, never an automatic fallback. It selects
**all direct children of the bound Host matching the exact target command,
arguments and cwd**, including this service's processes used by other idle
threads. It is not a POSIX process-group signal. It requires separate approval
for that complete target set as well as the existing Host-wide refresh scope.
Other services are not explicitly stopped; the global refresh may affect them.
All selected instances lose process-local previews.

The retained bounded mode supports up to eight loaded threads, all in the helper's
workspace, with every other thread idle. Every thread must report a connected
target catalog. The exact target-child count must equal the loaded-thread count;
shared clients, other workspaces, unsupported launchers and mismatched counts
are unsupported. Equal counts do **not** prove a thread-to-PID mapping. The
helper keeps `thread_process_mapping=unverified`; matching configuration on disk
is not proof of each running thread's historical configuration snapshot. The
current helper additionally requires actual consumer-reported PIDs before stop;
the set check does not establish a persistent thread-to-process mapping.

Reject other configured service names with the same launch signature; recheck
configuration, thread inventory, idle states and the fixed process set before
signalling. Open pidfds for all members, stop only those members, confirm all
have exited, then send at most one global refresh. Check every original thread's
catalog and constant read, and require a full replacement set containing no
original process identity. Snapshots still do not provide atomic isolation.

`probe --all-loaded-targets` checks this scope without signals, refresh or SQL.
`verify --all-loaded-targets --connection YOUR_TEST_ALIAS` adds reads in every
loaded thread, without restart. The flag is rejected for `refresh`, which does
not replace processes. Report `process_scope`, target identities and counts,
`process_signals_sent`, `process_stops_confirmed` and verified thread count.
Partial stop or uncertain refresh remains a failure, with no automatic retry.
For an incomplete group operation, first inspect the report and remaining
processes; `verify` cannot recover unavailable instances by itself.

The [new scope's validation](../validation/v3.8/V3_8_2_CODEX_MCP_GROUP_RESTART_2026_10_29_ZH.md)
separates owned-process tests, read-only live preflight and authorized live
restart. The earlier single-thread acceptance does not certify this new scope.

The latest approved group operation replaces both fixed targets and verifies both original consumers with one global refresh in 4.241s; the caller then verifies the changed Mutation parameter and four native fixture checks. The separately approved restoration also replaces both targets and verifies both original consumers, then confirms QA-alias unload; it takes 8.354s including its additional checks. The caller independently verifies unload and removal of QA Skills. Both one-time approvals are consumed; neither operation proves a per-thread PID map or a general latency bound.

### Startup investigations (October 29, 2026)

One separately approved
[header capture](../validation/v3.8/V3_8_2_HANDSHAKE_CAPTURE_2026_10_29_ZH.md)
shows a late `server/discover` ID0 result reaching a Host already awaiting
`initialize` ID1. Independent controls confirm that a modern connection rejects
legacy initialization; correcting response IDs would hide the actual problem.
A later [version-pinned analysis](../validation/v3.8/V3_8_2_STARTUP_FALLBACK_2026_10_29_ZH.md) confirms
Auto discovery waits 10s before legacy initialization on the same transport. The
per-server CODEX_MCP_PROTOCOL_VERSION marker selects this path in 0.165; omitting
it selects Legacy. At that checkpoint, the one-key workaround was prepared but not yet applied;
the subsequent deployment and current acceptance are recorded below.
Increasing the outer startup timeout does not change this fixed inner wait.
This evidence does not establish the cause of every earlier readiness failure.

The capture was a private temporary diagnostic, not a helper feature. Its failed
deployment was restored within two explicitly approved global refreshes; no new
model trial followed. Run venv Python using its configured path: resolving its
symlink before execution can select system Python without the helper dependency.

The subsequent [approved attempt](../validation/v3.8/V3_8_2_LEGACY_MITIGATION_ATTEMPT_2026_10_29_ZH.md)
fails closed before signaling: config/batchWrite with reloadUserConfig=true can
publish runtime settings and invalidate an earlier child binding. Restore and
verify independently; do not follow a new PID automatically. A staged-write
revision uses false before the separate explicit MCP refresh; it was then prepared but not yet Host-verified. Account for config runtime publication separately from
explicit refresh RPCs. That protocol-setting investigation did not add config editing to `restart`.

The approved [staged revision](../validation/v3.8/V3_8_2_LEGACY_RESTART_ACCEPTANCE_2026_10_29_ZH.md)
verifies parent replacement and native reads. All three subsequent same-turn
child startups still fail before business. Codex 0.165 spawn clones captured turn
config; a refreshed parent client alone does not prove children inherit the
updated settings. The effective child marker was not captured. Keep this lead
separate from a proven cache cause; do not spawn replacements or refresh again
to fill the acceptance score. The per-server Legacy setting remains in place.

#### New-parent-turn acceptance (October 29, 2026)

The [single probe](../validation/v3.8/V3_8_2_NEW_TURN_CHILD_PROBE_2026_10_29_ZH.md) passes; a separately frozen [three-task batch](../validation/v3.8/V3_8_2_NEW_TURN_BUSINESS_ACCEPTANCE_2026_10_29_REVISED_ZH.md) completes all two-round workflows, consumer parameter updates/removal and six matching core-query result groups. Strict whole-task 2/3 retains one model percentage-rounding error. No new config edit or refresh. Earlier failures remain; captured turn configuration is a source-supported lead, without exact child-env/wire or unique-cause proof. After an approved config change, verify the actual child in a bounded check rather than assuming same-turn inheritance or repeatedly restarting/replacing trials.

At the October 29 checkpoint, the retained Legacy setting selects a protocol path for one actual Host; it is not an old-package/SDK compatibility layer. Before release, propose simpler upstream fixes or Host upgrades with impact and focused acceptance for the maintainer to approve; do not silently change the Host or private configuration.

Earlier parent-Agent native reads and the three Luna consumers provide
actual-channel evidence; the latter separately checked parameter updates,
execution and removal. These historical checks do not replace verification of a
future intended change.

### VS Code automatic-restart withdrawal (October 31, 2026)

Automatic extension restart was deferred. Original startup settings were restored
byte-for-byte; bridge code/tests/detailed reports were privately archived, and a
subsequent read-only inspection confirmed bridge exit. No additional window
reload is needed merely to remove the bridge. Existing CLI/daemon paths and Skill
publication retain their declared scope. Experimental history and withdrawal
evidence remain in `local_archive/v382_review/20261031_vscode_restart_deferred/`,
outside normal source/tests and release documentation. This record does not
change the current-chat-only policy or manual VS Code reconnection requirement.
