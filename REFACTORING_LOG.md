# MCP SQL Server Refactoring Log

**Date:** December 2, 2025 (Updated: May 14, 2026)
**Author:** Code Refactoring Session

## Overview

This document records the major refactoring changes made to `mcp_sql_server.py` to follow FastMCP best practices and improve the overall design.

---

## Latest Update v3.4 (May 14, 2026) - MCP Hardening and Skills Profile Policy

### Overview

Reviewed ten proposed hardening items and implemented the
low-risk changes that improve security or test signal without changing the
default Skills execution model. Runtime SQL/Python source loading remains
unchanged: executable skill artifacts are still validated and cached at startup.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Enabled FastMCP `mask_error_details=True`; added configurable MCP tool timeouts; added `MAX_SQL_LENGTH` schema/runtime guard for raw `query(sql)`; added `SKILLS_EXCLUDE_PROFILES`; added optional query skill audit logging |
| `skills/_lib/audit.py` | Modified | Generalized audit wording from mutation-only to skill operations and records optional query metadata such as `total_rows` and `truncated` without logging returned data |
| `test_bug_fixes.py` | Modified | Refactored source-based checks so pytest tests assert instead of returning booleans |
| `tests/test_skills_disclosure.py` | Modified | Added coverage for profile exclusion, direct execution blocking, query skill audit, raw query MCP schema length metadata, and runtime raw SQL length rejection |
| `.env.example` | Modified | Documented `MCP_TOOL_TIMEOUT_SECONDS`, `MAX_SQL_LENGTH`, `SKILLS_EXCLUDE_PROFILES`, and `SKILLS_AUDIT_QUERIES` |
| `README.md` | Modified | Documented the new hardening controls and deferred decisions |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Recorded the profile policy, optional query audit, tool timeout, raw SQL length decision, and deferred v3.4.B3/v3.4.B4/v3.4.C1 choices |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Pytest warnings | Convert boolean-returning tests to assert wrappers | Leave source-verification script unchanged | Removes noisy pytest warnings while preserving direct script execution |
| Error masking | `mask_error_details=True` | Depend only on local sanitization | Masks unexpected exceptions while explicit `ToolError` messages continue to expose sanitized guidance |
| Raw SQL length | `MAX_SQL_LENGTH=20000` for `query(sql)` | Apply length caps to skill SQL templates | Free-form Agent SQL is untrusted input; reviewed skill templates are code artifacts validated at startup |
| Profile policy | `SKILLS_EXCLUDE_PROFILES` marks matching skills non-executable | Delete bundled demo skills from production branches | Keeps examples useful but gives production deployments an explicit guardrail |
| Query audit | `SKILLS_AUDIT_QUERIES=0` opt-in | Audit all query skills by default | Avoids surprising parameter logs; compliance-oriented deployments can enable it |
| Tool timeout | FastMCP `timeout` via `MCP_TOOL_TIMEOUT_SECONDS` | Only DB-level timeout | Covers non-DB stalls and foreground request hangs; default is conservative for schema tools |
| v3.4.B3 ToolResult metadata | Deferred decision | Wrap current dict returns in `ToolResult` | Would alter client-facing response contracts without a current need |
| v3.4.B4 Session schema cache | Deferred decision | Cache table names in `ctx.set_state()` | Reduces repeated metadata reads but can stale after DDL; table-readiness checks are lightweight |
| v3.4.C1 Schema resource | Deferred decision | Add `db://schema` MCP resource | Existing schema tool is explicit and broadly supported; resource path can be added later without blocking current workflows |

### Compatibility Notes

- All new runtime behavior is controlled by environment variables or preserves old defaults.
- `SKILLS_EXCLUDE_PROFILES` defaults to empty, so existing Skills catalogs are unchanged unless explicitly configured.
- `SKILLS_AUDIT_QUERIES` defaults to `0`; mutation auditing behavior is unchanged.
- `MAX_SQL_LENGTH` affects only raw `query(sql)` input, not reviewed query skill templates.
- `ToolError` messages remain visible by design under FastMCP error masking.

### Testing

- `.venv/bin/python -m pytest test_bug_fixes.py tests/test_skills_disclosure.py tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py -q` - 99 passed
- `.venv/bin/python -m pytest -q -k 'not test_mcp_server'` - 160 passed, 1 deselected

---

## Update v3.3 (May 14, 2026) - Skills Availability Filtering and SQLite Example

### Overview

