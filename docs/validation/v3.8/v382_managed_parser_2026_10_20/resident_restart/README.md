# Resident restart supplement — 2026-10-20

After the owner confirmed the restart, 16 current-Host calls satisfy the checked
contracts: six reads, four catalog/detail checks, two managed previews and four
expected refusals. Two SQLite file hashes and the complete 80-row order digest
remain unchanged; independent FTS MATCH count is four.

The original frozen expectations pass 15/16: the search expectation omitted a
documented related_skills match. Preserve that failure and apply the separate
expectation erratum; corrected verification passes 16/16 without a source repair
or repeated native calls. Do not classify this test error as a product failure.

`native_application.json.gz` contains Host application results with preview
handles consistently redacted from text/structured fields before export.
`native_plan.json.gz`, `expectation_erratum.json.gz`, both verification results,
`summary.json` and compressed scripts retain scope and provenance. These are
not full protocol frames, notifications or proof of original omitted metadata.

Only confirm=false previews were invoked; no confirmation/write or public revoke
operation was used. Proposals naturally expire under the configured 300-second
TTL; active revocation or observed expiry is not claimed. Special target-mode,
commit/rollback and two-protocol combinations remain source/package evidence.
There are no new complete-model trials or provider usage measurements.

All 435 older sealed files in 17 manifests remain unchanged. This supplement is
sealed independently; the parent's historical pending checkpoint stays intact.
Local source resources still match the final 77-resource wheel, without claiming
resident source-hash attestation. [Current report](../../V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).
