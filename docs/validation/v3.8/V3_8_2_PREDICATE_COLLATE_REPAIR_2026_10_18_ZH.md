# v3.8.2 SQLite 完整判断后缀与续接补修（2026-10-18）

承接[只读复评](V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md)，维护者批准后已补修 DRR-110。源码、类型／提示、独立安装验证及维护者重启后的 **71/71 项限定原生验收均通过**。版本仍为 v3.8.2，SQLGlot 固定 30.22.0。

## 本次完整待提交变更（相对 e49cd0e）

本表合并最初已提交版本复核、IS／ESCAPE 操作数补修及完整判断续接补修；更早已提交的架构接入保持其原验收归属。产品运行代码只修改 SQLite 方言分析所在的 `core/analysis.py`，持续执行原 SQL／绑定和既有独立读取策略、authorizer；版本、依赖、MySQL、配置及授权范围保持既有约定。

| 变更 | 变更前及原因 | 变更后及原理 | 好处 | 代价／边界 |
| --- | --- | --- | --- | --- |
| IS／IS NOT 右值 | NULL／参数快捷解析遗漏其后的 COLLATE | 右值按表达式优先级消费，COLLATE 保留在右操作数 | 原合法语法恢复，字符串比较含义保持 | 增加 SQLite 方言适配及升级回归 |
| LIKE ESCAPE 右值 | 字面量／NULL／参数快捷解析也遗漏 COLLATE | 以表达式入口消费 escape 右值，保留绑定和函数／依赖分析 | 字面量、空值、组合表达式及参数 Skill 可用 | 同样需要维护上游接口适配 |
| 完整判断后缀 | ISNULL／NOTNULL／NOT NULL、IN／NOT IN 后的 COLLATE 留作未解析 token | 在完整判断外构造后缀节点，显式保留 NOT 和结合位置 | 五类判断及 IN 子查询／空列表／行值、连续后缀恢复 | 不能将 COLLATE 移至 IN 左值，不能承诺任意语法支持 |
| 相邻判断续接 | 完整判断后接算术、拼接、位运算或 JSON 时也可能停在尾 token | 局部优先级表继续解析高优先级操作，再交回既有 range 入口 | 一并修复同根遗漏；540 条分析均完整，新增接受 480 条语义往返一致 | 增加少量解析检查与节点构造；未做新成本 A/B |
| Query Skill 可用性 | 合法定义因解析失败被跳过，随后详情／执行报 not found | 共享分析恢复后核验发现、详情、readiness、参数执行及视图／触发器计划 | 原定义可以加载，减少改 SQL 和恢复调用 | 恢复的 Skill 可增加发现列表条目和返回内容；专用场景保留源码／安装覆盖 |
| 回归与拒绝验证 | 缺少上述合法／误拒和隐藏依赖的对照 | 新增 100＋190＝290 项，比较独立 SQLite 与 AST 结合，同时验证未授权对象、受限函数、真实 DML 及状态不变 | 最终 2565 passed／四项跳过，类型／提示通过；修复保留原授权与执行边界 | 测试维护与运行耗时增加；四项可选 MySQL 跳过 |
| 安装与复用工具 | 原脚本只验证 wheel，缺少这些后缀及参数场景 | `installed_semantics.py` 增加显式 `--source` 和导入路径校验，扩展两协议查询／Skill；验证独立 wheel 及 75 项包资源 | 当前源码 130 次、安装定点 524 次通过；源码与安装分别留证 | wheel 解释器显式复用冻结依赖，不代表从零安装或重新解算依赖 |
| 文档、复核与证据 | 多阶段发现、失败和“待重启”状态容易混淆 | 中英文日志／README／索引、设计、发布说明、测试指南、四份复核／补修报告同步；DRR-109／110 按范围关闭，原生 25／71 项分批独立封存 | 结论可追溯，旧失败、源码归属和元数据勘误保留 | 归档体积和清单维护增加；历史 pending 检查点不改写，七项未用于生产执行的生成器限制保留 |

## 实现与相邻检查

