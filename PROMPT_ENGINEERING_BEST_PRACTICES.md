# Prompt Engineering Best Practices for MCP Tool Descriptions

This document summarizes best practices for designing prompts and tool descriptions in MCP (Model Context Protocol) servers, based on official guidelines from Microsoft, OpenAI, Google, and industry research.

## Table of Contents

- [1. Core Principles](#1-core-principles)
- [2. Emoji Usage](#2-emoji-usage)
- [3. Formatting Guidelines](#3-formatting-guidelines)
- [4. Tool Description Design](#4-tool-description-design)
- [5. Before vs After Examples](#5-before-vs-after-examples)
- [6. References](#6-references)
- [7. Token Optimization for MCP Prompts](#7-token-optimization-for-mcp-prompts-added-december-2025)

---

## 1. Core Principles

### 1.1 Clear and Concise

Write instructions in clear and concise language that's easy to understand.

| ❌ Less Effective | ✅ Better |
|-------------------|-----------|
| "The description should be fairly short, a few sentences only, and not too much more." | "Use a 3 to 5 sentence paragraph to describe this product." |

### 1.2 Specific

Be specific about the context, outcome, length, format, and style.

| ❌ Less Effective | ✅ Better |
|-------------------|-----------|
| "Write a poem about OpenAI." | "Write a short inspiring poem about OpenAI, focusing on the recent DALL-E product launch, in the style of Shakespeare." |

### 1.3 Keep It Brief

> "Instructions that are too long can lead to latency, timeouts, or issues handling the prompt."  
> — Microsoft Copilot Studio

### 1.4 Say What TO DO, Not What NOT TO DO

Positive instructions are more effective than prohibitions.

| ❌ Less Effective | ✅ Better |
|-------------------|-----------|
| "DO NOT ASK FOR PERSONAL INFORMATION. DO NOT REPEAT." | "If the user asks for personal info, respond with 'I cannot help with that. Please visit our FAQ page.'" |

---

## 2. Emoji Usage

### Recommendation: Avoid Emojis in Production Prompts

| Source | Guidance |
|--------|----------|
| Microsoft Learn | Emoji meanings vary by language, culture, and social group - may cause misunderstanding |
| OpenAI Best Practices | All examples use plain text, no emojis |
| Prompting Guide | Emphasizes "clear" and "direct" communication, no emojis in examples |

### Reasons to Avoid Emojis

1. **Token consumption**: Emojis typically consume 2-4 tokens each
2. **Inconsistent interpretation**: Different models may interpret emojis differently
3. **Ambiguity in technical contexts**: Emojis add unnecessary ambiguity
4. **Localization issues**: Meanings vary across cultures and languages

---

## 3. Formatting Guidelines

### 3.1 Recommended Formats

Models are trained on large quantities of web content in XML and Markdown.

| Format | Use Case | Example |
|--------|----------|---------|
| **Markdown** | Structured content | `### Heading`, `- List`, `**Bold**` |
| **XML** | Separating blocks | `<instruction>`, `<context>` |
| **Separators** | Distinguishing content | `---`, `###`, `"""` |
| **UPPERCASE** | Emphasizing keywords | `RULES:`, `PRIORITY:` |

### 3.2 Prompt Structure Template

```
### Instruction ###
{Clear directive}

### Context ###
{Relevant background information}

### Examples ###
{Expected input/output examples}

### Constraints ###
{Limitations and rules}
```

---

## 4. Tool Description Design

### 4.1 For MCP Server Instructions

Provide clear tool priority while maintaining flexibility for LLM decision-making:

```python
instructions="""Database query assistant with READ-ONLY access.

Tools: query (primary), list_tables, describe_table, check_connection

Workflow:
- Known table structure: query directly
- Unknown structure: list_tables first, then query

Safe statements: SELECT, SHOW, DESCRIBE, EXPLAIN."""
```

**Key principles:**
- Concise over verbose (fewer tokens = faster, cheaper)
- Descriptive over restrictive (let LLM decide based on context)
- Clear primary tool indication without forbidding exploration
- Aligned with MCP spec: tools are "model-controlled"

### 4.2 For Tool Docstrings

Include:
- **Purpose**: What the tool does
- **When to use**: Specific conditions for using this tool
- **When NOT to use**: (Optional but helpful) Conditions to avoid
- **Args**: Parameter descriptions
- **Returns**: What the tool returns
- **Examples**: Concrete usage examples

---

## 5. Before vs After Examples

### Before (With Emojis, Verbose)

```
🤖 You are a helpful database assistant! 
📊 You can help users query data from the database.
⚠️ Remember: Only SELECT queries are allowed!
🔧 Available tools: query, list_tables, describe_table, check_connection
💡 Tip: Always check connection first before doing anything!
```

**Issues:**
- Emojis consume extra tokens
- No clear priority
- Encourages unnecessary tool calls ("check connection first")
- Vague instructions

### After (Following Best Practices)

```
SQL database assistant with READ-ONLY access.

TOOL PRIORITY:
1. query - PRIMARY. Use FIRST for all data requests.
2. list_tables - Only if query fails with "table not found"
3. describe_table - Only if query fails with "column not found"
4. check_connection - Only for connection errors

RULES:
- DO NOT call check_connection before queries
- START with query() for any data request
```

**Improvements:**
- No emojis
- Clear priority order
- Explicit rules about what to do
- Correct/Wrong examples for guidance

---

## 6. References

### Official Documentation

1. **Microsoft Learn - Prompt Engineering Techniques**
   - URL: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/prompt-engineering
   - Key points: Use clear syntax, Markdown/XML formatting, separators

2. **Microsoft Copilot Studio - Best Practices for Prompt Instructions**
   - URL: https://learn.microsoft.com/en-us/microsoft-copilot-studio/nlu-prompt-node
   - Key points: Be specific, keep it brief, give the agent a way out

3. **OpenAI - Best Practices for Prompt Engineering**
   - URL: https://help.openai.com/en/articles/6654000-best-practices-for-prompt-engineering-with-the-openai-api
   - Key points: Use separators (###, """), be specific, reduce fluffy descriptions

4. **Prompting Guide - General Tips for Designing Prompts**
   - URL: https://www.promptingguide.ai/introduction/tips
   - Key points: Start simple, be specific, avoid impreciseness

5. **OpenAI Function Calling Guide** (Added December 2025)
   - URL: https://platform.openai.com/docs/guides/function-calling
   - Key points: Token limits apply to function descriptions, keep descriptions concise

6. **Google Gemini Function Calling** (Added December 2025)
   - URL: https://ai.google.dev/gemini-api/docs/function-calling
   - Key points: "Token limits: function descriptions and parameters count toward input token limits"

### Key Takeaways Summary

| Principle | Description |
|-----------|-------------|
| **Avoid Emojis** | Increases token consumption, may cause ambiguity |
| **Use Markdown/XML** | Models are trained on these formats extensively |
| **Be Specific** | "2-3 sentences" is better than "a few sentences" |
| **Say What TO DO** | Positive instructions outperform prohibitions |
| **Keep It Brief** | Long instructions cause latency and handling issues |
| **Use Separators** | `###`, `---`, `"""` help distinguish content blocks |
| **Minimize Tool Descriptions** | Function descriptions count toward token limits |

---

## 7. Token Optimization for MCP Prompts (Added December 2025)

### Why Token Optimization Matters

Function/tool descriptions and prompts count toward input token limits. Verbose prompts:
- Increase latency
- Increase cost  
- May hit context limits in complex conversations

### Optimization Techniques

#### 7.1 Remove Redundancy

Tool information already in docstrings doesn't need to repeat in system prompts:

| ❌ Redundant | ✅ Optimized |
|--------------|-------------|
| "query(sql) - Execute SQL queries. Use for SELECT, SHOW..." | "query (primary)" |
| "list_tables() - List all database tables with row counts" | "list_tables" |

#### 7.2 Combine Related Instructions

| ❌ Verbose (5 lines) | ✅ Concise (1 line) |
|---------------------|---------------------|
| "Use JOINs for combining related tables. Use INNER JOIN or LEFT JOIN. Use aggregation instead of fetching all rows. Use COUNT, SUM, GROUP BY. Always include LIMIT." | "Use aggregation (COUNT/GROUP BY) over raw data. Use JOINs for related data." |

#### 7.3 Remove Examples from System Prompts

LLMs can infer usage from context. Examples should go in tool docstrings, not system prompts.

| ❌ With Examples | ✅ Without Examples |
|-----------------|---------------------|
| "Example: SELECT id FROM products UNION SELECT id FROM categories" | "UNION enabled (tables: customers, orders, products)" |

### Real-World Case Study: sql_assistant Prompt

**Before optimization:** ~306 tokens
```
Database query assistant with READ-ONLY access.

TOOLS:
1. query(sql) - PRIMARY. Execute SELECT, SHOW, DESCRIBE, EXPLAIN.
2. list_tables() - List available tables...
[... 20+ lines ...]
```

**After optimization:** ~94 tokens (69% reduction)
```
READ-ONLY SQL assistant. Tools: query (primary), get_full_schema, list_tables, describe_table, get_table_summary, sample.

Workflow: get_full_schema() first → query with LIMIT for large tables.
Guidelines: Use aggregation (COUNT/GROUP BY) over raw data. Use JOINs for related data.
Always show SQL in response.
```

**Key changes:**
1. Removed tool descriptions (redundant with docstrings)
2. Combined guidelines into single sentences
3. Removed examples
4. Used symbols (→) instead of words

### Token Budget Guidelines

| Prompt Type | Recommended Limit | Rationale |
|-------------|------------------|-----------|
| System instructions | < 100 tokens | Leave room for conversation |
| Tool docstrings | < 50 tokens each | Models read all tools |
| MCP prompts | < 150 tokens | May be included in context |

---

*Document created: December 2025*  
*Last updated: December 2025*
