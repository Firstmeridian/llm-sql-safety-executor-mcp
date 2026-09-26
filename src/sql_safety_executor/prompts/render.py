"""Load reviewed text from installed package data, independently of cwd."""

from importlib.resources import files
from string import Template


def text(name: str) -> str:
    return (
        files("sql_safety_executor.prompts").joinpath(name).read_text(encoding="utf-8")
    )


def instructions(config) -> str:
    value = Template(text("server.md")).substitute(routing=text("routing.md"))
    if config.skills.mutation.mrtr.enabled:
        value += "\n" + text("mrtr.md")
    return value


def assistant(config) -> str:
    skills_info = ""
    if config.skills.enabled:
        skills_info = "\n- list_skills(search, category, detail_level, available_only, connection_id): Search pre-defined skills; full includes params\n- get_skill_detail(skill_name, connection_id, detail_level): Get params/schema for one known Skill\n- execute_query_skill(skill_name, params, connection_id): Execute a query skill with parameters\n"
        if config.skills.mutation.enabled:
            skills_info += "- execute_mutation_skill(skill_name, params, confirm, preview_token, connection_id): Preview a mutation on an authorized configured connection, then execute on the same connection with confirm=true plus the returned preview_token\n"
    value = Template(text("assistant.md")).substitute(
        routing=text("routing.md"),
        skills_info=skills_info,
        cross_table="UNION policy is connection-specific. Inspect the selected alias in list_connections(); query() and Query Skills enforce that target's policy.",
    )
    if config.skills.mutation.mrtr.enabled:
        value += "\n\n" + text("mrtr.md")
    return value
