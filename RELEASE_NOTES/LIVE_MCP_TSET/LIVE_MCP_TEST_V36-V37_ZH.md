# v3.6-v3.7 MySQL + SQLite MCP 协议联调记录

**日期：** 2026-07-31

**文档边界更新：** 2026-09-03

> **v3.7.1 迁移说明：** 本文是 v3.6-v3.7.0 协议联调历史记录，其中 token
> 格式和响应快照不代表 v3.7.1 契约。v3.7.1 `preview_token` 是 256-bit opaque
> handle，绑定状态保存在进程内 Store；现行规范见
> [Skills 安全策略](../../skills/SAFETY.md)。

2026-08-26 已在重启后的已配置 MCP 服务上完成 v3.7.1 opaque-handle direct
MCP live mutation 与恢复；它本身不等同于 fresh-subprocess approval-host 复验。
2026-08-28 又完成了 fresh-subprocess approval-host 的批准/拒绝复验，以及按目标
连接隔离的 UNION allow/deny 复验，因此 2026-08-21 的 v3.7.0 stdio/host 结果保留
为历史基线，不再是最新证据。

2026-08-28 发布前首次检查中，直接调用当前聊天 MCP 的默认连接
`check_connection` 返回已脱敏的 `Database query failed`；后续本地复核显示，
同一默认 MySQL 连接在 30 秒查询限制下超时。MySQL 服务启动且 MCP 重启后，
同日复验的 `check_connection`、`SELECT 1` 和 `COUNT(*)` 均成功，UNION 按目标连接的
`allow_union=false` policy 被拒绝。MySQL 只做了只读检查，没有执行 mutation。
本轮还在 disposable `live_test_sqlite` 上完成并恢复了 opaque-handle 可逆流程，
详情见 7.4。随后在 fresh stdio subprocess 中用临时环境仅打开
`analytics_demo_sqlite` 的 UNION，真实两行 UNION 成功而默认 MySQL 仍拒绝；同日
又重新复验了 fresh-subprocess approval host 的批准和拒绝路径，详情也见 7.4。

**结果：** 2026-07-31 联调通过；2026-08-13、2026-08-19 与 2026-08-20
的隔离 subprocess stdio 阻塞保留为历史尝试；2026-08-21 的 v3.7
人工批准 host、完整 server subprocess stdio 和拒绝路径复验通过；
2026-08-26 和 2026-08-28 的 v3.7.1 direct MCP opaque-handle 可逆流程通过；
2026-08-29 的渐进 Schema 投影 direct MCP 与 Agent 自然选择探索通过；
2026-09-01 的真实 MySQL 只读复验与 Skills readiness fail-closed 隔离回归通过；
2026-09-02 的最终 compact 默认契约与 Skills 非空默认值隔离回归通过，MySQL
数据面当天不可用，未误报为 live pass

**范围：** v3.6 基线配置解析、MCP stdio 协议、命名连接、严格 mutation policy、
一次性 preview token、MySQL/SQLite 写路径和 replay 拒绝；以及 v3.7 人工批准
host 的 in-memory contract 与 subprocess stdio 复验边界。v3.7.1 已在 disposable
`live_test_sqlite` 上通过 direct MCP 与 fresh-stdio reset/恢复；真实 MySQL reset
尚未执行，其 MySQL 兼容性目前仍以自动化回归为证据。

本文记录的协议联调只验证 stdio；2026-08-10 补充的 v3.6.1 HTTP 文字是部署
边界说明，不表示已经完成 HTTP transport 或多用户认证联调。

**阅读顺序：** 正文优先呈现当前配置和当前完整测试结论；早期隔离 fixture
协议 smoke 保留在文末“附录 A：历史协议基线”，用于审计和回溯，不作为当前配置
的主要结论。

## 1. v3.7 推荐配置与历史快照边界

以下配置最初用于准备 `reset-demo-order-to-pending` 的本地 live 测试；配置本身不构成
验证证据。后续 SQLite reset live 结果见 7.3/7.4；真实 MySQL reset 尚未执行：

```env
DB_CONNECTIONS=trade_analysis_mysql,analytics_demo_sqlite,live_test_sqlite
DEFAULT_DB_CONNECTION=trade_analysis_mysql
DB_LIVE_TEST_SQLITE_TYPE=sqlite
DB_LIVE_TEST_SQLITE_SQLITE_DATABASE_PATH=./local_data/live-test.db
DB_LIVE_TEST_SQLITE_ALLOWED_TABLES=orders
DB_LIVE_TEST_SQLITE_ALLOW_MUTATIONS=1
DB_LIVE_TEST_SQLITE_MUTATION_SKILLS=update-order-status,reset-demo-order-to-pending
SKILLS_ALLOW_MUTATION_CONNECTIONS=live_test_sqlite
MUTATION_PREVIEW_TOKEN_TTL_SECONDS=300
MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES=100
SKILLS_AUDIT_LOG=logs/mutation_audit.jsonl
```

该配置让三个连接同时保持可选，省略 `connection_id` 时仍默认路由到
`trade_analysis_mysql`；但全局 mutation allowlist 只包含可丢弃的
`live_test_sqlite`，所以 MySQL 与跟踪的 demo SQLite 在 preview 前拒绝写入。
当前本地 `local_data/live-test.db` fixture 的 `orders` 表包含主键 `id`、`status`、
`order_date` 和 `total_amount`，并准备了 2026-08 的确定性测试数据，因此既可用于
订单 mutation，也可用于 `monthly-sales-report-sqlite`。该数据库文件被 `.gitignore`
排除，不是干净 clone 可依赖的仓库资产；执行 live 测试前仍应确认本地 fixture 的
schema 和数据边界。reset 虽然声明兼容 MySQL，但应只在另建或明确选择的专用 MySQL
测试 alias 上授权，且仍必须通过其它 mutation policy 层。修改 `.env` 后需要重启
MCP server 才会重新加载连接注册表。

2026-08-20 的配置快照与 2026-08-21 的 live 证据早于 reset Skill 定稿；对应
真实写路径使用的是 `update-order-status`，数据库恢复依赖临时 fixture 或快照。
下文 2026-07-31 的真实联调仍使用当时的 `mysql`/`analytics` 别名，并按历史事实
保留。不得把这些结果改写成 reset 或真实 MySQL reset 已通过。

### Legacy 兼容层

