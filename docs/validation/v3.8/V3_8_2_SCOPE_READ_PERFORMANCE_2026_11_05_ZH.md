# v3.8.2 范围恢复、受控预览读取与 SQLite 估算分批

开始：2026-11-05；测量／整理跨至 11-06（Asia/Taipei）。比较基线为 `cf11c513fedd85029ed158af3053dcbc630160a2`，候选为本批未提交源码；版本仍为 v3.8.2。

## 目标、决定与当前结论

| 工作 | 原问题／原因 | 本批方案与收益 | 代价／边界 |
| --- | --- | --- | --- |
| [功能修复] B34／DRR-156 | all 模式跨 schema 拒绝却显示 `Only allowed tables: *`，恢复指引机械要求留在原连接 | 区分默认 schema 与具体 allowlist；保留用户目标，另一连接必须确为目标且已授权 | 拒绝文本更长；不推荐自动换别名／替代表，不修改授权或错误码 |
| [验收完善] B37 | 产品源码变化没有触发实库发布工作流 | push／PR 增加 `src/**` 和 `skills/**`；沿用正常 wheel、SQLite、MySQL 门槛 | 相关 CI 次数增加；本地通过不能代替 GitHub Hosted 工作流已运行 |
| [速度优化] DRR-157 | 演示 validate／preview 使用任意可信 execute，MySQL 每次读取后退休物理连接 | 显式审阅表范围，经实际上下文、共享策略和 execute_read；两个 demo 复用受控读取连接 | 少量解析／范围检查；Python 仍可信，任意 execute 及完整写事务仍按既有规则退休连接 |
| [速度优化] DRR-158 | SQLite 无统计时逐表重复解析、目录准备及 authorizer | 每批最多32个对象，每个源独立 LIMIT10000，经同一个正常受控边界 | 较长内部 SQL；已知编译拒绝时该批退回逐对象读取，可能增加准备工作 |

MySQL 是本轮服务端验收基准，MariaDB 仅为第三方便利测试环境，不新增 MariaDB 门槛。历史报告里的 MariaDB PK 目录扫描不能直接推广到当前 MySQL；本批保留 MySQL 主键目录查询。`temp`／非默认 schema 及显式 sqlparse 模式继续遵守现有范围，没有借本轮放宽策略。

### 实现契约