Added Agent-facing availability filtering for Skills discovery and introduced a
SQLite-specific monthly sales report example. The availability check now includes
DB compatibility, mutation switch state, and optional table-level schema
readiness. This change keeps startup discovery, SQL validation, mutation class
loading, and execution-time checks eager and unchanged as the security boundary.
`available_only` only changes which cached skill metadata is returned by
`list_skills()`.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` and `SKILLS_CHECK_SCHEMA_ON_LIST`; added `list_skills(..., available_only)`; included current `DB_TYPE`, mutation switch, and schema readiness in skill executability metadata; default Agent-facing catalog hides currently non-executable skills |
| `skills/monthly-sales-report-sqlite/` | Added | Added SQLite query skill using the sample SQLite schema (`orders.order_date`, `orders.total_amount`) |
| `skills/_lib/skill_loader.py` | Modified | Added `profiles` and declarative `tables` frontmatter support; query tables are merged from reviewed SQL extraction and declared tables |
| `skills/monthly-sales-report/skill_def.md` | Modified | Linked to the SQLite counterpart via `related_skills`, kept `databases: [mysql]`, and marked the bundled example as `profiles: [demo]` |
| `skills/update-order-status/skill_def.md` | Modified | Linked to both monthly report examples, marked the skill as `profiles: [demo]`, and declared `tables: [orders]` |
| `skills/SKILLS.md` | Modified | Regenerated/updated catalog to include databases, profiles, and table dependencies |
| `tests/test_skills_disclosure.py` | Modified | Added coverage for default availability filtering, schema readiness, explicit full catalog listing, env default override, DB-specific visibility, and MCP `list_tools()` schemas |
| `.env.example` | Modified | Documented `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1` and `SKILLS_CHECK_SCHEMA_ON_LIST=1` |
| `README.md` / `README_ZH.md` | Modified | Documented `available_only`, schema readiness, demo profiles, the new default behavior, full catalog override, and SQLite skill example |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Documented conditional availability filtering, related design decisions, and external practice references |
| `TEST_MCP_CLIENT_GUIDE.md` | Modified | Updated Skills smoke examples and config hints |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Availability filtering | `available_only` on `list_skills()` | Separate developer/admin listing tool | Keeps the MCP surface small and matches existing discovery workflow; developers can pass `available_only=false` |
| Default availability | `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=1` | Preserve full catalog as no-arg default | The tool is Agent-facing, so default discovery should not suggest skills that will fail under the current `DB_TYPE` or mutation switch |
| Schema readiness | `SKILLS_CHECK_SCHEMA_ON_LIST=1` table-existence check | Do no live schema check, or validate every column/type | Catches wrong-schema demo/production mismatches with low overhead while leaving precise validation to execution |
| Security boundary | Keep execution-time compatibility checks | Treat filtering as enforcement | Tool filtering is advisory/ergonomic; callers can still name hidden skills, so execution must remain authoritative |
| SQLite example | Separate `monthly-sales-report-sqlite` skill | One SQL template with dialect branches | Separate skills keep SQL review, startup validation, and Agent selection deterministic |
| Demo profiles | Mark bundled examples with `profiles: [demo]` | Disable examples by default | Keeps examples discoverable for sample databases while making their intended schema explicit |
| Missing `databases` | Keep meaning as all supported DBs | Require every skill to declare databases | Preserves compatibility for portable skills such as `update-order-status` |

### Compatibility Notes

- `ENABLE_SKILLS=0` still registers no Skills tools.
- `list_skills(available_only=false)` restores the full discovered catalog.
- `get_skill_detail(skill_name)` remains available for hidden incompatible or schema-unready skills and includes `executable=false` plus a `disabled_reason`.
- Execution checks still reject database-incompatible or schema-unready skills even if a caller bypasses discovery and directly calls an execution tool.

### External Practice Review

- OpenAI Tool Search supports deferred/client-executed discovery when available tools depend on project or system state; `available_only` is this project's in-MCP analog.
- Anthropic Agent Skills and MCP code-execution guidance emphasize progressive disclosure and loading only relevant definitions.
- Google Gemini function calling best practices recommend keeping the provided tool set relevant and small to reduce selection errors.
- FastMCP annotations and visibility features are useful for presentation and tool surfaces, but annotations are advisory.
- Microsoft function calling guidance emphasizes validating function calls and not relying only on omitted tool definitions as a security control.

### Testing

- `.venv/bin/python -m pytest tests/test_skills_disclosure.py -q` - 19 passed
- `.venv/bin/python -m pytest tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py tests/test_skills_disclosure.py -q` - 92 passed
- `.venv/bin/python -m pytest tests/test_skills_disclosure.py tests/test_skill_loader.py -q` - 74 passed
- `.venv/bin/python -m pytest -q -k 'not test_mcp_server'` - 156 passed, 1 deselected; warning cleanup was completed in v3.4

---

## Update v3.2 (May 12, 2026) - Skills Metadata On-Demand Disclosure

### Overview

Added MCP-level on-demand metadata disclosure for the Skills layer. This change
does **not** lazy-load executable artifacts: `discover()` still validates SQL and
pre-loads mutation classes at startup, and runtime execution still uses the
in-memory cache. Only the Agent-facing metadata projection changed.

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | Added `SKILLS_LIST_DEFAULT_DETAIL`; extended `list_skills(search, category, detail_level)`; added `get_skill_detail(skill_name)`; added compact/summary/full metadata projections and category aggregation |
| `skills/_lib/skill_loader.py` | Modified | Added optional `databases` metadata parsing/validation and included supported database types in generated `SKILLS.md` |
| `skills/monthly-sales-report/skill_def.md` | Modified | Declared `databases: [mysql]` because the example SQL uses MySQL-specific date functions |
| `tests/test_skills_disclosure.py` | Added | Tests for default summary disclosure, compact/full projections, search, category filtering, categories aggregation, overlong search rejection, and `get_skill_detail` errors |
| `tests/test_skill_loader.py` | Modified | Added coverage for omitted, scalar, multiple, case-insensitive, empty, and invalid `databases` values |
| `tests/conftest.py` | Modified | Added an engine assertion for SQLite fixture typing/analysis safety |
| `.env.example` | Modified | Added `SKILLS_LIST_DEFAULT_DETAIL=summary` documentation |
| `README.md` / `README_ZH.md` | Modified | Documented `get_skill_detail`, list projection levels, search/category filters, and the new workflow |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Documented metadata disclosure levels and clarified that executable artifacts remain eager-loaded for TOCTOU protection |
| `agent_examples/autogen_sql_agent_new.py` | Modified | Added `get_skill_detail` capability detection and prompt guidance |
| `TEST_MCP_CLIENT_GUIDE.md` | Modified | Updated Skills tool list and configuration example |

### Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Disclosure levels | `compact`, `summary`, `full` | `names` alias or custom field lists | Three stable levels cover discovery, compatibility-oriented metadata, and execution planning without exposing raw source |
| Default detail | `summary` via `SKILLS_LIST_DEFAULT_DETAIL` | Default `full` | Keeps the default useful while reducing unnecessary parameter-schema disclosure; per-call `detail_level` can override |
| Search | Case-insensitive substring | Regex/BM25 | Deterministic, dependency-free, avoids ReDoS and model-generated regex fragility |
| Category handling | Missing category maps to `uncategorized` | Omit category | Gives Agents a stable grouping key and supports category aggregation |
| Detail tool | Add `get_skill_detail(skill_name)` | Add `search_skills` or per-skill tools | One extra read-only tool enables on-demand params without tool explosion |
| Artifact loading | Keep startup eager validation/cache | Runtime disk reads | Preserves TOCTOU protection and existing security model |
| Database compatibility | Optional `databases` field | No DB type declaration | Prevents execution of DB-specific skills on incompatible adapters; omitted field means all supported DB types |

### Compatibility Notes

- `ENABLE_SKILLS=0` remains zero-overhead: no Skills tools are registered.
- Existing execution tools are unchanged.
- `list_skills()` now returns additive metadata fields such as `detail_level`,
  `matched_skills`, `categories`, and `hint`. Clients that need maximum detail
  can call `list_skills(detail_level="full")` or `get_skill_detail(skill_name)`.

### Testing

- `pytest tests/test_skills_disclosure.py -q` - 13 passed
- `pytest tests/test_skill_loader.py tests/test_query_skills.py tests/test_mutation_skills.py tests/test_skills_disclosure.py -q` - 85 passed

---

## Update v3.1 (March 17, 2026) - Explicit Source Declaration

### Overview

Added a mandatory `source` field to `skill_def.md` YAML frontmatter. Each skill must now explicitly declare its execution file (e.g. `source: query.sql`, `source: mutation.py`), replacing the previous convention-based implicit file association (hardcoded `query.sql` and `mutation.py` filenames).

This follows the **Explicit Configuration** principle — the same approach used by GitHub Actions (`action.yml` `main` field), npm (`package.json` `main` field), and Python (`pyproject.toml` entry points).

### Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `skills/_lib/skill_loader.py` | Modified | Added `source: str` field to `SkillMetadata`; new `_validate_source_filename()` function with security checks (path traversal, hidden files, suffix enforcement); `_parse_skill_md()` extracts and validates `source`; `discover()` uses `metadata.source` instead of hardcoded filenames |
| `skills/monthly-sales-report/skill_def.md` | Modified | Added `source: query.sql` to YAML frontmatter |
| `skills/update-order-status/skill_def.md` | Modified | Added `source: mutation.py` to YAML frontmatter |
| `tests/test_skill_loader.py` | Modified | All fixtures updated with `source` field; 9 new tests added (TestSourceField class): missing source, path traversal, backslash traversal, wrong suffix, mutation wrong suffix, hidden file, custom filename, source stored in metadata |
| `MCP_AGENTS_SKILLS_DESIGN.md` | Modified | Section 4: added `source` to YAML schema example; added 5th design rationale (Explicit Configuration principle with industry comparison table); Section 10: added design decision entry |
| `README.md` | Modified | Updated skill_def.md examples and "Adding Custom Skills" section |
| `README_ZH.md` | Modified | Updated skill_def.md examples and "如何添加自定义 Skill" section |
| `REFACTORING_LOG.md` | Modified | This entry |
| `skills/SAFETY.md` | Modified | Updated item #1 to reference explicit `source` field |

### Key Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Field name | `source` | `main`, `entry_point`, `file` | Consistent with web conventions; short and descriptive |
| Mandatory | Required, no default | Optional with convention fallback | User's explicit requirement; prevents ambiguity about file association |
| Suffix enforcement | query→.sql, mutation→.py | No enforcement | Prevents misconfiguration; catches type/file mismatch early |
| Filename validation | Regex + path traversal + hidden file checks | Path-only check | Defense-in-depth: `_validate_source_filename()` enforces safe character set, no path separators, no leading dots |
| Custom filenames | Allowed (e.g. `daily-revenue.sql`) | Fixed names only | Enables descriptive naming while maintaining security through validation |

### Source Filename Validation (`_validate_source_filename()`)

Security checks performed on the `source` field value:
1. Must not be empty
2. Max 128 characters
3. No path separators (`/` or `\\`) — prevents directory traversal
4. Must not start with `.` — prevents hidden files and `..` traversal
5. Must match regex `^[a-zA-Z0-9][a-zA-Z0-9._-]*$` — safe character set
6. Suffix must match skill type: `query` → `.sql`, `mutation` → `.py`
7. Resolved path must stay within skill directory — prevents symlink escape

### Testing

- **125 total tests, 0 failures** — all internal examples and tests migrated; external custom skills require adding `source` field (schema-breaking change)
- 9 new tests in `TestSourceField` class covering all validation paths
- All existing 38 skill_loader tests updated with `source` field and passing

---

## Update v3.0 (March 1, 2026) - Skills Extension Layer

### Overview

Added an optional Skills extension layer for pre-defined, parameterized SQL operations. Skills provide structured Agent interactions with query and mutation support, following Anthropic Agent Skills best practices for progressive disclosure.

**Backward Compatible**: `ENABLE_SKILLS=0` (default) — zero overhead, no tools registered.

### System Architecture (v3.0)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                          LLM / MCP Client (Agent)                            │
└────────────────────────────────┬──────────────────────────────────────────────┘
                                 │  MCP Protocol (stdio / SSE)
                                 ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          mcp_sql_server.py                                   │
│                          (FastMCP v3.0 Server)                               │
│                                                                              │
│   ┌─────── Core Tools (always on) ──────┐  ┌── Skills Tools (opt-in) ──────┐ │
│   │ query()           list_tables()     │  │ list_skills()               │ │
│   │ describe_table()  get_full_schema() │  │ execute_query_skill()       │ │
│   │ check_connection()                  │  │ execute_mutation_skill()    │ │
│   │ [sample()]  [get_table_summary()]   │  │                             │ │
│   │  ↑ ENABLE_SCHEMA_TOOLS opt-in      │  │  ↑ ENABLE_SKILLS opt-in     │ │
│   └──────────────┬──────────────────────┘  └──────────┬─────────────────┘ │
│                  │                                    │                    │
│   ┌──────────────▼────────────────┐    ┌──────────────▼──────────────────┐ │
│   │   sql_safety_checker.py      │    │       skills/_lib/              │ │
│   │   ─────────────────────      │    │   ┌──────────────────────────┐  │ │
│   │   is_sql_safe()  (allowlist) │    │   │ skill_loader.py          │  │ │
│   │   execute_sql()  (runtime)   │    │   │  discover() / load_*()   │  │ │
│   │                              │    │   ├──────────────────────────┤  │ │
│   │   + _is_query_safe_extended()│    │   │ mutation_base.py         │  │ │
│   │   + _check_table_allowlist() │    │   │  MutationBase (ABC)      │  │ │
│   │     (in mcp_sql_server.py)   │    │   ├──────────────────────────┤  │ │
│   └──────────────┬───────────────┘    │   │ audit.py                 │  │ │
│                  │                    │   │  AuditLogger → JSONL     │  │ │
│                  │                    │   └──────────┬───────────────┘  │ │
│                  │                    └──────────────┼──────────────────┘ │
│                  │                                   │                    │
│   ┌──────────────▼───────────────────────────────────▼──────────────────┐ │
│   │                       db_adapter.py                                │ │
│   │                    DatabaseAdapter (ABC)                           │ │
│   │   ┌────────────────────────┐  ┌────────────────────────┐          │ │
│   │   │    MySQLAdapter        │  │    SQLiteAdapter       │          │ │
│   │   │  execute() / execute   │  │  execute() / execute   │          │ │
│   │   │  _write() / get_*()   │  │  _write() / get_*()   │          │ │
│   │   └───────────┬────────────┘  └───────────┬────────────┘          │ │
│   └───────────────┼───────────────────────────┼────────────────────────┘ │
└───────────────────┼───────────────────────────┼──────────────────────────┘
                    │                           │
                    ▼                           ▼
              ┌──────────┐               ┌──────────────┐
              │  MySQL   │               │   SQLite     │
              │ (remote) │               │  (local file)│
              └──────────┘               └──────────────┘
```

