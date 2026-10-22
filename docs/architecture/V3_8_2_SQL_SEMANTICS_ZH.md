# v3.8.2 名称、方言语义与执行保障设计

日期：2026-10-16。维护者批准基于 3323f9c 实施；本文区分契约、各批已完成的实现／验收和剩余复验，不以设计描述代替通过证据。

## 后端验收范围（2026-10-21 维护者确认）

SQLite 继续按原生真值验收；MySQL 方言及服务端行为以 MySQL 为基准。MariaDB 不作为本轮验收条件，不默认增加兼容专项或测试实例。仍保留实际已测 MySQL 版本、大小写／会话配置的准确范围，不将单实例结果泛化为所有配置。

## SQLite 写入事务与完成态计数（2026-10-22，DRR-142／143）

此节保持SQLite契约；同日后续DRR-144／145已补MySQL原SQL绑定和真实InnoDB门槛。两后端execute_read都核对分析完整性、当前方言／会话及analysis.source_sql；内部已分析对象不得与另一SQL组合执行。匹配调用保留原SQL和绑定参数，不增加Agent步骤。事务性业务真值由测试独立连接观察，包含触发器／级联，排除自增分配等非回滚状态；不加入生产全库比较。真实服务器错误、物理自建会话断开和定向客户端注入分列记录；新矩阵通过不能泛化为所有引擎／模式／故障。[MySQL源码／安装证据](../validation/v3.8/V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md)的父检查点保留；[维护者重启后六项限定原生](../validation/v3.8/v382_mysql_write_contracts_2026_10_22/resident_restart/README.md)另已通过。三门槛已落实为[16类契约的有限执行表](../validation/v3.8/V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md)，后续[独立验收](../validation/v3.8/V3_8_2_STABILIZATION_2026_10_22_ZH.md)已在该范围通过；不外推到更广能力／故障或全部原生Host场景。


事务与结果证据属于执行适配器，不由解析成功保证。execute_write 在同一独占连接上核验真实 BEGIN，再执行原 SQL；在现有截止时间内分批取完并关闭 RETURNING／count_changes 结果，取完成后的原生计数。未知计数仅在实际 DML 根角色下用同连接 changes() 补充，避免 SELECT／DDL 继承旧值。不累计触发器／级联或返回行。

SQLite rolled_back 要求回滚前真实事务活跃、有效连接、回滚正常返回及之后事务结束；COMMIT 回执不明仍 unknown，无法确认清理时退休连接。MySQL 的既有证据规则独立；不引入全局 BEGIN event，不改变读取 authorizer／连接生命周期、配置、依赖、临时 sqlparse 回退或 Agent 必需步骤。源码／正常 wheel 私有文件库覆盖成功、失败、重放及清理后的独立真值；驻留重启状态与成本单列。[契约、代价与证据](../validation/v3.8/V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md)。

## 主键身份与成员顺序（2026-10-21，DRR-141）

列模型新增可选 `primary_key_position`：真实 PRIMARY 成员的一基正整数位置，非成员省略。SQLite 直接保留 table_xinfo.pk；MySQL 的单读及有界批读在原 COLUMNS 查询中左连接实际 schema／表／列的 KEY_COLUMN_USAGE、限定 PRIMARY，使用二进制残余比较保护存储组件身份。原生 COLUMN_KEY 展示值独立保留，不据 PRI 猜主键。失败沿用 metadata_query_failed，不伪装空主键。

compact 按位置排序实际成员，full／describe／可选 summary 保留位置；分组签名自然包含该字段，反序键不再合组。列顺序仍为表列序。位置可能有间隔：SQLite PRIMARY KEY(b,a,b,c) 的成员位置为 b=1、a=2、c=4，完整重复键项及方向／collation 仍看 describe.indexes。成员摘要、物理键与完整 DDL 是不同契约，不能据此扩大合组保证。

不新增每表索引查询、缓存、开关或解析适配，不改授权／读取 authorizer／原 SQL。接受 MySQL 目录连接、成员字段和分组增长成本；可核查矩阵及局部测量见[修复记录](../validation/v3.8/V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md)。

最新重启后12/12原生对齐目录。十五项同任务真实Luna业务通过，调用／token小幅增加、模型端耗时明显上升；三次弱提示解释仅1/3严格措辞通过，均未写入。程序成本、模型规划和引导效果分别评价，不能据此新增状态缓存或放松执行边界。[本次完整验收](../validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md)。

