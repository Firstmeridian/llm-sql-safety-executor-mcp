"""
Tests for MCP-facing Skills metadata disclosure.

These tests cover list_skills() projections, filtering, category aggregation,
and get_skill_detail(). They intentionally do not execute query or mutation
skills; execution behavior is covered by test_query_skills.py and
test_mutation_skills.py.
"""

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_LIB = PROJECT_ROOT / "skills" / "_lib"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SKILLS_LIB))


class DummyContext:
    """Minimal async context used to call FastMCP tool functions directly."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def info(self, message: str) -> None:
        self.messages.append(("info", message))

    async def warning(self, message: str) -> None:
        self.messages.append(("warning", message))

    async def error(self, message: str) -> None:
        self.messages.append(("error", message))


def create_demo_orders_table(module):
    """Create the minimal demo orders table required by bundled demo skills."""
    adapter = module.get_adapter()
    adapter.execute_write(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT,
            total_amount REAL,
            amount REAL,
            status TEXT
        )
        """,
        {},
    )


def disable_optional_skill_policies(monkeypatch):
    """Keep optional profile/audit policies stable across local .env files."""
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setenv("SKILLS_AUDIT_QUERIES", "0")
    monkeypatch.setenv("MAX_SQL_LENGTH", "20000")
    monkeypatch.setenv("MCP_TOOL_TIMEOUT_SECONDS", "120")


def configure_demo_sqlite_connection(monkeypatch):
    monkeypatch.setenv("DB_CONNECTIONS", "analytics_demo_sqlite")
    monkeypatch.setenv("DEFAULT_DB_CONNECTION", "analytics_demo_sqlite")
    monkeypatch.setenv("DB_ANALYTICS_DEMO_SQLITE_TYPE", "sqlite")
    monkeypatch.setenv(
        "DB_ANALYTICS_DEMO_SQLITE_SQLITE_DATABASE_PATH",
        ":memory:",
    )


@pytest.fixture
def skills_server(monkeypatch):
    """Import mcp_sql_server with Skills enabled and stable test settings."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.delenv("SKILLS_LIST_DEFAULT_DETAIL", raising=False)
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    # Avoid rewriting the generated human overview file during imports.
    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    create_demo_orders_table(module)
    yield module
    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)


def run_tool(coro):
    """Run an async MCP tool function in synchronous pytest tests."""
    result = asyncio.run(coro)
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    return result


def run_tool_result(coro):
    """Run an async MCP tool function and keep the raw ToolResult wrapper."""
    return asyncio.run(coro)


def test_list_default_summary_uses_env_default(skills_server):
    """Default list_skills() uses summary disclosure."""
    result = run_tool(skills_server.list_skills(ctx=DummyContext()))

    assert result["success"] is True
    assert result["detail_level"] == "summary"
    assert result["available_only"] is True
    assert result["current_database_type"] == "sqlite"
    assert result["schema_check_enabled"] is True
    assert result["schema_check_available"] is True
    assert result["total_skills"] == 4
    assert result["matched_catalog_skills"] == 4
    assert result["matched_skills"] == 1
    assert result["available_skills"] == 1
    assert result["unavailable_skills"] == 3
    assert result["filtered_unavailable_skills"] == 3
    assert result["schema_unready_skills"] == 0
    assert result["hint"]
    assert "not already known" in result["hint"]
    assert "detail_level='execution'" in result["hint"]

    report = result["skills"][0]
    assert report["name"] == "monthly-sales-report-sqlite"
    assert report["schema_ready"] is True
    assert "source" in report
    assert "triggers" in report
    assert report["profiles"] == ["demo"]
    assert "params" not in report


def test_default_availability_hides_missing_required_tables(monkeypatch):
    """available_only=true hides skills whose required tables are absent."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.delenv("SKILLS_LIST_DEFAULT_DETAIL", raising=False)
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        result = run_tool(module.list_skills(ctx=DummyContext()))
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["available_only"] is True
    assert result["matched_skills"] == 0
    assert result["available_skills"] == 0
    assert result["schema_unready_skills"] == 4
    assert result["filtered_unavailable_skills"] == 4


