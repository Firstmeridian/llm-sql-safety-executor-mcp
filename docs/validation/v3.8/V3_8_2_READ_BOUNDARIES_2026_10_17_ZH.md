# v3.8.2 视图读取边界与非执行型 EXPLAIN 补修（2026-10-17）

> 后续状态：本页保留前批源码与重启观察。后续复评确认触发器 READ、WITH REPLACE、UPDATE OR 遗漏，DRR-108 曾重开，后续补修及重启核验现已完成；修复及新源码状态见[计划后续报告](V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md)。历史原始证据不改写。

基于维护者尚未提交的 v3.8.2 工作树继续修复，版本保持 3.8.2。维护者批准补齐外部评审复现的两项 P2。前批“批准范围完成”只代表当时所测范围，本批明确补齐此前遗漏，不覆盖前批证据。

**当前状态：源码、安装包及维护者重启后的限定范围验收完成；原生 28/28 检查符合预期，数据快照不变。** 尚未替维护者暂存或提交。本批未新增完整 Luna 业务任务或模型 token／延迟成本对照，前批结果保留其源码归属。

## 问题、方案与取舍

| 问题 | 原行为／独立复现 | 补修 | 好处与代价 |
| --- | --- | --- | --- |
| P2：元数据工具中的数据读取未激活 authorizer | 在 auto/legacy 下，授权视图的 SLEEP 测试函数被 query 拒绝且零调用，但 sample、精确计数、默认估算和 describe_table 各调用一次。内置 pragma_database_list 视图也出现入口差异 | sample 与精确计数调用 execute_read；SQLite 有界估算也进入读取 guard。固定目录、索引与 sqlite_stat1 查询保留可信边界 | 不再把固定 SQL 模板等同于不求值业务表达式；增加分析和目录准备工作，不新增 Agent 必需工具调用 |
| 正常视图计数的相邻兼容边界 | COUNT 可能额外发出 database=null、空列、来源为空或外层 CTE 的底表 READ；简单接线误拒普通视图 | 激活回调前先核验所有分析根关系；只对唯一解析、属于已授权视图来源图的这类附加事件接受丢失的来源；真实 READ／函数仍检查 | 视图 grant 保持可用；直接底表、混合标量子查询和其他根关系不继承该 grant；歧义仍拒绝 |
| 估算模板与目录投影 | 旧 FROM 派生表模板不属于当前完整分析子集；目录可以先枚举后过滤授权 | 改为 LIMIT 10000 的内部 CTE，并 COUNT 非空 marker；估算在读取目录／数据前核验配置授权，未授权不采样。内部 CTE 避免与所选对象同名 | 不放开公开 query 的 FROM 派生表限制，不升级为全表 COUNT，不把内部名称保留为业务禁用名称 |
| P2：非执行型 DML EXPLAIN 回归 | UPDATE／DELETE／INSERT 计划在 3323f9c 和原生 SQLite 成功，v3.8.2 authorizer 默认拒绝；数据未变 | SQLAnalysis 明确携带 explain_payload；SQLite 仅对已确认的 INSERT／UPDATE／DELETE 计划允许相应编译事件，逐个核验实际目标。分析绑定原 SQL 和方言上下文 | 恢复计划功能；不关闭 authorizer，不允许实际写入，也不将 EXPLAIN 前缀当作通用豁免 |
| REPLACE 计划的相邻解析遗漏 | SQLite EXPLAIN／EXPLAIN QUERY PLAN REPLACE 在前批 v3.8.2 被解析失败；实际 SQLite 支持 | 去掉解释前缀后，在真正的语句槽将 REPLACE 投影为 INSERT 形 AST；仍执行原始 SQL | 恢复同类 DML 计划；不是 SQL 转译，也不允许实际 REPLACE |

固定目录查询仍需要读取内部 PRAGMA 表值函数。将所有元数据 SQL 一律套用公开 query 策略，会破坏正常内省；本次仅将会求值业务数据的读取纳入 guard。SQLite 特有的 authorizer 不能扩展宣称为 MySQL 的视图函数执行保证。