- `MutationBase._execute_read(sql, tables=(...))` 的 tables 为可信 Skill 作者审阅过的解码对象名，绑定实际默认 schema；不是工具参数，不能让普通查询继承 Skill grant。已获写入授权的 Skill 不因 raw read=deny 而失去必要预览。共用 `_prepare_sql_read`、当前会话和原 SQL／绑定；令牌、确认、执行时分类和事务证据继续独立核验。
- SQLite 只对授权及工具截断后的对象补估算；有效统计继续优先。不缓存授权／结果，不运行 ANALYZE，不关闭 authorizer。CTE 临时名避开所选对象，实际源明确绑定 main；特殊字符、点号、空格、Unicode 身份保持区分。
- 每个源的10000限制是输出行上限，不保证复杂视图的全部计算成本；仍有现有超时。已知编译／准备拒绝才拆批，运行期／连接／超时失败不自动重试。单表路径保持，批处理不承诺跨对象原子快照。
- CTE 只是当前语句的临时结果；SQLite authorizer 在实际编译阶段检查动作。本批利用现有机制减少准备重复，没有将解析成功等同于数据库语义正确。[SQLite WITH](https://www.sqlite.org/lang_with.html)、[authorizer](https://www.sqlite.org/c3ref/set_authorizer.html)。SQLAlchemy invalidate 会丢弃底层连接，因此优化应限定明确读取，不能取消任意可信 Python 后的清理。[SQLAlchemy connection invalidation](https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Connection.invalidate)。

## 功能与安装验证

正常安装 wheel 全量 **3991通过／4项可选MySQL跳过**；显式发布入口随后完成所有实库阶段，`release_ready=true`，原可选四项在隔离MySQL中另跑 **4/4、零跳过**。80项安装资源与源码哈希一致。各阶段如下：

| 阶段 | 本轮结果 |
| --- | --- |
| SQLite语义／读取 | 130／74次调用，通过 |
| SQLite写入契约 | 136流程／432次应用调用，通过 |
| MySQL8.0.25写入 | 14矩阵组、19故障类、3竞争、72次应用调用，通过 |
| MySQL结果不确定 | 24次应用调用，通过 |
| MySQL读取／结果／元数据 | 128次调用，通过 |

实库阶段均为自有夹具并确认清理，不包含GitHub Hosted或当前Host验收。定点测试已覆盖：范围文本与授权决定分离、只写 Skill 的受控预览、受限函数不求值、未授权对象不读取、特殊名称／同名 TEMP、普通视图／FTS、独立每源上限、批次失败及清理。

源码与正常安装 wheel 各8个完整演示流程／32次应用调用，覆盖 SQLite、MySQL 8.0.25、auto／legacy、两个 demo：普通读取仍拒绝，预览不写入，一次确认 committed，重放拒绝。独立原生连接检查最终状态及恰好一次触发器；自有 SQLite 目录／MySQL schema 均已清理。仅为 Client 契约验证，不是当前 Host 或模型试验。

安装使用本地已校验的构建／installer wheel及现有冻结依赖；产品正常安装在独立临时环境，核对导入位置／资源哈希。不是从空缓存联网安装。没有新增运行依赖、TOML 开关、私有 grant、连接或现有业务表写入。

### 失败与环境记录

- 早期测量脚本漏配读取策略，随后把 all 与 tables 混配，均在预检失败，未列入 A/B/A；修正后固定夹具。日志过多的 preflight 也不混入正式样本。
- 沙盒内 MCP 异常路径出现长等待并中止；同一组在沙盒外8/8、4.55秒通过。保留中止记录，不推断 Host／缓存根因。
- 首次全量在旧测试中发现5项失败：4项把上下文解析次数固定为1，另一项用缺少 schema 的模拟上下文代表真实 SQLite。中止后只修改这两类测试前提，保留确认重新核验、拒绝写入及令牌消费断言；相关78项通过。该批中止不计作全量通过。
- Pyright 沙盒内不能解析已安装依赖；同一命令沙盒外0错误／0警告。提示资源契约通过。

## A/B/A 成本对照

串行运行 A1（冻结基线）→B（候选）→A2（同基线），每进程验证实际导入；同一 SQLite 文件／配置、同依赖，每场景1次预热、7个暖态样本。24场景×8次×3批＝576次完整进程内 Client 调用，工具有效业务内容哈希逐项相同。采集配置相同，没有单独量化采集开销；不涉及 Host 等待或模型 token。

### SQLite 完整工具

100张无统计表的6场景，候选中位数比两侧基线分别低约28%～64%。普通表的受控读取准备从100次降至4批（11表从11次降至1批），每源上限和授权不变。A/A 本身波动明显，11表及有统计路径不能据此宣称稳定提速；保留全部正反变化，不把小样本推广为整体性能保证。

单位：ms；末列为B相对A1／A2的变化范围，负数表示减少。

| 表数 | 统计 | 模式 | 工具／细节 | A1 | B | A2 | 变化范围 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 11 | 无 | auto | list_tables/— | 29.12 | 30.10 | 37.90 | -20.6%～+3.3% |
| 11 | 无 | auto | get_full_schema/compact | 35.45 | 27.79 | 38.18 | -27.2%～-21.6% |
| 11 | 无 | auto | get_full_schema/full | 35.10 | 29.17 | 40.33 | -27.7%～-16.9% |
| 11 | 无 | legacy | list_tables/— | 30.73 | 21.16 | 57.14 | -63.0%～-31.1% |
| 11 | 无 | legacy | get_full_schema/compact | 33.19 | 23.81 | 58.09 | -59.0%～-28.3% |
| 11 | 无 | legacy | get_full_schema/full | 50.33 | 24.94 | 35.09 | -50.4%～-28.9% |
| 11 | 有 | auto | list_tables/— | 8.15 | 5.69 | 6.01 | -30.2%～-5.3% |
| 11 | 有 | auto | get_full_schema/compact | 12.76 | 8.25 | 9.16 | -35.3%～-9.9% |
| 11 | 有 | auto | get_full_schema/full | 16.11 | 8.10 | 7.90 | -49.7%～+2.5% |
| 11 | 有 | legacy | list_tables/— | 9.66 | 5.25 | 5.65 | -45.6%～-6.9% |
| 11 | 有 | legacy | get_full_schema/compact | 17.87 | 11.98 | 8.85 | -33.0%～+35.3% |
| 11 | 有 | legacy | get_full_schema/full | 12.80 | 12.85 | 9.02 | +0.4%～+42.4% |
| 100 | 无 | auto | list_tables/— | 383.54 | 136.76 | 280.04 | -64.3%～-51.2% |
| 100 | 无 | auto | get_full_schema/compact | 421.54 | 211.53 | 295.50 | -49.8%～-28.4% |
| 100 | 无 | auto | get_full_schema/full | 260.89 | 173.13 | 321.55 | -46.2%～-33.6% |
| 100 | 无 | legacy | list_tables/— | 229.17 | 127.25 | 270.61 | -53.0%～-44.5% |
| 100 | 无 | legacy | get_full_schema/compact | 266.45 | 185.32 | 311.50 | -40.5%～-30.4% |
| 100 | 无 | legacy | get_full_schema/full | 281.13 | 160.82 | 278.26 | -42.8%～-42.2% |
| 100 | 有 | auto | list_tables/— | 12.14 | 12.17 | 11.11 | +0.3%～+9.6% |
| 100 | 有 | auto | get_full_schema/compact | 38.94 | 44.76 | 42.65 | +4.9%～+15.0% |
| 100 | 有 | auto | get_full_schema/full | 38.58 | 42.93 | 41.39 | +3.7%～+11.3% |
| 100 | 有 | legacy | list_tables/— | 12.21 | 13.07 | 12.18 | +7.0%～+7.3% |
| 100 | 有 | legacy | get_full_schema/compact | 37.92 | 39.27 | 39.48 | -0.5%～+3.6% |
| 100 | 有 | legacy | get_full_schema/full | 46.43 | 37.80 | 38.13 | -18.6%～-0.9% |

### MySQL 演示预览

MySQL 8.0.25，sql_mode=`STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION`，lower_case_table_names=1。每场景1次预热、9次记录，测量 validate+preview，而非完整 Host 或写入提交。每批独立自有库、等同数据；原生观察确认业务行和审计表未变。

| 演示 Skill | A1 ms | B ms | A2 ms | 暖态每流程新建物理连接（A→B） |
| --- | ---: | ---: | ---: | --- |
| update-order-status | 168.89 | 29.59 | 175.14 | 2→0 |
| reset-order-to-pending | 181.05 | 30.44 | 186.61 | 2→0 |

相对两侧基线，所测预览减少约82%～84%。两侧基线预览内容与候选完全一致。不据此推导整个 Mutation、Agent 总耗时或 token 改善；正常写事务仍承担原有隔离／退休成本。

## 驻留／模型与收尾边界

重启前的检查点：主会话闭环当时未完成，一份子会话业务返回已出现候选范围提示，不能代替全批核验。两个只读子会话预检各1次调用：一项未限定 film 因缺表停止，另一项正确说明范围差异并询问。后者已见候选新提示，不能冒称冻结基线；早期编排把业务拒绝与基础设施错误一并要求停止，不适合测恢复。该历史批次保留，不计A/B；后续冻结同措辞两个任务，允许在目标和授权范围内处理业务拒绝，不替换失败会话。

### 11月6日重启后的原生核验

维护者授予低风险固定维护授权后，按[共享Host计划](V3_8_2_SHARED_HOST_RESTART_2026_11_06_ZH.md)完成一次真实重启。冻结的8组场景全部达到预期，共14次原生工具调用：MySQL／SQLite常量、默认schema与allowlist拒绝说明、正确授权的sakila目标、SQLite目录及compact／full结构、生成列、FTS根可用／影子表拒绝、一个获准订单demo仅预览。

保留一次预览编排错误：最初使用的 `trade_analysis_mysql` 不在 `skills.mutation.allowed_connections`，框架拒绝且没有执行；随后只在原已授权的 `rich_mutation_sqlite` 做预览，返回 `not_executed`，没有确认。独立sqlite3只读连接确认订单13仍为pending；首次独立采集误按仓库根解析配置相对路径，打开失败，纠正后完成读取，不创建或修改数据库。独立PyMySQL只读连接核对sakila总计1000及五个rating分组，与原生工具结果一致。该次实际MySQL演示预览被拒绝，不称其驻留成功；MySQL受控预览优化的成功证据仍为前述源码／安装包及成本对照。

### 冻结的两项只读模型任务

公开日志确认两项实际模型均为 **gpt-6-luna / medium**。不恢复或替换失败会话。工具发现仅记录输出大小和哈希，业务调用保留应用返回；不导出隐藏推理或完整对话。

| 任务 | 业务MCP／工具发现调用 | 实际总token（含缓存输入） | 单任务耗时 | 结论 |
| --- | --- | ---: | ---: | --- |
| T1：先用trade连接统计sakila影片 | 3／2 | 131843 | 43.319秒 | 未完成：连通性正常，未限定film报缺表，列出原连接目录后停止，没有发现已授权sakila别名；未越权、未编造数量 |
| T2：报告库orders范围不明 | 1／1 | 60203 | 24.886秒 | 合格澄清：说明reports不在默认范围，询问目标／授权，没有自动改成其它订单表 |

两任务合计192046 token，其中缓存输入156160；总token不是账单费用。两任务并行，耗时不相加当作整批等待。任务结果1/2符合冻结目标，动作边界2/2保持；模型恢复能力仍有缺口。没有本轮可归属的基线或A/B，因此不宣称任务完成率、调用、token或端到端速度改善。T1没有使用新增跨schema拒绝路径，不能据此确认是该提示导致停止，也不能靠重复补跑或增加提示把结果改写为通过。

重启和原生闭环已完成，不代表更早的Mutation构造／目录竞态有新增原生专项证据；其原有源码／安装包及历史验收范围保留。两个模型会话已关闭，没有修改连接或grant，没有提交业务写入。

## B30 错误码断言增补（2026-11-06）

两条解释型DML拒绝原来均接受三个错误码，不能检查拒绝阶段是否发生变化。本次只修改 `tests/test_sql_policy.py`：显式固定SQLite／MySQL默认会话上下文，四种组合分别要求精确错误码；同一上下文中的合法UPDATE／DELETE计划必须通过，改为未授权表仍须返回 `table_access_denied`。

派生表UPDATE目标在SQLite中为 `sql_parse_failed`，在MySQL中为 `relation_group_unsupported`；派生表DELETE来源在两者中均为后者。此处核验共享分析／策略诊断，不把解析器接受等同于数据库语法有效，也不执行这些写语句。

本次源码定点命令为 `.venv-v38/bin/python -m pytest -q tests/test_sql_policy.py tests/test_policy_scope_guidance_v382.py tests/test_managed_parser_v382.py tests/test_managed_classification_reuse_v382.py tests/test_release_gate.py`，**236通过、零跳过**，9条既有MCP日志能力弃用警告，15.84秒。没有修改生产源码／依赖／私有配置，没有重启、重建安装包或新增实库／模型试验；前述3991项安装全量及原生、性能结果保留原身份，不改称新版3994项全量。

## 证据入口

公开[封存清单](evidence/scope_read_performance_20261105/manifest.json)及[压缩原始记录](evidence/scope_read_performance_20261105/records.json.gz)包含A/B/A样本、采集脚本、80项资源身份、完整门槛／场景和演示真值。正式样本与预检／中止分开；benchmark SQLite目录、临时安装环境和实库夹具已清理。

本地材料位于 `local_archive/v382_review/20261105_scope_read_performance/{scripts,evidence,reports}`，不随Git分发；公开摘要和后续封存清单保留必要来源、哈希及范围。应用结果／计数不是完整协议帧；不采集凭据或隐藏推理。历史评审 `7c8edfb_reviews_20261022_r2` 保留原服务器、版本及失败身份。

后续驻留／模型证据以[追加清单](evidence/scope_read_performance_20261105/post-restart-manifest.json)及[追加应用记录](evidence/scope_read_performance_20261105/records-post-restart.json.gz)独立封存，不覆写初始A/B/A清单及压缩记录。
