## 计划：MCP Tool SQL Skills 扩展层

**概述**：在现有 LLM Database Safety Gateway MCP 服务上新增一个可选的技能扩展层，采用 `execute_query_skill` / `execute_mutation_skill` 两个统一入口工具，通过 `skills/` 目录中的 SKILL.md + SQL/Python 文件组织预定义操作。元数据格式对齐 Anthropic Agent Skills 开放规范（YAML frontmatter + Markdown body），实现渐进式披露。首批实施范围同时覆盖只读查询和基础写操作。

关键设计决策来源：
- **Anthropic Skills 规范**：SKILL.md 格式、渐进式披露 3 级、自由度匹配、可验证中间输出
- **Anthropic 最佳实践**：简洁性原则、一级深度引用、错误处理不推卸给 Agent、工作流检查清单
- **FastMCP 工具系统**：`ToolAnnotations` 区分读写、`ToolError` 安全错误报告、结构化输出
- **MCP Spec §7**：Validate all tool inputs; Implement proper access controls
- **Google Gemini**：强 schema 原则、重大后果操作需用户验证、有效工具集 10-20 个以内
- **Microsoft Azure**：Principle of Least Privilege; 写权限最小化——推荐读写分离账号

---

**Steps**

### 1. 目录结构设计（对齐 Agent Skills 规范）

在项目根目录下新增 `skills/` 目录，每个技能一个子目录，包含 `SKILL.md`：

```
skills/
├── SKILLS.md                          # 总览清单（顶层渐进式披露入口，自动生成）
├── SAFETY.md                          # 安全治理文档（顶层，非各 skill 的 references/）
│
├── monthly-sales-report/              # 查询技能示例
│   ├── SKILL.md                       # YAML frontmatter + 使用说明
│   └── query.sql                      # 预审计 SQL 模板
│
├── top-products/                      # 另一个查询技能
│   ├── SKILL.md
│   └── query.sql
│
├── update-order-status/               # 写操作技能示例
│   ├── SKILL.md                       # risk: medium, requires_confirmation: true
│   ├── mutation.py                    # validate → preview → execute 逻辑
│   └── references/
│       └── status-transitions.md      # 状态机文档（一级深度引用）
│
├── batch-import/                      # 另一个写操作技能
│   ├── SKILL.md
│   └── mutation.py
│
└── _lib/                              # 共享基础设施（不是 skill）
    ├── skill_loader.py                # 技能发现 + 加载 + 参数校验
    ├── mutation_base.py               # 写操作基类（validate→preview→execute）
    └── audit.py                       # 审计日志模块
```

对比 DRAFTPLAN.md 草案的变化：
- ~~`queries/` + `mutations/` 平铺~~ → 每个技能一个目录（对齐 Agent Skills 规范：`skill-name/SKILL.md`）
- ~~`_manifest.json`~~ → 每个 `SKILL.md` 的 YAML frontmatter 承载元数据
- ~~`scripts/`~~ → `_lib/`（避免与 Agent Skills 规范的 `scripts/` 含义冲突）
- 新增 `references/` 子目录用于一级深度引用（Anthropic 最佳实践：避免嵌套引用）
- 新增顶层 `SAFETY.md` 安全治理文档

### 2. SKILL.md 格式定义（对齐 Agent Skills YAML frontmatter 规范）

**查询技能 SKILL.md 示例** — `skills/monthly-sales-report/SKILL.md`：

```yaml
---
name: monthly-sales-report
version: "1.0"                  # 可选，用于审计溯源和变更管理
description: >                   # 功能概述（做什么）
  生成指定月份的销售汇总报告，包含日收入、订单量和平均订单额。
triggers:                        # 可选，触发条件关键词（何时用）
  - 月度销售
  - 月收入
  - 销售汇总
  - monthly sales
  - revenue report
type: query                    # query | mutation（Agent Skills 扩展字段）
risk: low                      # low | medium | high
# enabled: false               # 可选，默认 true；设为 false 则 skill_loader 跳过
params:
  year: {type: int, required: true, description: "年份 (如 2026)"}
  month: {type: int, required: true, min: 1, max: 12, description: "月份 (1-12)"}
category: reporting
---
```

Markdown body 部分保持 <500 行（Anthropic 建议），仅包含 Agent 需要的使用说明：

```markdown
## 使用方式
execute_query_skill("monthly-sales-report", {"year": 2026, "month": 1})

## 输出格式
返回每日汇总行：date, order_count, revenue, avg_order_value

## 注意事项
- 数据按日期升序排列
- revenue 和 avg_order_value 单位为数据库原始货币单位
```

**对应 query.sql 示例** — `skills/monthly-sales-report/query.sql`：

```sql
SELECT
    DATE(order_date) AS date,
    COUNT(*) AS order_count,
    SUM(amount) AS revenue,
    ROUND(AVG(amount), 2) AS avg_order_value
FROM orders
WHERE YEAR(order_date) = :year
  AND MONTH(order_date) = :month
GROUP BY DATE(order_date)
ORDER BY date ASC
```

命名参数 `:param_name` 对应 SQLAlchemy `text()` 参数化绑定语法（通过 `connection.execute(text(sql), params)` 传递）。

> 注：上述示例使用 `YEAR()` / `MONTH()` 为 MySQL 专属函数，SQLite 下需改用 `strftime('%Y', order_date)` 等。Skill SQL 模板由作者根据目标数据库类型编写，不保证跨数据库兼容。

**写操作技能 SKILL.md 示例** — `skills/update-order-status/SKILL.md`：

