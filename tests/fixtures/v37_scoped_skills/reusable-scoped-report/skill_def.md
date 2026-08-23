---
name: reusable-scoped-report
type: query
source: query.sql
risk: low
description: v3.7 reusable connection-scope integration fixture
databases: [sqlite]
connection_ids: [analytics, mysql_target, missing_target]
tables: [items]
params: {}
---

Integration fixture for parser, discovery, availability, and runtime scope.
