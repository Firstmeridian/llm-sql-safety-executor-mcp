# v3.8.2 相邻问题复查与当前完整 Agent 任务（2026-10-17）

> 后续：已获准补修 WHEN 角色边界，源码／安装及重启后限定 57/57 核验通过，另三个带实际子会话预检的双轮销售任务最终 3/3（保留一次初稿拒绝／恢复）；Host 结构化就绪日志、范围与实测见[后续报告](V3_8_2_TRIGGER_WHEN_2026_10_17_ZH.md)。下文保留发现时的原始结论、2/3 业务结果和源码范围。

承接[触发器局部 CTE 补修及限定重启复验](V3_8_2_TRIGGER_CTE_2026_10_17_ZH.md)。本批只审查、实测与记录，未改运行代码、依赖、版本、配置或配置库数据。75 项运行资源与前批封存源码一致。发现一项新的 P2 功能回归，建议提交前补修；DRR-108 对新边界重开，前批 57 项验收保留其实际场景范围。

## 结论与建议

| 项目 | 判断与证据 | 建议 |
| --- | --- | --- |
| P2：触发器 WHEN 中的 begin 业务列误作正文边界 | 当前六种写法 × 两前缀共 12 项合法计划误拒；同输入修复前源码全部成功。两种 Client 的 raw／Skill 也复现 | 优先补修实际 WHEN／正文分界，加入名称角色与表达式上下文回归，沿用现有分析与执行边界 |
| 外层独立子查询复用 CTE 名 | 前批已记录的保守功能限制；不等于本轮触发器局部 CTE 修复无效 | 保留限制与不同局部名恢复路径，另按 scope 身份完善 |
| 生成列的受限命名 UDF | 受信 schema／UDF 的已记录边界，旧新源码行为相同；无害计数函数确认虚拟生成列求值可能没有新的 FUNCTION 事件 | 保留可信部署约定，不将函数限制描述成任意 schema 的完整求值隔离；本批不扩大为不可信 schema 支持 |
| 某个 Luna 子会话的 SQL MCP 不可用 | 正确工具名被 Host 拒绝，随后本子会话目录为空；另外两个业务子会话及独立预检成功 | 作为完整任务可用性失败保留；不能归因于缓存或 MCP 代码，也不能用另一子会话的预检代替本会话可调用性 |

## 新 P2：WHEN／BEGIN 的角色混淆

最小私有夹具：

```sql
CREATE TABLE orders(n, "begin");
INSERT INTO orders VALUES(7, NULL);
CREATE TABLE audit_log(n);
CREATE TRIGGER log_orders AFTER INSERT ON orders
WHEN NEW.begin IS NULL
BEGIN
  INSERT INTO audit_log VALUES(NEW.n);
END;

EXPLAIN INSERT INTO orders(n) VALUES(99);
EXPLAIN QUERY PLAN INSERT INTO orders(n) VALUES(99);
```

两张表均授权，独立 SQLite 正常返回计划且数据不变，当前 MCP 返回 `view_scope_unresolved`。将**触发器定义内**的列引用写成 `NEW."begin"` 后成功。这是定义对照，不能误导 Agent 认为只修改外层 EXPLAIN 的引用就能恢复，也不授权它修改触发器。

原因位于 `src/sql_safety_executor/core/analysis.py:464`：`analyze_sqlite_trigger()` 从表名之后寻找第一个 `TokenType.BEGIN`，没有排除 WHEN 表达式中作为列名的 begin，随后截出了不完整表达式。上次补修扩大了 SELECT／DML 来源的准备范围，使原本未进入这个辅助分析分支的合法计划也受到影响。辅助函数的边界缺陷既已存在，但**当前相对补修前确有功能回归**。

扩展确认 `NEW.begin`、UPDATE／DELETE 的 `OLD.begin`、CASE、COALESCE 及 WHEN 子查询中的 begin 共六种形式；两种 EXPLAIN 前缀均误拒。带引号形式、合法 end 名称和包含 BEGIN／END 的字符串对照通过。裸 `NEW.when`／`NEW.on` 被 SQLite 自身拒绝，不计为产品问题；首轮夹具中断与校正保留。

建议按真实名称／表达式角色识别正文起点，继续让 SQLGlot 分析 WHEN 和各正文片段；执行原 SQL，保留依赖、受限函数、实际写入及歧义拒绝。不新增通用解析框架、不关闭 authorizer、不以忽略整个 WHEN 作为恢复方案。

## 定点验证及范围

| 层次 | 结果 |
| --- | --- |
| 相邻计划矩阵 | 26 个夹具 × 两前缀＝52 项符合预期，涵盖 INSTEAD OF／TEMP／BEFORE、RETURNING、RAISE、INSERT OR／UPDATE OR、兄弟 scope 及未授权来源／受限函数对照 |
| 关键字边界扩展 | 12 个夹具 × 两前缀＝24 项：当前 12 项成功、12 项误拒；修复前同输入 24 项全部成功。当前两组合计 76 个不同夹具／前缀组合，64 项符合预期、12 项误拒，不宣称全部通过 |
| 实际 Client | auto=`2026-07-28`、legacy=`2025-11-25`，共 28 次 in-process Client 调用；6 次 bare 定义 raw／Skill 执行误拒，6 次 quoted 对照成功；发现／详情能列出 Skill，实际 DML 继续拒绝，数据与回调状态正确清理 |
| 生成列观察 | 同一无害、deterministic 的 SLEEP 命名 UDF：读取虚拟生成列实际调用一次，COUNT 及 EXPLAIN 未调用；旧新源码一致，属于已载入 schema 的既有信任边界 |

