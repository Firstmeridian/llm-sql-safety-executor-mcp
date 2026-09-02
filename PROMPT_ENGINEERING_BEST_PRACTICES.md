# MCP Tool Contract and Evaluation Guide

This document is project guidance for designing, reviewing, and evaluating the
model-visible surface of `sql-safety-executor-mcp`. It covers MCP tool names,
input schemas, descriptions, server instructions, result envelopes, and the
evidence used to change them.

The historical filename is retained to avoid breaking existing repository
links; the title reflects the document's narrower current role.

It is **not** a universal prompt-engineering standard and is not an independent
security boundary. Current code, generated MCP schemas, runtime policy, database
permissions, automated tests, and verified live behavior remain authoritative
for what the server actually accepts and does.

**Last reviewed:** September 3, 2026

## Table of Contents

- [1. Scope and Decision Precedence](#1-scope-and-decision-precedence)
- [2. Responsibility by Contract Layer](#2-responsibility-by-contract-layer)
- [3. Tool Interface Design](#3-tool-interface-design)
- [4. Project-Specific Tool Selection](#4-project-specific-tool-selection)
- [5. Safety-Critical Wording](#5-safety-critical-wording)
- [6. Evaluation and Change Workflow](#6-evaluation-and-change-workflow)
- [7. Context and Token Efficiency](#7-context-and-token-efficiency)
- [8. Review Checklist](#8-review-checklist)
- [9. References and Source Quality](#9-references-and-source-quality)

---

## 1. Scope and Decision Precedence

### 1.1 What this guide is for

Use this guide when changing:

- a tool name, purpose, parameter, default, constraint, or return field;
- a FastMCP docstring or `Annotated`/`Field` parameter description;
- MCP server instructions or cross-tool routing guidance;
- compact/full projections, filtering, pagination, or truncation;
- Agent-facing errors, hints, approval wording, or safety claims;
- tests or live evidence intended to justify a tool-surface change.

This guide is narrower than general prompt writing. Tool interfaces are
executable contracts: wording, JSON Schema, runtime validation, and observed
behavior must agree.

### 1.2 Decision precedence

When sources disagree, use the following order as a review discipline rather
than treating any prose document as automatically correct:

1. User intent, accepted security invariants, database authorization, and
   normative requirements of the MCP version actually negotiated or targeted.
2. The intended public contract expressed by runtime behavior and the generated
   MCP `inputSchema`/`outputSchema`. A mismatch here is a defect to resolve, not
   a reason to ignore the protocol or security requirement above it.
3. Automated contract, functional, security, and regression tests plus verified
   live MCP traces.
4. Current official MCP, framework, and model-provider documentation, reviewed
   for applicability to this project and Host/model combination.
5. This guide and other internal heuristics.

Do not weaken an authorization or safety check merely to make a prompt shorter.
Do not preserve inaccurate prose merely because it appears in an older internal
guide. If implementation, machine schema, tests, and documentation disagree,
determine the intended contract and update all affected layers together.

### 1.3 Guidance is contextual

Advice such as “keep it brief,” “use positive instructions,” “use Markdown,” or
“expose fewer tools” is useful only when it improves the measured outcome.
Different Hosts assemble MCP instructions and tool definitions differently, and
models can respond differently to the same wording. Treat provider guidance as
an informed starting point, then validate it with this server's real tool
surface and representative tasks.

---

## 2. Responsibility by Contract Layer

No single prompt or description should carry the whole contract.

| Layer | Primary responsibility | Must not be used as a substitute for |
|-------|------------------------|--------------------------------------|
| Database grants and connection credentials | Authoritative database authorization and blast-radius control | Prompt wording or table-name filtering |
| Runtime policy and business logic | Read/write policy, allowlists, mutation state transitions, token consumption, limits, and fail-closed behavior | Model compliance |
| Python signature, MCP `inputSchema`, and framework validation mode | Parameter names, required/optional status, types, enums, defaults, machine-valid ranges, and whether compatible type coercion is accepted | A prose-only statement of valid inputs or handler-only validation |
| Tool description and parameter descriptions | Purpose, selection boundary, semantic meaning, cost, and important limitations | Runtime input validation or access control |
| MCP server instructions | Concise guidance shared across tools: routing, common workflows, and cross-tool invariants | Tool-specific parameter detail or guaranteed Host behavior |
| Structured result and errors | High-signal data, stable state distinctions, actionable next steps, and sanitized failures | Hidden assumptions that only a human can infer |
| Client/Host UX | Tool visibility, user confirmation, credential isolation, and approval presentation | A server-side `confirm=true` value or preview token |

Additional rules:

- MCP tool annotations are useful behavioral hints, but clients must not treat
  untrusted annotations as proof of safety.
- Server instructions may influence model behavior, but a Host is not required
  to incorporate them in exactly the same way as another Host. Verify the
  actual integration rather than assuming a universal assembled prompt.
- If an output schema is declared, the structured result must conform to it.
  Schema validation still does not solve response relevance or excessive size.

---

## 3. Tool Interface Design

### 3.1 Give each tool a distinct job

A tool should correspond to a natural Agent task, not merely wrap every
low-level API endpoint. Overlapping tools increase selection ambiguity and load
more descriptions into context.

Before adding a tool, ask:

- Does an existing tool already cover the task with one optional projection or
  filter?
- Would the new tool remove a repeated multi-call workflow, or merely duplicate
  it under another name?
- Can the intended user or a new developer choose correctly from the name and
  schema alone?
- Is the tool common enough to expose by default, or should it be optional or
  progressively disclosed?

Do not combine unrelated operations solely to reduce the tool count. A smaller
catalogue is valuable only while tool purposes remain coherent and auditable.

### 3.2 Make invalid parameter states hard to express

Prefer machine-readable constraints over prose-only rules:

- use descriptive parameter names;
- use `Literal`/enum for finite choices;
- declare concrete defaults that match omission behavior;
- use `Annotated` and Pydantic `Field` for descriptions and numeric bounds;
- use nullable types only when `null` has a real public meaning;
- distinguish zero, empty, missing, unavailable, disabled, and failed states;
- validate again at runtime where authorization or business state can change.

Example:

```python
detail_level: Annotated[
    Literal["compact", "full"],
    Field(description="compact for broad planning; full for adapter-visible column metadata"),
] = "compact"
```

The generated `tools/list` schema must be inspected in tests. A correct Python
annotation is not sufficient evidence if the framework emits a nullable or
otherwise different machine schema.

FastMCP uses flexible Pydantic validation by default and can coerce compatible
values such as `"false"` to `False` or `"10"` to `10`. This project enables
`strict_input_validation=True` so MCP calls are checked against the published
JSON Schema before handler execution. Test representative wrong-type JSON
values as well as schema shape; a boolean schema alone does not prove strict
runtime behavior under a framework's default mode. Strict protocol validation
does not replace handler checks for authorization or changing business state,
and direct Python calls bypass it, so public direct-call helpers must validate
decision-critical values explicitly when parity is required.

### 3.3 Write high-signal descriptions

A model-visible tool description should communicate the information needed to
choose and call the tool correctly:

- what the tool does;
- when it is preferable to adjacent tools;
- required parameters and non-obvious parameter effects;
- material cost or side effects, such as an exact `COUNT(*)` or a write;
- important semantic boundaries, such as “adapter-visible metadata, not full
  DDL” or “row count may be null when unavailable”;
- the next action after truncation or a recoverable validation error.

Avoid repeating every parameter in both server instructions and every tool
description. Do not remove a decision-critical boundary merely to satisfy an
arbitrary sentence or token limit.

### 3.4 Prefer conditional guidance to a fixed global priority

There is no universal ordering in which every database request should call the
tools. Use conditional rules:

- known table and columns, free-form read needed: call `query()` directly;
- only table names/counts needed: call `list_tables()`;
- broad columns or multi-table planning needed: call
  `get_full_schema(detail_level="compact")` directly;
- one selected table needs full adapter-visible column metadata: call
  `describe_table()`;
- several tables need nullable/default/key metadata: call
  `get_full_schema(detail_level="full")`;
- exact count is genuinely required: use explicit `COUNT(*)` or the optional
  `get_table_summary(exact_count=true)` with its cost understood;
- connection behavior fails or is uncertain: use `check_connection()`; do not
  make it an unconditional preflight call.

Use a deterministic sequence only when the workflow itself requires one, such
as mutation preview followed by execution with the same bound inputs.

### 3.5 Return useful context, not raw volume

Prefer structured, directly actionable fields. For potentially large results,
use a suitable combination of:

- compact/full projections;
- filtering or targeted lookup;
- pagination or bounded limits;
- truncation with an explicit truncation flag and next-step hint;
- code-side aggregation when the model does not need every raw record.

Errors should be sanitized but actionable. Tell the caller whether it should
correct an argument, choose a connection, request a narrower projection, retry
a preview, or inspect database state. Do not expose credentials, bound values,
internal SQL, or stack traces merely to make an error more detailed.

### 3.6 Formatting and style are tools, not invariants

- Use plain language and the smallest amount of Markdown that materially
  improves structure.
- XML tags or separators can help isolate complex blocks, but are not required
  for short tool descriptions.
- Uppercase labels and repeated emphasis do not create enforcement. Use them
  sparingly.
- Prefer positive instructions for ordinary workflow guidance, but use explicit
  negative wording where a safety boundary would otherwise be ambiguous.
- Reserve “must,” “never,” and “always” for actual protocol, security, or state
  invariants.
- Emojis are not categorically harmful or safe. Omit decorative emojis from
  this project's technical tool surface unless testing shows a functional
  benefit. Do not rely on a universal per-emoji token-cost claim.
- Examples are valuable when they disambiguate input shape or recovery. Remove
  examples that merely repeat the schema or become stale.

---

## 4. Project-Specific Tool Selection

### 4.1 Describe the service accurately

The service has a read-only core SQL surface and optional Skills. Query Skills
run reviewed reads. Mutation Skills, when explicitly enabled and authorized,
can perform controlled writes through a preview/execute protocol. Therefore,
do not describe the entire service as `READ-ONLY`.

A concise service summary should resemble:

```text
Database safety gateway with read-only core SQL tools and configured connection
routing. Use query() for free-form reads; use metadata tools for schema
discovery. Optional Skills provide reviewed queries and, when enabled,
controlled mutations that require preview plus a matching one-time token.
```

### 4.2 Connection routing

- Pass an exact user-provided connection alias unchanged.
- If only a database type is known, use `list_connections()` and select it only
  when exactly one matching alias exists; otherwise ask for the exact alias.
- Do not infer purpose from an alias name.
- Omitting `connection_id` selects the configured default only; it never means
  all connections.
- Read-only requests may iterate explicitly over discovered aliases when the
  user asks for all connections. Never broadcast a mutation.
- Discovering an alias does not grant write permission. Mutation authorization
  is decided by the target connection policy and Skill scope at runtime.

### 4.3 Skills disclosure

- Unknown Skill: use a targeted
  `list_skills(search=..., detail_level="compact", connection_id=...)` call.
- Known Skill with unknown parameters: use
  `get_skill_detail(detail_level="execution", connection_id=...)` directly.
- `list_skills(detail_level="full")` already includes parameter schemas; do not
  automatically follow it with `get_skill_detail()`.
- `available_only=true` is a discovery filter, not an authorization decision.
  Execution repeats the authoritative policy and readiness checks.

### 4.4 Mutation workflow

The mutation sequence is intentionally deterministic:

1. Preview with the intended Skill, parameters, and connection.
2. Present the preview through the client/application's approval UX.
3. Execute once with the returned token and the same bound request.
4. If the token is expired, unknown, consumed, or belongs to another process,
   run preview again; do not reconstruct or retry a write blindly.

The preview token is a short-lived one-time bearer capability, not proof that a
human approved the operation. Human confirmation belongs to the client/Host.
The server must continue to enforce mutation switches, connection policy,
binding, expiry, one-time consumption, optimistic locking, and audit behavior
regardless of prompt wording.

---

## 5. Safety-Critical Wording

### 5.1 Use explicit prohibitions when needed

“Say what to do” is a helpful writing heuristic, not a ban on negative rules.
For example, these prohibitions clarify real boundaries:

- do not send raw write SQL through `query()`;
- do not broadcast mutations across connections;
- do not treat a preview token as human approval;
- do not claim compact schema grouping proves full DDL equivalence;
- do not interpret `row_count=null` as an empty or small table.

Pair a prohibition with the supported alternative when possible. For example:
“Raw `SHOW` is rejected; use `list_tables()` or `describe_table()` for metadata.”

### 5.2 Prompts describe; code enforces

Safety-relevant statements must have an enforcement point and a regression
test. Tool descriptions cannot prevent:

- a direct Python call;
- a buggy or malicious MCP client;
- concurrent calls;
- database changes between discovery and execution;
- a credential with excessive database privileges.

For every safety claim, identify the runtime check, database control, or client
responsibility that makes it true. If none exists, rewrite the claim as a
limitation or implement the missing control before publishing it.

---

## 6. Evaluation and Change Workflow

### 6.1 Validate four evidence layers

1. **Machine contract:** inspect real `tools/list` output for names,
   descriptions, required fields, enum values, nullability, defaults, and
   numeric bounds.
2. **Deterministic behavior:** test valid inputs, invalid inputs, edge states,
   authorization, error classification, response shape, and non-execution on
   rejection.
3. **Agent behavior:** run representative natural-language tasks through the
   intended Host/model and inspect tool choice, arguments, redundant calls,
   recovery, and final answer quality.
4. **Live integration:** use a fresh server process and a disposable or approved
   test database. Record transport, enabled tools, connection profile, whether
   writes were possible, and what was actually observed.

Mock tests, an in-process FastMCP client, a fresh stdio smoke, and a long-running
IDE Host answer different questions. Label them accurately; do not use one as
evidence for another.

Restarting a server process and refreshing a Host's registered tool contract
are separate lifecycle steps. After a contract change, reconnect the MCP server
or reload the Host as required, fetch `tools/list` through that same Host, and
compare the relevant defaults, nullability, enums, bounds, and descriptions.
Do not run Agent tool-selection experiments while the Host still exposes a
stale schema, even if direct calls already reach the new backend behavior.

### 6.2 Use representative and held-out tasks

Include:

- direct queries with known schema;
- unknown-schema discovery;
- broad schema explanation and targeted drill-down;
- invalid enums, missing arguments, boundary values, and unavailable metadata;
- ambiguous connection requests and exact aliases;
- unavailable Skills and policy-denied mutations;
- preview, execute, replay, expiry, concurrency, database failure, and unknown
  write outcome where mutation behavior is in scope.

Run repeated Agent samples for nondeterministic behavior and keep some tasks
held out from prompt tuning. A single successful trace demonstrates possibility,
not reliability.

### 6.3 Measure outcomes, not wording preferences

Useful measures include:

- task completion and factual correctness;
- correct tool and connection selection;
- invalid-argument and recovery rate;
- unnecessary tool-call count;
- model-visible input and tool-result tokens;
- latency and database work;
- truncation frequency;
- unsafe attempt and fail-closed behavior.

Do not optimize solely for prompt length. A slightly longer description is an
improvement when it measurably prevents a wrong connection, expensive count,
redundant full-schema call, or unsafe assumption.

### 6.4 Project evidence

Use these maintained records alongside automated tests:

- [MCP Agent behavior validation](RELEASE_NOTES/GUIDE/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md)
- [v3.6-v3.7 live MCP tests](RELEASE_NOTES/LIVE_MCP_TSET/LIVE_MCP_TEST_V36-V37_ZH.md)
- [Design risk register](DESIGN_RISK_REGISTER.md)
- [Refactoring log](REFACTORING_LOG.md)

These are evidence records, not substitutes for rerunning checks after a tool
contract changes.

---

## 7. Context and Token Efficiency

Tool definitions consume model context in many function-calling integrations,
and large tool results consume additional context. Optimize both definition
size and returned data, but keep decision-critical semantics.

### 7.1 Prefer high-signal reductions

- Remove duplicated explanations from server instructions when the tool schema
  already carries them.
- Keep cross-tool routing in server instructions and tool-specific semantics in
  the tool/parameter description.
- Use compact projections, targeted filters, and bounded output for discovery.
- Return full detail only when the task needs it.
- Aggregate mechanically equivalent records in code when individual records are
  not needed, while disclosing the grouping basis.
- Provide actionable truncation and error hints so the Agent can narrow its next
  call.

Do not assume that symbols such as `→`, uppercase headings, or removing every
example always saves tokens or improves behavior. Tokenization and model
response vary.

### 7.2 Establish a reproducible baseline

Fixed rules such as “every tool description must be under 50 tokens” are not
portable best practices. Record the environment with each measurement:

| Baseline field | Record |
|----------------|--------|
| Host | Name/version, transport, and tool discovery behavior |
| Model | Model/version, sampling settings, and tokenizer used for estimates |
| Tool surface | Enabled tool count and serialized names/descriptions/schemas |
| Instructions | Raw MCP server instructions and, when observable, Host-assembled context |
| Workload | Representative tasks and expected tools/results |
| Outcomes | Calls, input/result tokens, latency, errors, retries, and correctness |

Compare absolute size and relative change against the last accepted baseline.
Treat a large increase as a review trigger, not an automatic failure. Historical
token measurements are observations for their recorded environment, not wire
size or future-model guarantees.

---

## 8. Review Checklist

### Contract consistency

- [ ] Tool name and description have one distinct purpose.
- [ ] Signature, `inputSchema`, prose defaults, and runtime behavior agree.
- [ ] Finite choices use enums/Literals; numeric limits are machine visible.
- [ ] `null`, empty, zero, unavailable, disabled, and failure are not collapsed.
- [ ] Structured outputs conform to any declared `outputSchema`.
- [ ] Tool annotations match behavior but are not treated as enforcement.

### Selection and efficiency

- [ ] Adjacent tools explain when each is preferable without imposing a false
      global ordering.
- [ ] Common tasks do not require redundant discovery calls.
- [ ] Broad outputs have compact/filter/limit/truncation behavior where needed.
- [ ] Full detail remains available for justified drill-down.
- [ ] Errors and truncation tell the caller what safe next action is available.

### Safety and operations

- [ ] Every safety claim maps to code, database authorization, or client UX.
- [ ] The framework validation mode is deliberate, and wrong-type protocol
  inputs plus direct-call bypasses are tested where contract parity matters.
- [ ] Expensive or state-changing parameters are explicit in machine-visible
      descriptions.
- [ ] Rejections occur before SQL, token issuance, or writes where required.
- [ ] Mutation wording distinguishes preview, bearer capability, human approval,
      execution, replay, and unknown outcome.
- [ ] Logs and errors remain useful without leaking SQL values or credentials.

### Evidence and documentation

- [ ] Contract and regression tests cover the change and its edge cases.
- [ ] After server restart, the intended Host reconnects and fetches a current
  `tools/list`; cached definitions are not used as release evidence.
- [ ] Agent evaluation uses representative tasks and repeated samples where
      nondeterminism matters.
- [ ] Live evidence states the exact Host/transport/configuration and whether
      writes occurred.
- [ ] README, release notes, risk register, examples, and test guides are aligned.
- [ ] Official links and version-sensitive claims have a review date.

---

## 9. References and Source Quality

### 9.1 Normative protocol source

1. **Model Context Protocol — Tools specification (current release)**
   - https://modelcontextprotocol.io/specification/2026-07-28/server/tools
   - Defines tool discovery/calls, descriptions, JSON Schema, structured
     content, output-schema conformance, annotations, errors, and security
     responsibilities.

2. **Model Context Protocol — 2025-06-18 Tools specification**
   - https://modelcontextprotocol.io/specification/2025-06-18/server/tools
   - Retained because existing framework/client deployments may negotiate this
     earlier protocol generation.

Normative keywords apply to the protocol version the client and server actually
negotiate or explicitly target. The current specification takes precedence over
blog posts and vendor prompting advice when designing a migration, but a newer
release is not evidence that the installed FastMCP and Hosts already implement
it.

### 9.2 Official implementation and provider guidance

3. **FastMCP — Tools**
   - https://gofastmcp.com/servers/tools
   - Documents how Python signatures, docstrings, `Annotated`, `Field`, return
     types, annotations, and validation become the exposed MCP contract.

4. **MCP Blog — Server Instructions**
   - https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/
   - Useful guidance for cross-tool instructions and Host variability; it is not
     a normative replacement for the MCP specification.

5. **OpenAI — Function calling**
   - https://developers.openai.com/api/docs/guides/function-calling
   - Recommends intuitive functions, enums/objects that exclude invalid states,
     code-side handling of known values, a focused initial tool set, and
     evaluation rather than treating tool-count suggestions as hard limits.

6. **Anthropic — Writing effective tools for agents**
   - https://www.anthropic.com/engineering/writing-tools-for-agents
   - Emphasizes distinct tools, high-signal results, concise/detailed response
     modes, actionable errors, comprehensive evaluation, and held-out tasks.

7. **Anthropic — Define tools**
   - https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools
   - Covers clear tool/parameter descriptions and input schemas for reliable
     selection and invocation.

8. **Anthropic — Building effective agents**
   - https://www.anthropic.com/engineering/building-effective-agents
   - Historical architectural guidance supporting simple systems and adding
     workflows or agentic complexity only when justified. The page itself notes
     that parts of the tooling landscape have changed since its 2024 release, so
     it is not used as current product/API documentation.

9. **Anthropic — Develop tests**
   - https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
   - Supports realistic cases, edge cases, repeated trials, and explicit success
     criteria.

10. **Google AI for Developers — Function calling with the Gemini API**
   - https://ai.google.dev/gemini-api/docs/function-calling
   - Demonstrates descriptive names, typed parameters, required fields, and
     application-controlled function execution.

11. **Microsoft Copilot Studio — Prompt instructions**
    - https://learn.microsoft.com/en-us/microsoft-copilot-studio/microsoft-copilot-extend-action-prompt
    - Recommends clear, specific, testable instructions with enough context and
      a recovery path. Its product-specific limits and UI guidance are not
      universal MCP constraints.

Core links above were rechecked on September 3, 2026. Provider guidance is
model- and product-specific; use it as reviewed input, not as a blanket rule.

### 9.3 Secondary material

12. **Prompt Engineering Guide — General tips**
    - https://www.promptingguide.ai/introduction/tips
    - May provide useful examples, but is secondary material and must not
      override the MCP specification, framework behavior, security design, or
      project evidence.

---

*Document created: December 2025*  
*Reframed as a project tool-contract and evaluation guide: September 3, 2026*
