# v3.8.0 外部评审处理与 CI 复核 · 2026-09-27

> **2026-09-28 后续确认：** 修复提交 `139d53a` 的远端 [CI 36330541822](https://github.com/Firstmeridian/llm-sql-safety-executor-mcp/actions/runs/36330541822) 已完整成功：786 passed、4 skipped，类型、构建和安装后验证均通过。下文“尚未推送/待远端运行”保留编写时语境。新增 UNION 发现问题及本轮处理见[复评记录](V3_8_REREVIEW_2026_09_28_ZH.md)，不回写旧失败或旧本地结果。

评审基线：`1be44b41ee79839c0e975e747f0b1a3fc41453a8`。输入为维护者提供的 MCP/FastMCP 与 TOML 两份独立评审，原件及局部探针保留在私有 `local_archive/v380_review_evidence/`。本文记录对源码、真实依赖和生产加载器的复核；未直接把报告中的建议或隔离 stub 结果当作生产验证。

## 已确认问题与处理

两份报告的 F 编号各自独立，以下加前缀以区分。

| 编号 | 核实与修复 | 证据及边界 |
| --- | --- | --- |
| MCP-F01 / TOML-F03 | `list_connections` 已采用五层写入授权描述，测试仍要求旧兼容授权措辞。改为检查五层条件、默认连接同样受限及发现不授权；不恢复旧文案。 | 原提交 CI 确实失败，详见下节；运行权限实现不是此失败的原因。 |
| TOML-F01 | 配置端遗漏 profile 规范化。严格字符串校验后去首尾空白、转小写并去重；空白项启动报错，快照为 tuple。 | 真实 TOML → 工厂 → FastMCP 发现/详情/Query 执行/Mutation 预览及执行/MRTR 均验证排除；原数字/布尔拒绝仍保留。 |
| TOML-F02 | tableless Query Skill 的发现绕过读取准入判断，错误宣称 executable。发现、连接策略摘要与执行共用无 I/O 的读取准入谓词。 | deny、空 allowlist、非空 allowlist、all 四种情况；实际执行此前已拒绝，不宣称发现了读取绕过。Mutation 独立授权不受此谓词收紧。 |
| TOML-F04 | 语义异常在脱敏时退化为 `value_error`。模型改用静态 `PydanticCustomError` 类型码；加载器仍只输出文件、字段、类型码。 | 两个 CLI 命令覆盖密钥多来源、tables/mode、UNION、后端互斥、MRTR 开关；包含敏感标记的错误不回显原值/堆栈。 |
| MCP-F02 | 等待 MRTR 的遥测默认归属连接 A，实际目标是 B。审批结果加入已验证的 B 元数据；中间件读取真正的 MRTR 包装结果，不再为普通未知请求填默认目标。 | 默认 MySQL、实际临时 SQLite：等待、同提案重发、提交/拒绝/取消都记录 B/sqlite；等待 success=null；拒绝与取消保留对应 phase；重放与早期失败不伪造 A。 |
| MCP-F03 | MRTR 参考 Host 直接等待 provider，缺少外层期限与审阅一致性校验。两种流程复用 `_approve_view`，统一取消、单调时钟期限、审阅指纹及批准后有效期检查。 | 真实 FastMCP + SQLite 覆盖迟到批准、吞取消、阻塞、嵌套内容修改、等待中过期、provider 异常/非法值、正常批准/拒绝；失败无写入。 |

`tests/test_v38_review_regressions.py` 使用生产 `load_config()`、真实 FastMCP Client/SDK 和临时 SQLite，业务定义经过实际目录加载。故障注入只控制 provider、时钟或禁止意外 I/O，不复制权限、配置或协议实现。最初 36 项回归在修复前得到 **31 failed、5 passed**；最终扩展为 **42 项**，单独运行全部通过。原 preview Host 的回归保留，未用新流程代替旧流程验证。

## CI 原始失败与本次验证

[原始 GitHub Actions 运行 36252844733](https://github.com/Firstmeridian/llm-sql-safety-executor-mcp/actions/runs/36252844733) 的 SHA 为上述基线，validate job 的 pytest 为 **1 failed、743 passed、4 skipped、1 warning（29.57 秒）**。失败项是 `test_schema_tool_descriptions_guide_minimal_discovery_path`；pyright、构建、安装后 wheel 验证均被跳过。此前文档中的 744 passed 来自最后一次提示词修改之前，不能代表已提交 SHA 的验收。

本次锁定环境：Python 3.12.3、uv 0.12.19、FastMCP 4.0.10、MCP / mcp-types 2.2.0、Pydantic 2.13.5。使用全新临时源码副本、独立开发依赖环境及独立 wheel 环境；副本只包含版本控制文件及本次新增的测试、文档，不复制私有 `.env`、TOML、密钥、业务数据库或原虚拟环境。

| 检查 | 结果 |
| --- | --- |
| `uv sync --frozen --group dev` | 全新环境安装成功，未更新锁文件 |
| `uv run --frozen pytest -q -rs` | **786 passed、4 skipped、1 warning（47.04 秒）**；告警来自旧协议日志通知弃用 |
| 最终定向复核 `tests/test_v38_review_regressions.py` | **42 passed（8.07 秒）**；将视图修改用例收紧为原有嵌套 warnings 列表的原地修改后，在同一干净环境重跑；运行代码未再改变 |
| `uv run --frozen pyright` | **0 errors、0 warnings** |
| `uv build` | sdist 与 wheel 均成功 |
| 锁定运行依赖 + wheel 非 editable 安装、`scripts/verify_installed.py` | 仓库外 cwd：离线配置检查、残留 `.env` 隔离、包内提示词、`2026-07-28` / `2025-11-25` stdio 查询均通过 |

以上是本地按 CI 步骤进行的验证。修复尚未推送，不把它写成远端 GitHub Actions 已通过；旧失败运行保留，后续推送应产生新的运行记录。四项可选真实 MySQL 集成测试未启用。测试写入仅针对临时 SQLite；未修改本地部署配置或操作用户业务库。

## 文档复核与重启后的原生只读补测

2026-09-27 对照实现再次核对双语 README、配置示例、指南、重构日志、发布说明与风险登记。明确示例中的 `exclude_profiles` 必须是字符串数组；本轮只修正文档和追加验证记录，未修改运行代码、测试或部署配置。变更文档的本地文件/图片链接及 `git diff --check` 均通过；不因文档复核而把前述全套测试描述为本轮重新运行。

用户确认服务已重启后，当前 IDE 会话直接调用已连接的 `sql-safety-executor-mcp`，共 **4 次调用：3 次成功、1 次预期拒绝**。

| 调用 | 目标 / 输入 | 观察 |
| --- | --- | --- |
| `list_connections` | 无参数 | 成功返回 3 个连接；可见工具说明包含五层写入条件及默认连接同等受限。配置发现不代表数据库已检查。 |
| `query` | `live_test_sqlite`；`SELECT 1 AS review_probe` | 返回 `review_probe=1`，结果明确标注该目标和 `db_type=sqlite`。 |
| `get_skill_detail` | `live_test_sqlite`；`sample-monthly-sales-report-sqlite`；`detail_level=execution` | 返回参数定义及 `executable=true`；提示后续调用应保持同一连接。这里只检查发现/就绪结果，没有执行报表。 |
| `query` | 不存在的 `review_missing_connection`；相同常量查询 | 明确返回 unknown connection 错误，没有返回默认连接结果。 |

沿用上轮测试目标，不执行 Mutation，也不查询业务数据行。当前会话可见 10 个工具，未暴露 `request_mutation_approval`；因此本次不验证原生 MRTR、人工审批 UI 或等待遥测。原生调用未提供协商协议、Host 版本或 usage，不沿用旧记录推定这些值。MRTR、profile 排除与 deny/空名单发现修复仍以上节的隔离自动化证据为准。

## 契约变化与明确保留的限制

- `exclude_profiles=["DEMO", " demo "]` 现在等同 `["demo"]`。这会使此前拼写问题造成的排除失效得到纠正；空白项从静默接受改为启动错误。修改部署前运行 `config check/explain`，配置快照仍需重启更新。密钥内容不做此规范化。
- 读取准入谓词本身不访问数据库；动态 schema readiness 仍可能读取元数据。发现不替代执行时的完整检查；写入五层授权及原子消费点不变。
- FastMCP 4.0.10 的 `InputRequiredToolResult.meta` 为空，实际业务元数据在 `.input_required.meta`。本次按安装源码与真实往返修复，不能假定两个字段自动相同。
- 无可信结果元数据的普通失败记录将 `connection_id/db_type` 留为 null；这是信息缺失，不是默认目标。诊断仍使用单独校验的 scope。SDK 在中间件前拒绝篡改参数/密封状态时，可能没有本项目遥测行；不宣称遥测是完整审计账本。
- Host 审批期限独立于服务端 token TTL。共享保护可在有缺陷的 provider 返回时拒绝迟到批准，但不保证终止恶意或永久阻塞的进程内 Python。外部取消/断连仍可能使提案等待 TTL；消费后失败不恢复令牌，不自动重试不确定写入。

| 设计项 | 当前结论 |
| --- | --- |
| D01 可信请求级任务范围 | **部分完成**：部署权限、显式目标及精确提案绑定已实现；`OperationContext` 不是可信任务授权载体。尚无经认证 Host 提供的每请求 grant，不能声称服务端独立理解/验证人的自然语言意图。作为后续独立设计，不借本次修复新增不完整认证接口。 |
| D04 稳定目录 / 动态 readiness 分层 | **暂缓独立接口拆分**：定义已快照，渐进披露保留，但列表/详情仍组合动态 readiness。性能改进需另行测量，不引入可能陈旧的授权结果缓存。 |
| D07 操作级可观测性 | 本次修复目标归属及拒绝/取消阶段；跨轮关联标识、完整 trace 与 OTel 导出仍暂缓，不记录 token 来冒充关联方案。 |
| 审批模式与部署 | 继续可信 Host 模式 A、默认关闭的托管单语句 MRTR、单进程内存提案、best-effort 审计。Tasks、远程多用户、独立审批认证、分布式恢复保持暂缓。 |
| 原生客户端验收 | 本轮参考 Host 回归不代表 Codex/Copilot 原生 MRTR 或人工审批 UI 通过。历史原生试验版本、协议缺失、失败及限制仍见原实测记录；本轮未扩大结论。 |

实现细节与使用约定同步于[配置指南](../guides/CONFIGURATION_ZH.md)、[安全边界](../security/V3_8_SECURITY.md)、[实施记录](../architecture/V3_8_IMPLEMENTATION_ZH.md)和根目录双语重构日志。历史评审报告、已失败 CI 及早期实测结论保持原样。