`default` alias、`DB_DEFAULT_*` 和 legacy `DB_TYPE`、`DB_USER`、
`DB_PASSWORD`、`DB_HOST`、`DB_NAME`、`SQLITE_DATABASE_PATH`、`ALLOW_UNION`、
`ALLOWED_TABLES` 已从本地 `.env` 的活动配置中移除。MySQL 与 SQLite 的实际
设置现在完全由 `DB_TRADE_ANALYSIS_MYSQL_*` 与
`DB_ANALYTICS_DEMO_SQLITE_*` 承载。

凭据仍只保存在 ignored local `.env`，不会写入本文档、聊天记录或提交历史。

## 2. 当前运维边界

- `.env` 当前注册 MySQL、demo SQLite 与 live-test SQLite 三个连接；三者都可按各自
  read policy 访问，但全局 mutation 目标只有 `live_test_sqlite`。MySQL 与 demo
  SQLite 即使保留连接级 mutation 开关，也会因不在全局 allowlist 中 fail closed。
- `DB_TRADE_ANALYSIS_MYSQL_ALLOWED_TABLES=*` 保留了原本的宽读权限；生产环境应收窄为明确表
  allowlist。
- v3.7 完整 MCP raw-query policy 每次只接受一条 statement，并拒绝 raw SHOW；
  metadata discovery 改用 `list_tables`/`describe_table`。限制性 allowlist 的
  comma/nested/CTE/qualified/ambiguous target 与 executable comment/hint 已有
  自动化回归，但本文件没有把它们记成真实 subprocess stdio 通过。
- 一次性 preview-token store 是进程内状态。推荐使用同一 MCP 子进程内的 stdio。
  若集成方在受信任私有边界内通过 HTTP transport 暴露 mutation，只能运行一个
  启用 mutation 的进程；v3.6.1 不定义多用户认证 HTTP mutation，程序也不会检测
  worker/replica 数。不得把多个 mutation worker 放在普通负载均衡器后。
  未来若出现明确的多副本写入需求，
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

## 4. 2026-07-31 当时配置下的完整真实功能测试

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

## 5. 基于 2026-07-31 快照的 Web、官方文档与 GitHub 实践复审

本节的“当前”均指 2026-07-31 当时的 `mysql`/`analytics` 配置与实现快照，不是
v3.7 当前能力声明，也不是当前 backlog。后续已处理或接受的项目以最新风险登记表
和 v3.7 发布说明为准。

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

2026-08-21 当时的本地静态测量快照（不是当前提示契约，也不是模型账单
usage）：

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

1. **v3.7.1 已修复：prompt 的 per-connection UNION 策略表达。**
   2026-08-21 的 `sql_assistant()` 文案错误地把默认连接的 UNION policy 当作全局
   提示；真实 `query()` 与 Query Skill 执行路径当时已经按目标连接强制执行。
   v3.7.1 将提示改为目标中立的说明，并增加默认/目标连接策略相反的双向回归测试，
   防止提示再次把某一连接的 policy 泛化为整个服务的 policy。

2. **v3.7.1 已收窄并接受：SQL 回显。**
   2026-08-21 的 prompt 无条件要求 `Always include SQL in response`。v3.7.1 只要求
   raw `query()` 调用报告实际提交的 SQL，以保留透明度和响应兼容性；Skill 调用只
   报告 Skill、参数和连接，不得编造 Skill 未披露的 SQL。raw query 的 SQL 仍可能
   进入 MCP 上下文，因此不得把 secret、token 或敏感个人数据放入 SQL literal。

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

## 6. v3.6.1 临时 SQLite stdio 复验

**执行日期：** 2026-08-13
**状态：** 当前自动化执行环境中阻塞于 MCP initialize，未形成新的通过结论。

本次按批准范围创建了 `/tmp` 下的一次性 SQLite `orders` 数据库、audit 文件和
stdio transport log，并通过环境变量禁用 `.env`，计划验证：连接/表发现、Skill
可用性、`pending -> confirmed` preview/execute、replay 拒绝、最终状态与完整 token
不进入 audit。未使用 tracked `sample_data/demo.db` 或真实 MySQL。

当前项目 `.venv` 中的 FastMCP 3.0.2 / MCP Python SDK 1.26.0 能启动
`start_server.py`，日志到达 `transport='stdio'`，但客户端未完成 initialize，因而
没有发出任何 `tools/call`；临时订单保持 `pending`，也没有生成 mutation audit。
相同行为可由不导入本项目代码的最小 FastMCP server 复现。为排除旧 FastMCP
版本因素，又在 `/tmp` 隔离安装 FastMCP 3.4.5 及其 client/server 依赖进行最小
对照，仍停在 initialize。项目 `.venv`、requirements 和 tracked 数据均未因此
修改。

因此，该现象目前只能判定为本次自动化执行环境中的 subprocess stdio/框架交互
阻塞，不能归因于 mutation 业务代码，也不能把本次尝试记为 stdio 通过。正文与
附录记录的 2026-07-31 历史真实 stdio 结果仍然有效，但不替代当前版本复验。
下一步应在普通本地终端或实际 MCP host 中运行同一临时 SQLite 流程；若在那里也
可复现，再单独登记为 runtime/dependency compatibility 风险并保留初始化 trace。

## 7. v3.7 人工批准 host 验证

**历史执行日期：** 2026-08-19；环境传递修复后复验：2026-08-20
**自动化合约结果：** 通过
**截至 2026-08-20 的 subprocess stdio 结果：** 当前执行环境中再次阻塞于 initialize，未执行写入

v3.7 为 `examples/manual_mutation_approval.py` 增加了两层验证。默认 pytest 使用
真实 `Client(module.mcp)` in-memory transport，对临时 SQLite `orders` 表完成
`pending -> confirmed` preview、批准、execute 和最终状态核对。这不是 fake client
路径，也不会接触 `.env` 或 tracked sample database；同时还有 fake client
状态机测试覆盖 deny、timeout、EOF/cancel、workflow 强制截止时间、畸形/过期
preview、参数快照、实际解析连接固定、完整 stdio 环境传递、精确 token 输出替换，
以及 execute 结果不确定时不重试。