## 关系调用角色与生成列（2026-10-20，DRR-129／130）

SQLite 关系调用头按具名对象解析，不应用标量函数别名或参数规则；FROM／JOIN 与表形式 IN 共用此路径，保留组件、引用、位置和参数。真实参数表达式仍完整分析，原 SQL 执行。JSON 调用保留有条件的模块使用事实，运行期先解析当前目录对象：实际 FTS5 按根／schema 授权及模块核验，内置 JSON 按其专有作用域，普通同名对象不得继承内部能力。

Skill 私有 `_inferred_analysis` 缓存保存不可变分析，包括有条件的虚拟关系事实；该批从默认 schema 快照补充实际依赖，授权／目录／可执行状态不缓存；2026-10-21 补齐非默认／未知状态及固定 TEMP 名称观察，见下节。元数据使用 table_xinfo 返回 hidden=0/2/3，排除 hidden=1；generation_type 及 compact generated_columns 均纳入适配器元数据签名，不推断表达式／完整 DDL 相同，不求值生成表达式。MySQL 投影不变。公开配置及临时 sqlparse 回退检查点不变。[契约、代价及当前验收](../validation/v3.8/V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md)。

## 目标与约定

1. 继续使用 RelationReference(schema, name) 表示解码后关系引用。原始 token、引用方式、源码范围、对象角色与作用域保存在分析记录；显示字符串不作为授权键。不 trim、Unicode casefold 或反复解码业务名称。
2. 区分物理关系引用、CTE、表别名和结果列别名。MySQL 数据库／表／列的尾空格规则不套用到所有角色；非法名称不自动修正为另一个对象。SQLite／MySQL 名称规则分别验证。
3. SQL 分析使用显式方言和受控会话上下文，统一输出语句、关系、作用域、调用、参数、不支持项与完整性。部分分析／失败不能表示为没有依赖。始终执行原 SQL 和原绑定参数。
4. 项目授权独立于数据库名称等价。引用方式等价不产生新 grant；限定名与名称内点号保持不同身份。结构化授权声明表达单个含点号名称，现用字符串表名仅作为明确的声明简写。
5. Query、Skill 与 readiness 共用名称及分析语义；Skill 缓存区分方言／会话上下文。元数据消费已授权的结构化对象和固定模板，不把可信操作能力暴露为工具参数。
6. 保持已授权视图可经该视图读取，不把底表变成可直接访问对象。authorizer 的视图来源需核对依赖链及 schema，不能见到非空 source 就放行，也不机械要求调用者同时具备全部底表 grant。
7. 正常业务读取保持一次 MCP 工具调用。运行时内部检查和首次连接初始化不作为 Agent 必需的新步骤。不得据此承诺相同 token、延迟或总成本。

## 尾注释／绑定身份与列接口收敛（2026-10-20，DRR-124—127）

- 读取分析完整检查原始注释，语句形态忽略合法HINT trivia及无执行内容的尾部Semicolon节点；真实第二句与受限目标／函数仍拒绝。保留原SQL及token位置，不拆分重写SQL。
- 受管分类共享传输层named_parameters／statement_text，按方言及会话区分真实绑定和字面／注释／引用名称冒号。每个启动候选同时检查形态及精确声明名；面向目标和消费token后仍重新取得实际上下文。classifier内部接口增加可选不可变参数名集合，LRU键相应增加声明名，不缓存值／权限／readiness／失败连接。旧绕过做法中的假参数应删除。
- Query Skill启动仅需存在一个允许候选，故首个允许可短路；全部拒绝仍返回首个完整决定。get_full_schema先授权／截断／检查名称，再调用显式get_columns_batch；基类逐表组合，MySQL每批最多199名称加schema绑定，保留精确名称／列序、整体失败语义。describe_table单表路径保持。定制MySQL列行为需覆盖新钩子，不探测旧接口做兼容。
- 请求内纯读取复用研究覆盖冷／暖推断、raw、窗口视图和物化CTE触发器计划。收益集中在冷推断，所测暖态无重复键；**不接入通用生产缓存**。未来优先评估直接传已有分析，禁止扩成状态／授权缓存；SQLite连接独占、authorizer及禁用statement cache的生命周期约定保持。

源码／安装通过，维护者重启后当前驻留34/34限定检查通过；定量成本、显式sqlparse旧限制和扩展代价见[实现记录](../validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md)。下方“尚未实施”小节为此前审计检查点。

