# v3.8.1 内部读取绑定、视图 readiness 与校验结果边界（2026-10-15）

版本保持 3.8.1。维护者批准本次复评后的修复；原三项关系身份／复验抛异常／限定 readiness 的验收保留在[上一批记录](V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md)。本批补齐相邻边界，不回写原 1162 项、36／12 次和 18/18 重启记录，也不把旧驻留结果归于新源码。

## 复现、方案与取舍

| 问题／决定 | 证据与实现 | 好处 | 代价与边界 |
| --- | --- | --- | --- |
| DRR-2026-091：sample／exact_count 授权与读取对象不同，P1 | 仅允许 main.orders，主表 7、临时表 99／100；修改前采样读临时表、默认估计 1、精确计数 2。临时视图以及主表缺失时的 temp／aux 同样复现。ConnectionContext.metadata_relation 绑定结构化身份，授权和适配器渲染消费同一个对象；生成 FROM "main"."orders" | 内部读取兑现 schema 授权，行数和列定义保持同一对象；不存在时直接失败，不向其他库回退 | schema/name 分别引用；SQLAlchemy text 的冒号绑定语法单独转义。没有改写用户 raw SQL；裸 raw 引用仍遵守引擎搜索顺序 |
| 同一决定：MySQL 元数据来源绑定 | 表／列／索引／估计与关系目录通过 :schema_name 绑定配置库，内部采样／计数使用同一配置库限定名；不使用可被会话状态改变的 DATABASE() 作 metadata 作用域 | 授权、readiness 身份与 metadata 查询来源对齐 | 不能据此声称消除了 MySQL 同会话临时表遮蔽；会话重置、临时对象清理或读写连接隔离另行设计，其他 MySQL 设置／MariaDB 未实测 |
| DRR-2026-092：合法视图 Query Skill 假缺表，P2 | main.orders 为 SELECT 7 视图时 raw 成功，旧 readiness 却缺表。新增 ReadRelation(reference, kind) 与 adapter.get_read_relations，观测默认 schema 中 table／view，不采集行数估计；readiness 消费结构化身份 | 发现、详情、执行识别被授权视图，保持点号名称区分；减少 readiness 不需要的逐表估计工作 | 存在性不等于列正确、视图底层权限或可写性；表发现工具保持 table-only。新 adapter 扩展须实现 metadata_schema／get_read_relations，未加假想旧扩展兼容层 |
| DRR-2026-093：可信 Mutation 返回结构非法 | 抛异常分支已修；另有 callback 返回异常对象、非布尔 valid、非字符串数组 errors、不可序列化附加字段等形态。preview／imperative execute 共用 normalize_mutation_validation，拒绝非法结构，返回固定安全原因 | 保留 validation_failed／not_executed；预览不发令牌，执行复验失败仍消费令牌并拒绝重放；不再由该路径产生通用序列化错误 | valid 要求严格 bool；errors 若存在须为字符串 list；附加字段须能 JSON 序列化。不盲目 str 任意对象，不修改全局序列化器；可信 Python 仍不是沙箱 |

最小语义接口已在本轮补齐以上职责；完整 SQL 分析接口、方言 AST 与 SQLite authorizer 仍按原决定分阶段推进。未新增运行时依赖、工具参数或 Agent 操作步骤。schema 限定名会增加少量返回 SQL 字符，严格校验增加序列化检查；没有重测模型 token／计费或总体性能，不作成本无退化保证。readiness 减少的工作来自取消逐表行数估计，不等于已测得固定延迟收益。