最初的 2026-08-19 live 尝试暴露出 MCP SDK 的 stdio transport 在未显式提供
`env` 时只传递少量系统变量：shell 中导出的 `DB_*`、Skill policy 和
`PYTHON_DOTENV_DISABLED` 不会自动进入子进程。该问题会让子进程转而读取另一套
项目 `.env`，因此不能把那次尝试当作正确 fixture 配置下的有效协议证据；不过它在
initialize 前已失败，没有发出工具调用或写入。

2026-08-20 修复为显式传递当前进程完整环境后，再次创建 `/tmp` 一次性 SQLite
数据库和 JSON params，禁用 `.env`，并使用当前 `.venv` Python 启动 CLI。15 秒与
最终 20 秒两次复验中，server 子进程均成功到达 FastMCP 3.0.2 的
`transport='stdio'` 启动日志，但 client 仍未在 init timeout 内完成 initialize，
CLI 以 `RuntimeError` fail closed 退出。没有
展示批准界面、没有发出 preview/execute、没有创建 audit；临时订单复核仍为
`pending`，随后 fixture 已清理。该次复验确认阻塞在正确环境传递之后仍存在。

该结果与第 6 节 2026-08-13 现象一致，不能把 in-memory 合约通过写成 subprocess
stdio live 通过，也没有证据说明阻塞由 v3.7 connection scope、批准状态机或 mutation
业务逻辑引起。真实 host/普通本地终端仍是下一次 stdio 复验位置。

本轮最终自动化回归（它不是 subprocess stdio live）为：默认仓库测试套件
`462 passed, 3 skipped`，其中聚焦 SQL/query/SQLite 套件为 `115 passed`；由于
`pytest.ini` 有意只收集 `tests/`，另行显式运行根目录
legacy `test_bug_fixes.py`，结果为 `2 passed`；`git diff --check` 通过。该结果验证
v3.7 policy/Skill/mutation regression；该结果记录的是 2026-08-20 之前的自动化
基线；2026-08-21 的历史 subprocess stdio 结果见下方第 7.1 节，2026-08-28 的最新
fresh-subprocess approval-host 和 UNION 目标 policy 复验见第 7.4 节。

### 7.1 v3.7.0 Live Validation（2026-08-21）

本节更新第 7 节前文的状态判断；第 7 节前文保留为 2026-08-19/20
的历史记录，不代表当前 subprocess 仍然 blocked。

**环境与版本：** 使用当前仓库和 `.venv`，确认：

```text
Python 3.12.3
fastmcp 3.0.2
mcp 1.26.0
```

在 `local_data/live-test.db` 建立了 `orders(id INTEGER PRIMARY KEY,
status TEXT NOT NULL)`，插入 `id=1, status=pending`。Host live 流程按批准范围另用
一个位于临时目录的一次性 SQLite fixture，其结构和初始数据相同；临时参数文件
包含 `order_id=1`、`new_status=confirmed`。
子进程仅收到 `env -i` 临时配置，设置
`PYTHON_DOTENV_DISABLED=1`、`stdio_test_sqlite` SQLite 连接、`orders` allowlist、
`update-order-status` mutation allowlist 和独立临时 audit 路径，未读取项目
`.env`。本次 live 完成后，一次性 fixture 已恢复为 `pending`，供拒绝结果复核；
`local_data/live-test.db` 仍为 `pending`。

**真实 MCP 基础检查：** 当前聊天 MCP 的 `list_connections` 显示默认连接
`trade_analysis_mysql` 和 SQLite `analytics_demo_sqlite`；默认 MySQL、显式
`analytics_demo_sqlite` 的 `check_connection` 均成功，旧别名 `analytics` 明确
拒绝。SQLite 的 schema/query 检查成功；MySQL 的只读 `SELECT COUNT(*) FROM
orders` 成功返回 8 行总数，`update-order-status` detail 显示 schema、连接和
mutation policy 均允许。

本节的直接 MCP 检查验证的是当前已运行 MCP 服务的配置和连接状态；它不单独证明
一个全新 subprocess 已从本地 `.env` 重新加载配置。若需要验证 `.env` 加载本身，
应在不设置 `PYTHON_DOTENV_DISABLED=1` 且不从父环境传入 `DB_*` 覆盖项的条件下，
启动 fresh subprocess，并只调用 `list_connections`、`list_skills` 等只读工具。

**批准流程：** 使用用户给定的 `env -i` 配置运行
`examples/manual_mutation_approval.py` 并输入精确的 `APPROVE`，进程退出码为 0。
Host 完成 initialize，显示了不含 bearer token 的批准视图；execute 使用 preview
返回并固定的 `connection_id=stdio_test_sqlite`，返回 `rowcount=1`、
`previous_status=pending`、`new_status=confirmed`。数据库状态变为
`confirmed`，独立 audit 文件存在并包含 preview、execute 各一条记录。stdout、
Host stderr、批准视图和 audit 均没有完整 token；stdout 中出现的
`preview_token_expires_at` 只是过期时间字段，不是 token 值，audit 不包含 token
字段。

**拒绝流程：** 将同一数据库重置为 `pending`，输入 `NO`，进程退出码为 3。stdout
只有 preview 和 `deny` 结果，明确返回“execute was not called”；audit 只有一条
preview 记录，没有 execute 记录，数据库仍为 `pending`。同一 Host 调用序列只有
一次 preview，没有自动重试，也没有 token 输出。

**in-memory 与 subprocess 分类：**

- **in-memory contract passed：** `test_workflow_contract_via_in_memory_fastmcp_client`
  通过（1 passed）；完整 `tests/test_manual_mutation_approval.py` 为 46 passed。
- **subprocess stdio passed：** APPROVE 写入、非 APPROVE 拒绝，以及后述最小 echo、
  `start_server.py`、完整 `mcp_sql_server` 三路 initialize 探针均通过。
- **subprocess stdio blocked at initialize：** 本次 2026-08-21 未复现；2026-08-13
  和 2026-08-19/20 的阻塞仍按历史结果保留，不能与本次通过混写。

**最小 FastMCP 二分：** 三路均使用当前 `.venv`、相同临时环境、仓库 cwd、
`StdioTransport(command=sys.executable, env=dict(os.environ), keep_alive=False)`
和 15 秒 initialize timeout：

| Target | Result |
|---|---|
| 最小 echo server（一个 `echo` tool，`mcp.run(transport="stdio")`） | initialize 和 tool call 通过 |
| `start_server.py` | initialize 通过 |
| 直接导入完整 `mcp_sql_server` 并 `mcp.run(transport="stdio")` | initialize 通过 |

