# 设计风险登记表

[English](DESIGN_RISK_REGISTER.md) | 中文

创建日期：2026-05-24  
最近评审：2026-05-26  
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
| [Google Gemini Function Calling 文档](https://ai.google.dev/gemini-api/docs/function-calling) | 使用清晰的函数/参数描述、强类型/枚举、相关且有限的工具集、稳健错误处理，并避免通过函数调用暴露敏感数据。 |
| [Microsoft Azure OpenAI Structured Outputs 文档](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs) | 严格 schema 很有用但受约束；任意 SQL 行结构不适合强行声明严格输出 schema。 |
| [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | 不应直接记录 secret、access token、密码、连接串或敏感个人数据；日志需要访问控制、保留/轮转策略和磁盘耗尽防护。 |

## 当前快照

项目当前没有实现通用 SQL 分页工具或 cursor-token 机制，也没有实现进程内遥测百分位聚合、模型可见 stats 工具/资源、session schema cache 或 `db://schema` resource。

v3.4.3 的运行时修复已让 SQLite 行数估算保持有界：当没有 `sqlite_stat1` 且 10,000 行采样达到上限时，`SQLiteAdapter.get_row_estimate()` 返回该上限作为下界估算，而不是继续执行完整 `COUNT(*)`。精确计数仍需通过用户 SQL 或 `get_table_summary(exact_count=True)` 显式触发。

## 登记表

| ID | 状态 | 领域 | 风险或关注点 | 是否计划修改 | 修改逻辑 | 当前结果 | 下一步 |
|---|---|---|---|---|---|---|---|
| V343-001 | 已实现 | SQLite 行数估算 | 元数据发现此前会从 10,000 行采样升级为大表完整 `COUNT(*)`。 | 是 | 优先使用 `sqlite_stat1`；采样达到上限时返回下界估算；精确计数保持显式触发。 | 2026-05-24 已完成：修改 `db_adapter.py`，在 `tests/test_db_adapter.py` 增加测试，并更新文档。 | 观察用户是否误解下界估算；需要精确值时建议运行 `ANALYZE` 或显式计数。 |
| V343-002 | 已实现 | 查询结果截断 | `query()` 和 `execute_query_skill()` 在截断返回 payload 前仍会获取完整 adapter 结果。 | v3.4.3 仅改文档 | 澄清截断只限制返回 payload；用户应使用 `WHERE`/`LIMIT`/`ORDER BY` 限制数据库工作量并稳定顺序。 | 工具消息和文档已更新；adapter 级流式/分批获取仍暂缓。 | 只有在兼容性测试充分时再评估 `fetchmany()` 或 streaming。 |
| V343-003 | 已实现 | 工具描述 | `list_tables()` 和 `get_full_schema()` 的 all/complete 表述会忽略 allowlist 和截断。 | 是 | 改为 visible/truncated 语义，并澄清 returned/visible counts。 | 面向工具和文档的描述已更新。 | 后续新增工具描述继续保持精确和保守。 |
| V343-004 | 已实现 | 安全文档措辞 | 部分文档过度声明 comprehensive SQL analysis 或所有调用都经 `validate_name()`/`validate_params()`。 | 是 | 将 sqlparse 描述为语句类型 allowlist 加 MCP 层扩展检查；区分 Skills 参数校验和基础 SQL/table 校验。 | README 和设计文档已更新。 | 不在缺少对应 enforcement 的情况下扩展安全声明。 |
| V343-005 | 已实现 | Prompt 指南 | `get_table_summary()` 曾被当成默认规划步骤，但该工具默认禁用，精确计数也是显式 opt-in。 | 是 | 默认优先 `describe_table()` 估算；只有需要精确计数时才使用显式 `COUNT(*)` 或 `get_table_summary(exact_count=True)`。 | Prompt guide 已更新；无需运行时测试。 | Prompt 示例要和默认启用工具保持一致。 |
| V343-006 | 需要策略决策 | 原始 SQL echo/log 可见性 | `query(sql)` 会把完整 SQL 记录到上下文并返回在结构化 payload 中；SQL literal 可能包含敏感值。 | 未定 | 选项：保留 echo 以便透明审计；加强文档警告；或新增 `ECHO_SQL_IN_RESULTS=0` 之类的可选控制。 | 待定。 | 修改 payload 前先决定兼容性/隐私策略。 |
| V343-007 | 需要策略决策 | Skills audit 参数日志 | Audit 仅截断长参数，不按 key/value 脱敏。 | 未定 | 可考虑敏感 key 模式、每个 skill 的脱敏元数据，或明确禁止 skill params 携带 secret。 | 待定。 | 先定义 audit 脱敏策略，再改运行时行为。 |
| V343-008 | 运维决策 | Append-only JSONL 日志 | Audit 和 telemetry 日志是本地 append-only 文件，没有内置轮转或保留策略。 | v3.4.3 不作为服务器逻辑 | 优先使用外部日志轮转/保留策略；部署需求明确前不加入进程内日志管理。 | 待补运维说明。 | 为生产部署记录推荐的轮转/保留方式。 |
| V343-009 | 已接受 | `ToolResult.meta` 可见性 | `_meta` 包含运行期统计，某些客户端可能展示。 | 不改行为 | 保持 metadata 非敏感；不加入 SQL、params、rows、凭据或用户身份。 | 接受当前取舍。 | 新增 meta 字段时重新审查。 |
| V343-010 | 暂缓 | 基础工具 output schema | 任意 SQL 行结构不适合统一声明严格 schema，容易误导。 | 不做 blanket 修改 | 只给稳定 envelope 的工具考虑 schema。 | 有意暂缓。 | 如有需要，逐个稳定工具评估。 |
| V343-011 | 不计划 | 通用 SQL 分页参数 | 对任意 SQL 添加 `limit`、`offset`、`page` 或 cursor token 会重复 SQL 语义，且无稳定排序时结果不可靠。 | 否 | 分页留给用户 SQL；如需封装，使用有明确排序键的领域 skill。 | 未实现。 | 未经新设计评审，不添加通用 `query(limit, offset)`。 |
| V343-012 | 暂缓 | 遥测 stats 工具 | 进程内 p50/p95 聚合或模型可见 stats 工具可能暴露操作模式，并需要有界状态设计。 | v3.4.3 之后继续暂缓 | 保持 opt-in JSONL；聚合交给外部日志处理。 | 有意暂缓。 | 只有出现有界且非模型可见的设计时再评估。 |
| V343-013 | 暂缓 | Session schema cache | Schema cache 在 DDL 后可能过期，并影响安全/可执行性判断。 | v3.4.3 之后继续暂缓 | 继续以执行时检查为准。 | 有意暂缓。 | 只有存在明确失效策略时再评估。 |
| V343-014 | 暂缓 | `db://schema` resource | Schema resource 会增加第二条 schema 访问路径，也会扩大模型可见上下文界面。 | v3.4.3 之后继续暂缓 | 继续使用显式 `get_full_schema()`。 | 有意暂缓。 | 只有客户端 resource 支持成为明确需求时再评估。 |

## 初始 v3.4.3 评审批次状态

1. V343-001 是本组唯一运行时行为修改，已实现。
2. V343-002 仅作为措辞/消息清理实现；adapter 级查询 streaming 暂缓。
3. V343-003 至 V343-005 作为文档和工具描述清理实现。
4. V343-006 至 V343-008 仍是策略或运维决策。

## 当前明确不做的事项

- 面向任意 SQL 的通用 `query(limit, offset)` 或 cursor-token 分页。
- 进程内 p50/p95 聚合或模型可见 stats 工具/资源。
- 对所有基础工具统一添加严格 output schema。
- 没有失效策略的 session schema cache。
- 在出现明确客户端需求前新增 `db://schema` resource。

## 更新流程

当某个条目被实现、拒绝或重新定范围时：

1. 更新 `状态`、`是否计划修改`、`修改逻辑`、`当前结果` 和 `最近评审`。
2. 行为修改必须补充或更新测试，并在条目中记录测试文件。
3. 纯文档修改要记录修改过的文档，以及为什么不需要运行时测试。
4. 策略条目在修改运行时行为前，先记录兼容性/安全取舍。
5. 除非条目创建有误，不要删除历史条目；将旧条目标记为已接受、暂缓或不计划。

## 评审清单

- 是否新增了模型可见 tool、resource、prompt、schema 或 meta 字段？
- 是否记录了 SQL、params、rows、用户标识、凭据或操作模式？
- 是否引入可能无界增长或过期的进程内/session 状态？
- 是否让昂贵数据库操作看起来像轻量元数据？
- 是否声明了代码无法保证的校验、完整性、精确性或排序？
- 测试是否覆盖了预期路径和被拒绝的失败模式？
