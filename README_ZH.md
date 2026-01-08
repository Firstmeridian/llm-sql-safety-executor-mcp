# SQL 安全执行器 - MCP 服务实现

[English](README.md) | 中文

一个面向 LLM 以及 AI Agent 的安全数据库查询服务：使大型语言模型(LLM)可通过标准化的MCP接口，以只读 SQL(SELECT/SHOW/DESCRIBE/EXPLAIN)安全获取数据库查询。并提供白名单、超时与结果截断等防护。降低误操作风险同时避免 Token 成本失控。  
它的目标是让 LLM(Agent) 具备“进入数据库”的能力。通过与AI Agent的配合，可以使LLM成为类似前端的系统，动态地与用户交互。

### 介绍
**启发：基于LLM/Agents的用户界面**  
本项目的理念最早起源于2025年初，受到部分GraphQL的影响。最初是计划由LLM或Agents作为前端入口，通过明确的语义向后端获取信息。  
实际上，SQL语句本身就是良好的查询信息载体。与其传递GraphQL，不如进一步直接传递SQL。尤其是考虑到目前主流的LLM几乎都可以在不经额外微调的情况下，较稳定的生成常用的SQL。  
但在此基础上，需要考虑三个关键问题：
1. 潜在的SQL注入
2. LLM本身的不确定性：生成SQL的安全性
3. 生成SQL的查询准确性、查询质量和查询效率

**关于问题1：**  
此场景实际上并非“前端直接传递SQL给后端使用”的情况，LLM(Agents)在这里更类似一个于服务端运行的服务端程序。所有的SQL，都是在服务端可控的环境下生成，通过stdio模式（当然也可以是在内网安全的HTTP方式）与其它后端服务通信。此场景中的Agents是可约束输入/输出的程序，与前端（外部用户）仅通过prompt对接。而在2025年的当下，防止prompt注入已经是十分广泛且成熟的实践，Agents的编写者可以很轻松的用多种方法来避免外部prompt注入。  
**关于问题2：**  
LLM的生成具有不确定性。即便有极小概率，这也会导致生成SQL的安全性无法得到保障。需要有SQL安全检查工具对生成的SQL进行检查和过滤。  
**关于问题3：**  
LLM(Agents)不能凭空生成SQL，需要有一定的上下文基础。这里的上下文可以是自然语言提示或数据库文档，但更重要的是数据库结构、查询示例以及数据本身。对于高质量的查询，就目前的来讲（截至2025年末），应当采用ReAct方案：即为推理 (Thought) --> 行动 (Action) --> 观察(Observation) --> 再思考决定下一步行动的循环。  
**总的来说，本项目是针对问题2和问题3的解决方案。**

### 项目演进：
在早期，本项目的目标是编写一个简易的SQL安全检查工具，用于在执行前对SQL语句检查和过滤。作为方法供LLM(Agents)进行调用(FunctionCall)

- 之后，[在(v1.0)版本](LLM_TO_MCP_FEASIBILITY_ANALYSIS.md) 进行了重构，以增加对标准化MCP服务架构的支持。同时进行解耦，在增强安全性和可扩展性的同时简化维护。