第一次完整 server 探针曾因临时 wrapper 不在 Python import path 得到
`ModuleNotFoundError: No module named 'mcp_sql_server'`；改为从仓库 cwd 使用
`python -c` 导入后通过，因此不计为 MCP/stdio 失败。三路均观察到 FastMCP
3.0.2 banner 和 `transport='stdio'` 启动日志。临时 stdout、stderr 和 audit 文件
未作为持久证据保留。当前结论是：**Host 状态机已实现，且 subprocess live
validation 已通过；不登记本次为 FastMCP/stdio 运行兼容性阻塞。**

### 7.2 2026-08-21 当前 MCP 连接的直接 Skill live smoke

本节记录另一条与 7.1 不同的证据：直接使用当前聊天已连接的
`mcp_sql-safety-ex_*` MCP 工具完成 Skill 调用，没有启动本地 subprocess，也不是
in-memory contract。当前配置中的 `analytics_demo_sqlite` 实际连接到
`sample_data/demo.db`；它不是 7.1 使用的一次性 fixture，也不是
`local_data/live-test.db`。因此本节只使用现有测试订单 `id=5`，并在测试前备份、
测试后恢复 `sample_data/demo.db`。

**调用链与结果：**

1. `list_skills(detail_level="full", available_only=true,
  connection_id="analytics_demo_sqlite")` 成功，SQLite query Skill 和两个
  mutation Skill 均报告可执行。
2. `get_skill_detail` 成功返回 `monthly-sales-report-sqlite` 和
  `update-order-status` 的完整参数/策略信息。
3. `execute_query_skill` 执行
  `monthly-sales-report-sqlite(year=2026, month=8)` 成功，返回 0 行，属于当前
  测试数据结果，不是 Skill 执行失败。
4. 只读 query 确认 `orders.id=5` 的初始状态为 `pending`。
5. `execute_mutation_skill(confirm=false)` 成功返回 pending -> confirmed preview
  和一次性 token；`confirm=true` 携带该 token 后真实写入成功，返回
  `rowcount=1`、`previous_status=pending`、`new_status=confirmed`。
6. 只读 query 确认状态为 `confirmed`；同一个 token 再次执行被拒绝，证明 replay
  保护生效。
7. 恢复数据库快照后再次 query 确认 `id=5` 回到 `pending`，并验证
  `sample_data/demo.db` 的 git diff clean。

完整 bearer token 出现在本次 MCP mutation preview 的工具响应中，但没有写入本文；
这说明直接让模型/聊天层承载 token 会扩大聊天记录、调试日志或上下文持久化的
泄露面。服务端 audit/meta 不记录完整 token；需要更强隔离时应优先使用 7.1 的
Host，或由 host 维护 token，而不是让模型直接读取和回显 bearer token。

**分类：** 本节是 **direct MCP Skill live smoke passed**；它补充验证了当前命名
连接下的 Skill discovery、query execution、mutation write、状态核验和 replay
拒绝，但不替代 7.1 的 subprocess stdio 或人工批准 Host 验证，也不证明
`local_data/live-test.db` 已通过当前聊天 MCP 路径。

### 7.3 v3.7.1 Opaque Handle Direct MCP Live Validation（2026-08-26）

本节记录重启 MCP 服务并重新发现工具后的 v3.7.1 窄范围 live 证据。工具 schema
已显示 opaque handle 且 `preview_token.maxLength=128`；此前会话附件中的
HMAC/4096 描述属于旧快照，不代表重启后的服务。

**调用链与结果：**

1. 默认 `trade_analysis_mysql` 在该时点 `check_connection` 成功；随后选择明确的
  disposable `live_test_sqlite`，只读 query 确认 `orders.id=1` 初始为 `pending`。
2. `update-order-status(confirm=false)` 返回 43 字符 URL-safe opaque handle 和
  `preview_token_expires_at`；响应中没有旧 envelope、
  `preview_token_expires_in_seconds`、顶层 hint 或嵌套 confirmation 字段。
3. 使用同一 handle 但把目标状态改为 `shipped` 的 execute 被拒绝，错误未回显
  handle；随后用原始 `confirmed` 参数执行成功，证明 request mismatch 没有消费
  有效记录。
4. 同一 handle 再次执行被拒绝；只读 query 确认状态为 `confirmed`，证明成功消费
  后 replay protection 生效。
5. 通过 `reset-demo-order-to-pending` 的独立 preview/execute 将记录恢复，最终
  query 确认 `orders.id=1` 回到 `pending`。

该流程是重启后已配置服务上的 **direct MCP live mutation passed**，验证 opaque
handle 的实际响应、匹配/消费和 replay 行为。它没有重新启动独立 fresh subprocess
或运行人工批准 Host，所以不能单独作为这两条 fresh-subprocess 路径的证据；
2026-08-28 的独立 fresh-subprocess approval-host 批准/拒绝与按目标连接的 UNION
allow/deny 复验见 7.4，已取代 2026-08-21 作为最新 live evidence。
2026-08-28 默认 MySQL 曾出现连接超时；服务启动并重启 MCP 后的恢复证据见 7.4。
该瞬时失败不推翻本节已经完成并恢复的 SQLite 流程。

### 7.4 当前代码 Direct MCP 复验（2026-08-28）

本节用于验证当前代码和重启后的当前配置，不把 7.3 的历史成功直接外推。真实
MySQL 仅执行只读检查；mutation 仍只在可丢弃的 `live_test_sqlite` 上进行。

**MySQL 只读结果：**

1. 默认 `trade_analysis_mysql` 的 `check_connection` 成功。
2. 显式目标上的 `SELECT 1 AS live_check` 成功返回一行。
3. 随后独立复核的 `SELECT COUNT(*) AS row_count FROM orders` 成功返回 `8`。
4. `SELECT 1 AS value UNION SELECT 2 AS value` 被该目标的
  `allow_union=false` policy 拒绝，响应包含正确的 `connection_id`。

**SQLite opaque-handle 可逆流程：**

1. 只读 query 确认 `orders.id=1` 初始为 `pending`；Skill discovery 显示
  `update-order-status` 和 `reset-demo-order-to-pending` 均可在该目标执行。
