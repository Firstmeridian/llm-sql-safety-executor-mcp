# v3.8 验收记录 · 2026-09-26

后续本地实测见[本地 live Review](V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：补充 Host 旧入口修复、真实 MySQL 连通、测试 SQLite 写入闭环和 9 次 Luna 原生 CLI 观察；用户重启后的[原生补测](V3_8_LIVE_REVIEW_2026_09_26_ZH.md#服务重连后的原生补测)另有当前会话直接调用及三组 Luna 六轮任务。以下历史运行结果保留各自范围，后续试验不覆盖或改写其失败与限制。

基线 `582822b`：Python 3.12.3 / FastMCP 3.0.2 / MCP SDK 1.26.0，676 passed、4 skipped。原工具参数与描述摘要已保存为 [baseline_contract.json](v3.8/baseline_contract.json)。原实测资料完整保存在 [v3.7](v3.7/)，本次不重写其失败与结论。

## 本次环境与自动化

新版本在独立 `.venv-v38` 中按 `uv.lock` 安装，保留原 `.venv` 和私有 `.env`。Python 3.12.3；FastMCP 4.0.10，MCP SDK / mcp-types 2.2.0，Pydantic 2.13.5，SQLAlchemy 2.1.1，sqlparse 0.6.0。

| 检查 | 实测结果 |
| --- | --- |
| 完整 pytest | 744 passed、4 skipped、1 个旧协议日志弃用告警（43.18 秒） |
| 类型检查 | pyright：0 errors / 0 warnings（最终源码检查） |
| 打包 | sdist + wheel 构建成功 |
| wheel 安装后验证 | 独立 `.venv-wheel`、依赖从锁导出，在仓库外临时 cwd 执行离线检查、提示词加载、现代/旧协议 stdio 查询成功 |
| 配置 | 未知字段/类型/版本、重复键、缺引用、错误默认、路径/cwd、三密钥源/边界/脱敏、只读默认、UNION、令牌范围、快照、关闭 Skills |
| 读取/写入回归 | 原 SQL/元数据/跨连接/Skill/事务结果/诊断清理/审计/遥测断言迁移；新增五层写入配置拒绝矩阵 |
| MRTR 状态机 | 首轮无写入、等待无事务、拒绝/取消、严格批准类型、缺答复重发、参数/目标/状态篡改、并发一次、过期、重启、64 KiB 拒绝、命令式拒绝；密封状态支持配置的长 TTL，重发不延长原提案期限 |
| 协议 | 真实 stdio `2026-07-28` 与 `2025-11-25`；参考 Host 现代审批往返；旧协议明确拒绝 MRTR，preview/execute 仍可提交 |
| 资源 | 两实例隔离、关闭连接/清空令牌、缺提示词启动失败清理、包导入无部署副作用 |

测试发现并修复的迁移问题包括：全局连接类型表遗漏、默认无读取授权的 tableless SQL、提交后序列化失败未在核心边界处理、框架/SDK 字段与取消接口变化、密封状态默认 600 秒与可配置预览期限不一致。最终结果只基于修复后的运行，不把此前失败计为通过。

旧测试中的配置夹具使用显式测试字典和临时 TOML；没有在应用包保留旧环境兼容。旧“错误配置静默回落”“default-only 授权”“仅项目内 Skill 目录”等断言已按新契约重写。测试数量增长包含新增覆盖，不能单独作为保证强度证明。

## 真实 Codex Host

Host：`codex-cli 0.155.0-alpha.16.3`；VS Code OpenAI 扩展 `26.917.62051`。测试实际启动的是 CLI，不能据此宣称扩展 UI 的审批行为已验证。通过隔离临时 SQLite、专用 server alias 和只记录协议元数据的透明 bridge，观察到初始化请求与响应均为 **MCP `2025-06-18`**；Host 声明 form/url elicitation，但这不等于支持现代 MRTR。

| 场景 | 工具调用 | 结果 | 实际 input / cached input / output tokens |
| --- | --- | --- | --- |
| 配置、明确 demo、禁止 blocked、未知 missing、请求审批 | 5 次 Host 尝试；4 次到达服务端 | 正确读取 demo；blocked 拒绝且未创建 DB；missing 拒绝且不回退；审批被 Host 拒绝发送 | 153994 / 141568 / 565 |
| “SQLite 中查询订单”歧义目标 | 1 次 list_connections | 明确询问连接，0 次数据库读取 | 59478 / 46592 / 118 |
| 默认连接后指定 demo、analytics 跨连接比较 | 3 次 query | 默认 demo=pending，显式 demo=pending，analytics=confirmed；结果匹配 | 81863 / 66560 / 285 |

三个场景观察到的误访问为 0、写入为 0。这里的 usage 来自 CLI `turn.completed.usage`，没有使用字符数估价；未提供完整可归因计费价格，故不推算金额。这些是单次行为观测，不证明所有模型/重复试验都无路由误差。

证据：[基础场景](v3.8/codex_summary.json)、[协议](v3.8/codex_protocol.jsonl)、[歧义](v3.8/ambiguous_summary.json)、[歧义协议](v3.8/ambiguous_protocol.jsonl)、[默认与跨连接](v3.8/default_cross_summary.json)、[协议](v3.8/default_cross_protocol.jsonl)。桥接器仅转发字节和记录方法、目标、工具名、协议，不自行实现协商。

实际阻断为 `MCP tool call requires approval, but approval policy is never`。因此 `request_mutation_approval` 没有到达服务端；没有审批表单、没有现代续接，**不能标为 Codex MRTR 已通过**。未修改安全注解或绕过 Host 审批来取得通过结果。服务端的旧协议拒绝和 preview/execute 可用性由参考 Client 自动化验证；当前 Codex headless Host 的人工 preview/execute 交互仍待 UI 验证。

## Copilot 与 MySQL 限制

可读取的 VS Code 环境版本为 **1.139.1**（commit `04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1`，WSL）。其可见远端扩展清单没有 Copilot，本环境不能操作用户的交互 UI。这不证明用户本地 UI 没有 Copilot。Copilot 扩展版本、协商协议、工具可见性、实际审批行为均为**未验证**，没有以其他客户端的结果代替。

未启用真实 MySQL 集成测试；四项显式可选实库检查保持 skipped。MySQL URL、脱敏、事务故障与诊断保护的 mock 回归正常；不将其等同真实服务器验证。

可复现实测命令：

```bash
uv sync --frozen --group dev
uv run pytest -q
uv run pyright
uv build
uv run python scripts/inspect_mcp.py --config /path/server.toml --mode auto
uv run python scripts/inspect_mcp.py --config /path/server.toml --mode legacy
uv run python -m examples.manual_mutation_approval \
  --config /path/server.toml --flow mrtr \
  --skill sample-update-order-status --params-file /path/params.json
```

CI 另行创建 wheel 环境运行 `scripts/verify_installed.py`。人工 Host 验收必须使用独立可丢弃数据库，记录实际版本/协议/能力与结果；不能把旧进程或旧协议结果标作新版 MRTR。重启使未使用提案失效；不确定写入必须先核对业务状态。

最终 `git diff --check` 无错误；公开四组配置通过相同离线加载器校验（MySQL 示例仅注入测试占位密钥，未连接）。CI 工作流已写入但未推送触发，不能将本地步骤通过称为 GitHub Actions 已运行。旧协议日志通知仍会触发 SDK 的弃用告警；现代调用已经改用服务端日志。

## 文档一致性复核

2026-09-26 对照当前模型、CLI、工具注册、审批 Host 和基线启动器复核文档：

- 将仍使用已删除脚本和 `.env` 的客户端指南归档为 v3.7 历史文档；当前指南改用包入口、显式 TOML 和 `scripts/` 工具。
- 为旧架构与 AutoGen 开发说明补充适用版本和当前入口；保留历史实测及原结论。历史 README 的链接仍指向历史客户端指南。
- 补齐工具契约指南的 MRTR、原提案期限和未知结果处理；明确风险登记中旧配置加载已移除，但私有 `.env` 文件保留，部分策略入口风险已在 v3.8 解决。
- 修正日志迁移表：基线启动器固定 INFO 与带时间戳文件，没有 `LOG_LEVEL` / `LOG_FILE` 配置项；新 TOML 显式配置日志，默认仅 stderr。
- `pytest -q -rs` 复跑为 **744 passed、4 skipped、1 warning（62.77 秒）**。四项跳过分别为 `test_db_adapter.py` 的三个 MySQL 集成测试和 `test_v372_write_outcomes.py` 的一个 MySQL 写入结果测试，均因未显式开启实库测试。
- 四组公开配置的 `check/explain` 再次通过；提示词检查、示例 SQLite 的 `SELECT 1` 和现代/旧协议 inspection 命令通过。协议分别为 `2026-07-28`、`2025-11-25`，默认 SQLite 样例均显示 7 个工具。未执行新的业务写入、真实 MySQL 或交互 Host 试验。

此次复核只修正文档；前述类型检查、wheel 和真实 Host 记录对应同一运行代码。

## README 原文恢复与增量更新复核

根据作者反馈，根目录中英文 README 恢复为基于 v3.7 原文的完整说明，保留原章节、设计讨论、实践经验、工具示例和每份 11 个图片引用；配置及接口按 v3.8 更新，归档文件不随本次恢复改写。

- 两份 README 各 24 个 JSON、6 个 TOML 代码块通过语法解析；本地文件、图片及 Markdown 锚点引用检查通过。
- 按文中说明组合三份 TOML，使用生产 `load_config()` 分别验证关闭 Skills、启用 preview/execute 和启用 MRTR 的配置。只使用临时目录与占位密钥，不连接数据库、不导入业务 Skill。
- 复核并移除当前使用说明中的 default-only 写入授权、旧启动命令和环境配置用法；修正工具数量、SDK 导入、日志通道及客户端验收范围。历史更新日志中的旧字段继续保留，避免改写历史。

本轮仅修改文档，未重跑完整运行测试或新增真实 Host/数据库验收；前述实测结果保持其原有适用范围。

## 双语文档与目录整理复核（2026-09-26）

- 将重构日志通过 `git mv` 移回根目录，补入 v3.8 的实现、兼容性、取舍和验证，新增中文维护版。原英文历史正文仅调整链接，不改写旧失败和结论。
- 将原历史指南目录中的 6 份文档通过 `git mv` 移到 `docs/guides/`，补充适用版本说明；文档归类按用途，历史接口和实测仍保留日期范围。
- `docs/README.md` 与 `README_ZH.md` 分别维护英文、中文索引；`config/examples/README.md` 与 `README_ZH.md` 说明四组模板、密钥来源、读取/写入权限、审批流程和复制后的相对路径。
- 64 份公开 Markdown 的 718 个本地链接与锚点检查通过；7 份搬迁文档与搬迁前正文对比通过，差异限于链接、新增适用说明和重构日志的新条目。
- 四组公开模板通过生产加载器及 CLI `config check/explain`，默认连接、Skills/Mutation 开关与别名和文档一致；MySQL 仅使用进程内占位密钥，并检查 explain 没有泄露该值。新增示例的 JSON/TOML/Bash 语法及审批 CLI 参数名称验证通过。

本轮没有修改运行代码或配置值，没有连接数据库、执行审批或写入，也未重跑全量 pytest、类型检查或真实 Host 验收。此前测试数字仍属于各自记录的运行。

## 本地补测后的最终文档核对（2026-09-26）

- 修正双语 README 及 v3.8 发布说明中仍将真实 MySQL 笼统列为“未验证”的旧摘要；明确后续连通/基础读取已通过，四项可选集成测试仍跳过，写入及故障恢复未验收。补入原生 Codex preview/execute、夹具恢复及三组 Luna 六轮任务，并将早期 MRTR 拦截与后续普通写入通路区分。
- 实施记录和双语重构日志同步引用后续证据；历史失败、参考 Client 与原生 Host 的协议范围、未知 usage、未运行的审批 UI/Copilot/远端 CI 均保持明确。
- 65 份公开 Markdown 的 745 个本地链接（包含 191 个 Markdown 锚点）通过检查；双语 README 与配置说明中的 50 个 JSON、14 个 TOML 代码块通过语法解析。
- 四组公开模板由生产加载器及 CLI `check/explain` 在仓库外 cwd 检查通过；MySQL 密钥仅使用临时占位值并验证解释输出脱敏，没有连接数据库或导入业务 Skill。本地 TOML、密钥、`.env` 与私有 Host 模板仍被 Git 忽略，未被跟踪。

本轮只修正文档，`git diff --check` 通过；未重跑全量 pytest、类型检查、打包或 live 调用，也未创建 Git commit。