## 受管分类复用与 readiness（2026-10-20）

readiness 只评估所需关系、默认 schema 覆盖和目录可用性；发现／详情仍独立评估完整可执行策略。受管分类使用实例内最多 128 项 LRU，精确键包含原 SQL、整个不可变 DialectContext（方言、完整模式、CTE 大小写、默认 schema）和解析器；只存不可变 PolicyDecision，包括纯分类拒绝，不存 AST 或数据库状态。原 SQL 不 trim／重写，名称组件不合并。

每个相关请求仍获取实际目标语义、检查独立授权／参数／readiness；确认消费 token 后再次获取上下文，命中仅省解析。MySQL 的每物理会话初始化／退休约定不变。连接失败在缓存外处理，异常不缓存；实例关闭清空，LRU 容量约束条目数，不是字节预算。并发 miss 可重复纯计算，不引入每键锁或 single-flight 框架。不新增 TOML 开关、依赖或 Agent 步骤；该 DRR-120 检查点未调整提示注释和 HIGH_NOT_PRECEDENCE；后续支持见下节。见[验收与成本](../validation/v3.8/V3_8_2_MANAGED_CLASSIFICATION_REUSE_2026_10_20_ZH.md)。

## 方言注释与 NOT（2026-10-20，DRR-121—123）

SQLite 按原生语法把块注释（包括 hint／MySQL directive 形文本）当空白，双横线不要求后续空白；字符串／引号名称中的文本不当注释。MySQL 从原始 token 间隙及每个 HINT 区域完整检查，不能只看 SQLGlot 保留下来的第一个 hint。先支持已知执行计划名称及扁平名称参数；SET_VAR、RESOURCE_GROUP、MAX_EXECUTION_TIME、未知名字、嵌套表达式和解析不完整的形式继续拒绝。提示不产生表 grant，不能隐藏真实函数或物理关系；是否被服务器应用不由项目解析保证。

检查通过后仅从分析 token 流移除 HINT；保留原 SQL、全部非 hint token 原始位置和执行绑定。此举避免 hint AST 自己的相对位置污染业务名称／函数分析。MySQL 方言的现有 UNARY_PARSERS 分派项区分原 token 的 ! 和 NOT；实际模式控制 NOT 的一元操作数解析层级，不新增 parser 方法覆盖或 SQL 重写。私有分派／_prev／解析方法仍是固定版本依赖，升级要重放16种模式与原生真值；不宣称通用解析器支持。

受管计划启动按数据库声明筛查SQLite加16个MySQL模式组合（两方言均声明时共17候选）；实际发现／预览／消费令牌后的复验仍绑定目标上下文，物理会话初始化不变。Query Skill的启动预筛单独使用SQLite及4个MySQL引用／转义模式候选，首个允许短路；具体目标仍做完整上下文分析，不能把两类启动候选数混用。sqlparse显式回退保留旧行为，不能概括为获得新hint约束；无目标的旧shape convenience helper继续跨候选保守判断，数据库能力以明确context的共享策略为准。详见[三项验收](../validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md)。

## MySQL 会话

- 配置可显式指定完整 sql_mode 集合；未指定时继承首个初始化会话的完整集合，并将后续物理连接初始化为相同约定。每条物理连接均在 SQLAlchemy 方言检测和业务使用前初始化／校验，重连和池重建同样处理，不只使用 first_connect。
- SQLGlot 的 mysql 方言不自动读取会话。ANSI_QUOTES、NO_BACKSLASH_ESCAPES 等影响解析的设置由项目适配器处理，不能只读另一个连接就假定执行连接一致。
- 正常请求不新增每次模式探测。此前提要求项目控制连接使用路径；可信扩展如需改变会话状态或创建临时对象，必须隔离或销毁污染连接。默认 rollback 不等于模式／临时对象清理。
- 会话上下文与 CTE 名称比较能力分开表达；现有常量 CTE 探测的结果不能用来推断 sql_mode。MySQL 配置库限定名也不能独自保证不存在同会话临时表遮蔽。

## SQLite 执行保障

