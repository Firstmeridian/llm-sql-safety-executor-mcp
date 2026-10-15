# v3.8.1 相邻词法边界补修（2026-10-15）

维护者重启后的[前批 Unicode 身份验收](V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md)已原生 **6/6 通过**。继续检查发现三类相邻问题，现已补修；生产相对前批只改 core/policy.py 与 core/sql.py，版本仍为 **3.8.1**。本批源码、安装包与真实 MySQL 检查通过；维护者重启后，相同原生探针与正常对照 **10/10 通过**，该批驻留验收完成。不把前批六项通过移作本批验收，也不推定缓存是历史差异的根因。

## 问题、原理与取舍

| 项目 | 修改前独立证据 | 修正 | 收益及代价 |
| --- | --- | --- | --- |
| P1 关系目标消失 | SQLite 中合法 window／offset／lock，以及 lımıt／offſet／wındow 等表可返回 7；只授权 orders 时旧策略仍允许部分查询，关系提取为空。raw 与 Skill 两协议矩阵复现 | FROM／JOIN／逗号之后优先取得目标，再识别子句边界；允许关系位置的单个关键字形名称成为结构化 RelationReference，继续逐组件授权 | 关闭漏查，授权与未授权、发现／详情／执行一致；仍依赖保守 sqlparse 分组，不宣称完全覆盖方言语义 |
| P2 Unicode 被当成 SQL 词汇 | unıon 被报 union_disabled，ınsert 被报 nested_write_denied；私有 SQLite UDF load_fıle 返回 7，却被当作 LOAD_FILE | 共享 sql_token_upper 从 token.value 仅转换 ASCII；不能用已经执行 Unicode upper() 的 normalized。同步语句形态、CTE、结构扫描及 EXPLAIN 正则的 ASCII 范围 | 保留真实业务拼写；统一词汇比较，不重写 SQL、不以展示字符串作授权键。配置标签／自然语言搜索不机械修改 |
| 现有保留函数的引号识别遗漏 | 私有 SQLite 注册仅返回 7 的同名无副作用函数，证明双引号／反引号／方括号实际可调用；旧 LOAD_FILE／账户检查漏拒这些形态 | 复用现有真实调用识别，按引用解码一次、ASCII 比较，统一处理既有文件／账户保留名称；CTE 列声明和字符串不算调用 | 不新增保留函数种类，真实保留调用在数据库 I/O 前拒绝；同名自定义函数按既有保留语义受限，quoted 列不受调用规则影响 |

