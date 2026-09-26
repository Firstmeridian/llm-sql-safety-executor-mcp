# v3.8 实施与决策记录

基线：`582822b4aa751516c4a7f7e738ea0c2708f0fea9`。重构前隔离测试：676 passed、4 skipped。

本次采纳三文件 TOML、实例级运行状态、可安装 src 包与独立提示词资源；将 MRTR 限于托管单语句写入，默认关闭。审批仍信任 Host，不声明服务端认证了真实人类。Tasks、多用户认证、分布式状态和跨重启恢复暂缓。

旧表白名单约束自由读取、元数据和 Query Skills，并不普遍约束 Mutation Skills。新 `read` 节保持此边界；写入由连接准入、Skill 白名单和执行计划约束。

配置迁移是破坏性变化：不读取旧 DB/Skills 环境配置，不保留 default-only 写入授权；未授权默认拒绝。显式密钥环境引用不属于配置覆盖。用户已有 `.env` 不删除。

安全不变量：未知目标不回退；所有请求固定目标；预览与执行绑定同一参数、连接和计划；令牌原子单次消费，消费后异常不恢复；不确定写入不自动重试；诊断 busy/cleanup_failed 不随请求或 scope 重置；审计仍为 best-effort。

验证记录将在各阶段完成后追加，未运行的 Host 或数据库场景不会记为通过。

完成后的自动化与实测分别记录在[阶段验收](../validation/V3_8_VALIDATION_ZH.md)和[本地 live Review](../validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：包含 Host 入口迁移/重连、真实 MySQL 连通与基础读取、原生 SQLite preview/execute 恢复，以及三组 Luna 六轮路由任务。原生 MRTR/人工审批 UI、Copilot、MySQL 写入及远端 CI 仍未验收；新旧参考协议的结果不替代原生 Host 协商证据。

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

CI 使用只读仓库权限、禁用 checkout 凭据持久化，并将 Actions 固定到核验的 commit SHA；uv 固定为本次实测的 0.12.19。接口依据 [actions/checkout 官方说明](https://github.com/actions/checkout) 与 [setup-uv 官方说明](https://github.com/astral-sh/setup-uv) 核对。远端 CI 尚未推送触发；本地已执行对应测试、类型与 wheel 验证步骤。
