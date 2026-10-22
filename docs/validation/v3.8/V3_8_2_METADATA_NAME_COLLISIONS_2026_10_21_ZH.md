# v3.8.2：内部元数据表值函数的同名业务对象遮蔽

后续状态：维护者批准先修DRR-136再与DRR-135统一重启；固定main绑定PRAGMA补修已实施，源码／安装及成本见[后续记录](V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md)。本页保留当时仅评估／待处理范围，旧封存字节不改。

日期2026-10-21；DRR-2026-136，开放P2。本次仅评估，未实施修复。这是本轮补查新确认的独立根因；上一轮并没有第二项已确认缺陷。

## 复现与范围

独立临时库中，main.anchor(n)返回7，另外建立普通业务表pragma_table_xinfo／pragma_table_info／pragma_index_list／pragma_index_xinfo。修改前77资源快照和本轮源码各15场景／30次adapter元数据调用，结果完全相同；包括main／TEMP／aux及普通名称对照。每份快照12个预期元数据失败，普通名称对照正常。

另以进程内Client的auto／legacy各测main的四个同名对象，修改前／本轮各32次应用调用，暴露帧逐项相同：

| 同名业务对象 | 实际影响 | 正常对照 |
| --- | --- | --- |
| pragma_table_xinfo | describe_table及compact/full get_full_schema返回metadata_query_failed，不能取得列 | 原始SELECT n FROM main.anchor仍返回7；直接PRAGMA main.table_xinfo('anchor')返回n |
| pragma_table_info | describe_table仍成功，但indexes_status=unavailable；compact/full schema仍成功 | 原始读取不变 |
| pragma_index_list | 索引元数据无法取得，列与schema保持正常 | 原始读取不变 |
| pragma_index_xinfo | 索引元数据无法取得，列与schema保持正常 | 原始读取不变 |

组件覆盖三类schema；协议级验证仅main，未冒充附加库原生Host或安装包复现。不是所有pragma_名称都影响全部工具，也没有据此证明授权绕过或业务数据改变。完整组件／Client应用记录见[本批证据](v382_attached_json_repair_2026_10_21/README.md)。

## 根因

get_columns使用FROM pragma_table_xinfo(...)，get_indexes使用pragma_index_list／pragma_index_xinfo／pragma_table_info。这些是可被普通业务关系遮蔽的表值函数名称；给函数传main参数只指定被检查对象的schema，不能保证调用头仍指内置函数。观察到的普通表遮蔽会产生“不是函数”的SQLite错误，经既有安全边界转换为MetadataQueryError。

直接PRAGMA语句不经过这个同名表解析路径。[SQLite PRAGMA说明](https://www.sqlite.org/pragma.html)。本轮DRR-135新增目录列表已采用固定PRAGMA database_list语句，并有普通pragma_database_list表的回归，未在新代码中重复此问题。

## 建议

值得修复，建议单独一批收敛内部目录读取：

1. 列信息使用固定、显式main的PRAGMA table_xinfo语句，原有可见生成列／隐藏列／cid顺序契约保持。
2. 索引使用固定PRAGMA index_list／index_xinfo及主键信息，保留方向、collation、表达式、部分索引、唯一性、排序及行数／耗时预算。
3. 参数／对象名严格按SQLite语法编码，不把普通业务名称改成保留名称，也不新增授权或关闭authorizer。仅给表值函数加main前缀不能解决main内同名对象，不应当作完整修复。
4. 同时验证主库绑定、TEMP／aux同名对象、正常生成列和索引投影，并测索引较多时成本。

主要代价是部分元数据组合从单条JOIN改为逐索引PRAGMA，内部查询次数可能增加；需有界执行及定点测量。正常Agent工具调用数量无需增加。新连接隔离等方案成本更大，目前没有必要新增通用框架或连接类型。

本轮批准的是DRR-135修复，以及对独立根因的评估；DRR-136保持开放，不把未实施方案写成已修复或写入commit的Fixes。原始失败及旧封存保留，不必重开结果编码／限额或SQLite EXPLAIN验收。

