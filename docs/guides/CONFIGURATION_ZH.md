# v3.8 TOML 配置及迁移契约

配置入口是 `load_config(path) -> AppConfig`。CLI 必须提供 `--config`；没有隐式搜索、dotenv 加载、旧环境覆盖或缺省连接身份继承。FastMCP 的 `.env` 搜索在正式入口导入框架前通过 `FASTMCP_ENV_FILE=os.devnull` 关闭。应用显式设置 `strict_input_validation=True`、`mask_error_details=True`。嵌入方若已先行导入 FastMCP，须负责自己的导入配置；安装第三方 `python-dotenv` 并不代表本项目恢复了旧通道。

```text
sql-safety-executor serve --config /path/server.toml
sql-safety-executor config check --config /path/server.toml
sql-safety-executor config explain --config /path/server.toml
```

`check` 和 `explain` 使用与启动相同的加载器，解析所有显式密钥引用，但不连接数据库、不导入 Skill、不创建日志。检查成功不代表数据库可达或 Skill 可执行。`explain` 展示生效值、声明文件/内置来源、超时继承来源及权限条件；密码始终脱敏。异常仅输出文件、字段与错误类别，不输出原始配置片段。

语义错误保留程序定义的安全错误码，例如 `exactly_one_secret_source_required`（密钥必须恰选一种来源）、`tables_require_allowlist_mode`（填写 tables 时必须使用 allowlist）、`union_requires_explicit_table_scope`（UNION 缺少有效读取范围）、`mrtr_requires_skills_and_mutations`（MRTR 依赖开关未开启）。不会直接输出 Pydantic 原始消息、输入或异常上下文；密钥读取失败仍使用统一错误类别，不泄露内容。

## 文件与路径

三文件各有顶层 `schema_version = 1`，由 `tomllib` 解析、严格 Pydantic 模型校验。禁止未知字段、字符串布尔值、字符串数字、负数限额和越界令牌配置；不再静默回落。TOML 重复键/重复连接声明直接报错。别名必须符合 `[a-z][a-z0-9_]{0,63}`，不接受声明重复大小写别名。

`server.toml` 必须引用 `files.connections`。可省略 `files.skills`，此时 Skills 关闭；显式引用文件缺失或无效始终报错。`server.default_connection` 必填且必须存在。请求中的未知目标不回退；省略 `connection_id` 才使用默认连接。

每个配置内路径相对于它的声明文件解析，包括子文件、SQLite、Skill、日志、审计和密钥文件。CLI 主文件路径先解析为绝对路径。SQLite `:memory:` 保持特殊语义。模板复制到其他位置后，应同步调整路径。配置和密钥在 `load_config()` 时形成快照；启用的 Skill 定义、SQL 模板及允许加载的 Python 类在 `create_server()` 初始化时加载。服务运行期间修改这些文件需重启才能生效；可信 Python 代码自身仍可修改进程状态，不构成沙箱或代码不可变保证。

## 默认值与限制

可选 telemetry 按调用成对抽样，写入 `tool_call_started`／`tool_call_finished`；只有结束事件携带业务结果。消费者按 `(server_instance_id, call_id)` 配对并筛选结束事件统计，request/session 摘要只是辅助关联，框架 session 不保证跨请求稳定。诊断窗口用 `sample_rate=1.0`，修改配置由维护者重启生效；不因本次补强自动启用。日志失败、强杀或中间件之前拒绝仍可缺记录。详见[字段、成本和计时边界](../validation/v3.8/V3_8_2_HOST_REQUEST_CORRELATION_2026_10_28_ZH.md)。

