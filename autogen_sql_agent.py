#!/usr/bin/env python3
"""
AutoGen Multi-Agent SQL Query System via MCP Server

This script demonstrates how to use AutoGen framework with a multi-agent team
to interact with the SQL Safety Checker MCP server using stdio transport.

Architecture:
- PlanningAgent: Breaks down complex queries into subtasks
- SQLExecutorAgent: Executes SQL queries via MCP tools
- AnalystAgent: Analyzes and interprets query results

Based on Microsoft AutoGen best practices:
- https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html
- https://learn.microsoft.com/en-us/azure/aks/ai-toolchain-operator-mcp
"""

import asyncio
import logging
import os
import sys
from typing import Sequence
from dotenv import load_dotenv

from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import McpWorkbench, StdioServerParams
from autogen_core.models import ModelInfo
from autogen_core.model_context import BufferedChatCompletionContext
from autogen_core import CancellationToken

# Configure logging
logging.basicConfig(
    # level=logging.INFO,
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# =============================================================================
# LLM Configuration
# =============================================================================

def get_model_client() -> tuple[OpenAIChatCompletionClient, str]:
    """
    Configure the LLM client.
    Supports: Gemini, OpenAI, or local models (Ollama).
    
    Returns:
        Tuple of (model_client, model_name)
    """
    # Check for Gemini API key first
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if gemini_api_key:
        model_name = "gemini-2.5-flash"
        return OpenAIChatCompletionClient(
            model=model_name,
            api_key=gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_info=ModelInfo(
                vision=True,
                function_calling=True,
                json_output=True,
                family="gemini-2.5-flash",
                structured_output=True,
            )
        ), model_name
    
    # Check for OpenAI API key
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        model_name = "gpt-4o-mini"
        return OpenAIChatCompletionClient(
            model=model_name,
            api_key=openai_api_key,
        ), model_name
    
    # Check for local Ollama
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
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
    
    raise ValueError(
        "No LLM API key found. Please set one of the following environment variables:\n"
        "  - GEMINI_API_KEY (for Google Gemini)\n"
        "  - OPENAI_API_KEY (for OpenAI)\n"
        "  - USE_OLLAMA=true (for local Ollama)"
    )


# =============================================================================
# SQL Agent System Prompts
# =============================================================================

PLANNING_AGENT_PROMPT = """You are a planning agent that coordinates database query tasks.

Your job is to:
1. Break down complex user requests into smaller, manageable subtasks
2. Determine what database information is needed
3. Assign specific tasks to appropriate team members
4. Track progress and ensure all subtasks are completed

Your team members are:
- SQLExecutorAgent: Executes SQL queries and retrieves data from the database
- AnalystAgent: Analyzes query results and provides insights
- User: The human user who can provide clarification, feedback, or additional requirements

## UNDERSTANDING TOOL RESULTS

IMPORTANT: When SQLExecutorAgent uses tools, the results appear in the conversation as:
- ToolCallExecutionEvent: Contains raw JSON data from the tool
- TextMessage from SQLExecutorAgent: Contains the summary of results

If you see a ToolCallExecutionEvent with data like:
`{"success":true,"data":[{"table_name":"test_users"}...]}`

This means the tool HAS ALREADY EXECUTED and returned data. Do NOT say you are "waiting" for results.

## CRITICAL RULES - YOU MUST FOLLOW:
1. NEVER guess or fabricate data - only use information that has been returned
2. NEVER assume table names, column names, or data values - always query first
3. When summarizing, use ONLY the exact data from query results - copy the actual values
4. If you see ToolCallExecutionEvent in the history, the data IS AVAILABLE - use it
5. Do NOT say "waiting for results" if tool execution events are visible in the conversation

Workflow:
- Work step by step, planning multiple queries as needed
- First explore the database structure before answering questions
- Verify assumptions with actual data
- If the request is unclear or ambiguous, ask the User for clarification

When assigning tasks, use this format:
1. <agent>: <specific task description>

After all subtasks are complete and you have sufficient data, summarize the findings.
In your summary, QUOTE the actual data returned by SQLExecutorAgent.

IMPORTANT: You cannot end the conversation yourself.
When the task is complete, present your final summary to the User and ask:
"Task complete. Please type APPROVE to confirm, or provide additional requests."
Only the User can say TERMINATE or APPROVE to end the conversation.
"""

SQL_EXECUTOR_AGENT_PROMPT = """You are a SQL executor agent with access to database tools.

Available tools:
1. check_connection - Verify database connectivity
2. list_tables - List all tables with row counts
3. describe_table - Get table structure (columns, types)
4. query - Execute read-only SQL queries (SELECT, SHOW, DESCRIBE, EXPLAIN)

## CRITICAL RESPONSE FORMAT

After EVERY tool call, you MUST respond with a clear text summary. Use this format:

=== Tool Result Summary ===
Tool executed: [tool name]
Status: Success/Failed

Results:
- [Key finding 1]
- [Key finding 2]
- [etc.]

Raw data: [paste relevant portions of the returned data]
===========================

## STRICT RULES

1. NEVER return an empty message - always write a summary
2. ALWAYS include the actual data values in your response
3. If the tool returns JSON, extract and list the key information
4. Execute one query at a time, report results, then wait for next instruction
5. Only use read-only queries (no INSERT, UPDATE, DELETE, DROP)
"""

ANALYST_AGENT_PROMPT = """You are a data analyst agent that interprets query results.

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

When analyzing, provide:
- Summary of key findings
- Supporting data points
- Any caveats or limitations
"""

SELECTOR_PROMPT = """Select the next agent to perform a task.

Available agents and their roles:
{roles}

Current conversation:
{history}

Selection rules:
1. PlanningAgent should start by breaking down the task into subtasks
2. SQLExecutorAgent should execute database queries when data is needed
3. AnalystAgent should analyze results after data is retrieved
4. PlanningAgent should check progress after other agents complete their work
5. If more data is needed, return to SQLExecutorAgent
6. Select User when:
   - The task is ambiguous and needs clarification
   - Results need human approval before proceeding
   - The team needs additional context from the user
   - A decision point requires human judgment
   - THE TASK IS COMPLETE and needs user approval (User must say APPROVE or TERMINATE)

Select the next agent from {participants} based on what's needed to progress the task.
Only return the agent name.
"""


# =============================================================================
# Main Application
# =============================================================================

def create_selector_func(planning_agent_name: str, sql_executor_name: str = "SQLExecutorAgent"):
    """
    Create a selector function that ensures proper conversation flow.
    
    Based on Microsoft AutoGen best practices:
    - PlanningAgent checks progress after specialized agents complete work
    - SQLExecutorAgent can continue if it returned an empty message (tool call without summary)
    - User agent is selected when task is complete
    """
    from autogen_agentchat.messages import ToolCallSummaryMessage, ToolCallExecutionEvent
    
    def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
        if len(messages) == 0:
            return planning_agent_name
        
        last_message = messages[-1]
        last_source = last_message.source if hasattr(last_message, 'source') else None
        
        # If SQLExecutorAgent just made a tool call but returned empty summary,
        # let it continue to produce a proper text summary
        if last_source == sql_executor_name:
            # Check if the last message is a ToolCallSummaryMessage with no content
            if isinstance(last_message, ToolCallSummaryMessage):
                content = last_message.content if hasattr(last_message, 'content') else ""
                if not content or content.strip() == "":
                    # Let SQLExecutorAgent try again to summarize
                    return sql_executor_name
        
        # After any non-planning agent speaks with actual content, return to planning agent
        if last_source and last_source != planning_agent_name and last_source != "User":
            return planning_agent_name
        
        # Let the model decide otherwise
        return None
    
    return selector_func



async def main() -> None:
    """Main function to run the Multi-Agent SQL Team."""
    
    # Configure MCP server parameters (stdio transport)
    mcp_server_params = StdioServerParams(
        command=sys.executable,  # Use current Python interpreter
        args=["start_server.py"],  # MCP server startup script
    )
    
    # Create MCP workbench and start the session
    async with McpWorkbench(mcp_server_params) as mcp_workbench:
        print("✅ MCP Server connected successfully!")
        
        # Get model client
        model_client, model_name = get_model_client()
        print(f"✅ Using LLM: {model_name}")
        
        # Create the Planning Agent (coordinator)
        planning_agent = AssistantAgent(
            name="PlanningAgent",
            description="A planning agent that breaks down complex database queries into subtasks and coordinates the team.",
            model_client=model_client,
            system_message=PLANNING_AGENT_PROMPT,
        )
        
        # Create the SQL Executor Agent (with MCP tools)
        sql_executor_agent = AssistantAgent(
            name="SQLExecutorAgent",
            description="An agent that executes SQL queries using database tools. Can list tables, describe schemas, and run SELECT queries.",
            model_client=model_client,
            workbench=mcp_workbench,  # Connect MCP tools
            reflect_on_tool_use=True,  # Reflect on tool results
            system_message=SQL_EXECUTOR_AGENT_PROMPT,
        )
        
        # Create the Analyst Agent (interprets results)
        analyst_agent = AssistantAgent(
            name="AnalystAgent",
            description="A data analyst agent that interprets query results, identifies patterns, and provides insights.",
            model_client=model_client,
            system_message=ANALYST_AGENT_PROMPT,
        )
        
        # Create User Proxy Agent for human intervention
        # This allows users to provide feedback, ask follow-up questions, or redirect the team
        user_proxy = UserProxyAgent(
            name="User",
            description="A human user who can provide feedback, ask follow-up questions, clarify requirements, or approve results. Select this agent when human input or clarification is needed.",
        )
        
        # Termination conditions
        # Best practice: Only user can terminate the conversation (human-in-the-loop)
        # Reference: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.html
        user_terminate = TextMentionTermination("TERMINATE", sources=["User"])
        user_approve = TextMentionTermination("APPROVE", sources=["User"])
        max_messages_termination = MaxMessageTermination(max_messages=30)
        termination = user_terminate | user_approve | max_messages_termination
        
        # Create the selector function
        selector_func = create_selector_func(planning_agent.name, sql_executor_agent.name)
        
        # Create model context to limit token usage in selector
        # Best practice: Use BufferedChatCompletionContext to prevent context overflow
        model_context = BufferedChatCompletionContext(buffer_size=10)
        
        # Create the SelectorGroupChat team
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent, user_proxy],
            model_client=model_client,
            termination_condition=termination,
            max_turns=15,  # Best practice: Add max_turns as additional safety limit
            selector_prompt=SELECTOR_PROMPT,
            selector_func=selector_func,  # Custom selector to ensure planning agent checks progress
            allow_repeated_speaker=True,  # Allow same agent to speak multiple times
            model_context=model_context,  # Limit context for selector model
        )
        
        # Interactive mode
        print("\n" + "=" * 60)
        print("Multi-Agent SQL Query Team - Powered by AutoGen & MCP")
        print("=" * 60)
        print("\nTeam Members:")
        print("  • PlanningAgent - Coordinates tasks and tracks progress")
        print("  • SQLExecutorAgent - Executes database queries")
        print("  • AnalystAgent - Analyzes results and provides insights")
        print("  • User - You! Can intervene, ask questions, or provide feedback")
        
        # Example tasks
        example_tasks = [
            "Check the database connection and list all available tables",
            "Describe the structure of all tables in the database",
            "Find the top 5 records from each table",
            "Analyze the data distribution across tables",
            "Generate a summary report of the database contents",
        ]
        
        print("\nExample tasks:")
        for i, task in enumerate(example_tasks, 1):
            print(f"  {i}. {task}")
        
        print("\nEnter a task number (1-5) or type a custom query:")
        print("Type 'q' to quit\n")
        
        while True:
            try:
                user_input = input(">>> ").strip()
                
                if user_input.lower() in ('q', 'quit', 'exit'):
                    print("Goodbye!")
                    break
                
                if not user_input:
                    continue
                
                # Check if it's a number (example task selection)
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
                
                # Run the task with cancellation support
                # Best practice: Use CancellationToken for graceful interruption
                cancellation_token = CancellationToken()
                stream = team.run_stream(
                    task=task,
                    cancellation_token=cancellation_token
                )
                await Console(stream, output_stats=True)
                
                # Reset for next task
                # Best practice: Always reset team state between tasks
                await team.reset()
                
                print("\n" + "=" * 60)
                print("Task completed. Enter a new task or 'q' to quit:")
                
            except KeyboardInterrupt:
                print("\n\nOperation interrupted. Goodbye!")
                logger.info("User interrupted the operation")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                logger.exception("Error during task execution")
                continue
        
        # Cleanup
        await model_client.close()


