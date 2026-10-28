# v3.8.2：Host 等待排查与最小请求关联（2026-10-28）

本轮完成项目侧观测补强，将 Host 根因调查保留为独立开放项。历史约 99.768 秒失败已关联到具体审核任务：`timed_out`、无批准／否决结论；此前小时级等待未建立同样的关联。项目侧测试通过不代表 Host 故障已修复，也没有端到端提速结论。

## 已收敛的事实

上一轮只确认公开审核超时。本次读取准确线程的本地元数据后，得到如下关联，未导出审核指令、历史上下文或模型推理内容：

| 分界 | 历史墙钟间隔 |
|---|---:|
| 公开调用 → 审核任务开始 | 0.040 秒 |
| 审核任务开始 → 中断 | 94.621 秒 |
| 审核中断 → 父任务取回错误 | 5.107 秒 |
| 合计 | 99.768 秒 |

审核期间存在非最终模型流事件；这排除了整个区间都尚未启动审核的解释。94.621 秒不是纯推理耗时，也不是配置的 deadline；5.107 秒不能解释成纯网络时间。父任务网络流重试没有关联成审核模型重试，目录刷新超时同时存在于成功对照中，均不足以归因。历史两次小时级成功预览继续单独保留。

Host 自动审核由独立 reviewer 完成，超时不是明确否决。[OpenAI 自动审核说明](https://learn.chatgpt.com/docs/sandboxing/auto-review)。本地证据目前不能分离其内部服务调度、生成、传输或取消处理，也没有准确的 Host action → MCP request → 服务器入口映射。

本地完整关联记录及反馈材料留在 `local_archive/v382_review/20261028_host_latency_followup/`；本批补强与反馈交接留在 `local_archive/v382_review/20261028_host_latency_instrumentation/`。这些本地目录被 Git 忽略；公开报告不附私人线程全文或连接配置。

## 最小实现与日志契约

仅修改既有 `ToolTelemetryMiddleware`，继续由 `observability.telemetry.enabled` 控制，默认关闭；未改私有配置、超时、权限、工具注解、业务返回或写入协议。无需增加依赖、结果字段、追踪服务、后台队列或自动重试机制。

被抽中的一次调用尽力追加两个 JSONL 事件，抽样只在入口决定一次：

| 字段／事件 | 含义 |
|---|---|
| `event=tool_call_started` | 已进入本项目 `on_call_tool` 中间件；尚不表示参数合法、已执行 SQL 或业务成功 |
| `event=tool_call_finished` | 中间件处理返回或抛出；不保证 Client 已收到响应 |
| `server_instance_id` | 每个中间件实例生成的随机标识；新实例／进程重启重新生成，不是系统 PID |
| `call_id` | 每次被抽中调用生成的随机标识；两事件用 `(server_instance_id, call_id)` 配对 |
| `request_id_hash` | MCP 请求 ID 在框架上下文中的表示摘要；没有请求 ID 时为 null，不将 `None` 变成字符串身份 |
| `session_id_hash` | 框架当前 session ID 的摘要，仅作辅助信息；现代 stdio 的框架 session 身份不保证跨请求稳定 |
| `timestamp` | UTC 墙钟，用于人工对齐；不能替代单调计时 |
| `execution_ms` | 仅结束事件包含，使用同进程 `perf_counter` 差值 |

两个摘要使用 `SHA256(json.dumps([server_instance_id, field_name, value], ensure_ascii=True, separators=(",", ":")).encode("ascii"))`。`field_name` 是 `request_id` 或 `session_id`。摘要编码保留输入值的类型及 Unicode 转义区别；但 FastMCP 4.0.10 已将 wire 请求 ID 转成字符串，不能靠此字段恢复 wire 整数／字符串差异。Host 映射需使用框架的字符串表示。不把客户端任意 ID 文本或会话标识原文写入日志。摘要不是认证凭据或匿名性承诺；知道原 ID 与实例标识时可以复算辅助关联。

入口没有 `success`、`call_completed`、数据库目标或业务阶段，避免提前推定成功或默认目标。结束保留原有业务字段：正常返回、业务拒绝、异常、MRTR 等待（`success=null`）和诊断目标范围仍分别表达。取消原样传播，结束记录错误类型；日志写入失败不替换原结果或异常。开始日志写入、关联提取与内部预处理包含在遥测 `execution_ms` 内，结束事件序列化／写入、框架后续处理、传输及 Host 审核不包含；业务结果 `_meta.execution_ms` 仍是原来的更窄窗口。

日志消费者必须按结束事件统计调用结果，而非按 JSONL 总行数计数。读取追加文件中的新旧混合记录可使用：

```python
finished = row.get("event", "tool_call_finished") == "tool_call_finished"
```

旧行没有关联标识，不能补造成已配对事件。默认关闭不新增日志；启用后每个被抽中请求通常从一行增加为两行，并增加一次同步落盘操作。未测量净耗时或 token 收益，不声称零开销。

## 验证与边界

新回归覆盖等待中可见入口、取消、并发、重复请求 ID、新实例、真实 stdio 进程重启、成对抽样、墙钟倒退、记录失败、缺失请求上下文、Unicode 编码及辅助函数输入类型差异、诊断预处理异常（类型用例不宣称框架保留 wire 类型）。两协议真实 stdio 测试各启动两次隔离服务，分别发送常量读取、只读策略拒绝与未知工具调用；四个服务进程合计 12 次工具请求。没有操作用户配置的数据库。

既有遥测、诊断、MRTR 等待／批准／拒绝及元数据测试按结束事件筛选，保留原来的业务断言。源码、正常安装 wheel 和实际常驻 Host 的验证分别计数，不将测试用 stdio 重启称为用户常驻服务已重启。

最终结果见[可提交的计数与源码／安装包摘要](v382_host_request_correlation_20261028/summary.json)：

| 检查 | 最终结果 |
|---|---|
| 六组相关回归 | 183 通过，零跳过 |
| 默认全量回归 | 3577 通过，4 项可选 MySQL 跳过，551 条警告；不代表新增实库发布验收 |
| 仓库外正常安装 wheel 的独立生命周期测试 | 11 通过；不加载项目测试 conftest；78 个运行资源与最终源码摘要一致 |
| 类型与提示契约 | Pyright 零错误／警告；提示契约通过 |
| 文档与差异 | 新链接可解析，`git diff --check` 通过 |
| 常驻 Host、自然模型任务、真实 MySQL | 本轮未运行；配置及依赖版本未改变 |

核心复验命令：

```bash
.venv-v38/bin/python -m pytest -q tests/test_tool_telemetry.py tests/test_telemetry_lifecycle.py tests/test_connection_diagnostics.py tests/test_v38_review_regressions.py tests/test_v38_mrtr.py tests/test_v342_meta_and_schema.py
.venv-v38/bin/python -m pytest -q
.venv-v38/bin/pyright --pythonpath /absolute/path/to/.venv-v38/bin/python
.venv-v38/bin/python scripts/check_prompt_contract.py --config config/server.toml
```

安装包使用既有离线构建工具与冻结依赖目录，通过标准 wheel 构建／installer 安装到独立环境；不是重新解析全部依赖。复制可移植的 `test_telemetry_lifecycle.py` 到仓库外，由 wheel 解释器运行 `pytest -q -o asyncio_mode=auto`，同时检查导入来自安装目录。构建、安装、测试和封存脚本均在本地批次 `scripts/` 保留。

首轮沙盒 stdio 在初始化阶段等待，主动停止；限定 45 秒诊断也未完成，沙盒外两协议定点通过。类型检查在沙盒内无法解析已安装依赖；沙盒外暴露的两处可空上下文类型问题已修正。并行改动期间一个旧测试 stub 尚未适配真实 request_context，初跑 1 失败／18 通过，已按真实接口修正；这些准备失败不记为 Host 历史超时复现。

入口／结束均为尽力记录：关闭、抽样、SDK 在中间件之前拒绝、记录失败、进程强杀或日志轮转都可能造成缺记录／单边记录。因此缺入口不能证明未到达；只有入口不能证明写入或持续运行；有结束也不能证明 Client 收到，更不能替代 `execution_outcome`。本次没有给审计增加事务完成账本或对业务结果增加关联字段。

## 完成条件和停止条件

| 工作 | 收敛条件 |
|---|---|
| 项目侧观测补强 | 同一调用配对、计时、异常／取消／日志失败、两协议和安装包检查通过；文档说明成本和缺记录边界 |
| 常驻诊断就绪 | 维护者在实际需要的有限诊断窗口启用 telemetry、使用 `sample_rate=1.0` 并手动重启；一个受控读取核验两事件和当前版本。未执行前保持未验 |
| Host 根因定位 | 获得同一审核请求的内部阶段链、deadline／取消来源与派发状态，能够解释主要等待并排除关键竞争解释 |
| Host 修复验证 | 根因确认后记录修复版本，在预先定义的匹配条件中验证原失败机制及正常路径 |
| 小时级等待 | 需要各自的阶段证据；不以本次 99 秒关联代替 |

现有证据足以完成本轮本地排查并交接 Host。没有新阶段数据、可检验假设或针对性版本变化时，停止重复 Luna 试验；没有计划新增模型任务。若新条件具备，先限定一个诊断样本及时间上限；仍不能关联就停止修正捕获方式，而不是自动扩大样本直到成功。

本会话没有可调用的 Host 反馈提交接口，反馈草案已准备，未发送；用户可通过 Host 的反馈入口提交最小材料。[OpenAI 故障反馈说明](https://learn.chatgpt.com/docs/reference/troubleshooting)。若历史内部记录已不可取得，根因可以长期保持“证据不足、待外部反馈／后续有界取证”，不必阻塞项目其他工作，也不能写成已修复。本轮不要求立即开启日志或重启常驻服务来追逐偶发故障。
