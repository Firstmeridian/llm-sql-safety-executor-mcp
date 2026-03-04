# 面向 AI Agent 的数据库安全访问入口 - MCP 服务

![Version](https://img.shields.io/badge/version-3.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)
![MCP](https://img.shields.io/badge/MCP-Protocol-orange)
![AutoGen](https://img.shields.io/badge/Framework-AutoGen-blueviolet?logo=microsoft)

[English](README.md) | 中文  
> [介绍](#介绍) | 
> [快速开始](#快速开始) | 
> [使用本项目的最佳实践](#使用本项目的最佳实践) | 
> [更新日志](#更新日志) | 
> [公开的 MCP 工具](#公开的-mcp-工具) | 
> [使用此 MCP 服务的 AutoGen 多智能体示例](#autogen-多-agent-示例) | 
> [本项目的其它文档](#本项目的其它文档)  
> [项目路线图](#项目路线图) · **下一步计划（2026.1）:** 增加对NoSQL的支持  

**面向 AI Agent 的数据库安全访问入口：赋予LLM(Agents)进入数据库的能力。**  
使大模型 (LLM) 通过标准化的 MCP 接口，以经过认证的 SQL 安全获取数据库查询。
并提供白名单、超时与结果截断等防护。降低误操作风险同时避免 Token 成本失控。  
除 MySQL、SQLite 外，还提供对 NoSQL 的支持。(in progress，NoSQL 支持计划在未来版本中提供)    
本项目解决了 LLM “进入数据库”的需求。并可通过与 AI Agent 的配合，扩展 LLM 的能力边界，延伸大模型在实际业务中的应用范围。

## 问题陈述

### 原始挑战
传统的 LLM-数据库集成面临以下限制：
- **安全风险**：LLM 生成的 SQL 可能包含危险操作（DELETE/UPDATE/DROP）
- **Token 爆炸**：大表查询返回海量数据，导致上下文溢出和费用失控
- **紧耦合**：数据库逻辑与 LLM 提示词和编排代码交织，难以维护和复用
- **查询质量**：LLM 缺乏表结构信息时，易生成无效或低效 SQL
- **可扩展性**：无法保证每个 LLM 实例所需的个性化数据库连接和安全配置

### 设计目标
- 为 AI 模型启用安全的 SQL 查询执行（仅 SELECT/SHOW/DESCRIBE/EXPLAIN）
- 防止 Token 爆炸：结果截断、表数限制
- 提供跨不同 AI 平台的标准化 MCP 接口
- 支持 ReAct 模式：提供表结构信息供 LLM 决策
- 可配置的安全策略：白名单、超时、UNION 控制

## 解决方案

### 服务架构

本项目实现标准化的 MCP（Model Context Protocol）服务，为 LLM 提供安全的数据库访问：

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP 客户端                                │
│         (VS Code Copilot / Claude Desktop / Gemini CLI)         │
└─────────────────────────┬───────────────────────────────────────┘
                          │ MCP Protocol (stdio)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   sql-safety-executor (MCP Server)              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 工具层:   query | list_tables | describe_table | ...       │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │ 安全层:     SQL 验证 | 表白名单 | 结果截断 | 查询超时         │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────┘
                          │ SQLAlchemy (连接池)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                           Database                              │
└─────────────────────────────────────────────────────────────────┘
```

### 核心设计

**1. 安全性检验**：仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN，自动拦截危险语句

**2. Token 保护**：结果截断（`MAX_RESULT_ROWS`）+ 表数限制（`MAX_OVERVIEW_TABLES`）

**3. 工具设计**：
- 采用 Model-driven 模式，优先提供决策规则而非固定流程
- 工具返回 `is_large`/`row_count` 等上下文，供 LLM 自主决策
- 支持基于配置的策略/提示注入（如 ALLOW_UNION、ALLOWED_TABLES、截断阈值），用更短、更相关的指导减少无效工具调用
- 错误反馈面向 LLM 优化：明确失败原因（安全拦截/表未允许/语法/超时/截断等）并给出修正建议，减少反复试错与无效调用，同时避免泄露敏感信息（凭据、系统表细节等）
- 适配 ReAct 模式：推理 → 行动 → 观察 → 再思考

**4. 典型工作流**：
```
结构未知：list_tables() → describe_table(target) → query(sql)
结构已知：query(sql) 直接执行
大表场景：观察 is_large=true → 使用 LIMIT 或聚合
```

### 安全功能
- **查询限制**：仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN
- **SQL 解析验证**：使用 `sqlparse` 进行全面的查询分析
- **连接安全**：基于环境的凭据管理
- **错误隔离**：面向LLM的全面异常处理和报告
- **接入隔离**：由宿主/运行环境控制接入边界
- **表白名单**：可配置限制访问的表
- **结果截断**：`MAX_RESULT_ROWS` / `MAX_RESULT_CHARS` 防止 Token 溢出
- **查询超时**：`QUERY_TIMEOUT_SECONDS` 防止慢查询
- **UNION 控制**：默认禁用，需配合白名单启用

### 关键组件

| 文件 | 职责 |
|------|------|
| `mcp_sql_server.py` | MCP 工具定义、安全验证、结果处理 |
| `sql_safety_checker.py` | SQL 语句解析和安全检查 |
| `db_adapter.py` | 数据库适配器抽象层（MySQL/SQLite 支持） |
| `start_server.py` | 服务启动、环境验证 |
| `skills/_lib/skill_loader.py` | 技能发现、YAML 解析、参数校验 (v3.0) |
| `skills/_lib/mutation_base.py` | 写操作技能抽象基类 (v3.0) |
| `skills/_lib/audit.py` | 写操作 JSONL 审计日志 (v3.0) |

## 设计理念
### 启发：基于LLM/Agents的用户界面
本项目的理念最早起源于2025年初，部分受到GraphQL的影响。最初是计划由LLM或Agents作为前端入口，通过明确的语义向后端获取信息。  
实际上，SQL语句本身就是良好的查询信息载体。与其传递GraphQL，不如进一步直接传递SQL。尤其在目前主流的LLM几乎都可以在不经额外微调的情况下，已能较稳定的生成常用的SQL。  
但在此基础上，需要考虑三个关键问题：
1. 潜在的SQL注入
2. LLM本身的不确定性：生成SQL的安全性
3. 生成SQL的查询准确性、查询质量和查询效率

**关于问题1：**  
此场景实际上并非“前端直接传递SQL给后端使用”的情况，LLM(Agents)在这里更类似于运行服务端在服务端的程序。所有的SQL，都是在服务端可控的环境下生成，通过stdio模式（当然也可以在安全的内网环境下使用HTTP方式）与其它后端服务通信。此场景中的Agents是可约束输入/输出的程序，与前端（外部用户）仅通过Prompt对接。而在2025年末的当下，防止Prompt注入已经是十分广泛且成熟的实践，Agents的编写者可以很轻松的用多种方法来避免外部Prompt注入。  
**关于问题2：**  
LLM的生成具有不确定性。即便有极小概率，这也会导致生成SQL的安全性无法得到保障。需要有SQL安全检查工具对生成的SQL进行检查和过滤。  
**关于问题3：**  
LLM(Agents)不能凭空生成SQL，需要有一定的上下文基础。这里的上下文可以是自然语言提示或数据库文档，但更重要的是数据库结构、查询示例以及数据本身。对于高质量的查询，就目前的情况来讲（截至2025年末），应当采用ReAct方案：即为推理 (Thought) --> 行动 (Action) --> 观察(Observation) --> 再思考决定下一步行动的循环。  
**总的来说，本项目是针对问题2和问题3的解决方案。**

### 项目演进
在早期，本项目的目标是编写一个简易的SQL安全检查工具，用于在执行前对SQL语句检查和过滤。作为方法供LLM(Agents)进行调用(FunctionCall)

- 之后，[在(v1.0)版本](LLM_TO_MCP_FEASIBILITY_ANALYSIS.md) 为了增加对标准化MCP服务架构的支持，对解决方案进行了重构。同时进行解耦，在增强安全性和可扩展性的同时简化维护。

- [在(v2.0)版本](REFACTORING_LOG.md) 针对实际的MCP使用场景，进行了查询效率和调用风险的优化。
  1. 通过工具合并以及增加新的常用工具，减少工具调用次数，优化工具调用效率。
  2. 聚焦于真实使用中的Token爆炸风险（这可能导致大量的LLM API费用支出）进行针对性优化。
  3. 同时新增了[多Agent调用该MCP服务的示例](README_ZH.md#autogen-多-agent-示例)，基于AutoGen框架，用于示范Agents与本服务的结合。

- [在(v2.1)版本](REFACTORING_LOG.md#latest-update-january-4-2026---tool-optimization--field-naming) 专注于工具设计和输出一致性的改进。优化并重构了大量工具，尽可能地遵守业界相关的最佳实践。整体设计上，采用ReAct方案推理 (Thought) --> 行动 (Action) --> 观察(Observation) --> 再思考决定下一步行动的循环范式。在保证查询效率的同时提升查询准确性和多步骤查询的质量。基于AutoGen的多agent调用示例也同步更新。

经过上述迭代，本项目从最初基于LLM/Agents的用户界面设想，演进到支持MCP的SQL综合查询服务。但需要承认的是，当前的项目虽然出发点不同，但实际上与目前的Text2SQL有所相似。  
在本项目构思初期（2025年3-4月），此类系统还是较为少见的。在当时，类似的Text2SQL实践主要还停留在：接收相关人员的提示，LLM单次生成SQL语句辅助其进行查询的背景下。而本项目的出发点不同，核心动机主要是 **使LLM(Agents)代替传统前端，成为新的“前端”，无论是界面中的数据还是界面本身，都能动态地与用户进行交互。** 让整个系统达到充分灵活且动态的效果。  
就目前来说，**本项目的核心思想是赋予LLM(Agents)进入数据库的能力。** 搭配不同的Agent，可以开发扩展出不同的工作场景。

### 项目路线图
**Agent Skills和扩展性**  
**Skills 扩展层已在 v3.0 版本中添加**（2026年3月）。详见 [MCP_AGENTS_SKILLS_DESIGN.md](MCP_AGENTS_SKILLS_DESIGN.md)。
同时计划对于本项目进行扩展性的提升。在现有的实践中我们认识到提供（封装成）具体的语义化工具的意义。业界也有对应的最佳实践论述：
> "Offload the burden from the model and use code where possible."  
> "Don't make the model fill arguments you already know."  
> "Combine functions that are always called in sequence."
> [— OpenAI, "Best practices for defining functions" (December 2025)](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions)

这说明在合理的情况下，一个实用的系统应该加入、并支持添加针对特定场景的额外工具。但是，过多的工具会占用更多上下文，并且会降低准确率/增加成本[1]。而Agent Skills的渐进式披露(progressive disclosure)[2]则可以避免这些问题。
因此，我们可以设想这样一个方案：用户或开发人员可以编写大量依赖于本MCP服务之上的"插件"（代码段/工具），通过skill_def.md管理，可以动态的增加与配置工具。而Agent则可以加载这些"插件"，灵活扩展其能力。

> [1]: ["Keep the number of functions small for higher accuracy."](https://platform.openai.com/docs/guides/function-calling)  
> [2]: ["This filesystem-based architecture enables progressive disclosure: Claude loads information in stages as needed, rather than consuming context upfront."](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#how-skills-work)

**多种类数据库支持（SQLite、NoSQL等）**  
- **SQLite 支持已在 v2.2 版本中添加**（2026年1月）
- NoSQL 支持计划在未来版本中提供

**人工定义的对数据库写入过程方法**  

**基于MCP协议细化权限管理**  

### 关于AI辅助开发(copilot, vibe-coding)的实践经验
本项目最初由Gemini CLI创建，在v1.0之后主要使用GitHub copilot进行开发。  
在使用AI辅助开发本项目的时候，基本遵循以下经验。
1. 尽可能的遵循web和GitHub上相关的最佳实践，比如Anthropic，Google，FastMCP和Microsoft等。避免幻觉和局部最优解的产生。
2. 尽可能使AI进行反思自己的输出。
3. 在满足1，2的前提下，尽可能减少对AI的约束。用最简洁的提示和步骤完成任务，并使AI完成完整的工作流。
> 对于上下文，要尽可能的保留充分完整；对于提示和约束，要尽量减少。

这就是本项目虽然保留了最初的GEMINI.md，但仅作为记录使用，并且也未增加AGENTS.md的原因。但skill_def.md或类似的"渐进式"文档是良好的实践。本项目的相关文档 [REFACTORING_LOG.md](REFACTORING_LOG.md) 和 [PROMPT_ENGINEERING_BEST_PRACTICES.md](PROMPT_ENGINEERING_BEST_PRACTICES.md) 体现了这一实践。

### 风险和局限
在编写本项目的实践中，使用了大量的AI辅助开发。尽管已经尽可能的review代码和进行测试，并添加了一系列安全设置。但精力有限，无法覆盖全部情况，尤其是考虑到有LLM参与其中的情况。  
**因此，不要在未经测试的情况下直接接入生产环境或与Agent搭配。这可能会导致意想不到的后果！**
贸然接入未经测试的Agent可能会导致 **不稳定、死循环、Token爆炸、巨量查询** 或其它未验证的负面影响。  
在近几次更新中，本项目进行了多次的效率优化，主要聚焦于减少不必要的工具调用次数和提升速度。并已经进行了一定的测试。但因为LLM(Agents)的随机性，在实际使用时，仍可能出现不必要的工具调用情况，尽管概率较小。  

### 已知问题和不足
- **行数相关字段可能不精确**：`list_tables()` / `describe_table()` / `get_full_schema()` 返回的 `row_count` 属于统计估计值：
  - **MySQL**：来自 `INFORMATION_SCHEMA.TABLES.TABLE_ROWS`（InnoDB 可能有明显偏差或滞后）
  - **SQLite**：来自 `sqlite_stat1`（如果已运行 ANALYZE）或采样策略
  - 仅建议用于“量级判断/是否加 LIMIT/是否大表”等策略，不应当作精确计数。
  - 如需精确行数，请使用 `SELECT COUNT(*) ...`，或启用 `ENABLE_TABLE_SUMMARY=1` 后使用 `get_table_summary(exact_count=True)`（注意大表可能较慢）。

- **为避免 Token 爆炸，返回结果可能被截断**：`query()`、`list_tables()`、`get_full_schema()` 会根据 `MAX_RESULT_ROWS` / `MAX_RESULT_CHARS` / `MAX_OVERVIEW_TABLES` / `MAX_SCHEMA_TABLES` 截断输出；因此“返回的数据/表/列”可能不是全量。需要全量时请显式使用更小范围的查询（加 `LIMIT`、按条件分页），或调整相关环境变量（风险自担）。

- **部分“总数”字段是“可见范围”语义**：例如 `total_tables` 在工具输出中表示“allowlist 参数过滤后的可见表数量（再考虑截断）”，并非一定等同于数据库实际总表数；请避免将其误读为“全库统计”。

### 使用本项目的最佳实践
- **推荐首先接入VS Code的GitHub Copilot进行试用。** VS Code中的GitHub Copilot是一个成熟的AI Agent工具，你可以选择免费模型（例如GPT-5 mini）在测试数据库中进行使用，这样安全性较高，同时可以避免额外的AI请求费用消耗。
- **在GitHub Copilot中使用的另一个好处是：可以赋予Copilot这种辅助编码AI进入数据库的能力，** 使其了解目标数据库的结构和数据分布。这在编写程序时可以提供更好的开发辅助和建议。
- **（以GitHub Copilot为例）在使用时，可以在提示中加上类似“为了回答的数据和理由准确充分，你需要一步一步，多次进行查询。”** 的提醒。这会引导AI进行多次逐步求精的，类似ReAct模式的查询，以获得更好的效果。这在解决复杂问题时尤为有用。
- **（以GitHub Copilot为例）在使用时显式的附加“#sql-safety-executor-mcp”工具，这样可以提醒AI优先使用该工具。** 

    ![tools](readme_pic/tools.png)
- **（以GitHub Copilot为例）善用Agent提供的“todo”工具**，这样可以让AI帮助计划查询步骤，提升性能和效率。

    ![todo](readme_pic/todo.png)
- 在最近的几次修改中（截至2026.1.7），进行了多次的安全优化，比如大数据量下的截断，特殊关键词的使用（比如union），表的白名单设置，针对不同配置的动态提示词等。但是 **更高的安全意味着更低的性能、效率和更高的消耗（比如更多的请求参数和Token消耗），因此请酌情配置安全性设置。**
- 实际上，Claude Code、Codex、Gemini CLI这样的AI客户端也与GitHub Copilot类似，但是 **应注意AI调用可能产生大量Token的费用问题。** 并且目前的测试（包括能力测试）主要集中在GitHub Copilot上完成。


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
3. 输入并选择 `MCP: Add Server`。

    ![MCP: Add Server](readme_pic/MCP:AddServer.png)
4. 根据引导一步一步添加上面的内容（请根据实际路径修改）。

实际上二者殊途同归，它们会生成一样位置的 `mcp.json` 文件。无论如何，您只需要保证 `.vscode` 中的 `mcp.json` 有以上配置即可。

#### 4. 验证与使用
1.  重启 VS Code，或使用 VS Code 命令面板重新加载窗口。
2.  打开 GitHub Copilot Chat ，确保处于Plan或Agent模式。
3.  点击输入框下方，模型选择框旁边的 **工具图标**。
4.  您应该能看到 `sql-safety-executor` 及其提供的工具 (如 `query`, `list_tables`)。确保它们已经被全部勾选。

    ![Add tools](readme_pic/Addtools.png)
5.  直接在对话中发送提问即可：“列出所有表”或“查询 users 表的前5行”。

    ![ask](readme_pic/ask.png)  
6. 之后可以看到 MCP 工具被调用。

    ![answer](readme_pic/answer.png) 

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
将服务器添加到您的 MCP 兼容客户端配置中（例如 VS Code、Claude Desktop 或其它 MCP 客户端）：

```json
{
  "mcpServers": {
    "sql-safety-executor-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["start_server.py"],
      "cwd": "/path/to/llm-sql-safety-executor-mcp"
    }
  }
}
```

- 将 `/path/to/` 替换为您的实际项目路径。
- 服务器从工作目录中的 `.env` 文件加载凭据。
- 对于虚拟环境，使用 Python 解释器的完整路径。

## 配置
位于.env文件中。需要先拷贝.env.example，重命名为.env以进行配置

### 数据库类型选择
```bash
# 数据库类型：'mysql'（默认）或 'sqlite'
DB_TYPE=mysql
```

### MySQL 配置（当 DB_TYPE=mysql 时使用）
```bash
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
DB_NAME=your_database_name
```

### SQLite 配置（当 DB_TYPE=sqlite 时使用）
```bash
# SQLite 数据库文件路径，或使用 ':memory:' 创建内存数据库
SQLITE_DATABASE_PATH=./sample_data/demo.db
# SQLITE_DATABASE_PATH=:memory:
```

> **注意 1：** `./sample_data/demo.db` 为示例数据库，适合测试场景。  
> **注意 2：** `SQLITE_DATABASE_PATH=:memory:` 会创建临时内存数据库（创建时数据库为空），服务重启后数据丢失，可用于测试和其他特殊用途。

```bash
# 可选：查询超时进度处理器间隔（默认：100）
# 较低的值 = 超时响应更快，但 CPU 开销更高
# SQLITE_PROGRESS_HANDLER_INTERVAL=100
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

# Skills 扩展 (v3.0)
ENABLE_SKILLS=0          # 主开关：启用 Skills 层（1=启用，0=禁用）
SKILLS_ALLOW_MUTATIONS=0 # 允许写操作技能（需要 ENABLE_SKILLS=1）
# SKILLS_DIR=skills/     # Skills 目录路径（相对或绝对）
# SKILLS_AUDIT_LOG=skills/_audit.jsonl  # 写操作审计日志（JSONL 格式）
# AGENT_ID=my-agent      # 审计日志中的 Agent 标识
```

**Skills 配置说明**：

Skills 层允许你将常用的 SQL 查询和数据变更操作封装为可复用的"技能"。默认关闭，不影响已有功能。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_SKILLS` | `0` | 主开关。设为 `1` 后注册 `list_skills` 和 `execute_query_skill` 工具 |
| `SKILLS_ALLOW_MUTATIONS` | `0` | 写操作开关。设为 `1` 后额外注册 `execute_mutation_skill` 工具，需要 `ENABLE_SKILLS=1` |
| `SKILLS_DIR` | `skills/` | 技能目录路径。必须位于项目根目录下（安全约束） |
| `SKILLS_AUDIT_LOG` | `skills/_audit.jsonl` | 写操作审计日志路径。每次 mutation 操作自动记录 |
| `AGENT_ID` | `unknown` | 审计日志中标识调用者的 Agent ID |

**典型配置场景**：

```bash
# 场景 1：仅启用只读查询技能（如 monthly-sales-report）
ENABLE_SKILLS=1
SKILLS_ALLOW_MUTATIONS=0

# 场景 2：同时启用查询和写操作技能（如 update-order-status）
ENABLE_SKILLS=1
SKILLS_ALLOW_MUTATIONS=1

# 场景 3：自定义技能目录和审计日志路径
ENABLE_SKILLS=1
SKILLS_ALLOW_MUTATIONS=1
SKILLS_DIR=my_custom_skills/
SKILLS_AUDIT_LOG=logs/skills_audit.jsonl
AGENT_ID=copilot-agent-1
```

> **安全提示**：`SKILLS_ALLOW_MUTATIONS` 是独立于 `ENABLE_SKILLS` 的第二层开关。即使 `ENABLE_SKILLS=1`，写操作默认仍然禁用，需要显式开启。这遵循最小权限原则。

### MCP 客户端集成
有关完整的客户端配置示例，请参阅 `mcp_config.json`。

## 更新日志

### v3.0 Skills 扩展层（2026年3月）

新增 Skills 扩展层 —— 预定义、参数化的 SQL 操作，用于结构化的 Agent 交互：

- **Skills 基础设施** (`skills/_lib/`)：
  - `skill_loader.py`：技能发现、YAML frontmatter 解析、参数校验、启动时 SQL 安全检查
  - `mutation_base.py`：实现 validate/preview/execute 模式的写操作抽象基类
  - `audit.py`：线程安全的 JSONL 审计日志，记录所有 mutation 操作
- **新增 MCP 工具**（通过 `ENABLE_SKILLS` 条件注册）：
  - `list_skills()`：渐进式披露 —— 返回技能元数据（名称、类型、风险、触发词）
  - `execute_query_skill(name, params)`：执行预审计的 SQL 模板，支持参数化绑定
  - `execute_mutation_skill(name, params, confirm)`：两阶段写操作（预览 → 确认）
- **安全模型**（`skills/SAFETY.md` 中 16 项）：模板即白名单、参数化查询、双层开关、错误脱敏
- **数据库适配器扩展**：`execute()` 新增可选 `params`、新增 `execute_write()` 方法
- **示例技能**：`monthly-sales-report`（查询）和 `update-order-status`（乐观锁写操作）
- **58 个新测试**：覆盖技能加载器、查询技能、写操作技能、审计日志
- **完全向后兼容**：`ENABLE_SKILLS=0`（默认）时零开销，不注册任何工具

设计详情参见 [MCP_AGENTS_SKILLS_DESIGN.md](MCP_AGENTS_SKILLS_DESIGN.md)。

### v2.2 SQLite 支持（2026年1月）

新增 SQLite 数据库支持，同时保持与 MySQL 的完全向后兼容：

- **新增数据库适配器架构**：引入 `db_adapter.py`，采用抽象基类模式
  - `DatabaseAdapter` ABC 定义所有数据库后端的统一接口
  - `MySQLAdapter`：保留所有现有 MySQL 功能
  - `SQLiteAdapter`：新增 SQLite 支持，带原生超时机制
  - `create_adapter()` 工厂函数自动选择适配器
- **SQLite 特定功能**：
  - 通过 `set_progress_handler()` 实现查询超时（SQLite 原生回调）
  - `StaticPool` 连接池（单连接，避免文件锁问题）
  - 使用 `sqlite_master` 和 `PRAGMA table_info()` 进行元数据查询
  - 行数估计使用 `sqlite_stat1` 或采样策略
- **新增环境变量**：
  - `DB_TYPE=mysql|sqlite` - 数据库类型选择（默认：mysql）
  - `SQLITE_DATABASE_PATH` - SQLite 文件路径或 `:memory:`
  - `SQLITE_PROGRESS_HANDLER_INTERVAL` - 超时检查频率
- **向后兼容**：所有现有 MySQL 配置继续正常工作
- **新增 `db_type` 字段**：工具响应现包含 `db_type` 字段标识当前数据库类型
- **完整测试套件**：53 个测试覆盖 MySQL 和 SQLite 适配器

详细设计决策、妥协和实现细节请参阅 [SQLITE_ADAPTER_DESIGN.md](SQLITE_ADAPTER_DESIGN.md)。变更日志详情请参阅 [REFACTORING_LOG.md](REFACTORING_LOG.md)。

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
  - 明确工具优先级：`query` 优先，其它仅在出错时使用
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

## 公开的 MCP 工具

该服务公开 5-10 个标准化的 MCP 工具（取决于配置）：

### 1. `query`（主要工具）
用途：执行带有自动安全验证的只读 SQL 查询

这是所有数据库操作的主要工具。安全验证是自动的 - 只允许经认证语句（SELECT、SHOW、DESCRIBE、EXPLAIN）。

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

### 8. `list_skills`（Skills 扩展，可选）
用途：列出所有可用的预定义技能（查询和写操作）。

**注意：** 需要 `ENABLE_SKILLS=1`。返回技能元数据，用于渐进式披露。

### 9. `execute_query_skill`（Skills 扩展，可选）
用途：执行预定义的查询技能，支持参数化 SQL。

**注意：** 需要 `ENABLE_SKILLS=1`。技能是预审计的 SQL 模板，绕过运行时 `is_sql_safe()` 检查。

输入：
```json
{
  "skill_name": "monthly-sales-report",
  "params": {"year": 2026, "month": 1}
}
```

### 10. `execute_mutation_skill`（Skills 扩展，可选）
用途：执行预定义的写操作技能，支持两阶段确认。

**注意：** 需要 `ENABLE_SKILLS=1` 和 `SKILLS_ALLOW_MUTATIONS=1`。遵循 validate → preview → execute 模式。

输入：
```json
{
  "skill_name": "update-order-status",
  "params": {"order_id": 42, "new_status": "shipped"},
  "confirm": false
}
```

`confirm=false`（默认）返回预览。`confirm=true` 执行写操作。

### Skills 扩展详解（v3.0）

Skills（技能）是预定义的、参数化的 SQL 操作，封装了常见的业务查询和数据变更逻辑。与核心工具 `query()` 允许 Agent 自由编写 SQL 不同，Skills 提供经过代码审查的 SQL 模板，Agent 只需传入参数即可执行，无需（也无法）自行编写 SQL。

**为什么需要 Skills？**
- **降低出错概率**：复杂的多表 JOIN、聚合查询容易出错，预定义模板确保 SQL 正确性
- **安全写操作**：核心工具仅支持只读查询（SELECT），Skills 通过严格的审计和确认机制支持写操作
- **效率提升**：Agent 无需多轮探索表结构再编写 SQL，一步调用即可完成
- **可扩展**：开发者可以根据业务需求自行添加新的 Skill

#### 示例 1：`monthly-sales-report`（查询技能）

**目标**：生成指定月份的每日销售汇总报告，包含日收入、订单数量和平均订单金额。

**目录结构**：
```
skills/monthly-sales-report/
├── skill_def.md    # 技能定义（YAML 元数据 + 使用说明）
└── query.sql       # SQL 模板
```

**`skill_def.md` 中的元数据**（YAML frontmatter）：
```yaml
name: monthly-sales-report
type: query              # 只读查询，不修改数据
risk: low                # 低风险
params:
  year: {type: int, required: true, description: "年份，如 2026"}
  month: {type: int, required: true, min: 1, max: 12, description: "月份 (1-12)"}
triggers:                # 关键词提示，帮助 Agent 匹配到此技能
  - monthly sales
  - revenue report
  - sales summary
```

**`query.sql` 内容**：
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

**调用方式**：Agent 通过 `execute_query_skill` 工具调用：
```json
{"skill_name": "monthly-sales-report", "params": "{\"year\": 2026, \"month\": 1}"}
```

**工作原理**：服务器启动时，`skill_loader.py` 扫描 `skills/` 目录，解析 `skill_def.md` 的 YAML frontmatter，并对 `query.sql` 进行安全检查（通过 `is_sql_safe()`）。运行时，Agent 传入参数 `year` 和 `month`，服务器通过 SQLAlchemy 的参数化绑定（`:year`、`:month`）安全地执行查询，防止 SQL 注入。

#### 示例 2：`update-order-status`（写操作技能）

**目标**：安全地更新订单状态，使用状态机约束防止非法转换（例如不能直接从 "pending" 跳到 "delivered"）。

**目录结构**：
```
skills/update-order-status/
├── skill_def.md                  # 技能定义
├── mutation.py                   # Python 逻辑（验证 + 预览 + 执行）
└── references/
    └── status-transitions.md     # 状态转换规则文档
```

**元数据**：
```yaml
name: update-order-status
type: mutation                     # 写操作
risk: medium                       # 中等风险
requires_confirmation: true        # 需要两阶段确认
params:
  order_id: {type: int, required: true, description: "订单 ID"}
  new_status: {type: str, required: true, 
    enum: [pending, confirmed, shipped, delivered, cancelled, returned],
    description: "目标状态"}
```

**状态转换规则**（内置于 `mutation.py`）：
```
pending    → confirmed, cancelled
confirmed  → shipped, cancelled
shipped    → delivered, returned
delivered  → returned
cancelled  → (终态，不可转换)
returned   → (终态，不可转换)
```

**两阶段调用流程**：

1. **预览**（`confirm=false`，默认）—— 只看不做：
```json
{"skill_name": "update-order-status", 
 "params": "{\"order_id\": 42, \"new_status\": \"shipped\"}",
 "confirm": false}
```
返回将要执行的 SQL 和预期影响，不实际修改数据。

2. **执行**（`confirm=true`）—— 确认后写入：
```json
{"skill_name": "update-order-status",
 "params": "{\"order_id\": 42, \"new_status\": \"shipped\"}",
 "confirm": true}
```

**安全机制**：
- **状态机验证**：`validate()` 检查当前状态是否允许转换到目标状态
- **乐观锁**：执行时使用 `WHERE status = :expected_status`，如果在预览和执行之间状态被其他人修改，则更新失败（返回 rowcount=0）
- **事务保护**：写操作在数据库事务中执行，失败时自动回滚
- **审计日志**：每次操作（无论成功失败）自动记录到 JSONL 审计文件

#### 如何添加自定义 Skill

**查询技能**（只读）：
1. 在 `skills/` 下创建目录，如 `skills/my-report/`
2. 编写 `skill_def.md`（YAML frontmatter + 说明文档）
3. 编写 `query.sql`（使用 `:param_name` 作为参数占位符）
4. 重启服务即可自动发现和注册

**写操作技能**（mutation）：
1. 同上创建目录和 `skill_def.md`（`type: mutation`）
2. 编写 `mutation.py`，定义 `Mutation` 类（继承 `MutationBase`）
3. 实现 `validate()`、`preview()`、`execute()` 三个方法
4. 设置 `SKILLS_ALLOW_MUTATIONS=1` 并重启服务

详细规范请参阅 [MCP_AGENTS_SKILLS_DESIGN.md](MCP_AGENTS_SKILLS_DESIGN.md) 和 [skills/SAFETY.md](skills/SAFETY.md)。


## 依赖要求

- Python 3.12+
- MySQL 或 SQLite 数据库
- 依赖：`sqlparse`、`SQLAlchemy>=2.0`、`PyMySQL`、`fastMCP`、`python-dotenv`、`pyyaml`

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

## 本项目的其它文档

- [Skills 设计文档](MCP_AGENTS_SKILLS_DESIGN.md)：v3.0 Skills 扩展层架构和设计决策
- [Skills 安全策略](skills/SAFETY.md)：面向技能作者的 16 项安全治理
- [可行性分析](LLM_TO_MCP_FEASIBILITY_ANALYSIS.md)：LLM 到 MCP 转换的详细分析
- [原始上下文](GEMINI.md)：项目背景和开发指南
- [重构日志](REFACTORING_LOG.md)：重构变更文档（v2.0 — v3.0）
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
