# v3.8.2 有限范围稳定性收敛执行表

日期：2026-10-22。目标是核实既有能力的共同契约，找出尚未被独立证据覆盖的边界；版本仍为 v3.8.2。维护者已确认三项门槛。本表将剩余工作排成有限批次；**排定不等于验收通过，也没有设置后台自动任务或发布日程。**

> 同日执行结果：S1—S4已按冻结范围完成；16类契约、四项补验缺口及三门槛范围内通过。254项定点回归、源码／正常wheel各332应用调用及定向故障变体通过；无新生产代码修改。详见[正式验收与限制](V3_8_2_STABILIZATION_2026_10_22_ZH.md)。原计划待执行检查点已独立封存保留。

## 当前状态与顺序

| 顺序 | 工作 | 当前状态 | 交付物／完成条件 |
| --- | --- | --- | --- |
| S0 | [功能修复／集成验证] 原 SQL 绑定、两后端真实写入状态 | 声明范围已完成 | DRR-142／143／144 修复；SQLite 与目标 MySQL/InnoDB 的独立真值、故障和令牌证据已形成；本批维护者重启后六项原生通过。保留各批未测范围，不代表所有写入故障已穷尽 |
| S1 | [契约审计] 逐格对照既有证据并冻结缺口清单 | 已完成 | C01—C16已映射测试／文件摘要／独立判据，执行前冻结四项补验缺口；未改生产代码 |
| S2 | [跨入口验收] 身份、授权、依赖与连接生命周期 | 范围内通过 | C01—C07、C14—C15定点正反例通过，源码／正常wheel对照及同名对象边界保留 |
| S3 | [结果与执行验收] 结果保真、元数据与写入证据复核 | 范围内通过 | C08—C13、C16：两后端读取结果／元数据对照通过；写入证据在核对资源差异与独立真值后复用，未重复全部故障 |
| S4 | [测试有效性／收尾] 哨兵、故障命中及发布结论 | 范围内通过 | 历史坏版本哨兵及两个定向结果变体检出目标缺陷，正向控制通过；旧证据保持、残余范围单列，无新运行修改／重启需求 |

S1 是接续工作的第一项，不优先开启新功能、全量性能调优或提示词改写。S2／S3 如发现生产缺陷，先记录根因、严重程度和有限相邻矩阵，再修复及复验；不能通过扩大拒绝范围让矩阵“变绿”。

## 固定范围：16 类契约场景

“场景”是一个有明确性质的测试族，**不是宣称只需 16 次调用**。S1 必须列出每族具体用例；只在后端语义相关的维度交叉，不将所有名称、语法、入口、模式机械做全笛卡尔积。既有大量回归是候选证据，尚不能自动填成通过。