2. preview `pending -> confirmed` 成功并返回 43 字符 opaque handle。
3. 使用同一 handle 将 execute 参数改成 `new_status=shipped` 时，请求绑定校验拒绝；
  随后以原始 `confirmed` 参数执行成功并返回 `rowcount=1`，证明 mismatch 没有消费
  有效 handle。
4. 同一 handle 再次执行被拒绝；只读 query 确认状态已变为 `confirmed`。
5. 使用独立 reset preview/handle 恢复，最终 query 确认状态回到 `pending`。

**证据边界：** 当前三个 live 连接的 `allow_union` 均为 `false`，因此当前 `.env`
的 direct MCP 复验只覆盖拒绝路径。本轮还通过独立 fresh subprocess 临时仅为
`analytics_demo_sqlite` 开启 UNION，真实验证 raw query 与 Query Skill 的 allow
分支，同时默认 MySQL 仍拒绝；这项临时覆盖不是当前 `.env` 默认策略。自动化多连接
矩阵继续覆盖相反 policy 组合。本轮没有在 MySQL 上执行 mutation。当前代码还在
`live_test_sqlite` 上完成了 fresh-subprocess approval host 的批准/拒绝复验；它与
上面的 direct MCP opaque-handle 流程使用独立的 server subprocess，但都只写入并
恢复同一个可丢弃的订单 `id=1`。

**Fresh subprocess UNION allow 分支：** 使用新的 `StdioTransport` server 进程，
只临时设置 `DB_ANALYTICS_DEMO_SQLITE_ALLOW_UNION=1`，未修改工作区 `.env`。该进程
的 `list_connections()` 确认 `analytics_demo_sqlite.allow_union=true`，而默认
`trade_analysis_mysql.allow_union=false`。目标 SQLite 执行
`SELECT id, status FROM orders WHERE id = 1 UNION SELECT id, status FROM orders
WHERE id = 2 ORDER BY id` 成功返回 2 行（`id=1/2`，均为 `completed`）；同一进程
对默认 MySQL 的 `SELECT 1 AS probe UNION SELECT 2 AS probe` 仍返回安全拒绝。该次
调用观测耗时分别约 134.28 ms 和 157.10 ms，只是单次联调样本，不是性能基准。
同一 fresh server 进程另以测试 harness 将同一条只读 UNION SQL 注入现有 query
Skill 的加载路径：`monthly-sales-report-sqlite` 指向
`analytics_demo_sqlite` 时成功返回 2 行，耗时约 348.74 ms；
`monthly-sales-report` 指向默认 MySQL 时被 UNION policy 拒绝，耗时约
2,040.54 ms。该 harness 使用空参数映射来隔离 UNION policy，不代表正式月报
Skill 的业务 SQL；它补充证明 Query Skill 的目标连接 policy 与 raw query 一致。

**Fresh-subprocess approval host：** 使用当前 `.venv`、当前本地配置和
`live_test_sqlite.orders.id=1`，临时参数为 `pending -> confirmed`。输入精确
`APPROVE` 的 Host 子进程墙钟耗时约 8,787.69 ms，退出码 0，最终状态
`executed`，目标为 `live_test_sqlite`，数据库返回 `rowcount=1`；批准视图和最终
stdout 均没有完整 bearer handle。恢复后输入 `NO` 的独立 Host 子进程耗时约
12,414.76 ms，退出码 3，状态 `deny`，消息明确为 execute 未调用，stdout 同样
没有完整 handle。两次流程均在各自的同一 Client/server 子进程内完成 preview
和后续决定；拒绝流程没有执行写入。

**详细 direct MCP 采样：** 以下是一个 fresh stdio server 进程中 19 个步骤的单次
观测，所有耗时为从客户端发起调用到收到结果的墙钟时间；错误传播也计入其中。
累计约 3,711.75 ms，不能代表吞吐、P95 或跨网络生产延迟。

| Step | Result | Observed ms |
|---|---|---:|
| `ping` | 成功 | 7.80 |
| `list_connections` | 3 个连接，默认 `trade_analysis_mysql` | 93.40 |
| MySQL `SELECT 1` | 1 行成功 | 412.50 |
| MySQL UNION | policy 拒绝 | 40.22 |
| live SQLite `COUNT(*)` | 返回 1 行，订单总数为 3 | 72.97 |
| live SQLite UNION | policy 拒绝 | 40.69 |
| `list_skills(full)` | 3 个可执行 Skill | 37.89 |
| `get_skill_detail(execution)` | mutation 参数/下一步成功返回 | 20.41 |
| SQLite 月报 Skill | 2026-08 返回 3 行 | 179.19 |
| execute 前查状态 | `pending` | 50.92 |
| mutation preview | `pending -> confirmed`，handle 43 字符 | 59.58 |
| 参数绑定 mismatch | 拒绝，handle 保留 | 1,438.14 |
| mismatch 后查状态 | 仍为 `pending` | 44.99 |
| 正确 execute | `rowcount=1`，变为 `confirmed` | 60.87 |
| execute 后查状态 | `confirmed` | 47.99 |
| replay | 已消费 handle，拒绝 | 959.81 |
| reset preview | `confirmed -> pending` | 42.22 |
| reset execute | `rowcount=1` | 59.40 |
| 最终查状态 | `pending` | 42.74 |

上面的 MySQL `COUNT(*)` 是随后独立完成的只读复核，不属于这份 19 步计时样本，
因此不为它补写未观测的耗时。

preview 返回的 handle 在该次采样中为 43 个字符、没有 `.`；这是当前实现的观测，
不是客户端应依赖的格式契约。`get_prompt("sql_assistant")` 通过 fresh MCP
subprocess 返回 1 条消息、2,959 字符、约 9.99 ms，包含
`UNION policy is connection-specific` 和 selected-alias 指引，不包含默认连接
UNION 泛化文案。最终只读查询确认 `live_test_sqlite.orders.id=1` 为 `pending`；
MySQL 全程只读，未执行 mutation。

### 7.5 渐进 Schema 投影 Live Validation（2026-08-29）

本节验证 `get_full_schema(detail_level="compact"|"full")`。测试目标为明确 alias
`trade_analysis_mysql`，真实 MySQL 全程只读。先用 fresh FastMCP stdio 子进程完成
payload 测量；随后重载 VS Code 窗口，使当前 Host 重新发现工具并直接复验新参数。
重载前，Host 的执行校验层虽然展示了新 schema，却把 `detail_level` 和
`group_identical` 拒绝为 additional properties；重载后相同调用均成功，因此该现象
分类为 Host 工具注册缓存，不是 server 实现失败。

