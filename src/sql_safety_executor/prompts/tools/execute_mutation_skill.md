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

If validation rejects a request, do not bypass the rule or change targets.
Before saying no path exists, check any returned related_available_skills
and other matching Skills with list_skills on the same connection. Use only a
path that fits the user's goal, and preview and approve every write separately.

Returns:
    Preview result (confirm=false) or execution result (confirm=true).
    For a valid preview, show returned preview_token_expires_at and timezone,
    or report expiry missing. Do not infer "valid"/"expired" from timestamps
    or today's date. Only execute checks validity; no automatic new preview.
