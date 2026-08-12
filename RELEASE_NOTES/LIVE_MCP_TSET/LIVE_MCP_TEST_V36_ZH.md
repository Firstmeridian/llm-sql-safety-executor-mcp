# v3.6 MySQL + SQLite MCP 协议联调记录

**日期：** 2026-07-31  
**文档边界更新：** 2026-08-10
**结果：** 通过  
**范围：** 配置解析、MCP stdio 协议、命名连接、严格 mutation policy、一次性
preview token、MySQL/SQLite 写路径和 replay 拒绝。

本文记录的协议联调只验证 stdio；2026-08-10 补充的 v3.6.1 HTTP 文字是部署
边界说明，不表示已经完成 HTTP transport 或多用户认证联调。

**阅读顺序：** 正文优先呈现当前配置和当前完整测试结论；早期隔离 fixture
协议 smoke 保留在文末“附录 A：历史协议基线”，用于审计和回溯，不作为当前配置
的主要结论。

## 1. 配置状态

当前本地 `.env` 已启用 v3.6 命名连接和严格 mutation policy：

```env
DB_CONNECTIONS=mysql,analytics
DEFAULT_DB_CONNECTION=mysql
SKILLS_ALLOW_MUTATION_CONNECTIONS=mysql,analytics
DB_MYSQL_ALLOW_MUTATIONS=1
DB_MYSQL_MUTATION_SKILLS=update-order-status
DB_ANALYTICS_ALLOW_MUTATIONS=1
DB_ANALYTICS_MUTATION_SKILLS=update-order-status
MUTATION_PREVIEW_TOKEN_TTL_SECONDS=300
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES=100
SKILLS_AUDIT_LOG=logs/mutation_audit.jsonl
```

配置解析确认：默认连接是 `mysql`；`mysql` 和 `analytics` 都只授权
`update-order-status` mutation Skill；token store 上限为 100。

### Legacy 兼容层

`default` alias、`DB_DEFAULT_*` 和 legacy `DB_TYPE`、`DB_USER`、
`DB_PASSWORD`、`DB_HOST`、`DB_NAME`、`SQLITE_DATABASE_PATH`、`ALLOW_UNION`、
`ALLOWED_TABLES` 已从本地 `.env` 的活动配置中移除。MySQL 与 SQLite 的实际
设置现在完全由 `DB_MYSQL_*` 与 `DB_ANALYTICS_*` 承载。

凭据仍只保存在 ignored local `.env`，不会写入本文档、聊天记录或提交历史。

## 2. 当前运维边界

- `.env` 当前仍允许 MySQL 和 analytics 对 `update-order-status` 写入。若日常
  运行不需要 MySQL 写入，应将 `DB_MYSQL_ALLOW_MUTATIONS=0`，并从
  `SKILLS_ALLOW_MUTATION_CONNECTIONS` 移除 `mysql`。
- `DB_MYSQL_ALLOWED_TABLES=*` 保留了原本的宽读权限；生产环境应收窄为明确表
  allowlist。
- 一次性 preview-token store 是进程内状态。推荐使用同一 MCP 子进程内的 stdio。
  若集成方在受信任私有边界内通过 HTTP transport 暴露 mutation，只能运行一个
  启用 mutation 的进程；v3.6.1 不定义多用户认证 HTTP mutation，程序也不会检测
  worker/replica 数。不得把多个 mutation worker 放在普通负载均衡器后。未来若出现明确的多副本写入需求，
  必须连同完整远程部署 profile 重新设计共享原子 store，不能依赖 sticky routing
  或退回 stateless HMAC。

## 3. 完全命名配置迁移验证

2026-07-31 后续将本地 `.env` 从“named policy + legacy credential fallback”
迁移为完全显式的 v3.6 命名配置：

- 已移除活动 legacy `DB_TYPE`、`DB_USER`、`DB_PASSWORD`、`DB_HOST`、
  `DB_NAME`、`SQLITE_DATABASE_PATH`、`ALLOW_UNION`、`ALLOWED_TABLES`。
- MySQL 凭据、数据库名、read/write policy 全部使用 `DB_MYSQL_*`；SQLite
  analytics 配置全部使用 `DB_ANALYTICS_*`。