### Skills Execution Flow

```
                          ┌─────────────────────────┐
                          │  Server Startup          │
                          └────────────┬─────────────┘
                                       ▼
                          ┌─────────────────────────┐
                          │  discover(_skills_dir)   │
                          │  - Scan skill_def.md     │
                          │  - Parse YAML frontmatter│
                          │  - Validate SQL safety   │
                          │  - Cache SkillMetadata   │
                          └────────────┬─────────────┘
                                       ▼
         ┌────────────────────────────────────────────────────────┐
         │                                                        │
  ┌──────▼──────┐       ┌──────────────────┐       ┌─────────────▼─────────────┐
  │ list_skills │       │execute_query_skill│       │  execute_mutation_skill   │
  │             │       │                  │       │                           │
  │ Return:     │       │ 1. validate_name │       │ confirm=false (preview):  │
  │  metadata   │       │ 2. load_query    │       │  1. validate_name         │
  │  (cached)   │       │ 3. validate_params│      │  2. load_mutation         │
  │             │       │ 4. adapter       │       │  3. validate_params       │
  │             │       │    .execute(     │       │  4. mutation.validate()   │
  │             │       │      sql, params)│       │  5. mutation.preview()    │
  └─────────────┘       └──────────────────┘       │  6. audit.log()          │
                                                   │                           │
                                                   │ confirm=true (execute):   │
                                                   │  1-3. (same as above)     │
                                                   │  4. mutation.validate()   │
                                                   │  5. mutation.run_execute()│
                                                   │     → adapter.execute     │
                                                   │       _write(sql, params) │
                                                   │  6. audit.log()          │
                                                   └───────────────────────────┘
```

### Architecture: Skills Directory Convention

```
skills/
├── SAFETY.md                          # Security governance (16 items)
├── SKILLS.md                          # Auto-generated overview (by discover())
├── _lib/                              # Shared infrastructure
│   ├── __init__.py
│   ├── skill_loader.py                # Discovery, loading, validation (~550 lines)
│   ├── mutation_base.py               # ABC for write operations (~170 lines)
│   └── audit.py                       # JSONL audit logger (~120 lines)
├── monthly-sales-report/              # Example query skill
│   ├── skill_def.md                   # YAML frontmatter + documentation
│   └── query.sql                      # Parameterized SQL template
└── update-order-status/               # Example mutation skill
    ├── skill_def.md                   # YAML frontmatter + documentation
    ├── mutation.py                    # validate/preview/execute logic
    └── references/
        └── status-transitions.md      # State machine documentation
```

### Naming: `skill_def.md` (not `SKILL.md`)

Skill definition files are named `skill_def.md` instead of `SKILL.md` to avoid conflicts with GitHub Copilot / FastMCP's built-in `SKILL.md` skill file format. VS Code's Copilot extension validates `SKILL.md` files against its own schema (expecting attributes like `argument-hint`, `compatibility`, `user-invokable` etc.), which produces false lint errors on our custom YAML frontmatter attributes (`type`, `risk`, `params`, `triggers` etc.).

### New Files

| File | Lines | Description |
|------|-------|-------------|
| `skills/_lib/skill_loader.py` | ~550 | Skill discovery, YAML parsing, SQL safety validation at startup, in-memory caching |
| `skills/_lib/mutation_base.py` | ~170 | ABC for mutations: validate → preview → execute pattern with audit logging |
| `skills/_lib/audit.py` | ~120 | Thread-safe JSONL audit logger with parameter sanitization |
| `skills/SAFETY.md` | — | 16-item security governance document for skill authors |
| `skills/monthly-sales-report/` | — | Example query skill (parameterized SQL) |
| `skills/update-order-status/` | — | Example mutation skill (state machine with optimistic locking) |
| `MCP_AGENTS_SKILLS_DESIGN.md` | ~270 | Design document: architecture, security model, decisions |
| `tests/test_skill_loader.py` | 30 tests | Discovery, parsing, validation, name checks, edge cases |
| `tests/test_query_skills.py` | 8 tests | Parameterized read, write, injection safety |
| `tests/test_mutation_skills.py` | 8 tests | Dry-run, confirm, idempotent, error sanitization |
| `tests/test_audit.py` | 7 tests | JSONL logging, sanitization, directory creation |
| `pyrightconfig.json` | — | Pyright/Pylance config: adds `skills/_lib` to `extraPaths` for import resolution, sets `reportMissingImports` to warning |

### Modified Files

| File | Change Type | Description |
|------|-------------|-------------|
| `mcp_sql_server.py` | Modified | v3.0 header, `ToolError` import, Skills config, 3 new MCP tools (`list_skills`, `execute_query_skill`, `execute_mutation_skill`), updated `sql_assistant` prompt |
| `db_adapter.py` | Modified | `execute()` accepts optional `params`, new `execute_write()` for transactions, unified `_handle_error(self, e, timeout=None)` |
| `start_server.py` | Modified | `validate_environment()` is now DB_TYPE-aware (MySQL vs SQLite) |
| `requirements.txt` | Modified | Added `pyyaml`, changed `SQLAlchemy` to `SQLAlchemy>=2.0` |
| `.env.example` | Modified | Added `ENABLE_SKILLS`, `SKILLS_ALLOW_MUTATIONS`, `SKILLS_DIR`, `SKILLS_AUDIT_LOG` |
| `README.md` | Modified | Version badge 3.0, v3.0 changelog, roadmap updated |
| `README_ZH.md` | Modified | Same updates in Chinese |

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tool architecture | 2-3 unified tools (list/query/mutation) | Prevents tool explosion (Google Gemini 10-20 rule) |
| Metadata format | `skill_def.md` YAML frontmatter | Anthropic Skills spec alignment, avoids VS Code conflict |
| SQL caching | discover() caches at startup | Eliminates TOCTOU (time-of-check-time-of-use) risks |
| Write safety | 3-stage validate/preview/execute | Anthropic "verifiable intermediate outputs" pattern |
| Error handling | ToolError propagation | FastMCP ToolError bypasses `mask_error_details` |
| Audit storage | JSONL file | Minimal dependency for MVP |

### Security Model (16 items in SAFETY.md)

