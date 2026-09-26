# Project context · v3.8

This project provides a trusted-local-Host MCP database safety gateway. See
[README](README.md), [configuration](docs/guides/CONFIGURATION_ZH.md),
[architecture](docs/architecture/V3_8_IMPLEMENTATION_ZH.md) and
[security](docs/security/V3_8_SECURITY.md) for current contracts.

Implementation is the installed `src/sql_safety_executor/` package. Run
`uv sync --frozen`, `uv run pytest`, `uv run pyright`, and `uv build`.
Start only with `sql-safety-executor serve --config /absolute/path/server.toml`.
No project dotenv configuration or root server script remains.

Core query entry points enforce full read policy. Structural SQL parsing alone
is not an authorized execution interface. Writes require all explicit policy
gates and one-time proposals. MRTR is default-off and managed-only; the Host is
trusted to collect human approval. Never infer an unknown write outcome or
automatically retry writes. Preserve historical evidence when updating docs.
