# Contract validation entry points

Run from a checkout after `uv sync --frozen --group dev`. The entry points and
portable tests below do not need `local_archive`, historical commits or a
developer's absolute directory.
Historical reports remain evidence for their original inputs, not current runs.

## Current Codex Host maintenance

Use the separate [development helper](../../docs/guides/CODEX_MCP_RESTART.md)
for an existing Linux Codex Host. Default probing is read-only; actual restart
requires unique process binding and explicit authorization for Host-wide refresh.
This is not part of automated release/CI runs and does not replace product gates.
[Native restart evidence](../../docs/validation/v3.8/V3_8_2_CODEX_MCP_RESTART_2026_10_28_ZH.md).

## Deterministic regression

Query Skill publication also has a separate, isolated stdio workflow:

```bash
python scripts/validation/query_reload.py --python /absolute/validated/python --package-root /absolute/checkout/src --output /tmp/query-reload-source-new.json
```

Run again with the normally installed wheel's site-packages as `--package-root`.
Each run creates/cleans its own SQLite/configuration, checks the child import
origin and both Client modes, and refuses existing output or optimized Python.
This is not a model trial, current-Host restart proof, or real-MySQL release gate.
The current Query and Mutation workflows also reject active paths replaced by
regular files or dangling links while retaining the live catalog and pending
previews; intentional removal still succeeds. See the [directory repair](../../docs/validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md)
and [earlier reload acceptance](../../docs/validation/v3.8/V3_8_2_QUERY_RELOAD_2026_10_28_ZH.md).

Mutation publication has an independent owned-fixture workflow:

```bash
python scripts/validation/mutation_reload.py --python /absolute/validated/python --package-root /absolute/checkout/src --output /tmp/mutation-reload-source-new.json
```

Repeat against a normally installed wheel. Both Client modes retain the same
server process across definition changes, failed candidates, removal and re-add;
independent native connections check business rows and trigger effects. Optional
`--mysql-config config/server.toml --mysql-alias YOUR_TEST_MYSQL_ALIAS` adds the
same workflows on uniquely owned, automatically removed MySQL schemas; it never
uses existing business tables or changes private configuration/grants. The test
account needs disposable-schema/trigger privileges. SQLite always runs. These
are application-level records, not full protocol frames, model trials or proof
that the current Host reloaded. See the [Mutation contract](../../docs/guides/MUTATION_SKILL_RELOAD.md).

```bash
uv run --frozen python scripts/validation/release_gate.py --profile fast --source src --output /tmp/contracts-fast-new
```

This runs the regular pytest suite, including portable contract sentinels and
native temporary-file SQLite tests. It removes the inherited live-MySQL opt-in,
retains JUnit skip details and writes `report.json` plus `summary.md`. Successful
fast regression has `release_ready=false`; the live scenarios are `not_run`
(**UNVERIFIED**). It does not read private TOMLs or configured business databases.

## Explicit release acceptance

The configured test account must permit creating/dropping disposable databases,
triggers and disconnecting its own fixture sessions. Running this profile
explicitly authorizes those temporary fixtures; use a dedicated test service.
Only exact schemas/sessions owned by the harness are removed. Existing business
tables, grants, repository configuration and global server settings are unchanged.

```bash
uv run --frozen python scripts/validation/release_gate.py --profile release --source src --config config/server.toml --alias YOUR_TEST_MYSQL_ALIAS --output /tmp/contracts-release-new
```

For a normally installed wheel, use its interpreter and omit `--source`. The
repository supplies scripts/tests; the product must import from that interpreter.
The CI release workflow builds and normally installs the frozen wheel before
running this profile. It creates an ephemeral MySQL 8.0 service; its actual
version is evidence, rather than assuming a rolling image tag stays unchanged.

CI can instead pass `--mysql-env` with `RELEASE_MYSQL_HOST`, `RELEASE_MYSQL_USER`
and `RELEASE_MYSQL_PASSWORD`. This generates temporary TOMLs, references the
password by environment variable and removes the files afterward. The current
adapter uses MySQL's default port. No private configuration is committed.

Release runs deterministic regression, SQLite semantics/controlled reads/writes,
MySQL/InnoDB writes/uncertain outcomes and MySQL result/metadata contracts. It
requires expected case counts and fixture cleanup. Four optional MySQL skips in
the initial pytest pass are followed by **four actual passes/zero skips** in the
isolated schema; any other skip blocks release acceptance. Genuine server errors,
own-session disconnections and labelled client injections keep their distinction.
This is a finite contract matrix, not arbitrary network-partition testing, a
native Host restart check or a model/task/token benchmark.

