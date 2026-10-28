# Contract validation entry points

Run from a checkout after `uv sync --frozen --group dev`. The entry points and
portable tests below do not need `local_archive`, historical commits or a
developer's absolute directory.
Historical reports remain evidence for their original inputs, not current runs.

## Deterministic regression

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
file hashes. Live write evidence records actual MySQL version/isolation/engine
settings. Equal product hashes alone do not justify evidence reuse.

`--baseline PREVIOUS_REPORT_JSON` compares identities and lists required
rechecks. It is planning only: this runner **never automatically reuses results**,
even when identities match. SQLite changes request SQLite contracts; Python,
product/test/lockfile or distribution changes conservatively request all scenarios.
Unknown/transitive packages follow the same rule. Run release acceptance afresh
before release, including after runtime/database upgrades without a lockfile diff.

`.github/workflows/ci.yml` runs deterministic regression on pushes/PRs.
`.github/workflows/release-contracts.yml` also runs on dependency/validation
changes, and supports manual dispatch before release. Relevant files include
`pyproject.toml`, `uv.lock`, `.python-version` and the CI workflows. A PR without
those changes can still require release acceptance; absence of this workflow
is not a passing live gate. Repository branch protection/release approval remains
the maintainer's responsibility.

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
