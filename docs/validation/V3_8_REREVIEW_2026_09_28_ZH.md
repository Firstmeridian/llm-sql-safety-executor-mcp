# v3.8.0 复评处理记录 · 2026-09-28

> **2026-10-01 后续：** 当前 MRTR 原生与协议验收状态见[补充记录](V3_8_MRTR_NATIVE_2026_10_01_ZH.md)。下文保留当时结果，不代表后续所有项目均未验收或均已通过。

复评基线：`139d53a82abf16431f3beb84fc037ed8e195119d`。维护者提供的 MCP/FastMCP、TOML 两份复评及局部探针保留在私有 `local_archive/v380_review_evidence(139d53a)/`。本记录独立核对源码、远端运行和实际回归，不把报告的静态推断等同于已运行测试。

## 结论及问题状态

上一轮六类问题已关闭：MCP-F01/TOML-F03 的旧文案断言、MCP-F02 的 MRTR 遥测归属、MCP-F03 的参考 Host 保护、TOML-F01 的 profile 规范化、TOML-F02 的禁读无表查询发现、TOML-F04 的安全语义错误码。三份 TOML、共享写入执行边界和既有审批保护无需重做。

本轮新增 TOML-N01 属于 **P2 发现与执行不一致**：允许读取但禁止 UNION 时，目录可能显示 UNION Query Skill 可执行，实际执行仍拒绝。已在真实框架中复现并修复；不是执行授权绕过，也不是上一轮读取总门槛修复回退。MCP 复评没有提出新的实现阻断项；原生 MRTR 人工审批验收仍独立待办。

## 已确认的远端 CI

通过 GitHub Actions 页面、run/job 元数据和原始 job 日志重新核实：

| 项目 | 结果 |
| --- | --- |
| SHA | `139d53a82abf16431f3beb84fc037ed8e195119d` |
| Run / Job | [36330541822](https://github.com/Firstmeridian/llm-sql-safety-executor-mcp/actions/runs/36330541822) / [108651490089](https://github.com/Firstmeridian/llm-sql-safety-executor-mcp/actions/runs/36330541822/job/108651490089) |
| Workflow / 触发 / 结论 | `tests-and-wheel` / push / completed、success |
| Job 完成时间 | 2026-09-27 15:43:33 UTC |
| 锁定依赖同步 | 成功 |
| pytest | **786 passed、4 skipped、1 warning（33.35 秒）** |
| pyright | **0 errors、0 warnings、0 informations** |
| 构建 | sdist 与 wheel 成功 |
| 非 editable wheel 安装后验证 | 仓库外配置检查、包内提示词、`2026-07-28` / `2025-11-25` stdio 查询成功 |

因此，`139d53a` 的远端验收阻断已解除。[9 月 27 日修复记录](V3_8_REVIEW_FIXES_2026_09_27_ZH.md)中“尚未推送、待远端运行”保留为当时状态；`1be44b4` 的失败运行仍保留。本轮新增 N01 修复尚未提交/推送，上述远端成功不能用于宣称新补丁也已通过远端 CI。

## N01 修复及设计取舍

`skills/access.py::_skill_availability_state()` 在 Query Skill 通过读取准入和声明表范围检查后，对已缓存的 SQL 调用执行路径同一个 `_validate_sql_query_policy(runtime, sql, connection.policy)`。它覆盖现有只读结构、UNION 与解析后表范围等固定策略，失败时设置 `policy_allowed=false` 和原因；默认发现隐藏，完整列表和详情解释拒绝。缺失 SQL 快照时同样不能声明可执行。

- 始终传入当前已解析连接的策略，不按默认连接删除目录中的 UNION 模板。另一明确授权连接仍可使用同一 Skill。
- 使用启动时 SQL 快照，不重新读取源文件，不替换或插值用户参数，不执行数据库 SQL。
- 不跨连接缓存授权结果，也不新增响应缓存。每次发现对候选 Query Skill 做静态预检，代价是额外解析 CPU；本次未做大目录性能基准。日后优化需保留目标隔离和执行复核，不能把旧可用性当作授权。
- 保留原有声明表、profile、连接类型/范围和动态 readiness 约束；Mutation 的五层授权及执行逻辑不变。
- 静态预检无数据库 I/O，不代表整个发现工具无 I/O：启用的动态 readiness 仍可能查询元数据。`executable=true` 不承诺参数有效、数据库可达、完整 SQL 方言兼容或最终执行成功。

## 回归和本地验证

新增 `tests/test_query_skill_static_policy.py`，共 **6 项**。生产 TOML 加载器和真实 FastMCP Client 使用隔离的临时 SQLite；修复前 **6 failed（2.22 秒）**，均在发现错误声明可执行处失败。

| 场景 | 验证内容 |
| --- | --- |
| UNION 两连接 × all/非空 allowlist × 现代/旧协议（4 项） | 默认连接禁止 UNION、另一连接允许；默认列表隐藏、完整列表及两种详情解释原因、禁止执行不触发 adapter SQL、允许执行返回两行；交替请求不会共享错误裁决。 |
| 双引号表名（1 项） | 元数据启发式未提取表名时，发现仍使用执行侧解析表范围；禁止连接拒绝、允许连接成功。避免只增加 UNION 特判。 |
| 缓存模板缺失（1 项） | 模拟内部快照异常，发现与详情不能宣称可执行，执行仍拒绝。此场景是故障注入，不是正常配置入口。 |

创建服务后删除测试 SQL 源文件，确认发现和执行均使用原快照。关闭 schema readiness，并在元数据调用和被禁止连接的 SQL 执行处放置失败哨兵；这些哨兵不替代生产策略逻辑。相关 Query/发现及上一轮回归合计 **97 passed、2 warnings（15.20 秒）**，类型检查无错误；warning 来自旧协议日志通知弃用。

完整验证采用只复制版本控制文件及新增测试的临时源码副本，全新开发环境、锁定依赖及独立 wheel 环境；保留用户现有虚拟环境和部署配置。

| 检查 | 结果 |
| --- | --- |
| `uv sync --frozen --group dev` | 全新环境安装成功，未修改锁文件；Python 3.12.3 / uv 0.12.19 / FastMCP 4.0.10 / MCP 2.2.0 / Pydantic 2.13.5 |
| `uv run --frozen pytest -q -rs` | **792 passed、4 skipped、3 warnings（49.54 秒）**；三个告警均来自旧协议日志通知路径 |
| `uv run --frozen pyright` | **0 errors、0 warnings、0 informations** |
| `uv build` | sdist 和 wheel 均成功 |
| 锁定运行依赖安装 wheel、`scripts/verify_installed.py` | 非 editable 安装成功；仓库外配置检查、包内提示词及新旧协议查询均通过 |

## 保持独立的验收范围

四项真实 MySQL 集成测试仍未启用；本轮没有操作业务数据库、修改本地连接权限或启用本地 MRTR。参考 Client 的新旧协议回归不替代原生 Codex/Copilot 的现代 MRTR 表单、批准/拒绝/超时交互和独立数据库结果验收。默认关闭 MRTR 的现有部署不因这些待办而要求扩大权限。

D01 的可信任务级授权、D04 的目录/readiness 独立接口、D07 的跨轮关联/OTel，继续作为后续范围；不在本次补丁中引入 Tasks、远程多用户、独立人类认证或分布式状态。安全约定见[安全边界](../security/V3_8_SECURITY.md)，配置约定见[迁移指南](../guides/CONFIGURATION_ZH.md)。
