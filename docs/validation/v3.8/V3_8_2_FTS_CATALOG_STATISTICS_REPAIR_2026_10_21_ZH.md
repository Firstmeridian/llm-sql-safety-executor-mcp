# v3.8.2：FTS 目录、统计来源与 external-content rowid 补修

2026-10-21，版本仍为 3.8.2。维护者已批准修复 DRR-137／138 及相邻问题。本批另通过冷态对照新确认第三个独立生产根因 DRR-139，并在授权的相邻范围补修。它不是上一轮已确认的问题，也不能把原回归中的错误预期另算为生产根因。

## 改动与边界

| [标签] 项目 | 变更前的问题 | 变更后原理与收益 | 代价／限制 |
| --- | --- | --- | --- |
| [功能修复] DRR-137 FTS 目录 | pragma_table_list 表值函数可被 main／TEMP／aux 同名业务表或视图遮蔽，使 FTS 查询、Skill 与数据估算误拒 | 在当前独占物理连接、回调外，按实际根 schema 对五个固定影子名称使用语句形式 PRAGMA table_list；分别编码 schema 标识符和目标字符串，继续核验真实 schema/name/shadow 类型 | 每个根由一次合并 TVF 查询变为五次定点 PRAGMA；每次扣目录预算、检查累计截止时间、有限取回并关闭 cursor。不是授权名称前缀或关闭 authorizer |
| [准确性修复] DRR-138 行数统计 | 任意第一条 sqlite_stat1 可能属于只覆盖一行的部分索引，1500 行表被估为 1，is_large=false | 优先 idx IS NULL 的整表统计；缺失／无效时按固定 index_list 核验当前完整索引，WITHOUT ROWID 用 table_list 核验实际主树身份；无法确认则走原有受控限量读取 | 完整索引来源核验增加目录查询；最多128个索引候选，过量回退；统计阶段共享超时、绑定分批、保持当前连接独占。统计仍可过期，10000行回退仍是下界，不自动 ANALYZE 或升级为全表 COUNT |
| [功能修复] DRR-139 external-content rowid | 默认 rowid、_rowid_、oid 与编译期列名称不一致；INTEGER PRIMARY KEY 别名回调报告 id，普通 rowid 的同义拼写回调报告 ROWID，导致冷态误拒；可信预热可能掩盖缺陷 | 核验实际内容表的固定 table_list／table_xinfo，必要时 index_list，将隐式 rowid 映射为编译列；同名显式列优先，区分 WITHOUT ROWID、视图／虚表和 INTEGER PRIMARY KEY DESC | 仅使用这三种隐式拼写时增加2–3条目录查询；列／索引取回上限65536、查询预算及截止时间沿用当前读取操作。不扩大直接底表／影子表 grant，不改原 SQL |
| [测试修正] 独立真值 | 原测试从相同 LIMIT 1 查询构造 expected，将错误行为固化 | 使用固定夹具真值及原生 SQLite 核对；覆盖索引顺序、仅分析部分索引、WITHOUT ROWID、失效／孤儿统计、统计缺失／过期、超限候选、目录遮蔽、冷／暖态和授权拒绝 | 更新错误预期不算第四个生产根因；保留初轮测试／夹具错误日志，不混为生产验收 |

固定目录查询与会求值的数据读取继续区分。仅已授权、已截断的表集合进入统计；fallback/sample/count 保持受控读取。没有新解析框架、通用缓存、TOML 开关、依赖、提示、工具 schema 或 Agent 必需调用步骤，也未改实际配置、grant 或配置数据库。

## 第三个独立根因的证据

原有冻结快照与修复前当前源码各15个冷态组件，均有8个相同误拒；独立 SQLite 全部返回 hello。相同定义先经可信原始查询预热时，15个受控调用又全部成功。因此不能以暖态成功证明冷态兼容，也不能将现象解释为 Host 缓存。补修后15个冷态均成功。

比较三类定义 id INTEGER PRIMARY KEY、id INTEGER PRIMARY KEY DESC、id TEXT PRIMARY KEY，及默认／rowid／_rowid_／oid／显式 id 五种配置。显式同名 rowid 列另有回归，避免把合法业务列替换成整数主键。此来源相对当前批前快照已存在；未据此宣称2c0a9e7已支持相同 FTS 能力。

## 验证与状态

最终回归3340通过／4项可选跳过，新增90例；类型0错误／0警告、提示词契约通过。源码及正常wheel各488次调用：每侧进程内356、独立stdio132，auto／legacy均覆盖；22场景全部完成，应用文本／结构化一致，两侧完整应用记录相同。77运行资源与正常安装一致，实际三份TOML及21提示资源不变，自清理夹具数据摘要保持。

