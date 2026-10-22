# v3.8.2 主键身份、顺序与双后端矩阵：DRR-141

日期：2026-10-21。维护者批准实施。源码／正常安装包检查完成；最新重启后，当前 Codex 原生通道完成冻结 **12/12** 核验，新主键位置、完整列投影、查询及继续拒绝均符合预期，驻留一致性已闭环。此前原生 7/12 与新 CLI 12/12 的差异及维护者暂缓重连检查点完整保留；本次恢复成功仍不能证明此前差异由缓存导致。

MySQL 方言及服务端验收按维护者最新决定以 MySQL 为准，MariaDB 不作为本轮验收要求。SQLite 保持独立原生验证。

## 改动与契约

| 项目 | 原方案与问题 | 当前方案 | 收益与代价 |
| --- | --- | --- | --- |
| SQLite 列元数据 | PRAGMA 已提供主键位置，但仅投影 PRI 标记，compact 按表列序列成员 | 实际 PRIMARY 成员携带可选 `primary_key_position`，直接复用 table_xinfo.pk | 保留键序；无新增查询，增加少量字段 |
| MySQL 单读／批读 | COLUMN_KEY=PRI 被当作真实 PRIMARY，无法确定复合键序；无主键的非空唯一索引也可能被误报主键 | 原列查询左连接 KEY_COLUMN_USAGE 的实际 PRIMARY，按 schema／表／列绑定；二进制残余比较保留存储组件身份 | 区分原生展示标记和实际主键；没有额外往返，有目录连接成本 |
| compact | 按表列序列 PRI，反序复合键可能与正序键合组 | 按真实位置排列成员；无 PRIMARY 返回 `[]`；分组签名包含位置 | Agent 可直接取得正确成员顺序，分组／返回体可能增大 |
| full／describe／可选 summary | 仅保留 key 标记 | 保留可选位置；非成员省略；普通列顺序不变 | 不需要额外工具步骤，返回字段增加 |
| 物理索引边界 | 容易把成员列表理解成完整键定义 | `primary_key` 是有序成员摘要；重复物理键项、方向和 collation 仍看 describe.indexes | 不新增重复索引查询，不承诺完整 DDL 或索引等价 |

`primary_key_position` 是从 1 开始的正整数，只属于实际 PRIMARY 成员。
`key_type`（full 中为 `key`）继续忠实保留数据库展示值，两者独立。
MySQL `PRI` 不证明 PRIMARY；不能根据表列序猜位置，不能把目录失败伪装成空主键。
SQLite `PRIMARY KEY(b,a,b,c)` 的成员位置可以是 b=1、a=2、c=4，不能强制连续；完整物理键项仍为 b,a,b,c。
没有修改 AST／authorizer、原 SQL、授权、依赖、提示、私有配置或版本号；没有新增开关、缓存或 Agent 必需轮次。

此实现取代此前“仅评估／未实施”的当前状态，但[历史评估](V3_8_2_COMPOSITE_KEY_METADATA_ASSESSMENT_2026_10_21_ZH.md)及其封存资料保留原时点，不回写当时的结论。

## 同功能、独立真值矩阵

SQLite 3.45.1 和 MySQL 8.0.25（lower_case_table_names=1）各 13 对象：12 张表、1 个视图。两端共同覆盖正／反序复合键、键方向、无主键非空唯一／复合唯一、可空唯一、无键、主键并存唯一、混合大小写列引用、点号／空格／Unicode 组件；SQLite 另有 WITHOUT ROWID 和重复键项，MySQL 另有 MyISAM／MEMORY 非空唯一索引。

SQLite 直接取独立连接的固定 table_xinfo／index_list／index_xinfo。MySQL 独立查询 KEY_COLUMN_USAGE，并用 **SHOW INDEX 的 PRIMARY／Seq_in_index 再次交叉核验**，不能仅以新适配器输出作为真值。所有测试 schema 均为随机新建、仅本批拥有，结束后删除；未改已有业务表、私有 TOML 或 grant。SQLite 读取前后文件摘要一致。

