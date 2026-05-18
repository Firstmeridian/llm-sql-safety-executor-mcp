#!/usr/bin/env python3
"""
AutoGen Multi-Agent SQL Query System via MCP Server (v3.0)
基于 AutoGen 框架的多智能体 SQL 查询系统，通过 MCP 协议与数据库交互

This script demonstrates how to use AutoGen framework with a multi-agent team
to interact with the SQL Safety Checker MCP server using stdio transport.
本脚本演示如何使用 AutoGen 框架构建多智能体团队，通过 stdio 传输方式
与 SQL Safety Checker MCP 服务器交互。

v3.0 Updates (from autogen_sql_agent.py):
- Dynamic tool discovery: detects server capabilities at startup via list_tools()
- Skills extension support: list_skills, get_skill_detail, execute_query_skill, execute_mutation_skill
- SQLite compatibility: prompts no longer assume MySQL-only syntax
- Optional tools: sample(), get_table_summary() detected and included in prompts
- MCP server prompt fusion: fetches sql_assistant prompt as supplementary context
- Refactored: shared agent creation logic via _create_agents() helper

Architecture:
- PlanningAgent: Breaks down complex queries into subtasks
- SQLExecutorAgent: Executes SQL queries and skills via MCP tools
- AnalystAgent: Analyzes and interprets query results

Based on Microsoft AutoGen best practices:

v3.0 更新内容（相对于旧版 autogen_sql_agent.py）:
- 动态工具发现：启动时通过 list_tools() 检测服务器已注册的工具
- Skills 扩展支持：list_skills, get_skill_detail, execute_query_skill, execute_mutation_skill
- SQLite 兼容：提示词不再假设仅支持 MySQL 语法
- 可选工具：sample()、get_table_summary() 根据服务器配置自动检测
- MCP 服务器提示词融合：获取 sql_assistant 提示词作为补充上下文
- 重构：通过 _create_agents() 共享智能体创建逻辑

多智能体架构（三个 AI 智能体 + 一个人类用户）:
- PlanningAgent（规划智能体）: 将复杂查询拆分为子任务，协调团队
- SQLExecutorAgent（SQL 执行智能体）: 通过 MCP 工具执行 SQL 和 Skills
- AnalystAgent（分析智能体）: 分析和解读查询结果
- User（用户）: 人类用户，提供反馈、审批变更操作

基于 Microsoft AutoGen 最佳实践:
- https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html
- https://learn.microsoft.com/en-us/azure/aks/ai-toolchain-operator-mcp

MCP Server compatibility:
- Core tools: query, list_tables, describe_table, get_full_schema, check_connection
- Optional tools: sample (ENABLE_SCHEMA_TOOLS=1), get_table_summary (ENABLE_TABLE_SUMMARY=1)
- Skills tools: list_skills, get_skill_detail, execute_query_skill (ENABLE_SKILLS=1),
  execute_mutation_skill (SKILLS_ALLOW_MUTATIONS=1)

MCP 服务器工具兼容性:
- 核心工具（始终可用）: query, list_tables, describe_table, get_full_schema, check_connection
- 可选工具: sample (需 ENABLE_SCHEMA_TOOLS=1), get_table_summary (需 ENABLE_TABLE_SUMMARY=1)
- Skills 工具: list_skills, get_skill_detail, execute_query_skill (需 ENABLE_SKILLS=1),
  execute_mutation_skill (需 SKILLS_ALLOW_MUTATIONS=1)
"""

# ---------------------------------------------------------------------------
# 标准库导入
# ---------------------------------------------------------------------------
import asyncio          # 异步 I/O 框架，AutoGen 智能体通信基于 async/await
import logging          # 日志记录
import os               # 环境变量读取
import sys              # 系统参数（获取 Python 解释器路径等）
from dataclasses import dataclass, field  # 数据类装饰器，用于 ServerCapabilities
from typing import Any, Sequence          # 类型注解
from dotenv import load_dotenv            # 从 .env 文件加载环境变量

# ---------------------------------------------------------------------------
# AutoGen 框架导入
# ---------------------------------------------------------------------------
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
# AssistantAgent: AI 智能体（由 LLM 驱动）
# UserProxyAgent: 人类用户代理（接收键盘输入）

from autogen_agentchat.teams import SelectorGroupChat
# SelectorGroupChat: 带选择器的群聊，由 LLM 决定下一个发言的智能体

from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
# TextMentionTermination: 当消息中出现指定文本时终止对话
# MaxMessageTermination: 达到最大消息数时终止

from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
# 消息基类，用于 selector_func 的类型注解

from autogen_agentchat.ui import Console
# Console: 将智能体对话流式输出到终端

from autogen_ext.models.openai import OpenAIChatCompletionClient
# 兼容 OpenAI API 格式的 LLM 客户端（也支持 Gemini、Ollama 等）

from autogen_ext.tools.mcp import McpWorkbench, StdioServerParams
# McpWorkbench: MCP 工具工作台，将 MCP 服务器的工具暴露给智能体
# StdioServerParams: 通过标准输入/输出启动 MCP 服务器的参数

from autogen_core.models import ModelInfo
# ModelInfo: 描述模型能力的数据类（是否支持 vision、function_calling 等）

from autogen_core.model_context import BufferedChatCompletionContext, TokenLimitedChatCompletionContext
# BufferedChatCompletionContext: 限制发送给 LLM 的消息数量
# TokenLimitedChatCompletionContext: 限制发送给 LLM 的 token 数量

from autogen_core import CancellationToken
# CancellationToken: 支持优雅取消正在运行的任务

# =============================================================================
# Gemini Thinking Model Compatibility Patch
# Gemini 思维模型兼容性补丁
# =============================================================================
# Gemini 3 (and 2.5) thinking models return a `thought_signature` in function call
# responses that MUST be echoed back in subsequent requests (400 error otherwise).
# 背景：Gemini 3（及 2.5）思维模型在函数调用响应中会返回 `thought_signature`，
# 后续请求中**必须**原样回传此签名，否则会收到 400 错误。
#
# AutoGen's FunctionCall dataclass only has (id, arguments, name) — no extra_content
# field — so the signature is silently dropped during message round-tripping.
# 问题：AutoGen 的 FunctionCall 数据类只有 (id, arguments, name) 三个字段，
# 没有 extra_content 字段，导致签名在消息往返过程中被静默丢弃。
#
# Google's official workaround (https://ai.google.dev/gemini-api/docs/thought-signatures):
# Use a dummy value "skip_thought_signature_validator" to bypass validation.
# 解决方案：Google 官方建议使用虚拟值 "skip_thought_signature_validator" 绕过验证。
#
# This monkey-patch injects the dummy signature into every tool_call sent to the API,
# so Gemini thinking models work transparently with AutoGen.
# 实现方式：通过猴子补丁（monkey-patch）修改 AutoGen 的 func_call_to_oai 函数，
# 在每个发送给 API 的 tool_call 中注入虚拟签名，使 Gemini 思维模型能与 AutoGen 透明配合。
# =============================================================================
_GEMINI_THINKING_PATCH_ENABLED = False  # Global switch, only enabled for Gemini / 全局开关，仅在使用 Gemini 时启用

