# MCP SQL Server 重构日志

[English](REFACTORING_LOG.md) | 中文

**创建日期：** 2025-12-02；**最近更新：** 2026-09-26  
**作者：** 项目重构与维护记录

## 概述

本文持续记录项目的重构、设计决策、兼容性变化、取舍和验证结果，范围从最初的 `mcp_sql_server.py` 延伸到当前可安装的 `sql_safety_executor` 包。

中文版按英文日志相同的版本和日期整理变更、原因、边界与验收。各历史条目附有英文对应位置，便于查阅原始逐文件清单、代码对照和完整实测表。旧文件名、环境变量、失败记录和测试数量保留其当时含义，不作为当前部署说明。后续实现变更应同步更新两种语言，不能用新的通过结果覆盖旧失败。

## v3.8.0 原生会话重连验证（2026-09-26）

- 用户重启后，当前 IDE 会话直接发现 10 个工具。完成 23 次原生调用，覆盖读取/策略拒绝及受控 SQLite 预览、提交、重放拒绝和补偿，夹具已恢复。三个隔离上下文 GPT-6 Luna 完成同一六轮路由脚本：18 轮、22 次调用，观察到误访问与代理 Mutation 调用均为 0。
- 修正 `list_connections` 仍残留的旧说明：默认连接不再有兼容写入授权，必须同样满足五层配置要求。运行侧已正确拒绝默认目标；新文案通过独立参考发现验证，原生试验使用已运行服务，不能算作重载新文案后的原生回归。
- 原生协议/usage 未暴露，MRTR 仍关闭。详见[重连补测及边界](docs/validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md#服务重连后的原生补测)。
- 最终文档核对将双语 README、发布说明与实施记录同步到后续原生证据：MySQL 连通/基础读取已通过，MySQL 写入、原生 MRTR/人工审批 UI、Copilot 和远端 CI 仍未验收；保留历史失败及各次测试的范围。

## v3.8.0 本地实测 Review 补充（2026-09-26）

- 发现 Codex 本地入口仍引用已删除的 `start_server.py`；备份 Host 配置后仅替换该服务的可执行文件及参数。操作指南补充实际 Host 配置迁移与重连步骤，区别于修改仓库模板。
- 将 `list_skills` 的工具说明及参数说明改为 TOML 发现字段，并修正加载器中旧目录信任边界注释；路由、默认值、策略与执行逻辑未变。
- 新旧协议的真实 stdio 客户端均通过；包括 MySQL 的三个本地目标通过连通/读取探测。两轮受控 SQLite 的预览、提交、重放拒绝和补偿恢复保持原夹具数据；未向 MySQL 或演示库调用 Mutation。
- 9 次全新 GPT-6 Luna 原生 Codex CLI 试验完成限定任务或正确澄清/拒绝，15 次工具调用，观察到误访问为 0。其中 1 次禁用的 UNION 被拒后纠正，保留该首次规划失败和实际 usage/调用记录。当前 IDE 会话仍需重连；未采集这些 CLI 的实际协商协议，本地 MRTR 仍关闭。
- MRTR/stdio/渐进披露专项回归为 **66 passed、1 warning**；没有重跑全量测试或完整多轮 Agent 基准。详见[本次实测与证据](docs/validation/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)。

## v3.8.0：FastMCP 4、TOML 配置与包结构重构（2026-09-26）

### 范围与基线

基线为 `582822b`：Python 3.12.3、FastMCP 3.0.2、MCP SDK 1.26.0，隔离环境默认测试为 **676 passed、4 skipped**。本轮升级到 FastMCP 4.0.10、MCP SDK / mcp-types 2.2.0，采用显式配置和实例级状态，并加入默认关闭的托管 MRTR。Python 要求仍为 ≥3.12。仓库版本为 3.8.0，本记录不代表已创建 tag 或正式发布。

### 安装包、安全核心与生命周期

- 运行代码移入 `src/sql_safety_executor/`，按 `config`、`core`、`database`、`skills`、`mcp`、`prompts`、`observability` 和 CLI 分工；整文件迁移先用 `git mv`，再拆分职责。
- 提供 `load_config(path) -> AppConfig` 和 `create_server(config) -> FastMCP`。配置、适配器、Skill 目录、提案及诊断状态归属于服务实例。基础导入不连接数据库、不导入业务 Skill、不创建日志；显式初始化加载已开启的可信定义，适配器按需创建，由 lifespan 清理资源。
- 完整读取策略与执行进入核心，删除只执行部分校验的公共 `execute_sql()`。核心返回 `OperationResult`，MCP 层处理协议输入、上下文和转换。核心序列化检查保留提交后响应处理失败时的写入结论。
- `skills/_lib` 移入安装包，通过 `sql_safety_executor.skills` 公开扩展类型和业务异常；删除 `sys.path` 注入，同步内置 Skill 并提供自定义导入迁移表。根目录 `skills/` 继续存放业务定义。允许显式配置外部可信目录；解析后路径边界检查不构成 Python 沙箱。
- 提示词拆为 UTF-8 包资源，由 `importlib.resources` 加载。先保留原路由/服务说明，再增加独立 MRTR 指引；资源缺失导致启动失败。参数类型、默认值与安全注解仍由代码定义。
- `pyproject.toml` 统一管理依赖、入口和检查，提交 `uv.lock`；AutoGen 使用独立依赖环境。控制台命令和 `python -m sql_safety_executor` 替代旧根目录启动脚本。

### 显式三文件 TOML 契约

`server.toml` 引用连接文件和可选 Skills 文件；`connections.toml` 保存目标身份与读写策略；`skills.toml` 保存发现、写入准入、提案、MRTR 和审计。每份文件声明 `schema_version = 1`，使用 `tomllib` 和严格 Pydantic 模型，未知字段、错误类型、无效默认连接/引用以及越界设置均报错。

所有启动必须传 `--config`。路径相对于声明文件解析；仅查询/连接超时按“内置值 → 公共默认 → 连接值”覆盖，数据库身份和凭据不跨连接继承。`config check` 与 `config explain` 使用同一加载器解析密钥，不连接数据库、不导入业务 Skill；解释输出脱敏并标明来源及禁用原因。

读取默认 `deny`，空白名单不授权，允许全部必须显式 `all`；UNION 还要求显式开启与有效读取范围。写入同时要求 Skills 开关、全局写入开关、全局目标准入、连接写入开关和连接 Skill 白名单，删除 default-only 兼容授权。读取表范围仍不普遍约束 Mutation。

密钥在 `value`、`env`、`file` 中三选一，无失败回退。文件必须为非空 UTF-8、最多 64 KiB，保留空白和末尾换行。配置与密钥形成启动快照。结果限制的 0 仍表示不限额，工具超时的 0 仍表示禁用；负数和非法提案边界由静默回落改为启动错误。

移除项目 dotenv 加载与旧环境配置；正式入口在框架导入前关闭 FastMCP 自动 `.env` 搜索。显式密钥环境引用继续支持，用户已有私有 `.env` 保留。本地 TOML/密钥与四组公开模板分离并加入忽略规则。关闭 Skills 时不导入业务实现、不注册工具、不做其就绪探测。

### 托管 MRTR 试点与既有审批流程

可选 `request_mutation_approval(skill_name, params, connection_id=None)` 仅在 MRTR、Skills 和写入开关同时开启时注册。要求 MCP `2026-07-28`、客户端表单能力和托管单语句 Skill；不支持的协议/能力及命令式 Skill 明确拒绝。既有 `execute_mutation_skill` preview/execute 流程继续可用。

两个入口复用 `MutationService` 和令牌存储。首轮创建服务端保存的不可变审阅快照，包含目标、Skill、规范化参数、SQL、绑定值及期限，返回 `InputRequiredResult`，不执行托管写入。超过 64 KiB 的快照直接拒绝，不能截断后批准。SDK 密封的 `request_state` 只携带续接引用，不替代服务端绑定、过期和单次消费校验；每实例临时密封密钥使用配置的提案 TTL。

缺失回答重发同一快照，不重新预览、不延长期限。只有 `accept` 且严格布尔 `approve=true` 进入执行；拒绝和取消关闭提案。原子消费仍发生在共享执行边界，后续任何异常都不恢复。等待不持有事务或行锁；响应丢失、状态不存在和结果未知均不构成自动重试理由。

参考 Host 增加 `--config` 和 `--flow preview|mrtr`，默认 preview。审批信任 Host 收集的决定，不独立认证真实人类。等待遥测为 `phase=awaiting_approval`、`success=null`。未新增响应缓存、Tasks、多用户审批认证、分布式共享状态或跨重启恢复；审计仍为 best-effort，命令式 Skill 整体结果仍保守为 `unknown`。

### 验证与仍未通过的范围

| 项目 | 记录 |
|---|---|
| 锁定环境测试 | **744 passed、4 skipped**，1 个旧协议日志弃用告警；初次最终运行 43.18 秒，文档复核时重跑 62.77 秒 |
| 类型检查 | Pyright：**0 errors、0 warnings** |
| 打包 | sdist/wheel 成功；独立 wheel 环境在仓库外加载提示词、离线配置与新旧协议查询通过 |
| 协议与状态机 | 真实 stdio `2026-07-28` / `2025-11-25`；参考 MRTR、旧 preview/execute、配置拒绝/脱敏、授权、重放/过期/错绑、并发、事务结果、两实例隔离和资源回收有自动化覆盖 |
| 实际 Codex | CLI `0.155.0-alpha.16.3` 协商 `2025-06-18`；路由试验未见误访问，但 Host 策略在发送前拦截 MRTR，**不能记为原生 MRTR 通过** |
| 未完成部分 | Copilot 交互审批不可操作；本轮未启用真实 MySQL 集成；CI 已配置但尚未推送运行，不能将本地通过称为远端 CI 已通过 |

证据及实际 usage 见 [v3.8 验收记录](docs/validation/V3_8_VALIDATION_ZH.md)。

### 文档维护与切换

根目录中英文 README 基于作者原文增量更新，保留原有结构、论述、示例与截图。重构日志回到根目录持续维护，新增本中文版。`docs/README.md` / `README_ZH.md` 提供双语索引；`config/examples/README.md` / `README_ZH.md` 说明公开配置模板。原 `docs/history/guides/` 的 6 份指南通过 `git mv` 移到 `docs/guides/`，保留各自版本范围、历史失败与结论。README 快照、旧公开 env 模板及按日期实测资料继续分别归档。

切换前检查 TOML、停止旧进程，再使用匹配的安装包与显式配置启动。回退同时恢复代码、依赖和配置。重启使待批准提案失效；不确定写入须先核对业务状态。详见[配置迁移](docs/guides/CONFIGURATION_ZH.md)、[实施决策](docs/architecture/V3_8_IMPLEMENTATION_ZH.md)和[安全边界](docs/security/V3_8_SECURITY.md)。

## 统一连接诊断（2026-09-22）

[英文对应记录](REFACTORING_LOG.md#unified-connection-diagnostics-september-22-2026)

将默认、命名和全部诊断统一到 `check_connection`，参数为可选 `connection_id` 与显式 `scope="single"|"all"`，删除复数工具，不提供兼容别名。两种范围复用独立诊断执行器和必含 scope 的报告。单查只统计选中目标，不能从配置数量推断 scope。

单查不再获取缓存业务适配器或查询数据库名，改为共享 30 秒/外层超时预算、进程级 busy 保护及清理失败后的禁用状态。身份元数据仅来自配置；遥测按 scope 处理，区分完成与成功。目标验证后的 busy/stopped/disabled 错误保留已验证范围；验证失败不附身份。当时 SDK 在项目中间件前拒绝的请求没有项目遥测，此行为在 v3.8 框架迁移中有明确差异。

这是破坏性工具/响应迁移，当时不改版本号、不发版、不打 tag。同步双语迁移说明，历史接口和评分保留。DRR-2026-066 仍开放：模型填写的 scope 和自然语言指引不能强制执行当次权限，严格部署仍需可信 Host/应用校验。

验证按基线 A、统一契约 B、仅措辞压缩 C 分阶段比较。C 出现前三个对应 B 样本未出现的“用途未定就探测默认库”，按冻结规则撤回 C、恢复 B；新的 B 复查也出现该问题，不能归因于压缩，所有失败轨迹保留，不声称普遍改善。

确定性验证：针对套件 **123 passed**，默认套件 **675 passed、4 skipped**；10 个变更 Python 文件（含评估 bridge）Pyright 为 0 errors、0 warnings，不等同全仓库类型检查。新 stdio 和已连接 Host 观察到新签名、复数工具消失、默认 MySQL/命名 SQLite/全部诊断成功及冲突参数拒绝；Host 不提供远端源码摘要或服务 `_meta`，不能将可见契约验证当成构建或遥测证明。

后续经授权完成 A/B/归档 C 各三组新六轮 Luna 工作流，共 54 个用户轮次、63 次 MCP 调用；本批次无新目标范围违规，9 次故意别名拼写错误均拒绝且不回退。此前失败不撤销，C 仍撤回。A→B 的 Host 描述减少 3,405 字符，但没有实际模型 usage，不能当作计费 token 收益。详见[分阶段实测](docs/validation/v3.7/V3_7_3_LIVE_MCP_TEST_UNIFIED_CONNECTION_DIAGNOSTICS_2026_09_22_ZH.md)。

## 托管单语句 Mutation 契约（2026-09-16）

[英文对应记录](REFACTORING_LOG.md#managed-single-statement-mutation-contract-september-16-2026)

在首次正式发布前将该安全契约归入 v3.7.3，保留对 Skill 作者的明确兼容性变化。以可编写的 `ManagedMutationPlan` 替代临时内置名称/源码/类精确结果注册表。计划声明一条不可变 DML、参数/绑定/常量来源、期望影响行数及可选结果字段；发现时验证并缓存，确认阶段只解析计划并执行一次适配器调用，不实例化或调用 Skill Python。

精确结论仅覆盖框架执行的数据库语句，不覆盖模块导入、preview 回调及同进程其它代码。命令式 `MutationBase` 保留为实验扩展通道，整体结果 `unknown`；旧 `exact_transaction_outcome` 声明拒绝并给迁移说明。

修复源于原 v3.0 提交 `04603e4` 的行为：关闭 Mutation 时发现阶段不再导入自定义写模块。后来的 sample 命名/Git 忽略更新只是使问题更易察觉，并非引入点。元数据和路径验证仍可供发现使用。

预提交复核进一步发现作者定义 preview 可能与缓存计划漂移：SQL 和绑定值改为全部由同一计划及最终序列化 binding 生成，预览签发和确认共用解析器。缺失 SQL/结果绑定不发令牌，作者不得提供保留 preview 字段；`error`、`error_code` 加入保留结果字段，避免矛盾审计。

两个内置 Mutation 已迁移。测试覆盖关闭导入、非法/多语句计划、最终方法、写前绑定、确认无回调、事务证据、取消与命令式回退；非内置 Skill 经真实内存 FastMCP Client/临时 SQLite 验证提交与回滚。不新增持久回执、后台 worker 或此阶段的新 MCP 工具。错误码明确可扩展；移除缺乏支持的 Anthropic 引语，改为有出处的转述。验证详情见 [v3.7 发布记录](docs/releases/RELEASE_NOTES_v3_7.md#verification--september-16-2026)。

## v3.7.3：连接路由与工具契约说明（2026-09-15）

[英文对应记录](REFACTORING_LOG.md#update-v373---connection-routing-and-tool-contract-clarity-september-15-2026)

将兼容的路由/示例修正归入 v3.7.3，同步徽章与维护说明；批量诊断和此前 Skill 改名仍属 v3.7.2。仅版本记录调整不改变运行 Python，不创建 tag；此前 **640 passed、4 skipped** 及 7 文件 Pyright 结果仍对应相同代码，DRR-2026-066 保持开放。

### 文档命名与中文设计记录（09-15）

修复指南与四份分日期路由/边界记录增加 `V3_7_3_` 前缀并更新链接。前缀标识评审范围，不表示所有历史基线都运行该版本；当时五个文件未受跟踪，改名没有暂存，原始证据内容/哈希保留。新增完整中文诊断设计记录及互链，保留历史评分与严格部署、封闭客户端响应模型边界。

### 验收规则与部署条件（09-15）

路由矩阵和双语风险登记对齐限制优先级。`list_connections` 新增 hint，不改变旧字段含义；封闭客户端模型可能需要适配。严格部署必须在调用前通过可信上下文校验显式别名、隐式默认和全部批量目标，不能用模型填写“确认”替代。服务端当时未新增此机制。

### 受限诊断与配置解读（09-15）

明确只允许一个已确定目标/默认连接时收窄宽泛诊断；禁止访问也禁止诊断；拒绝部分检查或限制不可协调则等待。`list_connections` 强调仅列配置，白名单不证明表存在或完整。新增三个协议用例，验证发现不连接/建文件，并区分配置表、可见表和物理表。

最终 **640 passed、4 skipped**，7 文件 Pyright 无错误/告警。两阶段临时 SQLite/内存 FastMCP 试验共 15 个 Luna 上下文、13 次实际调用；配置解读最终 3/3 通过，禁止目标仍有 2/3 上下文失败。DRR-2026-068 已实现并本地验收，066 仍开放；不是运行时当次授权已补齐。

### 提交前原生复核（09-15）

Host 已暴露等待规则。12 个隔离上下文尝试 36 次调用，含三组六轮工作流；用途/默认/全部路由及首次 describe 参数通过，冲突澄清仍未解决，配置被误说成表存在另记 068。同步 prompt 与 README 的 `skill_name` 示例，新增两个协议用例。默认 **637 passed、4 skipped**，元数据测试 49 passed，6 个变更 Python 文件 Pyright 无错误/告警。

### 未确定目标时等待（09-14）

用途不明、指代歧义、数据库类型无法唯一匹配或范围冲突时，只可选做配置发现，随后询问并等待；默认标记、别名名称、Agent 猜测或成功探测不构成用户选择。仅修改说明和提示，不改工具签名、诊断实现或策略。默认 **635 passed、4 skipped**，6 文件 Pyright 无错误/告警；当时原生 Host 元数据仍较旧，等待后续行为验收。

### 原生 Host 复核（09-14）

重启后 Host 已暴露新说明，9 个 Luna 上下文共 36 次尝试；三组工作流首次 describe 参数均正确，但用途猜库仍出现一次猜测查询和一次未请求的默认探测，冲突场景未澄清。067 已实现，066 保持开放。相关测试 92 passed，4 文件 Pyright 无错误/告警；当时仅将未提交发布说明归到 v3.7.3 候选，没有改运行版本或打 tag。

### 路由说明与参数示例修正（09-13）

无明确目标的普通连通性请求默认单查；记忆中的别名须显式传入，全查须有明确意图。修复六处 `describe_table(name...)` 为 `table_name`，新增 schema 对照、正常/截断 hint 和协议参数拒绝测试。默认 **635 passed、4 skipped**，受影响契约套件 47 passed，4 文件 Pyright 无错误/告警。新 stdio A/B fixture 与 IDE 旧服务分开，历史轨迹不改写。

## 批量连接诊断补充（2026-09-12）

[英文对应记录](REFACTORING_LOG.md#follow-up-batch-connection-diagnostics-september-12-2026)

当时新增无参 `check_connections()`，覆盖全部配置别名，保留单查和配置发现。报告保留每别名失败与预算结束时未知状态，批量元数据不再冒用默认连接。该双工具接口后来由 09-22 统一入口取代。

先考虑复用连接，再因 SQLite `StaticPool` 共享事务状态而否决：SQLAlchemy 2.0.46 的临时实验复现诊断 checkout 关闭导致无关未提交记录回滚。采用新建、非缓存诊断适配器和 SQLite 只读文件访问，不给全部业务操作扩锁。

lifespan 管理四 worker 执行器，一次只受理一批；等待预算 30 秒，并收窄为较小 MCP 超时的 80%。超时/取消后后台 worker 仍持有批次归属直到清理结束，避免反复请求堆积。清理异常独立于连通性可见，并锁定禁用直到重启。

`mode=ro` 不保证零文件系统写入：WAL 实验在读表时观察到 sidecar，而本次实际 `SELECT 1` 未创建。新增 WAL 事务与探测阻塞时延迟退出的子进程回归；网络扰动和 supervisor 终止演练仍属部署验证。

初次 **621 passed、4 skipped**，另补协议取消回归；最终 **632 passed、4 skipped**，诊断/遥测 36 passed，7 文件 Pyright 无错误/告警。临时 stdio 混合成功/失败验证不创建缺失数据库、不披露路径；三别名实测和旧部署基线分开记录。

## 示例 Skill 命名与本地文件（2026-09-12）

[英文对应记录](REFACTORING_LOG.md#follow-up-sample-skill-names-and-local-files-september-12-2026)

四个内置 Skill 用 `git mv` 改为 `sample-` 前缀，包括 `sample-reset-order-to-pending`。同步 frontmatter、关联、配置、客户端、测试和当时的精确结果注册。旧名没有别名；连接 Skill 白名单须迁移，重启后须重新 preview。旧发布/实测仍使用当时名称并链接迁移表。

非内置目录默认忽略，当时 `_lib/` 仍保留为框架代码；生成清单和默认审计从索引移除，磁盘副本保留。前缀是命名/Git 约定，不授予权限或精确事务结论；任意新 `sample-*` 目录也不会自动受跟踪。

验证 **600 passed、4 skipped**，包括改名后的真实内存 MCP 和自定义 sample 声明拒绝；10 项忽略规则测试通过，未执行真实库写入。干净索引导出再次为 600/4；16 个变更 Python 文件 Pyright 无错误/告警，链接检查通过。

## 事务结果与不确定 COMMIT（2026-09-10，含 09-11/12 补充）

[英文对应记录](REFACTORING_LOG.md#follow-up-transaction-outcomes-and-uncertain-commit-september-10-2026)

v3.7.2 将写入事务边界改为 `connect()` → 立即 `begin()` → execute → 可选行数不变量 → 显式 `commit()`。任何 SQL 之前先 begin，避免早期 autobegin 冲突；显式阶段区分“语句失败且证实回滚”和“COMMIT 确认失败”，后者始终未知。

两个适配器新增仅关键字 `expected_rowcount`；内置状态更新和 reset 在 COMMIT 前要求恰好一行。类型化结果/异常携带阶段与证据。MCP 结果增加 `execution_outcome`，可处理执行错误转为稳定错误码的业务失败；静态设置或令牌拒绝仍为工具错误。Host 先验身份、再读结果，仅执行一次、不自动跟进。未增加通用多语句事务框架或持久操作账本。

### 结果证据与取消

不再把任何自定义 `run_execute()` 成功硬编码成 committed。只有保留下来的适配器提交证据可产生精确结论，普通自定义成功为 `success=true, unknown`；畸形/自报失败、丢失精确证据均保守失败。COMMIT 内的 `CancelledError` 清理后变为 `commit_outcome_unknown`；提交前取消和进程控制异常仍按原规则传播，连接已消失时无法保证送达结果。

回滚证据要求回滚前事务活跃、连接有效，回滚后仍有效且不重连。修复 SQLAlchemy 失效连接下本地 no-op rollback 被误当数据库回滚的问题。自定义执行异常转换为脱敏、可审计的 unknown；Host 对非字符串 outcome 终止为未知。审计异常不得覆盖写入结论，序列化 fallback 丢弃不可序列化自定义结果，只留标量行数摘要。

09-11 区分 `rollback_failed`（回滚调用抛错）与 `rollback_unconfirmed`（清理返回但证据不足），不改变禁止自动重试的语义。持久回执仍记 DRR-2026-061，等待具体重启查询、无人值守恢复或有责任人的对账需求。

### 扩展模板方法与来源身份

09-12 将 `MutationBase.run_execute()` 定为框架最终方法：直接重写或经中间基类替换都会在发现时拒绝，作者迁移到 `execute()`/`execute_with_binding()`。`@final` 服务类型检查，`inspect.getattr_static()` 做运行时身份校验；框架直接调用基类实现，避免加载后子类替换绕过。

当时精确结果仅授予两个内置单语句 Skill。初版只查名字，外部同名多写 Skill 可将后一次回滚错报为整体回滚；随后增加真实 bundled 源文件与加载类身份校验，普通同名自定义仍 unknown。此临时方案后来在 09-16 被托管计划替代，不宣称可隔离恶意同进程 Python。

该轮没有新增 `AGENTS.md`；运行与安全契约放在受跟踪的设计/安全文档中，避免陈旧协作偏好自动影响后续任务。

### 分阶段验证

| 阶段 | 默认套件与类型检查 |
|---|---|
| 早期提交结果复核 | 583 passed、4 skipped；Pyright 0 errors，35 项第三方导入解析告警 |
| 09-11 回滚诊断 | 584 passed、4 skipped；2 个变更 Python 文件 0 errors，16 项既有解析告警 |
| 09-12 包装器边界 | 592 passed、4 skipped；0 errors，21 项既有解析告警 |
| 来源身份跟进 | 596 passed、4 skipped；真实内存 Client 验证同名多写自定义 Skill 保守未知 |
| 丢失提交证据回归 | 598 passed、4 skipped；覆盖真实注册内置类返回普通成功 dict 时保守 unknown |
| 最终默认套件 | 599 passed、4 skipped；实库用例仍为显式 opt-in |

09-12 另行在本地 MySQL 执行三个只读检查及一个独立连接 InnoDB 旧状态竞态，共 **4 passed**：两次竞态尝试为一次提交、一次行数回滚；UUID 临时表与失败清理受 `try/finally` 保护，随后只读核对无残留。此结果不覆盖网络断连或不确定 COMMIT 确认，不能替代 v3.8 的实库验收。

## 严格工具契约与真实行数估计（2026-09-03）

[英文对应记录](REFACTORING_LOG.md#follow-up-strict-tool-contracts-and-honest-row-estimates-september-3-2026)

开启 FastMCP `strict_input_validation=True`，MCP 拒绝字符串布尔/整数等错误类型；直接 Python 调用对 `group_identical`、`exact_count`、`available_only`、`confirm` 也严格检查，省略参数仍用声明默认值。`sample.limit` 通过 `Annotated`/`Field` 暴露 1–20，默认 5；MCP 和直接调用都在 SQL 前拒绝越界，不再静默 clamp。

投影与可用性参数统一非空 `Literal`/布尔契约，删除 None/大小写/空白兼容路径。准确 COUNT(*) 的费用和 MySQL 元数据锁风险直接写入参数说明。

未知行数不再伪装为零：SQLite 不受支持的元数据标识符、发现后被删除的表及 MySQL 可空估计返回 `row_count=null`；单表工具同时使 `row_count_approximate`、`is_large` 为 null。详细元数据无法安全读取时明确报 `unsupported_metadata_identifier`。

工具职责收窄：query 是自由 SQL 读取入口，schema 用专用工具，既有工作流用经过审查的 Query Skills。describe 的完整性仅指适配器可见列元数据，不声称完整 DDL。统一 AutoGen/README 中工具、计数、默认值、preview token 和错误示例。

聚焦套件 **203 passed、3 skipped**，默认 **521 passed、3 skipped**，8 文件 Pyright 无错误/告警。临时 SQLite Client 验证 0/21 在 SQL 前拒绝、1/20 成功；新 stdio 暴露正确默认。MySQL 只读检查返回 8 表、272 列、4 组。旧 VS Code Host 曾缓存 nullable/default-null schema，刷新后正确，故服务重启和 Host 工具重新发现是两项独立验收。

## 渐进式 Schema 投影（2026-08-29）

[英文对应记录](REFACTORING_LOG.md#follow-up-progressive-schema-projection-august-29-2026)

`get_full_schema` 默认 `detail_level="compact"`、`group_identical=true`，省略参数等价于显式 compact；需要 nullable/default/key 时请求 full。compact 保存所有返回表名、估计行数、列数、主键及 `[name,type]`；分组比较适配器暴露的全部列元数据及顺序，借 `grouping_basis` 明示不证明完整 DDL/索引/约束相同。

适配器元数据失败抛脱敏 `MetadataQueryError`，核心返回 `metadata_query_failed`，不交付部分投影；空库、缺表、非法标识符仍分开处理。就绪检查区分关闭、成功和不可用，启用但失败时 `schema_check_available=false`、`schema_ready=false`，不编造 missing_tables；执行在 SQL、preview、发令牌之前关闭准入。

当时 MySQL fixture 为 8 表/272 列。旧 Host 格式 full 为 36,676 字符/9,270 `o200k_base` tokens，grouped compact 为 8,732/2,068，分别减少 76.2%/77.7%。minified 对照为 18,404/5,314 → 3,728/1,128；加入默认值的当前 full 为 44,300/10,946，ungrouped compact 为 20,125/4,660。5 张表独立核实列信息及顺序相同，分组进一步降低 56.6%/55.6%。单张 41 列 describe 约 1,094 tokens，所有数字限定 fixture、Host、序列化和 tokenizer。

首个独立 Agent 仍先 list_tables 再 compact，说明多余发现尚在。说明更新后 3 个独立样本中 2 个直接 compact、1 个保留前置 list_tables；均完成，共 4 次调用，平均 1.33。估算 schema payload 平均 2,191 tokens，比全直接路径高 5.9%，比旧约 9,638 的两调用路径低 77.3%；不是跨模型保证或实际计费。

聚焦回归依次为 69 passed/3 skipped、就绪套件 83 passed、最终投影/Skills 56 passed，默认 **485 passed、3 skipped**。某次新 stdio 注册成功后 MySQL 连通性失败，后续 smoke 跳过；2026-09-01/02 的成功只读记录与该失败分开，无写入。未因输出 schema 或供应商 programmatic tool calling 引入大 union schema，直接由服务端投影保持跨客户端可用。

## Host 提示预算与路由取舍（2026-08-29）

[英文对应记录](REFACTORING_LOG.md#follow-up-host-specific-prompt-budget-and-routing-guidance-august-29-2026)

只读测量实际提示面，而非把通用 token 上限当硬指标。在当时 FastMCP/VS Code 路径中，instructions 是一块服务说明，9 份工具参数各重复自己的 `connection_id` 描述；其它 wrapper 可能呈现不同。

`o200k_base` 测得完整说明 1,128 字符/215 tokens，其中路由 799/156；每份别名描述 177/33，共约 297 tokens。压缩候选路由约 90 tokens，仅省 66；历史 HMAC 值约 335–350 tokens，不透明句柄中位约 29，收益更大。保留现有自包含路由说明，避免为小收益损伤语义。

未来应冻结 Host、模型、采样、schema、fixture 和任务，只改一个提示变量，分别记录路由正确性、冗余调用、实际输入 tokens 和延迟。此轮不改运行逻辑、不新增 DRR；提示指南中无通用依据的固定预算改为基线、相对增长及行为回归方法。

## v3.7.1：不透明预览句柄与 Agent 工作流（2026-08-28）

[英文对应记录](REFACTORING_LOG.md#update-v371---opaque-preview-handles-and-agent-workflow-efficiency-august-28-2026)

保留 `preview_token` 字段，将自描述 HMAC 换成随机 256-bit bearer 句柄。容量受限的进程内 Store 保存期限、请求绑定、预览状态及原子条件消费；错绑不消费，正确请求在动态验证/写入前单次消费。旧 secret 输入仅发不含值的忽略告警。

删去重复的有效秒数、执行 hint 和嵌套 confirmation 字段。`get_skill_detail` 增加 `execution|full` 非空投影，默认 full；已知参数或 list full 已给 schema 时不再建议重复查详情。

路由区分明确别名、唯一数据库类型和无法安全推断的用途。`sql_assistant` 对 UNION 保持目标中立，实际原始查询和 Query Skill 使用选中连接策略。当时保留的 `execute_sql()` 仅做语句形态检查，后来在 v3.8 删除。

消费后动态验证异常说明未尝试写入；进入执行后异常提示核对业务状态。内存消费与提交/送达不具备跨系统原子性，持久账本继续暂缓。

默认 **468 passed、3 skipped**，根回归 2 passed。已重启服务在 08-26 完成可逆 SQLite 流程；08-28 新 stdio Host 的 APPROVE 退出 0、rowcount=1，NO 退出 3、无 execute；另进程仅给 analytics_demo_sqlite 开 UNION，原始查询与 Query Skill 各返回两行，默认 MySQL 仍拒绝。MySQL 后续只读成功不抹去同日超时，详见[v3.6–v3.7 实测](docs/validation/v3.7/LIVE_MCP_TEST_V36-V37_ZH.md)。

## v3.7.0：Skill 范围、人工 Host 与 SQL 加固（2026-08-22）

[英文对应记录](REFACTORING_LOG.md#update-v370---scoped-skills-approval-host-and-sql-hardening-august-22-2026)

此阶段不改 v3.6 token 格式/Store 和写协议；新增可选连接范围、跨数据库 demo reset、独立 stdio 人工 Host 和方言安全检查。未知/重复 frontmatter 改为拒绝，是有意的兼容性收紧。

### 可选 `connection_ids`

元数据使用复数列表，调用参数仍为单数 `connection_id`。声明必须非空、规范化去重，拒绝通配符、DSN、路径、标量和错误别名。遗漏保留不按 Skill 限制目标的语义；单项不自动路由，多项不表示默认/故障转移顺序。省略调用目标仍先解析全局默认，再校验 Skill 范围。

已知元数据和值严格检查：布尔须为 YAML 布尔，triggers/related_skills 是字符串列表，category 非空；参数仅允许 type/required/min/max/enum/description，约束类型正确、enum 非空、数值上下界有序。不改为完整 JSON Schema。

运行时先校验目标属于 connection_ids、类型属于 databases，再应用已有 profile/schema/read/write 策略；元数据只收窄，不建连接、不授予权限。未配置 portable 别名显示 unavailable；一项类型冲突只拒绝该目标，不禁用同一 Skill 的其它合法目标。发现过滤不是授权，执行仍重复权威检查。

### 一次性人工批准 Host

示例以当前 Python 启动子进程，完整继承导出环境，preview/execute 使用同一 stdio Client 和规范化有限 JSON 快照。固定实际目标，校验 preview 身份、业务内容、布尔幂等、token 和时区期限，指纹防止 provider 篡改展示后批准。

有效期限取 CLI 超时与 token 剩余时间减安全余量的较小值，工作流自身执行单调时钟截止。展示包含 Skill/参数/目标/类型/业务预览/期限/幂等，不显示 bearer token。仅 APPROVE 执行；拒绝、空输入、超时、EOF、取消、畸形响应及 UI 错误关闭流程。使用 daemon 输入线程，避免超时后等待不可取消 stdin。

只尝试一次 execute，异常/超时一律未知、不重试。输出删除 token，异常回显也替换精确 bearer。参数文件、终端和结果仍可含业务敏感数据。此 Host 不证明真实人类认证；旧 preview 拒绝不撤销服务 token，记录保留到 TTL。Python 内存不保证安全擦除，完整继承环境也是可信本地妥协；产品化应限制传递变量并补身份/角色/持久审计。

### SQL 与 demo reset

完整策略只接受单语句，拒绝 raw SHOW、sys 等系统 schema、执行式注释/优化器 hint、无空白双横线、EXPLAIN ANALYZE 和嵌套写 DML。保留普通注释、字符串、合法非 ANALYZE 计划检查；提取 CTE、逗号 JOIN、子查询和 EXPLAIN 的真实目标/来源，严格白名单下歧义拒绝。此检查是保守形态/应用策略，不证明所有 SELECT 无副作用。

当时的 `reset-demo-order-to-pending` 要求明确 expected_status，预览绑定同一次读到的状态，SQL 用乐观锁恢复固定 pending。要求 orders.id 为 PRIMARY KEY/UNIQUE；它是补偿清理，不是事务回滚或生产重开订单 API。pending→X→pending 可触发状态 ABA 边界（DRR-2026-046），应使用独立记录、避免重叠预览、每场景优先新进程。

### 验证

默认最终 **462 passed、3 skipped**，SQL/Query/SQLite 聚焦 115 passed，reset 聚焦 94 passed，根回归 2 passed；真实内存 Client 恰好修改临时 SQLite 一次。08-13 和 08-19/20 的 stdio 初始化超时保留为失败环境观测，未产生 preview/审计/写入；08-21 才完成批准、拒绝及子进程检查。08-22 未完成真实 MySQL reset，不能借后续 SQLite 通过补记。

## v3.6.1：令牌存储与执行加固（2026-08-10）

[英文对应记录](REFACTORING_LOG.md#update-v361---preview-token-store-and-execution-hardening-august-10-2026)

沿用 v3.6 发布家族，关闭 DRR-2026-003/035/037/038/039/041/045/047。最终选择一个有容量、加锁的进程内 Store，优先 stdio，同一进程完成 preview/execute；条件性私有 HTTP 仅可信单 Mutation 进程，不定义多用户认证、跨 worker 或持久恢复。即使固定签名密钥，重启仍使 token 失效。

曾评估共享外部后端，因当时没有完整远程多副本需求/验证而暂缓：外部服务不能消除事务、清理和故障复杂性。

1. 从 v3.6 抽出聚焦 `preview_token_store.py`，不新增 token 表/文件/外部服务。
2. 轮换密钥测试使用实际 reload/rejection，替代自证式脱敏断言，覆盖写异常后的终态消费。
3. 状态绑定改为来自展示预览的同一次查询；声明 error（含空/null）或 success=false 的 preview 不发 token。
4. 内置状态 Skill 的无 binding `execute()` 拒绝，所有写入只走绑定路径。
5. 默认 pytest 禁用 dotenv、导入前安全 SQLite 基线、MySQL 显式 opt-in；保留 demo DB 基线，写测试只用可丢弃库。
6. 删除两个未引用可用性包装器，保留一个策略来源。
7. 消费后的动态验证失败也 best-effort 记录 execute 审计；提交后上下文/响应失败保留原成功审计，不再追加矛盾失败。
8. TTL 上限 86400、容量上限 100000；满时拒绝新发，不驱逐有效提案。启动只记安全配置摘要，不显示密钥，不把候选目标称为最终授权。
9. 删除不可达 `DB_<ID>_DATABASE_PATH`，只保留当时的 `DB_<ID>_SQLITE_DATABASE_PATH`。

当时默认 TTL=300、容量=10000，非法容量静默回落；这是旧环境契约，v3.8 已改严格 TOML。保留随机 jti、HMAC、执行状态绑定、过期清理和并发唯一消费；读扩展需独立只读端点/profile。聚焦 Mutation/Store 回归 **67 passed**，全量 **289 passed、3 skipped**，语法与 diff 检查通过；未引入外部 token 服务依赖，不扩大为远程/跨进程保证。

## v3.6 后测试隔离与文档补充（2026-08-02）

[英文对应记录](REFACTORING_LOG.md#post-v36-test-isolation-and-documentation-follow-up-august-2-2026)

本地 `.env` 的写准入为 mysql/analytics，而 v3.5 fixture 注册 default/analytics；导入时 dotenv 可把本地值重新带入，导致服务器导入失败。fixture 在重导入前显式将 `SKILLS_ALLOW_MUTATION_CONNECTIONS` 设空；删除变量不足以隔离，因为 dotenv 会补回。只修测试，不修改用户配置迎合 fixture。

新增命名连接/Skills/审批中文指南；更新服务器 token 模型与 `Mutation.execute` 约束，说明传输本身不是限流机制。本地 `.env` 加中文注释，生效值不变。v3.5 回归 **6 passed**、v3.6 设计套件 **27 passed**，diff 检查通过。

## 全项目 Pylance 类型安全补充（2026-08-02）

[英文对应记录](REFACTORING_LOG.md#project-wide-pylance-type-safety-follow-up-august-2-2026)

五个 severity-1 问题均来自 Optional 或松散类型跨 helper/test double 边界：客户端 note 传 None、Tool 被标成 object、可空 annotations 未收窄、DummyEngine 赋给生产 Engine 类型。

将 note 声明为 `str | None`，工具集合为 `dict[str, Tool]`，读取 annotations 前明确断言；只在三处测试替身赋值使用窄 `cast(Engine, ...)`，不放宽生产类型。补隔离写准入变量，命名策略测试显式关闭 MySQL 写入。优先在生产者/边界修正，不以泛 Any 或散落 ignore 替代契约。

Pylance severity-1 清零；无关未使用符号提示保留。相关套件 **70 passed、3 skipped**。

## v3.6：预览令牌与命名写策略（2026-05-30）

[英文对应记录](REFACTORING_LOG.md#update-v36-may-30-2026---mutation-preview-tokens-and-named-write-policy)

结束 v3.5 Mutation 仅默认连接的妥协。所有 `confirm=true`（包括默认）必须携带匹配 preview 返回的一次性 token。历史 HMAC 绑定 Skill/版本/规范化参数哈希、实际别名/类型、签发/到期、随机 jti 及执行 binding 哈希，登记到受限 Store，动态验证和写入前原子消费。

写授权同时要求 Skills、全局 Mutation、全局目标准入、连接允许和 Skill 白名单，再加类型/就绪/参数/业务验证及合法 token。读取白名单不等于写权限。当时遗漏全局准入变量会保留 default-only 兼容模式；v3.8 已明确删除。

| 决策 | 原因与代价 |
|---|---|
| 默认连接也要求 token | 避免两套强弱协议 |
| 消费放在提交之前 | 仅 HMAC 期限不足以防重放，提交后消费有竞态 |
| 满容量拒绝，不 LRU 驱逐 | 不静默使已审阅提案失效 |
| Skill 显式 build/execute binding | 确认时重新读取不能代替审阅状态；非空 binding 不得忽略 |
| 发现与执行共用写策略 | 发现只是使用体验，执行仍是授权点 |

直接单步 execute 调用方必须迁移两步。消费后验证、数据库、超时、审计或响应异常不恢复；不确定写入先复核业务状态再决定是否新建预览。Store 不持久、无跨 worker 状态、不能退回无状态 HMAC 接受。meta 只可含短关联 id，审计/遥测不记录完整 token 或短 id；confirmation 注解不是人类批准证明。

设计套件 **27 passed**，全量 **259 passed、3 skipped**；MySQL/SQLite stdio 检查发 token、执行、重放拒绝、跨目标错绑不消费原 token 及 pending→confirmed，清理证据另存实测记录。

## v3.5：命名多连接读取与 Query Skills（2026-05-30）

[英文对应记录](REFACTORING_LOG.md#update-v35-may-30-2026---named-multi-connection-read-tools-and-query-skills)

新增命名注册表和按别名懒加载适配器，基础读取/schema/Query Skills 增加可选 `connection_id`，新增只列配置的 `list_connections()`。在权限、就绪、helper SQL、执行、元数据、审计和遥测之前固定同一个目标，修复“一个适配器引用标识符、另一个默认适配器执行”的风险。

身份只能来自操作员配置的别名，不允许模型传 DSN；未知目标关闭。启动检查模板只读形态，运行时按选中连接表范围复核，规范化引用及 schema-qualified 标识符。公开元数据只给 alias/实际 db_type，SQLite 名称显示 `sqlite:<connection_id>`，不暴露文件路径/凭据。

当时 `DB_CONNECTIONS` 是显式命名配置门：未设置时忽略命名变量及 DEFAULT_DB_CONNECTION，保留旧单连接；结果限额仍全局。Mutation 刻意只支持默认，待后续专门设计目标绑定/写授权。

聚焦 **44 passed**、默认 **231 passed**，语法/编辑器检查通过。本地双连接 smoke 读取成功；analytics 仅列 orders，SQLite monthly report 可执行并返回零行，非默认 Mutation 明确不可执行。此为当时 `.env` 路径，v3.8 不继续支持。

## v3.4.3：有界 SQLite 估计与工具描述（2026-05-24）

[英文对应记录](REFACTORING_LOG.md#update-v343-may-24-2026---bounded-sqlite-estimates-and-tool-surface-wording)

SQLite 优先 sqlite_stat1，否则最多采样 10000 行；达到上限后返回下界估计，不升级到全表 COUNT(*)。精确计数保留给显式 SQL 或 `get_table_summary(exact_count=True)`。识别 SQLAlchemy 包装的 SQLite interrupted 为超时并完善类型。

修正文案：截断只限制返回 payload，不限制数据库工作或 fetch 峰值；schema/table 是可见、可能截断的范围。通用 query 不新增分页参数，因为稳定性依赖 SQL 语义和排序。客户端优先 structured_content，Skill 参数用对象而非 JSON 字符串。

风险登记完成 V343-001–005；006–008 用文档/运维约定处理（SQL 回显、参数为业务审计数据、外部轮转），009–014 接受/暂缓，不暗中变成新控制。默认 **183 passed**，诊断与 diff 无误；真实 stdio 覆盖读、发现、预览和可选遥测，遥测不含 SQL/参数/数据行。

## v3.4.2：统一 ToolResult、输出 Schema 与可选遥测（2026-05-21）

[英文对应记录](REFACTORING_LOG.md#update-v342-may-21-2026---unified-toolresult-output-schemas-and-optional-telemetry)

将所有 11 个工具统一为 ToolResult，两个 Skill 执行工具声明 outputSchema；业务 structuredContent 保持原契约，直接 Python 调用需读取包装内容。所有工具统一 tool_name/success meta，避免 Skills 特例。新增默认关闭的本地 JSONL 中间件和注解一致性 pytest，当时未配置 CI，不能称为 CI 强制。

评审修复区分 `call_completed`（正常返回）与业务 `success`，正常返回的安全拒绝/验证失败不能记成功。Mutation schema 反映 preview/result/validation 分支，mode 为必填枚举；开放附加字段以兼容演进。

采样默认 1.0，历史解析对有限越界 clamp、非法字符串或非有限值回落 1.0；v3.8 改为非法配置报错。只记录时间、工具、耗时、完成/成功、异常类和类型等安全字段，不读取 SQL/参数/数据行。操作员可离线算百分位，不新增模型可见的统计工具。日志使用模式仍有运营敏感性，须可信存储。

`_meta` 可被客户端忽略，当时 VS Code UI 不展示。真实 Client 覆盖注册 outputSchema、成功/业务拒绝/异常遥测；这些是当时的兼容性和可见性观察。

## v3.4.1：Skill 运行元数据与闭合世界注解（2026-05-19）

[英文对应记录](REFACTORING_LOG.md#update-v341-may-19-2026---toolresult-metadata-and-closed-world-annotations)

首次只包装两个 Skill 执行工具为 ToolResult，分离业务 payload 和耗时、计数、截断、模式、审计状态、幂等与版本诊断；其它九工具当时仍 dict，后由 v3.4.2 统一。

所有 MCP 工具设置 `openWorldHint=false`，表达配置数据库/服务边界而非任意外部实体；注解不授权。meta 不放 SQL、参数、结果数据，也不是审计账本。Query 审计仍默认关闭。Inspector/中间件可读 `_meta`，当时 VS Code UI 不展示，不能假定终端用户看得到。

## v3.4：MCP 加固与 Skills Profile（2026-05-14）

[英文对应记录](REFACTORING_LOG.md#update-v34-may-14-2026---mcp-hardening-and-skills-profile-policy)

评估十项加固，实施低风险控制而不改变启动验证/缓存执行文件的模式：`mask_error_details=True`、工具超时、原始 query SQL 长度限额 20000、profile 排除、默认关闭的 Query 审计。审计不记返回数据，预定义模板不套原始不可信 SQL 长度上限。

错误掩码保护意外异常，明确脱敏 ToolError 仍可见；profile 在发现和执行都应用，不要求删除 demo 文件。pytest 布尔返回改 assert 消除告警。当时 ToolResult 元数据、session schema cache、db://schema resource 暂缓，各有后续独立决策；缓存可能因 DDL 过期，不先引入。

相关套件 **99 passed**，默认排除旧服务 smoke 后 **160 passed、1 deselected**。

## v3.3：可用性过滤与 SQLite 示例（2026-05-14）

[英文对应记录](REFACTORING_LOG.md#update-v33-may-14-2026---skills-availability-filtering-and-sqlite-example)

`list_skills(available_only)` 默认仅显示当前类型、Mutation 开关及 schema 就绪允许执行的 Skill；`available_only=false` 可看完整目录，详情保留 disabled_reason。执行始终重新检查，隐藏不是权限机制。

增加 profiles/tables 元数据，Query 表依赖合并声明与 SQL 提取。schema 默认只检查表是否存在，不完整验证列/类型，精确要求留给执行。独立 SQLite monthly report 使用 demo 的 orders.total_amount 和日期函数，不在 MySQL SQL 内放方言分支；内置示例标记 demo 并互链，databases 缺省仍为所有支持类型。

选择现有 list 的过滤参数而非新增 admin 工具，保持工具面小；外部最佳实践只支持相关性/渐进披露原则，不把缺少工具定义当安全边界。聚焦 19、92、74 项测试分别通过；默认 **156 passed、1 deselected**，告警清理后续在 v3.4 完成。

## v3.2：Skills 元数据按需披露（2026-05-12）

[英文对应记录](REFACTORING_LOG.md#update-v32-may-12-2026---skills-metadata-on-demand-disclosure)

新增 compact/summary/full 投影、search/category 过滤与分类汇总，以及 `get_skill_detail(skill_name)`。默认 summary，搜索用大小写不敏感子串，不引入正则/BM25；无分类归 uncategorized。只调整模型可见元数据，SQL/写类仍启动校验并缓存，不做运行时磁盘懒加载。

可选 databases 表达方言兼容，省略为全支持类型；MySQL monthly report 明确 mysql。保持关闭 Skills 不注册工具，执行接口不变，list 附加 detail_level/matched_skills/categories/hint。AutoGen 增加能力检测与按需详情指引。披露套件 **13 passed**，Skills 相关总计 **85 passed**。

## v3.1：显式 source 声明（2026-03-17）

[英文对应记录](REFACTORING_LOG.md#update-v31-march-17-2026---explicit-source-declaration)

`skill_def.md` 必须声明 source，不再约定固定 query.sql/mutation.py。允许可读的自定义文件名，但 query 必须 .sql、mutation 必须 .py；必填不回退，避免歧义。迁移内置定义、全部 fixture、设计和双语说明。

校验 source：非空、最多 128 字符、无路径分隔符、不能以点开头、符合 `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`、类型后缀一致、解析路径在 Skill 目录内以防符号链接逃逸。

当时 **125 项测试全部通过**，新增 9 项 source 用例，已有 38 项 loader 测试迁移通过。外部 Skill 必须新增字段，是明确 schema 破坏性变化。

## v3.0：Skills 扩展层（2026-03-01）

[英文对应记录](REFACTORING_LOG.md#update-v30-march-1-2026---skills-extension-layer)

新增默认关闭的参数化查询/写操作扩展，以少量统一 list/query/mutation 工具避免每 Skill 一个工具。`skill_def.md` 的 YAML frontmatter 管理结构化定义，区别于客户端自带的 SKILL.md 约定；发现时校验并缓存 SQL/元数据/写类。

### 架构与文件

当时 `mcp_sql_server.py` 负责注册、参数与安全策略；`skills/_lib/skill_loader.py` 负责发现/校验，`mutation_base.py` 定义 validate→preview→execute 与审计，`audit.py` 写 JSONL，数据库适配器新增参数化 execute 和事务 execute_write。目录内有 MySQL monthly report 与状态更新示例，SAFETY 为作者治理，SKILLS.md 为生成目录。

原始架构图、流程图和文件行数表见英文对应条目；本阶段目录随后经过 sample 改名和 v3.8 拆包，不能用旧图指导新部署。

当时配置为 ENABLE_SKILLS=0、SKILLS_ALLOW_MUTATIONS=0、SKILLS_DIR=skills/、SKILLS_AUDIT_LOG=skills/_audit.jsonl，目录受项目根限制。后来 v3.8 允许显式外部可信目录并迁移到 TOML。原始记录为 64 个新增测试、53 个既有测试，共 **117 passed**，另有不同阶段 111 项的实测记录，保留原计数而不合并。

### 实施后审查：修复项

| 编号 | 问题与处理 |
|---|---|
| 1 | SHOW 拒绝泄露正则内容，改通用安全错误 |
| 2 | INFORMATION_SCHEMA 暴露受限表名，加入系统库阻止规则 |
| 3 | sample 使用 MySQL 引号，改按 adapter 方言引用 |
| 4 | summary 绕过适配器使用 MySQL 元数据，改通用 get_row_estimate/get_columns |
| 5–7 | 移出局部 json 导入、删除未使用 SHOW 集合、注明冗余标识符检查的纵深防御意图 |
| 8–12 | 修条件块未绑定变量、补抽象错误处理、import spec/loader 的 None guard、Row 类型说明及连接后非空断言 |
| 13 | SET SQL 引发 autobegin 后重复 begin，历史修复为 engine.begin；v3.7.2 又改为任何 SQL 前立即显式 begin 并保留 COMMIT 证据 |
| 14 | 每次加载重跑 exec_module，改发现时缓存写类 |
| 15 | 未声明参数被忽略，新增 unexpected 参数拒绝 |
| 16 | 审计目录创建失败导致全 Skills 崩溃，改警告并保留 best-effort |
| 17 | 自定义 execute 返回 success=false 却被包成成功，改抛业务异常，并补对应审计 |
| 18 | dataclass 内 type 注解解析问题，以延迟注解处理 |
| 19 | MySQL MAX_EXECUTION_TIME 不能保证 UPDATE 超时，写路径改 InnoDB 行锁等待限制，DML CPU/IO 全程限制留给驱动/部署 |

### 当时的取舍与后续处置

核心 dict 失败与 Skill ToolError 曾混用；当时不统一破坏客户端。可信单操作者场景暂不加限流，未来远程/多用户须补入口和身份限额。早期 CTE、lifespan 未清适配器、MySQL-only 示例等记录保留，后续分别加固或迁移；不能将当时“低风险”判断解释为当前完整安全保证。

内置写重复读取、读写间隔和二次矛盾审计后在 v3.6/v3.6.1 用 binding/乐观锁及审计归属修复；外部写者 ABA 仍单独登记。审计截断只针对顶层字符串，复杂参数未来须重审；bool coercion 后修为只接受明确布尔与 true/false 字符串，不用 Python truthiness。

### 当时的 MySQL 集成实测

通过 VS Code → FastMCP 3.0.2 stdio 测试，原记录包含实际数据库环境及完整调用表。覆盖 6 张原业务表、临时 orders/test_users、聚合和禁止 DROP、Skills 发现、缺表/缺 Skill 错误、预览及状态迁移。

19 项过程记录为 **18 通过、1 失败**：首次确认写入失败，定位 SQLAlchemy autobegin 冲突，修复后 pending→confirmed→shipped 成功，非法 shipped→pending 拒绝。SQLite 单测未触发 MySQL SET 会话语句路径，揭示 mock/单一后端覆盖限制。修后当阶段 111 个单测仍通过；清理临时表后保留原 6 表。这是历史实测，既不建议复用生产库试验，也不代表本次重新执行。

## GitHub 仓库改名（2026-01-13）

[英文对应记录](REFACTORING_LOG.md#update-january-13-2026---github-repository-rename)

仓库从 `vibe-coding-gemini-llm-execute-sql-tools` 改为 `llm-sql-safety-executor-mcp`，仅仓库级命名，无功能代码变化。原日志给出更新本地 origin 的命令及新仓库地址；这是当时操作记录，不自动执行远端变更。

## v2.2：SQLite 支持（2026-01-15）

[英文对应记录](REFACTORING_LOG.md#update-v22-january-15-2026---sqlite-database-support)

引入数据库适配器模式：`DatabaseAdapter` 抽象接口及 MySQL/SQLite 实现，共享 execute、连接、元数据、行数估计、关闭和标识符引用；安全检查与 MCP 工具通过适配器访问数据库，减少后端分支散落。

增加 DB_TYPE 与 SQLite 文件路径、进度 handler 超时设置，保留 MySQL 默认配置。SQLite 使用其方言/元数据和采样机制；设计理由、限制与示例代码见 [SQLite 设计](docs/architecture/SQLITE_ADAPTER_DESIGN.md)及英文原始图表。这是后续命名连接和多后端演进的基础。

## v2.1：工具优化与字段命名（2026-01-04）

[英文对应记录](REFACTORING_LOG.md#update-v21-january-4-2026---tool-optimization--field-naming)

`get_table_summary` 改为默认关闭，准确 COUNT(*) 仅在明确需要时启用；describe 默认提供估计行数、近似标记、is_large 和建议，避免每次规划都全表计数。

list_tables 与 get_full_schema 统一 `returned_table_count`（截断后返回数）、`total_tables`（白名单后、截断前可见数）、`tables`、`truncated`、`truncation_note`。新增 ENABLE_TABLE_SUMMARY=0、LARGE_TABLE_THRESHOLD=1000、MAX_OVERVIEW_TABLES=100。AutoGen 提示移除默认 summary 步骤，改按未知结构、多表 JOIN 和大表标记选择工具；历史输入/输出示例及文件表保留在英文对应节。

## 缺陷修复与截断配置（2025-12-29）

[英文对应记录](REFACTORING_LOG.md#previous-update-december-29-2025---bug-fixes)

修复 schema.table 的提取错误：旧正则误取 schema，新正则跳过可选 schema 前缀并识别实际表名；验证 bare/quoted 的 mydb.users 和 DESCRIBE mydb.products。修复 ALLOWED_TABLES=* 在提示中显示含糊，改为 all tables；列表过滤遇 * 跳过限定，避免全被滤空。

get_full_schema 增加 MAX_SCHEMA_TABLES=50，原百表、多列场景可能超过 200K 字符。历史估算表从 10 表约 9K 到 200 表约 860K 字符，超过 50 表截断；这些是字符量估计，不是实测计费。

默认返回行数 50→100、字符 8000→16000，支持 0 取消相应限额。历史空 ALLOWED_TABLES 允许普通读取但仍不开放 UNION；* 表示显式所有表，需另开 ALLOW_UNION 才可 UNION。缩短截断与 UNION 拒绝信息以减少重复内容。v3.8 迁移不能把旧空名单机械映射为同时开放读取和 UNION。

## UNION 策略、启动日志与提示优化（2025-12-23）

[英文对应记录](REFACTORING_LOG.md#update-december-23-2025)

新增 ALLOW_UNION，默认拒绝；启用仍需显式表范围。模块加载时记录配置开关摘要，便于当时排障；此导入期行为在 v3.8 已移除。

sql_assistant 从 1,224 字符缩至 376，历史表按粗略方式估算约 306→94 tokens、约 69% 减少。原记录保留优化前后提示：删重复工具描述、合并指引、按配置生成 UNION 内容。当时“先 full_schema”的流程后来被按意图选择 compact/单表等规则替代；这些旧估算不是实际 usage 或跨 Host 结论。

## 扩展 SQL 语句支持（2025-12-15）

[英文对应记录](REFACTORING_LOG.md#update-december-15-2025)

当时从 SELECT 扩展到 SHOW、DESCRIBE 和 EXPLAIN，新增 SAFE_SQL_TYPES 并同步服务说明、工具和 README。这是历史支持范围：后续完整 MCP 策略拒绝 raw SHOW，将元数据读取交给专用工具，也明确排除 EXPLAIN ANALYZE。

## v2.0 相对 v1.0 的变更概览（2025-12-02 起）

[英文对应记录](REFACTORING_LOG.md#changes-summary-v20-vs-v10)

最初服务约 460 行重构为约 280 行，记录约 40% 缩减。自动验证合入 query，减少查询前固定工具链：

| 旧工具 | 新工具/处理 |
|---|---|
| validate_sql_query | 删除，query 自动校验 |
| execute_safe_sql | query |
| check_database_connection | check_connection |
| get_table_schema | describe_table |
| get_sample_data | sample |
| get_server_info | 删除 |
| 无 | 新增 list_tables；12-23 又新增 get_full_schema、get_table_summary |

历史汇总含 12-23 增量时为 6→7 工具；早期简化对照曾为 6→5，两处阶段不同。原记录提出大多数查询由多步缩到 1–2 次调用，不作为所有 Agent 场景保证。

## v2.0 详细实现

[英文对应记录](REFACTORING_LOG.md#detailed-changes-v20)

- 加入 FastMCP lifespan，为资源初始化/清理提供结构；当时部分实际 cleanup 仍待后续完善。
- 增加只读、破坏性、幂等 ToolAnnotations，帮助客户端理解行为，注解自身不强制权限。
- 注入 Context，提供 MCP 日志和进度；v3.8 现代协议日志通道另有迁移。
- 精简 server instructions，说明已知/未知结构的路径，以 query 为主要自由查询工具，不强制固定探索步骤。
- 验证动态表名，仅接受安全标识符并支持中文，增加纵深防御。
- 通过当时环境开关条件注册可选工具。

## v2.0 工具使用路径

[英文对应记录](REFACTORING_LOG.md#tool-usage-guide-after-refactoring-v20)

已知结构直接 query 并自动安全验证；未知结构先 list_tables，再 describe_table 后 query；sample 用于少量样本，check_connection 用于连通性检查。旧示例参数和返回见英文代码块；当前工具签名以根 README 和 MCP schema 为准。

## 当时采用的工程实践

[英文对应记录](REFACTORING_LOG.md#best-practices-applied)

每个工具保持单一职责、名称贴合用途，返回成功/数据/错误结构一致；使用 async 与 Context，输入验证和表名防注入，错误提供必要上下文。后续逐步收紧结构化失败、结果证据和类型契约，不把早期总结当成所有边界已完成。

## v2.0 兼容性说明

[英文对应记录](REFACTORING_LOG.md#backward-compatibility-notes)

保留连接检查能力，但调用名统一为 check_connection；旧工具名不继续提供，客户端必须更新。此阶段主要迁移接口，功能目标延续；后续版本的兼容性变化分别记录。

## v2.0 修改文件

[英文对应记录](REFACTORING_LOG.md#files-modified-after-refactoring-v20)

`mcp_sql_server.py` 重写；`test_mcp_client.py` 迁移新工具名称；`test_mcp_functions.py` 去除对 MCP 模块的导入并用原始 SQL 做 schema 检查；创建本重构日志。旧测试脚本和 execute_sql 示例仅作历史，v3.8 使用 scripts 目录及完整核心策略。

## v2.0 设计依据与质量指标

[英文对应记录](REFACTORING_LOG.md#why-this-refactoring-follows-best-practices-v20)

将“验证 SQL + 执行 SQL”合并为一次 query 调用，减少工具选择负担。ToolAnnotations 用机器可见提示表达行为；Context 改善当时的日志/进度可见性；lifespan 为连接池及优雅退出提供基础。动态表名显式校验，复杂 system_orchestration/generate_select_sql 提示替换为较简单的 sql_assistant。

历史质量表记录代码约 460→280 行、类型提示从部分到完整，以及维护/测试面的简化。这些是当时的工程判断，不是当前代码规模目标，也不能用代码行数推断安全强度。当前维护优先完整契约、可复现验证和清晰边界。
