# 文档索引

[English](README.md) | 中文

项目动机、设计理念、快速开始与工具示例见根目录 [README](../README_ZH.md)。本索引按用途整理详细指南、设计决策与验收证据。

## 配置与使用

- [配置示例说明](../config/examples/README_ZH.md)：SQLite、MySQL、多连接与受控写入。
- [TOML 配置与迁移](guides/CONFIGURATION_ZH.md)：字段、默认值、密钥来源、权限、扩展导入及切换/回退。
- [MCP 客户端指南](guides/TEST_MCP_CLIENT_GUIDE.md)：离线检查、协议检查与 preview/MRTR 审批示例。
- [AutoGen 示例](../examples/autogen/README.md)：独立依赖环境与验证范围。

## 设计与可复用指南

- [Host请求关联与有界排查：10月28日](validation/v3.8/V3_8_2_HOST_REQUEST_CORRELATION_2026_10_28_ZH.md)：可选遥测增加成对事件、调用关联及单调计时；审核关联已缩小范围，Host根因与常驻启用另列。
- [本轮Agent指导四目标总览](../REFACTORING_LOG_ZH.md)：自然结果解释、有效探索、弱提示状态解释及耗时归因，分别说明已实现内容、实测效果、代价和开放项；[发布摘要](releases/RELEASE_NOTES_v3_8.md)采用同一结构，逐批证据保留在下方。
- [期限字段报告措辞勘误：10月28日](validation/v3.8/V3_8_2_EXPIRY_FIELD_SCREEN_ERRATA_2026_10_28_ZH.md)：按冻结编排分三波、波内并发；每组六条输入包含期限，其中五个回答要求报告。1/5、2/5及不采用决议不变，原封存保留。
- [期限字段有限筛选与停止决议：10月28日](validation/v3.8/V3_8_2_EXPIRY_FIELD_SCREEN_2026_10_28_ZH.md)：六构造记录会话／24回答，A／B均8/12、保留各4/4；候选不完整而停止采用，原生5/6及独立成本保留。无产品改动、条件性重启或新的Host根因结论。
- [P1期限日期误判的公开证据核对：10月28日](validation/v3.8/V3_8_2_EXPIRY_DATE_REVIEW_2026_10_28_ZH.md)：统一时区后确认过期陈述缺乏依据；日期混用为线索，非已证明内部原因。保留5/6及规则暴露差异，无新增模型试验或产品修改。
- [期限／状态来源重启自然复验：10月28日](validation/v3.8/V3_8_2_EXPIRY_TRANSITION_RESTART_2026_10_28_ZH.md)：六fresh双轮已关闭，状态／动作6/6、期限呈现3/3、完整解释5/6；指导已公开展示仍有一次有效性误判，猜错列后的恢复保留。不宣称因果提效或Host耗时已解决。
- [期限字段／演示状态来源：10月28日](validation/v3.8/V3_8_2_EXPIRY_TRANSITION_GUIDANCE_2026_10_28_ZH.md)：两项元数据修订独立核对，两Client模式72预览用例通过，执行规则保持；原工程待重启状态保留，原生结果见上列独立补充，仍有一次解释失败；外部批遗漏保持，不宣称模型或性能改善。
- [Host审核／重复发现有限复核：10月28日](validation/v3.8/V3_8_2_HOST_DISCOVERY_FOLLOWUP_2026_10_28_ZH.md)：审核内部原因仍未定位；九旧任务的相同定义展示反事实少15554字符，保留有用结构／参数探索。无新模型试验、产品改动或token／速度收益声明。
- [预览衔接重启原生补充：10月28日](validation/v3.8/V3_8_2_PREVIEW_ROUTING_RESTART_2026_10_28_ZH.md)：工具选择3/3、业务完成2/3、动作／取消3/3；一项Host审批审核超时，完整完成门槛未通过。三读取独立重放一致，保留混合成本，不宣称普遍改善。
- [Skill发现到实际预览：10月28日](validation/v3.8/V3_8_2_PREVIEW_ROUTING_2026_10_28_ZH.md)：单处说明澄清，三个冻结原生基线工具选择均正确；70定点回归及新安装／元数据核验通过，原待重启检查点保留；候选结果见上列独立原生补充，不宣称遗漏率已降低。
- [期限／付款范围重启原生任务：10月28日](validation/v3.8/V3_8_2_EXPIRY_SCOPE_RESTART_2026_10_28_ZH.md)：三项双轮任务已结束并关闭，业务／解释2/3、完整冻结流程1/3、动作边界3/3。一次实际预览期限解释正确；漏预览、重复定义及非因果成本保留，刷新已闭环。
- [期限判定澄清与付款范围矩阵：10月28日](validation/v3.8/V3_8_2_EXPIRY_SCOPE_2026_10_28_ZH.md)：六个构造记录会话，新旧各16/16；可移植付款真值及八种错误变体。保留原待验检查点，原生结果另见上列，不宣称普遍改善。
- [重连后无损发现A/B：10月28日](validation/v3.8/V3_8_2_DISCOVERY_AB_RESTART_2026_10_28_ZH.md)：八个完整任务、24条独立SQL重放；当前数据业务／动作8/8、完整解释4/8，保留期限误判、事后付款口径缺口及混合成本；不改产品默认。
- [原发现A/B与子会话就绪检查点](validation/v3.8/V3_8_2_DISCOVERY_AB_2026_10_28_ZH.md)：175组重建与两个子会话canary失败保留，其八项待验由上列独立续验补充。
- [单位／期限原生核验：10月28日](validation/v3.8/V3_8_2_UNITS_EXPIRY_RESTART_2026_10_28_ZH.md)：两个完整业务任务及独立显示探针；财务／CNY／70%通过，预览期限及状态证据缺口保留，严格业务1/2及实际成本分列。
- [单位依据与预览期限呈现：10月27日](validation/v3.8/V3_8_2_UNITS_EXPIRY_2026_10_27_ZH.md)：两处局部文本澄清、独立限定回放及明确上下文成本；保留当时待原生检查点。
- [可移植哨兵与依赖感知发布门槛](validation/v3.8/V3_8_2_PORTABLE_RELEASE_GATES_2026_10_22_ZH.md)：普通pytest、显式实库验收与环境身份；[可复用命令](../scripts/validation/README.md)。

