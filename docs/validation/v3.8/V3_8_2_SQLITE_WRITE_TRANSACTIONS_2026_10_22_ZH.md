# v3.8.2 SQLite 写入物理事务与完成态行数：DRR-142／143

日期：2026-10-22。按维护者批准修复。源码与正常安装包的私有文件库验证通过；当前驻留 MCP 尚待维护者手动重启及限定复验。此前主键／读取验收、十五项 Luna 业务成本与弱提示解释结果保留各自范围，不能证明这些实际写入场景已经通过。

## 原因与修复契约

| 项目 | 修复前的问题 | 当前方案 | 收益与代价 |
| --- | --- | --- | --- |
| DRR-142，P1 | sqlite3 旧事务控制下，SQLAlchemy 逻辑 begin 不保证 WITH／前置分号 DML 发出物理 BEGIN；写入已持久化，逻辑 rollback 却可能返回 rolled_back | 在同一独占执行连接上显式建立、核验物理事务，再执行原 SQL；完成结果后检查行数，最后 COMMIT | 恢复行数保护和真实事务边界；增加显式 BEGIN 的适配器工作 |
| DRR-143，P2 | RETURNING 尚未完成时 rowcount 为 0；SQLAlchemy 缓存值可能不更新，CTE 完成后仍可能为 -1 | 在原截止时间内分批消费、关闭结果，优先取完成后的原生 cursor.rowcount；实际 DML 仍未知时，同连接 SELECT changes() | 合法 RETURNING／CTE 可提交；多行结果必须完成，会有读取及 SQLite 自身缓冲成本 |
| 相邻部分失败 | CTE OR FAIL／触发器 RAISE(FAIL) 可留部分修改；遗留 RETURNING 游标关闭后可能延迟持久化 | 成功、异常、取消、超时均清理结果，再据物理事务前后状态判定回滚；不确定的连接退休 | 独立连接在返回、重放及服务器清理后核对数据；清理失败不能伪装成功回滚 |
| 结果证据 | 逻辑事务活跃被当成充分回滚证据 | SQLite 的 rolled_back 同时要求有效连接、回滚前真实事务活跃、回滚正常返回及回滚后真实事务结束；COMMIT 回执失败仍 unknown | 不确定时避免误导重试；引擎自行回滚等情况可能仍保守报告 unknown |

`changes()` 仅用于已经成功执行、需要补数的直接 DML，不用于 SELECT／EXPLAIN／DDL，避免继承上次写入的计数。复用现有方言词法 token 判断根语句角色、跳过 CTE 定义，不新增 AST 授权路径，不重新生成 SQL。两种受管分类器保留原配置语义；临时 sqlparse 回退没有因此依赖第二次 SQLGlot AST 校验。

计数遵循 SQLite 直接 DML 语义：不累计触发器、外键级联及 REPLACE 的附带删除；不能用 RETURNING 返回行数代替。INSTEAD OF 视图触发器可能返回一行、直接计数仍为 0，要求 1 行时继续回滚。普通匹配但值未变化的 UPDATE 仍计入受影响行。可选 expected_rowcount 省略时仍允许批量写入。

保留 `execute_write()` 的 rowcount 返回契约，RETURNING 行在适配器内部消费，不新增返回写入数据的工具接口。分批消费避免 Python 一次保存全部结果，但不能消除 SQLite 内部的 RETURNING 缓冲。超时为现有协作式控制及显式截止时间检查，不宣称硬实时中断所有锁等待。

不修改全局引擎事务模式或读取连接生命周期，不放宽 authorizer／授权，不改提示、依赖、版本号、真实配置或 grant，也不新增 Agent 必需的工具步骤。共享回滚函数新增可选后端证据探针；MySQL 事务证据规则保持独立，旧 InnoDB 范围不扩大。

## 验证与独立真值

