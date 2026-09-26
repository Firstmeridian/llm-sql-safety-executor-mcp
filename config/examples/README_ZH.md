# 配置示例说明

[English](README.md) | 中文

本目录提供 v3.8 的公开 TOML 模板，与服务使用同一个严格配置加载器，不包含真实部署密钥。下方命令从仓库根目录运行，先执行 `uv sync --frozen --group dev`；安装后的命令也可在仓库外通过绝对 `--config` 路径使用。

## 选择模板

| 目录 | 连接与默认目标 | Skills | 写入授权 |
|---|---|---|---|
| [sqlite](sqlite/server.toml) | SQLite `demo`，默认 `demo` | 关闭 | 无 |
| [mysql](mysql/server.toml) | MySQL `reporting`，默认 `reporting` | 未引用 Skills 文件，关闭 | 无 |
| [multi](multi/server.toml) | SQLite `demo`、MySQL `reporting`，默认 `demo` | 启用 Query Skills | 全局写入关闭 |
| [mutation](mutation/server.toml) | 独立 SQLite `demo_write`，默认 `demo_write` | 启用 | 仅允许 `demo_write` 上的 `sample-update-order-status`，MRTR 关闭 |

SQLite 读取白名单为 `orders`、`users`、`products`，MySQL 仅为 `orders`；写入模板的读取白名单也仅为 `orders`。四组模板均未启用 UNION。白名单表示授权范围，不证明这些表真实存在；Query Skill 是否可执行还取决于数据库类型、声明的连接范围/profile 和 schema 就绪检查。

## 三份文件分别配置什么

每份被引用的 TOML 都声明 `schema_version = 1`。

- `server.toml`：连接文件、可选 Skills 文件及必填的默认连接；还可配置工具、输出限制、公共超时、日志和遥测。
- `connections.toml`：每个连接独立声明后端、数据库身份、凭据、读取范围和连接级写入权限。
- `skills.toml`：可信定义目录、发现/就绪检查、全局写入准入、预览令牌、可选 MRTR 和审计。省略主文件对它的引用即可关闭 Skills；明确引用但文件缺失会报错。

启动必须传 `--config`，不会搜索 `.env`，也没有隐式 `DB_*` / `SKILLS_*` 配置覆盖。未知字段和非法类型会校验失败。配置内路径相对于声明它的 TOML 文件解析。配置、密钥和加载后的 Skill 定义均保持快照，修改后需要重启。

## SQLite：检查与启动

SQLite 模板使用仓库自带的 `sample_data/demo.db`，无需凭据：

```bash
uv run sql-safety-executor config check --config config/examples/sqlite/server.toml
uv run sql-safety-executor config explain --config config/examples/sqlite/server.toml
uv run sql-safety-executor serve --config config/examples/sqlite/server.toml
```

`check` 和 `explain` 使用同一加载器解析配置与密钥来源，不连接数据库、不导入业务 Skill。`explain` 会脱敏密钥，并解释生效设置与功能禁用原因。两者通过不代表数据库可连或 Skill 已就绪。`serve` 启动 stdio MCP 进程，正常使用时通常由 Host 携带这些参数启动。

## MySQL 与多连接

按实际部署设置 MySQL 的 host、user、database 与读取表名单。`mysql` 和 `multi` 模板都显式从启动进程解析 `REPORTING_DB_PASSWORD`。例如在 Bash 中：

```bash
read -r -s -p "Reporting database password: " REPORTING_DB_PASSWORD
export REPORTING_DB_PASSWORD
uv run sql-safety-executor config check --config config/examples/mysql/server.toml
uv run sql-safety-executor config check --config config/examples/multi/server.toml
```

IDE Host 也必须从自身启动环境获得该变量；仅在 `.env` 中写值不会生效。加载时会解析所有已配置连接的凭据，因此多连接模板即使默认 SQLite，也需要该变量。

也可在私有连接文件中改用密钥文件，三种来源只能选一种：

```toml
mysql.password = { file = "secrets/reporting.password" }
# 其它来源：{ env = "REPORTING_DB_PASSWORD" } 或 { value = "..." }
```

