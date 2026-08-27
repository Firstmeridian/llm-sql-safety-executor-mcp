"""v3.5 multi-connection regression tests."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Any, Coroutine

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SKILLS_LIB = PROJECT_ROOT / "skills" / "_lib"
if str(SKILLS_LIB) not in sys.path:
    sys.path.insert(0, str(SKILLS_LIB))


class DummyContext:
    async def info(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    async def warning(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    async def error(self, message: str) -> None:  # pragma: no cover - trivial
        pass


def run_tool(coro: Coroutine[Any, Any, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = asyncio.run(coro)
    structured_content = getattr(result, "structured_content", None)
    if structured_content is not None:
        if not isinstance(structured_content, dict):
            raise TypeError("Expected structured tool content to be a dictionary")
        meta = getattr(result, "meta", None)
        if not isinstance(meta, dict):
            raise TypeError("Expected tool metadata to be a dictionary")
        return structured_content, meta
    if not isinstance(result, dict):
        raise TypeError("Expected direct tool result to be a dictionary")
    return result, {}


def _create_rows_db(path: Path, table_name: str, label: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, label TEXT)")
    conn.execute(f"INSERT INTO {table_name} (label) VALUES (?)", (label,))
    conn.commit()
    conn.close()


def _create_orders_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT NOT NULL,
            total_amount REAL,
            amount REAL,
            status TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO orders (id, order_date, total_amount, amount, status) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "2026-01-15 10:00:00", 100.0, 100.0, "pending"),
            (2, "2026-01-15 12:00:00", 50.0, 50.0, "pending"),
        ],
    )
    conn.commit()
    conn.close()


def _reload_server(
    monkeypatch,
    default_db: Path,
    analytics_db: Path,
    *,
    skills: bool = False,
    mutations: bool = False,
    skills_dir: str = "skills/",
    with_mysql_target: bool = False,
    schema_check_on_list: bool | None = None,
    default_allowed_tables: str = "items",
    analytics_allowed_tables: str = "items,orders",
):
    connection_ids = ["default", "analytics"]
    if with_mysql_target:
        connection_ids.append("mysql_target")
    monkeypatch.setenv("DB_CONNECTIONS", ",".join(connection_ids))
    monkeypatch.setenv("DEFAULT_DB_CONNECTION", "default")
    monkeypatch.setenv("DB_DEFAULT_TYPE", "sqlite")
    monkeypatch.setenv("DB_DEFAULT_SQLITE_DATABASE_PATH", str(default_db))
    monkeypatch.setenv("DB_ANALYTICS_TYPE", "sqlite")
    monkeypatch.setenv("DB_ANALYTICS_SQLITE_DATABASE_PATH", str(analytics_db))
    monkeypatch.setenv("DB_DEFAULT_ALLOWED_TABLES", default_allowed_tables)
    monkeypatch.setenv("DB_ANALYTICS_ALLOWED_TABLES", analytics_allowed_tables)
    if with_mysql_target:
        monkeypatch.setenv("DB_MYSQL_TARGET_TYPE", "mysql")
        monkeypatch.setenv("DB_MYSQL_TARGET_USER", "fixture")
        monkeypatch.setenv("DB_MYSQL_TARGET_PASSWORD", "fixture")
        monkeypatch.setenv("DB_MYSQL_TARGET_HOST", "127.0.0.1")
        monkeypatch.setenv("DB_MYSQL_TARGET_NAME", "fixture")
        monkeypatch.setenv("DB_MYSQL_TARGET_ALLOWED_TABLES", "items")
    monkeypatch.setenv("ENABLE_SCHEMA_TOOLS", "1")
    monkeypatch.setenv("ENABLE_TABLE_SUMMARY", "1")
    monkeypatch.setenv("ENABLE_SKILLS", "1" if skills else "0")
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "1" if mutations else "0")
    # Keep the v3.5 fixture independent of a local v3.6 named-write policy.
    # An empty value prevents db_adapter.load_dotenv() from restoring a live
    # SKILLS_ALLOW_MUTATION_CONNECTIONS value during the module re-import.
    monkeypatch.setenv("SKILLS_ALLOW_MUTATION_CONNECTIONS", "")
    monkeypatch.setenv("SKILLS_DIR", skills_dir)
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setenv("SKILLS_AUDIT_QUERIES", "0")
    monkeypatch.setenv("MAX_SQL_LENGTH", "20000")
    monkeypatch.setenv("MCP_TOOL_TIMEOUT_SECONDS", "120")
    monkeypatch.delenv("SKILLS_LIST_DEFAULT_DETAIL", raising=False)
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    if schema_check_on_list is None:
        monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)
    else:
        monkeypatch.setenv(
            "SKILLS_CHECK_SCHEMA_ON_LIST",
            "1" if schema_check_on_list else "0",
        )

    if skills:
        import skill_loader

        monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_a, **_k: None)

    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("mcp_sql_server")


def _cleanup_modules():
    db_adapter = sys.modules.get("db_adapter")
    if db_adapter is not None:
        db_adapter.reset_adapter()
    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)


def test_core_tools_resolve_policy_and_execution_to_same_connection(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")

    module = _reload_server(monkeypatch, default_db, analytics_db)
    try:
        connections, meta = run_tool(module.list_connections(ctx=DummyContext()))
        assert connections["default_connection_id"] == "default"
        assert [item["connection_id"] for item in connections["connections"]] == [
            "default",
            "analytics",
        ]
        assert meta["connection_id"] == "default"

        default_result, default_meta = run_tool(
            module.query(sql="SELECT label FROM items", ctx=DummyContext())
        )
        analytics_result, analytics_meta = run_tool(
            module.query(
                sql="SELECT label FROM items",
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )

        assert default_result["data"][0]["label"] == "default-row"
        assert analytics_result["data"][0]["label"] == "analytics-row"
        assert default_result["connection_id"] == "default"
        assert analytics_result["connection_id"] == "analytics"
        assert default_meta["connection_id"] == "default"
        assert analytics_meta["connection_id"] == "analytics"

        summary, summary_meta = run_tool(
            module.get_table_summary(
                table_name="items",
                exact_count=True,
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )
        assert summary["row_count"] == 1
        assert summary["connection_id"] == "analytics"
        assert summary_meta["connection_id"] == "analytics"
    finally:
        _cleanup_modules()


@pytest.mark.parametrize(
    ("default_allow_union", "analytics_allow_union"),
    [(False, True), (True, False)],
)
def test_union_policy_and_disclosure_follow_selected_connection(
    tmp_path,
    monkeypatch,
    default_allow_union,
    analytics_allow_union,
):
    """A generic prompt must not copy the default alias's UNION policy."""
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")
    monkeypatch.setenv(
        "DB_DEFAULT_ALLOW_UNION",
        "1" if default_allow_union else "0",
    )
    monkeypatch.setenv(
        "DB_ANALYTICS_ALLOW_UNION",
        "1" if analytics_allow_union else "0",
    )

    module = _reload_server(monkeypatch, default_db, analytics_db)
    union_sql = "SELECT label FROM items UNION SELECT label FROM items"
    try:
        connections, _meta = run_tool(
            module.list_connections(ctx=DummyContext())
        )
        policy_by_id = {
            item["connection_id"]: item["policy"]
            for item in connections["connections"]
        }
        assert policy_by_id["default"]["allow_union"] is default_allow_union
        assert policy_by_id["analytics"]["allow_union"] is analytics_allow_union

        for connection_id, is_allowed in (
            ("default", default_allow_union),
            ("analytics", analytics_allow_union),
        ):
            if is_allowed:
                payload, meta = run_tool(
                    module.query(
                        sql=union_sql,
                        ctx=DummyContext(),
                        connection_id=connection_id,
                    )
                )
                assert payload["success"] is True
                assert payload["data"] == [{"label": f"{connection_id}-row"}]
                assert payload["connection_id"] == connection_id
                assert meta["connection_id"] == connection_id
            else:
                payload, meta = run_tool(
                    module.query(
                        sql=union_sql,
                        ctx=DummyContext(),
                        connection_id=connection_id,
                    )
                )
                assert payload["success"] is False
                assert "UNION queries disabled" in payload["error"]
                assert payload["connection_id"] == connection_id
                assert meta["connection_id"] == connection_id

        prompt = module.sql_assistant()
        assert "UNION policy is connection-specific" in prompt
        assert "selected alias in list_connections()" in prompt
        assert "UNION supported for combining results" not in prompt
        assert "UNION allowed for:" not in prompt
        assert "Query tables separately" not in prompt
    finally:
        _cleanup_modules()


