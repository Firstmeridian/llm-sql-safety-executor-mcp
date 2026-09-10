---
# Stable public identifier; it must match this Skill directory name.
name: update-order-status
# Skill implementation version, independent from the server release version.
version: "1.0"
# Short catalog description shown to Agents and operators.
description: >
  Safely update an order's status with state machine constraints
  to prevent illegal transitions.
# Natural-language discovery hints; they do not grant execution permission.
triggers:
  - update order status
  - ship order
  - confirm order
  - cancel order
  - deliver order
# Execution kind: mutation Skills may write only through reviewed Python code.
type: mutation
# Execution file relative to this directory; paths and suffixes are validated.
source: mutation.py
# Review classification shown in discovery metadata.
risk: medium
# The host must explicitly confirm after preview; this flag alone does not
# prove that a human approved the operation.
requires_confirmation: true
# Reusing the same request is not promised to return the same outcome.
idempotent: false
# Compatible database types. Alias/type conflicts fail closed at runtime.
databases: [mysql, sqlite]
# Optional deployment scope. Prefer semantic aliases; mysql/sqlite are legal
# but easy to confuse with database types. Multiple aliases support reuse, but
# their order has no routing or failover meaning.
# connection_ids: [orders_us, orders_eu]
# Operational tags used by SKILLS_EXCLUDE_PROFILES and catalog filtering.
profiles: [demo]
# Tables required for readiness checks and documentation; database grants and
# server allowlists remain authoritative.
tables: [orders]
# Strict input schema; undeclared params and invalid values are rejected.
params:
  # Primary key of the order whose status may change.
  order_id:
    # Coerce and validate the value as an integer.
    type: int
    # The caller must supply this parameter.
    required: true
    # Human-readable parameter guidance shown in Skill metadata.
    description: "Order ID to update"
  # Requested target status; the mutation implementation also validates the
  # current-to-target state transition.
  new_status:
    # Coerce and validate the value as a string.
    type: str
    # The caller must supply this parameter.
    required: true
    # Closed set accepted before the state-machine check.
    enum: [pending, confirmed, shipped, delivered, cancelled, returned]
    # Human-readable parameter guidance shown in Skill metadata.
    description: "Target status"
# Catalog grouping only; it is not an authorization boundary.
category: order-management
# Related catalog entries for navigation; this does not invoke them.
related_skills:
  - monthly-sales-report
  - monthly-sales-report-sqlite
---

## Workflow

1. Call with `confirm=false` → returns current status, preview, and `preview_token`
2. Review the preview result
3. Call with `confirm=true` and the returned `preview_token` → atomically consumes the token and executes only if the previewed status still matches

If the preview lookup fails or the transition becomes invalid during preview,
the call returns `success=false` and no token. Direct unbound `execute()` calls
are rejected; writes must use the preview-token binding path.

## Status Transition Rules

See [status-transitions.md](references/status-transitions.md)

## Safety Mechanisms

- One-time token: replay and concurrent reuse fail closed before the write
- Preview-state binding: `expected_status` is captured during preview
- Optimistic locking: `WHERE status = expected_status`
- Transaction: BEGIN → UPDATE → require exactly one affected row before COMMIT;
  zero/multiple rows roll back, while an unacknowledged COMMIT is `unknown`
- Audit log: preview/execute paths attempt best-effort JSONL logging; normal tool results report `audit_logged`
