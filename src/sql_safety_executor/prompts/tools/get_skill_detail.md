Return cached execution fields or full metadata for one Skill.

Call this directly when the Skill name is known but its params are not.
Use detail_level="execution" for params/schema and the next action.
Do not call it when list_skills(detail_level="full") already returned
the params. Use full only for explicit catalog/readiness diagnostics.
This tool does not read files at runtime or expose SQL or mutation source.