def _apply_gemini_thinking_patch() -> None:
    """Monkey-patch AutoGen's func_call_to_oai to inject dummy thought_signature.
    猴子补丁：修改 AutoGen 的 func_call_to_oai，注入虚拟 thought_signature。"""
    import autogen_ext.models.openai._message_transform as _mt
    _original = _mt.func_call_to_oai  # Save original function reference / 保存原始函数引用

    def _patched(message):  # type: ignore[no-untyped-def]
        result = _original(message)  # Call original first to get standard result / 先调用原始函数得到标准结果
        if _GEMINI_THINKING_PATCH_ENABLED:
            # Inject Google dummy signature to bypass thought_signature validation
            # 注入 Google 虚拟签名，绕过 thought_signature 校验
            result["extra_content"] = {  # type: ignore[typeddict-unknown-key]
                "google": {"thought_signature": "skip_thought_signature_validator"}
            }
        return result

    _mt.func_call_to_oai = _patched  # Replace original with patched function / 用补丁函数替换原始函数

# Apply patch at import time (only takes effect when _GEMINI_THINKING_PATCH_ENABLED=True)
# 程序启动时立即应用补丁（但只有 _GEMINI_THINKING_PATCH_ENABLED=True 时才生效）
_apply_gemini_thinking_patch()

