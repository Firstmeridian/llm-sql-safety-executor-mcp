# Unified connection diagnostics — design decision

> **v3.8 applicability (2026-09-26):** The unified diagnostic contract and cleanup safeguards remain relevant. Runtime ownership is now per service instance, and configuration/entry points use the installed package and TOML. See [migration](CONFIGURATION_ZH.md) and [implementation decisions](../architecture/V3_8_IMPLEMENTATION_ZH.md). Dated tests and earlier environment settings below retain their original scope.

[简体中文](V3_7_CONNECTION_DIAGNOSTICS_DESIGN_ZH.md)

Initial design: 2026-09-12, implemented in the v3.7.2 maintenance work.
The September 13–15 routing follow-ups belong to v3.7.3 and did not change
the diagnostic implementation. The September 22 update described first below
unifies the interface, isolated execution and report; it is a breaking migration
without a repository version change. See the [release record](../releases/RELEASE_NOTES_v3_7.md).

Dated follow-ups retain the rules and validation states of each stage. Current
routing/deployment acceptance is maintained in the [Agent validation guide](MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md#18-限制优先级与配置解读的可复用验收).

## Purpose and interface

```python
check_connection(connection_id: str | None = None, scope: Literal["single", "all"] = "single")
```

No arguments checks the default; `connection_id="alias"` checks one configured
alias; `scope="all"` checks all aliases in configuration order. All scope permits
only omitted/null connection_id. Invalid scopes, blank/unknown aliases, wrong
types, extra arguments and all-plus-non-null-alias combinations fail before
creating a connection or submitting diagnostic work. No URLs or credentials are
accepted. The old plural tool is removed without an alias.

Every scope uses fresh diagnostic connections. `list_connections()` lists
configuration without probing it. Diagnostics are never a startup hook or a
prerequisite for ordinary queries. For routing and restrictions, explicit all
scope must be requested and permitted; omitted scope does not imply all. A known
target is passed explicitly, while unresolved purposes/references or irreconcilable
restrictions require optional configuration discovery followed by waiting.

The report has required `scope`, `all_connected`, `complete`, `connection_count`,
`connected_count`, `cleanup_failed`, and alias-keyed `results`. Counts and
`all_connected` describe only the selected scope. Single scope has one entry and
does not label unrelated aliases not_checked. All scope stays `"all"` even with
one configured connection. Each result includes `db_type`, `cleanup_failed` and
required `status`/`connected` fields:

| status | connected | Meaning |
|---|---|---|
| connected | true | Fresh connection check succeeded |
| failed | false | Check completed with a sanitized failure |
| timeout | null | Started, but no result within the diagnostic deadline |
| not_checked | null | Not started before the deadline or stopped after cleanup failure |

Non-success entries include a safe `error`. `complete` requires every selected
entry to be connected/failed; `all_connected` requires every selected entry to
be connected. Failure, timeout and observed cleanup failure remain normal MCP
reports. Invalid input, busy/stopped diagnostics and cleanup-disabled requests
are tool errors outside the report schema.

Single-scope metadata and telemetry include its resolved alias, type and
`connection_scope="single"`; all scope includes counts and
`connection_scope="all"` without a default-alias identity. This identity comes
from configuration, without acquiring a business adapter. Errors retain valid
request scope and resolved identity when available; invalid aliases are not
logged verbatim or replaced with default identity. Report completion
(`call_completed`) is separate from operational `success`, which requires
`all_connected and not cleanup_failed`.

Telemetry has an SDK boundary: installed FastMCP 3.0.2 / MCP 1.26 validates
wire-schema errors (enum, length, type and extra arguments) before this tool
middleware, so those rejected calls have no project telemetry event. Requests
that reach the middleware still record invalid parameter combinations,
blank/unknown aliases and busy/stopped/disabled errors, without inventing default
identity. Regressions verify zero probes for rejected inputs and this observation
boundary; the project does not add an earlier SDK interception layer.

## Decision: reuse adapter logic, isolate connection instances

The initial preference was to reuse business connections for a simpler structure.
Inspection showed that the current SQLite adapter uses `StaticPool`, including
file-backed databases. Its checkouts share a DBAPI connection and transaction
state. Merely running `SELECT 1` through another checkout and closing it can
roll back unrelated uncommitted work. Making that reuse safe would require
coordinating diagnostic access with all business reads and writes, beyond this
feature's scope.

An isolated SQLAlchemy 2.0.46 in-memory experiment confirmed the risk: after a
business transaction inserted one uncommitted row, another checkout ran
`SELECT 1` and closed. The row count in the business transaction changed from
1 to 0. This was a disposable local experiment, not a test against user data.
[SQLAlchemy documents the same shared-transaction limitation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#using-staticpool-for-single-connection-memory-databases).

The chosen implementation adds an internal diagnostic mode to adapter creation:
reuse configuration parsing, backend checks and sanitization, but create a fresh
uncached adapter with `NullPool`. The worker owns creation, check and cleanup.
SQLite file URIs encode filename characters and use `mode=ro`; missing files
fail without being created. SQLite `:memory:` creates a disposable memory
database and therefore does not test existing application data. MySQL retains
the configured driver connection/read/write and query timeouts.

Here, read-only means no database writes, not zero filesystem writes. WAL-mode
reads can create or update `-wal`/`-shm` auxiliary files, depending on existing
files and directory permissions. `mode=ro` is not a filesystem sandbox. We do
not use `immutable=1`: that disables locking and change detection and is an
invalid assumption for a database other business connections can modify.
[SQLite URI semantics](https://sqlite.org/uri.html) and
[read-only WAL requirements](https://www.sqlite.org/wal.html#read_only_databases)
define this distinction. No checkpoint, journal-mode change or business-table
query is added to the production probe.

This measures whether configuration can establish a fresh connection. It does
not certify an existing pool, business schema, Skill readiness or write access.
No additional database-name query is made, and no host, filesystem path or
credential is included in the report.

## Deadline, cancellation and resource ownership

The server lifespan owns a dedicated executor with at most four workers. One
diagnostic request is admitted per process, for either scope; work is submitted
only as slots become available. Other single/all requests receive a safe busy
error instead of creating a queue.

The waiting budget is 30 seconds, or `min(30, 0.8*T)` for a positive configured
MCP timeout `T`. Disabling the outer timeout does not disable this budget. At the
deadline the scheduler stops submitting work and returns completed results plus
explicit incomplete states. Caller cancellation stops scheduling and propagates.
There is no retry, result polling, or mutation of a report after it returns.

Cancellation here means cancellation received by the server (for example an MCP
`notifications/cancelled` notification, sent by FastMCP `client.cancel(request_id)`).
Cancelling only a local Python waiter does not necessarily notify the server;
without notification the server continues under its original diagnostic budget.

Running DBAPI calls cannot be killed by cancelling an async waiter. A batch
keeps ownership until every submitted worker finishes its cleanup attempt, including after
timeouts and disconnects. Shutdown stops admission and cancels not-started work;
running workers attempt their own cleanup. Python process exit can wait for
these threads, so neither a hard driver termination deadline nor bounded process
shutdown is promised. Driver timeouts remain the underlying backstop.

A driver call that never returns can retain the batch indefinitely; a request
timeout does not make it safe to admit more probes. A process-level regression
uses a disposable child with a deliberately blocked substitute probe: the report
times out and executor shutdown returns, but process exit waits until the parent
releases the worker. The parent can kill only that child if the test fails.
This validates the lifecycle boundary, not actual network-driver behavior.
Before long-running unattended deployment, use an isolated database/network to
test dropped connections, blackholed traffic, driver timeout behavior and the
supervisor's graceful-stop/forced-termination policy. Those environment-specific
fault drills are deferred; no live network disruption, automatic watchdog or
new process-management framework is part of this feature.

### Review follow-up: observed cleanup failures

The original implementation logged an `adapter.close()` exception but returned
the earlier connection result and admitted another batch. An isolated substitute
reproduced two accepted batches with unclosed stub resources. This was evidence
of a missing failure contract, not evidence of a live database resource leak.

The minimal correction records `cleanup_failed` per result and in the report,
preserves the confirmed connectivity result, and latches a runner flag when a
worker observes cleanup failure. It stops further submissions; already-started
workers finish their own cleanup attempts. New batches return a safe MCP tool
error instructing the operator to restart the server process. Restarting a
client session or cycling lifespan does not clear the flag. Other tools remain
available. There is no retry loop, recovery worker, reset endpoint or new setting.

False means no failure observed at report time, not proof of resource release:
drivers or SQLAlchemy may handle some cleanup errors internally. Cleanup failure
after timeout/cancellation still latches the flag and is logged; reports already
returned are immutable. Later rejected calls record cleanup failure in telemetry.
This intentionally accepts loss of all diagnostics after a rare observable
cleanup error to avoid repeatedly opening connections when release is uncertain.

The result schema now requires `status` and `connected` rather than making them
optional via Pydantic defaults. Busy/stopped/disabled errors remain outside this
successful-report schema. Current tool descriptions apply the same independent
connection, deadline and error-channel rules to single and all scopes. The table
below preserves the initial cleanup/schema review changes before consolidation.

| Update | Benefit and reason | Mechanism / cost |
|---|---|---|
| Observe cleanup failure and disable subsequent batches | Prevent repeated resource accumulation after an observable failure | One boolean latch; process restart for recovery; no automatic recovery subsystem |
| Keep connectivity and cleanup separate | Do not turn a confirmed connection success into a false connectivity failure | Per-result/report `cleanup_failed`; telemetry success combines both outcomes |
| Require status fields in the output schema | Give generated clients the same guarantees as the documented payload | Remove field defaults and pass literals explicitly; negative schema tests |
| Clarify tool selection and MCP errors | Prevent confusion about default routing, isolation and busy responses | Tool descriptions plus bilingual README; no old-tool API change |
| Restore the historical v3.6 Skill name | Preserve the timeline while making the current name discoverable | Risk entry records `update-order-status` then, `sample-update-order-status` now |
| Clarify SQLite WAL and process-exit boundaries | Avoid interpreting read-only as zero filesystem writes or a request budget as guaranteed shutdown | WAL transaction regression and an isolated child-process test; deployment-specific network fault drills remain separate |

The installed FastMCP 3.0.2 implementation directly awaits async tools; blocking
database work must therefore be explicitly offloaded. Its foreground timeout
alone would discard partial results, which is why this tool has an earlier
internal deadline. [FastMCP timeout documentation](https://gofastmcp.com/servers/tools#timeouts)
and [Python executor cancellation semantics](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Executor.shutdown)
support these boundaries; they do not imply that cancelling a tool kills a thread.

## Unified contract review and migration — September 22, 2026

| Before | Now | Compatibility / operational cost |
|---|---|---|
| `check_connections()` | `check_connection(scope="all")` | Removed tool name; no deprecated alias |
| `check_connection()` / named call | Input syntax retained; fresh worker-owned connection | No longer tests a reused business adapter; may add per-call connection setup cost and now shares budget, busy and cleanup disable |
| Top-level `connected` | `results[alias].connected` | One report schema for both scopes; clients must migrate |
| `message`, `database_name`, `config` | Removed | No additional database-name query; identity is alias/type |
| Batch-only report without scope | Required `scope` for all reports | Scope is explicit, not inferred from count |
| Batch-only admission/error attribution | Scope-aware telemetry for every diagnostic | Single checks can be unavailable behind a running or cleanup-disabled all check |

The existing runner already accepts a list of configurations; one-item requests
reuse its lifecycle instead of adding another scheduler. This reduces two
execution/return contracts to one. It does not prove fewer Agent mistakes,
lower latency or lower billed token usage. A single report can be longer than
the old single response. Host-added repeated instructions can also dominate
visible tool text even after one tool is removed.

| Change | Earlier problem | Solution and benefit | Remaining cost |
|---|---|---|---|
| One diagnostic entry | Similar names plus two execution contracts | Explicit scope; one worker-owned path | Breaking public name/output migration |
| One report model | Single check lacked incomplete/cleanup states | Common required fields and per-alias outcomes | More fields for single-check clients |
| Configuration-only identity | Metadata could acquire business adapters | Resolve configuration before submitting workers | Identity may be absent for malformed requests |
| Evaluate shorter routing guidance | Repeated selection prose and Host wrapping | Separate interface migration B from compression C; revert on regression | C probed the default for an unresolved purpose; final wording restores B, with no delivered compression benefit |
| Shared resource guard | Separate single check bypassed batch protections | One admission gate and cleanup latch | Single checks share busy/disabled availability |

Validation freezes baseline A at `7d4a079`, compares unified interface B with
necessary wording changes, then compares wording-only C with B. Save metadata,
actual call traces, first-call correctness/recovery/final completion and forbidden
target access separately. Character counts are not token usage; no source-only
or fixture run establishes refreshed native-Host acceptance. Failed cases and
historical grades remain evidence, not targets to regrade. The current run's
verification results are in the [September 22 staged record](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_UNIFIED_CONNECTION_DIAGNOSTICS_2026_09_22_ZH.md), separately from the historical evidence below.

One isolated Luna trial on C listed configuration and then probed the default
despite an unresolved purpose, triggering the predeclared rollback. Final source
retains B wording and the unified interface; C's failure and raw trace remain
evidence. Fresh contexts after restoring B also showed the same failure, so it
cannot be attributed uniquely to compression and B does not reliably prevent
target guessing. Full six-turn trials are tracked separately in that record.
The subsequent connected-Host review verifies the refreshed unified signature,
default/named/all diagnostics and conflicting-argument rejection. It does not
attest to a remote source digest; that connector also does not expose `_meta`.
C's character reduction is not a delivered benefit.

Review coverage separates deterministic lifecycle checks from Agent behavior:
the default suite passed 675 tests with four existing opt-in MySQL skips, and
Pyright passed the ten changed Python files using the repository configuration
and explicit venv interpreter. This is not whole-repository Pyright. Timeouts,
cancellation, cleanup failures and WAL behavior are tested in isolation; live
MySQL/SQLite calls only check normal connectivity. No real database fault or
business write was introduced. Completing previously blocked fixture workflows
does not erase earlier failures or establish universal routing correctness.

Natural-language restrictions remain guidance. DRR-2026-066 stays Open. A strict
Host/application must authorize the actual targets before every action, including
implicit defaults and all configured targets; model-generated scope is not trusted
permission. This update adds no authorization subsystem or automatic retry.

Sources inform the method, not a guaranteed improvement: [Google's explicit
function definitions and validation](https://ai.google.dev/gemini-api/docs/function-calling#best-practices),
[MCP structured output and security requirements](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
and [Anthropic's workflow-based tool evaluations](https://www.anthropic.com/engineering/writing-tools-for-agents).

## Evidence and validation

The following dated records describe the interfaces and scores at their original
stages. References to two tools or unchanged single-check behavior are historical;
the current contract is above.


On 2026-09-13, eight fresh-context `gpt-5.6-luna` live task instances checked
tool selection. Explicit all/default/named/configuration and role-clarification
cases behaved as intended. Two of three unspecified-scope instances instead
selected all-connection diagnostics. All actual connection checks succeeded;
the issue was unintended scope expansion under ambiguous wording. The
[dated routing evaluation](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_CONNECTION_ROUTING_2026_09_13_ZH.md)
records exact prompts, calls, timings and limitations, and recommends making
the default-scope selection rule explicit before considering tool consolidation.
It does not claim the selection issue is already fixed; production prompts were
not changed in that evaluation.

The same dated record now also includes three fresh-context, six-turn order
dashboard trials. All completed the read-only aggregation, switched from all
connections back to the selected alias, and stopped on a misspelled alias until
the simulated user corrected it. All three initially supplied `name` instead
of `table_name` to `describe_table`, then recovered after input rejection. This
is a separate parameter-example consistency finding, not an error-free pass or
proof that the earlier unspecified-scope issue is resolved. The maintained
[Agent behavior validation method](MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md) now
separates complete-task outcomes, intermediate errors and isolated limit tests.

A later same-day unchanged-version retest used three new identical generic
connectivity prompts and three new six-turn trials. All three generic requests
selected the batch tool; all three complete tasks again initially supplied
`name` before correcting it to `table_name`. Contextual routing and task
completion succeeded. This adds baseline evidence only: no production prompt
change or post-fix A/B validation occurred, and DRR-2026-066/067 remain open.

Final boundary review used SQLite 3.45.1 and a disposable, cleanly closed WAL
database. The actual `SELECT 1` probe succeeded without creating sidecars in
that experiment. A separate table read through the same diagnostic adapter's
`mode=ro` connection created `-wal` and `-shm`; the main database bytes stayed
unchanged. This demonstrates the URI-mode boundary, not a claim that the current
probe always creates sidecars. The automated WAL regression checks committed
visibility, write rejection and preservation of a business transaction; it does
not require platform-specific sidecar creation behavior.

Review-time black-box live calls (before this cleanup/schema follow-up) used an
isolated-context agent that had not read the implementation. It selected the
batch tool directly from its exposed description: all three aliases succeeded
(`complete=true`, `all_connected=true`), with 7,173 ms observed at the caller.
Configuration discovery took 43 ms, the default MySQL check 199 ms, and a named
SQLite check 94 ms. All durations include transport overhead and are not a
comparative benchmark. The service reported current `sample-` names. No fault
injection or mutation was performed. The connector did not expose `_meta` to
the agent, so live telemetry forwarding was not inferred from these results.
These live observations do not validate cleanup failures; those use isolated
tests, including failures discovered after a timed-out response.

Planning-time MCP calls found three configured aliases. All three existing
single-connection checks succeeded; caller-observed durations were approximately
0.59–0.62 seconds, including transport overhead. The running service still
reported pre-migration Skill names, so this is a baseline of that instance,
not validation of the new batch tool or the latest repository revision.

Implementation validation on 2026-09-12:

- Default suite: `621 passed, 4 skipped`. The four existing opt-in MySQL cases
  remained skipped. A subsequently added MCP protocol-cancellation regression
  passed separately (`1 passed`); no live MySQL fault injection was performed.
- Pyright checked the seven changed Python files with `0 errors, 0 warnings`;
  the extended diagnostic test file was also checked separately.
- A fresh stdio server process, launched from the working tree with dotenv
  disabled and two temporary SQLite configurations, exposed the new tool and
  returned one success plus one confirmed failure. `complete=true`,
  `all_connected=false`, and aggregate metadata were correct. The missing file
  was not created and its path was not disclosed.
- That stdio call took 411.43 ms at the client and reported 175.395 ms of server
  execution. These are isolated smoke-test observations, not a production
  performance benchmark. Existing deployed MCP processes were not restarted.

Review follow-up validation on 2026-09-12:

- Default suite: `630 passed, 4 skipped`; existing opt-in MySQL cases remain
  skipped. Targeted diagnostics and telemetry tests: `34 passed`.
- Pyright checked `connection_diagnostics.py`, `mcp_sql_server.py` and
  `tests/test_connection_diagnostics.py`: `0 errors, 0 warnings`.
- New regressions reject missing `status`/`connected`, preserve connectivity
  when cleanup raises, stop further submissions and reject subsequent batches,
  retain the failure latch across lifespan restart, and handle a cleanup failure
  discovered after timeout without rewriting the returned report. In-memory MCP
  tests verify the cleanup flag, error channel and aggregate telemetry while
  configuration discovery remains available.
- `git diff --check` passed. The connected live service was not restarted for
  this follow-up; its observations above are a baseline, not validation of these
  latest changes.

Final WAL/process-boundary validation on 2026-09-12:

- Default suite: `632 passed, 4 skipped`; targeted diagnostics/telemetry:
  `36 passed`. The two added cases cover WAL transaction preservation and
  process exit waiting for a blocked diagnostic worker.
- Pyright checked all seven changed Python files with `0 errors, 0 warnings`.
- Added local Markdown link targets and `git diff --check` passed. No running
  MCP service or real database network was interrupted for these tests.

Automated coverage uses disposable SQLite databases and controlled driver/worker
substitutes: partial failure, deadline states, cancellation, worker limits,
busy/draining recovery, resource cleanup, business transaction preservation,
special filenames, missing files, output schema and sanitized aggregate telemetry.
FastMCP in-memory client tests exercise the actual registered tools, including
a shorter outer timeout and unchanged single-connection routing. Real MySQL is
not required for the hermetic suite; a deployed smoke check must first verify
that the running instance exposes the new tool.

[Anthropic's tool-design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)
supports consolidating useful workflows and evaluating real tool calls, while
warning against overlapping tools. Here, descriptions explicitly distinguish
single-alias checks, all-alias diagnostics and configuration discovery. These
sources inform the design; none mandates this particular API or worker count.


## Routing guidance follow-up (2026-09-13)

Implemented the bounded [routing/example correction](V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md):
no specified or established connectivity target selects the default single
connection; a confirmed conversational alias must be passed explicitly; a clear
all-connection request selects the batch tool. A continuation of a confirmed
all-scope task qualifies, while missing an alias or a generic connection problem
alone does not. Ambiguous purpose/references/conflicts require clarification.
This is Agent guidance, not server verification of natural-language intent.

The shared instructions, tool descriptions, parameter help, `sql_assistant`
and bilingual README now agree. Six current
`describe_table(name...)` examples use `table_name`; strict validation and
historical error traces remain unchanged. No diagnostic resource, waiting-budget,
connection-isolation, API or mutation-policy changes were needed.

Validation: `635 passed, 4 skipped`; metadata/schema follow-up `47 passed`;
Pyright on four changed Python files `0 errors, 0 warnings`. The
[Agent record](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_CONNECTION_ROUTING_2026_09_13_ZH.md)
separates fixture stdio trials from the old IDE Host and preserves observed
purpose-to-alias guessing. Passing protocol checks does not close the Agent
behavior risk or prove that a deployed Host has refreshed its tool metadata.


### Native-Host review update (2026-09-14)

The restarted Host now exposes the updated descriptions, and a real list_tables
response uses table_name in its hint. The [native retest](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_CONNECTION_ROUTING_2026_09_14_ZH.md)
records nine new Luna contexts, three full workflows and current read-only
MySQL/SQLite calls. DRR-2026-067 is implemented; DRR-2026-066 remains open because
purpose-only targets still triggered a guessed query or unrequested default probe.
Conflicting-scope trials respected the narrower restriction without clarifying.
These observations do not indicate a SQL/write-policy bypass, and no diagnostic
implementation or production prompt changed during this review. Related tests:
92 passed; four Python files: Pyright 0 errors, 0 warnings.

### Target clarification follow-up (2026-09-14, after the native review)

Implemented the [explicit waiting rule](V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md#8-用途目标未确定时暂停数据库操作2026-09-14):
when a purpose has no resolved target, references are ambiguous, a type has no
unique match, or scopes conflict, optionally list configuration, then ask and
wait. Do not explore schema, query, use Skills or run either diagnostic for that
request meanwhile. This takes precedence over schema-first workflow hints.

Targets come from explicit user choice, a trusted application binding applicable
to the request, or the existing unique structured db_type match rule. Agent
guesses, names, defaults and successful probes are not proof of intended purpose.
Only generic connectivity without target clues or a resolved conversational/
application target falls back to a default diagnostic; ordinary no-target queries
retain existing default routing. No diagnostic mechanism or mandatory server confirmation was
added; deterministic target enforcement remains an application/Host concern.

Default suite: 635 passed, 4 skipped; six changed Python files pass Pyright.
Local MCP discovery confirms the new metadata; description-free input/output
schemas and annotations match the committed version under the same isolated
configuration. Native Host metadata still precedes this follow-up, so behavior
acceptance remains pending rather than reusing previous trial results.

### Submission review (2026-09-15)

The [new native review](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_CONNECTION_ROUTING_2026_09_15_ZH.md)
confirms the Host now exposes the waiting rule. Twelve isolated Luna contexts
made 36 tool attempts, including three complete workflows. Purpose clarification,
default/all selection and returning to the chosen alias passed; conflicting
scope still triggered the narrower default check without clarification. This
remains an interaction-policy limitation, not observed scope expansion.

Review also aligned current Skill parameter examples with skill_name and added
real prompts/get versus tools/list checks, with mutation registration on/off and
no Skill execution. Final tests: 637 passed, 4 skipped; six Python files pass
Pyright. Table allowlist configuration being mistaken for physical table presence
is tracked separately under DRR-2026-068. No diagnostic mechanism changed.

The architecture remains deliberately small. Shared guidance grew and this Host
repeats instructions in tool metadata; manage that distribution cost before
adding more rules or a new routing framework. Keeping distinct single/business
and batch/fresh diagnostics avoids an unnecessary API migration. See the native
review for measured character counts, interpretation limits and commit scope.

### Restriction and configuration follow-up (2026-09-15)

The [current routing contract](V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md#10-限制优先级与配置语义补充修复2026-09-15)
permits a requested diagnostic to follow an explicit restriction to one resolved
alias or the default, reporting other connections unchecked. Prohibitions include
connection checks; rejected partial checks or irreconcilable restrictions require
waiting. Previous conflict trials retain their original grades. This does not
authorize writes or change either diagnostic implementation.

list_connections now adds an explanatory hint: its allowlist is configured access,
not evidence of table existence or a physical inventory. This additive field
causes no database I/O. Three new protocol cases cover absent databases and
different configured, visible and physical table sets. Full tests: 640 passed,
4 skipped; seven changed Python files pass Pyright with zero errors/warnings.

The [new fixture review](../validation/v3.7/V3_7_3_LIVE_MCP_TEST_CONNECTION_BOUNDARIES_2026_09_15_ZH.md)
records 15 fresh Luna contexts and 13 actual MCP calls across two metadata phases.
Final configuration interpretation passed 3/3, but explicit-prohibition cases
still failed in 2/3 contexts. This is not native-Host acceptance; DRR-2026-066 stays
Open. Runtime enforcement of per-request allowed targets needs trusted context
and call validation at the application/Host boundary, not more equivalent prompts
or a model-supplied confirmation field. No such new authorization interface is
part of this change.

For deployments requiring hard per-request target restrictions, trusted
application/Host validation is a prerequisite before go-live. It must cover
explicit aliases, the actual implicit default and all configured batch targets,
and prevent bypassing that boundary. Trusted local use retains the documented
limitation; the server does not implement this request-specific authorization.
The added list_connections hint also means independently defined closed client
response models may require an update; unchanged input contracts and existing
output fields do not imply an unchanged set of output fields.
