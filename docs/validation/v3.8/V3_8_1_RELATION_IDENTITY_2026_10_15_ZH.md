# v3.8.1 关系身份、Mutation 复验与 schema readiness 修复（2026-10-15）

版本保持 3.8.1。维护者批准修复外部复评指出的三项问题；本轮不接入生产 SQLGlot AST／SQLite authorizer，不增加旧部署／SDK／假想调用方兼容层，不修改现有数据库或配置。

## 独立复现与修复

修改前，68 份生产源码摘要匹配 10 月 14 日的 1114 项最终快照。隔离 SQLite 与真实 in-process FastMCP Client 在 legacy／auto 各 19 次、合计 38 次调用中复现三项问题；[修改前记录](relation_identity_2026_10_15/baseline_v381_review_20261015.json)与[源码摘要](relation_identity_2026_10_15/baseline_source.json)保留。af3420f 的 extractor 也把限定／单个点号名称投影成同一字符串；[历史检查](relation_identity_2026_10_15/baseline_v381_review_20261015_historical.json)使用当前导入依赖，不冒称旧版本全量 Host 实测。

| 问题 | 原因与表现 | 本轮实现 | 收益与代价 |
| --- | --- | --- | --- |
| P1 限定名与内部点号混淆 | main.orders 和 "main.orders" 被合并成同一授权字符串，原生分别返回 7／99 | RelationReference 保存 schema/name；解析、授权、推断缓存与 readiness 保留组件身份，展示字符串只用于结果和诊断 | 避免不同实体共享授权；增加内部对象／缓存和调用点适配，没有生产 AST 依赖 |
| P2 Mutation 消费令牌后复验抛异常 | _handle_error 改为类型化异常，异常对象进入 validation.errors，触发序列化错误 | 先用适配器固定消息脱敏，再转换字符串；预览异常分支也显式适配 | Host 得到 validation_failed／not_executed，保持准确令牌状态；继续消费一次性令牌并拒绝重放，不自动恢复它 |
| P2 限定 Skill 假缺表／错误匹配 | 裸名快照与拼接依赖混用；只有 orders 时假缺表，存在字面 "main.orders" 时又错误通过 | 快照带当前默认 schema；依赖按结构化身份比较；其他 schema 标为 unverified_tables | 恢复合法限定 Skill，与 raw 一致；默认快照只覆盖 SQLite main／配置的 MySQL database，跨 schema 不冒称已核验 |

系统库检查也使用真正的 schema 组件；SQLite 的业务实体 "information_schema.orders" 不等于 information_schema.orders。非执行 EXPLAIN／DESC、IN／NOT IN 和 CTE 沿用同一关系 walker；不把解析不完整视为已授权。元数据过滤将已解码裸表名绑定到其已知默认 schema，允许精确的限定 grant 发现／描述该表，同时不会将字面点号名字错配到该 grant。

## 名称声明与支持边界

配置 read.tables 与 Skill 声明 tables 继续使用字符串；它们不是 SQL 引用语法，保留空白和引号字符。第一个点分开 schema 与剩余 name，SQL 则直接从原始 token 得到组件，不能重新按字符串分割：

| 声明 | 能授权的 SQL 引用 | 不隐式授权的引用 |
| --- | --- | --- |
| orders | FROM orders | FROM main.orders |
| main.orders | FROM main.orders／FROM "main"."orders" | FROM "main.orders"／FROM main."main.orders" |
| main.main.orders | FROM main."main.orders" | FROM "main.orders"／FROM "main.main".orders |

完整支持任意带点 schema 的配置表达不在本轮；明确的组件身份可保守拒绝不能表达的授权，不能从字符串相等推导身份等价。物理拼写／ASCII 比较与 MySQL CTE 能力仍独立。SQL 原文执行，引号内部空白、转义与 Unicode 不被重新改写。

readiness.check_schema=true 时，当前快照覆盖 SQLite main／配置的 MySQL database。未限定依赖按这个默认快照做可用性观察；这不是 SQLite temp／attached 搜索顺序或完整 SQL 可执行性的证明。显式其他 schema 的依赖返回 unverified_tables、schema_check_available=false，发现可说明不可用，执行仍拒绝无法核验；不会用 main 的同名表证明 aux／temp 的对象存在。关闭 readiness 不扩大读授权。

full Skill 条目补齐 schema_check_enabled／schema_check_available、missing_tables／unverified_tables；空数组也明确返回。新增输出有少量返回字节成本，服务端有结构化对象比较成本；工具参数、Agent 调用步骤和运行时依赖不增加。本轮没有重测模型 token／计费／总体性能，不能把早期 Luna 和成本结论归给这份新源码。

