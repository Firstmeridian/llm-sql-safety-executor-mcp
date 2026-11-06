# Codex MCP 刷新与重连辅助

[English](CODEX_MCP_RESTART.md)

使用约定更新：2026-11-06。

使用 [`scripts/dev/restart_codex_mcp.py`](../../scripts/dev/restart_codex_mcp.py)
连接已有 Codex Host；它不向 SQL MCP 新增管理工具。

## 选择入口

| 需求 | 入口 |
| --- | --- |
| 发布受支持的 Query 或 Mutation 定义 | 优先使用 [`reload_skills()` 发布 Query](QUERY_SKILL_RELOAD_ZH.md)或[显式发布 Mutation](MUTATION_SKILL_RELOAD_ZH.md)。 |
| 检查 Host／目录绑定或核验现有连接 | 使用只读 `probe` 或 `verify`。 |
| 请求配置刷新 | 使用 `refresh`；配置未变时可能复用健康客户端。 |
| 为核心代码、共享依赖或部署配置改动替换进程 | 旧实际消费者 PID 可核验时使用 `restart`。 |
| 同一 Host 还有其他空闲聊天，只需替换当前消费者 | 显式使用 `--allow-shared-host`；先用 `verify --check-process` 只读预检；低风险固定授权适用时，提醒后运行 `restart`。 |
| 旧目录、Query 调用或 PID 不可用时引导／恢复 | 按下述独立前置条件显式选择 `recreate`；不自动从 `restart` 转入。 |
| VS Code Codex 重连，或无法确认作用范围 | 人工重连；扩展自动重启支持已搁置。 |

**当前使用约定：** 默认保持严格单会话。2026-11-06 批准新增显式
`--allow-shared-host` 受控共享 Host 模式：只主动停止当前聊天独占的 SQL MCP
进程，并接受一次全局刷新可能影响其他空闲聊天。维护者随后授予固定低风险维护授权：
其他聊天空闲、没有在途写入／等待写入结果，并接受可能重新预览时，提醒后执行，
不逐次请求批准；按操作状态而非 CLI／其它界面判断。结合 Host 状态和已知请求
记录核对条件，出现未决写入、具体不明状态或范围变化时暂停。idle 不证明没有
待确认预览，但此条件下可能重新预览已获接受。固定授权不扩大到组停止、
配置切换、额外刷新或不确定结果重试。
历史 `--all-loaded-targets` 组模式保留在文末，不自动启用；它会停止整个目标集合，
不能替代本模式，也不能作为拒绝后的自动补救。

## 前置条件

### 环境、绑定与范围

从已安装开发依赖的 checkout 运行（`websockets` 当前锁定为 17.1）。执行 venv
Python 时保留配置路径，不先 resolve 符号链接，以免误用缺少辅助依赖的系统 Python。

辅助只连接已有 Host 的 Unix WebSocket 端点，不启动／替换 Host，不新建／恢复／迁移
聊天。自动发现仅有界查找当前用户的 `/tmp/codex-daemon-UID/` 中已有 socket；也可用
`--socket` 指定端点。拒绝符号链接。`CODEX_THREAD_ID` 或显式 `--thread-id` 必须唯一
匹配已加载线程。默认 `--server` 是准确配置名 `sql-safety-executor-mcp`，不能写成
模型工具命名空间中的下划线形式。

Host 唯一性按已加载线程归属判断，与 MCP 目录是否可读取分开。两个端点均加载
当前线程时，即使一个目录查询失败也拒绝歧义，不把另一个视为唯一 Host。
普通 `probe`、`verify`、`refresh` 和 `restart` 路径还要求目标 Query 目录；
**此目录要求不适用于 `recreate` 恢复入口。**

已核对的 Codex 0.165／0.166 `config/mcpServer/reload` 没有服务／线程选择参数，刷新范围是
**该 Host 的全部已加载线程和 MCP 配置**。`--server` 只限定核验目标，不限定刷新范围。
维护须获准影响范围内的全部服务／加载线程，且没有在途写入或等待写入结果。
默认 `restart`、`refresh` 和 `recreate` 均要求仅加载当前线程。
共享 Host 例外仅适用于下述显式 `restart` 和只读 `verify --check-process`，
不扩展 `probe`、`refresh` 或 `recreate`。
除 `probe` 外的调用须指定已有测试连接别名。加载清单和 PID 复查不是原子隔离，
不能据此承诺并发环境绝对零影响。

