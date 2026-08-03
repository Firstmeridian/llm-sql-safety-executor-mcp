# 设计风险登记表

[English](DESIGN_RISK_REGISTER.md) | 中文

创建日期：2026-05-24
最近评审：2026-08-04

文档状态：长期维护的设计与运维风险登记表。  
初始评审批次：v3.4.3。

本文档记录本 MCP SQL 安全网关中的设计风险、取舍、拒绝方案和后续决策。它不是单一版本文档：历史 ID 会保留以便追踪，未来条目可以继续使用版本前缀，也可以使用 `DRR-YYYY-NNN` 格式。

## 范围

以下主题适合进入本登记表：工具行为、模型可见界面、数据库负载、安全声明、日志、缓存、遥测、资源、Schema、运维可靠性等相关风险和设计取舍。

本文档不能替代测试、发布日志或漏洞公告。任何条目如果改变运行时行为，都应补充测试，并在“当前结果”字段记录对应测试文件。

## 状态说明

| 状态 | 含义 |
|---|---|
| 已实现 | 代码或文档修改已完成并记录。 |
| 已接受 | 当前行为是有意识的取舍，暂不计划修改。 |
| 需要策略决策 | 修改前需要先决定兼容性、隐私或审计策略。 |
| 运维决策 | 当前更适合通过部署/运维说明处理，而不是加入服务器逻辑。 |
| 暂缓 | 方向有效，但当前版本没有足够需求或设计清晰度。 |
| 不计划 | 在当前架构下明确不做，除非需求发生变化。 |

## 风险等级说明

| 风险等级 | 含义 |
|---|---|
| 高 | 安全边界、敏感日志/审计、live database 或写入路径风险，可能影响生产安全、隐私或合规。 |
| 中 | 可靠性、运维、治理、可维护性或误导性声明风险，影响明确但范围相对可控。 |
| 低 | 兼容性、命名、文档精度或低影响清理风险，对运行时和安全边界影响有限。 |

`首次登记日期` 记录该行首次进入本登记表或对应评审批次的最早已知日期。

## 评审节奏

- 每个小版本发布前、任何工具界面变化后，复查未关闭条目。
- 涉及日志、缓存、遥测、原始 SQL、模型可见资源的条目，在安全评审后重新检查。
- 只要登记表发生实质修改，就更新“最近评审”。

## 外部最佳实践锚点

