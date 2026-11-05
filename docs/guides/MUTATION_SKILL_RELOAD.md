# Controlled Mutation Skill reload

[中文](MUTATION_SKILL_RELOAD_ZH.md)

After deploying trusted Mutation files to the configured Skill directory, call
`reload_skills` with `{"skill_type": "mutation"}`. The default `query` scope
preserves Mutation code and previews. Mutation publication requires both Skills
and Mutation execution to be enabled; it does not enable database writes.
Installing this implementation and its new tool parameter first requires a
new service process, followed by a Host tool-catalog refresh and a check from
the actual consumer. Subsequent supported definition updates do not.

## Publication, proposals and execution

Validate the complete candidate and publish one catalog reference in the
receiving instance. Support additions, changes, disable and removal. Unchanged
definitions keep their object and generation, without reimport or revision
increment. Declared metadata and exact entry bytes determine changes, even when
the author leaves `version` unchanged.

The strict catalog scan rejects active paths replaced by regular files,
dangling/loop symlinks or unverifiable directories. Detected disappearance or
directory identity change of an active entry during scanning also rejects the
whole candidate, even if the name returns. Failures keep the catalog, revision
and pending previews. Real deletion and valid directory symlinks resolving
within the configured root remain supported. See the
[November 5 scope/catalog repair](../validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md).

| State at publication | Behavior |
| --- | --- |
| Definition unchanged, or another Skill updated | Existing generation and proposals remain subject to normal expiry, authorization and one-time consumption |
| Definition changed, disabled or removed; token not consumed | Discard affected pending proposals; the user decides whether to preview again |
| Old preview still preparing, before token issuance | Check the current generation at issuance and reject a replaced definition |
| Token consumed before publication | Finish on the pinned original code, plan and bound values |
| Candidate validation fails | Keep the active catalog and pending proposals |
| A changes to B and later back to A | Assign a new activation generation; the original A's tokens do not revive |

Publication and token issuance/consumption have a defined order. The short
critical section contains no Python import, database operation, await or human
wait. A later publication can invalidate a proposal after issuance, even before
its response arrives. MRTR review attachment, inspection, re-asking, rejection
and approval check the same generation. MRTR's existing protocol and elicitation
requirements remain; hot reload does not broaden Host capabilities.

Publication does not cancel admitted executions. Preserve existing committed,
rolled-back and unknown outcome semantics. A lost response does not establish
non-execution and never authorizes an automatic retry. Each MCP request retains
one catalog snapshot across awaits.

For a confirmation rejected by framework checks **before trusted Skill
construction** (for example removal, disable, renamed parameters or narrowed
connection scope), retain the specific reason and state that this request wrote
nothing. Confirmation matches and consumes its token before constructing an imperative
Skill, including constructors that return normally. Missing, invalid, expired,
mismatched and consumed tokens therefore run no request-time Skill Python.
Once admitted, a construction failure does not restore the token. Imperative
re-validation failure retains `validation_failed` but reports whole-operation
`unknown`, since trusted setup or validation may already have side effects.
Generation rejection after preview Python does not assert that the request
wrote nothing. See the [October 31 follow-up](../validation/v3.8/V3_8_2_MUTATION_ADMISSION_HOST_BINDING_2026_10_31_ZH.md). This does not
establish an earlier request's outcome or apply to arbitrary constructors or
execution callbacks that may already have performed side effects. Do not
retry or create a new preview automatically. See the [targeted repair](../validation/v3.8/V3_8_2_RESTART_IDENTITY_REFUSAL_REPAIR_2026_10_29_ZH.md).

## Python scope and failure boundary

Compile the captured entry bytes into an independent candidate namespace;
never reload an active module in place. Both managed and imperative Mutations
use this mechanism. Shared Python dependencies, framework code, configuration,
secrets, connections and grants still require restart. Preserve existing Query
objects. Type conversion requires restart; publication is not broadcast between
server instances. Preserved Query names are skipped before probing filesystem
targets.

Skills are trusted maintainer code. Import executes module-level Python;
catalog atomicity cannot undo its external database, file or other side effects.
Keep top-level code declarative and business operations in lifecycle callbacks.
A failed candidate may execute top-level code again on a later attempt. The
management tool therefore declares destructive=true and idempotent=false;
loading does not grant business-write permission. Unchanged entries are reused.

Publication scans the bounded pending-proposal store; cost grows with its size,
and issuance/consumption share the publication lock. Ordinary calls do not scan
files, and admitted database execution does not hold that lock. This contract
does not claim a general speed or model-token improvement.

## Calling Agent confirmation

1. Check success, skill_type, revision, added/changed/removed and
   invalidated_previews. The count does not mean an admitted execution was cancelled.
2. Check affected details, parameters and scope in the actual consumer with the
   same target connection_id. Use discovery for additions/removals as needed.
3. When the business task needs a write, create a new preview for the new
   definition and obtain the required confirmation. Check the resulting outcome.
   Definition-only deployment does not require a write or executing every Skill.
4. After a lost response inspect loaded state instead of automatically publishing
   or executing again. Report missing evidence as unverified.

Publication does not establish readiness, authorization or business correctness.
Ordinary business calls add no file scan or mandatory refresh. Failure returns
mutation_reload_failed with a safe reason; competing reloads report
reload_in_progress.

See [Query reload](QUERY_SKILL_RELOAD.md), the [Codex restart helper](CODEX_MCP_RESTART.md)
and [Python reload caveats](https://docs.python.org/3.12/library/importlib.html#importlib.reload).

The [acceptance report](../validation/v3.8/V3_8_2_MUTATION_RELOAD_2026_10_29_ZH.md)
separates source/installed/live evidence from current-Host and model verification.

## Native workflow evidence

The separately frozen [three-consumer cohort](../validation/v3.8/V3_8_2_MUTATION_RELOAD_NATIVE_2026_10_29_ZH.md) passes3/3 two-round tasks and6/6 business answers, with independent rows/triggers. This covers actual publication/parameter changes/failure retention and confirmed execution, not native MRTR or the in-flight race. Exact config bytes are restored and QA definitions removed; both original consumers and the caller confirm runtime unload after a separately approved restart. The owned DB is deleted, with snapshot/audit retained. No A/B speed/token claim.
