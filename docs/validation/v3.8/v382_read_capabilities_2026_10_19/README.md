# v3.8.2 read-capability acceptance evidence

本批独立评审补修及维护者重启后验收；行为、取舍及成本见[正式报告](../V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md)。

- `verification.json`：源码／包摘要、2667 项回归、30 项原生核验、九个完整任务及覆盖限制。
- `evidence.json.gz`：108 次安装 stdio、原生应用结果、九个双轮任务的公开消息／调用／实际结果／usage、独立 SQL 重放与人工复核、成本摘要。
- `frozen_tasks.json.gz`：试验前冻结的提示、评分和独立真值。
- `pre_restart_manifest.json.gz`：保持不变的本地 67 项父检查点；`regression_release.log.gz` 保留最终完整回归输出。
- 三个 `.py.gz`：采集、复核和封存脚本；原始本地记录按摘要引用，不重跑封存覆盖既有文件。

公开记录省略无关 Host 全工具目录输出、日志／机器路径及完整配置发现，完整本地公开 I/O 保留；这是应用层证据，不是完整协议帧，也不采集隐藏推理。保留额外汇总表达式的自行修正、重复查询及目录截断，不把最终 9/9 推广为零错误、总体可用率或成本下降。
