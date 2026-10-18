# v3.8.2 SQLite 操作数 COLLATE 兼容补修（2026-10-18）

承接 [e49cd0e 最终复核](V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md)。维护者请求现在修复后，已在 SQLite 方言适配层恢复 IS／IS NOT 的 NULL、参数右值，并补齐同层发现的 LIKE ESCAPE 右值。版本仍为 **v3.8.2**，SQLGlot 仍固定 **30.22.0**。

源码、独立安装包及维护者重启后的 **25/25 项限定原生复验**均通过；DRR-109 状态为“已补修；限定驻留复验通过”。重启前四个定点请求的解析拒绝保留在父检查点，重启后结果另行封存。DRR-108 保持此前的限定关闭。

后续确认完整 ISNULL／NOTNULL／NOT NULL、IN／NOT IN 判断后的 COLLATE 仍有既有误拒，登记独立开放 DRR-110，见[相邻复评](V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md)。本报告的关闭范围限于已实测的 IS／ESCAPE 操作数，不代表完整 COLLATE 语法支持。后续 DRR-110 已获准[补修](V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)，源码／安装及维护者重启后的 71/71 项限定原生复验通过，按记录范围关闭。

## 原因、实现与取舍

| 原问题 | 本次方案 | 收益与边界 |
| --- | --- | --- |
| 上游 IS 的 NULL／placeholder 快捷分支未消费后续 COLLATE | SQLite Parser 只对这些右值使用既有表达式优先级解析；其余 IS 形态继续委托上游 | 保持 COLLATE 修饰右操作数，不移到整个判断；普通、NOT、DISTINCT、布尔及已加括号对照保持各自语义 |
| 同层 ESCAPE 的字符串／NULL／参数快捷分支也遗漏 COLLATE | SQLite ESCAPE 右值同样按表达式优先级消费 | NULL、字面量、参数和合法组合表达式恢复；真实关系和函数仍进入共享分析 |
| 合法语法恢复可能隐藏依赖或改变执行语句 | 保留原 SQL／参数，执行原有结构化读取策略及 authorizer | 隐藏底表、SLEEP／锁／文件／账户调用、真实 DML、缺少操作数及多语句继续拒绝；视图 grant 不变成底表直接 grant |

生产仅 `core/analysis.py` 相对 e49cd0e 改变。没有修改 MySQL 解析类、全局第三方包、依赖、配置、授权、审批、缓存／连接预算或数据库数据。没有正则补括号、AST SQL 重生成或 authorizer 豁免。

这次增加的是既有 SQLite 表达式入口的解析工作，没有新数据库探测或 Agent 必需工具调用。未做新的模型／服务器成本 A/B，不承诺零 CPU、零延迟或 token 改善。升级 SQLGlot 时须重验这两个适配入口；`complete` 仍只表示项目分析完整，不是数据库语法证明。