### `restart`：核验旧实际消费者 PID

默认真正重启要求 command／cwd 为绝对路径，并唯一匹配本地 stdio 子进程。
按监听 socket、用户、父进程、完整启动参数及工作目录绑定目标；shell 包装、
远程执行或歧义目标会明确失败。

磁盘配置及 argv／cwd 只确定**候选进程**。发送任何信号前，复用既有常量读取，
要求每个实际消费会话返回的 `_meta.server_pid` 与固定候选 PID 集合完全一致；
停止前复查启动时刻、启动别名及配置。身份缺失或不匹配均拒绝，包括另一服务配置
已删但旧进程仍在的情况。不能从磁盘配置推断身份，也不能通过旧停止逻辑绕过检查。

成功 query 仅在已有可选 `_meta` 增加一个 PID 整数，不改业务数据，不增加 SQL 或
网络往返；这是可信本地身份检查，不是远程认证或原子隔离。旧驻留没有此字段时，
`restart` 拒绝。可在条件满足时独立选择 `recreate`；否则转维护者处理。

### `--allow-shared-host`：当前消费者独占，刷新范围共享

此模式与 `--all-loaded-targets` 互斥，最多支持八个同 cwd 已加载线程，其他线程
须为 idle。逐线程检查目标目录 connected，并通过同一测试连接别名的常量读取
取得实际 PID；该别名须可在每个消费者使用。每个 PID 都须与实际绑定 Host 的
直接子进程及精确启动签名匹配，并形成逐线程唯一映射。当前消费者必须独占进程；
配置匹配、进程数量相等或目录可见，都不能替代该证明。

复核配置和全部固定进程身份后，紧邻发送停止信号前复查线程集合和空闲状态；
实际刷新前再复查线程集合和空闲状态。其他聊天活动、状态不可观察、成员变化、
共享进程或归属不明时停止。
只向已固定的当前 PID 发送 SIGTERM，等待退出后至多一次 Host 全局刷新；
不主动停止其他消费者，不追逐新 PID，不升级为 SIGKILL，也不重试或自动改用组模式／
`recreate`。本模式不切换配置、不启动桥接、不迁移聊天或重启 Host。

全局刷新可能复用或替换其他消费者及其他 MCP 服务。新目标进程身份须不属于操作前
全体目标进程集合，不能将另一个原消费者误作新目标。脚本须核验新目标 PID 和
全部原消费者的目录／只读调用，并分别报告其他消费者复用或替换的观察结果。
这些观察不证明零影响，也不证明其他 Agent 已取得新定义；无法完成核验时保留失败。
本模式的[正式验收记录](../validation/v3.8/V3_8_2_SHARED_HOST_RESTART_2026_11_06_ZH.md)
区分隔离回归与现场验收；现场操作依上述固定授权或另行批准，历史组验收不代替本模式验收。

### `recreate`：独立的引导／恢复前置条件

`recreate` 绑定已有 Host、当前线程及用户配置中的准确服务名，**不要求旧目录、
Query 调用或 PID 可用**。控制端可访问本身不是充分条件：仍须唯一绑定当前会话，
满足支持的启动配置和权限，并获得配置切换／Host 全局刷新范围授权。只读预检
用户配置来源、启用状态、绝对 stdio 启动定义和会话范围。目标停用／恢复由 Host
生命周期管理；辅助不向进程发送信号，也不自动进入此模式。

## 调用方式

### 只读探测与核验

```bash
python scripts/dev/restart_codex_mcp.py probe
python scripts/dev/restart_codex_mcp.py probe --check-process
python scripts/dev/restart_codex_mcp.py verify --connection YOUR_TEST_ALIAS
```