- 元数据表发现与估算分开：get_table_directory 仅返回有序表名及廉价目录估算；公开工具先授权、统计可见总数并截断，再 enrich_row_estimates。SQLite 在本次调用内批读选中名称的统计，缺失／无效时逐表执行原有受控限量计数；MySQL 目录自带的估算直接复用。get_tables 保留完整目录加补全的适配器便捷入口；第三方 adapter 需实现新的目录方法，不增加旧接口探测／回退兼容层。
- 固定统计先按每批最多200个名称绑定读取整表统计；缺失／无效时，按真实index_list／table_list核验完整索引或WITHOUT ROWID主树，最多128个索引候选。部分索引不代表整表，无法确认时回退受控有界估算；不跨请求缓存，也不保证多语句原子快照。不自动运行 ANALYZE；统计消失回退受控读取，超时等实际错误保持元数据失败。无冒号 SQL 可跳过传输层分词，仍须经过读取分析／授权／authorizer；带冒号路径保持原有识别。详见[元数据优化](../validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md)。

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

- `core/analysis.py` 输出不可变 `SQLAnalysis`：语句、关系集合、每次关系使用及来源、名称词法位置／角色、CTE 声明／作用域、函数、参数和不支持项。`complete` 仅代表本项目投影完整，不代表服务器语法／对象／列有效；未知结构返回 partial/failed。raw 和 Query Skill 共用 `_prepare_sql_read`，readiness 按同一方言上下文推断，缓存键包含模式和 CTE 比较规则。旧 `core/structure.py` 及重复读取解析已删除；受管写入保留独立规则，10 月 20 日默认迁移 SQLGlot，sqlparse 仅为临时显式回退，不将读取策略当成写入批准。
- SQLite 前向声明和隐式递归按真实 SQLite 规则生效；MySQL 保持定义顺序及显式递归自引用。SQLite 业务名称和 SQL 保留词仅折叠 ASCII；SQLGlot 的 Unicode 关键词／函数规范化不会改变原始授权名称。只在真实名称槽适配 contextual 名，声明不屏蔽查询体。 SQLite 仅保留实际 CURRENT_DATE／CURRENT_TIME／CURRENT_TIMESTAMP 无括号词汇；CURRENT_USER／LOCALTIME 等普通业务列不套用其他方言的函数语义，真正的受限调用仍拒绝。
- `read.relations=[{schema="main",name="main.orders"}]` 授权单个含点表名；省略 schema 表示默认 schema 的对象，默认裸名／限定名共享授权。Skill YAML 可用同名 `relations` 映射数组；它是约束和依赖声明，不产生 grant。`tables` 仍是首点拆分的简写，显示标签不重新解析。full Query Skill 新增 `analysis_complete`，不完整时 inferred_tables=null，不声称无依赖。readiness 仍只核验默认 schema。
- 元数据名称改为方言支持包络加逐组件引用，SQLite 不再套用统一 64 字符／字符白名单；空名和 NUL 仍不支持。MySQL 物理 schema/relation/column 保留 64 字符、BMP 和无尾空格约束；CTE／别名角色不套用物理尾空格限制。该包络不代替服务器全部对象命名规则。
- MySQL `sql_mode` 是完整数组，未配置时继承首个物理会话的完整集合。初始化 listener 在每个 connect 及 SQLAlchemy 自身方言检测前运行，必要时 SET 并回读；同值不再多读一次。显式配置要求展开的单项模式，不接受 ANSI/TRADITIONAL 等组合别名。适配 ANSI_QUOTES、NO_BACKSLASH_ESCAPES、PIPES_AS_CONCAT 与 HIGH_NOT_PRECEDENCE；前缀 NOT 按实际模式分组，! 始终高优先级，中缀 NOT IN／BETWEEN／LIKE 仍按原语法处理。未知／不支持的服务器行为不得作为通用兼容保证。
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

## 2026-10-18 已提交版本复核与独立 P3

首次复核时，e49cd0e 再次通过 2275 项回归、类型／提示及源码／封存核对。SQLGlot 30.22.0 对合法的 SQLite `IS NULL COLLATE`／`IS NOT NULL COLLATE` 存在解析兼容回归，authorizer 尚未参与；记录为开放、非阻断 DRR-109，不重开触发器／计划的 DRR-108。所报常量例可写为 `NULL IS (NULL COLLATE NOCASE)`；不能机械地将整个判断加括号，字符串比较可能改变语义。后续修复须在真实运算符优先级及拒绝对照下验证，该阶段未改原 SQL 或完整性策略。

新证据、旧版同输入对照及该阶段文档核对见[复核报告](../validation/v3.8/V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md)；该只读复核阶段仅增加文档／证据，当时运行资源与 e49cd0e 一致。下文记录随后获准实施的补修。

