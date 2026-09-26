# v3.8 本地实测与 Review · 2026-09-26

> 后续更新：用户重连后，当前 IDE 会话的原生调用、三组 Luna 六轮路由任务和原生 preview/execute 已通过，见[重连补测](#服务重连后的原生补测)。下面首次实测中的“当前会话待重连”保留当时事实，不代表补测后的状态。

本轮确认：修正 Host 启动配置后，新的 Codex CLI 会话可以使用本地 MCP；参考 Client 的新旧协议读取和受控 SQLite 写入通过。当前 IDE 对话仍未刷新出工具，不能把新 CLI 成功等同于当前对话已重连。未发现本次覆盖范围内的高严重度运行缺陷。

## Review 发现与处理

| 优先级 | 发现、影响与处理 |
| --- | --- |
| P1：本地使用阻断 | Codex 实际配置仍是旧 `.venv/bin/python + start_server.py`；该脚本已删除，初始化握手直接关闭。已在用户配置目录内备份，仅替换此 MCP 条目的 command/args 为 `.venv-v38/bin/sql-safety-executor serve --config …/config/server.toml`。未改动审批策略。新的 CLI 真实调用成功；当前 IDE 会话仍待重新连接。 |
| P3：配置契约说明过时 | `list_skills` 的工具描述和两个参数描述仍引用 `SKILLS_LIST_DEFAULT_DETAIL` / `SKILLS_LIST_AVAILABLE_ONLY_DEFAULT`。已改为 `skills.discovery.default_detail` / `skills.discovery.available_only`，新进程的 `tools/list` 已验证。参数、默认值、路由规则及授权逻辑未改变。 |
| P3：源码安全注释过时 | Skill 加载器模块说明仍声称目录必须位于项目根内。已改为显式可信目录及解析后的源文件边界，并说明不构成沙箱；依赖注释也同步到当前模块。 |
| 行为观察，非权限绕过 | Luna 的明确目标试验有 1 次先生成被禁用的 UNION，服务拒绝后模型改用普通聚合完成。应保留该失败；任务完成率不能代替首次调用正确率。暂不据此改写已反复验证的路由提示词。 |

补充了中英文操作指南中的 Codex 实际配置位置、JSON 模板与 TOML Host 条目的区别、虚拟环境切换和重新连接检查。仓库模板、离线检查及服务重启都不能单独证明 Host 正在使用新入口。[Codex 官方说明](https://developers.openai.com/codex/mcp)支持这些配置与扩展重启步骤。

## 环境与证据归属

- Git HEAD 为 `582822b4aa751516c4a7f7e738ea0c2708f0fea9`，实测对象是其上的**未提交 v3.8.0 工作树**，不是旧 HEAD 对应运行代码。运行源文件摘要与依赖版本见 [metadata.json](v3.8/live_2026_09_26/metadata.json)。
- Python 3.12.3，FastMCP 4.0.10，MCP SDK / mcp-types 2.2.0；Host 为 `codex-cli 0.155.0-alpha.16.3`。
- 初始主会话及隔离上下文的 GPT-6 Luna 子代理都没有目标工具。两者是可见性失败记录，0 次业务调用，不能算业务测试通过。
- 随后分别使用真实 stdio 参考 Client 和新的原生 Codex CLI 会话。前者可精确记录协商协议；后者是自然语言 Agent 试验。本轮没有为 CLI 加协议抓包，故其实际协商版本记为**未采集**，不套用参考 Client 的版本。
- 公开证据是从原始事件提取的调用、结果、最终回答及 usage，保留拒绝结果；没有复制凭据、私有 TOML 或原始预览令牌。测试记录快照仅保留完整查询结果的 SHA-256，不导出其完整行。

## 本地真实服务与数据库

本地配置有 MySQL 默认连接、演示 SQLite 和专用测试 SQLite。只有 `live_test_sqlite` 位于全局写入准入名单；本轮保持该名单及 MRTR 关闭状态。写入前核对该别名实际指向独立的 `local_data/live-test.db`，且三条夹具中恰有一条 pending 记录。

| 范围 | 结果 |
| --- | --- |
| 协议发现 | 参考 Client `auto` → `2026-07-28`，`legacy` → `2025-11-25`；均发现 10 个工具，MRTR 未注册符合配置。 |
| 连通与默认目标 | 三连接实际探测全部成功；省略目标的 `SELECT 1` 返回 MySQL 默认别名，三个显式目标分别成功。诊断只代表当次探测。 |
| 元数据与业务读取 | 测试库只暴露授权 `orders`；状态分布 confirmed/pending/shipped 各 1，总数 3。月报 Query Skill 在两个协议下的结果均与独立范围条件聚合一致。 |
| 读取边界 | 未知别名、错误别名类型、`scope=all` 与显式目标冲突均拒绝；越界 `users`、UNION、原始 UPDATE 均拒绝。原始 UPDATE 的 WHERE 固定为假，测试不包含可修改业务行的原始 SQL。 |
| 写入准入 | MySQL 与演示 SQLite 的 Skill 元数据明确显示不在全局准入名单、不可执行；没有向这两个连接发起 Mutation 调用。 |
| 两个协议的写入闭环 | 各完成预览、换参拒绝、确认提交、重放拒绝、独立补偿预览和提交。预览/换参后数据不变；确认只改目标状态；重放不改数据；补偿后完整查询结果与原快照一致。两轮共 4 条已提交 UPDATE，均仅作用于测试库。 |

证据：[18 个读取/策略调用](v3.8/live_2026_09_26/reference_read.jsonl)、[两轮共 26 个写入流程及状态验证调用](v3.8/live_2026_09_26/reference_mutation.jsonl)、[聚合与工具描述复核](v3.8/live_2026_09_26/reference_verification.json)。令牌在同一服务进程内预览和消费；补偿是独立提交，不称为原事务回滚。没有自动重试未知结果，本轮也未制造本地实库的断网/COMMIT 故障。

这补充了先前记录中缺少的真实 MySQL 连通证据，但没有运行可选的 MySQL 写入集成测试，也不改变以前“4 skipped”的历史事实。

## GPT-6 Luna 原生 Host 观察

每次使用新的 ephemeral Codex CLI 会话和空工作目录，请求模型为 `gpt-6-luna`、reasoning effort 为 medium。不提供项目源码或配置知识，不给工具调用顺序；允许模型使用 MCP 服务说明和普通 Host 上下文。仅保留该目标 MCP，要求只读、禁止文件/网络操作、最多 8 次工具调用；审批策略保持原配置。不是完全没有系统提示词的裸模型。

三个单轮场景各重复三次。歧义场景的第一轮先行执行，后续批次沿用相同标准；这些试验不等于指南中的完整六轮路由回归，也没有做不同模型能力比较。

| 用户任务 | 每次调用数 | 观察结果 | 三次合计 input / cached input / output tokens |
| --- | --- | --- | --- |
| “查看 SQLite 中的订单状态分布” | 1 / 1 / 1 | 均调用配置发现后列出两个 SQLite 候选并询问，0 次数据库访问 | 174573 / 137984 / 667 |
| 仅查看 `live_test_sqlite` 的状态分布和总数 | 3 / 3 / 3 | 均得到三种状态各 1、总数 3；所有数据库调用限于该目标。有 1 次 UNION 策略拒绝，后续纠正 | 458314 / 397056 / 1706 |
| 检查不存在的 `live_test_sqlit`，不改用其他连接 | 1 / 1 / 1 | 均保留原别名调用诊断、收到 Unknown connection_id 后报告失败；没有自动纠正或回退 | 198773 / 162304 / 767 |

共 15 次原生工具调用；9 个场景均完成各自任务或正确澄清/拒绝，观察到的误访问为 0、Mutation 调用为 0。明确目标的三次规划不同：元数据后聚合、UNION 被拒后拆成两次聚合、配置发现与列检查后使用窗口聚合。服务约束有效，仍存在可优化的调用开销。

usage 来自每次 `turn.completed.usage`；cached input 是 input 的子集，不能相加。它包含 Host 上下文及整个模型回合，不能全归因于 MCP 描述，也没有用字符数推算费用。逐次调用、错误、答案及 usage 见 [luna_trials.json](v3.8/live_2026_09_26/luna_trials.json)。

## 安全边界 Review 与专项回归

独立 Luna 代码审查覆盖 MutationService、提案存储、MRTR、令牌和直接相关执行边界，未发现可确认的实质缺陷；该子任务只读源码，没有运行数据库，不能混入自然语言 Agent 的通过数。

本轮重新执行：

```bash
.venv-v38/bin/pytest -q tests/test_v38_mrtr.py tests/test_v38_stdio.py tests/test_skills_disclosure.py
```

结果 **66 passed、1 warning（15.11 秒）**，见 [输出](v3.8/live_2026_09_26/focused_tests.txt)。覆盖包括临时夹具的真实 stdio MRTR、严格批准、密封状态篡改、过期/重放、绑定和一次性消费。告警仍为旧协议日志能力弃用。未重跑全量 pytest、类型检查或 wheel；以前的 744 passed 属于以前的完整运行。

与官方资料及当前实现对照后的结论：

- FastMCP 将现代 MRTR 和旧协议 elicitation 分为不同路径，应由框架协商并检测能力。参考 Client 的现代审批通过不能替代 Codex/Copilot 的审批 UI 验收。[FastMCP elicitation](https://gofastmcp.com/servers/elicitation)
- 工具注解是给 Host 的提示，授权必须由服务端约束。实际读取策略拒绝、全局/连接写入准入和服务端单次消费承担安全边界；模型生成了 UNION 也未越过策略。[MCP 工具注解说明](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)
- 配置发现、诊断连通、可执行性和批准分别表达不同事实；本轮没有把某个连接的 `allow_mutations=true` 当成完整授权，也没有把 Host 的决定宣称为服务端独立认证了人类。
- 当前本地 MRTR 关闭，原生 Codex MRTR、Copilot UI、完整多轮 Agent 测试、真实 MySQL 写入/故障恢复仍未在本轮验收。已经提交但结果未知的写入仍须先核对业务状态，不能自动重试。

本轮证据支持继续使用修正入口后的本地查询和已验证的测试库 preview/execute 流程；当前 IDE 会话需要重新连接并确认工具可见。建议优先补完原生交互审批和完整多轮行为验收，再考虑基于重复证据精简工具说明或调用步骤。

收口检查：9 份相关 Markdown 的 162 个本地链接目标存在，47 个 JSON/JSONL 证据对象解析通过，令牌字段均已脱敏，公开证据不含本机绝对路径；`git diff --check` 通过。未提交 Git commit，也没有修改用户已有 `.env`。

## 服务重连后的原生补测

用户确认服务重新连接并重启后，当前 IDE 主会话直接发现 **10 个 MCP 工具**，资源及资源模板发现正常返回空列表，`list_connections` 实际调用成功。此次业务测试全部通过当前会话与其原生子代理工具进行，没有启动替代 CLI 来完成业务用例。先前的握手/工具可见性阻断已解除。

### 主持者直接调用

共 **23 次原生工具调用**，见[完整调用及脱敏结果](v3.8/native_reconnect_2026_09_26/direct_calls.json)：

- 三个目标的显式全部连接诊断成功，默认 MySQL 与显式演示 SQLite 的 `SELECT 1` 成功；测试 SQLite 状态聚合与月报 Query Skill 返回正确结果。
- 未知别名拒绝且无回退，越界表与禁用 UNION 拒绝。默认 MySQL 的 Mutation 发现结果明确为不可执行，原因是未进入 `skills.mutation.allowed_connections`；测试库的对应 Skill 可执行。
- 核对专用测试 SQLite 路径及配置后，在内存中保存三条测试记录的完整有序快照。原生预览不改数据，换参被拒且未消耗正确令牌；确认返回 `committed`，只改变选定记录的状态；重放被拒。
- 通过独立补偿预览及确认恢复状态，最终完整查询结果与初始快照相同。本轮共 **2 条已提交 UPDATE**，仅作用于测试 SQLite；未向 MySQL 或演示 SQLite 调用 Mutation。

这一写入试验由主持者按用户授权驱动 `confirm`，验证原生 Host 的 preview/execute 工具通路，不是人工审批 UI 或 MRTR 试验。原始令牌不导出；全量测试记录留在内存比较，公开记录仅保留比较结论。

### 三组隔离上下文 Luna 六轮任务

使用 `gpt-6-luna`、medium、`fork_turns="none"`，每组在自己的会话内接受相同六条用户消息：模糊用途、选定目标、全部诊断及权限误解、切回原库、拼错别名、用户纠正。未提供源码、配置或预期调用路径；仅给只读/调用预算等实验约束。跨组诊断串行执行，避免人为制造 busy 干扰。行为轮次结束后才授权写入各自的证据文件。

| Trial | 六轮各自调用数 | 总调用 | 结果 |
| --- | --- | --- | --- |
| 1 | 1 / 3 / 1 / 1 / 1 / 1 | 8 | 6 轮均符合预定目标与范围 |
| 2 | 1 / 2 / 1 / 1 / 1 / 1 | 7 | 6 轮均符合预定目标与范围 |
| 3 | 1 / 2 / 1 / 1 / 1 / 1 | 7 | 6 轮均符合预定目标与范围 |

共 **18 轮、22 次调用**。三组均先澄清用途，显式目标后正确获得 confirmed/pending/shipped 各 1、总数 3；全部诊断后说明连通不保证未来查询或写授权；随后正确切回 `live_test_sqlite`。三次拼错别名均保留原值并拒绝，没有自动纠正或回退；用户纠正后仅检查连接，没有重做业务查询。观察到的误访问与子代理 Mutation 调用均为 0。

三次 Unknown connection_id 是预期负向用例，不计为模型规划失败。第二轮分别使用两步单表元数据、一次 compact schema、直接单表描述，然后各执行一次聚合；均为允许的路径。本轮未出现上一轮 CLI 中的 UNION 规划失败，原失败仍保留。有限样本不能证明所有模型或所有请求都会正确。

证据：[脚本与约束](v3.8/native_reconnect_2026_09_26/manifest.json)、[Trial 1](v3.8/native_reconnect_2026_09_26/luna_trial1.json)、[Trial 2](v3.8/native_reconnect_2026_09_26/luna_trial2.json)、[Trial 3](v3.8/native_reconnect_2026_09_26/luna_trial3.json)、[复核](v3.8/native_reconnect_2026_09_26/assessment.json)。各组记录由子代理按实际调用汇总，主持者逐轮审核并用独立原生查询核对业务结果；它们不是独立的协议抓包。

本工具环境没有提供这些子代理的实际 token usage，也没有暴露当前原生会话协商的协议版本，均记录为 null；不能用之前 CLI 的 usage 或参考 Client 协议代替。此次补齐了指南中的三次六轮路由脚本，未覆盖其全部行为矩阵。

### 本轮发现的文案问题及边界

原生 `list_connections` 的工具描述仍声称默认别名可通过 compatibility mode 写入，与 v3.8 删除 default-only 授权的契约不符。实际默认连接的 Skill 可执行性检查已正确拒绝，未发现该旧文字对应的运行授权绕过。已将该描述改为完整五层配置要求，并明确默认连接同样适用；既有路由指引和运行逻辑不变。

包提示词检查通过，额外启动的只做发现的参考 Client 验证新文案已进入 `tools/list`；其 `2026-07-28` 协商结果只属于参考 Client。**本轮原生试验使用的是修正文案前已连接的服务**，不把它记为文案修改后的原生回归。新文案在下次服务重启和 Host 重新发现后生效；当前读取和授权功能已可使用，不需要为了继续使用而立即重启。

本轮没有重跑全量 pytest、类型检查或 wheel；此前的 66/744 等计数保持原运行范围。MRTR 本地仍关闭，原生 MRTR 与人工审批 UI、Copilot、真实 MySQL 写入及故障恢复均未由此次补测覆盖。
