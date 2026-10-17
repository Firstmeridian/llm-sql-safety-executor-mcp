# v3.8.2 EXPLAIN 触发器与 SQLite DML 语法补修（2026-10-17）

> 后续状态：新增确认触发器子查询局部 CTE 计数误拒，DRR-108 对此边界重开后已补修，限定重启验收 57 项通过，见[局部 CTE 补充验收](V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md)。下文 2067 项回归、272 次安装及原生 42/42 保留当时源码范围，不代表新增边界的证据。

本批承接[读取边界验收](V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md)，修复后续复评确认的三类 P2。版本仍为 v3.8.2，不改配置、依赖、授权声明、Mutation 审批或 Agent 必需步骤。DRR-108 经复评重开并补修，现已按验证范围关闭：源码、最终 wheel 及维护者重启后的原生 42/42 核验通过。旧 28/28 保留原源码归属，不代替本批新观察。

## 问题与方案

| 问题 | 修复前 | 本批方案与收益 | 代价／限制 |
| --- | --- | --- | --- |
| 触发器 READ | NEW/OLD、WHEN、授权表、嵌套及 INSTEAD OF 触发器被当作未知来源 | 已确认的非执行型 DML 计划按 SQLite 实际 schema/name 检查直接 grant；触发器名不产生 grant | 普通 SELECT 来源约束不放宽，实际 DML 仍拒绝 |
| COUNT 与触发器视图 | 空列 READ 缺少 database；触发器引入的视图未准备依赖边 | 准备拒绝后，在回调外补查目录绑定／授权视图边，再准备原 SQL；NULL 数据库的候选包括未授权同名对象 | 增加目录／准备工作，main/temp/aux 无法唯一绑定时拒绝 |
| 视图 COUNT 来源丢失 | 底表额外 READ 可能被标成触发器来源 | 分离所需触发器目录定义的 WHEN 与 BEGIN...END 语句，交共享 SQLGlot 核验依赖；视图边不能借给另一条直接底表计数 | 支持子集，不是通用触发器语义引擎；不完整分析明确拒绝 |
| WITH 后 REPLACE | 首 token 适配遗漏 WITH 后主语句，包括多／嵌套／RECURSIVE、RETURNING、注释、DEFAULT VALUES | SQLite parser 的实际 statement dispatch 接受 REPLACE，分析成 INSERT 形；保留函数、CTE 名、字符串与原 SQL | 不做全局替换，MySQL 适配独立保留 |
| UPDATE OR 冲突子句 | 五类选项及前置 WITH 均 sql_parse_failed | 只在 SQLite UPDATE 位置识别 ROLLBACK/ABORT/FAIL/IGNORE/REPLACE，再分析真正目标和表达式 | 3323f9c 在 all 模式成功，但 allowlist 本来也拒绝，不能全部称为新增回归 |

采用按需准备，避免枚举并解析全库无关触发器／视图。回调仅记录缺少的绑定并返回 DENY，不执行 SQL；固定目录操作在回调返回后完成，同一连接独占锁覆盖全部准备。只有已确认、绑定原 SQL／上下文的非执行型 DML 计划能使用此流程。

每请求累计最多 2048 次名称目录查找、128 个新增准备请求；保留每个来源图最多 128 个视图／1024 条边。重试必须增加信息；歧义、无进展、超时或超预算均拒绝。共享单调时钟截止时间，准备后执行前再检查；授权图不跨请求复用。来源标签与 CTE／视图／触发器发生无法区分的冲突时保守拒绝。

## 验证状态

| 层次 | 结果与范围 |
| --- | --- |
| 新增回归 | 101 项通过；三类修复、视图计数、WHEN／直接底表拒绝、来源冲突、aux/temp、回调无 SQL、参数、实际 DML 与清理 |
| 全量 | **2067 passed／4 skipped／144 warnings**；跳过为可选 MySQL，警告为既有 MCP logging 弃用提示 |
| 类型／提示 | Pyright 0 errors／0 warnings；提示资源／路由契约通过 |
| 同输入矩阵 | 前后各 342 次 Client；修复后 292 次计划成功、42 次预定拒绝、8 次独立授权范围对照。两协议／两种前缀类别一致；完整私有数据未变，函数零调用 |
| 源码 child stdio | 修改前 132 次／修改后 140 次符合预期。差额为两个 Skill 修复前被启动校验跳过，修复后各多详情／执行；不是成本对照。覆盖 raw／发现／readiness／参数化 Skill／执行及连接 total_changes 不变 |
| 最终 wheel | 仓库外独立安装，真实 stdio 新增 140＋既有读取边界 74＋既有语义 58＝272 次；75 项运行资源与完整回归源码一致。通用 CLI／Prompt／两协议烟测通过 |
| 当前 Host | 维护者确认重启后原生 42/42 符合预期：26 项计划、12 项拒绝、1 次预检、1 次元数据及前后两次完整快照。五行全部五列不变；触发器专用夹具保留回归／安装覆盖 |

342 次中的两组早期夹具使用限定 SQL＋裸 grant，8 次按项目独立授权规则拒绝，属于范围对照。聚焦矩阵另用正确限定 grant，验证这两例已修复。总调用数不等于通过率，既有夹具授权／配置错误也不算产品缺陷。

## 串行成本

同脚本、同私有库，独立进程按前源码 A1 → 新源码 B → 前源码 A2 串行执行，无并发重回归／构建。每类预热三次后留 41 次，包含策略分析、adapter 准备和取完结果，不含 MCP／Host／模型。

