以下是 6 幅架构图（12 处模糊点分析已合并入主文档 DRAFTPLAN_final.md）。

---

## 一、架构图

### 图 1：现有架构（扩展前）

```
┌─────────────────────────────────────────────────────────────┐
│                      LLM / AI Agent                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ MCP Protocol (stdio)
┌──────────────────────────▼──────────────────────────────────┐
│                   start_server.py                            │
│                 (入口 + 环境验证)                              │
│                        │                                     │
│             ┌──────────▼──────────┐                          │
│             │  mcp_sql_server.py  │                          │
│             │   FastMCP Server    │                          │
│             │                     │                          │
│             │  ┌───────────────┐  │                          │
│             │  │ @mcp.tool     │  │  5-7 个只读工具           │
│             │  │ ● query()     │  │  所有工具 readOnly=True   │
│             │  │ ● list_tables │  │                          │
│             │  │ ● describe    │  │                          │
│             │  │ ● full_schema │  │                          │
│             │  │ ● check_conn  │  │                          │
│             │  │ ○ sample      │──┼── ENABLE_SCHEMA_TOOLS    │
│             │  │ ○ summary     │──┼── ENABLE_TABLE_SUMMARY   │
│             │  └───────┬───────┘  │                          │
│             │          │          │                          │
│             │  ┌───────▼───────┐  │                          │
│             │  │ 安全层 (4 级)  │  │                          │
│             │  │ 1.is_sql_safe │  │  只允许 SELECT/SHOW/     │
│             │  │ 2.extended_chk│  │  DESCRIBE/EXPLAIN        │
│             │  │ 3.table_allow │  │                          │
│             │  │ 4.identifier  │  │                          │
│             │  └───────┬───────┘  │                          │
│             └──────────┼──────────┘                          │
│                        │                                     │
│             ┌──────────▼──────────┐                          │
│             │ sql_safety_checker  │                          │
│             │  is_sql_safe()      │                          │
│             │  execute_sql()      │                          │
│             └──────────┬──────────┘                          │
│                        │                                     │
│             ┌──────────▼──────────┐                          │
│             │   db_adapter.py     │                          │
│             │                     │                          │
│             │  DatabaseAdapter    │  ABC                     │
│             │    ├─MySQLAdapter   │  SQLAlchemy+PyMySQL      │
│             │    └─SQLiteAdapter  │  SQLAlchemy+sqlite3      │
│             │                     │                          │
│             │  execute() → list|str                          │
│             │  (只读，无 params)  │                          │
│             └──────────┬──────────┘                          │
│                        │                                     │
└────────────────────────┼────────────────────────────────────┘
                         ▼
                  ┌──────────────┐
                  │   Database   │
                  │ MySQL/SQLite │
                  └──────────────┘
```

### 图 2：扩展后架构（Skills 层集成）

