# v3.8.2 名称、方言语义与执行保障设计

日期：2026-10-16。维护者批准基于 3323f9c 实施；本文区分契约、各批已完成的实现／验收和剩余复验，不以设计描述代替通过证据。

## 目标与约定

1. 继续使用 RelationReference(schema, name) 表示解码后关系引用。原始 token、引用方式、源码范围、对象角色与作用域保存在分析记录；显示字符串不作为授权键。不 trim、Unicode casefold 或反复解码业务名称。
2. 区分物理关系引用、CTE、表别名和结果列别名。MySQL 数据库／表／列的尾空格规则不套用到所有角色；非法名称不自动修正为另一个对象。SQLite／MySQL 名称规则分别验证。
3. SQL 分析使用显式方言和受控会话上下文，统一输出语句、关系、作用域、调用、参数、不支持项与完整性。部分分析／失败不能表示为没有依赖。始终执行原 SQL 和原绑定参数。
4. 项目授权独立于数据库名称等价。引用方式等价不产生新 grant；限定名与名称内点号保持不同身份。结构化授权声明表达单个含点号名称，现用字符串表名仅作为明确的声明简写。
5. Query、Skill 与 readiness 共用名称及分析语义；Skill 缓存区分方言／会话上下文。元数据消费已授权的结构化对象和固定模板，不把可信操作能力暴露为工具参数。
6. 保持已授权视图可经该视图读取，不把底表变成可直接访问对象。authorizer 的视图来源需核对依赖链及 schema，不能见到非空 source 就放行，也不机械要求调用者同时具备全部底表 grant。
7. 正常业务读取保持一次 MCP 工具调用。运行时内部检查和首次连接初始化不作为 Agent 必需的新步骤。不得据此承诺相同 token、延迟或总成本。

## MySQL 会话

- 配置可显式指定完整 sql_mode 集合；未指定时继承首个初始化会话的完整集合，并将后续物理连接初始化为相同约定。每条物理连接均在 SQLAlchemy 方言检测和业务使用前初始化／校验，重连和池重建同样处理，不只使用 first_connect。
- SQLGlot 的 mysql 方言不自动读取会话。ANSI_QUOTES、NO_BACKSLASH_ESCAPES 等影响解析的设置由项目适配器处理，不能只读另一个连接就假定执行连接一致。
- 正常请求不新增每次模式探测。此前提要求项目控制连接使用路径；可信扩展如需改变会话状态或创建临时对象，必须隔离或销毁污染连接。默认 rollback 不等于模式／临时对象清理。
- 会话上下文与 CTE 名称比较能力分开表达；现有常量 CTE 探测的结果不能用来推断 sql_mode。MySQL 配置库限定名也不能独自保证不存在同会话临时表遮蔽。

## SQLite 执行保障

- 现有业务 StaticPool 共享一个物理连接，必须先建立覆盖编译、执行、取完结果及清理的独占上下文；受管写入的完整事务也纳入连接管理。
- authorizer 注册于物理连接，使用显式的读取、可信元数据、受管写入上下文。回调本身不执行 SQL，拒绝使用 SQLITE_DENY，不用 IGNORE 将数据悄悄替换成 NULL。
- 回调保持至结果消费和可能重编译结束；处理 count(*) 的空列名、main/temp/aux、视图来源、PRAGMA 虚拟对象、异常、取消、连接重建与清理失败。
- 首次生产接入优先采用可证明正确的 DBAPI prepared-statement 缓存策略；不能混同 SQLAlchemy 编译缓存。若关闭语句缓存，单独测量编译和延迟代价，再决定优化。
- authorizer 不代替共享分析、项目策略、超时、写入审批和事务 outcome；不将可信 Python 扩展描述为沙箱。

## 阶段与验收