## 2026-10-18 操作数补修（DRR-109，限定复验通过）

维护者批准修复后，SQLite Parser 对 IS／IS NOT 的 NULL／参数右值及 LIKE ESCAPE 右值改用既有表达式优先级入口，保留 COLLATE 作用位置、真实依赖和函数；原始 SQL／参数继续执行。其余 IS 形态及 MySQL 不扩大改动。新增 100 项、全量 2375 项及源码／wheel 两协议验证通过；不新增数据库探测或 Agent 必需步骤，未做新的成本 A/B。重启前四例拒绝保留；维护者重启后 25/25 项原生验收符合预期，前后完整五行五列快照相同。DRR-109 按源码／安装及该原生范围关闭，DRR-108 保持限定关闭。[最新实现与证据](../validation/v3.8/V3_8_2_COLLATE_REPAIR_2026_10_18_ZH.md)。

后续只读复评时发现完整 ISNULL／NOTNULL／NOT NULL、IN／NOT IN 判断后直接接 COLLATE 仍有既有解析误拒，当时登记开放 DRR-110；当时给完整判断加括号可恢复，移到 IN 左操作数会改变语义。这组形式当时仍经过上游 range 路径，与已补修的 IS／ESCAPE 右值入口不同。该阶段只评估并建议同层定点适配，未改运行代码。[实测、范围与建议](../validation/v3.8/V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md)。

维护者随后批准实施：SQLite range 返回后按实际优先级续接后缀、算术／拼接／位运算和 JSON，再交回原 range；完整判断在 AST 中保持独立结合，复用现有节点及操作数解析。此处增加方言适配与轻量解析检查，未改原 SQL／授权／依赖，新增 190 项及最终 2565 项回归、524 次安装验证通过；维护者手动重启后 71/71 项原生计划符合预期，前后完整五行五列快照相同，DRR-110 按已记录源码／安装及原生范围关闭。七项既有生成器打印差异有原 SQL 工具对照，不将生成 SQL 用于执行。[实现、成本与限制](../validation/v3.8/V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)。


## 2026-10-19：读取能力与范围收敛

维护者批准外部反馈后的独立修复方案。all 的 `*` 绑定配置默认 schema；跨 schema 使用既有结构化 allowlist，不增加 all＋例外或 read.scope 组合。裸 grant 在加载时绑定默认对象，前置早拒、正常授权、Skill 显式依赖、readiness、元数据与实际编译统一语义。RelationReference 继续保留组件；数据库名称等价不扩大到其它对象，MySQL 临时表及 DEFINER 视图／函数边界保留。

SQLite 表名适配保留实际 SELECT／WITH 查询分派；视图定义可完整分析派生关系，raw FROM 子查询仍由形态策略拒绝。新增 VirtualRelationUse，已知 JSON 调用与物理关系区别记录，参数表达式／相关子查询仍递归分析。SQLite 内置 JSON 的实际 main 绑定以原生回调验证，不从视图所在 schema 推断；同名存储对象不冒充内置模块。未知命名表调用只在执行连接目录核验为受支持 FTS5 后获得内部能力，其他虚表普通扫描继续既有检查。

FTS5 能力在回调外、有界准备：核验实际模块声明、影子对象的名称及 shadow 类型、external-content 的实际身份和 FTS 列／rowid。每请求独立核验直接根，不把模块依赖写入用户 grant；仅在核验根存在时提供限定 data_version 内部能力。FTS PRAGMA 与直接 PRAGMA 的回调参数可完全相同，不能声称 source 证明模块来源。保留完整分析＋执行检查的分工、原 SQL／绑定、连接独占、每请求清理及模块缓存限制；不能用预热成功或 DBAPI cache=0 推断所有内部语句每次重报。

分析另记录锁读和会话赋值：普通读取拒绝执行型锁读，确认不执行的 EXPLAIN 另判，执行型 ANALYZE 维持拒绝。SQLite 目录别名的 COUNT(*) 与列读取按相同授权处理；不新增目录禁令。MySQL 库名展示取配置绑定、固定连接诊断用 metadata，上层可信扩展／写事务的会话废弃不变。

