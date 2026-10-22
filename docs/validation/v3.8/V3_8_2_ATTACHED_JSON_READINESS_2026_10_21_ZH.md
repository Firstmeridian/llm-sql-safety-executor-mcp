# v3.8.2：附加库 JSON 同名调用的 readiness 复评

日期：2026-10-21；评估对象为当前未提交工作树，版本保持3.8.2。本轮只评估并记录，未修改生产代码、测试源码、依赖、实际配置或grant，未访问配置数据库。此前读取结果三项修复的限定验收保持有效。

后续状态：维护者随后批准实施，DRR-135已完成有序观察补修及源码／安装验证；本页保留当时仅评估内容。[当前修复及待原生范围](V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md)。

## 结论

反馈属实，P2评级合理，建议提交前补修，登记DRR-2026-135。它是DRR-134的相邻观察范围遗漏：未限定json_each／json_tree调用可能读取附加库中的同名FTS5表，readiness却将其判为main内置模块、遗漏实际依赖。已授权夹具可读，未授权夹具仍由受控执行拒绝；不能据此称授权绕过。

SQLite按TEMP、main、附加顺序查找未限定对象；未发现main／TEMP对象不是“没有存储对象”的充分条件。显式schema引用只查指定目录。[SQLite名称解析](https://www.sqlite.org/lang_naming.html)、[ATTACH说明](https://www.sqlite.org/lang_attach.html)。内置同名虚表与实际存储虚表须继续按角色、目录和模块区分，不能只比较函数拼写。[SQLite虚表机制](https://www.sqlite.org/vtab.html)。

## 独立实测及相邻检查

[证据入口](v382_attached_json_readiness_2026_10_21/README.md)。332次源码应用调用：主矩阵296次、同会话ATTACH／DETACH补测36次。主问题包含进程内Client及独立child-stdio的auto／legacy四组，每组46次；其他七类对照及动态补测为进程内auto／legacy。SQLite为3.45.1，无新安装包、驻留Host或模型任务验收。

| [研究验证] 场景 | 实际结果 | 判断 |
| --- | --- | --- |
| aux独占两个JSON同名FTS根 | raw与Skill均返回hello aux；详情标builtin、未记aux依赖 | 反馈复现 |
| 引号、JOIN、表形式IN、CTE | 同名FTS依赖均遗漏；JOIN只留下main.anchor依赖 | 同根因的表达形式扩展 |
| 两个附加库均有同名根 | SQLite读取先附加的first；readiness仍标main builtin | 修复必须保留查找顺序，不能对集合任取一个 |
| 带点号schema名称a.ux | 实际读取该附加库；readiness仍标builtin | schema须按单个语义组件引用，不能拆点或直接拼接 |
| aux根未授权 | raw及Skill返回view_scope_unresolved，无数据；发现／详情仍误称executable | 同根因还影响可用性报告；执行防护有效 |
| 显式aux／main | aux保留依赖且无法核验；main正确使用builtin | 原补修及显式范围契约有效 |
| main／TEMP优先 | main存储根正确识别；TEMP根保留依赖且按既定范围无法核验 | 未发现该对照退化 |
| 无附加库／附加库无同名对象 | builtin与结果正确 | 不应为修复而一律拒绝所有JSON调用 |
| 同一Skill先无附加库、再ATTACH、再DETACH | 数据hello→hello aux→hello；readiness全程builtin，纯分析缓存每Skill保持1项 | 观察范围不足；无需清空纯分析缓存或重启 |
| 受限函数／直接影子读取 | 四组均正确拒绝 | 未发现执行授权放宽 |

矩阵84条可用性观察中52条复现相同的错误builtin分类，不能算52个独立缺陷。动态补测进一步确认同一根因。成功raw结果与独立sqlite3位置行真值相符；所有非ToolError文本／结构化结果一致。矩阵12个ToolError为显式aux／TEMP的预期readiness拒绝，未混为序列化故障。未新增确认其他独立根因缺陷；这不代表覆盖全部SQLite对象或语法。

## 原因与建议方案

skills/access.py的_conditional_skill_relations在main快照无对象、TEMP观察非None时直接判builtin；database/sqlite.py的get_json_shadow_relations只观察TEMP。执行侧authorizer准备已读取database_list并按实际目录解析，因此能读取已授权aux根，也能拒绝未授权根。问题在readiness绑定事实的覆盖范围，不在SQLGlot解析或读取结果编码。

建议沿现有接口做目的明确的小范围收敛：

1. 保留未限定引用的语义，确认绑定前不要把main当作实际身份。一次独占连接观察获得目录顺序，仅读取这两个名称的目录事实；不执行对象、查询业务数据或扩grant。
2. 按TEMP→main→附加顺序选择实际存储身份。明确main仍只用main；未知／失败／预算未覆盖不能判builtin。观察要保留完整性与顺序，不能只把当前无序集合扩成更多schema后任取。
3. 完整观察确认不存在同名存储对象后才判builtin；存在时保留实际schema/name依赖。按当前默认schema readiness契约，aux对象仍列unverified_tables且schema_ready=false，不把两个名称的存在性探测扩大解释为完整aux覆盖。
4. 元数据失败只影响依赖未覆盖范围的调用，避免连带误拒已确认的main对象或普通Skill；关闭readiness时继续无额外探测。实际授权／模块及执行保障保持即时核验，只缓存纯分析。
5. 加入本矩阵及ATTACH／DETACH、顺序变化、目录失败／预算耗尽、授权变化和readiness关闭回归；同时保留正常builtin／显式main成功。不增加解析器、通用缓存、TOML开关或Agent固定步骤。

若暂不观察附加库，最小正确兜底是将未覆盖的未限定调用保留unverified；不能继续断言builtin。相比一律保守拒绝，建议采用有界名称观察，减少不存在同名对象时的误拒。后续若要让Skill完整支持非默认schema，可独立讨论按精确对象扩readiness，本次不借遗漏隐式扩大范围。

## 收益、代价与验收边界

收益是依赖、发现、详情与执行前readiness对实际绑定一致，避免错误builtin／executable声明。主要代价是目录列表观察及每个相关附加库的两名称元数据查询，目录数／超时／预算须有界；不是每库全表统计或新的Agent必需调用。无附加库的额外开销也需定点测量，本轮未测修复后性能，不承诺零成本或提速。

对目前漏报且成功的aux Skill，按既定契约修复后会明确无法核验；已授权raw query仍可用。Agent可能需要依提示转用同连接raw读取。结果编码、限额和真实授权保持不变，不应扩大AST适配或放宽authorizer。提交前宜完成补修；无需因本问题重开DRR-131—133或原SQLite EXPLAIN验收。

77项运行资源、三份私有TOML前后相同，临时夹具清理；47份旧封存／1338条文件记录未改。此前16项原生验收未含“仅附加库有同名对象”的夹具，不能扩成此场景通过。首个评估脚本SQL参数构造错误、沙盒内stdio初始化超时均保留；纠正脚本并经单次命令批准后完整运行成功，不确认超时的底层根因。本轮不需要Full access、MCP重启或再次导入样本库。

