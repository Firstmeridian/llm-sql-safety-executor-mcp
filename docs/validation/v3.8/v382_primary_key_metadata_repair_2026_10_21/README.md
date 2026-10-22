# DRR-141: actual PRIMARY identity and ordered members

Source and normal-wheel checkpoint, 2026-10-21. Owner restart/native verification is pending; append a resident supplement without rewriting this checkpoint.

[Chinese report and costs](../V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md).

- `baseline_*.json.gz`, `source_*.json.gz`, `installed_*.json.gz`: final shared 13-object SQLite/MySQL matrices,96 application calls per backend per stage. Both modes/transports; native truth is included. Original values, including owned random fixture-schema fields, are retained.
- `validation-summary.json`, `final-checks.json`, `environment.json`: oracle comparisons, suite/resource/configuration scope and actual backend versions. Match text with structured application content; these are not complete protocol frames.
- `costs.json.gz`, `cost-summary.json`: serial same-fixture A1/B/A2,5 warmups and30 samples; local latency/payloads, no provider-token or full-model inference.
- `native_plan.json.gz`:12 frozen existing-alias checks, not yet resident acceptance. Special reverse/unique-only/repeated-part fixtures remain source/package scoped.
- `runtime_patch.diff`, compressed tests/drivers and logs: reproducible narrow source change, preserved initial failures and final passing checks. `preparation_notes.json` explains fixture/stub/schema-normalization corrections; no automatic-review rejection.
- `documentation_checks.json`, `manifest.json`: document/link checks and stored/decoded SHA-256 seals. Prior71 manifests/2180 file records remain intact. Do not overwrite historical assessment or current pending checkpoint.

No configured business table, private TOML, grant, prompt, version or dependency was changed. MySQL fixtures use random owned schemas and verify cleanup; SQLite files stay unchanged through reads. Binaries are retained in the local batch rather than duplicated here. Shared dependency reuse is declared in installed resource provenance. No new model trial is claimed.
