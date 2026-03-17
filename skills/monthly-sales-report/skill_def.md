---
name: monthly-sales-report
version: "1.0"
description: >
  Generate a monthly sales summary report including daily revenue,
  order count, and average order value for a specified month.
triggers:
  - monthly sales
  - revenue report
  - sales summary
  - monthly revenue
type: query
source: query.sql
risk: low
params:
  year: {type: int, required: true, description: "Year (e.g. 2026)"}
  month: {type: int, required: true, min: 1, max: 12, description: "Month (1-12)"}
category: reporting
---

## Usage

```
execute_query_skill("monthly-sales-report", {"year": 2026, "month": 1})
```

## Output Format

Returns daily summary rows: date, order_count, revenue, avg_order_value

## Notes

- Data is sorted by date in ascending order
- revenue and avg_order_value are in the database's native currency unit
- This query uses MySQL functions (YEAR, MONTH). For SQLite, use a
  different skill or modify the SQL template accordingly.