```yaml
---
name: update-order-status
version: "1.0"
description: >
  安全更新订单状态。支持状态机约束，防止非法转换。
triggers:
  - 更新订单状态
  - 发货
  - 确认订单
  - 取消订单
  - update order status
  - ship order
type: mutation
risk: medium
requires_confirmation: true    # 两阶段确认
idempotent: false              # 可选，默认 false；通过 list_skills() 和执行结果 dict 传达
params:
  order_id: {type: int, required: true}
  new_status: {type: str, required: true, enum: [pending, confirmed, shipped, delivered, cancelled, returned]}
category: order-management
related_skills:                # 可选，发现提示——Agent 可能还需要这些 skill
  - monthly-sales-report       # 更新后可能需要查看报表
---
```

Body 引用状态转换文档（一级深度）：

```markdown
## 工作流
1. 调用 confirm=false → 返回当前状态和预览
2. 检查预览结果是否符合预期
3. 调用 confirm=true → 执行更新

## 状态转换规则
详见 [status-transitions.md](references/status-transitions.md)

## 安全机制
- 乐观锁：WHERE status = expected_status
- 事务：BEGIN → UPDATE → 验证 rowcount → COMMIT/ROLLBACK
- 审计日志：自动记录每次操作
```

### 3. 在 `db_adapter.py` 中扩展 `execute()` 并新增 `execute_write()`

#### 3a. 为 `execute()` 添加可选 `params` 参数

Query Skill 需要参数化只读查询（如 `query.sql` 中的 `:year` / `:month` 命名参数），但现有 `execute(sql, timeout)` 不接受 params。内部 `connection.execute(text(sql))` 无法传递绑定参数——如果改为先字符串替换再传入，就不是参数化查询，违反 SAFETY.md 第 2 条的防注入原则。

为现有 `execute()` 新增可选参数 `params: dict | None = None`：

```python
@abstractmethod
def execute(self, sql: str, timeout: int | None = None, params: dict | None = None) -> list | str:
```

实现修改（MySQLAdapter / SQLiteAdapter 均同理）：

```python
# 修改前
result = connection.execute(text(sql))

# 修改后
if params:
    result = connection.execute(text(sql), params)
else:
    result = connection.execute(text(sql))
```

**向后兼容性**：`params` 默认 `None`，所有现有调用方（`execute(sql)` / `execute(sql, timeout=30)`）行为完全不变。这是新增可选参数，不是修改签名——零兼容性风险。

`execute_sql()` 包装函数（`sql_safety_checker.py`）无需修改——它仅服务于现有工具（`query()`、`sample()`、`get_table_summary()`）的自由 SQL 路径，不用于 Skill 执行。

#### 3b. 新增 `execute_write()` 抽象方法

mutation 技能需要写入能力，新增独立的写入方法。

```python
@abstractmethod
def execute_write(self, sql: str, params: dict, timeout: int | None = None) -> dict:
    """
    Execute a parameterized write SQL statement within a transaction.

    Args:
        sql: SQL with named parameters (e.g., "UPDATE t SET col=:val WHERE id=:id")
        params: Parameter dict for binding
        timeout: Optional timeout override in seconds

    Returns:
        {"success": True, "rowcount": N} on success

    Raises:
        SQLAlchemyError (or subclass) on failure — not caught here,
        propagates to caller (MutationBase) for error sanitization.
    """
    pass
```

实现要点：
- 使用 SQLAlchemy `text(sql)` + `connection.execute(text_obj, params)` 参数化查询（**防 SQL 注入**）
- 在 `connection.begin()` 事务块内执行，成功自动 commit，异常自动 rollback
- 返回 `dict` 格式（与 MCP 工具返回的 dict 惯例统一，避免 `isinstance(result, str)` 判断）——仅成功路径
- **失败时不捕获异常**，让 `SQLAlchemyError` 等自然传播至调用方（`MutationBase`）处理（参见 Step 5 错误处理链路）
- `MySQLAdapter`：复用现有 `MAX_EXECUTION_TIME` 超时机制
- `SQLiteAdapter`：复用现有 `set_progress_handler` 超时机制

**读写分离**：`execute()` 服务于只读查询（Query Skill + 现有 `query()` 工具），`execute_write()` 服务于写操作（Mutation Skill）。两者分离保持职责清晰：`execute()` 不开启显式事务（SQLAlchemy autobegin + 只读），`execute_write()` 使用 `connection.begin()` 显式事务（写入需要 commit/rollback）。

**v1.0 事务粒度**：每次 `execute_write()` 调用 = 单条 SQL + 显式事务（`with connection.begin():` 块，成功时自动 commit，异常时自动 rollback）。需要原子性的多步操作时，应使用单条 SQL 实现（如 CTE + UPDATE、`INSERT...ON DUPLICATE KEY UPDATE`），而非多次调用 `execute_write()`。跨 skill 的编排由 Agent 完成，不保证原子性。

**前置条件**：现有 `_handle_error()` 签名不一致（`MySQLAdapter._handle_error(e, timeout)` vs `SQLiteAdapter._handle_error(e)`），需先统一为 `_handle_error(self, e: Exception, timeout: int | None = None) -> str`，SQLiteAdapter 实现忽略 timeout 参数即可。同时修复超时消息分支：当 `timeout=None` 时不应输出 `"(Nones limit)"`，应改为 `f"({timeout}s limit)" if timeout else ""`，或统一用 `"Error: Query timeout exceeded"` 无后缀。此修复应在 Skills 扩展实现之前完成。

### 4. `_lib/skill_loader.py` — 技能发现与加载

