# SQL 安全检查器 - MCP 服务实现

[English](README.md) | 中文

一个基于 Python 的工具，使大型语言模型（LLM）能够通过标准化的 MCP（Model Context Protocol，模型上下文协议）服务接口安全地执行只读 SQL 查询。

## 快速开始

### 使用 VS Code 快速调用 MCP 服务

在 VS Code 通过配置 `mcp.json` 实现快速集成，可以直接在 GitHub Copilot Chat 中调用本项目的 SQL 工具。使 GitHub Copilot Chat 拥有面向数据库的能力。[当然，还可以在其它支持MCP的AI助手中使用。](README_ZH.md#配置-mcp-客户端)

#### 1. 准备工作
*   确保 VS Code 为最新版本。
*   安装 **GitHub Copilot Chat** 扩展。
*   确保本项目已安装依赖 (在本项目路径下运行 `pip install -r requirements.txt`)。
*   配置环境 `cp .env.example .env` 使用您的数据库凭据编辑 .env [在.env中配置环境变量](README_ZH.md#配置)

#### 2. 创建配置文件
在项目根目录下新建文件夹 `.vscode`（可能已存在，不存在则新建），并在其中新建文件 `mcp.json`。

#### 3. 填写配置 (关键步骤)
将以下内容复制到 `mcp.json` 中（如果`mcp.json`已存在则在其中追加配置即可， VS Code 是通过配置 `mcp.json` 进行 MCP Server 的识别）。**请务必修改为您的实际绝对路径**：

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/python", 
      "args": ["/absolute/path/to/start_server.py"],
      "cwd": "/absolute/path/to/project_root"
    }
  }
}
```

**配置详解：**
*   `command`: **必须**指向虚拟环境中的 Python 解释器绝对路径 (例如 `.venv/bin/python`)，不要直接用系统 `python`。
*   `args`: 指向 `start_server.py` 的绝对路径。
*   `cwd`: 项目根目录的绝对路径，确保能读取到 `.env` 文件。

**也可以用以下方式在 VS Code 的图形界面中配置：（推荐）**

1. 完成 “1. 准备工作” 。
2. 打开 VS Code 命令面板 (`Ctrl+Shift+P` / `Cmd+Shift+P`)。
3. 输入并选择 `MCP: Add Server`。![MCP: Add Server](readme_pic/MCP:AddServer.png)
4. 根据引导一步一步添加上面的内容（请根据实际路径修改）：

实际上二者殊途同归，它们会生成一样位置的 `mcp.json` 文件。无论如何，您只需要保证 `.vscode` 中的 `mcp.json` 有以上配置即可。

#### 4. 验证与使用
1.  重启 VS Code，或使用 VS Code 命令面板重新加载窗口。
2.  打开 GitHub Copilot Chat ，确保为Plan或Agent模式。
3.  点击输入框下方，模型选择框旁边的 **工具图标**。
4.  您应该能看到 `sql-safety-executor` 及其提供的工具 (如 `query`, `list_tables`)。确保它们已经被全部勾选。![Add tools](readme_pic/Addtools.png)
5.  直接在对话中发送提问即可：“列出所有表”或“查询 users 表的前5行”。![ask](readme_pic/ask.png)![answer](readme_pic/answer.png)
注意：虽然已经优化了工具使用，但还是推荐在 GitHub Copilot Chat 中通过免费模型（例如GPT-5 mini）进行使用，以避免额外的请求消耗。

#### 常见问题
*   **找不到工具？** 检查 `Output` (输出) 面板，切换到 "GitHub Copilot" 查看是否有报错。
*   **路径错误**：Windows 用户请注意 JSON 中的反斜杠转义 (例如 `C:\\Users\\...`)。

### MCP 服务用法
```bash
# 安装包括 MCP 支持在内的依赖
pip install -r requirements.txt

# 配置环境
cp .env.example .env
# 使用您的数据库凭据编辑 .env

# 启动 MCP 服务器
python start_server.py

# 测试 MCP 功能（内部函数）
python test_mcp_functions.py

# 通过客户端测试 MCP 服务器（模拟真实的 MCP 客户端）
python test_mcp_client.py
```

### AutoGen 多 Agent 示例
```bash
# 运行 AutoGen 多 Agent SQL 查询系统
# 需要：GEMINI_API_KEY、OPENAI_API_KEY 或 USE_OLLAMA=true
python autogen_sql_agent.py

