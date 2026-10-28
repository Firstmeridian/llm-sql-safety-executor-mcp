List all available pre-defined skills (query and mutation).

Supports MCP-level progressive disclosure:
- compact: lightweight catalog for discovery
- summary: compatibility-oriented metadata projection
- full: full cached parameter schema for planning execution

Omitting detail_level uses the startup-resolved
skills.discovery.default_detail TOML setting.

For a requested mutation preview/proposal, listing Skills is only discovery.
Use an executable matching Skill with execute_mutation_skill(skill_name,
params, confirm=false, connection_id) on this same connection and report
its actual result. A verbal plan is not a server preview. Do not create
a preview for an explanation-only request. Actual execution still needs
separate explicit approval.

This tool never reads skill files at runtime. It only projects metadata
from the startup-validated in-memory skill cache.

Returns:
    Dict with skills list and count