# Configure logging / 配置日志级别
# WARNING = only show warnings and errors; change to INFO for more debug info
# WARNING = 只显示警告和错误，改为 INFO 可看到更多调试信息
logging.basicConfig(
    # level=logging.INFO,  # Uncomment for debugging / 调试时取消注释此行
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (API keys, database connections, etc.)
# 从 .env 文件加载环境变量（API 密钥、数据库连接等配置）
load_dotenv()

# =============================================================================
# LLM Configuration / LLM 配置（大语言模型客户端）
# =============================================================================
# Supports three LLM backends, checked in priority order:
# 支持三种 LLM 后端，按优先级依次检测：
# 1. Google Gemini (需 GEMINI_API_KEY)
# 2. OpenAI (需 OPENAI_API_KEY)
# 3. Local Ollama / 本地 Ollama (需 USE_OLLAMA=true)
# =============================================================================

def get_model_client() -> tuple[OpenAIChatCompletionClient, str]:
    """
    Configure the LLM client.
    配置并返回 LLM 客户端。
    Supports: Gemini, OpenAI, or local models (Ollama).
    支持: Gemini, OpenAI, 或本地模型 (Ollama)。
    
    Returns:
        Tuple of (model_client, model_name)
        元组 (model_client, model_name)，分别是 LLM 客户端实例和模型名称
    """
    # --- Option 1: Google Gemini / 方案 1：Google Gemini ---
    # Check for Gemini API key first / 优先检查 Gemini API 密钥
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if gemini_api_key:
        # model_name = "gemini-2.5-flash-lite-preview-09-2025"
        model_name = "gemini-3.1-flash-lite-preview"  # Switch to newer model / 可切换到更新的模型

        # Enable thought_signature patch for Gemini thinking models (3.x and 2.5.x)
        # 启用 thought_signature 补丁（Gemini 2.5+ 思维模型需要）
        global _GEMINI_THINKING_PATCH_ENABLED
        _GEMINI_THINKING_PATCH_ENABLED = True

        return OpenAIChatCompletionClient(
            model=model_name,
            api_key=gemini_api_key,
            # Gemini provides an OpenAI-compatible API endpoint
            # Gemini 提供了兼容 OpenAI API 格式的端点
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info=ModelInfo(
                vision=True,            # Supports image input / 支持图片输入
                function_calling=True,   # Supports function calling (needed for MCP tools) / 支持函数调用（MCP 工具需要）
                json_output=True,        # Supports JSON output / 支持 JSON 输出
                family="gemini-2.5-flash",
                structured_output=True,  # Supports structured output / 支持结构化输出
            )
        ), model_name
    
    # use GitHub models
    # GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    # if GITHUB_TOKEN:
    #     model_name = "openai/gpt-5-nano"
    #     return OpenAIChatCompletionClient(
    #         model=model_name,
    #         api_key=GITHUB_TOKEN,
    #         base_url="https://models.github.ai/inference",
    #         model_info=ModelInfo(
    #             vision=True,
    #             function_calling=True,
    #             json_output=True,
    #             family="gpt-5",
    #             structured_output=True,
    #         )
    #     ), model_name
    
    # --- Option 2: OpenAI / 方案 2：OpenAI ---
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        model_name = "gpt-4o-mini"
        return OpenAIChatCompletionClient(
            model=model_name,
            api_key=openai_api_key,
        ), model_name
    
    # --- Option 3: Local Ollama / 方案 3：本地 Ollama ---
    # Ollama is a local open-source model service, free but requires local resources
    # Ollama 是本地运行的开源模型服务，免费但需要本地资源
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")  # Default: Qwen 7B / 默认使用通义千问 7B
    if os.environ.get("USE_OLLAMA", "false").lower() == "true":
        return OpenAIChatCompletionClient(
            model=ollama_model,
            api_key="ollama",
            base_url=ollama_base_url,
            model_info=ModelInfo(
                vision=False,
                function_calling=True,
                json_output=True,
                family="unknown",
                structured_output=True,
            )
        ), ollama_model
    
    # --- No LLM configuration found, raise error / 没有找到任何 LLM 配置，报错 ---
    raise ValueError(
        "No LLM API key found. Please set one of the following environment variables:\n"
        "  - GEMINI_API_KEY (for Google Gemini)\n"
        "  - OPENAI_API_KEY (for OpenAI)\n"
        "  - USE_OLLAMA=true (for local Ollama)"
    )


# =============================================================================
# Server Capability Detection (v3.0)
# 服务器能力检测 (v3.0 新增)
# =============================================================================
# Dynamic tool discovery: detect which MCP tools the server has registered.
# 设计思路：动态发现 MCP 服务器的已注册工具。
# 
# This allows the agent prompts to adapt to any server configuration
# (ENABLE_SKILLS, ENABLE_SCHEMA_TOOLS, ENABLE_TABLE_SUMMARY, etc.)
# without hardcoding assumptions.
# 为什么要动态检测？
# 1. MCP 服务器的工具取决于 .env 配置（ENABLE_SKILLS、ENABLE_SCHEMA_TOOLS 等）
# 2. 不同配置下可用工具数量不同（5-10 个）
# 3. 如果在提示词中描述不存在的工具，LLM 会产生“幻觉工具调用”（调用不存在的工具）
#
# Reference: MCP Spec — "Servers define capabilities during initialization"
# Reference: Google Gemini — "Keep the number of functions small for higher accuracy"
#   → Only describe tools that actually exist, avoiding hallucinated tool calls
#   → 只向 LLM 描述实际存在的工具，避免幻觉工具调用
# =============================================================================

@dataclass
class ServerCapabilities:
    """
    Detected MCP server capabilities based on registered tools.
    服务器能力数据类，存储检测到的 MCP 服务器能力。
    
    Populated by detect_server_capabilities() at startup,
    then passed to prompt builder functions for dynamic prompt construction.
    在启动时由 detect_server_capabilities() 填充，
    然后传递给各个 prompt builder 函数来动态构建提示词。
    """
    tool_names: set[str] = field(default_factory=set)  # All registered tool names / 服务器上所有已注册工具的名称集合
    has_skills: bool = False              # list_skills exists / 是否有 list_skills 工具（ENABLE_SKILLS=1）
    has_skill_detail: bool = False        # get_skill_detail exists
    has_mutation_skills: bool = False      # execute_mutation_skill exists / 是否有 execute_mutation_skill 工具（SKILLS_ALLOW_MUTATIONS=1）
    has_sample: bool = False              # sample tool exists / 是否有 sample 工具（ENABLE_SCHEMA_TOOLS=1）
    has_table_summary: bool = False       # get_table_summary exists / 是否有 get_table_summary 工具（ENABLE_TABLE_SUMMARY=1）
    server_prompt: str = ""               # sql_assistant prompt from server (if available) / 从服务器获取的 sql_assistant 提示词文本


async def detect_server_capabilities(workbench: McpWorkbench) -> ServerCapabilities:
    """
    Detect MCP server capabilities by querying registered tools and prompts.
    检测 MCP 服务器能力。
    
    Called once at startup after McpWorkbench connects. The returned capabilities
    drive dynamic prompt construction — agents only learn about tools that actually
    exist on the server.
    在启动时 McpWorkbench 连接成功后调用一次。
    返回的 ServerCapabilities 对象驱动后续的动态提示词构建——
    智能体只会学习到服务器上实际存在的工具。
    
    Steps / 实现步骤：
    1. Call list_tools() to get all registered tools / 调用 list_tools() 获取所有已注册的工具列表
    2. Determine capabilities from tool names / 根据工具名称判断各项能力是否存在
    3. Try to fetch the server's sql_assistant prompt (optional) / 尝试获取服务器的 sql_assistant 提示词（可选）
    """
    caps = ServerCapabilities()
    
    # Step 1: Discover registered tools
    # 步骤 1：发现已注册的工具
    # ToolSchema is a TypedDict — use bracket notation t["name"], not t.name
    # 注意：ToolSchema 是 TypedDict 类型，必须用方括号 t["name"] 访问，不能用 t.name
    tools = await workbench.list_tools()
    caps.tool_names = {t["name"] for t in tools}  # Extract all tool names into a set / 提取所有工具名称到集合
    
    # Determine capabilities from tool names / 根据工具名称判断各项能力
    caps.has_skills = "list_skills" in caps.tool_names
    caps.has_skill_detail = "get_skill_detail" in caps.tool_names
    caps.has_mutation_skills = "execute_mutation_skill" in caps.tool_names
    caps.has_sample = "sample" in caps.tool_names
    caps.has_table_summary = "get_table_summary" in caps.tool_names
    
    logger.info(f"Detected {len(caps.tool_names)} tools: {sorted(caps.tool_names)}")
    
    # Step 2: Try to fetch the server's sql_assistant prompt
    # 步骤 2：尝试获取服务器的 sql_assistant 提示词
    # This prompt is dynamically generated based on server configuration
    # (UNION policy, Skills status, etc.) and provides decision rules
    # that stay in sync with the server automatically.
    # 这个提示词是服务器根据当前配置动态生成的（包含 UNION 策略、Skills 状态等），
    # 作为补充上下文提供给 SQLExecutorAgent，确保智能体的规则与服务器配置保持同步。
    try:
        prompt_result = await workbench.get_prompt("sql_assistant")
        if prompt_result.messages:
            # Extract text content from prompt messages
            # 提取提示词消息中的文本内容
            # PromptMessage.content is TextContent | ImageContent | ...
            # 只取 TextContent 和纯字符串类型
            from mcp.types import TextContent
            parts = []
            for msg in prompt_result.messages:
                if isinstance(msg.content, TextContent):
                    parts.append(msg.content.text)
                elif isinstance(msg.content, str):
                    parts.append(msg.content)
            caps.server_prompt = "\n".join(parts)
            logger.info("Fetched sql_assistant prompt from server")
    except Exception as e:
        # Prompt may not be registered — silent fallback, doesn't affect main flow
        # 提示词可能未注册——静默回退，不影响主流程
        logger.debug(f"Could not fetch sql_assistant prompt: {e}")
    
    return caps


# =============================================================================
# Dynamic Prompt Builders (v3.0)
# 动态提示词构建器 (v3.0 新增)
# =============================================================================
# Prompts are built dynamically based on detected server capabilities.
# This ensures agents only reference tools that actually exist, preventing
# hallucinated tool calls (a key concern with Gemini and other models).
# 核心设计：根据检测到的服务器能力动态构建提示词。
# 确保智能体只引用实际存在的工具，避免幻觉工具调用。
#
# Reference: Google Gemini — "use clear and descriptive function names and descriptions"
# Reference: Anthropic — "Give models less freedom for higher-stakes operations"
# Reference: Microsoft — "Be specific about what you want the model to do"
# =============================================================================

def build_planning_prompt(caps: ServerCapabilities) -> str:
    """
    Build PlanningAgent system prompt based on server capabilities.
    构建 PlanningAgent（规划智能体）的系统提示词。
    
    The planning agent coordinates the team. Its prompt must reflect
    which tools are available so it can plan appropriate workflows.
    规划智能体是团队的协调者，负责拆分任务、分配工作、跟踪进度。
    
    Dynamic sections based on capabilities / 根据服务器能力动态添加/省略的片段：
    - SKILLS WORKFLOW: only when has_skills=True / 仅当 has_skills=True 时加入
    - MUTATION SAFETY: only when has_mutation_skills=True / 仅当 has_mutation_skills=True 时加入
    - sample tool hint: only when has_sample=True / 仅当 has_sample=True 时加入
    """
    # --- Skills workflow section (conditional) ---
    # --- Skills 工作流片段（仅当服务器启用了 Skills 扩展时才加入） ---
    skills_section = ""
    if caps.has_skills:
        skills_section = """
SKILLS WORKFLOW:
- The server provides pre-defined skills (parameterized operations) that are safer and more efficient than raw SQL.
- When a user request matches a known skill, prefer using skills over writing raw SQL.
- First call list_skills(search/category/detail_level/available_only) to discover available operations.
- The default catalog hides skills that cannot execute in the current DB, mutation configuration, or schema readiness state; use available_only=false only for developer catalog review.
- If a full catalog entry has schema_ready=false or missing_tables, do not execute it unless the database/schema has been prepared.
- If list_skills returns a hint or omits params, call get_skill_detail(skill_name) before execution.
- For query skills: use execute_query_skill(name, params) — pre-audited SQL templates.
- Skills accept structured parameters — pass a params dict, not raw SQL.
"""
    
    # --- Mutation safety section (conditional) ---
    # --- 变更安全片段（仅当服务器启用了变更类 Skills 时才加入） ---
    # Two-phase workflow: preview then confirm, ensuring human approval
    # 变更操作采用两阶段工作流：先预览再确认，确保人类审批
    mutation_section = ""
    if caps.has_mutation_skills:
        mutation_section = """
MUTATION SAFETY (CRITICAL - TWO-PHASE WORKFLOW):
- Mutation skills modify the database. They MUST follow a two-phase workflow:
  Phase 1 (Preview): execute_mutation_skill(name, params, confirm=false)
    → Returns preview of planned changes. NO database modifications.
  Phase 2 (Execute): execute_mutation_skill(name, params, confirm=true)
    → Actually commits changes to the database.
- After Phase 1, you MUST present the preview result to the User for approval.
- ONLY proceed to Phase 2 after the User explicitly approves.
- NEVER skip the preview step or auto-confirm mutations.
- NEVER call confirm=true without User approval first.
"""

    # --- Sample tool hint (when server has sample tool, suggest using it instead of writing SELECT...LIMIT) ---
    # --- sample 工具提示（当服务器有 sample 工具时，建议用它代替手写 SELECT...LIMIT） ---
    sample_hint = ""
    if caps.has_sample:
        sample_hint = "\n- For quick data preview: ask SQLExecutorAgent to use sample(table_name) instead of writing SELECT...LIMIT"

    return f"""You are a planning agent that coordinates database query tasks.

Your job is to:
1. Break down complex user requests into smaller, manageable subtasks
2. Determine what database information is needed
3. Assign specific tasks to appropriate team members
4. Track progress and ensure all subtasks are completed

Your team members are:
- SQLExecutorAgent: Executes SQL queries and retrieves data from the database{" and can execute pre-defined skills" if caps.has_skills else ""}
- AnalystAgent: Analyzes query results and provides insights
- User: The human user who can provide clarification, feedback, or additional requirements

CRITICAL RULES - YOU MUST FOLLOW:
1. NEVER guess or fabricate data - only use information that SQLExecutorAgent has actually returned
2. NEVER assume table names, column names, or data values - always query first
3. When summarizing, use ONLY the exact data from query results - copy the actual values
4. If you haven't seen specific information from a query result, say "not yet queried" instead of making up data
5. Before making any claims about the database, verify you have seen that information in a tool result

EFFICIENCY RULES - AVOID DELAYS:
1. Do NOT say "I am waiting for results" - tool results appear immediately in conversation
2. If you see ToolCallExecutionEvent or FunctionExecutionResult in history, DATA HAS ARRIVED - process it immediately
3. When you see SQLExecutorAgent's response, proceed directly to next step - never pause
4. Give clear, specific instructions - not vague requests
5. Remind SQLExecutorAgent to use LIMIT clause for large tables
6. Ask for aggregated statistics (COUNT, AVG) instead of raw data when possible
7. Never request all data from large tables - always ask for samples or summaries

QUERY STRATEGY (Token Optimization - Google/Microsoft Best Practices):
- For unknown tables: First use list_tables() for overview, then describe_table() for details
- For multi-table JOINs: Use get_full_schema() to get all tables at once
- For large tables (is_large=true in response): Request COUNT(*) first, then sample with LIMIT
- Prefer aggregation queries (GROUP BY, COUNT, AVG) over raw data retrieval
- Never request SELECT * without LIMIT - always specify needed columns{sample_hint}
{skills_section}{mutation_section}
Workflow:
- Work step by step, planning multiple queries as needed
- First explore the database structure before answering questions
- Verify assumptions with actual data
- If the request is unclear or ambiguous, ask the User for clarification

When assigning tasks, be SPECIFIC:
- GOOD: "SQLExecutorAgent: Run SELECT COUNT(*) FROM users to get the total count"
- BAD: "SQLExecutorAgent: Query the users table"

After all subtasks are complete and you have sufficient data, summarize the findings.
In your summary, QUOTE the actual data returned by SQLExecutorAgent.

IMPORTANT: You cannot end the conversation yourself.
When the task is complete, present your final summary to the User and ask:
"The current analysis is complete. If you want to continue, provide additional requests. If you want to end the conversation, type TERMINATE."
If there is a pending mutation preview and the User says APPROVE, treat that as approval to continue the workflow, not as a request to end the conversation.
Only the User can say TERMINATE to end the conversation.
"""


def build_sql_executor_prompt(caps: ServerCapabilities) -> str:
    """
    Build SQLExecutorAgent system prompt based on server capabilities.
    构建 SQLExecutorAgent（SQL 执行智能体）的系统提示词。
    
    Only describes tools that are actually registered on the server,
    preventing the LLM from attempting to call non-existent tools.
    这是最复杂的提示词构建器，因为 SQL 执行智能体是直接操作工具的人，
    必须精确知道哪些工具可用。
    
    Dynamic sections / 动态片段：
    - Core tools list (always 5) / 核心工具列表（始终 5 个）
    - Optional tools: sample, get_table_summary / 可选工具
    - Skills tools: list_skills, get_skill_detail, execute_query_skill, execute_mutation_skill
    - Skills usage guide (including two-phase mutation workflow) / Skills 使用指南
    - Server prompt supplement (sql_assistant as extra context) / 服务器提示词补充
    
    Reference: Google Gemini — "Keep the number of functions small for higher accuracy"
    Reference: OpenAI — "Best practices for defining functions"
    """
    # --- Core tools (always available) ---
    # --- 核心工具（这 5 个工具始终可用） ---
    tools_section = """Available tools:

Core tools (always available):
1. query(sql) - Execute read-only SQL queries (SELECT only; use list_tables/describe_table for schema discovery)
2. list_tables() - Database overview with table names and row estimates
3. describe_table(table_name) - Single table columns + row estimate + is_large hint
4. get_full_schema() - All tables with columns (use for multi-table JOINs)
5. check_connection() - Verify database connectivity (use only on connection errors)"""

    # --- Optional tools (conditional) ---
    # --- 可选工具（根据服务器配置动态添加） ---
    tool_num = 6  # Continue numbering after core tools / 接着核心工具的编号继续
    if caps.has_sample:
        tools_section += f"""
{tool_num}. sample(table_name, limit) - Quick data preview from a table (max 20 rows, faster than writing SELECT)"""
        tool_num += 1
    
    if caps.has_table_summary:
        tools_section += f"""
{tool_num}. get_table_summary(table_name, exact_count) - Table summary with optional exact COUNT(*)"""
        tool_num += 1

    # --- Skills tools (conditional, only when server has Skills enabled) ---
    # --- Skills 工具（仅当服务器启用了 Skills 时才加入） ---
    skills_tools = ""
    if caps.has_skills:
        skills_tools = f"""

Skills tools (pre-defined parameterized operations):
{tool_num}. list_skills(search, category, detail_level, available_only) - List/search skills with compact, summary, or full metadata"""
        tool_num += 1
        if caps.has_skill_detail:
            skills_tools += f"""
{tool_num}. get_skill_detail(skill_name) - Get one skill's parameter schema before execution"""
            tool_num += 1
        skills_tools += f"""
{tool_num}. execute_query_skill(skill_name, params) - Execute a query skill with structured parameters"""
        tool_num += 1

        # Mutation tool: supports two-phase workflow (confirm=false preview, confirm=true execute)
        # 变更工具：支持两阶段工作流（confirm=false 预览, confirm=true 执行）
        if caps.has_mutation_skills:
            skills_tools += f"""
{tool_num}. execute_mutation_skill(skill_name, params, confirm) - Execute a mutation skill
   - confirm=false (default): Preview mode — validates and shows planned changes, NO database writes
   - confirm=true: Execute mode — commits changes after validation (requires prior user approval)"""
            tool_num += 1

    # --- Skills usage guide (tells the agent how to properly use Skills) ---
    # --- Skills 使用指南（告诉智能体如何正确使用 Skills） ---
    skills_guide = ""
    if caps.has_skills:
        skills_guide = """
SKILLS USAGE:
- Skills are pre-audited, parameterized operations — safer and more token-efficient than raw SQL.
- Use list_skills() to discover currently executable skills. Use search/category filters when the intent is clear.
- Use available_only=false only when explicitly auditing the full developer catalog.
- If list_skills() does not include params, call get_skill_detail(skill_name) before execute_query_skill or execute_mutation_skill.
- For query skills: call execute_query_skill(skill_name, params) with required parameters.
- Skill results have the same format as query() results (data, row_count, truncated).
"""
        # Two-phase workflow explanation for mutation Skills
        # 变更类 Skills 的两阶段工作流说明
        if caps.has_mutation_skills:
            skills_guide += """
MUTATION SKILLS (TWO-PHASE WORKFLOW):
- Mutations ALWAYS start with confirm=false (preview). Report the preview to PlanningAgent.
- PlanningAgent will present preview to User. Only call confirm=true after User approves.
- Never call confirm=true on your own initiative.
"""

    # --- Server prompt supplement (append sql_assistant prompt as extra context) ---
    # --- 服务器提示词补充（将服务器的 sql_assistant prompt 作为额外上下文添加） ---
    # Why "supplement" not "replace"? Because hand-written prompts contain AutoGen
    # multi-agent-specific rules (summarization, truncation, token optimization, etc.)
    # that aren't in the server prompt. Server prompt provides server-config-specific rules.
    # 为什么作为“补充”而非“替换”？
    # 因为手写提示词包含 AutoGen 多智能体专用规则（摘要、截断、token 优化等），
    # 这些在服务器 prompt 中没有。服务器 prompt 则提供服务器配置相关的规则。
    server_supplement = ""
    if caps.server_prompt:
        server_supplement = f"""

SERVER CONFIGURATION CONTEXT (auto-detected from MCP server):
{caps.server_prompt}
"""

    return f"""You are a SQL executor agent with access to database tools.

{tools_section}{skills_tools}

Note: describe_table returns row_count (estimated) and is_large flag. Use is_large hint to decide if LIMIT is needed.

DATABASE COMPATIBILITY:
- The database may be MySQL or SQLite. Schema discovery should use the dedicated tools
  (list_tables, describe_table, get_full_schema) rather than raw SQL like SHOW or DESCRIBE commands.
- Write portable SQL when possible. If a query fails due to database-specific syntax, try an alternative.

PRE-QUERY VALIDATION (Microsoft Azure Best Practices):
Before executing any SELECT query on data tables:
1. If table structure is unknown, use list_tables() first, then describe_table() for details
2. Check is_large flag in describe_table response - if true, use LIMIT or aggregation
3. Never fetch all rows from large tables - use sampling or aggregation
4. For multi-table JOINs, use get_full_schema() to get all tables at once

CRITICAL TOKEN OPTIMIZATION RULES:
1. ALWAYS use LIMIT clause in SELECT queries - default to LIMIT 20 unless user specifies otherwise
2. For large tables (>100 rows), first get COUNT(*), then retrieve samples with LIMIT
3. Never SELECT * without LIMIT - select only needed columns
4. Summarize large results - don't return raw data exceeding 20 rows
5. Use aggregation (COUNT, SUM, AVG, MAX, MIN) instead of returning all rows

Example of good queries:
- SELECT COUNT(*) FROM users;  -- Get count first
- SELECT id, name FROM users LIMIT 20;  -- Sample with limit
- SELECT status, COUNT(*) FROM orders GROUP BY status;  -- Aggregate instead of raw data

HANDLING TRUNCATED RESULTS:
The server automatically truncates large results to prevent token overflow.
When you see "truncated": true in the response:
1. Inform the user: "Results truncated to X/Y rows"
2. Suggest using LIMIT clause for precise control
3. Offer to run aggregation queries (COUNT, GROUP BY) for full data analysis
4. Do NOT request more data without LIMIT - it will be truncated again

CRITICAL: After EVERY tool call, you MUST:
1. Summarize the results in plain text (NOT raw JSON/data dump)
2. List only KEY information (not all rows)
3. For large datasets, provide statistics (count, sample, distribution)
4. If truncated, mention it and suggest alternatives
{skills_guide}
Step-by-Step Query Approach:
- Execute one query at a time
- Report results clearly and concisely
- If a query fails, explain the error and suggest alternatives
- For read-only queries: no INSERT, UPDATE, DELETE, DROP (use mutation skills for writes if available)

When you complete a query, report:
- The query executed (or skill invoked)
- Summary statistics (row count, key patterns, truncation status)
- Sample data (max 5-10 rows)
- Observations about the data

NEVER dump large result sets. Always summarize.
{server_supplement}"""


def build_analyst_prompt(caps: ServerCapabilities) -> str:
    """
    Build AnalystAgent system prompt based on server capabilities.
    构建 AnalystAgent（分析智能体）的系统提示词。
    
    分析智能体负责解读查询结果、发现模式、提供见解。
    When Skills are enabled, adds a note about skill result format.
    当服务器启用了 Skills 时，会添加 Skills 结果格式说明。
    """
    skills_note = ""
    if caps.has_skills:
        skills_note = """
Note on Skills results:
- Results from skills contain the same data format as regular queries (data, row_count, etc.)
- The skill_name field indicates which pre-defined operation produced the data
- Analyze skill results with the same rigor as raw query results
"""

    return f"""You are a data analyst agent that interprets query results.

Your responsibilities:
1. Analyze data returned by SQLExecutorAgent
2. Identify patterns, trends, and insights
3. Perform calculations when needed (percentages, averages, etc.)
4. Provide clear, actionable conclusions

IMPORTANT: Evidence-Based Analysis
- Base all conclusions on actual data from queries
- If you need more data to support your analysis, ask SQLExecutorAgent to run additional queries
- Clearly explain your reasoning and calculations
- Highlight any data quality issues or limitations
{skills_note}
When analyzing, provide:
- Summary of key findings
- Supporting data points
- Any caveats or limitations
"""


def build_selector_prompt(caps: ServerCapabilities) -> str:
    """
    Build SelectorGroupChat selector prompt based on server capabilities.
    构建 SelectorGroupChat 选择器提示词。
    
    Contains {roles}, {history}, {participants} placeholders filled by
    SelectorGroupChat framework at runtime.
    包含 {roles}、{history}、{participants} 等占位符，
    由 SelectorGroupChat 框架在运行时填充。
    
    When mutation skills are available, adds a rule:
    mutation preview must be routed to User for approval.
    当服务器启用了变更类 Skills 时，会添加一条规则：
    变更预览返回后必须路由到 User 进行审批。
    """
    mutation_rule = ""
    if caps.has_mutation_skills:
        mutation_rule = """
   - A MUTATION PREVIEW has been returned and needs user approval before confirm=true"""

    return f"""Select the next agent to perform a task.

Available agents and their roles:
{{roles}}

Current conversation:
{{history}}

Selection rules:
1. PlanningAgent should start by breaking down the task into subtasks
2. SQLExecutorAgent should execute database queries{" or skills" if caps.has_skills else ""} when data is needed
3. AnalystAgent should analyze results after data is retrieved
4. PlanningAgent should check progress after other agents complete their work
5. If more data is needed, return to SQLExecutorAgent
6. Select User when:
   - The task is ambiguous and needs clarification
   - Results need human approval before proceeding
   - The team needs additional context from the user
   - A decision point requires human judgment{mutation_rule}
    - THE TASK IS COMPLETE and the user must decide whether to continue with more requests or end with TERMINATE
7. If the latest User message says APPROVE, treat it as approval to continue the workflow, not as a request to terminate
8. After a User APPROVE message, prefer PlanningAgent so it can decide the next approved step

Select the next agent from {{participants}} based on what's needed to progress the task.
Only return the agent name.
"""


# =============================================================================
# Agent Factory (v3.0 — shared between main() and run_single_task())
# 智能体工厂 (v3.0 — main() 和 run_single_task() 共用)
# =============================================================================
# Extracts common agent creation logic to avoid code duplication.
# Both run modes (interactive / single-task) use the same agent configuration.
# 抽取共享的智能体创建逻辑，避免代码重复。
# 两种运行模式（交互式 / 单任务）都使用相同的智能体配置。
# =============================================================================

def _build_sql_executor_description(caps: ServerCapabilities) -> str:
    """Build SQLExecutorAgent description based on capabilities.
    根据服务器能力构建 SQLExecutorAgent 的描述文本。
    
    Used in SelectorGroupChat's {roles} placeholder to help the selector LLM
    understand each agent's capabilities.
    描述文本用于 SelectorGroupChat 的 {roles} 占位符，
    帮助选择器 LLM 理解每个智能体的能力。
    """
    desc = "An agent that executes SQL queries using database tools. Can list tables, describe schemas, and run SELECT queries."
    if caps.has_skills:
        desc += " Can also execute pre-defined query skills."
    if caps.has_mutation_skills:
        desc += " Supports mutation skills with two-phase preview/confirm workflow."
    return desc


def _create_agents(
    model_client: OpenAIChatCompletionClient,
    mcp_workbench: McpWorkbench,
    caps: ServerCapabilities,
    include_user_proxy: bool = True,
) -> dict[str, Any]:
    """
    Create all agents with capability-aware prompts.
    创建所有智能体（使用能力感知的提示词）。
    
    Extracts the common agent creation logic shared between main() and
    run_single_task(), avoiding code duplication.
    这是 main() 和 run_single_task() 共用的智能体工厂函数。
    
    Args:
        model_client: The LLM client / LLM 客户端
        mcp_workbench: Connected MCP workbench / 已连接的 MCP 工作台
        caps: Detected server capabilities / 检测到的服务器能力
        include_user_proxy: Whether to include UserProxyAgent (interactive mode)
                           是否包含用户代理（交互模式需要，单任务模式不需要）
    
    Returns:
        Dict with 'planning', 'sql_executor', 'analyst', and optionally 'user_proxy' agents
        包含 'planning', 'sql_executor', 'analyst' 和可选 'user_proxy' 的字典
    """
    # --- Create PlanningAgent / 创建 PlanningAgent（规划智能体） ---
    planning_agent = AssistantAgent(
        name="PlanningAgent",
        description="A planning agent that breaks down complex database queries into subtasks and coordinates the team.",
        model_client=model_client,
        system_message=build_planning_prompt(caps),  # Dynamic prompt / 动态提示词
    )
    
    # --- Create SQLExecutorAgent / 创建 SQLExecutorAgent（SQL 执行智能体） ---
    # Use TokenLimitedChatCompletionContext to prevent token explosion from large query results
    # 使用 TokenLimitedChatCompletionContext 限制上下文 token 数，防止大量查询结果导致 token 爆炸
    sql_agent_context = TokenLimitedChatCompletionContext(
        model_client=model_client,
        token_limit=16000,  # Context token limit / 上下文 token 上限
    )
    sql_executor_agent = AssistantAgent(
        name="SQLExecutorAgent",
        description=_build_sql_executor_description(caps),  # Dynamic description / 动态描述
        model_client=model_client,
        workbench=mcp_workbench,  # Connect MCP tools / 连接 MCP 工具（智能体可以调用服务器上的工具）
        reflect_on_tool_use=False,  # Disabled: Gemini thinking models intermittently fail tool_choice="none" constraint
                                    # 禁用工具使用反思（Gemini 思维模型会间歇性违反 tool_choice="none" 约束）
        max_tool_iterations=5,  # Allow multi-step tool use / 允许多步工具调用
        system_message=build_sql_executor_prompt(caps),  # Dynamic prompt / 动态提示词
        model_context=sql_agent_context,  # Limit context size / 限制上下文大小
    )
    
    # --- Create AnalystAgent / 创建 AnalystAgent（分析智能体） ---
    analyst_agent = AssistantAgent(
        name="AnalystAgent",
        description="A data analyst agent that interprets query results, identifies patterns, and provides insights.",
        model_client=model_client,
        system_message=build_analyst_prompt(caps),
    )
    
    # Collect all agents / 汇总所有智能体
    agents: dict[str, Any] = {
        "planning": planning_agent,
        "sql_executor": sql_executor_agent,
        "analyst": analyst_agent,
    }
    
    # Interactive mode needs UserProxy (receives keyboard input)
    # Single-task mode doesn't need it (no human to type APPROVE)
    # 交互模式下需要用户代理（接收键盘输入）
    # 单任务模式不需要（没有人类可以输入 APPROVE）
    if include_user_proxy:
        agents["user_proxy"] = UserProxyAgent(
            name="User",
            description=(
                "A human user who can provide feedback, ask follow-up questions, "
                "clarify requirements, or approve results. Select this agent when "
                "human input or clarification is needed."
            ),
        )
    
    return agents


# =============================================================================
# Selector Function / 智能体选择器函数
# =============================================================================
# SelectorGroupChat has two selection layers:
# SelectorGroupChat 有两层选择机制：
# 1. selector_func (hard rules): runs first, uses result if it returns an agent name
#    selector_func（硬规则）: 先执行，如果返回智能体名称则直接使用
# 2. selector_prompt + LLM (soft rules): when selector_func returns None, LLM decides
#    selector_prompt + LLM（软规则）: 当 selector_func 返回 None 时，用 LLM 决定
# =============================================================================

def create_selector_func(planning_agent_name: str):
    """Create a selector function that ensures PlanningAgent checks progress after each step.
    创建智能体选择器函数，确保 PlanningAgent 能在每步之后检查进度。
    
    Routing rules / 路由规则（按优先级）：
    1. Empty history → PlanningAgent starts / 历史为空 → PlanningAgent 开始
    2. Non-planning, non-user agent spoke → PlanningAgent reviews progress
       非规划/非用户智能体发言后 → PlanningAgent 审查进度
     3. User said APPROVE → PlanningAgent decides the approved next step
         用户输入 APPROVE → 回到 PlanningAgent 决定获批后的下一步
     4. PlanningAgent spoke 2+ times consecutively → force to User (break empty-message loops)
         PlanningAgent 连续发言 2+ 次 → 强制路由到 User（打破空消息循环）
     5. Otherwise → let LLM selector decide / 其他情况 → 返回 None，让 LLM 选择器决定
    """
    def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
        # Rule 1: Empty history, PlanningAgent starts
        # 规则 1：历史为空，由 PlanningAgent 开始
        if len(messages) == 0:
            return planning_agent_name
        
        last_source = messages[-1].source if hasattr(messages[-1], 'source') else None
        
        # Rule 2: After any non-planning agent speaks, return to planning agent to check progress
        # 规则 2：其他智能体（非规划、非用户）发言后，回到规划智能体检查进度
        if last_source and last_source != planning_agent_name and last_source != "User":
            return planning_agent_name

        # Rule 3: If the user explicitly says APPROVE, route back to PlanningAgent
        # so the team can continue the approved workflow instead of terminating.
        # 规则 3：如果用户明确输入 APPROVE，回到 PlanningAgent，
        # 让团队继续已批准的流程，而不是结束会话。
        if last_source == "User":
            last_content = getattr(messages[-1], "content", "")
            if isinstance(last_content, str) and last_content.strip().upper() == "APPROVE":
                return planning_agent_name
        
        # Rule 4: Detect consecutive PlanningAgent turns (empty-message loop breaker)
        # If PlanningAgent spoke 2+ times in a row, force route to User
        # to avoid burning message budget on empty completions.
        # 规则 4：检测 PlanningAgent 连续发言（空消息循环中断器）
        # 如果 PlanningAgent 连续发言 2+ 次，强制路由到 User，
        # 避免在空输出上浪费消息配额
        if last_source == planning_agent_name and len(messages) >= 2:
            prev_source = messages[-2].source if hasattr(messages[-2], 'source') else None
            if prev_source == planning_agent_name:
                return "User"
        
        # Rule 5: Return None, let LLM decide based on selector_prompt
        # 规则 5：返回 None，让 LLM 根据 selector_prompt 自行决定
        return None
    
    return selector_func


# =============================================================================
# Main Application / 主程序
# =============================================================================

def _print_capabilities(caps: ServerCapabilities) -> None:
    """Print detected server capabilities to console.
    将检测到的服务器能力打印到控制台，便于用户确认配置。"""
    print(f"  📦 Tools detected: {len(caps.tool_names)}")
    print(f"     Core: query, list_tables, describe_table, get_full_schema, check_connection")
    
    optional = []
    if caps.has_sample:
        optional.append("sample")
    if caps.has_table_summary:
        optional.append("get_table_summary")
    if optional:
        print(f"     Optional: {', '.join(optional)}")
    
    if caps.has_skills:
        skills_tools = ["list_skills", "execute_query_skill"]
        if caps.has_skill_detail:
            skills_tools.insert(1, "get_skill_detail")
        if caps.has_mutation_skills:
            skills_tools.append("execute_mutation_skill")
        print(f"     Skills: {', '.join(skills_tools)}")
    else:
        print("     Skills: disabled (set ENABLE_SKILLS=1 in .env to enable)")
    
    if caps.server_prompt:
        print("  📋 Server prompt: loaded (sql_assistant)")


def _build_example_tasks(caps: ServerCapabilities) -> list[str]:
    """Build example tasks list based on server capabilities.
    根据服务器能力构建示例任务列表（显示在交互式菜单中）。"""
    tasks = [
        "Check the database connection and list all available tables",
        "Describe the structure of all tables in the database",
        "Find the top 5 records from each table",
        "Analyze the data distribution across tables",
        "Generate a summary report of the database contents",
    ]
    
    if caps.has_skills:
        tasks.append("List available skills and their descriptions")
        if caps.has_mutation_skills:
            tasks.append("Show me available mutation skills and their workflows")
    
    return tasks


async def main() -> None:
    """
    Main function: run the Multi-Agent SQL Team in interactive mode.
    主函数：运行多智能体 SQL 团队（交互模式）。
    
    Flow / 流程：
    1. Start MCP server (via stdio transport) / 启动 MCP 服务器（通过 stdio 传输）
    2. Detect server capabilities / 检测服务器能力
    3. Create LLM client and agent team / 创建 LLM 客户端和智能体团队
    4. Enter interactive loop for user tasks / 进入交互式循环，用户可以输入任务
    """
    
    # Configure MCP server params (stdio transport – communicates via stdin/stdout)
    # 配置 MCP 服务器参数（使用 stdio 传输方式）
    # stdio transport: communicate with subprocess via stdin/stdout, no network needed
    # stdio 传输：通过标准输入/输出与子进程通信，无需网络配置
    mcp_server_params = StdioServerParams(
        command=sys.executable,  # Use current Python interpreter / 使用当前 Python 解释器
        args=["start_server.py"],  # MCP server startup script / MCP 服务器启动脚本
    )
    
    # Create MCP workbench and start session
    # 创建 MCP 工作台并启动会话
    # async with ensures server process is cleaned up on exit
    # 使用 async with 确保服务器进程在退出时被正确清理
    # Note: Ctrl+C triggers ExceptionGroup (InvalidStateError) during MCP actor cleanup,
    # this is a known AutoGen MCP library limitation, not our bug.
    # 注意：Ctrl+C 在 MCP actor 清理时会触发 ExceptionGroup (InvalidStateError)，
    # 这是 AutoGen MCP 库的已知限制，不是我们的 bug。
    try:
      async with McpWorkbench(mcp_server_params) as mcp_workbench:
        print("✅ MCP Server connected successfully!")
        
        # Detect server capabilities (v3.0 new feature)
        # 检测服务器能力 (v3.0 新增)
        caps = await detect_server_capabilities(mcp_workbench)
        
        # Get LLM client / 获取 LLM 客户端
        model_client, model_name = get_model_client()
        print(f"✅ Using LLM: {model_name}")
        
        # Print detected capabilities / 打印检测到的能力
        _print_capabilities(caps)
        
        # Create agent team using capability-aware prompts
        # 使用能力感知的提示词创建智能体团队
        agents = _create_agents(model_client, mcp_workbench, caps, include_user_proxy=True)
        planning_agent = agents["planning"]
        sql_executor_agent = agents["sql_executor"]
        analyst_agent = agents["analyst"]
        user_proxy = agents["user_proxy"]
        
        # --- Termination Conditions / 终止条件 ---
        # Best practice: only the user can terminate the conversation (human-in-the-loop)
        # 最佳实践：只有用户可以终止对话（人类在环路中）
        # Ref / 参考: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.html
        user_terminate = TextMentionTermination("TERMINATE", sources=["User"])  # User types TERMINATE / 用户输入 TERMINATE
        max_messages_termination = MaxMessageTermination(max_messages=30)        # Safety valve: max 30 messages / 安全阀值：最多 30 条消息
        termination = user_terminate | max_messages_termination                  # APPROVE means continue; TERMINATE ends / APPROVE 表示继续，TERMINATE 才结束
        
        # Create selector function (hard rules layer)
        # 创建选择器函数（硬规则层）
        selector_func = create_selector_func(planning_agent.name)
        
        # Create model context, limit messages sent to selector LLM
        # 创建模型上下文，限制发送给选择器 LLM 的消息数量
        # Prevent selector context from growing too large, wasting tokens
        # 避免选择器上下文过大导致 token 浪费
        model_context = BufferedChatCompletionContext(buffer_size=20)
        
        # --- Create SelectorGroupChat Team / 创建 SelectorGroupChat 团队 ---
        # SelectorGroupChat is a core AutoGen component:
        # SelectorGroupChat 是 AutoGen 的核心组件：
        # - Each turn, selector_func (hard rules) or LLM (soft rules) picks the next speaker
        #   每轮由 selector_func（硬规则）或 LLM（软规则）选择下一个发言的智能体
        # - The selected agent generates a reply (may include tool calls)
        #   被选中的智能体生成回复（可能包含工具调用）
        # - All agents share the conversation history
        #   所有智能体共享对话历史
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent, user_proxy],
            model_client=model_client,
            termination_condition=termination,
            max_turns=30,               # Extra safety limit: max 30 turns / 额外安全限制：最多 30 轮
            selector_prompt=build_selector_prompt(caps),  # Dynamic selector prompt / 动态选择器提示词
            selector_func=selector_func,  # Custom selector (ensures planner reviews progress) / 自定义选择器（确保规划智能体审查进度）
            allow_repeated_speaker=True,  # Allow same agent to speak consecutively / 允许同一智能体连续发言
            model_context=model_context,  # Limit selector context / 限制选择器上下文
        )
        
        # Interactive mode
        print("\n" + "=" * 60)
        print("Multi-Agent SQL Query Team - Powered by AutoGen & MCP")
        print("=" * 60)
        print("\nTeam Members:")
        print("  • PlanningAgent - Coordinates tasks and tracks progress")
        executor_desc = "  • SQLExecutorAgent - Executes database queries"
        if caps.has_skills:
            executor_desc += " and pre-defined skills"
        print(executor_desc)
        print("  • AnalystAgent - Analyzes results and provides insights")
        print("  • User - You! Can intervene, ask questions, or provide feedback")
        
        # Build example task list based on capabilities
        # 根据能力构建示例任务列表
        example_tasks = _build_example_tasks(caps)
        
        print("\nExample tasks:")
        for i, task in enumerate(example_tasks, 1):
            print(f"  {i}. {task}")
        
        print(f"\nEnter a task number (1-{len(example_tasks)}) or type a custom query:")
        print("Type 'q' to quit\n")
        
        # Flush stdin buffer to avoid ghost commands from leftover input
        # 清除标准输入缓冲区中的残留输入，避免幽灵命令
        # termios.tcflush works at the OS terminal driver level, clearing all
        # pending input including characters invisible to select() + timeout=0
        # termios.tcflush 在操作系统终端驱动层面工作，能清除
        # 所有等待处理的输入，包括 select() + timeout=0 看不到的字符
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            # ImportError (non-Unix), termios.error, or OSError (pipe input)
            # ImportError（非 Unix）、termios.error 或 OSError（管道输入）
            import select
            while select.select([sys.stdin], [], [], 0.0)[0]:
                sys.stdin.readline()
        
        while True:
            try:
                user_input = input(">>> ").strip()
                
                if user_input.lower() in ('q', 'quit', 'exit'):
                    print("Goodbye!")
                    break
                
                if not user_input:
                    continue
                
                # Check if input is an example task number
                # 检查是否输入了示例任务编号
                if user_input.isdigit():
                    task_idx = int(user_input) - 1
                    if 0 <= task_idx < len(example_tasks):
                        task = example_tasks[task_idx]
                    else:
                        print(f"Invalid task number. Please enter 1-{len(example_tasks)}")
                        continue
                else:
                    task = user_input
                
                print(f"\n📝 Executing task: {task}\n")
                print("-" * 60)
                
                # Run task with cancellation token for graceful interruption
                # 使用取消令牌运行任务，支持优雅中断
                cancellation_token = CancellationToken()
                stream = team.run_stream(
                    task=task,
                    cancellation_token=cancellation_token
                )
                # Console() streams agent conversation to terminal, output_stats=True shows statistics
                # Console() 将智能体对话流式输出到终端，output_stats=True 显示统计信息
                await Console(stream, output_stats=True)
                
                # Reset only after the entire interactive conversation has ended.
                # If the user keeps replying after the planning summary, the same
                # run_stream session continues with the existing conversation context.
                # 仅在整轮交互会话结束后才 reset。
                # 如果用户在规划总结后继续追问，同一次 run_stream 会继续沿用现有上下文。
                await team.reset()
                
                print("\n" + "=" * 60)
                print("Task completed. Enter a new task or 'q' to quit:")
                
            except KeyboardInterrupt:
                print("\n\nOperation interrupted. Goodbye!")
                logger.info("User interrupted the operation")
                break
            except (asyncio.CancelledError, GeneratorExit):
                print("\n\nOperation cancelled. Goodbye!")
                break
            except Exception as e:
                if "interrupt" in str(e).lower() or "cancel" in str(e).lower():
                    print("\n\nOperation interrupted. Goodbye!")
                    break
                print(f"\n❌ Error: {e}")
                logger.exception("Error during task execution")
                continue
        
        # Clean up LLM client resources / 清理 LLM 客户端资源
        await model_client.close()
    except KeyboardInterrupt:
        print("\n\nOperation interrupted during startup. Goodbye!")
    except BaseExceptionGroup:
        # Silently handle ExceptionGroup(InvalidStateError) from MCP actor cleanup on Ctrl+C
        # MCP actor 清理时 Ctrl+C 会触发 ExceptionGroup(InvalidStateError)，静默处理
        print("\n\nOperation interrupted. Goodbye!")


