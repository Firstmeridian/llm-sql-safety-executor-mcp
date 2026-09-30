# MCP Client verification · v3.8

This guide uses the installed `sql_safety_executor` package and explicit TOML
configuration. Run repository scripts from the repository root after
`uv sync --frozen --group dev`. The previous script-based instructions remain in
the [v3.7 historical guide](TEST_MCP_CLIENT_GUIDE_v3_7.md).

## Offline checks

```bash
uv run sql-safety-executor config check --config config/examples/sqlite/server.toml
uv run sql-safety-executor config explain --config config/examples/sqlite/server.toml
uv run python scripts/check_prompt_contract.py --config config/examples/sqlite/server.toml
```

These commands resolve explicit secret references but do not connect to a
database or import business Skills. They do not prove that a database is
reachable or that a Skill can execute. See the [configuration contract](CONFIGURATION_ZH.md)
for path resolution, defaults, authorization and migration from `.env`.

## Protocol and tool inspection

### Update the actual Host launch entry

The repository's `mcp_config.json` (or private `mcp_config.local.json`) is a
template; editing it does not update a Host's saved configuration. In particular,
Codex uses `[mcp_servers.<name>]` in `~/.codex/config.toml` or trusted project
`.codex/config.toml`, not the template's `mcpServers` JSON wrapper:

```toml
[mcp_servers.sql-safety-executor-mcp]
command = "/absolute/project/.venv/bin/sql-safety-executor"
args = ["serve", "--config", "/absolute/project/config/server.toml"]
```