def test_list_compact_excludes_summary_fields(skills_server):
    """compact returns a lightweight but semantically useful catalog."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            detail_level="compact",
        )
    )

    skill = result["skills"][0]
    assert result["detail_level"] == "compact"
    assert {"name", "type", "description", "risk", "category", "executable"} <= set(skill)
    assert "source" not in skill
    assert "triggers" not in skill
    assert "params" not in skill


def test_list_full_includes_params_and_tables(skills_server):
    """full exposes cached parameter schema for execution planning."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            detail_level="full",
        )
    )

    report = next(s for s in result["skills"] if s["name"] == "monthly-sales-report-sqlite")
    assert "hint" not in result
    assert report["params"]["year"]["type"] == "int"
    assert report["version"] == "1.0"
    assert report["requires_confirmation"] is False
    assert "orders" in report["tables"]


def test_list_search_matches_description_and_is_case_insensitive(skills_server):
    """search matches description/triggers without requiring regex."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            search="REVENUE",
        )
    )

    assert result["matched_catalog_skills"] == 2
    assert result["matched_skills"] == 1
    assert result["skills"][0]["name"] == "monthly-sales-report-sqlite"


def test_list_search_no_match_returns_empty(skills_server):
    """No-match searches keep a structured empty result."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            search="definitely-not-a-skill",
        )
    )

    assert result["total_skills"] == 4
    assert result["matched_catalog_skills"] == 0
    assert result["matched_skills"] == 0
    assert result["skills"] == []
    assert result["categories"] == []


def test_list_category_filter_and_categories_aggregation(skills_server):
    """category filters exact category and reports filtered category counts."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            category="reporting",
        )
    )

    assert result["matched_catalog_skills"] == 2
    assert result["matched_skills"] == 1
    assert result["skills"][0]["name"] == "monthly-sales-report-sqlite"
    assert result["categories"] == [{"category": "reporting", "count": 1}]


def test_list_search_length_limit_rejects_overlong(skills_server):
    """Overlong search inputs are rejected before matching."""
    with pytest.raises(skills_server.ToolError):
        run_tool(
            skills_server.list_skills(
                ctx=DummyContext(),
                search="x" * 129,
            )
        )


def test_env_default_detail_full_applied(monkeypatch):
    """SKILLS_LIST_DEFAULT_DETAIL controls default disclosure."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.setenv("SKILLS_LIST_DEFAULT_DETAIL", "full")
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        create_demo_orders_table(module)
        result = run_tool(module.list_skills(ctx=DummyContext()))
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["detail_level"] == "full"
    assert "params" in result["skills"][0]