优先级依据见 [SQLite 运算符说明](https://www.sqlite.org/lang_expr.html#operators_and_parse_affecting_attributes)：COLLATE 是高于 IS 的后缀运算符。原生及应用对照继续保留 `'A' IS 'a' COLLATE NOCASE` 与 `('A' IS 'a') COLLATE NOCASE` 的不同结果。

## 验证

| 层次 | 最终结果与范围 |
| --- | --- |
| 新增回归 | **100 passed**：原始 NULL 例、IS NOT、三种内置 collation、AST 结合位置、条件／投影／CASE／CTE、NULL／字符串参数、普通视图、触发器 WHEN、两种 EXPLAIN、发现／详情／readiness／执行及必要拒绝 |
| 同输入前后 | 20 条 SQL × auto／legacy＝每版 40 次；e49cd0e 为 14 次成功、26 次解析拒绝，最终为 **40/40 成功**。所有合法输出匹配独立 SQLite 真值；这是定点恢复矩阵，不是真实任务失败率 |
| 全量 | **2375 passed／4 skipped／284 warnings，157.85 秒**；跳过是可选 MySQL，警告为既有 MCP logging 弃用 |
| 类型／提示 | Pyright 0 errors／0 warnings；当前提示资源和路由契约通过 |
| 当前源码真实 child stdio | **96 次**，两个协议均通过，含 NULL／ESCAPE、参数化 Skill、readiness、视图／临时对象及必要拒绝 |
| 当前独立 wheel | 语义 96＋既有触发器 CTE／WHEN 254＋计划／Skill 140＝**490 次**；通用 CLI／Prompt／两协议 smoke 通过，75 项包资源与最终源码一致 |
| 数据／受限函数 | 全部使用自动清理的私有夹具；服务连接 total_changes 和对应数据检查保持不变，受限测试函数零调用；没有配置库写入 |
| 当前驻留 Host | 维护者重启后 **25/25** 符合预期：20 项常量读取、三项拒绝及两次完整快照；五行五列相同，内容／结构化结果一致。重启前四例拒绝保留；新增视图／触发器／参数 Skill 夹具没有写入配置库，保持源码／安装证据归属 |

真实 stdio 协议为 auto=`2026-07-28`、legacy=`2025-11-25`，不套用到当前原生 Host。应用结果记录不是完整协议帧。旧源码从 e49cd0e 解包，核对 75 项资源并断言全新子进程实际导入路径；使用当前依赖，不冒充历史环境回放。

没有新增完整 Luna 业务任务或 MySQL 实库矩阵。此前 3/3 销售结果、模型／Host 失败、成本和 498 项历史封存保持各自源码范围，不改标为本批再次通过。

## 过程记录与安装范围

- 首批 80 项测试为 64 failed／16 passed；其中两项误要求无效 SQL 必须在解析层拒绝，实际数据库已正确返回 sql_syntax_error。保留初始断言和日志，修正层次预期后，IS 单独阶段完整回归 2355 项、wheel 478 次通过；该阶段的源码及原始结果另存，不当成最终 IS＋ESCAPE 证据。
- 相邻 ESCAPE 的新增 20 项先得到 18 failed／2 passed，再补修；最终 100 项和 2375 项完整回归通过。未为了使测试通过而放宽授权或完整性规则。
- 一次诊断误将 `analysis.complete` 等同于原生语法有效；原生会拒绝的 `SELECT 1 IS` 可被上游当成别名形态分析。记录实际状态，不据此扩大或重定义 complete。其它缺失右值／COLLATE 的边界仍解析失败，未见未捕获解析异常。
- 系统无 ensurepip，首轮普通 venv 引导失败；改用已校验的官方 PyPA installer 0.7.0。再次下载曾超时，最终重用本批已验证的解包缓存并逐项核验 wheel RECORD。失败、超时及最终正常 wheel 安装均保留，没有安装系统包或全局工具。
- sdist→wheel 使用既有缓存构建后端；新解释器**显式复用现有锁定依赖目录**，不是从零重新解算依赖。项目来自新解释器 site-packages，无 editable finder，75 项资源逐项一致。

复用入口 `scripts/validation/installed_semantics.py` 新增 `--source <src>`；省略时仍要求独立 wheel 解释器。脚本固化本批语义及参数 Skill 用例，输出路径须为新文件，避免覆盖历史记录。

## 状态、证据与交接

本批[源码／验证摘要](v382_collate_2026_10_18/verification.json)及[封存清单](v382_collate_2026_10_18/manifest.json)追加保存旧／新输入、早期失败、IS 单独阶段、最终源码及安装验证。此前 498 项封存文件原字节保持；初次复核中“P3 开放”仍是当时状态，不覆盖为已修。

维护者已手动重启，限定原生复验完成。独立 resident_restart 补充保留新结果，本父检查点的 pending 状态、初始拒绝及旧业务结果保持原字节；它们分别描述当时状态。提交建议使用本批 fix(v3.8.2) 草案，可包含尚未提交的最终复核文档；不修改版本号，不自行暂存或提交。

## 手动重启后的限定原生复验

维护者确认重启后，在当前 Codex 原生 SQL MCP 通道严格执行此前封存的 25 项计划，仅访问已解析的 `analytics_demo_sqlite`。**25/25 项符合预期**，没有新增配置夹具、写入、授权或依赖。

- 20 项合法常量读取覆盖原始未加括号示例、IS NOT、BINARY／NOCASE／RTRIM、投影／条件、ESCAPE NULL／字面量／组合表达式及括号对照；全部重新与独立内存 SQLite 真值比较。分别作为 `SELECT 7 AS n WHERE …` 的条件时，`'A' IS 'a' COLLATE NOCASE` 返回 7，`('A' IS 'a') COLLATE NOCASE` 返回空集，作用位置得到保留。
- 三项拒绝分别得到 `table_access_denied`、`expensive_function_denied`、`lock_function_denied`；均为结构化策略结果，没有通用工具错误。
- 前后 `orders` 完整五行五列快照相同，没有截断；每次工具内容与 structuredContent 一致，连接别名及返回原 SQL 均逐项核对。

[本次原生摘要](v382_collate_2026_10_18/resident_restart/verification.json)、[原始应用结果](v382_collate_2026_10_18/resident_restart/native_after_restart.json.gz)、[独立 SQLite 对照](v382_collate_2026_10_18/resident_restart/independent_sqlite.json)及[独立封存清单](v382_collate_2026_10_18/resident_restart/manifest.json)另存；此前 **556 项**封存文件与清单摘要逐项核验，新封存四项。当前 75 项运行资源及六项既有测试／脚本摘要仍匹配本批 2375 项回归／490 次安装验收检查点，因此本次仅续做原生和文档收口，没有重复运行或重新归属这些测试。

DRR-109 按该源码／安装及 25 项原生范围关闭；DRR-108 不重开。本次没有新增 Luna 完整任务、MySQL 实库或成本 A/B；配置视图、触发器及参数 Skill 未新增原生夹具。记录的是应用层工具结果，不是完整协议帧、原生协议版本或驻留代码对象证明；重启前差异的具体启动／缓存成因仍未定位。