# 或使用特定任务运行
python autogen_sql_agent.py "列出所有表并描述它们的结构"
```

`autogen_sql_agent.py` 展示了如何使用 Microsoft AutoGen 框架的多 Agent 团队（PlanningAgent、SQLExecutorAgent、AnalystAgent）与 MCP 服务器交互。

### 配置 MCP 客户端
将服务器添加到您的 MCP 兼容客户端配置中（例如 VS Code、Claude Desktop 或其他 MCP 客户端）：

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["start_server.py"],
      "cwd": "/path/to/vibe-coding-gemini-llm-execute-sql-tools"
    }
  }
}
```

- 将 `/path/to/` 替换为您的实际项目路径。
- 服务器从工作目录中的 `.env` 文件加载凭据。
- 对于虚拟环境，使用 Python 解释器的完整路径。

## 配置

### 必需的环境变量
```bash
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
DB_NAME=your_database_name
```

### 可选的环境变量
```bash
# 功能开关（1=启用，0=禁用）
ENABLE_SCHEMA_TOOLS=1  # 控制 sample() 工具

# 安全配置（生产环境推荐）
QUERY_TIMEOUT_SECONDS=30   # 查询超时秒数（P0 安全）
CONNECT_TIMEOUT_SECONDS=10 # 连接超时秒数

# 表白名单（逗号分隔，不区分大小写）
# 仅允许访问特定表 - 留空则允许所有
# 使用 "*" 显式允许所有表（UNION 需要配合此设置）
ALLOWED_TABLES=products,orders,customers

# UNION 查询策略
# 重要：UNION 需要双重配置才能启用：
#   1. ALLOW_UNION=1
#   2. ALLOWED_TABLES=table1,table2 或 ALLOWED_TABLES=*
# 如果 ALLOW_UNION=1 但 ALLOWED_TABLES 为空，UNION 仍会被阻止。
ALLOW_UNION=0

# Token 优化：限制结果大小以防止上下文溢出
# 设为 0 可禁用截断（用于数据导出场景）
MAX_RESULT_ROWS=100    # 每次查询返回的最大行数（0=不限制）
MAX_RESULT_CHARS=16000 # 响应中的最大字符数（0=不限制）
```

### MCP 客户端集成
有关完整的客户端配置示例，请参阅 `mcp_config.json`。

## 更新日志

### v2.0 重构（2025年12月）- 当前分支：`feature/v2.0-mcp-server-refactoring`

遵循 FastMCP 最佳实践的重大改进：

- **扩展 SQL 支持**：现支持多种只读语句类型
  - `SELECT`：标准数据检索
  - `SHOW`：数据库元数据（SHOW TABLES、SHOW COLUMNS 等）
  - `DESCRIBE`：表结构信息
  - `EXPLAIN`：查询执行计划分析
- **工具整合**：从 6 个工具减少到 5 个，然后通过新的优化工具扩展到 7 个
  - `validate_sql_query` + `execute_safe_sql` → 合并为 `query`（自动验证）
  - 新增 `list_tables` 工具用于数据库发现
  - 重命名工具以提高清晰度：`check_connection`、`describe_table`、`sample`
  - **新增（12月23日）**：添加 `get_full_schema` 和 `get_table_summary` 用于 Token 优化
- **优化服务器指令**：减少 LLM 的"探索性行为"（不必要的工具调用）
  - 明确工具优先级：`query` 优先，其他仅在出错时使用
  - 预期减少：每次查询从 4-5 次工具调用减少到 1-2 次
- **安全增强（2025年12月23日）**：
  - 查询超时保护（P0 安全）
  - 表白名单支持（`ALLOWED_TABLES`）
  - 可配置的 UNION 策略（`ALLOW_UNION`）
  - 结果截断以防止 Token 溢出
- **代码质量**：在保持功能的同时减少约 40% 的代码（约 460 → 约 280 行）
- **增强元数据**：添加 `ToolAnnotations` 以改善 LLM 工具选择
- **生命周期管理**：正确的异步资源生命周期（FastMCP 最佳实践）
- **SQL 注入防护**：为动态表名添加标识符验证

详细变更请参阅 [REFACTORING_LOG.md](REFACTORING_LOG.md)。

### v1.0 - MCP 服务架构

本项目已从直接函数调用方式转变为标准化的 MCP 服务架构，提供：