新增回归使用独立 sqlite3 文件连接播种、读取真值及 SQL trace，覆盖普通／WITH／递归 WITH／分号／注释，INSERT／UPDATE／DELETE 的有无 RETURNING、零／一／多行、行数不匹配、部分失败、引擎自行回滚、count_changes、触发器与级联、视图、非 DML、结果异常／取消／超时及事务清理故障。原 SQL（含前缀）实际到达 SQLite，物理 BEGIN／COMMIT／ROLLBACK 可观察。

源码和正常 wheel **各 432 次应用调用、136 个完整预览→确认→重放流程**，覆盖进程内／独立 stdio × auto／legacy × sqlglot／sqlparse。每个流程核对预览未写、确认结果、令牌已消费、重放拒绝，以及服务器清理后的独立数据真值。另保留正常读取、只读入口拒绝写入及受限函数拒绝对照。应用文本与结构化结果一致；脱敏预览令牌。这些是应用记录，不是完整协议帧或模型 token。

新增 **120 项回归**；全量 **3493 通过／4 项可选跳过**，定点 197 通过／1 项可选跳过，类型 0 错误／0 警告及提示资源检查通过。正常 wheel 的 **77 个运行资源**与当前源码一致，三份私有 TOML、1982 份旧公开证据及旧 77 份封存／2478 条文件记录均保持。详见[可核查证据索引](v382_sqlite_write_transactions_2026_10_22/README.md)。构建复用冻结依赖，并非重新解析安装整套依赖。

保留初次测试夹具用只读 execute 设置 PRAGMA 导致的两个失败、沙盒内类型依赖不可见、提示脚本首次缺少 --config 的准备错误及最终通过日志。它们不作为生产缺陷或最终通过证据。修复前 41 变体、游标生命周期反例及 120 次 Client 调用继续保留在本地 assessment 批次，不覆盖旧失败。

## 本机成本与适用范围

所有构建／测试结束后串行 A1／B／A2：A 为紧邻补修前冻结的 77 资源源码，B 为最终源码。同样的私有文件库、普通单行 UPDATE；每场景每阶段 40 次预热、400 次计时，成功及回滚均独立读取真值。不是相对 2c0a9e7 的全部累计改动对照。

| 场景，中位 ms | A1 | B | A2 | B 相对两个基准 |
| --- | ---: | ---: | ---: | --- |
| 普通一行提交 | 9.051 | 8.994 | 8.979 | -0.63%／+0.16% |
| 行数不匹配回滚 | 0.380 | 0.315 | 0.287 | -16.97%／+9.72% |

普通提交未见明显变化；回滚基准自身下降约 24.33%，不能据此宣称提速或严格零代价。显式 BEGIN、结果消费、状态检查及 CTE 未知计数时的补数查询有实际工作量。旧版 CTE／RETURNING 的功能失败不作为同能力速度基准；这里也未测模型 token、复杂 Agent 规划、冷启动或远程尾延迟。

## 驻留验收与剩余范围

待维护者按工作流手动重启当前 Codex 使用的 MCP，再做冻结的既有别名读取、元数据、继续拒绝及未确认预览检查。不向已配置数据库执行本轮 DML；实际事务、RETURNING 和故障注入证据属于上述源码／正常 wheel 私有夹具，不能用一次常量成功宣称驻留修复已被直接证明。

没有新增完整 Luna、同任务 token 或因果引导效果测量。此次工具契约及提示未改，不要求 Agent 增加步骤，但不承诺总 token 不变。此前弱提示取消试验的严格措辞 1/3 和模型耗时上升仍保留为独立后续；不以本批确定性测试消除它们。

依据：[SQLAlchemy SQLite 事务控制](https://docs.sqlalchemy.org/en/21/dialects/sqlite.html#transactions-with-sqlite-and-the-sqlite3-driver)、[Python sqlite3.rowcount](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Cursor.rowcount)、[SQLAlchemy CursorResult.rowcount](https://docs.sqlalchemy.org/en/21/core/connections.html#sqlalchemy.engine.CursorResult.rowcount)、[SQLite changes()](https://www.sqlite.org/c3ref/changes.html)、[SQLite RETURNING](https://www.sqlite.org/lang_returning.html)。
