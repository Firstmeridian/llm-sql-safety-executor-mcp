"""v3.4.2 regression coverage:

* **E1** — assert every base tool returns ``ToolResult`` with the documented
  ``meta`` shape (``tool_name``, ``db_type``, ``execution_ms``, ``success``,
  plus tool-specific counters where applicable).
* **E2** — assert ``execute_query_skill`` and ``execute_mutation_skill`` expose
  a populated MCP ``outputSchema`` via ``list_tools``.
* **E3** — assert the opt-in tool telemetry middleware records one JSONL line
  per ``tools/call`` when invoked through the real FastMCP ``Client`` path.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SKILLS_LIB = PROJECT_ROOT / "skills" / "_lib"
if _SKILLS_LIB.is_dir() and str(_SKILLS_LIB) not in sys.path:
    sys.path.insert(0, str(_SKILLS_LIB))


class _DummyContext:
    async def info(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    async def warning(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    async def error(self, message: str) -> None:  # pragma: no cover - trivial
        pass


def _reload_server(monkeypatch, **env):
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", ":memory:")
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setenv("SKILLS_AUDIT_QUERIES", "0")
    monkeypatch.setenv("MAX_SQL_LENGTH", "20000")
    monkeypatch.setenv("MCP_TOOL_TIMEOUT_SECONDS", "120")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(mod, None)

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_a, **_k: None)
    return importlib.import_module("mcp_sql_server")


def _seed_demo_table(module):
    adapter = module.get_adapter()
    adapter.execute_write(
        """
        CREATE TABLE IF NOT EXISTS widgets (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            qty INTEGER
        )
        """,
        {},
    )
    adapter.execute_write(
        "INSERT INTO widgets (name, qty) VALUES (:n, :q)",
        {"n": "alpha", "q": 3},
    )
    adapter.execute_write(
        "INSERT INTO widgets (name, qty) VALUES (:n, :q)",
        {"n": "beta", "q": 5},
    )


def _seed_orders_table(module):
    adapter = module.get_adapter()
    adapter.execute_write(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT,
            total_amount REAL,
            amount REAL,
            status TEXT NOT NULL
        )
        """,
        {},
    )
    adapter.execute_write(
        """
        INSERT INTO orders (id, order_date, total_amount, amount, status)
        VALUES (:id, :order_date, :total_amount, :amount, :status)
        """,
        {
            "id": 1,
            "order_date": "2026-01-15",
            "total_amount": 100.0,
            "amount": 100.0,
            "status": "pending",
        },
    )