| 修复前 | 本轮实现 | 收益、代价与边界 |
| --- | --- | --- |
| ISNULL／NOTNULL／NOT NULL、IN／NOT IN 后直接接 COLLATE 被误拒 | SQLite range 完成后继续处理后缀，COLLATE 包裹完整判断，保留 NOT 及显式结合位置 | 五类语法恢复，原 IN 的比较规则保持；不把 COLLATE 移至左值 |
| IN 子查询、空列表、行值及连续后缀同类失败 | 同一续接入口支持后续 range 和重复 COLLATE，复用 SQLGlot 节点及原子操作数解析 | 避免只适配两个示例；参数、真实关系及函数继续进入共享分析 |
| 完整判断后接算术、拼接、移位／位运算、JSON 运算也会失败 | 用局部优先级表处理既有 range 后的高优先级续接，再交回原 range 解析；解析树中为完整判断保留括号 | 明确限定在 SQLite 现有解析层，不新增通用框架；代价是维护这个方言续接入口和升级回归 |
| 合法 Query Skill 启动被跳过，随后 Skill not found | 同样受益于共享分析，补发现／详情／readiness／参数执行验证 | 原始定义可直接加载，不需要新增 Agent 步骤 |
| 修复可能隐藏底表、受限函数或改变执行语义 | 继续执行原 SQL／绑定，保留独立读取策略、authorizer 和实际目标检查 | 未授权关系、耗时／锁／文件／账户调用和真实 DML 保持拒绝；视图 grant 不授予直接底表访问 |

新增代码仍只位于 `core/analysis.py` 的 SQLite Parser；MySQL 解析、sql_mode、配置、grant、审批、连接和缓存约定不改。之前 IS／ESCAPE 的**右操作数** COLLATE 适配保留，与本次**完整判断**的后缀位置分开验证。没有 SQL 正则改写、AST SQL 重新生成后执行，或 authorizer 豁免。