1. Template = Whitelist — only pre-defined SQL/Python in `skills/` is executed
2. Parameterized queries via SQLAlchemy `text()` + named parameters
3. Dual switch: `ENABLE_SKILLS` (master) + `SKILLS_ALLOW_MUTATIONS` (second)
4. Startup SQL safety validation via `is_sql_safe()` (defense-in-depth)
5. Skill name regex `^[a-z0-9][a-z0-9-]*$` prevents path traversal
6. SKILLS_DIR constrained to project root
7. Error sanitization through `ToolError` (no internal detail leaks)

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_SKILLS` | `0` | Master switch for skills extension |
| `SKILLS_ALLOW_MUTATIONS` | `0` | Enable mutation skills (requires `ENABLE_SKILLS=1`) |
| `SKILLS_DIR` | `skills/` | Skills directory path (must be under project root) |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | Audit log file path |

### Testing

- **64 new tests** across 4 files (all pass)
- **53 existing tests** unchanged (all pass)
- **117 total tests, 0 failures** — backward compatibility confirmed
- All tests use SQLite in-memory databases for speed and isolation
- Key finding: SQLAlchemy Row objects use attribute access (`.column_name`) not dict access (`["column_name"]`)

> **Design Documentation:** See [MCP_AGENTS_SKILLS_DESIGN.md](MCP_AGENTS_SKILLS_DESIGN.md) for full architecture details.

### Post-Implementation Audit (March 1, 2026)

Code review following MCP Spec §7, Anthropic, Google Gemini, and Microsoft best practices.

#### Issues Found & Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | P0 Security | `_is_query_safe_extended` leaked regex pattern in error message (`f"SHOW command not allowed for security: {pattern}"`) | Replaced with generic message: `"This SHOW command is not allowed for security reasons"` |
| 2 | P0 Security | `INFORMATION_SCHEMA` bypass: `query("SELECT * FROM INFORMATION_SCHEMA.TABLES")` could bypass `ALLOWED_TABLES` controls, exposing restricted table names | Added `information_schema` to blocked system databases pattern |
| 3 | P1 Logic | `sample()` tool used MySQL-specific backtick quoting (`\`table\``) — would fail on SQLite | Dynamic quoting: backtick for MySQL, double-quote for SQLite via `adapter.db_type` |
| 4 | P1 Logic | `get_table_summary()` bypassed adapter layer, used MySQL-only `INFORMATION_SCHEMA` SQL directly | Refactored to use `adapter.get_row_estimate()` and `adapter.get_columns()` |
| 5 | P2 Quality | `import json` inside `_truncate_result()` function body | Moved to module-level imports |
| 6 | P2 Quality | `ALLOWED_SHOW_COMMANDS` set was dead code (defined but never referenced) | Removed |
| 7 | P2 Quality | `_is_valid_identifier` had redundant `dangerous_patterns` check | Added comment noting it's defense-in-depth (kept) |
| 8 | P0 Type | Pylance reported `_project_root`/`_skills_dir`/`Field` possibly unbound in Skills conditional blocks | Moved `sys`, `Path`, `Annotated`, `Field` imports to module level; pre-initialized path variables |
| 9 | P1 Type | `DatabaseAdapter` ABC missing `_handle_error()` method — Pylance couldn't resolve calls on abstract type | Added `_handle_error()` as a concrete method in `DatabaseAdapter` (default: returns generic error string) |
| 10 | P1 Type | `skill_loader.py`: `importlib.util.spec_from_file_location()` returns `Optional[ModuleSpec]`, but `spec` and `spec.loader` used without None check | Added explicit `None` guard with clear `ImportError` message |
| 11 | P2 Type | `mutation.py`: SQLAlchemy `Row.status` attribute access unrecognized by Pylance (dynamic attribute) | Added `# type: ignore[union-attr]` annotations (3 locations) |
| 12 | P2 Type | `test_query_skills.py` / `test_mutation_skills.py`: `adapter._engine` could be `None` before `connect()` | Added `assert adapter._engine is not None` after `connect()` |
| 13 | P0 Bug | `execute_write()` fails on MySQL: `connection.begin()` conflicts with SQLAlchemy 2.0 autobegin — `SET SESSION MAX_EXECUTION_TIME` triggers autobegin, then explicit `begin()` raises `InvalidRequestError` | Replaced `engine.connect()` + `connection.begin()` with `engine.begin()` context manager (both MySQL and SQLite adapters) |
| 14 | P2 Perf | `load_mutation()` re-executes `exec_module()` on every call — disk I/O + module compilation per mutation invocation | Pre-load mutation module class in `discover()` at startup, cache in `SkillMetadata._mutation_class`; `load_mutation()` now only instantiates from cache |
| 15 | P2 Security | `validate_params()` silently ignores extra parameters not defined in schema — defense-in-depth gap | Added `unexpected = set(params) - set(schema)` check at start; raises `ValueError` listing unexpected keys |
| 16 | P3 Robustness | `AuditLogger.__init__` calls `mkdir()` without error handling — `PermissionError` crashes entire Skills initialization | Wrapped `mkdir()` in try-except `OSError`; logs warning but allows AuditLogger to construct |
| 17 | P1 Logic | `mutation.py execute()` returns `{"success": False}` on failure instead of raising exception — bypasses `run_execute()` error handling chain, causes semantic contradiction (`{"success": True, "result": {"success": False}}`) in MCP tool response, and `run_execute()` `except ToolError` path lacked audit logging | Changed `execute()` to `raise ToolError(...)` on order-not-found and optimistic lock failure; added audit logging to `run_execute()` `except ToolError` path before re-raising |
| 18 | P2 Type | `SkillMetadata._mutation_class: type \| None` — Pylance reports "Variable not allowed in type expression". Python 3.12 introduced `type` as a soft keyword for type alias statements (`type X = ...`), causing Pylance to misparse the built-in `type` in annotation context within a `@dataclass` | Added `from __future__ import annotations` (PEP 563) to `skill_loader.py` — defers all annotation evaluation to string form, bypassing the `type` soft keyword parsing conflict |

#### Noted (Not Fixed — Design Decisions)

| # | Topic | Note |
|---|-------|------|
| A | Error pattern inconsistency | Core tools return `{"success": False, "error": ...}`, Skills tools raise `ToolError`. MCP Spec §6 favors `isError: true` (which ToolError maps to), but changing core tools would break backward compatibility. |
| B | Rate limiting | MCP Spec §7 requires "Rate limit tool invocations". Not implemented — acceptable for current single-agent deployment, recommended for production SSE multi-client mode. |
| C | CTE/WITH bypass | `_is_query_safe_extended` blocks `FROM (subquery)` but not `WITH ... AS` (CTE). Low risk since `is_sql_safe()` already restricts statement types to SELECT. |
| D | Lifespan cleanup | `lifespan()` context manager doesn't call `reset_adapter()` on shutdown. Minor — Python process exit cleans up resources. |
| E | `query.sql` MySQL-only functions | `monthly-sales-report/query.sql` uses `YEAR()`/`MONTH()` — MySQL-specific, not supported by SQLite. Acceptable as an example skill for a MySQL-primary project. `skill_def.md` Notes already marks it MySQL-only. Cross-database compatibility is the skill author's responsibility. |
| F | `_extract_table_names()` ignores `schema.table` | `skill_loader.py`'s `_extract_table_names()` regex doesn't handle `schema.table` format, but this function is only used for generating the `SKILLS.md` overview document — not involved in security validation. The core security path `_extract_tables_from_sql()` in `mcp_sql_server.py` already handles `schema.table` correctly (fixed in Bug Fix 1). |
| G | Mutation `execute()` duplicate SELECT | `mutation.py`'s `execute()` re-runs the same SELECT query as `validate()`. This is intentional security design — there may be a time gap between `validate()` (preview) and `execute()` (confirm) while the user reviews. The duplicate SELECT prevents TOCTOU (Time-of-Check-Time-of-Use) race conditions, ensuring data state still meets constraints at execution time. |
| H | Mutation read-write transaction gap | `mutation.py execute()` uses `adapter.execute()` (read-only) for the SELECT check, then `adapter.execute_write()` for the UPDATE — two separate connections/transactions. A narrow TOCTOU window exists between them. Acceptable because: (1) optimistic locking `WHERE status = :expected` + `rowcount == 0` detection is the effective final safety net, (2) merging SELECT+UPDATE into a single SQL would add complexity with minimal gain in low-concurrency scenarios. |
| I | `execute_mutation_skill` double audit risk | MCP tool layer `except` block and `run_execute()` both call `_audit_logger.log()`. Analysis shows no actual double-logging: `except ToolError: raise` skips the outer log, and only non-ToolError exceptions (which can't originate from `run_execute()`'s own ToolError raise) reach the outer catch. Code is correct as-is. |
| J | `_sanitize_params()` flat-only | `audit.py`'s `_sanitize_params()` only truncates top-level `str` values >500 chars, does not recurse into nested `dict`/`list`. No impact — current skill frontmatter schema only defines atomic types (`int`/`float`/`str`/`bool`). If future skills add complex parameter types, this should be revisited. |
| K | `_coerce_type()` bool conversion | `skill_loader.py`'s `_coerce_type()` uses `bool(value)` which makes `bool("false")` return `True` (any non-empty string is truthy in Python). No current skill uses `bool` parameters. If added, should use explicit mapping (`{"true": True, "false": False}`). |

### Live Integration Test Report (March 1, 2026)

End-to-end functional verification against production MySQL database (`trade_data_analysis` on `192.168.1.113`).  
All 10 MCP tools tested via VS Code MCP Client → FastMCP 3.0.2 stdio transport.

#### Test Environment

| Item | Value |
|------|-------|
| Database | MySQL 8.x, `trade_data_analysis` |
| Production tables | 6 tables, largest `trade_data_analysis_log` (~138K rows, 57 columns, Chinese A-stock data) |
| Test tables | `orders` (5 rows), `test_users` (2 rows) — created for testing, cleaned up after |
| Skills config | `ENABLE_SKILLS=1`, `SKILLS_ALLOW_MUTATIONS=1` |
| Sample skills | `monthly-sales-report` (query), `update-order-status` (mutation) |

#### Phase 1: Core Tools — All Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 1 | `check_connection` | Connect to MySQL | ✅ `"MySQL connection successful"` |
| 2 | `list_tables` | List all tables | ✅ 7 tables returned (6 production + 1 test) with estimated row counts |
| 3 | `describe_table` | `test_users` (small table) | ✅ 2 columns (id, name), 2 rows |
| 4 | `describe_table` | `trade_data_analysis_log` (large table) | ✅ 57 columns, ~135K rows, `is_large=true` |
| 5 | `query` | `SELECT * FROM test_users` | ✅ Returns Alice, Bob |
| 6 | `query` | Aggregation: `COUNT(*)`, `COUNT(DISTINCT ...)`, `GROUP BY` on 138K rows | ✅ 138K records, 6408 stocks, 87 industries |
| 7 | `query` | `GROUP BY industry ORDER BY cnt DESC LIMIT 10` | ✅ Top 10 industries by stock count |
| 8 | `query` | **Security**: `DROP TABLE test_users` | ✅ **Blocked**: `"Only read-only queries allowed"` |
| 9 | `get_full_schema` | Full database schema dump | ✅ All 7 tables with columns, ~35KB response |

