# MCP Client verification · v3.8

> October 14, 2026: target-specific CTE dependencies and measured MySQL ASCII CTE rules are covered in the [latest dated checks](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md#cte-依赖与实际名称规则修复2026-10-14). Reload the resident server before attributing results to new source; full Query Skill declared_tables/inferred_tables mark this implementation. Earlier model trials remain separate snapshots.

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
a claim about all current clients. The [acceptance audit](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)
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
See the [dated trial and evidence boundaries](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

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
limitation, never an MRTR pass. See the [v3.8 validation record](../validation/v3.8/V3_8_VALIDATION_ZH.md)
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

The user confirmed approving after more than ten minutes in the long-wait MRTR trial. It returned `Invalid or expired requestState` and the database stayed unchanged. Earlier MRTR approvals committed orders 1 and 2 without compensation in that trial; orders 1–3 were then all shipped. A separate later Copilot preview/execute trial committed a change and three restoration steps, as recorded above; do not merge these scopes. See the [dated evidence](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

For restart acceptance, establish that the server process actually changed and that the old proposal was submitted afterward. `approval_declined` alone does not establish a restart. The current Agent cannot reconnect the Codex-owned stdio child through its available tools, so native restart acceptance is pending. An independent client may control real server shutdown/startup, initialize a new session, submit the saved old continuation, and verify rejection and unchanged data. That test is now implemented in `tests/test_v38_mrtr_restart.py` and passed with the related 131-test suite. It verifies different PIDs, rejection before the original expiry, unchanged temporary SQLite data, and successful approval of a fresh proposal. It remains separate from native UI acceptance. Do not terminate the active Host's child without a recovery path.

## Readable review presentation

The review retains the question on the first line and complete JSON afterward, now with two-space indentation and readable Unicode. Reference Hosts must parse the entire remainder with a JSON parser, not assume single-line JSON. Formatting uses only the saved snapshot; missing-answer re-asks show the same review. The 64 KiB stored-review cap does not cap the expanded presentation message.

After restarting the service, verify the target, Skill, full SQL, bound values and expiry remain visible in the actual Host. For a presentation-only check in this Codex version, use the top-right close button (not Skip) to test cancellation without approving a write. New formatting has passed protocol/Host regressions and a post-restart screenshot in the tested Codex IDE; the close-button call returned `approval_cancelled` without a database change. Other clients still need their own rendering check. See the [current acceptance matrix](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

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
as Copilot settings. Full scope: [acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md).

### Version capture for built-in Copilot

As checked on October 1, 2026, the [official Stable release](https://code.visualstudio.com/updates/v1_140) is VS Code 1.140.0. The local VS Code Server matches that version/commit, and its `extensions/copilot/package.json` identifies `GitHub.copilot-chat` 0.68.0. Copilot Chat has been [built in since 1.116](https://code.visualstudio.com/updates/v1_116#_github-copilot-is-now-builtin); checking only the user extensions directory or the old standalone Marketplace listing misses this component.

Record release channel, editor/server version, bundled or overriding extension version, session harness and actual MCP initialization separately. Local package metadata establishes installation, not the protocol negotiated by a previous chat. See the [dated version supplement](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md) for exact paths and source boundaries. The earlier “versions not captured” statement describes the transcript-only stage.

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
computed from the current clock. See the [acceptance record](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)
for the 3-run behavior matrix and remaining limits.

### Reading mutation results and refreshing Host tool definitions (v3.8.1)

Both `execute_mutation_skill` and `request_mutation_approval` independently carry the same packaged result rules because
some Hosts, including Copilot, do not pass `outputSchema` descriptions to the
model. First check the result's target, Skill, phase and required-field validity; only for a valid result read `execution_outcome`, not `success`. A malformed required field such as `success="false"` leaves execution unconfirmed even when the payload claims committed. If actual rowcount is absent, report it as unreported instead of borrowing an estimate or another request's count. Treat an error without
`execution_outcome` as unknown; never retry or switch entry points without a
new user decision. Replay checks can give recorded results to an Agent in the
prompt, but that is not the same as the tool channel and should be reported as
such.

After changing tool descriptions, restarting the server was not enough in the
tested VS Code build. Run **MCP: Reset Cached Tools**, then make one tool call so
the Host lists tools again, and confirm the new text reached the model (for
example, ask a subagent to quote it) before behavior testing.

### Per-connection read policy in server instructions (v3.8.1)

Server instructions list each connection's configured read state, scope type
and UNION policy, plus the rule that FROM subqueries are rejected (use a CTE).
This reached Copilot's main Agent and subagents without any extra call; MCP
Prompts such as `sql_assistant` are user-invoked in Copilot and are not a
reliable delivery path. Instructions are built at startup, so restart and
refresh tool definitions after configuration changes. Compare UNION-disabled
and UNION-allowed connections when evaluating SQL planning, and use tables
larger than the 100-row result cap so that merging truncated output is visible.

### Real tool-channel result checks (v3.8.1)

Replaying results in a prompt does not show how an Agent reads a real tool
result. Use a dedicated local database and connection, approve every execute
separately, and have a fresh subagent run `confirm=true` and report. Useful
real cases are a normal commit, a consumed or invalid token (rejected before
execution), and a row changed between preview and execute (`rolled_back`).
To test reports after a decline, change the row after preview so that a
statement about current data can be checked. After a restart, server
instructions were once stale for the first call while tool descriptions were
not, so confirm both before testing.

### October 12 review evidence and completed refresh

The [final review](../validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md) separates fresh source/wheel stdio verification, native GPT-6 Luna tool calls and simulated-result replays. A replay that supplies only the MRTR description proves that description is independently useful; it does not prove that a native Host actually hid other tools or rendered approval UI. Use a fresh agent context per critical replay, preserve failures, and count calls and token usage from traces rather than self-reported totals. Compare performance only with matched tasks, models and Hosts.

The maintainer has restarted the resident service. Its actual description now matches final source and contains `first check validity` and `payload claims committed; execution is unconfirmed`. Interpretation checks using current metadata passed 3/3 each; native index/preview tasks passed 3/3 with no execution. Complete recovery routes were correct 2/3, with one omitted confirmed step corrected only on follow-up; preserve that first failure. The actual pending-to-shipped preview was rejected. Category filters select business groups, not query/mutation type; two empty category=mutation searches are included in observed costs. The final package already passes modern and legacy stdio enumeration, including both optional write descriptions under temporary test configuration. Keep production MRTR disabled if that is its configured policy. No further write to existing orders is needed for this refresh check.

## Read failure contract (v3.8.1, October 13)

For raw query and Query Skill SQL/policy failures, inspect structured_content.success and error_code, not only the MCP isError flag. An ordinary business failure can have isError=false and success=false. Database error text is fixed and safe; policy errors can describe configured table scope. hint is optional and does not authorize an action. Unknown-column/function/incomplete-SQL errors now carry distinct categories. Parameter, target, Skill scope and readiness errors may remain ToolErrors.

Python adapter callers receive list rows or DatabaseQueryError; SQL validators return PolicyDecision. Update current callers directly. The unreleased project excludes hypothetical old env/launch/SDK compatibility from this round. After server changes, restart and refresh the actual Host tool cache before native behavior comparison. See [acceptance and evidence](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md).

## Evidence recording profiles (October 14, 2026)

Keep historical records unchanged. New manifests identify source/environment, recording level, omissions and cleanup. Store captured raw logs compressed, metadata once per phase/protocol, and reference its digest from the ordered case records. Application-level inputs/content/structuredContent/isError/meta and timestamps are not complete JSON-RPC byte captures; protocol debugging may require IDs, notifications and original frames. Model-cost trials additionally retain the full task, all actual model-visible discovery/instructions/results, public answers and provider usage/cache categories, including discovery for unused tools. Exclude secrets and internal model reasoning, and state what was omitted. Compression and deduplication preserve collected information; they cannot restore information never recorded.

## October 14 CTE/cost/SQLGlot probes

Use scripts/review_v381/measure_policy.py and measure_client.py with explicit --source/--stage; freeze the before source before editing. --mysql reads the configured test orders and safe version/settings only; lock/delay calls are never run in native truth. Private SQLite covers unusual identifiers and both actual Client protocols. Record exploratory overlapping runs separately; serialize final A/B/A after regression, distinguish policy time, metadata/text/structured sizes and model usage. SQLGlot fetch_sqlglot.py pins 30.22.0, verifies its official wheel, and only extracts to /tmp; verify_sqlglot.py does not authorize or rewrite production SQL.

Subagent tools must be checked before counting model trials. Initial missing-tool attempts are retained; task-local required startup subsequently yielded six passed native CLI A/B tasks. Do not mix failure attempts, xhigh peers and medium CLI profiles or claim billing savings. Full frames are additional protocol evidence, not inferred from application results. See [acceptance](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md).

## Final quoted-identity acceptance (October 14, 2026)

The complete pending patch now passes 1114 tests with four optional MySQL skips, clean type/prompt checks and 22 installed-wheel stdio calls across both protocols. Twenty-five new regressions verify native SQLite identity for whitespace and quoted delimiters, including raw/Skill discovery/readiness/execution parity. After the final maintainer restart, 11/11 primary Host native checks passed; the old-policy probe is retained separately in the [final supplement](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md#提交前完整复核与补修2026-10-14). Earlier model usage remains attributed to its tested source.


## October 15 structured relation and revalidation checks

The latest source adds 48 cases: a qualified main.orders grant must refuse a distinct literal "main.orders" table, current-schema raw/Skill/metadata must agree, other schemas must be unverified rather than missing, and post-token validate exceptions must return validation_failed/not_executed with consumed-token metadata, zero writes and replay refusal. Full regression: 1162 passed/four skipped; 36 non-editable installed stdio calls and 12 real MySQL read-only calls passed. Final primary Host acceptance passed 18/18 native read-only checks after the maintainer restart; earlier mismatch evidence remains separate.

Keep independent Client/install/live snapshots separate from the resident Host and dated model trials. legacy Client can expose no initialize_result; record the protocol as unobserved rather than infer it. New public evidence includes redacted application results and compressed logs, not full transport frames. [Current acceptance and manifest](../validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md).

## October 15 schema-binding acceptance

For sample/exact counts, use a private server connection with main.orders=7 and temp.orders=99/100; verify the SQL explicitly selects main and count agrees with main columns. Repeat with a temp view and with main absent while temp/aux exists. Qualified raw refusal alone does not cover generated metadata SQL. A second fixture uses an authorized main view: verify discovery, detail and execution, plus dotted-name false matches. Validate malformed Mutation returns both before token issuance and after token consumption; verify safe result, no write and replay refusal.

The installed-wheel fixture bootstrap establishes its private temporary object in the serving connection; the product handlers are unchanged. Current batch: 1210 full passes/four skips, 60 installed stdio and 18 real MySQL read-only calls passed; 20/20 native checks on existing configured read paths passed after the maintainer restart. This Host disables sample/table_summary and has no view/failing-validator fixture, so those cases retain matched-source isolated/wheel evidence; native checks do not attest loaded code-object hashes. Earlier native 18/18 retains its prior-source attribution. Application records are not complete JSON-RPC frames; see [evidence](../validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md).


## October 17 view-read and explanation regression

Use `scripts/validation/read_boundaries.py --output <new>.json.gz` with an independently installed wheel interpreter. It starts real child stdio in both Client modes, uses automatically cleaned SQLite fixtures and harmless counter UDFs, and checks view reads, unknown estimates, normal metadata, plan Skills, DML/REPLACE explanations and unchanged data. `--source <frozen-src> --expect before` replays the preserved pre-repair v3.8.2 source. Include direct-base and mixed-root refusal controls when accepting source-less view-count callbacks. An EXPLAIN QUERY PLAN DELETE can correctly return an empty plan: check success/scope/state, not a fixed opcode layout or nonempty output. Keep read-only CLI config checks and installed resource hashes separate from resident Host and model task evidence. See [the repair report](../validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md).

The October 17 maintainer restart is verified by 28 native calls meeting expectations (including twelve expected refusals), matching text/structured payloads and unchanged full-row snapshots. This Host lacks sample/table_summary; do not relabel installed view/UDF coverage as native. Parent pre-restart checkpoints remain sealed, with current status appended in the separate resident supplement. No fresh full model trial or cost baseline is inferred.

## v3.8.2 semantic/lifecycle acceptance

Use `scripts/validation/semantics_matrix.py --output <new>.json.gz` for independent SQLite fixture truth; add `--mysql-alias <explicit-test-alias>` only with authorization for private SESSION/temporary fixtures. The script neither changes global modes nor writes existing business data. `mysql_sessions.py` tests private pool lifecycle with the same restriction. Other MySQL case settings/MariaDB remain unmeasured without independent instances.

Run `semantics_cost.py --source <frozen-src-or-current-src> --config <toml> --stage <A1/B/A2> --output <new>.json.gz` in separate sequential processes with no concurrent heavy tests/builds. Record drift and startup separately; decoded Client content is not complete protocol frames, and characters are not model tokens. `installed_semantics.py --source <src> --output <new>.json.gz` checks explicit source; omit --source with an outside-repository wheel interpreter. It uses private temporary databases, both stdio protocols, scoped metadata and real temp/view fixtures, including IS/ESCAPE operands, completed-predicate COLLATE/arithmetic continuations and bound Query Skills. Preserve interrupted/failed runs and use a fresh path instead of overwriting evidence.

After source changes, let the maintainer restart the actual Host service. Verify current behavior on a named test connection before attributing results to v3.8.2; validate a fresh Luna test agent's actual MCP call separately. Full task trials use frozen independent truth and fixed follow-ups; prior-source results are not current model acceptance. The initial restart passed ten canaries and all 12 frozen trials completed (11/12 fixed business checks). Preserve the currency-ranking failure and recovered CTE-count refusal. The latter is repaired and final post-restart native checks pass 5/5. Three fresh two-turn sales trials retain one first-turn namespace typo: all 14 actual MCP calls succeed, but only 2/3 trials complete both explicit business goals. Strict numeric coverage is recorded separately (1/3, including an optional-field mismatch). No fresh model pass is inferred from a tool catalog or self-report. See the [current report and final follow-up](../validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md).


### SQLite trigger and dialect plan follow-up (October 17)

Run `scripts/validation/sqlite_plans.py --output <fresh>.json.gz` with the independent wheel interpreter. It starts real child stdio in both modes and checks trigger reads/counts, view-only grants, WITH REPLACE, UPDATE OR, Skill discovery/detail/readiness/execution, actual-DML refusals, full persistent rows and serving-connection total_changes. `--source <frozen-src> --expect before` records the earlier failures; skipped-before Skills mean different total call counts, not a cost comparison. Use `sqlite_plan_cost.py --source <src> --stage A1/B/A2 --output <fresh>.json.gz` sequentially after heavy checks; successful-after versus failed-before plans are not equal work or model tokens. Keep main/temp/aux/source-role ambiguity refused. See [decisions, costs and scoped resident acceptance](../validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md).

Use `scripts/validation/sqlite_trigger_ctes.py --source <src> --output <fresh>.json.gz` for trigger-local CTEs; omit --source with the independent wheel interpreter. Both real stdio protocols cover constant/materialized CTE counts, WHEN, select-only/nested triggers, repeated names, raw/Skill readiness/execution, refusal controls and unchanged serving-connection total_changes. Extend scope/name regressions with schema collisions and catalog replacement. `sqlite_plan_cost.py` now includes trigger_cte_count; run A/B/A serially and separate recovered functionality from equal-work overhead. See the [supplement](../validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md).

The same trigger script now includes keyword-shaped WHEN columns, CASE/subquery controls, a denied WHEN dependency and a bound WHEN plan Skill. Verify original conditions and every body fragment; do not repair delimiter ambiguity by skipping the condition or disabling the authorizer. [Latest validation](../validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md).

For complete native Agent acceptance, freeze prompts and independent read-only truth before starting fresh trials. Verify one real call in each actual test child, then run both business turns in that same child; a separate preflight agent does not establish its readiness. Keep setup usage separate from business usage, initial refusals separate from final outcomes, and unavailable trials in the denominator. The [post-restart sales trials](../validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md#重启后的完整-agent-业务任务) preserve three complete trials, one unsupported-FROM refusal/recovery and earlier Host failures. Explicitly attribute phases from public scripted input boundaries when a base prompt is prepended; do not silently trust a collector that recognizes only exact prompt text. Canary-warmed contexts differ from earlier unprepared tasks and do not form a historical availability/cost A/B.

For historical-source comparisons, require an existing source directory, verify the imported package's actual `__file__`, and compare resource hashes with the sealed snapshot. A deleted temporary source can silently fall back to an editable installation. Restore sealed source archives into a fresh directory, keep failed preliminary records separately, and never overwrite an earlier evidence manifest. The trigger-local CTE restart supplement retains one caught example and the separately verified rerun.

Before future full Agent trials, verify a real SQL MCP call in the actual trial context. A separate preflight Agent or another successful trial cannot establish that context's client availability. Count unavailable trials separately and keep them in the overall outcome; do not retry fresh contexts until only successes remain. Preserve frozen historical conditions and avoid inferring a cache root cause from a later success. See the [current adjacent audit](../validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md).

Build backend packages need not be runtime dependencies. If the development venv lacks hatchling, use the normal isolated `uv build`; with an existing complete cache, `uv build --offline --cache-dir <existing-cache> --out-dir <batch-dist>` is reproducible without downloading dependencies. An empty cache is not the existing cache. Install the built wheel with `uv pip install --offline --cache-dir <existing-cache> --no-deps --force-reinstall --python <isolated-python> <wheel>` into the independent validation environment, then compare all packaged resources. Temporary uv/cache paths from earlier sessions are not permanent installations or a requirement for end users.

An offline build may reuse already-cached backend distributions with `python -m build --no-isolation`; record the backend versions. A normal wheel installation in a fresh interpreter may explicitly reuse a frozen dependency directory: assert the tested package comes from that interpreter, reject editable import hooks and compare packaged resources. Describe this as dependency reuse, not fresh dependency resolution. The WHEN batch records this path and the interrupted/timeout uv downloads separately.
