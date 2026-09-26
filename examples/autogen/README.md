# Optional AutoGen examples

These examples are outside the core runtime dependency set. Use a separate venv:

```bash
python3 -m venv .venv-autogen
.venv-autogen/bin/pip install -r examples/autogen/requirements.txt
# Export your chosen model provider credentials explicitly; no .env is loaded.
.venv-autogen/bin/python -m examples.autogen.autogen_sql_agent_new \
  --server-python /absolute/path/to/server/.venv/bin/python \
  --config /absolute/path/server.toml 'List configured connections'
```

The example environment may use an older MCP SDK; the server runs in its own
locked environment and negotiates through stdio. Core CI does not install or
claim live AutoGen/model compatibility. The pure prompt builders are tested.
For explicit human approval use the maintained reference Host:
`python -m examples.manual_mutation_approval --config ... --flow preview|mrtr ...`.
The examples retain their prior model integration assumptions; see
[the historical development guide](AGENT_DEVELOPMENT_ZH.md).
