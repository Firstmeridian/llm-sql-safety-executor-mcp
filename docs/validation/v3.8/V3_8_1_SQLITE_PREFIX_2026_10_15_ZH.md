# v3.8.1 SQLite 字面前缀与文档范围补修（2026-10-15）

两个反馈均属实且需要修正。表目录 get_tables 和关系目录 get_read_relations 都用了 NOT LIKE 'sqlite_%'；其中下划线是通配符，不是字面字符。合法 sqliteXorders／SQLITEXorders 的普通表和视图能 raw 查询，却被目录隐藏、被 readiness 误报缺失，导致 Skill 执行拒绝。这是本轮此前遗漏的功能误拒，不是读取授权扩大。

修改前 69 份生产资源匹配[上一批源码](schema_binding_2026_10_15/automation.json)。两种 Client 模式、表／视图及三个名字共 12 组、72 次隔离调用独立复现：8 个 sqliteXorders／SQLITEXorders 场景失败，4 个短名 sqlite 控制组正常。真正的 sqlite_sequence 由 AUTOINCREMENT 自动生成，目录仍应隐藏它。原[基线应用记录](sqlite_prefix_2026_10_15/baseline-calls.json.gz)压缩保留。

## 修正及边界

| 项目 | 实现／结果 | 取舍 |
| --- | --- | --- |
| 字面 sqlite_ 前缀，DRR-2026-094 | 两个目录共享 substr(name, 1, 7) COLLATE NOCASE != 'sqlite_'；前 7 字符与固定前缀比较，不使用通配符；保留 ASCII 比较规则 | 只改变目录过滤，不扩大表授权或工具 identifier 语法。表发现仍 table-only，readiness 观察 table／view；没有新依赖、参数或调用步骤 |
| SQLite／MySQL 保证范围 | 修正 README 中英 sample 说明和配置指南：SQLite 明确 main，避免 temp／aux 替代；MySQL 绑定配置库，但同会话临时表仍可能遮蔽永久表 | MySQL 会话生命周期仍需单独设计，不能把库限定描述为所有对象隔离；本轮未变更 MySQL 实现或新建真实数据库对象 |
| 完整 commit message | 按以往提交采用背景一句、7 条要点，分为修复／验证／范围三组；2126→737 字符、25→7 条；详细信息留在本批及此前验收记录 | 省略逐条微观修复和重复计数，不省略主要功能、验证类别、版本与暂缓决定；原长草案保留在忽略目录，不提交历史草案 |

SQLite 官方说明 LIKE 的下划线匹配单字符，ESCAPE 可指定字面字符；本实现选择字面子串比较，避免通配与转义混淆。[表达式说明](https://sqlite.org/lang_expr.html#the_like_glob_regexp_match_and_extract_operators)、[substr](https://sqlite.org/lang_corefunc.html#substr)。sqlite_ 是 SQLite 保留内部名称前缀。[CREATE TABLE](https://sqlite.org/lang_createtable.html)。MySQL 同会话临时表隐藏同名永久表，不能由 schema 限定概括为不存在此边界。[官方说明](https://dev.mysql.com/doc/refman/8.0/en/create-temporary-table.html)。

## 验证与当前状态

| 检查 | 结果与归属 |
| --- | --- |
| 新增回归 | 12 项，两种模式／表与视图／大小写及短名控制组；覆盖 raw、两个目录、完整 schema、Skill 发现／详情／执行和真实内部对象排除 |
| 定向回归 | 101 passed、3 skipped、27 warnings，10.38 秒；包含上一轮 48 项与适配器回归 |
| 全量 | **1222 passed、4 skipped、67 warnings，174.12 秒**；默认 MySQL opt-in 未启用。新增 legacy 案例增加 6 次既有 logging 弃用警告 |
| 类型／提示资源 | Pyright 0 errors／0 warnings，提示资源／路由契约通过 |
| 修复后隔离调用 | 与基线相同 72 次输入，12 组全部可发现／就绪／执行，合法表可见、视图保留 table-only 目录契约，内部对象仍排除 |
| 当前安装包 | 仓库外非 editable sdist／wheel，69 份资源逐项核对；真实 CLI serve、两模式 12 个私有实例共 **84 次 stdio 调用通过**，不替换产品 handler |
| 驻留 MCP | 维护者确认重启后，**16/16 次现有工具原生核验通过**：配置 1 次、SQLite 8 次、MySQL 7 次；目录、列／索引、readiness 与只读执行正常。特殊前缀案例保留隔离测试归属，此前 20/20 保留上一份源码归属。见[本次原生记录](sqlite_prefix_2026_10_15/native_after_restart.json) |

本次只修改一个生产文件（SQLite adapter），未增加协议字段或服务提示文本，版本仍为 3.8.1。现有 MySQL 源码未变，本轮不重跑其 18 次只读检查；旧记录保留原归属。原 1210 项、60／18 次与 20/20 原生证据不回写。

所有新增数据位于自动清理的私有临时目录，连接／子进程已关闭；未改现有 TOML、未写配置数据库、未创建 commit。应用结果和日志压缩保留，metadata 源码摘要集中记录；不是完整 JSON-RPC 帧，也未做模型 token／延迟成本对照。见[本批清单](sqlite_prefix_2026_10_15/manifest.json)。

## 维护者重启后的核验补记

收到维护者“已重启”后，重新调用当前 Host 注册的 SQL MCP 工具，16 次全部通过，文本 JSON 与 structuredContent 逐项一致。两个连接的 SELECT 1、表目录、orders 列／索引、对应方言 Skill 的发现／详情／执行正常，SQLite 完整 schema 正常。SQLite 月报返回 5 行，order_count 合计 5，与另行 raw COUNT 一致；MySQL 同月月报成功返回空集，raw COUNT 为 0，不将合法空结果记为失败。这 7 次 MySQL 原生调用属于本次运行核验，不新增独立适配器矩阵结果。

磁盘 69 份生产、41 份测试资源摘要均与本批已通过全量和安装包验证的快照一致；未改代码，故不重复执行已通过的全量回归。摘要比对只证明磁盘内容未变，不能证明驻留进程内已加载代码的具体哈希。当前配置没有特殊 sqliteXorders 夹具，本次原生核验也不能单独区分新旧目录谓词；该边界的直接证据来自同源码 12 项回归、修复后 72 次隔离调用和 84 次安装 CLI／stdio 调用。原生核验范围据此记录，不声称已在主会话重放该边界，亦不把重启后正常运行归因于已确认的缓存根因。

本次未写数据库、未改配置、未做模型成本复测；补录当前证据及文档状态，历史证据保持原归属。

后续维护者要求的[完整 Agent 业务任务](V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md)另批记录，包括新的模型用量和七条提交说明的增补；本页 737 字符草案、原生 16/16 及此前自动化计数均保留本批归属。