| 编号 | 要验证的共同性质 | 入口／后端与边界 | 现有候选证据入口 |
| --- | --- | --- | --- |
| C01 | 执行原 SQL 与完整分析、方言／会话上下文绑定；错配不下传，一致调用保持能力 | SQLite／MySQL 读取适配器；原始查询与 Query Skill | [绑定回归](../../../tests/test_read_analysis_binding_v382.py)、[MySQL 门槛](V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md) |
| C02 | 限定名与名称内部点号不会共享授权 | 原始查询、Skill 依赖／发现／详情／执行、采样／计数；按后端实际名称语义比较 | [名称矩阵](../../../scripts/validation/semantics_matrix.py)、[schema 绑定回归](../../../tests/test_schema_binding_review.py) |
| C03 | 引用方式解码正确，Unicode／合法空格不被规范化成另一业务对象；数据库名称等价不自动扩大 grant | 两后端实际支持形式；MySQL 不使用非法尾空格物理表名作为正例 | [关系调用与列验证](../../../scripts/validation/relation_calls_columns.py)、[语义矩阵](../../../scripts/validation/semantics_matrix.py) |
| C04 | 已授权目标与内部生成 SQL 的实际读取对象一致 | SQLite main／temp／aux 同名对象；MySQL 配置库限定及已记录的临时对象污染边界 | [schema 绑定回归](../../../tests/test_schema_binding_review.py)、[读取边界脚本](../../../scripts/validation/read_boundaries.py) |
| C05 | JSON 条件依赖保留 builtin／stored／unverified，未观察范围不能等同于无依赖 | SQLite 有序名称查找、main／temp／aux；Skill 默认发现、详情与执行前检查 | [附加库依赖回归](../../../tests/test_attached_json_readiness_v382.py) |
| C06 | CTE、别名、视图与物理关系按角色及作用域判定，不因同名丢失物理依赖 | 两后端原始查询／Skill；SQLite 视图和触发器非执行计划的既定范围 | [语义矩阵](../../../scripts/validation/semantics_matrix.py)、[触发器 CTE 脚本](../../../scripts/validation/sqlite_trigger_ctes.py) |
| C07 | FTS 根授权、实际模块／内容绑定与直接影子表拒绝一致，业务名称不被标量函数改写 | SQLite FTS 查询／Skill／相关元数据；仅既有支持模块 | [FTS 脚本](../../../scripts/validation/fts_boundaries.py)、[关系调用脚本](../../../scripts/validation/relation_calls_columns.py) |
| C08 | 会求值的数据读取均执行受控读取；目录操作保持可信边界；受限函数没有执行 | query／Skill／sample／精确计数／无统计估算；SQLite 视图正例与无害计数探针反例 | [读取边界回归](../../../tests/test_read_boundaries_v382.py)、[读取边界脚本](../../../scripts/validation/read_boundaries.py) |
| C09 | 元数据忠实且有界：生成列、原始声明类型、实际 PRIMARY 及顺序、整表统计来源 | describe／list／compact 与 full schema；SQLite／MySQL 各自原生目录真值 | [元数据验证](../../../scripts/validation/metadata_projection.py)、[主键修复](V3_8_2_PRIMARY_KEY_METADATA_REPAIR_2026_10_21_ZH.md) |
| C10 | 重复结果标签明确拒绝，不能静默覆盖数据 | query／Query Skill；sample 复用标签边界；两后端结果 | [结果回归](../../../tests/test_read_results_v382.py) |
| C11 | 二进制值按统一类型编码，不依赖是否碰巧为 UTF-8 | query／Query Skill／sample，含空值及非 UTF-8 值 | [结果回归](../../../tests/test_read_results_v382.py) |
| C12 | 限额按实际编码计算，超限首行可返回零行，截断说明与返回数据一致 | query／Query Skill／sample；空集、刚好边界、超限首行与多行 | [结果回归](../../../tests/test_read_results_v382.py) |
| C13 | 已声明支持的合法 SQL 正常通过，同时非执行计划不放行实际写入 | SQLite CTE／RETURNING 相关读取计划、COLLATE 已修形式；MySQL 固定版本／会话模式的已支持语法 | [计划补查脚本](../../../scripts/validation/read_plan_followups.py)、[已支持读取验证](../../../scripts/validation/read_capabilities.py) |
| C14 | 缓存纯分类不能代替即时授权、readiness、会话与令牌复验 | Skill 发现／详情／预览／消费令牌后的执行；状态变化与重复调用 | [分类复用回归](../../../tests/test_managed_classification_reuse_v382.py)、[受管计划脚本](../../../scripts/validation/managed_parser.py) |
| C15 | 连接初始／复用／重连后上下文和防护仍成立，不继承未清理回调、游标或事务 | SQLite 独占与语句缓存边界；MySQL 实际物理会话初始化；不把逻辑 close 当物理重连证据 | [会话回归](../../../tests/test_mysql_sessions_v382.py)、[MySQL 会话脚本](../../../scripts/validation/mysql_sessions.py)、[SQLite 写入回归](../../../tests/test_sqlite_write_transactions_v382.py) |
| C16 | committed／rolled_back／unknown、直接行数、触发器／级联真值及一次性令牌一致 | SQLite 和真实 MySQL/InnoDB：BEGIN、执行、取结果／计数、提交、回滚及清理；逐项区分真实故障与注入 | [SQLite 写入脚本](../../../scripts/validation/sqlite_writes.py)、[MySQL 写入脚本](../../../scripts/validation/mysql_writes.py)、[结果状态回归](../../../tests/test_v372_write_outcomes.py) |