[sqlparse 官方源码](https://github.com/andialbrecht/sqlparse/blob/master/sqlparse/sql.py)说明 value 保留原值，而 normalized 对 keyword 调用 upper()；本地已安装版本也逐项确认这一行为。[SQLite 关键字文档](https://www.sqlite.org/lang_keywords.html)说明部分上下文可把关键字作为标识符。这里的具体影响由本批 SQLite 原生执行与 MCP 矩阵确认，不把库的 token 标签当作数据库语义证明。

账户调用统一识别后，也消除普通 user(n) CTE 声明被扁平调用扫描误拒的相邻路径；bare CURRENT_USER 的原有保守保留不变。文件写入子句、五类锁／耗时调用、真正 ASCII PRAGMA／账户名称、UNION 与跨 schema 授权继续执行原规则。本批未新增包、配置、工具参数、提示文本或 Agent 必需步骤；未接入生产 AST／authorizer。检查仍有重复解析／token 扫描，不作零成本或延迟改善承诺。

## 验收与来源

| 检查 | 结果及范围 |
| --- | --- |
| 同输入基线与修复后 | 两协议 × 两种授权范围，各阶段 **68 次**私有 Client 调用；四类名称的 raw、发现、详情／readiness、Skill 执行，以及带引号保留调用。保留修改前结果，不以测试预期代替实际返回 |
| 回归 | 新增 **107 项**，覆盖 11 个名称、FROM／JOIN／逗号／限定名／带引号 IN、函数原生身份和引用、两协议全路径及缓存 Skill；最终全量 **1385 passed、4 skipped、71 warnings，122.69 秒**，MySQL opt-in 关闭。71 项为既有 logging 弃用警告，新增 legacy 案例增加三次 |
| I/O 顺序 | 未授权 raw／Skill 运行时与保留调用设置 execute／connect／get_read_relations 哨兵，拒绝前不得触达。独立的 Skill 发现／详情仍可观察当前 schema；schema_ready=true 与 policy_allowed=false 并不矛盾，不能把元数据观察等同授权 |
| 类型／提示 | 最终 Pyright **0 errors、0 warnings**；已安装提示资源／路由契约通过 |
| 安装包 | 仓库外非 editable sdist／wheel、69 份生产资源摘要核对，真实 CLI serve、两协议与两范围 **68 次 stdio 调用通过**；无 handler 替换 |
| MySQL | 当前源码私有 Client 在已配置 trade_analysis_mysql 两协议 **12/12**，仅常量／CTE／Unicode 别名读取和保留调用拒绝；未创建数据库对象，不证明物理 Unicode 名称全矩阵 |
| 扩展相邻审查 | 97 个候选名称中 **542 个原生有效案例**，未授权范围漏查 **0**；包括空格、引用字符、点号及关键字／Unicode 拼写。没有证明所有 SQL 语法均安全 |
| 驻留 | 修改前四条同输入探针分别到达 unknown_table／unknown_function；维护者重启后分别按预期返回 table_access_denied／file_operation_denied／server_state_denied；Unicode／CTE、真实 MySQL 与现有 Skill 正常对照也通过，共 **10/10**。正文／结构化结果一致；不据此认定缓存根因 |

所有私有 SQLite 夹具、安装目录及测试进程自动清理；未写配置数据库、TOML 或依赖文件，未创建 commit。应用记录保存 content／structuredContent／isError／meta，原生 Host 记录保存暴露的应用字段；压缩完整应用结果／日志，不宣称保存所有 JSON-RPC 帧或通知。旧批次清单逐字节校验，旧 Luna 用量继续归属旧源码，本批未新增模型 token 对照。

## 保留的保守限制与测试修正

扩展矩阵有 **18 个已授权但未加引号的写法仍被拒绝**：like／regexp（各三种）、replace／with（各五种），以及 lımıt／unıon 的裸 IN（各一种）。原因分别涉及 operator／DML／CTE 分类及 WHERE 分组；未授权时同样拒绝，未观察到读取越权。**18/18 已验证标准引用后的同义查询恢复并返回独立真值 99**。隔离重建两份摘要核对的前批模块、确认其他生产资源未变后，18 种原写法在前批策略也均拒绝；此项是源码策略重建，不冒充历史 Host 记录。统一分析／AST 阶段应把这些真值纳入矩阵。前批已保留的带引号 CTE 列列表限制也没有在本批扩大解析范围，不把引用所有名称当作普遍解决方案。

新增测试初稿有错误设定：空 allowlist 实际禁止所有读取；发现／详情的 schema 观察不能套用执行前的 I/O 哨兵；schema_ready 与授权是独立状态。另外初稿把上述两种裸 IN 解析限制误设为必成功。已修正用例并增加显式关闭及引用恢复检查。首轮 45 failed／60 passed 的完整日志未保存，保留其摘要，不伪称完整失败日志可追溯；中间 2 failed／103 passed 日志、早期 105 passed 日志及最终全量日志均保留。私有 Client 初次修复后收集也因 schema_ready 假设错误中止，修正后 68 次完整通过；前后请求保持一致。

本批记录 DRR-2026-096；见[证据清单](lexical_identity_2026_10_15/manifest.json)。重启后原生 10/10 已追加，历史修改前记录保留；[后续 CTE 声明／查询体扫描遗漏另行修复](V3_8_1_CTE_HEADER_2026_10_15_ZH.md)，不混合源码验收。
