List all available pre-defined skills (query and mutation).

Supports MCP-level progressive disclosure:
- compact: lightweight catalog for discovery
- summary: compatibility-oriented metadata projection
- full: full cached parameter schema for planning execution

Omitting detail_level uses the startup-resolved
skills.discovery.default_detail TOML setting.

This tool never reads skill files at runtime. It only projects metadata
from the startup-validated in-memory skill cache.

Returns:
    Dict with skills list and count
