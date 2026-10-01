# v3.8 实施与决策记录

基线：`582822b4aa751516c4a7f7e738ea0c2708f0fea9`。重构前隔离测试：676 passed、4 skipped。

本次采纳三文件 TOML、实例级运行状态、可安装 src 包与独立提示词资源；将 MRTR 限于托管单语句写入，默认关闭。审批仍信任 Host，不声明服务端认证了真实人类。Tasks、多用户认证、分布式状态和跨重启恢复暂缓。

旧表白名单约束自由读取、元数据和 Query Skills，并不普遍约束 Mutation Skills。新 `read` 节保持此边界；写入由连接准入、Skill 白名单和执行计划约束。

配置迁移是破坏性变化：不读取旧 DB/Skills 环境配置，不保留 default-only 写入授权；未授权默认拒绝。显式密钥环境引用不属于配置覆盖。用户已有 `.env` 不删除。

安全不变量：未知目标不回退；所有请求固定目标；预览与执行绑定同一参数、连接和计划；令牌原子单次消费，消费后异常不恢复；不确定写入不自动重试；诊断 busy/cleanup_failed 不随请求或 scope 重置；审计仍为 best-effort。

验证记录将在各阶段完成后追加，未运行的 Host 或数据库场景不会记为通过。

完成后的自动化与实测分别记录在[阶段验收](../validation/V3_8_VALIDATION_ZH.md)和[本地 live Review](../validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：包含 Host 入口迁移/重连、真实 MySQL 连通与基础读取、原生 SQLite preview/execute 恢复，以及三组 Luna 六轮路由任务。后续[10 月 1 日记录](../../REFACTORING_LOG_ZH.md)确认原生 Codex IDE MRTR 批准、取消及未勾选拒绝通过；[后续原生记录](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)确认长等待后批准被框架拒绝且未写入，独立真实进程重启及新提案执行对照已通过，业务 TTL 有模拟时钟覆盖；原生业务 TTL/重启 UI、MySQL 写入仍未验收；用户提供的 Copilot 试验被协议门槛拒绝，尚未进入表单；新旧参考协议的结果不替代原生 Host 协商证据。提交 `1be44b4` 的远端 CI 因旧提示词断言失败，修复与重新验证见[9 月 27 日记录](../validation/V3_8_REVIEW_FIXES_2026_09_27_ZH.md)。

## 审批信任归属补充（2026-10-01）

部署继续默认采用 preview/execute，MRTR 保持默认关闭并按实际 Host 显式启用。依据是[已测客户端的支持与验收范围](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)：Codex IDE 主要原生交互通过，Copilot 会话被协议门槛拒绝，仍有原生边界场景和证据缺口。此决定不宣称全行业兼容性，也不因默认流程选择而增强人工认证；不增加失败后自动切换写入入口的逻辑。

原有 preview/execute 的服务端门槛是 `confirm=true`、匹配的一次性 token 和既有权限/执行检查，不主动产生协议审批表单。参考 Host 可以用代码强制收集决定，但普通 Agent 自行调用两步工具时，聊天确认只是客户端行为约定。MRTR 将请求与批准响应纳入协议，并强制 accept/严格 true；仍不独立认证真人，自动化 Host 可提交同样响应。

MRTR 开关只控制额外工具注册，不移除旧 execute_mutation_skill，因此不是全局写入审批门禁。两条流程当前均采用可信 Host 模式 A。独立认证批准、Agent 无法取得批准凭据、所有写入路径不可绕过的授权检查尚未实现；沿用 [DRR-2026-050](../security/DESIGN_RISK_REGISTER.md#drr-2026-050-approval-boundary-follow-up-october-1-2026) 记录接受边界及重评条件。

## v3.8.1 拒绝恢复线索（2026-10-01）

版本升至 3.8.1（pyproject、包版本、MCP server 版本和锁文件项目条目）。本机无 uv，锁文件仅手工同步本项目 editable 条目的版本号，依赖解析未变；CI 仍用 `--frozen`。配置、授权、令牌与执行语义不变，无需迁移。

实现：`skills/access.py` 新增 `_related_available_skill_names()`，只读取被拒 Skill 自己的 `related_skills`，排除自身、未知名称及 Query Skill，并复用 `_get_skill_schema_snapshot()` 与 `_skill_availability_state()`，保证与 `list_skills` 的可用性判断一致。`core/mutations.py` 在 preview 与 execute 两个 `validation_failed` 分支调用它；异常只记录异常类名并省略字段，不改变审计、令牌或结果。MRTR 首轮经 `MutationService.prepare` 复用同一 preview 路径。`mcp/contracts.py` 声明可选字符串数组。

决策：服务端只给名称，不生成步骤或参数，避免把业务补偿逻辑或授权含义放进框架；仅列写入 Skill，因为报表类 Query Skill 不能达成写入目标。曾试验恢复 `preview_token_expires_in_seconds`，因 v3.7.1 已删除且相对秒数在对话中会过时而撤回。权衡与残余风险见 [DRR-2026-071/072](../security/DESIGN_RISK_REGISTER_ZH.md)、[安全说明](../security/V3_8_SECURITY.md#rejection-recovery-clue-v381)及[验收记录](../validation/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)。

结果解读引导（同属 3.8.1）：实测确认 Copilot 只把工具名、说明和输入参数交给模型，`outputSchema` 中对 `execution_outcome` 的说明对模型不可见。因此将规则写入 `prompts/tools/execute_mutation_skill.md` 的 “Reading results” 段，并替换原 Returns 段中两句泛化警告；MRTR 工具说明（`mcp/mrtr.py` 注册处）只补充等待／批准不是写入结果、续接协议错误不带结论，并引用共享规则。未写入服务端 instructions 或 `sql_assistant`：前者与工具说明同处上下文会重复计费，后者不会被 Host 自动注入。历史实测未记录过误读，按“低频、高代价”风险处理；MCP Tools 规范把工具执行错误定位为供模型自我纠正并重试的反馈，写入工具需要显式说明相反规则。没有修改执行、令牌、审批、输出结构或配置。测试将两段说明分别限制在 2800 和 500 字符以内，防止持续膨胀。设计稿中的多处共享资源、服务说明接入和 20 个验收场景被精简为以上两处和 6 个回放场景。残余风险见 DRR-2026-073。

按连接读取策略指导（同属 3.8.1）：`prompts/render.py` 新增 `connection_policies(config)`，按别名排序遍历已加载配置，用 `read_access_enabled()` 判断读取状态，每个连接输出一行“别名（类型）：reads disabled”或“reads all tables／allowlist of N table(s)；UNION allowed／disabled”；超过 `MAX_POLICY_LINES = 12` 的部分合并为一行数量并指向 `list_connections()`。新资源 `prompts/read_policy.md` 提供表头和通用规则（仅为配置、FROM 子查询一律拒绝并改用 CTE、禁止 UNION 时不要尝试、允许 UNION 不扩大范围且不可跨连接），`server.md` 与 `sql_assistant` 共用。未采纳设计稿的 `sql_assistant(connection_id)`：Copilot 中 MCP Prompt 只能由用户通过斜杠命令调用，模型拿不到；而服务说明已实测对主 Agent 和子代理都可见。这也意味着放弃了设计稿“服务说明保持连接中性”的约束；为避免把某连接的策略误读为全局规则，每行都以别名开头，并要求按所选连接的策略写 SQL。`list_connections()` 已返回同样的策略，但目标已知时模型不会先调用它，所以仅靠该工具不够。别名格式已由配置模型限制为 `[a-z][a-z0-9_]{0,63}`，不会把自由文本写入 instructions。`core/policy.py` 的 UNION 拒绝文本保留 `UNION queries disabled` 前缀（已有测试与调用方依赖），删去“combine results in your response”。执行、校验、输出结构和配置格式均未改。四个连接时 instructions 由 3,582 增至 4,415 字符。文本在启动时固定，配置变更需重启并刷新 Host。残余风险见 DRR-2026-074。

令牌拒绝文本（同属 3.8.1，来自真实通道复测）：`core/proposals.py` 的 `_consume_mutation_preview_token()` 在 execute 路径中先于任何 Skill 代码或数据库写入运行；缺失令牌之外的 5 条拒绝（过期、不匹配、未知或已用、绑定解析失败两种）共用 `_TOKEN_REJECTED` 后缀，说明“执行前已拒绝、本次未写入，先核对当前状态并由用户决定是否重新预览”，取代原 “run preview again”。拒绝仍是 ToolError（令牌拒绝不是业务执行结果的既有设计），条件与语义不变。工具说明加一句“A rejected preview_token means this request wrote nothing.”，使其与“无 outcome 的错误不证明任何事”的一般规则不冲突。曾试加“预览字段只代表预览时状态”，因复测无效果删除。实测与残余风险见验收记录和 DRR-2026-073。

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

完整 SQL 预检补齐 UNION 及解析后表范围等条件；原声明表、profile、连接范围、类型与 schema readiness 继续约束可用性。代价是每次发现增加候选 SQL 解析，尚未做大目录性能基准；静态预检无数据库 I/O，整个发现接口仍可能访问 readiness 元数据。此修复不等于完成 D04 独立接口，也不扩大 MRTR/任务授权范围。六项新增回归与验证结果见[本轮复评记录](../validation/V3_8_REREVIEW_2026_09_28_ZH.md)。
