# v3.8 security boundary / 安全边界

The supported deployment is a trusted local Host and a single server process. MCP annotations describe tools; they are not authorization. The server does not authenticate a human approver, provide remote multi-user identity isolation, or sandbox Python Skills.

本轮沿用可信 Host 审批模式 A。Host 负责可靠呈现审阅内容并收集人的决定；服务端负责目标、Skill、参数、提案绑定及单次消费。恶意或被攻陷的 Host 能伪造批准，不能宣称 MRTR 提供了独立人类认证。

## Authorization

Read access defaults to deny. An explicit allowlist (nonempty) or `all` grants read scope; structural checks still block writes, unsupported syntax, system schemas, file operations, unsafe comments and unauthorized UNION. Raw SQL and Query Skills share the complete policy. Metadata tools obey read scope. Unknown targets never fall back.

Writes require all five configuration gates: Skills, global mutation enablement, admitted target, target mutation enablement, and target Skill allowlist. Skill connection/type/profile restrictions and execution checks remain conjunctive. Read allowlists are not universal mutation allowlists. Authorized previews/readiness checks may inspect mutation business tables even if general reads are denied.

## Proposals and MRTR

- `execute_mutation_skill` retains preview/execute and its opaque 256-bit random bearer handle. Only a digest is used as the token-store key; possession still represents a capability.
- MRTR supports only cached, framework-managed, single-statement plans. Legacy imperative callbacks retain their earlier weaker guarantee and are rejected by MRTR.
- First round validates protocol/form capability, Skill mode and authorization before preparing a proposal. It does not execute the managed write. Custom preview Python is trusted code; the server cannot sandbox a malicious preview callback.
- Review includes resolved target, Skill, normalized parameters, SQL/bound values and expiry. One server-side review is capped at 64 KiB UTF-8; over-limit proposals are revoked and rejected, never truncated for approval. The existing execution binding cap remains 4096 bytes.
- FastMCP/SDK seals request state. The sealed reference is not a replacement for server-side proposal validation. The raw bearer token is omitted from displayed MRTR review and telemetry. Sealed state should also be treated as sensitive.
- Missing answers resend the same review without extending TTL. Only `accept` plus strict boolean `approve=true` executes. False, decline and cancel consume the pending proposal without executing. Invalid responses never approve.
- The SDK's sealed-state TTL explicitly follows the configured preview TTL, using an ephemeral key per service instance. Resealing a missing-answer continuation never extends the original server-side proposal expiry.
- Continuations must match the same target, Skill/version and normalized parameters. Execution uses the cached plan and preview binding; it does not rerun preview under an old approval.
- Consumption remains atomic at the execution boundary. Any failure after consumption leaves the token spent. Missing records, concurrent continuations and replay are not evidence that an earlier write did not happen.
- Waiting holds no transaction or row lock. An optimistic precondition may fail between review and execution; row-count mismatch rolls back the managed transaction.

Token state, diagnostics, connections and catalog are instance-owned and in-memory. Shutdown clears pending proposals. Restart cannot recover approvals. There is no distributed or durable completion ledger. Capacity is count-based; with the configured review/binding maxima, administrators should size `max_entries` for memory use rather than blindly choosing the maximum.

## Outcome and observability

`success` reports handler completion. `execution_outcome` reports transaction evidence: `not_executed`, `rolled_back`, `committed`, `unknown`. A committed write can have `success=false` when notification/serialization fails. Core result construction validates serializability inside the outcome boundary. Later network loss remains uncertain to the caller. Never automatically retry an uncertain write.

Audit remains **best-effort**. It may fail after a write and is not an authorization ledger. Audit may contain business parameters (bounded strings, not universal content redaction); restrict access. Metadata-only tool telemetry omits SQL, params, rows, credentials and token identifiers. An MRTR input-required round has `phase=awaiting_approval` and `success=null`, not business success. Diagnostic busy/draining/cleanup-failed protection is retained. No application result cache is enabled for previews, executes or MRTR.

Database least privilege remains necessary. SQL parsing is a conservative safety filter, not a complete proof of all DB-specific side effects. Read-shaped functions and database-specific behavior retain the existing risk scope. Response truncation is not a database work or peak-memory limit. Synchronous backend work can outlast an outer timeout; reconcile state before retrying.

## Configuration and trusted code

Secrets use exactly one explicit source, have no fallback, and preserve whitespace/newlines. Offline errors and explanation redact secrets. File-based secret size is bounded at 64 KiB. Existing `.env` files and unrelated DB environment variables have no configuration effect through supported entry points. Embedders that import FastMCP beforehand own that import's settings.

Only trusted operators should edit TOML or Skill directories. Source and definition containment prevents accidental directory escapes, including symlinks; Python code can still import files, open connections, or mutate process state. Loading a class is not a sandbox. Definition snapshots mean file edits require restart, not that arbitrary trusted Python becomes immutable or harmless.

Configuration check does not load business code. Service initialization discovers Skills and can reject individual invalid definitions while leaving valid Skills available. Readiness is an availability observation, never an authorization grant. `agent_id` / Host-provided client labels are not authenticated identities.

## Accepted limits / 暂缓项

Tasks, remote multi-user auth, independently authenticated approvals, durable/distributed recovery, providers, CodeMode, generic result caching and OTel export are outside this release. Native Host version and observed protocol must be recorded separately from reference Client tests. A legacy client rejection is a compatibility result, not an MRTR approval pass.
