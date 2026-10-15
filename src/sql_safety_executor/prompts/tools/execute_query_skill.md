Execute a pre-defined query skill with parameterized SQL.

Skills are pre-audited SQL templates and are checked against the same
read-query policy used by the raw query(sql) tool at startup and runtime.

Uses named parameters (:param_name) via SQLAlchemy text() for SQL injection prevention.

Args:
    skill_name: The skill name (e.g., "sample-monthly-sales-report")
    params: Parameter dict matching the skill's frontmatter schema

Returns:
    Query results (same format as query(), plus skill_name). SQL/policy
    failures return success=false, error_code, a safe error and an optional
    hint; discovery does not authorize writes or bypass the target policy.
