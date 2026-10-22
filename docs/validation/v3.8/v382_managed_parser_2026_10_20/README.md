# Managed-plan migration evidence — 2026-10-20

[Report / 范围、决议与限制](../V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).

This checkpoint covers source/package validation. Native resident acceptance is
pending the owner restart and must be appended separately. Previous model trials
are not attributed to this source; no new model-usage claims are made.

- `corpus.json.gz`: frozen two actual definitions, 98 SQL cases and 10 contexts.
- `final_comparison.json.gz`: both complete validators with identical plan/binds,
  independent SQLite EXPLAIN truth and six separately added comment controls.
- `mysql_plans.json.gz`: 64 non-executing plans and actual session-mode checks;
  no configured business/global writes or connection credentials.
- `source_stdio.json.gz`, `installed_stdio_final.json.gz`: 40 application calls
  each, both explicit parsers and both Client modes. Disposable SQLite only;
  records include temporary process-local preview handles, not active grants.
- `parser_cost.json.gz`: sequential fixed-workload A/B/C/A microbenchmark with
  every timing sample and explicit nonclaims about new target checks and models.
- `pytest_full_final.log.gz`, `pyright_final.log.gz`, prompt/config/diff logs:
  final verification. Failed/intermediate runs stay in the local batch, with the
  first full-run failure also published for scope transparency.
- `verification.json` and `installed_resources_final.json.gz`: runtime/resource,
  dependency, final wheel, historical seal and build attribution. A fresh
  interpreter normally installs the wheel while explicitly reusing frozen deps.
- Compressed reproduction scripts and the manifest preserve the checked inputs.

Application results are not complete JSON-RPC frames, notifications, raw field
omission evidence or model/provider token records. No business data was written
in configured databases. The local batch additionally retains runtime archives,
wheel bytes, build logs and all diagnostics; it is ignored by Git.