- [在(v2.0)版本](REFACTORING_LOG.md) 针对实际的MCP使用场景，进行了查询效率和调用风险的优化。
  1. 通过工具合并以及增加新的常用工具，减少工具调用次数，优化工具调用效率。
  2. 聚焦于真实使用中的token爆炸风险（这可能导致大量的LLM API费用支出）进行针对性优化。
  3. 同时新增了[多Agent调用该MCP服务的示例](README_ZH.md#autogen-多-agent-示例)，基于AutoGen框架，用于示范Agents于本服务的结合。

- [在(v2.1)版本](REFACTORING_LOG.md#latest-update-january-4-2026---tool-optimization--field-naming) 专注于工具设计和输出一致性的改进。优化并重构了大量工具，尽可能的遵守业界相关的最佳实践。整体设计上，采用ReAct方案推理 (Thought) --> 行动 (Action) --> 观察(Observation) --> 再思考决定下一步行动的循环范式。在保证查询效率的同时提升查询准确性和多步骤查询的质量。基于AutoGen的多agent调用示例也同步更新。

经过上述迭代，本项目从最初基于LLM/Agents的用户界面设想，演进到支持MCP的SQL综合查询服务。但需要承认的是，当前的项目虽然出发点不同，但实际上与目前的Text2SQL有所相似。  
在本项目构思初期（2025年3-4月），此类系统还是较为少见的。在当时，类似的Text2SQL实践主要还停留在：接收相关人员的提示，LLM单次生成SQL语句辅助其进行查询的背景下。而本项目的出发点不同，核心动机主要是 **使LLM(Agents)代替传统前端，成为新的“前端”，动态地与用户交互，无论是界面中的数据还是界面。** 让整个系统达到充分灵活且动态的效果。  
就目前来说，**本项目的核心思想是赋予LLM(Agents)进入数据库的能力。** 搭配不同的Agent，可以开发扩展出不同的工作场景。

### 项目路线图
**Agent Skills和扩展性**  
在未来，计划引入对Agent Skills的支持。
同时计划对于本项目进行扩展性的提升。在现有的实践中我们认识到提供（封装成）具体的语义化工具的意义。业界也有对应的最佳实践论述：
> "Offload the burden from the model and use code where possible."  
> "Don't make the model fill arguments you already know."  
> "Combine functions that are always called in sequence."
> [— OpenAI, "Best practices for defining functions" (December 2025)](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions)

这说明在合理的情况下，一个实用的系统应该加入、并支持添加针对特定场景的额外工具。但是，过多的工具会占用更多上下文，并且会降低准确率/增加成本[1]。而Agent Skills的渐进式披露(progressive disclosure)[2]则可以避免这些问题。
因此，我们可以设想这样一个方案：用户或开发人员可以编写大量依赖于本MCP服务之上的“插件”（代码段/工具），通过SKILL.md管理，可以动态的增加与配置工具。而Agent则可以加载这些“插件”，灵活扩展其能力。

> [1]: ["Keep the number of functions small for higher accuracy."](https://platform.openai.com/docs/guides/function-calling)  
> [2]: ["This filesystem-based architecture enables progressive disclosure: Claude loads information in stages as needed, rather than consuming context upfront."](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#how-skills-work)


### 关于AI辅助开发(copilot, vibe-coding)的实践经验
本项目最初由Gemini CLI创建，在v1.0之后主要使用GitHub copilot进行开发。  
在使用AI辅助开发本项目的时候，基本遵循以下经验。
1. 尽可能的遵循web和GitHub上相关的最佳实践，比如Anthropic，Google，FastMCP和Microsoft等。避免幻觉和局部最优解的产生。
2. 尽可能使AI进行反思自己的输出。
3. 在满足1，2的前提下，尽可能减少对AI的约束。用最简洁的提示和步骤完成任务，并使AI完成完整的工作流。
> 对于上下文，要尽可能的保留充分完整；对于提示和约束，要尽量减少。

这就是本项目虽然保留了最初的GEMINI.md，但仅作为记录使用，并且也未增加AGENTS.md的原因。但SKILL.md或类似的“渐进式”文档是良好的实践。本项目的相关文档 [REFACTORING_LOG.md](REFACTORING_LOG.md) 和 [PROMPT_ENGINEERING_BEST_PRACTICES.md](PROMPT_ENGINEERING_BEST_PRACTICES.md) 体现了这一实践。

### 风险和局限
在编写本项目的实践中，使用了大量的AI辅助开发。尽管已经尽可能的review代码和进行测试，并添加了一系列安全设置。但精力有限，无法覆盖全部情况，尤其是考虑到有LLM参与其中的情况。  
**因此，不要在未经测试的情况下直接接入生产环境或与Agent搭配。这可能会导致意想不到的后果！**
贸然接入未经测试的Agent可能会导致 **不稳定、死循环、token爆炸、巨量查询** 或其它未验证的负面影响。  
在最近的几次修改中，进行了多次的效率优化，主要聚焦于减少不必要的工具调用次数和速度优化。但因为LLM(Agents)的随机性，在实际使用时，仍可能出现不必要的工具调用情况，尽管概率较小。

### 已知问题和不足
- **行数相关字段可能不精确**：`list_tables()` / `describe_table()` / `get_full_schema()` 在默认情况下返回的 `row_count` 来自 `INFORMATION_SCHEMA.TABLES.TABLE_ROWS`，属于统计估计值（尤其对 InnoDB 可能有明显偏差或滞后），仅建议用于“量级判断/是否加 LIMIT/是否大表”等策略，不应当当作精确计数。
  - 如需精确行数，请使用 `SELECT COUNT(*) ...`，或启用 `ENABLE_TABLE_SUMMARY=1` 后使用 `get_table_summary(exact_count=True)`（注意大表可能较慢）。

- **为避免 token 爆炸，返回结果可能被截断**：`query()`、`list_tables()`、`get_full_schema()` 会根据 `MAX_RESULT_ROWS` / `MAX_RESULT_CHARS` / `MAX_OVERVIEW_TABLES` / `MAX_SCHEMA_TABLES` 截断输出；因此“返回的数据/表/列”可能不是全量。需要全量时请显式使用更小范围的查询（加 `LIMIT`、按条件分页），或调整相关环境变量（风险自担）。

- **部分“总数”字段是“可见范围”语义**：例如 `total_tables` 在工具输出中表示“allowlist 参数过滤后的可见表数量（再考虑截断）”，并非一定等同于数据库实际总表数；请避免将其误读为“全库统计”。

### 使用本项目的最佳实践
- **推荐首先接入VS Code的GitHub Copilot进行试用。** VS Code中的GitHub Copilot是一个成熟的AI Agent工具，你可以选择免费模型（例如GPT-5 mini）在测试数据库中进行使用，这样安全性较高，同时可以避免额外的AI请求费用消耗。
- **在GitHub Copilot中使用的另一个好处是：可以使Copilot这种辅助编码AI获得进入数据库的能力，** 使其了解目标数据库的结构和数据分布。这在编写程序时可以提供更好的开发辅助和建议。
- **（以GitHub Copilot为例）在使用时，可以在提示中加上类似“为了回答的数据和理由准确充分，你需要一步一步，多次进行查询。”** 的提醒。这会引导AI进行多次，复杂，类似ReAct模式的查询，以获得更好的效果。这在解决复杂问题时尤为有用。
- **（以GitHub Copilot为例）在使用时显式的附加“#sql-safety-executor-mcp”工具，这样可以提醒AI优先使用该工具。** ![tools](readme_pic/tools.png)
- **（以GitHub Copilot为例）善用Agent提供的“todo”工具**，这样可以让AI帮助计划查询步骤，提升性能和效率。![todo](readme_pic/todo.png)
- 在最近的几次修改中（截至2026.1.7），进行了多次的安全优化，比如大数据量下的截断，特殊关键词的使用（比如union），表的白名单设置，针对不同配置的动态提示词等。但是 **更高的安全意味着更低的性能、效率和更高的消耗（比如更多的请求参数和token消耗），因此请酌情配置安全性设置。**
- 实际上，Claude Code、Codex、Gemini CLI这样的AI客户端也与GitHub Copilot类似，但是 **请注意AI调用可能产生大量token的费用问题。** 并且目前的测试（包括能力测试）主要集中在GitHub Copilot上完成。


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
2.  打开 GitHub Copilot Chat ，确保处于Plan或Agent模式。
3.  点击输入框下方，模型选择框旁边的 **工具图标**。
4.  您应该能看到 `sql-safety-executor` 及其提供的工具 (如 `query`, `list_tables`)。确保它们已经被全部勾选。![Add tools](readme_pic/Addtools.png)
5.  直接在对话中发送提问即可：“列出所有表”或“查询 users 表的前5行”。![ask](readme_pic/ask.png)  
可以看到 MCP 工具被调用![answer](readme_pic/answer.png)  
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
      "cwd": "/path/to/llm-sql-executor-gateway-mcp"
    }
  }
}
```

- 将 `/path/to/` 替换为您的实际项目路径。
- 服务器从工作目录中的 `.env` 文件加载凭据。
- 对于虚拟环境，使用 Python 解释器的完整路径。

## 配置（位于.env文件中。需要先拷贝.env.example，重命名为.env以进行配置）

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
ENABLE_SCHEMA_TOOLS=1    # 控制 sample() 工具
ENABLE_TABLE_SUMMARY=0   # 控制 get_table_summary() 工具（默认：禁用）
                         # describe_table() 已提供估计行数

# 大表阈值，用于 is_large 标志和查询建议
# 超过此行数的表会触发 LIMIT/聚合提示
LARGE_TABLE_THRESHOLD=1000

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
MAX_RESULT_ROWS=100      # 每次查询返回的最大行数（0=不限制）
MAX_RESULT_CHARS=16000   # 响应中的最大字符数（0=不限制）
MAX_SCHEMA_TABLES=50     # get_full_schema 返回的最大表数（0=不限制）
MAX_OVERVIEW_TABLES=100  # list_tables 返回的最大表数（0=不限制）
```

### MCP 客户端集成
有关完整的客户端配置示例，请参阅 `mcp_config.json`。

## 更新日志

### v2.1 工具优化（2026年1月）

专注于工具设计和输出一致性的改进：

- **`get_table_summary` 现为可选工具**：默认禁用（`ENABLE_TABLE_SUMMARY=0`），因为 `describe_table()` 已提供估计行数。仅在需要精确 COUNT(*) 时启用。
- **增强的 `describe_table`**：现在返回 `row_count`、`row_count_approximate`、`is_large` 标志和 `recommendation` 查询建议。
- **重构 `list_tables` 输出**：
  - `data` → `tables`，更清晰
  - 新增 `database_name`、`returned_table_count`、`total_tables`、`truncated`、`truncation_note`
- **一致的字段命名**：`returned_table_count` vs `total_tables` 规范同时应用于 `list_tables` 和 `get_full_schema`
- **新增环境变量**：
  - `ENABLE_TABLE_SUMMARY=0` - 控制 `get_table_summary()` 工具
  - `LARGE_TABLE_THRESHOLD=1000` - `is_large` 标志的阈值
  - `MAX_OVERVIEW_TABLES=100` - `list_tables()` 最大表数
- **AutoGen Agent 提示更新**：移除 `get_table_summary()` 引用，更新工作流为 `list_tables() → describe_table()` 模式

详细变更请参阅 [REFACTORING_LOG.md](REFACTORING_LOG.md)。

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

该解决方案实现了一个 MCP 服务器，提供标准化的数据库访问：

```
传统方式：                    MCP 服务方式：
LLM → 直接函数调用            LLM → MCP 客户端 → MCP 服务器 → 数据库
```

---

### 关键组件

1. `start_server.py`：服务器启动和环境验证
2. `mcp_sql_server.py`：核心 MCP 工具定义和功能（v2.0 重构）
3. `sql_safety_checker.py`：原始验证和执行逻辑
4. `test_mcp_functions.py`：内部函数测试
5. `test_mcp_client.py`：MCP 协议测试

## 公开的 MCP 工具

该服务公开 5-7 个标准化的 MCP 工具（取决于配置）：

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
用途：数据库概览 - 列出所有表及其估计行数

轻量级的初始探索工具。行数为 INFORMATION_SCHEMA 估计值（InnoDB 可能有 ±40% 误差）。

输出：
```json
{
  "success": true,
  "database_name": "mydb",
  "returned_table_count": 2,
  "total_tables": 2,
  "tables": [
    {"table_name": "users", "row_count": 150},
    {"table_name": "products", "row_count": 500}
  ],
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null,
  "hint": "Row counts are estimates (InnoDB ±40%). total_tables = visible after allowlist."
}
```

### 4. `describe_table`
用途：获取表结构 - 列信息、估计行数和查询建议

返回列详情以及来自 INFORMATION_SCHEMA 的估计行数（避免 COUNT(*) 全表扫描）。包含 `is_large` 标志用于查询规划。

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
  "row_count": 1500,
  "row_count_approximate": true,
  "column_count": 5,
  "columns": [
    {"column_name": "id", "data_type": "int", "nullable": "NO", "key_type": "PRI"},
    {"column_name": "name", "data_type": "varchar", "nullable": "YES", "key_type": ""}
  ],
  "is_large": true,
  "recommendation": "Large table (~1500 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
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

### 6. `get_full_schema`
用途：在一次调用中获取完整的数据库模式（所有表和列）

适用于多表 JOIN 或需要一次性获取所有表结构的场景。对于单表查询，建议使用 `describe_table()`。

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
  "returned_table_count": 1,
  "total_tables": 1,
  "total_columns": 2,
  "row_count_approximate": true,
  "truncated": false,
  "truncation_note": null,
  "hint": "Row counts are estimates (InnoDB ±40%). Use LIMIT for large tables (row_count > 1000). total_tables = visible after allowlist."
}
```

### 7. `get_table_summary`（可选）
用途：获取表统计信息，支持可选的精确行数计算

**注意**：此工具由 `ENABLE_TABLE_SUMMARY` 环境变量控制（默认：**禁用**）。`describe_table()` 工具已经提供估计行数，因此只有在需要精确计数时才需要此工具。

**警告**：`exact_count=True` 会运行 COUNT(*)，在大型 InnoDB 表上可能很慢（全表扫描）。

输入：
```json
{
  "table_name": "users",
  "exact_count": false
}
```

输出：
```json
{
  "success": true,
  "table_name": "users",
  "row_count": 150,
  "row_count_approximate": true,
  "column_count": 5,
  "columns": [...],
  "is_large": true,
  "recommendation": "Large table (~150 rows). Use LIMIT or aggregation (COUNT/GROUP BY)."
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