async def run_single_task(task: str) -> None:
    """
    Single-task mode: non-interactive execution of one task.
    单任务模式：非交互式执行单个任务。
    
    Suitable for scripting or testing. Differences from main():
    适用于脚本化或测试场景。与 main() 的区别：
    - No UserProxyAgent (no human to type APPROVE)
      不包含 UserProxyAgent（没有人类可以输入 APPROVE）
    - Only MaxMessageTermination as termination condition
      仅用 MaxMessageTermination 作为终止条件
    - Exits after completing the single task
      执行完单个任务后直接退出
    
    Args:
        task: The task/query string to execute / 要执行的任务/查询字符串
    """
    mcp_server_params = StdioServerParams(
        command=sys.executable,
        args=["start_server.py"],
    )
    
    async with McpWorkbench(mcp_server_params) as mcp_workbench:
        # Detect server capabilities / 检测服务器能力
        caps = await detect_server_capabilities(mcp_workbench)
        
        model_client, model_name = get_model_client()
        
        # Create agents (no user proxy since this is non-interactive mode)
        # 创建智能体（不包含用户代理，因为是非交互模式）
        agents = _create_agents(model_client, mcp_workbench, caps, include_user_proxy=False)
        planning_agent = agents["planning"]
        sql_executor_agent = agents["sql_executor"]
        analyst_agent = agents["analyst"]
        
        # Termination: only MaxMessageTermination (no user proxy, can't type APPROVE)
        # 终止条件：仅使用消息数量限制（无用户代理，无法输入 APPROVE）
        max_messages_termination = MaxMessageTermination(max_messages=30)
        termination = max_messages_termination
        
        # Create selector function / 创建选择器函数
        selector_func = create_selector_func(planning_agent.name)
        
        # Limit selector context size / 限制选择器上下文大小
        model_context = BufferedChatCompletionContext(buffer_size=20)
        
        # Create team (same config as main() but without user proxy)
        # 创建团队（与 main() 相同的配置，但不包含用户代理）
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent],
            model_client=model_client,
            termination_condition=termination,
            max_turns=30,
            selector_prompt=build_selector_prompt(caps),
            selector_func=selector_func,
            allow_repeated_speaker=True,
            model_context=model_context,
        )
        
        # Run task with cancellation token / 使用取消令牌运行任务
        cancellation_token = CancellationToken()
        stream = team.run_stream(
            task=task,
            cancellation_token=cancellation_token
        )
        await Console(stream, output_stats=True)
        
        # Clean up LLM client resources / 清理 LLM 客户端资源
        await model_client.close()


# =============================================================================
# Entry Point / 程序入口
# =============================================================================
# Two run modes supported / 支持两种运行方式：
# 1. python autogen_sql_agent_new.py          → Interactive mode / 交互模式
# 2. python autogen_sql_agent_new.py "query..." → Single-task mode / 单任务模式
if __name__ == "__main__":
    try:
        # Check CLI args: if task string provided, enter single-task mode
        # 检查命令行参数：如果提供了任务字符串，进入单任务模式
        if len(sys.argv) > 1:
            task = " ".join(sys.argv[1:])  # Join CLI args into task string / 将命令行参数拼接为任务字符串
            asyncio.run(run_single_task(task))
        else:
            # No args, enter interactive mode / 无参数，进入交互模式
            asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Ctrl+C exit / Ctrl+C 退出
    except BaseExceptionGroup:
        # Silently handle ExceptionGroup from MCP actor cleanup
        # 静默处理 MCP actor 清理时的异常组
        pass
