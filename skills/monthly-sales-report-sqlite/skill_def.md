---
name: monthly-sales-report-sqlite
version: "1.0"
description: >
  Generate a SQLite monthly sales summary report including daily revenue,
  order count, and average order value for a specified month.
triggers:
  - monthly sales
  - revenue report
  - sales summary
  - monthly revenue
  - sqlite monthly sales
type: query
source: query.sql
risk: low
idempotent: true
databases: [sqlite]
profiles: [demo]
params:
  year: {type: int, required: true, description: "Year (e.g. 2026)"}
  month: {type: int, required: true, min: 1, max: 12, description: "Month (1-12)"}
category: reporting
related_skills:
  - monthly-sales-report
---

## Usage

```
execute_query_skill("monthly-sales-report-sqlite", {"year": 2026, "month": 1})
```

## Output Format

Returns daily summary rows: date, order_count, revenue, avg_order_value

## Notes

- Data is sorted by date in ascending order
- revenue and avg_order_value use the SQLite demo schema's `orders.total_amount`
  column
- This query is intended for SQLite databases with ISO-8601 text timestamps in
  `orders.order_date`
- For MySQL, use `monthly-sales-report`