# v3.8.2：SQLite 原生声明类型补修

**最新状态：维护者已重启，9/9项冻结原生核验通过；新增相邻源码／安装各144调用亦通过。下文初始pending保持补充前收尾时点，当前结论见文末重启补充。**

2026-10-21，版本仍为3.8.2。维护者批准实施DRR-2026-140。源码和正常安装包验证完成；**尚待维护者手动重启后的9项冻结原生核验**，不把当前磁盘源码视为驻留进程已更新。

## 修复与契约

| 项目 | 修复前 | 修复后及原理 | 好处与代价 |
| --- | --- | --- | --- |
| 单表／summary类型 | `row[2] or "TEXT"`把原生空类型补成TEXT | get_columns直接保留table_xinfo返回的类型字符串，包括空字符串／空格 | 避免伪造声明；客户端需接受已有字符串字段的空值 |
| compact/full | 空类型和TEXT可能合并；full同样报告错误类型 | 共用原生类型；分组签名自然区分空类型与TEXT | 信息更准确，分组增多可能增加响应体 |
| 同源对象 | 未声明普通／生成列、CTAS、FTS可见列和部分表达式视图受影响 | 各投影均与独立原生PRAGMA逐列对比 | 不按行值／表达式猜测类型；FTS隐藏列、生成列标记和列序保持 |
| 验收预期 | 旧脚本复制TEXT补值后对比，不能证明类型无损 | 新测试直接比较原生字符串；旧记录保留并限定归一化范围 | 防止测试镜像实现缺陷；不重写历史失败或验收 |

