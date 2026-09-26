Execute a pre-defined mutation (write) skill.

Two-phase workflow:
    1. confirm=false (default) — validate + preview, no database changes;
        registers and returns a one-time preview_token
    2. confirm=true — verify and atomically consume preview_token.
        Managed single-statement Skills execute their cached plan
        directly in the framework without instantiating or calling
        the Skill class;
        imperative Skills re-validate and execute with conservative
        whole-operation outcome semantics.

For managed Skills, preview_sql and bound_params come from the same
cached plan and final binding used for execution. Skill-supplied
copies or unresolved values are rejected before token issuance.

Args:
    skill_name: The mutation skill name (e.g., "sample-update-order-status")
    params: Parameter dict matching the skill's frontmatter schema
    confirm: False=dry-run preview (default), True=actual execution
    preview_token: Required when confirm=True; returned by preview
    connection_id: Configured target connection; omit for the default

Returns:
    Preview result (confirm=false) or execution result (confirm=true).
    Every returned payload includes execution_outcome. Processable
    execute failures return success=false plus an extensible
    error_code with stable published meanings;
    callers must not infer success merely because no ToolError was
    raised and must never retry an unknown outcome automatically.