@pytest.mark.parametrize(
    ("default_allow_union", "analytics_allow_union"),
    [(False, True), (True, False)],
)
def test_query_skill_union_policy_follows_selected_connection(
    tmp_path,
    monkeypatch,
    default_allow_union,
    analytics_allow_union,
):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")
    monkeypatch.setenv(
        "DB_DEFAULT_ALLOW_UNION",
        "1" if default_allow_union else "0",
    )
    monkeypatch.setenv(
        "DB_ANALYTICS_ALLOW_UNION",
        "1" if analytics_allow_union else "0",
    )

    module = _reload_server(monkeypatch, default_db, analytics_db, skills=True)
    union_sql = "SELECT label FROM items UNION SELECT label FROM items"
    skill_name = "monthly-sales-report-sqlite"
    try:
        module.get_skills_cache()[skill_name].tables = ["items"]
        monkeypatch.setattr(
            module,
            "load_query",
            lambda _skill_name: (union_sql, {}),
        )

        for connection_id, is_allowed in (
            ("default", default_allow_union),
            ("analytics", analytics_allow_union),
        ):
            if is_allowed:
                payload, meta = run_tool(
                    module.execute_query_skill(
                        skill_name=skill_name,
                        params={},
                        ctx=DummyContext(),
                        connection_id=connection_id,
                    )
                )
                assert payload["success"] is True
                assert payload["data"] == [{"label": f"{connection_id}-row"}]
                assert payload["connection_id"] == connection_id
                assert meta["connection_id"] == connection_id
            else:
                with pytest.raises(
                    module.ToolError,
                    match="UNION queries disabled",
                ):
                    run_tool(
                        module.execute_query_skill(
                            skill_name=skill_name,
                            params={},
                            ctx=DummyContext(),
                            connection_id=connection_id,
                        )
                    )
    finally:
        _cleanup_modules()