估算被受限函数、受限来源或无法核验的读取边界拒绝时，行数返回 null，列和索引仍可用；null 表示未知，不是零行。真正的目录读取失败仍保持元数据错误，不伪装成空结果。SQLite 视图内 PRAGMA 来源被识别为 server_state_denied，不再误报为该保留来源不存在。

## 验收结果与证据范围

| 验证 | 本批结果与范围 |
| --- | --- |
| 独立评审对照 | 当前补修前源码与 3323f9c 各 44 次 Client 调用，两种模式；私有夹具数据不变。之前评估记录保留在本批 evidence 中 |
| 定点回归 | 新增 70 项：两模式、裸／限定授权、七类保留调用与内置 PRAGMA 来源、正常视图与计数、内部 CTE 同名业务对象、未授权预估、DML／REPLACE 计划及状态不变 |
| 最终全量、类型与提示契约 | 1966 passed／4 skipped／114 warnings；Pyright 0 errors／0 warnings；提示契约通过。前批 1896 和中间 1958 结果保留各自范围 |
| 安装包／真实 child stdio | 最终 wheel 两模式新增边界 74 次＋既有语义 58 次＝132 次调用通过；75 项运行资源与最终源码一致。修复前同脚本 74 次对照与前批 75 项资源一致；CLI check/explain 通过 |
| MySQL 只读 | 12 次源 Client 只读调用，两种模式；sample 与同 SQL query 一致，精确计数与 query 一致，列元数据可用；未创建对象或写入数据 |
| 当前驻留 Host | 维护者确认重启后，本批 28/28 检查符合预期；9 次非执行型 DML／REPLACE 计划、正常元数据／CTE 计数及 12 项拒绝对照通过；前后五行全部五列一致。未暴露入口保留安装覆盖，不把前批 Host 5/5 改标为本批 |
| 完整模型任务与成本 | 本批未重跑；前批 15 trial／42 轮跨源码批次的结果、失败、评分限制和成本漂移原样保留，不改标为本批模型验收 |

证据目录：[v382_read_boundaries_2026_10_17](v382_read_boundaries_2026_10_17/)。新增清单独立封存；[前批清单](v382_2026_10_16/manifest.json)及 CTE 计数补修清单保持原字节。应用结果记录包含请求、text／structured 返回和源码摘要，不包含完整协议帧、通知或原始字段省略差异。

可复用脚本：`scripts/validation/read_boundaries.py --source <frozen-src> --expect before --output <new>.json.gz` 重放补修前 v3.8.2；新安装 wheel 的独立解释器去掉 --source 并使用默认 --expect after。全部数据库、配置及无害函数属于自动清理的私有夹具。SLEEP 仅增加计数并返回零，不执行延迟；视图将调用放在 WHERE 中，避免计数时被投影裁剪而产生虚假的零调用结论。

当前 Host 工具目录仍未暴露 sample／get_table_summary；这些入口由同源码的真实 child stdio 及回归覆盖，不能用原生 query 成功替代。维护者确认重启后，已核验 Host 可用的 query、describe_table、list_tables 和拒绝对照；未新增原生受限函数视图夹具，也未修改工具配置。

## 保留的失败、限制与决定

- 初次定点接线暴露估算模板解析失败、视图额外计数 READ 误拒及旧测试未配置读取授权；修复模板／计数事件并显式配置测试授权后通过，保留中间失败日志。
- 沙盒内 Pyright 看不到已安装依赖，stdio 子进程启动后未完成握手；中断沙盒内停滞回归，使用获准的命令级权限重跑。不得把环境失败算成源码通过，也不据此断言具体系统调用或 Host 缓存根因。
- SQLite EXPLAIN 仍会触发编译期 authorizer。只放开已确认计划所需的三种 DML 编译事件；PRAGMA、DDL、ATTACH、事务及其他默认拒绝不获得豁免。触发器或关联计划涉及未授权实际目标时，计划也可被拒绝。
- SQLAnalysis 必须与原 SQL 和方言上下文一致；不能把 EXPLAIN 分析对象复用于实际 UPDATE。回调、超时、连接独占和结果消费范围不缩短。
- 在根关系已全部核验后恢复视图计数来源，不等同于把依赖边变为全局 grant。跨 schema／目录／来源歧义继续保守拒绝。
- 本批不增加解析器框架、开关、运行依赖或配置项。估算最多计数 10000 条匹配记录，仍不保证数据库只扫描 10000 条底层记录或所有同步函数可被强制打断。可信 schema／UDF／Python 边界不变。
- 新增数据读取 guard 带来解析、目录及回调成本；未用前批计时或字符数量证明本批零开销／零 token 增量。真实写入审批与事务 outcome 不变，未写入配置中的业务数据库。

