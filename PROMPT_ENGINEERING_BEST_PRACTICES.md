# Prompt Engineering Best Practices for MCP Tool Descriptions

This document summarizes best practices for designing prompts and tool descriptions in MCP (Model Context Protocol) servers, based on official guidelines from Microsoft, OpenAI, and industry research.

## Table of Contents

- [1. Core Principles](#1-core-principles)
- [2. Emoji Usage](#2-emoji-usage)
- [3. Formatting Guidelines](#3-formatting-guidelines)
- [4. Tool Description Design](#4-tool-description-design)
- [5. Before vs After Examples](#5-before-vs-after-examples)
- [6. References](#6-references)

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

Establish clear tool priority and usage rules:

```python
instructions="""SQL database assistant with READ-ONLY access.

TOOL PRIORITY:
1. query - PRIMARY. Use FIRST for all data requests.
2. list_tables - Only if query fails with "table not found"
3. describe_table - Only if query fails with "column not found"
4. check_connection - Only for connection errors

RULES:
- DO NOT call check_connection before queries
- DO NOT call list_tables/describe_table to explore
- START with query() for any data request

CORRECT: query("SELECT * FROM table WHERE condition")
WRONG: check_connection -> list_tables -> describe_table -> query"""
```

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

### Key Takeaways Summary

| Principle | Description |
|-----------|-------------|
| **Avoid Emojis** | Increases token consumption, may cause ambiguity |
| **Use Markdown/XML** | Models are trained on these formats extensively |
| **Be Specific** | "2-3 sentences" is better than "a few sentences" |
| **Say What TO DO** | Positive instructions outperform prohibitions |
| **Keep It Brief** | Long instructions cause latency and handling issues |
| **Use Separators** | `###`, `---`, `"""` help distinguish content blocks |

---

*Document created: December 2024*  
*Last updated: December 2024*
