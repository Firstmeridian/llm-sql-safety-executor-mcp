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
- Core tools: list_connections, query, list_tables, describe_table, get_full_schema, check_connection
- Connectivity diagnostics: check_connection with single/all scope
- Optional tools: sample (ENABLE_SCHEMA_TOOLS=1), get_table_summary (ENABLE_TABLE_SUMMARY=1)
- Skills tools: list_skills, get_skill_detail, execute_query_skill (ENABLE_SKILLS=1),
  execute_mutation_skill (SKILLS_ALLOW_MUTATIONS=1)

MCP 服务器工具兼容性:
- 核心工具（始终可用）: list_connections, query, list_tables, describe_table, get_full_schema, check_connection
- 连通性诊断: check_connection，通过 single/all scope 选择范围
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
from .prompts import ServerCapabilities, build_planning_prompt, build_sql_executor_prompt, build_analyst_prompt, build_selector_prompt, _build_sql_executor_description, _build_example_tasks
from dataclasses import dataclass, field  # 数据类装饰器，用于 ServerCapabilities
from typing import Any, Sequence          # 类型注解

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
# 2. 不同配置下可用工具数量不同（6-12 个）
# 3. 如果在提示词中描述不存在的工具，LLM 会产生“幻觉工具调用”（调用不存在的工具）
#
# Reference: MCP Spec — "Servers define capabilities during initialization"
# Reference: Google Gemini — "Keep the number of functions small for higher accuracy"
#   → Only describe tools that actually exist, avoiding hallucinated tool calls
#   → 只向 LLM 描述实际存在的工具，避免幻觉工具调用
# =============================================================================



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









# =============================================================================
# Agent Factory (v3.0 — shared between main() and run_single_task())
# 智能体工厂 (v3.0 — main() 和 run_single_task() 共用)
# =============================================================================
# Extracts common agent creation logic to avoid code duplication.
# Both run modes (interactive / single-task) use the same agent configuration.
# 抽取共享的智能体创建逻辑，避免代码重复。
# 两种运行模式（交互式 / 单任务）都使用相同的智能体配置。
# =============================================================================



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
    print(f"     Core: list_connections, query, list_tables, describe_table, get_full_schema, check_connection")
    
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




async def main(config, server_python) -> None:
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
        command=server_python,  # Use current Python interpreter / 使用当前 Python 解释器
        args=["-m", "sql_safety_executor", "serve", "--config", config],
        env=dict(os.environ),  # MCP server startup script / MCP 服务器启动脚本
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


async def run_single_task(task: str, config, server_python) -> None:
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
        command=server_python,
        args=["-m", "sql_safety_executor", "serve", "--config", config],
        env=dict(os.environ),
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
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--server-python", required=True, help="Python from the server's separate locked environment")
    parser.add_argument("task", nargs="?")
    options = parser.parse_args()
    config_path = str(options.config.resolve())
    try:
        asyncio.run(run_single_task(options.task, config_path, options.server_python) if options.task else main(config_path, options.server_python))
    except KeyboardInterrupt:
        pass