- [Agent证据：10月27日重启原生补充](validation/v3.8/V3_8_2_AGENT_EVIDENCE_RESTART_2026_10_27_ZH.md)：C及预览取消通过；财务数值／时间口径通过，无来源币种符号保留；实际调用／token与限制分别记录。
- [Agent证据补充：10月27日](validation/v3.8/V3_8_2_AGENT_EVIDENCE_FOLLOWUP_2026_10_27_ZH.md)：结果声明完整性、可移植时间／采集检查、限定回放及发现／Host诊断；原重启前检查点保留。
- [Agent结果指导：10月25日重启及完整任务](validation/v3.8/V3_8_2_AGENT_INTERPRETATION_RESTART_2026_10_25_ZH.md)：匹配6／保留2项业务检查通过；调用／token代价不一致、时间戳倒置与回放遗漏保留。
- [Agent结果解释、同版本A/A及采集边界](validation/v3.8/V3_8_2_AGENT_INTERPRETATION_2026_10_23_ZH.md)：原源码／安装及待重启检查点；后续原生证据另存。
- [v3.8.2 有限范围稳定性验收](validation/v3.8/V3_8_2_STABILIZATION_2026_10_22_ZH.md)：16类冻结契约及三门槛范围内通过，254项定点回归、源码／wheel各332调用，独立真值与故障哨兵；[执行表与停止条件](validation/v3.8/V3_8_2_STABILIZATION_PLAN_2026_10_22_ZH.md)。
- [v3.8.2 MySQL 原 SQL 绑定与真实 InnoDB 写入门槛](validation/v3.8/V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md)：绑定修复、真实故障／独立真值及unknown／令牌；源码／安装通过，[维护者重启后原生6/6](validation/v3.8/v382_mysql_write_contracts_2026_10_22/resident_restart/README.md)另行封存。
- [v3.8.2 SQLite 真实写入事务与完成态行数](validation/v3.8/V3_8_2_SQLITE_WRITE_TRANSACTIONS_2026_10_22_ZH.md)：WITH／分号回滚、RETURNING及私有源码／安装完整流程；[重启后12/12及稳定性复评](validation/v3.8/V3_8_2_WRITE_RESTART_AND_STABILIZATION_2026_10_22_ZH.md)独立保留范围与后续建议。

