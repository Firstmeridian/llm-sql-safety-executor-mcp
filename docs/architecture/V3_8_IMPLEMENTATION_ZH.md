# v3.8 实施与决策记录

基线：`582822b4aa751516c4a7f7e738ea0c2708f0fea9`。重构前隔离测试：676 passed、4 skipped。

本次采纳三文件 TOML、实例级运行状态、可安装 src 包与独立提示词资源；将 MRTR 限于托管单语句写入，默认关闭。审批仍信任 Host，不声明服务端认证了真实人类。Tasks、多用户认证、分布式状态和跨重启恢复暂缓。

旧表白名单约束自由读取、元数据和 Query Skills，并不普遍约束 Mutation Skills。新 `read` 节保持此边界；写入由连接准入、Skill 白名单和执行计划约束。

配置迁移是破坏性变化：不读取旧 DB/Skills 环境配置，不保留 default-only 写入授权；未授权默认拒绝。显式密钥环境引用不属于配置覆盖。用户已有 `.env` 不删除。

安全不变量：未知目标不回退；所有请求固定目标；预览与执行绑定同一参数、连接和计划；令牌原子单次消费，消费后异常不恢复；不确定写入不自动重试；诊断 busy/cleanup_failed 不随请求或 scope 重置；审计仍为 best-effort。

验证记录将在各阶段完成后追加，未运行的 Host 或数据库场景不会记为通过。