将此键放在目标 `[connections.<id>]` 表中，替换现有 `mysql.password`，不要重复定义。路径相对于该连接文件解析。密钥文件必须是非空 UTF-8，最大 64 KiB；空白和末尾换行都属于密码内容。读取失败不会尝试其它来源。不要把真实凭据写进受 Git 跟踪的模板。

多连接调用省略 `connection_id` 时使用显式默认目标；未知别名直接拒绝，不回退。读取工具不会自动查询所有连接；仅 `check_connection(scope="all")` 显式诊断所有配置目标，调用仍需符合用户允许的范围。

## 受控写入示例

此模板特意使用独立的可丢弃数据库，先创建一次：

```bash
uv run python scripts/setup_sqlite_demo.py --output local_data/mutation-demo.db
uv run sql-safety-executor config check --config config/examples/mutation/server.toml
```

初始化脚本拒绝覆盖已有文件。初始订单为 `id=1`、`status="pending"`。将下方参数保存到私有 JSON 文件，再传入其路径：

```json
{"order_id": 1, "new_status": "confirmed"}
```

```bash
uv run python -m examples.manual_mutation_approval \
  --config config/examples/mutation/server.toml --flow preview \
  --skill sample-update-order-status --connection-id demo_write \
  --params-file /absolute/path/to/params.json
```

参考 Host 展示审阅内容，仅接受期限内输入的字面值 `APPROVE`。批准后会真实修改该测试数据库。写入必须同时通过五项配置条件：Skills 开启、全局写入开启、连接在 `allowed_connections` 内、连接允许写入、Skill 在连接白名单中。读取白名单不是 Mutation SQL 的通用写入范围。若要使用 reset Skill，还须显式将它加入连接白名单，公开模板没有授予它权限。

使用 MRTR 时，在私有 Skills 文件中将 `skills.mutation.mrtr.enabled` 设为 `true`，参考 Host 传入对应部署的 `--config` 和 `--flow mrtr`。它要求 MCP `2026-07-28`、客户端表单能力及托管单语句 Skill。旧客户端仍可使用 preview/execute；不支持 MRTR 的调用会明确拒绝。服务端信任 Host 收集的决定，不独立认证真实人类。结果未知或响应丢失时不得自动重试，须先核对业务状态。重启会使未使用提案失效。

## 复制到本地配置时的注意事项

本地部署可使用已忽略的 `config/server.toml`、`config/connections.toml` 和 `config/skills.toml`。复制前检查是否已有配置，保留当前设置与密钥。应复制主文件实际引用的全部文件，并调整因声明文件目录变化而改变的相对路径：

| 字段 | 位于 `config/examples/<name>/` 的模板 | 复制到 `config/` 后 |
|---|---|---|
| SQLite demo `sqlite.path` | `../../../sample_data/demo.db` | `../sample_data/demo.db` |
| 写入 demo `sqlite.path` | `../../../local_data/mutation-demo.db` | `../local_data/mutation-demo.db` |
| `skills.directory` | `../../../skills` | `../skills` |
| 写入 demo `skills.audit.path` | `../../../logs/demo-mutations.jsonl` | `../logs/demo-mutations.jsonl` |
| `files.connections` / `files.skills` | 同级文件名 | 文件仍同级时无需修改 |

`config/*.toml`、`config/secrets/` 和 `mcp_config.local.json` 已被 Git 忽略；`config/examples/` 是公开、受跟踪的模板目录。其它自定义位置需要另行添加忽略规则。Python Skill 是可信代码，目录边界检查不是沙箱；应使用显式且经过审查的路径。

先检查本地副本，再让 Host 指向其绝对 `server.toml` 路径。切换版本前停止旧进程；回退需同时匹配代码、依赖和配置。完整字段、默认值及新旧映射见[配置与迁移指南](../../docs/guides/CONFIGURATION_ZH.md)，另见[客户端指南](../../docs/guides/TEST_MCP_CLIENT_GUIDE.md)和[验收限制](../../docs/validation/V3_8_VALIDATION_ZH.md)。