SQLite 的限定名只搜索对应 schema，未限定名字按 temp、main、附加库搜索。[官方名称解析](https://sqlite.org/lang_naming.html)。视图能出现在 FROM 中，临时视图属于连接生命周期。[CREATE VIEW](https://sqlite.org/lang_createview.html)。MySQL 同会话临时表会遮蔽同名永久表；配置库限定不能被描述为全部会话对象隔离。[MySQL 官方说明](https://dev.mysql.com/doc/refman/8.0/en/create-temporary-table.html)。连接池默认回滚也不是完整资源清理保证。[SQLAlchemy reset 说明](https://docs.sqlalchemy.org/en/20/core/pooling.html#custom-reset-on-return-schemes)。

## 验证与源码归属

修改前 69 份生产资源匹配上一批快照；[源码摘要](schema_binding_2026_10_15/baseline_source.json)与压缩源码保留。两模式共 130 次 matrix 调用、22 次相邻边界调用复现问题，baseline 应用结果压缩保留。本批使用相同夹具、工具输入序列重验修复；断言从“复现”切换为“固定 schema／视图可用／安全失败”。

| 检查 | 当前结果／范围 |
| --- | --- |
| 新增回归 | 48 passed，覆盖 main／temp／aux、临时视图、主表缺失、裸 metadata grant、视图／点号身份、无估计 readiness、schema 引用及冒号、MySQL metadata 参数、两模式与两个阶段的非法校验结果／令牌状态／重放 |
| 全量回归 | **1210 passed、4 skipped、61 warnings，165.67 秒**；默认 MySQL opt-in 未启用。首次 1207 passed／3 failed／4 skipped，失败均来自旧测试期待或 mock 接口，适配后通过；新增 legacy 用例增加 21 次既有 logging 弃用警告 |
| 类型／提示资源 | Pyright 0 errors／0 warnings；提示资源与路由契约通过。沙盒内 Pyright 无法解析依赖的日志独立保留 |
| 修复后 Client 矩阵 | 两模式 130＋22 次；详见本批 after 压缩记录 |
| 非 editable 安装包 | 当前 sdist／wheel、仓库外导入、69 份资源逐项核对，**60 次 stdio 调用通过**。私有 bootstrap 只在测试服务同一连接建立同名临时表，不替换产品 handler；旧身份／复验、schema 绑定、视图与非法 callback 返回均覆盖 |
| 真实 MySQL | 隔离配置／策略对象，使用已配置测试 MySQL；两模式 **18 次 SELECT／metadata 调用通过**，包括原限定 raw／Skill／元数据与新增 sample／默认估计／精确计数。未建立真实视图或临时表，不宣称实测了这些 MySQL 边界 |
| 当前驻留 MCP | 维护者确认重启后，**20/20 现有工具原生核验通过**，17 项成功、3 项业务拒绝；文本／结构化结果 20 项一致。sample／table_summary 在当前配置关闭，未配置视图／故障 validator；这些特殊边界仍由同源码的隔离／安装夹具覆盖。见[本批原生结果](schema_binding_2026_10_15/native_after_restart.json)；旧 18/18 保留上一份源码归属 |

首次全量的三处适配：MySQL metadata 参数增加 schema_name；readiness failure mock 从 get_tables 改为 get_read_relations；sample SQL 期待增加 main。既有定向组在沙盒中停滞，以 SIGINT 退出；默认全量 opt-in MySQL 未启用，获准环境完成回归。安装 harness 读取 SDK 旧 protocolVersion 属性的弃用警告不归为产品失败，legacy Client 未公开 initialize_result 时仍记录 null。

所有夹具为临时目录／临时进程，均关闭并清理；未修改现有 TOML，未写配置数据库，未创建 Git commit。公开输入／应用结果／失败日志压缩保存，不包含完整 JSON-RPC 帧、全部通知或模型 usage；令牌材料省略并标注。新[manifest](schema_binding_2026_10_15/manifest.json)关联当前源码和验证层级，旧批次保留原归属。

## 维护者重启后的驻留核验完成

维护者确认重启后，当前 Codex 主会话注册工具可调用；MySQL／SQLite 常量查询、两库 Skill 发现／详情／执行、表目录与列／索引／完整 schema，以及点号名称拒绝、引号内部空白 CTE、SLEEP／GET_LOCK 拒绝共 20 次检查通过。17 次成功、3 次业务拒绝，无 ToolError，全部文本与 structuredContent 一致。

月报再用同条件 raw COUNT 独立核对：SQLite 2026 年 1 月 5 单；MySQL 同期 0 单，Skill 空结果是合法业务结果。该检查不需要写入或调用 Mutation。原生返回数据不单独证明某条路径在数据库访问前拒绝，执行前顺序继续由回归／隔离 SQL 轨迹支持。

本地主配置 tools.schema=false、tools.table_summary=false，与当前 Host 未注册这两项一致。主会话没有本批视图／故障 callback 夹具；不能把 20 次结果写成已在主会话重放全部修复场景，也不单凭没有变化的公共返回证明进程内代码对象身份。69 份生产资源和 40 份测试资源仍匹配 1210 项、60 次安装包快照；这里的 SHA-256 核对针对磁盘／安装包。维护者重启事实、现有工具健康核验与特殊场景的匹配源码证据共同完成本轮已批准验收范围。

本次仅追加文档和证据，没有改源码、配置、数据库或版本，没有重跑已通过的全量／类型／安装检查。原 18/18 与此前缓存根因未知的记录保留，不推断这次成功证明此前由缓存造成。生产 AST／authorizer、MySQL 临时对象／会话生命周期、更广实例与模型成本仍按原决定另行推进。