核心职责：
- **发现**：扫描 `skills/` 目录，读取每个 `SKILL.md` 的 YAML frontmatter（~100 tokens/技能）；对 `type: query` 的技能同时读取 `query.sql` 并执行 `is_sql_safe()` 校验（启动时纵深防御），不通过则跳过该 skill 并 log error
- **过滤**：跳过 `enabled: false` 的技能（不出现在 `list_skills()` 输出中）
- **加载**：按需解析 SKILL.md body + `query.sql` 或导入 `mutation.py`
- **校验**：基于 frontmatter 中的 `params` schema 验证调用参数（类型、范围、enum）
- **关联验证**：对 `related_skills` 引用的 skill 名称做 warning-only 验证（存在则通过，不存在则 log warning，不硬失败）
- **注册**：生成动态 `SKILLS.md` 总览清单

关键设计点（来自 Anthropic 最佳实践）：
- 使用 `---` 分隔符分割提取 YAML frontmatter（`parts = content.split('---', 2)`，`len(parts) < 3` 时报错），然后 `yaml.safe_load(parts[1])`，无需 `python-frontmatter` 等第三方库
- SQL 模板使用命名参数 (`:param_name`)，由 loader 做参数绑定，**防注入**
- 错误处理"不推卸"：loader 内部捕获并给出具体错误信息，不让 Agent 猜测
- `enabled` 字段默认 `true`；缺省等同于 `enabled: true`（向后兼容现有 SKILL.md）

#### Skill 名称输入验证

`skill_loader.py` 在接收 `skill_name` 参数时必须校验，防止路径遍历攻击：

- **格式校验**：仅允许 `^[a-z0-9][a-z0-9-]*$`（小写+数字+连字符，对齐 Agent Skills 规范的 name 约束）
- **路径安全**：不含路径分隔符（`/`、`\`、`..`），不合法名称立即返回错误，不尝试文件系统操作
- 校验在任何文件 I/O 之前执行

对应测试：`test_path_traversal_rejected` — `../../../etc/passwd` 被拒绝。

#### 公开 API 定义

```python
@dataclass
class SkillMetadata:
    name: str
    type: Literal["query", "mutation"]
    risk: Literal["low", "medium", "high"]
    description: str
    params: dict[str, dict] = field(default_factory=dict)  # 允许无参数技能
    triggers: list[str] = field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True
    idempotent: bool = False
    requires_confirmation: bool = False
    category: str | None = None
    related_skills: list[str] = field(default_factory=list)
    # ── 内部字段（discover() 填充，非 YAML frontmatter 来源）──
    _sql_template: str | None = field(default=None, repr=False)  # query skill 的缓存 SQL
    tables: list[str] = field(default_factory=list)               # 自动提取的涉及表名
```

```python
# ── 启动时 ──
def discover(skills_dir: Path) -> dict[str, SkillMetadata]
    """扫描 skills/ 目录，解析所有 SKILL.md frontmatter，返回已启用技能的元数据。
    对 type: query 的技能同时读取 query.sql 并执行 is_sql_safe() 校验（启动时纵深防御），
    不通过则跳过该 skill 并 log error——确保只有安全模板才能注册。
    通过校验的 SQL 模板缓存到 SkillMetadata._sql_template，同时提取涉及的表名
    填充 SkillMetadata.tables（供 generate_skills_md() 列出，见 SAFETY.md #14）。"""

def generate_skills_md(skills: dict[str, SkillMetadata], output_path: Path) -> None
    """生成 skills/SKILLS.md 静态总览文件。
    从 SkillMetadata.tables 读取各 skill 涉及的表名并列出，供 code reviewer 审查。"""

# ── 运行时 ──
def validate_name(skill_name: str) -> None
    """正则校验 skill_name，不合法时 raises ValueError。"""

def load_query(skill_name: str) -> tuple[str, dict]
    """返回 (sql_template, param_schema)，找不到时 raises FileNotFoundError。
    内部校验 metadata.type == 'query'，类型不匹配时 raises TypeError。
    SQL 模板从 SkillMetadata._sql_template 缓存读取（discover() 启动时已校验并缓存），
    不再从磁盘重新读取——消除 TOCTOU 风险（启动后文件篡改不影响运行时）。"""

def load_mutation(skill_name: str, adapter: DatabaseAdapter, logger: AuditLogger) -> MutationBase
    """动态导入 mutation.py 并实例化，找不到时 raises FileNotFoundError。
    内部校验 metadata.type == 'mutation'，类型不匹配时 raises TypeError。"""

def validate_params(params: dict, schema: dict) -> dict
    """校验参数类型/范围/必填，返回校验后的 params，不合法时 raises TypeError/ValueError。"""
```

`list_skills()` 的返回值结构由 `SkillMetadata` 自动确定。

### 5. `_lib/mutation_base.py` — 写操作基类

对应 DRAFTPLAN.md 草案的 `MutationBase`，增强以下来自 Anthropic 研究的模式：

- **可验证中间输出**（Anthropic "plan-validate-execute" pattern）：
  - `validate(params)` → 前置检查，返回结构化验证结果
  - `preview(params)` → dry-run，生成将执行的 SQL 预览和影响范围
  - `execute(params)` → 事务内执行，带乐观锁
- **自由度匹配**（Anthropic "degrees of freedom"）：
  - 写操作 = **低自由度**（"Run exactly this script"），mutation.py 精确定义每一步
  - 查询操作 = **中自由度**（有模板但参数可变）
- **错误处理**：`MutationBase` 基类在内部 `try/except` 中统一捕获 `adapter.execute_write()` 抛出的异常，通过 `adapter._handle_error(e)` 脱敏后 raise FastMCP `ToolError`，避免泄露连接串/表结构等内部信息。FastMCP 的 `ToolError` 继承 `FastMCPError`，被服务器原样透传（不受 `mask_error_details` 遮蔽）。

完整错误处理链路：

```
adapter.execute_write(sql, params)
  ├─ 成功 → return {"success": True, "rowcount": N}
  └─ 失败 → SQLAlchemyError 自然传播