- 新启动的 MCP stdio 子进程通过 `check_connection(connection_id="mysql")`
  和 `check_connection(connection_id="analytics")` 验证两端均已连接成功。
- 该验证没有执行 SQL query、Skill preview 或 mutation write。

## 4. 当前配置下的完整真实功能测试

**执行时间：** 2026-07-31  
**入口：** 当前聊天连接的 `mcp_sql-safety-ex_*` 工具  
**写入范围：** 仅使用临时订单 `id=990001`，测试结束后删除。

### 4.1 连接与基础工具

| Tool | MySQL | SQLite analytics | Result |
|---|---|---|---|
| `check_connection` | 成功 | 成功 | 通过 |
| `list_connections` | `mysql` 为 default | `analytics` 已配置 | 通过 |
| `list_tables` | 8 张可见表 | 1 张可见表：`orders` | 通过 |
| `describe_table(orders)` | 7 列 | 5 列 | 通过 |
| `get_full_schema` | 成功，返回完整 schema envelope | 成功，1 表/5 列 | 通过 |

第一次省略 `connection_id` 的默认 MySQL `check_connection` 曾出现一次
30 秒 timeout；随后显式 `connection_id="mysql"`、显式 `analytics` 和再次省略
参数的默认检查均成功。该次被记录为远程 MySQL 瞬时连接波动，不是配置解析失败。

### 4.2 Raw query 边界

- 两端执行 `COUNT(*)` 和受限订单状态查询成功。
- 两端提交 `DELETE FROM orders` 都返回只读拒绝，没有修改数据。
- 未知 `connection_id="missing"` fail closed。
- 将 `monthly-sales-report-sqlite` 投给 MySQL 被 DB type compatibility 拒绝。
- 当前 `.env` 的 `ENABLE_SCHEMA_TOOLS=0`、`ENABLE_TABLE_SUMMARY=0`，因此
  `sample` 和 `get_table_summary` 没有注册，未作为启用功能测试。

### 4.3 Skills discovery/detail/query

- 两个连接的 `list_skills(detail_level="full", available_only=true)` 均显示
  一个方言匹配的 query Skill 和 `update-order-status` mutation Skill 可执行。
- `get_skill_detail` 对 MySQL/SQLite 对应 query Skill 和 mutation Skill 均成功；
  `mutation_policy_allowed=true`、`schema_ready=true`。
- MySQL `monthly-sales-report` 和 SQLite
  `monthly-sales-report-sqlite` 均成功执行，当前 2026-07 返回 0 行，属于
  数据结果，不是执行失败。

### 4.4 Mutation preview/execute/replay

1. 在 MySQL 和 SQLite 各创建唯一临时 `pending` 订单 `990001`。
2. 两端通过 `execute_mutation_skill(confirm=false)` 成功返回 preview token，
   `expected_status=pending`。
3. 两端携带各自 token 执行成功，均返回 `rowcount=1`、
   `previous_status=pending`、`new_status=confirmed`。
4. 两端用同一 token 再次执行均被拒绝，证明一次性 replay 保护生效。
5. 用 MySQL token 指向 `analytics` 被 connection binding 拒绝，随后该 token
   在正确的 MySQL 连接上仍可执行，证明静态目标绑定拒绝不会错误消费 token。
6. analytics 额外完成了 `confirmed -> shipped` 的 preview/execute/replay
   验证；MySQL 也完成了 `confirmed -> shipped` 的 preview，并用于跨连接 token
   拒绝后在正确连接执行的验证。
7. 通过只读 query 验证两端临时订单状态后，再用数据库客户端删除；删除结果
   MySQL 1 行、SQLite 1 行，清理后两端查询 `id=990001` 均为 0。

本次 mutation 相关 audit 中命中临时订单的记录数为 8；未输出 audit 内容，避免
把业务参数带入聊天记录。完整 token 不写入 audit/meta。

### 4.5 覆盖结论与剩余边界

