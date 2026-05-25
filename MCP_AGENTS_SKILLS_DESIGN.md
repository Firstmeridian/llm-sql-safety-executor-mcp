# MCP Agents Skills Design Document

> **Version**: 3.4
> **Status**: Implemented
> **Date**: 2026-05
> **Reference**: DRAFTPLAN_final.md, DRAFTPLAN_final_addendum.md

## 1. Overview

The Skills extension layer adds pre-defined, parameterized SQL operations
(queries and mutations) to the LLM Database Safety Gateway MCP server.
Skills are discoverable, auditable, and controlled by environment variables.

### Goals

- **Structured database operations** — Replace free-form SQL with reviewed templates
- **Progressive disclosure** — MCP-level catalog/detail/execute workflow for token efficiency
- **Write operation safety** — Plan-validate-execute pattern with dry-run default
- **Full backward compatibility** — Zero impact when disabled (`ENABLE_SKILLS=0`)
- **Minimal dependency footprint** — Only adds `pyyaml` to requirements

### Non-Goals

- Per-skill dynamic tool registration (avoided for tool count control)
- Built-in pipeline/DAG execution engine (Agent handles orchestration)
- Runtime SQL sandboxing (security via code review + template whitelist)

## 2. Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    mcp_sql_server.py                        │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ list_skills │  │ get_skill_detail │  │ execute_*     │  │
│  │  read-only  │  │    read-only     │  │ _skill tools  │  │
│  └──────┬──────┘  └────────┬─────────┘  └───────┬───────┘  │
│         │                  │                    │          │
│  ┌──────┴──────────────────┴────────────────────┴────────┐  │
│  │                   skills/_lib/                          │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │  │
│  │  │ skill_loader  │ │mutation_base │ │    audit       │  │  │
│  │  │  discover()   │ │ MutationBase │ │ AuditLogger    │  │  │
│  │  │  load_query() │ │ validate()   │ │ log()          │  │  │
│  │  │  load_mutation│ │ preview()    │ │ JSONL output   │  │  │
│  │  │  validate_*() │ │ execute()    │ │                │  │  │
│  │  └──────┬────────┘ └──────┬───────┘ └───────┬────────┘  │  │
│  └─────────┼─────────────────┼─────────────────┼───────────┘  │
│            │                 │                 │              │
│  ┌─────────┴─────────────────┴─────────────────┘              │
│  │              db_adapter.py                                 │
│  │  execute(sql, params=...)  ←  query skills (read-only)     │
│  │  execute_write(sql, params) ←  mutation skills (write)     │
│  └────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────┘
```

### Information Flow

```
Agent → list_skills(search/category/detail_level/available_only)
                               → Searchable skill catalog (compact/summary/full)
Agent → get_skill_detail(name) → Full cached parameter schema for one skill
Agent → execute_query_skill()  → skill_loader → adapter.execute(sql, params)
Agent → execute_mutation_skill(confirm=false)
                               → mutation.validate() + preview()
Agent → execute_mutation_skill(confirm=true)
                               → mutation.validate() + run_execute() → adapter.execute_write()
                                                                     → audit.log()
```

### Shared Infrastructure and Skill Structure

The following diagram shows the relationship between the shared
infrastructure under `skills/_lib/`, the concrete skill folders, and the
MCP tool entry points. The key idea is that `_lib` is not a skill by itself
— it is the common execution framework used by all skills.

```mermaid
flowchart TD
    A[skills directory] --> B[_lib shared infrastructure]
    A --> C[Concrete skill folders]

    B --> B1[__init__.py<br/>Package marker]
    B --> B2[skill_loader.py<br/>Discover load validate cache]
    B --> B3[mutation_base.py<br/>Base class for write skills]
    B --> B4[audit.py<br/>JSONL audit logging]

    C --> C1[monthly-sales-report<br/>skill_def.md + query.sql]
    C --> C2[monthly-sales-report-sqlite<br/>skill_def.md + query.sql]
    C --> C3[update-order-status<br/>skill_def.md + mutation.py]

    B2 --> D[mcp_sql_server.py startup discover]
    D --> E[In-memory skill cache]

    E --> F[get_skill_detail]
    E --> G[execute_query_skill]
    E --> H[execute_mutation_skill]

    G --> I[load_query]
    I --> J[Cached SQL template]
    J --> K[Read-only execution]

    H --> L[load_mutation]
    L --> M[Instantiate Mutation class]
    M --> N1[validate]
    N1 --> N2[preview]
    N2 --> O[execute]
    O --> P[run_execute wrapper]
    P --> Q[audit log write]
```

This diagram emphasizes two architectural boundaries:

- `_lib` contains reusable infrastructure, not business-specific skills.
- Concrete skills provide only metadata plus executable artifacts; the server
  handles loading, validation, execution, and audit centrally.

### Runtime Call Flow

The following diagram focuses on the actual runtime interactions after the
server has already completed startup discovery and cached all valid skills.

```mermaid
sequenceDiagram
    participant Server as mcp_sql_server.py
    participant Loader as skill_loader.py
    participant Cache as In-memory cache
    participant Skill as Skill files
    participant Base as mutation_base.py
    participant Audit as audit.py
    participant DB as DatabaseAdapter

    Note over Server,DB: Startup phase
    Server->>Loader: discover(skills_dir)
    Loader->>Skill: Read skill_def.md
    Loader->>Loader: Validate name source params databases
    alt Query skill
        Loader->>Skill: Read query.sql
        Loader->>Loader: is_sql_safe check
        Loader->>Cache: Cache SQL template and metadata
    else Mutation skill
        Loader->>Skill: Import Mutation class from mutation.py
        Loader->>Cache: Cache Mutation class and metadata
    end

    Note over Server,DB: Query skill execution
    Server->>Loader: load_query(skill_name)
    Loader->>Cache: Fetch cached SQL and schema
    Loader-->>Server: sql_template, param_schema
    Server->>Loader: validate_params(params, schema)
    Server->>DB: execute(sql_template, validated_params)
    DB-->>Server: Query result

    Note over Server,DB: Mutation preview flow
    Server->>Loader: load_mutation(skill_name, adapter, audit_logger)
    Loader->>Cache: Fetch cached Mutation class
    Loader-->>Server: Mutation instance
    Server->>Base: mutation.validate(params)
    Base->>DB: execute(read-only validation query)
    DB-->>Base: Current state
    Server->>Base: mutation.preview(params)
    Base->>DB: execute(read-only preview query)
    DB-->>Base: Preview context
    Server->>Audit: log(mode=preview)

    Note over Server,DB: Mutation execute flow
    Server->>Base: mutation.run_execute(params, skill_name)
    Base->>Base: Call execute(params)
    Base->>DB: execute_write(sql, params)
    DB-->>Base: rowcount or exception
    alt Success
        Base->>Audit: log(mode=execute, success)
        Base-->>Server: Result dict
    else Failure
        Base->>DB: _handle_error(e)
        Base->>Audit: log(mode=execute, error)
        Base-->>Server: ToolError(sanitized)
    end
