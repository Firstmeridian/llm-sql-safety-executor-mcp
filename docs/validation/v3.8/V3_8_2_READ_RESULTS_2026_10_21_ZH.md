# v3.8.2：共享读取结果边界与条件依赖补修

日期：2026-10-21；版本保持 3.8.2。接续仅评估批次，维护者批准统一 query／Query Skill／sample 的结果检查、值编码和限额，再补齐条件依赖。不扩 AST 适配、不放宽 authorizer，不新增依赖、私有配置／grant 或开关。

同日后续复评曾确认未限定JSON调用仅在附加库存在同名FTS时遗漏依赖，登记DRR-135；随后已获批准补修并完成源码／安装验证，见[当前有序观察实现](V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md)。下述原生16项及原已测源码／安装范围保持，不重新归属后续源码；读取结果三项修复不因此重开。

## 变更、原因和代价

| 项目 | 变更前的问题 | 方案与收益 | 代价／边界 |
| --- | --- | --- | --- |
| [功能修复] 重复标签（DRR-131） | 7 AS n,99 AS n 转 dict 后只剩 99，仍返回成功 | 实际 Row 键序列在字典投影前检查，返回 duplicate_result_columns 及唯一 AS 提示；n／N 保持独立，不套用授权名称规则 | 暂不新增 columns/rows 格式或自动改名；Agent 需在重复标签时改 SQL 重试。空结果没有返回行，不新增列描述接口 |
| [功能修复] 值编码（DRR-132） | BLOB 按内容决定成功或通用工具错误；inf 变成 SQL NULL | bytes／bytearray／memoryview 统一为 {$type:binary,encoding:base64,data:…}；非有限 float 为 {$type:float,value:Infinity/-Infinity/NaN}。日期、时长、Decimal 等保留既有 JSON 表示 | 二进制体积约 4/3 加标签；必要递归编码开销。不支持对象、非法 Unicode 返回 result_encoding_failed，不暴露异常文本／任意 __dict__ |
| [功能修复] 共享限额（DRR-133） | 首行过大仍返回，sample 没有字符保护；计量的 str 与实际序列化不同 | 同一编码结果按紧凑 JSON 字符数累加前缀，只编码每个计量行一次；首行超限返回零行，明确原因及缩小投影提示。三个读取入口共用处理与失败路径 | sample 增加 total_rows、truncated、truncation_note，截断时附 reason。非截断普通 query／Skill 不增加 reason 字段。result_chars=1 明确拒绝，0 仍关闭；数据限额不等于整帧／token／执行或 fetch 限额 |
| [功能修复] 三态依赖（DRR-134） | 非默认 JSON 同名 FTS 或元数据失败时被当作无依赖，执行前提前返回 | 条件语法仍纯缓存，当前观察分类 builtin／stored／unverified；未知及存储依赖保留，发现／详情／执行共用 readiness。非默认 schema 仍明确无法核验 | SQLite 开启 readiness 时每快照增加一次固定 TEMP 目录查询，覆盖两个 JSON 名称，避免未限定调用被 TEMP 遮蔽后仍称 builtin；不遍历 attached schema，不缓存目录事实 |

ReadResultError 是读取表示失败，独立于数据库查询异常及写入结果。失败发生于 OperationResult／MCP 协议编码之前；Query Skill 的结果编码失败也进入原有失败审计路径。固定错误不携带原始异常、二进制或未知对象内部信息。

原 SQL、参数、方言／会话、授权、受控读取、预览令牌和写入执行结果不在本批重写。关闭 readiness 不探测目录，实际读取仍即时核验模块及授权。默认 schema 的明确 builtin 依赖不要求业务表 grant；TEMP 或其他 schema 不因同名而获得默认 schema readiness 覆盖。full Skill 详情只在有条件依赖时附 conditional_dependencies，普通查询不新增空字段。

## 验证状态

源码、安装、驻留 Host 和模型证据分别记录。[源码／安装检查点](v382_read_results_2026_10_21/README.md)保留当时待重启的状态；维护者确认重启后，另追加[原生验收补充](v382_read_results_2026_10_21/resident_restart/README.md)，不挪用前批 Luna 完成率或 token 数据。

