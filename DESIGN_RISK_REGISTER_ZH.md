# 设计风险登记表

[English](DESIGN_RISK_REGISTER.md) | 中文

创建日期：2026-05-24
最近评审：2026-08-22

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
| [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) | 应用校验需要配合参数绑定和最小权限数据库账号；table/view/object grant 仍是权威边界。 |
| [MySQL stored program restrictions](https://dev.mysql.com/doc/refman/8.4/en/stored-program-restrictions.html) / [locking functions](https://dev.mysql.com/doc/refman/8.4/en/locking-functions.html) | SELECT 形状的 stored-function 与 named-lock 调用可能产生外层 statement type 看不出的效果；语法过滤不能替代账号权限。 |

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

2026-08-04，对合并后的 v3.5/v3.6 改动集做了一次提交前复审：运行默认测试套件（259 passed、3 skipped），在不执行破坏性 SQL 的前提下重新探测 SQL policy，并对照 FastMCP 3.0.2 与 MCP 2025-06-18 tools 规范核对实现。复审确认了已实现的边界，同时新增下表十条记录。其中当时影响最大的三条是：真实 mutation 联调在被跟踪的示例数据库中留下的数据漂移（DRR-2026-035）、server 级 `instructions` 仍宣称只读但 mutation 工具可写（DRR-2026-036），以及默认 pytest 环境隔离不完整、部分重新打开 DRR-2026-023（DRR-2026-039）。复审同时确认没有运行时行为与已实现的 v3.5/v3.6 条目矛盾，文档漂移仅限于 DRR-2026-042 记录的 v3.5 时期遗留措辞。

2026-08-06，v3.6.1 维护更新关闭了 DRR-2026-037、DRR-2026-038 与
DRR-2026-041，并扩展了 DRR-2026-034 记录的 replay 防护。该版本仍属于
v3.6 release family。

2026-08-08 的范围评审以有界进程内 memory store 和 stdio-first 部署关闭了
DRR-2026-045。条件性 HTTP mutation 仅限受信任私有边界中的单进程；多用户认证
HTTP 和跨主机副本不是 v3.6.1 基线。只读容量只能通过独立 endpoint/profile/pool
扩展。

2026-08-10 的 follow-up 关闭了 DRR-2026-036、DRR-2026-040 与 DRR-2026-042，
记录 DRR-2026-043 的已接受不对称默认值，将 preview TTL 限制为最多 86400 秒，
收紧 preview 失败契约，并用完整工具层并发 replay 回归替换重复的 store 并发测试。

2026-08-20 的 v3.7 对抗复核发现，只读 statement shape 不足以实施 table scope：
comma join、comment-separated keyword、qualified name、过宽 SHOW 与多 statement
都可能绕过或误导 regex 时代的 extractor。因此 v3.7 选择收窄可接受 raw grammar，
而不是引入一个声称完整的跨方言 AST policy。同一轮复核还补齐了严格 Skill
metadata value 校验，并增加明确仅供测试的跨数据库 reset mutation。数据库
最小权限和 schema 强制的订单 id 唯一性仍是权威边界，因为 SELECT 形状的
stored function 与
locking function 可能产生 outer-statement checker 无法证明不存在的副作用。

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
| DRR-2026-003 | 已实现 | 低 | 2026-05-26 | Skills 可用性 helper | `_skill_executable_state()` 和 `_skill_is_executable()` 只包装 `_skill_availability_state()`，且没有真实调用者。这些额外名称会让 availability policy 看起来不像集中在一个入口。 | 是 | 删除两个 wrapper，保留 `_skill_availability_state()` 作为唯一判断来源。 | 2026-08-10 已在 `mcp_sql_server.py` 实现；Skills disclosure 与多连接回归在删除后通过。 | Availability 决策继续集中到 `_skill_availability_state()`；不要为没有消费者的 convenience wrapper 增加入口。 |
| DRR-2026-004 | 已接受 | 低 | 2026-05-26 | 旧 feature switch 命名 | `ENABLE_SCHEMA_TOOLS` 是历史名称，但当前实际只 gate `sample()`，不是全部 schema tools。重命名更清晰，但会带来兼容性 churn。 | 仅文档/兼容处理 | 不把该开关扩展成控制无关 schema tools。如果将来确实需要澄清，可增加兼容别名如 `ENABLE_SAMPLE_TOOL`，不要改变旧变量语义。 | 作为历史命名妥协接受。 | 文档继续精确说明当前该开关只控制 `sample()`。 |
| DRR-2026-005 | 已接受 | 低 | 2026-05-26 | 低层 SQLite 调优面 | `SQLITE_PROGRESS_HANDLER_INTERVAL` 暴露 SQLite VM progress handler 频率。timeout 机制本身合理，但 interval 比多数部署需要的控制面更底层。 | 暂不改行为 | 把 `QUERY_TIMEOUT_SECONDS` 作为用户主要 timeout 控制；没有实测部署需求时，不再新增类似低层 DB 调优 env var。 | 为兼容性接受当前取舍。 | 只有该 interval 导致实测 CPU/延迟问题，或进入可破坏兼容的清理版本时，再评估移除低频调优旋钮。 |
| DRR-2026-006 | 暂缓 | 中 | 2026-05-26 | import/startup 副作用 | `start_server.py` 在模块 import 时就导入 server、加载 `.env`、创建 `logs/` 并安装带时间戳的 `FileHandler`，而这些发生在环境校验之前。单纯 import 或工具探测也可能创建文件并提前冻结 server 配置。 | 候选代码清理，尚未实现 | import 路径理想上保持只读。只有在做聚焦的启动流程清理时，才把 logging setup 和 `mcp_sql_server` import 移入 `main()` 或显式 startup factory。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。 | 重新评估时补测试：import `start_server.py` 不创建日志文件，同时保持 FastMCP `Client(str(start_server.py))` 可启动。 |
| DRR-2026-007 | 暂缓 | 中 | 2026-05-26 | 导入期配置冻结 | `db_adapter.py` 在 import 时把 DB 配置读成模块常量，`sql_safety_checker.py` 直接 import `QUERY_TIMEOUT_SECONDS`，adapter 又全局缓存。测试为了切换配置必须 reload module 或清 `sys.modules`。 | 暂不做大 settings 重构 | 没有具体需求时，不引入大 settings object。若清理，应优先选择窄 factory/config injection 路径，并保留现有公开 API。 | 2026-05-26 已记录到本登记表；尚未改运行时代码。2026-05-29 结合多数据库前置修复计划复核后确认：前面的安全/加固项已基本完成，因此该项已成为运行时多数据库支持前最主要的地基风险。 | 多数据库工作现在可以进入 design-only 阶段，但真正实现前应先选定窄范围的 connection-aware adapter/config 方案（例如按调用选择 `connection_id` registry），而不是继续扩展当前 process-global `DB_TYPE` 与 singleton adapter 路径。若之后需要清理启动/import 路径，再与 DRR-2026-006 一并评估。 |
| DRR-2026-008 | 已实现 | 高 | 2026-05-26 | Adapter metadata 标识符处理 | MySQL 和 SQLite 的 adapter metadata 方法曾把 `table_name` 拼进 SQL/PRAGMA。MCP tools 调用前多数会校验标识符，但 adapter 也是测试和脚本会直接使用的公共内部边界。 | 是 | 在 adapter metadata 边界集中校验简单未限定标识符。MySQL `INFORMATION_SCHEMA` table-name 谓词改用参数绑定；SQLite metadata 路径在 `PRAGMA` 或 bounded sample SQL 前先校验并引用 identifier。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 覆盖非法表名、schema-qualified 名称、quoted identifiers、MySQL 绑定和 SQLite bounded-sample 引用。 | 如果未来 DB 支持需要 schema-qualified 名称，新增结构化 `(schema, table)` API，而不是接受 dotted 或预先 quoted 的字符串。 |
| DRR-2026-009 | 暂缓 | 中 | 2026-05-26 | Smoke/manual 测试边界 | 根目录 `test_mcp_client.py`、`test_mcp_functions.py`、源码读取型 `test_bug_fixes.py` 混合了手动集成检查和 pytest 自动收集；部分依赖真实 DB/server 或检查源码字符串而非行为。 | 候选测试清理 | 行为回归测试应放在 `tests/`；manual smoke flow 应移动到显式脚本或标记为 integration/manual。替换成行为测试前，不删除仍有价值的覆盖。 | v3.7 部分清理：等价行为覆盖落入 `tests/test_sql_policy.py` 后，已从 `test_bug_fixes.py` 删除过时 table-regex 源码字符串断言。其它 legacy source/manual smoke 仍保留，因此本条继续暂缓。 | 只有已有等价行为覆盖时才继续替换源码形状断言。决定 CI/manual integration 边界后，再整理剩余脚本归属。 |
| DRR-2026-010 | 已接受 | 低 | 2026-05-26 | 运行模块中的 demo 写入 | `sql_safety_checker.py` 的 `__main__` demo 会创建并 seed `test_users` 表。它不是导入期副作用，但把写入型 demo setup 放在 safety module 中会增加心智负担。 | 暂不改行为 | 写入示例优先放在显式 demo/setup 脚本中；不要继续向 runtime library module 添加写入 demo。 | 作为历史 demo 代码接受。 | 清理示例时，将该 demo 移到 `scripts/` 或文档，让 `sql_safety_checker.py` 聚焦 validation/execution helper。 |
| DRR-2026-011 | 已实现 | 高 | 2026-05-26 | MySQL SELECT 文件操作 | 基础和扩展 SQL 安全检查曾把 MySQL `SELECT ... INTO OUTFILE`、`SELECT ... INTO DUMPFILE`、`LOAD_FILE(...)` 当作安全 SELECT 形式。如果 DB 账号有 `FILE` 权限，这些语法可读写 server-side 文件；`DUMPFILE`/`LOAD_FILE` 还可能不包含表名，因此 table allowlist 无法覆盖该风险。 | 是 | 在 MCP 层、注释规范化后显式拒绝 MySQL server-side 文件操作。保持窄 denylist，不引入大 SQL parser 重写。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 OUTFILE、DUMPFILE、LOAD_FILE 和 comment-separated 形式。 | 继续依赖无 `FILE` 权限的最小权限 DB 账号；新增 SQL backend 时补方言相关测试。 |
| DRR-2026-012 | 已实现 | 高 | 2026-05-26 | SHOW/system schema 绕过形式 | 扩展检查曾阻断普通 `SHOW VARIABLES` 和 `information_schema.tables`，但 regex 不拦截 comment-separated SHOW 形式，以及 `` `information_schema`.`tables` ``、`` `mysql`.`user` `` 这类反引号引用系统 schema。 | 是 | 在 denylist 检查前做注释剥离/空白规范化，并扩展系统 schema 匹配以覆盖 quoted schema identifier。table allowlist 仍只是纵深防御，不是唯一系统 schema 屏障。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 comment-separated SHOW 和 quoted `mysql`/`performance_schema`/`information_schema` 引用。 | 后续元数据访问变更继续走共享 policy；避免新增分叉且更弱的 SQL 检查。 |
| DRR-2026-013 | 已实现 | 高 | 2026-05-26 | SQL 方言/parser 语义与会执行的形式 | `is_sql_safe()` 曾主要依赖 `sqlparse` 顶层类型，接受会执行的 `EXPLAIN ANALYZE`、SELECT 形状的嵌套写 DML，并在 policy 检查前使用通用注释剥离。MySQL 会执行 `/*! ... */` 内容，且仅把后接空白/控制字符的 `--` 视为注释；optimizer hint 与 MariaDB executable comment 也是服务端 directive，不是普通注释。错误剥离会隐藏或改变服务器实际执行的内容。 | 是 | 把声明的 runtime 契约限于 Oracle MySQL/SQLite 行为。普通注释规范化前拒绝 ANALYZE explain、嵌套写 DML、`/*! ... */`、`/*+ ... */`、`/*M! ... */` 与非空白 `--`；保留普通注释、注释样字符串和非 ANALYZE plan。不得声称全面 SQL 语义分析或独立 MariaDB 方言支持。 | v3.7.0 于 2026-08-20 在 `sql_safety_checker.py` 与共享 MCP policy 实现。测试覆盖 ANALYZE/CTE、executable/optimizer/MariaDB comment、dash-comment 方言差异、被隐藏的 OUTFILE/system-schema、普通注释/字符串和普通 `EXPLAIN`。依据 [MySQL EXPLAIN](https://dev.mysql.com/doc/refman/8.4/en/explain.html)、[MySQL comments](https://dev.mysql.com/doc/refman/8.4/en/comments.html)、[MySQL 双横线规则](https://dev.mysql.com/doc/refman/8.4/en/ansi-diff-comments.html)与 [SQLite EXPLAIN](https://www.sqlite.org/lang_explain.html)。 | 新方言在声明支持前必须评审 EXPLAIN、CTE 与注释语义。保持窄而 fail closed；没有明确语法需求和方言测试时不引入通用 parser。 |
| DRR-2026-014 | 已实现 | 中 | 2026-05-26 | Adapter metadata 语义注入 | 直接调用 SQLite adapter 时，`get_row_estimate("users) --")` 这类 table name 曾可改变 metadata SQL 语义，包括注释掉 bounded sample 的 `LIMIT` 并退化为完整 count。MCP tools 会拒绝这些标识符，但 adapter 方法仍是公共内部边界。 | 是 | 与 DRR-2026-008 相同：adapter metadata 方法现在先校验，并在 SQLite bounded sampling 中引用 identifier。MCP 上游校验仍只是纵深防御，不是唯一防线。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 证明非法 identifier 不会进入 `execute()`，且有效 sampling 使用 quoted SQLite identifier。 | exact-count 路径和未来 metadata helper 继续沿用同一 adapter identifier policy。 |
| DRR-2026-015 | 已实现 | 高 | 2026-05-26 | 错误日志参数暴露 | Adapter `_handle_error()` 曾记录 `str(e)[:200]`。SQLAlchemy 异常字符串可能包含 SQL 文本和 bound parameter values，然后才返回 sanitized client error。这是本地日志暴露，不是客户端响应暴露。 | 是 | 保持客户端错误 sanitized，同时把 adapter 本地异常日志收敛为 exception class，并在 engine 创建处配置 SQLAlchemy `hide_parameters=True`。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 验证 adapter 日志不包含 SQL 文本或参数值。 | Audit payload 和 tool telemetry 继续按各自文档策略处理；adapter 路径不要重新引入 raw exception logging。 |
| DRR-2026-016 | 已实现 | 中 | 2026-05-27 | CI guardrail 声明过强 | README/REFACTORING_LOG 中曾有 annotation consistency regression 会在 CI 中失败的表述，但仓库当前只有 pytest guardrail，没有配套 CI workflow/config。这会让 reviewer 误以为仓库已经有自动化 CI enforcement。 | 文档清理 | 在真正加入 CI 前，把文档改为 pytest/local/default test guardrail，避免安全/流程声明超过实际 enforcement。 | 2026-05-30 已更新 README、README_ZH、MCP_AGENTS_SKILLS_DESIGN、REFACTORING_LOG 和本登记表；未新增 workflow。 | 如果后续新增 CI，再回头更新这些文档并记录 workflow 文件。 |
| DRR-2026-017 | 已实现 | 中 | 2026-05-27 | SQLAlchemy URL 构造 hygiene | MySQL 连接初始化曾用 f-string 拼接包含用户名、密码、host、database 的 URL。凭据中若包含 `@`、`:`、`/` 等特殊字符，可能导致解析错误或难排查的连接失败；该问题也靠近已有参数日志风险。 | 是 | 改用 SQLAlchemy `URL.create` 结构化构造连接 URL，并在创建 engine 时配合 `hide_parameters=True` 和明确 logging name。范围比大 settings 重构更窄。 | 2026-05-28 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 覆盖包含 `@`、`:`、`/` 的凭据构造。 | 未来加入多数据库 registry 时，再评估多 URL builder 和每连接 logging identifier。 |
| DRR-2026-018 | 已实现 | 高 | 2026-05-27 | Skills 目录 containment | Skills 启动时曾对绝对 `SKILLS_DIR` 使用字符串前缀与项目根目录比较。路径字符串以项目根目录开头的 sibling 路径可能通过该检查，而 mutation skills 会在 discovery 阶段通过 `exec_module()` 导入执行。本地可信 repo 内 Skill 执行是预期行为，但 containment check 不应弱于后续 loader 层的路径检查。 | 是 | 在 discovery/import 前，用 `Path.resolve().relative_to()` 替换字符串前缀判断。继续明确 mutation skill code 是可信本地代码，不把 `SKILLS_DIR` 宣称为 sandbox。 | 2026-05-28 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 sibling-prefix 路径拒绝。 | 如果未来再次调整 Skills 路径策略，补 symlink-specific containment 测试。 |
| DRR-2026-019 | 已实现 | 高 | 2026-05-27 | Query skill 安全一致性 | Query skill discovery 曾只用基础 `is_sql_safe()` 预审 SQL 模板，没有应用自由 `query(sql)` 工具的 MCP 扩展检查或 table allowlist。因此 query skills 可在启动时接受 DRR-2026-011 和 DRR-2026-012 中的同类 SQL 形状，而 `execute_query_skill()` 后续又跳过运行时 SQL safety check，依赖 discovery-time trust。 | 是 | 增加共享 read-query policy 函数并注入 query skill discovery；`execute_query_skill()` 在执行前也会重新检查缓存的 SQL 模板。 | 2026-05-28 已在 `mcp_sql_server.py` 和 `skills/_lib/skill_loader.py` 实现；测试覆盖 policy 注入和共享 deny checks。 | 后续新增多数据库 `connection_id` 支持时，保持 raw query 与 query skill 使用同一 validation helper。 |
| DRR-2026-020 | 已实现 | 中 | 2026-05-27 | Skills metadata 与参数 schema 声明 | `validate_params()` 使用小型自定义 schema 语言，而不是 JSON Schema。它已拒绝额外调用参数，但未知 type 曾直接通过，bool coercion 曾把 `"false"` 当真值。v3.7 复核又发现，拼错的嵌套 constraint、标量 `enum`、字符串数值边界和字符串形式的顶层 boolean 可能通过 discovery，随后削弱校验或披露准确性。 | 是 | 保留轻量 DSL，但严格校验已声明 vocabulary 与值。顶层 boolean 必须是 YAML boolean，列表/字符串 metadata 必须符合文档形状。每个参数只接受 `type`、`required`、`min`、`max`、`enum`、`description`；constraint 必须与类型兼容，enum 必须是非空列表，边界必须有序。运行时 bool 仍只解析原生布尔值和显式 `"true"`/`"false"` 字符串。它仍不是完整 JSON Schema。 | 第一阶段 type/bool 加固于 2026-05-29 落地。v3.7.0 在 `skills/_lib/skill_loader.py` 补齐 discovery-time metadata 值和嵌套 constraint 校验；`tests/test_skill_loader.py` 覆盖畸形 metadata、constraint 形状/类型、边界、enum、未知 key 和既有 runtime coercion。 | 未来新增字段、constraint 或参数类型前，必须显式加入 vocabulary 并测试。没有定义 namespace 与兼容规则时，不得静默接受扩展 metadata。 |
| DRR-2026-021 | 已实现 | 中 | 2026-05-27 | Mutation skill 类型完整性 | Mutation discovery 过去只检查模块中有 `Mutation` 属性；frontmatter `name` 也可能与目录身份不一致。由于 `mutation.py` 会在 discovery 阶段通过 `exec_module()` 动态导入执行，畸形的可信本地插件应在运行时 tool 路径缓存或实例化前 fail closed。 | 是 | Discovery 现在要求 frontmatter `name` 必填、符合命名规则，并与 skill 目录名完全一致。Mutation source 必须导出名为 `Mutation` 的 class，且必须是具体的 `MutationBase` 子类。mutation 代码体安全仍依赖人工 review；这不是面向不可信插件的 sandbox。 | 2026-05-29 已在 `skills/_lib/skill_loader.py`、`README.md`、`README_ZH.md`、`MCP_AGENTS_SKILLS_DESIGN.md` 和 `skills/SAFETY.md` 实现；`tests/test_skill_loader.py` 覆盖缺失/不匹配/非法 name，以及缺少、非 class、非 subclass、抽象 `Mutation` 导出。 | 如果未来需要支持不可信第三方插件，应单独设计进程隔离或 sandbox，而不是继续扩展该 loader invariant。 |
| DRR-2026-022 | 已实现 | 高 | 2026-05-27 | Skills audit 完整性声明过强 | `AuditLogger.log()` 仍是 best-effort；审计写入失败以及 token 前的参数/validation 拒绝仍可能没有 JSONL 记录。旧文档/config 曾过度暗示完整记录和 fail-closed audit 行为。 | 是 | 保持 audit 为 best-effort observability，而不是事务控制；正常结果 metadata 报告实际审计状态。v3.6.1 follow-up 让 post-consume 动态 validation 拒绝尝试 execute 失败审计；已提交写入后的响应阶段失败则保留既有 success audit，不追加矛盾的 failure。 | 已在 `skills/_lib/audit.py`、`skills/_lib/mutation_base.py`、`mcp_sql_server.py`、文档和回归中实现。2026-08-10 follow-up 覆盖动态 validation 返回 invalid 或抛 `ToolError`、诚实 `audit_logged`、无写入/replay 行为，以及 post-write response failure 只有一条成功 execute audit。 | 如果合规要求 guaranteed audit，应设计 transactional outbox 或数据库审计机制。不要把 JSONL 文件当成 fail-closed 证据，审计失败也不得弱化 mutation 拒绝。 |
| DRR-2026-023 | 已实现 | 高 | 2026-05-27 | 默认 pytest live database 边界 | `test_mcp_client.py::test_mcp_server` 曾被默认 pytest 收集。只要当前配置的数据库可连接，它会用当前 `.env` 启动 MCP server、list tables、count 第一张表、describe 第一张表、sample rows，并可能执行 query skill。这可能触达 live/类生产数据库，并把 sample data 打印到 pytest captured output 或失败日志中。 | 是 | 将默认收集限定到 `tests/`，保留根目录 MCP smoke 检查为显式脚本，并说明其 live-data 边界。DRR-2026-039 follow-up 还在 pytest 中禁用 `.env`、设置安全 SQLite/process 默认值，并把 MySQL 集成测试改为显式 opt-in。 | 已在 `pytest.ini`、`tests/conftest.py`、`README.md`、`README_ZH.md` 和 `TEST_MCP_CLIENT_GUIDE.md` 实现；默认 pytest 不收集根目录 smoke 脚本，也不能继承开发者 `.env`。 | 后续 live DB smoke 检查继续留在默认收集之外，除非具备显式 opt-in gate 和非敏感输出策略。 |
| DRR-2026-024 | 暂缓 | 中 | 2026-05-27 | 依赖可复现性 | `requirements.txt` 大多是不固定版本或只有下限的依赖，其中 FastMCP 和 SQLAlchemy API 被项目直接使用。没有 lockfile、constraints file 或 CI matrix 时，未来安装可能静默选择行为/兼容性变化的版本，从而削弱“本地/default tests 代表 release 行为”的声明。dry-run 证据也显示，当前冲突面主要来自 optional AutoGen 依赖链，而不是核心 server runtime 路径。 | Packaging/workflow 清理候选，尚未实现。AutoGen 示例不是本程序主线 runtime。 | 后续若修复，优先拆分 runtime/dev/optional AutoGen dependencies，再为实际支持的安装路径增加 constraints 或 documented tested version set。不要把无约束安装描述成可复现 release input。 | 2026-05-27 配置/依赖复审后记录。2026-05-29 验证：当前 `.venv` 的 `pip check` 报告 `autogen-core 0.7.5` 要求 `protobuf~=5.29.3`，但已安装 `protobuf 6.33.5`；干净 requirements dry-run 会解析到 `protobuf 5.29.6`，仅核心 runtime 解析不会引入 `protobuf`。v3.6.1 只增加 `PYTHON_DOTENV_DISABLED` 所需的窄约束 `python-dotenv>=1.2.0`；这不会让更广泛的依赖集合变得可复现。 | 更广泛的问题继续暂缓。不要让 optional AutoGen 示例依赖定义核心 runtime 的可复现性声明，也不要把当前未锁定集合描述为可复现 release input。 |
| DRR-2026-025 | 已实现 | 高 | 2026-05-27 | MySQL mutation timeout 语义 | `MySQLAdapter.execute_write()` 曾使用 `MAX_EXECUTION_TIME`，但 MySQL 文档将该机制描述为偏 SELECT/read-query。受控 MySQL 验证确认了缺口：`timeout=1` 下 `SELECT SLEEP(2)` 约 1.079s 停止，而 `UPDATE ... SLEEP(2)` 仍在约 2.171s 后提交成功。 | 是 | 移除写入路径的 `MAX_EXECUTION_TIME`。MySQL `execute_write()` 现在会在 mutation 前设置 session `innodb_lock_wait_timeout = max(1, timeout_seconds)`，若该防护无法配置则 fail closed。文档已区分只读查询 timeout、InnoDB 行锁等待 timeout、PyMySQL socket timeout 和部署侧 DML 控制。 | 2026-05-29 已在 `db_adapter.py`、`tests/test_db_adapter.py`、README/docs 和 Skills safety 文档中实现。受控证明使用数据库 `trade_data_analysis`：旧写入路径忽略 `timeout=1`；另一个 lock-wait 场景在 `innodb_lock_wait_timeout=2` 下约 3.236s 抛出 OperationalError 1205。 | 剩余边界：这不是覆盖所有 MySQL DML CPU/IO 工作的完整 wall-clock statement timeout。如果生产需要硬性的 mutation 执行上限，仍需把 driver read/write timeout 和部署侧 statement controls 纳入方案。 |
| DRR-2026-026 | 已实现 | 高 | 2026-05-30 | 多连接 policy/execution 串线 | 运行时多数据库支持如果让 policy、identifier quoting/schema helper、adapter execution、metadata、audit 或 telemetry 从不同连接读取，就可能出现“展示/校验针对数据库 A，执行却打到数据库 B”的串线风险。 | 是 | 引入 `ConnectionContext`，并在 policy、schema readiness、方言相关 helper SQL、执行、metadata、audit 和 telemetry 之前解析目标连接。`sample()` 和精确表计数中的内部 helper SQL 直接在选中的 adapter 上执行，不再绕回 legacy 默认执行包装。 | 2026-05-30 已在 `db_adapter.py`、`sql_safety_checker.py` 和 `mcp_sql_server.py` 实现；`tests/test_multi_connection_v35.py` 覆盖同连接 policy/execution 和未知 id fail-closed。 | 后续新增工具继续沿用 resolve-first 模式；任何会 quote identifier 或执行内部 SQL 的 helper 路径都要补回归测试。 |
| DRR-2026-027 | 已实现 | 高 | 2026-05-30 | Skills 展示与执行不一致 | 命名连接和 per-connection allowlist 出现后，Skills discovery 可能把某个 skill 展示为在一个数据库类型/schema 下可执行，但实际执行使用另一 adapter。 | 是 | 让 `list_skills`、`get_skill_detail`、`execute_query_skill` 接受可选 `connection_id`，并在同一个目标连接上评估 DB 兼容性、schema readiness、allowlist、metadata、可选 audit 和 telemetry。`SkillMetadata.databases` 仍是 DB 类型兼容字段，不是 connection-id allowlist。 | 2026-05-30 已在 `mcp_sql_server.py` 实现；`tests/test_multi_connection_v35.py`、`tests/test_skills_disclosure.py` 和文档覆盖目标连接的 availability/execution 一致性。 | 继续把 `available_only` 说明为发现层过滤，不是授权边界；执行期检查仍必须保留。 |
| DRR-2026-028 | 已实现 | 中 | 2026-05-30 | Adapter registry 生命周期与资源边界 | 多个命名连接意味着多个长期存在的 SQLAlchemy Engine。如果 registry/reset/lifecycle 不清楚，会泄漏资源，也会让需要切换环境的测试更复杂。 | 是 | 新增按配置化 `connection_id` 懒加载的进程内 adapter cache，并提供 `reset_adapter(connection_id=None)` 关闭单个或全部 adapter，用于测试/重配置。连接定义仍由服务器端配置并在 import 时解析，不引入动态 per-request DSN。 | 2026-05-30 已在 `db_adapter.py` 实现；`tests/test_db_adapter.py` 和 `tests/test_multi_connection_v35.py` 覆盖 registry 行为。 | 暂缓 LRU/上限/凭据刷新。若部署配置大量连接或需要运行时配置 reload，再重新设计。 |
| DRR-2026-029 | 已实现 | 中 | 2026-05-30 | 日志和元数据中的连接身份 | 运维需要知道一次 tool call 打到了哪个配置化连接，但如果在 `ToolResult.meta`、telemetry、audit 或结构化 payload 展示字段中暴露连接内部信息，会泄漏敏感 DB 细节。 | 是 | 在结果 metadata、可选 telemetry 和 Skills audit 中加入安全别名 `connection_id` 与实际 `db_type`；`list_connections()` 只返回别名和 policy 摘要。公开 SQLite `database_name` 展示字段使用 `sqlite:<connection_id>`，不暴露文件路径。仍排除 DSN、host、用户名、密码、SQLite 路径、SQL params 和返回行。 | 2026-05-30 已在 `mcp_sql_server.py`、`skills/_lib/audit.py`、`skills/_lib/mutation_base.py`、文档和测试中实现；follow-up 测试覆盖 `check_connection()` / `list_tables()` 不暴露 SQLite 路径。 | 新增 metadata/audit/payload 字段时重新审查；未经隐私评审不要加入连接内部信息。 |
| DRR-2026-030 | 已实现 | 高 | 2026-05-30 | 多连接 mutation 写入 | 允许 mutation Skills 选择任意配置化连接，需要 per-connection 写权限、preview/execute 目标绑定、audit 语义，以及针对 SQLite 文件锁和 MySQL 写超时的更强运维说明。 | 是 | 要求全局 mutation 目标 allowlist、per-connection 写开关、per-connection Skill allowlist，以及绑定 skill/version/params/connection/DB type/expiry 的 HMAC preview token。未配置全局路由策略时保持仅默认连接。 | 已在 `db_adapter.py` 和 `mcp_sql_server.py` 实现；discovery 与 execution 共享 policy 检查。`tests/test_mutation_multi_connection_v36_design.py` 覆盖路由、token 绑定、目标隔离、拒绝层、精确过期边界、篡改、Skill version 变化、重启行为和完整 token 不暴露；adapter 测试覆盖配置解析与 legacy 隔离。 | Replay 与 preview-state hardening 已在 DRR-2026-034 实现。每个授权写目标仍需持续说明 SQLite lock 和 MySQL DML timeout 边界。 |
| DRR-2026-031 | 已实现 | 高 | 2026-05-30 | Quoted identifier allowlist 绕过 | MCP table extractor 曾没有一致处理常见 quoted identifiers。`FROM "forbidden"`、`FROM [forbidden]` 或 `FROM main."forbidden"` 这类形式可能绕过或误导 table allowlist 比较，即使实际引用的是不允许访问的表。 | 是 | 在和目标连接 allowlist 比较前，规范化反引号、双引号、方括号和 schema-qualified 引用。保持为聚焦的 extractor 加固，不引入完整 SQL parser。 | 2026-05-30 已在 `mcp_sql_server.py` 实现；`tests/test_sql_policy.py` 覆盖 quoted/schema-qualified deny case 和允许的 quoted 表。 | 后续 table-reference 解析继续走共享 policy 路径；扩展语法支持前先补方言示例测试。 |
| DRR-2026-032 | 已实现 | 中 | 2026-05-30 | Legacy named-env 泄漏 | 本地多连接 `.env` 中的 `DB_DEFAULT_*` 和 `DEFAULT_DB_CONNECTION` 可能在 `DB_CONNECTIONS` 未设置或为空时影响 legacy 单连接模式，破坏向后兼容，或因为 named default 不存在导致 legacy 启动失败。 | 是 | 将 `DB_CONNECTIONS` 作为命名连接唯一 feature gate。legacy 模式忽略 `DB_<ID>_*` 和 `DEFAULT_DB_CONNECTION`；`DB_TYPE` / `SQLITE_DATABASE_PATH` 继续作为权威配置。 | 2026-05-30 已在 `db_adapter.py`、`.env.example`、README/docs 和测试中实现；`tests/test_db_adapter.py` 覆盖 legacy 模式忽略 `DB_DEFAULT_*` 和默认连接选择。 | 后续新增 per-connection setting 时保留该 gate；未经显式迁移决策，不让 named 变量影响 legacy 模式。 |
| DRR-2026-033 | 已实现 | 中 | 2026-05-30 | 兼容 helper 解析顺序 | 独立 helper `sql_safety_checker.execute_sql(..., connection_id=...)` 曾可能先做 SQL safety，再解析目标连接。未知 id 应先 fail closed，再考虑任何目标相关 policy 或执行路径。 | 是 | 在 `is_sql_safe()` 和 adapter execution 前先用 `get_connection_config()` 解析 `connection_id`，保持和 MCP 工具的 resolve-first 不变量一致。 | 2026-05-30 已在 `sql_safety_checker.py` 实现；`tests/test_multi_connection_v35.py` 覆盖未知 `connection_id` 会先返回连接错误而不是 SQL policy 错误。 | 后续扩展 connection-aware policy 时，保持兼容 helper 与 MCP tool 顺序一致。 |
| DRR-2026-034 | 已实现 | 高 | 2026-05-30 | Preview-token replay 与审阅状态漂移 | 有效 HMAC token 曾可在过期前 replay；内置 mutation 还会在 execute 时重新读取当前状态，而不是锁定 preview 展示的状态。单靠乐观锁不是通用 replay 或“所见即所写”边界。 | 是 | 增加随机 `jti` 和有界 execution-state hash；在加锁的有界进程内 memory store 中登记 digest/expiry/canonical binding，并在动态 validation/write 前消费。后续失败仍保持 terminal consumption，绝不回退到 stateless HMAC。 | 已在 `mcp_sql_server.py`、`preview_token_store.py`、`MutationBase` 和 `update-order-status` 实现。测试覆盖唯一签发、顺序 replay、两个并发完整工具调用只能产生一次写入、有界容量、懒过期、重启失效、静态拒绝不消费、terminal 失败、状态漂移和无绑定执行拒绝。 | Preview 与 execute 必须进入同一进程。推荐客户端自有 stdio。条件性 HTTP mutation 仅限受信任私有边界中的单进程；多用户认证 HTTP 不属于 v3.6.1。重启或跨进程请求会使 token 失效。禁止 stateless fallback。 |
| DRR-2026-035 | 已实现 | 低 | 2026-08-04 | 示例数据库 fixture 漂移已解决 | Mutation live smoke 曾让被跟踪的示例数据库看起来包含未提交的状态变化；当前已经不存在该工作树漂移。 | 是 | 让 `sample_data/demo.db` 保持 tracked baseline；任何会执行写入的测试都使用一次性数据库。 | 2026-08-10 复核：`git diff -- sample_data/demo.db` 为空，`HEAD` 和工作区中的订单 `id=4` 都是 `confirmed`。 | 后续 live write 检查不得把 tracked sample database 当作 mutation fixture；应创建临时副本或临时数据库。 |
| DRR-2026-036 | 已实现 | 中 | 2026-08-04 | Server instructions 曾错误声称全局只读 | FastMCP server 级 `instructions` 曾写成 “Database query assistant with READ-ONLY access”，但可选 Mutation Skill 能执行受控写入；模型可见能力说明与实际界面不一致。 | 是 | 简洁说明只读核心 SQL 工具、配置化连接路由、可选 Skills，以及由 preview 和一次性 token 保护的受控 mutation。 | 2026-08-10 已在 `mcp_sql_server.py` 实现。回归测试断言 instructions 不再声称全局只读，并明确提到受控 mutation 和一次性 token。 | 后续工具面变化时同步 instructions；不得暗示 `confirm=true` 能证明人类批准。 |
| DRR-2026-037 | 已实现 | 中 | 2026-08-04 | Mutation 双执行路径 | `MutationBase` 要求实现具体的 `execute()`，因此 `update-order-status` 曾同时保留 `execute()` 和 `execute_with_binding()`；公开的 `execute()` 会重新读状态并在没有 preview binding 时写入，若在 MCP 外调用会重新引入 DRR-2026-034 的 TOCTOU。 | 是 | 保留满足抽象接口的 `execute()`，但让它直接抛出 `ToolError`。唯一权威写路径为 `_execute_with_expected_status()`，只能通过携带服务端 preview state 的 `execute_with_binding()` 到达。 | 2026-08-06 已在 `skills/update-order-status/mutation.py` 实现；`test_update_order_status_rejects_direct_unbound_execute` 验证直调失败且数据不变。 | 只有一个 binding-only Skill 时保留 ABC，使畸形 Skill 继续在 discovery 阶段失败。若多个 binding-only Skills 证明需要重构，移除 abstract method 前必须增加 loader invariant，要求至少覆写 `execute()` 或 `execute_with_binding()` 之一。 |
| DRR-2026-038 | 已实现 | 中 | 2026-08-04 | Preview 绑定来源与预览失败仍签发 token | `update-order-status` 的 binding 曾来自 validation 第一次读取，而展示内容来自 preview 的第二次读取；两次读取之间的变化会导致展示与绑定不一致，第二次读取失败时仍可能报告成功并签发 token。 | 是 | Preview 返回自身读取的 `current_status`，binding 只从该字段构建。任何包含 `error`、声明 `success=false`，或提供非布尔/非 true `success` 值的 preview 都失败、不签发 token。 | 已在 `mcp_sql_server.py` 和 `skills/update-order-status/mutation.py` 实现。回归覆盖状态插入变化、非空/空/null `error`、布尔 false 与 malformed non-true success 值；所有失败 preview 后 store 都为空。 | 自定义 mutation Skill 成功时应省略 `success` 或把它设为布尔 true；失败时应返回 `error`、返回布尔 `success=false` 或抛出 `ToolError`。只有 Skills 增多且字典契约难以维护时才引入 typed result。 |
| DRR-2026-039 | 已实现 | 高 | 2026-08-04 | 默认 pytest 环境隔离缺口 | `tests/conftest.py` 此前只清空两个路由变量，而 `db_adapter.py` 会加载开发者 `.env`。legacy 数据库凭据、读 policy、Skills 和 telemetry 配置因此可能改变默认测试；可选 MySQL fixture 甚至可能连接 live database。 | 是 | 在应用导入前设置 `PYTHON_DOTENV_DISABLED=1`，为默认 pytest 建立明确的安全 SQLite/config 基线；除非显式请求 live integration，否则清空 legacy MySQL 凭据，并要求 `RUN_MYSQL_INTEGRATION_TESTS=1` 后 MySQL fixture 才能连接。 | 2026-08-10 已在 `tests/conftest.py` 实现；README/testing guidance 明确 `.env` 会被忽略，live MySQL 需要 shell 显式 opt-in 与导出的凭据。完整 pytest 仍以三个 MySQL integration skip 通过。 | 默认 pytest 必须继续禁用 `.env`。未来任何 live service/database fixture 都必须有自己的显式 opt-in gate，且不得意外进入默认收集。 |
| DRR-2026-040 | 已实现 | 低 | 2026-08-04 | 不可达的配置 helper | `mcp_sql_server.py` 中的 `_parse_table_allowlist()` 从未调用；实时 allowlist 解析已经归属 `db_adapter.py`，保留两条路径会诱导后续改错函数。 | 是 | 删除死 helper 及其分歧日志，使 allowlist 解析只有一个归属；补上 `pytest.ini` 文件末尾换行。 | 2026-08-10 已实现。运行时 `ALLOWED_TABLES` 继续来自已解析的连接 policy。 | 保持 allowlist 解析集中在 `db_adapter.py`。 |
| DRR-2026-041 | 已实现 | 中 | 2026-08-04 | Mutation 回归断言偏弱 | Secret 轮换测试曾在轮换/断言前结束，一处脱敏断言恒真，也没有端到端覆盖 `adapter.execute_write()` 抛错后的 terminal token 消费。这些弱点降低了 replay 边界的可信度。 | 仅测试加固 | 使用不同 secret 完成 reload 并断言拒绝且无写入；用直接 non-disclosure 断言替换恒真式；注入数据库写失败并断言旧 token 无法复用。 | 已在 `tests/test_mutation_multi_connection_v36_design.py` 与 `tests/test_mutation_skills.py` 实现。证据包括 secret 轮换、non-disclosure、数据库失败后的 terminal consumption、store 原子消费，以及两个并发完整 execute 工具调用只产生一次数据库写入。 | 后续 preview-token store 或执行路径变更必须保留这些回归作为证据。 |
| DRR-2026-042 | 已实现 | 低 | 2026-08-04 | v3.6 之后遗留的 v3.5 时期措辞 | 多份文档在 v3.6 已引入命名写 policy 后，仍把 v3.5 的仅默认连接妥协描述为当前状态。 | 是 | 为 default-only 行为补上“省略 `SKILLS_ALLOW_MUTATION_CONNECTIONS` 时”的限定，并分开记录 v3.5→v3.6 与 v3.6→v3.6.1。 | 2026-08-10 已在客户端指南、README、Skills 指南、Agent 指南、设计文档和发布说明中完成；最后一处无条件 “limited to the default connection in v3.5” 已修正。 | 后续维护版本继续把基线能力与补丁修复分开记录。 |
| DRR-2026-043 | 已接受 | 中 | 2026-08-04 | 读 allowlist fail-open 与写 allowlist fail-closed 不对称 | `DB_<ID>_ALLOWED_TABLES` 为空或省略表示所有可见表都可读，而 `DB_<ID>_MUTATION_SKILLS` 为空或省略表示拒绝所有写入。两个默认值有意不同。 | 仅文档声明 | 保留读侧兼容默认值和写侧 deny-by-default；集中说明不对称并建议生产环境配置具体读表 allowlist。 | 2026-08-10 已在中英文 env example 与 README 配置/安全说明中记录；行为本身仍是已接受的兼容取舍。 | 保持警告靠近两类 policy 示例；仅在破坏性版本中重新考虑读侧默认值。 |
| DRR-2026-044 | 已接受 | 低 | 2026-08-04 | Preview-token store 容量自我拒绝 | `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES` 限制每进程未过期 token，容量满时 fail closed。反复 preview 不 execute 会在过期前填满 store；惰性清理会在锁内扫描有界字典。 | 部分加固 | 保留 fail-closed 容量和惰性清理；把 TTL 限制为 `1-86400` 秒、容量限制为 `1-100000`；无效值分别回退到 `300` 和 `10000`。没有实测负载前不增加 heap/后台清理服务。 | 默认 TTL 300、容量 10000 不变；测试覆盖不驱逐、过期释放和两类配置上限。容量上限只是防误配置护栏，不是经验证的吞吐声明；仍无 per-client 限流。 | v3.6.1 不支持不可信或多用户 HTTP mutation。只有明确远程/高吞吐需求时才重新评估 quota、限流和索引化 expiry。 |
| DRR-2026-045 | 已实现 | 中 | 2026-08-08 | 共享 token backend 与实际部署范围 | 共享 backend 能协调 worker/副本，但生产级远程服务还需要认证、传输安全、可观测性、副本配置一致性和数据库治理；只增加 token store 会夸大部署成熟度。 | 是 | 保留有界进程内 store，并推荐客户端自有 stdio。条件性 HTTP mutation 仅限受信任私有边界中的单进程；多用户认证 HTTP 和共享 mutation 副本不属于 v3.6.1。读扩展只能使用独立 read-only endpoint/profile/pool。 | 已实现：活动文档说明同进程边界、连续性损失、程序不强制 worker 数，以及当前没有多用户 HTTP 安全设计。 | 只有出现明确远程 mutation 需求时，才连同完整部署 profile 重新设计共享状态。禁止 stateless HMAC-only 校验。 |
| DRR-2026-046 | 已接受 | 低 | 2026-08-10 | 仅比较 status 的乐观锁与 ABA 变化 | `update-order-status` 和 v3.7 `reset-demo-order-to-pending` 示例都会绑定并比较展示的 `status`。外部写入者或 demo reset 自身可在另一个 token 有效期内形成 `pending -> X -> pending`，导致 execute 时 status 相同而中间变化未被发现。 | 不新增通用 schema | reset 明确仅供 demo/test，且调用方必须声明准确的非 pending 来源状态。加入 revision/`updated_at` 条件需要真实业务 schema 契约和 migration；在 portable framework demo 中虚构一列属于过度设计。建议使用专用 fixture、不为同一订单保留重叠 preview，并为每个 live-test 场景启动新的 stdio 进程。 | 接受为有界的 demo/外部写入者局限。只要 execute 时状态与 preview 展示值不同，现有保护仍会拒绝；但仅绑定 status 无法发现已经循环回原值的变化。 | 真实目标表提供稳定 revision/version，或生产流程可恢复旧状态时，再把版本字段加入 binding 与 `WHERE`。不得把 demo reset 作为生产订单重开 API，也不要在框架中虚构通用 timestamp 契约。 |
| DRR-2026-047 | 已实现 | 低 | 2026-08-10 | 不可达的命名 SQLite 路径别名 | 命名 SQLite 分支含有未文档化 `DB_<ID>_DATABASE_PATH` fallback，但前面的 canonical `DB_<ID>_SQLITE_DATABASE_PATH` lookup 总会提供字符串默认值，因此 `None` guard 与别名读取不可达。把它转为支持配置只会新增重复配置面和优先级规则，没有兼容收益。 | 是 | 删除死 fallback。继续把 `DB_<ID>_SQLITE_DATABASE_PATH` 作为唯一命名 SQLite 路径配置；不为不可达别名补文档、激活逻辑或测试 fixture 清理。 | 2026-08-10 已在 `db_adapter.py` 实现。现有命名 SQLite 与 legacy 隔离测试通过，运行时行为不变。 | 保持命名连接配置显式且唯一。若测试环境 suffix 漂移成为真实问题，应隔离项目自有 `DB_*` 命名空间，而不是让死别名转正。 |
| DRR-2026-048 | 已接受 | 低 | 2026-08-13 | Preview-token 交付与消费记账边缘 | Preview 成功后会先登记 token，再执行 best-effort audit、`ctx.info()` 和 `ToolResult` 构造。若服务器能观察到的异常发生在登记之后、结果返回之前，客户端拿不到可用 token，但对应 record 会占用一个有界 store 槽位直到过期/惰性清理；audit 可能已经记录 preview success，通用 adapter sanitizer 还可能把响应或日志失败误报为数据库查询失败。由于执行仍要求未交付的高熵 token，这不会允许 mutation 或 replay。另一个相关维护边缘是：`consume()` 会先移除 record，再由 helper 校验服务器生成的 binding hash/JSON；若未来重构破坏内部不变量，token 可能已经消费，但调用方尚未设置 `token_consumed=True`。当前唯一签发路径使用同一份 canonical 数据，因此该分支不可达。 | 当前不修改代码 | 保持当前 fail-closed、短 TTL、有界容量和同进程原子消费。不得声称 token 交付具有原子性：函数返回后的网络失败天然存在交付不确定性。若出现运维证据或后续正好修改生命周期，可增加锁内、按 digest 精确删除的 `discard()` 处理服务器可观察到的返回前失败，区分响应处理错误与数据库错误，并补回归测试。只有 binding/storage 路径重构或引入共享/持久化 backend 时，才重新设计消费结果的状态传递。 | v3.6.1 接受该低影响的交付/记账局限。它不会引入未授权写入、replay 或乐观锁绕过；可能残留的 record 受 store 容量与 token 过期时间共同约束。pop 后的内部检查目前只比较和解析同一 canonical 服务端签发路径产生的数据。 | 若实际观察到 preview 响应失败、HTTP transport 成为主要部署方式，或 token storage/serialization 出现第二个 producer，则重新评估。任何清理都只能是 best-effort，不得暗示服务器能判断交给传输层后丢失的响应是否已被客户端收到。 |
| DRR-2026-049 | 已实现 | 中 | 2026-08-19 | 可选 Skill 连接范围与授权/路由歧义 | 可复用 Skill 需要表达预期连接；复用 `databases`、接受自动路由 metadata、把 metadata 当权限，或静默忽略范围字段拼写错误，都可能打错数据库或取消预期限制。多值还需定义别名缺失/DB 不兼容行为。 | 是 | 新增严格限制性的复数 `connection_ids`。省略保持旧行为；运行时省略仍用全局默认。拒绝未知 frontmatter 字段和重复 YAML key，使安全相关 typo 在 discovery fail closed。adapter 前校验 scope/type，其余 policy 在查询执行或写入前继续生效；冲突按目标拒绝，其它有效成员可复用。 | 已在 loader/server 实现；测试覆盖语法、未知/重复字段、grammar 对齐、规范化、不自动路由、policy 交集、目标隔离和 token 前拒绝。真实 fixture 独立覆盖有效、未配置与 DB 冲突 alias。 | Metadata 只收窄；直接 Python 调用绕过 MCP 路由。严格未知字段意味着自定义 metadata 以后需要显式扩展 namespace。建议语义别名；只有具体全成员需求才重审全局禁用。 |
| DRR-2026-050 | 已接受 | 中 | 2026-08-19 | 人工批准 host 不是服务端可验证的人类授权 | preview token 能证明匹配 preview 并阻止 replay，但客户端可自动回传。console host 增加批准体验，服务端仍不认证批准人，其他客户端可绕过，deny 不上报，外部 payload 日志也可能泄漏 token。 | 实现示例并明确局限 | 在同一 stdio Client/server 中运行；规范化有限 JSON 参数，拒绝 provider 修改批准视图，由 workflow 强制截止时间，固定 preview 目标，不重试不确定执行。完整环境继承避免可信本地 host 静默换用另一 `.env`，但也把全部导出 secret/control variable 纳入子进程信任边界。没有产品需求时不增加 Elicitation/HTTP auth/cancel/持久服务。 | 测试覆盖各决定状态、迟到批准、畸形/过期 preview、请求快照、批准视图修改拒绝、目标固定、环境传递、token 脱敏和不重试。文档明确它不是身份/合规证明，并说明 params/preview/execute 输出可能敏感。 | deny token 占容量至 TTL；Python 不能保证内存擦除；恶意 provider 需进程隔离。产品化 host 应选择性转发项目配置。若要求身份、职责分离、持久 deny 或远程多用户 mutation，应设计认证批准/审计服务。 |
| DRR-2026-051 | 已实现 | 高 | 2026-08-20 | Raw read grammar 与 table allowlist 完整性 | regex 时代的表提取器会漏掉 comma join 或 comment-separated 表、丢弃 schema qualifier，并把 EXPLAIN 关键字误当表。过宽 SHOW、跨 session EXPLAIN 和允许多条 statement 也使 metadata/system scope 校验不完整，并让行为依赖未来 driver。 | 是 | 保持 raw query/Query Skill 共用一个保守 policy。只接受单条 statement；规范化普通注释但不剥离 executable directive；拒绝 raw SHOW 与跨 session EXPLAIN/DESCRIBE；把 `sys` 纳入 system schema；保留 qualifier；限制性 allowlist 下无法完整提取 table scope 时 fail closed。非 ANALYZE 的 EXPLAIN-family DML 仍有用途，但其写 target 与全部 read/USING source 都必须在 scope 内。不得声称完整跨方言 parser。 | v3.7.0 已在 `mcp_sql_server.py`/`sql_safety_checker.py` 实现；`tests/test_sql_policy.py` 覆盖 comma join、comment separator、qualified name、nested/CTE table、EXPLAIN 误报/跨 session 形式、EXPLAIN/DESCRIBE/DESC `UPDATE`/`INSERT`/`REPLACE`/`DELETE` target、CTE alias、multi-table `DELETE ... USING` source、SHOW 变体、无字符串字面量误报的 system schema、ambiguous target 与多 statement。Query Skill 依据 DRR-2026-019 复用相同 runtime helper。低层 `is_sql_safe()` 为兼容仍识别 SHOW，但完整 MCP policy 从不执行。 | 只有出现具体受支持方言需求并补正反测试时才扩展 grammar。schema discovery 使用 `list_tables`/`describe_table`，数据库 grant 继续作为权威边界。 |
| DRR-2026-052 | 运维决策 | 高 | 2026-08-20 | SELECT 形状的副作用与数据库授权 | Statement-shape gate 无法证明所有外层 `SELECT` 没有副作用。MySQL stored function 可能修改数据或以 definer 权限运行，`GET_LOCK()` 会创建 session state，metadata 可见性也取决于权限。命名连接还可能复用比 raw-query 角色更宽的凭据。 | 部署指导，不做函数 denylist | 把 SQL checker 与 `ALLOWED_TABLES` 定位为应用层 guard。生产只读 alias 只授予对象级 `SELECT`，撤销不需要的 `EXECUTE`、`FILE`、`PROCESS`、管理与跨 schema 权限；可行时分离读写凭据。不断扩大的函数 denylist 很脆弱，不能替代 grant。 | v3.7 已在 README、env example、Skills 安全指南、release/guide 与本登记表记录。代码继续执行保守 shape/table policy，但不声称语义证明。 | 若 mutation alias 必须使用更宽凭据，可在未来由真实需求驱动的版本考虑禁止该 alias 的 raw query。把 stored routine 与账号 grant 作为部署工件评审。 |
| DRR-2026-053 | 已接受 | 中 | 2026-08-20 | 跨数据库 demo reset 的行唯一性 | MySQL/SQLite reset 使用按 `orders.id` 和 status 匹配的可移植乐观锁 UPDATE。若数据库没有强制 id 唯一，畸形 schema 或并发插入可能匹配多行；应用层预读无法跨两种方言提供原子唯一性保证。 | Schema 契约加诊断 guard | 要求 `orders.id` 是 `PRIMARY KEY` 或 `UNIQUE`，与内置 demo schema 和一般关系数据库设计一致。保留可移植的 read-side 精确基数检查，在 preview 前拒绝已经损坏的 fixture；但不声称它替代 constraint，也不为 demo Skill 增加方言分支或 framework transaction API。 | Skill 会验证只读到一行、要求显式 expected source state，并采用与 `update-order-status` 相同的可移植乐观锁形状。单元回归覆盖重复行诊断拒绝；受支持执行依赖数据库唯一约束。 | 真实目标无法实施唯一约束时不得启用该 Skill。只有出现确切的跨方言 mutation，需要应用层实施多语句不变量时，才增加 adapter transaction primitive。 |

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
