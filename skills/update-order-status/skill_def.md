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

1. Call with `confirm=false` → returns current status and preview
2. Review the preview result
3. Call with `confirm=true` → executes the update

## Status Transition Rules

See [status-transitions.md](references/status-transitions.md)

## Safety Mechanisms

- Optimistic locking: `WHERE status = expected_status`
- Transaction: BEGIN → UPDATE → verify rowcount → COMMIT/ROLLBACK
- Audit log: every operation is automatically recorded
