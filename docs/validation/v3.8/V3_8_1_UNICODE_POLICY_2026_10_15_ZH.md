# v3.8.1 Unicode 保留名称误拒与文档入口整理（2026-10-15）

反馈属实，属于 P2 功能误拒，已修复。该批生产变更仅在 policy.py；版本保持 **3.8.1**。维护者重启后，同输入三个常量探针、两个真实 ASCII 保留名称对照及现有报表 Skill 共 **6/6 原生检查通过**。这关闭该批驻留验收；[后续相邻词法检查与补修](V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md)单独记录，不将本结果移作后续源码验收。

## 复现、相邻检查与修正

| 项目 | 修改前证据 | 修正与边界 |
| --- | --- | --- |
| PRAGMA 普通名称 | 独立 SQLite 中 pragma_locKing_mode 返回 7，pragma_locking_mode 返回 99，身份不同；授权前者后，FROM 和 SQLite IN 均 server_state_denied，相应 Query Skill 启动时跳过 | _relation_object_names 的普通名称和 Function 名称均改用现有 ascii_identifier_lower；不把 K 折叠成 k |
| 相邻账户名称 | 普通列 current_uſer 返回 7，current_user 返回 99；旧 .upper() 将长 s 转为 S，前者 raw 和 Skill 同样被误拒 | 账户保留集合及比较统一为 ASCII 小写；真实 USER／CURRENT_USER／SESSION_USER／SYSTEM_USER／CURRENT_ROLE 的现有拒绝保留 |
| 内部解析默认值 | 四个关系／CTE 辅助函数仍默认 str.lower，但现有生产入口已显式传入目标转换，不把它们算作四项已复现漏洞 | 默认值也统一为 ASCII 转换，预防内部调用再引入 Unicode 身份折叠；显式大小写敏感路径继续传入原比较规则 |
| 其他转换 | 锁／耗时函数、系统 schema、关系授权／readiness 已用 ASCII；目录过滤没有复发 | SQL 关键字分类、配置标签与自然语言搜索不是物理对象身份比较，不作全项目机械替换 |

Python 的 [str.lower](https://docs.python.org/3.12/library/stdtypes.html#str.lower) 使用 Unicode 大小写规则。SQLite 的[标识符比较接口](https://sqlite.org/c3ref/stricmp.html)与其内部名称比较一致，默认 ASCII 比较范围及可扩展性另见 [FAQ](https://sqlite.org/faq.html#q18)。本次结论由原生同库两实体和协议路径共同确认，不把字符串排序规则或 Python 的转换直接当作所有数据库的标识符语义。

原规则保留 ASCII PRAGMA 名称的有限集合，仍不是整个 pragma_ 前缀禁令；列／字符串语义、表授权和目标连接范围不变。Unicode Function 形态的回归只验证“不被当成 ASCII 保留名称”，不宣称普通表能作为表值函数调用，也不保证未注册函数可执行。元数据工具原来的 identifier 语法限制没有扩大。本次未接入 AST／authorizer、未加依赖、配置或 Agent 调用步骤。

## 验收

| 检查 | 结果与范围 |
| --- | --- |
| 相同输入基线／修复后 | 两协议每阶段 **26 次**私有 Client 调用；三类业务查询、默认发现、详情／readiness、执行均恢复；真实 ASCII 保留名称继续拒绝，危险 Skill 模板继续跳过 |
| 新增回归 | **56 passed、1 warning，3.76 秒**；原生名称身份、ASCII 大小写／四种引用／限定名、FROM／IN、账户列、函数分类及两协议全路径；哨兵验证保留名称不进入 adapter.execute |
| 全量 | **1278 passed、4 skipped、68 warnings，116.31 秒**；RUN_MYSQL_INTEGRATION_TESTS=0；新增旧协议案例增加一次既有 logging 弃用警告 |
| 类型／提示契约 | Pyright **0 errors、0 warnings**；已安装提示资源／路由契约通过，未改提示文本 |
| 安装包 | 当前 sdist／wheel，仓库外非 editable；69 份生产资源摘要逐项核对，真实 CLI serve、两种协议 **26 次 stdio 调用通过** |
| 刷新探针 | 三条无列列表的常量 CTE，重启前当前 Host 均 server_state_denied；维护者重启后相同 SQL 均返回 n=7。两个真实 ASCII 保留名称继续拒绝，报表 Skill 返回五单／1709.93；共 **6/6**，文本与结构化结果一致。只确认重启后的行为，不由此认定之前由缓存导致 |

修改前完整生产资源摘要匹配[前批已验收快照](sqlite_prefix_2026_10_15/automation.json)。修改后只有 policy.py 不同；此前 1222 项／84 次安装包调用、原生 16/16 和[12 个完整 Luna 任务](V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md)继续归属其源码快照，不能标为最后补修的再次实测。未新增 MySQL Unicode 实库验证或模型 token／成本对照，不从回归总时长推性能改善。

首次类型检查未找到已安装依赖（49 errors／1 warning）；保留日志，随后在获准环境使用绝对解释器路径通过，不能唯一归因于某个因素。首次安装包已完成构建／安装，但私有 stdio 初始化没有完成结果集；SIGINT 未退出后，仅终止本轮父子进程，保留日志并清理临时目录。获准环境重跑完整 26 次成功；未操作配置中的驻留服务，不将首轮未完成当成产品验收通过或确定的沙盒根因。

最初的原生刷新探针含带引号 CTE 的列列表；当前源码的对应形态被 relation_scope_unresolved 保守拒绝，不能证明该探针重启后应成功。原记录保留，改用无列列表且已在 fresh Client 验证的形态重新采集刷新前记录；只对修正后的同一输入做重启比较，不混合两组。此处没有扩大现有 CTE 解析范围。

## README 的信息分工

用户指出首页连续堆放验收引用不妥，采纳。阶段计数、驻留状态和评审过程频繁变化，会挤占项目定位／快速开始，也容易把不同源码的证据混为当前结论。本次撤下中英根 README 各四段阶段提示；docs/README 中英各六段提示也移入“发布与验收”栏目。

- README：版本更新日志保留简短行为摘要，链接重构日志、发布说明和验收索引；部署说明及导航保留。
- REFACTORING_LOG 中英：保存每批改动、决定、原因、取舍和验收范围。
- 发布说明：面向使用者描述契约及限制；docs/README 汇总各日期验收入口。
- 独立验收文档及证据目录：保留任务脚本、数字、失败、实际用量和源码归属，不删除或改写历史 JSON。

本批新增 DRR-2026-095；完整提交说明继续为七条分组，补入 Unicode 身份并将风险编号范围延伸至 095。所有新数据库对象均在自动清理的私有 SQLite；未改配置数据库或 TOML、未创建 commit。见[本批证据清单](pragma_identity_2026_10_15/manifest.json)。