#### Phase 2: Skills Discovery — Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 10 | `list_skills` | Discover available skills | ✅ 2 skills found: `monthly-sales-report` (query/low), `update-order-status` (mutation/high) |

#### Phase 3: Query Skill — All Pass

| # | Tool | Test | Result |
|---|------|------|--------|
| 11 | `execute_query_skill` | `monthly-sales-report` (before test data) | ✅ Error correctly: `"Table or column not found"` (orders table didn't exist yet) |
| 12 | `execute_query_skill` | `monthly-sales-report` with `{year:2026, month:1}` (after creating orders) | ✅ **Success**: 5 daily rows with `order_count`, `revenue`, `avg_order_value` |
| 13 | `execute_query_skill` | `nonexistent-skill` | ✅ Error correctly: `"Skill not found"` |

#### Phase 4: Mutation Skill — Bug Found & Fixed

| # | Tool | Test | Result |
|---|------|------|--------|
| 14 | `execute_mutation_skill` | Dry-run (`confirm=false`): `{order_id:1, new_status:"confirmed"}` | ✅ Preview returned UPDATE SQL with optimistic locking |
| 15 | `execute_mutation_skill` | Execute (`confirm=true`) — **BEFORE FIX** | ❌ **FAILED**: `"Database query failed"` |
| 16 | (diagnosis) | Root cause analysis | 🔍 `InvalidRequestError: This connection has already initialized a Transaction() object via begin() or autobegin; can't call begin() here` |
| 17 | `execute_mutation_skill` | Execute (`confirm=true`) — **AFTER FIX** | ✅ **Success**: `pending` → `confirmed`, `rowcount: 1` |
| 18 | `execute_mutation_skill` | Chained transition: `confirmed` → `shipped` | ✅ **Success**: `rowcount: 1` |
| 19 | `execute_mutation_skill` | **Security**: illegal transition `shipped` → `pending` | ✅ **Blocked**: `"Transition from 'shipped' to 'pending' is not allowed. Allowed: ['delivered', 'returned']"` |

#### Bug #13: `execute_write()` SQLAlchemy autobegin conflict

**Symptom**: `execute_mutation_skill(confirm=true)` returns `"Error: Database query failed"` on MySQL.  
Dry-run (preview) works; confirm (execute) fails. Data unchanged.

**Root Cause**: In `MySQLAdapter.execute_write()`:

```python
# BEFORE (buggy)
with self._engine.connect() as connection:
    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
    # ↑ This triggers SQLAlchemy 2.0 autobegin (implicit transaction)
    
    with connection.begin():  # ← FAILS: autobegin already active
        result = connection.execute(text(sql), params)
```

SQLAlchemy 2.0 uses "autobegin" — any `execute()` call on a connection implicitly starts a transaction. The `SET SESSION MAX_EXECUTION_TIME` call activated autobegin, then the explicit `connection.begin()` raised `InvalidRequestError` because a transaction was already in progress.

**Why unit tests didn't catch it**: All 111 tests use SQLite in-memory with `StaticPool` (shared single connection), where the connection lifecycle differs. The timeout mechanism uses `set_progress_handler()` instead of `SET SESSION`, so the autobegin trigger path doesn't exist in SQLite tests.

**Fix**: Replace `engine.connect()` + `connection.begin()` with `engine.begin()`:

```python
# AFTER (fixed) — both MySQL and SQLite adapters
with self._engine.begin() as connection:  # explicit transaction from the start
    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}"))
    result = connection.execute(text(sql), params)
    # auto-commit on context exit, auto-rollback on exception
```

`engine.begin()` creates a connection with an explicit transaction from the start, avoiding the autobegin conflict. All subsequent `execute()` calls within this context operate within the same transaction.

**Verification**: After fix, mutation skill confirmed working (tests #17-19 above). 111 unit tests remain green.

#### Phase 5: Cleanup

| Action | Result |
|--------|--------|
| Drop `orders` table | ✅ Removed from production DB |
| Drop `test_users` table | ✅ Removed from production DB |
| Verify table count | ✅ 6 original tables remain |

#### Summary

| Category | Tests | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Core tools | 9 | 9 | 0 | Including security block |
| Skills discovery | 1 | 1 | 0 | |
| Query skill | 3 | 3 | 0 | Including error cases |
| Mutation skill | 6 | 5 | 1 | 1 failure → bug found → fixed → re-verified |
| **Total** | **19** | **18** | **1** | **Bug #13 found, fixed, verified** |

All 10 MCP tools verified functional. One P0 bug discovered and fixed during testing.  
111 unit tests pass after fix. Test environment cleaned up — no residual test data in production.

---

## Update (January 13, 2026) - GitHub Repository Rename

This update records a repository-level rename (no functional code changes).

- **Old repo name:** `vibe-coding-gemini-llm-execute-sql-tools`
- **New repo name:** `llm-sql-safety-executor-mcp`
- **New URL:** https://github.com/Firstmeridian/llm-sql-safety-executor-mcp

### Local Git Update

After renaming on GitHub, update your local `origin` remote to avoid relying on redirects:

```bash
git remote -v
git remote set-url origin https://github.com/Firstmeridian/llm-sql-safety-executor-mcp.git
git remote -v

# optional verification
git fetch origin --prune
```

---

## Update v2.2 (January 15, 2026) - SQLite Database Support

### Overview

Added SQLite database support while maintaining full backward compatibility with MySQL. This enables the MCP server to work with lightweight SQLite databases for development, testing, and embedded use cases.

### Architecture: Database Adapter Pattern

Introduced `db_adapter.py` implementing the Abstract Base Class (ABC) pattern:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE ADAPTER ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                          ┌─────────────────────┐                            │
│                          │  DatabaseAdapter    │ (ABC)                      │
│                          │  ─────────────────  │                            │
│                          │  + connect()        │                            │
│                          │  + execute()        │                            │
│                          │  + get_tables()     │                            │
│                          │  + get_columns()    │                            │
│                          │  + get_row_estimate()│                           │
│                          │  + check_connection()│                           │
│                          │  + get_database_name()│                          │
│                          │  + close()          │                            │
│                          │  + db_type (property)│                           │
│                          └─────────┬───────────┘                            │
│                                    │                                        │
│                    ┌───────────────┴───────────────┐                        │
│                    │                               │                        │
│           ┌────────▼────────┐             ┌───────▼────────┐                │
│           │   MySQLAdapter  │             │  SQLiteAdapter │                │
│           │  ─────────────  │             │  ────────────  │                │
│           │  - SQLAlchemy   │             │  - SQLAlchemy  │                │
│           │  - PyMySQL      │             │  - sqlite3     │                │
│           │  - QueuePool    │             │  - StaticPool  │                │
│           │  - MAX_EXEC_TIME│             │  - progress_   │                │
│           │                 │             │    handler     │                │
│           └─────────────────┘             └────────────────┘                │
│                                                                             │
│                          ┌─────────────────────┐                            │
│                          │  create_adapter()   │ (Factory)                  │
│                          │  ─────────────────  │                            │
│                          │  DB_TYPE → Adapter  │                            │
│                          └─────────────────────┘                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `db_adapter.py` | **NEW** (749 lines) | Database adapter abstraction layer |
| `sql_safety_checker.py` | Modified | Now uses adapter; removed MySQL-specific code |
| `mcp_sql_server.py` | Modified | Uses adapter methods; adds `db_type` to responses |
| `.env.example` | Modified | Added SQLite configuration section |
| `.env` | Modified | Added SQLite configuration section |
| `README.md` | Modified | v2.2 changelog, SQLite config docs |
| `README_ZH.md` | Modified | v2.2 changelog, SQLite config docs |
| `tests/conftest.py` | **NEW** (318 lines) | Pytest fixtures for SQLite/MySQL tests |
| `tests/test_db_adapter.py` | **NEW** | Unit tests for adapters |
| `tests/test_sqlite_integration.py` | **NEW** | SQLite integration tests |
| `requirements.txt` | Modified | Added `pytest` dependency |

> **Detailed Design Documentation:** See [SQLITE_ADAPTER_DESIGN.md](SQLITE_ADAPTER_DESIGN.md) for design decisions, conventions, compromises, potential issues, and implementation details.

---

## Update v2.1 (January 4, 2026) - Tool Optimization & Field Naming

### Major Changes

#### 1. `get_table_summary` Now Optional (Default: Disabled)

**Rationale:** The `describe_table()` tool already provides estimated row counts from INFORMATION_SCHEMA. The `get_table_summary()` tool with its optional `COUNT(*)` feature is only needed when exact counts are required.

**Configuration:**
```env
# Default: disabled (describe_table provides estimates)
ENABLE_TABLE_SUMMARY=0

# Enable when exact counts via COUNT(*) are needed
ENABLE_TABLE_SUMMARY=1
```

**New Parameters:**
- `exact_count` (bool, default: False): When True, runs COUNT(*) for precise count (slow on large tables)

#### 2. `describe_table` Enhanced with Row Count and Hints

**New Output Fields:**
```json
{
  "row_count": 1500,
  "row_count_approximate": true,
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
}
```

**Benefits:**
- Eliminates need for separate `get_table_summary()` call in most cases
- Provides query planning hints based on `LARGE_TABLE_THRESHOLD`

#### 3. `list_tables` Output Restructured

**Before:**
```json
{
  "success": true,
  "data": [...],
  "table_count": 2
}
```

**After:**
```json
{
  "success": true,
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [...],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null
}
```

**Field Naming Convention:**
- `returned_table_count`: Number of tables in response (after truncation)
- `total_tables`: Visible tables (after allowlist filtering, before truncation)
- `tables`: Renamed from `data` for clarity

#### 4. `get_full_schema` Output Aligned

Same field naming convention applied:
- `returned_table_count` instead of `table_count`
- `total_tables` field added
- `truncated` and `truncation_note` always present

#### 5. New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TABLE_SUMMARY` | 0 | Enable `get_table_summary()` tool |
| `LARGE_TABLE_THRESHOLD` | 1000 | Rows threshold for `is_large` flag |
| `MAX_OVERVIEW_TABLES` | 100 | Max tables in `list_tables()` |

#### 6. AutoGen Agent Prompts Updated

Removed `get_table_summary()` references from agent prompts since:
- Tool is disabled by default
- `describe_table()` now provides equivalent functionality

Updated workflow guidance:
```
- For unknown tables: list_tables() → describe_table()
- For multi-table JOINs: get_full_schema()
- Check is_large flag in describe_table response
```

### Files Changed

| File | Changes |
|------|---------|
| `mcp_sql_server.py` | Tool restructuring, field naming, new env vars |
| `.env.example` | New environment variable documentation |
| `autogen_sql_agent.py` | Updated prompts, removed get_table_summary refs |
| `test_mcp_client.py` | Validate new field structure |
| `test_bug_fixes.py` | Updated tests for new fields |

---

## Previous Update (December 29, 2025) - Bug Fixes

### Bug Fix 1: Schema.table Regex Extraction (P1)

**Problem:** `_extract_tables_from_sql()` incorrectly extracted schema name instead of table name when using `schema.table` syntax (e.g., `SELECT * FROM mydb.users` extracted "mydb" instead of "users").

**Impact:** Table allowlist validation could incorrectly block/allow queries when using schema-qualified table names.

**Root Cause:****
```python
# Old regex - captures first identifier (schema)
from_join_pattern = r'(?:FROM|JOIN)\s+`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
```

**Fix:** Updated regex to handle optional schema prefix and capture only the table name:
```python
# Fixed regex - skips optional schema., captures table name
from_join_pattern = r'(?:FROM|JOIN)\s+(?:`?[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*`?\s*\.\s*)?`?([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)`?'
```

**Test Cases Verified:**
- `SELECT * FROM mydb.users` → extracts "users" ✅
- `SELECT * FROM \`mydb\`.\`users\`` → extracts "users" ✅
- `DESCRIBE mydb.products` → extracts "products" ✅

### Bug Fix 2: sql_assistant Prompt Display for ALLOWED_TABLES=* (P2)

**Problem:** When `ALLOWED_TABLES=*` was set, the prompt displayed "UNION enabled (tables: *)" which was unclear to LLMs.

**Fix:** Added special handling to display "all tables" instead of "*":
```python
# Before
cross_table = f"UNION enabled (tables: {', '.join(sorted(ALLOWED_TABLES))})"
# Output: "UNION enabled (tables: *)"

# After
if "*" in ALLOWED_TABLES:
    tables_desc = "all tables"
else:
    tables_desc = ', '.join(sorted(ALLOWED_TABLES))
cross_table = f"UNION enabled ({tables_desc})"
# Output: "UNION enabled (all tables)"
```

### Bug Fix 3: get_full_schema Truncation Protection (P0)

**Problem:** `get_full_schema()` could return extremely large responses for databases with many tables (100+ tables with 30+ columns each could exceed 200K+ characters), causing LLM context overflow.

**Fix:** Added truncation protection with `MAX_SCHEMA_TABLES = 50`:
```python
MAX_SCHEMA_TABLES = 50  # Reasonable limit for most LLM contexts
total_tables = len(tables_data)
truncated = False

if total_tables > MAX_SCHEMA_TABLES:
    tables_data = tables_data[:MAX_SCHEMA_TABLES]
    truncated = True
    await ctx.warning(f"Schema truncated: showing {MAX_SCHEMA_TABLES}/{total_tables} tables")

# ... (build schema) ...

if truncated:
    result["truncated"] = True
    result["truncation_note"] = f"Showing {MAX_SCHEMA_TABLES}/{total_tables} tables. Use describe_table(table_name) for specific tables not shown."
```

**Size Estimates:**
| Database Size | Tables | Estimated Chars | Truncated? |
|--------------|--------|-----------------|------------|
| Small | 10 | ~9K | No |
| Medium | 50 | ~88K | At limit |
| Large | 100 | ~260K | Yes → 50 |
| Very Large | 200 | ~860K | Yes → 50 |

---

### Previous Fix: ALLOWED_TABLES=* Filtering Issue

**Problem:** When `ALLOWED_TABLES=*` was set, `list_tables()` and `get_full_schema()` returned empty results because the filter logic checked if table names were literally in the set `{"*"}`.

**Root Cause:**
```python
# Buggy code
if ALLOWED_TABLES is not None:
    data = [t for t in data if t["table_name"].lower() in ALLOWED_TABLES]
    # ALLOWED_TABLES = {"*"}, no table name equals "*", so all filtered out!
```

**Fix:** Added check to skip filtering when `"*"` is in the allowlist:
```python
# Fixed code
if ALLOWED_TABLES is not None and "*" not in ALLOWED_TABLES:
    data = [t for t in data if t["table_name"].lower() in ALLOWED_TABLES]
```

**Affected Functions:**
- `list_tables()` - Line ~552
- `get_full_schema()` - Line ~683

### Configuration Improvements & Truncation Optimization

This update relaxes default truncation limits, adds `ALLOWED_TABLES=*` support, and simplifies error messages.

#### 1. Relaxed Default Truncation Limits

| Setting | Before | After | Reason |
|---------|--------|-------|--------|
| `MAX_RESULT_ROWS` | 50 | 100 | More practical for analysis tasks |
| `MAX_RESULT_CHARS` | 8000 | 16000 | Reduces premature truncation |

#### 2. Disable Truncation Support

Set `MAX_RESULT_ROWS=0` or `MAX_RESULT_CHARS=0` to disable respective limits:

```env
# Disable all truncation (for data export scenarios)
MAX_RESULT_ROWS=0
MAX_RESULT_CHARS=0
```

#### 3. ALLOWED_TABLES=* Support

Added special value `*` to explicitly allow all tables (required for UNION with unrestricted access):

```env
# Enable UNION and allow all tables
ALLOW_UNION=1
ALLOWED_TABLES=*
```

**Behavior:**
- `ALLOWED_TABLES=` (empty): Allow all tables for normal queries, but UNION still blocked
- `ALLOWED_TABLES=*`: Explicitly allow all tables, enables UNION when `ALLOW_UNION=1`
- `ALLOWED_TABLES=t1,t2`: Only allow specified tables

#### 4. Simplified Truncation Messages

Reduced truncation note length to minimize token consumption:

| Before | After |
|--------|-------|
| `"Results truncated to 50 rows. Use 'SELECT ... LIMIT n' for precise control. Total available: 200 rows."` | `"Showing 100/200 rows. Use LIMIT clause for full control."` |

#### 5. Simplified UNION Error Message

| Before | After |
|--------|-------|
| `"UNION queries require ALLOWED_TABLES to be configured. Set ALLOWED_TABLES environment variable or use separate queries."` | `"UNION requires ALLOWED_TABLES. Set ALLOWED_TABLES=table1,table2 or ALLOWED_TABLES=* to enable."` |

#### Files Changed

| File | Change |
|------|--------|
| `mcp_sql_server.py` | Relaxed defaults, added `*` support, simplified messages |
| `.env.example` | Updated documentation and default values |

---

## Update (December 23, 2025)

### Security & Token Optimization

This update adds configurable UNION query policy, startup logging, and significant prompt optimization following OpenAI/Google best practices.

#### 1. ALLOW_UNION Configuration (P2 Security)

Added configurable UNION query handling for flexible security vs efficiency trade-off:

| Setting | Behavior | Use Case |
|---------|----------|----------|
| `ALLOW_UNION=0` (default) | Block UNION, guide LLM to multiple queries | Maximum security |
| `ALLOW_UNION=1` + `ALLOWED_TABLES` | Allow UNION with table validation | Efficiency mode |
| `ALLOW_UNION=1` without allowlist | Block UNION (requires allowlist) | Defense-in-depth |

**Configuration Example (.env):**
```env
# P2: UNION Query Policy (0=disabled/safer, 1=enabled with table allowlist)
ALLOW_UNION=0

# Required when ALLOW_UNION=1
ALLOWED_TABLES=customers,orders,products
```

#### 2. Startup Logging for Security Configuration

Added logging at module load to confirm security settings:

```python
# Log security configuration at module load
if ALLOW_UNION:
    if ALLOWED_TABLES:
        logger.info(f"UNION queries enabled with table allowlist: {sorted(ALLOWED_TABLES)}")
    else:
        logger.warning("ALLOW_UNION=1 but no ALLOWED_TABLES configured - UNION will be blocked")
else:
    logger.info("UNION queries disabled (default safe mode)")
```

#### 3. Prompt Token Optimization (69% Reduction)

Significantly reduced `sql_assistant` prompt size following OpenAI/Google best practices:

> **Google**: "Token limits: function descriptions and parameters count toward input token limits"
> **OpenAI**: "If you run into token limits, we suggest limiting the number of functions or the length of the descriptions"

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Characters | 1,224 | 376 | -69% |
| Tokens (approx) | ~306 | ~94 | -69% |

**Before (verbose):**
```python
"""Database query assistant with READ-ONLY access.

TOOLS:
1. query(sql) - PRIMARY. Execute SELECT, SHOW, DESCRIBE, EXPLAIN.
2. list_tables() - List available tables (use if structure unknown)
3. describe_table(name) - Get single table columns
4. get_full_schema() - Get ALL tables and columns in ONE call (recommended first)
5. get_table_summary(name) - Get table statistics without raw data
6. sample(table, limit) - Preview table data

QUERY GUIDELINES:
- Use JOINs for combining related tables (INNER JOIN, LEFT JOIN)
- Use aggregation (COUNT, SUM, GROUP BY) instead of fetching all rows
- Always include LIMIT for large result sets

UNION QUERIES:
- UNION is enabled for combining results from multiple tables
- All tables in UNION must be in allowlist: customers, orders, products
- Example: SELECT id, name FROM products UNION SELECT id, title FROM categories

WORKFLOW (Token Optimized):
- Start with: get_full_schema() to understand database structure
- For large tables: get_table_summary() first, then query with LIMIT
- Prefer aggregation over raw data retrieval

Always show executed SQL in response. Format results as readable tables."""
```

**After (optimized):**
```python
"""READ-ONLY SQL assistant. Tools: query (primary), get_full_schema, list_tables, describe_table, get_table_summary, sample.

Workflow: get_full_schema() first → query with LIMIT for large tables.
Guidelines: Use aggregation (COUNT/GROUP BY) over raw data. UNION enabled (tables: customers, orders, products). Use JOINs for related data.
Always show SQL in response."""
```

**Key optimization principles applied:**
- Remove redundant tool descriptions (already in docstrings)
- Combine related guidelines into single sentences
- Remove examples (LLM can infer from context)
- Dynamic UNION guidance based on configuration

#### Files Changed

| File | Change |
|------|--------|
| `mcp_sql_server.py` | Added ALLOW_UNION config, startup logging, optimized prompt |
| `.env.example` | Added ALLOW_UNION=0 documentation |

#### References

- [OpenAI Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling)
- [Google Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [FastMCP Prompts Documentation](https://github.com/jlowin/fastmcp)

---

## Update (December 15, 2025)

### Extended SQL Statement Support

Added support for additional read-only SQL statement types beyond SELECT:

| Statement | Purpose | Example |
|-----------|---------|---------|
| `SELECT` | Data retrieval | `SELECT * FROM users` |
| `SHOW` | Database metadata | `SHOW TABLES`, `SHOW COLUMNS FROM users` |
| `DESCRIBE` | Table structure | `DESCRIBE users` |
| `EXPLAIN` | Query plan analysis | `EXPLAIN SELECT * FROM users` |

**Files Changed:**
- `sql_safety_checker.py`: Added `SAFE_SQL_TYPES` constant and updated `is_sql_safe()` function
- `mcp_sql_server.py`: Updated instructions, tool descriptions, and prompts
- `README.md`: Updated documentation to reflect new capabilities

**Server Instructions Updated:**
```python
instructions="""You are a database query assistant with READ-ONLY access.
Use the query tool for most operations. Safe statements: SELECT, SHOW, DESCRIBE, EXPLAIN.
Use list_tables first if you don't know the database structure.
If first time querying or unsure about columns: list_tables() -> describe_table() -> query()
If you already know the table structure: query directly"""
```

---

## Changes Summary (v2.0 vs. v1.0)

### 1. Code Reduction
- **Before:** ~460 lines
- **After:** ~280 lines
- **Reduction:** ~40% less code while maintaining functionality

### 2. Tool Consolidation

| Old Tools | New Tools | Reason |
|-----------|-----------|--------|
| `validate_sql_query` | *(removed)* | Validation is now automatic inside `query()` |
| `execute_safe_sql` | `query` | Renamed for clarity and brevity |
| `check_database_connection` | `check_connection` | Renamed, kept for backward compatibility |
| `get_table_schema` | `describe_table` | Matches SQL `DESCRIBE` command |
| `get_sample_data` | `sample` | Shorter, more intuitive name |
| `get_server_info` | *(removed)* | Rarely used, low value |
| *(new)* | `list_tables` | Essential for database discovery |
| *(new - Dec 23)* | `get_full_schema` | Token optimization: Get all tables/columns in ONE call |
| *(new - Dec 23)* | `get_table_summary` | Token optimization: Get table stats without raw data |

**Summary:**
- Original: 6 tools → Now: 7 tools
- 2 removed (`validate_sql_query`, `get_server_info`)
- 3 added (`list_tables`, `get_full_schema`, `get_table_summary`)
- 4 renamed

### Tool Migration Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOOL MIGRATION MAP                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   OLD TOOLS (6)                              NEW TOOLS (7)                  │
│   ═══════════                                ════════════                   │
│                                                                             │
│   ┌──────────────────────┐                                                  │
│   │  validate_sql_query  │ ──────┐                                          │
│   └──────────────────────┘       │  (merged)   ┌─────────────┐              │
│                                  ├───────────► │    query    │              │
│   ┌──────────────────────┐       │             └─────────────┘              │
│   │   execute_safe_sql   │ ──────┘                                          │
│   └──────────────────────┘                                                  │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │check_database_connection│ ─────────► │  check_connection │               │
│   └──────────────────────┘               └──────────────────┘               │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │   get_table_schema   │ ─────────────►│  describe_table  │               │
│   └──────────────────────┘               └──────────────────┘               │
│                                                                             │
│   ┌──────────────────────┐   (renamed)   ┌──────────────────┐               │
│   │    get_sample_data   │ ─────────────►│      sample      │ [OPTIONAL]    │
│   └──────────────────────┘               └──────────────────┘               │
│                                          (requires ENABLE_SCHEMA_TOOLS=1)   │
│                                                                             │
│   ┌──────────────────────┐                                                  │
│   │    get_server_info   │ ─────────────► ✗ REMOVED                         │
│   └──────────────────────┘                                                  │
│                                                                             │
│                              (new)       ┌──────────────────┐               │
│                          ★ ─────────────►│   list_tables    │               │
│                                          └──────────────────┘               │
│                                                                             │
│                          ★ (new Dec 23)  ┌──────────────────┐               │
│                            ─────────────►│  get_full_schema │               │
│                                          └──────────────────┘               │
│                                                                             │
│                          ★ (new Dec 23)  ┌──────────────────┐               │
│                            ─────────────►│ get_table_summary│               │
│                                          └──────────────────┘               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Renamed (1:1 mapping)
  ──┬──────►  Merged (N:1 mapping)  
  ✗ REMOVED   Tool no longer exists
  ★           Newly added tool
```

### 3. Tool Count Optimization
- **Before:** 6 tools called per simple query
- **After:** 1-2 tools for most queries

---

## Detailed Changes (v2.0)

### A. Added Lifespan Management

```python
@asynccontextmanager
async def lifespan(mcp_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan context manager."""
    logger.info("SQL Safety Checker MCP Server starting...")
    yield {"initialized": True}
    logger.info("SQL Safety Checker MCP Server shutting down...")
```

**Reason:** FastMCP best practice for managing server lifecycle and resources (e.g., database connection pools).

### B. Added ToolAnnotations

```python
@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute SQL Query",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
```

**Reason:** Provides metadata to LLM clients about tool behavior:
- `readOnlyHint`: Indicates the tool doesn't modify data
- `destructiveHint`: Indicates the tool doesn't delete data
- `idempotentHint`: Indicates repeated calls have the same effect

### C. Added Context Injection

```python
async def query(sql: str, ctx: Context) -> dict[str, Any]:
    await ctx.info(f"Executing query: {sql}")
    # ...
    await ctx.warning(f"Rejected unsafe query: {sql}")
```

**Reason:** 
- Structured logging through MCP protocol
- Client can receive real-time progress updates
- Better debugging and monitoring capabilities

### D. Improved Server Instructions (Updated December 2025)

The server instructions were optimized following prompt engineering best practices to reduce LLM's "exploratory behavior" (making unnecessary tool calls).

**Original Instructions:**
```python
instructions="""You are a database query assistant with READ-ONLY access.
Use the query tool for most operations. Only SELECT statements are allowed.
Use list_tables first if you don't know the database structure."""
```

**Optimized Instructions (Updated December 15, 2025):**
```python
instructions="""Database query assistant with READ-ONLY access.

Tools: query (primary), list_tables, describe_table, check_connection

Workflow:
- Known table structure: query directly
- Unknown structure: list_tables first, then query

Safe statements: SELECT, SHOW, DESCRIBE, EXPLAIN."""
```

**Design Rationale:**
- **Concise**: Reduced token count while preserving all essential information
- **Flexible**: Allows LLM to choose exploration when needed (per MCP design philosophy)
- **Clear priority**: `query (primary)` indicates main tool without being restrictive
- **Workflow guidance**: Provides both paths (known/unknown structure) without forcing either
- **Aligned with MCP spec**: Tools are "model-controlled" - LLM decides based on context

See [PROMPT_ENGINEERING_BEST_PRACTICES.md](PROMPT_ENGINEERING_BEST_PRACTICES.md) for detailed guidelines.

### E. Added SQL Injection Prevention

```python
def _is_valid_identifier(name: str) -> bool:
    """Validate table/column name to prevent SQL injection."""
    return bool(re.match(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff]*$', name))
```

**Reason:** Prevents SQL injection through table names while supporting Chinese characters.

### F. Conditional Tool Registration

```python
SCHEMA_TOOLS_ENABLED = os.getenv("ENABLE_SCHEMA_TOOLS", "1") == "1"

if SCHEMA_TOOLS_ENABLED:
    @mcp.tool(...)
    async def sample(...):
        ...
```

**Reason:** Allows disabling optional tools via environment variables for production deployments.

---

## Tool Usage Guide (After Refactoring, v2.0)

### Primary Workflow
```
query("SELECT * FROM users LIMIT 10")  # Direct query - most common
```

### Discovery Workflow
```
list_tables()                          # Step 1: Find tables
describe_table("users")                # Step 2: Understand structure
query("SELECT name FROM users")        # Step 3: Execute query
```

### Utility Tools
```
check_connection()                     # Verify database connection
sample("users", limit=5)               # Preview table data
```

---

## Best Practices Applied

1. **Single Responsibility:** Each tool does one thing well
2. **Clear Naming:** Tool names match their purpose (e.g., `describe_table` ≈ SQL `DESCRIBE`)
3. **Consistent Return Format:** All tools return `{"success": bool, "data": ..., "error": ...}`
4. **Proper Async:** All tools are async with proper Context usage
5. **Defensive Programming:** Input validation, SQL injection prevention
6. **Graceful Degradation:** Clear error messages with context

---

## Backward Compatibility Notes

- `check_connection` (previously `check_database_connection`) was kept for compatibility
- Old tool names are no longer available - clients need to update their calls
- The functionality remains the same, only the interface has improved

---

## Files Modified (After Refactoring, v2.0)

| File | Change Type |
|------|-------------|
| `mcp_sql_server.py` | Complete rewrite |
| `test_mcp_client.py` | Updated tool names to match new API |
| `test_mcp_functions.py` | Removed mcp_sql_server imports, use raw SQL |
| `REFACTORING_LOG.md` | Created (this file) |

### test_mcp_client.py Changes

Updated all tool calls to use new names:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    test_mcp_client.py TOOL CALL UPDATES                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   OLD TOOL CALLS                             NEW TOOL CALLS                 │
│   ══════════════                             ══════════════                 │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │ check_database_connection│ ─────────────►│    check_connection      │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │    get_table_schema      │ ─────────────►│    describe_table        │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │     get_sample_data      │ ─────────────►│        sample            │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐                                              │
│   │    validate_sql_query    │ ─────────────► ✗ REMOVED (merged into query) │
│   └──────────────────────────┘                                              │
│                                                                             │
│   ┌──────────────────────────┐               ┌──────────────────────────┐   │
│   │     execute_safe_sql     │ ─────────────►│        query             │   │
│   └──────────────────────────┘   (renamed)   └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────┐                                              │
│   │     get_server_info      │ ─────────────► ✗ REMOVED (low value)         │
│   └──────────────────────────┘                                              │
│                                                                             │
│                                  (new)       ┌──────────────────────────┐   │
│                              ★ ─────────────►│      list_tables         │   │
│                                              └──────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  REASON: Align test script with refactored mcp_sql_server.py API            │
│  IMPACT: Test logic unchanged - only tool names updated                     │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Tool name updated (1:1 mapping)
  ✗ REMOVED   Test case removed (tool no longer exists)
  ★           New test case added
```

### test_mcp_functions.py Changes

Removed dependency on `mcp_sql_server.py`, now uses raw SQL for schema tests:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   test_mcp_functions.py IMPORT UPDATES                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   BEFORE                                     AFTER                          │
│   ══════                                     ═════                          │
│                                                                             │
│   ┌──────────────────────────────────┐                                      │
│   │ from mcp_sql_server import       │                                      │
│   │     get_sample_data,             │ ─────────────► ✗ REMOVED             │
│   │     get_table_schema             │                                      │
│   └──────────────────────────────────┘                                      │
│                                                                             │
│   ┌──────────────────────────────────┐       ┌──────────────────────────┐   │
│   │ get_table_schema(table_name)     │ ─────►│ execute_safe_sql(        │   │
│   └──────────────────────────────────┘       │   "SELECT ... FROM       │   │
│                                              │   INFORMATION_SCHEMA..." │   │
│                                              │ )                        │   │
│                                              └──────────────────────────┘   │
│                                                                             │
│   ┌──────────────────────────────────┐       ┌──────────────────────────┐   │
│   │ get_sample_data(table, limit)    │ ─────►│ execute_safe_sql(        │   │
│   └──────────────────────────────────┘       │   "SELECT * FROM table   │   │
│                                              │    LIMIT n"              │   │
│                                              │ )                        │   │
│                                              └──────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  REASON: mcp_sql_server.py no longer exports these functions after refactor │
│  IMPACT: Test logic unchanged - only data retrieval method changed          │
│  BENEFIT: test_mcp_functions.py now only depends on sql_safety_checker.py   │
└─────────────────────────────────────────────────────────────────────────────┘

Legend:
  ─────────►  Implementation changed
  ✗ REMOVED   Import removed
```

---

## Why This Refactoring Follows Best Practices (v2.0)

### 1. Tool Design Simplification

| Aspect | Before | After | Why Better |
|--------|--------|-------|------------|
| Query execution | `validate_sql_query` + `execute_safe_sql` (2 calls) | `query()` with automatic validation (1 call) | MCP best practice: fewer tools = easier for LLM to choose correctly |
| Tool count | 6 tools | 5 tools with clearer responsibilities | Reduces cognitive load for LLM clients |

### 2. ToolAnnotations Usage

```python
@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,      # Tells LLM this is a read-only operation
        destructiveHint=False,  # Tells LLM this is safe
        idempotentHint=True,    # Tells LLM this can be retried safely
    )
)
```

These annotations help LLM clients understand tool behavior without reading documentation, leading to better tool selection.

### 3. Async + Context Pattern

```python
# Before (synchronous, basic logging)
def execute_safe_sql(sql_query: str) -> Dict[str, Any]:
    logger.info(...)

# After (async, structured logging via Context)
async def query(sql: str, ctx: Context) -> dict[str, Any]:
    await ctx.info(f"Executing query: {sql}")
```

Using `Context` is the FastMCP recommended approach:
- Provides structured logging through MCP protocol
- Enables real-time progress reporting to clients
- Better observability and debugging

### 4. Lifespan Management

```python
@asynccontextmanager
async def lifespan(mcp_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    # Initialize resources on startup
    yield {"initialized": True}
    # Cleanup resources on shutdown
```

Proper resource lifecycle management:
- Prepares for future connection pooling
- Follows Python async best practices
- Enables graceful shutdown

### 5. Enhanced SQL Injection Protection

```python
def _is_valid_identifier(name: str) -> bool:
    """Validate table/column name to prevent SQL injection."""
    return bool(re.match(r'^[\w\u4e00-\u9fff][\w\u4e00-\u9fff]*$', name))
```

New version explicitly validates dynamic table names, adding defense-in-depth security.

### 6. Simplified Prompts

| Before | After |
|--------|-------|
| Verbose `system_orchestration` prompt | Clean `sql_assistant` prompt |
| Complex `generate_select_sql` prompt | Removed (unnecessary) |

Simpler prompts are easier to maintain and less likely to confuse LLM clients.

### 7. Code Quality Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Lines of code | ~460 | ~280 | -40% |
| Cognitive complexity | High | Low | Easier to maintain |
| Test surface area | Large | Small | Easier to test |
| Type hints | Partial | Complete | Better IDE support |