```

This runtime view shows an important distinction from standard Agent Skills:

- Skill files are loaded eagerly at startup, not lazily at first use.
- Runtime tool calls operate on cached SQL templates and cached Mutation
  classes.
- Progressive disclosure exists at the MCP interaction layer
  (`list_skills()` → `get_skill_detail()` → `execute_*_skill()`), not as
  runtime filesystem reads by the Agent.

### Skill Lifecycle

The following diagram illustrates the complete lifecycle of a skill, from
authoring to runtime execution. The key architectural decision is the
**separation of startup-time validation from runtime execution** — all
security checks happen before the server accepts any requests.

```mermaid
flowchart LR
    subgraph Author["Phase 1: Authoring"]
        D1["skill_def.md\nYAML metadata\n+ documentation"]
        D2["query.sql\nSQL template"]
        D3["mutation.py\nPython logic"]
    end

    subgraph Startup["Phase 2: Server Startup — discover()"]
        S1["Scan skills/ directory"]
        S2["Parse YAML frontmatter"]
        S3["Validate SQL safety\nis_sql_safe()"]
        S4["Import Mutation class\nimportlib.util"]
        S5["Cache to _skills_cache"]
        S6["Generate SKILLS.md"]
    end

    subgraph Runtime["Phase 3: Runtime — Agent Interaction"]
        R1["list_skills()\nsearchable metadata catalog"]
        R2["get_skill_detail()\nfull cached params schema"]
        R3["execute_query_skill()\ncached SQL + params"]
        R4["execute_mutation_skill()\ncached class + params"]
    end

    D1 --> S1
    D2 --> S1
    D3 --> S1
    S1 --> S2 --> S3 & S4
    S3 --> S5
    S4 --> S5
    S5 --> S6
    S5 -.->|"in-memory cache"| R1 & R2 & R3 & R4
```

> **Design reference**: The eager startup validation follows the "fail-fast"
> principle — if a skill has unsafe SQL or a malformed source module, the server
> refuses to register it at startup, not at the first runtime invocation. This
> eliminates an entire class of runtime errors and is consistent with
> [MCP Specification §7 — Security](https://modelcontextprotocol.io/specification/2025-03-26/basic/security):
> *"Validate all inputs"* and *"Implement proper access controls."*

### Query Skill Execution Flow

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as MCP Server
    participant Loader as skill_loader
    participant Adapter as db_adapter
    participant DB as Database

    Agent->>MCP: execute_query_skill(name, params)
    MCP->>Loader: validate_name(name)
    Loader-->>MCP: ✓ name valid
    MCP->>Loader: load_query(name)
    Loader-->>MCP: cached {sql_template, metadata}
    MCP->>Loader: validate_params(params, metadata)
    Loader-->>MCP: ✓ params coerced & validated
    MCP->>Adapter: execute(sql_template, params=params)
    Adapter->>DB: Parameterized query (SQLAlchemy text())
    DB-->>Adapter: result rows
    Adapter-->>MCP: formatted result
    MCP-->>Agent: {success, data, row_count}
```

> **Design reference**: Parameters are bound via SQLAlchemy `text()` +
> parameter dict, never via string concatenation. This follows the
> industry-standard parameterized query pattern recommended by
> [OWASP — SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html).

### Mutation Skill Two-Phase Execution Flow