本次覆盖了当前启用配置下的连接、表发现、schema、raw query、query Skill、
mutation policy、preview token、状态绑定、正确连接执行、跨连接拒绝、replay
拒绝和可回收真实写入。它仍不是穷尽式测试：没有覆盖 `sample`/精确表摘要（当前
关闭）、SQLite 锁竞争、MySQL DML 超时故障、MCP 多进程共享 token store 或所有
数据库异常分支。当前 MySQL 仍配置 `DB_MYSQL_ALLOWED_TABLES=*` 和 mutation 写
授权，日常生产使用应按实际需要收窄。

## 5. Web、官方文档与 GitHub 实践复审

**复审日期：** 2026-08-01  
**复审结论：** 当前结果符合 v3.6 已启用功能的预期；编排和安全方向基本符合
主流工具调用最佳实践，但本记录不能被解释为穷尽式生产证明。

### 5.1 结果与测试编排判断

- 连接、表发现、schema、只读 query、query Skill、mutation policy、preview
  token、状态绑定、正确目标执行、跨连接拒绝、replay 拒绝和清理结果相互一致，
  没有发现与当前实现契约矛盾的成功结果。
- 先 `check_connection`，再连接/表/schema 发现，再 query/Skill discovery，
  最后执行 preview/execute，并在写入后做只读验证和清理，适合真实 MCP 联调。
- 日常 Agent 使用不应机械执行完整链路。当前 `sql_assistant` 使用条件规则：
  已知表直接 query，未知结构才探索，连接错误时才检查连接；这比固定的每次
  `check_connection -> schema -> query` 链更符合 model-controlled tool 的方向。
- 第 4 节是“当前启用配置的完整真实功能 smoke”，不是所有可选工具、数据库故障、
  锁竞争和多进程部署的穷尽测试；该边界已在第 4.5 节列出。

### 5.2 证据优先级与对应关系

本次复审采用以下证据优先级：

1. **第一优先级：规范性与官方安全文档。** MCP 规范/安全最佳实践，以及
  OpenAI、Anthropic、Google、Microsoft 的官方工具调用文档，用于判断输入校验、
  权限、确认、schema、结构化输出和 Agent 编排原则。
2. **第二优先级：官方框架文档与官方仓库。** FastMCP 官方文档/GitHub、MCP
  Python SDK 官方 GitHub，用于判断本项目对 `ToolResult`、structured content、
  annotations、timeout、typed tool 和 stdio client 的实现是否符合框架惯例。
3. **第三优先级：其他 GitHub 高 star 项目。** 只用于观察可维护的实现惯例、测试
  编排或输出裁剪方式，不用于替代规范，也不单独证明安全结论。

因此，下面的“符合”表示与第一、第二优先级依据一致；GitHub 高 star 项目没有被
当作本项目安全边界或合规结论的主要证据。

| 来源 | 相关指导 | 本项目当前对应 | 判断 |
|---|---|---|---|
| OpenAI Function Calling | 用代码承担约束、清晰定义工具和参数、避免把高风险逻辑交给模型自由生成 | SQL/Mutation 由服务端缓存和执行，参数由 schema 校验，mutation 不接受自由 SQL | 符合方向 |
| Anthropic Building Effective Agents | 高影响操作降低模型自由度；使用可验证的中间输出 | mutation preview、一次性 token、preview-state binding、execute 前重新 validation | 强符合 |
| Google Gemini Function Calling | 使用强 schema、类型、范围、枚举和有限的相关工具集 | FastMCP/Pydantic 字段约束、Skill params 的 type/min/max/enum、10 个当前工具 | 基本符合 |
| Microsoft Foundry Function Calling | 服务端验证 function/tool call，使用可信数据，遵循最小权限；有副作用时明确确认 | connection policy、table allowlist、token 绑定和 preview/execute；但 MySQL 当前 `ALLOWED_TABLES=*` 且允许写 | 机制符合，生产配置需收紧 |
| MCP Security Best Practices | 输入校验、权限控制、敏感信息不进入工具输出；本地 server 优先受限 transport | unknown id fail closed、结构化校验、stdio、token/audit 不泄漏 | 符合当前范围 |
| FastMCP 官方文档/GitHub | 类型注解和 docstring 生成 schema；`ToolResult` 提供 structured output/meta；timeout 和 annotations 是工具契约 | 工具使用 Annotated/Field、output schema、ToolResult.meta、timeout、ToolAnnotations | 符合；官方框架依据 |
| MCP Python SDK 官方 GitHub | 通过 typed tool 与 structured content 让客户端可程序化处理结果 | smoke 使用 `Client.call_tool()`，按 `structured_content` 读取结果 | 符合；官方框架依据 |
| 其他 GitHub 高 star MCP 项目 | 可借鉴测试、分页、输出裁剪和部署模式 | 本次没有用其作为安全或合规结论依据 | 次要旁证 |