| 节/字段 | 默认值 / 约束 |
| --- | --- |
| `server.tool_timeout_seconds` | 120，非负有限数；0 禁用工具超时 |
| `tools.schema` | true，历史上只控制可选 `sample`；基础 metadata 工具仍注册 |
| `tools.table_summary` / `tools.large_table_threshold` | false / 1000（非负整数） |
| `limits.result_rows` / `result_chars` | 100 / 16000；0 不限额；result_chars 非零时至少 2 |
| `limits.sql_chars` | 20000；0 不限额，继续保留原输入作用域 |
| `limits.schema_tables` / `overview_tables` | 50 / 100；0 不限额 |
| `defaults.timeouts.query_seconds` / `connect_seconds` | 30 / 10；正整数 |
| `observability.logging.level` / `path` | INFO / 不写日志文件，服务日志到 stderr |
| `observability.telemetry.enabled` / `path` / `sample_rate` | false / `../logs/tool_calls.jsonl` / 1.0，范围 [0,1] |
| `connections.<id>.sqlite.progress_handler_interval` | 100，正整数 |
| `connections.<id>.read.mode` / `tables` / `allow_union` | deny / [] / false |
| `connections.<id>.mutation.enabled` / `skills` | false / [] |
| `skills.enabled` / `directory` | false / `../skills` |
| `skills.discovery.default_detail` / `available_only` | summary / true；detail 为 compact、summary、full |
| `skills.readiness.check_schema` | true；同时影响发现与执行前就绪检查 |
| `skills.policy.exclude_profiles` | []；严格字符串数组，去首尾空白、转小写并去重；空白项报错。执行限制，不只是隐藏列表 |
| `skills.mutation.enabled` / `allowed_connections` | false / [] |
| `skills.mutation.preview.ttl_seconds` | 300，范围 1…86400 |
| `skills.mutation.preview.max_entries` | 10000，范围 1…100000 |
| `skills.mutation.mrtr.enabled` | false；开启必须同时开启 Skills 与全局写入。仅控制额外 MRTR 工具注册，不禁用旧 preview/execute，不是全局强制人工审批开关 |
| `skills.audit.queries` / `path` / `agent_id` | false / `../logs/skill_audit.jsonl` / unknown |

仅查询超时和连接超时按“内置值 → server 公共默认 → connections 目标值”覆盖。数据库类型、文件、host、user、database、password 不继承其他连接。MySQL 必须声明且仅声明 `mysql`，SQLite 必须声明且仅声明 `sqlite`。`agent_id` 是可伪造审计标签，不是认证主体。

结果截断只限制已取回的响应，不能限制数据库扫描、查询工作量或所有瞬时内存；仍应使用 WHERE/LIMIT/ORDER BY。工具超时也不证明数据库写入已回滚。

## 密钥

```toml
mysql.password = { value = "literal" }        # 三选一
# mysql.password = { env = "DB_SECRET" }
# mysql.password = { file = "secrets/password" }
```

不提供失败回退，不做 `strip()`；空密钥拒绝。文件 UTF-8，最多 65536 字节；末尾换行属于密码内容。不存在的环境变量、文件错误、无效 UTF-8、双来源对象都报错。环境变量只有经 `{env=...}` 显式引用才使用，不允许借此覆盖其他配置。

实际凭据不要提交。私有 `config/*.toml`、`config/secrets/` 已忽略；公开样例仅保留占位或明确的环境引用。配置错误脱敏不替代操作系统文件权限和 Host 的凭据隔离。

本地部署约定：三份私有文件可使用 `config/server.toml`、`config/connections.toml` 和 `config/skills.toml`；密码文件放在 `config/secrets/`，并通过 `{file=...}` 引用。机器专用的 MCP 启动配置使用根目录 `mcp_config.local.json`，本地操作说明使用 `config/LOCAL_SETUP.md`；这两项同样加入 Git 忽略规则。公开的 `mcp_config.json` 保留通用路径占位符。私有 TOML、密钥与本地客户端配置应限制为仅当前用户可读写；复制客户端配置时采用实际已安装 v3.8 的绝对可执行文件路径。

## 读取和写入

`read.mode = "deny"` 阻止读取。`allowlist` 只授权列出的关系，空集合不授权；`all` 必须显式设置，覆盖配置默认 schema，不能同时填写 `tables`／`relations`。跨 schema 使用 allowlist＋明确组件。表名不允许 `*`。裸声明绑定默认对象，也接受默认 schema 限定引用；temp／aux／其它库同名对象不继承。查询继续检查只读语法、系统 schema、文件操作、锁读、UNION 和表范围；旧的部分检查 `execute_sql()` 已移除。

Query Skill 的发现、详情和执行共享读取准入判断；即使 SQL 为 `SELECT 1`、没有声明表，deny 或空 allowlist 下也不可执行，并从 `available_only=true` 的发现中隐藏。明确未授权的依赖先拒绝；MySQL CTE 大小写歧义可以在最低必需依赖已授权后触发一次无物理表的常量能力探测，成功结果按适配器缓存，失败保持精确比较并在 30 秒后允许重试。启动目录扫描仍无数据库 I/O；schema readiness 是另一项元数据检查。

