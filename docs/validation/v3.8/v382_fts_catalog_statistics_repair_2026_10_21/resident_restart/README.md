# DRR-137／138／139 重启后限定验收

2026-10-21。维护者确认重启当前 Codex 使用的 SQL MCP 后，冻结的10项既有别名检查全部通过。本补充与父检查点分开封存，父报告中的 pending 属于重启前历史状态。

| 检查 | 结果 |
| --- | --- |
| sqlite_features_sqlite 单连接诊断 | connected；完整结果，无清理异常 |
| SQLite 常量读取 | n=7 |
| FTS MATCH／表调用两种写法 | 均为 n=1，与独立只读 SQLite 一致 |
| pages 元数据 | 10列，status=virtual；完整索引，包含部分索引属性 |
| compact／full schema | 均为6表34列；列、生成标记及各表行数与独立真值一致 |
| 直接读取 FTS 影子表 | table_access_denied |
| SLEEP(0) | expensive_function_denied |
| trade_analysis_mysql 常量读取 | n=7 |

10次调用均为 isError=false，应用成功／预期拒绝符合契约，文本与 structured content 一致。没有重试原生调用，也没有配置数据库写入。77运行资源的磁盘摘要、三份私有TOML及配置SQLite文件摘要保持；59份父及历史manifest、1998条文件记录的存储与已声明解压摘要全部核验不变。磁盘摘要不是驻留进程内存源码证明。

目录同名碰撞、部分索引1500→1及默认rowid冷态等专用夹具仍归属父批源码／正常安装验证，没有在配置库重建。父批3340通过／4项可选跳过、源码／wheel各488调用及串行成本保留原范围；本补充没有新构建、全量回归、完整Luna任务或模型token测量，不据此承诺性能收益或确认Host缓存根因。DRR-137／138／139按这些声明范围完成验收。

- [原始应用记录](native_results.json.gz)、[核验结论](integrity.json)、[独立真值](metadata_truth.json)。应用记录不包含完整协议帧、通知或模型用量。
- [Host元数据摘要](tool_metadata_summary.json)：保存本会话实际暴露的10个工具名／description；不冒充tools/list的完整输入／输出schema。
- [核验脚本](verify.py.gz)、[过程说明](preparation_notes.json)。首次证据读取脚本未兼容历史摘要字段名，修正后通过；未重复工具调用或改产品代码。
- [父批实现及成本报告](../../V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md)、[冻结计划](../native_plan.json)。父pending、失败及本补充独立保留。