GitHub 上的 FastMCP/MCP Python SDK 官方仓库属于官方框架实现参考；其他高 star
GitHub 项目只属于次要实现旁证。最终判断优先采用官方协议、官方平台文档、官方
框架文档和本仓库可执行测试证据。

### 5.3 Prompt、工具定义和 token 消耗复审

本地静态测量（不是模型账单 usage）：

| Surface | Size | 粗略说明 |
|---|---:|---|
| `sql_assistant()` prompt | 1,555 字符 | 按字符/4 粗估约 389，实际取决于 tokenizer |
| 10 个工具 description + input/output schema | 10,748 字符 | 按字符/4 粗估约 2,687 |
| prompt + 工具定义 | 12,303 字符 | 按字符/4 粗估约 3,076 |

这些数字不能当作精确的 `prompt_tokens` 或 API 计费量。MCP server 当前没有
模型侧 tokenizer 或 provider usage 回传，因此真实 token 成本仍需在宿主 Agent/API
层通过 usage 字段或 tokenizer 统计。

当前 token 控制符合实践的部分：

- Skills 采用 `list_skills` 的 compact/summary/full 渐进披露，不把所有 Skill
  源码或完整 schema 默认塞进 Agent 上下文。
- `query` 有 `MAX_RESULT_ROWS`、`MAX_RESULT_CHARS`；表/schema 有数量上限；
  文档明确说明截断返回不等于限制数据库工作量。
- mutation token 不进入 audit/meta；只记录 hash 前缀和安全运行元数据。
- `get_full_schema` 能按 `MAX_SCHEMA_TABLES` 截断，但当前实现主要按表数量限制，
  没有统一的 schema 总字符上限。本次真实 MySQL schema 结果曾达到工具输出资源
  约 36 KB，说明它是当前最明显的上下文/token 风险点。

### 5.4 复审发现与优先级

1. **中优先级：prompt 的 per-connection 策略表达不足。**
   `sql_assistant()` 的 `cross_table` 文案仍使用默认策略概念；它没有完整表达
   `analytics` 独立的 `ALLOW_UNION`/`ALLOWED_TABLES`。此外，代码中的
   `if ALLOW_UNION and ALLOWED_TABLES` 在未来打开默认 UNION 时可能引用未定义的
   `ALLOWED_TABLES`。当前 `.env` 的默认 UNION 为关闭，因此本次 smoke 未触发该问题。

2. **中优先级：减少不必要的 SQL 回显。**
   prompt 当前要求 `Always include SQL in response`，这会重复工具 payload、增加
   输出 token，并扩大 SQL 可见性。更合适的规则是：默认简要说明 query；只有用户
   明确要求或解释失败时才回显完整 SQL。

3. **中优先级：为 `get_full_schema` 增加字符级预算。**
   表数量上限不能覆盖宽表/复杂 schema 的大输出。应增加 schema payload 的总字符
   上限或按列/表渐进返回，并为截断增加明确 metadata；不要只依赖模型自行控制。

4. **低优先级：增加宿主层 token usage 观测。**
   服务端已有 execution time、row count、truncated 等 metadata，但没有 provider
   prompt/completion token。该能力应放在实际调用模型的 Agent/API 层，避免 MCP server
   引入模型供应商耦合。

5. **配置风险：当前 MySQL 权限适合 smoke，不适合默认生产姿态。**
   `DB_MYSQL_ALLOWED_TABLES=*` 和 `DB_MYSQL_ALLOW_MUTATIONS=1` 扩大了真实库的读写
   blast radius。若只是日常只读使用，应移除 `mysql` mutation target、关闭 MySQL
   mutation，并将表 allowlist 收窄为业务所需表。

### 5.5 二次复审结论

