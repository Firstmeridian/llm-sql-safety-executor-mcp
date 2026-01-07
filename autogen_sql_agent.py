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
from autogen_core.model_context import BufferedChatCompletionContext, TokenLimitedChatCompletionContext
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
        model_name = "gemini-2.5-flash-lite-preview-09-2025"
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
- Never request SELECT * without LIMIT - always specify needed columns

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
"Task complete. Please type APPROVE to confirm, or provide additional requests."
Only the User can say TERMINATE or APPROVE to end the conversation.
"""

SQL_EXECUTOR_AGENT_PROMPT = """You are a SQL executor agent with access to database tools.

Available tools:
1. check_connection - Verify database connectivity (use only on connection errors)
2. list_tables - Database overview with table names and row estimates
3. describe_table - Single table columns + row estimate + is_large hint
4. query - Execute read-only SQL queries (SELECT, SHOW, DESCRIBE, EXPLAIN)
5. get_full_schema - All tables with columns (use for multi-table JOINs)

Note: describe_table returns row_count (estimated) and is_large flag. Use is_large hint to decide if LIMIT is needed.

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

Step-by-Step Query Approach:
- Execute one query at a time
- Report results clearly and concisely
- If a query fails, explain the error and suggest alternatives
- Only use read-only queries (no INSERT, UPDATE, DELETE, DROP)

When you complete a query, report:
- The query executed
- Summary statistics (row count, key patterns, truncation status)
- Sample data (max 5-10 rows)
- Observations about the data

NEVER dump large result sets. Always summarize.
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

def create_selector_func(planning_agent_name: str):
    """Create a selector function that ensures PlanningAgent checks progress after each step."""
    def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
        if len(messages) == 0:
            return planning_agent_name
        
        last_source = messages[-1].source if hasattr(messages[-1], 'source') else None
        
        # After any non-planning agent speaks, return to planning agent to check progress
        if last_source and last_source != planning_agent_name and last_source != "user":
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
        # Use TokenLimitedChatCompletionContext to prevent token explosion from large query results
        sql_agent_context = TokenLimitedChatCompletionContext(
            model_client=model_client,
            token_limit=16000,  # Limit context to prevent massive token usage
        )
        sql_executor_agent = AssistantAgent(
            name="SQLExecutorAgent",
            description="An agent that executes SQL queries using database tools. Can list tables, describe schemas, and run SELECT queries.",
            model_client=model_client,
            workbench=mcp_workbench,  # Connect MCP tools
            reflect_on_tool_use=True,  # Reflect on tool results
            system_message=SQL_EXECUTOR_AGENT_PROMPT,
            model_context=sql_agent_context,  # Limit context size
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
        selector_func = create_selector_func(planning_agent.name)
        
        # Create model context to limit token usage in selector
        # Best practice: Use BufferedChatCompletionContext to prevent context overflow
        model_context = BufferedChatCompletionContext(buffer_size=20)
        
        # Create the SelectorGroupChat team
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent, user_proxy],
            model_client=model_client,
            termination_condition=termination,
            max_turns=30,  # Best practice: Add max_turns as additional safety limit
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
            model_context=TokenLimitedChatCompletionContext(model_client=model_client, token_limit=16000),
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
        model_context = BufferedChatCompletionContext(buffer_size=20)
        
        # Create team
        team = SelectorGroupChat(
            participants=[planning_agent, sql_executor_agent, analyst_agent],
            model_client=model_client,
            termination_condition=termination,
            max_turns=30,
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