```
┌────────────────────────────────────────────────────────────────┐
│                       LLM / AI Agent                            │
└───────────────────────────┬────────────────────────────────────┘
                            │ MCP Protocol (stdio)
┌───────────────────────────▼────────────────────────────────────┐
│                    start_server.py                               │
│                                                                  │
│  ┌─────────────────── mcp_sql_server.py ──────────────────────┐ │
│  │                                                             │ │
│  │  ┌─ 现有工具 (始终注册) ──┐  ┌─ Skills 工具 ──────────────┐│ │
│  │  │ ● query()              │  │ ○ list_skills()            ││ │
│  │  │ ● list_tables()        │  │ ○ execute_query_skill()    ││ │
│  │  │ ● describe_table()     │  │ ○ execute_mutation_skill() ││ │
│  │  │ ● get_full_schema()    │  │                            ││ │
│  │  │ ● check_connection()   │  │ 受 ENABLE_SKILLS 控制      ││ │
│  │  │ ○ sample()             │  │ mutation 受二次开关         ││ │
│  │  │ ○ get_table_summary()  │  │ SKILLS_ALLOW_MUTATIONS     ││ │
│  │  └────────┬───────────────┘  └──────────┬─────────────────┘│ │
│  │           │                              │                  │ │
│  │  ┌────────▼───────────┐    ┌─────────────▼───────────────┐ │ │
│  │  │ 安全层 (既有 4 级)  │    │    skills/_lib/              │ │ │
│  │  │ is_sql_safe()      │    │                              │ │ │
│  │  │ extended_check()   │    │  skill_loader.py             │ │ │
│  │  │ table_allowlist()  │    │   ├─ discover()  扫描目录    │ │ │
│  │  │ valid_identifier() │    │   ├─ validate()  参数校验    │ │ │
│  │  └────────┬───────────┘    │   └─ load()      加载执行    │ │ │
│  │           │                │                              │ │ │
│  │           │                │  mutation_base.py            │ │ │
│  │           │                │   ├─ validate()  前置检查    │ │ │
│  │           │                │   ├─ preview()   dry-run     │ │ │
│  │           │                │   └─ execute()   事务执行    │ │ │
│  │           │                │                              │ │ │
│  │           │                │  audit.py                    │ │ │
│  │           │                │   └─ log()       JSONL 记录  │ │ │
│  │           │                └───────────────┬──────────────┘ │ │
│  └───────────┼────────────────────────────────┼────────────────┘ │
│              │                                │                   │
│  ┌───────────▼──────────── db_adapter.py ─────▼───────────────┐  │
│  │                                                             │  │
│  │  DatabaseAdapter (ABC)                                      │  │
│  │    ├─ execute(sql, params?) → list|str  [现有·只读+参数化]  │  │
│  │    ├─ execute_write(sql, params, timeout?) → dict [新增·写入]         │  │
│  │    ├─ get_tables() / get_columns()                          │  │
│  │    └─ _handle_error()                  [错误脱敏·共享]      │  │
│  │                                                             │  │
│  │    MySQLAdapter  ──── SQLAlchemy + QueuePool                │  │
│  │    SQLiteAdapter ──── SQLAlchemy + StaticPool               │  │
│  └──────────────────────────┬──────────────────────────────────┘  │
│                             │                                     │
└─────────────────────────────┼─────────────────────────────────────┘
                              ▼
                       ┌──────────────┐
                       │   Database   │
                       │ MySQL/SQLite │
                       └──────────────┘

                    skills/ 目录结构
              ┌──────────────────────────┐
              │ skills/                  │
              │ ├── SKILLS.md  (自动生成) │
              │ ├── SAFETY.md            │
              │ ├── _lib/                │
              │ │   ├── skill_loader.py  │
              │ │   ├── mutation_base.py │
              │ │   └── audit.py         │
              │ ├── monthly-sales-report/│
              │ │   ├── SKILL.md         │
              │ │   └── query.sql        │
              │ └── update-order-status/ │
              │     ├── SKILL.md         │
              │     ├── mutation.py      │
              │     └── references/      │
              └──────────────────────────┘
```

### 图 3：Query Skill 数据流

```
Agent 调用: execute_query_skill("monthly-sales-report", {"year":2026, "month":1})
      │
      ▼
┌─ mcp_sql_server.py ──────────────────────────────────────────┐
│ execute_query_skill(skill_name, params)                       │
│   │                                                           │
│   ├─① skill_loader.validate_name("monthly-sales-report")     │
│   │    → 正则 ^[a-z0-9][a-z0-9-]*$ 校验                       │
│   │                                                           │
│   ├─② skill_loader.load_query("monthly-sales-report")         │
│   │    → 从 discover() 缓存获取 SkillMetadata                  │
│   │    → 校验 type == 'query'                                  │
│   │    → 返回缓存的 SQL 模板 + params schema                   │
│   │                                                           │
│   ├─③ skill_loader.validate_params(params, schema)            │
│   │    → 类型/范围/必填校验                                     │
│   │                                                           │
│   ├─④⑤ adapter.execute(sql, params=validated_params)          │
│   │    → 参数绑定在 adapter 内部完成                            │
│   │    → 绕过 is_sql_safe() 和 ALLOWED_TABLES（模板已预审计，见 SAFETY.md #1 & #14）   │
│   │                                                           │
│   ├─⑥ _serialize_result() + _truncate_result()                │
│   │                                                           │
│   └─⑦ 返回 {"success": True, "data": [...], ...}             │
└───────────────────────────────────────────────────────────────┘
```

### 图 4：Mutation Skill 数据流（两阶段）

