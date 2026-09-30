# v3.8 security boundary / 安全边界

The supported deployment is a trusted local Host and a single server process. MCP annotations describe tools; they are not authorization. The server does not authenticate a human approver, provide remote multi-user identity isolation, or sandbox Python Skills.

本轮沿用可信 Host 审批模式 A。Host 负责可靠呈现审阅内容并收集人的决定；服务端负责目标、Skill、参数、提案绑定及单次消费。恶意或被攻陷的 Host 能伪造批准，不能宣称 MRTR 提供了独立人类认证。

## Where approval is enforced

MRTR is a protocol pattern for requesting more input, not inherently a human-approval system. This project's `request_mutation_approval` uses it to require a bound approving response before executing that proposal; the Host remains responsible for obtaining the person's decision.

**MRTR 给 `request_mutation_approval` 这个入口增加了服务端强制的“批准轮次”；而 preview/execute 的“人工批准”属于 Host 工作流，Server 强制 preview-token 协议、权限与执行检查，但并不知道是否真的有人批准。** 此处“批准轮次”指服务端必须收到有效绑定的 `accept` 与严格布尔 `approve=true`，不证明真人在场或点击，也不改变旧入口仍可用的事实。

| Boundary | Legacy preview/execute | MRTR |
|---|---|---|
| Human interaction | The Host implements it; the server does not request an approval form. An Agent may ask in conversation, or the reference Host may require literal `APPROVE`. | The server returns a protocol input request; the Host renders it and supplies a decision. Window rendering and human interaction depend on that Host. |
| Server execution gate | `confirm=true`, a valid matching one-time preview token, configuration grants and execution checks. | A valid bound continuation, `accept` with strict boolean `approve=true`, and the shared proposal/grant/execution checks. |
| Independent evidence of a human | None: a client with both tool access and the token can submit execute without asking a person. | None: an automated or compromised Host can supply an accepting response. Sealing binds continuation state; it does not authenticate the approver. |

`skills.mutation.mrtr.enabled` controls registration of the optional MRTR tool. Enabling it does **not** disable `execute_mutation_skill` or require every mutation to use MRTR; disabling it does **not** disable otherwise authorized legacy mutations. Client tool-call permissions are another Host control, not a server-verifiable approval of the exact SQL.

Trusted-Host mode A is the accepted boundary (DRR-2026-050). A conversation-only instruction to ask permission is an Agent behavior rule, not a server authorization gate. The reference Host enforces its own decision/deadline checks in code, so legacy approval need not rely solely on an Agent following instructions; other authorized clients can still call the service directly. Both flows continue enforcing target, parameter, expiry, replay and database policies even though they do not prove human approval.