def test_per_call_detail_overrides_env(skills_server):
    """Explicit detail_level overrides the environment default."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            detail_level="compact",
        )
    )

    assert result["detail_level"] == "compact"


def test_get_skill_detail_returns_full_metadata(skills_server):
    """get_skill_detail returns full cached metadata for one skill."""
    result = run_tool(
        skills_server.get_skill_detail(
            skill_name="monthly-sales-report-sqlite",
            ctx=DummyContext(),
        )
    )

    assert result["success"] is True
    assert result["skill"]["name"] == "monthly-sales-report-sqlite"
    assert result["skill"]["params"]["month"]["max"] == 12
    assert result["skill"]["executable"] is True
    assert result["skill"]["schema_ready"] is True
    assert result["skill"]["profiles"] == ["demo"]
    assert result["schema_check_enabled"] is True
    assert "execute_query_skill" in result["usage_hint"]


def test_get_skill_detail_execution_returns_invocation_fields(skills_server):
    """execution projection omits catalog and readiness diagnostics."""
    result = run_tool(
        skills_server.get_skill_detail(
            skill_name="monthly-sales-report-sqlite",
            ctx=DummyContext(),
            detail_level="execution",
        )
    )

    assert set(result) == {
        "success",
        "skill",
        "connection_id",
        "current_database_type",
        "usage_hint",
    }
    assert set(result["skill"]) == {
        "name",
        "type",
        "params",
        "executable",
        "requires_confirmation",
    }
    assert result["skill"]["params"]["month"]["max"] == 12
    assert result["skill"]["executable"] is True
    assert result["skill"]["requires_confirmation"] is False


def test_get_skill_detail_execution_includes_disabled_reason(skills_server):
    """execution projection preserves the actionable rejection reason."""
    result = run_tool(
        skills_server.get_skill_detail(
            skill_name="monthly-sales-report",
            ctx=DummyContext(),
            detail_level="execution",
        )
    )

    assert result["skill"]["executable"] is False
    assert "not compatible" in result["skill"]["disabled_reason"]


def test_get_skill_detail_rejects_unknown_projection(skills_server):
    """get_skill_detail accepts only its backward-compatible projections."""
    with pytest.raises(skills_server.ToolError, match="execution, full"):
        run_tool(
            skills_server.get_skill_detail(
                skill_name="monthly-sales-report-sqlite",
                ctx=DummyContext(),
                detail_level="compact",
            )
        )


def test_get_skill_detail_marks_database_incompatible(skills_server):
    """Full details remain available for incompatible skills with a clear reason."""
    result = run_tool(
        skills_server.get_skill_detail(
            skill_name="monthly-sales-report",
            ctx=DummyContext(),
        )
    )

    assert result["skill"]["name"] == "monthly-sales-report"
    assert result["skill"]["executable"] is False
    assert "not compatible" in result["skill"]["disabled_reason"]
    assert "sqlite" in result["skill"]["disabled_reason"]


def test_available_only_false_returns_full_catalog(skills_server):
    """Developers can request the full discovered catalog explicitly."""
    result = run_tool(
        skills_server.list_skills(
            ctx=DummyContext(),
            available_only=False,
        )
    )

    names = [skill["name"] for skill in result["skills"]]
    assert names == [
        "monthly-sales-report",
        "monthly-sales-report-sqlite",
        "reset-demo-order-to-pending",
        "update-order-status",
    ]
    assert result["available_only"] is False
    assert result["matched_catalog_skills"] == 4
    assert result["matched_skills"] == 4
    assert result["available_skills"] == 1
    assert result["unavailable_skills"] == 3
    assert result["filtered_unavailable_skills"] == 0

    reset = next(
        skill
        for skill in result["skills"]
        if skill["name"] == "reset-demo-order-to-pending"
    )
    assert reset["databases"] == ["mysql", "sqlite"]

    mysql_report = next(skill for skill in result["skills"] if skill["name"] == "monthly-sales-report")
    assert mysql_report["executable"] is False
    assert "not compatible" in mysql_report["disabled_reason"]

    mutation = next(skill for skill in result["skills"] if skill["name"] == "update-order-status")
    assert mutation["executable"] is False
    assert "SKILLS_ALLOW_MUTATIONS=0" in mutation["disabled_reason"]


def test_excluded_profiles_hide_demo_skills_by_default(monkeypatch):
    """SKILLS_EXCLUDE_PROFILES makes matching profiles non-executable."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "demo")
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        create_demo_orders_table(module)
        result = run_tool(module.list_skills(ctx=DummyContext()))
        full_catalog = run_tool(module.list_skills(ctx=DummyContext(), available_only=False))
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["excluded_profiles"] == ["demo"]
    assert result["profile_excluded_skills"] == 4
    assert result["matched_skills"] == 0
    assert result["filtered_unavailable_skills"] == 4

    sqlite_report = next(
        skill for skill in full_catalog["skills"]
        if skill["name"] == "monthly-sales-report-sqlite"
    )
    assert sqlite_report["executable"] is False
    assert sqlite_report["profile_allowed"] is False
    assert sqlite_report["excluded_profiles"] == ["demo"]
    assert "SKILLS_EXCLUDE_PROFILES" in sqlite_report["disabled_reason"]


