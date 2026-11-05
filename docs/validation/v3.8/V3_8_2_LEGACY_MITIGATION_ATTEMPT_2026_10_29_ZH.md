# v3.8.2 单键Legacy缓解尝试与恢复（2026-10-29）

维护者批准[单键方案](V3_8_2_STARTUP_FALLBACK_2026_10_29_ZH.md)后已执行一次尝试，**未通过，不进入完整模型任务**。配置写入后的旧进程绑定失效，ProcessGuard在发送信号前拒绝操作；恢复原标记后，独立只读审核确认原配置字节完全相同、唯一SQL MCP目标、目录及SQLite／MySQL常量正常。当前仍使用原现代标记，未留下Legacy缓解。

编排中的错误假设是：带reloadUserConfig=true写入配置后，先前绑定的进程仍稳定。官方同版本源码表明该选项会向已加载线程发布运行配置并安排MCP预热；不能把配置API只当作磁盘编辑，再无条件沿用旧进程身份。保护检查按预期阻止了错误目标停止。**这是私有部署编排问题，不是本轮发现新的SQL策略或Query热加载缺陷。**

## 1. 实际操作和恢复

| 步骤 | 实际证据 |
| --- | --- |
| 前置检查 | 同一Host、唯一加载线程及完整匹配目标；原标记2026-07-28、只读常量通过。 |
| 单键删除 | 带即时expectedVersion的config/batchWrite被接受；磁盘及配置读取均确认标记缺省，其它设置语义不变。reloadUserConfig=true。 |
| 显式停止 | guard.stop先重新核对目标时返回target_process_not_unique；尚未进入pidfd_send_signal，没有脚本SIGTERM。该错误也用于零匹配，不能据此称存在多个重复目标。 |
| 条件恢复 | 原字符串写回被接受，同样带reloadUserConfig=true；一次显式config/mcpServer/reload被接受。原控制器随后的即时进程唯一性检查仍失败，未能自行完成恢复声明。 |
| 独立审核 | 稍后只读检查确认原配置SHA-256完全恢复、其它设置语义不变，同一Host当前仅一个加载线程、11工具及唯一新目标；旧目标已不存在。SQLite／MySQL常量成功。恢复由此关闭，不能据此把缓解记为成功。 |

本次显式MCP刷新请求共**一次，仅条件恢复**；实施阶段未发显式刷新。另有**两次配置写入请求自动运行配置发布**，这与显式刷新RPC是不同操作，也具有Host全线程作用范围，不能省略或把它们等同于零影响。未采集每次预热的实际重建总数。以后预算应同时列出配置写入及其运行发布行为、显式刷新和进程信号，不能只用一个“刷新次数”代表全部副作用。

原journal保留implementation_verified=false、restore_verified=false及原始失败，不事后改写；独立restoration-audit另列当前恢复成功。没有新模型会话、没有执行业务轮，不占用三个已计划任务作为失败或通过；历史完整1/3保持。失败停止条件生效，不把尚余的显式刷新数量拿来再次部署。

## 2. 同版本源码解释及修订

核对官方0.165标签中的以下路径：

- [config_processor](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/config_processor.rs)：batch_write先处理文件及Host插件／Skills缓存；reloadUserConfig=true再调用reload_user_config，遍历已加载线程并发布运行配置。
- [session/config_refresh](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/session/config_refresh.rs)：运行配置发布会标脏MCP，并安排预热。此路径能在控制器的显式停止前改变进程绑定；本轮没有旧PID退出的逐时刻日志，不能断言每次内部重建的精确次序。
- [mcp_refresh](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/mcp_refresh.rs)：显式MCP刷新另从当前配置层加载并向线程发布MCP配置。

最小修订为：删除与条件恢复的config/batchWrite均使用**reloadUserConfig=false**。先只暂存单键配置；重新确认原唯一目标仍在，pidfd正常停止目标，再做一次明确获准的Host全局MCP刷新来加载配置。若目标仍因其它机制变化，继续拒绝，不追逐新PID，也不省去身份检查。

false并非完全无Host副作用：batch_write仍清插件／Skills缓存，但不进入上述自动运行配置发布分支。保留expectedVersion、精确单键、其它设置摘要及无SIGKILL／无自动重试规则。不改产品、数据库、授权、command／args／cwd或依赖。

修订控制器已准备，与旧版仅说明及reloadUserConfig一行不同。四项fake检查通过：暂存删除与恢复保持模拟runtime身份、配置失配先于写入拒绝，以及原true分支能触发指定的身份变更哨兵。它们用于检错，不能替代实际Host验证。源码副本按Git blob核验，未把最新分支冒充本机实现。

## 3. 下一步与当前边界

| 顺序 | 工作 | 通过／停止条件 |
| --- | --- | --- |
| 1 | [待批准] 修订后重新实施 | 新批准私有单键、暂存语义和最多两次显式全局刷新：一次实施、一次仅失败时恢复。旧失败停止条件不自动解除。 |
| 2 | [原生验证] 新目标与目录／读取 | 确认唯一替换进程、主会话原生SQLite／MySQL常量。失败恢复并停止，不继续业务。 |
| 3 | [完整验收] 最多三个新双轮任务 | 原生通过后冻结夹具、独立真值、消费实例发布和参数；失败保留，不替换到通过。 |

本轮已恢复，无待恢复配置、未关闭模型Agent或待终止的测试进程；不要求维护者反复手动重启。当前产品回归不因私有编排变化重跑或重算。20个受保护项目文件、既有274封存成员及相对链接另行复核。私有归档20261029_legacy_query_acceptance按plans／scripts／tests／drafts／evidence／reports组织；未运行的修订控制器在独立v2目录，便于后续新批次保存真实结果。
