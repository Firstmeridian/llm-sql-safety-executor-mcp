# v3.8.2 已提交版本最终复核与 COLLATE 限制（2026-10-18）

> 后续已获准[补修 IS／ESCAPE 操作数](V3_8_2_COLLATE_REPAIR_2026_10_18_ZH.md)，源码／安装通过，维护者重启后 25/25 项限定原生复验通过，DRR-109 按记录范围关闭。下文保留 e49cd0e 首次复核时的 P3 发现、开放状态和原始证据。

核验提交：`e49cd0eebb9bdf56ac6c114522af5b8743ba3bbf`。检查开始时工作区干净；75 项运行资源与最后 WHEN／安装验收闭包一致。未发现新的阻断问题；用户提出的 IS NULL COLLATE 问题确实存在，记录为独立的 **非阻断 P3 功能兼容回归 DRR-2026-109**，不重开已限定验收的 DRR-108。

本批不修改产品代码、依赖、配置、正式测试或数据库内容。新增内容是文档及本次检查证据，不是 COLLATE 功能修复；版本仍为 v3.8.2，无需重启。

## 已提交版本检查

| 项目 | 本次结果与范围 |
| --- | --- |
| 提交完整性 | 当前代码正是 e49cd0e；75 项磁盘运行资源匹配最后验收摘要，之前 487 项封存文件 SHA-256／字节数核验未变 |
| 全量回归 | **2275 passed／4 skipped／240 warnings，165.25 秒**；四项为可选 MySQL，警告为既有 MCP logging 弃用。不把通过计数当作覆盖此次新兼容限制 |
| 类型／提示 | Pyright 0 errors／0 warnings；安装提示资源与当前 TOML 路由契约通过 |
| 文档链接 | 提交内 22 篇变更 Markdown 的 757 个本地链接均有效，所需本地文件目标均已被提交；本批文档增量后，23 篇文档的 768 个本地链接均有效，git diff --check 通过 |
| 当前原生 MCP | 在已明确的 analytics_demo_sqlite 做八次只读常量查询，实际返回与当前源码吻合；保留成功、空集及两次解析拒绝 |
| 私有 Client 对照 | 相同 16 条 SQL，auto／legacy 各一次，每版 32 次：3323f9c 均成功；e49cd0e 有 12 次成功、20 次解析拒绝（十种写法各两模式） |
| 安装／业务历史 | 同源码安装 394 次、原生限定 57/57 及最新三次完整双轮 Luna 最终 3/3 沿用其原封存范围；本批没有重新运行这些安装／业务任务，不改写先前失败 |

完整回归包含本地子进程，类型检查需要现有依赖，按已有沙盒受限证据使用限定命令在沙盒外运行。无新依赖安装、Host 配置变更或服务重启。当前原生接口不暴露加载代码对象摘要或协商协议，仍不将磁盘摘要当作驻留逐对象证明。

## COLLATE：结果与根因

| SQL | 独立 SQLite 3.45.1 | 当前原生 MCP |
| --- | --- | --- |
| `SELECT 7 AS n WHERE NULL IS NULL COLLATE NOCASE;` | 返回 7 | sql_parse_failed |
| `SELECT 7 AS n WHERE (NULL IS NULL) COLLATE NOCASE;` | 返回 7 | 返回 7 |
| `SELECT 7 AS n WHERE NULL IS (NULL COLLATE NOCASE);` | 返回 7 | 返回 7 |
| `SELECT 7 AS n WHERE 0 IS NOT NULL COLLATE NOCASE;` | 返回 7 | sql_parse_failed |
| `SELECT 7 AS n WHERE NULL IS NULL;` | 返回 7 | 返回 7 |

直接调用固定版本 SQLGlot **30.22.0** 的 SQLite parser，同样在首例的 COLLATE token 抛 ParseError。其 `_parse_is()` 优先以 `_parse_null()` 消费 NULL，未按此 SQLite 写法继续吸收右侧 COLLATE 表达式；项目共享分析将失败转换为 sql_parse_failed，尚未进入 SQLite authorizer。不能把这个失败归为权限、触发器 CTE 或未刷新的驻留状态。

定点矩阵还确认 IS NOT NULL、BINARY／RTRIM 及 SELECT 投影中的相邻写法；十种合法写法均被当前解析层拒绝。原 3323f9c 的同输入 32 次 Client 调用成功，表明这是接入新解析链路后的功能兼容回归。旧源码从该提交解包，先匹配 70 项资源摘要，再在全新子进程断言实际导入路径；两版使用当前相同依赖，不能称为历史环境回放。原生 SQLite 真值、SQLGlot 诊断、包路径、版本和两模式公开应用结果全部保留。

这十种写法是刻意选择的定点矩阵，不代表真实任务的错误率。本批未观察到它扩大授权或执行写入；现有完整回归与先前已修复触发器八例的验收不因此失效。

## 恢复写法与语义边界

对用户给出的 NULL 例，以下写法已在原生 MCP 验证通过，并保留原式右侧 COLLATE 的结合位置：

```sql
SELECT 7 AS n WHERE NULL IS (NULL COLLATE NOCASE);
```

不能机械地给整个 IS 判断添加括号，作为所有 COLLATE 表达式的通用替代。当前原生与独立 SQLite 均验证：

```sql
SELECT 7 AS n WHERE 'A' IS 'a' COLLATE NOCASE;   -- 返回 7
SELECT 7 AS n WHERE ('A' IS 'a') COLLATE NOCASE; -- 返回空集
```

[SQLite 运算符说明](https://www.sqlite.org/lang_expr.html#operators_and_parse_affecting_attributes)将 COLLATE 列为高于 IS 的后缀运算符；移动括号会改变它修饰的表达式。这里的常量 NULL 正例相同，不能推导任意业务表达式等价。

## 优先级与建议

- **保留 P3、独立登记是合理的。** 问题有明确边界，存在同连接单次调用的恢复写法，当前没有授权漏查证据；DRR-108 的触发器／非执行型计划修复继续按其范围关闭。
- **值得后续单独修复。** 建议先补 IS／IS NOT、NULL／参数、COLLATE 优先级、投影／条件／CTE／Skill 及真实关系／受限调用对照，再验证小范围 SQLite 方言适配或对应上游版本修复。本批未验证其他 SQLGlot 版本，不承诺升级即可解决。
- 不用字符串正则自动补括号，不放宽完整性要求，不关闭 authorizer；继续执行原 SQL。具体实现应在上述语义对照通过后确定。

文档主体与 e49cd0e 一致。补充本 P3，并将初始验收／局部 CTE 报告的最新入口更新为当前结论；日期分段中的旧 sqlparse／authorizer 暂缓、旧模型成绩和 pending 检查点仍保留其历史语境。旧 487 项封存证据不改写。

本批[核验摘要](v382_final_review_2026_10_18/verification.json)及[封存清单](v382_final_review_2026_10_18/manifest.json)记录当前全量／类型／提示结果、八次原生结果和两版 Client 对照。文档增量属于 e49cd0e 之后，产品运行资源仍与该提交一致。