def test_profile_exclusion_blocks_direct_query_skill(monkeypatch):
    """Profile policy is enforced even when callers bypass discovery."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "demo")

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        create_demo_orders_table(module)
        with pytest.raises(module.ToolError, match="SKILLS_EXCLUDE_PROFILES"):
            run_tool(
                module.execute_query_skill(
                    skill_name="monthly-sales-report-sqlite",
                    params={"year": 2026, "month": 1},
                    ctx=DummyContext(),
                )
            )
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)


def test_query_skill_audit_is_opt_in(monkeypatch, tmp_path):
    """SKILLS_AUDIT_QUERIES records query metadata without result data."""
    disable_optional_skill_policies(monkeypatch)
    audit_log = tmp_path / "query_audit.jsonl"
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.setenv("SKILLS_AUDIT_QUERIES", "1")
    monkeypatch.setenv("SKILLS_AUDIT_LOG", str(audit_log))

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        create_demo_orders_table(module)
        adapter = module.get_adapter()
        adapter.execute_write(
            """
            INSERT INTO orders (id, order_date, total_amount, amount, status)
            VALUES (:id, :order_date, :total_amount, :amount, :status)
            """,
            {
                "id": 1,
                "order_date": "2026-01-15",
                "total_amount": 42.5,
                "amount": 42.5,
                "status": "pending",
            },
        )

        tool_result = run_tool_result(
            module.execute_query_skill(
                skill_name="monthly-sales-report-sqlite",
                params={"year": 2026, "month": 1},
                ctx=DummyContext(),
            )
        )
        result = tool_result.structured_content
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["success"] is True
    assert tool_result.meta["skill_name"] == "monthly-sales-report-sqlite"
    assert tool_result.meta["skill_type"] == "query"
    assert tool_result.meta["mode"] == "query"
    assert tool_result.meta["row_count"] == 1
    assert tool_result.meta["total_rows"] == 1
    assert tool_result.meta["truncated"] is False
    assert tool_result.meta["audit_logged"] is True
    assert "execution_ms" in tool_result.meta
    entry = json.loads(audit_log.read_text().strip())
    assert entry["skill_name"] == "monthly-sales-report-sqlite"
    assert entry["mode"] == "query"
    assert entry["success"] is True
    assert entry["rowcount"] == 1
    assert entry["total_rows"] == 1
    assert "data" not in entry


def test_env_available_only_default_can_show_full_catalog(monkeypatch):
    """SKILLS_LIST_AVAILABLE_ONLY_DEFAULT=0 restores full-catalog default listing."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.setenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", "0")
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        create_demo_orders_table(module)
        result = run_tool(module.list_skills(ctx=DummyContext()))
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["available_only"] is False
    assert result["matched_skills"] == 4