| 来源 | 本文档采用的相关指导 |
|---|---|
| [FastMCP Tools 文档](https://gofastmcp.com/servers/tools) | `ToolResult.meta` 是运行期元数据；`output_schema` 必须匹配结构化输出；tool annotations 是提示而非安全边界；清晰的 schema 和描述有助于客户端选择工具。 |
| [FastMCP Middleware 文档](https://gofastmcp.com/servers/middleware) | Middleware 可通过 `on_call_tool` 记录或转换工具调用；响应限制可能破坏结构化输出一致性；缓存 key 默认不包含用户/session 身份，除非显式设计。 |
| [Model Context Protocol 文档](https://modelcontextprotocol.io/docs) / [Claude Code MCP 文档](https://docs.anthropic.com/en/docs/claude-code/mcp) | MCP 工具输出可能挤占上下文；resources 和 tools 都是模型可见界面；更小、更清晰的界面能降低上下文和工具选择风险。 |
| [Python importlib 文档](https://docs.python.org/3/library/importlib.html) / [abc 文档](https://docs.python.org/3/library/abc.html) | `exec_module()` 会在动态导入时执行模块代码；ABC 与 `issubclass()` 适合作为 mutation plugin 具体子类契约的结构性检查。 |
| [Google Gemini Function Calling 文档](https://ai.google.dev/gemini-api/docs/function-calling) | 使用清晰的函数/参数描述、强类型/枚举、相关且有限的工具集、稳健错误处理，并避免通过函数调用暴露敏感数据。 |
| [Microsoft Azure OpenAI Structured Outputs 文档](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs) | 严格 schema 很有用但受约束；任意 SQL 行结构不适合强行声明严格输出 schema。 |
| [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | 不应直接记录 secret、access token、密码、连接串或敏感个人数据；日志需要访问控制、保留/轮转策略和磁盘耗尽防护。 |

## 当前快照

项目当前没有实现通用 SQL 分页工具或 cursor-token 机制，也没有实现进程内遥测百分位聚合、模型可见 stats 工具/资源、session schema cache 或 `db://schema` resource。

v3.4.3 的运行时修复已让 SQLite 行数估算保持有界：当没有 `sqlite_stat1` 且 10,000 行采样达到上限时，`SQLiteAdapter.get_row_estimate()` 返回该上限作为下界估算，而不是继续执行完整 `COUNT(*)`。精确计数仍需通过用户 SQL 或 `get_table_summary(exact_count=True)` 显式触发。

V343-006 至 V343-008 已在 2026-05-26 再次评审。当前策略是文档声明和部署约束，而不是新增运行时控制：原始 SQL echo 为了兼容性和排障透明度继续保留；Skill audit params 被视为业务审计数据而不是 secret 存储；JSONL 轮转/保留交由部署环境处理。

2026-05-26 的实现层过度设计复审没有发现已落地的通用分页、stats tool/resource、session schema cache、`db://schema` resource、raw SQL echo 开关、audit 脱敏策略引擎或进程内日志管理器。主要实现清理候选是启动期生成面向人工审阅的 `skills/SKILLS.md`；其它低优先级清理候选记录在下表。以下条目目前只记录风险和后续决策点，尚未修改运行时代码。

随后对非 AutoGen 模块的复审发现，导入期副作用、导入期配置冻结、adapter metadata 标识符处理，以及 manual smoke 脚本被普通 pytest 收集，是更值得持续跟踪的维护/安全边界风险。这些先作为设计风险记录；除非有明确清理计划，不应贸然引入大 settings object 或大规模测试目录重排。

后续安全边界复审又发现 MCP 扩展 SQL 检查和本地错误日志中存在窄范围 hardening gap。以下条目仅记录风险；当前改动不修改运行时行为。

2026-05-27 又做了一次只读、怀疑式复核：重新运行直接安全判断探针，但没有把危险 SQL 发往 live database 执行。复核确认 DRR-2026-011、DRR-2026-012 和 DRR-2026-015 基本准确；将 DRR-2026-013 收窄为方言/检查范围声明过宽，而不是已经证实的 MySQL/SQLite 写入路径；并补充下方 workflow/SQLAlchemy hygiene 方面遗漏的风险。

随后在 2026-05-27 继续只读复查了 Skills loader/audit 层、配置/启动界面、adapter 写入语义和默认测试收集边界。结果显示，部分此前风险被低估：本地 Skills 代码和元数据仍需要自己的边界校验；query skills 尚未共享自由 `query(sql)` 工具的扩展 SQL 检查；默认 pytest 可通过根目录 smoke test 触达 live database；依赖安装不可复现；MySQL mutation timeout 文档/注释当前依赖的是偏 SELECT 的机制，缺少写入路径证明。

2026-05-28 的聚焦加固批次先实现最高优先级 SQL policy 和日志卫生修复，尚未启动多数据库实现。自由查询与 query skills 已共享同一读查询策略；MySQL 文件操作和 quoted/comment-separated 系统元数据绕过形式被拒绝；Skills 目录 containment 改用路径边界判断；adapter 日志和 SQLAlchemy engine 配置避免暴露 SQL 参数值。

同一 2026-05-28 加固批次也关闭了 DRR-2026-008 和 DRR-2026-014 记录的 adapter metadata 标识符边界。Adapter metadata 方法现在只接受简单未限定表名；能作为数据值处理的 table-name 谓词使用参数绑定；SQLite 中必须作为 identifier 的位置会先校验再引用。

随后在 2026-05-28，DRR-2026-023 也通过明确默认 pytest 契约关闭：`pytest.ini` 将默认收集范围限定为 `tests/`；根目录 MCP smoke 脚本继续作为 manual/live 检查，通过脚本入口在安全的开发库或 fixture 库上显式运行。

2026-05-29，DRR-2026-020 通过收紧轻量 Skills 参数 schema 关闭，而不是替换成完整 JSON Schema。未知参数类型现在会在 discovery 和 validation 阶段 fail closed；bool 参数只接受 JSON boolean 以及显式 `true`/`false` 字符串字面量。

同样在 2026-05-29，一次多数据库就绪度复核认为，之前“先修再做设计”的前置计划已经足够支撑设计阶段：DRR-2026-011、DRR-2026-012、DRR-2026-015、DRR-2026-017、DRR-2026-018、DRR-2026-019、DRR-2026-023、DRR-2026-025 已实现，adapter 边界相关的 DRR-2026-008 与 DRR-2026-014 也已落地。DRR-2026-024 仍保持暂缓，但不视为阻断项，因为当前观察到的冲突面位于 optional AutoGen 示例依赖，而不是核心 server runtime。由此，多数据库工作可以进入 design-only 阶段，但还不适合直接在当前 process-global adapter 与 `DB_TYPE` 地基上进入运行时实现。

2026-05-30，v3.5 已实现第一段运行时多数据库能力：配置化命名连接、connection-aware 只读核心工具、connection-scoped 查询 Skills，以及安全的 `connection_id` 元数据/审计/遥测。实现有意把 mutation Skills 保持为仅默认连接。先解析连接的不变量现在成为运行时设计的一部分：工具必须先解析 `ConnectionContext`，再做 SQL policy、schema readiness、内部辅助 SQL、执行、metadata、audit 和 telemetry。未知连接 id fail closed，不会回退到默认连接。

同日结合官方文档和最佳实践做的 follow-up review 又关闭了几个边界缺口：table allowlist 现在会规范化 quoted 与 schema-qualified identifiers；公开 SQLite payload 使用 `sqlite:<connection_id>` 而不是文件路径；legacy 模式只有在显式设置 `DB_CONNECTIONS` 后才会启用 `DB_<ID>_*` 与 `DEFAULT_DB_CONNECTION`；独立兼容 helper `execute_sql()` 也会先解析目标连接，再做 SQL policy。

同一次复核也收窄了 v3.6 mutation 多连接设计方向：写操作应采用一致的高影响操作协议。目前 preview-token core 和严格 per-connection mutation policy 均已实现。只读 policy 与写授权保持分离；未设置新的全局 mutation 目标 allowlist 时，仍保持仅默认连接路由。

2026-08-04，对合并后的 v3.5/v3.6 改动集做了一次提交前复审：运行默认测试套件（259 passed、3 skipped），在不执行破坏性 SQL 的前提下重新探测 SQL policy，并对照 FastMCP 3.0.2 与 MCP 2025-06-18 tools 规范核对实现。复审确认了已实现的边界，同时新增下表十条记录。其中影响最大的三条是：真实 mutation 联调在被跟踪的示例数据库中留下的数据漂移（DRR-2026-035）、server 级 `instructions` 仍宣称只读但 mutation 工具可写（DRR-2026-036），以及默认 pytest 环境隔离不完整、部分重新打开 DRR-2026-023（DRR-2026-039）。复审同时确认没有运行时行为与已实现的 v3.5/v3.6 条目矛盾，文档漂移仅限于 DRR-2026-042 记录的 v3.5 时期遗留措辞。

## 登记表

| ID | 状态 | 风险等级 | 首次登记日期 | 领域 | 风险或关注点 | 是否计划修改 | 修改逻辑 | 当前结果 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|
| V343-001 | 已实现 | 中 | 2026-05-24 | SQLite 行数估算 | 元数据发现此前会从 10,000 行采样升级为大表完整 `COUNT(*)`。 | 是 | 优先使用 `sqlite_stat1`；采样达到上限时返回下界估算；精确计数保持显式触发。 | 2026-05-24 已完成：修改 `db_adapter.py`，在 `tests/test_db_adapter.py` 增加测试，并更新文档。 | 观察用户是否误解下界估算；需要精确值时建议运行 `ANALYZE` 或显式计数。 |
| V343-002 | 已实现 | 中 | 2026-05-24 | 查询结果截断 | `query()` 和 `execute_query_skill()` 在截断返回 payload 前仍会获取完整 adapter 结果。 | v3.4.3 仅改文档 | 澄清截断只限制返回 payload；用户应使用 `WHERE`/`LIMIT`/`ORDER BY` 限制数据库工作量并稳定顺序。 | 工具消息和文档已更新；adapter 级流式/分批获取仍暂缓。 | 只有在兼容性测试充分时再评估 `fetchmany()` 或 streaming。 |
| V343-003 | 已实现 | 低 | 2026-05-24 | 工具描述 | `list_tables()` 和 `get_full_schema()` 的 all/complete 表述会忽略 allowlist 和截断。 | 是 | 改为 visible/truncated 语义，并澄清 returned/visible counts。 | 面向工具和文档的描述已更新。 | 后续新增工具描述继续保持精确和保守。 |
| V343-004 | 已实现 | 中 | 2026-05-24 | 安全文档措辞 | 部分文档过度声明 comprehensive SQL analysis 或所有调用都经 `validate_name()`/`validate_params()`。 | 是 | 将 sqlparse 描述为语句类型 allowlist 加 MCP 层扩展检查；区分 Skills 参数校验和基础 SQL/table 校验。 | README 和设计文档已更新。 | 不在缺少对应 enforcement 的情况下扩展安全声明。 |
| V343-005 | 已实现 | 低 | 2026-05-24 | Prompt 指南 | `get_table_summary()` 曾被当成默认规划步骤，但该工具默认禁用，精确计数也是显式 opt-in。 | 是 | 默认优先 `describe_table()` 估算；只有需要精确计数时才使用显式 `COUNT(*)` 或 `get_table_summary(exact_count=True)`。 | Prompt guide 已更新；无需运行时测试。 | Prompt 示例要和默认启用工具保持一致。 |
| V343-006 | 已接受 | 高 | 2026-05-26 | 原始 SQL echo/log 可见性 | `query(sql)` 会把完整 SQL 记录到上下文并返回在结构化 payload 中；SQL literal 可能包含敏感值。 | 仅文档声明 | 为兼容性和排障透明度保留当前 echo 行为。不要在原始 SQL literal 中放 secret、token 或敏感个人数据；重复且敏感的工作流优先用低敏谓词、视图或经过 review 的 Skill。 | 2026-05-26 已在 README 和本登记表中声明；不新增运行时开关，避免过早造成兼容性 churn。 | 只有隐私敏感部署明确需要时，再评估 echo/log opt-out 开关。 |
| V343-007 | 已接受 | 高 | 2026-05-26 | Skills audit 参数日志 | Audit 仅截断长参数，不按 key/value 脱敏。 | 仅文档声明 | 将 skill params 视为业务审计数据，而不是 secret 存储。`SKILLS_AUDIT_QUERIES=0` 继续作为默认；mutation audit 为了可追踪性保持自动尝试记录，完整性边界见 DRR-2026-022。 | 2026-05-26 已在 README、`skills/SAFETY.md`、`.env.example` 和本登记表中声明；不新增运行时脱敏层。 | 如果未来 Skill 确实需要敏感参数，再评估 key-based redaction 或 per-skill redaction metadata。 |
| V343-008 | 运维决策 | 中 | 2026-05-26 | Append-only JSONL 日志 | Audit、telemetry 和 server logs 是本地文件，没有内置轮转或保留策略。 | 文档/部署指导 | 优先使用外部日志轮转、保留、访问控制和磁盘监控，而不是进程内日志管理。Audit/telemetry 每次写入都会重新打开文件，适合 rename/create 式外部轮转。 | 2026-05-26 已在 README、`skills/SAFETY.md`、`.env.example` 和本登记表中声明。 | 生产环境使用 `logrotate`、平台日志、cron cleanup 或托管日志 sink；只有受限单文件部署明确需要时再改代码。 |
| V343-009 | 已接受 | 低 | 2026-05-24 | `ToolResult.meta` 可见性 | `_meta` 包含运行期统计，某些客户端可能展示。 | 不改行为 | 保持 metadata 非敏感；不加入 SQL、params、rows、凭据或用户身份。 | 接受当前取舍。 | 新增 meta 字段时重新审查。 |
| V343-010 | 暂缓 | 低 | 2026-05-24 | 基础工具 output schema | 任意 SQL 行结构不适合统一声明严格 schema，容易误导。 | 不做 blanket 修改 | 只给稳定 envelope 的工具考虑 schema。 | 有意暂缓。 | 如有需要，逐个稳定工具评估。 |
| V343-011 | 不计划 | 低 | 2026-05-24 | 通用 SQL 分页参数 | 对任意 SQL 添加 `limit`、`offset`、`page` 或 cursor token 会重复 SQL 语义，且无稳定排序时结果不可靠。 | 否 | 分页留给用户 SQL；如需封装，使用有明确排序键的领域 skill。 | 未实现。 | 未经新设计评审，不添加通用 `query(limit, offset)`。 |
| V343-012 | 暂缓 | 中 | 2026-05-24 | 遥测 stats 工具 | 进程内 p50/p95 聚合或模型可见 stats 工具可能暴露操作模式，并需要有界状态设计。 | v3.4.3 之后继续暂缓 | 保持 opt-in JSONL；聚合交给外部日志处理。 | 有意暂缓。 | 只有出现有界且非模型可见的设计时再评估。 |
| V343-013 | 暂缓 | 中 | 2026-05-24 | Session schema cache | Schema cache 在 DDL 后可能过期，并影响安全/可执行性判断。 | v3.4.3 之后继续暂缓 | 继续以执行时检查为准。 | 有意暂缓。 | 只有存在明确失效策略时再评估。 |
| V343-014 | 暂缓 | 中 | 2026-05-24 | `db://schema` resource | Schema resource 会增加第二条 schema 访问路径，也会扩大模型可见上下文界面。 | v3.4.3 之后继续暂缓 | 继续使用显式 `get_full_schema()`。 | 有意暂缓。 | 只有客户端 resource 支持成为明确需求时再评估。 |
| DRR-2026-001 | 暂缓 | 中 | 2026-05-26 | 启动期副作用 | 启用 Skills 时，server import/startup 当前会 discover skills 并写入面向人工审阅的 `skills/SKILLS.md`。除日志/审计文件外，运行时启动路径理想上应保持只读。 | 候选代码清理，尚未实现 | 保留启动期 eager discovery/cache 作为 TOCTOU 防护；如果修改，应把人工总览生成移到显式维护命令或脚本。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。 | 修改代码前先决定 `skills/SKILLS.md` 是否继续作为 tracked generated artifact，并为显式生成路径补测试/文档。 |
| DRR-2026-002 | 已接受 | 低 | 2026-05-26 | 展示型环境默认值 | `SKILLS_LIST_DEFAULT_DETAIL` 和 `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` 是展示默认值，而 `list_skills()` 已支持单次调用传入 `detail_level` 和 `available_only`。额外 env 默认值会扩大配置矩阵和测试重新 import 成本。 | 暂不改行为 | 将这些变量视为兼容性默认值，而不是安全控制；单次调用参数仍是主接口。 | 为兼容性接受当前取舍。 | 只有确认没有具体客户端需要环境级列表默认值，或进入破坏性版本时，再评估移除/收敛。 |
| DRR-2026-003 | 暂缓 | 低 | 2026-05-26 | Skills 可用性 helper | `_skill_executable_state()` 和 `_skill_is_executable()` 只是包裹 `_skill_availability_state()`，且当前没有调用点。小型未用 wrapper 会让可用性逻辑看起来更像策略引擎。 | 低优先级代码清理 | 后续触碰 Skills 可用性代码时删除未用 wrapper；保留 `_skill_availability_state()` 作为单一判断来源。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。2026-08-04 复查：两者仍只互相引用，且 v3.5 改动集给它们各加了一个 `connection` 参数而不是删除，说明清理触发条件已满足但未执行。 | 在下一次修改 Skills 可用性代码时删除这两个 wrapper，并运行 `tests/test_skills_disclosure.py` 和 `tests/test_multi_connection_v35.py`。 |
| DRR-2026-004 | 已接受 | 低 | 2026-05-26 | 旧 feature switch 命名 | `ENABLE_SCHEMA_TOOLS` 是历史名称，但当前实际只 gate `sample()`，不是全部 schema tools。重命名更清晰，但会带来兼容性 churn。 | 仅文档/兼容处理 | 不把该开关扩展成控制无关 schema tools。如果将来确实需要澄清，可增加兼容别名如 `ENABLE_SAMPLE_TOOL`，不要改变旧变量语义。 | 作为历史命名妥协接受。 | 文档继续精确说明当前该开关只控制 `sample()`。 |
| DRR-2026-005 | 已接受 | 低 | 2026-05-26 | 低层 SQLite 调优面 | `SQLITE_PROGRESS_HANDLER_INTERVAL` 暴露 SQLite VM progress handler 频率。timeout 机制本身合理，但 interval 比多数部署需要的控制面更底层。 | 暂不改行为 | 把 `QUERY_TIMEOUT_SECONDS` 作为用户主要 timeout 控制；没有实测部署需求时，不再新增类似低层 DB 调优 env var。 | 为兼容性接受当前取舍。 | 只有该 interval 导致实测 CPU/延迟问题，或进入可破坏兼容的清理版本时，再评估移除低频调优旋钮。 |
| DRR-2026-006 | 暂缓 | 中 | 2026-05-26 | import/startup 副作用 | `start_server.py` 在模块 import 时就导入 server、加载 `.env`、创建 `logs/` 并安装带时间戳的 `FileHandler`，而这些发生在环境校验之前。单纯 import 或工具探测也可能创建文件并提前冻结 server 配置。 | 候选代码清理，尚未实现 | import 路径理想上保持只读。只有在做聚焦的启动流程清理时，才把 logging setup 和 `mcp_sql_server` import 移入 `main()` 或显式 startup factory。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。 | 重新评估时补测试：import `start_server.py` 不创建日志文件，同时保持 FastMCP `Client(str(start_server.py))` 可启动。 |
| DRR-2026-007 | 暂缓 | 中 | 2026-05-26 | 导入期配置冻结 | `db_adapter.py` 在 import 时把 DB 配置读成模块常量，`sql_safety_checker.py` 直接 import `QUERY_TIMEOUT_SECONDS`，adapter 又全局缓存。测试为了切换配置必须 reload module 或清 `sys.modules`。 | 暂不做大 settings 重构 | 没有具体需求时，不引入大 settings object。若清理，应优先选择窄 factory/config injection 路径，并保留现有公开 API。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。2026-05-29 结合多数据库前置修复计划复核后确认：前面的安全/加固项已基本完成，因此该项已成为运行时多数据库支持前最主要的地基风险。 | 多数据库工作现在可以进入 design-only 阶段，但真正实现前应先选定窄范围的 connection-aware adapter/config 方案（例如按调用选择 `connection_id` registry），而不是继续扩展当前 process-global `DB_TYPE` 与 singleton adapter 路径。若之后需要清理启动/import 路径，再与 DRR-2026-006 一并评估。 |
| DRR-2026-008 | 已实现 | 高 | 2026-05-26 | Adapter metadata 标识符处理 | MySQL 和 SQLite 的 adapter metadata 方法曾把 `table_name` 拼进 SQL/PRAGMA。MCP tools 调用前多数会校验标识符，但 adapter 也是测试和脚本会直接使用的公共内部边界。 | 是 | 在 adapter metadata 边界集中校验简单未限定标识符。MySQL `INFORMATION_SCHEMA` table-name 谓词改用参数绑定；SQLite metadata 路径在 `PRAGMA` 或 bounded sample SQL 前先校验并引用 identifier。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 覆盖非法表名、schema-qualified 名称、quoted identifiers、MySQL 绑定和 SQLite bounded-sample 引用。 | 如果未来 DB 支持需要 schema-qualified 名称，新增结构化 `(schema, table)` API，而不是接受 dotted 或预先 quoted 的字符串。 |
| DRR-2026-009 | 暂缓 | 中 | 2026-05-26 | Smoke/manual 测试边界 | 根目录 `test_mcp_client.py`、`test_mcp_functions.py`、源码读取型 `test_bug_fixes.py` 混合了手动集成检查和 pytest 自动收集；部分依赖真实 DB/server 或检查源码字符串而非行为。 | 候选测试清理 | 行为回归测试应放在 `tests/`；manual smoke flow 应移动到显式脚本或标记为 integration/manual。替换成行为测试前，不删除仍有价值的覆盖。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。 | 先决定默认 pytest 边界和 CI 期望，再整理脚本/测试归属。 |
| DRR-2026-010 | 已接受 | 低 | 2026-05-26 | 运行模块中的 demo 写入 | `sql_safety_checker.py` 的 `__main__` demo 会创建并 seed `test_users` 表。它不是导入期副作用，但把写入型 demo setup 放在 safety module 中会增加心智负担。 | 暂不改行为 | 写入示例优先放在显式 demo/setup 脚本中；不要继续向 runtime library module 添加写入 demo。 | 作为历史 demo 代码接受。 | 清理示例时，将该 demo 移到 `scripts/` 或文档，让 `sql_safety_checker.py` 聚焦 validation/execution helper。 |
| DRR-2026-011 | 已实现 | 高 | 2026-05-26 | MySQL SELECT 文件操作 | 基础和扩展 SQL 安全检查曾把 MySQL `SELECT ... INTO OUTFILE`、`SELECT ... INTO DUMPFILE`、`LOAD_FILE(...)` 当作安全 SELECT 形式。如果 DB 账号有 `FILE` 权限，这些语法可读写 server-side 文件；`DUMPFILE`/`LOAD_FILE` 还可能不包含表名，因此 table allowlist 无法覆盖该风险。 | 是 | 在 MCP 层、注释规范化后显式拒绝 MySQL server-side 文件操作。保持窄 denylist，不引入大 SQL parser 重写。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 OUTFILE、DUMPFILE、LOAD_FILE 和 comment-separated 形式。 | 继续依赖无 `FILE` 权限的最小权限 DB 账号；新增 SQL backend 时补方言相关测试。 |
| DRR-2026-012 | 已实现 | 高 | 2026-05-26 | SHOW/system schema 绕过形式 | 扩展检查曾阻断普通 `SHOW VARIABLES` 和 `information_schema.tables`，但 regex 不拦截 comment-separated SHOW 形式，以及 `` `information_schema`.`tables` ``、`` `mysql`.`user` `` 这类反引号引用系统 schema。 | 是 | 在 denylist 检查前做注释剥离/空白规范化，并扩展系统 schema 匹配以覆盖 quoted schema identifier。table allowlist 仍只是纵深防御，不是唯一系统 schema 屏障。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 comment-separated SHOW 和 quoted `mysql`/`performance_schema`/`information_schema` 引用。 | 后续元数据访问变更继续走共享 policy；避免新增分叉且更弱的 SQL 检查。 |
| DRR-2026-013 | 暂缓 | 中 | 2026-05-26 | SQL 方言安全声明过宽 | `is_sql_safe()` 主要看 `sqlparse` 顶层类型，当前会把 `WITH ... DELETE ... RETURNING ... SELECT ...` 这类 data-modifying CTE 形式判为安全。直接探针也确认 `EXPLAIN DELETE ...` 会被判为安全。当前 MySQL/SQLite 路径尚未证明这些形式会真的执行破坏性写入，但模块文档声称覆盖 PostgreSQL 风格方言。 | 文档或 parser 加固，尚未实现 | 要么把保证收窄到当前支持的 MySQL/SQLite 执行路径，要么显式检查 CTE/嵌套结构中的 DML token。避免声明 comprehensive SQL analysis；在没有方言证据前，也不要把 `EXPLAIN` 包裹 DML 等同于执行 DML。 | 2026-05-26 已记录；2026-05-27 复核后将其精确为 safety scope/声明精度问题，而不是已确认的 MySQL/SQLite 写入漏洞。尚未改运行时代码。 | 改声明或检查前，补 data-modifying CTE、`EXPLAIN DELETE` 和 nested DML-looking token 测试。 |
| DRR-2026-014 | 已实现 | 中 | 2026-05-26 | Adapter metadata 语义注入 | 直接调用 SQLite adapter 时，`get_row_estimate("users) --")` 这类 table name 曾可改变 metadata SQL 语义，包括注释掉 bounded sample 的 `LIMIT` 并退化为完整 count。MCP tools 会拒绝这些标识符，但 adapter 方法仍是公共内部边界。 | 是 | 与 DRR-2026-008 相同：adapter metadata 方法现在先校验，并在 SQLite bounded sampling 中引用 identifier。MCP 上游校验仍只是纵深防御，不是唯一防线。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 证明非法 identifier 不会进入 `execute()`，且有效 sampling 使用 quoted SQLite identifier。 | exact-count 路径和未来 metadata helper 继续沿用同一 adapter identifier policy。 |
| DRR-2026-015 | 已实现 | 高 | 2026-05-26 | 错误日志参数暴露 | Adapter `_handle_error()` 曾记录 `str(e)[:200]`。SQLAlchemy 异常字符串可能包含 SQL 文本和 bound parameter values，然后才返回 sanitized client error。这是本地日志暴露，不是客户端响应暴露。 | 是 | 保持客户端错误 sanitized，同时把 adapter 本地异常日志收敛为 exception class，并在 engine 创建处配置 SQLAlchemy `hide_parameters=True`。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 验证 adapter 日志不包含 SQL 文本或参数值。 | Audit payload 和 tool telemetry 继续按各自文档策略处理；adapter 路径不要重新引入 raw exception logging。 |
| DRR-2026-016 | 已实现 | 中 | 2026-05-27 | CI guardrail 声明过强 | README/REFACTORING_LOG 中曾有 annotation consistency regression 会在 CI 中失败的表述，但仓库当前只有 pytest guardrail，没有配套 CI workflow/config。这会让 reviewer 误以为仓库已经有自动化 CI enforcement。 | 文档清理 | 在真正加入 CI 前，把文档改为 pytest/local/default test guardrail，避免安全/流程声明超过实际 enforcement。 | 2026-05-30 已更新 README、README_ZH、MCP_AGENTS_SKILLS_DESIGN、REFACTORING_LOG 和本登记表；未新增 workflow。 | 如果后续新增 CI，再回头更新这些文档并记录 workflow 文件。 |
| DRR-2026-017 | 已实现 | 中 | 2026-05-27 | SQLAlchemy URL 构造 hygiene | MySQL 连接初始化曾用 f-string 拼接包含用户名、密码、host、database 的 URL。凭据中若包含 `@`、`:`、`/` 等特殊字符，可能导致解析错误或难排查的连接失败；该问题也靠近已有参数日志风险。 | 是 | 改用 SQLAlchemy `URL.create` 结构化构造连接 URL，并在创建 engine 时配合 `hide_parameters=True` 和明确 logging name。范围比大 settings 重构更窄。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 覆盖包含 `@`、`:`、`/` 的凭据构造。 | 未来加入多数据库 registry 时，再评估多 URL builder 和每连接 logging identifier。 |
| DRR-2026-018 | 已实现 | 高 | 2026-05-27 | Skills 目录 containment | Skills 启动时曾对绝对 `SKILLS_DIR` 使用字符串前缀与项目根目录比较。路径字符串以项目根目录开头的 sibling 路径可能通过该检查，而 mutation skills 会在 discovery 阶段通过 `exec_module()` 导入执行。本地可信 repo 内 Skill 执行是预期行为，但 containment check 不应弱于后续 loader 层的路径检查。 | 是 | 在 discovery/import 前，用 `Path.resolve().relative_to()` 替换字符串前缀判断。继续明确 mutation skill code 是可信本地代码，不把 `SKILLS_DIR` 宣称为 sandbox。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 sibling-prefix 路径拒绝。 | 如果未来再次调整 Skills 路径策略，补 symlink-specific containment 测试。 |
| DRR-2026-019 | 已实现 | 高 | 2026-05-27 | Query skill 安全一致性 | Query skill discovery 曾只用基础 `is_sql_safe()` 预审 SQL 模板，没有应用自由 `query(sql)` 工具的 MCP 扩展检查或 table allowlist。因此 query skills 可在启动时接受 DRR-2026-011 和 DRR-2026-012 中的同类 SQL 形状，而 `execute_query_skill()` 后续又跳过运行时 SQL safety check，依赖 discovery-time trust。 | 是 | 增加共享 read-query policy 函数并注入 query skill discovery；`execute_query_skill()` 在执行前也会重新检查缓存的 SQL 模板。 | 2026-05-28 已在 `mcp_sql_server.py` 和 `skills/_lib/skill_loader.py` 实现；测试覆盖 policy 注入和共享 deny checks。 | 后续新增多数据库 `connection_id` 支持时，保持 raw query 与 query skill 使用同一 validation helper。 |
| DRR-2026-020 | 已实现 | 中 | 2026-05-27 | Skills 参数 schema 声明 | `validate_params()` 使用小型自定义 schema 语言，而不是 JSON Schema；它已经拒绝额外参数，但曾存在弱边界：未知 type 名称会直接通过，`bool(value)` 会让 `"false"` 这类字符串变成真值。这会削弱文档或工具描述中类似 strict function schema 的强校验暗示。 | 是 | 将支持的 schema vocabulary 收紧为 `int`、`float`、`str`、`bool`；未知类型现在 fail closed。bool 参数只解析原生布尔值和显式 `"true"`/`"false"` 字符串字面量，不使用 Python truthiness。该 schema 仍是轻量自定义 schema，不描述为完整 JSON Schema。 | 2026-05-29 已在 `skills/_lib/skill_loader.py` 实现；`tests/test_skill_loader.py` 覆盖未知类型、`"false"`、`"0"`、数字 truthy 值、额外参数和 enum 约束。 | 后续新增参数类型前，先显式加入 vocabulary 并补验证测试。 |
| DRR-2026-021 | 已实现 | 中 | 2026-05-27 | Mutation skill 类型完整性 | Mutation discovery 过去只检查模块中有 `Mutation` 属性；frontmatter `name` 也可能与目录身份不一致。由于 `mutation.py` 会在 discovery 阶段通过 `exec_module()` 动态导入执行，畸形的可信本地插件应在运行时 tool 路径缓存或实例化前 fail closed。 | 是 | Discovery 现在要求 frontmatter `name` 必填、符合命名规则，并与 skill 目录名完全一致。Mutation source 必须导出名为 `Mutation` 的 class，且必须是具体的 `MutationBase` 子类。mutation 代码体安全仍依赖人工 review；这不是面向不可信插件的 sandbox。 | 2026-05-29 已在 `skills/_lib/skill_loader.py`、`README.md`、`README_ZH.md`、`MCP_AGENTS_SKILLS_DESIGN.md` 和 `skills/SAFETY.md` 实现；`tests/test_skill_loader.py` 覆盖缺失/不匹配/非法 name，以及缺少、非 class、非 subclass、抽象 `Mutation` 导出。 | 如果未来需要支持不可信第三方插件，应单独设计进程隔离或 sandbox，而不是继续扩展该 loader invariant。 |
| DRR-2026-022 | 已实现 | 高 | 2026-05-27 | Skills audit 完整性声明过强 | `AuditLogger.log()` 仍是 best-effort，审计写入失败或 mutation 参数校验失败仍可能没有 JSONL 记录。旧文档/config 中的表述过度暗示完整记录和 fail-closed audit 行为。 | 是 | 保持 audit 作为 best-effort observability，而不是 fail-closed 事务控制。`AuditLogger.log()` 现在返回写入成功/失败但不抛出；正常 query/mutation 工具结果会基于实际 audit 路径报告 `audit_logged`，校验失败路径显式返回 `audit_logged=false`。文档已补充审计写入失败和校验失败 caveat。 | 2026-05-29 已在 `skills/_lib/audit.py`、`skills/_lib/mutation_base.py`、`mcp_sql_server.py`、README/docs/Skills safety 文档和测试中实现；测试覆盖写入失败、mutation 成功 metadata、validation-failure metadata。 | 如果未来合规要求 guaranteed audit，需要单独设计 transactional/outbox 或数据库审计机制；不要把当前 best-effort JSONL 文件当作 fail-closed 证据。 |
| DRR-2026-023 | 已实现 | 高 | 2026-05-27 | 默认 pytest live database 边界 | `test_mcp_client.py::test_mcp_server` 曾被默认 pytest 收集。只要当前配置的数据库可连接，它会用当前 `.env` 启动 MCP server、list tables、count 第一张表、describe 第一张表、sample rows，并可能执行 query skill。这可能触达 live/类生产数据库，并把 sample data 打印到 pytest captured output 或失败日志中。 | 是 | 通过新增 `pytest.ini` 中的 `testpaths = tests`，让默认 pytest suite 保持 hermetic。根目录 MCP smoke 检查继续作为显式脚本入口，文档已提示只在安全的开发库或 fixture 库上运行。 | 2026-05-28 已在 `pytest.ini`、`README.md`、`README_ZH.md` 和 `TEST_MCP_CLIENT_GUIDE.md` 实现；`python -m pytest --collect-only -q` 现在默认不收集根目录 smoke 脚本。 | 后续 live DB smoke 检查继续留在默认收集之外，除非具备显式 opt-in gate 和非敏感输出策略。 |
| DRR-2026-024 | 暂缓 | 中 | 2026-05-27 | 依赖可复现性 | `requirements.txt` 大多是不固定版本或只有下限的依赖，其中 FastMCP 和 SQLAlchemy API 被项目直接使用。没有 lockfile、constraints file 或 CI matrix 时，未来安装可能静默选择行为/兼容性变化的版本，从而削弱“本地/default tests 代表 release 行为”的声明。dry-run 证据也显示，当前冲突面主要来自 optional AutoGen 依赖链，而不是核心 server runtime 路径。 | Packaging/workflow 清理候选，尚未实现。AutoGen 示例不是本程序主线 runtime。 | 后续若修复，优先拆分 runtime/dev/optional AutoGen dependencies，再为实际支持的安装路径增加 constraints 或 documented tested version set。不要把无约束安装描述成可复现 release input。 | 2026-05-27 配置/依赖复审后记录。2026-05-29 验证：当前 `.venv` 的 `pip check` 仍报告 `autogen-core 0.7.5` 要求 `protobuf~=5.29.3`，但已安装 `protobuf 6.33.5`；`pip install --dry-run --ignore-installed -r requirements.txt` 会解析到包含 `protobuf 5.29.6` 的干净集合；仅核心 runtime dry-run 不会引入 `protobuf`；仅 AutoGen dry-run 会拉入 `protobuf 5.29.6`。在现有 `.venv` 中运行 `pip install --dry-run -r requirements.txt` 只会安装/降级 `protobuf 5.29.6`。本次未修改依赖文件，也未改变环境包；报告只写入 `/tmp`。 | 继续暂缓，除非后续编辑安装/文档路径。不要让 optional AutoGen 示例依赖定义核心 runtime 的可复现性声明。 |
| DRR-2026-025 | 已实现 | 高 | 2026-05-27 | MySQL mutation timeout 语义 | `MySQLAdapter.execute_write()` 曾使用 `MAX_EXECUTION_TIME`，但 MySQL 文档将该机制描述为偏 SELECT/read-query。受控 MySQL 验证确认了缺口：`timeout=1` 下 `SELECT SLEEP(2)` 约 1.079s 停止，而 `UPDATE ... SLEEP(2)` 仍在约 2.171s 后提交成功。 | 是 | 移除写入路径的 `MAX_EXECUTION_TIME`。MySQL `execute_write()` 现在会在 mutation 前设置 session `innodb_lock_wait_timeout = max(1, timeout_seconds)`，若该防护无法配置则 fail closed。文档已区分只读查询 timeout、InnoDB 行锁等待 timeout、PyMySQL socket timeout 和部署侧 DML 控制。 | 2026-05-29 已在 `db_adapter.py`、`tests/test_db_adapter.py`、README/docs 和 Skills safety 文档中实现。受控证明使用数据库 `trade_data_analysis`：旧写入路径忽略 `timeout=1`；另一个 lock-wait 场景在 `innodb_lock_wait_timeout=2` 下约 3.236s 抛出 OperationalError 1205。 | 剩余边界：这不是覆盖所有 MySQL DML CPU/IO 工作的完整 wall-clock statement timeout。如果生产需要硬性的 mutation 执行上限，仍需把 driver read/write timeout 和部署侧 statement controls 纳入方案。 |
| DRR-2026-026 | 已实现 | 高 | 2026-05-30 | 多连接 policy/execution 串线 | 运行时多数据库支持如果让 policy、identifier quoting/schema helper、adapter execution、metadata、audit 或 telemetry 从不同连接读取，就可能出现“展示/校验针对数据库 A，执行却打到数据库 B”的串线风险。 | 是 | 引入 `ConnectionContext`，并在 policy、schema readiness、方言相关 helper SQL、执行、metadata、audit 和 telemetry 之前解析目标连接。`sample()` 和精确表计数中的内部 helper SQL 直接在选中的 adapter 上执行，不再绕回 legacy 默认执行包装。 | 2026-05-30 已在 `db_adapter.py`、`sql_safety_checker.py` 和 `mcp_sql_server.py` 实现；`tests/test_multi_connection_v35.py` 覆盖同连接 policy/execution 和未知 id fail-closed。 | 后续新增工具继续沿用 resolve-first 模式；任何会 quote identifier 或执行内部 SQL 的 helper 路径都要补回归测试。 |
| DRR-2026-027 | 已实现 | 高 | 2026-05-30 | Skills 展示与执行不一致 | 命名连接和 per-connection allowlist 出现后，Skills discovery 可能把某个 skill 展示为在一个数据库类型/schema 下可执行，但实际执行使用另一 adapter。 | 是 | 让 `list_skills`、`get_skill_detail`、`execute_query_skill` 接受可选 `connection_id`，并在同一个目标连接上评估 DB 兼容性、schema readiness、allowlist、metadata、可选 audit 和 telemetry。`SkillMetadata.databases` 仍是 DB 类型兼容字段，不是 connection-id allowlist。 | 2026-05-30 已在 `mcp_sql_server.py` 实现；`tests/test_multi_connection_v35.py`、`tests/test_skills_disclosure.py` 和文档覆盖目标连接的 availability/execution 一致性。 | 继续把 `available_only` 说明为发现层过滤，不是授权边界；执行期检查仍必须保留。 |
| DRR-2026-028 | 已实现 | 中 | 2026-05-30 | Adapter registry 生命周期与资源边界 | 多个命名连接意味着多个长期存在的 SQLAlchemy Engine。如果 registry/reset/lifecycle 不清楚，会泄漏资源，也会让需要切换环境的测试更复杂。 | 是 | 新增按配置化 `connection_id` 懒加载的进程内 adapter cache，并提供 `reset_adapter(connection_id=None)` 关闭单个或全部 adapter，用于测试/重配置。连接定义仍由服务器端配置并在 import 时解析，不引入动态 per-request DSN。 | 2026-05-30 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 和 `tests/test_multi_connection_v35.py` 覆盖 registry 行为。 | 暂缓 LRU/上限/凭据刷新。若部署配置大量连接或需要运行时配置 reload，再重新设计。 |
| DRR-2026-029 | 已实现 | 中 | 2026-05-30 | 日志和元数据中的连接身份 | 运维需要知道一次 tool call 打到了哪个配置化连接，但如果在 `ToolResult.meta`、telemetry、audit 或结构化 payload 展示字段中暴露连接内部信息，会泄漏敏感 DB 细节。 | 是 | 在结果 metadata、可选 telemetry 和 Skills audit 中加入安全别名 `connection_id` 与实际 `db_type`；`list_connections()` 只返回别名和 policy 摘要。公开 SQLite `database_name` 展示字段使用 `sqlite:<connection_id>`，不暴露文件路径。仍排除 DSN、host、用户名、密码、SQLite 路径、SQL params 和返回行。 | 2026-05-30 已在 `mcp_sql_server.py`、`skills/_lib/audit.py`、`skills/_lib/mutation_base.py`、文档和测试中实现；follow-up 测试覆盖 `check_connection()` / `list_tables()` 不暴露 SQLite 路径。 | 新增 metadata/audit/payload 字段时重新审查；未经隐私评审不要加入连接内部信息。 |
| DRR-2026-030 | 已实现 | 高 | 2026-05-30 | 多连接 mutation 写入 | 允许 mutation Skills 选择任意配置化连接，需要 per-connection 写权限、preview/execute 目标绑定、audit 语义，以及针对 SQLite 文件锁和 MySQL 写超时的更强运维说明。 | 是 | 要求全局 mutation 目标 allowlist、per-connection 写开关、per-connection Skill allowlist，以及绑定 skill/version/params/connection/DB type/expiry 的 HMAC preview token。未配置全局路由策略时保持仅默认连接。 | 已在 `db_adapter.py` 和 `mcp_sql_server.py` 实现；discovery 与 execution 共享 policy 检查。`tests/test_mutation_multi_connection_v36_design.py` 覆盖路由、token 绑定、目标隔离、拒绝层、精确过期边界、篡改、Skill version 变化、重启行为和完整 token 不暴露；adapter 测试覆盖配置解析与 legacy 隔离。 | Replay 与 preview-state hardening 已在 DRR-2026-034 实现。每个授权写目标仍需持续说明 SQLite lock 和 MySQL DML timeout 边界。 |
| DRR-2026-031 | 已实现 | 高 | 2026-05-30 | Quoted identifier allowlist 绕过 | MCP table extractor 曾没有一致处理常见 quoted identifiers。`FROM "forbidden"`、`FROM [forbidden]` 或 `FROM main."forbidden"` 这类形式可能绕过或误导 table allowlist 比较，即使实际引用的是不允许访问的表。 | 是 | 在和目标连接 allowlist 比较前，规范化反引号、双引号、方括号和 schema-qualified 引用。保持为聚焦的 extractor 加固，不引入完整 SQL parser。 | 2026-05-30 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 quoted/schema-qualified deny case 和允许的 quoted 表。 | 后续 table-reference 解析继续走共享 policy 路径；扩展语法支持前先补方言示例测试。 |
| DRR-2026-032 | 已实现 | 中 | 2026-05-30 | Legacy named-env 泄漏 | 本地多连接 `.env` 中的 `DB_DEFAULT_*` 和 `DEFAULT_DB_CONNECTION` 可能在 `DB_CONNECTIONS` 未设置或为空时影响 legacy 单连接模式，破坏向后兼容，或因为 named default 不存在导致 legacy 启动失败。 | 是 | 将 `DB_CONNECTIONS` 作为命名连接唯一 feature gate。legacy 模式忽略 `DB_<ID>_*` 和 `DEFAULT_DB_CONNECTION`；`DB_TYPE` / `SQLITE_DATABASE_PATH` 继续作为权威配置。 | 2026-05-30 已在 `db_adapter.py`、`.env.example`、README/docs 和测试中实现；`tests/test_db_adapter.py` 覆盖 legacy 模式忽略 `DB_DEFAULT_*` 和默认连接选择。 | 后续新增 per-connection setting 时保留该 gate；未经显式迁移决策，不让 named 变量影响 legacy 模式。 |
| DRR-2026-033 | 已实现 | 中 | 2026-05-30 | 兼容 helper 解析顺序 | 独立 helper `sql_safety_checker.execute_sql(..., connection_id=...)` 曾可能先做 SQL safety，再解析目标连接。未知 id 应先 fail closed，再考虑任何目标相关 policy 或执行路径。 | 是 | 在 `is_sql_safe()` 和 adapter execution 前先用 `get_connection_config()` 解析 `connection_id`，保持和 MCP 工具的 resolve-first 不变量一致。 | 2026-05-30 已在 `sql_safety_checker.py` 实现；`tests/test_multi_connection_v35.py` 覆盖未知 `connection_id` 会先返回连接错误而不是 SQL policy 错误。 | 后续扩展 connection-aware policy 时，保持兼容 helper 与 MCP tool 顺序一致。 |
| DRR-2026-034 | 已实现 | 高 | 2026-05-30 | Preview-token replay 与审阅状态漂移 | 有效 HMAC token 曾可在过期前 replay；内置 mutation 还会在 execute 时重新读取当前状态，而不是锁定 preview 展示的状态。单靠乐观锁不是通用 replay 或“所见即所写”边界。 | 是 | 增加随机 `jti` 和有界 execution-state hash；在有界加锁 memory store 中登记 digest/expiry/canonical binding，并在动态 validation/write 前原子消费。后续失败保持 terminal。状态敏感 Skill 必须显式处理非空 binding。 | 已在 `mcp_sql_server.py`、`MutationBase` 和 `update-order-status` 实现。测试覆盖唯一签发、顺序/并发 replay、容量与懒过期、重启失效、静态拒绝不消费、validation/write/audit 后 terminal、状态漂移和忽略 binding 拒绝。 | 当前 memory backend 适用于单进程 stdio/单 worker。多 worker 在共享原子 backend 实现前仍不支持；禁止加入 stateless fallback。 |
| DRR-2026-035 | 暂缓 | 低 | 2026-08-04 | 示例数据库 fixture 漂移 | v3.6 mutation 真实联调在被 git 跟踪的 `sample_data/demo.db` 中留下了数据变更：订单 `id=4` 从 `pending` 变为 `confirmed`。除此之外所有表和行数与 `HEAD` 完全一致，临时订单 `990001` 已删除。联调记录只写了 `990001` 的清理，因此这处残留看起来像是有意变更，实际不是。 | 待维护者决策 | 示例 fixture 应保持确定性初始状态，让内置 demo Skill、`scripts/setup_demo_db.py` 和 `profiles: [demo]` 示例可复现。要么回滚该文件，要么显式接受新状态并在 fixture 文档中说明。 | 2026-08-04 通过对比 `git show HEAD:sample_data/demo.db` 与工作区发现；本次复审未修改任何文件。 | 提交前决定回滚 `sample_data/demo.db`，还是把 `confirmed` 记录为新的文档化基线。后续真实写入 smoke 应优先使用一次性 fixture 库，而不是被跟踪的示例文件。 |
| DRR-2026-036 | 暂缓 | 中 | 2026-08-04 | Server instructions 声称只读 | FastMCP server 级 `instructions` 仍写着 “Database query assistant with READ-ONLY access”，且只提到 `query`、`describe_table` 和 `get_full_schema`。当 `ENABLE_SKILLS=1` 且 `SKILLS_ALLOW_MUTATIONS=1` 时，`execute_mutation_skill` 会真实写库，并且所有核心工具都接受 `connection_id`。这是模型可见文本，能力声明不准确会影响工具选择，也会错误呈现服务的安全画像。 | 文档/运行时措辞修复，尚未实现 | 让 `instructions` 描述实际注册的界面：默认只读核心工具、可选 Skills、受 preview-token 协议保护的可选受控写入，以及配置化 `connection_id` 路由。保持简短，因为 server instructions 会占用模型上下文。 | 2026-08-04 已记录；尚未改运行时代码。FastMCP 与 MCP 指导都把 tool/server 描述视为选择依据，应准确反映实际行为。 | 下次调整 mutation 界面时重写 `instructions`，并新增测试：注册了 mutation 工具但 instructions 仍声称只读时应失败。 |
| DRR-2026-037 | 暂缓 | 中 | 2026-08-04 | Mutation 双执行路径 | `MutationBase` 要求实现具体的 `execute()`，因此 `update-order-status` 同时保留了 `execute()` 和 `execute_with_binding()`。在 MCP 路径中 `run_execute()` 始终走 binding，且 `build_execution_binding()` 不会返回空值，所以 `execute()` 在该路径下不可达。但它仍是公开可调用路径：重新读取当前状态并在没有 preview 绑定的情况下写入，正是 DRR-2026-034 消除的 TOCTOU 行为。 | 代码清理，尚未实现 | 状态敏感 Skill 应只保留一条权威写入路径。要么让 `execute()` 抛出 `ToolError` 并指向 binding 路径，要么调整 ABC 结构，使 binding-aware Skill 不必额外保留一个更弱的兄弟实现。 | 2026-08-04 已记录；尚未改运行时代码。当前无法通过 MCP 利用，因为工具层不会直接调用 `execute()`。 | 在新增第二个状态敏感 mutation Skill 前先确定 ABC 契约，并补测试断言工具层无法到达无绑定路径。 |
| DRR-2026-038 | 暂缓 | 中 | 2026-08-04 | Preview 绑定来源与预览失败仍签发 token | `update-order-status` 的 `build_execution_binding()` 读取 `validation["current_status"]`，但 `preview()` 会执行自己独立的 `SELECT` 并展示第二次读取的状态。文档和 DRR-2026-034 把该绑定描述为“preview 展示的状态”。如果订单行在 `validate()` 与 `preview()` 之间发生变化，展示状态与绑定状态会不同。更窄的情况是订单行在两次调用之间消失：`preview()` 返回 `{"preview_sql": "N/A", "error": ...}`，但仍会签发 token，且 payload 报告 `success=true`。 | 代码与文档修正，尚未实现 | 要么用产生展示结果的同一次读取构建绑定，要么把保证改述为“preview 之前刚校验过的状态”。此外，preview 结果报告错误时不应签发 preview token。 | 2026-08-04 已记录；尚未改运行时代码。窗口很窄，且乐观锁仍能阻止覆盖非预期状态，因此这是正确性/声明精度问题，而不是已证实的不安全写入。 | 补回归测试：在 `validate()` 与 `preview()` 之间修改订单行，断言绑定来源以及预览失败不签发 token。 |
| DRR-2026-039 | 暂缓 | 高 | 2026-08-04 | 默认 pytest 环境隔离缺口 | `tests/conftest.py` 在导入时只清空 `DB_CONNECTIONS` 和 `SKILLS_ALLOW_MUTATION_CONNECTIONS`，但 `db_adapter.py` 在 import 时就调用 `load_dotenv()`。legacy 的 `DB_TYPE`、`DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_NAME`、`SQLITE_DATABASE_PATH`、`ALLOW_UNION`、`ALLOWED_TABLES` 以及 Skills/telemetry 开关仍来自开发者 `.env`。`mysql_adapter` fixture 只在这些 legacy 变量缺失或服务器不可达时跳过，因此仍使用 legacy 变量风格的开发者会让测试连接真实 MySQL。这部分重新打开了 DRR-2026-023，而后者的结论声称默认套件是 hermetic。 | 测试隔离修复，尚未实现 | 隔离代码实际读取的完整配置变量集合，而不只是此前弄坏某个 fixture 的那两个。建议在 `conftest.py` 使用显式清理/允许列表，并为任何 live database fixture 增加显式 opt-in gate。 | 2026-08-04 已记录；尚未改运行时代码。当前本地运行之所以跳过 MySQL，只是因为该开发者的 `.env` 已迁移到 `DB_MYSQL_*`，因此 hermetic 是偶然而非强制。 | 扩展 `conftest.py` 隔离范围，为 `mysql_adapter` 增加显式 integration opt-in 标记，并在套件真正结构性 hermetic 后修正 DRR-2026-023 的措辞。 |
| DRR-2026-040 | 暂缓 | 低 | 2026-08-04 | 不可达的配置 helper | `mcp_sql_server.py` 中的 `_parse_table_allowlist()` 已定义但从未被调用。模块级 `ALLOWED_TABLES` 现在从 `_DEFAULT_CONNECTION_POLICY.allowed_tables` 派生，因此这个 legacy 解析器和它的启动日志已是死代码。在实时 policy 路径旁保留第二个语义不同的 allowlist 解析器，会诱导后续修改改错函数。 | 低优先级代码清理 | 与 DRR-2026-003 的 wrapper 一并删除，让 allowlist 解析在 `db_adapter.py` 中只有一个归属。另外 `pytest.ini` 当前缺少文件末尾换行。 | 2026-08-04 已记录；尚未改运行时代码。 | 在下一次 `mcp_sql_server.py` 清理中移除，并重新运行 `tests/test_sql_policy.py` 和 `tests/test_multi_connection_v35.py`。 |
| DRR-2026-041 | 暂缓 | 中 | 2026-08-04 | Mutation 回归断言偏弱 | 三处测试弱点降低了 v3.6 套件的信号强度。`tests/test_mutation_multi_connection_v36_design.py` 中的签名 secret 轮换用例取得 preview 后直接返回，没有第二次导入、没有更换 secret、也没有断言，即使轮换完全失效也会通过。`tests/test_mutation_skills.py` 中的 `assert "sqlalchemy" not in error_msg.lower() or "Error:" in error_msg` 右操作数已被前一条断言保证，使这条脱敏检查恒真。没有任何测试 monkeypatch `adapter.execute_write()` 抛出异常，因此数据库写入失败时的 token terminal 消费分支没有端到端覆盖。 | 测试加固，尚未实现 | 断言必须能够失败。用直接检查替换恒真断言，补全轮换场景，并新增写入失败用例，断言 token 已被消费且脱敏错误提示需要重新 preview。 | 2026-08-04 已记录；尚未改运行时代码。v3.6 的其它分支（过期、容量、篡改、跨连接、replay）确有真实覆盖。 | 在把 v3.6 套件作为共享 store 或多 worker token backend 的证据之前，先修复这三处。 |
| DRR-2026-042 | 暂缓 | 低 | 2026-08-04 | v3.6 之后遗留的 v3.5 时期措辞 | 多份文档仍把 v3.5 的妥协描述为当前状态。`MCP_AGENTS_SKILLS_DESIGN.md` 安全表第 17 行写着 mutation Skills 只在默认连接执行“直到多连接写策略被显式设计”，而 v3.6 已经实现。`README.md` 把“v3.5 default-only mutation scope”列为无条件的可用性过滤原因。`TEST_MCP_CLIENT_GUIDE.md` 标题仍是“(v3.5)”，正文却已记录 v3.6 的 `preview_token` 协议。`agent_examples/AGENT_DEVELOPMENT_ZH.md` 漏掉 `list_connections` 与 `get_skill_detail`，并写成 `execute_mutation_skill` 只需要 `SKILLS_ALLOW_MUTATIONS=1`。`SKILLS_AUDIT_QUERIES` 上方的注释仍说 mutation Skills“无条件审计”，与 DRR-2026-022 记录的 best-effort 语义矛盾。 | 文档清理 | 为所有 default-only 表述补上“当省略 `SKILLS_ALLOW_MUTATION_CONNECTIONS` 时”的限定；更新指南标题和 Agent 工具表；把审计注释改为 best-effort 措辞。 | 2026-08-04 已记录。已另行核实环境变量名/默认值、工具数量声明、EN/ZH 登记表条目对齐和 Markdown 相对链接均与代码一致。 | 在下一次文档整理中统一处理，并对照 `mcp_sql_server.py` 重新核对工具注册条件。 |
| DRR-2026-043 | 已接受 | 中 | 2026-08-04 | 读 allowlist fail-open 与写 allowlist fail-closed 不对称 | `DB_<ID>_ALLOWED_TABLES` 为空或省略表示所有可见表都可读，而 `DB_<ID>_MUTATION_SKILLS` 为空或省略表示拒绝所有写入。两个默认值都是有意为之，但方向相反，且分别记录在不同位置，运维可能合理地误以为“留空总是更严格的选择”。 | 仅文档声明 | 读侧默认为兼容 legacy `ALLOWED_TABLES` 语义而保留，写侧继续 deny-by-default。应在同一处集中说明这个不对称，而不是分散在两个配置段落中隐含表达。 | 2026-08-04 作为有意的兼容性取舍接受。 | 在 `.env.example`、`.env.example_ZH` 和 README 安全章节增加明确说明；生产部署建议配置具体的读表 allowlist。 |
| DRR-2026-044 | 已接受 | 低 | 2026-08-04 | Preview-token store 容量自我拒绝 | `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES` 限制未过期 token 数量，容量耗尽时 fail closed 而不驱逐有效条目。因此持续 preview 但不 execute 的客户端可以填满 store，在条目过期前（最长 `MUTATION_PREVIEW_TOKEN_TTL_SECONDS`）阻塞正常 preview。 | 不改行为 | fail closed 是正确取舍：为腾出空间而驱逐已审阅的 preview 会静默作废已批准的工作。preview 路径的可用性风险低于失去 replay 保护。 | 2026-08-04 接受。默认容量 10000 配合 300 秒 TTL，使该情况难以被意外触发。服务端仍未实现按客户端的限流，而 MCP 将其列为服务端责任（`skills/SAFETY.md` §13）。 | 若服务将来通过 HTTP 暴露给不可信调用方，与限流一并重新评估。 |

## 初始 v3.4.3 评审批次状态

1. V343-001 是本组唯一运行时行为修改，已实现。
2. V343-002 仅作为措辞/消息清理实现；adapter 级查询 streaming 暂缓。
3. V343-003 至 V343-005 作为文档和工具描述清理实现。
4. V343-006 至 V343-008 已明确作为文档和运维约束收口，而不是新增运行时控制。

## 当前明确不做的事项

- 面向任意 SQL 的通用 `query(limit, offset)` 或 cursor-token 分页。
- 进程内 p50/p95 聚合或模型可见 stats 工具/资源。
- 对所有基础工具统一添加严格 output schema。
- 没有失效策略的 session schema cache。
- 在出现明确客户端需求前新增 `db://schema` resource。
- 在部署要求明确前加入进程内日志轮转/保留逻辑。
- 没有隐私敏感部署需求时新增 raw SQL echo 开关或 audit 脱敏策略引擎。
- 在启动期新增运行时生成的人工文档/维护产物；现有 `skills/SKILLS.md` 启动期生成已由 DRR-2026-001 跟踪。
- 没有明确客户端/部署需求时新增展示型环境默认值或低层调优开关。
- 没有明确启动需求时新增 import-time 文件系统副作用或配置读取，让测试必须靠 reload module 才能切换配置。
- 对可以通过公开 helper 或 MCP tool 行为测试覆盖的逻辑新增源码字符串回归测试。
- 在自由 `query(sql)` 工具中允许 MySQL `SELECT` 文件读写特性（`OUTFILE`、`DUMPFILE`、`LOAD_FILE`）。
- SQL 方言把注释/引号当作语法时，仅依赖匹配普通空白或未引用形式的 regex 来阻断 system schema 与 SHOW 命令。
- 本地 DB error logs 记录 SQLAlchemy 参数值。
- 在仓库没有 CI workflow 时，声明测试会在 CI 中失败或由 CI 自动拦截。
- 有结构化 URL API 可用时，仍用原始凭据字符串手写 SQLAlchemy database URL。
- 将字符串前缀路径检查视为可信本地 Skills 代码的充分 containment。
- 在 validation 尚未共享前，声明 query skill SQL 与自由 `query(sql)` 工具获得相同扩展 safety checks。
- 将轻量 Skills params schema 描述成完整 JSON Schema，或在没有显式验证测试时新增参数类型。
- 将 best-effort audit 写入描述成完整、fail-closed 的 mutation audit。
- 没有显式 integration-test opt-in 时，让默认 pytest 连接 live database 或打印 sampled row data。
- 将只有下限或未固定版本的依赖安装视为可复现 release input。
- 没有版本特定证明时，把偏 SELECT 的 MySQL timeout 设置当作 mutation/lock-wait 保护。
- 接受模型传入任意 DSN，或在 `connection_id` 未知时静默回退到默认连接。
- 用一个目标连接计算 Skills 可用性，却用另一个目标连接执行。
- 在 per-connection 写策略、preview/execute 目标绑定和 audit 语义设计完成前启用多连接 mutation 写入。
- 将真实写入联调对被跟踪示例 fixture 数据库造成的副作用一并提交。
- 在模型可见的 server instructions 或工具描述中，声称比当前配置下实际注册的工具界面更窄的能力。
- 在已要求 preview-state binding 后，仍为状态敏感的 mutation Skill 保留第二条无绑定写入路径。
- 编写无法触发失败的回归断言，或只搭建场景而不断言结果的测试。
- 在默认 pytest 仍会从开发者 `.env` 读取 live database 配置时，声称它是 hermetic 的。

## 更新流程

当某个条目被实现、拒绝或重新定范围时：

1. 更新 `状态`、必要时更新 `风险等级`、`是否计划修改`、`修改逻辑`、`当前结果` 和 `最近评审`。
2. 行为修改必须补充或更新测试，并在条目中记录测试文件。
3. 纯文档修改要记录修改过的文档，以及为什么不需要运行时测试。
4. 策略条目在修改运行时行为前，先记录兼容性/安全取舍。
5. 新增条目时，`首次登记日期` 填该风险首次进入本登记表的日期，而不是最近复审日期。
6. 除非条目创建有误，不要删除历史条目；将旧条目标记为已接受、暂缓或不计划。

## 评审清单

- 是否新增了模型可见 tool、resource、prompt、schema 或 meta 字段？
- 是否记录了 SQL、params、rows、用户标识、凭据或操作模式？
- 是否引入可能无界增长或过期的进程内/session 状态？
- 启动/import 路径是否写入生成式人工文档或维护产物？
- 启动/import 路径是否在环境校验前创建文件、安装 handler 或冻结配置？
- 公共内部边界是否依赖上游校验，而不是自己做最小 identifier validation/quoting？
- 顶层 read-only SQL 类型是否仍能在当前方言中执行文件 I/O、读取 server 文件或包含嵌套 DML？
- 在返回 sanitized client error 前，日志里是否已经包含 raw SQL、bound params、secret 或 SQLAlchemy 参数 dump？
- 文档是否声明了 CI、生产或自动化 enforcement，而仓库实际上没有提供？
- database URL 和 DB error log 的构造方式是否可能暴露或误解析 credentials/parameters？
- Skills path、frontmatter 字段、mutation class 和自定义参数 schema 是否在 loader 边界 fail closed？
- Query skills 与自由 query tool 是否共享同一 SQL safety policy？如果没有，文档是否分别说明？
- 默认 pytest 是否保持 hermetic，还是在未显式 opt-in 时也会连接 live database 并打印数据？
- 依赖版本是否能复现当前声明的行为和 API？
- Timeout 表述是否由实际执行的数据库语句类型支持，尤其是 writes 和 lock waits？
- 是否让昂贵数据库操作看起来像轻量元数据？
- 是否先解析 `ConnectionContext`，再做 policy、readiness、helper SQL、执行、metadata、audit 和 telemetry？
- Skills 的列表/详情/执行是否使用同一目标连接，并在未知 connection id 时 fail closed？
- 新增日志/meta/audit 字段是否暴露了连接串、host、用户、密码、SQLite 路径、SQL params 或返回行？
- 是否声明了代码无法保证的校验、完整性、精确性或排序？
- 测试是否覆盖了预期路径和被拒绝的失败模式？
- 本次 diff 是否把真实联调对被跟踪二进制或示例 fixture 的副作用，当成了有意变更？
- server `instructions` 和工具描述是否与当前 feature switch 下实际注册的工具界面一致？
- 默认测试套件是否隔离了代码在 import 时读取的全部配置变量，而不只是之前弄坏过 fixture 的那几个？
- 新增的每条断言是否真的可能失败，新增测试是否断言了其名称声称覆盖的行为？