默认仅只读探测。`probe --check-process` 检查候选进程，不发送信号、不读 SQL，
保持 `process_binding_verified=false`，不证明实际消费者身份。可用
`verify --check-process` 并指定测试连接，只读核验该绑定。`verify` 不请求刷新，
仅核验目录及 `SELECT 1 AS codex_mcp_restart_canary`。旧 `probe_codex_mcp.py`
入口作为只读别名复用同一传输实现。

### 替换已核验的旧进程

```bash
python scripts/dev/restart_codex_mcp.py restart --allow-host-wide --connection YOUR_TEST_ALIAS
```

完成前置绑定及常量读取后，通过 Linux pidfd 向固定目标发送 SIGTERM，等待最多
10 秒，不升级为 SIGKILL；然后仅发送一次 Host 刷新，重新取得目标目录、运行常量
读取并确认新进程身份。发送刷新前复查加载线程集合；这些检查仍不构成原子并发隔离。

### 同 Host 其他聊天空闲时，只替换当前消费者

```bash
# 只读预检，不停止进程或刷新：
python scripts/dev/restart_codex_mcp.py verify --check-process --allow-shared-host --connection YOUR_TEST_ALIAS
# 复核低风险固定授权条件并提醒后；不符合时暂停：
python scripts/dev/restart_codex_mcp.py restart --allow-shared-host --allow-host-wide --connection YOUR_TEST_ALIAS
```

`--allow-shared-host` 只接受 `restart` 或带 `--check-process` 的 `verify`。
只读预检不需要 `--allow-host-wide`；实际 `restart` 仍必须显式给出此参数。
预检成功不保留未来操作资格；`restart` 会重新核验。预检或停止后检查失败时，
不要扩大范围或追加刷新；按失败阶段报告现状，必要时转人工恢复。

### 请求配置刷新

```bash
python scripts/dev/restart_codex_mcp.py refresh --allow-host-wide --connection YOUR_TEST_ALIAS
```

`refresh` 先核验常量读取、复查加载集合，再请求配置刷新，不停止进程。
配置未变时 Host 可能复用健康客户端，因此刷新成功不证明真正重启。

### 旧目录／调用／PID 不可用时显式由 Host 重建

```bash
python scripts/dev/restart_codex_mcp.py recreate --dry-run --connection YOUR_TEST_ALIAS
# 确认计划及配置切换／全局刷新范围获准后；state-file必须为新文件：
python scripts/dev/restart_codex_mcp.py recreate --allow-config-toggle --allow-host-wide --connection YOUR_TEST_ALIAS --state-file /tmp/sql-mcp-recreate-001.json
```

1. 只读核对独立恢复前置条件。`--dry-run` 不写配置、不读 SQL、不刷新；退出 0 的
   `recreate_plan_verified` 仅证明计划，不证明重建或工具可用。
2. 新建恢复日志，以原配置版本只将 `mcp_servers.<name>.enabled` 改为 false，
   暂存后做第一次全局刷新。要求各原消费者明确返回 disabled 且工具为空。
3. 按停用写入返回的版本恢复原值或原本省略，再做第二次全局刷新。不整文件覆盖配置
   或覆盖并发修改。编辑范围仅为目标键；Host 可能调整格式，`config_bytes_restored`
   另报实际字节是否相同，不承诺任意 TOML 布局逐字还原。
4. 按下节成功条件核验各原消费者目录、常量读取及新进程身份。

首次停用配置及每次 Host 全局刷新（含恢复后的刷新）前，均在对应恢复日志
flush／`fsync` 后复查固定加载会话范围。范围改变或检查失败时，不发送该次停用
或刷新。**已确认停用后的清理仍须执行：** 范围检查失败不取消失败恢复节所述的
一次版本受控配置恢复尝试，也不允许再补一次刷新。日志仅含阶段、版本及启用原值，
不含配置正文、凭据或业务数据。

## 成功确认

### 脚本结果与有界读取

退出 0 须结合 `status` 和核验字段解释：