def _seed_schema_projection_tables(module):
    adapter = module.get_adapter()
    for table_name, default_value in (
        ("schema_twin_a", "alpha"),
        ("schema_twin_b", "alpha"),
        ("schema_variant", "beta"),
    ):
        adapter.execute_write(
            f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL DEFAULT '{default_value}',
                amount REAL
            )
            """,
            {},
        )


# ─────────────────────────────── E1 ──────────────────────────────────


def _assert_common_meta(meta: dict, expected_tool: str) -> None:
    assert meta["tool_name"] == expected_tool, meta
    assert meta["db_type"] in ("sqlite", "mysql"), meta
    assert isinstance(meta["connection_id"], str), meta
    assert isinstance(meta["execution_ms"], (int, float)), meta
    assert meta["execution_ms"] >= 0, meta
    assert isinstance(meta["success"], bool), meta


@pytest.fixture
def base_server(monkeypatch):
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="0",
        ENABLE_SCHEMA_TOOLS="1",
        ENABLE_TABLE_SUMMARY="1",
    )
    _seed_demo_table(module)
    yield module
    for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(mod, None)


def test_meta_query_success(base_server):
    result = asyncio.run(
        base_server.query(sql="SELECT id, name FROM widgets ORDER BY id", ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "query")
    assert result.meta["success"] is True
    assert result.meta["row_count"] == 2
    assert result.meta["total_rows"] == 2
    assert result.meta["truncated"] is False


def test_meta_list_connections(base_server):
    result = asyncio.run(base_server.list_connections(ctx=_DummyContext()))
    _assert_common_meta(result.meta, "list_connections")
    assert result.meta["success"] is True
    assert result.structured_content["default_connection_id"] == result.meta["connection_id"]


def test_meta_query_rejected_unsafe(base_server):
    """B1 invariant: an unsafe-SQL rejection must report success=False in meta."""
    result = asyncio.run(base_server.query(sql="DROP TABLE widgets", ctx=_DummyContext()))
    _assert_common_meta(result.meta, "query")
    assert result.meta["success"] is False


def test_meta_check_connection(base_server):
    result = asyncio.run(base_server.check_connection(ctx=_DummyContext()))
    _assert_common_meta(result.meta, "check_connection")
    assert result.meta["success"] is True


def test_meta_list_tables(base_server):
    result = asyncio.run(base_server.list_tables(ctx=_DummyContext()))
    _assert_common_meta(result.meta, "list_tables")
    assert result.meta["success"] is True
    assert result.meta["returned_table_count"] >= 1
    assert result.meta["total_tables"] >= 1
    assert "get_full_schema(detail_level='compact') directly" in (
        result.structured_content["hint"]
    )


def test_table_discovery_error_is_not_reported_as_empty_schema(base_server, monkeypatch):
    adapter = base_server.get_adapter()

    def fail_metadata():
        raise base_server.MetadataQueryError("listing tables")

    monkeypatch.setattr(adapter, "get_tables", fail_metadata)

    for tool in (base_server.list_tables, base_server.get_full_schema):
        result = asyncio.run(tool(ctx=_DummyContext()))
        _assert_common_meta(result.meta, tool.__name__)
        assert result.meta["success"] is False
        assert result.structured_content["success"] is False
        assert result.structured_content["error_code"] == "metadata_query_failed"
        assert "tables" not in result.structured_content
        assert "schema" not in result.structured_content

    async def _call_over_mcp():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            return await client.call_tool("get_full_schema", {"detail_level": "compact"})

    protocol_result = asyncio.run(_call_over_mcp())
    protocol_content = protocol_result.structured_content
    assert isinstance(protocol_content, dict)
    assert protocol_content["success"] is False
    assert protocol_content["error_code"] == "metadata_query_failed"
    assert "schema_groups" not in protocol_content


def test_meta_describe_table(base_server):
    result = asyncio.run(
        base_server.describe_table(table_name="widgets", ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "describe_table")
    assert result.meta["success"] is True


def test_single_table_tools_preserve_unavailable_row_estimate(
    base_server,
    monkeypatch,
):
    """Unknown estimates must not be presented as zero or as a small table."""
    class RecordingContext(_DummyContext):
        def __init__(self):
            self.info_messages = []

        async def info(self, message: str) -> None:
            self.info_messages.append(message)

    adapter = base_server.get_adapter()
    monkeypatch.setattr(adapter, "get_row_estimate", lambda _table_name: None)

    tools = [base_server.describe_table]
    if hasattr(base_server, "get_table_summary"):
        tools.append(base_server.get_table_summary)

    for tool in tools:
        ctx = RecordingContext()
        result = asyncio.run(tool(table_name="widgets", ctx=ctx))
        payload = result.structured_content

        assert payload["success"] is True
        assert payload["row_count"] is None
        assert payload["row_count_approximate"] is None
        assert payload["is_large"] is None
        assert "recommendation" not in payload
        assert "row_count" not in result.meta
        assert "is_large" not in result.meta
        assert any("unknown rows" in message for message in ctx.info_messages)
        assert all("~None" not in message for message in ctx.info_messages)

    exact = asyncio.run(
        base_server.get_table_summary(
            table_name="widgets",
            exact_count=True,
            ctx=_DummyContext(),
        )
    ).structured_content
    assert exact["row_count"] == 2
    assert exact["row_count_approximate"] is False
    assert exact["is_large"] is False


def test_column_metadata_error_is_not_reported_as_not_found(base_server, monkeypatch):
    adapter = base_server.get_adapter()

    def fail_metadata(_table_name):
        raise base_server.MetadataQueryError("reading table columns")

    monkeypatch.setattr(adapter, "get_columns", fail_metadata)

    for tool in (base_server.describe_table, base_server.get_table_summary):
        result = asyncio.run(
            tool(table_name="widgets", ctx=_DummyContext())
        )
        _assert_common_meta(result.meta, tool.__name__)
        assert result.meta["success"] is False
        assert result.structured_content["error_code"] == "metadata_query_failed"
        assert "not found" not in result.structured_content["error"].lower()

    result = asyncio.run(
        base_server.get_full_schema(ctx=_DummyContext(), detail_level="compact")
    )
    _assert_common_meta(result.meta, "get_full_schema")
    assert result.meta["success"] is False
    assert result.structured_content["error_code"] == "metadata_query_failed"
    assert "schema_groups" not in result.structured_content


def test_get_full_schema_distinguishes_unsupported_discovered_identifier(base_server):
    adapter = base_server.get_adapter()
    adapter.execute_write('CREATE TABLE "odd-name" (id INTEGER PRIMARY KEY)', {})

    table_result = asyncio.run(base_server.list_tables(ctx=_DummyContext()))
    odd_table = next(
        table
        for table in table_result.structured_content["tables"]
        if table["table_name"] == "odd-name"
    )
    assert odd_table["row_count"] is None
    assert "null means an estimate is unavailable" in (
        table_result.structured_content["hint"]
    )

    result = asyncio.run(
        base_server.get_full_schema(ctx=_DummyContext(), detail_level="compact")
    )

    _assert_common_meta(result.meta, "get_full_schema")
    assert result.meta["success"] is False
    assert (
        result.structured_content["error_code"]
        == "unsupported_metadata_identifier"
    )
    assert "schema_groups" not in result.structured_content
    assert "odd-name" not in result.structured_content["error"]


def test_get_table_summary_reports_missing_table(base_server):
    result = asyncio.run(
        base_server.get_table_summary(
            table_name="missing_table",
            ctx=_DummyContext(),
        )
    )

    _assert_common_meta(result.meta, "get_table_summary")
    assert result.meta["success"] is False
    assert "not found" in result.structured_content["error"].lower()


def test_meta_get_full_schema(base_server):
    result = asyncio.run(base_server.get_full_schema(ctx=_DummyContext()))
    _assert_common_meta(result.meta, "get_full_schema")
    assert result.meta["success"] is True


def test_get_full_schema_defaults_to_grouped_compact_projection(base_server):
    omitted = asyncio.run(base_server.get_full_schema(ctx=_DummyContext()))
    explicit = asyncio.run(
        base_server.get_full_schema(ctx=_DummyContext(), detail_level="compact")
    )
    payload = omitted.structured_content

    assert payload == explicit.structured_content
    assert payload["detail_level"] == "compact"
    assert payload["grouped_by_schema"] is True
    assert payload["grouping_basis"] == "adapter_visible_column_metadata_and_order"
    assert "schema_groups" in payload
    assert "schema" not in payload


def test_get_full_schema_explicit_full_retains_adapter_projection(base_server):
    grouped = asyncio.run(
        base_server.get_full_schema(
            ctx=_DummyContext(),
            detail_level="full",
            group_identical=True,
        )
    )
    ungrouped = asyncio.run(
        base_server.get_full_schema(
            ctx=_DummyContext(),
            detail_level="full",
            group_identical=False,
        )
    )
    payload = grouped.structured_content

    assert payload == ungrouped.structured_content
    assert payload["detail_level"] == "full"
    assert "schema" in payload
    for grouping_field in (
        "schema_groups",
        "schema_group_count",
        "grouped_by_schema",
        "grouping_basis",
    ):
        assert grouping_field not in payload
    assert {"name", "type", "nullable", "key", "default"} == set(
        payload["schema"]["widgets"]["columns"][0]
    )


def test_get_full_schema_compact_groups_only_equal_adapter_metadata(base_server):
    _seed_schema_projection_tables(base_server)

    result = asyncio.run(
        base_server.get_full_schema(
            ctx=_DummyContext(),
            detail_level="compact",
        )
    )
    payload = result.structured_content

    assert payload["detail_level"] == "compact"
    assert payload["grouped_by_schema"] is True
    assert payload["grouping_basis"] == "adapter_visible_column_metadata_and_order"
    assert "schema" not in payload
    assert payload["schema_group_count"] == 3

    groups_by_tables = {
        frozenset(table["name"] for table in group["tables"]): group
        for group in payload["schema_groups"]
    }
    twin_group = groups_by_tables[frozenset({"schema_twin_a", "schema_twin_b"})]
    assert twin_group["column_count"] == 3
    assert twin_group["columns"] == [
        ["id", "INTEGER"],
        ["code", "TEXT"],
        ["amount", "REAL"],
    ]
    assert twin_group["primary_key"] == ["id"]
    assert frozenset({"schema_variant"}) in groups_by_tables
    assert "get_full_schema(detail_level='full')" in payload["hint"]


def test_get_full_schema_compact_can_disable_grouping(base_server):
    _seed_schema_projection_tables(base_server)

    result = asyncio.run(
        base_server.get_full_schema(
            ctx=_DummyContext(),
            detail_level="compact",
            group_identical=False,
        )
    )
    payload = result.structured_content

    assert payload["grouped_by_schema"] is False
    assert payload["grouping_basis"] == "none"
    assert payload["schema_group_count"] == payload["returned_table_count"]
    assert all(len(group["tables"]) == 1 for group in payload["schema_groups"])


@pytest.mark.parametrize("invalid_detail_level", ["invalid", "FULL", None])
def test_get_full_schema_rejects_invalid_detail_level(
    base_server,
    invalid_detail_level,
):
    with pytest.raises(base_server.ToolError, match="Allowed values: compact, full"):
        asyncio.run(
            base_server.get_full_schema(
                ctx=_DummyContext(),
                detail_level=invalid_detail_level,
            )
        )


@pytest.mark.parametrize("invalid_group_identical", [None, 0, 1, "false"])
def test_get_full_schema_direct_call_rejects_non_boolean_grouping(
    base_server,
    invalid_group_identical,
):
    with pytest.raises(base_server.ToolError, match="group_identical must be a boolean"):
        asyncio.run(
            base_server.get_full_schema(
                ctx=_DummyContext(),
                group_identical=invalid_group_identical,
            )
        )


def test_get_full_schema_input_schema_exposes_projection_enum(base_server):
    async def _list_tools():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(_list_tools())
    schema_tool = next(tool for tool in tools if tool.name == "get_full_schema")
    properties = schema_tool.inputSchema["properties"]
    detail_schema = properties["detail_level"]

    assert detail_schema["enum"] == ["compact", "full"]
    assert detail_schema["default"] == "compact"
    assert "anyOf" not in detail_schema
    assert properties["group_identical"]["default"] is True
    assert "Ignored in full mode" in properties["group_identical"]["description"]
    assert "not proof of full DDL" in properties["group_identical"]["description"]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_type"),
    [
        ("get_full_schema", {"group_identical": "false"}, "boolean"),
        (
            "get_table_summary",
            {"table_name": "widgets", "exact_count": "true"},
            "boolean",
        ),
        ("sample", {"table_name": "widgets", "limit": "1"}, "integer"),
    ],
)
def test_mcp_rejects_wrong_type_scalars(
    base_server,
    tool_name,
    arguments,
    expected_type,
):
    """Strict MCP validation must not coerce string scalar values."""
    async def _call_tool():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            return await client.call_tool(tool_name, arguments)

    with pytest.raises(
        base_server.ToolError,
        match=f"is not of type '{expected_type}'",
    ):
        asyncio.run(_call_tool())


def test_optional_tool_input_schemas_expose_cost_and_range_contracts(base_server):
    async def _list_tools():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(_list_tools())}

    limit_schema = tools["sample"].inputSchema["properties"]["limit"]
    assert limit_schema["type"] == "integer"
    assert limit_schema["default"] == 5
    assert limit_schema["minimum"] == 1
    assert limit_schema["maximum"] == 20
    assert "out-of-range values are rejected" in limit_schema["description"]

    exact_count_schema = tools["get_table_summary"].inputSchema["properties"][
        "exact_count"
    ]
    assert exact_count_schema["type"] == "boolean"
    assert exact_count_schema["default"] is False
    assert "SELECT COUNT(*)" in exact_count_schema["description"]
    assert "full scan" in exact_count_schema["description"]
    assert "metadata-lock contention" in exact_count_schema["description"]


def test_sample_mcp_enforces_limit_range_before_execution(
    base_server,
    monkeypatch,
):
    executed_sql = []
    adapter = base_server.get_adapter()
    original_execute = adapter.execute

    def _record_execute(sql):
        executed_sql.append(sql)
        return original_execute(sql)

    monkeypatch.setattr(adapter, "execute", _record_execute)

    async def _call_limits():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            below = await client.call_tool(
                "sample",
                {"table_name": "widgets", "limit": 0},
                raise_on_error=False,
            )
            above = await client.call_tool(
                "sample",
                {"table_name": "widgets", "limit": 21},
                raise_on_error=False,
            )
            lower_bound = await client.call_tool(
                "sample",
                {"table_name": "widgets", "limit": 1},
            )
            upper_bound = await client.call_tool(
                "sample",
                {"table_name": "widgets", "limit": 20},
            )
            return below, above, lower_bound, upper_bound

    below, above, lower_bound, upper_bound = asyncio.run(_call_limits())

    assert below.is_error is True
    assert above.is_error is True
    assert lower_bound.is_error is False
    assert upper_bound.is_error is False
    lower_content = lower_bound.structured_content
    upper_content = upper_bound.structured_content
    assert isinstance(lower_content, dict)
    assert isinstance(upper_content, dict)
    assert lower_content["query"].endswith("LIMIT 1")
    assert upper_content["query"].endswith("LIMIT 20")
    assert executed_sql == [
        'SELECT * FROM "widgets" LIMIT 1',
        'SELECT * FROM "widgets" LIMIT 20',
    ]


def test_schema_tool_descriptions_guide_minimal_discovery_path(base_server):
    async def _list_tools():
        from fastmcp import Client

        async with Client(base_server.mcp) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(_list_tools())}
    descriptions = {
        name: " ".join((tool.description or "").split())
        for name, tool in tools.items()
    }

    assert "Do not call it as a routine prerequisite" in descriptions[
        "check_connection"
    ]
    assert 'call get_full_schema(detail_level="compact") directly' in (
        descriptions["list_tables"]
    )
    assert "Do not call repeatedly to survey many tables" in (
        descriptions["describe_table"]
    )
    assert "full adapter-visible column metadata" in descriptions["describe_table"]
    assert "not complete DDL" in descriptions["describe_table"]
    assert "primary tool for free-form read-only SQL" in descriptions["query"]
    assert "metadata tools for schema discovery" in descriptions["query"]
    assert "strict named-write policy" in descriptions["list_connections"]
    assert "default alias in compatibility mode" in descriptions[
        "list_connections"
    ]
    assert "Discovery itself never authorizes writes" in descriptions[
        "list_connections"
    ]
    assert "This tool takes no arguments" in descriptions["list_connections"]
    assert tools["list_connections"].inputSchema["properties"] == {}
    assert "Call compact directly instead of list_tables" in (
        descriptions["get_full_schema"]
    )
    assert 'get_full_schema(detail_level="compact") directly' in (
        base_server.mcp.instructions
    )
    prompt = base_server.sql_assistant()
    assert "list_connections(): Show configured connection ids" in prompt
    assert "takes no arguments" in prompt
    assert "Use list_tables() when names/counts are enough" in prompt
    assert 'get_full_schema(detail_level="compact") directly' in prompt


def test_meta_get_table_summary(base_server):
    if not hasattr(base_server, "get_table_summary"):
        pytest.skip("get_table_summary not enabled in this build")
    result = asyncio.run(
        base_server.get_table_summary(table_name="widgets", ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "get_table_summary")
    assert result.meta["success"] is True


@pytest.mark.parametrize("invalid_exact_count", [None, 0, 1, "true"])
def test_get_table_summary_direct_call_rejects_non_boolean_exact_count(
    base_server,
    monkeypatch,
    invalid_exact_count,
):
    adapter = base_server.get_adapter()

    def fail_execute(*_args, **_kwargs):
        pytest.fail("Invalid direct-call exact_count must not execute SQL")

    monkeypatch.setattr(adapter, "execute", fail_execute)

    with pytest.raises(base_server.ToolError, match="exact_count must be a boolean"):
        asyncio.run(
            base_server.get_table_summary(
                table_name="widgets",
                exact_count=invalid_exact_count,
                ctx=_DummyContext(),
            )
        )


def test_meta_sample(base_server):
    if not hasattr(base_server, "sample"):
        pytest.skip("sample tool not enabled in this build")
    result = asyncio.run(
        base_server.sample(table_name="widgets", limit=2, ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "sample")
    assert result.meta["success"] is True


@pytest.mark.parametrize("invalid_limit", [0, 21, True, None])
def test_sample_direct_calls_reject_invalid_limit_before_execution(
    base_server,
    monkeypatch,
    invalid_limit,
):
    adapter = base_server.get_adapter()

    def fail_execute(*_args, **_kwargs):
        pytest.fail("Invalid direct-call limit must not execute SQL")

    monkeypatch.setattr(adapter, "execute", fail_execute)

    with pytest.raises(base_server.ToolError, match="integer from 1 through 20"):
        asyncio.run(
            base_server.sample(
                table_name="widgets",
                limit=invalid_limit,
                ctx=_DummyContext(),
            )
        )


# ─────────────────────────────── E2 ──────────────────────────────────


def test_skill_tools_declare_output_schema(monkeypatch):
    """Both skill tools must expose a populated outputSchema via list_tools."""
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="1",
        SKILLS_DIR="skills/",
        SKILLS_ALLOW_MUTATIONS="1",
    )
    try:

        async def _list():
            from fastmcp import Client

            async with Client(module.mcp) as client:
                return await client.list_tools()

        tools = asyncio.run(_list())
        by_name = {t.name: t for t in tools}

        for tool_name in ("execute_query_skill", "execute_mutation_skill"):
            assert tool_name in by_name, f"{tool_name} missing from list_tools"
            schema = getattr(by_name[tool_name], "outputSchema", None)
            assert schema is not None, f"{tool_name} outputSchema is None"
            assert schema.get("type") == "object", schema
            assert "properties" in schema and schema["properties"], schema
            assert "success" in schema["properties"], schema
            assert "skill_name" in schema["properties"], schema

        mut_schema = by_name["execute_mutation_skill"].outputSchema
        assert "mode" in mut_schema["properties"], mut_schema
        mode_enum = mut_schema["properties"]["mode"].get("enum")
        assert mode_enum == ["preview", "execute"], mut_schema
    finally:
        for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(mod, None)


def test_skill_tool_meta_has_uniform_fields(monkeypatch, tmp_path):
    """Skill tools participate in the same meta contract as base tools."""
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="1",
        SKILLS_DIR="skills/",
        SKILLS_ALLOW_MUTATIONS="1",
        SKILLS_AUDIT_LOG=str(tmp_path / "skills-audit.jsonl"),
    )
    try:
        _seed_orders_table(module)

        query_result = asyncio.run(
            module.execute_query_skill(
                skill_name="monthly-sales-report-sqlite",
                params={"year": 2026, "month": 1},
                ctx=_DummyContext(),
            )
        )
        _assert_common_meta(query_result.meta, "execute_query_skill")
        assert query_result.meta["success"] is True
        assert query_result.meta["skill_name"] == "monthly-sales-report-sqlite"
        assert query_result.meta["mode"] == "query"

        mutation_result = asyncio.run(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params={"order_id": 1, "new_status": "confirmed"},
                ctx=_DummyContext(),
                confirm=False,
            )
        )
        _assert_common_meta(mutation_result.meta, "execute_mutation_skill")
        assert mutation_result.structured_content["success"] is True
        assert mutation_result.meta["success"] is True
        assert mutation_result.meta["skill_name"] == "update-order-status"
        assert mutation_result.meta["mode"] == "preview"
        assert mutation_result.meta["audit_logged"] is True
        assert mutation_result.meta["preview_token_required"] is True
        assert mutation_result.meta["preview_token_validated"] is False
        assert mutation_result.meta["preview_token_consumed"] is False

        mutation_execute_result = asyncio.run(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params={"order_id": 1, "new_status": "confirmed"},
                ctx=_DummyContext(),
                confirm=True,
                preview_token=mutation_result.structured_content["preview_token"],
            )
        )
        assert mutation_execute_result.structured_content["success"] is True
        assert mutation_execute_result.meta["success"] is True
        assert mutation_execute_result.meta["mode"] == "execute"
        assert mutation_execute_result.meta["audit_logged"] is True
        assert mutation_execute_result.meta["preview_token_required"] is True
        assert mutation_execute_result.meta["preview_token_validated"] is True
        assert mutation_execute_result.meta["preview_token_consumed"] is True
    finally:
        for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(mod, None)


# ─────────────────────────────── E3 ──────────────────────────────────


def test_telemetry_end_to_end_via_client(monkeypatch, tmp_path):
    """Real FastMCP Client → tools/call path must produce a telemetry record."""
    log_path = tmp_path / "tool_calls.jsonl"
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="0",
        ENABLE_TOOL_TELEMETRY="1",
        TOOL_TELEMETRY_LOG_PATH=str(log_path),
    )
    try:
        _seed_demo_table(module)

        async def _call():
            from fastmcp import Client

            async with Client(module.mcp) as client:
                await client.call_tool(
                    "query", {"sql": "SELECT id FROM widgets ORDER BY id"}
                )
                # Trigger a business-level rejection so B1 is exercised end-to-end.
                await client.call_tool("query", {"sql": "DROP TABLE widgets"})

        asyncio.run(_call())

        assert log_path.exists(), "telemetry log was not created"
        lines = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) >= 2, lines
        query_records = [r for r in lines if r["tool_name"] == "query"]
        assert len(query_records) >= 2, lines

        # First call succeeded at both transport and business layers.
        ok = query_records[0]
        assert ok["call_completed"] is True
        assert ok["success"] is True
        assert ok["error_class"] is None

        # Second call: business-level rejection, transport-level success.
        rej = query_records[1]
        assert rej["call_completed"] is True
        assert rej["success"] is False
        assert rej["error_class"] is None

        # Sanitization invariants.
        for record in lines:
            for forbidden in ("sql", "params", "rows", "data", "password"):
                assert forbidden not in record, record
    finally:
        for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(mod, None)


def test_skill_telemetry_end_to_end_honors_business_failure(monkeypatch, tmp_path):
    """Skill business rejection must be logged as success=false via Client path."""
    log_path = tmp_path / "skill_tool_calls.jsonl"
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="1",
        SKILLS_DIR="skills/",
        SKILLS_ALLOW_MUTATIONS="1",
        ENABLE_TOOL_TELEMETRY="1",
        TOOL_TELEMETRY_LOG_PATH=str(log_path),
    )
    try:
        _seed_orders_table(module)

        async def _call():
            from fastmcp import Client

            async with Client(module.mcp) as client:
                await client.call_tool(
                    "execute_mutation_skill",
                    {
                        "skill_name": "update-order-status",
                        "params": {"order_id": 1, "new_status": "delivered"},
                        "confirm": False,
                    },
                )

        asyncio.run(_call())

        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        mutation_records = [
            r for r in records if r["tool_name"] == "execute_mutation_skill"
        ]
        assert len(mutation_records) == 1, records
        record = mutation_records[0]
        assert record["call_completed"] is True
        assert record["success"] is False
        assert record["error_class"] is None
        for forbidden in ("sql", "params", "rows", "data", "password"):
            assert forbidden not in record, record
    finally:
        for mod in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
            sys.modules.pop(mod, None)