- 面向服务的架构：将直接的 LLM 函数调用转换为独立的 MCP 服务器
- 标准化协议：实现 MCP 工具以实现一致的 AI 模型集成
- 增强的关注点分离：将服务器启动逻辑分离到专用的 `start_server.py`
- 改进的可扩展性：单个服务器实例支持多个并发 LLM 客户端
- 更好的安全性：通过 MCP 协议进行服务隔离和受控访问

## 问题陈述

### 原始挑战
传统的 LLM-数据库集成面临以下限制：
- 紧耦合：数据库逻辑与 LLM 交互代码交织在一起
- 可扩展性问题：每个 LLM 实例需要单独的数据库连接
- 安全问题：直接访问数据库函数而没有适当的隔离
- 维护开销：更改需要跨多个 LLM 实现进行更新
- 有限的可重用性：特定平台的实现难以共享

### 核心需求
- 为 AI 模型启用安全的 SQL 查询执行
- 确保只允许只读语句（SELECT、SHOW、DESCRIBE、EXPLAIN）
- 提供跨不同 AI 平台的一致接口
- 保持高性能和可靠性
- 支持多个并发 AI 模型连接

## 解决方案

### v2.0 - 优化的工具设计（2025年12月）

v2.0 重构专注于通过以下方式减少 LLM 的"探索性行为"：

```
之前（v1.0）：                          之后（v2.0）：
LLM 每次查询调用 4-5 个工具            LLM 每次查询调用 1-2 个工具

check_connection                        query（主要）
    ↓                                      ↓
list_tables                             [仅在出错时]
    ↓                                      ↓
describe_table                          list_tables / describe_table
    ↓
query
```

**关键优化：**
- 服务器指令中明确的工具优先级
- 明确的"何时不使用"指导
- 为 LLM 提供正确/错误使用示例
- 遵循 Microsoft/OpenAI 提示工程最佳实践

### v1.0 - MCP 服务架构

我们的解决方案实现了一个 MCP 服务器，提供标准化的数据库访问：

```
传统方式：                    MCP 服务方式：
LLM → 直接函数调用            LLM → MCP 客户端 → MCP 服务器 → 数据库
```

### 关键组件

1. `start_server.py`：服务器启动和环境验证
2. `mcp_sql_server.py`：核心 MCP 工具定义和功能（v2.0 重构）
3. `sql_safety_checker.py`：原始验证和执行逻辑（未更改）
4. `test_mcp_functions.py`：内部函数测试
5. `test_mcp_client.py`：MCP 协议测试

## 公开的 MCP 工具

该服务公开了七个标准化的 MCP 工具（2025年12月重构）：

### 1. `query`（主要工具）
用途：执行带有自动安全验证的只读 SQL 查询

这是所有数据库操作的主要工具。安全验证是自动的 - 只允许只读语句（SELECT、SHOW、DESCRIBE、EXPLAIN）。

输入：
```json
{
  "sql": "SELECT COUNT(*) as total FROM products"
}
```

输出：
```json
{
  "success": true,
  "query": "SELECT COUNT(*) as total FROM products",
  "data": [
    {"total": 150}
  ],
  "row_count": 1
}
```

### 2. `check_connection`
用途：测试数据库连接和配置

输出：
```json
{
  "connected": true,
  "message": "Database connection successful"
}
```

### 3. `list_tables`
用途：列出数据库中所有表及其行数

输出：
```json
{
  "success": true,
  "data": [
    {"table_name": "users", "row_count": 150},
    {"table_name": "products", "row_count": 500}
  ],
  "table_count": 2
}
```

### 4. `describe_table`
用途：检索特定表的列信息

输入：
```json
{
  "table_name": "users"
}
```

输出：
```json
{
  "success": true,
  "table_name": "users",
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI"},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": ""}
  ],
  "column_count": 2
}
```

### 5. `sample`（可选）
用途：从指定表中检索示例数据

**注意**：此工具由 `ENABLE_SCHEMA_TOOLS` 环境变量控制（默认：启用）

输入：
```json
{
  "table_name": "users",
  "limit": 5
}
```

输出：
```json
{
  "success": true,
  "table_name": "users",
  "data": [
    {"id": 1, "name": "Alice"},
    {"id": 2, "name": "Bob"}
  ],
  "row_count": 2,
  "query": "SELECT * FROM `users` LIMIT 5"
}
```