| 结果 | 证明范围 |
| --- | --- |
| `binding_verified` | 仅证明目录绑定；`probe` 不证明工具可调用。 |
| `connection_verified` | 实际常量 Query 返回成功；`reload_attempted`、`reload_accepted`、`read_probe_verified` 和目录摘要分别标明阶段。 |
| `restart` 成功 | 还须有 `phase=complete`、`process_binding_verified`、`process_stop_attempted`、`process_restart_verified=true` 和 `read_probe_verified=true`。 |
| 共享 Host `verify --check-process` 成功 | 还须核验全部原消费者的目录、常量读取和唯一 PID 映射；不证明已重启，不发送信号或刷新。 |
| 共享 Host `restart` 成功 | 除上述 `restart` 条件外，须确认当前目标身份已替换、全部原消费者核验通过，并分别记录其他消费者复用／替换；不能把它解释为其他聊天零影响。 |
| `recreate` 成功 | 须有 `phase=complete`、`target_disabled_verified`、`config_restored`、`process_restart_verified` 和 `read_probe_verified`；每个原消费者的常量读取须成功，返回 PID 匹配准确 Host／启动定义，且 PID／启动时刻不属于操作前子进程快照。 |
| `recreate_plan_verified` | 仅为 dry-run 计划。 |

共享模式回执应为 `shared_host_mode=true`、
`process_scope=current_thread_exclusive_child` 和
`thread_process_mapping=consumer_pid_verified`。`read_probe_verified_thread_count`
须覆盖全部原消费者；`consumer_process_observations` 按 `thread_sha256`、
`current_thread`、`before`、`after`、`process_replaced` 分别记录观察。
成功重启的 `process_signals_sent=1`、`process_stops_confirmed=1` 只证明脚本主动
停止了一个目标，不表示 Host 未影响其他进程；只读预检不发送停止信号。

目录摘要不变不代表没有刷新，摘要或 `{}` 均不能单独证明进程替换；
`refresh`／`verify` 仍将替换标为未验。`recreate` 的新实际消费者不证明所有旧进程
已退出；无已知旧 PID 时，保留 `previous_target_exit_verified=false`。

刷新受理后，目录发布和客户端启动可能尚未完成。按已验 0.165 schema 有界观察
`null`、`notStarted`、`starting` 及恢复后的旧 `disabled`；明确失败、取消、需认证
或未知状态立即停止。`connected` 须同时提供 `query`。

普通 RPC 默认 10 秒、最多 30 秒。`restart`、`refresh`、`recreate` 刷新后的
全体消费者目录／单次常量读取**共享最多 30 秒**，同时受原 **60 秒 RPC 总预算**
及扣除恢复预留后适用的工作截止约束。每消费者仅发送一次刷新后常量请求。
读取窗口不延长总预算；预算耗尽不发送新请求。线程清单／通知数量仍有界，连接建立
和清理另有各自超时。

### 维护互斥、建议与计时

`restart`、`refresh` 和非 dry-run `recreate` 在唯一绑定 Host 后，按其控制端点
取得非阻塞文件锁；锁覆盖不同服务名／聊天的辅助维护，直到核验和必要的配置清理结束。
冲突返回 `host_maintenance_in_progress`，不等待、不停止进程或刷新。
`probe`、`verify` 和 dry-run 不加锁。`maintenance_lock_acquired=true` 表示本次曾取得锁，
不表示命令退出后仍占用。锁文件保留在当前用户私有的
`/tmp/codex-mcp-maintenance-UID/`；进程退出释放系统锁，不靠删除文件判断是否占用。
它只协调使用本脚本、连接同一控制端点的维护，不锁住人工操作或 Host 自身行为，
也不替代范围／状态复查。

JSON 回执的 `next_action` 给出 `action` 和简短说明。它不执行恢复，也不授予新权限；
已发刷新但核验失败时建议只读核对，配置已恢复但运行状态未验时建议按日志人工协调，
不自动补发刷新或扩大范围。

