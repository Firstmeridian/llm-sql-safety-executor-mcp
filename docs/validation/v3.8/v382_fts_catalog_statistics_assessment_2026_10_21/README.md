# FTS catalog and statistics assessment

October 21, 2026. **Assessment only; two open P2 issues, no production repair.**

- [Findings, recommended fixes and scope](../V3_8_2_FTS_CATALOG_STATISTICS_ASSESSMENT_2026_10_21_ZH.md).
- [Verified summary](evidence/summary.json): source 284 / existing normal-wheel 96 / isolated 2c0a9e7 baseline 14 Client calls, 394 total. Complete matrices and text/structured equality establish reproducibility, not successful execution or repair acceptance.
- [Source](evidence/source.json.gz), [installed](evidence/installed.json.gz), [baseline](evidence/baseline.json.gz): both Client modes; source/wheel each 32 child-stdio calls use the two original fixtures.
- [Final components](evidence/components-final.json):16 root/collision combinations and 80 targeted fixed-PRAGMA checks; includes index-only ANALYZE.

DRR-137: FTS guard bootstrap still reads shadowable pragma_table_list. Ordinary
same-name tables/views affect reads and metadata even outside the root schema.
DRR-138: partial-index statistics are mistaken for table cardinality, including
WITHOUT ROWID and creation-order variants; the baseline reproduces it.
An existing first-stat regression assertion mirrors the erroneous behavior.

All 77 runtime resources and three private TOMLs remain unchanged. All fixtures
are disposable; no configured database, native Host or model calls, writes,
new package build/install, full regression or performance claim. Earlier 55
manifests/1723 file records are intact. Preserve prior scoped native acceptance
and its original pending/failure checkpoints. Captures are application results,
not complete protocol frames. Gzip preserves every stored/decoded byte.