| 工作负载 | A1 median/p95 ms | B median/p95 ms | A2 median/p95 ms | 解释 |
| --- | ---: | ---: | ---: | --- |
| 普通读取 | 0.666/1.345 | 0.672/1.273 | 0.697/1.306 | 均成功，有基线漂移，不承诺零开销 |
| 普通 UPDATE 计划 | 0.699/1.333 | 0.750/1.418 | 0.766/1.157 | 均成功，一次准备、两条目录语句 |
| 触发器视图 COUNT | 0.726/1.419 | 3.062/4.809 | 0.709/1.179 | 原拒绝、现成功；新实现三次准备、14 条目录语句 |
| WITH REPLACE | 0.367/0.684 | 3.747/5.934 | 0.391/0.663 | 此夹具也触发视图 COUNT，现三次准备、17 条目录语句 |
| UPDATE OR IGNORE | 0.205/0.351 | 0.894/1.419 | 0.206/0.386 | 原解析失败、现成功，一次准备、两条目录语句 |

后三项前后功能结果不同，不是等工作量开销比较。小型本地结果不是生产延迟或 token 保证。前批 15 个 Luna trial 的失败、完成率与用量保留其源码归属；本批未重新运行完整 Luna 任务。

## 限制与保留记录

- schema/UDF/Python 扩展仍可信；编译授权不保证所有表达式每次求值都再授权，例如已加载生成列。MySQL 没有等价 authorizer，本批不扩大其保证。
- 只创建自动清理的私有夹具，不执行配置库业务写入，不改变预览令牌、审批、审计或事务 outcome。
- 保留最初新回归失败、首版修复遗漏触发器视图 COUNT、超时断言及首次 stdio 使用错误 allowed_connections 字段的日志。依赖核验／执行前截止时间检查补齐，夹具改用现有 connection_ids 后通过。夹具错误不归为产品缺陷。
- 本机运行 venv 没有 hatchling，直接 no-isolation build 失败；复用已有 uv 和正确的离线缓存后，sdist→wheel 构建／独立安装通过。错误缓存路径的失败也保留，不向运行依赖追加构建后端。
- 不重写先前 manifest／日志／失败；应用结果 JSON 不等同完整协议帧或通知。

## 复现与证据

### 维护者重启后的原生核验

维护者明确确认重启后，在当前 Codex SQL MCP 固定使用 analytics_demo_sqlite。记录始于 2026-10-16 19:26:52 UTC（北京时间 10 月 17 日），42/42 符合预期，所有文本／结构化结果一致。

- 26 项计划：普通 UPDATE、五种 UPDATE OR、WITH UPDATE OR IGNORE，以及单／多／嵌套 CTE、RECURSIVE 前缀、RETURNING、同名 CTE／replace()／字符串、注释及 DEFAULT VALUES 的 REPLACE；均覆盖 EXPLAIN 和 EXPLAIN QUERY PLAN。空计划保持成功。
- 12 项拒绝：四条带 WHERE 0／空输入的实际 DML 形态、未授权计划目标、点号身份、temp 范围、耗时／锁调用、EXPLAIN ANALYZE 与禁用 UNION。
- SELECT 7 预检、一次 describe_table 和前后两次按 id 排序的完整快照；五行全部五列相同。未执行真实业务 Mutation，未改变配置或新增对象。

原生没有新增触发器／视图／UDF／计划 Skill 夹具，相关细节仍以同源码回归与 140 次新增安装 stdio 为据（安装总数 272）。Host 未暴露 sample／table_summary 或协商协议版本，不套用独立 Client 的协议，也不把可调用工具目录当作驻留代码对象摘要。未追加完整 Luna trial、模型 token 或原生延迟基线。

原生[独立清单](v382_explain_followup_2026_10_17/resident_restart/manifest.json)与[核验摘要](v382_explain_followup_2026_10_17/resident_restart/verification.json)追加在 resident_restart。父批 50 项封存文件（含当时 pending 状态）原字节保留；本次同时验证更早 245 项原始证据未变。75 项磁盘运行资源仍与完整回归／安装闭包一致，但未读取驻留进程代码对象摘要。DRR-108 按上述源码、安装和原生范围关闭，不宣称所有 SQLite 语法或来源歧义均受支持。

### 脚本与前置检查点

- `scripts/validation/sqlite_plans.py --source <src> --expect before|after --output <新文件>.json.gz`：真实 child stdio；独立 wheel 环境省略 --source，从仓库外运行。
- `scripts/validation/sqlite_plan_cost.py --source <src> --stage A1|B|A2 --output <新文件>.json.gz`：串行策略／adapter 成本。
- 本批[证据清单](v382_explain_followup_2026_10_17/manifest.json)与[源码归属](v382_explain_followup_2026_10_17/source_closure.json)，前批由原报告导航。

官方依据：[SQLite EXPLAIN](https://www.sqlite.org/lang_explain.html)、[authorizer](https://www.sqlite.org/c3ref/set_authorizer.html)、[回调参数](https://www.sqlite.org/c3ref/c_alter_table.html)、[触发器](https://www.sqlite.org/lang_createtrigger.html)、[冲突处理](https://www.sqlite.org/lang_conflict.html)。计划仍触发编译授权，不能豁免 PRAGMA；NULL／空列／来源角色、回调不重入及 UPDATE OR 词汇按实际方言核验。