## 官方依据

- [SQLite EXPLAIN](https://www.sqlite.org/lang_explain.html)：改变执行行为，不取消编译期 authorizer；部分 PRAGMA 在准备阶段生效，因此不应因 EXPLAIN 而放行。
- [SQLite authorizer action codes](https://www.sqlite.org/c3ref/c_alter_table.html)：按实际操作、对象、数据库及来源核验。
- [SQLite authorizer 生命周期](https://www.sqlite.org/c3ref/set_authorizer.html)：编译／重编译期间生效，保留到取完结果；COUNT 的空列事件不代表可以跳过关系授权。

决议：DRR-2026-107、108。优先修复现有执行边界与同类兼容遗漏，不新建通用框架；本批按已暴露的原生入口及同源码安装包覆盖完成验收；保留未暴露入口与完整模型／成本未重测的范围说明。


## 维护者重启后的原生核验（2026-10-17）

维护者明确确认 MCP 已重启后，通过当前 Codex 原生 SQL MCP 通道执行。记录时间为 2026-10-16 18:03:30 UTC（北京时间 10 月 17 日）；目标固定为 analytics_demo_sqlite。仅有工具目录不足以证明可调用，先以 SELECT 7 确认可用，再执行此前误拒的 EXPLAIN QUERY PLAN DELETE；本次成功，且空计划被正确保留。

| 检查组 | 调用数 | 结果 |
| --- | --- | --- |
| 通道检查与前后完整数据快照 | 3 | SELECT 7 成功；orders 前后五行全部五列完全一致，规范化摘要一致 |
| 普通表元数据 | 2 | describe_table 的行数估算为 5、列和索引可用；list_tables 只显示授权 orders，估算为 5 |
| 非执行型计划 | 9 | 两种前缀 × UPDATE／INSERT／DELETE／REPLACE 共八次，加 UPDATE RETURNING；均成功。QUERY PLAN 的零行计划是合法结果，不要求固定 opcode 或非空输出 |
| CTE 计数 | 2 | 物化 CTE 及有界 marker 计数均为 5，保留前批计数修复 |
| 拒绝对照 | 12 | 实际 DML 形态四次均带 WHERE 0 并被 read_only_required 拒绝；保留 SLEEP、GET_LOCK、PRAGMA 来源、未授权读取／计划、计划内 SLEEP 以及 PRAGMA／DDL 解释的拒绝 |
| 合计 | 28 | 28/28 符合预期；其中 12 次预期拒绝，不称为所有请求执行成功。全部 text 与 structured 返回一致 |

原生记录及独立封存清单位于 [resident_restart](v382_read_boundaries_2026_10_17/resident_restart/manifest.json)。父批 25 项封存文件保持原字节，原 verification.json 中“待重启”是当时检查点，不覆盖为后续结论；当前状态以本补充 verification 为准。75 项磁盘运行资源仍与最终全量／安装批一致，但未读取驻留进程的代码对象摘要，不把磁盘一致性当成进程内逐对象证明。原生通道未暴露协商协议版本，未套用独立 Client 的两协议版本。

sample／get_table_summary 不在当前 Host 暴露集合中，也没有原生受限函数视图夹具，因此跨入口零函数调用等细节仍来自同源码安装包与回归。未运行新的完整 Luna 业务任务、模型 token 或成本对照，也未新增业务数据库写入。此次只更新文档和证据，不修改运行代码，无须因这些归档动作再次重启。
