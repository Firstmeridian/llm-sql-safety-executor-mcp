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

## Demo Fixture Restoration

Use this only when the user asks to restore dedicated demo/test data. For
example, restore `delivered` to `shipped` on the same connection:

1. `sample-reset-order-to-pending`: `delivered` → `pending`
2. `sample-update-order-status`: `pending` → `confirmed`
3. `sample-update-order-status`: `confirmed` → `shipped`

Each step is a separately committed mutation with its own preview and approval.
The sequence is not atomic: cancellation or failure leaves earlier commits in
place. Stop on failure or unknown outcome, reconcile the current state, and do
not retry automatically. This is not a production reopen or rollback.