原生驻留验收待维护者一次手动重启，已冻结10项既有别名计划。两次独立sqlite3只读查询仅用于冻结当前FTS／列真值，不算原生MCP验收；本批尚未调用配置数据库的MCP。旧20/20与模型证据保持原范围，不替代本批验证。特殊碰撞、部分索引、冷态rowid仍以本批源码／安装夹具为证据，不宣称原生重建了它们。

全仓内部TVF目录SQL相邻扫描不再发现FROM／JOIN pragma_*；列／索引四类修复保持。没有再确认第四个独立生产根因。错误的镜像测试、失效／过期统计、10000下界和超预算回退分别记录，不合并成新增缺陷。

[可核对证据](v382_fts_catalog_statistics_repair_2026_10_21/README.md)。这是应用文本／structured content 记录，不是完整协议帧、通知或模型 token 测量。以前的[开放评估](V3_8_2_FTS_CATALOG_STATISTICS_ASSESSMENT_2026_10_21_ZH.md)及其失败样本保留。

## 串行成本与解释

测试／构建结束后依次A1→B→A2，内存SQLite、暖态直接adapter；每场景10次预热、7组各25次，报告组均值的中位数，单位ms。基线为本批前工作树，含之前未提交修复，不能解释成相对2c0a9e7的完整版本提升。

| 场景 | 旧A1／A2 | 新B | 范围 |
| --- | --- | --- | --- |
| fts_internal | 1.519 / 0.914 | 0.971 | 相同结果；有基线漂移 |
| fts_external_id | 1.707 / 1.072 | 1.122 | 相同结果；有基线漂移 |
| fts_external_default_warm | 1.794 / 1.032 | 1.165 | 相同结果；有基线漂移 |
| stats_none | 2.232 / 1.719 | 1.560 | 相同结果；有基线漂移 |
| stats_table | 0.749 / 0.676 | 0.601 | 相同结果；有基线漂移 |
| stats_full1 | 0.711 / 0.491 | 1.090 | 相同结果；有基线漂移 |
| stats_full64 | 0.790 / 0.445 | 2.575 | 相同结果；有基线漂移 |
| stats_without_rowid | 0.800 / 0.497 | 1.314 | 相同结果；有基线漂移 |
| stats_partial | 0.819 / 0.541 | 0.520 | 旧1→新1500，工作结果不同 |

完整索引1个约增加0.38–0.60ms，64个约增加1.79–2.13ms；WITHOUT ROWID约增加0.51–0.82ms。这是当前来源核验的实际代价，不宣称无退化。其余场景受A1／A2明显漂移影响，不承诺提速；统计部分索引场景恢复正确1500，不能将旧错误1当作等价工作量。

FTS内置目录语句从1次合并TVF变为5次定点PRAGMA，trace还包括原有database_list，因此FTS trace PRAGMA为1→6；默认external-content rowid再增加3次，本例为1→9。带显式真实id时无需rowid目录补查。trace事件不是协议或Agent调用次数；没有新增固定Agent步骤，亦无新token／模型成本结论。

保留初轮夹具错误、可信预热掩盖现象、脚本分类错误、计时导出Row序列化错误、沙盒类型路径失败及被中止的全量日志；最终验收和时序另文件，不覆盖失败。

## 官方依据

SQLite 说明 stat1 第一个整数是索引行数，部分索引可少于整表；idx IS NULL 对应表基数，WITHOUT ROWID 主树使用 idx=tbl。[统计格式](https://www.sqlite.org/fileformat2.html#the_sqlite_stat1_table)。固定 PRAGMA 可绑定 schema，table_list 区分 shadow 和 WITHOUT ROWID，index_list 标记 partial；table_xinfo 保留实际列身份。[PRAGMA 说明](https://www.sqlite.org/pragma.html#pragma_table_list)。INTEGER PRIMARY KEY 和内联 DESC、显式 rowid 名称及其别名规则另见 [CREATE TABLE](https://www.sqlite.org/lang_createtable.html#rowids_and_the_integer_primary_key)。

## 重启后验收补充（2026-10-21）

维护者确认重启后，冻结的10/10既有别名原生检查全部通过：FTS MATCH与表调用均返回1，pages10列／完整索引及compact/full6表34列与独立只读SQLite一致，各表行数估算符合当前真值；影子表和耗时函数继续拒绝，MySQL常量读取成功。文本／结构化一致，77磁盘运行资源、三份私有TOML及SQLite文件不变，59份旧manifest／1998条文件记录保持。

DRR-137／138／139按声明范围完成验收；上文“待重启”及父证据中的pending保留为当时检查点。目录碰撞、部分索引1500→1和默认rowid冷态专用夹具仍属于源码／安装验证，不将既有别名smoke扩成这些原生重放。无新模型、token、构建、全量或速度声明。[独立重启补充及原始应用记录](v382_fts_catalog_statistics_repair_2026_10_21/resident_restart/README.md)。