| 阶段 | 内容 | 完成条件 |
| --- | --- | --- |
| 1 | 基线与接口／授权契约 | 源码、环境和回归冻结；接口可测试，决定有记录 |
| 2 | 对象／引用／模式矩阵 | 独立原生真值，合法／非法／未授权分开记录，覆盖不同入口 |
| 3 | 连接语义基础 | 新连接、复用、重连、异常和清理的定点验证 |
| 4A | SQLGlot 生产适配 | 分类／关系／作用域／依赖共用结果；不完整分析不放行；移除已替换的重复解析 |
| 4B | SQLite authorizer | 对象与操作检查、视图、缓存、重编译和并发完整闭环 |
| 5 | 全体验收及文档 | 全量／类型／提示、安装包两协议、实库、重启后 Host 和原生 Luna 完整任务；成本单独评价 |

实现状态：阶段 1、3、4A、4B 已落地，阶段 2 的本机矩阵已完成，阶段 5 已完成首批 12 个完整 Luna 任务、CTE 计数补修及最后原生 5/5／三次双轮 Luna 销售复验；模型失败与机械评分限制独立记录，批准范围已闭环。版本目标 3.8.2，最终状态以[验收记录](../validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md)为准。既有 3.8.1 证据封存，不覆盖或改写源码归属。其他 MySQL 大小写配置及 MariaDB 没有独立实例，明确标为未实测。

## 已落地的接口及边界

- `core/analysis.py` 输出不可变 `SQLAnalysis`：语句、关系集合、每次关系使用及来源、名称词法位置／角色、CTE 声明／作用域、函数、参数和不支持项。`complete` 仅代表本项目投影完整，不代表服务器语法／对象／列有效；未知结构返回 partial/failed。raw 和 Query Skill 共用 `_prepare_sql_read`，readiness 按同一方言上下文推断，缓存键包含模式和 CTE 比较规则。旧 `core/structure.py` 及重复读取解析已删除；受管写入的独立计划检查仍使用 sqlparse，不将读取 AST 当成写入批准。
- SQLite 前向声明和隐式递归按真实 SQLite 规则生效；MySQL 保持定义顺序及显式递归自引用。SQLite 业务名称和 SQL 保留词仅折叠 ASCII；SQLGlot 的 Unicode 关键词／函数规范化不会改变原始授权名称。只在真实名称槽适配 contextual 名，声明不屏蔽查询体。 SQLite 仅保留实际 CURRENT_DATE／CURRENT_TIME／CURRENT_TIMESTAMP 无括号词汇；CURRENT_USER／LOCALTIME 等普通业务列不套用其他方言的函数语义，真正的受限调用仍拒绝。
- `read.relations=[{schema="main",name="main.orders"}]` 授权单个含点表名；省略 schema 表示裸引用。Skill YAML 可用同名 `relations` 映射数组；它是约束和依赖声明，不产生 grant。`tables` 仍是首点拆分的简写，显示标签不重新解析。full Query Skill 新增 `analysis_complete`，不完整时 inferred_tables=null，不声称无依赖。readiness 仍只核验默认 schema。
- 元数据名称改为方言支持包络加逐组件引用，SQLite 不再套用统一 64 字符／字符白名单；空名和 NUL 仍不支持。MySQL 物理 schema/relation/column 保留 64 字符、BMP 和无尾空格约束；CTE／别名角色不套用物理尾空格限制。该包络不代替服务器全部对象命名规则。
- MySQL `sql_mode` 是完整数组，未配置时继承首个物理会话的完整集合。初始化 listener 在每个 connect 及 SQLAlchemy 自身方言检测前运行，必要时 SET 并回读；同值不再多读一次。显式配置要求展开的单项模式，不接受 ANSI/TRADITIONAL 等组合别名。适配 ANSI_QUOTES、NO_BACKSLASH_ESCAPES、PIPES_AS_CONCAT；HIGH_NOT_PRECEDENCE 返回 sql_mode_unsupported。未知／不支持的服务器行为不得作为通用兼容保证。
- 任意可信 MySQL execute 和完整写事务在确定结果后销毁所用物理连接，避免模式／临时对象带回业务池；受控 read/metadata 才复用。代价是可信操作之后重新连接；销毁失败不篡改已确定的 mutation outcome。直接使用私有 engine/DBAPI 的扩展必须自行维护这个约定。
- `database/transport.py` 只保护 SQLAlchemy 对冒号的绑定识别；仅真实占位符绑定。字符串、名称、注释及原有反斜线在驱动收到的 SQL 中保留，不用 AST 重写／转译执行 SQL。标识符 renderer 只做名称组件引用，不承担传输转义。
- SQLite 物理连接安装稳定 authorizer，adapter RLock 覆盖准备、执行、取完结果、完整写事务与清理；DBAPI `cached_statements=0`，不等同于 SQLAlchemy 编译缓存。可信固定元数据准备在回调激活前执行，回调中不再执行 SQL。超时覆盖视图准备和执行；回调异常安全拒绝，使用 DENY 而非 IGNORE。
- 视图依赖按实际默认／限定 schema 解析，并记录 view／内部 CTE 来源边；视图 grant 不允许直接读取底表。每次请求重新建立来源链，不跨请求复用授权结果；上限为 2048 次目录查找、128 个视图和 1024 条来源边。依赖含不支持的虚拟关系、同名跨 schema 来源、与用户 CTE 冲突的来源标签或嵌套重名 CTE 时返回 view_scope_unresolved，不猜测来源。SQLite 某些 rowid／计数计划产生 database=null 的空列 READ 事件，仅绑定到当前分析唯一、已由目录解析的候选对象；有歧义仍拒绝。
- 物化／常量 CTE 的 COUNT(*) 可能产生 database=null、列名为空的 READ。只对声明唯一、且独占准备时所有已附加目录均无同名物理对象的 CTE 标签接受该事件；不把它当作表授权。每个真实底表 READ、受限函数和操作仍独立检查；跨目录同名／作用域歧义保持保守拒绝。这是完整 Luna 任务发现后的补修，原试验与修复后验证分别归档。
- schema、UDF 和 Python Skill 是可信部署内容。authorizer 检查编译动作，不保证在每次函数求值（例如已加载 schema 的生成列）重新发出 FUNCTION 回调；不承诺所有函数无副作用。外层取消也不能强制停止所有同步数据库工作。MySQL 没有等价的本地 authorizer；会话初始化及销毁不等于隔离任意存储例程的副作用。

