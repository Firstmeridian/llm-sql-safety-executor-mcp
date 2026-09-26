# LLM Database Safety Gateway - MCP Service

![Version](https://img.shields.io/badge/version-3.8.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)
![MCP](https://img.shields.io/badge/MCP-Protocol-orange)
![AutoGen](https://img.shields.io/badge/Framework-AutoGen-blueviolet?logo=microsoft)

English | [中文](README_ZH.md)
> [Introduction](#introduction) | 
> [Quick Start](#quick-start) | 
> [Best Practices](#best-practices) | 
> [Changelog](#changelog) | 
> [Exposed MCP Tools](#exposed-mcp-tools) | 
> [AutoGen Multi Agent Example](#autogen-multi-agent-example) | 
> [Other Documentation](#other-documentation)  
> [Roadmap](#roadmap) · **v3.8 Update:** FastMCP 4, TOML configuration and optional MRTR approval  

> **v3.8 deployment update**: FastMCP 4, explicit three-file TOML, an installed package and instance-owned state; optional managed MRTR is disabled by default. Legacy `.env` configuration and root launch scripts are retired. See [migration](docs/guides/CONFIGURATION_ZH.md), [implementation decisions](docs/architecture/V3_8_IMPLEMENTATION_ZH.md) and [validation scope](docs/validation/V3_8_VALIDATION_ZH.md).

## introduction

**A secure database access gateway for AI Agents: Empowering LLM (Agents) with database access capabilities.**  
- Enables Large Language Models (LLMs) to query databases safely through standardized MCP interfaces with security-validated SQL.Provides protections such as allowlists, timeouts, and result truncation. Mitigates operational risks while preventing token cost overruns.  
- In addition to MySQL and SQLite, support for NoSQL is also planned. (work in progress for a future release)  
- Furthermore, this project supports server-side, plugin-style operation extensions inspired by Agent Skills. Users or developers can write reusable pre-defined parameterized operations (queries and controlled writes) to extend capabilities, managed uniformly through `skill_def.md`. Agents can discover and invoke them on demand to handle complex queries, sensitive mutations, and specific business workflows.  

This project resolves the LLM database accessibility bottleneck. By coordinating with AI Agents, it expands the capability boundaries of LLMs and extends the application scope of large models in real-world business scenarios.

## Problem Statement

### Original Challenges
Traditional LLM-database integration faces the following limitations:
- **Security Risks**: LLM-generated SQL may contain dangerous operations (DELETE/UPDATE/DROP).
- **Token Explosion**: Large table queries returning massive amounts of data, leading to context overflow and uncontrolled costs.
- **Tight Coupling**: Database logic intertwined with LLM prompts and orchestration code, making maintenance and reuse difficult.
- **Query Quality**: Without table structure information, LLMs are prone to generating invalid or inefficient SQL.
- **Scalability**: Inability to guarantee personalized database connections and security configurations needed for each LLM instance.

### Design Goals
- Enable conservatively filtered SQL query execution for AI models (the MCP
  policy accepts one `SELECT`, `DESCRIBE`, or non-ANALYZE `EXPLAIN`; use schema
  tools instead of raw `SHOW`).
- Prevent Token Explosion: Result truncation (`limits.result_rows`) + Table count limits (`limits.overview_tables`).
- Provide a standardized MCP interface across different AI platforms.
- Support ReAct Pattern: Provide table structure information for LLM decision-making.
- Configurable Security Policies: Allowlists, timeouts, UNION control.
- Extensible Operation Capabilities: Support for complex and sensitive change scenarios through skills-based operation extensions.

## Solution

### Service Architecture

This project implements a standard MCP (Model Context Protocol) service to provide secure database access for LLMs:

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Client                               │
│         (VS Code Copilot / Claude Desktop / Gemini CLI)         │
└─────────────────────────┬───────────────────────────────────────┘
                          │ MCP Protocol (stdio)
                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                   sql-safety-executor (MCP Server)                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │ Tool Layer:   list_connections | query | list_tables | describe_table  │ │
│  ├─────────────────────────────────────────────────────────────────────────┤ │
│  │ Skills Layer (Optional): list_skills | get_skill_detail                 │ │
│  │                         | execute_query_skill | execute_mutation_skill  │ │
│  │    skill_def.md → Param Validation → Pre-built SQL/Mutation → Audit Log │ │
│  ├─────────────────────────────────────────────────────────────────────────┤ │
│  │ Safety Layer: SQL Validation | Allowlist | Truncation | Timeout         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬────────────────────────────────────────────────────┘
                          │ SQLAlchemy (Connection Pool)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                           Database                              │
└─────────────────────────────────────────────────────────────────┘
```

### Core Design

**1. Security Validation**: The MCP policy allows one SELECT/DESCRIBE or
non-ANALYZE EXPLAIN form on the supported MySQL/SQLite adapters, while rejecting
raw SHOW, write DML,
nested write-DML CTE text, executing `EXPLAIN ANALYZE` forms, and MySQL comment
forms whose server semantics differ from generic comment stripping. This is a
conservative gate, not comprehensive SQL semantic analysis for arbitrary dialects.

**2. Token Protection**: Result truncation (`limits.result_rows`) + Table count limits (`limits.overview_tables`).

**3. Tool Design**:
- Adopts a Model-driven pattern, prioritizing decision rules over fixed workflows.
- Tools return context like `is_large`/`row_count` to enable LLM autonomy.
- MCP `ToolAnnotations` include read-only/destructive/idempotent hints plus `openWorldHint=false`, reflecting that tools operate inside the configured database boundary rather than arbitrary external systems.
- Skills execution tools return structured business payloads and attach
  `ToolResult.meta` runtime metadata (for example elapsed time, row counts,
  truncation state, and Skill version) for debugging and observability.
- Supports configuration-based policy/prompt injection (e.g., read.allow_union, read.tables, truncation thresholds), using shorter, more relevant guidance to reduce invalid tool calls.
- Error feedback optimized for LLMs: Clearly identifies failure reasons (security blocking/table not allowed/syntax/timeout/truncation, etc.) and offers correction suggestions, reducing trial-and-error and invalid calls while avoiding leakage of sensitive information (credentials, system table details, etc.).
- Adapted for ReAct Pattern: Thought → Action → Observation → Rethink.

**4. Skills Extension Layer** (Optional, enabled with `skills.enabled=true`):
- Pre-defined parameterized operations: Encapsulate complex queries and sensitive writes as reusable skills — Agents only need to pass parameters, no need to write SQL
- Server-side enforcement: SQL safety checks at startup + strong parameter type validation (type/min/max/enum) + best-effort audit state for write operations
- Two-phase write protocol: Mutation skills require preview (`confirm=false`) → execute with the returned `preview_token` (`confirm=true`) to bind the reviewed request/state and reject replay or preview/execute drift. Human approval exists only when a trusted client presents the preview and collects it; see the v3.8 preview/MRTR Host example.
- Transaction outcomes (v3.7.2): built-in single-statement mutations enforce
  `expected_rowcount=1` before COMMIT. Structured results separate tool
  `success` from `execution_outcome` (`not_executed`, `rolled_back`,
  `committed`, or `unknown`); hosts must never retry an uncertain execute.
  Only preserved adapter COMMIT evidence can produce `committed`. An ordinary
  custom-Skill success is conservatively `success=true, unknown`.
- Progressive disclosure: Agents can search a lightweight catalog with
  `list_skills()`, request `get_skill_detail(detail_level="execution")` only
  when a known Skill's params are still unknown, and execute directly when the
  params are already available (including from `list_skills(..., detail_level="full")`).

**5. Typical Workflow**:
```
Structure Unknown: names/counts only → list_tables()
                   broad columns → get_full_schema(detail_level="compact") directly
                   one target table → describe_table(target) → query(sql)
Structure Known: query(sql) directly
Large Table Scenario: Observe is_large=true → Use LIMIT or Aggregation
Skills Scenario: unknown Skill → list_skills(search=..., detail_level="compact", connection_id=target)
                 → get_skill_detail(skill_name=..., connection_id=target, detail_level="execution") when needed
                 known Skill + unknown params → get_skill_detail(skill_name=..., connection_id=target, detail_level="execution")
                 known params → execute_query_skill(skill_name, params, connection_id=target)
                 or mutation preview → user approval → same params/connection_id + returned preview_token
```

### Safety Features
- **Query Restrictions**: On the supported MySQL/SQLite adapters, the full MCP
  policy accepts exactly one SELECT, DESCRIBE, or non-ANALYZE EXPLAIN. Raw SHOW
  is rejected; use `list_tables()`/`describe_table()` for metadata. Nested write
  DML, `EXPLAIN ANALYZE`, executable comments/hints, and ambiguous
  non-whitespace `--` forms are rejected.
- **SQL Parsing Validation**: Statement-type allowlist via `sqlparse` plus the complete core query policy.
- **Connection Security**: Explicit TOML and secret-source configuration. Named connections (`connection_id`) without accepting arbitrary DSNs from tools or model output.
- **Error Isolation**: Comprehensive exception handling and reporting tailored for LLMs.
- **Access Isolation**: Access boundaries controlled by the host/runtime environment.
- **Table Allowlist**: Configurable restrictions on readable tables.
- **Database Authorization Remains Authoritative**: The SQL checker is a
  conservative statement-shape/application-policy gate, not a proof that every
  `SELECT` is side-effect free. MySQL stored functions and functions such as
  `GET_LOCK()` can have effects not visible from the outer statement type.
  Production read aliases should have object-level `SELECT` only and should
  not receive unnecessary `EXECUTE`, `FILE`, `PROCESS`, administrative, or
  cross-schema privileges. Keep mutation credentials separate where practical.
- **Result Truncation**: `limits.result_rows` / `limits.result_chars` to prevent Token overflow.
- **Timeout Controls**: `timeouts.query_seconds` limits read queries and MySQL InnoDB mutation row-lock waits; it is not a guarantee for all long-running DML CPU/IO work.
- **UNION Control**: Disabled by default; enabling requires an explicit valid read scope.

#### Skills-Related
- **Skills Template-as-Allowlist**: SQL templates are validated for read-only shape at startup, cached in memory, and re-checked against target-connection policy at runtime — no runtime reread of cached definitions (limits definition-file TOCTOU)
- **Skills Strong Parameter Validation**: type/min/max/enum constraints + rejection of parameters outside schema (prevents injection/hallucination)
- **Skills Dual-Layer Switches**: `skills.enabled` + `skills.mutation.enabled`, plus global connection admission and connection-level mutation/Skill authorization
- **Closed-World Tool Hints**: MCP tools set `openWorldHint=false` because they interact with the configured database/server boundary, not arbitrary external entities. These hints improve client UX but are advisory, not security controls. **Future-tool checklist**: any newly added tool that reaches outside the configured database (external HTTP APIs, webhooks, third-party services, cross-instance DB calls, etc.) MUST set `openWorldHint=true` and be reviewed against this list; `tests/test_annotations_consistency.py` provides a pytest/local-test guardrail through an explicit allowlist. The v3.8 CI workflow includes these tests; local passage does not claim a remote CI run.
- **Skills Runtime Metadata**: Ordinary tool responses wrap their structured payloads in `ToolResult` and expose runtime `meta` fields (`tool_name`, `execution_ms`, `success`, plus tool-specific counters). Single-connection results include `db_type` and `connection_id`; batch diagnostics use `connection_scope="all"` and aggregate counts without a default-connection identity. Mutation results also mirror `execution_outcome` and structured-failure `error_code`. Metadata intentionally excludes raw SQL, returned rows, parameter values, DSNs, credentials, hosts, and SQLite file paths.
  - **Raw SQL visibility policy**: The raw `query(sql)` tool currently echoes the submitted SQL in its structured payload and may log it through the tool context for transparency and debugging (service logs on modern protocols; client logging notifications on legacy protocols). Do not place secrets, tokens, credentials, or sensitive personal data in SQL literals. Use reviewed Skills, low-sensitivity predicates, or database views for repeatable sensitive workflows.
  - **Scope (v3.5)**: Uniform `ToolResult.meta` across base tools (`list_connections`, `query`, `check_connection`, `list_tables`, `describe_table`, `get_full_schema`, `get_table_summary`, `sample`) **and** Skills tools (`list_skills`, `get_skill_detail`, `execute_query_skill`, `execute_mutation_skill`). Base tools use the shared `_tool_result(...)` helper; Skills tools use `_skill_tool_result(...)`. Core services return `OperationResult`, converted at the MCP boundary. Direct Python callers can read `result.structured_content` for the payload and `result.meta` for metadata uniformly.
  - **Client visibility**: Per MCP spec, the `_meta` field is OPTIONAL and clients MAY ignore it. Real-world behavior varies: server-side middleware, MCP Inspector, and clients that explicitly surface `_meta` will see runtime metadata; VS Code's MCP UI (as of testing) does not display it. Treat `ToolResult.meta` primarily as a server-side observability hook and an opt-in client signal, not as a guaranteed user-visible diagnostic.
  - **Minimal example** (see the [historical envelope examples](docs/guides/TEST_MCP_CLIENT_GUIDE_v3_7.md) and the [current client guide](docs/guides/TEST_MCP_CLIENT_GUIDE.md)):

    ```jsonc
    // execute_query_skill response
    {
      "structuredContent": { "success": true, "skill_name": "sample-monthly-sales-report",
                              "data": [/* rows */], "row_count": 2, "total_rows": 2,
                              "truncated": false, "truncation_note": null },
      "_meta": { "tool_name": "execute_query_skill", "success": true,
          "skill_name": "sample-monthly-sales-report", "skill_type": "query",
          "mode": "query", "execution_ms": 12.3, "row_count": 2,
                  "total_rows": 2, "truncated": false, "audit_logged": false,
                  "db_type": "mysql", "connection_id": "trade_analysis_mysql", "idempotent": true, "skill_version": "1.0.0" }
    }
    ```

  | Level | Configuration | `skills.enabled` | `skills.mutation.enabled` | Available Tools | Permission |
  |:---:|------|:---:|:---:|------|------|
  | L0 | Default | `false` | — | Base tools (query, list_tables, etc.) | Reads require explicit authorization |
  | L1 | Skills enabled | `true` | `false` | + list_skills, get_skill_detail, execute_query_skill | + Pre-defined read-only skills |
  | L2 | Mutations enabled | `true` | `true` | + execute_mutation_skill | + Controlled writes after target authorization (two-phase preview/execute gate) |

- **MRTR (optional)**: The full configuration exposes up to 13 tools. Approval waiting returns `InputRequiredResult`; telemetry records `phase=awaiting_approval`, `success=null`. Continuations share the same proposal/execution service; waiting is not business success.
- **Skills Two-Phase Preview/Execute Gate**: Write operations require a matching server-issued preview token; this prevents replay and drift but is not proof of human approval without a trusted client workflow
- **Skills Audit Logging**: Mutation preview/execute paths attempt best-effort JSONL audit logging; normal tool results report `audit_logged`

### Key Components

Runtime code lives in `src/sql_safety_executor/`:

| Module | Responsibility |
|---|---|
| `config/` | Strict TOML, secret resolution and configuration provenance |
| `core/` | Complete read policy, query services, proposals and mutation execution |
| `database/` | MySQL/SQLite adapters, connection registry and transaction evidence |
| `skills/` | Trusted Skill SDK, definition loading, discovery and readiness |
| `mcp/` | FastMCP factory, tool registration, encoding and MRTR |
| `prompts/` | Packaged instructions, routing guidance and tool descriptions |
| `observability/` | Audit and sanitized tool telemetry |
| `cli.py` | Explicit startup and offline configuration check/explain |

The root `skills/` directory still holds business definitions. Public factories are `load_config(path)` and `create_server(config)`. Basic imports do not connect, import business Skills or create logs. Configuration, connections, catalog snapshots, proposals and diagnostics belong to a service instance and are cleaned up by its lifespan. See [v3.8 implementation decisions](docs/architecture/V3_8_IMPLEMENTATION_ZH.md).

## Design Philosophy
### Motivation: LLM/Agent-Based User Interface
The philosophy of this project originated in early 2025, partially influenced by GraphQL. Initially, the plan was for LLMs or Agents to serve as a frontend entry point, fetching information from the backend through explicit semantics.
In reality, SQL itself is an excellent carrier for query information. Rather than passing GraphQL, it is better to pass SQL directly. Especially since current mainstream LLMs (as of late 2025) can generate common SQL quite stably without additional fine-tuning.
However, three key issues need to be considered:
1. Potential SQL Injection.
2. The uncertainty of LLMs themselves: The safety of generated SQL.
3. The accuracy, quality, and efficiency of the generated SQL queries.

**Regarding Issue 1:**
This is not a case of a frontend directly sending SQL to a backend for execution. Here, LLMs (Agents) behave more like server-side programs. SQL is generated in a controlled server environment, with stdio as the recommended mutation transport. Conditional private HTTP use has the single-process and trust-boundary limits documented below; v3.8 still does not define multi-user authenticated HTTP mutation. Agents remain programs with constrained inputs and outputs, but prompt injection defenses complement rather than replace server-side policy and authorization.

**Regarding Issue 2:**
LLM generation is uncertain. Even with a very low probability, this can lead to generated SQL safety not being guaranteed. A SQL safety check tool is needed to inspect and filter generated SQL.

**Regarding Issue 3:**
LLMs (Agents) cannot generate SQL out of thin air; they need a certain context foundation. This context can be natural language prompts or database documentation, but more importantly, database structure, query examples, and the data itself. For high-quality queries, as things stand (end of 2025), a ReAct approach should be adopted: a cycle of Thought --> Action --> Observation --> Rethink to decide the next action.

**In summary, this project is the solution to Issue 2 and Issue 3.**

### Project Evolution
Early on, the goal was to build a simple SQL safety checker that could inspect and filter SQL statements before execution, to be invoked by LLMs (Agents) through function calling.

- Later, [in version (v1.0)](docs/architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md), the solution was refactored to add support for the standardized MCP service architecture. Decoupling was also performed to simplify maintenance while enhancing security and scalability.

- [In version (v2.0)](REFACTORING_LOG.md), optimizations for query efficiency and call risks were made for actual MCP usage scenarios.
  1. Optimized tool call efficiency by merging tools and adding new commonly used tools to reduce the number of tool calls.
  2. Focused on specific optimizations for Token Explosion risks in real-world usage (which can lead to massive LLM API costs).
  3. Added [examples of multi-Agent calls to this MCP service](README.md#autogen-multi-agent-example), based on the AutoGen framework, to demonstrate the combination of Agents and this service.

- [In version (v2.1)](REFACTORING_LOG.md#update-v21-january-4-2026---tool-optimization--field-naming), the focus was on improving tool design and output consistency. Many tools were optimized and refactored to adhere as closely as possible to industry best practices. The overall design adopts the ReAct paradigm (Thought --> Action --> Observation --> Rethink) loop. This improves query accuracy and multi-step query quality while ensuring query efficiency. The AutoGen-based multi-agent example was also updated synchronously.

Through these iterations, this project evolved from an initial concept of an LLM/Agent-based user interface to an MCP-supported comprehensive SQL query service. It is worth acknowledging that although the starting point was different, the current project actually shares similarities with current Text2SQL solutions.  
In the early conception of this project (March-April 2025), such systems were relatively rare. At that time, similar Text2SQL practices were mainly stuck in the context of receiving prompts from relevant personnel and the LLM generating SQL statements once to assist their queries. The core motivation of this project is **to enable LLMs (Agents) to replace traditional frontends and become the new "frontend", capable of dynamic interaction with users regarding both the data in the interface and the interface itself.** Making the entire system fully flexible and dynamic.  
For now, **the core idea of this project is to empower LLMs (Agents) with the ability to enter the database.** Combined with different Agents, different work scenarios can be developed and extended.


- [In v3.8](docs/releases/RELEASE_NOTES_v3_8.md), FastMCP 4 and the installed package separate runtime state, explicit TOML and prompt resources. Optional managed MRTR extends the retained preview/execute workflow.

### Roadmap
**Agent Skills and Extensibility**
**Skills extension layer added in v3.0** (March 2026). See [MCP_AGENTS_SKILLS_DESIGN.md](docs/architecture/MCP_AGENTS_SKILLS_DESIGN.md) for details.
In existing practices, we realize the significance of providing (encapsulated) specific semantic tools. The industry also has corresponding best practice discussions:
> "Offload the burden from the model and use code where possible."  
> "Don't make the model fill arguments you already know."  
> "Combine functions that are always called in sequence."
> [— OpenAI, "Best practices for defining functions" (December 2025)](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions)

This indicates that in reasonable cases, a practical system should include and support adding extra tools tailored for specific scenarios. However, too many tools consume more context, reduce accuracy, and increase costs[1]. Progressive disclosure[2] of Agent Skills can avoid these issues.
Therefore, we can envision a scheme where users or developers can write a large number of "plugins" (code snippets/tools) dependent on this MCP service, managed via skill_def.md, allowing for dynamic addition and configuration of tools. Agents can then load these "plugins" to flexibly extend their capabilities.
Of course, unlike standard Agent Skills, this project's Skills provide pre-built, safety-constrained operations that the server executes on the Agent's behalf. This difference is intentional, primarily for [security considerations](README.md#skills-design-considerations).

> [1]: ["Keep the number of functions small for higher accuracy."](https://platform.openai.com/docs/guides/function-calling)  
> [2]: ["This filesystem-based architecture enables progressive disclosure: Claude loads information in stages as needed, rather than consuming context upfront."](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#how-skills-work)

**Support for Multiple Database Types (SQLite, NoSQL, etc.)**  
- **SQLite support added in v2.2** (January 2026)
- NoSQL support planned for future releases

**Manually Defined Methods for Database Write Processes**  

**Refined Permission Management Based on MCP Protocol**  

### Skills Design Considerations

This project's Skills layer borrows some design elements from [Anthropic Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) (directory structure, YAML frontmatter, name conventions), but **does not adopt the standard Agent Skills format. This is an intentional design decision for the following reasons:**

**1. Fundamentally Different Execution Model**

Standard Agent Skills assume the Agent has a code execution environment and file system access (VM / sandbox) — the Agent reads SKILL.md instructions and writes/executes code itself [1], [2]. This project is an MCP Server: the Agent calls remote tools via JSON-RPC and cannot `bash: cat skill_def.md` [5]. The standard Skills' three-level progressive disclosure (Agent reads files on demand via bash) is neither feasible nor meaningful in an MCP architecture [1].

**2. Different Trust Boundaries**

Standard Agent Skills trust the Agent to correctly follow instructions [1] — e.g., SKILL.md says "use pdfplumber to open file", and the Agent writes Python code to do so [2]. This project deals with database write operations and cannot trust the Agent to act freely:
- SQL must pass `is_sql_safe()` validation
- Parameters must be validated by strong typing (type/min/max/enum), not natural language understanding
- Mutations (INSERT/UPDATE/DELETE) use reviewed Skill classes: declarative
  `ManagedMutationBase` for one framework-executed statement, or trusted
  imperative `MutationBase` with conservative `unknown` outcome semantics
- Mutation preview/execute paths attempt best-effort audit logging on the server side

Standard Agent Skills lack these mechanisms because their design assumption is "Agent operates freely in a controlled VM", while this project's assumption is "**Agent is untrusted, Server enforces all security constraints**".

**3. TOCTOU Security Requirements Conflict with Lazy Loading**

Standard Agent Skills use on-demand loading (Agent reads files at runtime via bash) [1], [2], meaning files can be tampered with at any time. For document-processing Skills this is irrelevant, but for SQL templates and mutation code, reading from disk at runtime introduces TOCTOU (Time-of-Check-Time-of-Use) risk [4]. This project's full pre-loading (`discover()` validates at startup + caches to memory, no runtime reread of cached definitions) is an intentional security design that directly conflicts with the standard Skills' lazy model.

**4. Standard Skills "Teach Agent How to Do" vs. This Project "Does It for Agent"**

| Standard Agent Skills | This Project's Skills |
|---|---|
| SKILL.md tells Agent "use this library, follow these steps to process PDF" | `query.sql` / `mutation.py` are **executable artifacts**, not instructions |
| Agent generates and executes code itself | Server executes pre-built SQL/Python, Agent only passes parameters |
| Skill is a knowledge package | Skill is an action template |

Converting to the standard format would mean turning SQL templates into "instruction documents" for the Agent to write SQL itself — which is exactly what this project aims to prevent.

**5. Valuable Elements Borrowed from Standard Skills**

This project has already incorporated design elements from standard Agent Skills that are applicable to MCP scenarios:
- Directory structure: one folder per skill + entry file;
- YAML frontmatter: `name` (with regex constraint `^[a-z0-9][a-z0-9-]*$`) and `description` [3];
- Progressive interaction: MCP-level progressive interaction (`list_skills()` → `get_skill_detail()` → `execute_*_skill()`);
- Composability: `related_skills` field for composability.
Elements that don't apply (SKILL.md body as Agent instructions, bash file system access, Agent self-executing scripts) were not adopted.

> **References**  
> [1] [Anthropic, "Agent Skills — Overview", 2025. Describes standard Agent Skills' three-level progressive disclosure, VM execution environment, and file system architecture.](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)  
> [2] [Anthropic, "Equipping agents for the real world with Agent Skills", 2025. Details the SKILL.md format, Agent's file loading mechanism via bash, and Skills' positioning as "knowledge packages".](https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills)  
> [3] [Anthropic, "Agent Skills — Best Practices", 2025. Contains name field constraints (≤64 chars, `^[a-z0-9-]+$`) and description specifications.](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)  
> [4] [MITRE CWE-367: "Time-of-check Time-of-use (TOCTOU) Race Condition". Standard definition of the TOCTOU security risk referenced in point 3.](https://cwe.mitre.org/data/definitions/367.html)  
> [5] [Model Context Protocol Specification, "Architecture — Transports". MCP uses JSON-RPC 2.0 over stdio/SSE, Agent interacts with Server via tool calls, no file system access.](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)

#### Skills Security Considerations

**Security Model Overview**

The following diagram shows the four security layers a request passes through from Agent to database:

```mermaid
flowchart TB
    subgraph Agent["Agent Side (Untrusted)"]
        A1["LLM Agent<br/>(Claude / GPT / etc.)"]
    end

    subgraph MCP["MCP Protocol Boundary"]
        direction TB
        T1["query(sql, connection_id?)"]
        T2["execute_query_skill(skill_name, params, connection_id?)"]
        T3["execute_mutation_skill(skill_name, params, confirm,<br/>preview_token?, connection_id?)"]
        T4["list_skills(connection_id?) / get_skill_detail(connection_id?) /<br/>describe_table(connection_id?) / ..."]
    end

    subgraph Server["MCP Server Safety Layer (Trusted)"]
        direction TB

        subgraph S1["Layer 1: Input Validation"]
            V1["is_sql_safe()<br/>Read forms only; no EXPLAIN ANALYZE"]
            V2["_is_query_safe_extended()<br/>Block system tables/UNION/subqueries"]
            V3["_check_table_allowlist()<br/>Table-level access control"]
            V4["validate_name()<br/>^a-z0-9- prevents path traversal"]
            V5["validate_params()<br/>type/range/enum constraints"]
        end

        subgraph S2["Layer 2: Execution Control"]
            E1["query.sql template<br/>Pre-validated at startup via is_sql_safe()"]
            E2["Parameterized binding<br/>SQLAlchemy text() + params"]
            E3["mutation: validate()<br/>Business rule validation"]
            E4["mutation: preview()<br/>Dry-run preview"]
            E5["mutation: execute()<br/>Execute within transaction"]
        end

        subgraph S3["Layer 3: Runtime Protection"]
            R1["QUERY_TIMEOUT<br/>Timeout interruption"]
            R2["limits.result_rows/CHARS<br/>Result truncation"]
            R3["_handle_error()<br/>Error message sanitization"]
            R4["skills.directory containment<br/>Sources stay inside the declared trusted root"]
        end

        subgraph S4["Layer 4: Audit & Visibility"]
            AU1["AuditLogger<br/>JSONL audit log"]
            AU2["Catalog snapshot<br/>Optional overview export"]
            AU3["ToolContext<br/>Modern logs / legacy notifications"]
        end
    end

    subgraph DB["Database"]
        DB1["MySQL / SQLite"]
    end

    A1 -->|"MCP tool call"| T1 & T2 & T3 & T4

    T1 -->|"Raw SQL"| V1 --> V2 --> V3 --> E2 --> R1 --> R2
    T2 -->|"skill_name + params"| V4 --> V5 --> E2 --> R1 --> R2
    E1 -.->|"Pre-validated at startup<br/>ensures template safety"| E2
    T3 -->|"skill_name + params + confirm"| V4 --> V5 --> E3 --> E4 & E5

    E2 --> DB1
    E5 -->|"Transaction"| DB1
    E5 --> AU1

    DB1 -.->|"On exception"| R3 -.->|"Sanitized error"| A1
    R2 -->|"Truncated result"| A1

    style Agent fill:#fee,stroke:#c33
    style Server fill:#efe,stroke:#3a3
    style DB fill:#eef,stroke:#33c
    style MCP fill:#ffd,stroke:#aa3
```

**1. The Implicit Trust Model of Standard Agent Skills**

The execution flow of standard Agent Skills is:

```
User request → Agent reads SKILL.md → Agent writes code → Agent executes in VM
```

The Agent **is both the decision-maker and the executor**, and security relies on:
- VM sandbox isolation (network, file system restricted)
- Agent will "follow instructions" and operate as directed
- Skills sources are trusted (officially recommended to use trusted sources only)

This is sufficient for document processing (PDF/Excel) — worst case is generating an incorrect file in the sandbox.

**2. This Project's Threat Model Is Completely Different**

This project's execution flow is:

```
User request → Agent calls MCP tool → MCP Server executes pre-built SQL → Production database
```

**Attack surface includes:**
- **Prompt injection**: Malicious user input may induce Agent to pass dangerous parameters
- **Agent hallucination**: Agent may "creatively" call non-existent skills or pass out-of-bounds parameters
- **TOCTOU**: If SQL is read from disk at runtime, an attacker modifying the file can inject arbitrary SQL
- **SQL injection**: Improper Agent parameter concatenation directly threatens production data

If the standard Agent Skills model were adopted, it would mean letting the Agent read SQL templates, concatenate parameters, and decide execution itself — **every one of the above security checkpoints would disappear**.

**3. This Project's Defense in Depth Is Incompatible with Standard Skills**

| Security Mechanism | This Project's Implementation | Under Standard Skills |
|---|---|---|
| **SQL Allowlist Validation** | `is_sql_safe()` validates at startup; unsafe skills are rejected from registration | Agent reads SQL files at runtime and executes them, bypassing validation |
| **Strong Parameter Validation** | `validate_params()` enforces type/min/max/enum | Agent understands parameters from natural language, no hard constraints |
| **Anti-Parameter Injection** | Rejects parameters outside schema (`unexpected` check) | Agent decides what parameters to pass |
| **TOCTOU Protection** | Loaded into memory at startup, no runtime reread of cached definitions | Agent reads files via bash each time, files may have been tampered with |
| **Mutation Transaction Safety** | Adapter enforces BEGIN→UPDATE→pre-COMMIT rowcount check→COMMIT/ROLLBACK and reports uncertainty | Agent writes transaction code itself, may miss rollback or misclassify COMMIT failure |
| **Audit Logging** | Mutation preview/execute paths attempt best-effort writes to `skills.audit.path`; normal results report `audit_logged` | Depends on Agent voluntarily calling logging (unreliable) |
| **Confirmation Mechanism** | Server enforces preview → one-time bound token → execute; optional preview/MRTR Host collects exact `APPROVE`, without proving human identity to the server | Agent decides whether to confirm, with no hard server-side preview/replay boundary |

The standard Agent Skills security model is **"sandbox isolation + trust Agent"**. This project's security model is **"do not trust Agent, Server enforces all security constraints"**. Converting to standard Agent Skills would mean handing security control from the Server back to the Agent — in a production database scenario, this is a downgrade, not an upgrade.

### Experience with AI-Assisted Development (Copilot, Vibe-Coding)
This project was originally created by Gemini CLI and primarily developed using GitHub Copilot after v1.0.
When using AI to assist in developing this project, the following experiences were generally followed:
1. Follow best practices on the web and GitHub as much as possible, such as those from Anthropic, Google, FastMCP, and Microsoft. Avoid hallucinations and local optima.
2. Make the AI reflect on its own output as much as possible.
3. Under the premise of satisfying 1 and 2, minimize constraints on the AI. Use the simplest prompts and steps to complete tasks, and let the AI complete the full workflow.
> Keep context as full and complete as possible; keep prompts and constraints to a minimum.

This is why although the original GEMINI.md is retained, it is only for record-keeping, and AGENTS.md was not added. However, skill_def.md or similar "progressive" documentation is good practice. The project's related documents [REFACTORING_LOG.md](REFACTORING_LOG.md) and [PROMPT_ENGINEERING_BEST_PRACTICES.md](docs/guides/PROMPT_ENGINEERING_BEST_PRACTICES.md) reflect this practice.

### Risks and Limitations
In the practice of writing this project, a large amount of AI-assisted development was used. Although code reviews and tests have been conducted as much as possible, and a series of security settings have been added, with limited resources, it cannot cover all situations, especially considering the involvement of LLMs.
**Therefore, do not directly connect to a production environment or pair with an Agent without testing. This may lead to unexpected consequences!**
Rashly connecting an untested Agent may lead to **instability, infinite loops, Token explosion, massive queries**, or other unverified negative effects.
In recent updates, multiple efficiency optimizations have been carried out for this project, mainly focusing on reducing unnecessary tool call counts and increasing speed. Certain tests have been performed. However, due to the randomness of LLMs (Agents), unnecessary tool calls may still occur in actual use, although the probability is small.

### Known Issues and Limitations
- **Tool inputs are schema-strict at the MCP boundary**: the server enables FastMCP `strict_input_validation`, so values such as `"false"` for a boolean or `"10"` for an integer are rejected rather than coerced. Omitted optional parameters still use their declared defaults. Direct Python calls do not pass through MCP validation; decision-critical direct-call parameters have matching handler checks where supported.
- **Refresh tools after a contract upgrade**: restarting the MCP server and refreshing an IDE Host's registered `tools/list` are separate steps. Reconnect the server or reload the Host window after tool names, descriptions, schemas, or defaults change, and verify the schema from that same Host before Agent behavior testing.
- **Row count fields may be imprecise**: `list_tables()` / `describe_table()` / `get_full_schema()` and `get_table_summary(exact_count=false)` return `row_count` as estimates:
  - **MySQL**: from `INFORMATION_SCHEMA.TABLES.TABLE_ROWS` (InnoDB may have significant deviation or lag)
  - **SQLite**: from `sqlite_stat1` (if ANALYZE has been run) or bounded 10,000-row sampling; if the sample cap is reached, the value is a lower-bound estimate unless statistics exist
  - An individual `row_count` can be `null` when the adapter cannot safely provide an estimate; `null` means unknown, not an empty table. In that case, single-table tools also return `row_count_approximate=null` and `is_large=null` rather than classifying the table as small. This includes a SQLite name outside the conservative generated-metadata grammar and a table dropped between discovery and bounded sampling.
  - Only recommended for "order of magnitude judgment/whether to add LIMIT/whether it is a large table" strategies.
  - If an exact count is needed, please use `SELECT COUNT(*) ...`, or enable `tools.table_summary=true` and use `get_table_summary(exact_count=True)` (note that large tables may be slow).

- **Result truncation and projection to avoid Token explosion**: `query()` uses `limits.result_rows` / `limits.result_chars`, `list_tables()` uses `limits.overview_tables`, and `get_full_schema()` uses `limits.schema_tables`; therefore, returned rows or tables may not be complete. `limits.result_chars` does not cap schema-tool payloads. Use `get_full_schema(detail_level="compact")` for broad schema explanations, then `describe_table()` only for requested table details. Query truncation does not reduce database execution work or Python-side fetching; use explicit `WHERE`, `LIMIT`, and `ORDER BY` to limit work and stabilize ordering.

- **Some "Total" fields have "Visible Range" semantics**: For example, `total_tables` represents the number of visible tables after allowlist filtering and **before** response truncation. It is not necessarily the physical database total; `returned_table_count` is the number actually returned after truncation.

### Best Practices
- **We recommend starting with GitHub Copilot in VS Code.** GitHub Copilot in VS Code is a mature AI agent tool. Earlier trials used GPT-5 mini. Choose a model within your current account allowance and start with a test database to control risk and cost.
- **Another benefit of using GitHub Copilot is that it empowers this coding-assistant AI with database access capabilities,** allowing it to understand the target database's structure and data distribution. This leads to better development assistance and suggestions when writing code.
- **When using GitHub Copilot, you can add a prompt reminder such as "To make the data and reasoning accurate and sufficient, query step by step and refine the answer over multiple queries."** This nudges the AI toward a multi-step refinement process similar to a ReAct workflow, which is especially useful for complex tasks.
- **When using GitHub Copilot, explicitly attach the "#sql-safety-executor-mcp" tool so the model is reminded to prioritize it.** 

    ![tools](readme_pic/tools.png)

- **When using GitHub Copilot, make good use of the Agent's "todo" tool**, which helps the AI plan query steps and improve efficiency. 

    ![todo](readme_pic/todo.png)

- In recent modifications (as of Jan 7, 2026), multiple security optimizations have been made, such as truncation for large data volumes, use of special keywords (like union), table allowlist settings, and dynamic prompts for different configurations. However, **higher security means lower performance/efficiency and higher consumption (e.g., more request parameters and Token consumption), so please configure security settings as appropriate.**
- In practice, AI clients such as Claude Code, Codex, and Gemini CLI are similar to GitHub Copilot, but **be aware that AI calls may generate substantial token costs.** Earlier testing, including capability testing, mainly used GitHub Copilot. v3.8 reference Client results, actual Codex behavior and pending Copilot validation are recorded separately in [validation](docs/validation/V3_8_VALIDATION_ZH.md).

## Quick Start

### Quickly Call MCP Service using VS Code

By configuring `mcp.json` in VS Code for quick integration, you can directly call the SQL tools of this project in GitHub Copilot Chat. This empowers GitHub Copilot Chat with database-oriented capabilities. [Of course, it can also be used in other MCP-supported AI assistants.](README.md#configuring-mcp-client)

#### 1. Preparation
*   Use a VS Code version with MCP support, Python ≥3.12, and uv.
*   Install the **GitHub Copilot Chat** extension.
*   Ensure project dependencies are installed (run `uv sync --frozen --group dev` in the project path).
*   Check the SQLite example with `uv run sql-safety-executor config check --config config/examples/sqlite/server.toml`; create your own TOMLs using [Configuration](#configuration) for real targets.

#### 2. Create Configuration File
Create a new folder `.vscode` in the project root directory (create if it doesn't exist), and create a file `mcp.json` inside it.

#### 3. Fill in Configuration (Critical Step)
Copy the following content into `mcp.json` (if `mcp.json` already exists, append the configuration to it; VS Code respects `mcp.json` for MCP Server recognition). **Be sure to modify it to your actual absolute path**:

```json
{
  "servers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/project/.venv/bin/sql-safety-executor",
      "args": [
        "serve",
        "--config",
        "/absolute/path/to/project/config/examples/sqlite/server.toml"
      ]
    }
  }
}
```

**Configuration Details:**
*   `command`: the absolute path of `sql-safety-executor` in the environment where this package is installed.
*   `args`: `serve --config` followed by the absolute main TOML path. The example uses the bundled SQLite configuration; select your own `server.toml` for deployment.
*   No `cwd` is needed to discover `.env`; paths inside TOML are resolved relative to their declaring file.
*   VS Code `.vscode/mcp.json` uses top-level `servers`; other clients may use `mcpServers`. See the [official VS Code configuration guide](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

**You can also configure via VS Code GUI: (Recommended)**

1. Complete "1. Preparation".
2. Open VS Code Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
3. Type and select `MCP: Add Server`. 

    ![MCP: Add Server](readme_pic/MCP:AddServer_en.png)
4. Add the above content step by step following the guide (please modify according to actual path).

The guided flow lets you choose workspace or user scope; verify the saved location and command/args. The original screenshots below illustrate the workflow; UI positions may vary by client version.

#### 4. Verification and Usage
1.  Restart VS Code, or use the Command Palette to reload the window.
2.  Open GitHub Copilot Chat, ensure it is in Plan or Agent mode.
3.  Click the **Tool Icon** next to the model selection box below the input field.
4.  You should be able to see `sql-safety-executor` and its provided tools (e.g., `query`, `list_tables`). Ensure they are all checked. 

    ![Add tools](readme_pic/Addtools.png)
5.  Send a question directly in the conversation: "List all tables" or "Query the first 5 rows of the users table".

    ![ask](readme_pic/ask.png)
6.  Then you can see the MCP tool being called.  

    ![answer](readme_pic/answer_en.png)

Note: start with a disposable database and choose a model within your current account allowance. Copilot interactive approval has not been tested for v3.8; tool visibility does not prove MRTR support. See [validation](docs/validation/V3_8_VALIDATION_ZH.md).

#### Common Issues
*   **Cannot find tools?** Check the `Output` panel, switch to "GitHub Copilot" to see if there are errors.
*   **Path Error**: Windows users please note backslash escaping in JSON (e.g., `C:\\Users\\...`).

### MCP Service Usage
```bash
# Install dependencies including MCP support
uv sync --frozen --group dev

# Check the SQLite example offline
uv run sql-safety-executor config check --config config/examples/sqlite/server.toml
# For real targets, prepare explicit TOMLs as described below

# Start MCP Server
uv run sql-safety-executor serve --config config/examples/sqlite/server.toml

# Run the default hermetic pytest suite
# This collects tests/ only, ignores .env, and uses safe SQLite defaults.
uv run pytest -q

# Optional live/manual smoke check: internal functions against configured DB
uv run python scripts/query.py --config config/examples/sqlite/server.toml 'SELECT 1 AS value'

# Optional: inspect protocol, tools and configured targets without database probes
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml
```

### AutoGen Multi-Agent Example

The AutoGen example retains its multi-Agent team (PlanningAgent, SQLExecutorAgent, AnalystAgent), now in a separate dependency environment. Export provider credentials explicitly; no `.env` is loaded.

```bash
python3 -m venv .venv-autogen
.venv-autogen/bin/pip install -r examples/autogen/requirements.txt
.venv-autogen/bin/python -m examples.autogen.autogen_sql_agent_new \
  --server-python /absolute/path/to/project/.venv/bin/python \
  --config /absolute/path/to/project/config/examples/sqlite/server.toml \
  "List all tables and describe their structure"
```

See the [example guide](examples/autogen/README.md) for isolation and validation scope; live AutoGen/model compatibility is not claimed.

### Configuring MCP Client
Add the server to your MCP-compatible client configuration (e.g., VS Code, Claude Desktop, or other MCP clients):

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/project/.venv/bin/sql-safety-executor",
      "args": [
        "serve",
        "--config",
        "/absolute/path/to/project/config/examples/sqlite/server.toml"
      ]
    }
  }
}
```

- Replace `/absolute/path/to/project` with your actual project path.
- The server reads explicit TOML and secret references; it does not load the old `.env`.
- Use the executable in the actual v3.8 environment, or its Python with `-m sql_safety_executor serve --config ...`.

## Configuration

v3.8 replaces `.env` configuration with three TOMLs. Existing private `.env` files are retained, but neither dotenv loading nor ambient `DB_*` / `SKILLS_*` configuration overrides remain. Each file declares `schema_version = 1`; unknown fields, invalid types, negative limits and out-of-range proposal settings fail startup.

| File | Ownership |
|---|---|
| `server.toml` | File references, default target, tools, output limits, common timeouts, logging and telemetry |
| `connections.toml` | Per-target backend, identity, secret, read policy and mutation authorization |
| `skills.toml` | Definition directory, discovery/readiness, global write admission, proposals, MRTR and audit |

The following fragments assume files under the repository's `config/` directory. Merge fragments for the same file without repeating table declarations. Adjust relative paths when copying templates from another directory.

Main file `config/server.toml`:
```toml
schema_version = 1
[files]
connections = "connections.toml"
skills = "skills.toml"
[server]
default_connection = "trade_analysis_mysql"
tool_timeout_seconds = 120
```

`files.connections` and `server.default_connection` are required; the default must exist. Omitting `files.skills` disables Skills. An explicitly referenced missing or invalid file is an error.

### Database Type Selection

Each `connections.<id>` explicitly declares `type = "mysql"` or `type = "sqlite"` and exactly the matching backend section. Database identity and credentials do not inherit from another connection.

### MySQL Configuration (type = "mysql")

In `config/connections.toml`:
```toml
schema_version = 1
[connections.trade_analysis_mysql]
type = "mysql"
[connections.trade_analysis_mysql.mysql]
host = "your_database_host"
user = "your_database_user"
database = "your_database_name"
password = { file = "secrets/mysql.password" }
[connections.trade_analysis_mysql.read]
mode = "allowlist"
tables = ["products", "orders", "customers"]
allow_union = false
```

Choose exactly one password source: `{file="secrets/mysql.password"}`, `{env="MYSQL_PASSWORD"}`, or `{value="..."}`. Environment references are explicit and do not load `.env`. No source fallback is permitted. Secret files are UTF-8, at most 64 KiB, nonempty, and preserve whitespace including trailing newlines. Do not add comments or quotes to the secret file.

### SQLite Configuration (type = "sqlite")

Add to the same `connections.toml`:
```toml
[connections.analytics_demo_sqlite]
type = "sqlite"
[connections.analytics_demo_sqlite.sqlite]
path = "../sample_data/demo.db"
progress_handler_interval = 100
[connections.analytics_demo_sqlite.read]
mode = "allowlist"
tables = ["orders"]
allow_union = false
[connections.analytics_demo_sqlite.timeouts]
query_seconds = 30
```

> `sample_data/demo.db` is the bundled test database. `:memory:` starts empty and loses data on restart. `progress_handler_interval` counts SQLite virtual-machine instructions between timeout checks; smaller intervals check more frequently with more callback overhead.

### Named Connections

Single and multiple targets use the same explicit definitions; there is no `DB_CONNECTIONS` feature gate or legacy identity fallback. Omitted `connection_id` uses `server.default_connection`; unknown targets fail closed. Only `check_connection(scope="all")` explicitly selects all configured targets.

Prefer semantic connection ids such as `trade_analysis_mysql`,
`analytics_demo_sqlite`, or `orders_primary`. Bare `mysql`/`sqlite` are legal
but easy to confuse with DB-type values. Avoid `default` because the actual
default is already represented by `server.default_connection`.
Connection ids are opaque routing aliases: never infer `db_type` from an alias
suffix or name. Use the configured `connections.<id>.type` value or the structured
`db_type` returned by `list_connections()`. Do not infer a business purpose or
role from an alias either. A resolved target must come from the user's explicit
choice, a trusted application binding for this request, or exactly one matching
structured `db_type` when only a database type was requested. Agent guesses,
alias names, the default flag, and successful connection checks are not evidence
of the user's intended target.

When a purpose/role has no resolved target, a reference is ambiguous, a type has
no unique match, or scope restrictions cannot be reconciled, optionally list candidates with
`list_connections()`, then ask the user to choose or clarify and **wait for the
answer**. Do not inspect schema, query, discover/execute Skills, or run connection
diagnostics for that unresolved request. Already known candidates need not be
listed again. These rules take precedence over advice to explore/query first;
ordinary requests without target clues retain existing default routing.
They guide Agents; the server does not validate conversation state or enforce
user selection. Deterministic target restrictions require trusted application/
Host validation in addition to the existing database policies.
For deployments requiring hard per-request target restrictions, that validation
is a prerequisite before go-live. It must cover explicit aliases, the actual
default for an implicit single-target call, and every configured target for
`check_connection(scope="all")`. See the
[deployment acceptance criteria](docs/guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md#18-限制优先级与配置解读的可复用验收).
Trusted local use can retain the documented Agent limitation; the current server
does not supply this per-request authorization mechanism.

An explicit prohibition on accessing a target also prohibits connection checks.
For a requested connectivity diagnostic, an explicit restriction to one resolved
alias or the default limits a broader request: check only that target and state
that other connections were not checked. If the user explicitly rejects partial
checks, the permitted target is unresolved, or the restrictions remain
inconsistent, ask and wait. This does not authorize writes or arbitrary target
selection and does not turn a single-connection result into an all-connection report.


v3.8 connection conventions and trade-offs:

- Resolve the target before policy, readiness, execution, metadata, audit and telemetry; tools cannot supply arbitrary DSNs.
- Reads default to `deny`. An empty `allowlist` grants nothing; unrestricted business-table scope requires explicit `all`. `tables` is only meaningful for allowlists and rejects `"*"`.
- UNION additionally needs `allow_union=true` and valid table scope. Do not mechanically turn an old empty allowlist into both unrestricted reads and UNION permission.
- Writes require Skills, global mutation enablement, admitted connection, connection mutation enablement and a matching Skill allowlist. There is no default-only implicit grant. Read scopes are not universal mutation scopes.
- Only query/connect timeouts inherit built-in → common → connection values. Output limits belong to the service instance. `sql_assistant` stays connection-neutral; inspect the selected target through `list_connections()`.
- Skill `connection_ids` intersects `databases`, profile and execution policy. Unconfigured portable aliases remain unavailable, do not create connections and grant no access. Omitting the request target still uses the default, never the Skill list's first member.
- Public connection metadata omits DSNs, hosts, users, passwords and SQLite paths. SQLite database labels use `sqlite:<connection_id>`; diagnostics identify aliases.

### Optional Service Settings

Add these sections to `server.toml`:
```toml
[tools]
schema = true
table_summary = false
large_table_threshold = 1000
[defaults.timeouts]
query_seconds = 30
connect_seconds = 10
[limits]
result_rows = 100
result_chars = 16000
sql_chars = 20000
schema_tables = 50
overview_tables = 100
[observability.logging]
level = "INFO"
# path = "../logs/server.log"
[observability.telemetry]
enabled = false
path = "../logs/tool_calls.jsonl"
sample_rate = 1.0
```

`tools.schema` retains its historical sample-only registration meaning; basic metadata tools remain registered. `table_summary` enables optional counts, whose exact COUNT(*) may be expensive. Limits accept 0 for unlimited; tool timeout accepts 0 for disabled, while database query/connect timeouts must be positive integers. Truncation does not bound database work or all peak memory. MySQL mutation query timeout bounds row-lock waits, not all DML CPU/IO work.

Service logs go to stderr, with an optional additional file; stdout is reserved for MCP. Telemetry contains sanitized call metadata; sample_rate is in [0,1]. Configuration, resolved secrets and Skill definitions are snapshots; changes require restart.

**Skills configuration**:

Skills package common SQL queries and mutations as reusable operations. They are disabled by default and remain subject to target authorization when enabled. Complete `config/skills.toml` example:
```toml
schema_version = 1
[skills]
enabled = false
directory = "../skills"
[skills.discovery]
default_detail = "summary"
available_only = true
[skills.readiness]
check_schema = true
[skills.policy]
exclude_profiles = []
[skills.mutation]
enabled = false
allowed_connections = []
[skills.mutation.preview]
ttl_seconds = 300
max_entries = 10000
[skills.mutation.mrtr]
enabled = false
[skills.audit]
queries = false
path = "../logs/skill_audit.jsonl"
agent_id = "unknown"
```

| Field (under skills) | Default | Meaning |
|---|---|---|
| `enabled` | false | Disabled means no business Skill imports, tools or readiness probes |
| `directory` | ../skills | Explicit external trusted directories allowed; resolved sources/definitions must remain inside, but Python is not sandboxed |
| `discovery.default_detail` | summary | compact / summary / full; individual calls can override |
| `discovery.available_only` | true | Hide unavailable Skills for the target; false is diagnostic, not permission |
| `readiness.check_schema` | true | Discovery and execution fail closed on missing tables/unavailable metadata; disabling is not proof of readiness |
| `policy.exclude_profiles` | [] | Matching profiles cannot execute and disappear from default discovery |
| `mutation.enabled` | false | Global write switch, subject to four further configuration gates |
| `mutation.allowed_connections` | [] | Exact target admission; empty grants nothing; connection Skill allowlist still applies |
| `mutation.preview.ttl_seconds` | 300 | 1–86400 seconds; invalid values fail startup rather than falling back |
| `mutation.preview.max_entries` | 10000 | 1–100000 entries; full stores refuse issuance, not evict valid proposals |
| `mutation.mrtr.enabled` | false | Optional managed single-statement approval; Skills and writes must also be enabled |
| `audit.queries` | false | Opt-in query audit; mutation audit retains its best-effort behavior |
| `audit.path` / `audit.agent_id` | ../logs/skill_audit.jsonl / unknown | Audit location and source label; the label is not an authenticated identity |

**Preview-token deployment boundary**:

- Proposals live in one bounded service-instance memory store; preview and execute must reach that same instance. The supported CLI transport is stdio.
- Restart invalidates pending proposals. Missing state does not prove no earlier write occurred; reconcile uncertain outcomes before deciding whether to preview again.
- No shared multi-worker approvals, durable completion ledger, stateless fallback or cross-restart recovery is provided.
- Python Skills remain trusted code; containment and managed plans do not isolate module imports, preview callbacks or arbitrary in-process effects.

**Manual approval Host (preview / MRTR)**:

`examples/manual_mutation_approval.py` starts the installed package with the active Python and requires `--config`; `--flow preview` is the default. It keeps exact parameters and proposals in one stdio Client/subprocess and accepts only literal `APPROVE` before its deadline. `--flow mrtr` additionally needs explicit MRTR enablement, a managed single-statement Skill, MCP `2026-07-28` and Host form support.

MRTR holds the same review snapshot (at most 64 KiB) and uses framework-sealed continuation state. Missing answers resend the review without rerunning preview or extending the original expiry. Only accept plus strict boolean approve=true executes. Decline/cancel closes the proposal; a local denial in the retained preview Host does not revoke its server token before TTL. Neither flow automatically retries uncertain writes.

Approval trusts the Host rather than independently authenticating a human. Review/terminal output can contain business data, and sealed state is sensitive. The child inherits exported process variables; a productized Host should restrict that environment as appropriate. This does not restore dotenv configuration.

**Privacy and log operations notes**:

- Skill audit params are truncated for log size, not key/value redacted. Treat skill parameters as business audit data and do not pass secrets, tokens, credentials, or sensitive personal data as skill params.
- Mutation audit is attempted automatically when mutation skills are enabled, but audit write failures do not block the operation. Query skill audit remains opt-in (`skills.audit.queries=false` by default) to avoid surprising read-query parameter logs. v3.5 audit entries may include a safe `connection_id` alias and actual `db_type`; they still do not contain DSNs, hosts, passwords, SQLite file paths, SQL text, or returned rows.
- Pre-token parameter/validation rejection and audit write failures can return a normal tool result with `audit_logged=false`. Once imperative execute has consumed a valid token, a later dynamic validation rejection attempts a best-effort execute audit. Managed confirmation performs no dynamic Skill validation. The JSONL file remains a visibility aid, not a fail-closed transaction control.
- If a write commits but context notification or response construction later fails, the existing success audit is retained without a contradictory failure record. When a fallback response is deliverable it says `success=false, execution_outcome=committed`; complete response loss remains unknown to the client. Either case is terminal and the token remains consumed.
- The process-local preview-token store supports the stdio deployment. Custom transport embedding remains within a trusted single-process boundary. Multi-user authenticated HTTP mutation, cross-worker execution, and cross-replica execution are outside the current design; the server never falls back to stateless token acceptance.
- `skills.audit.path`, `observability.telemetry.path`, and `observability.logging.path` are local files. In production, place them on trusted storage with restricted permissions and external rotation/retention, such as `logrotate`, platform logging, cron cleanup, or a managed log sink. A typical starting point is daily or size-based rotation, compression, and 14-90 days retention depending on compliance needs.


**Typical configuration scenarios**:

These are edits to the named fields, not fragments to append repeatedly to the same table.

| Scenario | Configuration |
|---|---|
| Read-only Query Skills | `skills.enabled=true`, `skills.mutation.enabled=false`, plus target read authorization |
| Query and mutation Skills | Enable both switches, list `skills.mutation.allowed_connections`, and grant the connection policy below |
| Custom directory/audit | Set `skills.directory`, `skills.audit.path`, `skills.audit.agent_id` |
| Complete catalog review | `skills.discovery.available_only=false`, or override available_only in the call |
| Skip live schema checks | `skills.readiness.check_schema=false`; use CLI check/explain for entirely offline configuration validation |
| Exclude demo Skills | `skills.policy.exclude_profiles=["demo"]`, affecting both discovery and execution |
| Audit Query Skills | `skills.audit.queries=true`; may record business parameters, not returned rows |
| Managed MRTR | After write authorization, enable `skills.mutation.mrtr.enabled=true` and verify actual Host support |

For example, allow the two demo mutations on `analytics_demo_sqlite`: set `skills.enabled=true`, `skills.mutation.enabled=true` and `skills.mutation.allowed_connections=["analytics_demo_sqlite"]` in skills.toml, then add to connections.toml:
```toml
[connections.analytics_demo_sqlite.mutation]
enabled = true
skills = ["sample-update-order-status", "sample-reset-order-to-pending"]
```

**Demo Skills schema**:

The bundled sales report, status update and reset Skills use the demo profile and a compatible orders table. Use a separate disposable database:
```bash
uv run python scripts/setup_sqlite_demo.py --output local_data/mutation-demo.db
# MySQL: only use a dedicated demo target
uv run python scripts/setup_demo_db.py --config /path/server.toml --connection-id mysql_demo
uv run python -m examples.manual_mutation_approval \
  --config config/examples/mutation/server.toml --flow preview \
  --skill sample-update-order-status --params-file /path/params.json
```

SQLite setup refuses to overwrite an existing file. MySQL setup still needs explicit `--drop-existing` or `--seed-existing` to modify an existing orders table. The public [mutation template](config/examples/mutation/server.toml) disables MRTR by default.

Additional protections include `strict_input_validation=True`, `mask_error_details=True`, tool timeouts and raw SQL length limits. Deliberate safe validation failures remain actionable to callers.

### MCP Client Integration

See [mcp_config.json](mcp_config.json) for the portable template. Private `config/*.toml`, `config/secrets/` and `mcp_config.local.json` are ignored by Git; do not commit real credentials. The [configuration guide](docs/guides/CONFIGURATION_ZH.md) covers field mappings, defaults, SDK imports and cutover/rollback. Check TOML, stop the old process, and start with matching new dependencies and entry points; rollback also requires matching code, dependencies and configuration.


## Changelog

### v3.8.0 FastMCP 4, TOML and Managed MRTR (September 2026)

- FastMCP 4.0.10 / MCP SDK 2.2.0 with framework-owned negotiation; modern `2026-07-28` and legacy `2025-11-25` stdio verified.
- Installed `src/sql_safety_executor` package; instance-owned configuration, adapters, catalog, tokens and diagnostics; prompts shipped as wheel resources.
- Three strict TOMLs, mandatory `--config`, explicit secrets and offline `config check/explain`. Reads default to deny; all write gates are required. Remove default-only grants and partial-policy `execute_sql()`.
- Default-off `request_mutation_approval` for managed single statements: sealed state, 64 KiB review cap, strict approval, original expiry and atomic consumption; no retry of uncertain writes.
- Migrate public Skill SDK imports, trusted external directories, clients, isolated AutoGen examples, documentation, dependency lock and CI.
- Automated results: 744 passed, 4 skipped; type checks and installed-wheel verification passed. Subsequent live checks verified MySQL connectivity/basic reads, native Codex SQLite preview/execute with fixture restoration, and three isolated Luna six-turn routing trials. The earlier MRTR dispatch refusal remains recorded; native MRTR/human approval UI, Copilot, MySQL writes and remote CI remain unverified.

See [release notes](docs/releases/RELEASE_NOTES_v3_8.md) and [validation](docs/validation/V3_8_VALIDATION_ZH.md). Historical entries below retain their original configuration, paths and conclusions; they are not v3.8 deployment instructions.


Historical version entries retain their original Skill names. Current names
are listed in the [v3.7.2 migration table](docs/releases/RELEASE_NOTES_v3_7.md#sample-skill-names-and-local-files).

### Managed Single-Statement Mutations (September 16, 2026)

This follow-up is included in v3.7.3 before its first formal publication.
The Skill-author contract changes below still require migration; see the
[version scope and compatibility note](docs/releases/RELEASE_NOTES_v3_7.md#managed-single-statement-mutation-contract--september-16-2026).

- Added immutable `ManagedMutationPlan` declarations for one parameterized
  INSERT, UPDATE, or DELETE. Discovery validates the statement, named binds,
  frontmatter parameter references, exact expected row count, and result fields.
- Managed previews take `preview_sql` and `bound_params` exclusively from the
  cached plan and final binding. Skill-supplied copies are rejected; SQL and
  result values must resolve before token issuance. Result mappings also reserve
  `error` and `error_code` to keep audit evidence consistent.
- Confirmation resolves the consumed preview binding and executes the cached
  plan directly through the adapter. It does not instantiate the Skill or call
  Skill `validate()`, `execute()`, or `execute_with_binding()`. Mutable
  business invariants must therefore be encoded in the statement predicate and
  protected by `expected_rowcount`.
- Migrated both bundled mutation samples to the managed path. Exact outcomes
  now describe the framework's only managed database statement; they do not
  prove that module import or preview-time Python had no side effects.
- Kept imperative `MutationBase` as a trusted, experimental escape hatch. Its
  whole-Skill success and failure remain `unknown` because callbacks may issue
  multiple writes or perform effects the framework cannot observe.
- When `SKILLS_ALLOW_MUTATIONS=0`, discovery parses mutation metadata and checks
  source paths but does not import custom mutation modules. Enabling writes and
  restarting the server imports them for review-time validation and previews.
- The removed `exact_transaction_outcome` flag and built-in name/path/class
  registry are no longer extension contracts. Pre-release custom Skills should
  migrate to `ManagedMutationBase` or remain imperative.

### Unified connection diagnostics (September 22, 2026)

- Unified default, named and all diagnostics under `check_connection`, with an
  explicit `scope="all"` and one required-scope report schema. The plural tool
  is removed without a compatibility alias.
- Single checks now use independent worker-owned connections and share the
  existing deadline, busy and cleanup-disable protection. This is a breaking
  tool/output migration; the repository version is unchanged.
- The [current design record](docs/guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md)
  covers migration, costs, staged validation and the unchanged per-request
  authorization limitation. Historical entries below describe their dated stage.
- Review verification: **675 passed, 4 skipped**; ten changed Python files pass
  Pyright. The restarted Host exposes the unified tool and passes default MySQL,
  named SQLite and all-connection smoke checks. [Staged Agent evidence](docs/validation/v3.7/V3_7_3_LIVE_MCP_TEST_UNIFIED_CONNECTION_DIAGNOSTICS_2026_09_22_ZH.md)
  preserves routing failures; DRR-2026-066 remains open, and the C wording trial
  was reverted to B. No universal accuracy or billed-token improvement is claimed.

### v3.7.3 Connection Routing and Tool Contract Clarity (September 2026)

Repository version prepared on September 15; creating a release/tag is a separate step.

- Clarified default, resolved-target and explicitly permitted all-connection
  diagnostics. Unresolved purposes require waiting before database work;
  explicit single-target restrictions narrow requested diagnostics. Prohibited
  targets must not be checked; irreconcilable restrictions require waiting.
- Added configuration-only guidance to `list_connections`: allowed tables do
  not prove table existence or physical completeness. Discovery still does not
  connect to databases.
- Aligned current `table_name` / `skill_name` examples and MCP descriptions.
  Both diagnostic tools retain their APIs
  and connection/resource behavior.
- Added protocol regressions and native/fixture Agent evaluation records.
  Source validation: **640 passed, 4 skipped**; seven Python files pass Pyright.
  Explicit-prohibition fixture failures keep DRR-2026-066 open; latest guidance
  still needs native-Host discovery and acceptance.
- See the [v3.7.3 notes](docs/releases/RELEASE_NOTES_v3_7.md#v373--connection-routing-and-tool-contract-clarity)
  for compatibility and evidence boundaries. Batch diagnostics were introduced
  in the preceding v3.7.2 work.

### v3.7.2 Transaction Outcomes and No-Retry Host (September 2026)

- Added keyword-only `expected_rowcount` to MySQL/SQLite `execute_write()` and
  moved both built-in mutation Skills' exact-one check before COMMIT, so zero or
  multi-row updates are rolled back.
- Added structured `execution_outcome` and stable failure `error_code` fields;
  `success` now describes tool handling independently from database state.
- Treats any COMMIT exception as `unknown`; later rollback/cleanup cannot prove
  that COMMIT failed. A confirmed COMMIT stays `committed` through audit or
  response errors.
- Tightened the approval host to validate response identity first and never
  retry, re-preview, or switch targets after its single execute call.
- Removed an unconditional success-path `committed` claim: the built-ins now
  preserve typed adapter evidence, custom success without whole-operation proof
  remains `unknown`, and malformed/self-reported-failure Skill results become
  structured unknown failures. COMMIT-stage `asyncio.CancelledError` is also
  converted to typed `commit_outcome_unknown` when a response remains possible.
- Made `MutationBase.run_execute()` a framework-owned wrapper. The loader now
  rejects direct and inherited custom overrides at discovery; custom business
  behavior belongs in `execute()` or `execute_with_binding()`. This is an
  intentional pre-release extension-contract change that centralizes outcome
  validation, error sanitization, and execution audit. The loader also reserves
  `exact_transaction_outcome=True` for the two framework-registered built-ins;
  it verifies the bundled source path and registers the loaded class identity.
  Reusing a built-in name in `SKILLS_DIR` does not grant exact outcomes: a custom
  exact declaration fails discovery; ordinary custom outcomes remain `unknown`.
  Connection `MUTATION_SKILLS` allowlists still refer to names in the configured
  catalog; review those permissions when replacing `SKILLS_DIR`.
- Full contract, compatibility impact, accepted boundaries, tests, and reviewed
  primary references are in the
  [v3.7.2 release notes](docs/releases/RELEASE_NOTES_v3_7.md#v372--write-transactions-and-uncertain-results).

### v3.7.1 Opaque Preview Handles and Agent Workflow Efficiency (August 2026)

- Replaced the self-describing HMAC preview-token envelope with a random
  256-bit opaque bearer handle while retaining exact request/state binding,
  TTL, bounded process-local storage, atomic one-time consumption, and the
  same-process mutation deployment boundary.
- Added `get_skill_detail(detail_level="execution")` as a compact invocation
  projection while keeping `full` as the default. Agent
  guidance now skips redundant detail calls after `list_skills(...,
  detail_level="full")` or when params are already known.
- Made connection routing guidance fail closed for ambiguous database types and
  purpose-only descriptions. The shared prompt no longer presents the default
  connection's UNION policy as global; callers inspect the selected alias's
  policy through `list_connections()` and runtime enforces that exact target.
- Reduced duplicate mutation preview fields and marked
  `MUTATION_PREVIEW_TOKEN_SECRET` obsolete. See the v3.7 release-family notes
  for the response-compatibility details and current validation evidence.

### v3.7.0 Scoped Skills, Approval Host, and SQL Hardening (August 2026)

- Added optional strict `connection_ids` metadata to `skill_def.md`; one alias
  directly scopes a Skill and multiple aliases support reuse. Existing
  documented-schema Skills that omit it keep their routing behavior.
- Reject unknown frontmatter fields and duplicate YAML mapping keys so a typo
  in `connection_ids` cannot silently remove an intended restriction.
- Checked Skill alias scope and DB-type compatibility before adapter creation;
  existing profile/schema/table/query/mutation policy remains an independent
  gate before query execution or database writes. Unknown or conflicting
  targets fail closed per target without disabling other valid members.
- Added a stdio-only, non-AutoGen manual approval host example and deterministic
  state-machine tests. It keeps the token out of its approval view/output and
  never auto-retries an uncertain execute.
- Added the portable `reset-demo-order-to-pending` mutation for disposable
  MySQL/SQLite fixtures. It requires an exact expected source status, fixes the
  target to `pending`, and is a demo/test compensating action—not a rollback or
  a production order-reopening API.
- Tightened known Skill metadata and nested parameter-constraint value types;
  the small custom DSL now rejects malformed booleans, lists, enum, and bounds
  during discovery.
- Narrowed SQL safety claims to supported Oracle MySQL/SQLite behavior. The
  full MCP policy accepts one statement, rejects raw SHOW and executable
  comments/hints, preserves qualified table identity, and conservatively
  extracts comma/nested/CTE/EXPLAIN tables under restrictive allowlists.

### v3.6.1 Preview-Token Hardening (August 2026)

- Retained the v3.6 bounded process-local memory store with atomic issue/consume
  and formalized its same-process deployment boundary.
- Made preview execution bindings come from the state actually displayed by
  preview, stopped issuing tokens for failed previews, and disabled the
  bundled state-sensitive Skill's direct unbound `execute()` path.
- Strengthened secret-rotation, sanitization, database-failure consumption,
  concurrent-consumption, and memory-store regression coverage.

### v3.6 Mutation Preview Tokens and Named Write Policy (May 2026)

Adds mandatory preview-token binding and opt-in strict mutation routing across
configured named connections:

> Historical format note: v3.6 used a self-describing HMAC envelope. Since
> v3.7.1, the implementation preserves the `preview_token` API field but returns a
> 256-bit opaque handle and keeps all binding state in the process-local Store.
> The signing-secret setting and client-visible `jti`/payload format are obsolete.

- In v3.6, `execute_mutation_skill(confirm=false)` returned an API-opaque,
  signed but unencrypted bearer `preview_token`, expiry fields, and token-related
  `_meta` fields.
- The matching v3.6 execute rejected missing, expired, tampered, or
  params/skill/connection-mismatched tokens before writes.
- The v3.6 envelope was HMAC-signed and bound skill name, version, canonical
  params hash, resolved `connection_id`, `db_type`, issue time, and expiry.
- Each v3.6 token carried a random `jti` and was registered in a bounded
  process-local atomic store; execute consumed it before dynamic validation/write.
- Preview-sensitive state was bound separately from params; the bundled order
  mutation used the status shown during preview in its optimistic lock.
- `execute_mutation_skill` accepted optional `connection_id`; strict routing
  required the global target allowlist plus per-connection switch and Skill allowlist.
- TTL/capacity settings bounded outstanding records, and process restart
  invalidated them even when the historical signing key was fixed.
- The v3.6 regression suite covered target isolation, policy rejection, expiry,
  tamper/version binding, secret reload behavior, replay, and token non-exposure.

### v3.5 Named Multi-Connection Read Tools and Query Skills (May 2026)

Adds configured named database connections while preserving the legacy single
default connection path:

- Added a `DatabaseConfig` / `ConnectionPolicy` registry in `db_adapter.py` and one lazy adapter cache per configured `connection_id`; `get_adapter()` with no argument still returns the default connection for backward compatibility
- Added `list_connections()` and optional `connection_id` parameters to read-only core tools (`query`, `check_connection`, `list_tables`, `describe_table`, `get_full_schema`, optional `get_table_summary`, optional `sample`)
- Raw SQL tools now resolve the target connection before read-query policy, table allowlist checks, dialect-specific internal SQL, and execution. This fixes the historical risk where one code path could quote for one adapter but execute through the default adapter.
- Table allowlists now recognize common quoted identifier forms such as backticks, double quotes, square brackets, and schema-qualified references before deciding whether a table is allowed.
- Query Skills are now connection-scoped for listing, detail, execution, runtime metadata, optional query audit, and telemetry. `SkillMetadata.databases` remains a DB type compatibility field, not a connection-id allowlist.
- Query Skill startup validation still checks read-only shape and structural deny rules, but table allowlists are enforced at runtime against the resolved target connection. This compromise is necessary because allowlists are now connection-scoped.
- Mutation Skills remain default-connection only in v3.5. Non-default discovery marks them non-executable with an explicit reason; multi-connection write policy, preview/execute consistency across write targets, and per-connection mutation permissions remain deferred.
- `ToolResult.meta`, optional telemetry JSONL, and Skills audit JSONL can now include safe `connection_id` plus actual `db_type`. They still exclude DSNs, credentials, SQL params, returned rows, and database internals. SQLite database names in public tool payloads use the safe alias `sqlite:<connection_id>`.
- Tests added in `tests/test_multi_connection_v35.py` and expanded registry/meta/audit tests cover same-connection policy/execution, unknown connection fail-closed behavior, and Skills display/execution consistency.

### v3.4.3 Bounded SQLite Estimates and Design Risk Register (May 2026)

Focused on bounded metadata behavior and long-term design-risk tracking:

- `SQLiteAdapter.get_row_estimate()` now uses `sqlite_stat1` when available and otherwise returns the 10,000-row sampling cap as a lower-bound estimate for larger tables instead of running full `COUNT(*)`
- Query truncation warnings now clarify that truncation limits returned payload only; SQL `WHERE`/`LIMIT`/`ORDER BY` is still required to limit database work and stabilize ordering
- `list_tables()` and `get_full_schema()` descriptions now use visible/truncated wording instead of implying all tables or complete schema are always returned
- Security wording now distinguishes sqlparse statement-type allowlisting, MCP-layer checks, Skills parameter validation, and base SQL/table validators
- Added [Design Risk Register](docs/security/DESIGN_RISK_REGISTER.md) and [中文版本](docs/security/DESIGN_RISK_REGISTER_ZH.md) as long-term tracking documents for accepted, deferred, rejected, and policy-required design risks
- Final review fixes tightened SQLite timeout classification, MCP client smoke-test assertions/result parsing, full-profile tool-count wording, and SQLite write-lock wording. Direct MCP stdio validation covered base tools, Skills tools, mutation preview, and sanitized telemetry.

### v3.4.2 Unified ToolResult, Output Schemas, and Optional Telemetry (May 2026)

Generalized the v3.4.1 metadata pattern across the full tool surface and added two optional observability features:

- **All registered MCP tools in the full profile** (up to 12 as of v3.5: core SQL tools, optional schema/table-summary tools, connection discovery, skill discovery/detail tools, and skill execution tools) return `ToolResult` with `structuredContent` (previous business payload, unchanged) plus a `meta` block carrying `tool_name`, `execution_ms`, `db_type`, `connection_id`, `success`, and tool-specific counters such as `row_count`, `total_rows`, and `truncated`
- Skills execution tools also carry the same common `meta.tool_name` and `meta.success` fields; `meta.success` is derived from `structuredContent.success`, so the system records "did the tool call crash?" separately from "did the business operation succeed?". A Skill blocked by invalid parameters, a safety rule, or a disallowed state transition may return a normal failure result instead of raising. In telemetry, that appears as `call_completed=true` and `success=false`, which indicates a business-level rejection rather than a transport/runtime crash
- `execute_query_skill` and `execute_mutation_skill` now declare an MCP `outputSchema` so compliant clients can validate `structuredContent` shape without trial and error
- New opt-in `ENABLE_TOOL_TELEMETRY=1` enables a FastMCP middleware that appends a sanitized JSONL record per `tools/call` invocation to `TOOL_TELEMETRY_LOG_PATH` (default `logs/tool_calls.jsonl`); the record contains only `timestamp`, `tool_name`, `execution_ms`, `call_completed`, `success`, `error_class`, `db_type`, and as of v3.5 `connection_id` — never SQL, parameters, returned rows, connection strings, or credentials. `call_completed` reflects whether the tool returned without raising; `success` honors the tool's own `ToolResult.meta.success` when present, so business-level rejections (e.g. a safety-checker veto returning `success=False` without raising) are correctly distinguished from transport-level crashes
- Optional `TOOL_TELEMETRY_SAMPLE_RATE` (a finite float from `0.0` to `1.0`, default `1.0`) controls the probability of writing JSONL telemetry records in high-throughput deployments; out-of-range values are clamped, and invalid or non-finite values (`nan`, `inf`) fall back to `1.0`. Here, "default `1.0`" means that once telemetry is enabled via `ENABLE_TOOL_TELEMETRY=1`, an unset `TOOL_TELEMETRY_SAMPLE_RATE` is treated as `1.0`, so every `tools/call` invocation writes a telemetry record by default. The project does not enable the telemetry middleware or write JSONL logs by default, because `ENABLE_TOOL_TELEMETRY` defaults to `0`. Put simply, `ENABLE_TOOL_TELEMETRY` decides whether anything is logged, while `TOOL_TELEMETRY_SAMPLE_RATE` decides how much gets logged.
- New pytest annotation-consistency test (`tests/test_annotations_consistency.py`) keeps `ToolAnnotations` (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`) aligned with the documented intent for every registered tool
- Per MCP spec the `_meta` field is OPTIONAL — clients MAY ignore it. The VS Code MCP UI for example only renders `structuredContent`; treat `meta` as server-side observability
- Direct in-process callers should unwrap with `getattr(result, "structured_content", result)` (see `tests/test_skills_disclosure.py::run_tool`)



### v3.4.1 ToolResult Runtime Metadata and Closed-World Annotations (May 2026)

Completed the protocol/observability follow-up from v3.4 without changing the existing structured result payloads:

- `execute_query_skill` and `execute_mutation_skill` now return `ToolResult` with the previous business payload in `structuredContent` and non-sensitive runtime diagnostics in `meta`
- Runtime metadata includes timing, mode, skill version/type, database type, idempotency, row counts, truncation state, and audit logging state where applicable
- Runtime metadata intentionally excludes raw SQL templates, parameter values, returned rows, credentials, and database connection internals
- All MCP tools now set `openWorldHint=false` to reflect the configured database/server boundary; this remains an advisory client hint, not an authorization control
- Tests cover Skills `ToolResult.meta` behavior and verify every listed MCP tool exposes the closed-world annotation

### v3.4 MCP Hardening and Skills Profile Policy (May 2026)

Implemented a conservative hardening pass:

- Enabled FastMCP `mask_error_details=True`; intentional `ToolError` messages still carry sanitized details
- Added `MCP_TOOL_TIMEOUT_SECONDS` to apply a foreground timeout to registered MCP tools
- Added `MAX_SQL_LENGTH` plus MCP schema `minLength`/`maxLength` metadata for raw `query(sql)` input
- Added `SKILLS_EXCLUDE_PROFILES` so deployments can hide and block demo-profile skills without deleting examples
- Added optional `SKILLS_AUDIT_QUERIES=1` query skill audit logging; returned data is never written to the audit log
- Fixed `test_bug_fixes.py` pytest wrappers so tests assert instead of returning booleans
- At v3.4 time, deferred (`ToolResult.meta`), (session-state schema caching), and (`db://schema` resources) as explicit design decisions; `ToolResult.meta` later landed incrementally in v3.4.1/v3.4.2, while schema caching and `db://schema` resources remain deferred

### v3.3 Skills Availability and Metadata Disclosure (May 2026)

Added on-demand metadata disclosure for the Skills layer while preserving startup validation and cache semantics:

- `list_skills(search, category, detail_level, available_only)`: Searchable catalog with `compact`, `summary`, and `full` projections plus optional availability filtering
- `get_skill_detail(skill_name)`: Fetches one skill's cached parameter schema and execution metadata on demand
- `SKILLS_LIST_DEFAULT_DETAIL`: Environment-controlled default projection (`summary` by default)
- `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT`: Agent-facing default hides currently non-executable skills while `available_only=false` preserves the full developer catalog
- `SKILLS_CHECK_SCHEMA_ON_LIST`: Optional live table-existence readiness check; default discovery hides Skills with missing required tables or table readiness that cannot currently be verified
- Security boundary preserved: no runtime SQL/Python source reads and no raw source disclosure to Agents
- Category aggregation added; missing categories are reported as `uncategorized`
- Optional `databases` skill metadata prevents DB-specific skills from executing on incompatible adapters
- Optional `profiles` skill metadata marks bundled sample skills as `demo`
- Added `monthly-sales-report-sqlite` as a SQLite-specific counterpart to the MySQL example skill

### v3.0 Skills Extension (March 2026)

Added the Skills extension layer — pre-defined, parameterized SQL operations for structured agent interactions:

- **Skills Infrastructure** (`skills/_lib/`):
  - `skill_loader.py`: Skill discovery, YAML frontmatter parsing, parameter validation, SQL safety checks at startup
  - `mutation_base.py`: Abstract base class implementing validate/preview/execute pattern for write operations
  - `audit.py`: Best-effort JSONL audit trail for mutation preview/execute paths with thread-safe logging
- **New MCP Tools** (conditionally registered via `ENABLE_SKILLS`):
  - `list_skills()`: Progressive disclosure — returns skill metadata (name, type, risk, triggers)
  - `execute_query_skill(name, params)`: Execute pre-audited SQL templates with parameterized binding
  - `execute_mutation_skill(name, params, confirm)`: Two-phase write operations (preview → confirm)
- **Security Model** (`skills/SAFETY.md`): Template-as-whitelist, parameterized queries, dual-layer switches, error sanitization, audit/privacy boundaries, and v3.5 connection-scope constraints
- **Database Adapter Extensions**: `execute()` now accepts optional `params`, new `execute_write()` method
- **Example Skills**: `monthly-sales-report` (MySQL query), `monthly-sales-report-sqlite` (SQLite query), `update-order-status` (portable business mutation), and `reset-demo-order-to-pending` (portable demo/test compensation)
- **58 New Tests**: Covering skill loader, query skills, mutation skills, and audit logging
- **New Dependencies**: `pyyaml` for skill_def.md frontmatter parsing; `SQLAlchemy>=2.0` version constraint added
- **Full Backward Compatibility**: `ENABLE_SKILLS=0` (default) — zero overhead, no tools registered

For design details, see [MCP_AGENTS_SKILLS_DESIGN.md](docs/architecture/MCP_AGENTS_SKILLS_DESIGN.md).

### v2.2 SQLite Support (January 2026)

Added support for SQLite databases while maintaining full backward compatibility with MySQL:

- **New Database Adapter Architecture**: Introduced `db_adapter.py` with Abstract Base Class pattern
  - `DatabaseAdapter` ABC defines unified interface for all database backends
  - `MySQLAdapter`: Preserves all existing MySQL functionality
  - `SQLiteAdapter`: New SQLite support with native timeout mechanism
  - `create_adapter()` factory function for automatic adapter selection
- **SQLite-Specific Features**:
  - Query timeout via `set_progress_handler()` (native SQLite callback)
  - `StaticPool` connection pooling (single process-local connection; SQLite file-level write locks still apply)
  - `sqlite_master` and `PRAGMA table_info()` for metadata queries
  - Row count estimation using `sqlite_stat1` or bounded sampling
- **New Environment Variables**:
  - `DB_TYPE=mysql|sqlite` - Database type selection (default: mysql)
  - `SQLITE_DATABASE_PATH` - Path to SQLite file or `:memory:`
  - `SQLITE_PROGRESS_HANDLER_INTERVAL` - Timeout check frequency
- **Backward Compatibility**: All existing MySQL configurations continue to work unchanged
- **New `db_type` Field**: Tool responses include `db_type` indicating the active database type (v3.5 treats this as the target connection's DB type)
- **Comprehensive Test Suite**: 53 tests covering both MySQL and SQLite adapters

For detailed design decisions, compromises, and implementation details, see [SQLITE_ADAPTER_DESIGN.md](docs/architecture/SQLITE_ADAPTER_DESIGN.md). For change log details, see [REFACTORING_LOG.md](REFACTORING_LOG.md).

### v2.1 Tool Optimization (January 2026)

Focused on improvements in tool design and output consistency:

- **`get_table_summary` is now optional**: Disabled by default (`ENABLE_TABLE_SUMMARY=0`) as `describe_table()` already provides estimated row counts. Enable only when precise COUNT(*) is needed.
- **Enhanced `describe_table`**: Now returns `row_count`, `row_count_approximate`, `is_large` flag, and `recommendation` query suggestions.
- **Refactored `list_tables` output**:
  - `data` → `tables`, clearer.
  - Added `database_name`, `returned_table_count`, `total_tables`, `truncated`, `truncation_note`.
- **Consistent Field Naming**: `returned_table_count` vs `total_tables` standard applied to both `list_tables` and `get_full_schema`.
- **New Environment Variables**:
  - `ENABLE_TABLE_SUMMARY=0` - Controls `get_table_summary()` tool.
  - `LARGE_TABLE_THRESHOLD=1000` - Threshold for `is_large` flag.
  - `MAX_OVERVIEW_TABLES=100` - Max tables for `list_tables()`.
- **AutoGen Agent Prompt Update**: Removed `get_table_summary()` reference, updated workflow to `list_tables() → describe_table()` pattern.

For detailed changes, please refer to [REFACTORING_LOG.md](REFACTORING_LOG.md).

### v2.0 Refactoring (December 2025) - Historical Branch: `feature/v2.0-mcp-server-refactoring`

Major improvements following FastMCP best practices:

- **Expanded SQL Support (historical v2 behavior; v3.7 full MCP policy now rejects raw SHOW)**: Added multiple read-only statement types
  - `SELECT`: Standard data retrieval
  - `SHOW`: added historically; v3.7 full MCP policy rejects raw SHOW and uses
    `list_tables()`/`describe_table()` for metadata
  - `DESCRIBE`: Table structure information
  - `EXPLAIN`: Query execution plan analysis
- **Tool Consolidation**: Reduced from 6 tools to 5, then expanded to 7 via new optimized tools
  - `validate_sql_query` + `execute_safe_sql` → Consolidated into `query` (Automatic Validation)
  - Added `list_tables` tool for database discovery
  - Renamed tools for clarity: `check_connection`, `describe_table`, `sample`
  - **New (Dec 23)**: Added `get_full_schema` and `get_table_summary` for Token optimization
- **Optimized Server Instructions**: Reduced "exploratory behavior" (unnecessary tool calls) from LLMs
  - Explicit tool priority: `query` first, others only on error
  - Expected reduction: From 4-5 tool calls per query to 1-2 calls
- **Security Enhancements (Dec 23, 2025)**:
  - Read-query timeout and MySQL mutation row-lock wait protection (P0 Safety)
  - Table Allowlist support (`ALLOWED_TABLES`)
  - Configurable UNION policy (`ALLOW_UNION`)
  - Result truncation to prevent Token overflow
- **Code Quality**: Reduced code by ~40% (approx 460 → 280 rows) while maintaining functionality
- **Enhanced Metadata**: Added `ToolAnnotations` to improve LLM tool selection
- **Lifecycle Management**: Correct asynchronous resource lifecycle (FastMCP Best Practice)
- **SQL Injection Protection**: Identifier validation for dynamic table names

For detailed changes, please refer to [REFACTORING_LOG.md](REFACTORING_LOG.md).

### v1.0 - MCP Service Architecture

This project has transitioned from direct function calls to a standardized MCP service architecture, providing:

- Service-Oriented Architecture: Converted direct LLM function calls into an independent MCP server.
- Standardized Protocol: Implemented MCP tools for consistent AI model integration.
- Enhanced Separation of Concerns: Separated server startup logic into dedicated `start_server.py`.
- Improved Scalability: Single server instance supports multiple concurrent LLM clients.
- Better Security: Service isolation and controlled access via MCP protocol.

## Exposed MCP Tools

The service exposes 6–13 standardized MCP tools (depending on configuration). Response examples below show selected fields; sample table names require the corresponding read authorization:

### 0. `list_connections`
Usage: List configured database connection ids and non-sensitive policy metadata.

Listing does not connect or select a target for the user. For an unresolved
purpose, present candidates neutrally and wait for the user's choice; a default
flag does not identify an analytics database or justify a diagnostic/schema call.
`policy.allowed_tables` describes access configuration, not verified table
existence or a complete physical table inventory.
A short `hint` in the result repeats this distinction for Agents reading the
returned configuration. Discovery still does not inspect databases, and the
existing fields retain their meanings.
Clients with a closed response model must allow or declare the additional `hint`
field; compatibility with independently defined closed models is not guaranteed.

Output:
```json
{
  "success": true,
  "default_connection_id": "trade_analysis_mysql",
  "connection_count": 2,
  "hint": "Configuration only; no database was inspected. allowed_tables is an access policy, not proof of table existence or a complete table inventory. Say 'configured to allow orders', not 'the database only has orders'.",
  "connections": [
    {
      "connection_id": "trade_analysis_mysql",
      "db_type": "mysql",
      "is_default": true,
      "policy": {"read_mode": "allowlist", "read_enabled": true, "allow_union": false, "allowed_tables_mode": "allowlist"}
    },
    {
      "connection_id": "analytics_demo_sqlite",
      "db_type": "sqlite",
      "is_default": false,
      "policy": {"read_mode": "allowlist", "read_enabled": true, "allow_union": false, "allowed_tables_mode": "allowlist"}
    }
  ]
}
```

The tool does not expose DSNs, hosts, users, passwords, or SQLite file paths.
A returned alias may be passed to read-only tools and Query Skills, subject to
their policies and Skill scope. A Mutation Skill requires explicit global target admission and connection-level authorization for that Skill, including on the default connection. Discovery does not grant write access.

### 1. `query` (Free-form Read Tool)
Usage: Execute read-only SQL queries with automatic security validation.

This is the primary tool for free-form read-only SQL, not every database task.
Use metadata tools for schema discovery and reviewed Query Skills for defined
workflows. Security validation is automatic; the full MCP policy accepts one
SELECT, DESCRIBE, or non-ANALYZE EXPLAIN on the supported MySQL/SQLite adapters.
Raw SHOW is rejected; use `list_tables()` or `describe_table()` for metadata
discovery.

Input:
```json
{
  "sql": "SELECT COUNT(*) as total FROM orders",
  "connection_id": "analytics_demo_sqlite"
}
```

Output:
```json
{
  "success": true,
  "connection_id": "analytics_demo_sqlite",
  "db_type": "sqlite",
  "query": "SELECT COUNT(*) as total FROM orders",
  "data": [
    {"total": 150}
  ],
  "row_count": 1
}
```

### 2. `check_connection`

Usage: Diagnose fresh connection capability for the default, one named alias,
or all configured aliases through one interface:

```python
check_connection()                              # default connection
check_connection(connection_id="analytics_demo_sqlite")  # named connection
check_connection(scope="all")                   # all configured connections
```

`scope` accepts only `"single"` (default) or `"all"`. Omitted/null
`connection_id` selects the default only in single scope. All scope requires an
omitted/null alias; combining it with a non-null alias is rejected before
opening connections. Invalid scopes, blank/unknown aliases, wrong types and
extra arguments are rejected without guessing or falling back.

Use on request or for connection troubleshooting, never as an automatic startup
check or ordinary query prerequisite. A generic connectivity request without
target clues or a resolved target uses the default. A known target must be passed
explicitly. Unresolved purposes, ambiguous references or irreconcilable restrictions
require clarification and waiting; only `list_connections()` may be used to offer
configured candidates. Explicit single-target restrictions narrow a broad request;
prohibitions include diagnostics. If partial checks are rejected, wait instead.
All scope requires a request that permits every configured target. These instructions
and the `scope` parameter are not per-request authorization controls.

Every call uses disposable diagnostic connections, including single scope. It
checks neither business pool health, tables, Skill readiness nor write privileges.
`list_connections()` remains configuration-only.

Single-connection output:

```json
{
  "scope": "single",
  "all_connected": true,
  "complete": true,
  "connection_count": 1,
  "connected_count": 1,
  "cleanup_failed": false,
  "results": {
    "analytics_demo_sqlite": {
      "db_type": "sqlite",
      "status": "connected",
      "connected": true,
      "cleanup_failed": false
    }
  }
}
```

Both scopes use this schema. Results preserve configuration order; counts and
`all_connected` refer only to the selected scope. Single scope has one entry and
never marks other configured aliases `not_checked`. With one configured alias,
`scope="all"` still returns `"scope": "all"`.

`complete` means every selected alias has a confirmed success/failure;
`all_connected` means all selected aliases connected. `failed` has
`connected=false` and a safe error; `timeout` means a started check has no result
by the deadline, and `not_checked` means it did not start before the deadline or
before cleanup failure stopped scheduling. Both incomplete statuses use
`connected=null`. Connection failure, timeout and observed cleanup failure return
normal diagnostic reports. Input errors, busy/stopped diagnostics and cleanup-disabled
requests use the MCP tool error channel outside the report schema.

All diagnostics share one process-wide runner with up to four worker threads
and a 30-second waiting budget. For positive `server.tool_timeout_seconds=T`, use
`min(30, 0.8*T)`; disabling the outer timeout retains 30 seconds. A single or all
request is busy until previous workers finish their cleanup attempts, including
after cancellation/timeout. There is no queue, automatic retry or polling API.
The budget cannot kill a driver call; process exit may also wait for workers.
Validate network faults and the supervisor's termination policy in isolation
before unattended deployment.

Creation, checking and closing occur in the same worker; adapters never enter
the business cache. SQLite files use encoded `mode=ro` URIs and missing files are
not created. `:memory:` tests a fresh disposable memory database only. Read-only
does not guarantee zero filesystem writes: WAL reads may create or update
`-wal`/`-shm` files. No `immutable=1` assumption is made.

A cleanup failure preserves the confirmed connectivity result, sets
`cleanup_failed`, stops further submissions and disables **all diagnostics**
until the server process restarts. Reconnecting the client or cycling lifespan
does not reset it. Other tools remain available. A false flag only means no
failure was observed at report time; late failures still disable future calls
without rewriting earlier reports.

Single-scope `_meta`/telemetry record the selected alias, type and scope; all
scope uses `connection_scope="all"` and counts without a default alias/type.
`success = all_connected and not cleanup_failed`, whereas `call_completed`
records normal report completion. Metadata never requires a business adapter.

**Breaking migration:** `check_connections()` is removed without an alias;
replace it with `check_connection(scope="all")`. Existing single calls retain
input syntax but must read `results[alias].connected` instead of top-level
`connected`; old `message`, `database_name` and `config` fields are removed.
Single checks now share diagnostic isolation, budget, busy and cleanup-disable
behavior. See the [design and migration record](docs/guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md).


### 3. `list_tables`
Usage: Visible Database Overview - List returned/allowed tables and their estimated row counts.

Lightweight initial exploration tool. The table list may be truncated by `limits.overview_tables`. Row counts are INFORMATION_SCHEMA estimates for MySQL (InnoDB estimates may differ significantly from the actual count) or SQLite statistics/sampling.

An individual `row_count` is `null` when no safe estimate is available; it does
not mean that the table is empty. Table discovery remains available in that
case, while tools that must generate metadata SQL can reject an unsupported
identifier explicitly.

If adapter metadata cannot be read, this tool returns `success=false` with
`error_code="metadata_query_failed"` rather than an empty result.

Output:
```json
{
  "success": true,
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [
    {"table_name": "users", "row_count": 150},
    {"table_name": "products", "row_count": 500}
  ],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null,
  "hint": "Row counts are estimates; null means unavailable, not empty. total_tables = visible after allowlist."
}
```

### 4. `describe_table`
Usage: Get Table Structure - Column info, estimated row count, and query suggestions.

Returns full adapter-visible column metadata and estimated row counts from
adapter metadata/statistics (MySQL INFORMATION_SCHEMA; SQLite sqlite_stat1 or
bounded sampling). This is not complete DDL: indexes, foreign keys, checks, and
other backend-specific properties may be absent. Includes `is_large` for query
planning and avoids automatic COUNT(*) full table scans.

If adapter metadata cannot be read, this tool returns `success=false` with
`error_code="metadata_query_failed"` rather than a missing-table or zero-row
result. If MySQL returns no usable estimate, the successful response uses
`row_count=null`, `row_count_approximate=null`, and `is_large=null`; no
large-table recommendation is inferred from the unknown value.

Input:
```json
{
  "table_name": "users"
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "row_count": 1500,
  "row_count_approximate": true,
  "column_count": 2,
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI", "default_value": null},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": "", "default_value": null}
  ],
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
}
```

### 5. `sample` (Optional)
Usage: Retrieve sample data from a specified table.

**Note**: This tool is controlled by `tools.schema` TOML setting (Default: Enabled)

`limit` defaults to 5 and its MCP input schema accepts integers from 1 through
20 inclusive. Out-of-range MCP calls are rejected before SQL execution rather
than silently clamped. Direct Python calls receive the same explicit rejection,
so both entry paths share one range contract.

Input:
```json
{
  "table_name": "users",
  "limit": 5
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "data": [
    {"id": 1, "name": "Alice"},
    {"id": 2, "name": "Bob"}
  ],
  "row_count": 2,
  "query": "SELECT * FROM `users` LIMIT 5"
}
```

### 6. `get_full_schema`
Usage: Fetch a compact or full visible database schema overview in one call.

`detail_level="compact"` is the machine-visible default and is intended for broad table explanations and multi-table planning; omitting the parameter is equivalent to passing `compact`. It returns `[name, type]` column pairs, primary keys, column counts, and every table's row estimate. With `group_identical=true` (the default), tables share a group only when all column metadata currently exposed by the adapter and the column order are equal. For MySQL, that comparison covers column name, base data type, nullability, key marker, and default; it does **not** prove equality of complete DDL, indexes, foreign keys, checks, length/precision, unsigned flags, collations, or generated expressions. The response records this boundary in `grouping_basis`. Set `group_identical=false` when every compact table must remain separate; the parameter is ignored in full mode.

Request `detail_level="full"` explicitly for `nullable`, `default`, and key metadata across multiple tables. A database/metadata failure returns `success=false` with `error_code="metadata_query_failed"` instead of being reported as an empty database, empty schema, missing table, or zero-row estimate. A row estimate can be `null` when unavailable; null does not mean empty. If table discovery returns a database identifier outside the schema tools' conservative identifier grammar, projection fails explicitly with `error_code="unsupported_metadata_identifier"` rather than misclassifying it as a query failure or emitting an empty table. The visible table set may be filtered by allowlist and truncated by `limits.schema_tables`; use `describe_table()` for one-table drill-down.

Compact output:
```json
{
  "success": true,
  "detail_level": "compact",
  "schema_groups": [
    {
      "tables": [{"name": "users", "row_count": 150}],
      "column_count": 2,
      "columns": [["id", "int"], ["name", "varchar"]],
      "primary_key": ["id"]
    }
  ],
  "schema_group_count": 1,
  "grouped_by_schema": true,
  "grouping_basis": "adapter_visible_column_metadata_and_order",
  "returned_table_count": 1,
  "total_tables": 1,
  "total_columns": 2,
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null
}
```

Full output keeps the table-keyed `schema` mapping. Each column contains
`name`, `type`, `nullable`, `key`, and `default` from the database adapter.

### 7. `get_table_summary` (Optional)
Usage: Get table statistics, supports optional exact row count calculation.

**Note**: This tool is controlled by `tools.table_summary` TOML setting (Default: **Disabled**). `describe_table()` tool already provides estimated row counts, so this tool is needed only when precise counting is required.

**Warning**: `exact_count=True` will run COUNT(*), which may be slow on large
tables (full table scan; MySQL may also encounter metadata-lock contention).
This cost warning is also part of the machine-visible parameter description.
If adapter row-estimate metadata (`exact_count=false`) or column metadata in
either mode cannot be read, the tool returns `success=false` with
`error_code="metadata_query_failed"` rather than an empty, missing, or zero-row
result. An explicit `COUNT(*)` execution failure uses its existing query-error
response instead. If MySQL returns an unavailable estimate without a query
failure, the approximate response preserves `row_count=null`,
`row_count_approximate=null`, and `is_large=null`; `exact_count=true` retains
integer row counts and boolean classification fields.

Input:
```json
{
  "table_name": "users",
  "exact_count": false
}
```

Output:
```json
{
  "success": true,
  "table_name": "users",
  "row_count": 1500,
  "row_count_approximate": true,
  "column_count": 2,
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI", "default_value": null},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": "", "default_value": null}
  ],
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
}
```

### 8. `list_skills` (Skills Extension, Optional)
Usage: List pre-defined skills (query and mutation), with optional search, category filtering, metadata projection, and availability filtering.

**Note**: Requires `skills.enabled=true`. `detail_level` is a non-null `compact|summary|full` enum. Its machine-visible default is the startup-resolved `skills.discovery.default_detail` (`summary` by default); `full` already includes parameter schemas, so do not follow it with `get_skill_detail()`. `available_only` is a non-null boolean whose machine-visible default likewise equals the startup-resolved `skills.discovery.available_only` (`true` by default), so Agent-facing discovery hides skills that cannot execute for the target `connection_id` because of optional Skill `connection_ids` scope, DB type compatibility, mutation switches/write policy, query connection allowlist, missing required tables, or an unavailable enabled schema-readiness check. In the last case `schema_check_available=false` distinguishes “unverified” from a known `missing_tables` result. Pass `available_only=false` to inspect the full developer catalog and failure reasons. This only changes Agent-facing metadata disclosure; execution repeats the authoritative checks and fails closed when enabled readiness cannot be verified. Query Skills accept `connection_id`; mutation Skills also accept it when strict named-write policy authorizes the target.

In summary/full output, `configured_connection_ids` means the subset of that
Skill's declared `connection_ids` present in this deployment; it is not the
server's complete connection registry. `unconfigured_connection_ids` is the
declared portable remainder, and `connection_type_conflicts` reports declared
configured members whose actual DB type does not match `databases`.

Input:
```json
{
  "search": "revenue",
  "category": "reporting",
  "detail_level": "summary",
  "available_only": true
}
```

Output:
```json
{
  "success": true,
  "skills": [
    {
      "name": "sample-monthly-sales-report-sqlite",
      "type": "query",
      "risk": "low",
      "description": "Generate a SQLite monthly sales summary report...",
      "category": "reporting",
      "executable": true,
      "schema_ready": true,
      "source": "query.sql",
      "triggers": ["monthly sales", "revenue report"],
      "idempotent": true,
      "databases": ["sqlite"],
      "connection_ids": null,
      "configured_connection_ids": [],
      "unconfigured_connection_ids": [],
      "connection_type_conflicts": [],
      "connection_scope_allowed": true,
      "profiles": ["demo"]
    }
  ],
  "total_skills": 4,
  "matched_skills": 1,
  "matched_catalog_skills": 2,
  "available_skills": 1,
  "unavailable_skills": 1,
  "filtered_unavailable_skills": 1,
  "schema_unready_skills": 0,
  "connection_scope_blocked_skills": 0,
  "connection_type_conflict_skills": 0,
  "query_skills": 1,
  "mutation_skills": 0,
  "mutations_enabled": false,
  "schema_check_enabled": true,
  "schema_check_available": true,
  "detail_level": "summary",
  "available_only": true,
  "current_database_type": "sqlite",
  "connection_id": "analytics_demo_sqlite",
  "search": "revenue",
  "category": "reporting",
  "categories": [{"category": "reporting", "count": 1}],
  "hint": "If params are not already known, call get_skill_detail(skill_name, connection_id, detail_level='execution') with the same target connection before execution."
}
```

### 9. `get_skill_detail` (Skills Extension, Optional)
Usage: Retrieve cached execution fields or full metadata for a single skill.

**Note**: Requires `skills.enabled=true`. `detail_level` is a non-null `execution|full` enum with machine-visible default `full`. Use `execution` when the Skill name is known but params are not; it is the recommended projection for parameter schema and the next action. Reserve `full` for explicit catalog/readiness diagnostics, and do not call this tool when `list_skills(detail_level="full")` already returned params. The execution projection contains only invocation fields, resolved connection/DB type, and the next action. This tool does not read skill files at runtime and does not expose raw SQL or mutation Python source. Only parsed YAML frontmatter values can enter these MCP responses; YAML comments and the Markdown body remain developer documentation and do not consume Agent context.

Input:
```json
{
  "skill_name": "sample-monthly-sales-report",
  "connection_id": "trade_analysis_mysql",
  "detail_level": "execution"
}
```

Output:
```json
{
  "success": true,
  "skill": {
    "name": "sample-monthly-sales-report",
    "type": "query",
    "params": {
      "year": {"type": "int", "required": true},
      "month": {"type": "int", "required": true, "min": 1, "max": 12}
    },
    "executable": true,
    "requires_confirmation": false
  },
  "connection_id": "trade_analysis_mysql",
  "current_database_type": "mysql",
  "usage_hint": "Call execute_query_skill(skill_name, params, connection_id) with this same target connection and params matching the schema."
}
```

### 10. `execute_query_skill` (Skills Extension, Optional)
Usage: Execute a pre-defined query skill with parameterized SQL.

**Note**: Requires `skills.enabled=true`. Query Skills are reviewed SQL templates that are validated at startup for read-only/structural safety and re-checked at runtime against the resolved target connection, including per-connection table allowlists. They no longer rely on a pure startup-only trust path.

Input:
```json
{
  "skill_name": "sample-monthly-sales-report",
  "params": {"year": 2026, "month": 1}
}
```

### 11. `execute_mutation_skill` (Skills Extension, Optional)
Usage: Execute a pre-defined mutation (write) skill through the two-phase preview/execute gate.

**Note**: Requires `skills.enabled=true` and `skills.mutation.enabled=true`. Follows validate → preview → execute pattern.

Input:
```json
{
  "skill_name": "sample-update-order-status",
  "params": {"order_id": 42, "new_status": "shipped"},
  "confirm": false
}
```

`confirm=false` (default) returns a preview and `preview_token`. `confirm=true`
executes the mutation only when the same call includes the matching
`preview_token`. Every returned payload includes `execution_outcome`; returned
failures also include stable `error_code` and sanitized `error`. Static
parameter/permission/Skill/token rejection still raises `ToolError`. Clients
must inspect both `success` and `execution_outcome`: a committed response-stage
failure can be `success=false, execution_outcome=committed`, while an exception
or missing response remains unknown to the client. `committed` is emitted only
from preserved successful adapter COMMIT evidence for a validated managed plan;
an imperative custom-Skill success is `success=true, execution_outcome=unknown`
and is terminal in the reference host. A custom result with missing/false/
malformed `success` becomes a structured unknown failure rather than being
upgraded by the server. For pre-COMMIT cleanup, `rollback_failed` means the
rollback call raised; `rollback_unconfirmed` means it returned locally but the
transaction/connection could not provide sufficient database-side evidence.
Both carry `execution_outcome=unknown` and must not be retried automatically.
`MutationBase.run_execute()` is framework-owned for imperative Skills: discovery rejects custom
classes that override it directly or through an intermediate base class.
Custom Skill authors must put business logic in `execute()` or
`execute_with_binding()` so the framework cannot accidentally lose its outcome,
sanitization, or audit wrapper. Python `@final` documents the rule for type
checkers; the loader check enforces it at runtime. This is not an untrusted-code
sandbox. MCP invokes the base wrapper directly, so replacing the subclass method
after discovery is ignored; trusted code can still tamper with the framework
base or other in-process objects.
`exact_transaction_outcome` is no longer supported. A custom Skill that needs
exact single-statement database evidence must inherit `ManagedMutationBase` and
declare a valid immutable `ManagedMutationPlan`. At confirmation, the framework
uses the cached plan and never invokes a Skill execution callback. This proves
the outcome of that managed database statement, not the absence of effects from
module import, preview callbacks, malicious in-process monkeypatching, or other
code in the same trust boundary.
For managed Skills, the framework generates `preview_sql` and `bound_params`
from that same cached plan and final binding before issuing a token. Skill
callbacks supply only business context, warnings and binding state; supplying
either reserved preview field or failing value resolution returns a tool error
without a token. Descriptive prose and estimates remain Skill-provided content.
`error_code` is an extensible string set: published meanings stay stable, but
clients must tolerate new codes and rely on identity validation, `success` and
`execution_outcome`. An unknown code never permits automatic retry.
`managed_plan_resolution_failed` means confirmation-time resolution failed
before the adapter write call, with `execution_outcome=not_executed`.
This release has no durable operation ID or receipt lookup. A later business
state that matches the request does not prove request-level attribution, and an
absent future receipt would not by itself prove rollback unless that protocol
explicitly defines authoritative consistency, in-progress, retention, and
terminal-not-found semantics. The deferred design trigger is tracked in
DRR-2026-061 rather than a separate speculative plan.

### 12. `request_mutation_approval` (Optional MRTR Approval)

Usage: prepare an immutable managed single-statement proposal, collect approval through a trusted Host, and execute once on a valid continuation.

**Requirements**: `skills.mutation.mrtr.enabled=true`, Skills and writes enabled, complete target authorization, MCP `2026-07-28` and client form elicitation. The tool is absent by default. Unsupported protocols and imperative Skills are explicitly refused; existing preview/execute remains available.

Input:
```json
{
  "skill_name": "sample-update-order-status",
  "params": {"order_id": 42, "new_status": "shipped"},
  "connection_id": "analytics_demo_sqlite"
}
```

The first round returns `InputRequiredResult` with target, Skill, normalized parameters, SQL, bindings and expiry, without executing the managed write. The Host/framework handles input responses and sealed request_state; the model need not copy raw bearer tokens. The server saves that exact review (at most 64 KiB). Missing answers resend it; a new preview cannot inherit an earlier approval.

Only a valid accept with strict boolean `approve=true` reaches shared execution. Decline/cancel closes the proposal. Original expiry, binding and atomic single consumption remain authoritative. Waiting holds no transaction or row lock; repeated continuation cannot authorize another execution. Failures after consumption never restore the token, and missing state or a lost response does not prove no prior write occurred. Inspect `success` and `execution_outcome`; never automatically retry an uncertain write.

This verifies the trusted Host's decision against a proposal, not an independently authenticated human. Reference Host `--flow mrtr` and protocol tests cover the flow; actual Codex/Copilot limits are recorded in [validation](docs/validation/V3_8_VALIDATION_ZH.md).

### Skills Extension Details (Since v3.0)

Skills are pre-defined, parameterized SQL operations that encapsulate common business queries and data mutations. Unlike the core `query()` tool where the Agent writes free-form SQL, Skills provide code-reviewed SQL templates — the Agent only needs to pass parameters.

**Why Skills?**
- **Fewer errors**: Complex multi-table JOINs and aggregations are error-prone; pre-defined templates ensure SQL correctness
- **Safe writes**: Core tools only support read-only queries (SELECT); Skills use a server-enforced preview/token gate and best-effort audit metadata. Optional host approval uses the retained preview/execute flow or managed MRTR in v3.8
- **Efficiency**: Agent skips multi-round schema exploration and SQL authoring — one call does the job
- **Extensible**: Developers can add custom Skills for their specific business needs

#### Example 1: `sample-monthly-sales-report` (Query Skill)

**Goal**: Generate a daily sales summary for a specified month, including revenue, order count, and average order value.

**Directory structure**:
```
skills/sample-monthly-sales-report/
├── skill_def.md    # Skill definition (YAML metadata + usage docs)
└── query.sql       # SQL template
```

**Metadata** (YAML frontmatter in `skill_def.md`):
```yaml
name: sample-monthly-sales-report   # Required; must match the skill directory name
type: query              # Read-only, no data modification
source: query.sql        # Explicit execution file declaration (required)
risk: low
databases: [mysql]       # Optional: supported DB types (omit = all)
# connection_ids: [sales_primary, sales_reporting] # Optional deployment-specific v3.7 scope
params:
  year: {type: int, required: true, description: "Year (e.g. 2026)"}
  month: {type: int, required: true, min: 1, max: 12, description: "Month (1-12)"}
triggers:                # Keyword hints to help agents match this skill
  - monthly sales
  - revenue report
  - sales summary
```

**`query.sql`**:
```sql
SELECT
    DATE(order_date) AS date,
    COUNT(*) AS order_count,
    SUM(amount) AS revenue,
    ROUND(AVG(amount), 2) AS avg_order_value
FROM orders
WHERE YEAR(order_date) = :year
  AND MONTH(order_date) = :month
GROUP BY DATE(order_date)
ORDER BY date ASC
```

**Invocation**: Agent calls via `execute_query_skill`:
```json
{"skill_name": "sample-monthly-sales-report", "params": {"year": 2026, "month": 1}}
```

**How it works**: On server startup, `sql_safety_executor.skills.catalog.SkillCatalog` scans the `skills/` directory, parses the YAML frontmatter from `skill_def.md`, reads the source file declared by the `source` field, and validates it via `is_sql_safe()`. At runtime, the Agent passes `year` and `month` parameters, and the server executes the query safely using SQLAlchemy's parameterized binding (`:year`, `:month`), preventing SQL injection.

#### SQLite counterpart: `sample-monthly-sales-report-sqlite`

The repository also includes `sample-monthly-sales-report-sqlite` for the sample SQLite database. It is intentionally a separate skill instead of a dialect branch inside the MySQL skill:

```yaml
name: sample-monthly-sales-report-sqlite
type: query
source: query.sql
risk: low
databases: [sqlite]
profiles: [demo]
params:
  year: {type: int, required: true, description: "Year (e.g. 2026)"}
  month: {type: int, required: true, min: 1, max: 12, description: "Month (1-12)"}
category: reporting
related_skills:
  - sample-monthly-sales-report
```

The SQLite query uses the demo schema's `orders.total_amount` column and ISO-8601 text dates:

```sql
SELECT
    date(order_date) AS date,
    COUNT(*) AS order_count,
    COALESCE(SUM(total_amount), 0) AS revenue,
    ROUND(AVG(total_amount), 2) AS avg_order_value
FROM orders
WHERE order_date >= printf('%04d-%02d-01', :year, :month)
  AND order_date < date(printf('%04d-%02d-01', :year, :month), '+1 month')
GROUP BY date(order_date)
ORDER BY date ASC
```

The bundled `sample-monthly-sales-report`, `sample-monthly-sales-report-sqlite`, `sample-update-order-status`, and `sample-reset-order-to-pending` skills are marked with `profiles: [demo]` because they require an `orders` demo schema. With `skills.readiness.check_schema=true`, `available_only=true` hides them when the target connection does not contain their required tables or when database metadata is unavailable and readiness cannot be verified. Dialect-specific query SQL remains in separate Skills, while portable mutations explicitly declare both supported database types; this keeps startup validation simple and makes `available_only` filtering deterministic for Agents.

#### Example 2: `sample-update-order-status` (Mutation Skill)

**Goal**: Safely update an order's status using state machine constraints to prevent illegal transitions (e.g., cannot jump from "pending" to "delivered").

**Directory structure**:
```
skills/sample-update-order-status/
├── skill_def.md                  # Skill definition
├── mutation.py                   # Preview logic + immutable managed write plan
└── references/
    └── status-transitions.md     # State machine documentation
```

**Metadata**:
```yaml
name: sample-update-order-status
type: mutation                     # Write operation
source: mutation.py                # Validated implementation file
risk: medium
requires_confirmation: true        # Requests preview/execute + client confirmation UX; not human-identity proof
params:
  order_id: {type: int, required: true, description: "Order ID"}
  new_status: {type: str, required: true, 
    enum: [pending, confirmed, shipped, delivered, cancelled, returned],
    description: "Target status"}
```

**State transition rules** (built into `mutation.py`):
```
pending    → confirmed, cancelled
confirmed  → shipped, cancelled
shipped    → delivered, returned
delivered  → returned
cancelled  → (terminal state)
returned   → (terminal state)
```

**Two-phase invocation**:

1. **Preview** (`confirm=false`, default) — look before you leap:
```json
{"skill_name": "sample-update-order-status",
 "params": {"order_id": 42, "new_status": "shipped"},
 "confirm": false}
```
Returns the SQL that would be executed, its expected impact, and a random
256-bit API-opaque bearer `preview_token` handle, without modifying data.

2. **Execute** (`confirm=true`) — write after confirmation and token validation:
```json
{"skill_name": "sample-update-order-status",
 "params": {"order_id": 42, "new_status": "shipped"},
 "confirm": true,
 "preview_token": "<token returned by preview>"}
```

The server-side Store record is bound to the skill name, skill version,
canonical params, resolved `connection_id`, DB type, expiry, and the minimal
preview-time execution state. The handle is one-time: execute atomically
matches and consumes its record before imperative dynamic validation or the
managed/imperative database write. Any later outcome, including validation,
database, timeout, audit, or
response failure, leaves the handle consumed. If the write result is uncertain,
inspect current business state before deciding whether another preview/mutation
is appropriate; do not blindly retry. Static request/policy rejection or a
request-binding mismatch does not consume the valid record. Handles default to
`skills.mutation.preview.ttl_seconds=300`, with a valid range of `1-86400`.
The process-local memory store loses all outstanding handles on process restart.
Preview and execute must reach the same process; cross-worker/cross-replica
mutation execution is unsupported and never enables stateless token acceptance.
Clients must not parse the handle or depend on its format. Because it
necessarily passes through the authorized client and may enter model context,
clients should minimize durable retention and logging and protect access to
context and logs. Bearer confidentiality matters until consumption or expiry;
short TTL, exact binding, and one-time use limit but do not eliminate the impact
of disclosure. The short `preview_token_id` in applicable tool metadata is only
a client correlation hint; audit and telemetry persist neither the full token
nor that short identifier.

**Safety mechanisms**:
- **State machine validation**: `validate()` checks if current status allows transition to target status
- **Preview-token binding**: `confirm=true` must include the token returned by the matching preview call
- **One-time consumption**: a token can authorize at most one execute attempt; uncertain outcomes are not automatically retried
- **Preview-state binding**: managed Skills use `build_execution_binding()` to
  capture displayed state; confirmation resolves that binding into the cached
  SQL predicate without calling Skill Python again
- **Failed-preview handling**: a preview result containing `error` or reporting `success=false` receives no token
- **Optimistic locking**: Uses `WHERE status = :expected_status` at execution time and `expected_rowcount=1` before COMMIT; zero or multiple rows roll back
- **Transaction outcome**: pre-COMMIT failures report `rolled_back` only when rollback is confirmed; COMMIT acknowledgement failure reports `unknown`; MySQL guarantees are limited to transactional InnoDB DML
- **Audit logging**: Mutation preview/execute paths attempt best-effort JSONL audit logging; audit write failures do not roll back data changes

#### Example 3: `sample-reset-order-to-pending` (Portable Demo Reset)

This demo/test Skill accepts `order_id` and the exact non-pending state expected
after a preceding live-test mutation. Its target is fixed to `pending` in
reviewed code, and its SQL is compatible with MySQL and SQLite:

```yaml
name: sample-reset-order-to-pending
type: mutation
source: mutation.py
risk: medium
requires_confirmation: true
idempotent: false
databases: [mysql, sqlite]
# connection_ids: [orders_demo_mysql, orders_demo_sqlite]
profiles: [demo]
tables: [orders]
params:
  order_id: {type: int, required: true, min: 1}
  expected_status: {type: str, required: true,
    enum: [confirmed, shipped, delivered, cancelled, returned]}
```

The reset first asserts that the current state equals the caller's
`expected_status`; preview displays and binds that state, and execution repeats
it in `WHERE id=:order_id AND status=:expected_status`. This makes the call both
a test assertion and a compensating cleanup mutation. It is not a transactional
rollback or a production order-reopening API, and cleanup may still fail after
the preceding write committed.

Supported schemas must define `orders.id` as `PRIMARY KEY` or `UNIQUE`. The
commented aliases are not routes or permissions until an operator enables
them. Because the Skill intentionally creates `pending -> X -> pending`, use
dedicated demo/test records, avoid overlapping previews for the same order, and
prefer a fresh stdio server process for each live-test scenario.

#### Adding Custom Skills

Bundled examples use the reserved `sample-` prefix. Create your own Skill in a
directory such as `skills/my-report/` without that prefix. Git ignores immediate
subdirectories of `skills/` except the four bundled examples explicitly listed
in `.gitignore`; the framework SDK now lives in the installed package. New `sample-*` directories
are also ignored; adding a bundled example requires updating `.gitignore`.
Keep the directory name and frontmatter `name` identical.
The prefix is a repository convention, not execution permission or managed-plan
eligibility. Metadata/path checks, mutation switches, connection allowlists,
and managed-plan validation still apply.

`skills/SKILLS.md` can be explicitly exported; v3.8 startup does not generate it. The old `skills/_audit.jsonl` remains ignored; the current default is `../logs/skill_audit.jsonl` relative to the Skills TOML. The examples below and their tracked `skill_def.md` files provide shared documentation. Existing
tracked custom files are not untracked automatically by `.gitignore`.
Use `git rm --cached -r -- skills/my-report/` to stop tracking an existing
custom directory while preserving its local files. Custom `skills.directory` and
audit paths need corresponding ignore rules if stored inside your repository.
See the [name migration table](docs/releases/RELEASE_NOTES_v3_7.md#sample-skill-names-and-local-files)
when upgrading an existing configuration.

Review all custom Skill files and their dependencies before deploying or
restarting the server. Git ignore rules do not affect discovery or provide
execution isolation: mutation modules are imported during discovery when
`skills.mutation.enabled=true`,
which executes their module-level Python code. Use least-privilege database
credentials and review the actual Skill directory together with connection
policies; see [Skills security governance](docs/security/SAFETY.md#11-mutationpy-execution-constraints).

**Query skills** (read-only):
1. Create a directory under `skills/`, e.g. `skills/my-report/`
2. Write `skill_def.md` (YAML frontmatter + documentation), must include `source` field pointing to the SQL file (e.g. `source: my-report.sql`)
  - The frontmatter `name` is required, must match the directory name, and must follow `^[a-z0-9][a-z0-9-]*$`
  - Unknown frontmatter fields and duplicate YAML mapping keys are rejected.
    This prevents a misspelled security field from being silently ignored;
    future custom metadata needs an explicitly supported extension field.
  - Optional `connection_ids` must be a non-empty list of valid alias
    identifiers. Only members configured in the current deployment can run;
    portable unconfigured members remain visible as unavailable. The field
    only narrows targets; omission preserves previous behavior, and a call
    without `connection_id` still resolves the global default rather than the
    first list member
3. Write the corresponding `.sql` file (use `:param_name` as parameter placeholders), filename must match the `source` field
4. Restart the server — the skill is auto-discovered and registered

v3.8 extensions import the installed SDK without injecting `skills/_lib` into `sys.path`:

```python
from sql_safety_executor.skills import (
    ManagedMutationBase, ManagedMutationPlan, ManagedMutationValue,
    MutationBase, OperationError,
)
```

Use `OperationError` for business failures; the MCP boundary converts it. See the [import migration table](docs/guides/CONFIGURATION_ZH.md#扩展导入与切换). External directories must be explicitly configured and trusted; resolved definitions/sources stay within the declared root. This is not a Python sandbox.

**Mutation skills** (write):
1. Create the directory and `skill_def.md` as above (`type: mutation`), must include `source` field pointing to the Python file (e.g. `source: mutation.py`)
2. Prefer a concrete `Mutation` class inheriting from `ManagedMutationBase`.
   Declare one immutable `ManagedMutationPlan` containing a direct parameterized
   INSERT/UPDATE/DELETE, its named value sources, `expected_rowcount`, and any
   public result fields. Implement `validate()`, `preview()`, and optional
   `build_execution_binding()` for preview only. Confirmation never calls Skill
   Python, so put every mutable invariant in the SQL predicate and bind preview
   state explicitly. Return business context/warnings/state only from managed
   `preview()`; remove Skill-defined `preview_sql` and `bound_params`. The
   framework generates them and rejects unresolved SQL/result values before
   issuing a token. See [the reserved result fields](docs/security/SAFETY.md#11-mutationpy-execution-constraints)
3. Use `MutationBase` only for a reviewed imperative workflow that cannot fit
   one statement. Implement `validate()`, `preview()`, `execute()`, and when
   needed `build_execution_binding()` / `execute_with_binding()`. The whole
   operation always reports `execution_outcome=unknown`
4. Do not override `run_execute()`, including through an intermediate custom
   base class. It is the framework-owned wrapper for the imperative path
5. Remove `exact_transaction_outcome`; discovery rejects this obsolete flag.
   Managed eligibility comes from the validated plan type, not a Skill name,
   file path, boolean declaration, or returned Python object
6. Enable `skills.enabled=true` and `skills.mutation.enabled=true`, list the target in `skills.mutation.allowed_connections`, and set that connection's `mutation.enabled=true` with the Skill in `mutation.skills`. Every gate also applies to the default connection; database grants remain necessary.
7. After reviewing the Skill code and connection policies, restart the server

> **About the `source` field**: `source` is a mandatory field that explicitly declares the association
> between the skill definition file (`skill_def.md`) and its execution file. This follows the
> **Explicit Configuration** principle, consistent with industry standards like GitHub Actions
> (`action.yml`'s `main` field) and npm (`package.json`'s `main` field).
> The `source` filename is validated for security: no path traversal allowed, suffix must match
> `type` (query→`.sql`, mutation→`.py`).

For the design background, see [MCP_AGENTS_SKILLS_DESIGN.md](docs/architecture/MCP_AGENTS_SKILLS_DESIGN.md) and the [historical Skills security policy](docs/security/SAFETY.md). Current deployment and extension contracts are in the [v3.8 configuration guide](docs/guides/CONFIGURATION_ZH.md) and [security boundaries](docs/security/V3_8_SECURITY.md).

#### Skills Design Architecture

**Skill Lifecycle**

Each Skill goes through three phases from authoring to runtime. The core design decision is to **separate startup-time artifact validation from runtime target-connection policy enforcement**. Startup rejects malformed or structurally unsafe skill artifacts early; runtime still resolves the target connection and enforces DB compatibility, schema readiness, per-connection allowlists, parameter validation, execution controls, metadata, audit, and telemetry.

```mermaid
flowchart LR
    subgraph Author["Phase 1: Authoring"]
        D1["skill_def.md\nYAML metadata\n+ docs"]
        D2["query.sql\nSQL template"]
        D3["mutation.py\nPython logic"]
    end

    subgraph Startup["Phase 2: Server Startup — discover()"]
        S1["Scan skills/ directory"]
        S2["Parse YAML frontmatter"]
        S3["SQL safety check\nis_sql_safe()"]
        S4["Import allowed Mutation classes\nimportlib.util"]
        S5["Write to instance catalog\nSkillCatalog"]
        S6["Optional overview export"]
    end

    subgraph Runtime["Phase 3: Runtime — Agent Interaction"]
        R1["list_skills()\nMetadata catalog"]
        R2["get_skill_detail()\nCached params schema"]
        R3["execute_query_skill()\nCached SQL + params"]
        R4["execute_mutation_skill()\nCached class + params"]
    end

    D1 --> S1
    D2 --> S1
    D3 --> S1
    S1 --> S2 --> S3 & S4
    S3 --> S5
    S4 --> S5
    S5 -.-> S6
    S5 -.->|"Memory cache"| R1 & R2 & R3 & R4
```

> Startup validation follows the **fail-fast principle** — if a Skill's SQL is unsafe or its source module is malformed,
> the server rejects registration at startup rather than failing on first invocation.
> This aligns with [MCP Specification §7 — Security](https://modelcontextprotocol.io/specification/2025-03-26/basic/security):
> *"Validate all inputs"* and *"Implement proper access controls."*

**Mutation Two-Phase Execution Flow**

Mutation Skills provide an intermediate preview for review. This applies the workflow-checking approach discussed in [Anthropic's Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents); it is this project's design, not a prescribed Anthropic protocol. Agents can inspect it; a user reviews it only when a client/host renders it and collects a decision.

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as MCP Server
    participant Mutation as MutationBase
    participant Adapter as DatabaseAdapter
    participant Audit as AuditLogger
    participant DB as Database

    Note over Agent,DB: Phase 1: Preview (confirm=false)
    Agent->>MCP: execute_mutation_skill(skill_name, params, false)
    MCP->>MCP: validate_name() + validate_params()
    MCP->>Mutation: validate(params)
    Mutation->>DB: SELECT query for current state
    DB-->>Mutation: Current record
    MCP->>Mutation: preview(params)
    Mutation-->>MCP: Business context + binding state
    MCP->>Mutation: build_execution_binding(params, validation, preview)
    Mutation-->>MCP: Final binding
    MCP->>MCP: Resolve plan values; generate SQL/bound_params; issue token
    MCP-->>Agent: Preview + preview_token (no framework write)

    Note over Agent,DB: Phase 2: Confirm Execute (confirm=true)
    Agent->>MCP: execute_mutation_skill(skill_name, params, true, preview_token)
    MCP->>MCP: validate_name + validate_params (re-validate)
    MCP->>MCP: look up handle; compare request binding; atomically consume
    MCP->>MCP: resolve cached ManagedMutationPlan + preview binding
    MCP->>Adapter: execute_write(UPDATE ... WHERE status=:expected, expected_rowcount=1)
    Adapter->>DB: BEGIN → UPDATE → COMMIT
    DB-->>Adapter: rowcount
    MCP->>Audit: log(operation details)
    MCP-->>Agent: Execution result
```

> **Design references**:
> - Prefer simple, composable workflows; add complexity when justified (paraphrase). — [Anthropic, Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents). The managed single-statement path is this project's application of that advice.
> - Managed confirmation does not repeat a Python validation callback. Its TOCTOU
>   protection is the preview-bound SQL predicate plus the pre-COMMIT row-count
>   invariant. Imperative Skills retain execute-time re-validation and `unknown`
>   whole-operation semantics
> - Parameter binding uses SQLAlchemy `text()` + parameter dicts, following [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) standards

**skill_def.md Format Design**

`skill_def.md` uses a layered design of YAML frontmatter + Markdown body, serving different audiences:

- **YAML frontmatter** (top section): Machine-parsed by `sql_safety_executor.skills.catalog.SkillCatalog` at server startup, extracting structured fields like `name`, `type`, `params` for registration and validation. Agents access this metadata (formatted) via `list_skills()` and `get_skill_detail()`, not by reading the file directly.
- **Markdown body** (bottom section): Natural language documentation for developers (usage instructions, workflow hints, notes, etc.). **Not sent to the Agent** — this is a key difference from standard Agent Skills: the standard SKILL.md body contains instructions for the Agent to read, while this project's body is documentation for humans.
- **Parameter constraint declarations**: `type`/`min`/`max`/`enum` declared in YAML, enforced uniformly by `validate_params()`. Skill authors don't need to duplicate validation logic in code.

**Example** — using `sample-monthly-sales-report`'s `skill_def.md`:

```yaml
---
name: sample-monthly-sales-report          # Name constraint: ^[a-z0-9][a-z0-9-]*$
type: query                         # query | mutation
source: query.sql                   # Explicit execution file (required, suffix must match type)
risk: low                           # low | medium | high
databases: [mysql]                  # Optional: supported DB types (omit = all)
# connection_ids:                   # Optional deployment-specific v3.7 scope
#   - orders_primary
#   - orders_reporting
params:                             # Parameter schema (Server-side enforced)
  year: {type: int, required: true} #   → validate_params() checks type
  month: {type: int, required: true,
          min: 1, max: 12}          #   → Range constraint, blocks out-of-bounds
triggers:                           # Keyword hints (for Agent matching)
  - monthly sales
  - revenue report
---
## Usage                            ← Markdown body: developer-visible only
execute_query_skill("sample-monthly-sales-report", {"year": 2026, "month": 1})

## Notes
- Uses MySQL YEAR()/MONTH() functions, SQLite requires replacement
```

In the example above, after the Server extracts the parameter schema from YAML:
1. Agent passes `{"year": 2026, "month": 13}` → Server rejects (`month` exceeds `max: 12`)
2. Agent passes undefined parameter `{"year": 2026, "month": 1, "limit": 10}` → Server rejects (`unexpected` parameter)
3. Agent passes `{"year": "2026", "month": "1"}` → Server auto-coerces types (`_coerce_type()` → `int`)

This follows Google's [Function Calling Best Practices](https://ai.google.dev/gemini-api/docs/function-calling#best_practices): *"Use strong schema: specify types, limits, enums, and valid patterns"* — constraining parameters at the schema level rather than relying on the Agent's natural language understanding.

**Industry Best Practices Alignment**:
| Best Practice | Source | This Project's Implementation |
|----------|------|-------------|
| *"Offload the burden from the model and use code where possible."* | [OpenAI — Function Calling (2025)](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions) | Skills pre-build SQL/Python logic, Agent only passes parameters |
| *"Use clear and descriptive function/parameter names and descriptions."* | [Google Gemini — Function Calling](https://ai.google.dev/gemini-api/docs/function-calling#best_practices) | YAML frontmatter provides structured names, descriptions, and parameter constraints |
| Prefer simple, composable workflows (paraphrase) | [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | Project design: a managed plan specifies one framework-executed statement |
| *"Validate all inputs"* | [MCP Specification §7 — Security](https://modelcontextprotocol.io/specification/2025-03-26/basic/security) | Skills execution calls validate skill names and params; base tools use SQL/table-specific validators |
| Parameterized queries | [OWASP — SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) | SQLAlchemy `text()` + parameter binding, zero string concatenation |

For complete design details, execution flow diagrams, and industry best practices alignment analysis, see [MCP_AGENTS_SKILLS_DESIGN.md](docs/architecture/MCP_AGENTS_SKILLS_DESIGN.md).


## Requirements

- Python 3.12+ and a MySQL or SQLite database.
- FastMCP 4.0.10 / MCP SDK 2.2.0; SQLAlchemy, sqlparse, PyMySQL, Pydantic and PyYAML are managed by `pyproject.toml` and locked in `uv.lock`.
- AutoGen examples use a separate environment. Indirect python-dotenv installation does not imply support for old environment configuration.

## Testing

Default pytest collection is limited to `tests/` by `pyproject.toml`, with isolated temporary configuration and SQLite fixtures; the private `.env` is not loaded. Optional MySQL integration checks require `RUN_MYSQL_INTEGRATION_TESTS=1` and explicitly exported test credentials. This is a test-fixture input, not a server configuration fallback.

```bash
uv run pytest -q -rs
uv run pyright
uv build
```

v3.8 results: 744 passed, 4 skipped; clean type checks; installed-wheel prompts and modern/legacy protocol queries verified outside the repository. Four live MySQL checks remain disabled. CI is configured but has not been pushed/run remotely; native Host successes and limitations are recorded separately in [validation](docs/validation/V3_8_VALIDATION_ZH.md).

Later [live review and native reconnection tests](docs/validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md) verified MySQL connection/basic read probes and a native SQLite preview/execute/compensation cycle. Three isolated GPT-6 Luna agents completed six rounds each (22 calls, no observed wrong-target access); the host-directed write fixture was restored. These are separate from the four skipped MySQL integration tests and do not establish native MRTR, human approval UI or MySQL write behavior. Native subagent usage/protocol were not exposed; no cost or negotiated-version claims are inferred.

### Test Scripts

#### 1. `scripts/query.py` — Core Query Check

Runs the complete read policy shared with MCP and actually accesses the selected database. Use an appropriate test target:

```bash
uv run python scripts/query.py --config config/examples/sqlite/server.toml \
  --connection-id demo 'SELECT 1 AS value'
```

#### 2. `scripts/inspect_mcp.py` — MCP Protocol Check

Starts a fresh stdio subprocess and displays negotiated protocol, tool definitions, instructions and configured aliases, without actively probing a database or issuing business queries:

```bash
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode auto
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode legacy
```

Startup still discovers enabled trusted Skills. For offline configuration only, use `config check/explain`; `scripts/check_prompt_contract.py` checks installed prompts. See the [client guide](docs/guides/TEST_MCP_CLIENT_GUIDE.md).

## Other Documentation

- [Configuration examples](config/examples/README.md): SQLite, MySQL, multiple connections and controlled mutations
- [v3.8 configuration and migration](docs/guides/CONFIGURATION_ZH.md): TOML, permissions, SDK imports and cutover
- [v3.8 implementation decisions](docs/architecture/V3_8_IMPLEMENTATION_ZH.md): package structure, state and reference-plan review
- [v3.8 security boundaries](docs/security/V3_8_SECURITY.md): trusted Python/Host, MRTR, audit and unknown outcomes
- [v3.8 release notes](docs/releases/RELEASE_NOTES_v3_8.md) and [validation](docs/validation/V3_8_VALIDATION_ZH.md)
- [Documentation index](docs/README.md): current contracts and historical material

- [Skills Design](docs/architecture/MCP_AGENTS_SKILLS_DESIGN.md): v3.0 Skills extension layer architecture and design decisions
- [Historical Skills Security Policy](docs/security/SAFETY.md): security governance for skill authors
- [Release Notes v3.5](docs/releases/RELEASE_NOTES_v3_5.md): named multi-connection release summary, compatibility notes, limits, and validation evidence
- [Release Notes v3.6/v3.6.1](docs/releases/RELEASE_NOTES_v3_6.md): mutation preview tokens, named-write policy, execution binding fixes, and the formalized same-process deployment boundary
- [Release Notes v3.7/v3.7.3](docs/releases/RELEASE_NOTES_v3_7.md): v3.7 capabilities, transaction outcomes, and connection-routing/tool-contract corrections from that release
- [v3.5-v3.7 Skills Guide (Chinese)](docs/guides/V3_5-V3_7_SKILLS_GUIDE_ZH.md): connection routing, write policy, preview tokens, Skill scope, and approval boundaries
- [Design Risk Register](docs/security/DESIGN_RISK_REGISTER.md): Long-term design, security, and operations risk register
- [Feasibility Analysis](docs/architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md): Detailed analysis of LLM to MCP conversion
- [Original Context](GEMINI.md): Project background and development guide
- [Refactoring Log](REFACTORING_LOG.md): Maintained refactoring decisions and validation (v2.0 — v3.8)
- [MCP Client Test Guide](docs/guides/TEST_MCP_CLIENT_GUIDE.md): Guide for testing MCP Server via client
- [MCP Agent Behavior Validation Method (Chinese)](docs/guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md): Method for validating natural tool selection, redundant calls, connection routing, and progressive disclosure
- [MCP Tool Contract and Evaluation Guide](docs/guides/PROMPT_ENGINEERING_BEST_PRACTICES.md): Project guidance for tool schemas, descriptions, instructions, safety boundaries, and evaluation
- [Agent Examples Development Log (Chinese)](examples/autogen/AGENT_DEVELOPMENT_ZH.md): AutoGen multi-agent example design and decisions

## Contribution

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make changes and conduct appropriate testing
4. Add tests for new features
5. Update documentation as needed
6. Submit a Pull Request

## Support

For technical issues, feature requests, or questions:
- Create an issue in the GitHub repository
- Include relevant error messages and configuration details
- Provide steps to reproduce the issue

---