最终全量 **3126 通过／4 可选跳过**，包含本批 **64 项新增回归**；类型、源码／安装提示契约通过。正常独立 wheel 安装后 **77 项运行资源**与最终源码逐项相同，复用已核验的离线构建及冻结依赖，无全局安装或依赖升级。最终源码／安装各 **176 次调用**：进程内 auto／legacy 和独立 child-stdio auto／legacy 各 44 次。全部期望成立，文本和结构化应用返回逐项一致；其中各 24 个工具错误是按既定范围拒绝非默认 schema Skill，不能说成所有调用都执行成功。受限函数及直接影子表读取继续拒绝。

临时 SQLite 文件及77资源／三份私有TOML摘要前后一致，夹具已清理；配置 MySQL 仅执行常量 SELECT，既有 SQLite 也只做常量探测。43 份此前封存／1152 条文件记录保持原字节。前置评估失败、首次全量的测试替身接口遗漏、首次类型检查的依赖路径及真实缺失导入、中间通过版本均保留。

维护者确认重启后，冻结的 **16/16 项原生只读检查通过**。SQLite／MySQL 的常量及唯一标签正常，重复标签均返回 duplicate_result_columns；UTF-8／非 UTF-8 BLOB 均为带类型 base64；超限首行均返回零行并说明 char_limit。SQLite 正负 Infinity 与 NULL 保持区分，SLEEP 及 FTS 影子表仍拒绝。16 次返回的文本／结构化内容一致，isError 均为 false；预期失败通过应用级 error_code 表达。

重启前重复列仍返回 n=99 的 native_before 原样保留，不断言其缓存根因。本次核对磁盘上的77项运行资源、三份私有TOML及配置SQLite文件摘要不变，45份旧封存／1329条文件记录完整；资源摘要不作为驻留内存代码的直接证明。特殊 aux／TEMP Skill、元数据失败、sample 范围归属源码／安装，不改私有配置为原生补夹具。没有新增 Luna 完整任务、回归重跑、构建或 provider token／引导消融对照，不挪用前批模型完成率。

## 局部成本与取舍

最终在测试／构建结束后串行 A/B/A，以本批修改前工作树为基线，并非 HEAD。普通数据数组摘要相同，记录每阶段9组样本；固定一次 readiness 观察实际目录语句为1→2→1。单位为毫秒：

| 暖态局部处理 | 基线 A1／A2 中位 | 最终 B 中位 |
| --- | --- | --- |
| 20 行结果编码及计量 | 0.107／0.155 | 0.162 |
| 100 行结果编码及计量 | 0.501／0.836 | 0.939 |
| SQLite readiness 快照 | 0.155／0.228 | 0.375 |

阶段漂移明显，不给普遍退化百分比或延迟保证。这些是局部组件成本，不是 MCP／模型完整任务延迟；固定 TEMP 查询和必要值检查有开销，不能称为提速。普通成功 query／Skill 的数据和非截断字段不增加；二进制及非有限值改变表示，sample 增加必要状态字段，不能推导实际 provider token 增减。

计量使用已有 Pydantic 编码器，避免与实际协议的浮点指数／转义格式不同，也减少 Python 每行 JSON 计量开销。接入前单进程原型的100行处理为1.001→0.737ms，随后最终回归补了三个精确边界；原型不是完整工具提速证据。更早计量脚本用了不存在的清理方法，未落盘的失败不并入结果；初始重叠调度也未作为串行数据。最终取以上完整串行记录，旧通过／原型记录保留。

## 完成范围与保留边界

上述原生检查已完成，本批按源码／安装／原生分别声明的范围完成验收。现有配置没有 aux/TEMP Skill 成对夹具和 sample 工具注册时，相应细分范围以隔离 Client／安装包为证；不为验收临时改私有配置或 grant。本次仅追加文档和独立封存，无需再次重启或重复安装。

没有新增通用结果缓存、流式游标、字段局部截断、AST 适配或 authorizer 开关。数据大小的保证只针对 data 数组的紧凑 JSON 字符，不含 SQL 回显、提示、元数据、协议重复内容或通知；小预算不能承诺整条工具结果大小。二进制和数值类型表示改变需同步调用方解释，项目尚未正式发布，不保留会丢失数据的隐式 UTF-8 行为。

## 依据

- [Pydantic bytes 与非有限数配置](https://docs.pydantic.dev/latest/api/config/)
- [SQLAlchemy Row._mapping](https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Row._mapping)
- [SQLite FTS5 查询形式](https://sqlite.org/fts5.html#full_text_query_syntax)

本批不升级这些依赖，不把解析成功等同于实际数据库绑定正确。