```
═══ 阶段 1: Preview (confirm=false) ═══

Agent: execute_mutation_skill("update-order-status",
         {"order_id":42, "new_status":"shipped"}, confirm=false)
      │
      ▼
┌─ mcp_sql_server.py ───────────────────────────────────────────┐
│ execute_mutation_skill(skill_name, params, confirm=False)       │
│   │                                                             │
│   ├─① validate_name + load_mutation                             │
│   │    → importlib 加载 mutation.py                              │
│   │    → 实例化子类(adapter, audit_logger)                       │
│   │                                                             │
│   ├─② validate_params(params, schema)                           │
│   │                                                             │
│   ├─③ mutation.validate(params)                                 │
│   │    → {"valid": True, "current_status": "confirmed"}         │
│   │                                                             │
│   ├─④ mutation.preview(params)                                  │
│   │    → {"sql": "UPDATE orders SET status=:new WHERE ...",     │
│   │       "affected_rows_estimate": 1,                          │
│   │       "warnings": ["状态将从 confirmed → shipped"]}         │
│   │                                                             │
│   ├─⑤ audit.log(mode="preview", ...)                            │
│   │                                                             │
│   └─⑥ 返回 preview 结果（数据库无变更）                           │
└─────────────────────────────────────────────────────────────────┘

═══ 阶段 2: Execute (confirm=true) ═══

Agent: execute_mutation_skill("update-order-status",
         {"order_id":42, "new_status":"shipped"}, confirm=true)
      │
      ▼
┌─ mcp_sql_server.py ───────────────────────────────────────────┐
│ execute_mutation_skill(skill_name, params, confirm=True)        │
│   │                                                             │
│   ├─① validate_name + load + validate_params (同上)             │
│   │                                                             │
│   ├─② mutation.validate(params) → 再次校验 (防止状态变化)        │
│   │                                                             │
│   ├─③ mutation.execute(params)                                  │
│   │    └─ self.adapter.execute_write(                            │
│   │         "UPDATE orders SET status=:new                      │
│   │          WHERE id=:id AND status=:expected",                │
│   │         {"new":"shipped", "id":42, "expected":"confirmed"}) │
│   │       → 事务: BEGIN → execute → COMMIT/ROLLBACK             │
│   │       → {"success": True, "rowcount": 1}                   │
│   │                                                             │
│   ├─④ audit.log(mode="execute", result=..., ...)                │
│   │                                                             │
│   └─⑤ 返回 {"success":True, "rowcount":1, "skill":"update-.."}  │
└─────────────────────────────────────────────────────────────────┘
```

### 图 5：安全层级对比

```
                 现有工具 (query 等)          Skills 扩展工具
                 ═══════════════════          ═══════════════
  Layer 1        is_sql_safe()               Skill 名称正则校验
                 (SELECT/SHOW 白名单)         ^[a-z0-9][a-z0-9-]*$

  Layer 2        _is_query_safe_extended()   模板白名单
                 (阻止危险模式)               (只执行预审计的 .sql/.py)

  Layer 3        _check_table_allowlist()    参数化查询
                 (ALLOWED_TABLES)             execute(text(sql), params)

  Layer 4        _is_valid_identifier()      Frontmatter 参数校验
                 (标识符注入防护)              (类型/范围/enum)

  Layer 5                                    ✅ ALLOWED_TABLES 绕过
                                             (模板即白名单，SAFETY.md #14)

  Layer 6                                    Dry-run 默认
                                             (confirm=false 先预览)

  Layer 7                                    双层环境变量开关
                                             ENABLE_SKILLS +
                                             SKILLS_ALLOW_MUTATIONS
```

### 图 6：模块初始化时序

```
start_server.py
      │
      ├─ from mcp_sql_server import mcp  ← 模块级 import，Python 加载即刻执行
      │    │
      │    ├─ db_adapter.py 加载 → load_dotenv()  ← 环境变量在此处首次加载
      │    │
      │    ├─ [现有] 工具注册 (模块级 @mcp.tool 装饰器)
      │    │    ├─ query, list_tables, describe_table, ...
      │    │    └─ 条件: sample (ENABLE_SCHEMA_TOOLS)
      │    │             summary (ENABLE_TABLE_SUMMARY)
      │    │
      │    └─ [新增] Skills 工具注册 (模块级，同步执行)
      │         │
      │         ├─ if ENABLE_SKILLS:
      │         │    ├─ skill_loader.discover()
      │         │    │    ├─ 扫描 skills/*/SKILL.md
      │         │    │    ├─ 解析 YAML frontmatter
      │         │    │    ├─ 过滤 enabled: false
      │         │    │    ├─ 验证 related_skills (warning-only)
      │         │    │    ├─ query.sql 执行 is_sql_safe() 校验
      │         │    │    ├─ 缓存 SQL 模板到 _sql_template
      │         │    │    └─ 提取表名到 tables
      │         │    │
      │         │    ├─ 生成 skills/SKILLS.md
      │         │    │
      │         │    ├─ 注册 list_skills()
      │         │    ├─ 注册 execute_query_skill()
      │         │    │
      │         │    └─ if SKILLS_ALLOW_MUTATIONS:
      │         │         └─ 注册 execute_mutation_skill()
      │         │
      │         └─ else: 无操作，现有行为不变
      │
      ├─ load_dotenv()               ← start_server.py L16（冗余，db_adapter 已调用）
      │
      └─ main()
           ├─ validate_environment()   ← 注意：执行在工具注册之后
           │    └─ ⚠️ 既有限制：硬编码 MySQL 变量，SQLite 时误报失败
           │
           └─ mcp.run()
                │
                └─ lifespan() 启动
                     └─ yield {"initialized": True}
```

---