`data_type`、full的`type`和compact列对第二项提供SQLite报告的类型元数据，不保证亲和性或实际值的存储类。空字符串不代表TEXT，也不能统一改写为BLOB。普通未声明列与表达式视图的语义不同；当前SQLite3.45.1下`n`和`n ""`虽都报告空类型，比较行为仍可能不同。compact只声明adapter可见元数据相同，不证明完整DDL或SQLite语义等价。参见SQLite官方[类型、亲和性及比较规则](https://www.sqlite.org/datatype3.html)、[table_xinfo](https://www.sqlite.org/pragma.html#pragma_table_xinfo)、[生成列](https://www.sqlite.org/gencol.html)及[STRICT ANY](https://www.sqlite.org/stricttables.html)。

运行资源仅`database/sqlite.py`的类型字段及说明变化。不新增查询、求值、缓存、AST规则、依赖、配置开关或Agent固定调用；三份私有TOML、授权、提示资源及配置数据库不变。get_columns每表仍执行一次固定main.table_xinfo；MySQL类型映射不变。

## 验证

| 检查 | 结果与范围 |
| --- | --- |
| 新增回归 | 13项；涵盖9类声明、两种Client模式全部投影／分组、元数据不求值及STRICT ANY |
| 相关回归 | 80通过，25项框架弃用告警 |
| 最终全量 | 3353通过、4可选跳过，547项框架弃用告警；287.96秒 |
| 类型／提示 | pyright 0 errors／0 warnings；提示契约检查通过 |
| 源码／正常wheel | 各184次应用调用；inprocess／独立stdio各auto／legacy四组，每组46次；两侧各36项直接列观察 |
| 独立真值 | 18类对象原生table_xinfo及读取结果；describe、可选summary、compact分组／不分组、full逐列对比原始类型，不补TEXT |
| 一致性 | 源码／安装应用记录逐项相同；每次文本与结构化结果相同；原始读取／Query Skill业务语义与修复前一致 |
| 安装身份 | 离线已校验构建缓存，正常sdist→wheel及PyPA installer独立安装；77项运行资源一致，无editable替代；wheel另存私有证据目录 |
| 完整性 | 63份既有manifest／2047条文件记录的存储及已声明解压摘要保持；三份TOML及配置SQLite文件摘要保持 |
| 驻留原生 | 待维护者重启；9项既有别名计划已冻结，尚未把它们记为通过 |

普通表、空类型／空格、自定义类型、STRICT ANY、CTAS、VIRTUAL／STORED、FTS、继承与表达式视图均覆盖；NULL/default、隐藏列、生成标记及正常raw／Skill语义保持。单表支持视图，schema概览仍按既有目录契约仅列出表，未扩大范围。相关回归继续拒绝未授权对象；本项不调整authorizer或读取函数规则。所测相邻范围未确认新的独立缺陷，不承诺全项目无bug。

## 成本与证据限制

同一18对象夹具的工具实际输出由14表17列／9组恢复为14表17列／11组。一次inprocess auto应用文本字符比较如下；其它模式／传输的结果一致。

| 投影 | 修复前字符 | 修复后字符 |
| --- | ---: | ---: |
| compact分组 | 2126 | 2314 |
| compact不分组 | 2506 | 2482 |
| full | 2290 | 2266 |

这不是延迟基准或provider token测量。响应体取决于实际类型和分组，不能承诺token减少。固定调用流程相同、无新增数据库语句；没有新增完整Luna任务或引导消融，旧模型证据保留其原源码范围。应用结果记录也不等于完整协议帧、通知或原始省略字段。

前批DRR-137／138／139限定验收继续成立，不因本P3重新打开。此前[仅评估检查点](V3_8_2_SQLITE_DECLARED_TYPES_ASSESSMENT_2026_10_21_ZH.md)及其初始化失败、旧基线夹具修正均保留原字节，不推断缓存根因。本轮仅有一次无效文档补丁定位，未改任何文件，后续文档正常完成；无本批生产验收失败。

## 复现与收尾

新增测试为`tests/test_sqlite_declared_types_v382.py`。公开[证据入口](v382_sqlite_declared_types_repair_2026_10_21/README.md)提供Client／核验脚本、应用结果和检查摘要；原始完整构建及环境记录位于`local_archive/v382_review/20261021_sqlite_declared_type_repair/`，私有目录按baseline／scripts／evidence／reports／drafts分层。

重启后按冻结计划检查pages_fts原生空类型、pages生成列、compact/full6表34列、FTS读取及受限函数／影子表拒绝、SQLite值语义和MySQL对照。可选summary及18类临时对象仍为源码／安装范围，不因此改实际配置或新增数据库对象。重启补充应独立追加，保留本次pending检查点。


## 维护者重启后的限定核验与相邻补查

维护者确认重启后，冻结9/9项原生检查全部符合预期。pages_fts的title／body均恢复原生空类型；pages10列及status=virtual、compact/full6表34列、完整索引／行数与独立只读sqlite3原生元数据一致。FTS返回1，普通SQLite值语义和MySQL常量正常；直接影子及耗时函数仍分别返回table_access_denied／expensive_function_denied。所有应用文本与结构化结果一致。

相邻另用10类临时对象，源码／原正常wheel各144应用调用、各20直接列观察，两模式／进程内与独立stdio一致。检查默认值缺省、显式NULL、0、空字符串、文本0，空格／自定义／带长度声明，点号／空格／Unicode名称，STRICT TEXT、继承／CAST视图及生成列。describe／summary／full逐字段对比独立原生类型、nullable、默认值、key及生成标记；compact保持不同默认值对象分组区分，raw／Skill结果正确。所测范围未确认新的独立生产缺陷，不推导全项目无bug。

生产源码、77运行资源、三份私有TOML及配置SQLite文件在核验前后均不变；65份旧manifest／2097文件记录的存储及已声明解压摘要保持。此次仅新增验证及文档说明，无新构建、安装、全量、模型或性能测量。前次3353全量及各184源码／安装仍属父修复检查点；不把288个新隔离调用计为原生Host调用。特殊类型／可选summary仍为源码／安装范围。

旧SQLite适配器设计文档中的TEXT补值示例是v3.7历史，不重写原示例；新增提示明确已由本次契约取代。父报告原始字节保存于补充证据，先前documentation_checks中的摘要表示当时报告，不据此否定历史完整性。父private/public manifest及pending不改写，重启记录独立[封存补充](v382_sqlite_declared_types_repair_2026_10_21/resident_restart/README.md)。当前无需再重启、构建、装包、导入或重复全量；没有确认缓存根因，无新增grant或配置库写入。