Use the environment where v3.8 is actually installed (which may be `.venv-v38`
during migration). Back up the existing Host entry and replace both its
executable and arguments; a saved `start_server.py` entry cannot start v3.8.
Reconnect the server/restart the extension after saving. A process already
running, a successful offline config check, or a configured-server list is not
proof that the active conversation can discover and call its tools. Verify
`list_connections` through that Host. See the [official Codex MCP guide](https://developers.openai.com/codex/mcp).

### Inspect a fresh reference server

```bash
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode auto
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode legacy
```

The script starts a fresh stdio server, prints the negotiated protocol,
`tools/list` schemas, configured connections and server instructions, then
closes the process. With the locked reference Client, these modes negotiate
`2026-07-28` and `2025-11-25`, respectively. It does not call a database query or
connection probe. Unlike offline checks, startup does discover enabled Skills;
enabled mutation modules are trusted Python and may have import side effects.

Only configured tools should appear. In particular, Skills-disabled deployments
must omit all Skills tools, and `request_mutation_approval` appears only when
MRTR, Skills and global writes are enabled. Registration does not grant access
to every configured target or Skill.

For an actual read through the complete core policy:

```bash
uv run python scripts/query.py --config config/examples/sqlite/server.toml \
  --connection-id demo 'SELECT 1 AS value'
```

This last command accesses the selected database. It is a core-service check,
not a protocol or natural-language Agent test. Use a disposable fixture for
queries that inspect business data; schema and count operations can also incur
database work.

## Reference human-approval Host

Preview/execute remains the recommended default as of October 1, with MRTR
opt-in per verified Host. The tested Codex IDE handled the main native approval
interactions; the tested Copilot session failed the protocol gate. This is not
a claim about all current clients. The [acceptance audit](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)
separates native coverage, automated coverage and outstanding evidence.

Do not automatically fall back to another write entry point after an MRTR
refusal, cancellation, timeout or uncertain result. Choosing preview/execute
for a deployment is separate from retrying a particular mutation. Reconcile
uncertain writes before considering a newly reviewed and authorized proposal.

Create the separate demo database once; the setup script refuses to overwrite
an existing file:

```bash
uv run python scripts/setup_sqlite_demo.py --output local_data/mutation-demo.db
```

Prepare a UTF-8 JSON file containing
`{"order_id": 1, "new_status": "confirmed"}`, then run:

```bash
uv run python -m examples.manual_mutation_approval \
  --config config/examples/mutation/server.toml --flow preview \
  --connection-id demo_write --skill sample-update-order-status \
  --params-file /absolute/path/params.json
```

The legacy MCP tool does not itself request an approval window. Calling preview
directly from an Agent chat returns a token; any subsequent conversational
confirmation is implemented by that Agent/Host. The example above instead
enforces approval in the reference Host's code. An authorized alternative
client can still submit `confirm=true` with a matching token without a human.

MRTR requests Host input through the protocol and verifies the bound response,
but the Host can answer automatically. Neither flow independently authenticates
a person. A generic tool permission prompt is separate from reviewing the exact
SQL. Enabling MRTR also leaves legacy preview/execute available; it does not
impose approval windows on all writes. See [DRR-2026-050 and the flow comparison](../security/V3_8_SECURITY.md#where-approval-is-enforced).

For acceptance records, distinguish preview success, actual user approval,
execution and post-write verification. If the user asks a question after a
preview, do not treat it as approval. If approval arrives after expiry, prepare
and review a new proposal instead of assuming the old approval transfers.

An approval choice returned by a client question tool records a response; it
does not prove that the user saw or reviewed the complete proposal. Keeping SQL
and bindings only in that tool's message field is not visible-review evidence.
If the user reports a missing preview, do not mark review presentation as
accepted. Show the complete target, Skill, parameters, SQL, bindings and expiry
in the chat body and wait for an explicit approval reply before future writes.
This is a client interaction rule, not a new server authorization control.

Keep separate trials distinct. On October 1, the Copilot legacy flow committed
shipped -> delivered and then restored the demo order through three separately
committed steps: delivered -> pending -> confirmed -> shipped. A later preview
with expiry 20:44:01 UTC had no execute; that result does not erase the earlier
writes. Final state equality is not evidence of no intervening mutation or a
transaction rollback. Recorded approval choices do not establish visible review.
See the [dated trial and evidence boundaries](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

The default flow is `preview`. For MRTR, first set
`skills.mutation.mrtr.enabled = true` in the selected Skills TOML, then use
`--flow mrtr`. Use a fresh fixture or deliberately restore the business state
before another trial; a successful first run changes the order status. The
reference Host accepts only literal `APPROVE`; its default approval deadline is
60 seconds and its default tool timeout is 120 seconds. The server's original
proposal expiry also remains authoritative.

Both flows share an outer deadline, a fingerprint of the displayed review
(including nested values), and an expiry recheck after approval. A custom
provider returning late or modifying the view cannot approve execution. The
deadline is separate from server token TTL. These checks guard buggy trusted
providers; they cannot forcibly stop hostile or permanently blocking Python.
MRTR cancels the proposal for detected failures, while a lost connection or
external cancellation may leave it pending until expiry.

MRTR requires the modern protocol and form elicitation, and supports only
managed single-statement mutations. The Host displays the review and collects
the decision; the server validates bindings and consumes a proposal once. A
missing/expired proposal or lost response does not prove that a previous write
did not happen. Do not automatically retry; reconcile the business state first.
See [security boundaries](../security/V3_8_SECURITY.md).

## Automated and native Host evidence

```bash
uv run pytest -q -rs
uv run pyright
uv build
```

Pytest collection is configured in `pyproject.toml`. The default suite uses
isolated fixtures and does not load the private `.env`. The optional MySQL test
fixture still accepts explicitly exported `DB_USER`, `DB_PASSWORD`, `DB_HOST`
and `DB_NAME` only after `RUN_MYSQL_INTEGRATION_TESTS=1`; this is a test harness
input, not a restored server configuration channel. Use a dedicated test DB.
CI separately installs the wheel and runs `scripts/verify_installed.py` from
outside the repository with both protocol generations and packaged prompts.

Reference Client success does not establish Codex or Copilot compatibility.
For each native Host, record the actual version, negotiated protocol, visible
tools, approval UI/decision, call trace, resulting database state and actual
usage. An unsupported protocol/capability or Host policy refusal is a recorded
limitation, never an MRTR pass. See the [v3.8 validation record](../validation/V3_8_VALIDATION_ZH.md)
and the [Agent evaluation method](MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md).


## Native approval checkbox acceptance (October 1, 2026)

Distinguish the Host permission to call `request_mutation_approval` from the
subsequent MRTR review form. To test refusal, allow the tool call, leave the
review form's approval checkbox unchecked, then submit. In the inspected Codex
IDE extension 26.917.62051, Skip sends `decline`; the top-right close button and
Escape send `cancel`. Test these separately: expect `approval_declined` for
Skip or unchecked Continue, and `approval_cancelled` for close/Escape. Other
Hosts may map their controls differently. Always verify the returned
`error_code`, `execution_outcome` and database state.

The shared server form now uses a required boolean `approve` with
`default=false`. This standard MCP hint fixed unchecked submission in the tested
Codex IDE; required presence does not require a true value. The server still
executes only for `accept` with strict boolean true, and does not fill in missing
answers from the default. A Host that still blocks unchecked submission should
be recorded as incompatible for this case; do not check the box to bypass the
validation. Other Host UIs need their own acceptance tests.

See the [refactoring log](../../REFACTORING_LOG.md#v380-mrtr-approval-form-default-october-1-2026)
for the observed versions, approval/cancellation/refusal results, 121-test
regression run and pending native expiry/restart cases.

## Delayed approval and restart acceptance (October 1, 2026)

Capture the proposal's `expires_at` and timezone before waiting. Approve only after that timestamp plus at least ten seconds; an early approval can commit a real test write. Distinguish Host timeout, framework `invalid_request_state`, and business proposal expiry. A framework error may have no `execution_outcome`; independently read database state instead of inventing a business result or retrying the write.

The user confirmed approving after more than ten minutes in the long-wait MRTR trial. It returned `Invalid or expired requestState` and the database stayed unchanged. Earlier MRTR approvals committed orders 1 and 2 without compensation in that trial; orders 1–3 were then all shipped. A separate later Copilot preview/execute trial committed a change and three restoration steps, as recorded above; do not merge these scopes. See the [dated evidence](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

For restart acceptance, establish that the server process actually changed and that the old proposal was submitted afterward. `approval_declined` alone does not establish a restart. The current Agent cannot reconnect the Codex-owned stdio child through its available tools, so native restart acceptance is pending. An independent client may control real server shutdown/startup, initialize a new session, submit the saved old continuation, and verify rejection and unchanged data. That test is now implemented in `tests/test_v38_mrtr_restart.py` and passed with the related 131-test suite. It verifies different PIDs, rejection before the original expiry, unchanged temporary SQLite data, and successful approval of a fresh proposal. It remains separate from native UI acceptance. Do not terminate the active Host's child without a recovery path.

## Readable review presentation

The review retains the question on the first line and complete JSON afterward, now with two-space indentation and readable Unicode. Reference Hosts must parse the entire remainder with a JSON parser, not assume single-line JSON. Formatting uses only the saved snapshot; missing-answer re-asks show the same review. The 64 KiB stored-review cap does not cap the expanded presentation message.

After restarting the service, verify the target, Skill, full SQL, bound values and expiry remain visible in the actual Host. For a presentation-only check in this Codex version, use the top-right close button (not Skip) to test cancellation without approving a write. New formatting has passed protocol/Host regressions and a post-restart screenshot in the tested Codex IDE; the close-button call returned `approval_cancelled` without a database change. Other clients still need their own rendering check. See the [current acceptance matrix](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Verify the running service after a presentation change

Editing the module does not update a running stdio process. Ensure the Host has
restarted the service after the patch, then re-open a new review. On October 1,
both inspected Codex-owned service processes predated the indentation patch;
the displayed compact JSON was therefore from processes started with old code.
The inspected frontend uses `whitespace-pre-wrap` for form messages. New-process
protocol tests verify indented output; a subsequent user restart and screenshot
confirmed the native multiline display in this Codex IDE. Do not introduce hot reload or silently remap decline
into cancel to make this acceptance pass.

### Copilot observation (October 1, 2026)

A user-supplied native Copilot transcript showed two unchanged reads around a
single MRTR request rejected by the MCP 2026-07-28 requirement. No form appeared,
no approval was submitted, and no alternative write flow was invoked. Record
protocol-gate rejection separately from UI acceptance. “Latest” was reported,
but exact client/extension versions and the negotiated protocol were not
captured. Obtain initialization evidence before attributing a particular
protocol version or form capability; do not reuse Codex-specific feature flags
as Copilot settings. Full scope: [acceptance record](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Version capture for built-in Copilot

As checked on October 1, 2026, the [official Stable release](https://code.visualstudio.com/updates/v1_140) is VS Code 1.140.0. The local VS Code Server matches that version/commit, and its `extensions/copilot/package.json` identifies `GitHub.copilot-chat` 0.68.0. Copilot Chat has been [built in since 1.116](https://code.visualstudio.com/updates/v1_116#_github-copilot-is-now-builtin); checking only the user extensions directory or the old standalone Marketplace listing misses this component.

Record release channel, editor/server version, bundled or overriding extension version, session harness and actual MCP initialization separately. Local package metadata establishes installation, not the protocol negotiated by a previous chat. See the [dated version supplement](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md) for exact paths and source boundaries. The earlier “versions not captured” statement describes the transcript-only stage.

Later inspection of the same Copilot session log records VS Code 1.140.0 and
Copilot 0.68.0, and corroborates the approval tool's protocol-gate error. The
installed Copilot bundle contains an MCP SDK whose latest protocol constant is
2025-11-25 and whose supported-version list omits 2026-07-28. This is static
evidence about that bundled SDK, not proof that the session used that client
path or that every Copilot harness lacks MRTR. The actual request protocol,
capabilities and backend remain unverified. For 2026-07-28, inspect per-request
protocol/capability metadata as well as any legacy initialization; Agent Host
Protocol versions are not MCP versions. This follow-up added no database or UI
test. Full evidence and remaining uncertainty are in the dated acceptance record.

## Skill rejection recovery and subagent delegation (v3.8.1, October 1, 2026)

A `validation_failed` mutation response may include
`related_available_skills`: names of declared related mutation Skills that are
currently executable on the same connection. It is a discovery clue only, not a
recommendation, authorization or approval. Preview and approve every write in
any alternative path separately, and do not bypass the rejected rule or change
targets.

When delegating to a database subagent, state the user's goal and what to report
if a Skill rejects it, for example: "If it is rejected, explain how the goal
could still be achieved, but do not execute anything." Do not ask a subagent
whether a preview token is still usable. Report `preview_token_expires_at` as
returned; execute alone decides validity, and any Host-side countdown should be
computed from the current clock. See the [acceptance record](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)
for the 3-run behavior matrix and remaining limits.

### Reading mutation results and refreshing Host tool definitions (v3.8.1)

The `execute_mutation_skill` description now carries the result rules because
some Hosts, including Copilot, do not pass `outputSchema` descriptions to the
model. Read `execution_outcome`, not `success`; treat an error without
`execution_outcome` as unknown; never retry or switch entry points without a
new user decision. Replay checks can give recorded results to an Agent in the
prompt, but that is not the same as the tool channel and should be reported as
such.

After changing tool descriptions, restarting the server was not enough in the
tested VS Code build. Run **MCP: Reset Cached Tools**, then make one tool call so
the Host lists tools again, and confirm the new text reached the model (for
example, ask a subagent to quote it) before behavior testing.
