# v3.8.2 名称、方言与执行保障验收（2026-10-16）

> 最新状态：e49cd0e 的[最终复核与独立 COLLATE P3](V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md)已完成；WHEN 修复及限定驻留验收见[后续报告](V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。下文模型／成本／原生结果保留其原源码归属，不改标为后续版本的再次验收。

基线为维护者提交 `3323f9c29add7fd158410d5ce57a70fb58c5f2cb`。维护者批准实施 v3.8.2，代码／接口已落地；**维护者重启后首批 Host 10/10、fresh Luna 可调用，12 个完整 trial／36 轮已完成，固定检查 11/12（一次浮点／金额精度排序口径不一致，见下文歧义说明）。业务试验发现的 CTE 计数误拒已补修并完成最后重启复验：原生 5/5，三次 fresh Luna 双轮销售未见服务误拒，按明确业务要求 2/3 完成，严格数字检查 1/3，原因分列。批准范围验收已完成，模型失败不隐藏。** 未替用户暂存或提交。

> 2026-10-17 后续复核发现读取边界与非执行型 EXPLAIN 两项遗漏，已补修并独立记录在[后续验收](V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md)。上述完成结论与本文件封存证据保留当时源码范围，不能代替补修后的驻留 Host 核验；该后续批次现已完成维护者重启后的原生 28/28 检查，工具未暴露范围仍明确保留。

## 完整改动及取舍

| 变更 | 原状态／问题 | 现方案与原理 | 原因／好处 | 代价及范围 |
| --- | --- | --- | --- | --- |
| 名称与方言接口 | 字符串简写不能无歧义表达所有 schema/name；业务名称容易被通用规范化误伤 | 保留 RelationReference，词法名称／引用／角色／位置／作用域和每次关系来源分开记录；只做 ASCII 保留词比较 | 区分限定名、字面点号、空格与 Unicode 名称；引用等价不自动扩权 | 仍是支持包络，不是完整数据库语义引擎；MySQL 物理名不能套用 SQLite 示例 |
| 结构化声明 | read.tables 与 Skill tables 都按首点拆分 | 新增严格 read.relations 和 Skill relations 映射数组；默认 schema readiness 共用结构化依赖 | 配置、raw、Skill、发现、详情和元数据身份一致；字面 * 不是全局 wildcard | 增加可选声明形式；限定引用仍需相应 grant；其他 schema readiness 明确 unverified |
| 统一 SQL 分析 | 分类、关系、CTE 和依赖检查存在多次独立解析 | SQLGlot 30.22.0 显式 SQLite/MySQL 上下文；移除旧 core/structure.py 及重复读取解析；原 SQL／参数执行 | partial/failed 不再表示零依赖；SQLite 名称槽、索引提示、别名和 IN 保留真实边界；普通 CURRENT_USER／LOCALTIME 等列不套用 SQL 标准裸函数语义；函数体不被声明掩盖 | 新运行依赖和解析适配维护成本；不支持项仍拒绝，无旧解析执行回退；受管写计划仍独立检查 |
| CTE 方言 | SQLite 被保守套用有序／显式递归规则 | SQLite 所有同块声明可见／隐式递归；MySQL 有序声明／显式递归自引用；大小写能力另行测量 | 减少 SQLite 假依赖，保留 MySQL 同名物理表检查 | 数据库仍决定循环／语法有效性；没有全方言兼容承诺 |
| MySQL 会话 | 另一连接探测的 mode 不能代表整个池；rollback 不清理会话状态 | 每个物理 connect 在方言检测前初始化／校验完整模式；显式完整集合或继承首个集合；可信任意操作／完整写事务后退休连接 | 执行连接和分析上下文一致；重连／池重建保持约定；明确物理拒绝先于模式初始化 I/O | 可信操作增加重新连接成本；仅受控 read/metadata 复用；私有 engine 扩展自行遵约；不保证存储例程无副作用 |
| SQLite authorizer | 编译后的真实 main/temp/aux 对象和视图来源缺少独立核验 | 稳定物理回调、完整连接独占、cached_statements=0；回调至取完结果生效；实际对象／函数／操作核验 | 同名 temp 不继承主库裸 grant；视图 grant 可经核验来源链读取，不赋予直接底表 grant | 串行访问、目录检查和重新编译有成本；复杂／歧义来源及预算超限拒绝；schema/UDF/Python 可信边界不变 |
| 视图／生命周期 | 缓存、来源标签和准备后 schema 变化可能让朴素 authorizer 失真 | 每请求重建有界来源边，核验视图内部 CTE；空数据库 READ 仅接受唯一已解析候选；异常清理与完整事务锁 | 不沿用旧编译授权；正常 count/rowid 计划可执行；回调不执行 SQL，不用 IGNORE 替换 NULL | 2048 次目录查找／128 视图／1024 边；冲突来源／部分虚拟关系视图返回 view_scope_unresolved；外层取消不强制停止所有同步工作 |
| 元数据及传输 | 统一 64 字符／字符白名单误拒合法 SQLite 名；SQLAlchemy 把名称／字符串里的冒号当绑定 | 方言名称支持包络＋组件引用；独立 transport 只绑定真实占位符并保留原字符串、名称、注释和反斜线 | 工具授权目标与生成 SQL 一致；支持带点／空格／引用符／冒号及长 SQLite 名 | 元数据支持面扩大，需维护方言矩阵；服务器仍是最终语法裁判；不 trim 非法 MySQL 名到另一对象 |
| 配置／文档／固化 | 新类型可能遗漏到离线命令；历史实测脚本带固定日期／版本 | 修复 config explain 结构化数组序列化；统一包／MCP 版本；新增矩阵、会话、成本、安装验收脚本，任务采集按真实版本／唯一 agent ID | 安装、离线命令和真实 MCP 一起验；后续不重复临时安装与手工探测 | 保留中间失败；脚本默认不覆盖证据；历史数据不重写为新版本结果 |

## 已完成的验证

| 项目 | 结果／证据 | 结论的边界 |
| --- | --- | --- |
| 改前基线 | 1750 passed、4 skipped、77 warnings，137.10s；baseline_*.json | 实际工作环境及 owner commit，非干净环境／远端 CI |
| 当前完整回归 | **1896 passed、4 skipped、82 warnings，254.45s**；[补修后日志](v382_2026_10_16/cte_count_followup/full-cte-count.log.gz)；补修前 1881 项及中间失败分别保留 | 四项 opt-in MySQL 测试未运行；警告为既有 legacy logging 类，新增夹具增加出现次数；中间失败另存 |
| 类型／提示 | Pyright 0 errors/0 warnings；当前 TOML 提示契约通过 | 未改 prompt 资源；类型／文本通过不等于模型任务验收 |
| 独立原生 SQLite | 完整矩阵见 semantics_matrix_accepted.json.gz：542 物理名称、1000 上下文、300 合法 CTE、4 个拒绝对照、576 无害保留函数调用 | 原生私有 sqlite3 真值＋应用判定，不是 Host 调用；本机 SQLite 3.45.1；不将失败夹具计成语法无效 |
| MySQL 名称／模式 | 同矩阵：8 种 ANSI_QUOTES／NO_BACKSLASH_ESCAPES／PIPES_AS_CONCAT 组合，144 条原生观察，包含别名、临时关系、非递归自身／前向物理表及递归；真实私有池的显式／继承生命周期两组通过 | Oracle MySQL 8.0.25、lower_case_table_names=1；预期非法尾空格／ANSI 标识符找不到列不算实现失败；其他设置／MariaDB 未测 |
| 安装包 | sdist→wheel，独立 /tmp 非 editable 环境；两协议 58 次定点 child stdio 工具调用（含新增 CTE 计数与 Skill），另有通用 CLI／提示／两协议安装核验 | 模拟器不替代真实 stdio；已解码 content/structured 记录不包含完整协议帧和通知；75 个资源已与安装包逐项核对 |
| Luna 就绪 | 新 GPT-6 Luna 确实调用 SELECT 7，公开事件及 Host 用量保留 | 这是重启前可调用性验证，**不是 v3.8.2 完整业务任务通过证据** |
| 当前 Host／完整 Luna | 首批 Host 10/10、fresh Luna 两条实际调用通过；12 trial／36 轮固定检查 11/12，数据不变 | 该 12 trial 属于补修前源码；补修后另有原生 5/5 和三次双轮销售（明确目标 2/3、严格数字检查 1/3）；分别归档，不替换先前失败 |

原生 MySQL 的结果别名观察：当前服务／原始 PyMySQL cursor 都返回去掉开头空格的结果标签（例如输入 ` f `，返回 `f `）。反斜线及反引号的 12 个别名观察原样保留。这不能推导为物理表名 trim，也不说明所有方言／所有对象类别等价；不会据此扩大授权或修改名称。

## 成本与记录约定

第一次 A1/B/A2 与构建／回归并发，保留为探索记录，不作为主要对照。正式 serial_A1/B/A2 使用冻结旧 src 和当前 src、相同私有数据／SQL／绑定／两协议，独立进程串行执行并关闭日志，区分首轮、启动及 warm 样本。正式三阶段均完成，每阶段两协议、各 13 轮 7 次调用（182 次），warm 统计排除首轮；以下给出绝对数值，不以字符数冒充 token，不承诺同工具调用数就等成本。语句缓存 128/0 的原生对照只隔离缓存代价，不代表整个应用成本。

| 测量 | A1：3323f9c | B：v3.8.2 补修前源码 | A2：3323f9c |
| --- | ---: | ---: | ---: |
| 策略 SELECT 7 AS n，中位 ms | 2.978 | 0.181 | 3.043 |
| 策略 SELECT COUNT(*) AS n FROM orders，中位 ms | 6.184 | 0.281 | 6.260 |
| 策略 WITH selected AS (SELECT id,amount FROM orders WHERE amount>=10) SELECT SUM(amount) AS n FROM selected，中位 ms | 18.404 | 0.623 | 17.945 |
| 策略 WITH sums AS (SELECT order_id,SUM(amount) AS n FROM items GROUP BY order_id) SELECT SUM(s.n) AS n FROM orders o JOIN sums s ON s.order_id=o.id，中位 ms | 28.129 | 0.924 | 27.973 |
| 策略 SELECT SUM(n) AS n FROM report，中位 ms | 6.683 | 0.308 | 6.351 |
| 策略 SELECT SLEEP(0) AS n，中位 ms | 2.621 | 0.227 | 2.576 |
| 现代 7 调用链 中位 ms | 147.67 | 25.91 | 140.50 |
| 现代 7 调用链 p95 ms | 199.25 | 27.94 | 157.67 |
| legacy 7 调用链 中位 ms | 147.10 | 27.84 | 144.13 |
| legacy 7 调用链 p95 ms | 150.74 | 32.92 | 163.91 |
| 策略冷导入 ms（每阶段一次） | 99.99 | 180.97 | 82.92 |
| 进程峰值 RSS KiB | 110248 | 119024 | 110172 |
| 固定 instructions＋工具描述／input schema 字符数 | 22680 | 22680 | 22680 |

范围：CTE 计数补修前的 accepted_A1/B/A2（原始记录 cost_accepted_*.json.gz）；6 条相同 SQL 的策略各 80 个 warm 样本；每条工具链包含 6 次 raw query（含预期 SLEEP 拒绝）和 1 次 Query Skill，私有数据 200 订单／400 明细。每阶段两协议、各 13 轮，共 182 次；warm 排除首轮。该批 B 的 75 个源码资源与当批安装包哈希一致，三阶段脚本哈希一致。真实 in-process Client、相同关闭日志，非网络 Host／模型计费。A1/A2 导入及 p95 仍有漂移，不能泛化一个比值。此样本的策略／Client 链下降，同时 SQLGlot 冷导入和进程峰值内存上升（约 8.6 MiB）；SQLite 独占／目录／回调／重新编译及可信 MySQL 操作重连的成本继续保留。前一 serial_* 和并发探索 A1/B/A2 都作为源码／条件独立的检查点保存，不冒充最终源码。

原生 SQLite cache 对照（B，同 SQL 各 100 个 warm 样本，只测 sqlite3，不含应用检查）：

| SQL | cache=128 中位 ms | cache=0 中位 ms |
| --- | ---: | ---: |
| SELECT 7 AS n | 0.00143 | 0.00292 |
| SELECT COUNT(*) AS n FROM orders | 0.00658 | 0.00918 |
| WITH selected AS (SELECT id,amount FROM orders WHERE amount>=10) SELECT SUM(amount) AS n FROM selected | 0.02236 | 0.02698 |
| WITH sums AS (SELECT order_id,SUM(amount) AS n FROM items GROUP BY order_id) SELECT SUM(s.n) AS n FROM orders o JOIN sums s ON s.order_id=o.id | 0.15125 | 0.19573 |

JSON 新规范保留：摘要／清单＋一次原始公开应用结果＋重复测量数组，适当 gzip，源与脚本哈希、失败、未测项、时间和环境范围明确。原始协议帧／通知未采集就明确说明，不笼统称完全没有信息减少。预览 bearer 值按既有规范脱敏，隐藏推理不归档。旧批次封存，不改写。

## 决议、数据状态和待办

- v3.8.2；旧 env／旧入口／旧 SDK 和假想历史调用方兼容不纳入范围；真实扩展点变更及迁移已明确记录。RelationReference／授权／原 SQL 是独立契约；AST 和 authorizer 分别接入，不互相冒充证明。
- 不新增每请求 MySQL 模式探测，不新增 Agent 必需工具步骤，不更改写入批准、token、mutation outcome 或审计边界。authorizer 仅 SQLite；MySQL 控制会话生命周期仍须数据库权限和可信部署。
- 只使用私有 SQLite、MySQL SESSION／临时对象；未修改当前 TOML、既有业务数据或全局模式。任务真值以只读方式读取；真实写入仍须按实际授权审批。
- 已校验临时 uv 0.8.22 和 SQLGlot 30.22.0 官方 wheel；只将 SQLGlot 加入项目运行依赖／锁文件，其他锁定版本不升级。项目 editable 安装元数据已更新到 3.8.2（此前实际为 3.8.0），uv 为 /tmp 工具，未全局安装。
- 首批 Host canary、fresh Luna 可调用性、完整任务及实际 usage、truth_after 已完成，完整任务批次已封存。补修后最终 Host 5/5、三次双轮 Luna 销售、truth_after 及父批次封存已完成；各项通过范围和模型失败分别记录。

设计／来源：[架构及官方文档取舍](../../architecture/V3_8_2_SQL_SEMANTICS_ZH.md)。决议另记中英 REFACTORING_LOG 和 DRR-2026-100–106；旧 v3.8.1 原因判断及证据保持原记录，不把重启后通过写成已证明缓存根因。


### 最后方言复核

收尾原生检查确认 CURRENT_USER 在 SQLite 中可为普通列；先前实现及旧测试把它套用为其他方言的裸函数。SQLGlot SQLite tokenizer 现只保留实际三个 current-time 词汇，普通业务列、raw／Skill／发现／执行按 SQLite 真值对齐；真正 CURRENT_USER() 调用和 MySQL 裸 CURRENT_USER 继续拒绝。新增十项语义／真实列对照，并把旧 SQLite 拒绝夹具改为真实调用，加上 ASCII 业务列正对照，而非删除函数限制。先前 1871 项整套记录、后续四个旧假设失败和修正分别保留。该补修前批次最后 **1881 passed／4 skipped**、48 次两协议安装语义调用及同源成本均通过核对，后续 CTE 计数补修另记。


## 可复用内容与交接

- 项目依赖／版本固定在 pyproject.toml 与 uv.lock，后续用 `uv sync --frozen --group dev` 建环境，无需再次临时寻找 SQLGlot；源码／安装包／MCP 版本一致。临时 uv 未全局安装。
- `scripts/validation/` 固化名称／模式矩阵、私有 MySQL 会话生命周期、冻结源码成本、仓库外 wheel 语义验证。现有完整任务 truth/collect 工具改为读取真实版本、按唯一 agent ID 查找会话，支持独立 output-dir；当前计划已冻结。历史封存输出不重跑覆盖。
- 证据索引：[验证摘要](v382_2026_10_16/verification.json)、[补修前源码与脚本清单](v382_2026_10_16/source_final.json)、[补修后当前源码清单](v382_2026_10_16/cte_count_followup/source_current.json)、[成本摘要](v382_2026_10_16/cost_summary.json)、[原生矩阵](v382_2026_10_16/semantics_matrix_accepted.json.gz)、[安装 stdio](v382_2026_10_16/installed_semantics_accepted.json.gz)、[完整任务计划](v382_2026_10_16/real_tasks/plan.json)。中间错误、过时假设、被中断或仅有进度的运行日志均保留，不能以无结尾日志声称通过。
- `manifest_pre_restart.json` 保留初始检查点；`real_tasks/manifest.json` 已封存补修前 12 个 trial。父批次最终 manifest 已在补修后原生及 Luna 复验完成后封存；补修后任务另有独立 manifest，不把不同源码合并为同一验收结果。
- 提交建议草案：`local_archive/v382_review/handoff/commit-message-v382.txt`。当前源码和文档均未替维护者暂存／提交；CTE 计数补修原生复验及证据封存已完成；未新增远端 CI、其他 Host 或真实写入通过声明。


## 重启后的完整任务与补修

维护者首次重启后，[当前 Codex Host](v382_2026_10_16/native_after_restart.json) 10/10 符合预期，fresh GPT-6 Luna 实际执行常量及 SQLite 前向 CTE 两次成功。裸 orders grant 不自动扩展为 main.orders；普通 CURRENT_USER 列进入 unknown_column，而真实 CURRENT_USER()／SLEEP／锁调用仍被拒绝。这是当前行为证据，不是驻留源码哈希证明，也不确认此前缓存问题的根因。

随后按冻结脚本以 GPT-6 Luna medium、fork_context=false 完成四类各三次试验：

| 任务 | 完整 trial／固定检查通过 | 用户轮数 | 可核对 MCP 返回 | 人工复核 |
| --- | ---: | ---: | ---: | --- |
| 三季度销售与排除 east | 3／3 | 6 | 24 | 720 行、38 产品、331921.71；更新范围 548 行、253826.38。trial 2 首个合法综合查询被服务误拒，拆分后恢复，不能记首次成功 |
| 财务对账与重复连接高估 | 3／2 | 6 | 24 | 48 单、24556.85，错误连接 74460.86、高估 49904.01，最高收入地区订单占比 37.50%；trial 2 按浮点尾差选了 38／80／27，未满足按分精度并列取 1／2／3 的固定规则 |
| 多连接月报、缩小范围及精确别名 | 3／3 | 15 | 33 | 月度／状态数值、连接范围、空集与失败区分正确；拒绝已知不存在别名无需故意调用工具产生错误 |
| 业务拒绝、恢复路径与取消 | 3／3 | 9 | 21 | returned → pending → confirmed → shipped 完整；无 confirm=true，取消后重新读状态，仍为 returned |

总计 **12 trial／36 轮，固定检查 11/12**。金融任务原始文字没有明确要求排序前先舍入，虽然固定参考采用金额精度／0.01 容差解释并列，仍存在需求歧义；不能把这一项直接定性为 MCP 算错或 Agent 答案在任何口径下都错。保留原始评分与轨迹，另附[解释补充](v382_2026_10_16/cte_count_followup/assessment_addendum.json)，未来脚本应显式约定排序精度。措辞和效率另评：三个恢复试验都提前预览了 reset，trial 1／2 在第二轮复用了此前预览，trial 3 再次预览；三个路由试验都没有充分使用已观察到的 Skill readiness 解释表存在性，trial 1 还没有给出空月报的零汇总。财务 trial 1／3 自行复核分精度后修正了浮点排名；trial 2 的失败保留，不偷偷重跑或用后续纠正替代。一次空 Skill 搜索、40 次本地工具目录检查、13 次目录输出截断均保留。试验未见未授权读取或实际写入；这不表示覆盖任意并发／故障／Host。

[实际轨迹、检查和用量](v382_2026_10_16/real_tasks/summary.json)：102 次公开 MCP 返回观察（97 个完整应用 envelope、5 个单次编排内去重业务体回退），151 次 Host 模型响应；输入 **5105240**，其中缓存 **4782720**，输出 **33585**，各轮活动时间合计 **572.041 秒**。缓存是输入子集，不再次相加；活动时间包含模型／Host／工具与共享服务影响，不是服务端延迟。首个 preflight 不计入这些完整任务用量，也不拿此批与历史模型结果做同条件 A/B 或账单比较。隐藏推理不归档，完整 bearer 值脱敏，应用事件不冒充完整协议帧。

[truth_before](v382_2026_10_16/real_tasks/truth_before.json)／[truth_after](v382_2026_10_16/real_tasks/truth_after.json) 的 75 项源码一致，7 张 SQLite 授权表摘要及 MySQL 核对值不变；该批已按原源码[封存](v382_2026_10_16/real_tasks/manifest.json)。采集器的别名拒绝机械评分原先要求工具报错，现接受“已知不存在而不做数据库调用”的正确路径；这是修正评分器，不改冻结业务要求，不重跑模型。保留原调用和最终回答，人工审阅不能由数字出现检测替代。

### CTE 计数补修（DRR-2026-106）

原综合查询的独立 sqlite3 执行成功，输出 11 行；真实 authorizer 事件最后包含 `(sales, 空列, database=null, source=null)`。物化／常量 CTE 不一定对应物理表，旧 guard 的“必须找到唯一物理对象”误拒了该合法事件。[SQLite 官方 authorizer 文档](https://www.sqlite.org/c3ref/set_authorizer.html)说明 COUNT(*) 的空列事件及回调参数可能为空；此处 CTE 的具体回调形态由本机原生记录确认，不声称官方保证每个 SQLite 版本均相同。

修复仅接受声明唯一、且独占准备期间所有附加目录无同名对象的 CTE 标签空列事件；不会为 main／temp／aux 物理对象授予新权限。实际底表、函数及其他操作仍独立核验，回调不执行 SQL。目录／作用域冲突仍拒绝，新增目录工作计入既有 2048 次预算，不要求 Agent 增加必需工具步骤。代价是有界目录查询和保守同名拒绝。

原生事件及原查询、6 failed／7 passed 的修复前回归、补修前 authorizer 文件和报告均在[补修目录](v382_2026_10_16/cte_count_followup/)保存。新增 15 项回归覆盖物化／常量／Unicode CTE、视图内 CTE、main／temp／aux 同名冲突、未授权底表与受限函数不求值；当前完整回归 **1896 passed、4 skipped、82 warnings，254.45s**。回归期间并行进行了类型／构建／安装工作，不能把该耗时与此前 93.35s 当性能对照。Pyright 0/0、提示检查、仓库外 wheel／CLI／两协议 58 次语义调用通过，75 项当前资源一致；源码原综合查询一次返回 11 行，与独立真值相同。

保留沙盒内 MySQL 真值网络失败与 Pyright 依赖不可见，按获准的命令级权限重试通过；安装验收新增 UNION 夹具最初未启用 UNION，保留失败日志，修正私有夹具后通过，未改业务 TOML。原报告及旧回归／安装包结果保留源码归属，不改写为这次补修的通过证据。

最后重型验证结束后，重新串行 A1／B／A2（相同脚本、私有数据、SQL、两协议，各 182 次调用）：

| 测量 | A1：3323f9c | B：含 CTE 计数补修 | A2：3323f9c |
| --- | ---: | ---: | ---: |
| 现代七调用链中位 ms | 222.81 | 42.13 | 190.11 |
| 现代七调用链 p95 ms | 449.34 | 44.58 | 215.39 |
| legacy 七调用链中位 ms | 199.13 | 40.16 | 190.75 |
| legacy 七调用链 p95 ms | 251.77 | 43.55 | 197.99 |
| 冷导入 ms（每阶段一次） | 125.08 | 220.60 | 114.01 |
| 峰值 RSS KiB | 109804 | 119116 | 110132 |
| 固定元数据字符 | 22680 | 22680 | 22680 |

[当前成本摘要](v382_2026_10_16/cte_count_followup/cost_summary.json)及同目录原始记录保留策略／缓存／首轮统计，B 与当前 75 项源码一致。该轮基线也有明显漂移；不能把不同批次 B 的 25.91 与 42.13 ms 差值直接归因于此次补修，不宣称相同字符就相同 token 或整体零成本。上述旧 accepted 成本表仍属于补修前源码。

**最终重启核验已完成：** [重启前拒绝](v382_2026_10_16/cte_count_followup/native_before_final_restart.json) 原样保留；[重启后 5/5](v382_2026_10_16/cte_count_followup/native_after_final_restart.json) 中原综合查询一次返回 11 行，物化／常量 CTE 计数成功，未授权底表与受限函数继续拒绝。fresh Luna 的两条真实调用也通过；其最终 prose 对 JSON 的复述不作为原始证据，使用实际公开工具返回。该结果符合新增补修行为，不反推历史其他会话的缓存／绑定根因。


### 最终源码上的完整销售任务补充

这批使用[提前冻结的原业务脚本](v382_2026_10_16/cte_count_followup/luna_tasks/plan.json)，三次 fresh GPT-6 Luna medium、每次两轮；未把 SQL、真值或前批结果喂给模型。与首批 12 trial 合计 **15 次试验、42 轮用户交互**，不是 15 次业务全部成功，也不是同一源码的单批试验。

| trial | 初始三季度复盘 | 排除 east 后的第二轮 | 评价 |
| --- | --- | --- | --- |
| 1 | 拼错工具命名空间并提前停止，未取得数据库结果 | 纠正名称后完整查询，548 条、253826.38、38 产品及前三名正确 | 首轮业务未完成；不能用第二轮成功替换第一次失败 |
| 2 | 720 条、331921.71、38 产品、各季度／环比、最高地区及占比、产品前三名均满足明确任务 | 新范围指标正确 | 明确业务目标完成；机械数字覆盖另要求最高地区金额 92670.74 出现在最终文本，而原题只要求地区与占比，保留该过严检查失败 |
| 3 | 明确业务指标正确 | 新范围指标正确 | 业务完成；实际 SQL 使用 < 2026-10-01，最终措辞“至 10 月 1 日”不够精确 |

[严格检查](v382_2026_10_16/cte_count_followup/luna_tasks/summary.json) **1/3**；[逐条人工业务复核](v382_2026_10_16/cte_count_followup/luna_tasks/manual_assessment.json) **2/3**。不在观察结果后偷偷移除失败检查，也不把本来没有要求的额外输出缺失定为 MCP 算错。所有第二轮更新范围答案正确，全部真实 MCP 调用保持目标连接、无写入、无截断。

trial 1 实际调用 `tools.mcp__sql_safety_executor__list_tables`，正确名称为 `tools.mcp__sql_safety_executor_mcp__list_tables`。TypeError 发生在到达 SQL MCP 之前；同一会话第二轮检查目录后，正确名称可正常调用。因此本次已确认是模型拼写／恢复行为问题，不是“工具名正确但客户端未就绪”；此结论不扩展到以前未定位的会话。另保留该模型过宽检索全部工具目录、第二轮先做过滤后 east 诊断再自行纠正的额外工作，不为模型隐藏低效步骤。

本批实际 **14 次 MCP 返回全部成功**，另有 1 次服务器前不存在函数尝试；33 次 Host 模型响应、12 次本地目录检查、4 次目录输出截断，输入 **1126532**（缓存 **1053952**）、输出 **7693**，活动时间合计 **111.718 秒**。preflight 两次调用不计入业务成本。统计范围为 5 个应用 envelope／9 个业务体回退，均已对照真实编排代码。一个返回被 content／structured 两次打印时，720.0／720 的数值表示曾被统计两次，现仅在 fallback 统计中去重；[校正记录](v382_2026_10_16/cte_count_followup/luna_tasks/collection_correction.json)证明原始公开事件哈希不变，未丢弃原字段、数值表示或失败，也没有重跑模型。

采集／评分脚本现从计划读取案例数与重复次数，缺少人工复核文件时明确标注，不再套用旧批次硬编码评语；无 MCP 返回的试验记录失败而非统计崩溃。只调整验收辅助脚本，[最终资源与脚本摘要](v382_2026_10_16/cte_count_followup/source_closure.json)列出差异；75 项运行资源及已回归测试未变化，不为辅助统计修订重跑 1896 项生产回归。

[本批真值前后](v382_2026_10_16/cte_count_followup/luna_tasks/truth_after.json)的 75 项源码、7 张 SQLite 授权表指纹及 MySQL 汇总不变，也与首批数据一致。原始事件、独立真值、实际 usage、脚本版本与清单全部留存。实际写入／提交／回滚、并发冲突／断网、其他模型／Host 和未具备的 MySQL 大小写配置／MariaDB 仍不在这些完整 Agent 任务的通过范围。