SQLite 的[后缀运算符规则](https://www.sqlite.org/lang_expr.html#operators_and_parse_affecting_attributes)和[IN 排序规则](https://www.sqlite.org/datatype3.html#assigning_collating_sequences_from_sql)是语义依据。原 `'A' IN ('a') COLLATE NOCASE` 与整个判断括号形式都得到 0，`'A' COLLATE NOCASE IN ('a')` 得到 1；此前 IS 右值／整个判断的相反结合对照也保留。

## 最终源码与安装验证

| 检查 | 结果与范围 |
| --- | --- |
| 新增回归 | **190 项**，包括五类判断、三种 collation、条件／投影、AST 结合、连续操作、三值逻辑、参数、Skill、视图、触发器 WHEN／两种非执行计划及必要拒绝 |
| 最终全量 | **2565 passed／4 skipped／373 warnings，456.44 秒**；四项可选 MySQL 跳过，警告为既有 MCP logging 弃用 |
| 类型／提示 | 最终 Pyright 0 errors／0 warnings；提示资源和路由契约通过 |
| 同输入前后 | 沿用复评的 57 条输入：修复前两模式 114 次中 54 次解析误拒；最终 **114/114 成功**，结果匹配独立 SQLite。这是定点语法矩阵，不是业务失败率 |
| 判断续接矩阵 | 540 条合法常量输入，修复前仅 60 条分析完整，最终 **540/540 完整**；新增接受的 480 条全部通过独立 AST SQL 往返语义对照 |
| 当前源码真实 child stdio | **130 次**，两种模式通过，覆盖新增直接形式、算术、字符串语义及参数 Skill |
| 独立 wheel | **524 次**：语义 130＋既有触发器 CTE／WHEN 254＋计划／Skill 140；CLI／Prompt／两协议 smoke 另通过，75 项包资源与最终源码一致 |
| 数据与受限函数 | 自动清理的私有夹具；控制用例数据、连接 total_changes 保持，受限函数零调用；未写入配置数据库 |
| 当前原生 | 维护者重启后 **71/71** 符合固定预期：66 条常量读取、三项策略拒绝及两次完整快照；五行五列相同，内容／结构化结果一致。修复前 IN 拒绝保留；参数 Skill／视图／触发器保留源码／安装归属 |

实际 child stdio 协议为 auto=`2026-07-28`、legacy=`2025-11-25`；不据此声明当前原生 Host 的协议。应用结果记录不包含完整传输帧。没有新增 Luna 完整任务、MySQL 实库、远端 CI 或模型／服务器成本 A/B；先前业务通过率、Host 失败和测量保持各自源码归属。

本轮没有新增数据库探测或 Agent 必需调用。续接检查增加解析和节点构造工作，也在普通 range 返回时增加轻量检查；此前被跳过的 Skill 恢复后，发现列表可能增加条目和返回内容。未做模型 token 对照，不承诺零 CPU／延迟或 token 改善。

## 已保留的诊断与工具限制

- 首批新增 176 项在修复前为 148 failed／28 passed；最初有一个私有 IN 表夹具错误地使用三列，改为单列后重新记录同样数量的失败。两份日志保留；首份日志中的错误夹具不作为合法 SQL 正例，校正后日志用于正式修复前对照。
- 第一阶段定点 276 项通过；独立往返检查暴露缺少显式括号的打印问题，随后为完整判断加 AST 括号。阶段定点 290 项通过，最终新增 190 项及此前 100 项全部包含在最终完整回归中。早期源码与构建结果是中间检查点，不当作最终包证据。
- 最终 540 项中，原始 SQL 与直接生成 SQL 的结果一致为 **533/540**。其余七项是修复前已存在的 SQLGlot 生成器括号问题，例如 `7 NOTNULL IN (0,1,2)`；本批未重新生成 SQL 执行，增加七项真实工具正例／两模式共 14 项回归确认原 SQL 输出正确。新增接受的 480 项没有这类差异，不能将生成器往返限制说成当前工具返回错误。
- 沙盒内首次类型检查无法解析已安装依赖；正常环境复核发现一处 None 分支类型错误并补齐显式返回，最终类型及完整回归通过。初始检查记录不删除。未请求 Full access。
- 使用缓存构建后端完成 sdist→wheel。新解释器正常安装项目 wheel，显式复用锁定依赖目录；不是从零解算依赖。复用此前已校验的官方 PyPA installer，逐项验证 RECORD；未更新项目或全局依赖。

## 状态与证据

DRR-110 当前为“已补修；限定驻留复验通过”，按本报告记录的源码／安装及 71 项原生范围关闭；DRR-109／108 保持此前限定关闭。维护者已按工作流手动重启，当前原生在 `analytics_demo_sqlite` 完成固定计划：预检、65 条常量、三项拒绝及前后两个完整快照。没有新增原生配置 Skill／视图／触发器夹具或数据库写入。

[摘要与资源范围](v382_predicate_collate_repair_2026_10_18/verification.json)、[固定原生计划](v382_predicate_collate_repair_2026_10_18/evidence/native_plan.json)及[封存清单](v382_predicate_collate_repair_2026_10_18/manifest.json)独立追加。此前 **573 项**封存不改写，评估时的开放状态和失败保留；本源码／安装检查点的 pending 状态保留原字节，已完成的原生结果另存 resident_restart，见下文。

提交说明仍为 fix(v3.8.2) 同主题草案，涵盖尚未提交的操作数、完整判断续接及复评记录；维护者自行暂存／提交。

## 手动重启后的限定原生验收

维护者确认重启后，实际当前 Codex 原生 SQL MCP 通道逐项执行冻结计划，**71/71 项符合预期**。66 条常量（含预检）全部重新与独立内存 SQLite 对照，覆盖五类判断、三种 COLLATE、条件／投影、括号及 IN 字符串语义、子查询／空列表／行值、连续后缀和判断、算术、拼接、位运算、JSON，以及此前 IS／ESCAPE 修复的 canary。

三项拒绝分别为 `table_access_denied`、`expensive_function_denied`、`lock_function_denied`。前后 `orders` 的完整五行五列快照相同且未截断；每次工具文本与 structuredContent 一致，返回连接别名、原 SQL 和行数均核对，没有通用工具错误。

[原生摘要](v382_predicate_collate_repair_2026_10_18/resident_restart/verification.json)、[原始应用结果](v382_predicate_collate_repair_2026_10_18/resident_restart/native_after_restart.json.gz)、[独立 SQLite 结果](v382_predicate_collate_repair_2026_10_18/resident_restart/independent_sqlite.json)及[原生封存清单](v382_predicate_collate_repair_2026_10_18/resident_restart/manifest.json)独立追加。此前 **621 项**封存及清单摘要均重新核验，新原生封存四项；75 项运行资源与八项既有测试／脚本摘要仍匹配 2565 项回归／524 次安装检查点。因此本次只续做原生和文档，没有重复运行或重新归属此前测试。

封存元数据的 `independent_sqlite.json.scope` 曾沿用“20 条”旧说明，实际内容和验证摘要均为 **66 条**；记录和逐项比较全部正确。已用[独立勘误](v382_predicate_collate_repair_2026_10_18/resident_restart/metadata_correction/errata.json)与[勘误清单](v382_predicate_collate_repair_2026_10_18/resident_restart/metadata_correction/manifest.json)追加修正范围说明，新封存一项，不改写原数据、原生结论或旧清单；本地续验脚本的说明也已修正。

本次未新增 Luna 完整任务、MySQL 实库或成本 A/B，也未在配置库加入参数 Skill／视图／触发器夹具。应用记录不等于完整协议帧、原生协商协议或驻留代码对象证明。原生关闭只覆盖所列范围，不宣称任意 SQLite 语法完整支持；重启前差异的具体启动／缓存成因未定位。