The two-phase execution pattern implements Anthropic's
["verifiable intermediate outputs"](https://docs.anthropic.com/en/docs/build-with-claude/agentic-systems#practices-for-effective-agentic-systems)
principle — the agent (and user) can review planned changes before committing.

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as MCP Server
    participant Loader as skill_loader
    participant Mutation as MutationBase
    participant Adapter as db_adapter
    participant Audit as AuditLogger
    participant DB as Database

    Note over Agent,DB: Phase 1: Preview (confirm=false)
    Agent->>MCP: execute_mutation_skill(name, params, confirm=false)
    MCP->>Loader: validate_name(name) + validate_params(params)
    MCP->>Loader: load_mutation(name, adapter, audit_logger)
    Loader-->>MCP: Mutation instance (from cached class)
    MCP->>Mutation: validate(params)
    Mutation->>Adapter: execute(SELECT ... WHERE id=:id)
    Adapter->>DB: query current state
    DB-->>Adapter: current record
    Adapter-->>Mutation: current data
    Mutation-->>MCP: validation result (state check passed)
    MCP->>Mutation: preview(params)
    Mutation-->>MCP: {preview_sql, current_status, new_status}
    MCP-->>Agent: {preview, requires_confirmation: true}

    Note over Agent,DB: Phase 2: Execute (confirm=true)
    Agent->>MCP: execute_mutation_skill(name, params, confirm=true)
    MCP->>Loader: validate_name + validate_params (re-validate)
    MCP->>Loader: load_mutation(name, adapter, audit_logger)
    MCP->>Mutation: run_execute(params)
    Mutation->>Mutation: validate(params) — re-verify (TOCTOU defense)
    Mutation->>Adapter: execute_write(UPDATE ... WHERE status=:expected)
    Adapter->>DB: BEGIN → UPDATE → COMMIT
    DB-->>Adapter: rowcount
    Adapter-->>Mutation: {success: true, rowcount: N}
    Mutation->>Audit: log(skill, params, result, agent_id)
    Mutation-->>MCP: {success, rowcount, message}
    MCP-->>Agent: execution result

    Note over Agent,DB: Error path
    Adapter--xMutation: SQLAlchemyError
    Mutation->>Adapter: _handle_error(e) → sanitized message
    Mutation--xMCP: raise ToolError(sanitized)
    MCP--xAgent: error (no sensitive details leaked)
```

> **Design references**:
> - *"Give models less freedom for higher-stakes operations."* — Anthropic,
>   ["Building effective agents" (2024)](https://docs.anthropic.com/en/docs/build-with-claude/agentic-systems#practices-for-effective-agentic-systems).
>   Mutation operations use constrained code paths, not free-form agent code.
> - *"Verifiable intermediate outputs"* — ibid.
>   The preview phase allows the agent (and user) to verify planned changes.
> - The `validate()` call in Phase 2 is **intentionally duplicated** to defend
>   against TOCTOU: the data state may have changed between preview and confirm.

## 3. Directory Structure

```
skills/
├── SAFETY.md                          # Security governance (16 items)
├── SKILLS.md                          # Auto-generated overview (by discover())
├── _lib/                              # Shared infrastructure
│   ├── __init__.py
│   ├── skill_loader.py                # Discovery, loading, validation
│   ├── mutation_base.py               # ABC for write operations
│   └── audit.py                       # JSONL audit logger
├── monthly-sales-report/              # Example MySQL query skill
│   ├── skill_def.md                   # YAML frontmatter + documentation
│   └── query.sql                      # Parameterized SQL template
├── monthly-sales-report-sqlite/       # Example SQLite query skill
│   ├── skill_def.md                   # YAML frontmatter + documentation
│   └── query.sql                      # Parameterized SQL template
└── update-order-status/               # Example mutation skill
    ├── skill_def.md                   # YAML frontmatter + documentation
    ├── mutation.py                    # validate/preview/execute logic
    └── references/
        └── status-transitions.md      # State machine documentation
```

## 4. skill_def.md Format

Each skill is defined by a `skill_def.md` file with YAML frontmatter:

```yaml
---
name: skill-name              # ^[a-z0-9][a-z0-9-]*$ (max 64 chars)
version: "1.0"                # Optional, for audit/versioning
description: >                # What the skill does
  Human-readable description.
triggers:                     # Optional, keyword hints for agent matching
  - keyword1
  - keyword2
type: query                   # query | mutation
source: query.sql             # Required: execution file (validated filename)
risk: low                     # low | medium | high
databases: [mysql, sqlite]    # Optional: supported DB types (default: all)
enabled: true                 # Optional, default true
idempotent: false             # Optional, default false
requires_confirmation: true   # Optional, for mutations
params:
  param_name:
    type: int                 # int | float | str | bool
    required: true
    min: 1                    # Optional range constraint
    max: 100
    enum: [a, b, c]           # Optional enum constraint
    description: "..."        # Optional
category: reporting           # Optional
related_skills:               # Optional, discovery hints
  - other-skill-name
---

Markdown body with usage instructions (< 500 lines recommended).
```

### Design Rationale

The `skill_def.md` format is designed around four principles:

**1. Self-contained definition** — Each skill carries its own metadata,
parameter schema, and documentation in a single file. This follows Google's
["use clear and descriptive function/parameter names and descriptions"](https://ai.google.dev/gemini-api/docs/function-calling#best_practices)
principle for function calling: define parameters with precise types,
constraints, and descriptions to reduce ambiguity and hallucination.

**2. Declarative parameter validation** — Parameter constraints (`type`,
`min`, `max`, `enum`) are declared in YAML rather than implemented in code.
The server's `validate_params()` enforces these constraints uniformly for
all skills. This follows
[MCP Specification §7](https://modelcontextprotocol.io/specification/2025-03-26/basic/security):
*"Validate all inputs"* — validation is defined once in the schema and
enforced automatically by the infrastructure, not by each individual skill.

**3. Information layering** — `skill_def.md` serves two audiences:

| Audience | Reads | Purpose |
|----------|-------|---------|
| **Server** (`skill_loader.py`) | YAML frontmatter | Registration, validation, parameter schema |
| **Developers** | Markdown body | Context, workflow, maintenance notes |
| **Agent** | Neither directly | Receives structured metadata via `list_skills()` and `get_skill_detail()` |

This separation means the Agent never sees the markdown body or the raw SQL
template — it only receives structured metadata via `list_skills()` and
`get_skill_detail()`.
In contrast, standard Agent Skills expect the Agent to read the full SKILL.md
content as executable instructions.

**4. Anthropic-compatible naming** — The choice of YAML frontmatter and the
`name` field regex (`^[a-z0-9][a-z0-9-]*$`) deliberately align with the
[Anthropic Agent Skills spec](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).
Developers familiar with the standard format will find `skill_def.md`
immediately readable, even though the execution model is fundamentally
different (see Section 11).

**5. Explicit source declaration** — The `source` field is **mandatory** and
explicitly declares the execution file associated with the skill (e.g.
`source: query.sql`, `source: mutation.py`). This follows the
**Explicit Configuration** principle used by industry-standard tools:

| Tool | Manifest | Field | Purpose |
|------|----------|-------|---------|
| GitHub Actions | `action.yml` | `main` | Entry point JS file |
| npm | `package.json` | `main` | Package entry point |
| Python | `pyproject.toml` | `[project.scripts]` | Console entry points |
| Google Gemini | Function declarations | `name`, `parameters` | Explicit schema |
| MCP Specification | Tool registration | `inputSchema` | Explicit schema |

The `source` filename is validated by `_validate_source_filename()` for:
- **Path traversal prevention**: no `/` or `\`, no leading `.`
- **Suffix enforcement**: `query` → `.sql`, `mutation` → `.py`
- **Safe character set**: `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`
- **Length limit**: max 128 characters

This replaces the previous convention-based approach (hardcoded `query.sql`
and `mutation.py`) with explicit declaration, enabling custom filenames
like `daily-revenue.sql` while maintaining security through validation.

```mermaid
flowchart TB
    subgraph SD["skill_def.md"]
        direction TB
        Y["YAML Frontmatter\n─────────────────\nname, type, risk\nparams (type/min/max/enum)\ntriggers, related_skills"]
        M["Markdown Body\n─────────────────\nUsage instructions\nWorkflow notes\nCaveats"]
    end

    subgraph Consumers["Consumers"]
        SL["skill_loader.py\n(Server startup)"]
        DEV["Developer\n(Code review)"]
        AG["Agent\n(Runtime)"]
    end

    Y -->|"parsed by discover()"| SL
    Y -.->|"also readable by"| DEV
    M -->|"read by"| DEV
    M -.->|"NOT sent to"| AG
    SL -->|"list_skills() metadata"| AG

    style SD fill:#f9f9f9,stroke:#999
    style Y fill:#ffe,stroke:#aa3
    style M fill:#eef,stroke:#33c
```

## 5. Security Model

See [skills/SAFETY.md](skills/SAFETY.md) for the full 16-item security policy.

### Security Model Overview

The following diagram shows the four security layers that every request passes through, from the untrusted Agent to the database:

```mermaid
flowchart TB
    subgraph Agent["Agent Side (Untrusted)"]
        A1["LLM Agent<br/>(Claude / GPT / etc.)"]
    end

    subgraph MCP["MCP Protocol Boundary"]
        direction TB
        T1["query(sql)"]
        T2["execute_query_skill(name, params)"]
        T3["execute_mutation_skill(name, params, confirm)"]
        T4["list_skills() / describe_table() / ..."]
    end

    subgraph Server["MCP Server Security Layer (Trusted)"]
        direction TB

        subgraph S1["Layer 1: Input Validation"]
            V1["is_sql_safe()<br/>Allow only SELECT/SHOW/DESCRIBE/EXPLAIN"]
            V2["_is_query_safe_extended()<br/>Block system tables/UNION/subqueries"]
            V3["_check_table_allowlist()<br/>Table-level access control"]
            V4["validate_name()<br/>^a-z0-9- prevent path traversal"]
            V5["validate_params()<br/>Type/range/enum constraints"]
        end

        subgraph S2["Layer 2: Execution Control"]
            E1["query.sql template<br/>Startup is_sql_safe() pre-validation"]
            E2["Parameterized binding<br/>SQLAlchemy text() + params"]
            E3["mutation: validate()<br/>Business rule validation"]
            E4["mutation: preview()<br/>Dry-run preview"]
            E5["mutation: execute()<br/>Execute in transaction"]
        end

        subgraph S3["Layer 3: Runtime Protection"]
            R1["QUERY_TIMEOUT<br/>Timeout interrupt"]
            R2["MAX_RESULT_ROWS/CHARS<br/>Result truncation"]
            R3["_handle_error()<br/>Error message sanitization"]
            R4["SKILLS_DIR path constraint<br/>Must be within project root"]
        end

        subgraph S4["Layer 4: Audit & Visibility"]
            AU1["AuditLogger<br/>JSONL audit log"]
            AU2["SKILLS.md<br/>Auto-generated overview"]
            AU3["ctx.info() / ctx.warning()<br/>MCP progress notifications"]
        end
    end

    subgraph DB["Database"]
        DB1["MySQL / SQLite"]
    end

    A1 -->|"MCP tool call"| T1 & T2 & T3 & T4

    T1 -->|"Raw SQL"| V1 --> V2 --> V3 --> E2 --> R1 --> R2
    T2 -->|"skill_name + params"| V4 --> V5 --> E2 --> R1 --> R2
    E1 -.->|"Startup pre-validation<br/>Ensures template safety"| E2
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

### Key Principles

| # | Principle | Implementation |
|---|-----------|----------------|
| 1 | Template as whitelist | Only pre-defined SQL/Python executed |
| 2 | Parameterized queries | SQLAlchemy `text()` + params binding |
| 3 | Dry-run default | `confirm=False` returns preview only |
| 4 | Dual-layer switches | `ENABLE_SKILLS` + `SKILLS_ALLOW_MUTATIONS` |

**Three-Level Permission Progression:**

| Level | Configuration | `ENABLE_SKILLS` | `SKILLS_ALLOW_MUTATIONS` | Available Tools | Permission |
|:---:|------|:---:|:---:|------|------|
| L0 | Default | `0` | — | Base tools (query, list_tables, etc.) | Read-only queries |
| L1 | Skills enabled | `1` | `0` | + list_skills, get_skill_detail, execute_query_skill | + Pre-defined read-only skills |
| L2 | Mutations enabled | `1` | `1` | + execute_mutation_skill | + Controlled writes (two-phase confirm) |

| 7 | Trust boundary | skills/ = source code, changes via code review |
| 12 | Error sanitization | `_handle_error()` → `ToolError` (no leaks) |
| 14 | ALLOWED_TABLES bypass | Skill SQL pre-audited, review-based trust |
| 15 | Path constraint | SKILLS_DIR must be within project root |

### Error Handling Chain

```
adapter.execute_write() failure
  → SQLAlchemyError propagates
    → MutationBase.run_execute() catches
      → adapter._handle_error(e) sanitizes
        → raise ToolError(sanitized)
          → FastMCP passes through to Client (no double-masking)
```

## 6. MCP Tool Registration

### Conditional Registration Pattern

```python
if SKILLS_ENABLED:
    # resolve + validate SKILLS_DIR
    # import skills infrastructure
    # discover() at module load time
    # register: list_skills(), get_skill_detail(), execute_query_skill()
    
    if SKILLS_ALLOW_MUTATIONS:
        # register: execute_mutation_skill()
```

### Tool Annotations

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|------|-------------|-----------------|----------------|---------------|
| `list_skills` | true | false | true | false |
| `get_skill_detail` | true | false | true | false |
| `execute_query_skill` | true | false | true | false |
| `execute_mutation_skill` | false | true | false | false |

`idempotentHint=false` for mutations is a conservative default. Per-skill
idempotency info is conveyed via `list_skills()` and execution result dicts.
`openWorldHint=false` is used consistently because these tools operate inside
the configured database/server boundary rather than interacting with arbitrary
external entities. This is an advisory MCP client hint; authorization still
comes from environment switches, table allowlists, schema readiness checks, and
execution-time validation.

### Runtime Tool Metadata

All 11 MCP tools return `ToolResult` (uniform since v3.4.2) so FastMCP clients
receive per-invocation `meta` alongside the existing structured payload. The
payload remains the same JSON object that clients read from
`structuredContent` / `.data`; metadata is reserved for diagnostics and
observability.

Runtime metadata always includes `tool_name`, `db_type`, `execution_ms`, and
`success`. For base tools, `success` is passed directly by each tool's result
wrapper. For Skills execution tools, `success` is derived from the stable
`structuredContent["success"]` payload so business-level validation failures
(for example a mutation preview rejected by the state machine) are visible to
telemetry even when the tool returns normally rather than raising `ToolError`.
Data-returning tools add `row_count`, `total_rows`, `truncated`. Skills
execution tools additionally expose `skill_name`, `skill_type`, `skill_version`,
current `mode` (`query`, `preview`, or `execute`), and `idempotent`. Metadata
intentionally does **not** include raw SQL templates, returned data rows, or
parameter values. Query-parameter logging remains governed only by the explicit
`SKILLS_AUDIT_QUERIES` audit switch.

Operational telemetry (`ENABLE_TOOL_TELEMETRY=1`) writes a separate JSONL record
per `tools/call` with sanitized fields only: `timestamp`, `tool_name`,
`execution_ms`, `call_completed`, `success`, `error_class`, and `db_type`.
`call_completed` records transport/control-flow completion, while `success`
records the tool's own business outcome. This split avoids the common ambiguity
where a safety or validation rejection returns a normal MCP response but should
still count as an unsuccessful business operation. Sampling is intentionally
simple (`TOOL_TELEMETRY_SAMPLE_RATE`, finite float clamped to 0.0-1.0) and does
not provide p50/p95 aggregation inside the MCP server; richer analytics should
run outside the server over the JSONL stream to avoid extra state and sensitive
usage-pattern disclosure.

### Tool Count Impact

| Configuration | Tool Count |
|--------------|------------|
| ENABLE_SKILLS=0 | 5-7 (unchanged) |
| ENABLE_SKILLS=1, MUTATIONS=0 | 8-10 |
| ENABLE_SKILLS=1, MUTATIONS=1 | 9-11 |

The full Skills profile remains within Google Gemini's recommended 10-20 tools range. The base read-only profile intentionally stays below that range to keep simple deployments compact.

## 7. Database Adapter Extensions

### execute() — Optional params (Step 3a)

```python
def execute(self, sql, timeout=None, params=None) -> list | str:
    if params:
        result = connection.execute(text(sql), params)
    else:
        result = connection.execute(text(sql))
```

Fully backward compatible — `params` defaults to `None`.

### execute_write() — New method (Step 3b)

```python
def execute_write(self, sql, params, timeout=None) -> dict:
    with self._engine.begin() as connection:
        result = connection.execute(text(sql), params)
    return {"success": True, "rowcount": result.rowcount}
```

- Uses `engine.begin()` for explicit transaction (auto-commit on success, auto-rollback on exception)
- Avoids `engine.connect()` + `connection.begin()` pattern which conflicts with SQLAlchemy 2.0 autobegin
- Returns dict (not str on error — exceptions propagate)
- Read/write separation by convention (SAFETY.md #16)

## 8. Progressive Disclosure

MCP-level metadata disclosure is separated from executable artifact loading.
The Agent sees only the amount of skill metadata needed for the current step;
the server still validates and caches SQL templates and mutation classes at
startup.

| Level | Source | Content | Runtime disk I/O |
|-------|--------|---------|------------------|
| Catalog | `list_skills(detail_level="compact")` | name, type, description, risk, category, executability, schema readiness | No |
| Summary | `list_skills()` or `detail_level="summary"` | compact fields plus triggers, databases, profiles, source filename, idempotency, related skills | No |
| Detail | `get_skill_detail(name)` or `list_skills(detail_level="full")` | full cached frontmatter metadata plus params schema, version, requires_confirmation, tables | No |
| Source review | Developer reads files in `skills/` | raw SQL/Python source for code review | Outside MCP runtime |

`list_skills()` also supports deterministic substring search and exact category
filtering. Skills without a category are grouped under `uncategorized`. Regex
search is intentionally not supported in the first implementation to avoid ReDoS
risks and brittle model-generated regular expressions.

`available_only` filters the catalog to skills that can execute in the current
server state. By default it follows `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1`, so
Agent-facing discovery hides database-incompatible skills, mutation skills when
`SKILLS_ALLOW_MUTATIONS=0`, and schema-unready skills when
`SKILLS_CHECK_SCHEMA_ON_LIST=1`. Developers can pass `available_only=false` to
inspect the full discovered catalog. This filter is a discovery optimization,
not an authorization boundary; execution-time checks remain mandatory.

Schema readiness is intentionally table-level in this implementation. Query
skills derive `tables` from the reviewed SQL template, and mutation skills can
declare `tables` in frontmatter. The server checks whether those tables exist in
the current database and exposes `schema_ready` plus `missing_tables`. It does
not validate every column shape during discovery, because that would increase
metadata complexity and risk false negatives for reviewed templates.

Bundled example skills use `profiles: [demo]` because they target the demo
`orders` schema. Profiles remain descriptive metadata by default, but deployments
can set `SKILLS_EXCLUDE_PROFILES=demo` to mark matching skills non-executable,
hide them from default Agent discovery, and reject direct execution attempts.
This keeps examples in the repository while giving production deployments a
clear policy switch.

## 9. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SKILLS` | `0` | Master switch for skills extension |
| `SKILLS_ALLOW_MUTATIONS` | `0` | Enable mutation skills (second switch) |
| `SKILLS_LIST_DEFAULT_DETAIL` | `summary` | Default `list_skills()` metadata projection: `compact`, `summary`, or `full` |
| `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` | `1` | Default `list_skills()` availability filter; `1` hides currently non-executable skills from Agent discovery, while `available_only=false` exposes the full developer catalog |
| `SKILLS_CHECK_SCHEMA_ON_LIST` | `1` | Include live table-existence checks in Skills readiness metadata; missing tables set `schema_ready=false` and are hidden by `available_only=true` |
| `SKILLS_EXCLUDE_PROFILES` | empty | Comma-separated profile policy; matching skills are non-executable, hidden by default discovery, and rejected at execution time |
| `SKILLS_DIR` | `skills/` | Skills directory path |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | Audit log file path |
| `SKILLS_AUDIT_QUERIES` | `0` | Optional query skill audit; records metadata and row counts, never returned data |
| `MAX_SQL_LENGTH` | `20000` | Maximum raw `query(sql)` input length exposed in the MCP schema and enforced before execution; `0` disables the length cap |
| `MCP_TOOL_TIMEOUT_SECONDS` | `120` | FastMCP foreground tool timeout for registered tools; `0` disables the FastMCP timeout |
| `ENABLE_TOOL_TELEMETRY` | `0` | Enable sanitized per-tool-call JSONL telemetry middleware |
| `TOOL_TELEMETRY_LOG_PATH` | `logs/tool_calls.jsonl` | Local JSONL destination for telemetry records |
| `TOOL_TELEMETRY_SAMPLE_RATE` | `1.0` | Telemetry write sampling probability (finite float clamped to 0.0-1.0; invalid values fall back to 1.0) |

## 10. Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Architecture | Unified registration (2-3 tools) | Per-skill tools / FastMCP mount() | Prevents tool explosion; Google Gemini 10-20 rule |
| On-demand metadata disclosure | `list_skills()` projections + `get_skill_detail()` | Runtime source-file lazy loading | Reduces Agent-facing metadata while preserving startup validation and TOCTOU protection |
| Skill search | Case-insensitive substring + exact category filter | Regex/BM25 search | Deterministic, dependency-free, and avoids ReDoS from model-generated regex |
| Availability filtering | `available_only` filters by current `DB_TYPE`, mutation switch, and schema readiness | Always return full discovered catalog | Aligns with conditional tool enabling and reduces Agent selection errors; developers retain full catalog access with `available_only=false` |
| Schema readiness scope | Table existence only | Full column/type compatibility check | Catches the common wrong-schema case with low overhead; reviewed SQL/mutation code still provides the precise execution-time validation |
| Demo skills | `profiles: [demo]` plus optional `SKILLS_EXCLUDE_PROFILES=demo` | Delete or disable bundled examples by default | Keeps examples usable for local demos while allowing production deployments to hide and block them explicitly |
| Query skill audit | Optional `SKILLS_AUDIT_QUERIES=1` | Audit every read skill by default | Avoids surprising sensitive parameter logs while providing an opt-in compliance trail; returned data is never logged |
| Raw SQL length | `MAX_SQL_LENGTH` for `query(sql)` | Apply the same cap to reviewed skill templates | Free-form SQL is agent-provided input and needs schema/runtime bounds; reviewed skill SQL is startup-validated code and should not be constrained by the user-input cap |
| Tool timeout | FastMCP `timeout=MCP_TOOL_TIMEOUT_SECONDS` | Rely only on DB query timeout | Protects the MCP foreground request from non-DB stalls while keeping the DB timeout as the lower-level query guard |
| v3.4.1.B1 ToolResult metadata | Implemented for Skills execution tools | Keep plain dict returns everywhere | Adds runtime diagnostics (`execution_ms`, row counts, truncation, skill version) without changing the structured payload; metadata excludes SQL, params, and returned rows |
| v3.4.1.B2 Closed-world annotations | `openWorldHint=false` on all MCP tools | Leave FastMCP default `openWorldHint=true` | The server operates inside a configured database boundary, so closed-world hints better represent client-facing safety semantics; hints remain advisory, not authorization |
| v3.4.1.B3 Direct-call API asymmetry | Skills execution tools return `ToolResult`; all other tools still return `dict` | Refactor every tool to return `ToolResult` for uniform return shape | Limits the v3.4.1 change surface to where rich runtime diagnostics matter; Python callers must read `result.structured_content` / `result.meta` on the two skill tools while continuing to use plain `dict` on the rest. Tracked as a follow-up for v3.4.2 if uniform return shape becomes valuable. Per MCP spec the `_meta` field is OPTIONAL and clients MAY ignore it (e.g. VS Code's MCP UI does not currently surface it), so `ToolResult.meta` is primarily a server-side observability hook |
| v3.4.2.A1 Uniform ToolResult | All registered tools in the full profile converted to `ToolResult` | Keep mixed return shape from v3.4.1 | Removes the B3 asymmetry; every tool now carries `tool_name`/`execution_ms`/`db_type`/`success` plus tool-specific counters (`row_count`, `total_rows`, `truncated`) in `meta`; `structuredContent` is byte-identical to v3.4.1 so MCP clients see no behavior change |
| v3.4.2.A2 Skill outputSchema | Declared on `execute_query_skill` and `execute_mutation_skill` | No schema (clients infer shape) | MCP `outputSchema` lets compliant clients validate `structuredContent`; the schemas use `additionalProperties: true` to tolerate preview/execute payload variation in mutations |
| v3.4.2.A3 Tool telemetry | Opt-in middleware (`ENABLE_TOOL_TELEMETRY=1`) writes sanitized JSONL to `TOOL_TELEMETRY_LOG_PATH`, with optional `TOOL_TELEMETRY_SAMPLE_RATE` | Always-on telemetry, in-process p95 aggregation, or external sink | Default behavior unchanged; the middleware records only `timestamp`/`tool_name`/`execution_ms`/`call_completed`/`success`/`error_class`/`db_type`, never SQL/params/rows/credentials. `success` follows `ToolResult.meta.success`; `call_completed` captures exception-free return. Sampling is deliberately simple and finite-clamped. Percentile aggregation remains external to avoid server state, extra dependencies, and usage-pattern disclosure through a stats tool |
| v3.4.2.A4 Annotation drift lint | `tests/test_annotations_consistency.py` | Fail-fast at server startup | Pytest captures drift in CI without making the server brittle to in-progress local edits; aligned with the test-driven safety convention already used by the project |
| v3.4.B4 Schema state cache | Deferred decision | Cache schema table names in FastMCP session state | Reduces repeated metadata calls but risks stale readiness after DDL; current table checks are simple and execution guards remain authoritative |
| v3.4.C1 Schema resource | Deferred decision | Add `db://schema` MCP resource now | Existing `get_full_schema` tool is explicit and already supported by clients; resource support varies and would add a second schema access path |
| Metadata | skill_def.md YAML frontmatter | JSON manifest | Anthropic Agent Skills spec alignment |
| Params validation | Inline in frontmatter | JSON Schema file | Single-file self-description |
| Write safety | 3-stage (validate/preview/execute) | Simple confirm flag | Anthropic "verifiable intermediate outputs" |
| Audit storage | JSONL file | Database table | Minimal dependency for MVP |
| Source declaration | Mandatory `source` field | Convention-based (hardcoded filenames) | Explicit Configuration principle: GitHub Actions, npm, Python all use explicit entry points; enables custom filenames while `_validate_source_filename()` enforces path safety and suffix matching |
| Write interface | Separate `execute_write()` | Reuse `execute()` | Read/write separation, clear responsibilities |
| SQL caching | discover() caches at startup | Runtime disk reads | Eliminates TOCTOU risk |
| Mutation caching | discover() pre-loads mutation classes | Per-call `exec_module()` | Eliminates runtime disk I/O + module compilation |
| Error handling | Exceptions propagate + ToolError | Error dict returns | FastMCP ToolError bypasses mask_error_details |
| ALLOWED_TABLES | Skills bypass at runtime | Runtime table check | Template = whitelist (code review trust) |
| SQLAlchemy version | `>=2.0` explicit | No constraint | 2.0 implicit transactions prevent accidental writes |
| Example skill SQL | Separate MySQL and SQLite examples | One cross-DB SQL template with runtime branching | Keeps templates clear, keeps startup validation deterministic, and lets availability filtering hide incompatible dialects before execution planning |
| Table name extraction | `_extract_table_names()` ignores `schema.table` | Full `schema.table` regex | Function only used for `SKILLS.md` generation (non-security); core path `_extract_tables_from_sql()` handles `schema.table` correctly |
| Mutation duplicate SELECT | `execute()` re-runs `validate()` SELECT | Single SELECT in `validate()` only | Intentional TOCTOU prevention — user review gap between preview and confirm requires re-verification of data state |
| Mutation error contract | `execute()` raises `ToolError` on failure | Return `{"success": False}` dict | Exceptions follow `run_execute()` error handling chain; return-dict failures bypass audit logging and cause semantic contradiction in MCP tool response |
| Mutation read-write gap | Separate `execute()` + `execute_write()` calls | Single SQL merging SELECT+UPDATE | Optimistic locking `WHERE status = :expected` + `rowcount == 0` is the effective safety net; merging adds complexity with minimal gain |
| `_coerce_type()` bool | `bool(value)` (Python built-in) | Explicit `"true"/"false"` mapping | No bool params in current skills; acceptable for MVP, should be revisited when bool params are added |
| Annotation evaluation | `from __future__ import annotations` (PEP 563) in `skill_loader.py` | Runtime annotation evaluation (default) | Python 3.12 `type` soft keyword conflicts with `SkillMetadata.type` field annotation; PEP 563 deferred evaluation resolves Pylance parsing ambiguity |
| Database compatibility | Optional `databases` field | No DB type declaration | Follows npm `engines`, Python `requires-python`, Terraform `required_providers` pattern; runtime `DB_TYPE` check prevents incompatible skill execution; `None` = all databases (zero overhead for cross-DB skills) |

## 11. Relationship to Standard Agent Skills (Anthropic Agent Skills)

This section documents **why this project does not adopt the standard
[Anthropic Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
format**, and what elements were selectively borrowed. For user-facing

### 11.1 Architectural Divergence

Standard Agent Skills assume the agent operates inside a **VM / sandbox with
filesystem access and code execution capabilities**. The agent reads `SKILL.md`
via `bash`, writes its own code, and executes it locally. This enables the
three-level progressive disclosure model:

| Level | Standard Agent Skills | This Project |
|-------|----------------------|--------------|
| **L1: Metadata** | YAML frontmatter loaded into system prompt at startup (~100 tokens/skill) | `list_skills()` returns projected metadata from in-memory cache |
| **L2: Instructions** | Agent reads SKILL.md body via `bash: cat SKILL.md` when triggered | N/A — skill_def.md body is for human developers, not consumed by agent at runtime |
| **L3: Resources** | Agent reads bundled files (scripts, references) on demand via bash | `get_skill_detail()` returns cached params/schema metadata; SQL templates and mutation classes are **pre-loaded at startup** into `_skills_cache`, never read from disk at runtime |

In MCP architecture, the agent communicates with the server via JSON-RPC
over stdio/SSE ([MCP Spec — Transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)).
The agent **cannot access the server's filesystem** — `bash: cat skill_def.md` is
not possible. Standard Skills' filesystem-based progressive disclosure is
therefore architecturally incompatible with MCP.

This project implements **MCP-level progressive disclosure** instead:
`list_skills()` (catalog) → `get_skill_detail()` (one skill's cached schema)
→ `execute_*_skill()` (execution). From the agent's perspective, this achieves
the same staged interaction pattern without requiring filesystem access.

#### Visual Comparison: Loading Flow

```mermaid
flowchart LR
  subgraph A[This Project's Skills Extension Layer]
    A1[Server startup] --> A2[Read ENABLE_SKILLS and SKILLS_DIR]
    A2 --> A3[discover scans skills directory]
    A3 --> A4[Parse skill_def.md]
    A4 --> A5{Skill type}
    A5 -->|query| A6[Read and validate source SQL file]
    A5 -->|mutation| A7[Import and cache Mutation class]
    A6 --> A8[Write to in-memory cache]
    A7 --> A8
    A8 --> A9[Register MCP tools list_skills get_skill_detail execute_query_skill execute_mutation_skill]
    A9 --> A10[At runtime the Agent calls tools on demand]
    A10 --> A11[Server executes from cached template or class]
  end

  subgraph B[Standard Agent Skills]
    B1[Agent startup] --> B2[Load skill metadata name and description]
    B2 --> B3[User request arrives]
    B3 --> B4{Does a skill match}
    B4 -->|yes| B5[Read SKILL.md body]
    B5 --> B6{Need more resources}
    B6 -->|yes| B7[Read extra docs or run bundled scripts]
    B6 -->|no| B8[Complete task using loaded instructions]
    B7 --> B8
    B4 -->|no| B9[Do not load that skill body]
  end

  A11 -. key distinction .-> C1[Eager startup discovery and caching]
  B5 -. key distinction .-> C2[Lazy load of instructions when triggered]
  C1 --- C2
```

### 11.2 Trust Model and Threat Boundary

Standard Agent Skills operate under a **"sandbox isolation + trust the agent"**
security model:

```
User request → Agent reads SKILL.md → Agent writes code → Agent executes in VM
```

The agent is **both decision-maker and executor**. Safety relies on VM sandbox
restrictions (limited network/filesystem) and the assumption that the agent
will faithfully follow instructions. This is appropriate for document
processing tasks (PDF/Excel) where the worst case is generating an incorrect
file inside a sandbox.

This project operates under a fundamentally different threat model — **"do not
trust the agent; server enforces all constraints"**:

```
User request → Agent calls MCP tool → MCP Server executes pre-built SQL → Production database
```

Attack surfaces specific to this architecture:

| Threat | Description | Mitigation |
|--------|-------------|------------|
| **Prompt injection** | Malicious user input induces agent to pass dangerous parameters | `validate_params()` enforces type/min/max/enum constraints at server side |
| **Agent hallucination** | Agent invents non-existent skills or passes out-of-range parameters | `validate_name()` + cache lookup + schema-level rejection of unexpected params |
| **TOCTOU** | If SQL were read from disk at runtime, file tampering = arbitrary SQL injection | `discover()` pre-loads and caches at startup; zero disk I/O at runtime (see [CWE-367](https://cwe.mitre.org/data/definitions/367.html)) |
| **SQL injection via params** | Agent-supplied parameters could be concatenated unsafely | SQLAlchemy `text()` + parameterized binding; no string concatenation |

Adopting the standard Agent Skills model would mean letting the agent read SQL
templates, assemble parameters, and decide when to execute — **every security
checkpoint listed above would be bypassed**.

### 11.3 "Teaching the Agent" vs "Acting for the Agent"

This is the most fundamental conceptual difference:

- **Standard Agent Skills**: SKILL.md is an **instruction document** (knowledge
  pack). It tells the agent *how* to accomplish a task — "use pdfplumber to
  extract text", "run this script to fill forms". The agent then writes and
  executes its own code.

- **This project's Skills**: `query.sql` and `mutation.py` are **executable
  artifacts** (action templates). They are not instructions for the agent to
  interpret — they are pre-built operations that the server executes on behalf
  of the agent. The agent only provides parameters.

Converting to the standard format would mean turning SQL templates into
"instruction documents" that tell the agent to write its own SQL — which is
precisely **the scenario this project exists to prevent**.

### 11.4 Borrowed Elements

The following elements from the standard Agent Skills spec are applicable to
MCP and have been adopted:

**Directory structure**: Each skill is a folder with an entry file
(`skill_def.md`) plus optional bundled resources (e.g., `references/`).
This mirrors the standard `SKILL.md` + bundled files pattern.

**YAML frontmatter**: The `name` field follows the same regex constraint as
the standard spec (`^[a-z0-9][a-z0-9-]*$`, max 64 characters). The
`description` field serves the same purpose — providing discovery metadata
for the agent.

**Progressive interaction**: While the *mechanism* differs (MCP tool calls
vs bash file reads), the *pattern* is the same — the agent first discovers
what skills are available (low token cost), then selects and executes
specific skills (higher token cost only when needed).

**Composability via `related_skills`**: The `related_skills` field in
`skill_def.md` allows skills to declare associations with other skills.
For example, `update-order-status` declares:

```yaml
related_skills:
  - monthly-sales-report
  - monthly-sales-report-sqlite
```

This indicates a business-level association — after updating order status,
the agent may want to generate a sales report. When the agent calls
`list_skills()`, returned metadata includes `related_skills`, enabling
the agent to **discover workflow chains organically** rather than following a
hardcoded pipeline. This is analogous to "customers who bought X also
bought Y" — loose coupling between independently defined skills, with the
agent deciding whether and when to compose them. At startup, `discover()`
validates that all `related_skills` references point to existing skills
(warning-only, does not block registration).

#### Visual Comparison: Directory Structure

```mermaid
flowchart TB
  subgraph P[This Project's skills directory]
    P0[skills]
    P0 --> P1[_lib]
    P1 --> P11[skill_loader.py]
    P1 --> P12[mutation_base.py]
    P1 --> P13[audit.py]
    P0 --> P2[monthly-sales-report]
    P2 --> P21[skill_def.md]
    P2 --> P22[query.sql]
    P0 --> P3[monthly-sales-report-sqlite]
    P3 --> P31[skill_def.md]
    P3 --> P32[query.sql]
    P0 --> P4[update-order-status]
    P4 --> P41[skill_def.md]
    P4 --> P42[mutation.py]
    P4 --> P43[references]
    P43 --> P431[status-transitions.md]
  end

  subgraph S[Standard Agent Skills directory]
    S0[.claude/skills or platform-managed skill bundle]
    S0 --> S1[pdf-skill]
    S1 --> S11[SKILL.md]
    S1 --> S12[FORMS.md]
    S1 --> S13[REFERENCE.md]
    S1 --> S14[scripts]
    S14 --> S141[fill_form.py]
    S0 --> S2[another-skill]
    S2 --> S21[SKILL.md]
    S2 --> S22[other docs and resources]
  end

  P21 -. metadata and schema .-> X1[Parsed by discover on the server]
  P22 -. executable SQL template .-> X2[Executed through MCP tools]
  P32 -. executable Python mutation logic .-> X3[Executed through MCP tools]
  S11 -. metadata plus instructions .-> Y1[Read by the agent to decide how to act]
  S12 -. extra guidance .-> Y2[Loaded on demand]
  S141 -. bundled utility script .-> Y3[Run on demand by the agent]
```

**Elements NOT adopted** (inapplicable to MCP):

| Standard Element | Why Not Adopted |
|-----------------|-----------------|
| SKILL.md body as agent instructions | Agent has no filesystem access via MCP; skill_def.md body is for human developers |
| Agent reads files via bash | MCP protocol boundary prevents server filesystem access |
| Agent executes bundled scripts | Server-side execution model — agent only passes parameters |
| On-demand lazy loading | Conflicts with TOCTOU security requirement (Section 11.2) |

### 11.5 Security Depth Comparison

| Security Mechanism | This Project | Under Standard Agent Skills |
|----|----|----|
| **SQL whitelist** | `is_sql_safe()` validates at startup; unsafe skills rejected before registration | Agent reads SQL file at runtime and executes — bypasses validation |
| **Parameter validation** | `validate_params()` enforces type/min/max/enum constraints at server side; rejects parameters not defined in schema | Agent interprets parameters from natural language — no hard constraints; agent decides what values to pass |
| **TOCTOU prevention** | `discover()` reads all files into memory at startup; runtime = zero disk I/O | Agent reads files via bash on every invocation; files may have been tampered with between reads |
| **Mutation transaction safety** | `MutationBase` enforces BEGIN → UPDATE → verify rowcount → COMMIT/ROLLBACK | Agent writes its own transaction code; may omit rollback or error handling |
| **Audit logging** | Every mutation operation automatically recorded to `_audit.jsonl` by server infrastructure | Depends on agent voluntarily calling logging — unreliable |
| **Confirmation mechanism** | `requires_confirmation: true` + two-phase execution (preview → confirm) enforced by server | Agent decides whether to confirm — can be bypassed by prompt injection |

### 11.6 Summary

| Dimension | Standard Agent Skills | This Project's Skills |
|-----------|----------------------|----------------------|
| **Purpose** | Give a general-purpose agent domain expertise | Give an untrusted agent safe, pre-built database operations |
| **Skill content** | Instructions + scripts + references (knowledge) | SQL templates + Python mutation classes (executable artifacts) |
| **Executor** | Agent itself (in VM/sandbox) | MCP Server (on behalf of agent) |
| **Trust model** | Sandbox isolation + trust the agent | Do not trust the agent; server enforces all constraints |
| **Loading** | Lazy, on-demand via bash | Eager, all-at-startup via `discover()` |
| **Security responsibility** | Agent + sandbox | Server infrastructure |

The standard Agent Skills format solves: *"How to give a general-purpose agent
domain expertise."* This project solves: *"How to let an untrusted agent safely
operate on a database."* The threat models, trust boundaries, and execution
architectures are fundamentally different. Forcing the standard format would
sacrifice core security properties (startup validation, typed parameters,
server-side enforcement) without gaining any benefit — since the agent cannot
access the server filesystem through MCP anyway.

## 12. Testing

64 new tests across 4 files:

| File | Tests | Coverage |
|------|-------|---------|
| `test_skill_loader.py` | 35 | Discovery, parsing, validation, name checks, mutation class caching, extra params rejection |
| `test_query_skills.py` | 8 | Parameterized read, write, injection safety |
| `test_mutation_skills.py` | 9 | Dry-run, confirm, idempotent, error sanitization, ToolError audit logging |
| `test_audit.py` | 8 | JSONL logging, sanitization, directory creation, mkdir error handling |

All tests use SQLite in-memory databases for speed and isolation.

## 13. Future Extensions

- **Per-operation independent tools**: High-frequency skills as dedicated MCP tools
- **Confirmation tokens**: Server-side anti-replay for untrusted callers
- **Write connection isolation**: `DB_WRITE_*` env vars for separate write accounts
- **Audit to database**: Optional `_audit_log` table for structured querying
- **mutation.sql**: SQL-only mutations for simple INSERT/UPDATE operations
- **`adapter.transaction()`**: Multi-statement atomic transactions
- **Output schemas**: Optional explicit `output_schema` declarations for selected stable tool responses

## 14. Industry Best Practices Alignment

This section documents how the Skills extension aligns with industry best
practices from major AI platform providers and security standards.

### Tool Design Principles

| Principle | Source | How Applied |
|-----------|--------|-------------|
| *"Offload the burden from the model and use code where possible."* | [OpenAI — Function Calling Best Practices (2025)](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions) | Skills pre-build SQL/Python logic; Agent only passes parameters |
| *"Don't make the model fill arguments you already know."* | OpenAI, ibid. | Skill metadata and SQL templates encode business knowledge |
| *"Keep the number of tools small for higher accuracy."* | [OpenAI — Function Calling](https://platform.openai.com/docs/guides/function-calling) | Unified `execute_*_skill()` tools instead of per-skill tool registration |
| *"Use clear and descriptive function/parameter names and descriptions."* | [Google Gemini — Function Calling Best Practices](https://ai.google.dev/gemini-api/docs/function-calling#best_practices) | `skill_def.md` YAML frontmatter provides structured name, description, and parameter schemas |
| *"Use strong schema: specify types, limits, enums, and valid patterns."* | Google Gemini, ibid. | `validate_params()` enforces `type`, `min`, `max`, `enum` constraints declared in YAML |
| 10-20 tools recommended range | [Google Gemini — Function Calling Limits](https://ai.google.dev/gemini-api/docs/function-calling) | Maximum 11 tools when all optional schema/table-summary and mutation skills are enabled (within range) |

### Agent Architecture Principles

| Principle | Source | How Applied |
|-----------|--------|-------------|
| *"Give models less freedom for higher-stakes operations."* | [Anthropic — Building Effective Agents (2024)](https://docs.anthropic.com/en/docs/build-with-claude/agentic-systems) | Mutation skills use constrained `MutationBase` ABC; no free-form code execution |
| *"Verifiable intermediate outputs"* | Anthropic, ibid. | Two-phase execution: `confirm=false` returns preview for verification |
| *"Plan-validate-execute"* pattern | Anthropic, ibid. | `MutationBase` enforces `validate()` → `preview()` → `execute()` stages |
| Progressive disclosure | [Anthropic — Agent Skills Overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) | `list_skills()` returns compact/summary/full projected metadata; `get_skill_detail()` retrieves one cached params schema on demand |
| Conditional tool discovery | [OpenAI — Tool Search](https://developers.openai.com/api/docs/guides/tools-tool-search) | `available_only` filters skills according to current project/server state, including DB type, mutation switch, and schema readiness, before the Agent plans execution |
| Dynamic relevant tool set | [Google Gemini — Function Calling Best Practices](https://ai.google.dev/gemini-api/docs/function-calling) | Default Agent-facing skill discovery hides incompatible skills to reduce tool-selection errors |
| Metadata naming convention | [Anthropic — Agent Skills Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | `name` regex `^[a-z0-9][a-z0-9-]*$` (max 64 chars), aligned with standard |

### Security Standards

| Principle | Source | How Applied |
|-----------|--------|-------------|
| *"Validate all inputs"* | [MCP Specification §7 — Security](https://modelcontextprotocol.io/specification/2025-03-26/basic/security) | Skills execution validates skill names and params; base tools use SQL/table-specific validators |
| *"Implement proper access controls"* | MCP Spec §7, ibid. | Dual-layer switches + ALLOWED_TABLES + path constraints |
| Parameterized queries | [OWASP — SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) | SQLAlchemy `text()` + parameter binding; zero string concatenation |
| TOCTOU prevention | [MITRE CWE-367](https://cwe.mitre.org/data/definitions/367.html) | Startup-time caching eliminates runtime file reads |
| Least privilege | OWASP, general | `ENABLE_SKILLS=0` by default; `SKILLS_ALLOW_MUTATIONS=0` by default |
| Tool filtering is not authorization | [Microsoft — Function Calling Responsibly](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/function-calling) | `available_only` is only a discovery filter; execution still validates skill name, params, mutation switch, `DB_TYPE`, and required-table readiness |
| Error sanitization | [FastMCP — ToolError](https://gofastmcp.com/servers/tools#errors) | `_handle_error()` strips sensitive details; `ToolError` bypasses `mask_error_details` |

### Framework Integration

| Pattern | Source | How Applied |
|---------|--------|-------------|
| `ToolError` for expected failures | [FastMCP — Error Handling](https://gofastmcp.com/servers/tools#errors) | Mutation failures raise `ToolError` (passed to client) vs generic exceptions (masked) |
| `ToolAnnotations` metadata | [FastMCP — Tool Annotations](https://gofastmcp.com/servers/tools#tool-annotations) | `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint=false` for MCP tools |
| Runtime tool metadata | [FastMCP — ToolResult and Metadata](https://gofastmcp.com/servers/tools#toolresult-and-metadata) | All 11 tools return `ToolResult` with unchanged structured payload plus non-sensitive runtime `meta` (uniform since v3.4.2) |
| Explicit transaction via `engine.begin()` | [SQLAlchemy 2.0 — Transactions](https://docs.sqlalchemy.org/en/20/core/connections.html#using-transactions) | `execute_write()` uses `engine.begin()` context manager (auto-commit/auto-rollback) |
| Identifier quoting | [SQLAlchemy — `quoted_name()`](https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.quoted_name) | Table names quoted to prevent SQL injection in dynamic identifiers |
