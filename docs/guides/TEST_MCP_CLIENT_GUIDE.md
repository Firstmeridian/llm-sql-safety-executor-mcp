# MCP Client verification · v3.8

This guide uses the installed `sql_safety_executor` package and explicit TOML
configuration. Run repository scripts from the repository root after
`uv sync --frozen --group dev`. The previous script-based instructions remain in
the [v3.7 historical guide](TEST_MCP_CLIENT_GUIDE_v3_7.md).

## Offline checks

```bash
uv run sql-safety-executor config check --config config/examples/sqlite/server.toml
uv run sql-safety-executor config explain --config config/examples/sqlite/server.toml
uv run python scripts/check_prompt_contract.py --config config/examples/sqlite/server.toml
```

These commands resolve explicit secret references but do not connect to a
database or import business Skills. They do not prove that a database is
reachable or that a Skill can execute. See the [configuration contract](CONFIGURATION_ZH.md)
for path resolution, defaults, authorization and migration from `.env`.

## Protocol and tool inspection

### Update the actual Host launch entry

The repository's `mcp_config.json` (or private `mcp_config.local.json`) is a
template; editing it does not update a Host's saved configuration. In particular,
Codex uses `[mcp_servers.<name>]` in `~/.codex/config.toml` or trusted project
`.codex/config.toml`, not the template's `mcpServers` JSON wrapper:

```toml
[mcp_servers.sql-safety-executor-mcp]
command = "/absolute/project/.venv/bin/sql-safety-executor"
args = ["serve", "--config", "/absolute/project/config/server.toml"]
```

Use the environment where v3.8 is actually installed (which may be `.venv-v38`
during migration). Back up the existing Host entry and replace both its
executable and arguments; a saved `start_server.py` entry cannot start v3.8.
Reconnect the server/restart the extension after saving. A process already
running, a successful offline config check, or a configured-server list is not
proof that the active conversation can discover and call its tools. Verify
`list_connections` through that Host. See the [official Codex MCP guide](https://developers.openai.com/codex/mcp).

### Inspect a fresh reference server

```bash
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode auto
uv run python scripts/inspect_mcp.py --config config/examples/sqlite/server.toml --mode legacy
```

The script starts a fresh stdio server, prints the negotiated protocol,
`tools/list` schemas, configured connections and server instructions, then
closes the process. With the locked reference Client, these modes negotiate
`2026-07-28` and `2025-11-25`, respectively. It does not call a database query or
connection probe. Unlike offline checks, startup does discover enabled Skills;
enabled mutation modules are trusted Python and may have import side effects.

Only configured tools should appear. In particular, Skills-disabled deployments
must omit all Skills tools, and `request_mutation_approval` appears only when
MRTR, Skills and global writes are enabled. Registration does not grant access
to every configured target or Skill.

For an actual read through the complete core policy:

```bash
uv run python scripts/query.py --config config/examples/sqlite/server.toml \
  --connection-id demo 'SELECT 1 AS value'
```

This last command accesses the selected database. It is a core-service check,
not a protocol or natural-language Agent test. Use a disposable fixture for
queries that inspect business data; schema and count operations can also incur
database work.

## Reference human-approval Host

Create the separate demo database once; the setup script refuses to overwrite
an existing file:

```bash
uv run python scripts/setup_sqlite_demo.py --output local_data/mutation-demo.db
```

Prepare a UTF-8 JSON file containing
`{"order_id": 1, "new_status": "confirmed"}`, then run:

```bash
uv run python -m examples.manual_mutation_approval \
  --config config/examples/mutation/server.toml --flow preview \
  --connection-id demo_write --skill sample-update-order-status \
  --params-file /absolute/path/params.json
```

The default flow is `preview`. For MRTR, first set
`skills.mutation.mrtr.enabled = true` in the selected Skills TOML, then use
`--flow mrtr`. Use a fresh fixture or deliberately restore the business state
before another trial; a successful first run changes the order status. The
reference Host accepts only literal `APPROVE`; its default approval deadline is
60 seconds and its default tool timeout is 120 seconds. The server's original
proposal expiry also remains authoritative.

MRTR requires the modern protocol and form elicitation, and supports only
managed single-statement mutations. The Host displays the review and collects
the decision; the server validates bindings and consumes a proposal once. A
missing/expired proposal or lost response does not prove that a previous write
did not happen. Do not automatically retry; reconcile the business state first.
See [security boundaries](../security/V3_8_SECURITY.md).

## Automated and native Host evidence

```bash
uv run pytest -q -rs
uv run pyright
uv build
```

Pytest collection is configured in `pyproject.toml`. The default suite uses
isolated fixtures and does not load the private `.env`. The optional MySQL test
fixture still accepts explicitly exported `DB_USER`, `DB_PASSWORD`, `DB_HOST`
and `DB_NAME` only after `RUN_MYSQL_INTEGRATION_TESTS=1`; this is a test harness
input, not a restored server configuration channel. Use a dedicated test DB.
CI separately installs the wheel and runs `scripts/verify_installed.py` from
outside the repository with both protocol generations and packaged prompts.

Reference Client success does not establish Codex or Copilot compatibility.
For each native Host, record the actual version, negotiated protocol, visible
tools, approval UI/decision, call trace, resulting database state and actual
usage. An unsupported protocol/capability or Host policy refusal is a recorded
limitation, never an MRTR pass. See the [v3.8 validation record](../validation/V3_8_VALIDATION_ZH.md)
and the [Agent evaluation method](MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md).