**不提供 authorizer 的 TOML 关闭开关。** 关闭会改变实际对象／视图操作检查，增加两套运行及验收契约，且不能解决前置解析兼容问题。本轮按对象和操作修补兼容性；有具体替换需求再单独设计扩展责任，不把关闭当作等价优化。无新增运行依赖或 Agent 必需调用，准备工作及内部读取增加的开销另测。当前源码、安装、原生／完整任务状态及 DRR-111—115 见[本批记录](../validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md)，此前关闭与证据保留各自范围。


## 2026-10-20：FTS 预热函数检查与具名 schema（DRR-116／117）

core/read_rules.restricted_function_code 只接收已按 ASCII 折叠的函数身份集合，供原始读取策略、SQLite FUNCTION 回调及可达视图／触发器分析准备共享；不依赖 SQLAnalysis 类型，也不重跑完整 raw 形态／授权策略。视图已完整分析后检查保留函数，再准备其虚拟依赖及能力；每请求重新检查定义，不信任可信 FTS 完整投影留下的模块编译缓存。保守检查整个可达定义，未选用的受限表达式也拒绝；正常派生内容视图继续通过。没有额外 SQL 解析、目录读取或 Agent 必需步骤，只有对已有函数事实的检查；生成列与可信UDF边界不扩为完整沙箱。

VirtualRelationUse.kind=builtin 才应用内建调用默认 schema 限制，sqlite_named 的显式 aux／temp 组件授权和 FTS 实际模块核验保持；不扩大 all、未知虚表模块、直接内容／影子 grant 或非默认 readiness。原 SQL／绑定、连接独占、重试限额及异常清理不变。[本轮验证、成本和重启状态](../validation/v3.8/V3_8_2_FTS_FOLLOWUPS_2026_10_20_ZH.md)。

## 2026-10-20：受管写入分类迁移（DRR-119）

`core/managed_sql.py` 复用现有 `_tokens` 的方言／会话词法和 parser 的公开 parse，独立检查单个 INSERT／UPDATE／DELETE AST、嵌套写入及原始主语句动词。根 CTE 名称通过源码位置排除，避免 bare REPLACE 被 AST 归一成 INSERT 后意外允许，同时保留 INSERT OR REPLACE。共享注释事实按实际方言检查；SQLite注释按空白，MySQL可执行／状态／资源／超时／未知hint或歧义注释拒绝，已识别的计划hint子集允许；字符串及引号名称中的文本保留。没有新增 SQLGlot `_parse_*` 覆盖或执行 AST 生成 SQL。

`skills/mutation.validate_managed_mutation_plan` 保留原计划字段、SQLAlchemy 命名绑定集合和值来源检查。catalog 在启动时按 databases 候选方言筛查；`skills/access` 在已授权、类型兼容的目标上校验可执行性；`core/mutations` 在预览回调前核验，`run_managed_mutation` 在令牌消费后、adapter 写调用前复验实际上下文。确认期失败返回 managed_plan_validation_failed／not_executed，令牌仍不可重放。预览期失败复用 validation_failed，不签令牌。

复验使用 resolve_analysis_context；真实 adapter／测试替身都须履行该现有接口，不猜测缺省方言。MySQL 的实际写连接受现有每物理连接初始化规则保证；无需新增适配器方法或每请求模式查询。读取与写入共享方言基础而不共享批准规则；写入仍属于可信完整事务路径。

临时配置与移除时点遵守维护者选择：默认 SQLGlot，显式 sqlparse 回退，保留依赖至观察期评审。B32 的双实现及既有私有 Parser 维护风险尚未完全关闭；本批缩小默认依赖路径，未证明所有 SQL 等价或数据库语义正确。[语料、范围与验收](../validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md)。

## 2026-10-20 相邻复查：尚未实施的补齐

本节保留当次仅审计检查点；DRR-124／125随后已批准修复，当前行为及验收见本文前面的“尾注释／绑定身份与列接口收敛”及[实现报告](../validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md)，不将下文历史开放状态当作当前未修结论。

DRR-124／125仍开放：读取计句须区分尾注释AST节点与真实第二语句；受管加载／目标校验与执行应共享真实绑定词法身份，不能只用原始SQLAlchemy text扫描。此次只登记和测量，不改运行实现。后续优先补两项，再分别做启动候选首个通过短路和已授权／截断对象的有界列批读；原型不是现有adapter接口，不缓存授权／目录或恢复statement cache。当前范围、局部性能样本及代价见[复查](../validation/v3.8/V3_8_2_FINAL_AUDIT_2026_10_20_ZH.md)。

## 共享读取结果与三态依赖（2026-10-21，DRR-131—134）