决议：本轮分别完成 AST 与 authorizer 接入，不以解析成功证明数据库语义，也不等待完整 SQL 语义引擎才修复现有名称边界。支持子集仍拒绝 FROM 派生／括号关系、单引号关系、ODBC、TABLE 查询表达式、原始 SHOW／PRAGMA 和既有保留调用；这不是可任意执行 SQLite/MySQL 语法的工具。业务读取仍一次工具调用，内部检查增加数据库和 CPU 工作，成本与模型任务单独测量。

## 2026-10-17 读取边界补修（DRR-2026-107、108）

最新补充：触发器子查询 CTE 空列 READ 按实际来源、owner／片段／scope 接入回调外准备，覆盖纯 SELECT／WHEN 及多触发器重复局部名；真实物理依赖及函数独立检查。共享连接锁、累计预算及截止时间，不把局部标签加入全局授权集合。DRR-108 对此边界重开后已补修，限定重启验收 57 项通过，最新证据见[局部 CTE 报告](../validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md)；下文关闭记录保留前批范围。触发器局部重复名支持不能推广至外层所有 scope：两个独立外层子查询复用局部 CTE 名仍保守拒绝，前后源码及原生已验证，不同局部名可恢复；后续扩展另补 scope／冲突矩阵。

再后续相邻审计确认 WHEN 中 begin 列误作正文标记，DRR-108 对新边界重开；旧限定关闭保留历史范围。该审计时源码的完整 Luna 销售任务通过 2/3，Host 可用性失败与生成列既有信任边界单列，见[审计报告](../validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md)。

