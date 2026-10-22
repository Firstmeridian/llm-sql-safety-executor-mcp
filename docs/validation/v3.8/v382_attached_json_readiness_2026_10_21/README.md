# Attached JSON-name readiness: assessment only

Version 3.8.2, October 21, 2026. **P2 / DRR-2026-135 is confirmed and not repaired.**
See the [findings, matrix and recommended repair](../V3_8_2_ATTACHED_JSON_READINESS_2026_10_21_ZH.md).

- [Summary and integrity](evidence/summary.json): 332 source application calls, 296 matrix plus 36 dynamic. The primary case uses in-process/child-stdio auto/legacy; seven controls and ATTACH/DETACH use in-process auto/legacy.
- [Matrix application records](evidence/results.json.gz): exposed content/structuredContent, independent positional SQLite truth and observations. Fifty-two of 84 matrix observations show one shared false-builtin root cause, not 52 independent defects.
- [Same-Skill dynamic records](evidence/dynamic.json.gz): data changes from builtin to attached FTS and back, while readiness incorrectly keeps builtin. Pure analysis retains one cache entry per observed Skill.
- Unauthorized attached roots, restricted functions and direct FTS shadow reads remain rejected. Explicit aux dependencies, main/TEMP priority and ordinary builtin controls behave as described in the report.

No source, dependency, actual configuration/grant or configured database was changed
or accessed. Seventy-seven runtime resources and three private TOMLs are unchanged;
all disposable fixtures were removed, preserving 47 earlier manifests/1338 file records.
No installed-wheel, resident Host, model, performance or token acceptance is claimed.
Application records are not complete transport frames or notifications. Earlier
harness and initialization failures remain in the private assessment archive.
The manifest includes compressed and decoded hashes. Preserve this checkpoint;
append any future repair independently.