async def run_single_task(task: str) -> None:
    """
    Run a single task without interactive mode.
    Useful for scripting or testing.
    
    Args:
        task: The task/query to execute
    """
    mcp_server_params = StdioServerParams(
        command=sys.executable,
        args=["start_server.py"],
    )
    
    async with McpWorkbench(mcp_server_params) as mcp_workbench:
        model_client, model_name = get_model_client()
        
        # Create agents
        planning_agent = AssistantAgent(
            name="PlanningAgent",
            description="A planning agent that breaks down complex database queries into subtasks.",
            model_client=model_client,
            system_message=PLANNING_AGENT_PROMPT,
        )
        
        sql_executor_agent = AssistantAgent(
            name="SQLExecutorAgent",
            description="An agent that executes SQL queries using database tools.",
            model_client=model_client,
            workbench=mcp_workbench,
            reflect_on_tool_use=True,
            system_message=SQL_EXECUTOR_AGENT_PROMPT,
        )
        
        analyst_agent = AssistantAgent(
            name="AnalystAgent",
            description="A data analyst agent that interprets query results.",
            model_client=model_client,
            system_message=ANALYST_AGENT_PROMPT,
        )
        
        # Termination conditions - user-controlled
        user_terminate = TextMentionTermination("TERMINATE", sources=["User"])
        user_approve = TextMentionTermination("APPROVE", sources=["User"])
        max_messages_termination = MaxMessageTermination(max_messages=30)
        termination = user_terminate | user_approve | max_messages_termination
        
        # Create selector function
        selector_func = create_selector_func(planning_agent.name)
        
        # Create model context to limit token usage
        model_context = BufferedChatCompletionContext(buffer_size=10)
        
        # Create team
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent],
            model_client=model_client,
            termination_condition=termination,
            max_turns=15,
            selector_prompt=SELECTOR_PROMPT,
            selector_func=selector_func,
            allow_repeated_speaker=True,
            model_context=model_context,
        )
        
        # Run the task with cancellation support
        cancellation_token = CancellationToken()
        stream = team.run_stream(
            task=task,
            cancellation_token=cancellation_token
        )
        await Console(stream, output_stats=True)
        
        await model_client.close()


if __name__ == "__main__":
    # Check for command line task argument
    if len(sys.argv) > 1:
        # Run single task from command line
        task = " ".join(sys.argv[1:])
        asyncio.run(run_single_task(task))
    else:
        # Run interactive mode
        asyncio.run(main())
