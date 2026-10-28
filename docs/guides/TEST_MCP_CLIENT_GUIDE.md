# MCP Client verification · v3.8

> October 22, 2026: use the [portable contract entry points](../../scripts/validation/README.md) for deterministic and explicit live release checks. Reload the resident server after runtime/configuration changes before attributing native results to new source. The [October 14 CTE checks](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md#cte-依赖与实际名称规则修复2026-10-14) and earlier model trials remain dated snapshots.

This guide uses the installed `sql_safety_executor` package and explicit TOML
configuration. Run repository scripts from the repository root after
`uv sync --frozen --group dev`. The previous script-based instructions remain in
the [v3.7 historical guide](TEST_MCP_CLIENT_GUIDE_v3_7.md).

## Offline checks

### Correlated middleware events (October 28)

Use `tests/test_telemetry_lifecycle.py` for pending-call entry, cancellation, paired sampling, duplicate IDs/concurrency, clock jumps, log failures and both stdio protocols across process restarts. Filter `tool_call_finished` when counting outcomes; old mixed-log records may use `row.get("event", "tool_call_finished")`. Pair by `(server_instance_id, call_id)`, not by framework session/request digests alone. Wall timestamps align records; monotonic `execution_ms` excludes Host review and final-event writing. A missing entry/finish is an observation gap, not a business outcome. Installed tests and maintainer-restarted resident validation are distinct. The [acceptance and stopping criteria](../validation/v3.8/V3_8_2_HOST_REQUEST_CORRELATION_2026_10_28_ZH.md) retain the unresolved reviewer cause and avoid new model trials without incremental evidence.

### Strict expiry-field candidate screening (October 28)

The [bounded screen](../validation/v3.8/V3_8_2_EXPIRY_FIELD_SCREEN_2026_10_28_ZH.md) freezes one field-description factor and exactly six supplied-record sessions/24 answers. Match the observed declaration-only exposure without claiming it is every Host's complete input. Both conditions complete8/12; fewer unsupported expiry claims do not offset omitted deadlines, so the candidate is not adopted. This strict gate rejects a tie, unlike earlier explicit-contract clarification screens. Keep required facts and semantic alternatives, true server expiry rejection, valid committed outcomes and response-loss uncertainty; do not require a fixed disclaimer. A failed screen cancels its conditional engineering/native stages rather than creating a pending restart. Zero tool calls mean native routing, recovery and Host timeout behavior were not tested; report usage/cache and public windows without a speed or token-saving claim.

### Retrospective expiry-date checks (October 28)

The [P1 public-trace review](../validation/v3.8/V3_8_2_EXPIRY_DATE_REVIEW_2026_10_28_ZH.md) normalizes the returned deadline and logged answer to the explicitly supplied environment zone. Do not compare a UTC calendar date directly with a local current_date. This exposes an unsupported claim, not the model's internal cause, synchronized clocks or runtime token validity. P2/P3 have the same cross-day condition but different longer-rule exposure; they are contextual contrasts, not a causal experiment. Keep the original5/6 score. The review makes no new MCP/model calls, and any future equivalent-time representation replay must retain its constructed-record identity.

### Owner-restarted natural expiry/transition replication (October 28)

The [native supplement](../validation/v3.8/V3_8_2_EXPIRY_TRANSITION_RESTART_2026_10_28_ZH.md) closes freshness and all six frozen two-turn attempts, with18 actual Luna-medium contexts. State/action checks6/6 and deadline reporting3/3 do not hide full interpretation5/6: one task publicly displayed the new field guidance yet inferred expiry from dates. Visible text is evidence of exposure, not complete provider input or guaranteed compliance; do not explain that failure solely by missing disclosure. Preserve its failed conclusion and the independently reproduced/recovered bad-column query. Business25 requests/1191028 tokens include all paths, not an efficiency claim. No new runtime change or restart is required; Host latency remains open without a new causal phase observation.

### Expiry-field and demo-lifecycle visibility (October 28)

The [metadata checkpoint](../validation/v3.8/V3_8_2_EXPIRY_TRANSITION_GUIDANCE_2026_10_28_ZH.md) compares the actual registered output field independently from the demo Skill description. Where a Host exposes output-schema descriptions, the existing expiry field offers an additional reporting surface; this is not a guarantee that a model receives every rule. Preserve the independently loaded write descriptions for Hosts that omit that schema. Report returned time and zone or missing expiry; a timestamp never establishes current token validity.

Check compact/summary/full catalogs and full Skill detail against all36 transitions through real previews and an independent database observer. The minimal execution detail intentionally omits the description; keep its existing shape. The generated static overview is only a100-character excerpt. Source, wheel and metadata checks do not prove natural-task improvement: after one owner restart, run the six frozen fresh natural-discovery tasks without forcing full definitions, coaching or replacing failures. Retain the external natural batch's omissions and costs; combined model validation does not isolate each edit's effect. Host diagnosis resumes only with new correlated phase evidence or stable recurrence, not a new timeout setting.

### Agent result interpretation and timing boundaries (October 23–27)

Freeze the actual model/effort, installed resources, data/configuration hashes,
observable Host definitions, task wording, graders and held-out tasks before A/B.
Capture the chain from packaged text through generated definitions and Host
exposure to actual returns. Missing full model-received definitions remain an
observation gap; a model quoting a rule does not prove complete delivery.

Grade factual truth and evidence-supported statements separately. Preview-only
cancellation requires neither a fixed disclaimer nor an extra read. Pair true
empty results with first-row character truncation, complete output with bounded
SQL, and valid write outcomes with missing/malformed/wrong-target records.
total_rows counts fetched rows for that SQL, not all matching database records.
Supplied-record replays supplement native tasks and must not be reported as
real protocol outcomes or database writes. Preserve failures and valid alternative
paths; evaluate each exploration call by information gained.

Same-configuration A/A estimates repeat variability, not collection overhead.
Use a separate small collection-on/off fixture for overhead; mark components
unquantified when they cannot be separated. execution_ms ends before result-object
construction/serialization validation, and some tools start it after initial
checks/logging. Client time minus execution_ms is only time outside that window,
not network time. Use each process's own monotonic clock for durations, associate
requests by ID, and report concurrent unions separately from task sums/batch wall
time. Keep unobservable Host stages unattributed. The [current report](../validation/v3.8/V3_8_2_AGENT_INTERPRETATION_2026_10_23_ZH.md)
retains A/A variation and incomplete candidate replay. The [owner-restarted follow-up](../validation/v3.8/V3_8_2_AGENT_INTERPRETATION_RESTART_2026_10_25_ZH.md)
checks six matched/two held-out native tasks; this does not close the distinct
replay omissions or prove model superiority. Preserve negative/out-of-order public
timestamp deltas and withhold elapsed comparisons; never repair them with zero or
absolute values. Reconstructed application counts must recognize metadata printed
as bare JSON text as well as structured results. Keep the original collection and
a reviewed correction, and recheck the baseline instead of silently changing its
denominator.

The [October 27 follow-up](../validation/v3.8/V3_8_2_AGENT_EVIDENCE_FOLLOWUP_2026_10_27_ZH.md)
adds a bounded replay screen for preserving payload claims alongside invalid or
mismatched requested-operation conclusions. This does not rewrite historical
grades or constitute native tool outcomes. Keep temporal and unit-source checks
separate from SQL replay: current data can hide equality-boundary mistakes, and a
numeric amount alone does not establish currency. For the declared rental task,
use the explicit interval [start, return); other tasks must declare their own
convention. Run the portable checks without a private database:

```bash
uv run --frozen python scripts/validation/agent_task_boundaries.py
uv run --frozen pytest -q tests/test_agent_evidence.py
```

`agent_evidence.application_observations()` links yielded exec/wait returns and
preserves identical result slots. Its output is observations, **not request
counts**; use a separate invocation ledger or expanded call-code audit. Prefer
structured content to its text duplicate, but never deduplicate distinct calls by
payload. The helper neither reads raw session logs nor redacts secrets; use only
reviewed public events. Actual model/effort still needs per-turn verification.

Discovery grouping can reduce repeated display text while retaining complete
rules, but full text can also exceed a previously sliced display. Character
comparisons do not establish token, success or latency gains. Host-local handler
timings confirm some historical long waits; code-mode duration and audit-end
timestamps do not identify approval, dispatch, server entry or database time.
Never subtract nested windows as disjoint phases. New wording requires owner
restart/native verification independently of replay and installed checks. The
[October 27 native supplement](../validation/v3.8/V3_8_2_AGENT_EVIDENCE_RESTART_2026_10_27_ZH.md)
closes that wording's refresh check: preview/cancellation passes; finance numbers
and declared time predicates pass, while unsupported currency symbols remain.
Report full semantic completion as1/2, separately from successful calls and SQL
fidelity. Public discovery in one child does not prove another child received the
same complete definitions. No malformed native payload or confirmed write was
tested; the supplied-record screen retains its distinct scope.

### Bounded Host timing and repeated-discovery diagnostics (October 28)

The [retrospective follow-up](../validation/v3.8/V3_8_2_HOST_DISCOVERY_FOLLOWUP_2026_10_28_ZH.md)
queries only exact original threads/call IDs and a bounded read-only log window.
Export whitelisted numeric fields, not raw review transcripts or hidden reasoning.
An exec may yield and multiple waits may observe one request: those outer timing
windows are not separate review/SQL phases and must not be added as such. Missing
best-effort audit records do not prove a request never reached the server.
An approval deadline does not establish that MCP tool_timeout_sec is its remedy.

For definition reuse, compare identical visible tool descriptions within one
thread, keeping every first full and changed definition. Restart this reasoning
for another session or uncertain context retention; this is not a general cache
of all protocol metadata. In nine existing tasks,27 displays contain two exact
repeats; omitting them changes only15554 JSON characters, not the32 actual
business requests/results or observed provider usage. Five renderer controls are
not product regressions or new Agent trials. Grade database exploration by new
information; useful schema recovery and compact-to-parameter detail remain valid.

### Discovery to actual preview (October 28)

The [single-factor routing checkpoint](../validation/v3.8/V3_8_2_PREVIEW_ROUTING_2026_10_28_ZH.md)
clarifies list_skills: a directory entry or verbal next step is not a server
preview. For a requested mutation proposal, use an executable matching Skill,
schema-valid params and the same connection with confirm=false, then report the
actual result. An explanation-only request must not silently become a proposal;
actual execution remains separately approved. Full params do not need a detail
call; compact discovery may still need one. Do not impose a single exploration
path or add execution approval before an already requested preview.

Three new native baselines choose correctly; this does not erase the earlier
missing preview or establish its sole cause. Candidate source/normal-wheel
metadata changes only the list description, with70 focused regressions and dual
stdio checks passing. The [separate native supplement](../validation/v3.8/V3_8_2_PREVIEW_ROUTING_RESTART_2026_10_28_ZH.md)
closes all three candidate two-turn tasks after verifying actual-child canaries
and current definitions: routing3/3, business completion2/3. One correctly
requested preview hits the Host automatic approval-review deadline, without an
application result; the other actual preview and explanation-only control pass.
The full completion gate remains unmet. Preserve this failure without retrying
the frozen trial; do not invent a server unknown outcome or infer an unsafe
action from the Host timeout. Keep routing, expiry
wording, definition reuse and costs separately scored; fewer calls from an
incomplete task are not an efficiency benefit. Historical full-suite/type gates
retain their original scope and were not rerun for this text-only factor.

### Explicit expiry interpretation and payment scope (October 28)

The [separate clarification and matrix](../validation/v3.8/V3_8_2_EXPIRY_SCOPE_2026_10_28_ZH.md)
screens the ordinary-write wording with six supplied-record sessions: A/B each
16/16, not native improvement evidence. A returned timestamp is not an execution
validity decision. Preserve an explicit server expiry rejection and allow a new
preview the user explicitly requested; do not start one automatically. Keep
historical natural failures rather than rewriting them as fixed.

Run the portable payment oracle via
`python scripts/validation/agent_task_boundaries.py`. Verify payment participation
separately from active-rental time, count rentals separately from payments, and
include zero/refunds and both month boundaries. Multiple valid joins are allowed;
known-bad business SQL should still execute faithfully. The inline constant CTE
requires existing UNION permission: initial rich_mutation_sqlite denials were
correct, and later checks used permitted analytics_rich_sqlite/sakila_mysql
without changing grants. Independent DBAPI and real source/wheel dual-protocol
checks do not certify native Agent behavior. Three prospective native two-turn
tasks were pending owner restart at that checkpoint, with actual-child canaries,
complete first-use disclosure, independent truth, fixed stops and separate usage.

The [post-restart native supplement](../validation/v3.8/V3_8_2_EXPIRY_SCOPE_RESTART_2026_10_28_ZH.md)
completes those three tasks: business/interpretation2/3, full frozen protocol1/3,
action boundaries3/3. Actual preview expiry interpretation is1/1, but requested
preview completion is1/2; never count a missing tool call as successful expiry
guidance. Correct payment results do not erase two repeated definition displays.
Separate business truth, result fidelity and protocol adherence; retain failures
without coaching or replacing trials. Four successful reads independently replay
identically; no paired native baseline supports speed/token improvement. Current
refresh is closed, without further runtime edits or repeat engineering gates.

### Lossless discovery and child readiness (October 28)

The subsequent [lossless discovery experiment](../validation/v3.8/V3_8_2_DISCOVERY_AB_2026_10_28_ZH.md)
compares full per-tool versus shared-prefix displays under the same first-use
complete-disclosure protocol. Exact reconstruction and visible rules do not
prove a callable client: both first-pair canaries fail at the Host boundary.
Retain these availability failures and their costs; eight frozen trials remain
unstarted until owner reconnection. Do not replace failed sessions, convert
175 renderer self-checks into product test counts, or claim task-token savings
from character differences. This is a Host-side experiment, not a production
tool-loading API, new cache or removal of independent tool instructions.

The separate [owner-reconnected continuation](../validation/v3.8/V3_8_2_DISCOVERY_AB_RESTART_2026_10_28_ZH.md)
finishes those eight full tasks with actual-child canaries and24 independent read
replays. Current-data/actions8/8 does not imply complete interpretation: all four
previews show expiry but incorrectly claim it has passed, even with full rules
visible. Preserve this failure and a separate post-hoc LEFT JOIN payment-scope
counterexample. Do not derive correct SQL semantics solely from current numbers.
Shared-prefix-once means once per display batch; single-tool batches add wrapping
characters. Observed token/call differences include different SQL and recoveries,
not a causal format gain or evidence for a new product default. No forced extra
product call, automatic re-preview, token revocation or clock-based validity claim.

### Unit sources and preview expiry (October 27)

The [local clarification](../validation/v3.8/V3_8_2_UNITS_EXPIRY_2026_10_27_ZH.md)
adds sourced-unit guidance to each read tool and explicit expiry presentation to
ordinary-write previews. Keep known currencies, physical units and justified
derived percentages; an unsupported unit is omitted, not discovered through an
extra mandatory query. For a valid preview, report the returned expiry with its
timezone, or state it was not reported. Do not infer current token validity or
expose the bearer handle. Cancellation does not require repeating a proposal.

Freeze positive/negative cases before testing. Explicit supplied-record screens
can pass even while natural native tasks still omit a rule: units tie in this
batch. Preserve both results, the expiry false-validity assertion and exact costs.
The [October 28 native supplement](../validation/v3.8/V3_8_2_UNITS_EXPIRY_RESTART_2026_10_28_ZH.md)
verifies refreshed definitions and all three actual-child canaries. Two full
business tasks and a separate display probe complete: finance units/CNY/70% pass,
but preview expiry is omitted and cancellation leaves its old state observation
unqualified. Strict business1/2 and display1/1; do not grade unchanged database
truth as contemporaneous evidence for a model claim. Parent-rule presence does
not prove child visibility: discovery output was clipped and tail excerpts miss
the expiry paragraph. No causal, stable improvement, timing or billing claim.

### Portable contracts and explicit release gate (October 22)

Use the [portable validation entry points](../../scripts/validation/README.md)
for deterministic CI versus explicit live acceptance. `release_gate.py --profile
fast --source src --output <new-directory>` runs pytest with actual skip counts;
successful fast checks still leave live MySQL **UNVERIFIED**, not release-ready.
The release profile requires `--config/--alias` or `--mysql-env`, uses owned
temporary schemas, runs both backend/application contracts, and requires the four
optional MySQL cases to actually pass with no skips. Setup failure cannot turn
into a passing integration gate. Neither profile restarts the active Host.

Reports include actual runtime/dependency identity, not just product hashes.
Dependency/validation changes also trigger the separate installed-wheel/MySQL CI
workflow; manual release dispatch remains required when applicable. Baseline
comparison only plans rechecks and never automatically reuses previous results.
No model-token/performance conclusion follows from this infrastructure change.

### October 20 read/binding and column follow-up

The durable [read/managed follow-up runner](../../scripts/validation/read_plan_followups.py)
resolves its source/Skill/output paths and starts disposable SQLite child services.
Use `--help` for required arguments. It runs both Client modes and both configured
managed classifiers, recording 84 calls per source or installed package: discovery,
tail-comment reads/Skills, literal versus actual bindings, write/restore/replay,
rollback, complete schema projections and continued policy refusals. Its writes
are confined to its temporary fixture; do not substitute configured business data.

This checkpoint has **3003 full-suite passes/four optional skips**, then **two
additional session-binding passes**, clean type/source-and-installed prompt checks,
84 source/84 wheel calls and six installed MySQL calls. Seventy-seven package
resources and the wheel digest are verified. Real MySQL checks separately compare
five catalogs and sixteen isolated session modes using original SQL, with orders
unchanged. Recipes, exact inputs, failed attempts, paired costs and evidence are
in the [record](../validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md).
Reuse the documented verified offline build cache/frozen environment; no new
runtime package or global installation is required. Temporary paths are not a
persistent installation. Application results are not complete wire frames.

The operation-local analysis-reuse study is a direct-handler prototype, not
production code or model acceptance. Earlier complete Agent trials retain their
source scope. After the owner restart, 34/34 scoped native checks pass, with exact MySQL
metadata/report truth, unconfirmed previews and unchanged data. The separate
[resident supplement](../validation/v3.8/v382_read_plan_repair_2026_10_20/resident_restart/README.md)
retains fixture/mode limits and preserves the parent pending seals.

The subsequent [complete Agent evaluation](../validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_20_ZH.md)
adds fifteen actual Luna-medium two-turn trials and sixty native SQL replays on
the same resources, with same-prompt historical usage and increases retained.
Check public per-turn model/effort in addition to each child canary: three
close/resume recoveries restored SQL tools but changed the actual model to Sol
ultra. Keep those diagnostics/costs separate, qualify three fresh same-model
replacements, and never infer an isolated guidance effect from task compliance.

### Base offline commands

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


### Read capability and scope checks (October 19, 2026)

Run `scripts/validation/read_capabilities.py --source <absolute-src> --output <fresh>.json.gz`, or omit `--source` with the independent wheel interpreter. Both actual child-stdio protocols use disposable fixtures for derived views, known JSON calls, FTS root-only grants, sample/exact/estimated metadata, Skill disclosure/readiness/execution, default/main/temp/aux scope, catalog counts and non-executing trigger plans. Restricted-function counters and the persistent database hash must stay unchanged. Records are application content/structured results, not full protocol frames or model usage. Final source/package/native attribution and complete Luna tasks are in the [batch record](../validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md).

FTS validation must include fresh and metadata-warmed connections, reconnection/schema replacement, internal/external-content/contentless storage, direct ungranted shadow/content reads and mixed queries. An internal PRAGMA source parameter is not sufficient provenance. SQLite JSON module READs bind to main even inside a temp/attached view; verify actual callback identity rather than assigning view ownership. Do not disable authorizer or expand configured grants silently to make a trial pass. The normal all-mode scope is now the configured default schema; explicit cross-schema allowlists remain supported.


## Metadata projection validation (v3.8.2)

Run the independent temporary-fixture child-stdio check after changes to table discovery, estimates or transport binding:

~~~bash
.venv-v38/bin/python scripts/validation/metadata_projection.py --source "$PWD/src" --output /tmp/metadata-source-unique.json.gz
~~~

For wheel validation, use the independent installed interpreter, omit --source and choose a new output path. The script verifies both protocols, counts/order/truncation, statistics/no-statistics, empty projections, Unicode/colon names, and unchanged temporary database hashes. Pair it with read_capabilities.py for view/JSON/FTS guarded-read controls. Tests in test_metadata_cost_v382.py check actual work and failure branches. These are application-result checks, not full protocol frames or complex model-task evidence. Performance stages must run serially without tests/builds in parallel; source/package, resident restart and model usage retain separate attribution. [Decisions and current acceptance](../validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md).


## FTS cached-content and qualified-call validation (v3.8.2)

~~~bash
.venv-v38/bin/python scripts/validation/fts_boundaries.py --source "$PWD/src" --output /tmp/fts-source-unique.json.gz
~~~

Use the independent installed interpreter without --source for wheel verification. Both real child-stdio protocols cover cold, column-only warm and trusted full-projection warm states; raw query, Query Skill, sample, exact count and descriptor estimates; normal derived content views, aux MATCH/table-call/IN equivalence, builtin qualification refusal and unchanged direct grants/all-mode scope. The deliberately harmless SLEEP replacement must have zero additional calls during guarded operations. Record its intentional trusted-warm call separately; descriptor row_count=null can be the expected unavailable estimate. All four generated database hashes must remain unchanged. Pair this with read_capabilities.py and metadata_projection.py, retain raw application results and source hashes, and do not relabel these checks as full protocol capture or complex model trials. New baseline failures must be preserved. Whole-definition checks deliberately refuse unused restricted view expressions; generated-column/UDF trust is a separate existing boundary. [Repair and current status](../validation/v3.8/V3_8_2_FTS_FOLLOWUPS_2026_10_20_ZH.md).

## Managed-plan parser migration checks (October 20)

Run `scripts/validation/managed_parser.py --source /absolute/repository/src --skills /absolute/repository/skills --output /fresh/results.json.gz` with the repository interpreter. For an independently installed wheel, use that interpreter and omit `--source`. The script creates disposable SQLite databases, tests both configured parsers and both Client modes, and records discovery/detail, preview, committed update/restoration, one-use token rejection, row-count rollback and final database truth (40 calls per source/package run). It performs no configured database writes. Results are application records, not full protocol frames or model token evidence.

Use `config check/explain` to verify the selector. Preserve original SQL and named-bind assertions, target-mode rejection before preview and again after token consumption, and missing-COMMIT evidence tests. Do not replace DB truth with AST acceptance or label isolated lifecycles as complete model tasks. Native Host acceptance requires an owner restart; configured writes still require separate approval. See the [frozen corpus and validation scope](../validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).

## Managed classification reuse checks (October 20)

Use `tests/test_managed_classification_reuse_v382.py` for readiness isolation, exact SQL/context/parser keys, bounded eviction, instance isolation, cleanup, concurrent pure misses and live execution gates after warming. Context-change/failure confirmations must consume their token, return not_executed and refuse replay without executing a write. Both parser modes still use the ordinary lifecycle validation script above.

Compare performance against the post-migration 77-resource snapshot, not HEAD or the earlier 76-resource pre-migration archive. Measure readiness-only A1 and final reuse separately, serial A/B/A per protocol, away from tests/builds. Untimed cache hit/miss and context-resolution counts are separate from timed client roundtrips. [Frozen recipes, results and scope](../validation/v3.8/V3_8_2_MANAGED_CLASSIFICATION_REUSE_2026_10_20_ZH.md). No new complete-model or configured-MySQL-write claim follows from fixture lifecycles.

## Dialect comment and NOT checks (October 20)

Use `scripts/validation/comment_modes.py` with the same --source/--skills/--output convention as managed_parser.py. It runs both parser selectors and both protocol modes on disposable SQLite: reviewed comment Query Skill discovery/detail/readiness/execution, exact original managed comment SQL/binds, commit/restoration/replay/rollback, real function/table restrictions and raw DML refusal. Opaque fixture handles are consistently redacted before export. MySQL hint/mode semantics use separately recorded actual-session scalar comparisons and non-executing EXPLAIN; SQLite stdio is not MySQL or complete-model evidence.

Keep full scoped policy tests separate from shape/function-only analysis. Compare against the post-DRR-120 archive; 1513 boundary groups are a synthetic matrix, not business refusal rate. Startup expands from nine to seventeen candidates; measure it separately from warm six-call stdio cycles. [Scope, recipes and limits](../validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md).
### SQLite relation-call names and generated-column metadata

Run `scripts/validation/relation_calls_columns.py --output /fresh/results.json`
with the repository interpreter. For the independent wheel interpreter, pass
`--scope installed` and a separate output path. The script creates only disposable
SQLite/TOML fixtures and records both child-stdio Client modes, 538 tool calls,
420 independent truth comparisons, Skill discovery/detail/execution, generated
column projections, hidden-column counts and refusal controls. It preserves
actual package resource hashes and verifies cleanup; it does not access the
configured databases, measure model tokens or replace resident Host acceptance.
Focused regression is `python -m pytest -q tests/test_relation_calls_columns_v382.py`.
[Decisions, costs and current status](../validation/v3.8/V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md).


### Read-result and conditional-dependency boundaries (2026-10-21)

Run tests/test_read_results_v382.py for actual duplicate labels (case-distinct labels remain valid), tagged BLOB/non-finite values, prefix limits including zero rows, escaping/Unicode, temporal/decimal conventions, and scoped JSON-name readiness. A frozen result_chars=1 file is invalid because even [] needs two compact JSON characters. Pair raw query, Query Skill and sample; check application success/error_code and both text/structured content, not merely MCP isError.

The local repair archive contains a self-contained verify.py driver for the current configured MySQL constant-read alias plus disposable SQLite/Skill fixtures. It accepts a fresh --output and explicit --scope source/installed; independent child stdio and in-process auto/legacy records are separate, including expected readiness refusals. Readiness-off adds no catalog probes; actual unauthorized roots remain refused. Use tests and package checks for aux/TEMP/sample cases absent from the resident Host. No full model task or token comparison is implied. [Contract and evidence](../validation/v3.8/V3_8_2_READ_RESULTS_2026_10_21_ZH.md).

Also test unqualified JSON-name calls with objects only in attached schemas: explicit aux cases or fixtures with main/TEMP shadows do not cover that lookup path. The [DRR-135 assessment](../validation/v3.8/V3_8_2_ATTACHED_JSON_READINESS_2026_10_21_ZH.md) retains 332 source calls, including ordered attachments, quoting/JOIN/IN/CTE, unauthorized roots and same-Skill ATTACH/DETACH. It confirms an open readiness issue, not repair acceptance; no new configuration or grant is required to reproduce it with disposable fixtures.

The subsequent [ordered-observation repair](../validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md) retains that checkpoint and adds 67 regression cases plus final source/normal-wheel each 332 application calls. Cover explicit/resolved state parity, partial catalogs, count/time limits, default-scope controls, live grants and readiness-off. Reuse the private self-contained probe/dynamic drivers with fresh --output and explicit --scope; do not pool intermediate packages or old native/model evidence. DRR-136 was subsequently approved and repaired with fixed main-bound PRAGMA statements. The [repair record](../validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md) adds 57 regressions and six collision fixtures over in-process/child-stdio auto/legacy. Verify full column/index payloads against native PRAGMA truth, generation/hidden projection, quoted/dotted names, WITHOUT ROWID auxiliary rows and all-or-unavailable budgets. Preserve the initialization-timeout log and final retry separately. DRR-135/136 now share 20/20 post-owner-restart native checks on existing aliases; special collision/attached fixtures remain source/package scoped. Preserve the separate resident_restart supplement and parent pending seals; retain application costs separately from model/token claims.


### FTS catalog/statistic sources and cold external-content rowids (DRR-137–139)

Use the repair-batch self-contained `clients.py` with a fresh `--output`, explicit `--scope` and absolute `--source`; omit `--source` under the normal-wheel interpreter. Check main/TEMP/aux table/view collisions, real shadow types and quoted schema/root names; whole-table, nonpartial-index, WITHOUT ROWID and index-only ANALYZE sources; stale/no-stat/10000-limit controls. FTS external-content must be evaluated cold before any trusted warm query, including default/rowid/_rowid_/oid/id. Test declared same-name columns and INTEGER PRIMARY KEY DESC separately; continue rejecting direct base/shadow reads. Compare unchanged fixture hashes and application content/structured output, not full protocol envelopes. Keep aborted fixture scripts, sandbox type/full-test failures and later completed runs separately. Run cost A/B/A serially after tests/builds, distinguish changed wrong/right outputs from equal-work overhead, and request one owner restart only after package checks. [Repair record](../validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md).


## Native SQLite declared-type validation (v3.8.2)

Use `tests/test_sqlite_declared_types_v382.py` and the [repair record](../validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_REPAIR_2026_10_21_ZH.md) with its archived Client/verifier scripts. Compare each type directly with `PRAGMA main.table_xinfo` output: do not apply `or "TEXT"` or infer affinity from stored values. Cover undeclared/TEXT/BLOB/INTEGER/NUMERIC/empty/space/custom/STRICT ANY, CTAS, generated columns, FTS visible versus hidden columns and inherited/expression views. Check describe, optional summary, compact grouped/ungrouped, full schema, raw and Skill results, plus zero expression evaluation and unchanged query counts. Enable summary only in the disposable fixture; configured tool exposure need not change.

The frozen fixture runs46 calls per mode/transport,184 per source or independent normal wheel; in-process and child-stdio auto/legacy output must agree. Use a fresh output path, then check fixture cleanup and unchanged database/configuration hashes. Compact grouping can increase when invented TEXT types disappear; payload characters are not provider tokens. Do not rewrite old normalized-type evidence or count earlier native/model trials as this source. Request one owner restart after the final package checks; keep native existing-alias scope separate from disposable cases.


## Actual PRIMARY identity and member order (DRR-141)

Run `tests/test_primary_key_metadata_v382.py`. Compare SQLite positions directly with fixed table_xinfo, and physical index parts with index_xinfo; repeated parts and gaps are valid. For MySQL, compare KEY_COLUMN_USAGE with independent SHOW INDEX PRIMARY/Seq_in_index. Include reverse composite order, non-null unique without PRIMARY, nullable unique, no key, PRIMARY plus unique, mixed-case column references and decoded special components. Native COLUMN_KEY=PRI is a display flag, never an oracle for actual PRIMARY membership.

The [repair archive](../validation/v3.8/v382_primary_key_metadata_repair_2026_10_21/README.md) includes matrix.py: `--backend sqlite|mysql --stage baseline|source|installed --output /fresh/result.json`. Use the chosen source or normal-wheel interpreter with its declared dependencies. Each backend has13 objects and96 application calls across in-process/stdio auto/legacy. The MySQL helper uses an existing local test alias solely to create an owned random schema, then drops only that schema; confirm fixture authorization before reusing it elsewhere. Never modify existing configured tables or grants for this recipe.

Verify optional positive primary_key_position only on actual members, native display flags unchanged, full/describe/summary positions, compact grouped/ungrouped order and changed grouping, raw/sample/exact values, continued refusals and fixture cleanup. Keep a normal-wheel baseline; do not compare solely against old adapter output. Run serial same-fixture A1/B/A2 after builds/tests, retain all samples and payload changes, and distinguish local costs from model tokens. Freeze existing-alias truth and one restart plan only after package checks; special fixture coverage does not become resident or full-model coverage.


DRR-141 resident follow-up: after the reported restart, native7/12 versus fresh configured CLI12/12 still differs on five PRIMARY-position cases. Keep raw failures and do not substitute the fresh process for resident acceptance. Multiple same-entry processes and a later successful launch do not prove which client/process serves the native tool channel or establish a cache root cause. The owner subsequently restarted and current native12/12 passes; preserve the historical pending [checkpoint](../validation/v3.8/v382_primary_key_metadata_repair_2026_10_21/resident_restart/README.md). MySQL is the server/dialect acceptance target; MariaDB is not a required environment. Retain native SQLite and actual MySQL version/session scope.


The [October21 complete task audit](../validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md) closes latest native12/12 and reruns all fifteen exact historical prompts with actual Luna-medium contexts and independent native truth. Retain calls108→113, business tokens+3.85%, and higher public task wall time; do not attribute the whole model/Host delay to SQL. Separately freeze natural cancellation prompts that do not teach the expected interpretation: three probes retain one initial task omission, one unsupported current-state assertion and ambiguous cancellation language. Preserve first-attempt denominators, extra user reminders and costs; do not replace them with only final success. Keep local fixed-flow A/B/A and diagnostic A/B/B/A separate from provider usage and retain unfavorable samples. No runtime change or new full-suite/build is needed for this documentation-only follow-up.


## SQLite physical write lifecycle (October22, DRR-142/143)

Use `tests/test_sqlite_write_transactions_v382.py` for adapter-level private-file truth and `scripts/validation/sqlite_writes.py --source /absolute/repository/src --output /fresh/source.json.gz` for both in-process/stdio, auto/legacy and SQLGlot/sqlparse full preview-confirm-replay flows. With a normal wheel interpreter, omit --source and run outside editable imports; the script asserts the installed package location. Every write targets its disposable database, never configured business tables. Application records redact tokens and are not full protocol frames or model usage.

Freeze ordinary/CTE/semicolon INSERT/UPDATE/DELETE with/without RETURNING, correct/zero/multiple counts, partial failure and engine-auto-rollback, plus unchanged data after response, token replay and server/cursor cleanup. Check real BEGIN/COMMIT/ROLLBACK traces and independent sqlite3 connections. Include count_changes, direct versus trigger/cascade counts, INSTEAD OF view zero counts, non-DML stale-count prevention, result cancellation/deadline/fetch/close faults and missing physical acknowledgements. Preserve initial fixture/preparation failures separately.

Never substitute logical SQLAlchemy transaction activity, returned-row length or a cached rowcount for physical evidence. Uncertain commit/cleanup stays unknown and tokens remain spent. Measure costs serially on ordinary operations correct in both snapshots; a formerly failing CTE/RETURNING case is capability recovery, not a comparable speed baseline. Owner restart checks on existing aliases are limited reads, refusals and unconfirmed previews unless configured writes are separately approved. [Repair, cost and current acceptance](../validation/v3.8/V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md).


## Live MySQL/InnoDB write gate (October22, DRR-144/145)

Run `tests/test_read_analysis_binding_v382.py` for exact-source rejection before base dispatch, unchanged matching SQL/params, context/completeness/write controls and SQLite preconnect parity. Do not accept an import failure or an unrelated exception as a killed binding sentinel.

For the approved test account, run `scripts/validation/mysql_writes.py --config /absolute/test/server.toml --alias test_mysql --source /absolute/repository/src --legacy-tests --output /fresh/source.json.gz`. The script creates one random owned mcp_contract_* schema, requires CREATE/DROP DATABASE and TRIGGER plus observation of its own lock wait in INNODB_TRX, and drops only its exact created schema. It never changes configured business tables, grants or global settings. Observe fixture authorization before running against another server; no silent skip/fallback for missing access. The four legacy opt-in tests receive credentials only through the subprocess environment and run inside this private schema; do not treat default optional skips as integration passes.

Use the normal installed-wheel interpreter without --source for the same matrix. Run a fresh `--section unknown-clients` output per source/wheel for two in-process injected commit-ack controls, both classifiers and Client modes. Data truth comes from independent native PyMySQL with the explicit FOUND_ROWS contract; it shares no project parser, policy or value-mapping helpers. Read binding also covers pool reuse/reconnect. Check specific actual server errno and real LOCK WAIT, injection hits, token consumption, target Invalid preview_token rejection and independent final data; an unrelated tool error does not pass replay validation. Serialize/redact application results rather than claiming complete frames or model usage.

Treat committed/rolled_back/unknown as evidence contracts. Compare transactional business rows, trigger audits and cascades after cleanup; allow consumed AUTO_INCREMENT gaps and other explicitly non-transactional allocation state. This is a test oracle, not a production full-database comparison. Do not automatically retry unknown or reuse consumed tokens. Keep real server errors/session disconnects separate from labelled client faults; this matrix does not simulate arbitrary network partitions or cover other engines/isolation profiles. Freeze one limited restart plan after source/package checks; public tools cannot inject the internal analysis object. [Current gate definitions, evidence and limits](../validation/v3.8/V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md).

The [finite stabilization plan](../validation/v3.8/V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md) fixes16 contract families, evidence reuse, execution order and stop conditions. Audit concrete coverage before adding tests; retain supported positive cases alongside refusal controls. The [owner-restarted native6/6 supplement](../validation/v3.8/v382_mysql_write_contracts_2026_10_22/resident_restart/README.md) completes only the frozen refresh scope. Internal mismatch, real writes and cross-entry coverage need their own evidence. The subsequent [bounded stabilization acceptance](../validation/v3.8/V3_8_2_STABILIZATION_2026_10_22_ZH.md) completes S1–S4 using those distinct proofs; the six-call result alone does not accept them.

For the approved MySQL test account, `scripts/validation/stabilization_mysql_reads.py --config /absolute/test/server.toml --alias test_mysql --source /absolute/repository/src --output /fresh/reads.json.gz` adds a smaller read-contract matrix in an owned disposable schema. Use the existing normal-wheel interpreter and omit --source for the matching installation check. This script imports the sibling mysql_writes fixture ownership/cleanup helper; run it from its repository location. It creates and seeds only its exact random schema and verifies removal, never existing business tables. Independent PyMySQL queries/direct catalogs supply duplicate labels, bytes, generated values and actual PRIMARY ordering; checks cover raw/Skill/sample, data truncation and compact/full metadata in both Client modes/transports. Records are application results, not full wire frames or model usage. Do not reuse this test authorization for a different server or change grants/configuration without the agreed discussion.
