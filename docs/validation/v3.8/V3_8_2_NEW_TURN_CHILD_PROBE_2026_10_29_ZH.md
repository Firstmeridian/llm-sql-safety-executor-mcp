# 新父轮 Luna 子会话就绪定点（2026-10-29）

按维护者批准，仅创建一个 fresh GPT-6 Luna medium，fork_context=false；不修改配置、不刷新或重启。准确子线程 starting→ready，connected／11工具；WAIT完成后只发一次原生 query，analytics_rich_sqlite 返回 new_turn_child_canary=1。子会话已关闭。

| 检查 | 本批结果 |
| --- | --- |
| 准确子线程启动及实际调用 | 1/1；一个原生查询成功，无替补或重试 |
| 私有配置／父进程 | 现代协议标记仍缺省；配置哈希及唯一父目标身份前后相同 |
| 父 SQLite／MySQL 常量 | 前后均通过 |
| 保护文件／历史封存 | 20项及343成员不变 |
| 模型成本 | WAIT input 14036／output 7；定点 input 49515／output 312；cached input分别13440／38144，属于input子集 |
| 完整业务能力 | 本批未测，不能由常量成功替代 |

同一结果在content／structured结果中各出现一次，按调用及相同应用正文去重后只有一个结果，不能计作两次调用。采集仅含公开消息／工具I/O、模型身份和数值用量，不含隐藏推理或完整协议帧。

上批三个子线程失败保持原结论。官方0.165源码显示spawn复制父轮捕获配置；本批新父轮成功，为该条件解释增加证据，但未取得准确子env或协议帧，不能断言唯一根因、缓存已证实或所有Host场景已解决。状态观察本身可能影响初始化。本批没有A/B，不能据此宣称速度或token改善。

下一步单独冻结完整双轮业务批，不把本定点与此前失败合并回写通过。

本地材料：[入口](../../../local_archive/v382_review/20261029_new_turn_child_probe/reports/README_ZH.md)。
