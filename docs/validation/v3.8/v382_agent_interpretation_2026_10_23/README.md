# Agent 解释评估：重启前候选证据

基线 `7c8edfbd0ea418659450377b2bbd46cd9e9dd476`；版本 v3.8.2。
本检查点不包含候选原生 B 或保留任务通过声明，后续重启核验另加补充。
方法、改动与未通过项见[报告](../V3_8_2_AGENT_INTERPRETATION_2026_10_23_ZH.md)。

| 文件 | 内容／采集层级 |
| --- | --- |
| [summary.json.gz](summary.json.gz) | 冻结任务／保留措辞／评分，六个原生任务的最终陈述与 provider usage，A/A 时间窗及调用，九个构造回放回答／用量，逐项遗漏、独立驱动真值及17条SQL重放；源码／安装资源哈希与检查计数。 |
| [collection_cost.json.gz](collection_cost.json.gz) | 自动清理SQLite夹具的两种Client模式、1926调用、八交错块／模式、完整流程样本和本进程四阶段内存计时。不能量化Host／日志导出／磁盘开销，净采集成本未可靠分离。 |
| [manifest.json](manifest.json) | 本检查点文件与报告／提示／检查文件的SHA-256；后续另加补充，不回写父pending记录。 |

公开摘要不是完整协议帧，也不是模型实际收到的完整定义；不含隐藏推理或预览令牌。
私有批次 `local_archive/v382_review/20261023_agent_interpretation/` 另存选定公开工具I/O、
定义链路、原始检查日志及准备失败。两者都不宣称持有完整provider输入。
解压可用 Python `gzip.decompress(Path(...).read_bytes())`，内容为 UTF-8 JSON。

六个原生任务业务通过不等于候选改善。显式规则回放的关键事实完整覆盖为基线11/12、
候选10/12：两者均漏提无效载荷声称committed，候选另漏报其他目标已提交。
这些解释不完整与错误断言写入／未写入分开计分；首次回答均保留。
A/A同配置仅估计重复波动，不能估计采集开销或证明修改导致性能变化。