def test_union_missing_allowlist_error_is_target_connection_specific(
    tmp_path,
    monkeypatch,
):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")
    monkeypatch.setenv("DB_DEFAULT_ALLOW_UNION", "0")
    monkeypatch.setenv("DB_ANALYTICS_ALLOW_UNION", "1")

    module = _reload_server(
        monkeypatch,
        default_db,
        analytics_db,
        analytics_allowed_tables="",
    )
    try:
        payload, meta = run_tool(
            module.query(
                sql="SELECT label FROM items UNION SELECT label FROM items",
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )
        assert payload["success"] is False
        assert "selected connection" in payload["error"]
        assert "Configure that connection's ALLOWED_TABLES policy" in payload["error"]
        assert payload["connection_id"] == "analytics"
        assert meta["connection_id"] == "analytics"
    finally:
        _cleanup_modules()


def test_unknown_connection_id_does_not_fall_back(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")

    module = _reload_server(monkeypatch, default_db, analytics_db)
    try:
        with pytest.raises(module.ToolError, match="Unknown connection_id"):
            run_tool(
                module.query(
                    sql="SELECT label FROM items",
                    ctx=DummyContext(),
                    connection_id="missing",
                )
            )
    finally:
        _cleanup_modules()


def test_execute_sql_resolves_unknown_connection_before_sql_policy(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")

    _reload_server(monkeypatch, default_db, analytics_db)
    try:
        from sql_safety_checker import execute_sql

        result = execute_sql("DROP TABLE items", connection_id="missing")

        assert isinstance(result, str)
        assert result.startswith("Error: Unknown connection_id")
    finally:
        _cleanup_modules()


def test_sqlite_database_path_is_not_exposed_in_tool_payload(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")

    module = _reload_server(monkeypatch, default_db, analytics_db)
    try:
        check_payload, check_meta = run_tool(
            module.check_connection(ctx=DummyContext(), connection_id="analytics")
        )
        tables_payload, tables_meta = run_tool(
            module.list_tables(ctx=DummyContext(), connection_id="analytics")
        )

        assert check_payload["database_name"] == "sqlite:analytics"
        assert tables_payload["database_name"] == "sqlite:analytics"
        assert str(analytics_db) not in str(check_payload)
        assert str(analytics_db) not in str(tables_payload)
        assert str(analytics_db) not in str(check_meta)
        assert str(analytics_db) not in str(tables_meta)
    finally:
        _cleanup_modules()


def test_query_skills_are_displayed_and_executed_for_target_connection(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_orders_db(analytics_db)

    module = _reload_server(
        monkeypatch,
        default_db,
        analytics_db,
        skills=True,
    )
    try:
        assert (
            module.get_skills_cache()[
                "monthly-sales-report-sqlite"
            ].connection_ids
            is None
        )
        default_skills, _ = run_tool(
            module.list_skills(ctx=DummyContext(), connection_id="default")
        )
        analytics_skills, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )

        assert default_skills["connection_id"] == "default"
        assert analytics_skills["connection_id"] == "analytics"
        assert [skill["name"] for skill in default_skills["skills"]] == []
        assert [skill["name"] for skill in analytics_skills["skills"]] == [
            "monthly-sales-report-sqlite"
        ]

        result, meta = run_tool(
            module.execute_query_skill(
                skill_name="monthly-sales-report-sqlite",
                params={"year": 2026, "month": 1},
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )
        assert result["success"] is True
        assert result["connection_id"] == "analytics"
        assert result["row_count"] == 1
        assert result["data"][0]["date"] == "2026-01-15"
        assert meta["connection_id"] == "analytics"

        with pytest.raises(module.ToolError, match="requires table.*not found"):
            run_tool(
                module.execute_query_skill(
                    skill_name="monthly-sales-report-sqlite",
                    params={"year": 2026, "month": 1},
                    ctx=DummyContext(),
                    connection_id="default",
                )
            )
    finally:
        _cleanup_modules()


def test_query_skill_connection_scope_is_targeted_and_does_not_auto_route(
    tmp_path,
    monkeypatch,
):
    """v3.7 scope narrows targets without changing omitted=default semantics."""
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_orders_db(analytics_db)

    module = _reload_server(monkeypatch, default_db, analytics_db, skills=True)
    try:
        meta = module.get_skills_cache()["monthly-sales-report-sqlite"]
        meta.connection_ids = ["analytics", "not_configured_here"]

        default_catalog, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="default",
                available_only=False,
            )
        )
        analytics_catalog, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="analytics",
                available_only=False,
            )
        )
        default_skill = next(
            item for item in default_catalog["skills"]
            if item["name"] == meta.name
        )
        analytics_skill = next(
            item for item in analytics_catalog["skills"]
            if item["name"] == meta.name
        )

        assert default_skill["connection_scope_allowed"] is False
        assert analytics_skill["connection_scope_allowed"] is True
        assert analytics_skill["connection_ids"] == [
            "analytics",
            "not_configured_here",
        ]
        assert analytics_skill["configured_connection_ids"] == ["analytics"]
        assert analytics_skill["unconfigured_connection_ids"] == [
            "not_configured_here"
        ]

        with pytest.raises(module.ToolError, match="allowed connection_ids"):
            run_tool(
                module.execute_query_skill(
                    skill_name=meta.name,
                    params={"year": 2026, "month": 1},
                    ctx=DummyContext(),
                )
            )

        result, _ = run_tool(
            module.execute_query_skill(
                skill_name=meta.name,
                params={"year": 2026, "month": 1},
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )
        assert result["connection_id"] == "analytics"
        assert result["data"][0]["date"] == "2026-01-15"
    finally:
        _cleanup_modules()


def test_query_skill_scope_rejects_before_adapter_construction(
    tmp_path,
    monkeypatch,
):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_orders_db(analytics_db)

    module = _reload_server(monkeypatch, default_db, analytics_db, skills=True)
    try:
        meta = module.get_skills_cache()["monthly-sales-report-sqlite"]
        meta.connection_ids = ["analytics"]

        def unexpected_adapter(_connection_id):
            raise AssertionError("scope rejection must precede adapter construction")

        monkeypatch.setattr(module, "get_adapter", unexpected_adapter)
        with pytest.raises(module.ToolError, match="allowed connection_ids"):
            run_tool(
                module.execute_query_skill(
                    skill_name=meta.name,
                    params={"year": 2026, "month": 1},
                    ctx=DummyContext(),
                    connection_id="default",
                )
            )
    finally:
        _cleanup_modules()


def test_frontmatter_scope_conflict_isolated_per_target_end_to_end(
    tmp_path,
    monkeypatch,
    caplog,
):
    """Real frontmatter keeps valid aliases usable and rejects conflicts early."""
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_rows_db(analytics_db, "items", "analytics-row")
    caplog.set_level("WARNING")

    module = _reload_server(
        monkeypatch,
        default_db,
        analytics_db,
        skills=True,
        skills_dir="tests/fixtures/v37_scoped_skills",
        with_mysql_target=True,
        schema_check_on_list=False,
    )
    try:
        meta = module.get_skills_cache()["reusable-scoped-report"]
        assert meta.connection_ids == [
            "analytics",
            "missing_target",
            "mysql_target",
        ]
        assert meta.databases == ["sqlite"]
        assert "not configured in this deployment" in caplog.text
        assert "connection scope conflict" in caplog.text

        analytics_catalog, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="analytics",
                detail_level="full",
                available_only=True,
            )
        )
        assert [item["name"] for item in analytics_catalog["skills"]] == [
            "reusable-scoped-report"
        ]
        disclosed = analytics_catalog["skills"][0]
        assert disclosed["configured_connection_ids"] == [
            "analytics",
            "mysql_target",
        ]
        assert disclosed["unconfigured_connection_ids"] == ["missing_target"]
        assert disclosed["connection_type_conflicts"] == [
            {
                "connection_id": "mysql_target",
                "actual_db_type": "mysql",
                "supported_db_types": ["sqlite"],
            }
        ]

        result, _ = run_tool(
            module.execute_query_skill(
                skill_name=meta.name,
                params={},
                ctx=DummyContext(),
                connection_id="analytics",
            )
        )
        assert result["data"] == [{"label": "analytics-row"}]

        conflict_catalog, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="mysql_target",
                available_only=True,
            )
        )
        assert conflict_catalog["skills"] == []
        assert conflict_catalog["connection_type_conflict_skills"] == 1

        def unexpected_adapter(_connection_id):
            raise AssertionError(
                "DB-type rejection must precede adapter construction"
            )

        monkeypatch.setattr(module, "get_adapter", unexpected_adapter)
        with pytest.raises(module.ToolError, match="not compatible"):
            run_tool(
                module.execute_query_skill(
                    skill_name=meta.name,
                    params={},
                    ctx=DummyContext(),
                    connection_id="mysql_target",
                )
            )
    finally:
        _cleanup_modules()


def test_mutation_skills_remain_default_connection_only_when_enabled(tmp_path, monkeypatch):
    default_db = tmp_path / "default.db"
    analytics_db = tmp_path / "analytics.db"
    _create_rows_db(default_db, "items", "default-row")
    _create_orders_db(analytics_db)

    module = _reload_server(
        monkeypatch,
        default_db,
        analytics_db,
        skills=True,
        mutations=True,
    )
    try:
        analytics_skills, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="analytics",
                available_only=False,
            )
        )

        mutation_skill = next(
            skill
            for skill in analytics_skills["skills"]
            if skill["name"] == "update-order-status"
        )
        assert mutation_skill["executable"] is False
        assert mutation_skill["disabled_reason"] == (
            "Mutation skills are limited to the default connection unless "
            "v3.6 mutation connection policy is configured."
        )
    finally:
        _cleanup_modules()