私有夹具自动清理，未给当前配置库增加触发器、UDF、连接或 Skill。Client 验证不是 child stdio 或原生 Host 的触发器夹具验证。未改运行代码，因此未重跑前批 2196 项回归、构建与 340 次安装调用，不把旧结果当作已覆盖新 P2。

[SQLite EXPLAIN 说明](https://www.sqlite.org/lang_explain.html)明确 EXPLAIN 不取消准备期 authorizer；[触发器说明](https://sqlite.org/lang_createtrigger.html)允许 WHEN 使用合适事件的 NEW／OLD。begin 的具体合法形式由本批原生真值确认，不笼统推广到所有关键字。[authorizer 说明](https://www.sqlite.org/c3ref/set_authorizer.html)特别说明生成列回调时机；项目原有[安全范围](../../security/V3_8_SECURITY.md)和[设计约定](../../architecture/V3_8_2_SQL_SEMANTICS_ZH.md)已保留该限制。

## 复杂、完整的 Agent 任务

此前确实执行过[四类 12 次／36 轮任务](V3_8_2_VALIDATION_2026_10_16_ZH.md#重启后的完整任务与补修)，固定检查 11/12；随后 CTE 计数补修增加三次双轮销售任务，人工业务复核 2/3、严格数字检查 1/3。原失败及用量保留，属于各自源码，不能套用到后续触发器补修。上一批 69 次原生调用则是定点工具验收，没有新增完整模型任务。

本批在当前源码上另做三次 fresh GPT-6 Luna medium 试验，fork_context=false，每次两轮。任务及业务评分规则在开始前[冻结](v382_adjacent_audit_2026_10_17/real_tasks/plan.json)，初始用户提示与前批双轮销售任务相同；没有提供 SQL、数值真值或其他试验结果。业务涉及发现三张季度表、保留每条销售记录金额、跨季度去重、季度增长、地区占比、产品排名，再排除 east 重新计算与解释范围变化。每轮最多 12 次 MCP 尝试，不使用文件、shell、网络或其他数据库客户端。

| trial | 首轮完整复盘 | 第二轮排除 east | 结果与效率 |
| --- | --- | --- | --- |
| 1 | 720 条／331921.71／38 产品，季度、增长、地区和产品排名正确 | 548 条／253826.38／38 产品及新前三名正确 | 完成；3 次 MCP 返回，先 compact schema，再两轮各一个综合聚合 |
| 2 | 所有明确业务指标正确 | 新范围及不能沿用的指标解释正确 | 完成；9 次 MCP 返回，对三张同结构表逐一 describe 较低效 |
| 3 | 正确名称的 list_tables 在 Host 层不可调用，无业务结果 | 同子会话目录仍为空，未重算 | 完整任务失败；零 MCP 应用返回，原始错误及两个未完成轮次保留 |

**完整试验业务与固定检查均为 2/3，六轮中四轮完成。**成功试验全部查询结果未截断、没有跨连接或写入；不能只按 12 次实际 MCP 返回全部成功来宣称三次任务全通过。第三次原文自述“两次 MCP 尝试”，公开轨迹实际是一次 MCP 调用尝试加目录检查，统计采用公开轨迹。

第三次最初目录确实含正确 SQL 工具名，实际调用返回 `MCP tool \`sql-safety-executor-mcp/list_tables\` is not available to the model`，随后两次 SQL 工具目录为空。独立预检和另外两个子会话成功，不能证明本子会话正常；证据不足以细分初始化、时序或绑定原因，不能确认缓存根因。今后应在**实际待测试的子会话内**先做轻量真实 canary；不可调用仍计可用性失败，不能无限重开直到成功并丢弃失败。

[实际轨迹、评分与用量](v382_adjacent_audit_2026_10_17/real_tasks/summary.json)：12 次 MCP 应用返回、另 1 次 Host 层调用失败，21 次模型响应、7 次本地工具目录检查；输入 578822（其中缓存 534912）、输出 4354，活动时间合计 138.706 秒。独立预检另存，不计业务用量。共享 Host／服务与工具目录不同，不与旧批次作同条件成本比较，不把活动时间称为服务端延迟；记录不含隐藏推理或完整协议帧。

[独立真值前后](v382_adjacent_audit_2026_10_17/real_tasks/truth_after.json)的 75 项资源、七张 SQLite 授权表指纹及相关汇总不变。结果仅说明本次销售任务与实际工具环境，不替代新 P2 的私有夹具，也不覆盖其他 Host、实际写入、并发冲突或全部业务。

## 证据与后续

本批[摘要](v382_adjacent_audit_2026_10_17/verification.json)、[封存清单](v382_adjacent_audit_2026_10_17/manifest.json)保留初始失败、扩展矩阵、两种 Client、三次模型任务和脚本。前批已封存文件保持原字节，DRR-108 的此前限定关闭是历史检查点。

建议顺序：先修 WHEN／BEGIN 角色边界并复验同输入，再补有价值的名称／scope 用例；外层重复 CTE 作为独立功能改进；Host 子会话可用性与服务器语义分别调查。当前不建议把生成列的既有可信部署限制扩成新的隔离框架。本批不改提交草案中的已实现内容，也不建议在新 P2 修复前宣称 v3.8.2 最终验收已全部关闭。