通过读取准入和声明表范围检查后，发现/详情使用执行侧 SQL 策略预检缓存模板，包括 UNION 开关和按目标连接解析的表范围。禁止 UNION 的连接会隐藏相应 Skill，完整列表/详情给出原因；另一明确允许 UNION 的连接仍可使用同一模板。预检不执行业务 SQL、不重读文件、不跨连接缓存授权结论。Query Skill full 的 tables 是声明／推断并集，declared_tables 和 inferred_tables 区分来源；静态 SKILLS.md 只列声明。物理表声明保留名字中的真实字符和空格，不能把 CTE 别名当作实体依赖；SQLite 表身份只折叠 ASCII 大小写，MySQL 物理表授权继续精确匹配。执行期仍重新验证，executable=true 不保证参数、数据库状态或 SQL 方言一定满足执行要求。详见[最新验收](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md#cte-依赖与实际名称规则修复2026-10-14)。

`exclude_profiles = ["DEMO", " demo "]` 的快照等同于 `["demo"]`；`[]` 不排除任何 profile，`[""]` 或纯空白项以 `nonempty_profile_name_required` 报错，数字/布尔值不会转为字符串。该规范化只用于 profile 标签，不适用于密钥内容。此项修复会让之前误写大小写或空白的排除配置真正生效，重启前应运行 `config check/explain` 核对。

`allow_union = true` 还要求有效表范围。特别注意：旧空白名单读取本来较宽松，但 `ALLOW_UNION=1` 与旧空名单组合仍禁止 UNION。迁移成 `mode="all"` 时必须保留 `allow_union=false`，除非另行明确扩大权限。不能将旧配置字段机械逐项转换。

自 v3.8.1 起，服务启动时会把每个连接的读取状态、表范围类型（all 或含表数量的 allowlist）和 UNION 状态写入 MCP instructions，供 Agent 在编写 SQL 前参考；不列表名、主机或路径，超过 12 个连接时只给数量。修改这些字段后需重启服务并刷新 Host 工具定义。该文本只是指导，执行时仍由完整读取策略独立检查。

`read.tables` 的大小写规则（v3.8.1 起）：SQLite 连接仅折叠 ASCII 大小写；MySQL 连接保留配置中的大小写并精确匹配，因为 `lower_case_table_names=0`（Linux 默认）时 `Orders` 与 `orders` 是不同的表。MySQL 条目应写成数据库中的存储名；在不区分大小写的服务器上，大小写不同的查询引用也会被拒绝。`mode = "all"` 不列默认 schema 内的表名白名单；schema 范围仍须检查，不能据此跨库。Skill schema readiness 也使用对应连接的表身份；它只观察可用性，不授权执行。见 DRR-2026-076 及本页 v3.8.2 范围更新。

10 月 12 日复核后的读取子集保守拒绝关系括号组、单引号对象、ODBC 包装和 TABLE 表达式；可用标准标识符引用及受支持的 JOIN／CTE。v3.8.2 起，CTE 按实际方言处理：SQLite 支持前向引用和隐式递归；MySQL 保持定义顺序与显式递归自引用，不豁免实际同名物理表。内置 PRAGMA 对象名保留，普通 `pragma_` 列、别名及非保留业务表名允许。`read.mode="all"` 仍执行结构、系统对象等检查，不能绕过这些限制。

`describe_table()` 自动采集已授权表的索引，没有新增 TOML 开关，`get_full_schema()` 不含索引。采集固定限 128 个索引、2048 键项和 64 KiB UTF-8 索引数组，独立于 `limits.result_chars`；时间沿用配置 query timeout，仅索引阶段协作式生效。超限／失败返回 `indexes_status="unavailable"`、`indexes=null`，保留列信息；不能解释为无索引。SQLite 元数据明确读取 main，普通 SQL 会话的临时对象仍由可信扩展负责。索引名等新增披露和采集成本属于已接受取舍，见[最终复核](../validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md)。

Mutation Skills 的写入权限是五层配置与既有执行检查的交集：

1. `skills.enabled = true`。
2. `skills.mutation.enabled = true`。
3. 连接在 `skills.mutation.allowed_connections` 中。
4. `connections.<id>.mutation.enabled = true`。
5. Skill 在 `connections.<id>.mutation.skills` 中（或显式 `"*"`）。

Skill 的 `databases`、`connection_ids`、profile、参数、就绪和托管计划仍继续收紧作用域。读表白名单不会普遍限制 Mutation Skills。关闭读取不自动撤销已显式授权的写入，托管 preview 和内部就绪仍可能读取其业务表。删除了旧 default-only 兼容授权；空连接准入名单不允许默认连接写入。

## 默认审批流程（2026-10-01 决策）

继续以 preview/execute 为默认，保持 `skills.mutation.mrtr.enabled = false`；这沿用现有模型及公开模板默认值，不是配置迁移或禁写开关。10 月 1 日所测 Codex IDE 已完成主要原生审批交互，所测 Copilot 会话被协议门槛拒绝；不足以概括全部客户端的支持情况。只有核实实际 Host 的协议、能力、审阅展示和决定续接后，才在对应部署显式开启 MRTR。见[验收复核](../validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)。

preview/execute 的人工交互由可信 Host 负责，可用专用 Host 代码强制执行；只在提示词中要求 Agent 询问，则仅是行为约定。MRTR 在自身入口强制校验批准响应，仍不能证明来自真人，也不会关闭旧入口。审批失败、取消、超时或结果未知后，不应自动改走另一入口写入；必须按原任务授权重新审阅，结果未知时先核对业务状态。需要防止客户端自行批准时，应采用尚未实现的独立授权设计，见[安全边界](../security/V3_8_SECURITY.md#where-approval-is-enforced)。

## 逐字段迁移

| 旧字段 | TOML 归属 | 说明 |
| --- | --- | --- |
| `DEFAULT_DB_CONNECTION` | server: `server.default_connection` | 必填 |
| `DB_CONNECTIONS` | connections: `connections` 的键 | 移除重复注册列表 |
| `DB_TYPE` / `DB_<ID>_TYPE` | `connections.<id>.type` | 不继承默认目标 |
| `DB_USER/HOST/NAME`（含命名形式） | `connections.<id>.mysql.user/host/database` | 每个 MySQL 连接完整声明 |
| `DB_PASSWORD`（含命名形式） | `connections.<id>.mysql.password` | 三选一显式密钥来源 |
| `SQLITE_DATABASE_PATH` / `DB_<ID>_SQLITE_DATABASE_PATH` | `connections.<id>.sqlite.path` | 相对声明文件，非 cwd |
| `SQLITE_PROGRESS_HANDLER_INTERVAL`（含命名形式） | `connections.<id>.sqlite.progress_handler_interval` | 正整数 |
| `QUERY_TIMEOUT_SECONDS` / `CONNECT_TIMEOUT_SECONDS` | server: `defaults.timeouts.query_seconds/connect_seconds` | 仅这两项可继承 |
| `DB_<ID>_QUERY_TIMEOUT_SECONDS/CONNECT_TIMEOUT_SECONDS` | `connections.<id>.timeouts.query_seconds/connect_seconds` | 覆盖公共值 |
| `ALLOWED_TABLES`（含命名形式） | `connections.<id>.read.mode/tables` | 默认 deny，空 allowlist 拒绝 |
| `ALLOW_UNION`（含命名形式） | `connections.<id>.read.allow_union` | 处理旧空名单例外 |
| `DB_<ID>_ALLOW_MUTATIONS` | `connections.<id>.mutation.enabled` | 连接开关 |
| `DB_<ID>_MUTATION_SKILLS` | `connections.<id>.mutation.skills` | 不与其他名单自动合并 |
| `MCP_TOOL_TIMEOUT_SECONDS` | server: `server.tool_timeout_seconds` | 0 禁用 |
| `ENABLE_SCHEMA_TOOLS` | server: `tools.schema` | 保留历史 sample 开关语义 |
| `ENABLE_TABLE_SUMMARY` / `LARGE_TABLE_THRESHOLD` | server: `tools.table_summary/large_table_threshold` | 默认 false / 1000 |
| `MAX_RESULT_ROWS/MAX_RESULT_CHARS` | server: `limits.result_rows/result_chars` | 0 不限额 |
| `MAX_SQL_LENGTH` | server: `limits.sql_chars` | 0 不限额 |
| `MAX_SCHEMA_TABLES/MAX_OVERVIEW_TABLES` | server: `limits.schema_tables/overview_tables` | 0 不限额 |
| `ENABLE_TOOL_TELEMETRY` | server: `observability.telemetry.enabled` | 默认 false |
| `TOOL_TELEMETRY_LOG_PATH/TOOL_TELEMETRY_SAMPLE_RATE` | server: `observability.telemetry.path/sample_rate` | 采样越界直接报错 |
| `ENABLE_SKILLS` / `SKILLS_DIR` | skills: `skills.enabled/directory` | 缺 Skills 引用即关闭 |
| `SKILLS_LIST_DEFAULT_DETAIL` | `skills.discovery.default_detail` | 默认 summary |
| `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT` | `skills.discovery.available_only` | 默认 true |
| `SKILLS_CHECK_SCHEMA_ON_LIST` | `skills.readiness.check_schema` | 保留执行侧作用 |
| `SKILLS_EXCLUDE_PROFILES` | `skills.policy.exclude_profiles` | 授权限制 |
| `SKILLS_ALLOW_MUTATIONS` | `skills.mutation.enabled` | 默认 false |
| `SKILLS_ALLOW_MUTATION_CONNECTIONS` | `skills.mutation.allowed_connections` | 空名单不授权任何连接 |
| `MUTATION_PREVIEW_TOKEN_TTL_SECONDS` | `skills.mutation.preview.ttl_seconds` | 越界报错，不回落 |
| `MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES` | `skills.mutation.preview.max_entries` | 越界报错，不回落 |
| `MUTATION_PREVIEW_TOKEN_SECRET` | 移除，无替代项 | 旧参数已过时；令牌依旧随机单次句柄 |
| `SKILLS_AUDIT_LOG/SKILLS_AUDIT_QUERIES/AGENT_ID` | `skills.audit.path/queries/agent_id` | best-effort，不改变认证语义 |
| 旧启动器固定 INFO 级别与带时间戳的文件日志（没有 `LOG_LEVEL` / `LOG_FILE` 配置项） | server: `observability.logging.level/path` | 新增显式配置；默认仅 stderr，设置 path 后同时写文件 |

旧公共模板保存在 [历史配置](../history/config/)，供人工比对；不提供兼容加载或自动授权转换。

## 扩展导入与切换

| 旧导入/调用 | v3.8 |
| --- | --- |
| `from mutation_base import MutationBase, ManagedMutationBase, ManagedMutationPlan, ManagedMutationValue` | `from sql_safety_executor.skills import ...` |
| `from fastmcp.exceptions import ToolError`（业务 Skill） | `from sql_safety_executor.skills import OperationError` |
| `from audit import AuditLogger` | `from sql_safety_executor.observability.audit import AuditLogger`；路径显式传入 |
| `import skill_loader` 的全局缓存方法 | 实例化 `sql_safety_executor.skills.catalog.SkillCatalog`；服务运行时持有自己的实例 |
| `from db_adapter import ...` | `sql_safety_executor.database.models/base/mysql/sqlite/outcomes/registry` |
| `SQLiteAdapter(path)` / `MySQLAdapter()` | 使用显式 `DatabaseConfig`，或服务实例 `ConnectionRegistry` |
| `execute_sql(sql)` | 完整策略入口 `core.queries.query(runtime, sql, context, connection_id)` 或 MCP `query` |
| `python start_server.py` | 控制台命令或 `python -m sql_safety_executor serve --config ...` |

无 `sys.path` 注入。配置中可指定外部可信目录；解析后定义和源码必须在所声明目录边界内。Python Skill 可以执行任意进程权限内代码；这里不是沙箱。

切换：先生成并 `config check` 新文件，停止旧进程，再用锁定依赖和显式 TOML 启动。未使用令牌随停机失效。回退需要同步恢复代码、依赖和旧配置；出现过不确定写入时，先核对业务状态再决定下一步。

### 更新实际 Host 的启动配置

仓库中的 `mcp_config.json` 和私有 `mcp_config.local.json` 是模板，修改它们不会自动更新 Host 已保存的入口。Codex 使用 `~/.codex/config.toml`（或受信任项目的 `.codex/config.toml`）中的 `[mcp_servers.<name>]`，不能直接复制 `mcpServers` JSON 外层：

```toml
[mcp_servers.sql-safety-executor-mcp]
command = "/absolute/project/.venv/bin/sql-safety-executor"
args = ["serve", "--config", "/absolute/project/config/server.toml"]
```

备份后同时更新可执行文件和参数；采用实际已安装 v3.8 的环境，迁移期间可能是 `.venv-v38`。仍引用已删除 `start_server.py` 的条目会在握手前退出。保存后重新连接服务，必要时重启扩展；以当前 Host 会话能发现工具并调用 `list_connections` 为准。仅看“服务已配置”、离线 `check` 通过或独立 Client 成功，不能证明原会话已刷新。[Codex 官方 MCP 配置说明](https://developers.openai.com/codex/mcp)明确区分 Host 配置与扩展重启步骤。

## v3.8.1 查询错误与发布前接口决定（2026-10-13）

维护者确认项目未正式发布：旧 `.env`、旧启动入口、旧 SDK 迁移及假想历史调用方兼容，不纳入本轮修复；现有历史迁移说明保留供参考，不增加兼容加载或旧接口包装。更好的设计应主动报告并建议。版本仍为 3.8.1。

SQLite IN/NOT IN 裸关系也受 read.tables 与内置 PRAGMA 检查。当时限定名需匹配限定条目；本次 v3.8.2 已统一默认对象身份，`orders` 与 `main.orders` 授权等价，但不授权 temp／aux 等其它 schema。字符串关键字不触发 UNION／FROM 规则。MySQL CTE 使用连接测得的 ASCII 比较规则，能力未知时保守精确；含 UNION 的递归写法受 allow_union 控制。SQL／策略失败通过 success=false/error_code/error 与可选 hint 返回；Query Skill 不再以 Error: 字符串识别数据库失败。详情与当时未验证环境见[本轮记录](../validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md)。

## v3.8.1 读取函数限制

raw query 与 Query Skill 默认拒绝真实 GET_LOCK／RELEASE_LOCK／RELEASE_ALL_LOCKS／SLEEP／BENCHMARK 调用，两种数据库一致，无新增配置开关或全面函数白名单。含此调用的 Query Skill 模板启动时跳过并记录固定原因；字符串、普通列／别名和 CTE 声明不受该名字限制，同名自定义实际调用仍受限。不要把 Query Skill 当作例外，现有写入批准规则不变。v3.8.2 已将 SQLGlot 30.22.0 作为锁定运行依赖并接入 SQLite authorizer；下方按日期的小节保留 v3.8.1 阶段范围，当前契约见本文 v3.8.2 小节。见[范围与验收](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md)。

## 实体名称与最后身份补修（2026-10-14）

read.tables 和 Skill 声明的 tables 是名称声明，保留真实空白及引号字符；首个点号区分 schema 与 name，SQL 引用则从 token 保留组件。标签的 trim／lower 规则不能用于实体授权。SQL 语法中的一层引号／转义由策略从原始 token 解码，连续空白不会被整体压缩。元数据工具的标识符语法仍更窄。当前检查与已完成的最后重启核验见[最后验收](../validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md#提交前完整复核与补修2026-10-14)。


## 结构化关系与 schema readiness（2026-10-15）

read.tables=["main.orders"] 授权 FROM main.orders，不授权单个字面 FROM "main.orders"；read.tables=["main.main.orders"] 可授权 FROM main."main.orders"。声明字符串只在首个点分开 schema/name，不解析 SQL 引号；任意带点 schema 的声明语法未扩展。当时裸 grant 不自动授权限定引用；2026-10-19 收敛为下节的默认对象身份，裸名与默认限定名均可引用同一获准对象。元数据操作绑定默认 schema，不泄露字面点号对象。

默认 readiness 观察 SQLite main／配置的 MySQL database。其他显式 schema 的依赖返回 unverified_tables，不假报 missing_tables，也不由默认同名表替代；关闭 readiness 不增加表授权。full Skill 补充 schema 核验标志和两类数组，字符串展示不成为授权键。版本／运行依赖不变，生产 AST／authorizer 仍暂缓。见[本轮验收与支持边界](../validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md)。

## 2026-10-15：内部读取绑定与视图 readiness

表工具仍接收保守语法的裸 table_name；授权与生成 SQL 使用同一个结构化对象。SQLite 的 sample 和 get_table_summary(exact_count=true) 固定读取 main，避免同名 temp／aux 替代。MySQL 的生成读取与元数据绑定配置库，但同一会话的临时表仍可能遮蔽同名永久表；绑定配置库不提供临时对象隔离。配置数据库名逐组件引用，不能把 schema.name 作为单个标识符。

readiness 观察默认 schema 中 table／view，表发现工具仍只列普通表；关闭 readiness 不扩大授权。视图存在性不保证底层访问、列语义或可写。Mutation validate 的 valid 须为严格 bool、errors 若存在须为字符串 list、附加字段可 JSON 序列化；非法返回固定安全失败，执行阶段仍消费一次性令牌。无需新增 TOML 字段或 Agent 步骤；第三方 adapter 应实现 metadata_schema／get_read_relations。MySQL 临时对象生命周期另行设计。见[本批验收](../validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md)。

v3.8.2 元数据优化另外要求 adapter 实现 get_table_directory：仅返回有序 table_name／row_count，不执行用户数据扫描；昂贵估算放在 enrich_row_estimates，只处理公开工具已授权并截断的表。目录可免费取得估算的 backend 沿用默认补全方法；get_tables 便捷入口组合这两个方法。SQLite 统计仅在一次补全中批读，不新增 TOML 缓存开关，不自动 ANALYZE；limits.overview_tables／schema_tables 仍只改变返回上限，0 仍为不限。见[接口和验收](../validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md)。

SQLite 目录只排除字面 sqlite_ 内部前缀，合法 sqliteX... 表／视图不能被下划线通配误过滤；此过滤不扩大读授权。该补修没有新增配置字段；见[字面前缀验证](../validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md)。


## v3.8.2：结构化声明与会话约定

`tables` 简写继续按首个点分开 schema/name；含点、引号或空格的业务名称优先使用结构化组件，字符串显示值不作为授权键：

```toml
[connections.demo.read]
mode = "allowlist"
relations = [{ schema = "main", name = "orders" }, { schema = "main", name = "main.orders" }]
```

这分别授权 `main.orders` 和 `main."main.orders"`，不自动互通。省略 schema 表示默认 schema 的对象；默认对象的裸名和限定名共享授权，temp/aux 同名对象不能继承。普通读取不因此增加 Agent 工具步骤。表工具输入仍是裸业务名称，但改为方言支持包络加安全组件引用：SQLite 可含点、空格、引用字符和超过 64 字符的名称；空名/NUL 不支持。MySQL 物理名继续遵守其长度、BMP 和尾空格限制，不对合法名称 trim。

Skill frontmatter 可声明相同身份；声明是额外约束／依赖，不能增加 grant：

```yaml
relations:
  - schema: main
    name: main.orders
```

Query Skill full 返回 `analysis_complete`；不完整推断为 `inferred_tables=null`，不可执行，不能当成无依赖。readiness 只观察 main／配置的 MySQL database；其他 schema 仍为 unverified。

MySQL 可配置 `mysql.sql_mode = ["STRICT_TRANS_TABLES", "NO_ENGINE_SUBSTITUTION", "ANSI_QUOTES"]`。该数组是完整集合，不是增量；不要无意移除严格模式。省略则继承首个初始化物理会话的完整集合，后续连接／重连保持该约定；不是每次请求探测。只接受展开的模式名称，ANSI/TRADITIONAL 等组合别名返回配置错误。解析适配 ANSI_QUOTES、NO_BACKSLASH_ESCAPES、PIPES_AS_CONCAT 与 HIGH_NOT_PRECEDENCE；前缀 NOT 按实际模式分组，! 始终高优先级，中缀 NOT IN／BETWEEN／LIKE 仍按原语法处理。可信扩展经任意 execute 或完整写事务后会销毁会话，增加重新连接成本；直接操作私有 engine 的扩展自行维护约定。

注释规则按实际连接方言生效。SQLite hint形块注释是普通注释；MySQL只支持已识别的计划提示子集，SET_VAR／资源／超时／未知提示仍不支持。无新增配置开关，原始SQL／会话／批准契约保持；[范围与验收](../validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md)。

SQLite 使用连接独占及 `cached_statements=0`，authorizer 在编译至取完结果期间生效；固定目录／统计信息与受管写入为独立可信上下文；sample、精确计数及会读取数据的 SQLite 估算激活读取 guard，估算被拒时行数为 null，列／索引仍可用。视图可经已授权视图读取，底表不因此获得直接 grant。复杂／歧义来源、不支持的虚拟关系或预算超限返回明确拒绝；完整预算、缓存、同步取消和可信 schema/UDF 限制见[架构决议](../architecture/V3_8_2_SQL_SEMANTICS_ZH.md)。MySQL 无等价 authorizer，限定配置库本身不能防止同会话临时表遮蔽；会话销毁约定解决复用污染，不保证任意存储例程无副作用。


## 2026-10-19：范围、JSON／FTS 与执行保障

`all` 限定默认 schema；跨 schema 仍可用 allowlist 的结构化 `relations` 声明，不新增 all＋例外组合。`list_connections()` 的 policy 补充 `read_scope`／`default_schema` 事实，读取启用不等于存在性证明。SQLite 目录在明确授权下可读；COUNT(*) 与列读取保持一致，原始 PRAGMA／状态限制不变。

SQLite 支持内置 json_each/json_tree，MySQL 支持 JSON_TABLE；函数参数中的真实表、相关子查询和受限操作仍检查，不把内置函数名当作物理表 grant。SQLite FTS5 以已授权根表建立限定内部依赖，使用者无需直接授权影子表或 external-content 表；直接访问它们仍按原有 grant 检查。未知表函数模块不借用这些能力，其它虚表的普通扫描保持既有检查。

普通读取拒绝执行型 FOR UPDATE／FOR SHARE／LOCK IN SHARE MODE 及修饰，确认不执行的 EXPLAIN 仍可分析；执行型 EXPLAIN ANALYZE 继续拒绝。INTO @变量／@变量赋值与文件输出分别诊断；位置参数 ?／?1 不受此接口支持，可使用命名参数 Query Skill。

**authorizer 始终用于 SQLite 受控读取，本轮不增加 TOML 关闭开关。** 关闭会改变视图／实际对象的保障且增加两套行为维护成本，不能作为兼容性补丁。固定元数据／受管写入是内部限定上下文，不是对外的绕过参数。MySQL 没有等价 authorizer。新语义、成本及源码／安装／驻留状态见[补修记录](../validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md)。

## 2026-10-20：受管写入计划解析器观察期

```toml
[skills.mutation]
managed_plan_parser = "sqlglot" # 默认；临时回退可明确改为 "sqlparse"
```

只接受这两个小写字符串；拼错、布尔值或未知值启动报错。配置是进程快照，修改后重启并重新预览，旧令牌不会跨进程恢复。`config explain` 展示 `skills.mutation.managed_plan_parser` 的值和来源。公开写入示例已补字段，私有配置无需增加字段即可采用默认值。

选择项仅控制受管 INSERT／UPDATE／DELETE 计划的分类，不关闭读取策略、SQLite authorizer、写入准入、人工批准、一次性令牌或事务证据检查。无逐工具覆盖和失败后自动回退。命令式 Mutation 不通过它分类任意 Python 回调；Python Skill 仍是可信代码。

启动时没有实际执行连接，仅按 Skill 的 databases 尝试 SQLite／受支持 MySQL 模式候选；至少一种接受才加载。面向具体目标的发现／详情、预览和消费令牌后的执行前再次复验。MySQL 沿用每物理连接初始化／核验完整 sql_mode 的约定，不把另一个会话的一次探测永久套到整个池，也不新增每请求模式探测。

临时 sqlparse 路径保留旧的、忽略方言／模式的类型分类，因此回退不提供相同的语法与注释保证；它不修改现有绑定或批准边界。SQLGlot 也不是完整数据库验证器，部分数据库非法语法仍能解析。观察两至三个后续发布检查点后再决定删除回退、配置字段和依赖；不因时间到期自动移除。退出条件、差异、成本和验收见[迁移记录](../validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md)。

## 2026-10-20 补修后的绑定与元数据约定

DRR-124／125已完成源码／安装补修，维护者重启后另通过34/34限定原生核验：合法单句读取支持终止分号后普通注释；受管计划按实际方言／会话共享执行侧真实绑定身份，不再把字面／注释／引用名称中的冒号当参数。两解析器均获得绑定修复，但显式临时sqlparse仍保留旧尾注释分类限制，不等同于默认AST能力。实际占位符与声明目标仍须精确匹配，过去为绕过误认而声明的假参数应删除；无需新增配置或grant。

get_full_schema列读取先授权和截断，再经get_columns_batch。MySQL每批最多199个表名加1个配置schema绑定，按精确返回名称投影；SQLite基类组合原逐表接口。扩展backend若定制MySQL列行为，应考虑新批量钩子，不提供旧接口探测兼容。没有新TOML开关或Agent步骤。Query Skill启动首个候选允许即可停止；具体连接的发现／预览／执行及消费令牌后仍按实际上下文核验。

纯分类缓存键增加声明绑定名，值／授权／状态不缓存。请求内纯读取分析只做研究，未加通用缓存。实现、成本及已知范围见[补修记录](../validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md)。以下保留此前仅审计时的开放记录。

## 2026-10-20 前次审计时的两项功能限制

DRR-124／125的历史审计曾发现尾注释误报multiple_statements及计划字面冒号误作参数，sqlparse回退也不能解决；[原评估](../validation/v3.8/V3_8_2_FINAL_AUDIT_2026_10_20_ZH.md)保留当时未修状态。后续已共享真实绑定身份并正确忽略无执行内容的尾部节点，原SQL及指令注释检查保留，无需修改配置或grant。[当前实现及验收](../validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md)。

## 读取结果与条件依赖（2026-10-21）

query／Query Skill／sample 共用实际列标签检查、带类型的 binary/base64 与非有限 float 编码，以及编码后的紧凑 JSON 数据字符限额。首行超限允许零行，返回截断原因及缩小列投影提示；sample 同时受请求 1～20 行上限约束。目录／列／索引描述不受此限额，完整协议帧／通知、SQL 回显、数据库执行／fetch 和模型 token 也不由此限制。result_chars=1 无法容纳空数组，配置明确拒绝；0 仍关闭该限额。无新增开关或依赖。

Skill的JSON名称条件依赖保留builtin／stored／unverified三态。启用readiness时，SQLite观察两个名称，按TEMP→main→附加顺序保留实际身份及覆盖完整性；最多32个schema，共用观察查询超时。完整确认无同名存储对象才判builtin，部分观察保留unverified。非默认schema仍按已有范围无法核验；关闭时无新探测，实际模块／grant／authorizer继续即时核验，只缓存纯语法。[当前契约及验收](../validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md)。

内部adapter扩展钩子get_json_shadow_relations已由get_json_name_observation及专用不可变观察类型替换；None表示未观察，不保留假想旧接口兼容。不新增TOML开关或grant。DRR-136现已改用四类固定main绑定PRAGMA读取列／索引，业务名称不再遮蔽内部元数据函数；不新增TOML开关或扩大grant。索引N+2次目录读取及有界取回的代价见[补修记录](../validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md)。DRR-135/136统一重启后20/20限定原生通过；特殊附加／碰撞仍归属源码／安装。磁盘摘要不能单独证明驻留内存身份。