上述 WHEN／BEGIN 问题随后按表达式真实角色补修：可选 FOR EACH ROW 后，现有 SQLite SQLGlot 解析消费完整条件，再要求正文标记；原始 WHEN 与各片段仍独立分析，运行原 SQL。多一次表达式解析，无新增 I/O／grant／Agent 必需调用。当前 2275 回归及安装 394 次通过，维护者重启后原生限定核验 57/57 通过；三个实际子会话先各做真实 canary，再各完成双轮销售任务，最终 3/3，保留一次不支持 FROM 形态的拒绝与自主恢复，旧 2/3 不改写。专用触发器仍为同源码回归／安装覆盖，DRR-108 据此限定关闭；Host 目录缓存与就绪客户端的排查另见[最新报告](../validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。

后续复评确认触发器 READ、WITH 后 REPLACE 和 UPDATE OR 遗漏，DRR-108 曾重开，现按验证范围关闭（重启后原生 42/42）；当前补修及驻留状态见[后续报告](../validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md)。以下前批观察保留其源码范围。

前批完成结论保留当时范围；评审发现的元数据数据读取遗漏与非执行型 EXPLAIN 回归已补修，维护者重启后原生 28/28 检查已通过；sample／table_summary 未在该 Host 暴露，跨入口函数视图细节保留同源码安装／回归覆盖。完整[补修与验收](../validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md)独立归档。

- 可信目录查询与会求值视图的数据读取分开：sample、精确计数走 execute_read；SQLite 估算使用有界 CTE、读取前核验配置授权，之后同样激活 guard。目录／索引／sqlite_stat1 保持可信。估算拒绝返回 null，保留列／索引。
- 所有分析根关系在回调激活前核验；视图 COUNT 丢失来源的空数据库／空列 READ 仅绑定唯一候选且匹配已授权视图边，不授予底表直接访问权。内部 CTE 的 marker 计数不依赖合成 CTE 的空列事件。
- SQLAnalysis 记录 explain_payload 并绑定原 SQL／上下文；仅确认的 SQLite INSERT／UPDATE／DELETE（含 REPLACE 投影）计划允许相应编译事件，仍检查每个实际目标、函数和来源。实际 DML、PRAGMA／DDL／ATTACH 不获豁免；计划输出可合法为空。
- 不新增配置、框架、依赖或 Agent 必需调用。新增内部分析／目录检查成本不引用前批计时作为零开销证明；MySQL 没有 SQLite authorizer，schema／UDF 可信范围仍保留。

## 参考与本项目取舍

本批 EXPLAIN 后续实现：SQLite 在真实 statement dispatch 解析 REPLACE，在 UPDATE 角色解析五类 OR 子句；执行原 SQL。计划仅按实际关系 grant 放行编译读取，缺少绑定／视图边时 DENY 后在回调外有界补查再准备。所需触发器 WHEN／BEGIN...END 区域按原 token 切分，语句本体继续共享 SQLGlot 分析；不新建 CTE 解析器或通用触发器框架。每请求累计 2048 次名称目录查找、最多 128 个新增准备请求，维持图预算和统一超时；所有重试持有原连接锁。普通读取／实际 DML 不获得计划豁免，未授权底表不能借视图边；不支持定义或来源歧义明确拒绝。

- [MySQL 名称规则](https://dev.mysql.com/doc/refman/8.0/en/identifiers.html)：按对象角色解释，不增加通用 trim。
- [MySQL SQL mode](https://dev.mysql.com/doc/refman/8.0/en/sql-mode.html)：采用会话初始化约定，保留完整集合。
- [SQLAlchemy MySQL 初始化](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#changing-the-sql-mode)：每个物理连接执行，并考虑监听器先后顺序。
- [SQLite 表达式及常量](https://www.sqlite.org/lang_expr.html)：SQLite 词汇与数据库原生查询对照，不能直接继承 SQL 标准／其他方言的裸函数名。
- [SQLite authorizer](https://sqlite.org/c3ref/set_authorizer.html)：编译期授权及重编译约束，保持完整生命周期。
- [SQLGlot MySQL 实现](https://sqlglot.com/sqlglot/dialects/mysql.html)：项目负责会话模式适配，解析成功不证明数据库语义正确。

项目尚未正式发布；本轮不增加旧 env、旧入口、旧 SDK 或假想调用方迁移兼容层。维护者手动重启 MCP；配置数据库写入和本地连接修改继续按实际授权处理，私有测试夹具自动清理。