### 6. `get_full_schema`（新增 - 2025年12月）
用途：在一次调用中获取完整的数据库模式（所有表和列）

首先使用此工具，而不是多次调用 `describe_table()`。减少工具调用并提前提供完整上下文。

输出：
```json
{
  "success": true,
  "schema": {
    "users": {
      "row_count": 150,
      "columns": [
        {"name": "id", "type": "int", "nullable": "NO", "key": "PRI"},
        {"name": "name", "type": "varchar", "nullable": "YES", "key": ""}
      ]
    }
  },
  "table_count": 1,
  "total_columns": 2
}
```

### 7. `get_table_summary`（新增 - 2025年12月）
用途：获取表的汇总统计信息，无需获取原始数据

使用此工具进行快速分析，而不是 `SELECT *` 查询。

输入：
```json
{
  "table_name": "users"
}
```

输出：
```json
{
  "success": true,
  "table_name": "users",
  "total_rows": 150,
  "column_count": 5,
  "columns": [...],
  "is_large": true,
  "recommendation": "Table has 150 rows. Use 'SELECT ... LIMIT 10' for samples."
}
```

## 实现的优势

- 🔒 增强安全性：通过 SQL 解析实现服务隔离和仅 SELECT 执行
- 🔌 标准化集成：MCP 工具为 LLM 客户端提供一致的接口
- 🧹 可维护性：关注点清晰分离（启动/环境验证在 `start_server.py` 中；工具隔离）
- ⚡ 性能：SQLAlchemy 连接池减少连接开销
- 🧩 兼容性：MySQL 支持；与 MCP 兼容的客户端（如 Claude Desktop）和自定义应用程序一起工作；保留原始直接调用函数
- ⚙️ 可配置性：基于环境的凭据和启动时所需变量的验证
- 🔍 可发现性：用于探索模式和数据的可选数据库内省工具

## 安全功能

- 查询限制：仅允许 SELECT 语句
- SQL 解析验证：使用 `sqlparse` 进行全面的查询分析
- 连接安全：基于环境的凭据管理
- 错误隔离：全面的异常处理和报告
- 访问控制：MCP 协议级别的权限管理

## 依赖要求

- Python 3.12+
- MySQL 数据库
- 依赖：`sqlparse`、`SQLAlchemy`、`PyMySQL`、`fastMCP`、`python-dotenv`

## 测试

### 测试脚本

该项目包括两个互补的测试脚本：

#### 1. `test_mcp_functions.py` - 内部函数测试
直接测试底层函数，不通过 MCP 协议：
```bash
python test_mcp_functions.py
```

此脚本验证：
- SQL 验证逻辑（安全和不安全的查询）
- 数据库连接
- 查询执行
- 模式内省（如果启用）
- 示例数据检索（如果启用）

#### 2. `test_mcp_client.py` - MCP 协议测试
使用 FastMCP Client 通过 MCP 协议测试服务器：
```bash
python test_mcp_client.py
```

此脚本：
- 使用 FastMCP 的 `Client` API 连接到 MCP 服务器
- 测试服务器信息和数据库连接
- 执行多个 SQL 查询（列出表、SELECT、COUNT）
- 测试可选的模式工具（如果启用）
- 验证数据序列化格式

## 其他文档

- [可行性分析](LLM_TO_MCP_FEASIBILITY_ANALYSIS.md)：LLM 到 MCP 转换的详细分析
- [原始上下文](GEMINI.md)：项目背景和开发指南
- [重构日志](REFACTORING_LOG.md)：2025年12月重构变更文档
- [MCP 客户端测试指南](TEST_MCP_CLIENT_GUIDE.md)：通过客户端测试 MCP 服务器的指南
- [提示工程最佳实践](PROMPT_ENGINEERING_BEST_PRACTICES.md)：MCP 工具描述和提示的指南

## 贡献

1. Fork 仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 进行更改并进行适当的测试
4. 为新功能添加测试
5. 根据需要更新文档
6. 提交 Pull Request

## 支持

对于技术问题、功能请求或疑问：
- 在 GitHub 仓库中创建 issue
- 包含相关错误消息和配置详细信息
- 提供重现问题的步骤

---

*本项目展示了从直接 LLM 函数调用到标准化 MCP 服务的成功转换，为 AI 驱动的数据工作流提供了改进的可扩展性、安全性和可维护性。*