MutationBase.execute(params)           # 基类模板方法
  ├─ try:
  │    result = self.adapter.execute_write(sql, params)
  │    self.logger.log(mode="execute", result=result, ...)
  │    return result
  └─ except Exception as e:
       sanitized = self.adapter._handle_error(e)
       raise ToolError(sanitized)       # → FastMCP 原样透传至 Client
```

#### Adapter 注入与写入链路

```python
class MutationBase:
    def __init__(self, adapter: DatabaseAdapter, logger: AuditLogger):
        self.adapter = adapter
        self.logger = logger

    @abstractmethod
    def validate(self, params: dict) -> dict: ...

    @abstractmethod
    def preview(self, params: dict) -> dict: ...

    @abstractmethod
    def execute(self, params: dict) -> dict: ...
```

#### `validate()` / `preview()` / `execute()` 返回值结构

```python
# validate() 成功
{"valid": True}
# validate() 失败
{"valid": False, "errors": ["order_id 42 不存在", "..."]}

# preview()
{
    "sql": "UPDATE orders SET status=:new WHERE id=:id AND status=:expected",
    "bound_params": {"new": "shipped", "id": 42, "expected": "confirmed"},
    "affected_rows_estimate": 1,          # 可选
    "warnings": ["状态将从 confirmed 变为 shipped"],  # 可选
    "requires_confirmation": True          # 明确提示 Agent 下一步需 confirm=True
}

# execute()
{"success": True, "rowcount": 1}
```

完整写入链路：

```
execute_mutation_skill() Tool
  → skill_loader.load_mutation(skill_name)
    → 实例化 mutation.py 子类，注入 adapter + logger
      → 子类 execute() 内调用 self.adapter.execute_write(sql, params)
        → 事务提交 / 异常回滚
