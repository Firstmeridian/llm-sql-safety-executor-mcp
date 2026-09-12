# Batch connection diagnostics — design decision

Date: 2026-09-12. Applies to the current v3.7.2 maintenance work.

## Purpose and interface

`check_connections()` performs one explicitly requested diagnostic of all
configured aliases, in configuration order, without accepting aliases, URLs or
credentials as arguments. It consolidates discovery, checking and summarization.
It is never a startup hook or a prerequisite for ordinary queries. The existing
`check_connection(connection_id=None)` still checks one business adapter, and
`list_connections()` lists configuration without probing it.

The report contains `all_connected`, `complete`, `connection_count`,
`connected_count`, `cleanup_failed`, and alias-keyed `results`. Each result carries
`db_type`, `cleanup_failed`, and required `status`/`connected` fields:

| status | connected | Meaning |
|---|---|---|
| connected | true | Fresh connection check succeeded |
| failed | false | Check completed with a sanitized failure |
| timeout | null | Started, but no result within the diagnostic deadline |
| not_checked | null | Not started before the deadline or stopped after cleanup failure |

Non-success entries include a safe `error`. `complete` requires every entry to
be connected/failed; `all_connected` requires every entry to be connected. The
report is a normal MCP result even if every database fails. Busy or stopped
diagnostics are request-level tool errors. Aggregate metadata/telemetry use
`connection_scope=all` and counts, omit default-alias identity, and distinguish
report completion (`call_completed`) from operational success (`success`).
`all_connected` and `complete` describe connectivity only. Operational `success`
requires `all_connected and not cleanup_failed`.

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
batch is admitted per process; work is submitted only as slots become available.
Other batch requests receive a safe busy error instead of creating a queue.

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
This intentionally accepts loss of batch diagnostics after a rare observable
cleanup error to avoid repeatedly opening connections when release is uncertain.

The result schema now requires `status` and `connected` rather than making them
optional via Pydantic defaults. Busy/stopped/disabled errors remain outside this
successful-report schema. Tool descriptions explicitly distinguish the old
business-adapter `check_connection()` from fresh-connection `check_connections()`.

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

## Evidence and validation

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