## 三项门槛如何判定

1. **真实状态。** 事务性业务行及事务性触发器／级联是判据；清理结束后使用独立数据库连接取真值，不经过被测解析、授权或结果编码。保留各后端计数差异；MySQL 自增分配空洞不视为回滚失败。unknown 同时验证“已变”与“未变”，不能解释为未执行，也不自动重试。源头仅为模拟对象的测试不能单独证明真实回滚。
2. **跨入口一致且保留能力。** 适用场景同时核对授权对象、实际读取对象和合法成功结果。限定名称、同名对象与会话变化不能靠字符串拼接或默认上下文推断。readiness 尚不能核验的范围保持明确 unverified，不伪造支持，也不以收紧策略代替修复。内部接口反例由内部测试证明，不能拿普通工具成功替代。
3. **测试能检出目标破坏。** 复用 SQLite 假回滚／RETURNING 和 MySQL 分析错配等已知坏哨兵，并保留正常调用正向控制。S1 为缺口只挑少量对应变体，例如跳过目标绑定、提前读计数、抑制物理 BEGIN、漏掉受控读取；必须证明注入实际命中且因目标断言失败。导入错误、权限不足、沙盒超时不计为检出缺陷，不默认引入通用变异测试平台。

## 执行边界与停止条件

- 冻结当前已安装一致的 **77 个运行资源**及三份私有 TOML 摘要；后续证据标注具体资源摘要，不能将旧源码通过直接算作当前通过。旧证据可作为对照与判据来源；资源无关性须说明。
- 只覆盖现有 SQLite 与实际 MySQL 8.0.25／InnoDB，按当前会话契约验收；MariaDB、新引擎、新 SQL 模式和通用语法扩展不纳入本轮。MySQL 同会话临时表可能遮蔽配置库对象这一既有限制不改写成已保证消除；污染连接的可信扩展约束单独保留。
- 主会话原生检查仅做已授权读取、预期拒绝及未确认预览。真实写入使用已约定的隔离临时夹具，清理仅限自己创建的准确对象；不变更配置／grant／已有业务数据。需要新的此类变更时再沟通。
- 优先复用冻结源码／正常 wheel 及证据；只有运行代码变化或明确证据缺口才重做受影响检查。生产改动按工作流执行必要全量、类型／提示和安装验证；集中到一个修复批次后再请维护者手动重启，不让每条用例触发一次重启。
- 复杂 Luna 任务不是物理事务或授权证明。若后续修改结果契约、工具引导或 Agent 路径，再固定同提示／同数据运行受影响完整任务，分别报告业务、步骤、调用、token 和措辞。当前十五项历史任务及弱提示严格措辞 1/3 的失败保留，不追加或外推为本轮效果。
- 每个 C 编号都必须有“证据覆盖／补测结果／明确契约外”的结论。任何声明支持的缺口不能用“契约外”掩盖；确认的 P1／P2 未修或关键真值证据不足时不通过发布门槛。非阻断 P3 写清影响和处理决定。
- S1 冻结的清单关闭、三项门槛通过并保留限制后，结束本轮收敛；新功能、新方言和独立新问题另建后续任务。新发现的严重问题仍应重新判断发布影响，不能为了守住范围忽略。完成这一有限矩阵不等于承诺程序没有剩余缺陷。

本表保留执行约定并同步实际状态；新证据在[收敛验收](V3_8_2_STABILIZATION_2026_10_22_ZH.md)独立记录。无新运行／提示／依赖／配置／grant变更，没有新的全量、性能或模型效果声明。重启后的状态沿用[六项原生补充](v382_mysql_write_contracts_2026_10_22/resident_restart/README.md)的原范围；之前的[源码／安装门槛检查点](V3_8_2_MYSQL_WRITE_CONTRACTS_2026_10_22_ZH.md)保持原始字节及当时待重启状态。
