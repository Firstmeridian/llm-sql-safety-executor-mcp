---
name: update-order-status
version: "1.0"
description: >
  Safely update an order's status with state machine constraints
  to prevent illegal transitions.
triggers:
  - update order status
  - ship order
  - confirm order
  - cancel order
  - deliver order
type: mutation
source: mutation.py
risk: medium
requires_confirmation: true
idempotent: false
profiles: [demo]
tables: [orders]
params:
  order_id: {type: int, required: true, description: "Order ID to update"}
  new_status: {type: str, required: true, enum: [pending, confirmed, shipped, delivered, cancelled, returned], description: "Target status"}
category: order-management
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
- Transaction: BEGIN → UPDATE → verify rowcount → COMMIT/ROLLBACK
- Audit log: preview/execute paths attempt best-effort JSONL logging; normal tool results report `audit_logged`
