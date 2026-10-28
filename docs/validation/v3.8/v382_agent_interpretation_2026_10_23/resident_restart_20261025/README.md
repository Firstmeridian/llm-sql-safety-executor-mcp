# 2026-10-25：独立重启补充

[本批报告](../../V3_8_2_AGENT_INTERPRETATION_RESTART_2026_10_25_ZH.md)关闭候选的待重启／冻结原生任务核验，
不把[父检查点](../README.md)或其回放遗漏改写成通过。

- [summary.json.gz](summary.json.gz)：八个fresh Luna medium双轮任务的原始最终陈述、provider usage、
  原文与阶段核验、手工语义复核、20＋2条独立读取重放、配置／资源快照、采集计数修正及公开时间戳异常。
- [manifest.json](manifest.json)：本补充文件及报告的SHA-256；独立封存，不覆盖父记录。

业务按范围6/6匹配、2/2保留通过；匹配MCP调用29→33，业务tokens990,466→976,133。
这不证明提示词带来收益；父显式回放A11/12、B10/12完整事实的限制仍在。
本批公开时间戳有−1.716秒倒置，不修补为正数，端到端耗时比较未量化。

摘要不等于完整协议帧／模型输入，不含隐藏推理、凭据或预览句柄。
私有公开轨迹／脚本位于`local_archive/v382_review/20261025_agent_interpretation_restart/`。
读取压缩JSON可用Python gzip.decompress；后续新增补充，不覆写本检查点。