def test_mysql_database_hides_sqlite_skill_by_default(monkeypatch):
    """Default availability filtering follows the current DB_TYPE."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    monkeypatch.setenv("DB_TYPE", "mysql")
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "0")
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")
    try:
        monkeypatch.setattr(module, "_get_skill_schema_table_names", lambda _connection: {"orders"})
        result = run_tool(module.list_skills(ctx=DummyContext()))
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    assert result["current_database_type"] == "mysql"
    assert result["available_only"] is True
    assert [skill["name"] for skill in result["skills"]] == ["monthly-sales-report"]


def test_fastmcp_tool_schema_exposes_skill_parameters(monkeypatch):
    """list_tools exposes Agent-callable Skills parameters in MCP schema."""
    disable_optional_skill_policies(monkeypatch)
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    configure_demo_sqlite_connection(monkeypatch)
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "1")
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_args, **_kwargs: None)

    sys.modules.pop("mcp_sql_server", None)
    sys.modules.pop("db_adapter", None)
    sys.modules.pop("sql_safety_checker", None)
    module = importlib.import_module("mcp_sql_server")

    async def inspect_tools():
        from fastmcp import Client

        async with Client(module.mcp) as client:
            tools = await client.list_tools()
        return tools

    try:
        tools = run_tool(inspect_tools())
    finally:
        sys.modules.pop("mcp_sql_server", None)
        sys.modules.pop("db_adapter", None)
        sys.modules.pop("sql_safety_checker", None)

    schemas = {tool.name: tool.inputSchema for tool in tools}
    annotations = {tool.name: tool.annotations for tool in tools}

    list_props = schemas["list_skills"]["properties"]
    assert "available_only" in list_props
    assert list_props["available_only"]["anyOf"][0]["type"] == "boolean"

    raw_query_schema = schemas["query"]
    assert raw_query_schema["properties"]["sql"]["minLength"] == 1
    assert raw_query_schema["properties"]["sql"]["maxLength"] == module.MAX_SQL_LENGTH
    connection_description = raw_query_schema["properties"]["connection_id"]["description"]
    assert "exact aliases unchanged" in connection_description
    assert "never means all connections" in connection_description
    assert "discover aliases" in connection_description
    assert "match a database type" in connection_description
    assert "ambiguous" not in connection_description
    query_schema = schemas["execute_query_skill"]
    assert "params" in query_schema["properties"]
    assert "params" in query_schema["required"]

    detail_schema = schemas["get_skill_detail"]
    assert "detail_level" in detail_schema["properties"]
    detail_level_schema = detail_schema["properties"]["detail_level"]
    assert "execution (recommended)" in detail_level_schema["description"]
    assert {"execution", "full"} in [
        set(branch["enum"])
        for branch in detail_level_schema["anyOf"]
        if "enum" in branch
    ]

    mutation_schema = schemas["execute_mutation_skill"]
    assert "params" in mutation_schema["properties"]
    assert "confirm" in mutation_schema["properties"]
    assert mutation_schema["properties"]["confirm"]["type"] == "boolean"

    for tool_name, annotation in annotations.items():
        assert annotation is not None, tool_name
        assert annotation.openWorldHint is False, tool_name


def test_raw_query_rejects_over_max_sql_length(skills_server):
    """query(sql) rejects overlong SQL before database execution."""
    result = run_tool(
        skills_server.query(
            sql="SELECT " + "1" * skills_server.MAX_SQL_LENGTH,
            ctx=DummyContext(),
        )
    )

    assert result["success"] is False
    assert "too long" in result["error"]
    assert result["max_sql_length"] == skills_server.MAX_SQL_LENGTH


def test_get_skill_detail_unknown_raises(skills_server):
    """Unknown skill names return a ToolError."""
    with pytest.raises(skills_server.ToolError):
        run_tool(
            skills_server.get_skill_detail(
                skill_name="missing-skill",
                ctx=DummyContext(),
            )
        )


def test_get_skill_detail_validates_name(skills_server):
    """Invalid skill names are rejected before cache lookup."""
    with pytest.raises(skills_server.ToolError):
        run_tool(
            skills_server.get_skill_detail(
                skill_name="../../../etc/passwd",
                ctx=DummyContext(),
            )
        )


def test_mutation_skill_marked_non_executable_when_disabled(skills_server):
    """Mutation metadata remains visible but execution availability is explicit."""
    result = run_tool(
        skills_server.get_skill_detail(
            skill_name="update-order-status",
            ctx=DummyContext(),
        )
    )

    assert result["skill"]["type"] == "mutation"
    assert result["skill"]["executable"] is False
    assert "SKILLS_ALLOW_MUTATIONS=0" in result["skill"]["disabled_reason"]
    assert "disabled" in result["usage_hint"].lower()
