# Prompt Templates (FastMCP)

本服务通过 `@mcp.prompt` 装饰器暴露可重用的提示模板。客户端可使用 `prompts/list` 与 `prompts/get` 方法（或等效UI界面）发现与获取这些模板。

## 可用提示模板

### system_orchestration
- **用途**：系统级工作流程指导，定义安全策略和工具调用顺序
- **名称**：`system_orchestration`  
- **参数**：无
- **返回**：系统级提示文本，包含只读策略和调用规则
- **使用场景**：会话初始化时注入作为系统提示

**示例调用**：
```python
system_prompt = mcp_client.get_prompt("system_orchestration")
```

### generate_select_sql  
- **用途**：将自然语言请求转换为安全的SELECT语句指导
- **名称**：`generate_select_sql`
- **参数**：
  - `user_request` (必需): 用户的自然语言数据查询请求
  - `schema` (可选): 数据库表结构信息，默认为空
  - `dialect` (可选): SQL方言类型，默认为 "mysql"
- **返回**：结构化的SQL生成指导模板
- **使用场景**：需要从自然语言生成SQL查询时

**示例调用**：
```python
sql_prompt = mcp_client.get_prompt("generate_select_sql", {
    "user_request": "显示所有活跃用户的姓名和邮箱",
    "schema": "users(id INT, name VARCHAR(255), email VARCHAR(255), status ENUM('active','inactive'))",
    "dialect": "mysql"
})
```

## 推荐调用流程

### 标准工作流程

1. **连接检查**（可选但推荐）：
   ```python
   connection_status = mcp_client.call_tool("check_database_connection")
   ```

2. **系统提示注入**：
   ```python
   system_rules = mcp_client.get_prompt("system_orchestration")
   # 将 system_rules 注入为系统级上下文
   ```

3. **探索数据库结构**（如需要）：
   ```python
   # 获取所有表
   tables = mcp_client.call_tool("get_table_schema")
   
   # 获取特定表结构
   user_table = mcp_client.call_tool("get_table_schema", {"table_name": "users"})
   
   # 查看样本数据
   sample = mcp_client.call_tool("get_sample_data", {"table_name": "users", "limit": 3})
   ```

4. **SQL生成**（如需要）：
   ```python
   # 获取表结构信息
   schema_info = mcp_client.call_tool("get_table_schema", {"table_name": "users"})
   
   # 使用结构信息生成SQL
   sql_guide = mcp_client.get_prompt("generate_select_sql", {
       "user_request": user_query,
       "schema": format_schema(schema_info["data"])
   })
   # 使用指导生成SQL语句
   ```

5. **安全验证**（必须）：
   ```python
   validation = mcp_client.call_tool("validate_sql_query", {"sql_query": generated_sql})
   ```

6. **执行查询**（验证通过后）：
   ```python
   if validation["is_safe"]:
       result = mcp_client.call_tool("execute_safe_sql", {"sql_query": generated_sql})
   ```

## 安全注意事项

- 所有提示模板都强制只读访问策略
- `system_orchestration` 提供强制性安全约束
- `generate_select_sql` 明确禁止DML/DDL操作
- 建议始终按推荐流程调用，确保查询安全性

## 与工具的关系

| 提示模板 | 配合工具 | 作用 |
|---------|----------|------|
| `system_orchestration` | 所有工具 | 定义整体使用规则 |
| `generate_select_sql` | `validate_sql_query` + `execute_safe_sql` | 生成→验证→执行流程 |

## 使用示例：完整流程

```python
# 1. 初始化系统
system_prompt = mcp_client.get_prompt("system_orchestration")
conn_check = mcp_client.call_tool("check_database_connection")

# 2. 探索数据库
all_tables = mcp_client.call_tool("get_table_schema")
print(f"Available tables: {all_tables['data']}")

# 3. 查看特定表
user_schema = mcp_client.call_tool("get_table_schema", {"table_name": "users"})
user_sample = mcp_client.call_tool("get_sample_data", {"table_name": "users", "limit": 2})

# 4. 生成SQL查询
schema_text = format_schema_for_prompt(user_schema["data"])
sql_guide = mcp_client.get_prompt("generate_select_sql", {
    "user_request": "找出所有活跃用户的邮箱",
    "schema": schema_text,
    "dialect": "mysql"
})

# 5. 验证并执行
generated_sql = "SELECT email FROM users WHERE status = 'active'"
validation = mcp_client.call_tool("validate_sql_query", {"sql_query": generated_sql})

if validation["is_safe"]:
    result = mcp_client.call_tool("execute_safe_sql", {"sql_query": generated_sql})
    print(f"Query results: {result['data']}")
else:
    print(f"Query rejected: {validation['message']}")
```

---
*更多信息请参考 README.md 中的工具文档*
