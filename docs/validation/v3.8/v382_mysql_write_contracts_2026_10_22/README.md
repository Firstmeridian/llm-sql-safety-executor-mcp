# Exact SQL binding and real MySQL/InnoDB gate — October 22, 2026

DRR-144 adds only exact analysis.source_sql binding to MySQL's existing read preconditions. Current consistent MCP callers were not a reproduced bypass. DRR-145 closes the explicitly declared live verification gap without claiming a new production defect or complete stabilization.

Source and normal wheel each pass14 native-oracle write groups,19 faults (five actual server errors, two own-session disconnects and12 labelled client injections), three races, and96 application calls/32 preview-confirm-replay flows. Ordinary72 calls cover in-process/stdio, auto/legacy and both managed classifiers; the extra24 unknown calls use in-process labelled commit-ack injection with real durable/unchanged controls, one attempt and spent-token rejection. Native PyMySQL oracles compare business/trigger/cascade data independently of project analysis/policy/results; AUTO_INCREMENT gaps are permitted. No production full-DB comparison, new Agent step or configuration switch.

Full3505 regressions pass/four optional skips; the four existing opt-in MySQL tests separately pass4/4 in the disposable schema. Types/prompts pass,77 installed resources match; fixture schemas removed and configs/grants/existing business tables unchanged. Preserve preparation errors, interrupted sandbox checks and old81 seals/2677 records. Application records redact tokens and are not complete protocol frames or model usage. No new performance/model claim. Six limited native checks await the owner restart; their eventual success cannot directly prove the internal source-mismatch branch.

See the [contract, gate definitions and limits](../V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md), [final checks](checks.json.gz), [frozen resident plan](resident_plan.json.gz) and [documentation check](documentation_checks.json.gz). Core rerunnable gate: decompress mysql_writes.py.gz to the repository scripts/validation path or use that tracked path, select an explicitly approved test alias, pass --source for source or omit it under the normal wheel interpreter. Use fresh output paths; --section unknown-clients is the distinct in-process fault supplement. The script requires disposable-schema/trigger privileges and actual lock-wait observation, fails rather than silently skipping missing access, and deletes only the exact schema it created.

Evidence and supporting scripts (gzip; manifest contains encoded/decoded hashes):

- [baseline.json.gz](baseline.json.gz)
- [binding_current.log.gz](binding_current.log.gz)
- [binding_final.log.gz](binding_final.log.gz)
- [binding_known_bad.log.gz](binding_known_bad.log.gz)
- [binding_sentinels.json.gz](binding_sentinels.json.gz)
- [binding_sentinels.log.gz](binding_sentinels.log.gz)
- [build_install.log.gz](build_install.log.gz)
- [checks.json.gz](checks.json.gz)
- [full_tests.log.gz](full_tests.log.gz)
- [full_tests_final.log.gz](full_tests_final.log.gz)
- [installed_final.json.gz](installed_final.json.gz)
- [installed_final.log.gz](installed_final.log.gz)
- [installed_resources.json.gz](installed_resources.json.gz)
- [installed_unknown.json.gz](installed_unknown.json.gz)
- [installed_unknown.log.gz](installed_unknown.log.gz)
- [postflight.json.gz](postflight.json.gz)
- [postflight.log.gz](postflight.log.gz)
- [preflight.json.gz](preflight.json.gz)
- [prompts.log.gz](prompts.log.gz)
- [publish.log.gz](publish.log.gz)
- [resident_plan.json.gz](resident_plan.json.gz)
- [source_attempt1.json.gz](source_attempt1.json.gz)
- [source_attempt1.log.gz](source_attempt1.log.gz)
- [source_attempt2.json.gz](source_attempt2.json.gz)
- [source_attempt2.log.gz](source_attempt2.log.gz)
- [source_attempt3.json.gz](source_attempt3.json.gz)
- [source_attempt3.log.gz](source_attempt3.log.gz)
- [source_unknown.json.gz](source_unknown.json.gz)
- [source_unknown.log.gz](source_unknown.log.gz)
- [types.log.gz](types.log.gz)
- [types_final.log.gz](types_final.log.gz)
- [update_docs.log.gz](update_docs.log.gz)
- [verify.log.gz](verify.log.gz)
- [build_install.py.gz](build_install.py.gz)
- [postflight.py.gz](postflight.py.gz)
- [preflight.py.gz](preflight.py.gz)
- [publish.py.gz](publish.py.gz)
- [sentinels.py.gz](sentinels.py.gz)
- [update_docs.py.gz](update_docs.py.gz)
- [verify.py.gz](verify.py.gz)
- [mysql_writes.py.gz](mysql_writes.py.gz)
- [test_read_analysis_binding_v382.py.gz](test_read_analysis_binding_v382.py.gz)
- [mysql_current.py.gz](mysql_current.py.gz)
- [mysql_baseline.py.gz](mysql_baseline.py.gz)

- [Report snapshot](assessment.md.gz)
- [Manifest](manifest.json)