`timings_ms` 使用脚本进程自己的单调时钟。`total` 从操作入口计到清理后的最终回执快照，
不含 CLI 参数解析／端点发现、最后日志落盘、释放互斥锁和 stdout 序列化；端点发现失败的回执则
记录 CLI 已经过的窗口。另按实际经过的阶段记录 `host_binding`、`process_stop`、
`host_refresh`、`consumer_verification`，以及必要时的 `config_cleanup`。
失败窗口也记录；`recreate` 的两次刷新 RPC 耗时累加。阶段不是完整分解，相加不等于
`total`；RPC 等待不等同于 Host 内部处理时间，不能据此归因。原有 60／30 秒预算不变。

### 调用 Agent 的实际通道确认

脚本核验与调用 Agent 核验分别记录。官方
[App Server 说明](https://learn.chatgpt.com/docs/app-server)将 reload 描述为读取配置
并排队刷新；请求受理本身不证明进程已替换。

1. 检查上表对应模式的全部成功条件。`reload_accepted` 仅说明请求受理，
   不证明重建完成、进程替换或模型已取得工具定义。
2. 从调用 Agent 的当前实际会话进行原生工具核验。只读常量确认该通道可调用；
   若目的为安装新代码／依赖／工具契约，还须检查此次改动对应的只读行为或实际可见
   定义。新 PID 和常量本身不足以证明目标改动生效。可复用任务已有核验，不为确认
   部署而执行写入。
3. 分别报告进程替换、连接可用、目标改动生效。无法观察模型收到的定义时，保留
   `model_tool_visibility=unverified`，不能凭控制端点目录改写为已验。若需要下一轮
   重新生成工具目录，先报告尚未确认，再在该轮核验，不自动刷新或重试。

未来每次有目的的重启仍按对应改动确认；不要求每次业务查询重启或重新发现工具。

## 失败恢复／诊断

### 保留未确认结果并清理已确认的停用

失败退出 2，保留失败 `phase`。刷新响应丢失属于结果未确认；尝试停止但刷新未完成
不证明服务可用。可先用只读 `verify` 检查现状。即使刷新已接受，目录／读取失败仍是
验收失败；`verify` 自身不能恢复已断连实例。

RPC、常量请求、配置写入或刷新超时／结果不确定后，不自动重试。不自动从 `restart`
转 `recreate`、扩大到组模式、推断此前写入未执行或重放 Mutation。等待更久本身
不证明启动根因已经修复。

`recreate` 已确认停用后，若尚未尝试恢复，失败清理仍按**该次写入返回的精确版本，
最多尝试恢复一次配置**；范围变化或恢复前日志写入失败同样如此。首次停用及每次刷新
的范围门槛不能写成停止所有版本受控清理。已发送或结果不确定的恢复不重发，不覆盖
较新用户修改，不额外补刷新。配置恢复不证明运行态已恢复。

在原 60 秒 RPC 总预算内，为撤回已确认停用预留一个普通 RPC 窗口（`--timeout` 秒）；
工作阶段提前截止，恢复不延长总预算。预留不保证传输、磁盘或 Host 故障下一定恢复。
查看日志、`reason`、`config_restored` 和 `manual_recovery_required`；冲突和未解决
故障仍须人工核对恢复。

### 读取核验诊断

失败结果保留核验子步骤及 `last_rpc` 的方法、实际等待上限、单调时钟耗时和
`request_sent`。后者只表示已尝试发送，不证明 Host 收到；不记录参数或凭据。
先看配置恢复状态和具体失败步骤，再判断结果。

### Host／当前会话绑定诊断

`probe` 及其他模式保留 `binding_diagnostics`：每候选一个有界编号与结束阶段，
区分端点校验、连接、初始化、线程列表／归属、服务目录及最终唯一性。连接错误仅报告
允许的异常类别和适用 errno，不输出 socket 路径、线程列表或异常正文。
`thread_id_source` 区分 `--thread-id` 与 `CODEX_THREAD_ID`；`endpoint_source`
区分 `--socket` 与自动发现，即使显式值与环境相等也不混淆来源。

`current_thread_not_loaded` 只在完整线程列表已取得后使用。目录超时会保留
`current_thread_loaded=true` 及 `phase=catalog`，不能据顶层
`current_host_not_verified` 误判为线程不存在。其他候选握手失败也会保留；重复匹配
仍拒绝。不删除归属检查、不恢复／创建线程，也不依据标题、工作目录或工具名猜测
Host。显式 socket／thread 覆盖须有可信对应；辅助直接加载磁盘当前源码，不依赖
重启 SQL MCP 来取得诊断。

## 限制

- 仅覆盖已验证的本地 Linux Unix WebSocket 控制。仅 stdio 控制、远程 Host、不同
  认证方式及不可访问端点仍可能需要维护者操作。沙盒可申请针对性 socket 权限，
  不必默认要求 Full access。**VS Code Codex 继续人工重连**，不接管其私有 stdio 管道。
- Host 配置版本是并发校验用的不透明值，即使带 `sha256:` 前缀也不能用文件摘要替代。
  版本检查防止并发覆盖，不提供跨 Host 隔离；其他 Host 仍可能读到共享用户配置的
  暂时切换。范围复查与 RPC 发送也不原子。
- 默认及共享 Host `restart` 不编辑配置，显式 `recreate` 仅暂时切换目标启用键。不增加授权变更、
  Host／线程新建或终止、向其他服务发信号、业务表检查或 Mutation 执行。
  两次重建刷新均为 Host 全局操作；不新增运行依赖、SQL MCP 管理工具或普通查询步骤，
  不作通用 Host 保证。
- 重启／重建会丢失进程内预览，与 Query 定义发布不同；这不证明此前写入未执行。
  共享 Host 模式只主动停止当前消费者，但 Host 自身可能因全局刷新替换其他消费者，
  使其预览失效；调用前须接受这一范围，不能承诺其他聊天完全不受影响。
  目录停用及新消费者成功不证明所有旧进程已退出。Host 清理可能异步进行并采用自身
  终止策略；`recreate` 辅助本身不向进程发送信号。
- 应以实际 Host 二进制核对 [OpenAI 协议](https://learn.chatgpt.com/docs/app-server)
  schema。历史 PATH CLI 0.164 与当时 Host 0.165 不同；2026-11-06 另核对了实际
  Host 0.166 的全局 reload 定义。这不证明共享模式已完成现场验收，也不能解释此前
  proxy 超时根因或保证所有 Host 版本。

## 历史验收和启动调查

以下按各批日期、范围保留已通过、失败和未验结果。后续成功不改写先前未完成命令，
历史一次性授权也不构成当前维护授权。

### 单会话重启与身份补修（2026-10-28～29）

实际验收及保留失败见[本批记录](../validation/v3.8/V3_8_2_CODEX_MCP_RESTART_2026_10_28_ZH.md)。
当时原生验收已观察到配置刷新与实际进程重启的区别。
[身份补修报告](../validation/v3.8/V3_8_2_RESTART_IDENTITY_REFUSAL_REPAIR_2026_10_29_ZH.md)
保留当时人工升级待验状态；后续恢复记录不改写该检查点。

### 初次重建验收（2026-10-29）

[前批限定验收](../validation/v3.8/V3_8_2_CODEX_MCP_HOST_RECREATE_2026_10_29_ZH.md)：
**78 项辅助回归及五个完整隔离 Host 流程**通过。另获准的实际恢复完成原配置恢复和
两次刷新，但最终核验超时。后续只读绑定及调用 Agent 行为通过，没有再次刷新；
该历史首次命令仍未完整通过。

### 就绪修正与完整实际恢复（2026-10-29）

[本轮对照](../validation/v3.8/V3_8_2_CODEX_MCP_READINESS_2026_10_29_ZH.md)：
**97 项辅助回归、两项旧版缺陷哨兵及三个新版隔离 Host 完整流程**通过。
另获准的新版实际恢复已一次命令完整通过：原配置恢复、新实际消费者和读取均确认，
调用 Agent 原生常量也通过。该一次批准已使用；此前首次真实超时保留，不与前批合并计数。

### 预算与范围审阅（2026-11-01、11-05）

[最终审阅](../validation/v3.8/V3_8_2_FINAL_REVIEW_2026_11_01_ZH.md)记录原总预算内的
恢复预留。[11 月 5 日范围／目录补修](../validation/v3.8/V3_8_2_SCOPE_CATALOG_REPAIR_2026_11_05_ZH.md)
记录恢复日志 flush／`fsync` 后，首次停用及每次刷新前的范围复查。两者均不把范围
拒绝变成跳过已确认停用的清理，也不让检查与发送成为原子操作。

### 共享Host模式与固定低风险授权（2026-11-06）

[本批记录](../validation/v3.8/V3_8_2_SHARED_HOST_RESTART_2026_11_06_ZH.md)：完整辅助230项通过；维护者随后授予固定低风险维护授权，提醒后一次真实操作仅停止当前消费者、刷新一次，新目标／原消费者2/2读取及调用Agent新行为均通过。另一原消费者本次复用，不承诺未来都不重连。固定授权以实际操作状态判定，包含同Host的CLI消费者；只读预检不能代替请求状态判断。此授权不适用下节组停止、recreate或失败追加刷新。

### 历史多会话能力与验收（2026-10-29；当前不建议）

此节保留既有能力和历史验收，不作为当前自动维护建议；当前默认与显式共享范围见页首。
组模式主动停止所有匹配目标，`--allow-shared-host` 只主动停止当前独占目标；两者互斥，
均不能在拒绝后自动启用。历史组验收不证明新共享模式通过。

本节说明PID绑定的`restart`组模式；`recreate`按上节由Host管理命名服务，不能混同为直接进程集合停止。

`--all-loaded-targets` 是显式选项，不会在单会话失败后自动启用。它选择
**绑定 Host 下完整匹配目标 command、args、cwd 的所有直接子进程**，包括其他空闲
会话使用的此服务；不是 POSIX 进程组信号。实际使用须批准整个目标集合及原有的
Host 全局刷新范围。脚本不主动停止其他服务，但全局刷新仍可能影响它们。
所有被重启实例的进程内预览令牌都会失效。

保留的有界实现最多支持八个加载会话，全部须属于脚本当前工作目录，其他会话须为 idle；
每个会话都须已有 connected 的目标目录。匹配目标子进程数须等于加载会话数；共享客户端、
不同目录、未支持启动方式或数量不一致会停止。数量相等**不证明逐会话 PID 对应**，
`thread_process_mapping` 保持 `unverified`。磁盘配置也不能证明每个在用线程的历史配置快照。
停止前仍须核验实际消费者返回的PID；集合相等不建立持续的逐会话进程映射。

拒绝其他服务名使用相同启动签名；停止前重查配置、线程集合、空闲状态及固定进程成员。
为全部成员取得 pidfd，只向固定成员发送正常停止信号；全部退出后至多一次全局刷新。
随后逐个核验原加载会话的目录及只读常量，并确认完整的新进程集合不含任何原身份。
这些快照检查仍不是原子的并发隔离。

`probe --all-loaded-targets` 只检查此范围，不发信号、不刷新、不读数据库。
`verify --all-loaded-targets --connection YOUR_TEST_ALIAS` 增加逐会话常量读取，不重启。
`refresh` 不替换进程，因此拒绝搭配此选项。报告分别列出 `process_scope`、成员身份／数量、
`process_signals_sent`、`process_stops_confirmed` 及读取通过的线程数。
局部停止或刷新结果不确定均保留为失败，不自动重试；先查看报告及剩余成员，
`verify` 自身不能恢复已断连实例。

本范围的[新增验收记录](../validation/v3.8/V3_8_2_CODEX_MCP_GROUP_RESTART_2026_10_29_ZH.md)
区分自有进程测试、现场只读预检和另获批准的真实组重启；本轮固定授权不适用组停止。此前单会话验收不替代新增范围。

最新另获准的组操作以一次全局刷新完成两固定目标替换及两原消费者读取，4.241秒；调用Agent另验Mutation新参数及四项原生夹具。随后另获准的恢复重启也完成两目标替换／两原消费者读取及QA别名卸载，含额外核验8.354秒；当前Agent另验卸载和QA Skill移除。两次单次授权均已使用，不自动推广，也不据此证明逐线程PID映射或通用耗时。

### 启动调查（2026-10-29）

一次另获批准的[帧头采集](../validation/v3.8/V3_8_2_HANDSHAKE_CAPTURE_2026_10_29_ZH.md)
确认server/discover ID0的迟到结果进入了Host等待initialize ID1的阶段；独立对照确认
现代连接会拒绝旧式初始化。不能改响应ID掩盖问题。[随后同版本源码及启动测量](../validation/v3.8/V3_8_2_STARTUP_FALLBACK_2026_10_29_ZH.md)
确认Auto等10秒后在同管道旧式初始化；0.165的单服务CODEX_MCP_PROTOCOL_VERSION标记选择
此路径，无标记则Legacy。该分析时点单键缓解仅准备，后续部署及当前验收见下文；调大外层启动超时
不能直接改变内部固定等待。该结论也不推广成所有旧子会话不可用的根因。

该采集是私有临时诊断，不是辅助脚本新增功能。部署预检失败后在获准的两次全局刷新内
恢复，没有新增模型试验。执行venv Python保留配置路径，不先resolve符号链接，否则
可能误用缺少辅助依赖的系统Python。

后续[已批准尝试](../validation/v3.8/V3_8_2_LEGACY_MITIGATION_ATTEMPT_2026_10_29_ZH.md)在发信号前安全停止：
config/batchWrite的reloadUserConfig=true会发布运行配置，可能使旧绑定先失效。应恢复并
独立核验，不自动追逐新PID。暂存修订使用false，再另做显式MCP刷新；该尝试时点仅准备，后续Host验收见下文。配置运行发布与显式刷新RPC分别计量，该协议设置调查没有把配置编辑加入`restart`。

随后获批的[暂存修订](../validation/v3.8/V3_8_2_LEGACY_RESTART_ACCEPTANCE_2026_10_29_ZH.md)已核验父进程替换及原生读取。
但三个同轮新子线程仍在业务前启动失败。Codex0.165的spawn克隆当前轮捕获配置，父客户端
刷新不等于子代理已继承新设置；本批没有子线程有效标记证据。此线索不能写成已确认缓存
原因，也不据此追加会话／刷新凑通过率。单服务Legacy设置按批准保留。

#### 新父轮验收（2026-10-29）

[单项定点](../validation/v3.8/V3_8_2_NEW_TURN_CHILD_PROBE_2026_10_29_ZH.md)通过；另冻结的[三个双轮任务](../validation/v3.8/V3_8_2_NEW_TURN_BUSINESS_ACCEPTANCE_2026_10_29_REVISED_ZH.md)完成全部流程、消费参数更新／删除及六组核心查询一致。严格完整任务2/3保留一处模型降幅舍入误差。无额外配置编辑／刷新，旧失败保留。复制当前轮配置仍为源码支持的线索，没有准确子env／帧或唯一原因证明。获批修改配置后，优先有界核验实际子线程，不假定同轮继承，也不反复重启／替换到通过。

在2026-10-29记录时，所保留的Legacy设置是单个真实Host的协议启动选择，不是旧包／旧SDK兼容层。项目尚未发布；更简洁的上游修复／Host升级方案应先提出收益、影响及定点验收计划，再由维护者批准，不自动修改Host或私有配置。

前批主 Agent 原生读取及三个 Luna 消费实例提供了实际通道证据；后者分别核对参数更新、
执行和删除。这些历史核验不替代未来目标改动的对应确认。

### VS Code 自动重启撤回（2026-10-31）

当时扩展自动重启支持已搁置。启动设置恢复原字节，桥接源码／测试／详细报告移入
私有归档，后续只读检查确认桥接进程退出。无需为撤下桥接再重载窗口。既有 CLI／daemon
辅助及 Skill 发布保留声明范围。实验过程和撤回证据保存在
`local_archive/v382_review/20261031_vscode_restart_deferred/`，不进入正常源码／测试或
发布文档；此记录不改变当前默认／显式共享范围和 VS Code 人工重连要求。