**Direct MCP 结果：**

1. `check_connection(connection_id="trade_analysis_mysql")` 成功，目标数据库为
  `trade_data_analysis`。
2. 显式 `detail_level="full"` 成功，返回 8 表、272 列，`truncated=false`。
3. `detail_level="compact", group_identical=true` 成功，返回 4 个 schema group；
  其中 5 张 `va_manual_*` 表共享一个经当前 adapter 可见列元数据和列顺序判等的组。
  该判等不覆盖完整 DDL、索引或约束，不能据此声称这些对象完全等价。
4. `detail_level="compact", group_identical=false` 成功，返回 8 个独立 group。
5. 当时省略 `detail_level` 的 fresh-process 响应与显式 full 完全相同；该中间默认值
   后来由 7.7 记录的最终 compact 默认取代。
   当前 full 相对改动前是加法兼容（新增顶层 `detail_level` 和列 `default`），并非旧
   payload 逐字节不变。

以下字符数使用 JSON 文本的 Python 字符长度；token 使用
`tiktoken/o200k_base`。Pretty 表示两空格缩进，minified 表示无可选空白。旧 full
来自改动前保存的同库 Host 结果；当前三种模式在同库、同数据上测量，并由重载后的
direct Host 调用复现响应语义。它们不是 API 账单或跨 Host 的通用保证。

| Schema payload | Pretty 字符 | Pretty token | Minified 字符 | Minified token | 相对旧 full 的 Pretty token |
|---|---:|---:|---:|---:|---:|
| 改动前 full | 36,676 | 9,270 | 18,404 | 5,314 | 基线 |
| 当前 full（含 adapter default） | 44,300 | 10,946 | 22,760 | 5,934 | +18.1% |
| compact，不分组 | 20,125 | 4,660 | 8,273 | 2,492 | -49.7% |
| compact，adapter 可见列元数据判等分组 | 8,732 | 2,068 | 3,728 | 1,128 | **-77.7%** |

Grouped compact 相对旧 full 减少 76.2% pretty 字符和 77.7% pretty token；相对
当前含 default 的 full 减少 80.3% / 81.1%。仅启用该元数据判等分组，就比
ungrouped compact 再减少 56.6% pretty 字符和 55.6% pretty token。此前单张 41 列
`describe_table()` 约为 1,094 token，因此 broad overview 使用 grouped compact
还能避免 Host 截断后逐表重复钻取所产生的额外上下文。

**低上下文 Agent 自然选择样本：** 独立 `MCP Runner` 只收到“概览该 alias 的表、
用途、同构关系，并指出订单分析应深入哪张表”的业务目标；提示没有指定工具、参数
或调用顺序，也没有提供上述测量结论。Agent 自主执行：

| 样本 | 实际轨迹 | 调用数 | Full/describe/query | 截断 | 结果 |
|---|---|---:|---:|---|---|
| broad schema overview，`n=1` | `list_tables` → `get_full_schema(compact, group_identical=true)` | 2 | 0 | 否 | 正确识别 8 表、4 组、5 张同构 `va_manual_*` 表，并优先定位 `orders` |

该轨迹发生在后续引导微调前，并暴露出 grouped compact 已包含表名和行估计时仍先调
`list_tables` 的冗余。微调后的 fresh-process pretty payload 为：`list_tables` 368
token、grouped compact 2,068 token；若仍走两调用路径约为 2,436 token，直接 compact
可再省 368 token。相对当前口径的旧 `list_tables + pre-change full` 约 9,638 token，
直接 compact 约减少 78.5%。这不包含 system prompt、工具 schema、Agent 回答或
provider usage，不能当作完整会话账单。

**引导微调后重启验收：** MCP 服务重启后，先通过 `check_connection` 确认 alias 仍指向
`trade_data_analysis`，再直接调用 grouped compact，复核 8 表、272 列、4 组且
`truncated=false`。随后 3 个相互独立的低上下文 `MCP Runner` 接收与历史样本相同的
broad overview 目标，不指定工具名、参数或顺序：

| 样本 | 实际轨迹 | 调用数 | Full/describe/query | 截断/错误 | 结果 |
|---:|---|---:|---:|---|---|
| 1 | `list_tables` → grouped compact | 2 | 0 | 无 | 正确完成 |
| 2 | grouped compact | 1 | 0 | 无 | 正确完成 |
| 3 | grouped compact | 1 | 0 | 无 | 正确完成 |

Direct compact 选择率为 `2/3`（66.7%），前置 `list_tables` 为 `1/3`；共 4 次调用，
平均 1.33 次/样本，未调用 full、`describe_table` 或 `query`。按上述 pretty payload
估算，3 次 schema 结果共 6,572 token，平均约 2,191 token/样本，仅比全部 direct
compact 的 2,068 token 下界高 123 token（5.9%）。相对旧
`list_tables + pre-change full` 的约 9,638 token/样本，平均 payload 下降约 77.3%。
这些仍是 payload-only 估算，不包含工具定义、系统提示、Agent 回答或 provider usage。

**修复后 fresh stdio 复验（2026-08-29）：** 使用
`.venv/bin/python -m pytest -q test_mcp_client.py -s` 启动独立 stdio server，实际
该批 `tools/list` 中 `detail_level` 为非空 `compact|full` enum、机器默认值为
`full`；7.7 记录了后来定稿的 `compact` 默认。字段当时已不再
含 nullable `anyOf`。随后对 `trade_analysis_mysql` 调用 grouped compact，返回 8 表、
272 列、4 组、`truncated=false`，并显式返回
`grouping_basis="adapter_visible_column_metadata_and_order"`。同一 smoke 的
`SELECT 1`、`COUNT(*)`、单表描述和 query Skill 均为只读；非法 `DELETE` 与不存在的
mutation Skill 在执行写入前被拒绝，全程没有 mutation 或数据库写入。结果为
`1 passed`。该复验验证当前 fresh-process 工具契约；已运行的 VS Code/Codex Host
仍需重启或刷新工具注册后才会看到新的默认值与描述。

该批次支持引导微调后多数样本会自然跳过冗余 discovery，但仍观测到 `1/3` 前置
`list_tables`。历史 `n=1` 与本批 `n=3` 不是随机对照实验；小样本结果不能外推为所有
模型、Host、温度或任务措辞的保证。

