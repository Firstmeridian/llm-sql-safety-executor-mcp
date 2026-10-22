# v3.8.2：FTS 目录遮蔽与统计来源复评

2026-10-21。**仅评估，未修复生产代码。** 两项反馈属实，均值得在提交前补修，登记开放P2：DRR-2026-137／138。当前不需要重启、重新安装或Full access，不新增实际配置／grant，不写配置数据库。

## 结论与必要性

| [标签] 问题 | 复核结果与影响 | 建议与必要性 |
| --- | --- | --- |
| [功能误拒] DRR-137 FTS authorizer目录 | authorizer.py:329仍用未限定的pragma_table_list表值函数。普通同名表／视图位于main、TEMP或aux均使授权FTS调用、MATCH及Query Skill执行返回unknown_column；估算传播为describe／list／compact／full的metadata_query_failed，精确汇总也失败 | 应修。改为实际schema上的固定PRAGMA目录读取，仍核验真实shadow类型和当前根授权，不禁用authorizer，不按名称前缀直接授予读取能力 |
| [估算错误] DRR-138 统计身份 | sqlite.py:680对每表任取第一条sqlite_stat1。1500行表的部分索引只有1行，错误估算为1，is_large=false；原始COUNT和精确汇总仍为1500 | 应修。优先整表基数来源，否则核验非部分索引；无法确认时走现有受控有界估算，避免误导Agent的LIMIT／聚合选择 |

DRR-137的路径已在四类adapter元数据PRAGMA补修之前存在，属于同类遗漏，未证明是该补修引入的回归；本次以当前源码与此前冻结快照的authorizer身份核对。上轮相邻扫描只覆盖database adapter与skills目录，漏查了authorizer中的bootstrap SQL，应明确承认这一检查范围缺口。DRR-138在完整2c0a9e7隔离包中也复现，不能归因于最近批量统计优化。

先前DRR-135／136的20/20原生检查并不包含新建pragma_table_list对象或ANALYZE部分索引夹具；[原验收](v382_metadata_pragma_repair_2026_10_21/resident_restart/README.md)保留限定范围，不改写为全程序无遗漏。附加JSON依赖修复及已完成的四类列／索引PRAGMA修复无需否定。

## 实测及相邻检查

共394次实际Client调用：当前源码284（16场景）、复用已有正常wheel96（四个原始／对照场景）、隔离2c0a9e7基数案例14。auto／legacy均覆盖；当前源码与wheel各32次独立child-stdio，其余为进程内。所有会话完成，返回的应用文本／结构化一致，安装子集与源码逐项相同。**这是复现和对照通过，不是394次业务执行成功，更不是修复验收。**

| 扩展范围 | 观察 | 归类 |
| --- | --- | --- |
| main／TEMP／aux普通同名表或视图 | 六种碰撞均影响main FTS，原生SQLite仍返回hello；Skill详情可用但实际执行失败 | DRR-137同根，readiness不承诺完整执行成功，不能另算附加JSON依赖回归 |
| main／TEMP／aux／带点schema的FTS根 | 16次组件：无碰撞四次受控读取成功；有碰撞12次unknown_column；独立SQLite16次成功 | DRR-137同根；修复必须使用根的实际schema，不能一律写死main |
| 固定目录方案可行性 | 80次针对五个真实影子名称的PRAGMA，均返回对应schema及shadow类型，保留大小写、单引号与带点schema | 只是只读方案验证，未替换生产实现或测量完整性能 |
| 同时存在完整和部分索引 | 两种创建顺序分别得到1与1500；同一SQL无ORDER BY不能把任意第一条当契约 | DRR-138同根，不把某次恰好正确当修复 |
| WITHOUT ROWID／仅ANALYZE部分索引 | 前者整表基数记录idx=tbl，仍被前面的partial覆盖；后者根本没有idx IS NULL记录，当前仍误估1 | DRR-138同根；仅加idx IS NULL排序不足以覆盖全部情况 |
| 普通完整索引、无ANALYZE及空表 | 当前对应估算正常 | 正例对照 |
| 15000行且无统计／未更新的旧统计 | 前者保留10000有界下界；后者可保留旧100而当前真值1500 | 已有近似估算限制，区别于把不同对象的统计误当整表，未另报独立缺陷 |

另发现现有tests/test_metadata_cost_v382.py:171的test_multiple_index_statistics_keep_first_observation，用相同LIMIT 1计算期望，甚至包含部分索引，因而固化错误。补修时应改为独立整表／合法全索引基数语义，不以实现输出定义正确答案。这是测试遗漏，不单列第三个生产根因。

本次未确认第三个独立生产问题。FTS精确汇总失败、compact／full错误规模、WITHOUT ROWID与创建顺序均是上述两项的同根扩展，不凑独立问题数。当前证据没有证明读取授权绕过。

## 建议实施边界

1. FTS目录仍使用当前独占的原生连接，在callback之外做固定`PRAGMA "实际schema".table_list('影子名称')`。schema引用和名称字面量分别编码；不复用adapter另开连接。按真正目录查询计入lookup预算，共用截止时间，有界取回；验证真实schema/name/type。定点方案可逐个检查五个候选名称；接受必要目录调用成本，实施时测量，不能由本评估推断百分比。
2. 统计先取可解析的整表记录：idx IS NULL；WITHOUT ROWID主树应结合实际对象类型识别idx=tbl。其他记录仅在当前目录确认对应非部分索引后使用。不调用完整get_indexes来获得partial标记，避免不必要的逐索引xinfo和字节成本；目录无法确认则有界受控回退，不返回伪零、不自动执行ANALYZE。
3. 保持先授权／截断后统计、现有批次参数预算、当前授权／authorizer及10000有界读取。目录／统计事实不跨请求缓存。普通统计仍可能过时，修复后不能称实时或精确行数，精确计数仍显式选择。
4. 同批补齐两个原始复现、扩展schema／引用、真实影子拒绝、统计来源／缺失／无效／WITHOUT ROWID／部分ANALYZE及性能定点；一次最终源码／安装检查后统一重启。无需新增AST、通用缓存或配置开关，不增加Agent固定调用步骤。

主要收益是恢复合法FTS任务和正确的表规模提示，减少无效改SQL／错误选择全表读取的机会；本轮没有模型任务或token对照，不能声称节省具体token或工具次数。代价主要是少量目录核验与回归覆盖，保留有界估算而非隐式全表精确COUNT。

## 归档与范围

[证据入口](v382_fts_catalog_statistics_assessment_2026_10_21/README.md)。77项运行资源及三份实际TOML不变，既有wheel77资源与当前源码一致；所有临时夹具自动清理，未调用配置数据库、原生Host或新模型，无新构建／安装／全量回归／性能验收。55份旧封存、1723文件记录保留，包括上轮闭环及其准备失败。本次新风险和建议不能提前写进commit草案的已修复项。

## 官方依据及适用限制

[SQLite table_list说明](https://www.sqlite.org/pragma.html#pragma_table_list)提供实际schema及shadow类型，支持固定schema和单个表名过滤；同名对象干扰的具体表现来自本项目隔离复现，而非仅由文档推断。

[SQLite sqlite_stat1定义](https://www.sqlite.org/fileformat2.html#the_sqlite_stat1_table)说明索引统计首项是索引基数；部分索引不等于整表，idx为空及WITHOUT ROWID主树有各自含义。[ANALYZE说明](https://www.sqlite.org/lang_analyze.html)也不保证统计随每次数据写入实时更新。修复应校正统计身份，同时保留近似性质。
