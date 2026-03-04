# MCP Agents Skills Design Document

> **Version**: 3.0  
> **Status**: Implemented  
> **Date**: 2026-03  
> **Reference**: DRAFTPLAN_final.md, DRAFTPLAN_final_addendum.md

## 1. Overview

The Skills extension layer adds pre-defined, parameterized SQL operations
(queries and mutations) to the LLM Database Safety Gateway MCP server.
Skills are discoverable, auditable, and controlled by environment variables.

### Goals

- **Structured database operations** — Replace free-form SQL with reviewed templates
- **Progressive disclosure** — Three-level information architecture for token efficiency
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
│  │ list_skills  │  │execute_query_skill│  │execute_mutation│  │
│  │  (readOnly)  │  │  (readOnly)      │  │  _skill       │  │
│  └──────┬───────┘  └────────┬─────────┘  └───────┬───────┘  │
│         │                   │                     │          │
│  ┌──────┴───────────────────┴─────────────────────┴───────┐  │
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
Agent → list_skills()          → Skill metadata (name, type, risk, triggers)
Agent → execute_query_skill()  → skill_loader → adapter.execute(sql, params)
Agent → execute_mutation_skill(confirm=false)
                               → mutation.validate() + preview()
Agent → execute_mutation_skill(confirm=true)
                               → mutation.validate() + run_execute() → adapter.execute_write()
                                                                     → audit.log()
```

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
├── monthly-sales-report/              # Example query skill
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
risk: low                     # low | medium | high
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

## 5. Security Model

See [skills/SAFETY.md](skills/SAFETY.md) for the full 16-item security policy.

### Key Principles

| # | Principle | Implementation |
|---|-----------|----------------|
| 1 | Template as whitelist | Only pre-defined SQL/Python executed |
| 2 | Parameterized queries | SQLAlchemy `text()` + params binding |
| 3 | Dry-run default | `confirm=False` returns preview only |
| 4 | Dual-layer switches | `ENABLE_SKILLS` + `SKILLS_ALLOW_MUTATIONS` |
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
    # register: list_skills(), execute_query_skill()
    
    if SKILLS_ALLOW_MUTATIONS:
        # register: execute_mutation_skill()
```

### Tool Annotations

| Tool | readOnlyHint | destructiveHint | idempotentHint |
|------|-------------|-----------------|----------------|
| `list_skills` | true | false | true |
| `execute_query_skill` | true | false | true |
| `execute_mutation_skill` | false | true | false |

`idempotentHint=false` for mutations is a conservative default. Per-skill
idempotency info is conveyed via `list_skills()` and execution result dicts.

### Tool Count Impact

| Configuration | Tool Count |
|--------------|------------|
| ENABLE_SKILLS=0 | 5-7 (unchanged) |
| ENABLE_SKILLS=1, MUTATIONS=0 | 7-9 |
| ENABLE_SKILLS=1, MUTATIONS=1 | 8-10 |

Within Google Gemini's recommended 10-20 tools range.

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

Three levels of information, following Anthropic best practices:

| Level | Source | Token Cost | Content |
|-------|--------|-----------|---------|
| 1 | `list_skills()` | ~100/skill | name, type, risk, triggers, description |
| 2 | skill_def.md body | < 500 lines | Usage, workflow, notes |
| 3 | query.sql / mutation.py | Varies | Actual SQL/Python source |

## 9. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SKILLS` | `0` | Master switch for skills extension |
| `SKILLS_ALLOW_MUTATIONS` | `0` | Enable mutation skills (second switch) |
| `SKILLS_DIR` | `skills/` | Skills directory path |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | Audit log file path |

## 10. Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Architecture | Unified registration (2-3 tools) | Per-skill tools / FastMCP mount() | Prevents tool explosion; Google Gemini 10-20 rule |
| Metadata | skill_def.md YAML frontmatter | JSON manifest | Anthropic Agent Skills spec alignment |
| Params validation | Inline in frontmatter | JSON Schema file | Single-file self-description |
| Write safety | 3-stage (validate/preview/execute) | Simple confirm flag | Anthropic "verifiable intermediate outputs" |
| Audit storage | JSONL file | Database table | Minimal dependency for MVP |
| Write interface | Separate `execute_write()` | Reuse `execute()` | Read/write separation, clear responsibilities |
| SQL caching | discover() caches at startup | Runtime disk reads | Eliminates TOCTOU risk |
| Mutation caching | discover() pre-loads mutation classes | Per-call `exec_module()` | Eliminates runtime disk I/O + module compilation |
| Error handling | Exceptions propagate + ToolError | Error dict returns | FastMCP ToolError bypasses mask_error_details |
| ALLOWED_TABLES | Skills bypass at runtime | Runtime table check | Template = whitelist (code review trust) |
| SQLAlchemy version | `>=2.0` explicit | No constraint | 2.0 implicit transactions prevent accidental writes |
| Example skill SQL | MySQL-only `YEAR()`/`MONTH()` | Cross-DB functions | Example skill for MySQL-primary project; `skill_def.md` Notes marks MySQL-only; cross-DB compatibility is skill author's responsibility |
| Table name extraction | `_extract_table_names()` ignores `schema.table` | Full `schema.table` regex | Function only used for `SKILLS.md` generation (non-security); core path `_extract_tables_from_sql()` handles `schema.table` correctly |
| Mutation duplicate SELECT | `execute()` re-runs `validate()` SELECT | Single SELECT in `validate()` only | Intentional TOCTOU prevention — user review gap between preview and confirm requires re-verification of data state |
| Mutation error contract | `execute()` raises `ToolError` on failure | Return `{"success": False}` dict | Exceptions follow `run_execute()` error handling chain; return-dict failures bypass audit logging and cause semantic contradiction in MCP tool response |
| Mutation read-write gap | Separate `execute()` + `execute_write()` calls | Single SQL merging SELECT+UPDATE | Optimistic locking `WHERE status = :expected` + `rowcount == 0` is the effective safety net; merging adds complexity with minimal gain |
| `_coerce_type()` bool | `bool(value)` (Python built-in) | Explicit `"true"/"false"` mapping | No bool params in current skills; acceptable for MVP, should be revisited when bool params are added |

## 11. Testing

64 new tests across 4 files:

| File | Tests | Coverage |
|------|-------|---------|
| `test_skill_loader.py` | 35 | Discovery, parsing, validation, name checks, mutation class caching, extra params rejection |
| `test_query_skills.py` | 8 | Parameterized read, write, injection safety |
| `test_mutation_skills.py` | 9 | Dry-run, confirm, idempotent, error sanitization, ToolError audit logging |
| `test_audit.py` | 8 | JSONL logging, sanitization, directory creation, mkdir error handling |

All tests use SQLite in-memory databases for speed and isolation.

## 12. Future Extensions

- **Per-operation independent tools**: High-frequency skills as dedicated MCP tools
- **Confirmation tokens**: Server-side anti-replay for untrusted callers
- **Write connection isolation**: `DB_WRITE_*` env vars for separate write accounts
- **Audit to database**: Optional `_audit_log` table for structured querying
- **mutation.sql**: SQL-only mutations for simple INSERT/UPDATE operations
- **`adapter.transaction()`**: Multi-statement atomic transactions
- **`ToolResult.meta`**: Per-invocation runtime metadata via FastMCP v2.11.0+
