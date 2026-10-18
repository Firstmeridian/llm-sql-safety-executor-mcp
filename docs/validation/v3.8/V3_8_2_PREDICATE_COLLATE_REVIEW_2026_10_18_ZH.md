# v3.8.2 完整判断后的 COLLATE 复评（2026-10-18）

> 后续维护者已批准[补修](V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)，源码／安装验证及维护者重启后的 71/71 项限定原生验收通过，DRR-110 按记录范围关闭。下文保留本批只读复评时的开放状态及原始失败。

**结论：反馈属实，是既有、非阻断 P3 功能兼容遗漏，登记为开放的 DRR-2026-110；建议同轮定点补修。** 本批仅分析、私有实测、文档与证据，未修改产品实现、正式测试、配置、依赖、授权或版本。此前 DRR-109 的 IS／ESCAPE 操作数及 25 项原生限定验收保持有效，不能将其扩大为完整 COLLATE 语法支持。

## 实测结果

下表 SQL 均为 `SELECT 7 AS n WHERE <判断> COLLATE NOCASE;`。独立 SQLite 均返回 7；当前源码 auto／legacy Client 和实际原生 MCP 结果一致。

| 判断 | 直接接 COLLATE | 给整个判断加括号后 |
| --- | --- | --- |
| `NULL ISNULL` | sql_parse_failed | 返回 7 |
| `7 NOTNULL` | sql_parse_failed | 返回 7 |
| `7 NOT NULL` | sql_parse_failed | 返回 7 |
| `7 IN (7)` | sql_parse_failed | 返回 7 |
| `7 NOT IN (8)` | sql_parse_failed | 返回 7 |

固定 57 条合法常量语句：五种判断各覆盖 BINARY／NOCASE／RTRIM、WHERE／投影、直接／括号对照，并加入 17 项相邻输入。每版两种 Client 各执行全部 57 条：

| 范围 | 结果与归属 |
| --- | --- |
| 当前源码 | 114 次调用：60 次成功且结果匹配独立 SQLite，54 次 sql_parse_failed，即 27 种形式在两种模式下误拒 |
| e49cd0e | 同输入 114 次：56 次成功、58 次解析拒绝；与当前仅差此前修好的 IS／ESCAPE 两条 canary，各两模式 |
| 当前原生 | 15 次常量请求：五组直接／括号对照、三项 IN 字符串对照及两项既有修复 canary；9 次成功、6 次解析拒绝，内容与结构化结果一致 |
| 当前 Query Skill | 私有夹具 18 次调用；两个直接形式启动时因 sql_parse_failed 被跳过，发现列表只含两个括号形式，详情／执行直接形式均返回 Skill not found 工具错误（共八次，structured=null），括号形式可发现、schema_ready 且执行返回 7 |
| 源码与历史 | 独立基线解包、子进程实际导入路径断言及 75 项资源一致；当前也匹配之前的验收快照。此前 560 项封存核验通过，新封存 13 项 |

两种 Client 协议分别为 auto=`2026-07-28`、legacy=`2025-11-25`；本批为真实进程内 Client，未重新做 child stdio／wheel。基线使用当前依赖环境，不是历史环境回放。当前原生限定使用此前已解析的 `analytics_demo_sqlite`，全部为常量读取，没有配置库写入或原生 Skill 夹具。没有新完整 Luna 任务、MySQL 实库或成本 A/B；这组选定语法矩阵不是业务任务失败率。

## 根因与语义边界

当前项目的 SQLite Parser 已适配 `_parse_is()` 和 `_parse_escape()` 中的右操作数，但这五种完成判断后的后缀仍经过 SQLGlot 30.22.0 上游 `Parser._parse_range()`。该函数完成 IN／NULL 判断及 NOT 包装后，没有消费随后作用于完整判断的 COLLATE，尾 token 留给上层而触发解析失败。对应上游函数源码及行号已随记录保存。本批失败的 `analysis.status` 为 failed，尚未进入读取 authorizer；不是 MCP 未刷新。

同输入还确认：`IN (SELECT ...)`、空 IN 列表、行值 IN、判断后继续接 IN、连续 COLLATE 的直接形式有同类遗漏。所测 BETWEEN／NOT BETWEEN、LIKE、GLOB、EXISTS 以及已修 IS／ESCAPE 对照在当前版本成功；不能推导所有判断都受影响。

SQLite 将 COLLATE 定义为后缀运算符，IN 列表比较使用左操作数的排序规则；见[表达式规则](https://www.sqlite.org/lang_expr.html#operators_and_parse_affecting_attributes)与[排序规则 §7.1](https://www.sqlite.org/datatype3.html#assigning_collating_sequences_from_sql)。独立 SQLite 及实际原生对照为：

| 表达式 | 独立 SQLite | 当前 MCP |
| --- | ---: | --- |
| `'A' IN ('a') COLLATE NOCASE` | 0 | sql_parse_failed |
| `('A' IN ('a')) COLLATE NOCASE` | 0 | 0 |
| `'A' COLLATE NOCASE IN ('a')` | 1 | 1 |

因此，这组特定写法可临时给**整个判断**加括号；不能将 COLLATE 移到左操作数。它与此前 IS 右值问题的结合位置不同，也不应制作一个面向所有 SQL 的正则括号改写。

## 建议与取舍

建议在同一 SQLite 方言适配层补齐完整判断后的后缀处理，按语法角色构造 COLLATE 节点，保留 NOT 包装、后续判断及多重后缀的结合顺序。继续执行原 SQL 和绑定值，保持共享依赖分析、独立授权及 authorizer。无需为本组输入提前引入新框架或更换依赖，但本批尚未实现／证明具体适配算法。

补修前先将本组矩阵转为语义回归：既要比较数据库输出，也要核对 AST 中 COLLATE 包裹的是完整判断；覆盖三值逻辑、NOT、连续判断、子查询／物理关系和参数。随后补 Query Skill 发现／详情／readiness／执行，以及未授权底表、受限函数和非执行型计划对照，复验此前 IS／ESCAPE 两类相反的结合位置。

收益是减少合法查询及 Query Skill 的误拒和恢复步骤；代价是维护更多方言适配与升级回归。预期方案无需新数据库探测或 Agent 必需步骤，但未实现前不承诺零成本。保持 P3 非阻断合理；考虑到已定位到现有解析入口，建议本轮修复，长期只记录限制的收益较小。

## 证据与交接

[本批摘要](v382_predicate_collate_review_2026_10_18/verification.json)、[固定输入](v382_predicate_collate_review_2026_10_18/plan.json)、[当前源码](v382_predicate_collate_review_2026_10_18/current.json.gz)、[e49cd0e 对照](v382_predicate_collate_review_2026_10_18/baseline.json.gz)、[原生请求](v382_predicate_collate_review_2026_10_18/native.json.gz)、[Skill 记录](v382_predicate_collate_review_2026_10_18/skills.json.gz)及[封存清单](v382_predicate_collate_review_2026_10_18/manifest.json)独立保存。私有临时基线已核验后清理；历史失败和上次限定关闭不改写。本批没有产品代码修改，因此不需要重启。
