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


# ─────────────────────────────── E1 ──────────────────────────────────


def _assert_common_meta(meta: dict, expected_tool: str) -> None:
    assert meta["tool_name"] == expected_tool, meta
    assert meta["db_type"] in ("sqlite", "mysql"), meta
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


def test_meta_describe_table(base_server):
    result = asyncio.run(
        base_server.describe_table(table_name="widgets", ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "describe_table")
    assert result.meta["success"] is True


def test_meta_get_full_schema(base_server):
    result = asyncio.run(base_server.get_full_schema(ctx=_DummyContext()))
    _assert_common_meta(result.meta, "get_full_schema")
    assert result.meta["success"] is True


def test_meta_get_table_summary(base_server):
    if not hasattr(base_server, "get_table_summary"):
        pytest.skip("get_table_summary not enabled in this build")
    result = asyncio.run(
        base_server.get_table_summary(table_name="widgets", ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "get_table_summary")
    assert result.meta["success"] is True


def test_meta_sample(base_server):
    if not hasattr(base_server, "sample"):
        pytest.skip("sample tool not enabled in this build")
    result = asyncio.run(
        base_server.sample(table_name="widgets", limit=2, ctx=_DummyContext())
    )
    _assert_common_meta(result.meta, "sample")
    assert result.meta["success"] is True


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


def test_skill_tool_meta_has_uniform_fields(monkeypatch):
    """Skill tools participate in the same meta contract as base tools."""
    module = _reload_server(
        monkeypatch,
        ENABLE_SKILLS="1",
        SKILLS_DIR="skills/",
        SKILLS_ALLOW_MUTATIONS="1",
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
                params={"order_id": 1, "new_status": "delivered"},
                ctx=_DummyContext(),
                confirm=False,
            )
        )
        _assert_common_meta(mutation_result.meta, "execute_mutation_skill")
        assert mutation_result.structured_content["success"] is False
        assert mutation_result.meta["success"] is False
        assert mutation_result.meta["skill_name"] == "update-order-status"
        assert mutation_result.meta["mode"] == "preview"
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