SQLite 名称解析按数据库和对象共同识别，Pydantic 不会自动将任意异常对象转为 JSON。[SQLite 名称解析](https://sqlite.org/lang_naming.html)、[Pydantic 序列化](https://pydantic.dev/docs/validation/latest/concepts/serialization/#json-mode)支持这些边界。SQLGlot 试验里的字符串投影仍只作展示／对照，不是生产授权；后续接入需要结构化接口和方言适配。[SQLGlot 官方 FAQ](https://sqlglot.com/sqlglot.html#faq)说明解析成功不等于服务器接受。authorizer 的 prepare／缓存／连接生命周期另行设计。[SQLite authorizer 说明](https://sqlite.org/c3ref/set_authorizer.html)

## 验收与证据

| 检查 | 结果及范围 |
| --- | --- |
| 新增定点回归 | 48 项通过，覆盖三种引用符、限定／内部点号、CTE／IN、真实与字面同名表、大小写、两模式发现／详情／执行／元数据、其他 schema 无法核验、三类复验异常及令牌重放 |
| 完整回归 | **1162 passed、4 skipped、40 warnings，134.84 秒**；MySQL opt-in 关闭。警告来自既有协议 logging 路径，新增 legacy 用例增加次数 |
| 类型／提示契约 | Pyright 0 errors／0 warnings；提示资源／路由契约通过 |
| 当前安装包 | 仓库外非 editable sdist／wheel，逐文件匹配 69 份包源码／提示资源；两模式共 **36 次真实 stdio 调用**，见[安装包结果](relation_identity_2026_10_15/installed_wheel.json) |
| 真实 MySQL | 隔离目录／配置对象中的限定只读 grant，raw／发现／详情／Skill／元数据两模式共 **12 次通过**，见[结果](relation_identity_2026_10_15/live_mysql.json)；未改现有 TOML，未写实库 |
| 主会话状态 | 维护者重启后 **18/18 原生核验通过**，其中 8 项业务拒绝、10 项成功，18 项文本／结构化内容一致。拒绝指纹从旧 system_schema_denied 变为 table_access_denied；full Skill scope 字段已出现。见[当前原生记录](relation_identity_2026_10_15/native_after_restart.json)，独立 Client／wheel 证据保留 |

原 1114 项、10 月 14 日 11/11 原生结果及模型／成本记录保留，不回写旧通过数。维护者提供的外部报告称 10 月 15 日此前重启后 7/7 原生通过；本轮未独立读取其原始帧，按外部报告标注，不当作本次改代码之后的重启证据。旧状态差异原因仍未确定，不能写成已确认由缓存导致。

首次新增回归发现 full 投影缺少 schema 核验字段并予以补齐。首次全量 1159 passed／3 failed，失败来自缺少 MySQL database 或仍用裸字符串的模拟快照；更新夹具后 4 个定向用例及最终全量通过。默认沙盒的旧定向组停滞后以 SIGINT 结束；沙盒内 Pyright 无法读取已装依赖，获准环境通过。首次 wheel 业务检查通过后，harness 读取 legacy Client 不提供的 initialize_result 失败；改为记录未观察到的协议字段，重新验证通过。失败日志独立保留。

新[证据清单](relation_identity_2026_10_15/manifest.json)记录采集层级、源码与日志摘要；应用结果／压缩日志不是完整 JSON-RPC 帧，legacy Client 未暴露协议版本时保留 null 而不猜测；预览令牌材料省略并说明。DRR-2026-088–090 记录本轮三项决定。未创建 Git commit。

## 最后维护者重启与原生验收闭环

维护者确认重启后，直接使用当前 Codex 主会话的 SQL MCP 完成 18 次调用：配置发现 1 次、读取／拒绝／CTE／普通数据与函数、Skill 发现／详情／执行、表列表／结构化列与索引。8 次业务拒绝、10 次成功，无 ToolError；所有文本与 structuredContent 一致。MySQL F/f CTE 返回 8，SQLite 月报返回 5 行，新 full readiness 字段和空数组均可见。69 份生产文件 SHA-256 仍匹配 1162 项与 36 次安装快照，本次未改源码、配置或数据库，无须重复全量回归。

第一条身份指纹由重启前 system_schema_denied 变为 table_access_denied，证明该次调用使用新关系分类；不据此推断此前差异的缓存根因。元数据调用成功返回 indexes_status=complete，harness 最初错误期待 available／unavailable；读取现行 complete／unavailable 契约后重验同一记录通过，无重复工具调用，初始断言失误保存在原生 JSON。

主会话的现有别名没有隔离夹具中的限定 grant／故障 validator，因此这 18 项不冒称在主会话直接重放了全部三项夹具。三项完整正反例由相同源码的 48 项回归、安装包 stdio 和隔离策略的真实 MySQL 共同覆盖；主会话补齐最后的新策略／接口行为。前一轮外部报告 7/7、10 月 14 日 11/11、重启前结果及失败试验均保留原归属。当前批准的修复与验收范围完成；生产 AST／authorizer、其他 MySQL 设置／MariaDB 与更广模型成本仍按既有决定另行推进。