完成后的自动化与实测分别记录在[阶段验收](../validation/v3.8/V3_8_VALIDATION_ZH.md)和[本地 live Review](../validation/v3.8/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：包含 Host 入口迁移/重连、真实 MySQL 连通与基础读取、原生 SQLite preview/execute 恢复，以及三组 Luna 六轮路由任务。后续[10 月 1 日记录](../../REFACTORING_LOG_ZH.md)确认原生 Codex IDE MRTR 批准、取消及未勾选拒绝通过；[后续原生记录](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)确认长等待后批准被框架拒绝且未写入，独立真实进程重启及新提案执行对照已通过，业务 TTL 有模拟时钟覆盖；原生业务 TTL/重启 UI、MySQL 写入仍未验收；用户提供的 Copilot 试验被协议门槛拒绝，尚未进入表单；新旧参考协议的结果不替代原生 Host 协商证据。提交 `1be44b4` 的远端 CI 因旧提示词断言失败，修复与重新验证见[9 月 27 日记录](../validation/v3.8/V3_8_REVIEW_FIXES_2026_09_27_ZH.md)。

## 审批信任归属补充（2026-10-01）

部署继续默认采用 preview/execute，MRTR 保持默认关闭并按实际 Host 显式启用。依据是[已测客户端的支持与验收范围](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)：Codex IDE 主要原生交互通过，Copilot 会话被协议门槛拒绝，仍有原生边界场景和证据缺口。此决定不宣称全行业兼容性，也不因默认流程选择而增强人工认证；不增加失败后自动切换写入入口的逻辑。

原有 preview/execute 的服务端门槛是 `confirm=true`、匹配的一次性 token 和既有权限/执行检查，不主动产生协议审批表单。参考 Host 可以用代码强制收集决定，但普通 Agent 自行调用两步工具时，聊天确认只是客户端行为约定。MRTR 将请求与批准响应纳入协议，并强制 accept/严格 true；仍不独立认证真人，自动化 Host 可提交同样响应。

MRTR 开关只控制额外工具注册，不移除旧 execute_mutation_skill，因此不是全局写入审批门禁。两条流程当前均采用可信 Host 模式 A。独立认证批准、Agent 无法取得批准凭据、所有写入路径不可绕过的授权检查尚未实现；沿用 [DRR-2026-050](../security/DESIGN_RISK_REGISTER.md#drr-2026-050-approval-boundary-follow-up-october-1-2026) 记录接受边界及重评条件。

## v3.8.1 拒绝恢复线索（2026-10-01）

版本升至 3.8.1（pyproject、包版本、MCP server 版本和锁文件项目条目）。本机无 uv，锁文件仅手工同步本项目 editable 条目的版本号，依赖解析未变；CI 仍用 `--frozen`。配置、授权、令牌与执行语义不变，无需迁移。

实现：`skills/access.py` 新增 `_related_available_skill_names()`，只读取被拒 Skill 自己的 `related_skills`，排除自身、未知名称及 Query Skill，并复用 `_get_skill_schema_snapshot()` 与 `_skill_availability_state()`，保证与 `list_skills` 的可用性判断一致。`core/mutations.py` 在 preview 与 execute 两个 `validation_failed` 分支调用它；异常只记录异常类名并省略字段，不改变审计、令牌或结果。MRTR 首轮经 `MutationService.prepare` 复用同一 preview 路径。`mcp/contracts.py` 声明可选字符串数组。

决策：服务端只给名称，不生成步骤或参数，避免把业务补偿逻辑或授权含义放进框架；仅列写入 Skill，因为报表类 Query Skill 不能达成写入目标。曾试验恢复 `preview_token_expires_in_seconds`，因 v3.7.1 已删除且相对秒数在对话中会过时而撤回。权衡与残余风险见 [DRR-2026-071/072](../security/DESIGN_RISK_REGISTER_ZH.md)、[安全说明](../security/V3_8_SECURITY.md#rejection-recovery-clue-v381)及[验收记录](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)。

结果解读引导（最初实现，同属 3.8.1；后续修订见下方 10 月 12 日复核）：实测确认 Copilot 只把工具名、说明和输入参数交给模型，`outputSchema` 中对 `execution_outcome` 的说明对模型不可见。因此将规则写入 `prompts/tools/execute_mutation_skill.md` 的 “Reading results” 段，并替换原 Returns 段中两句泛化警告；MRTR 工具说明（`mcp/mrtr.py` 注册处）只补充等待／批准不是写入结果、续接协议错误不带结论，并引用共享规则。未写入服务端 instructions 或 `sql_assistant`：前者与工具说明同处上下文会重复计费，后者不会被 Host 自动注入。历史实测未记录过误读，按“低频、高代价”风险处理；MCP Tools 规范把工具执行错误定位为供模型自我纠正并重试的反馈，写入工具需要显式说明相反规则。没有修改执行、令牌、审批、输出结构或配置。测试将两段说明分别限制在 2800 和 500 字符以内，防止持续膨胀。设计稿中的多处共享资源、服务说明接入和 20 个验收场景被精简为以上两处和 6 个回放场景。残余风险见 DRR-2026-073。

按连接读取策略指导（同属 3.8.1）：`prompts/render.py` 新增 `connection_policies(config)`，按别名排序遍历已加载配置，用 `read_access_enabled()` 判断读取状态，每个连接输出一行“别名（类型）：reads disabled”或“reads all tables／allowlist of N table(s)；UNION allowed／disabled”；超过 `MAX_POLICY_LINES = 12` 的部分合并为一行数量并指向 `list_connections()`。新资源 `prompts/read_policy.md` 提供表头和通用规则（仅为配置、FROM 子查询一律拒绝并改用 CTE、禁止 UNION 时不要尝试、允许 UNION 不扩大范围且不可跨连接），`server.md` 与 `sql_assistant` 共用。未采纳设计稿的 `sql_assistant(connection_id)`：Copilot 中 MCP Prompt 只能由用户通过斜杠命令调用，模型拿不到；而服务说明已实测对主 Agent 和子代理都可见。这也意味着放弃了设计稿“服务说明保持连接中性”的约束；为避免把某连接的策略误读为全局规则，每行都以别名开头，并要求按所选连接的策略写 SQL。`list_connections()` 已返回同样的策略，但目标已知时模型不会先调用它，所以仅靠该工具不够。别名格式已由配置模型限制为 `[a-z][a-z0-9_]{0,63}`，不会把自由文本写入 instructions。`core/policy.py` 的 UNION 拒绝文本保留 `UNION queries disabled` 前缀（已有测试与调用方依赖），删去“combine results in your response”。执行、校验、输出结构和配置格式均未改。四个连接时 instructions 由 3,582 增至 4,415 字符。文本在启动时固定，配置变更需重启并刷新 Host。残余风险见 DRR-2026-074。

令牌拒绝文本（同属 3.8.1，来自真实通道复测）：`core/proposals.py` 的 `_consume_mutation_preview_token()` 在框架写入边界前拒绝无效令牌；托管 confirm 复用缓存计划，命令式 Skill 的构造、Adapter 获取和就绪检查可早于校验，不能保证先于任何 Skill 代码；受信任扩展不得在这些阶段写入；缺失令牌之外的 5 条拒绝（过期、不匹配、未知或已用、绑定解析失败两种）共用 `_TOKEN_REJECTED` 后缀，说明“执行前已拒绝、本次未写入，先核对当前状态并由用户决定是否重新预览”，取代原 “run preview again”。拒绝仍是 ToolError（令牌拒绝不是业务执行结果的既有设计），条件与语义不变。工具说明加一句“A rejected preview_token means this request wrote nothing.”，使其与“无 outcome 的错误不证明任何事”的一般规则不冲突。曾试加“预览字段只代表预览时状态”，因复测无效果删除。实测与残余风险见验收记录和 DRR-2026-073。

服务器状态读取（最初实现，同属 3.8.1，2026-10-03；引用对象及普通业务名称的当前规则见下方 10 月 12 日复核）：`core/policy.py` 新增 `_server_state_reference_error()`，由 `_is_query_safe_extended()` 在文件操作检查之后、UNION 检查之前调用，因此同时作用于原始 `query()` 与 Query Skill 的启动和运行时校验。它遍历 sqlparse 扁平化后的 token（跳过字符串与注释）：`@@` 运算符、`USER`/`SESSION_USER`/`SYSTEM_USER`/`CURRENT_ROLE` 后接括号或任意形式的 `CURRENT_USER`、被识别为 Name 且规范化后以 `pragma_` 开头的名称拒绝；部分引用名漏查及普通同前缀业务名称误拒已在 10 月 12 日修复。这是黑名单，其他函数见 DRR-2026-075。

MySQL 表名大小写（最初实现，同属 3.8.1；readiness 的后续统一见下方 10 月 12 日复核）：`ConnectionPolicy` 新增 `case_sensitive_tables` 与 `table_key()`/`allows_table()`；加载器对 MySQL 保留配置大小写并置为 true，SQLite 仍转小写。表引用提取函数接受 `fold` 参数，`_check_table_allowlist()` 按策略选择是否保留大小写（含 CTE 名称）；`list_tables()`、`get_full_schema()`、`describe_table()` 与 Query Skill 可用性都改用 `allows_table()`。系统库检查仍按小写比较（只会多拦）。未读取 `lower_case_table_names`，故在不区分大小写的服务器上偏保守，见 DRR-2026-076。

结构化索引（最初实现，同属 3.8.1；当前键项字段、能力探测及预算见下方 10 月 12 日复核）：评估“在 `query()` 中支持有限原始 SHOW”的提案后改为结构化方案。`DatabaseAdapter.get_indexes()` 默认抛 `MetadataQueryError`；`MySQLAdapter` 用参数化的 `INFORMATION_SCHEMA.STATISTICS` 查询（不选 `CARDINALITY`，避免刷新缓存统计），按索引名分组，`COLUMN_NAME` 为 NULL 的函数索引键部分映射为 `null` + `has_expression`，非 BTREE 给出 `type`；`SQLiteAdapter` 用绑定参数的 `pragma_index_list`、`pragma_index_xinfo`（`key = 1`，`cid = -2` 为表达式）与 `pragma_table_info`，`partial` 始终返回，若没有 `origin = 'pk'` 的索引却有主键列，则合成 `name = null` 的 rowid 主键。这些是适配器内部查询，不经过 `query()` 策略；Agent 仍不能直接查询系统表或 PRAGMA。`describe_table()` 在列元数据成功后读取索引；仅索引失败时返回 `indexes_status="unavailable"`、`indexes=null` 与固定错误文本。工具说明 1,065 → 1,369 字符；SHOW、系统库与 PRAGMA 的拒绝提示指向 `describe_table()`。未加开关，`get_full_schema()` 不变。风险见 DRR-2026-077。

## v3.8.1 五次提交复核（2026-10-12）

接续[10-03 初始记录](../validation/v3.8/V3_8_1_REVIEW_2026_10_03_ZH.md)，完成结果见[本轮证据](../validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md)。版本不变；此节修订上文最初实现的边界，历史描述和预算保留其时间语境。

`core/policy.py` 将关系对象提取复用于 PRAGMA／系统库检查；引用内置 PRAGMA 名仍拒绝，普通列、别名和非保留业务表名不因 `pragma_` 前缀误拒。CTE 逐项累积可见名称，只有显式 RECURSIVE 才在自身定义中豁免自身；外层／内层作用域分别处理。关系括号组、单引号对象、ODBC 包装与 TABLE 表达式保守拒绝；STRAIGHT_JOIN 及 ON／USING 后的逗号关系纳入表提取。这不是完整 SQL 方言解析器，SQLite 前向 CTE／隐式递归等合法语法在白名单下可能被拒绝（DRR-2026-078）。

`skills/access.py` 的 readiness 快照和声明表同用连接 `table_key()`，MySQL 精确、SQLite 折叠；观察可用性仍不增加执行授权。真实双 Runtime 同别名 A/B/A 验证 instructions 与注册 Prompt 各自对应配置，sentinel 验证其渲染无 Adapter 获取／构造／元数据 I/O。

SQLite 列、表、索引和行数估算元数据固定 main；索引以两次绑定查询采集，避免 temp 同名对象污染。MySQL 先探测 STATISTICS 是否有 IS_VISIBLE，再查询索引；无能力时 visible=null，探测失败不重试成弱查询。`columns` 保留，新增 `key_parts` 表达方向、collation／prefix_length；MySQL `visible` 是优化器可见性。表达式原文、部分谓词、完整约束与基数仍未提供。`database/indexes.py` 共用 128 索引／2048 键项／64 KiB 索引数组预算和索引阶段剩余时间，超限整组不可用，列元数据保留；不能称为完整工具硬期限（DRR-2026-079）。

结果规则移入 `prompts/mutation_results.md`，`render.tool_description()` 分别注入普通写入及 MRTR 注册描述；每个工具独立可读，不要求另一工具可见。规则先核对目标、Skill、阶段和字段有效性，再判断有效 outcome，禁止借用预估或另一请求的行数。异常 required 字段例与缺失 rowcount 的措辞来自保留失败后的独立定点回放。最终描述 3,546／2,642 字符，回归预算 3,600／2,700；同时加载时公共文本会占两份上下文，未在 instructions／assistant 再复制。指导不改变服务端执行或认证能力（DRR-2026-073）。

最终源码回归、两协议 stdio、wheel 安装与两库原生对照通过；维护者手动重启后，当前 Host 描述与最终源码对照及两类解释各 3/3 已通过；原生索引／预览 3/3，完整恢复路线 2/3 的漏步骤误述另行保留，实际业务规则拒绝跳转，未执行。原生工具测试与模拟 MRTR 回放分别归档，不新增 MRTR UI 兼容声明。

## 结构与生命周期

`src/sql_safety_executor/` 是唯一运行包：`config` 处理严格模型、来源与密钥；`core` 提供完整读取策略、查询/schema/诊断服务及 Mutation 提案/执行；`database` 保留适配器与事务证据；`skills` 提供可信扩展 SDK、目录快照和发现服务；`mcp` 负责注册、上下文、结果编码和 MRTR；`prompts` 保存 UTF-8 资源；`observability` 处理审计与脱敏工具遥测；`cli` 提供显式启动和离线检查。

`GatewayRuntime` 由 `create_server(config)` 构造，每个实例分别拥有注册表、SkillCatalog、令牌存储、审计和诊断管理器。业务适配器按需构造，数据库连接由操作触发；诊断使用独立适配器及清理状态。lifespan 开始诊断管理，退出时关闭资源并清空令牌；初始化失败也回收。基础包导入没有数据库连接、业务 Skill 导入或日志文件创建。

MCP 普通工具绑定到协议无关核心函数。核心使用 `OperationContext`、`OperationResult`、`OperationError`；框架类型不进入核心。`OperationResult` 在核心边界检查可序列化性，避免提交后的转换错误丢失写入结论。删除旧公共 `execute_sql()` 部分校验入口。`MutationService` 供人工流程与 MRTR 复用相同准备/执行实现及同一令牌库，消费点没有移到审批 UI 层。

参数类型、默认值、验证 Field 与安全注解仍由代码/静态注册元数据定义。服务说明、路由规则、`sql_assistant` 和长工具描述先从基线原样抽取到资源；MRTR 说明是独立增量资源。工厂在启动时读取全部被注册工具的提示词和 assistant 文本，缺失即启动失败。wheel 包含这些资源；不会依赖源码仓库 cwd。

## 依赖、测试与工程约定

`pyproject.toml` 是依赖、入口、pytest 与类型检查的唯一配置；`uv.lock` 固定 FastMCP 4.0.10 / SDK 2.2.0 等实际解析版本。Python ≥3.12。AutoGen 使用独立示例环境，其协议依赖不约束核心。新版示例的纯提示词构建器单独迁出，核心测试不必安装 AutoGen。

整文件迁移使用 `git mv`，后续再拆分。未制作发布 tag 或自动提交。旧 README、公开 env 模板、发布说明和实测资料保存在 `docs/history`、`docs/releases`、`docs/validation/v3.7`，保留原版本结论，不伪装成新版验收。

根目录双语 README 以 v3.7 原文为基础维护，保留作者的项目动机、设计理念、演进、AI 协作经验、工具示例与截图，不再精简为文档入口页。v3.8 按原章节更新配置、依赖、启动方式、目录结构和扩展接口，增补 MRTR 及实际验证范围；专题细节链接到 `docs/`。历史更新日志保留当时的配置名和结论，与当前使用说明明确区分。后续版本沿用这种增量更新方式。

文档按用途维护：`docs/README.md` / `README_ZH.md` 提供双语索引，`config/examples/README.md` / `README_ZH.md` 说明公开模板。重要指南统一放在 `docs/guides/`，版本前缀用于标注适用范围，不作为移入历史目录的理由。原重构日志通过 `git mv` 回到根目录 `REFACTORING_LOG.md`，新增 `REFACTORING_LOG_ZH.md` 并同步记录 v3.8；历史条目保留原接口、失败及验证范围。`docs/history/` 仅保留归档快照和旧公开配置模板，不承担持续维护日志与可复用指南的职责。

旧测试中的环境/重导入夹具改为显式 `SCENARIO` 测试字典、临时三份 TOML、真实加载器与实例绑定视图。该字典沿用历史字段名便于对照安全断言，**不是 os.environ，也不进入生产包**。GatewayView 仅绑定原函数、注入故障和检查实例状态，不实现权限或 SQL 执行。旧环境兼容/default-only/静默回落测试已改为新契约下的拒绝或解释测试。新增 TOML、MRTR、真实 stdio、生命周期及 wheel 检查直接使用公开接口。

## 参考稿评审与明确差异

- 采纳独立安全核心、明确目标及状态归属；不把令牌、注册表、诊断变成全局单例。
- 采纳三份 TOML、显式引用、快照；禁止跨连接身份继承和隐式环境覆盖。密钥内容不 strip，末尾换行算内容。
- 表白名单经代码与测试核实属于读取策略，继续命名 `read`。不宣称通用限制 Mutation。
- MRTR 本轮仅托管单语句、默认关闭、可信 Host 模式 A。保留旧人工 preview/execute，无能力时明确拒绝，不回退到可能阻塞的旧 elicitation。
- `tools.schema` 的名称不够精确，但为保留有效工具开关语义，仍只控制 sample；基础 metadata 工具的实际数据授权来自 read policy。已在配置指南明示。
- 现代协议协商、密封状态与能力表示使用框架/SDK；业务不实现握手。现代 Client 没有 legacy InitializeResult，校验迁移到 `protocol_version` / `instructions` / `server_info`。
- 密封状态使用每实例临时密钥，其 TTL 显式采用配置的预览期限，避免 SDK 默认 600 秒提前终止较长审批窗口。缺答复重发时仍校验原服务端提案期限，重新密封不延长批准窗口。
- FastMCP 4 在中间件内校验更多输入，拒绝请求可能产生遥测失败记录；不能沿用旧“schema 拒绝必然没有遥测”的断言。SDK v2 的本地调用取消会发送 abandon/cancel 通知，诊断清理保护已有迁移覆盖。
- 不新增 Tasks、Providers、CodeMode、通用结果缓存或 OTel；不提升审计等级，不扩大命令式 Skill 的事务保证。

官方资料：[FastMCP 4 升级](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)、[4.0.10 release](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.10)、[MRTR / elicitation](https://gofastmcp.com/servers/elicitation)。以实际锁定安装及协议测试核对资料，不将客户端“支持 MCP”推断为“已支持 MRTR”。

现代协议已废弃 legacy logging capability；`mcp.context.ToolContext` 在现代请求下使用服务日志，旧协议仍保留原客户端日志通知。CLI 显式传入配置日志级别。逐实例审计锁不提供跨进程/跨实例共用日志文件的全局顺序保证，部署建议使用不同审计路径。

CI 使用只读仓库权限、禁用 checkout 凭据持久化，并将 Actions 固定到核验的 commit SHA；uv 固定为本次实测的 0.12.19。接口依据 [actions/checkout 官方说明](https://github.com/actions/checkout) 与 [setup-uv 官方说明](https://github.com/astral-sh/setup-uv) 核对。提交后的失败与修复后本地 CI 等价验证分别记录，不再用提交前的通过结果代表远端运行。

## 2026-09-27 外部评审后的约定

配置端 profile 经严格字符串校验后统一去空白、转小写并去重，空项报错；语义错误使用静态类型码保留原因且不泄露输入。Query Skill 可用性与执行共享纯读取准入谓词，动态 readiness 仍独立执行，Mutation 授权边界不变。

MRTR 等待结果附带已验证的目标元数据，中间件从 FastMCP 包装对象中的原始 `InputRequiredResult.meta` 读取。普通结果缺少身份时记录 null，诊断继续按独立校验的 scope 归属。参考 Host 两条流程共享审批期限、展示内容指纹和有效期复核；服务端原子消费边界不变。

概要设计 D01 仅部分完成：显式连接/部署权限不等于可信请求级任务授权，`OperationContext` 不是 grant。D04 的稳定定义与动态 readiness 仍在列表/详情中组合，独立接口与优化暂缓。D07 本次修正归属与阶段，但跨轮关联、完整追踪及 OTel 仍暂缓。扩大这些边界需单独设计和测试，不将报告建议自动视为本次新增功能范围。

## 2026-09-28 复评收口与静态策略预检

已独立核实 `139d53a` 的远端 CI 全流程成功，上一轮问题关闭；原始失败和本地记录保持原时间范围。新增 N01 的 UNION 发现不一致经真实 FastMCP/SQLite 复现后修复：Query Skill 通过读取准入与声明表范围检查后，用 `_validate_sql_query_policy()` 对同一缓存模板和当前连接做预检。执行入口继续复核，不在目录加载时按默认连接删模板，也不跨连接缓存裁决。

完整 SQL 预检补齐 UNION 及解析后表范围等条件；原声明表、profile、连接范围、类型与 schema readiness 继续约束可用性。代价是每次发现增加候选 SQL 解析，尚未做大目录性能基准；静态预检无数据库 I/O，整个发现接口仍可能访问 readiness 元数据。此修复不等于完成 D04 独立接口，也不扩大 MRTR/任务授权范围。六项新增回归与验证结果见[本轮复评记录](../validation/v3.8/V3_8_REREVIEW_2026_09_28_ZH.md)。

## v3.8.1 结构化读策略与查询异常（2026-10-13）

维护者批准发布前直接调整内部接口，版本仍为 3.8.1。旧 `.env`、旧启动入口、旧 SDK 迁移及假想历史调用方兼容不纳入本轮；更好的设计应主动报告并建议。当前 Host 与扩展按实际使用验证。历史迁移段落保留原日期，不成为本轮兼容层需求。

`core/decisions.py::PolicyDecision` 表达允许／拒绝、原因码、说明和恢复提示；`core/sql.py::classify_sql_statement()` 为语句形态入口。`core/policy.py` 复用 token 与作用域关系提取，新增 SQLite IN/NOT IN 裸关系，在同一 walker 中处理 CTE 可见性、白名单与内置 PRAGMA 对象。UNION／FROM 形态不匹配字符串中的文本；递归 CTE 内真实 UNION 仍受开关限制。

`skills/catalog.py::_extract_table_names()` 改用共享 scoped extractor；`skills/access.py` 的可用性与 `skills/tools.py` 的执行使用相同决策，显式依赖仍约束执行，SQL／依赖策略在 schema readiness 之前拒绝。启动静态判定不执行数据库 SQL；运行时 CTE 歧义可以触发常量能力探测。

13 日追加核验确认 SQLite F/f CTE 假依赖，14 日按维护者决定修复：目录不再合并推断到声明 tables，_inferred_tables 缓存精确／ASCII 不区分大小写两种候选；按目标规则选择后供发现、表搜索、readiness 和执行使用。full Query Skill 的 tables 返回所需并集，declared_tables／inferred_tables 说明来源；静态 SKILLS.md 只列声明。不同目标不能互相污染依赖结论，显式额外限制保留。两阶段证据见[验收记录](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md)。

`database/errors.py` 定义 `DatabaseQueryError` 与固定分类器。execute 成功返回行列表，失败抛类型化异常；_handle_error 仅构造安全异常并按类名记录日志。MySQL 使用 orig errno；SQLite 使用主错误码与驱动前缀细化 SQLITE_ERROR；未知错误保持通用类。schema、诊断、metadata 和 Query Skill 调用点同步，metadata 内部包装为 MetadataQueryError；查询错误不替换写入事务 outcome。

Query Skill SQL／策略错误通过 success=false 业务结果返回，outputSchema 按成功／失败分支要求字段；操作参数／作用域／readiness 异常仍可走 ToolError。工具说明明确读取 success/error_code/hint，避免 Host 看不到 outputSchema 时缺少解释。

14 日 MySQLAdapter.resolve_cte_case_sensitive() 通过两个仅含常量、名字大小写不同的 CTE 验证重名规则；不引用物理表。1066／4004 表示 ASCII 大小写不区分，成功返回 1 表示精确；未知异常保守且 30 秒后可重试。仅歧义且最低必需物理依赖已授权时探测，成功按适配器实例缓存，close／重启清除。首次判定可能有常量 I/O，业务 SQL 在授权后执行。_extract_tables_from_sql 的 cte_case_sensitive 独立于物理表拼写／授权，保留限定对象、自／前向依赖；SQLite 身份使用 ASCII 映射，解码后的引号空格及物理表声明不 trim。当前 MySQL 1 已实测，0/2 和 MariaDB 未独立实测，非 ASCII 大小写保守。authorizer／AST 仍为候选；见[本轮记录](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md#cte-依赖与实际名称规则修复2026-10-14)。

## 10 月 14 日矩阵、函数限制与 SQLGlot 验证

core/policy.py 的 _read_function_decision() 在共享扩展读取检查中识别五种真实调用；_cte_header_token_ids() 区分 CTE 声明列列表。名字仅 ASCII 折叠，引号真实字符保留；返回 PolicyDecision 的 lock_function_denied／expensive_function_denied，在适配器能力与业务 I/O 之前。启动模板验证沿用跳过机制，运行时仍独立检查。普通函数、literal／列／CTE 不扩大限制，metadata／受管写入模型保留。

scripts/review_v381/ 为可复验的矩阵、成本和 SQLGlot 试验，生产包不导入。30.22.0 固定官方 wheel 仅隔离解压；投影明确 physical_tables、functions、ctes、parameters、unsupported，不生成执行 SQL。SQLite IN 的 field、CTE 方言范围需项目适配；SQLite EXPLAIN 可为不透明 Command。AST／authorizer 生产接入未实施；见[本轮验收](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md)。

## 提交前引号身份补修（2026-10-14）

策略规范化改为处理空白／注释 token，保留字符串和引用名的内部空白。`_identifier_name_parts()` 从原始 token 解码一层，避免 `get_real_name()` 再次去引用及重复分隔符未解码；CTE、物理名和限定组件共用。最后新增 25 回归，1114 项全量及两协议 22 次安装包调用通过；当前 Host 刷新状态与独立证据见[提交前验收](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md#提交前完整复核与补修2026-10-14)。

## 引用名方言边界与后续架构建议（2026-10-14）

本节补充已修复问题的适用边界，并提出下一阶段方案；不是生产接入决议。不同 `" f "`／`"  f  "` 物理表的身份对照已在 SQLite 实测。[MySQL 官方标识符规则](https://dev.mysql.com/doc/refman/8.0/en/identifiers.html)禁止数据库名／表名／列名以空格结尾；其双引号引用还受 ANSI_QUOTES 影响。这些规则不应从一个对象角色推广到全部角色，也不应从一个后端推广到另一后端。当前修复保留引用内真实字符，未实现全部方言语义校验；元数据接口支持的名称语法仍有独立边界。

建议在后续生产设计中分清以下职责：

1. **词法身份保留。** 使用结构化名称组件，保存原始 token、引用方式、仅解码一次的真实名称、限定组件和对象角色。不能对名称整体 strip、合并内部空白或做通用 Unicode casefold；名称中的点也不能被再次拆成限定符。数据库继续执行原 SQL，不把 AST 重新生成的 SQL 用于执行。
2. **按连接与对象角色解释方言。** 由后端语义模块提供引用／转义规则、CTE 可见性与大小写比较，以及支持范围内的名称合法性。MySQL 上下文考虑实际服务版本、大小写设置和有效 sql_mode；会话设置需与执行连接一致，能力缓存有清除／更新边界。规则未知时保留身份并返回保守或不支持的结果，不能把非法名称修剪成另一个对象。
3. **语法分析与授权分离。** SQLGlot 使用显式输入方言，投影结构化依赖与作用域，项目策略再判定表范围、UNION 和受限函数。后端解析得到的等价关系不自动扩大项目 grant：当前 MySQL 物理表授权保留精确拼写要求，CTE 大小写能力单独处理。raw／Skill 的发现、readiness、执行共用这些语义；元数据接口复用身份规则但可以维持自己的支持语法子集。解析不完整必须显式标记，不能把空依赖当成已经授权。[SQLGlot 官方说明](https://sqlglot.com/sqlglot.html#faq)明确解析成功不等于数据库可执行，因此它不承担完整服务器语义校验。
4. **执行侧验证。** SQLite authorizer 可在实际 prepare 阶段依据数据库回调的对象检查权限，作为额外保障；需设计连接独占、statement cache／重新编译及回调生命周期，不能与内部元数据／受管写入混用上下文。默认采用整条拒绝，避免 SQLITE_IGNORE 将读取替换为 NULL 而改变结果。[SQLite 官方回调说明](https://sqlite.org/c3ref/set_authorizer.html)列出了这些时序和连接限制，authorizer 也不等于完整语义验证器。MySQL 不使用这套 SQLite API，继续依赖共享策略、数据库权限和类型化执行异常；本节不引入代理、通用预执行 SQL 或新工具调用。
5. **验证与分阶段采用。** 增补按对象角色区分的原生方言案例，覆盖尾随／内部空格、引用符、有效 SQL 模式、转义、大小写、CTE 遮蔽和限定名。记录数据库是否接受、实际物理依赖、项目是否授权三个不同结果。先验证结构化接口并比较差异，再分别决定 AST／authorizer 接入与可支持语法，沿用隔离 SQLGlot 试验的成本基线，不直接宣称生产性能或完整方言支持。

预期收益是避免分析与执行对名称理解不同，并把后续方言扩展集中到有边界的后端语义模块。代价是更多对象角色／会话状态测试、缓存和连接生命周期管理，以及 AST 的依赖、启动与内存成本；默认不增加 Agent 的 MCP 调用步骤。以上生产工作仍按维护者约定另行设计，本次补充只改文档，不改变版本、运行时依赖或此前验收结果。


## 结构化关系身份的生产小范围接入（2026-10-15）

维护者批准本轮三项修复，实施了前述建议中的关系身份与默认 schema 一致性边界。database/relations.py 的 RelationReference 保存 schema/name；共享 walker 输出组件给授权与 Skill 缓存，展示函数只为工具结果／矩阵生成名称。ConnectionPolicy 预先构造组件 grant，SQL 不从已解码字符串重新划分限定名；metadata 授权绑定默认 schema。SkillSchemaSnapshot 的名称是带 schema 的身份集合，其他 schema 显式标为无法核验。

命令式 Mutation 消费 preview token 后的 validate 异常由适配器固定消息脱敏后转字符串，保留 validation_failed／not_executed 与令牌消费；预览异常也显式转换。内部接口直接调整，48 新回归／1162 全量、两模式安装包 36 次和真实 MySQL 只读 12 次通过；维护者重启后的最后原生核验 18/18 通过。完整 SQL 分析对象、生产 SQLGlot／authorizer、会话模式和任意 schema 语法仍另行设计。见[验收与决定](../validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md)。

## 2026-10-15：最小关系语义接口补齐

ConnectionContext.metadata_relation 将已解码 metadata 名字绑定默认 schema；ConnectionPolicy.allows_metadata_relation 与 DatabaseAdapter.render_metadata_relation 消费相同 RelationReference，生成 SQL 逐组件引用，SQLAlchemy text 的冒号解析独立转义。SQLite 内部采样／精确计数固定 main；MySQL metadata 参数绑定配置库。

ReadRelation 保存 reference／kind，adapter.get_read_relations 仅观察当前 schema 的 table／view，Skills snapshot 直接保留其结构化身份，不把 table-only 目录当作所有关系存在性。原 table discovery 不扩展，视图底层读取不自动成为 raw 授权。normalize_mutation_validation 在 preview 与命令式复验共用，检查严格 bool、字符串 errors 与 JSON 序列化性，非法返回固定失败并保留令牌语义。没有生产 AST／authorizer、旧部署／SDK 兼容层或新工具步骤；完整分析和连接生命周期仍分阶段推进。[证据](../validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md)。

## 2026-10-15：SQLite 字面内部前缀补漏

SQLite adapter 的两个目录共享固定前 7 字符与 sqlite_ 的 NOCASE 比较，替代未转义的 LIKE sqlite_%。不使用展示名／通配符推断内部对象，不改变授权或工具参数。合法表／视图 raw 与 Skill readiness 恢复一致；schema 绑定的临时对象保证只适用于 SQLite main，MySQL 同会话临时表边界另行设计。[证据](../validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md)。

## 2026-10-15：保留名称与业务 Unicode 身份

_relation_object_names 的普通对象与 Function 分支复用 ascii_identifier_lower；账户保留集合及 _server_state_reference_error 的比较也统一 ASCII 小写，避免 K→k、ſ→S 等 Unicode 转换混淆不同业务实体。关系／CTE 辅助函数默认转换同步；现有生产入口的显式目标比较方式继续有效。真正的保留 ASCII PRAGMA／账户名称仍拒绝，关键字、配置标签、自然语言搜索不机械套用物理对象规则。没有新增 AST、依赖、接口或元数据标识符语法。[复现、取舍及验收](../validation/v3.8/V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md)。

## 2026-10-15：原始词汇及关系目标位置

sql_token_upper 仅按 ASCII 转换 token.value，避免 sqlparse.normalized 已执行 Unicode 大写后的信息丢失。语句形态、CTE 与读取结构共用这一词汇接口；它不是完整分析对象，也不能作为关系授权键。_relation_targets 在 FROM／JOIN／逗号后的目标位置优先识别关系，之后才应用子句边界；_table_references_from_target 接受该位置单个关键字形标识符，保留 RelationReference，不能因为 window／offset／lock 等词形把关系丢弃。

_read_function_decision 的实际调用识别同时服务既有文件／账户保留规则，标准引用只解码一次，声明列列表和字符串排除。_server_state_reference_error 保留 bare CURRENT_USER 的原有规则并复用账户调用判定，避免普通 user(n) CTE 声明被另一次扁平扫描误判。仍有重复解析；生产 AST／authorizer 未接入。未加引号的 like／regexp／replace／with、部分裸 IN 及带引号 CTE 列列表保持保守限制，具体范围与引用恢复见[相邻边界验收](../validation/v3.8/V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md)。

## 2026-10-15：CTE 声明排除的深度边界

带双引号的 CTE 列列表可能与 AS／查询体嵌套在同一 Identifier。_cte_header_token_ids 现在从原始叶子 token 识别声明层 AS，追踪括号深度，只提交 AS 之前的名称／列列表排除集；边界无法识别时不扩大排除。不能把一个容器整体当声明，否则真实调用会从共享扫描消失。

来源重建确认锁／耗时规则原已有此遗漏，上一次合并文件／账户扫描扩大了受影响类别；本次在底层边界统一修正并加入组合回归。关系解析/readiness 对带引号 CTE 列列表的保守限制、MATERIALIZED 形态分类及生产 AST／authorizer 接入仍分开处理。下一阶段应共用一次 CTE／关系分析，让 raw、Skill 与 readiness 消费相同语义；本轮没有为了修复函数漏查而扩大方言解析范围。[问题来源及验收](../validation/v3.8/V3_8_1_CTE_HEADER_2026_10_15_ZH.md)。

## 2026-10-15：未分类 WITH 的诊断边界

classify_sql_statement 仍以 get_type() 作为保守形态分类的一部分；裸 unıon／offſet／wındow／window 等合法 SQLite CTE 声明可能为 UNKNOWN，实际支持未恢复。UNKNOWN 回退到原始首 token 为 WITH 时，现在返回 sql_parse_failed，提示一致引用名称或简化读取，不将无法判定归为已知写入并给出 mutation 路由。已识别的 UPDATE／INSERT／DELETE 等继续 read_only_required；不通过首词 WITH 推断安全，不修改原 SQL 或扩大允许范围。

该小修只调整结构化错误及恢复语义，未知 WITH 内即使包含写入也继续拒绝。共享 CTE／关系分析和 AST 阶段再解决裸名及其他方言支持；元数据身份、readiness 和函数检查的既有契约继续有效。[功能限制、来源及验收](../validation/v3.8/V3_8_1_CTE_CLASSIFICATION_2026_10_15_ZH.md)。

## 2026-10-15：共享 CTE 结构与查询块边界

本节是以上诊断阶段的后续生产修复，DRR-2026-099。新增 core/structure.py，SQLFragment 保留原始叶子和查询体文本，CTEDefinition 保留 name／columns／materialization／声明叶子身份，WithClause 保留 recursive／有序 definitions／query。parse_with_clause 在平衡括号和明确 AS 上识别边界，支持标准引用列列表、普通注释及 SQLite 物化提示；不以 sqlparse 的可选 Identifier／Function 分组或 UNKNOWN 判定数据库语义。

classify_sql_statement 对完整 WITH 读取主命令，实际写入仍拒绝；读取中的 DML token 仅在确定属于声明或关系名称叶子时排除。关系目标选择器与关系分析共用，不能把 Function／Identifier 整组排除而隐藏参数或查询体。保留函数同样只排除声明名称／列列表，继续遍历全部查询体。significant_sql_tokens 在当前块展开可选 WHERE 容器，避免 IN 右侧 Unicode 名称因词法分组被丢到外层；嵌套查询仍按自身块分析。

_collect_table_references 使用同一 WithClause 依声明顺序遍历每个 body 和主 query，保留传入的外层可见名称；只有显式 RECURSIVE 增加本名。仍按原始 RelationReference、连接的物理／CTE 大小写规则检查身份，限定名不被 CTE 豁免。Skill 的推断／readiness 原有调用链因此获得相同结构解释，不再把带引号列列表的 CTE 当成物理依赖。

这是共用结构接口，**不表示整条 SQL 只解析一次**：片段分析与不同策略检查仍有重复解析。本次不修改交给数据库的 SQL，不引入方言 AST 依赖、跨请求判定缓存或生产 authorizer；数据库依然决定其方言语法有效性。与前批“保守不支持”的阶段描述分开，所复现的裸名、列列表、注释／物化和裸 IN 边界现已修复；其他 SQLite／MySQL 语义差异及未测后端保持显式范围。[功能、成本和验收](../validation/v3.8/V3_8_1_CTE_ANALYSIS_2026_10_15_ZH.md)。