| 验证阶段 | SQLite | MySQL | 结果 |
| --- | --- | --- | --- |
| 冻结修复前正常 wheel | 96 应用调用 | 96 应用调用 | compact 分别有 6／8 张表的主键成员身份或顺序与真值不符 |
| 当前源码 | 96 应用调用 | 96 应用调用 | 所测成员／位置、完整索引及全列投影对齐原生真值 |
| 当前正常安装 wheel | 96 应用调用 | 96 应用调用 | 与源码一致；仅规范化已逐项核实的随机 schema 字段 |
| 全量回归 | 两端共享 3373 通过／4 可选跳过，新增 20 项回归 | 类型 0 错误／0 警告；提示资源检查通过 | 旧测试夹具更新的初次失败和最终结果分别保留 |

每阶段每后端覆盖 in-process／独立 stdio × auto／legacy，四组各 24 调用：describe、精确 summary、compact 分组／不分组、full、list_tables、raw、sample、未授权表及受限函数拒绝。应用文本与 structured 内容一致；这不是完整协议帧，也不是完整模型任务。

实际 MySQL 的 InnoDB、MyISAM、MEMORY 夹具均复现：非空唯一索引列显示 PRI，但原生 PRIMARY 目录为空。当前 compact 正确返回空主键，同时保留原生 PRI 展示。此前 8 张既有表未复现该风险的评估仍正确描述其当时范围，现已另行取得直接证据。

相同 12 表矩阵 compact 分组：SQLite 7→8，MySQL 7→9；compact 文本分别 1959→2057、1899→2069 字符，full 分别 2671→3046、2581→2856 字符。更准确的 metadata 可能增大模型输入，字符数不是 provider token。不得把本次局部结果解释为两种后端整体质量排名。

## 成本与取舍

固定同一后端、同一个 64 表临时夹具，串行运行旧正常 wheel A1 → 当前源码 B → 旧正常 wheel A2。每阶段 5 次预热、30 次计时；没有与回归／构建并跑。表目录只投影已授权 64 张表，排除拒绝控制对象。以下基准是 A1、A2 **各自中位数的均值**；原始样本和两个基准阶段均保留。

| 后端／场景 | 基准中位参考 ms | 当前中位 ms | 差值 ms | 变化 |
| --- | ---: | ---: | ---: | ---: |
| SQLite 单表列 | 0.123 | 0.173 | +0.050 | +40.9% |
| SQLite 64 表列批读 | 8.127 | 7.993 | -0.134 | -1.6% |
| SQLite compact 工具 | 112.083 | 106.646 | -5.438 | -4.9% |
| SQLite full 工具 | 109.892 | 108.145 | -1.747 | -1.6% |
| MySQL 单表列 | 14.549 | 14.434 | -0.115 | -0.8% |
| MySQL 单表批读 | 12.753 | 13.510 | +0.757 | +5.9% |
| MySQL 64 表列批读 | 21.743 | 25.233 | +3.490 | +16.1% |
| MySQL compact 工具 | 40.657 | 43.331 | +2.675 | +6.6% |
| MySQL full 工具 | 40.703 | 43.084 | +2.381 | +5.8% |

这是准确性修复，不是速度优化。MySQL 目录连接与新增输出有实际成本，本机完整工具中位约增加 2.4～2.7 ms；SQLite 单表 0.05 ms 上升样本同样保留，不能笼统称“零成本”。SQLite 整体工具差异落在基准阶段波动范围内，不承诺提速。这里不测冷启动、远程部署、尾延迟保证或模型 token；A/B 输出准确性及体积也不同，不能全归因于计算优化。64 表一批仍是一条列目录查询；没有回退为每表索引读取，也没有删去授权、会话或结果检查。

## 最新重启核验与历史边界