```

参数一致性说明：`validate/preview/execute` 三方法均接收 `params: dict`。在两阶段调用模式下（`confirm=false` → `confirm=true`），这是两次独立 MCP Tool 调用，参数一致性由 Agent 保证，乐观锁（`WHERE status = expected_status`）作为最终防线。

#### mutation.py 执行约束

`mutation_base.py` 的 `execute()` 仅允许调用 `self.adapter.execute_write()`，禁止直接文件 I/O、网络请求或子进程调用。code review 时需检查 mutation.py 是否仅使用基类提供的 API。

#### mutation.py 动态导入约定

每个 `mutation.py` 必须导出一个名为 `Mutation` 的类（继承 `MutationBase`）。`skill_loader.load_mutation()` 使用 `importlib.util` 动态导入：

```python
spec = importlib.util.spec_from_file_location(
    f"skills.{skill_name}.mutation",
    skills_dir / skill_name / "mutation.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
mutation_class = module.Mutation  # 约定类名
```

缺少 `Mutation` 类时报错：`"mutation.py must export a class named 'Mutation' (subclass of MutationBase)"`。

`spec.loader.exec_module(module)` 失败时（`ImportError` / `SyntaxError` / `ModuleNotFoundError`）raises 原异常，附带 skill 名和文件路径上下文，便于调试。

#### 可选：SQL-only mutation 轻量替代

对于仅需简单 INSERT/UPDATE 的技能（如 `log-query-feedback`），强制编写 mutation.py 类会引入不必要的样板代码。`skill_loader.py` 可同时支持两种 mutation 载体：

- **mutation.py**：复杂写操作（含业务校验、乐观锁、多步事务），使用 `MutationBase` 子类
- **mutation.sql**：简单写操作，参数化 SQL 模板，参数校验由 SKILL.md frontmatter schema 承担

加载优先级：`mutation.py` > `mutation.sql`（同时存在时以 Python 为准）。

> 此项为可选优化，可在 PoC 验证核心流程后再实现。简单 INSERT 场景下 SQL-only 约 20 行 vs mutation.py 约 50 行，减少 ~60% 代码量，符合自由度匹配原则——简单操作不需要 Python 级自由度。

### 6. MCP 工具注册（统一入口方案）

在 `mcp_sql_server.py` 中注册新工具，受 `ENABLE_SKILLS` 环境变量控制：

- `list_skills()` — `readOnlyHint=True`，返回所有已启用技能的 name + description + triggers + type + risk（渐进式披露第 1 级：仅元数据）。`triggers` 提供关键词级匹配提示，帮助 Agent 快速判断何时应选用此 skill；`description` 保持功能概述角色不变。仅返回 `enabled` 不为 `false` 的技能。
- `execute_query_skill(skill_name, params)` — `readOnlyHint=True, destructiveHint=False, idempotentHint=True`。绕过 `is_sql_safe()` 安全检查和 `ALLOWED_TABLES` 表名检查（模板 SQL 已预审计，安全保证来源于 code review）。执行路径：`skill_loader.load_query()` 获取 SQL 模板 → `validate_params()` 校验参数 → `adapter.execute(sql, params=validated_params)` 参数化只读执行（利用 Step 3a 新增的可选 `params` 参数）。复用 `_serialize_result()` + `_truncate_result()` 保持与现有 `query()` 一致的返回格式和 Token 控制。返回结构与 `query()` 相同（`success/data/row_count/truncated/...`），额外加 `"skill_name": str` 字段。错误处理：`validate_name()` / `load_query()` / `validate_params()` 抛出的异常统一捕获并以 `ToolError` 返回，与 mutation skill 错误处理模式一致。
- `execute_mutation_skill(skill_name, params, confirm=False)` — `readOnlyHint=False, destructiveHint=True, idempotentHint=False`（保守值，因为统一入口工具的 ToolAnnotations 在注册时固定，无法按 skill 动态变化）。各 skill 的 `idempotent` 信息通过 `list_skills()` 返回值和执行结果 dict 中的 `"idempotent": bool` 字段传达，供 Agent/Client 自行判断。
  - 受 `SKILLS_ALLOW_MUTATIONS` 二次开关控制，默认不注册

工具总数从当前 5-7 个增至 7-10 个（取决于是否启用 mutation 工具），仍在 Google Gemini 建议的 10-20 个合理范围内（避免“工具爆炸”）。

### 7. `_lib/audit.py` — 审计日志

所有 mutation 操作自动记录：
- who: Agent 标识（`ctx.client_id or os.getenv("AGENT_ID", "unknown")`，优先使用 MCP 协议的 client identity，未提供时回退至环境变量）
- what: skill_name + params + mode（preview/execute）
- when: 时间戳
- result: success/failure + 影响行数
- 存储：追加到 `skills/_audit.jsonl`（简单实现）或数据库表（生产环境）
- 并发安全：stdio 模式下单客户端无并发风险；SSE 多客户端模式下需使用 `threading.Lock` 或 `fcntl.flock()` 文件锁防止 JSON 行损坏

### 8. 顶层 `SKILLS.md` 自动生成

`skill_loader.py` 在启动时扫描所有 `SKILL.md` frontmatter，自动生成 `skills/SKILLS.md` 静态总览文件，供人类开发者 code review 和部署审查使用。`enabled: false` 的技能不出现在总览中。发现和工具注册均在**模块导入时同步执行**（与现有 `ENABLE_SCHEMA_TOOLS` / `ENABLE_TABLE_SUMMARY` 条件注册模式一致），不在 `lifespan()` 异步上下文中执行。`discover()` 做文件 I/O + YAML 解析 + query.sql 安全校验（`is_sql_safe()`），不涉及数据库连接，耗时可忽略。

**已知限制**：现有 `start_server.py` 的 `validate_environment()` 硬编码检查 MySQL 环境变量（`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_NAME`），当 `DB_TYPE=sqlite` 时会误报失败。此为既有 bug，应在 Skills 实现前修复：按 `DB_TYPE` 决定检查哪些变量。注意实际执行顺序为：`from mcp_sql_server import mcp`（模块级 import，触发全部工具注册）→ `load_dotenv()` → `main()` → `validate_environment()` → `mcp.run()`——工具注册发生在 `validate_environment()` **之前**。

**Agent 的运行时入口是 Step 6 中的 `list_skills()` MCP 工具**（渐进式披露第 1 级），而非直接读取此文件。渐进式披露流程：`list_skills()` 返回元数据（第 1 级）→ Agent 按需加载完整 SKILL.md（第 2 级）→ SQL/Python 文件（第 3 级）。

### 9. `skills/SAFETY.md` — 安全治理文档

在 `skills/` 顶层新增安全策略文档，内容涵盖：

1. **模板/脚本即白名单**：只执行 `skills/` 目录下预定义的 query.sql / mutation.py，无自由 SQL 输入
2. **参数化查询**：所有参数通过 SQLAlchemy `text()` + 参数 dict 绑定（`connection.execute(text(sql), params)`），防止 SQL 注入
3. **dry-run 默认**：`confirm=False` 默认行为，Agent 必须先预览再确认
4. **双层开关**：`ENABLE_SKILLS` + `SKILLS_ALLOW_MUTATIONS`，默认关闭时 Tool 不注册
5. **超时保护**：继承 `db_adapter.py` 的 `QUERY_TIMEOUT_SECONDS`
6. **幂等性**：mutation 作者应使用 `INSERT OR IGNORE` / `ON DUPLICATE KEY UPDATE` / 乐观锁等幂等写入模式，防止 Agent 重试导致重复写入
7. **脚本信任边界**：`skills/` 下的文件与源代码处于同一信任边界，变更应通过 code review；`skill_loader.py` 只从固定路径加载，不支持 `..` 遍历或动态注册；生产环境建议 skills 目录设为只读
8. **推荐的最小权限部署实践**：生产环境建议使用独立数据库账号，仅对 skill 涉及的表有 INSERT/UPDATE 权限；SQLite 场景下建议写入数据库文件与主数据库分离
9. **confirm 令牌**：当前不实现服务端令牌机制，依赖 MCP Client 的 `destructiveHint` 确认 UI；如未来暴露给不信任调用者，应添加 confirmation token（`hash(skill_name+params+timestamp)` + 过期时间）
10. **审计日志**：mutation 操作通过 `audit.py` 记录到 JSONL 文件，内容包含 skill_name、params、mode、result、时间戳
11. **mutation.py 执行约束**：`mutation_base.py` 的 `execute()` 仅允许调用 `self.adapter.execute_write()`，禁止直接文件 I/O、网络请求或子进程调用；code review 时需检查 mutation.py 是否仅使用基类提供的 API
12. **错误脱敏**：`mutation_base.py` 统一捕获异常，通过 `adapter._handle_error()` 脱敏后以 `ToolError` 返回，避免泄露连接串/表结构等内部信息
13. **速率限制**：当前依赖 MCP 传输层（stdio/SSE）的隐式限流；如未来独立暴露 HTTP 端口或面向不信任调用者，应添加 per-skill 或全局 rate limiting（对应 MCP Spec §7 "Rate limit tool invocations" 要求）
14. **ALLOWED_TABLES 交互**：Skill SQL 模板不经过运行时 `ALLOWED_TABLES` 检查，安全保证来源于 code review（模板即白名单，与源代码处于同一信任边界）；`generate_skills_md()` 在生成 SKILLS.md 时自动提取并列出每个 skill 涉及的表名，供 code reviewer 审查
15. **SKILLS_DIR 路径约束**：`SKILLS_DIR` 环境变量可配置，但 `discover()` 应校验其解析后的绝对路径位于项目根目录内（`resolved_path.is_relative_to(project_root)`），防止通过 `.env` 文件投毒将恶意 `mutation.py` 注入外部路径
16. **读写方法约定**：`execute()` 与 `execute_write()` 的读写分离为约定性质（技术上 `execute()` 也能执行写 SQL，`execute_write()` 也能执行读 SQL）；安全保证来源于调用方通约（`execute_query_skill` 调 `execute()`，`execute_mutation_skill` 调 `execute_write()`）和 code review，而非运行时强制；SQLAlchemy 2.0 的隐式事务提供额外安全网——`execute()` 路径无 `commit()` 则写操作不会持久化

### 10. 环境变量与配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_SKILLS` | `0` | 是否启用技能扩展层 |
| `SKILLS_DIR` | `skills/` | 技能目录路径 |
| `SKILLS_ALLOW_MUTATIONS` | `0` | 是否允许写操作技能（二次开关） |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | 审计日志路径 |

向后兼容：`ENABLE_SKILLS=0` 时完全不加载技能层，现有工具行为不变。

### 11. 依赖管理

新增依赖：`pyyaml`（解析 SKILL.md frontmatter）。添加到 `requirements.txt`。
同时明确 `SQLAlchemy>=2.0` 版本约束——SQLAlchemy 2.0 的 `connection.execute()` 默认在隐式事务中运行（无 autocommit），确保 `execute()` 只读路径中意外的写 SQL 不会持久化（无 `commit()` 则自动 rollback）。SQLAlchemy 1.x 的 autocommit 行为可能让写操作意外生效。
不引入其他外部依赖，保持项目轻量。

### 12. 测试

在 `tests/` 下新增：
- `test_skill_loader.py` — 技能发现、frontmatter 解析、参数校验、名称验证
- `test_query_skills.py` — SQL 模板加载和参数绑定（用 SQLite 内存库）
- `test_mutation_skills.py` — validate→preview→execute 流程、乐观锁、回滚
- `test_audit.py` — 审计日志记录

#### 具体测试用例清单

| # | 测试项 | 覆盖范围 |
|---|--------|----------|
| 1 | `test_execute_write_basic` | `adapter.execute_write(sql, params)` 参数绑定与写入 |
| 2 | `test_execute_write_injection_safe` | params 含 `'; DROP TABLE --` 不注入 |
| 3 | `test_load_skill_success` | SKILL.md frontmatter 解析 + query.sql / mutation.py 加载 |
| 4 | `test_load_skill_not_found` | 不存在的 skill 返回错误 |
| 5 | `test_path_traversal_rejected` | `../../../etc/passwd` 被拒绝 |
| 6 | `test_validate_params_valid` | 合法参数通过 frontmatter schema 校验 |
| 7 | `test_validate_params_invalid` | 类型错误 / 超范围 / 缺必填 → 拒绝 |
| 8 | `test_dry_run_no_write` | `confirm=False` 返回预览，数据库无变更 |
| 9 | `test_confirm_writes_data` | `confirm=True` 实际写入并验证 |
| 10 | `test_idempotent_write` | 同参数写入两次，幂等策略生效 |
| 11 | `test_skills_disabled` | `ENABLE_SKILLS=0` 时 Tool 不注册 |
| 12 | `test_mutations_disabled` | `ENABLE_SKILLS=1` + `SKILLS_ALLOW_MUTATIONS=0` 时仅 query skill 可用 |
| 13 | `test_audit_log_recorded` | mutation 操作后 JSONL 审计日志包含预期字段 |
| 14 | `test_skill_enabled_false_skipped` | `enabled: false` 的 skill 不出现在 list_skills() 输出中 |
| 15 | `test_triggers_in_list_skills` | list_skills() 输出包含 triggers 字段 |
| 16 | `test_related_skills_warning` | `related_skills` 引用不存在的 skill 时 log warning 但不报错 |
| 17 | `test_execute_write_exception_propagates` | `adapter.execute_write()` 失败时异常传播而非返回错误 dict |
| 18 | `test_execute_with_params_readonly` | `adapter.execute(sql, params={...})` 参数化只读查询返回正确结果 |
| 19 | `test_execute_without_params_unchanged` | `adapter.execute(sql)` 无 params 时行为与修改前完全一致 |
| 20 | `test_malformed_skill_md` | YAML 语法错误 / 缺失必填字段（`type`/`risk`）时报错并给出具体原因 |
| 21 | `test_mutation_missing_mutation_class` | `mutation.py` 缺少约定的 `Mutation` 类时报错 |
| 22 | `test_query_skill_type_mismatch` | 对 `type: mutation` 的 skill 调用 `execute_query_skill` 时 raises TypeError |
| 23 | `test_skills_dir_not_found` | `SKILLS_DIR` 指向不存在路径时的启动行为（无 skill 注册，不崩溃） |
| 24 | `test_validate_name_valid` | 合法名称（`my-skill-1`、`report2`）通过正则校验 |
| 25 | `test_generate_skills_md` | SKILLS.md 生成结果包含所有已启用 skill 的名称和描述 |
| 26 | `test_discover_rejects_unsafe_sql` | `discover()` 对含 `DROP TABLE` 的 query.sql 跳过该 skill 并 log error |
| 27 | `test_mutation_error_sanitization` | 异常经 `_handle_error()` 脱敏后通过 `ToolError` 返回，不泄露内部信息 |
| 28 | `test_load_query_returns_cached_sql` | `load_query()` 返回 `discover()` 缓存的 SQL 模板，不重新读盘 |
| 29 | `test_no_params_skill` | 无 `params` 字段的 SKILL.md 正常加载，`validate_params({}, {})` 通过 |
| 30 | `test_mutation_import_error` | `mutation.py` 中 `import` 失败时 raises 异常并包含 skill 名和文件路径 |
| 31 | `test_query_skill_error_returns_tool_error` | `execute_query_skill` 在 `validate_name`/`load_query`/`validate_params` 失败时返回 `ToolError` |

---

**Verification**

1. `pytest tests/test_skill_loader.py` — 验证技能发现和参数校验
2. `pytest tests/test_query_skills.py -v` — 验证查询技能端到端执行
3. `pytest tests/test_mutation_skills.py -v` — 验证写操作三阶段流程
4. 手动测试：`ENABLE_SKILLS=1 python start_server.py`，通过 MCP 客户端调用 `list_skills()` → `execute_query_skill()` → `execute_mutation_skill(confirm=false)` → `execute_mutation_skill(confirm=true)`
5. 向后兼容验证：`ENABLE_SKILLS=0 python start_server.py`，确认现有工具不受影响

---

**Decisions**

| 决策 | 选择 | 放弃 | 原因 |
|------|------|------|------|
| 架构 | 统一注册（2 个入口工具） | FastMCP mount() 子服务器 | 更简单，避免工具爆炸，用户选择 |
| 元数据 | SKILL.md (YAML frontmatter) | `_manifest.json` | 对齐 Anthropic Agent Skills 开放规范，Agent 可直接读取 |
| 技能目录 | 每技能一个子目录 | 按类型平铺 (queries/, mutations/) | 符合 Agent Skills 规范结构，利于独立维护和引用管理 |
| 参数校验 | SKILL.md frontmatter 内联 | 独立 JSON Schema 文件 | 单文件自描述，减少文件碎片 |
| 写操作安全 | 三阶段 (validate→preview→execute) + 乐观锁 + 审计 | 简单 confirm 开关 | Anthropic "可验证中间输出" + "低自由度" 最佳实践 |
| 审计存储 | JSONL 文件（MVP） | 数据库表 | 最小依赖起步，后续可迁移 |
| 写入接口 | 新增 `execute_write()` 方法 | — | 读写分离——只读查询与写操作各有独立方法，职责清晰 |
| 参数化只读查询 | 为 `execute()` 新增可选 `params` 参数 | 新增 `execute_read()` 方法 / 绕过 adapter 直接用 engine | 完全向后兼容（默认 `None`）；避免冗余方法；保持封装完整性 |
| `execute_write()` 返回 | `dict` 格式 | `int \| str` | 与 MCP 工具返回格式统一，避免 `isinstance` 类型判断 |
| Skill 名称格式 | 严格模式 `^[a-z0-9][a-z0-9-]*$` | 宽松 `[a-zA-Z0-9_-]` | 对齐 Agent Skills 规范 name 约束 |
| 触发条件 | `triggers` 关键词列表（与 `description` 分离） | 触发条件内嵌于 `description` | 统一入口架构中 Agent 通过 list_skills() 获取元数据，结构化 triggers 提升匹配精度且 token 开销极低 |
| Per-skill 启用控制 | `enabled` 字段（默认 true） | per-skill 环境变量 `requires: ENV=1` | 声明式、配置与 skill 共存、与 FastMCP Component Visibility 一致；环境变量模式记入未来路线 |
| 版本追踪 | `version` 可选字段（自由格式字符串） | 无版本字段 | 审计溯源、变更管理、未来缓存失效键，零架构成本 |
| Skill 间组合 | `related_skills` 发现提示 + Agent 自行编排 | 内置 pipeline/DAG 系统 | MCP "工具独立" 设计理念；pipeline 引入依赖解析/错误传播/部分回滚等复杂度；Agent 即编排层 |
| 事务粒度 | 单条 SQL + 显式事务 | 多语句事务上下文管理器 | v1.0 保持简单，单语句符合 Anthropic "低自由度" 原则；`adapter.transaction()` 记入未来路线 |
| idempotent 传达 | `list_skills()` + 执行结果 dict | ToolAnnotations `idempotentHint` | 统一入口工具的 ToolAnnotations 在注册时固定，无法按 skill 动态变化（MCP Spec 确认） |
| 错误处理 | `execute_write()` 不捕获异常 + `MutationBase` raise `ToolError` | `execute_write()` 返回错误 dict | FastMCP `ToolError` 继承 `FastMCPError` 原样透传，绕过 `mask_error_details`；两套错误机制不能共存 |
| ALLOWED_TABLES 交互 | Skill SQL 绕过 ALLOWED_TABLES | 仍经过运行时表名检查 | 模板即白名单（代码级信任 > 正则表名提取），SAFETY.md 明确注明 |
| SQLAlchemy 版本 | 明确约束 `>=2.0` | 无版本约束 | 2.0 的隐式事务确保 `execute()` 只读路径中意外写 SQL 不持久化；1.x 的 autocommit 行为有安全风险 |
| Skill 类型交叉防护 | `load_query()` 校验 `type=="query"`，`load_mutation()` 校验 `type=="mutation"` | 不检查，依赖调用方 | 防止 mutation 目录中的 query.sql 被 `execute_query_skill` 加载——类型不匹配时立即拒绝 |
| SKILLS_DIR 路径安全 | `discover()` 校验 SKILLS_DIR 在项目根目录内 | 不校验，任意路径 | 防止 `.env` 投毒将恶意 mutation.py 注入外部路径 |
| Query SQL 安全校验时机 | `discover()` 启动时校验（fail-fast） | `load_query()` 运行时校验 | 启动时拦截非法模板，不让其出现在 `list_skills()` 中；符合 fail-fast 原则和"错误处理不推卸给 Agent"最佳实践 |
| SQL 模板缓存 | `discover()` 缓存 + `load_query()` 返回缓存 | 运行时重新读盘 | 消除 TOCTOU 风险（启动后文件篡改不影响运行时）；同时为 `generate_skills_md()` 提供表名提取数据源 |
| 无参数技能 | `params` 默认 `field(default_factory=dict)` | `params` 必填 | 允许 `SELECT COUNT(*) FROM t` 等无参数查询技能，向后兼容 |

---

**设计依据溯源表**

| 来源 | 关键原则 | 本计划对应 |
|------|----------|------------|
| **MCP Spec** §7 | Validate all tool inputs; Implement proper access controls; Rate limit tool invocations | 参数化查询 + 模板白名单 + dry-run 两步确认 + 速率限制（当前依赖传输层，未来可添加应用层限流） |
| **FastMCP** Component Visibility | Disabled tools 不出现在 `list_tools` | `if ENABLE_SKILLS:` 条件注册 |
| **FastMCP** Annotations | `readOnlyHint`, `destructiveHint`, `idempotentHint` | query skill: readOnly=True; mutation skill: destructive=True, idempotentHint=False（保守值）；idempotent 信息通过 list_skills() 返回值和执行结果 dict 传达 |
| **FastMCP** Validation | `Annotated[type, Field(...)]` | Tool 参数使用 `Annotated` + `Field(description=...)` |
| **Google Gemini** | 强 schema 原则——参数应为结构化对象 | `params` 使用 `dict[str, Any]` |
| **Google Gemini** | "如果函数调用会产生重大后果，请在执行之前先向用户验证" | `confirm=False` 默认 dry-run |
| **Google Gemini** | "有效工具集保持在 10-20 个以内" | 2 个统一入口 + list_skills，而非每技能一个 Tool |
| **Microsoft Azure** | Principle of Least Privilege; Validate Function Calls | 双层开关 + 仅允许预定义脚本 + 参数校验 |
| **Microsoft Azure** | 写权限最小化——推荐读写分离账号 | SAFETY.md 记录推荐的最小权限部署实践 |
| **Anthropic** | Low freedom for fragile operations; Plan-Validate-Execute | mutation.py 三阶段：validate → preview → execute |
| **Anthropic** | Progressive disclosure | list_skills → SKILL.md → query.sql/mutation.py 三级加载 |
| **ui-ux-pro-max-skill** | 数据文件自文档化; `--persist` 两步模式 | SKILL.md YAML frontmatter 自描述 + confirm 参数 |
| **Anthropic Skills** | description 应包含"做什么"+"何时触发" | `description`（功能概述）+ `triggers`（关键词级匹配），结构化分离 |
| **FastMCP** Component Visibility | Disabled components 不出现在 list | `enabled: false` 的 skill 在 list_skills() 和 SKILLS.md 中不可见 |
| **MCP 设计理念** | 工具独立，Agent 编排 | `related_skills` 发现提示，不内置 pipeline；组合逻辑由 Agent 完成 |

---

**未来扩展路线（PoC 后迭代）**

- **每 operation 独立 Tool**：高频操作拆为独立 Tool 获得完美 schema
- **Confirmation token**：服务端令牌机制，防止跳过 dry-run
- **写入连接隔离**：`DB_WRITE_*` 系列环境变量配置独立写入账号
- **审计日志持久化**：可选写入 `_audit_log` 数据库表
- **技能 lint/版本化**：CI 中检查 SKILL.md 格式合规性
- **mutation.sql 轻量替代**：SQL-only 写操作支持（如首批未实现）
- **Per-skill 环境变量前置条件**：`requires: ENV_VAR=1` 模式，适用于多租户/细粒度权限场景
- **Skill pipeline/DAG 编排**：内置多 skill 组合执行引擎，适用于复杂数据管道场景（当前由 Agent 自行编排）
- **应用层速率限制**：per-skill 或全局 rate limiting，适用于独立 HTTP 暴露或不信任调用者场景
- **`adapter.transaction()` 上下文管理器**：支持 mutation.py 内多条 SQL 原子性执行，当 v1.0 单语句模式出现真实需求时引入
- **`ToolResult.meta`**：利用 FastMCP v2.11.0+ 的 `meta` 字段在每次工具调用中动态返回运行时元数据（如 `idempotent`、`skill_version`），更符合 MCP 协议语义
- **`ToolResult.structured_content`**：利用 FastMCP v2.10.0+ 同时返回 `content`（人类可读文本）和 `structured_content`（机器可读 JSON），query skill 可双通道输出
