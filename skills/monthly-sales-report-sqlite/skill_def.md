---
# Stable public identifier; it must match this Skill directory name.
name: monthly-sales-report-sqlite
# Skill implementation version, independent from the server release version.
version: "1.0"
# Short catalog description shown to Agents and operators.
description: >
  Generate a SQLite monthly sales summary report including daily revenue,
  order count, and average order value for a specified month.
# Natural-language discovery hints; they do not grant execution permission.
triggers:
  - monthly sales
  - revenue report
  - sales summary
  - monthly revenue
  - sqlite monthly sales
# Execution kind: query Skills use a reviewed SQL template and never write.
type: query
# Execution file relative to this directory; paths and suffixes are validated.
source: query.sql
# Review classification shown in discovery metadata.
risk: low
# Repeating the same query does not change database state.
idempotent: true
# Compatible database types. This is separate from connection alias scope.
databases: [sqlite]
# Optional deployment scope (aliases, not DB types or permissions). Omit it to
# let callers choose any otherwise-authorized compatible connection.
# connection_ids: [analytics_demo_sqlite]
# Operational tags used by SKILLS_EXCLUDE_PROFILES and catalog filtering.
profiles: [demo]
# Strict input schema; undeclared params and invalid values are rejected.
params:
  # Calendar year used by the reviewed SQL template.
  year:
    # Coerce and validate the value as an integer.
    type: int
    # The caller must supply this parameter.
    required: true
    # Human-readable parameter guidance shown in Skill metadata.
    description: "Year (e.g. 2026)"
  # Calendar month used by the reviewed SQL template.
  month:
    # Coerce and validate the value as an integer.
    type: int
    # The caller must supply this parameter.
    required: true
    # Inclusive lower bound.
    min: 1
    # Inclusive upper bound.
    max: 12
    # Human-readable parameter guidance shown in Skill metadata.
    description: "Month (1-12)"
# Catalog grouping only; it is not an authorization boundary.
category: reporting
# Related catalog entries for navigation; this does not invoke them.
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
