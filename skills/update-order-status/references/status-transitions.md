# Status Transition Rules

## Allowed Transitions

| From        | Allowed To                       |
|-------------|----------------------------------|
| pending     | confirmed, cancelled             |
| confirmed   | shipped, cancelled               |
| shipped     | delivered, returned              |
| delivered   | returned                         |
| cancelled   | (terminal state)                 |
| returned    | (terminal state)                 |

## Rules

1. **Terminal states** (`cancelled`, `returned`) cannot transition further.
2. **No backward transitions** — e.g., `shipped` → `confirmed` is not allowed.
3. **Optimistic locking** — The UPDATE uses `WHERE status = :expected_status`
   to prevent concurrent conflicting updates. If `rowcount == 0`, the status
   has already changed (possibly by another agent or user).
4. **Cancelled** can be reached from `pending` or `confirmed` only.
5. **Returned** requires the order to have been `shipped` or `delivered`.
