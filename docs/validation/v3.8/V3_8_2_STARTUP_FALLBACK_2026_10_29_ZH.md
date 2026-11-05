# v3.8.2 Host发现回退与服务启动定位（2026-10-29）

已用本机Codex **0.165.0** 对应标签及其固定Rust SDK依赖，解释前批捕获的迟到发现响应冲突：现代发现等待约10秒后，Host在同一连接发送旧式initialize；迟到的发现结果ID0随后被当作等待ID1时的异常响应。当前SQL MCP配置显式启用了这条现代路径。**建议先验证单服务取消现代协议标记的有限缓解，不改SQL策略或响应ID。** 配置与Host尚未改变，缓解及新的完整模型验收仍待批准／执行。

这是[帧头采集](V3_8_2_HANDSHAKE_CAPTURE_2026_10_29_ZH.md)之后的源码与独立进程分析。原有失败、1/3完整业务结果及sealed报告保持；本批没有新增业务模型任务，没有消耗新的全局刷新授权。

## 1. 同版本实现与证据强度

只读确认实际Host二进制版本为0.165.0，并保存二进制SHA-256。官方rust-v0.165.0标签指向360319d8dee62d87e2d59fc0c21805d79519cfed；Cargo固定rmcp3.5.1至98a54789b80110ad210495c4ad845c89e1980471。保存11份官方源码及Git blob核验。版本匹配与实测轨迹互相支持，但没有本机二进制的可复现构建证明，不能称逐指令验证。

| 核对项 | 实现与结论 |
| --- | --- |
| 启用条件 | Host功能允许现代协议且该stdio服务env中存在CODEX_MCP_PROTOCOL_VERSION=2026-07-28时选择现代Auto；无此标记则选择Legacy。当前目标标记确实存在。Host消费并移除标记，不是Python服务读取它。 |
| 发现等待 | 固定依赖中的Auto以10秒包裹discover_startup；超时后使用同一transport及递增ID调用legacy_startup。 |
| ID冲突 | legacy_startup等待自己的initialize ID；expect_response遇到另一成功响应ID即报ConflictInitResponseId。与先discover0、后initialize1、再result0的原trace相符。 |
| 协议时代 | 前批SDK与独占对照确认：已选择现代时代的服务连接拒绝随后initialize。只丢掉ID0仍不足以证明能完成回退。 |
| 超时边界 | Host外层startup握手超时与rmcp内部10秒发现等待不同。调大外层不能直接修改内部等待，tool_timeout更不是这一层。 |
| 较新公开分支 | c92700d分支有独立stdio_handshake及迟到发现处理／重建helper测试；这些文件不在0.165标签。可交给Host维护方参考，未安装或验收该分支，不宣称升级某已发布版本必然解决。 |