- [v3.8.2 最新完整 Agent 任务与实际成本](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_21_ZH.md) — 原生12/12；15项配对业务通过，token+3.85%、调用+4.63%；3项自然取消试验保留解释不足。
- [v3.8.2 真实 PRIMARY 身份与有序成员](validation/v3.8/V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md) — SQLite／MySQL共享契约、真值及成本；最新原生12/12；此前7/12差异保留；MariaDB不作验收要求。
- [v3.8.2 SQLite声明类型补修](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_REPAIR_2026_10_21_ZH.md) — 各投影／分组保留原生空类型；重启后9/9限定原生通过，另各144次源码／安装相邻调用通过。
- [v3.8.2 SQLite声明类型复评](validation/v3.8/V3_8_2_SQLITE_DECLARED_TYPES_ASSESSMENT_2026_10_21_ZH.md) — 确认既有P3，空类型被展示为TEXT；修复前的历史评估，后续批准补修见上项。

- [v3.8.2 FTS目录、统计来源及external-content rowid补修](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_REPAIR_2026_10_21_ZH.md) — 源码／安装通过；维护者重启后10/10既有别名原生核验通过，专用夹具范围单列。

- [v3.8.2 关系调用身份、JSON 同名根与 SQLite 生成列补修](validation/v3.8/V3_8_2_RELATION_CALLS_COLUMNS_2026_10_20_ZH.md)。
- [v3.8.2 完整Agent任务：实际token、调用、结果解释与配置复核](validation/v3.8/V3_8_2_COMPLETE_AGENT_EVAL_2026_10_20_ZH.md)。
- [v3.8.2 尾注释／绑定补修、列批读及请求内复用研究](validation/v3.8/V3_8_2_READ_PLAN_REPAIR_2026_10_20_ZH.md)。
- [v3.8.2 前次复查：补修前的问题及性能原型](validation/v3.8/V3_8_2_FINAL_AUDIT_2026_10_20_ZH.md)。
- [v3.8.2 方言注释、MySQL计划提示与NOT优先级](validation/v3.8/V3_8_2_DIALECT_COMMENTS_NOT_2026_10_20_ZH.md).
- [v3.8.2 readiness 职责拆分与有界受管分类复用](validation/v3.8/V3_8_2_MANAGED_CLASSIFICATION_REUSE_2026_10_20_ZH.md).
- [v3.8.2 受管计划 SQLGlot 迁移、临时回退与方言验收](validation/v3.8/V3_8_2_MANAGED_PARSER_2026_10_20_ZH.md).
- [v3.8.2 读取能力、schema 范围及 JSON／FTS 补修](validation/v3.8/V3_8_2_READ_CAPABILITIES_2026_10_19_ZH.md)。
- [v3.8.2 补修后复核：MySQL 元数据成本与两项待修 FTS 边界](validation/v3.8/V3_8_2_POSTREPAIR_AUDIT_2026_10_20_ZH.md)。
- [v3.8.2 SQLite 元数据退化：实测拆分与优化顺序](validation/v3.8/V3_8_2_SQLITE_METADATA_COST_2026_10_20_ZH.md)。
- [v3.8.2 FTS 缓存内容函数与限定根补修](validation/v3.8/V3_8_2_FTS_FOLLOWUPS_2026_10_20_ZH.md)。
- [v3.8.2 元数据优化：实现、成本及重启状态](validation/v3.8/V3_8_2_METADATA_OPTIMIZATION_2026_10_20_ZH.md)。
- [重构日志](../REFACTORING_LOG_ZH.md) / [English](../REFACTORING_LOG.md)：持续维护变更、决策、取舍和验证记录，包含 v3.8。
- [名称／会话语义、SQLGlot 与 SQLite authorizer](architecture/V3_8_2_SQL_SEMANTICS_ZH.md).
- [v3.8.2 验收、成本与限制](validation/v3.8/V3_8_2_VALIDATION_2026_10_16_ZH.md).
- [v3.8.2 视图读取与非执行型计划补修](validation/v3.8/V3_8_2_READ_BOUNDARIES_2026_10_17_ZH.md).
- [v3.8.2 触发器、WITH REPLACE 与 UPDATE OR 计划后续补修](validation/v3.8/V3_8_2_EXPLAIN_FOLLOWUP_2026_10_17_ZH.md).

