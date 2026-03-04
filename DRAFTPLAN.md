# Agent Skills 扩展方案草案

**日期：** 2026年2月26日  
**参考项目：** [ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (v2.0)  
**当前项目：** LLM Database Safety Gateway (v2.2)

---

## 背景

本文基于对 `ui-ux-pro-max-skill` 项目的深入分析，探讨以下两个问题：

1. **CSV vs Database**：该项目中的 CSV 数据组织形式是否是最佳实践？迁移到数据库是否更优？
2. **可执行脚本 + 文件的扩展模式**：本 MCP 项目能否借鉴该模式，通过类似方式扩展数据库写入/更新策略？

---

## 一、ui-ux-pro-max-skill 项目结构分析

### 1.1 数据架构

该项目以 CSV 文件作为知识库，通过 Python 脚本提供搜索和推理能力：

```
src/ui-ux-pro-max/
├── data/                          # 知识库 (CSV)
│   ├── styles.csv          (96KB, 67条, 22列)  ← 核心：UI 风格的完整参数
│   ├── products.csv         (30KB, 100条, 9列)  ← 产品类型→风格映射
│   ├── ui-reasoning.csv     (31KB, 100条, 10列) ← 推理引擎决策规则 (JSON嵌入)
│   ├── typography.csv       (32KB, 57条, 10列)  ← 字体配对
│   ├── colors.csv           (10KB, 96条, 7列)   ← 配色方案
│   ├── landing.csv          (14KB, 24条, 6列)   ← 着陆页模式
│   ├── ux-guidelines.csv    (19KB, 99条, 9列)   ← UX 最佳实践
│   ├── charts.csv           (8KB, 25条, 8列)    ← 图表类型
│   ├── icons.csv            (13KB)               ← 图标推荐
│   ├── react-performance.csv(15KB)               ← React 性能指南
│   ├── web-interface.csv    (7KB)                ← Web 界面指南
│   └── stacks/              (13个 CSV)           ← 技术栈特定指南
├── scripts/
│   ├── search.py            ← CLI 入口：被 Agent 调用
│   ├── core.py              ← BM25 搜索引擎
│   └── design_system.py     ← 推理引擎：多域搜索 + 规则匹配 + 聚合输出
└── templates/               ← 技能注入模板 (SKILL.md 等)
```

### 1.2 数据流和关系

```
用户查询 "beauty spa"
  │
  ▼
search.py (CLI 入口，被 Agent 直接调用)
  │
  ▼
design_system.py (推理引擎)
  ├── Step 1: 搜索 products.csv → 识别类别 "Beauty/Spa/Wellness Service"
  ├── Step 2: 查找 ui-reasoning.csv → 获取决策规则 + 风格优先级
  ├── Step 3: 并行多域搜索 (BM25)
  │   ├── styles.csv   (用风格优先级关键词增强查询)
  │   ├── colors.csv
  │   ├── typography.csv
  │   └── landing.csv
  ├── Step 4: 基于优先级选择最佳匹配
  └── Step 5: 聚合输出设计系统推荐
```

### 1.3 关键设计特点

| 特点 | 具体实现 |
|------|----------|
| **离线自包含** | 无外部依赖，纯 Python 标准库 |
| **BM25 文本搜索** | 自实现 BM25 算法 (~80行)，支持 TF-IDF 排名 |
| **多域搜索聚合** | 一次查询同时搜索 5 个领域，结合推理规则选择最佳结果 |
| **嵌入式决策规则** | `ui-reasoning.csv` 中 JSON 格式的条件规则 |
| **渐进式披露** | 通过 SKILL.md + 模板系统，按需暴露给不同 AI 平台 |
| **数据与逻辑分离** | CSV 纯数据，Python 纯逻辑，互不耦合 |

---

## 二、问题一：CSV vs 数据库

### 2.1 CSV 在该项目中的合理性

CSV 在 `ui-ux-pro-max-skill` 的场景下有其合理性：

| 优势 | 说明 |
|------|------|
| **零依赖** | 该项目定位为 Agent Skill（技能插件），需跨平台安装到用户项目中。CSV + 标准库意味着无需安装数据库 |
| **可审计/可 diff** | Git 对 CSV 友好，团队可直接 review 数据变更 |
| **数据量小** | 全部 CSV 总计约 270KB，完全可以常驻内存 |
| **只读场景** | 数据是预编辑的参考知识，运行时不修改 |
| **分发简单** | 通过 npm CLI 或 git clone 即可安装，无需数据库配置 |

### 2.2 CSV 的局限性

但 CSV 并非没有问题：

| 局限 | 具体表现 |
|------|----------|
| **数据关系表达弱** | products→styles→colors 的关联靠字符串匹配和 Python 代码硬编码（`_find_reasoning_rule` 做模糊匹配）|
| **查询能力有限** | BM25 只是文本相似度，无法做 `WHERE color_mood = 'Trust blue' AND severity = 'HIGH'` 这样的精确过滤 |
| **大字段不友好** | `styles.csv` 每行 22 列、很多列含大段文本（AI Prompt Keywords、CSS Keywords、Checklist），CSV 编辑困难，容易引入格式错误 |
| **扩展性差** | 目前 100 个 product 类型 × 67 个 style × 96 个 palette，交叉关联全靠搜索，无法做精确 JOIN |
| **嵌入 JSON 的反模式** | `ui-reasoning.csv` 中的 `Decision_Rules` 列嵌入了 JSON 字符串，这是 CSV 和关系数据混用的典型反模式 |
| **无全文索引** | BM25 每次搜索需要全量扫描 + 重建索引，数据量大了性能会下降 |

### 2.3 数据库方案分析

如果将这些数据放入数据库（通过本 MCP 服务访问），方案如下：

#### 数据库 Schema 设计

```sql
-- 核心实体表
CREATE TABLE styles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,               -- "Glassmorphism"
    type TEXT,                         -- "General" / "Landing Page" / "BI/Analytics"
    keywords TEXT,                     -- BM25 或 FTS 索引的基础
    primary_colors TEXT,
    effects_animation TEXT,
    best_for TEXT,
    do_not_use_for TEXT,
    performance TEXT,                  -- "⚡ Excellent"
    accessibility TEXT,                -- "✓ WCAG AAA"
    complexity TEXT,                   -- "Low" / "Medium" / "High"
    ai_prompt_keywords TEXT,
    css_keywords TEXT,
    implementation_checklist TEXT,
    design_system_variables TEXT
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    product_type TEXT NOT NULL,        -- "Beauty/Spa/Wellness Service"
    keywords TEXT,
    primary_style TEXT,                -- FK → styles.name
    secondary_styles TEXT,
    landing_page_pattern TEXT,
    dashboard_style TEXT,
    color_palette_focus TEXT,
    key_considerations TEXT
);

CREATE TABLE reasoning_rules (
    id INTEGER PRIMARY KEY,
    ui_category TEXT NOT NULL,         -- 与 products.product_type 关联
    recommended_pattern TEXT,
    style_priority TEXT,               -- "Soft UI Evolution + Neumorphism"
    color_mood TEXT,
    typography_mood TEXT,
    key_effects TEXT,
    anti_patterns TEXT,
    severity TEXT                      -- "HIGH" / "MEDIUM"
);

-- 将 JSON 决策规则拆分为独立表
CREATE TABLE decision_rules (
    id INTEGER PRIMARY KEY,
    reasoning_id INTEGER REFERENCES reasoning_rules(id),
    condition_key TEXT,                -- "must_have" / "if_luxury"
    condition_value TEXT               -- "booking-system" / "add-gold-accents"
);

CREATE TABLE colors (
    id INTEGER PRIMARY KEY,
    product_type TEXT,
    primary_hex TEXT,
    secondary_hex TEXT,
    cta_hex TEXT,
    background_hex TEXT,
    text_hex TEXT,
    notes TEXT
);

CREATE TABLE typography (
    id INTEGER PRIMARY KEY,
    pairing_name TEXT,
    category TEXT,
    heading_font TEXT,
    body_font TEXT,
    mood_keywords TEXT,
    best_for TEXT,
    google_fonts_url TEXT,
    css_import TEXT
);

-- SQLite FTS5 全文搜索（替代 BM25）
CREATE VIRTUAL TABLE styles_fts USING fts5(
    name, keywords, best_for, ai_prompt_keywords,
    content='styles', content_rowid='id'
);
```

#### 数据库的优势

```sql
-- 精确关联查询（CSV 做不到）
SELECT s.name, s.effects_animation, c.primary_hex, t.heading_font
FROM products p
JOIN reasoning_rules r ON r.ui_category = p.product_type
JOIN styles s ON s.name LIKE '%' || r.style_priority || '%'
JOIN colors c ON c.product_type = p.product_type
JOIN typography t ON t.mood_keywords LIKE '%' || r.typography_mood || '%'
WHERE p.product_type = 'Beauty/Spa/Wellness Service';

-- FTS5 全文搜索（内置 BM25 排名，替代自实现）
SELECT *, rank FROM styles_fts WHERE styles_fts MATCH 'glass modern premium'
ORDER BY rank;

-- 条件过滤（CSV 需要加载全部数据再逐行过滤）
SELECT * FROM reasoning_rules
WHERE severity = 'HIGH'
AND anti_patterns NOT LIKE '%AI purple%';

-- 聚合统计
SELECT type, COUNT(*) as count, 
       GROUP_CONCAT(name, ', ') as styles
FROM styles GROUP BY type;
```

### 2.4 结论：CSV 对该项目是合理选择，但数据库是更好的"下一步"

**CSV 的适用条件（该项目满足）：**
- Agent Skill 形态，需要零依赖安装
- 数据量小（< 1MB），只读
- 数据源相对稳定，人工维护
- 分发方式是文件拷贝

**数据库的适用条件（当以下情况出现时应迁移）：**
- 数据量增长（> 500条/表，或总量 > 5MB）
- 需要精确的关联查询（如跨表 JOIN）
- 需要运行时数据更新（用户反馈、A/B 测试结果）
- 需要支持多用户并发访问
- 需要复杂的过滤/排序/分页

**本 MCP 服务的价值**：如果 `ui-ux-pro-max-skill` 未来将数据迁移到 SQLite 数据库，本 MCP 服务可以：
1. 提供安全的只读 SQL 访问（现有功能）
2. 替代自实现的 BM25，利用 SQLite FTS5 实现更强的全文搜索
3. 通过 `describe_table()` 和 `get_full_schema()` 帮助 LLM 理解数据结构
4. 提供 `MAX_RESULT_ROWS` 等截断保护，防止大量数据溢出 Agent 上下文

---

## 三、问题二：可执行脚本 + 文件的扩展模式

### 3.1 ui-ux-pro-max-skill 的模式总结

该项目的核心架构模式可以概括为：

```
知识库 (CSV/文件) + 搜索/推理脚本 (Python) + 技能清单 (SKILL.md)
↓                   ↓                          ↓
数据层              逻辑层                      发现层
(静态、可审计)      (可执行、可测试)            (渐进式披露)
```

这个模式的精髓在于：
- **数据与逻辑分离**：知识库文件独立存储，脚本只负责检索和推理
- **CLI 接口**：`search.py` 作为统一入口，Agent 通过 `python3 search.py "<query>"` 调用
- **渐进式披露**：SKILL.md 告诉 Agent 何时及如何使用该工具，按需加载

### 3.2 映射到本 MCP 项目：SQL Skills 扩展方案

#### 核心思路

借鉴该模式，将本 MCP 服务从"通用安全网关"扩展为"可配置的数据库操作技能平台"：

```
CSV 文件 (知识库)  →  SQL 文件 (预定义查询模板)
Python 脚本 (搜索) →  Python 脚本 (安全执行器 + 校验器)
SKILL.md (发现)    →  SKILLS.md (渐进式技能披露)
```

#### 提议的目录结构

```
llm-sql-safety-executor-mcp/
├── mcp_sql_server.py              # 核心 MCP 服务（现有）
├── sql_safety_checker.py          # SQL 安全检查器（现有）
├── db_adapter.py                  # 数据库适配器（现有）
│
├── skills/                        # 🆕 技能扩展层
│   ├── SKILLS.md                  # 技能清单：描述所有可用技能（渐进式披露）
│   │
│   ├── queries/                   # 只读查询模板
│   │   ├── monthly_report.sql     # 预定义的安全查询
│   │   ├── user_stats.sql
│   │   ├── top_products.sql
│   │   └── _manifest.json         # 查询元数据（描述、参数、权限）
│   │
│   ├── mutations/                 # 受控的写操作
│   │   ├── update_order_status.py # 带验证的更新操作
│   │   ├── batch_import.py        # 批量导入（含事务 + 回滚）
│   │   ├── archive_records.py     # 归档操作
│   │   └── _manifest.json         # 操作元数据（风险等级、审批要求）
│   │
│   └── scripts/                   # 支撑脚本
│       ├── skill_loader.py        # 技能加载器（读取清单 + 注册工具）
│       ├── mutation_executor.py   # 安全的写操作执行器
│       └── validator.py           # 前置/后置校验逻辑
│
└── start_server.py                # 启动入口（支持加载 skills/）
```

#### 3.2.1 只读查询技能（SQL 文件 → 对应 CSV）

**SQL 文件示例** (`skills/queries/monthly_report.sql`)：

```sql
-- @name: monthly_sales_report
-- @description: 生成指定月份的销售汇总报告
-- @params: year (int), month (int)
-- @risk: LOW
-- @category: reporting

SELECT 
    DATE_FORMAT(order_date, '%Y-%m-%d') AS date,
    COUNT(*) AS order_count,
    SUM(total_amount) AS revenue,
    AVG(total_amount) AS avg_order_value
FROM orders
WHERE YEAR(order_date) = :year 
  AND MONTH(order_date) = :month
GROUP BY DATE_FORMAT(order_date, '%Y-%m-%d')
ORDER BY date;
```

**查询清单** (`skills/queries/_manifest.json`)：

```json
{
  "queries": [
    {
      "name": "monthly_sales_report",
      "file": "monthly_report.sql",
      "description": "生成指定月份的销售汇总报告",
      "params": {
        "year": {"type": "int", "required": true},
        "month": {"type": "int", "required": true, "min": 1, "max": 12}
      },
      "risk_level": "LOW",
      "category": "reporting",
      "allowed_roles": ["analyst", "admin"]
    }
  ]
}
```

**优势对比**：

| 方面 | 当前方式（LLM 生成 SQL） | Skills 方式（预定义模板） |
|------|--------------------------|--------------------------|
| 安全性 | 依赖安全检查器拦截 | SQL 预审计，参数化防注入 |
| 准确性 | LLM 可能生成低质量 SQL | DBA 预优化，索引友好 |
| 效率 | 需要 describe_table → 构思 → query | 直接调用，减少工具调用次数 |
| 一致性 | 每次生成可能不同 | 固定输出格式，可预测 |
| Token 消耗 | 高（需要上下文理解表结构） | 低（直接填参数执行） |

#### 3.2.2 受控写操作技能（Python 脚本 → 对应 CSV 的写入方式）

这是最关键的创新点。当前 MCP 服务只允许 SELECT，但实际业务中写操作不可避免。

**写操作脚本示例** (`skills/mutations/update_order_status.py`)：

```python
"""
@name: update_order_status
@description: 安全地更新订单状态
@risk: MEDIUM
@requires_confirmation: true
@audit_log: true
"""

from skills.scripts.mutation_executor import MutationBase, ValidationError

class UpdateOrderStatus(MutationBase):
    """受控的订单状态更新操作。"""
    
    # 允许的状态转换（状态机）
    VALID_TRANSITIONS = {
        'pending':    ['confirmed', 'cancelled'],
        'confirmed':  ['shipped', 'cancelled'],
        'shipped':    ['delivered', 'returned'],
        'delivered':  ['returned'],
    }
    
    def validate(self, order_id: int, new_status: str) -> dict:
        """前置验证：检查状态转换是否合法。"""
        # 1. 参数验证
        if new_status not in ['pending', 'confirmed', 'shipped', 
                               'delivered', 'cancelled', 'returned']:
            raise ValidationError(f"Invalid status: {new_status}")
        
        # 2. 查询当前状态（只读，安全）
        current = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :id", {"id": order_id}
        )
        if not current:
            raise ValidationError(f"Order {order_id} not found")
        
        current_status = current[0]['status']
        
        # 3. 检查状态转换合法性
        allowed = self.VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ValidationError(
                f"Cannot transition from '{current_status}' to '{new_status}'. "
                f"Allowed: {allowed}"
            )
        
        return {
            "order_id": order_id,
            "current_status": current_status,
            "new_status": new_status,
            "preview": f"UPDATE orders SET status='{new_status}' WHERE id={order_id}"
        }
    
    def execute(self, order_id: int, new_status: str) -> dict:
        """执行更新（事务内）。"""
        result = self.adapter.execute(
            "UPDATE orders SET status = :status, updated_at = NOW() "
            "WHERE id = :id AND status = :expected_status",
            {
                "id": order_id, 
                "status": new_status,
                "expected_status": self.validated_data['current_status']  # 乐观锁
            }
        )
        
        if result.rowcount == 0:
            raise ValidationError("Update failed: status may have changed concurrently")
        
        return {
            "success": True,
            "order_id": order_id,
            "old_status": self.validated_data['current_status'],
            "new_status": new_status,
            "message": f"Order {order_id} status updated to '{new_status}'"
        }
```

**写操作安全机制**：

```
Agent 请求 "将订单 #123 标记为已发货"
  │
  ▼
MCP Tool: execute_skill("update_order_status", {order_id: 123, new_status: "shipped"})
  │
  ├── 1. 加载技能脚本 (skill_loader.py)
  ├── 2. 前置验证 (validate)
  │   ├── 参数类型/范围检查
  │   ├── 查询当前状态（SELECT，安全）
  │   ├── 状态机检查（合法转换？）
  │   └── 返回预览（dry-run 结果）
  ├── 3. 确认步骤（如果 requires_confirmation = true）
  │   └── 返回预览给 Agent → Agent 决定是否继续
  ├── 4. 事务执行 (execute)
  │   ├── BEGIN TRANSACTION
  │   ├── 乐观锁 UPDATE（WHERE status = expected）
  │   ├── 验证 rowcount
  │   └── COMMIT 或 ROLLBACK
  └── 5. 审计日志
      └── 记录: who(agent), what(mutation), when, params, result
```

### 3.3 MCP 工具注册设计

技能通过动态注册成为 MCP 工具：

```python
# mcp_sql_server.py 扩展

# 加载并注册查询技能
if SKILLS_ENABLED:
    from skills.scripts.skill_loader import SkillLoader
    
    skill_loader = SkillLoader(skills_dir="skills/")
    
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Execute Pre-defined Query Skill",
            readOnlyHint=True,
            destructiveHint=False,
        )
    )
    async def execute_query_skill(
        skill_name: str, 
        params: dict, 
        ctx: Context
    ) -> dict:
        """执行预定义的安全查询技能。
        
        Args:
            skill_name: 技能名称（见 SKILLS.md）
            params: 查询参数
        """
        return await skill_loader.execute_query(skill_name, params)
    
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Execute Mutation Skill (Write)",
            readOnlyHint=False,
            destructiveHint=True,
        )
    )
    async def execute_mutation_skill(
        skill_name: str,
        params: dict,
        confirm: bool = False,
        ctx: Context
    ) -> dict:
        """执行受控的数据库写操作技能。
        
        第一次调用 (confirm=False): 返回预览和影响范围
        第二次调用 (confirm=True):  执行实际修改
        
        Args:
            skill_name: 操作名称
            params: 操作参数
            confirm: 是否确认执行（两阶段提交）
        """
        if not confirm:
            return await skill_loader.preview_mutation(skill_name, params)
        return await skill_loader.execute_mutation(skill_name, params)
```

### 3.4 渐进式披露：SKILLS.md

```markdown
# Available Skills

## Query Skills (Read-Only)
| Skill | Description | Params | Risk |
|-------|-------------|--------|------|
| monthly_sales_report | 月度销售汇总 | year, month | LOW |
| top_products | 热销商品排行 | limit, period | LOW |
| user_stats | 用户统计概览 | date_from, date_to | LOW |

## Mutation Skills (Write - Requires Confirmation)
| Skill | Description | Params | Risk | Confirmation |
|-------|-------------|--------|------|--------------|
| update_order_status | 更新订单状态 | order_id, new_status | MEDIUM | Required |
| batch_import | 批量数据导入 | file_path, table | HIGH | Required |
| archive_records | 归档历史数据 | table, before_date | HIGH | Required |

## Usage
- Query skills: `execute_query_skill("monthly_sales_report", {"year": 2026, "month": 1})`
- Mutation skills: First preview, then confirm
  1. `execute_mutation_skill("update_order_status", {"order_id": 123, "new_status": "shipped"}, confirm=false)`
  2. Review the preview result
  3. `execute_mutation_skill("update_order_status", {"order_id": 123, "new_status": "shipped"}, confirm=true)`
```

---

## 四、两个方向的关系

这两个方向实际上可以结合：

```
┌────────────────────────────────────────────────────────────────────┐
│                    LLM Database Safety Gateway                     │
│                       (MCP Service v3.0)                           │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────────────────┐    ┌───────────────────────────────────┐  │
│  │  Generic Tools       │    │  Skills Layer                    │  │
│  │  ────────────────    │    │  ──────────────                  │  │
│  │  query()             │    │  execute_query_skill()           │  │
│  │  list_tables()       │    │  execute_mutation_skill()        │  │
│  │  describe_table()    │    │                                  │  │
│  │  get_full_schema()   │    │  queries/*.sql  (只读模板)       │  │
│  │                      │    │  mutations/*.py (写操作+校验)    │  │
│  │  ← 通用探索          │    │  ← 特定场景优化                 │  │
│  └─────────────────────┘    └───────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Safety Layer (现有)                                         │  │
│  │  SQL Validation | Allowlist | Truncation | Timeout           │  │
│  │  + Mutation Validation | State Machine | Audit Log (新增)    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Database Adapter Layer (现有)                               │  │
│  │  MySQL | SQLite | (future: PostgreSQL | NoSQL)               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**场景示例**：一个 UI/UX 设计 Agent 的工作流：

1. Agent 连接本 MCP 服务，后端数据库中存储了 ui-ux-pro-max 的设计系统数据
2. Agent 阅读 `SKILLS.md`，发现 `design_system_search` 查询技能
3. Agent 调用 `execute_query_skill("design_system_search", {"query": "beauty spa"})` 
4. MCP 服务执行预定义的 FTS5 搜索 SQL，返回匹配的风格+配色+字体组合
5. 如果需要添加新的设计数据，Agent 调用 `execute_mutation_skill("add_style", {...}, confirm=false)` 预览
6. 确认后执行写入

这样既利用了数据库的查询能力（问题一），又通过技能系统提供了安全的写操作扩展（问题二）。

---

## 五、实施路线建议

### Phase 1: 只读查询技能 (低风险，快速价值)
- [ ] 设计 `skills/queries/` 结构和 `_manifest.json` Schema
- [ ] 实现 `skill_loader.py`（加载 + 参数验证 + 执行）
- [ ] 注册 `execute_query_skill` MCP 工具
- [ ] 编写 `SKILLS.md` 模板
- [ ] 测试：预定义查询 vs LLM 生成查询的对比

### Phase 2: 受控写操作技能 (中风险，核心价值)
- [ ] 设计 `MutationBase` 基类（validate → preview → execute 三阶段）
- [ ] 实现事务管理 + 乐观锁
- [ ] 实现审计日志
- [ ] 注册 `execute_mutation_skill` MCP 工具（两阶段确认）
- [ ] 编写示例 mutation 脚本

### Phase 3: 外部数据迁移支持 (低风险，生态价值) 
- [ ] 提供 CSV → SQLite 迁移工具
- [ ] 支持 FTS5 全文搜索索引自动创建
- [ ] 为 ui-ux-pro-max-skill 等项目提供数据库后端方案的示例

---

## 六、注意事项

1. **安全优先**：写操作技能必须经过严格测试。两阶段确认、乐观锁、审计日志是底线。
2. **向后兼容**：技能系统应是可选的 (`ENABLE_SKILLS=0/1`)，不影响现有工具。
3. **防止工具爆炸**：技能不应暴露为独立 MCP 工具，而是通过 `execute_query_skill` / `execute_mutation_skill` 两个统一入口访问。这符合 OpenAI 的最佳实践——"保持工具数量少以提高准确性"。
4. **渐进式披露**：`SKILLS.md` 是关键，它让 Agent 按需发现技能，而非一次性加载所有上下文。