读取结果在数据库执行之后、OperationResult／协议编码之前，经同一 _prepare_read_result 处理。实际 Row 标签在转 dict 前检查；值递归变为明确 JSON 表示，二进制及非有限数值保留类型；未知对象不再以 __dict__／str 暴露。单行 JSON 只在限额计算中编码一次，以前缀累加 brackets／comma 的字符数确定返回行数，允许零行。应用错误与数据库异常独立，Query Skill 的失败审计仍记录失败；原 SQL、参数、读取策略和写入执行结果边界保持独立。

SkillSchemaSnapshot 增加仅限本次观察的 JSON TEMP 同名对象事实。SQLite 固定查询两个名称，不读取对象数据；未限定 JSON 调用先考虑 TEMP，明确 main 只使用 main。解析缓存保留条件语法；readiness 将条件身份分类为 builtin、stored 或 unverified，后两者进入依赖列表，未知不等于缺失。发现／详情／执行前检查共用该结论；其他 schema 不因此获得 readiness 覆盖。关闭 readiness 不进行目录探测。成本是 SQLite 启用 readiness 时每次快照增加一条固定目录查询，不增加 Agent 必需工具调用。

DRR-135后续已批准补修：get_json_name_observation以SQLiteJSONNameObservation替换旧TEMP集合，保留两名称的有序关系、成功schema前缀及complete。固定PRAGMA database_list后按TEMP→main→附加顺序观察，最多32个schema，共用观察查询超时；只完整缺失才判builtin。部分观察保留未知未限定身份，已找到的前缀存储对象仍有效；显式main及普通Skill不因无关观察失败连带误拒。显式／未限定绑定到同一存储对象时均为stored，非默认readiness仍无法核验。不新增框架／缓存／开关，不改authorizer。[当前实现及代价](../validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md)。

DRR-136随后已批准补修：列与索引元数据统一采用固定main绑定PRAGMA，目标按字符串字面量编码，避开同名业务对象；Python保留原列／索引投影，索引整组持现有连接锁。有限取回及原索引数／键／字节／时间预算保持；N个实际索引由2次变N+2次目录语句。此内部目录路径不代替实际读取策略／authorizer，不新增配置或缓存。[实现、成本及限定重启核验](../validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md)。

此处不新增 AST 适配、授权能力、通用缓存或配置开关，也不更改 SQLite authorizer 回调。[本批契约、成本和验收](../validation/v3.8/V3_8_2_READ_RESULTS_2026_10_21_ZH.md)。

DRR-137／138后续已批准补修：FTS固定PRAGMA按实际schema逐个核验影子名称及类型；统计只使用整表／已核验完整索引来源，超预算候选回退受控估算。相邻DRR-139将external-content隐式rowid映射到实际编译列：显式同名列优先，核验INTEGER主键别名、DESC例外及WITHOUT ROWID，不把可信预热当正确性证明。所有目录工作仍在独占连接的回调外、受查找／取回／时间预算约束；不新增解析框架或缓存。接受额外目录成本；维护者重启后10/10既有别名原生核验通过，专用碰撞／部分索引／冷态夹具仍保持源码／安装范围。[实现和当前验证](../validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md)。


## SQLite声明类型表示（2026-10-21，DRR-140）

get_columns直接保留table_xinfo的原生类型字符串；空字符串不再补为TEXT，也不改写成BLOB／UNKNOWN／null。describe_table及可选summary的data_type、full的type、compact列对第二项共用此值；生成列／隐藏列及列序契约保持。不增加目录查询、求值、AST适配、缓存、配置或Agent固定调用。

该字段提供数据库报告的类型元数据，不推断亲和性或实际存储类。普通未声明列、显式空类型、表达式视图可能提供相同空字符串，但不能据此认定完整语义相同；当前SQLite3.45.1下n与n ""的比较行为还可不同。STRICT ANY及生成列依其原生声明报告，不按已有行或表达式推断。compact继续仅按adapter可见metadata分组；空类型与TEXT恢复区分后可能增组及响应体。

未来验收直接对比原生PRAGMA类型，不复用被测的TEXT补值。历史封存中采用相同补值的“真值一致”只证明该归一化投影一致，保留原字节和时点，不能作为类型无损证明。本轮源码／正常wheel验证及维护者重启后限定范围见[补修记录](../validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_REPAIR_2026_10_21_ZH.md)；此前137／138／139限定验收不重开。