- [v3.8.2 触发器局部 CTE 计划补修](validation/v3.8/V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md)。
- [v3.8.2 相邻问题复查与当前完整 Agent 任务](validation/v3.8/V3_8_2_ADJACENT_AUDIT_2026_10_17_ZH.md)。
- [v3.8.2 触发器 WHEN 修复与 Host 就绪排查](validation/v3.8/V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。
- [v3.8.2 已提交版本最终复核与 COLLATE P3 初次发现](validation/v3.8/V3_8_2_FINAL_REVIEW_2026_10_18_ZH.md).
- [v3.8.2 SQLite 操作数 COLLATE 补修](validation/v3.8/V3_8_2_COLLATE_REPAIR_2026_10_18_ZH.md).
- [v3.8.2 完整判断后 COLLATE 复评与 P3 初次发现](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REVIEW_2026_10_18_ZH.md)。
- [v3.8.2 完整判断后缀补修及限定原生验收](validation/v3.8/V3_8_2_PREDICATE_COLLATE_REPAIR_2026_10_18_ZH.md)。
- [v3.8 实施决策](architecture/V3_8_IMPLEMENTATION_ZH.md)：包结构、实例状态与参考稿评审。
- [工具契约与评估方法](guides/PROMPT_ENGINEERING_BEST_PRACTICES.md)：参数 schema、工具说明、提示词与行为检查。
- [Agent 编排行为验证方法](guides/MCP_AGENT_BEHAVIOR_VALIDATION_ZH.md)：可复用的路由、渐进披露和成本评估方法。
- [命名连接、Skills 与批准流程（v3.5–v3.7）](guides/V3_5-V3_7_SKILLS_GUIDE_ZH.md)。
- [统一连接诊断设计](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN_ZH.md) / [English](guides/V3_7_CONNECTION_DIAGNOSTICS_DESIGN.md)。
- [连接范围与参数示例修复方案（v3.7.3）](guides/V3_7_3_CONNECTION_ROUTING_REMEDIATION_ZH.md)。
- [此前的客户端指南（v3.7）](guides/TEST_MCP_CLIENT_GUIDE_v3_7.md)：保留该版本的响应示例与检查方式。
- 架构背景：[Skills 设计](architecture/MCP_AGENTS_SKILLS_DESIGN.md)、[SQLite 适配器](architecture/SQLITE_ADAPTER_DESIGN.md)、[LLM 转 MCP 可行性](architecture/LLM_TO_MCP_FEASIBILITY_ANALYSIS.md)。

指南统一放在 `docs/guides/`，文件名中的旧版本号不影响其作为设计和使用参考的价值。适用范围以文首说明与分日期记录为准；旧脚本、环境配置及测试数量不能直接当作当前部署说明。使用 v3.8 安装包时，请同时参考当前配置与客户端指南。

## 安全

- [v3.8 安全边界](security/V3_8_SECURITY.md)：可信 Python/Host、MRTR、单进程状态、审计与不确定结果。
- [设计风险登记](security/DESIGN_RISK_REGISTER_ZH.md) / [English](security/DESIGN_RISK_REGISTER.md)。
- [Skills 安全策略](security/SAFETY.md)：原扩展治理约定；适用版本和当前契约入口见文首。

## 发布与验收

- [v3.8 验收正文与原始证据](validation/v3.8/)。
- [共享 CTE 分析、功能修复与相邻检查](validation/v3.8/V3_8_1_CTE_ANALYSIS_2026_10_15_ZH.md).
- [未分类 WITH 恢复与开放的 CTE 限制](validation/v3.8/V3_8_1_CTE_CLASSIFICATION_2026_10_15_ZH.md).
- [CTE 声明与查询体调用边界](validation/v3.8/V3_8_1_CTE_HEADER_2026_10_15_ZH.md).
- [关系词法边界与保留函数引用](validation/v3.8/V3_8_1_LEXICAL_BOUNDARIES_2026_10_15_ZH.md).
- [Unicode 保留名称补修](validation/v3.8/V3_8_1_UNICODE_POLICY_2026_10_15_ZH.md).
- [完整原生 Agent 业务任务](validation/v3.8/V3_8_1_AGENT_REAL_TASKS_2026_10_15_ZH.md).
- [SQLite 目录字面前缀与方言范围](validation/v3.8/V3_8_1_SQLITE_PREFIX_2026_10_15_ZH.md).
- [内部 schema 绑定与关系 readiness](validation/v3.8/V3_8_1_SCHEMA_BINDING_2026_10_15_ZH.md).
- [结构化关系身份与 Mutation 复验](validation/v3.8/V3_8_1_RELATION_IDENTITY_2026_10_15_ZH.md).
- [CTE／成本矩阵、函数策略与 SQLGlot 验证](validation/v3.8/V3_8_1_PHASE123_2026_10_14_ZH.md).

- [10 月 13 日 v3.8.1 复评整改](validation/v3.8/V3_8_1_FOLLOWUP_2026_10_13_ZH.md)：IN 授权、结构化策略／查询异常、评审勘误与当前验收范围。
- [10 月 12 日 v3.8.1 复核收尾](validation/v3.8/V3_8_1_REVIEW_2026_10_12_ZH.md)：最终回归、安装包／真实数据库检查、GPT-6 Luna 轨迹、保留失败、已完成的常驻 Host 刷新核验及恢复路线误述。
- [10 月 3 日 v3.8.1 复核](validation/v3.8/V3_8_1_REVIEW_2026_10_03_ZH.md)：五次提交审查、查询策略修复、有界索引元数据与实测限制。

- [10 月 1 日 MRTR 原生验收](validation/v3.8/V3_8_MRTR_NATIVE_2026_10_01_ZH.md)：实际提交、延迟批准拒绝、夹具最终状态及 TTL/重启待验收边界。

- [v3.8 复评处理记录](validation/v3.8/V3_8_REREVIEW_2026_09_28_ZH.md)：确认 `139d53a` 远端 CI 成功，补齐 Query Skill 静态策略发现，记录回归和 Host 待验收范围。
- [v3.8 外部评审修复记录](validation/v3.8/V3_8_REVIEW_FIXES_2026_09_27_ZH.md)：已确认问题、CI 失败、生产路径回归及待验收范围。

- [v3.8 本地 live Review](validation/v3.8/V3_8_LIVE_REVIEW_2026_09_26_ZH.md)：Host 入口修复、真实数据库检查、9 次 Luna CLI 试验，以及后续原生重连和三组六轮代理测试；保留失败与验收边界。
- [v3.8 发布说明](releases/RELEASE_NOTES_v3_8.md)及[验收与实际 Host 限制](validation/v3.8/V3_8_VALIDATION_ZH.md)。
- [v3.7 发布说明](releases/RELEASE_NOTES_v3_7.md)、[v3.6](releases/RELEASE_NOTES_v3_6.md)、[v3.5](releases/RELEASE_NOTES_v3_5.md)。
- [v3.7 实测记录](validation/v3.7/)与 [v3.8 证据](validation/v3.8/)。保留原版本、失败试验和结论，不把旧版通过当成 v3.8 已验收。

## 归档快照

- [v3.7 README 中文版](history/README_v3.7_ZH.md) / [English](history/README_v3.7.md)。
- [旧公开环境配置模板](history/config/)：仅作迁移参考，服务不再加载 `.env`。

根目录 README 和重构日志继续维护。SQL 与业务 Skill 定义仍放在根目录 `skills/`，框架 SDK 位于 `src/sql_safety_executor/skills/`。

- [v3.8.2 读取结果与条件依赖补修（2026-10-21）](validation/v3.8/V3_8_2_READ_RESULTS_2026_10_21_ZH.md) — 统一编码／限额／readiness，源码／安装／原生分开归属。
- [v3.8.2 附加库JSON同名readiness复评（2026-10-21）](validation/v3.8/V3_8_2_ATTACHED_JSON_READINESS_2026_10_21_ZH.md) — 历史仅评估检查点，332次源码调用，当时DRR-135开放；随后补修见下项。
- [v3.8.2 附加名称有序观察补修（2026-10-21）](validation/v3.8/V3_8_2_ATTACHED_JSON_REPAIR_2026_10_21_ZH.md) — DRR-135已实施，新增67回归，原源码／wheel各332调用；统一重启20/20通过，特殊夹具仍属源码／安装。
- [v3.8.2 内部元数据名称遮蔽评估（2026-10-21）](validation/v3.8/V3_8_2_METADATA_NAME_COLLISIONS_2026_10_21_ZH.md) — 历史独立旧P2／DRR-136评估，随后补修见下项。
- [v3.8.2 内部元数据PRAGMA补修（2026-10-21）](validation/v3.8/V3_8_2_METADATA_PRAGMA_REPAIR_2026_10_21_ZH.md) — DRR-136已实施，补名称碰撞／预算／返回值核对及串行成本；统一重启20/20已核验；[独立补充](validation/v3.8/v382_metadata_pragma_repair_2026_10_21/resident_restart/README.md)。
- [v3.8.2 FTS目录／统计来源复评（2026-10-21）](validation/v3.8/V3_8_2_FTS_CATALOG_STATISTICS_ASSESSMENT_2026_10_21_ZH.md) — 历史开放检查点：两项P2、394次隔离Client调用；后续补修及限定验收见上方记录。
