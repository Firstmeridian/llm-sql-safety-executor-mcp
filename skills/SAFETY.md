# Skills Extension — Security Governance

This document defines the security policies and constraints for the
Skills extension layer. All skill authors and code reviewers should
read this before creating or approving skills.

## 1. Template/Script as Whitelist

Only execution files explicitly declared via the `source` field in
`skill_def.md` are loaded and executed. There is no free-form SQL input
path — the skill template IS the whitelist. The `source` filename is
validated by `_validate_source_filename()` for path traversal prevention,
hidden file rejection, safe character set, and suffix enforcement
(query → `.sql`, mutation → `.py`).

## 2. Parameterized Queries

All parameters are bound via SQLAlchemy `text()` + parameter dict
(`connection.execute(text(sql), params)`). Direct string interpolation
is **never** used. This prevents SQL injection by design.

## 3. Dry-Run Default

`confirm=False` is the default for mutation skills. Agents must preview
the operation before confirming execution with `confirm=True`.

## 4. Dual-Layer Switches

- `ENABLE_SKILLS` — Master switch. When `0` (default), no skills tools
  are registered and the entire extension is invisible.
- `SKILLS_ALLOW_MUTATIONS` — Second switch. When `0` (default), only
  read-only query skills are available; `execute_mutation_skill` is not
  registered as an MCP tool.

## 5. Timeout Protection

Skills inherit `QUERY_TIMEOUT_SECONDS` from `db_adapter.py`. Query
skills use the existing read timeout. Mutation skills use the same
timeout mechanism through `execute_write()`.

## 6. Idempotency

Mutation authors should prefer idempotent write patterns:
- `INSERT OR IGNORE` / `ON DUPLICATE KEY UPDATE`
- Optimistic locking (`WHERE status = :expected`)
- Conditional updates (`WHERE updated_at = :expected_ts`)

This prevents duplicate effects when agents retry operations.

## 7. Script Trust Boundary

Files under `skills/` are in the **same trust boundary** as source code.
Changes must go through code review. `skill_loader.py` only loads from
a fixed directory path — `..` traversal and dynamic registration are
rejected. In production, consider making the skills directory read-only.

## 8. Least-Privilege Deployment

Production recommendations:
- Use a dedicated database account with INSERT/UPDATE permissions only
  on tables that skills actually need
- For SQLite: use a separate database file for writes if possible
- Grant only the minimum permissions required by each skill's SQL

## 9. Confirmation Token

Currently not implemented. Security relies on MCP Client's
`destructiveHint` confirmation UI. If the service is exposed to
untrusted callers in the future, add a server-side confirmation token:
`hash(skill_name + params + timestamp)` with expiration.

## 10. Audit Log

All mutation operations are logged to JSONL via `audit.py`:
- **who**: `ctx.client_id` or `AGENT_ID` env var (fallback: "unknown")
- **what**: skill_name, params, mode (preview/execute)
- **when**: ISO 8601 timestamp
- **result**: success/failure and details

Log path: `SKILLS_AUDIT_LOG` env var (default: `skills/_audit.jsonl`).

## 11. mutation.py Execution Constraints

`MutationBase.execute()` should only call `self.adapter.execute_write()`.
Direct file I/O, network requests, or subprocess calls are prohibited.
Code reviewers must verify that `mutation.py` uses only the base class
API (`self.adapter.execute()`, `self.adapter.execute_write()`).

## 12. Error Sanitization

`MutationBase.run_execute()` catches exceptions and sanitizes them via
`adapter._handle_error()` before raising `ToolError`. This prevents
leaking connection strings, table schemas, or internal details to the
LLM agent.

## 13. Rate Limiting

Currently relies on implicit rate limiting from the MCP transport layer
(stdio/SSE). If the service is exposed via HTTP or to untrusted callers,
add per-skill or global rate limiting (per MCP Spec §7).

## 14. ALLOWED_TABLES Interaction

Skill SQL templates **bypass** runtime `ALLOWED_TABLES` checks. Security
comes from code review (template = whitelist, same trust boundary as
source code). `generate_skills_md()` automatically extracts and lists
table names used by each skill in `SKILLS.md` for reviewer audit.

## 15. SKILLS_DIR Path Constraint

`SKILLS_DIR` is configurable via environment variable, but `discover()`
validates that the resolved absolute path is within the project root
(`resolved_path` starts with `project_root`). This prevents `.env` file
poisoning that could inject malicious `mutation.py` from external paths.

## 16. Read/Write Method Convention

The separation between `execute()` (read) and `execute_write()` (write)
is **conventional**, not enforced at runtime. Security comes from:
- Calling convention: `execute_query_skill` → `execute()`,
  `execute_mutation_skill` → `execute_write()`
- Code review of skill implementations
- SQLAlchemy 2.0 implicit transactions: `execute()` path has no
  `commit()`, so accidental write SQL won't persist (auto-rollback)