主要依据：[Codex协议选择](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/rmcp-client/src/protocol_mode.rs)、[标记消费与外层超时](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/rmcp-client/src/rmcp_client.rs)、[固定SDK的Auto及响应核对](https://github.com/modelcontextprotocol/rust-sdk/blob/98a54789b80110ad210495c4ad845c89e1980471/crates/rmcp/src/service/client.rs)、[较新分支的迟到发现处理](https://github.com/openai/codex/blob/c92700d2993707ee16eb63b35a1cdd7fcc563f69/codex-rs/rmcp-client/src/stdio_handshake.rs)。

因此本次具体冲突不再仅有“Host客户端未就绪”的检测点。但原trace只含帧头，不能回填原参数或错误正文；本次也不把所有旧失败、审核超时及长等待归为同因。记录器刻度与Host计时起点不同，约9.86秒不是对内部10秒时钟的精确复测。

## 2. 冻结的九次独立启动测量

先关闭准备代码的辅助代理，再按A、B、B、A、A、B固定顺序串行启动六个独占stdio进程。A为当前项目配置，B为一个SQLite内存连接、关闭Skills的最小配置。随后各一cProfile及A一importtime，共九次，全部首响应成功、退出0，无SIGTERM或残留。四项fake collector测试先通过，未替换失败或跑到通过。

每次只发一次现代server/discover ID0，不走Host、不运行SQL、不写配置数据库。父进程自身单调时钟从Popen前至首响应；30秒／16帧，关闭stdin5秒，必要时仅SIGTERM自有进程3秒。普通stderr及响应正文不导出。

| 配置 | 普通首响应秒数（按各自实际顺序） | 中位数 |
| --- | --- | ---: |
| A 当前项目 | 7.160、4.264、3.699 | 4.264秒 |
| B 最小配置 | 4.301、4.533、5.166 | 4.533秒 |

A/B同时改变目录、连接数及工具组成，不是单因素性能试验。无主动冷缓存、OS及背景调度未受控；三个重复值仅显示波动，不能推导普遍启动分布或认定A优于B。普通记录没有复现超过10秒；这不否定前批同管道约11.58秒的实际发现迟到，也不能量化前批记录器开销。

带仪器记录：A／B cProfile首响应17.078／12.189秒，server模块导入累计13.930／9.866秒；A配置加载0.167秒、catalog discover0.281秒、create_server0.871秒。A importtime首响应8.104秒，server模块累计导入6.949秒，其内部包含FastMCP／MCP、Pydantic模型、项目诊断与SQLAlchemy导入。**这些累计值嵌套、受仪器影响，不能相加、扣算精确阶段占比或当作普通启动值。** A的cli.main汇总与caller累计不一致，排除该项，不据其作阶段结论。配置、目录及服务构建有成本，但当前证据不支持“Skills过多是主要原因”或先引入启动缓存。这里只将框架／依赖导入识别为优先检查分支。

没有采集开／关的单因素对照，不量化仪器开销；没有模型任务A/B，不宣称token或工具调用效率改善。

## 3. 具体缓解与独立兼容检查

建议从私有Codex配置的目标服务env中**仅删除CODEX_MCP_PROTOCOL_VERSION**，通过当前Host支持的Legacy路径规避现代发现超时后同连接回退。不能把值改成2025-11-25或2025-06-18：0.165的现代stdio选择器会拒绝这些标记。保留command、args、cwd、项目TOML、所有授权和超时设置。

另冻结并执行一个独占兼容进程：使用Host Legacy首选2025-06-18初始化，tools/list获得11工具；analytics_rich_sqlite的常量读取通过；reload_skills空变更成功、revision0；退出0。四个请求及initialized通知均正常。它不修改Host，只作用于测试新进程，不能代替实际Host／模型验证。原有源码与wheel双协议结果保持，不重算成新全量回归。

旧握手改变协议生命周期，暂不使用现代发现／逐请求envelope；不能笼统保证所有现代能力等价。官方0.165测试包含Legacy的SEP1034默认值及elicitation，但本批没有实测当前Host的完整写入确认交互。[官方双模式测试](https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/rmcp-client/tests/mcp_2026_stdio.rs)。本轮新完整任务应聚焦已批准的Query发布与读取，不据此扩大写入批准。

私有草案明确：批准后带expectedVersion删除单键，唯一绑定目标、正常停止目标并做一次Host全局刷新；验证新进程、目录及常量，然后再冻结有限完整双轮任务。失败停止并恢复原标记，最多一次条件恢复刷新。全局刷新会触及该Host加载的其它MCP，进程重启会丢失预览令牌；不终止Host或其它服务进程、不增加SIGKILL／自动重复刷新。**草案尚未执行，新的批准不能由先前两次授权替代。**

## 4. 当前状态与下一步

| 工作 | 状态／停止条件 |
| --- | --- |
| [原因定位] 同版本发现回退 | 已完成源码核对，与捕获轨迹一致；历史其它失败保持各自证据范围。 |
| [耗时定位] 服务启动 | 九项按冻结顺序完成；导入为主要线索，未独立定位所有调度及Host等待。暂不改生产启动或引入缓存。 |
| [兼容验证] 显式Legacy | 独立进程通过11工具、常量及无变更发布；实际Host缓解未执行。 |
| [配置决策] 最小缓解 | 单键删除／恢复和最多两次新刷新范围待批准。无新依赖、协议兼容补丁或产品开关。 |
| [完整验收] 新业务批次 | 缓解原生验证通过后再冻结最多三个完整双轮任务；保留所有失败，不更换到通过。当前历史完整1/3不变。 |

本批受保护20文件、原私有配置及既有231封存成员另行核验。编码辅助代理已关闭，测试自有进程均清理；只读检查当前Host仍一个加载线程、11工具，主会话原生常量读取成功。没有全局刷新、生产代码修改、依赖升级或新增模型用量。私有归档位于local_archive/v382_review/20261029_startup_fallback_analysis，分plans／fixtures／scripts／tests／evidence／drafts／reports组织。历史报告保留当时未定位的状态；本报告补充新结论。
