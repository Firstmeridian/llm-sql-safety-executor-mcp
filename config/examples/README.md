# Configuration examples

English | [中文](README_ZH.md)

These public v3.8 templates use the same strict TOML loader as the server. They contain no deployment secrets. Run the commands below from the repository root after `uv sync --frozen --group dev`; an installed executable can also run outside the repository with an absolute `--config` path.

## Choose a template

| Directory | Connections / default | Skills | Mutation authorization |
|---|---|---|---|
| [sqlite](sqlite/server.toml) | SQLite `demo`; default `demo` | Disabled | None |
| [mysql](mysql/server.toml) | MySQL `reporting`; default `reporting` | No Skills file referenced, so disabled | None |
| [multi](multi/server.toml) | SQLite `demo` and MySQL `reporting`; default `demo` | Query Skills enabled | Global writes disabled |
| [mutation](mutation/server.toml) | Separate SQLite `demo_write`; default `demo_write` | Enabled | Only `sample-update-order-status` on `demo_write`; MRTR disabled |

SQLite read scopes allow `orders`, `users`, and `products`; MySQL allows only `orders`. The mutation template allows reads only from `orders`. No template enables UNION. Configured table names express permission, not proof that tables exist. Query Skill availability also depends on backend, declared scope/profile and schema readiness.

## File responsibilities

Every referenced TOML declares `schema_version = 1`.

- `server.toml` names the connections/optional Skills files and the required default connection. It can also configure tools, output limits, common timeouts, logging and telemetry.
- `connections.toml` declares each target independently: backend, database identity, credentials, read scope and connection-level mutation permission.
- `skills.toml` configures trusted definitions, discovery/readiness, global mutation admission, preview tokens, optional MRTR and audit. Omitting its reference disables Skills; a referenced missing file is an error.

The server requires `--config`; it does not discover `.env` or accept implicit `DB_*` / `SKILLS_*` overrides. Unknown fields and invalid types fail validation. File paths resolve relative to the TOML that declares them. Configuration, secrets and loaded Skill definitions remain snapshots until restart.

## SQLite: check and start

The SQLite template uses the bundled `sample_data/demo.db` and requires no credentials:

```bash
uv run sql-safety-executor config check --config config/examples/sqlite/server.toml
uv run sql-safety-executor config explain --config config/examples/sqlite/server.toml
uv run sql-safety-executor serve --config config/examples/sqlite/server.toml
```

`check` and `explain` parse the same configuration and resolve secrets, but do not connect to databases or import business Skills. `explain` redacts secrets and describes effective settings and disabled features. Neither command proves database connectivity or Skill readiness. `serve` starts the stdio MCP process; normally a Host launches it using those arguments.

## MySQL and multiple targets

Set the MySQL host, user, database and allowed tables for your deployment. Both `mysql` and `multi` explicitly resolve `REPORTING_DB_PASSWORD` from the launching process. For example, in Bash:

```bash
read -r -s -p "Reporting database password: " REPORTING_DB_PASSWORD
export REPORTING_DB_PASSWORD
uv run sql-safety-executor config check --config config/examples/mysql/server.toml
uv run sql-safety-executor config check --config config/examples/multi/server.toml
```

An IDE Host must receive the variable in its own launch environment. A value stored only in `.env` is not read. All configured credentials are resolved during loading, so the multi-target template needs this variable even when SQLite is the default.

Alternatively, in your private connections file choose exactly one source:

```toml
mysql.password = { file = "secrets/reporting.password" }
# Alternatives: { env = "REPORTING_DB_PASSWORD" } or { value = "..." }
```

Place this key inside the chosen `[connections.<id>]` table, replacing the existing `mysql.password` key. Paths are relative to that connections file. Secret files must be nonempty UTF-8, at most 64 KiB; whitespace and a trailing newline are part of the password. No fallback source is tried. Keep real credentials out of tracked templates.

For multiple connections, omitted `connection_id` selects the explicit default. Unknown aliases fail without fallback. Read tools do not automatically query every connection; only `check_connection(scope="all")` explicitly selects all configured targets for diagnostics, when the request permits that scope.

## Controlled mutation example

This template intentionally points to a separate disposable database. Prepare it once:

```bash
uv run python scripts/setup_sqlite_demo.py --output local_data/mutation-demo.db
uv run sql-safety-executor config check --config config/examples/mutation/server.toml
```

The setup script refuses to overwrite an existing file. Its initial order has `id=1` and `status="pending"`. Save the following request parameters to a private JSON file, then supply its path:

```json
{"order_id": 1, "new_status": "confirmed"}
```

```bash
uv run python -m examples.manual_mutation_approval \
  --config config/examples/mutation/server.toml --flow preview \
  --skill sample-update-order-status --connection-id demo_write \
  --params-file /absolute/path/to/params.json
```

The reference Host displays the review and accepts only literal `APPROVE` before expiry. An approval performs a real write to the disposable database. Write admission requires all five configuration gates: Skills enabled, global mutations enabled, the connection in `allowed_connections`, connection mutation enabled, and the Skill in its allowlist. Read allowlists do not universally constrain mutation SQL. Adding the reset Skill also requires explicitly admitting that Skill; the public template does not grant it.

For MRTR, set `skills.mutation.mrtr.enabled = true` in your private Skills file and run the Host with that deployment's `--config` and `--flow mrtr`. This requires MCP `2026-07-28`, client form elicitation and a managed single-statement Skill. Older clients can use preview/execute; an unsupported MRTR call is rejected. The server trusts the Host's approval decision, without independently authenticating a human. Do not automatically retry unknown outcomes or lost responses; inspect business state first. Restart invalidates unused proposals.

## Copying templates into local configuration

Use the ignored `config/server.toml`, `config/connections.toml` and `config/skills.toml` for local deployment. Review existing files before copying; preserve your current settings and secrets. Copy all files referenced by the chosen main file, then adjust paths because their declaring directory has changed:

| Field | Template under `config/examples/<name>/` | Copy under `config/` |
|---|---|---|
| SQLite demo `sqlite.path` | `../../../sample_data/demo.db` | `../sample_data/demo.db` |
| Mutation `sqlite.path` | `../../../local_data/mutation-demo.db` | `../local_data/mutation-demo.db` |
| `skills.directory` | `../../../skills` | `../skills` |
| Mutation `skills.audit.path` | `../../../logs/demo-mutations.jsonl` | `../logs/demo-mutations.jsonl` |
| `files.connections` / `files.skills` | Sibling filenames | Unchanged if still siblings |

`config/*.toml`, `config/secrets/` and `mcp_config.local.json` are ignored; `config/examples/` is public and tracked. Other custom locations need their own ignore rules. Python Skills are trusted code; directory containment does not sandbox them. Use explicit, reviewed paths.

Check the local copy before pointing your Host at its absolute `server.toml` path. Stop the old process before switching versions. Rollback requires matching code, dependencies and configuration together. For every field, default and old-to-new mapping, see the [configuration and migration guide](../../docs/guides/CONFIGURATION_ZH.md); see also the [client guide](../../docs/guides/TEST_MCP_CLIENT_GUIDE.md) and [validation limits](../../docs/validation/V3_8_VALIDATION_ZH.md).