### 7.6 MySQL 恢复复验与 Skills Readiness 补漏（2026-09-01）

MySQL 恢复后，当前 Host 对明确 alias `trade_analysis_mysql` 顺序执行纯只读
`get_full_schema` 调用：grouped compact 返回 8 表、272 列、4 组，ungrouped
compact 返回 8 个独立组，两者均 `truncated=false`；grouped 响应明确携带
`grouping_basis="adapter_visible_column_metadata_and_order"`。省略
`detail_level` 与显式 `full` 的结构化响应完全相同；`full` 下切换
`group_identical` 不产生分组字段或响应变化。当前 Host 对 `structuredContent`
做 minified JSON 序列化后，grouped compact、ungrouped compact、full 分别约为
3,860、8,368、22,760 字符。该字符数受响应文案和序列化方式影响，不是协议保证。

同批代码审查发现 Skills readiness 曾把“检查主动关闭”和“metadata 读取失败”都压成
`None`，从而可能在检查已启用时把依赖表的 Skill 继续显示为
`schema_ready=true`。修复后使用显式 disabled/available/unavailable snapshot：
metadata 不可用时返回 `schema_check_available=false`、`schema_ready=false`，不伪造
`missing_tables`，默认发现面隐藏相关 Skill，直接 query/mutation 执行则在 SQL、
preview token 和写入前 fail closed。该失败路径通过隔离 SQLite/mock 回归验证，未通过
修改真实 MySQL 状态来人为制造故障。整个 MySQL 复验没有调用 `query` 或 mutation，
没有数据库写入。相关 Skills disclosure/mutation 聚焦套件为 `83 passed`，默认全量
套件为 `484 passed, 3 skipped`。

### 7.7 最终默认契约复验（2026-09-02）

由于本项目尚未正式发布，`get_full_schema()` 的最终默认值收敛为
`detail_level="compact"`。省略投影参数现在等价于显式
`detail_level="compact", group_identical=true`，默认响应使用 `schema_groups`；需要
以表名为 key 的完整 adapter 元数据时必须显式传入 `detail_level="full"`。隔离 SQLite
回归同时确认 full 模式下切换 `group_identical` 不改变响应，也不产生任何分组字段。

Skills 工具契约也完成收敛：`list_skills.detail_level` 是非空
`compact|summary|full` enum，`available_only` 是非空 boolean，二者的 JSON Schema
默认值等于该进程启动时解析出的环境配置；`get_skill_detail.detail_level` 是非空
`execution|full` enum，默认 `full`。非默认启动配置 `full/false` 也通过了“机器默认值
等于省略参数后的运行值”回归。

验证结果如下：

- Schema/Skills 聚焦套件：`56 passed`；
- 默认全量套件：`485 passed, 3 skipped`；
- fresh stdio MySQL 进程成功完成 MCP 注册，`tools/list` 显示
  `get_full_schema.detail_level` 为非空 enum 且默认 `compact`；随后
  `check_connection` 返回已脱敏的 `Database query failed`，smoke 按既有规则跳过，
  未执行 schema、SQL 或 mutation；
- 当前已连接 MCP 的显式 compact 只读调用同样返回
  `error_code="metadata_query_failed"`，所以本节不把 MySQL 数据面写成通过；
- `PYTHON_DOTENV_DISABLED=1` 的临时 SQLite fresh-stdio 尝试在 MCP initialize
  阶段阻塞，观察后已终止；它不构成功能失败证据，也不计为通过。

因此，2026-09-02 的证据覆盖最终工具注册契约和隔离运行语义；最近一次真实 MySQL
投影成功仍是 7.6 记录的 2026-09-01 只读复验。上述尝试均未产生数据库写入。

### 7.8 工具契约精度与范围校验（2026-09-02）

本批修正 `sample.limit`、`get_table_summary.exact_count` 以及核心工具选择说明。验证
分成两部分，避免把不同配置或 Host 缓存混写为同一种证据。

**隔离 SQLite FastMCP protocol probe：** 在 fresh process 中启用可选 schema 和
table-summary 工具，仅使用一次性 `:memory:` 数据库。`tools/list` 实际返回：

- `sample.limit`：`type=integer`、`default=5`、`minimum=1`、`maximum=20`，说明明确
  越界会被拒绝；
- `get_table_summary.exact_count`：`type=boolean`、`default=false`，参数说明明确
  `SELECT COUNT(*)` 可能全扫描、在大表上较慢，并可能遇到 MySQL metadata-lock
  contention；
- `query`、`describe_table`、`list_connections` 的注册说明分别显示自由形式只读
  SQL、adapter 可见列元数据而非完整 DDL，以及“默认 alias 保留 mutation 兼容模式、
  非默认 alias 要求严格命名写授权，连接发现本身不授权写”的边界；`sql_assistant`
  中的 `list_skills` 签名包含 `connection_id`。

真实 MCP 调用 `sample(limit=0)` 与 `sample(limit=21)` 均返回 validation error；
拦截的 `adapter.execute` 调用列表保持为空，证明拒绝发生在 handler/SQL 之前。
`limit=1` 与 `limit=20` 均成功，生成的 SQLite SQL 分别以 `LIMIT 1` 与 `LIMIT 20`
结尾。该段记录 MCP 边界验证；Python 直接调用与最终严格契约见 7.9。
该 probe 的聚焦结果为 `4 passed, 77 deselected`。

**Fresh stdio + 配置的 MySQL：** 运行维护脚本
`.venv/bin/python -m pytest -q test_mcp_client.py -s`，结果为 `1 passed`。新 server
成功初始化，`tools/list` 暴露修正后的三个核心工具说明；`list_tables` 返回 8 张表，
默认 grouped compact 返回 8 表、272 列、4 组且未截断；`SELECT 1`、对 8 行
`orders` 的只读 `COUNT(*)`、`describe_table(orders)` 和 query Skill 均成功；非法
`DELETE` 与不存在的 mutation Skill 在写入前被拒绝。当前部署未注册 `sample` 和
`get_table_summary`，因此不能用这次 MySQL stdio smoke 声称验证了两个可选参数；
它们的证据来自上述隔离 probe。MySQL 全程没有执行 mutation 或数据库写入。