Missing release configuration exits **2 / unverified** before test commands;
failed checks exit **1**, interruption **130**. Neither is release acceptance.
Every run needs a new output directory. The GitHub summary shows unverified
scenarios even if setup fails; CI retains logs, JUnit and application evidence.
These records are not full JSON-RPC frames. Keep local evidence private unless
reviewed for publication.

## Dependencies and evidence validity

Every run captures Python implementation/version/platform, actual linked SQLite
version/compile options, installed distribution versions (including transitive
packages), product resources, validation scripts/tests/workflows and dependency
file hashes. The existing `validation` identity also includes recursive root
`skills/**` Python/SQL/Markdown files (including referenced Markdown) and static
`tests/fixtures/**` SQL/Markdown inputs. Additions and deletions change that
identity as well as edits. Bytecode, audit logs and private connection TOMLs are
not collected by this file manifest. Live write evidence records actual MySQL
version/isolation/engine settings. Equal product hashes alone do not justify
evidence reuse.

Directory-link targets are also part of validation identity, including linked
input roots; selected file links retain both their target and content identity.
Retargeting an active, contained Skill link must not silently pass the final
check merely because both deployment directories already exist. Directory links
are not recursively followed; this does not expand supported Skill containment.

Both profiles compare the captured identity at the end and fail on detected
input/environment drift. This checks start/end identity, not uninterrupted
immutability: changing an input and restoring its bytes before the final check
can escape detection. Keep inputs stable during acceptance; no filesystem
watcher, repository lock or automatic evidence reuse is introduced. See the
[input-fingerprint repair](../../docs/validation/v3.8/V3_8_2_RELEASE_INPUT_FINGERPRINT_2026_11_06_ZH.md).

`--baseline PREVIOUS_REPORT_JSON` compares identities and lists required
rechecks. It is planning only: this runner **never automatically reuses results**,
even when identities match. SQLite changes request SQLite contracts; Python,
product/test/Skill/fixture/lockfile or distribution changes conservatively request all scenarios.
Unknown/transitive packages follow the same rule. Run release acceptance afresh
before release, including after runtime/database upgrades without a lockfile diff.

`.github/workflows/ci.yml` runs deterministic regression on pushes/PRs.
For both `push` and `pull_request`, B37 adds `src/**` and `skills/**` triggers to
`.github/workflows/release-contracts.yml`, so source and Skill/demo definition
changes trigger the existing normally installed-wheel release gate: deterministic
regression, SQLite contracts and explicit live MySQL/InnoDB/result/metadata
contracts. Existing dependency/validation triggers and manual dispatch remain,
including `pyproject.toml`, `uv.lock`, `.python-version`, both CI workflows,
`scripts/validation/**`, `tests/test_contract_sentinels.py` and
`tests/test_release_gate.py`. The input-fingerprint follow-up also adds
`tests/fixtures/**` to both events; the gate tests assert these paths. A trigger
is not a passing gate, and fast regression is not live acceptance. A PR outside
these paths can still require release acceptance. Repository branch protection/
release approval remains the maintainer's responsibility.

## Portable sentinels

Agent-evidence checks are independent of model trials and configured databases:

```bash
uv run --frozen python scripts/validation/agent_task_boundaries.py
uv run --frozen pytest -q tests/test_agent_evidence.py
```

The native in-memory fixture uses an explicitly declared half-open rental
interval and catches mistakes on both equality boundaries. Public-evidence
helpers associate exec/wait and preserve equal result slots; observations are not
request counts. They do not collect/redact logs or grade natural-language answers.
Use an invocation ledger and separate semantic review. These checks do not certify
Agent performance, native Host readiness or live MySQL behavior.

The payment fixture independently compares a Python row-loop oracle with native
SQLite. It includes missing/other-month/multiple payments, zero/refunds, repeated
amounts, two stores and exact rental/month boundaries. Inner joins, EXISTS and
null-rejecting left joins are valid alternatives. Eight known-wrong scope/count/
sum variants must differ from truth; these are business-evaluation sentinels,
not new gateway restrictions. The helper can emit a read-only constant CTE for
SQLite/MySQL; UNION still requires the selected connection's existing permission.

```bash
uv run --frozen pytest -q tests/test_contract_sentinels.py tests/test_release_gate.py
```

The result sentinels compile two altered function objects in private namespaces,
remove exactly the intended branch, demonstrate concrete lost values/limit
overflow and retain successful normal controls. They do not edit product files.
A missed branch, import failure, unrelated exception or environment timeout fails
the test rather than counting as defect detection. Existing native SQLite
transaction/RETURNING and exact-analysis-binding regressions remain ordinary
pytest tests; no full historical checkout or general mutation platform is needed.
