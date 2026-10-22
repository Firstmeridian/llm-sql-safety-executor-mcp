# v3.8.2：SQLite 空声明类型元数据复评

2026-10-21，版本仍3.8.2。本批仅评估，不修改生产代码、测试、实际配置、grant或配置数据库。DRR-137／138／139的既有限定验收继续成立；本次未独立重放外部评审新增的37个rowid变体，也不将其计入本批实测。

## 结论

确认一个既有P3，登记为DRR-2026-140。SQLiteAdapter.get_columns的`row[2] or "TEXT"`把数据库返回的空类型替换为显式TEXT，影响describe_table、get_table_summary及compact/full schema。原始读取与Query Skill结果保持SQLite实际语义，错误发生在元数据表示层，不是执行时把值转换成了TEXT，也没有证据表明它扩大授权。

| 夹具 | PRAGMA类型 | 当前元数据 | typeof(n) | n='7' |
| --- | --- | --- | --- | --- |
| CREATE TABLE untyped(n)，插入整数7 | 空字符串 | TEXT | integer | 0 |
| CREATE TABLE typed_text(n TEXT)，插入整数7 | TEXT | TEXT | text | 1 |
| 未声明类型的VIRTUAL／STORED生成列 | 空字符串 | TEXT | integer | 0 |
| FTS5可见n列，插入整数7 | 空字符串 | TEXT | integer | 0 |
| SELECT 7 AS n的表达式视图 | 空字符串 | TEXT | integer | 0 |

`2c0a9e7`冻结源码的sqlite.py已与git对象逐字节核对，同样存在问题。因此不是本轮目录、统计或rowid补修引入的回归，不应重开DRR-137／138／139。P3判断依据是影响元数据准确性及Agent决策，所测正常读取没有误拒、数据丢失或授权绕过；它仍值得在提交前用小范围改动处理。

## 相邻检查

- 同一根因还让compact把未声明类型表与TEXT表合并；同样结构的未声明／TEXT生成列也合并。当前夹具14表17列被分成9组，按原生类型直接构造签名应为11组。这是纯签名计算的方案验证，未补丁生产代码，也不是已修复的工具结果。
- CREATE TABLE AS SELECT常量、显式空类型、生成列、FTS可见列及部分表达式视图均受影响。相反，BLOB／INTEGER／NUMERIC／STRING／空格类型／STRICT ANY及直接继承TEXT的视图保留原生非空类型。FTS隐藏列继续排除，生成列标记及列计数正常。
- 单表describe支持已授权视图，但get_full_schema按既有目录契约只概览表；本次没有把视图未列入概览另算缺陷。
- MySQL列路径直接传递INFORMATION_SCHEMA的数据类型，没有相同的TEXT补值。数据库读策略、authorizer及Skill readiness不依赖这个展示类型字段；所测Query Skill保持可用且结果正确。
- 历史验收脚本曾把原生空类型同样映射为TEXT后比较，因此那些“与真值一致”的声明仅覆盖其明确采用的适配器类型映射，不能证明声明类型无损。后续回归应直接比较原生PRAGMA类型，不再复制被测转换；旧封存脚本及记录保持原字节，新增更正证据。

本次18类对象、两模式／两传输的定点检查未确认其他独立P1／P2；不据此承诺全项目无缺陷。

## 推荐修法与取舍

推荐让SQLite的data_type保留PRAGMA返回的字符串，包括空字符串；full的type及compact的[name,type]直接沿用。空字符串的产品说明应为“SQLite未提供非空类型信息；不据此认定TEXT或推断实际值类型”。保留现有字符串字段，不新增null／UNKNOWN等第二套编码，也不新增开关、数据采样、AST规则或通用类型推断。

声明类型、亲和性与存储类必须分开。普通未声明类型列具有BLOB亲和性，视图表达式却可能没有亲和性；不能统一把空类型改写成BLOB。当前SQLite3.45.1的两个合法定义`n`与`n ""`还会返回同样的空PRAGMA类型，但整数7与文本'7'的比较结果不同；保留原生空字符串不意味着元数据已经完整表达语义。现有compact声明只是adapter可见列信息相同，不证明DDL、亲和性或约束相同。

若将来确需亲和性字段，应另行约定普通表、视图、虚表、STRICT ANY及不确定状态；本P3无需承担该范围。生成列应以列声明而非生成表达式推断类型。参考SQLite官方[类型／比较／视图亲和性](https://www.sqlite.org/datatype3.html)、[table_info与table_xinfo](https://www.sqlite.org/pragma.html#pragma_table_xinfo)、[生成列规则](https://www.sqlite.org/gencol.html)、[STRICT ANY](https://www.sqlite.org/stricttables.html)。

实施时新增正反例，覆盖两个Client模式的describe／summary／compact／full、生成列和FTS，确认显式TEXT等非空类型保持；读取和Skill仍按原语义执行，目录不求值表达式，元数据授权保持。同步README字段说明、生成列／FTS契约及旧映射的验收勘误即可，不需要扩大解析层或放宽authorizer。

直接传递空字符串几乎没有额外计算或数据库访问，不增加固定Agent调用步骤；但compact可能分成更多组，响应体可能增长，不能承诺所有任务token不变。对依赖当前错误TEXT值的调用方属于可见契约更正，应明确通知；项目尚未正式发布，不需要为此增加兼容开关。

## 证据与限制

- 当前源码184次应用调用：进程内auto／legacy及独立stdio auto／legacy各46次，覆盖18对象；另有36次直接列元数据观察。
- 旧2c0a9e7共32次进程内调用，两模式各16次，覆盖4个基本对象；确认同根类型与分组问题，不冒充当前包或新完整协议测试。
- 当前原生2次：常量比较语义正确，pages_fts两列仍展示TEXT；与前批封存的原生PRAGMA空类型比较，配置SQLite文件摘要一致。本批未新建原生配置库对象或新增grant。
- 最终应用调用成功，文本／structured content一致；成功仅表示工具完成，元数据错误按预期复现。源码77资源、三份私有配置及数据库文件不变，61份旧manifest／2020条文件记录的已声明存储及解压摘要保持。
- 首次source运行92次进程内调用后两条stdio初始化失败，后续在进程沙盒外运行成功；现有错误不能细分底层根因，不写成缓存问题。旧版初轮32次中限定名读取还命中了已知旧授权表示差异；只在临时夹具同时声明bare/main后完成新的32次类型对照。初轮与最终输出分别保留。
- 无新构建、安装、全量回归、Luna任务、模型token或性能测量。无需为本次只读评估重启MCP。完整应用证据见[归档入口](v382_sqlite_declared_types_assessment_2026_10_21/README.md)。
