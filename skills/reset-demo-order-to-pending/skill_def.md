---
# Stable public identifier; it must match this Skill directory name.
name: reset-demo-order-to-pending
# Skill implementation version, independent from the server release version.
version: "1.0"
# Short catalog description shown to Agents and operators.
description: >
  Reset one demo order from an explicitly expected non-pending status to
  pending on MySQL or SQLite.
# Natural-language discovery hints; they do not grant execution permission.
triggers:
  - reset demo order to pending
  - restore demo order status
# Execution kind: mutation Skills may write only through reviewed Python code.
type: mutation
# Execution file relative to this directory; paths and suffixes are validated.
source: mutation.py
# Review classification shown in discovery metadata.
risk: medium
# The host must explicitly confirm after preview; this flag alone does not
# prove that a human approved the operation.
requires_confirmation: true
# A replay is rejected and an already-pending order is not reported as another
# successful reset, so callers must not assume idempotent response semantics.
idempotent: false
# The parameterized optimistic-lock SQL is shared by MySQL and SQLite.
databases: [mysql, sqlite]
# Optional deployment scope. Prefer dedicated demo/test connection aliases;
# omission preserves portability but does not grant access to any connection.
# connection_ids: [orders_demo_mysql, orders_demo_sqlite]
# Operational tags used by SKILLS_EXCLUDE_PROFILES and catalog filtering.
profiles: [demo]
# Tables required for readiness checks and documentation; database grants and
# server allowlists remain authoritative. orders.id must be PRIMARY KEY/UNIQUE.
tables: [orders]
# Strict input schema; undeclared params and invalid values are rejected.
params:
  # Identifier of the demo order to restore to the baseline pending state.
  order_id:
    type: int
    required: true
    min: 1
    description: "Demo order ID to reset"
  # Makes the reset also assert the state produced by the preceding live test.
  # The target remains fixed to pending in reviewed Python code.
  expected_status:
    type: str
    required: true
    enum: [confirmed, shipped, delivered, cancelled, returned]
    description: "Non-pending status expected before reset"
# Catalog grouping only; it is not an authorization boundary.
category: test-operations
# Related catalog entries for navigation; this does not invoke them.
related_skills:
  - update-order-status
---

## Purpose and workflow

This is a demo/test compensating mutation, not a production order-reopening
operation and not a transactional rollback. It lets an MCP live test assert the
state created by a preceding mutation and then restore the reusable fixture:

1. Call with `confirm=false`, `order_id`, and the exact non-pending
   `expected_status` produced by the test.
2. Review the order id, expected/current state, fixed `pending` target,
   resolved connection id, and expiry.
3. Call with `confirm=true`, the same params and connection id, and the returned
   token. The write succeeds only while the row still has the previewed state.

## Safety boundaries

- The target is fixed in reviewed code to `pending`; callers cannot choose an
  arbitrary target state.
- The required `expected_status` both checks the preceding test result and is
  bound into the token and optimistic-lock predicate.
- The write requires exactly one affected row inside the transaction before
  COMMIT. Zero or multiple rows roll back; COMMIT acknowledgement failure is
  reported as `unknown` and is never automatically retried.
- `orders.id` must be `PRIMARY KEY` or `UNIQUE`. The portable SQL relies on that
  database constraint; its read-side cardinality check is diagnostic defense,
  not a substitute for schema-enforced uniqueness.
- This Skill intentionally creates `pending -> X -> pending` cycles. Run it
  only on dedicated demo/test data, avoid overlapping previews for the same
  order, and prefer a fresh stdio server process per live-test scenario.
- A successful reset is a second committed mutation. It cannot atomically undo
  an earlier MCP call, and cleanup can still fail after the first write.
- Direct unbound `execute()` calls fail closed.
- `databases` and optional `connection_ids` restrict compatibility/routing but
  never grant write access; all server mutation policy layers still apply.
