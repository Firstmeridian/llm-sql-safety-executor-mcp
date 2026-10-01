"""Load reviewed text from installed package data, independently of cwd."""

from importlib.resources import files
from string import Template

from sql_safety_executor.core.connections import read_access_enabled

MAX_POLICY_LINES = 12


def text(name: str) -> str:
    return (
        files("sql_safety_executor.prompts").joinpath(name).read_text(encoding="utf-8")
    )


def connection_policies(config) -> str:
    """Summarize each connection's configured read and UNION policy without I/O."""
    lines = []
    aliases = sorted(config.connections)
    for alias in aliases[:MAX_POLICY_LINES]:
        connection = config.connections[alias]
        policy = connection.policy
        if not read_access_enabled(policy):
            lines.append(f"- {alias} ({connection.db_type}): reads disabled")
            continue
        scope = (
            "all tables"
            if policy.read_mode == "all"
            else f"allowlist of {len(policy.allowed_tables)} table(s)"
        )
        union = "UNION allowed" if policy.allow_union else "UNION disabled"
        lines.append(f"- {alias} ({connection.db_type}): reads {scope}; {union}")
    if len(aliases) > MAX_POLICY_LINES:
        lines.append(
            f"- {len(aliases) - MAX_POLICY_LINES} more connection(s): "
            "see list_connections()"
        )
    return "\n".join(lines)


def read_policy(config) -> str:
    return Template(text("read_policy.md")).substitute(
        connection_policies=connection_policies(config)
    )


def instructions(config) -> str:
    value = Template(text("server.md")).substitute(
        routing=text("routing.md"),
        read_policy=read_policy(config),
    )
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
        cross_table="UNION policy is connection-specific. Inspect the selected alias in list_connections() when needed; query() and Query Skills enforce that target's policy.\n\n" + read_policy(config),
    )
    if config.skills.mutation.mrtr.enabled:
        value += "\n\n" + text("mrtr.md")
    return value