本次按“官方文档/规范优先，GitHub 次要参考”的要求重新审阅后，结论保持不变：

- 当前第 4 节真实测试结果与 v3.6 已启用功能契约一致，且临时写入已清理。
- preview → token-bound execute → 状态验证 → replay 拒绝的编排，与高影响操作
  使用可验证中间结果、服务端校验和显式确认的官方方向一致。
- 当前 prompt/工具定义/渐进披露已经是合理基线，但 per-connection prompt 表达、
  `get_full_schema` 字符级预算和 provider token usage 观测仍是实际改进项。
- “通过”只表示当前启用配置和已覆盖范围通过；不表示所有可选工具、异常分支、
  多进程部署或生产权限配置均已证明安全。

### 5.6 依据链接

- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Building Effective Agents](https://platform.claude.com/docs/en/docs/build-with-claude/agentic-systems)
- [Google Gemini Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Microsoft Foundry Function Calling](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/function-calling)
- [MCP Security Best Practices](https://modelcontextprotocol.org/specification/2025-06-18/basic/security_best_practices)
- [FastMCP Tools](https://gofastmcp.com/servers/tools)
- [FastMCP GitHub](https://github.com/PrefectHQ/fastmcp)
- [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk)

## 附录 A：历史协议基线

以下内容来自早期隔离 fixture 批次。它验证了独立 `StdioTransport` 子进程和
临时 MySQL/SQLite 目标，不代表当前业务数据库状态；保留它是为了回溯早期协议
行为和清理证据。

### A.1 直接连接检查

通过聊天附带的 `mcp_sql-safety-ex_check_connection` 调用实际 MCP server 的
`check_connection` 工具。前缀 `mcp_sql-safety-ex_` 是聊天环境为已连接 MCP
server 添加的命名空间，不是 server 内部工具名。当时的调用省略
`connection_id`，因此检查的是当前默认连接：

| Target | Result | DB type | Connection id |
|---|---|---|---|
| Current default | Connected | MySQL | `mysql` |

该聊天工具实际支持可选 `connection_id`；传入 `mysql` 或 `analytics` 可以分别
检查对应连接。该早期批次只通过聊天工具补充检查了默认 `mysql`，而 MySQL + SQLite
双连接的完整结果来自真实 FastMCP stdio 协议 smoke，以及正文第 4 节的当前配置
完整测试。

### A.2 MCP 协议联调方法

测试使用 FastMCP `StdioTransport` 启动 `start_server.py` 子进程，再使用
`Client.call_tool()` 发起真实 MCP `tools/call` 请求。子进程通过临时环境覆盖：

- MySQL 指向一次性 schema `llm_mcp_v36_smoke_<date>_<suffix>`。
- SQLite 指向 `logs/` 下的一次性 fixture 文件。
- 两端都只允许 `orders` 表和 `update-order-status`。
- 审计写入独立 fixture JSONL，不使用 tracked `skills/_audit.jsonl`。

因此该历史协议批次没有向 `trade_data_analysis` 或原始 `sample_data/demo.db` 写入。

### A.3 执行结果

MCP 子进程注册了 10 个工具。以下行为均通过断言：

| Area | MySQL fixture | SQLite fixture |
|---|---|---|
| `check_connection` | Connected | Connected |
| `list_tables` | 仅 `orders` 可见 | 仅 `orders` 可见 |
| `query` | fixture order 初始为 `pending` | fixture order 初始为 `pending` |
| `list_skills(available_only=true)` | `update-order-status` executable | `update-order-status` executable |
| Mutation preview | 返回 token hash prefix | 返回 token hash prefix |
| Mutation execute | `pending` -> `confirmed`，rowcount 1 | `pending` -> `confirmed`，rowcount 1 |
| Replay | 同一 token 被拒绝 | 同一 token 被拒绝 |

审计产生 4 条 fixture 记录（两端各 preview + execute），并验证其中没有完整
`preview_token`。

### A.4 清理

协议联调完成后已删除：

- 临时 MySQL smoke schema；
- 临时 SQLite fixture；
- 临时 MCP stdio 日志；
- 临时 smoke audit JSONL。

该历史批次未修改现有业务 schema、原始 SQLite demo 文件、tracked 审计样例或凭据。