回归结果为：聚焦 metadata/multi-connection 套件 `81 passed`；默认全量套件
`488 passed, 3 skipped`；`git diff --check` 与相关 Python 编译检查通过。长期运行的
IDE/Codex Host 没有用于证明本批新描述已经刷新；修改后仍需重启/刷新 Host 的工具
注册缓存。

### 7.9 严格参数契约与未知行数语义（2026-09-03）

本批将 MCP `inputSchema`、Python 函数签名和 handler 校验收敛为一个契约，并修正
无法估算行数时误报为 0 的行为：

- `SKILLS_LIST_DEFAULT_DETAIL` 经专用解析器返回静态
  `Literal["compact", "summary", "full"]`；`get_full_schema`、`list_skills` 和
  `get_skill_detail` 的投影类型使用共享 Literal alias；
- 省略参数仍使用声明默认值，但 Python 直接调用显式传 `None`、大小写/空白变体，
  或向 `available_only` 传非布尔值时会明确拒绝，不再解释成默认值；
- `sample.limit` 的 Python 直接调用与 MCP 一致，只接受整数 1..20；0、21、`true`
  和 `None` 均在 SQL 前拒绝，不再静默截断；
- SQLite 可发现但不满足保守 metadata identifier 语法的表仍由 `list_tables` 返回，
  其 `row_count=null` 表示未知而非空表；MySQL 的 NULL `TABLE_ROWS` 也会在 discovery
  与单表 adapter 路径保持为 null；
- `list_connections` 明确为无参数工具；`list_skills` 不再把 `summary` 描述成固定
  默认值，而是说明省略参数采用启动时解析的配置。

**隔离协议与单元回归：** 聚焦 adapter/schema/Skills/multi-connection 套件结果为
`175 passed, 3 skipped`。FastMCP Client 继续证明 `sample.limit` 的 JSON Schema 为 integer、默认 5、
minimum 1、maximum 20，且 MCP 越界值在 adapter SQL 前被拒绝。新增直接调用测试和
`odd-name` SQLite 表测试覆盖上述严格拒绝与 null/zero 区分；MySQL adapter mock
同时验证 NULL estimate 保持 null、真实 0 保持 0。`describe_table()` 与 approximate
`get_table_summary()` 的隔离回归进一步验证未知估算会输出
`row_count=null`、`row_count_approximate=null`、`is_large=null`，不会生成大表建议或
`~None` 日志；`exact_count=true` 的整数/布尔语义保持不变。

**静态检查：** 临时 Pyright 1.1.411 使用项目 `.venv` 依赖解析
`mcp_sql_server.py`，结果为 `0 errors, 0 warnings, 0 informations`。这不仅验证了
原 3272 行动态 `str` 默认值问题已消失，也检查了该文件其余静态类型诊断。

**Fresh stdio + 配置的 MySQL：** 运行
`.venv/bin/python -m pytest -q test_mcp_client.py -s`，结果为 `1 passed`。fresh
server 从当前源码启动并成功完成初始化；`list_tables` 返回 8 张表，新的 hint 明确
“null means unavailable, not empty”；默认 grouped compact 返回 8 表、272 列、4 组
且未截断。`SELECT 1`、`orders` 的只读 `COUNT(*)`、`describe_table(orders)` 和 Query
Skill 均成功；非法 `DELETE` 和不存在的 mutation Skill 在写入前被拒绝。8 张 MySQL
表本次均取得数值估计，因此 null 分支以隔离 adapter/core-tool 回归为证据。全程没有
mutation 或数据库写入。

最终默认全量结果为 `507 passed, 3 skipped`。`git diff --check` 和 Python 编译检查
在最终差异复核中执行。

### 7.10 Strict FastMCP Validation 与 Host Rediscovery（2026-09-03）

本轮进一步区分机器 schema、FastMCP runtime validation 和 Python 直调三层契约。
FastMCP 3.0.2 默认 flexible validation 的隔离探针证明，字符串
`group_identical="false"` 会被转换为 boolean false。Server 随后显式启用
`strict_input_validation=True`；fresh in-process Client 验证字符串 boolean 和字符串
integer 均在 handler/SQL 前被 JSON Schema 拒绝。Python 直调不经过该协议层，因此
`group_identical`、`exact_count`、`available_only` 与 mutation 的 `confirm` 复用显式
boolean 校验，`None`、0/1 和字符串不再静默进入 false/true 分支；非法 `confirm`
还会在 Skill 加载、token 消费或数据库访问前停止。

SQLite row-estimate 回归还模拟了 table discovery 后、bounded sample 前对象被删除的
并发 DDL 窗口。该路径现在返回 `row_count=null`，表示估计不可用；真实空表仍返回
0。名称不满足保守 metadata identifier 语法的表也保持相同 unknown 语义。

**Fresh stdio 协议与只读 MySQL：** 独立启动当前 `start_server.py` 后，`tools/list`
暴露非空 `compact|full`、默认 `compact`，以及 boolean `group_identical`、默认 true；
传入字符串 `"false"` 返回 `Input validation error`。省略参数的 grouped compact
调用成功返回 `trade_analysis_mysql` 的 8 表、272 列、4 组，
`grouping_basis="adapter_visible_column_metadata_and_order"`，`truncated=false`。
全过程只读。相关 adapter/schema/Skills/multi-connection 套件为
`203 passed, 3 skipped`，默认全量为 `521 passed, 3 skipped`。Pyright 1.1.411
使用项目虚拟环境，对当前全部 8 个已修改 Python 文件报告
`0 errors, 0 warnings`。

**当前 VS Code Host 边界：** 本轮修改前，长期运行的当前 Host 仍向模型显示旧的
nullable/default-null `detail_level` schema，但 direct backend 已返回新 compact 行为并
拒绝 null。这证明 server process restart 与 Host tool rediscovery 是独立生命周期。
Server 无法清除 Host 私有注册缓存；需要断开/重连 MCP 或 Reload Window，并从同一
Host 重新获取 `tools/list`。本轮末当前 Host 完成工具重新发现，实际暴露非空
`compact|full`、默认 compact 和 boolean grouping 默认 true；随后通过当前 Host 的
默认调用复现 8 表、272 列、4 组且未截断。该结果完成当前 Host 契约验收，但本节未
追加 Agent 自然选择样本，也不把 fresh stdio 证据与 Host 证据混为同一来源。

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