- 正常 wheel 的 77 项运行资源与源码一致；只复用现有冻结依赖，不新增运行依赖或全局安装。三份私有 TOML及先前 71 份 manifest／2180 条文件记录不变。
- 初始 Unicode 表名夹具被 MySQL 实际存储规则改写，改用两端共同有效名称后重跑基准与当前；不套用 SQLite 身份规则、不扩大 grant。模拟行形状遗漏、沙盒导入失败及随机 schema 对照修正等均保留在准备记录。
- 当前没有新增确认的相邻独立生产根因；这不保证全部版本／引擎／元数据均完整。其他 lower_case_table_names、隐藏自动主键、DDL 并发变化未实测；MariaDB 不作为验收要求。完整类型、外键和完整 DDL 仍不在本次契约。
- 此前差异检查点执行冻结 12 项：现有 SQLite 6 表、Sakila MySQL 16 表／89 列。SQLite pages、MySQL film_actor／film_category 的 describe，以及两端 full schema 缺少新位置字段，共 5 项未通过；其余 7 项通过，但其中兼容旧输出的检查不能单独证明当前通道加载了新源码。
- 相同实际连接、同 12 项计划的全新 CLI/stdin-stdout auto 全部通过，完整列／位置及原生目录对齐。77 运行资源、三份私有 TOML、配置 SQLite 文件及 73 份先前封存／2279 条记录保持不变；MySQL 原生目录复查也与冻结真值一致。
- 只读进程观察发现 4 个相同入口的 SQL MCP，其中 3 个早于源码修改、1 个在修改后启动。本次执行工具与其中 3 个进程均属于同一 Codex 父进程，但仍不足以确定实际工具通道绑定哪个客户端／进程；不能把它写成已确认缓存根因，也不能否认维护者已完成某次重启。
- 此前维护者选择稍后重连；本次已完成12/12，保留此前失败及父 pending 封存。特殊反序／唯一／重复键夹具仍保持源码／安装证据，不冒称当前 Host 原样重放。[实际通道与新 CLI 对照](v382_primary_key_metadata_repair_2026_10_21/resident_restart/README.md)。
- 此前差异检查点没有新增 Luna 任务。本次另建完整任务／成本补充，分别保留其源码、历史基准、任务与计数范围；不改父 pending 或此前差异封存。

可核查的[记录、脚本及摘要](v382_primary_key_metadata_repair_2026_10_21/README.md)；私有补充位于 `local_archive/v382_review/20261021_primary_key_metadata_repair/`，按 baseline／scripts／evidence／reports／drafts 分层。

依据：[SQLite table_xinfo／table_info 主键序号](https://www.sqlite.org/pragma.html#pragma_table_xinfo)、[SQLite index_xinfo](https://www.sqlite.org/pragma.html#pragma_index_xinfo)、[MySQL COLUMNS 的 PRI 含义](https://dev.mysql.com/doc/refman/8.0/en/information-schema-columns-table.html)、[KEY_COLUMN_USAGE 的约束内位置](https://dev.mysql.com/doc/refman/8.0/en/information-schema-key-column-usage-table.html)、[STATISTICS 的 PRIMARY 和索引序号](https://dev.mysql.com/doc/refman/8.0/en/information-schema-statistics-table.html)。这些定义用于解释目录事实，不替代本项目授权。

最新12项包括SQLite pages／pages_fts describe、两端compact/full、MySQL film_actor／film_category describe、两端常量值、影子表及耗时函数拒绝。SQLite6表34列、Sakila16表89列与冻结独立目录逐项对齐；完整调用见后续完整任务补充。特殊反序／唯一／重复物理键夹具仍属源码／安装矩阵，不冒称当前Host重放。

本批后续[完整任务与成本](V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md)另存最新12/12原生、十五项历史配对任务及三项弱提示试验。业务结果正确不等于普遍更快／更省，解释不足及成本上升均保留。