If the requirement changes to preventing an Agent/client from approving its own writes, a separate authenticated approval authority must issue authorization unavailable to that Agent and bound to the exact proposal, with every write entry point enforcing it. An unbypassable trusted gateway is another possible deployment boundary. These are future designs, not properties of current tokens, MRTR, tool annotations or UI prompts; hiding a tool only from the model is not sufficient server-side enforcement. See the [DRR follow-up](DESIGN_RISK_REGISTER.md#drr-2026-050-approval-boundary-follow-up-october-1-2026).

## Authorization

The October 1 deployment decision retains preview/execute as the default, with MRTR disabled unless explicitly enabled for a verified Host. Native Codex IDE evidence and the tested Copilot protocol rejection justify this compatibility choice only for the observed scope; see the [acceptance audit](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md). This does not strengthen either flow's human-identity guarantee. A client must not automatically switch write entry points after an approval refusal, cancellation, timeout or uncertain outcome. This is a Host workflow requirement, not a cross-entry-point server lock; reconcile uncertain writes first.

Read access defaults to deny. An explicit allowlist (nonempty) or `all` grants read scope; structural checks still block writes, unsupported syntax, system schemas, file operations, unsafe comments and unauthorized UNION. Raw SQL and Query Skills share the complete policy. Metadata tools obey read scope. Unknown targets never fall back.

Writes require all five configuration gates: Skills, global mutation enablement, admitted target, target mutation enablement, and target Skill allowlist. Skill connection/type/profile restrictions and execution checks remain conjunctive. Read allowlists are not universal mutation allowlists. Authorized previews/readiness checks may inspect mutation business tables even if general reads are denied.

Profile exclusions are normalized once in the TOML loader (trim, lowercase, deduplicate); blank entries fail startup. Query Skill availability uses the same read-admission predicate as execution, including tableless SQL. These checks do not grant mutation access.

Query Skill discovery also preflights the cached SQL with the execution path's full static policy for the resolved connection, including UNION and parsed table scope. A denied template remains in the catalog for other authorized targets; verdicts are not shared across connections. This adds parsing work to discovery, not database SQL execution. Enabled schema readiness can still perform metadata I/O, and execution repeats the authoritative checks. Availability does not guarantee valid parameters, dialect compatibility, database availability or successful execution.

Explicit target binding and deployment permissions do not authenticate the user's natural-language task scope. `OperationContext` carries operational callbacks, not a trusted per-request authorization grant. A Host-authenticated task-scope boundary remains deferred; an Agent can request any operation that the deployment otherwise authorizes.

## Proposals and MRTR

- `execute_mutation_skill` retains preview/execute and its opaque 256-bit random bearer handle. Only a digest is used as the token-store key; possession still represents a capability.
- MRTR supports only cached, framework-managed, single-statement plans. Legacy imperative callbacks retain their earlier weaker guarantee and are rejected by MRTR.
- First round validates protocol/form capability, Skill mode and authorization before preparing a proposal. It does not execute the managed write. Custom preview Python is trusted code; the server cannot sandbox a malicious preview callback.
- Review includes resolved target, Skill, normalized parameters, SQL/bound values and expiry. One server-side review is capped at 64 KiB UTF-8; over-limit proposals are revoked and rejected, never truncated for approval. The existing execution binding cap remains 4096 bytes.
- FastMCP/SDK seals request state. The sealed reference is not a replacement for server-side proposal validation. The raw bearer token is omitted from displayed MRTR review and telemetry. Sealed state should also be treated as sensitive.
- Missing answers resend the same review without extending TTL. Only `accept` plus strict boolean `approve=true` executes. False, decline and cancel consume the pending proposal without executing. Invalid responses never approve.
- The required boolean `approve` field advertises `default=false` as a form initialization hint. It does not supply missing response data or authorize execution. Explicit false uses the refusal path. On October 1, the tested Codex IDE accepted an unchecked submission after this hint was added; the user confirmed the UI action and the server returned `approval_declined` without a database change. This is standard MCP schema metadata, not a Host-specific bypass. Other Host/version combinations still require UI verification; see the [dated acceptance and scope audit](../../REFACTORING_LOG.md#v380-mrtr-approval-form-default-october-1-2026).
- The SDK's sealed-state TTL explicitly follows the configured preview TTL, using an ephemeral key per service instance. Resealing a missing-answer continuation never extends the original server-side proposal expiry.
- Continuations must match the same target, Skill/version and normalized parameters. Execution uses the cached plan and preview binding; it does not rerun preview under an old approval.
- Consumption remains atomic at the execution boundary. Any failure after consumption leaves the token spent. Missing records, concurrent continuations and replay are not evidence that an earlier write did not happen.
- Waiting holds no transaction or row lock. An optimistic precondition may fail between review and execution; row-count mismatch rolls back the managed transaction.

Token state, diagnostics, connections and catalog are instance-owned and in-memory. Shutdown clears pending proposals. Restart cannot recover approvals. There is no distributed or durable completion ledger. Capacity is count-based; with the configured review/binding maxima, administrators should size `max_entries` for memory use rather than blindly choosing the maximum.

Native October 1 testing observed a user-approved continuation after a long wait rejected with `invalid_request_state`; independent reads showed no change. This framework protocol error carries no business `execution_outcome` and does not independently exercise the business TTL branch. A separate real-process stdio regression now verifies old-state rejection before expiry and successful fresh approval after restart; native restart UI behavior remains unverified; see the [acceptance record](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md). No cross-client guarantee follows from this one Host's result.

The reference Host's preview and MRTR flows share an outer approval deadline, a fingerprint of the displayed review (including nested values), and a post-decision expiry check. Late approval, altered review, invalid decisions or provider errors fail closed. Host approval timeout is independent of server token TTL. Cooperative providers are cancelled; a blocking provider or one suppressing cancellation is rejected when it returns, but this is not a hard termination or isolation guarantee against hostile Python. MRTR sends cancellation for these failures; external task/transport cancellation can leave a proposal pending until TTL. No automatic write retry is introduced.

## Outcome and observability

`success` reports handler completion. `execution_outcome` reports transaction evidence: `not_executed`, `rolled_back`, `committed`, `unknown`. A committed write can have `success=false` when notification/serialization fails. Core result construction validates serializability inside the outcome boundary. Later network loss remains uncertain to the caller. Never automatically retry an uncertain write.

Audit remains **best-effort**. It may fail after a write and is not an authorization ledger. Audit may contain business parameters (bounded strings, not universal content redaction); restrict access. Metadata-only tool telemetry omits SQL, params, rows, credentials and token identifiers. An MRTR input-required round has `phase=awaiting_approval` and `success=null`, not business success. Diagnostic busy/draining/cleanup-failed protection is retained. No application result cache is enabled for previews, executes or MRTR.

Waiting and missing-answer MRTR rounds carry the validated target in result metadata; FastMCP stores it under `InputRequiredToolResult.input_required.meta`. Decline/cancel phases are `approval_declined` / `approval_cancelled`. Ordinary results use validated result metadata too; without it, `connection_id` and `db_type` remain null, including early rejections. Telemetry never guesses the default or echoes an unvalidated target. Diagnostics retain their separately validated scope behavior. Sealed-state rejection may occur before middleware and produce no tool telemetry event. These records are not a complete request ledger or a cross-round operation trace.

Database least privilege remains necessary. SQL parsing is a conservative safety filter, not a complete proof of all DB-specific side effects. Read-shaped functions and database-specific behavior retain the existing risk scope. Response truncation is not a database work or peak-memory limit. Synchronous backend work can outlast an outer timeout; reconcile state before retrying.

## Configuration and trusted code

Secrets use exactly one explicit source, have no fallback, and preserve whitespace/newlines. Offline errors and explanation redact secrets. File-based secret size is bounded at 64 KiB. Existing `.env` files and unrelated DB environment variables have no configuration effect through supported entry points. Embedders that import FastMCP beforehand own that import's settings.

Only trusted operators should edit TOML or Skill directories. Source and definition containment prevents accidental directory escapes, including symlinks; Python code can still import files, open connections, or mutate process state. Loading a class is not a sandbox. Definition snapshots mean file edits require restart, not that arbitrary trusted Python becomes immutable or harmless.

Configuration check does not load business code. Service initialization discovers Skills and can reject individual invalid definitions while leaving valid Skills available. Readiness is an availability observation, never an authorization grant. `agent_id` / Host-provided client labels are not authenticated identities.

## MCP Apps result viewer / MCP Apps 结果视图

`apps.enabled` defaults to false. When enabled, the server registers one static `ui://sql-safety-executor/result-viewer.html` resource and binds only `query` and `execute_query_skill` to it. The View is a presentation layer for the result the Host already received; it adds no execution path, and read policy, truncation and write gates are unchanged. `structuredContent` is the same payload that is serialized into the text `content`, so no extra data is exposed to the View and non-Apps Hosts keep the text fallback.

- Every gateway tool (including `execute_mutation_skill` and `request_mutation_approval`) declares `_meta.ui.visibility=["model"]`. Per MCP Apps, the Host must reject View-initiated `tools/call` for these tools. The View also never sends `tools/call`, `resources/read`, `ui/message`, `ui/open-link` or `ui/update-model-context`. It cannot approve, preview or execute a write and is not an approval surface.
- Row values are untrusted database content. The View renders them only through `textContent`; it has no remote scripts, styles, fonts or images. The resource declares an explicit empty `_meta.ui.csp` and the document adds its own restrictive CSP (`default-src 'none'`, `connect-src 'none'`, `frame-src 'none'`, `base-uri 'none'`, `form-action 'none'`). Host CSS variables are applied only as custom properties.
- Iframe sandboxing, CSP enforcement and visibility filtering are Host obligations. A non-conforming Host can ignore visibility; the server cannot verify Host sandboxing. Existing server-side gates still apply to every tool call regardless of its origin.
- FastMCP 4.0.10 advertises `capabilities.extensions["io.modelcontextprotocol/ui"]` on MCP 2026-07-28 for every server, including when `apps.enabled=false` (the SDK strips it on 2025-11-25). With the switch off there are no UI resources or UI metadata to act on; the advertisement is not a grant.

## Accepted limits / 暂缓项

Tasks, remote multi-user auth, independently authenticated approvals, durable/distributed recovery, providers, CodeMode, generic result caching and OTel export are outside this release. Native Host version and observed protocol must be recorded separately from reference Client tests. A legacy client rejection is a compatibility result, not an MRTR approval pass.

### Review presentation

MRTR formats the saved review snapshot as indented Unicode JSON without removing fields or truncating SQL/bindings. The first-line question plus JSON contract remains compatible with the reference Host. Canonical stored bindings and strict approval checks are unchanged. The 64 KiB limit covers the stored review, not the expanded display message. Actual whitespace rendering is Host-controlled and needs native verification; readability changes do not authenticate a human or expand approval authority.

### Rejection recovery clue (v3.8.1)

On `validation_failed` (preview, execute, and MRTR's shared first round), the server may return `related_available_skills`. The list is limited to names in the rejected Skill's own `related_skills` that are mutation Skills executable on the same resolved connection under the same availability checks as `list_skills`: profile, connection scope, database type, every mutation grant and schema readiness. It is computed only after validation fails, issues no token and never changes `success`, `error_code` or `execution_outcome`; lookup failure omits it and logs only the exception class.

The field is advisory. It grants nothing, carries no parameters or sequencing advice, and cannot bypass the rejected rule. Every alternative write keeps its own preview, approval, binding and single-use token, and a multi-step restoration is a series of independent commits, not an atomic rollback. It discloses only names already visible through `list_skills` on that connection, and adds one readiness metadata lookup on qualifying rejections. Author-declared links can be incomplete or unsuitable; Agents may still ignore or misuse them (DRR-2026-071).

Previews return only absolute `preview_token_expires_at`; execute alone enforces expiry. Agents judging validity from their own date can misreport a live token as expired. This is conservative and accepted (DRR-2026-072); a relative-expiry field was not restored.
