"""v3.6 mutation preview-token and multi-connection policy regressions."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import logging
import sqlite3
import sys
import threading
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


def _create_orders_db(path: Path, label: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT NOT NULL,
            total_amount REAL,
            amount REAL,
            status TEXT,
            source_label TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO orders (
            id, order_date, total_amount, amount, status, source_label
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "2026-01-15 10:00:00", 100.0, 100.0, "pending", label),
            (2, "2026-01-15 12:00:00", 50.0, 50.0, "pending", label),
        ],
    )
    conn.commit()
    conn.close()


def _order_status(path: Path, order_id: int) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT status FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        conn.close()


def _reload_server(
    monkeypatch,
    mysql_db: Path,
    analytics_db: Path,
    *,
    allow_analytics_mutations: bool = True,
    mutation_connections: str = "mysql,analytics",
    analytics_mutation_skills: str = "update-order-status",
    preview_token_ttl_seconds: int = 300,
    preview_token_store_max_entries: int = 10000,
    check_schema_on_list: bool | None = None,
):
    monkeypatch.setenv("DB_CONNECTIONS", "mysql,analytics")
    monkeypatch.setenv("DEFAULT_DB_CONNECTION", "mysql")
    # The mysql alias uses SQLite fixtures here to keep the design tests hermetic.
    monkeypatch.setenv("DB_MYSQL_TYPE", "sqlite")
    monkeypatch.setenv("DB_MYSQL_SQLITE_DATABASE_PATH", str(mysql_db))
    monkeypatch.setenv("DB_MYSQL_ALLOWED_TABLES", "orders")
    monkeypatch.setenv("DB_ANALYTICS_TYPE", "sqlite")
    monkeypatch.setenv("DB_ANALYTICS_SQLITE_DATABASE_PATH", str(analytics_db))
    monkeypatch.setenv("DB_ANALYTICS_ALLOWED_TABLES", "orders")
    monkeypatch.setenv("ENABLE_SKILLS", "1")
    monkeypatch.setenv("SKILLS_ALLOW_MUTATIONS", "1")
    monkeypatch.setenv("SKILLS_DIR", "skills/")
    monkeypatch.setenv("SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setenv("SKILLS_AUDIT_QUERIES", "0")
    monkeypatch.setenv(
        "SKILLS_AUDIT_LOG",
        str(mysql_db.parent / "mutation-audit.jsonl"),
    )
    monkeypatch.setenv("MAX_SQL_LENGTH", "20000")
    monkeypatch.setenv("MCP_TOOL_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv(
        "MUTATION_PREVIEW_TOKEN_TTL_SECONDS",
        str(preview_token_ttl_seconds),
    )
    monkeypatch.setenv(
        "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES",
        str(preview_token_store_max_entries),
    )
    monkeypatch.setenv(
        "SKILLS_ALLOW_MUTATION_CONNECTIONS",
        mutation_connections,
    )
    monkeypatch.setenv("DB_MYSQL_ALLOW_MUTATIONS", "1")
    monkeypatch.setenv("DB_MYSQL_MUTATION_SKILLS", "update-order-status")
    monkeypatch.setenv(
        "DB_ANALYTICS_ALLOW_MUTATIONS",
        "1" if allow_analytics_mutations else "0",
    )
    monkeypatch.setenv(
        "DB_ANALYTICS_MUTATION_SKILLS",
        analytics_mutation_skills,
    )
    monkeypatch.delenv("SKILLS_LIST_DEFAULT_DETAIL", raising=False)
    monkeypatch.delenv("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    if check_schema_on_list is None:
        monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)
    else:
        monkeypatch.setenv(
            "SKILLS_CHECK_SCHEMA_ON_LIST",
            "1" if check_schema_on_list else "0",
        )

    import skill_loader

    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_a, **_k: None)

    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("mcp_sql_server")


def _cleanup_modules() -> None:
    db_adapter = sys.modules.get("db_adapter")
    if db_adapter is not None:
        db_adapter.reset_adapter()
    for module_name in ("mcp_sql_server", "db_adapter", "sql_safety_checker"):
        sys.modules.pop(module_name, None)


def _params(order_id: int = 1, new_status: str = "confirmed") -> dict[str, object]:
    return {"order_id": order_id, "new_status": new_status}


def _set_order_status(path: Path, order_id: int, status: str) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_default_execute_requires_preview_token(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        with pytest.raises(module.ToolError, match="preview[_ -]?token|preview token"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_reset_skill_completes_mutation_compensation_flow(tmp_path, monkeypatch):
    """A mutation and its demo reset both use the real token/tool path."""
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        analytics_mutation_skills=(
            "update-order-status,reset-demo-order-to-pending"
        ),
    )
    try:
        update_preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params={"order_id": 1, "new_status": "confirmed"},
                connection_id="analytics",
                ctx=DummyContext(),
                confirm=False,
            )
        )
        update_result, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params={"order_id": 1, "new_status": "confirmed"},
                connection_id="analytics",
                ctx=DummyContext(),
                confirm=True,
                preview_token=update_preview["preview_token"],
            )
        )
        assert update_result["success"] is True
        assert _order_status(analytics_db, 1) == "confirmed"

        reset_params = {"order_id": 1, "expected_status": "confirmed"}
        preview, preview_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="reset-demo-order-to-pending",
                params=reset_params,
                connection_id="analytics",
                ctx=DummyContext(),
                confirm=False,
            )
        )
        assert preview["success"] is True
        assert preview["preview"]["current_status"] == "confirmed"
        assert preview["preview"]["new_status"] == "pending"
        assert preview_meta["preview_token_required"] is True
        assert _order_status(analytics_db, 1) == "confirmed"

        executed, executed_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="reset-demo-order-to-pending",
                params=reset_params,
                connection_id="analytics",
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert executed["success"] is True
        assert executed["result"]["previous_status"] == "confirmed"
        assert executed["result"]["new_status"] == "pending"
        assert executed_meta["preview_token_consumed"] is True
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_server_instructions_describe_optional_mutations(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        assert "READ-ONLY access" not in module.mcp.instructions
        assert "read-only core SQL tools" in module.mcp.instructions
        assert "controlled mutations" in module.mcp.instructions
        assert "one-time token" in module.mcp.instructions
        assert "pass it unchanged" in module.mcp.instructions
        assert "only a database type" in module.mcp.instructions
        assert "exactly one has that db_type" in module.mcp.instructions
        assert "only a purpose or role" in module.mcp.instructions
        assert "do not infer a connection from alias names" in module.mcp.instructions
        assert "asks which aliases are available" in module.mcp.instructions
        assert "ask them to choose an exact alias" in module.mcp.instructions
        assert "it never means all connections" in module.mcp.instructions
        assert "Never broadcast mutations" in module.mcp.instructions
        prompt = module.sql_assistant()
        assert module._CONNECTION_ROUTING_GUIDANCE in prompt
        assert 'list_skills(..., detail_level="compact")' in prompt
        assert 'get_skill_detail(..., detail_level="execution") directly' in prompt
        assert 'list_skills(detail_level="full")? Execute directly' in prompt
        assert "preview first with confirm=false" in prompt
        assert "UNION policy is connection-specific" in prompt
        assert "selected alias in list_connections()" in prompt
        assert "For raw query() calls, include the executed SQL" in prompt
        assert "do not invent SQL that was not disclosed" in " ".join(prompt.split())
    finally:
        _cleanup_modules()


def test_preview_token_ttl_above_max_falls_back_to_default(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_ttl_seconds=86_401,
    )
    try:
        assert module.MUTATION_PREVIEW_TOKEN_TTL_MAX_SECONDS == 86_400
        assert module.MUTATION_PREVIEW_TOKEN_TTL_SECONDS == 300
    finally:
        _cleanup_modules()


def test_preview_token_store_capacity_above_max_falls_back_to_default(
    tmp_path,
    monkeypatch,
    caplog,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    with caplog.at_level(logging.WARNING, logger="mcp_sql_server"):
        module = _reload_server(
            monkeypatch,
            mysql_db,
            analytics_db,
            preview_token_store_max_entries=100_001,
        )
    try:
        assert module.MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES_MAX == 100_000
        assert module.MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES == 10_000
        assert any(
            "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES" in record.getMessage()
            and "must be <= 100000" in record.getMessage()
            for record in caplog.records
        )
    finally:
        _cleanup_modules()


def test_preview_token_store_capacity_accepts_maximum(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_store_max_entries=100_000,
    )
    try:
        assert module.MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES == 100_000
    finally:
        _cleanup_modules()


def test_mutation_handle_startup_visibility_ignores_legacy_secret(
    tmp_path,
    monkeypatch,
    caplog,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")
    legacy_secret = "obsolete-preview-token-secret"
    monkeypatch.setenv("MUTATION_PREVIEW_TOKEN_SECRET", legacy_secret)

    with caplog.at_level(logging.INFO, logger="mcp_sql_server"):
        _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        all_messages = "\n".join(
            record.getMessage() for record in caplog.records
        )
        assert (
            "Mutation preview tokens: 256-bit opaque handles with "
            "process-local one-time state"
        ) in all_messages
        assert "MUTATION_PREVIEW_TOKEN_SECRET is obsolete and ignored" in all_messages
        assert legacy_secret not in all_messages
        assert "signing secret" not in all_messages
    finally:
        _cleanup_modules()


def test_mutation_authorization_startup_summary_strict_mode(
    tmp_path,
    monkeypatch,
    caplog,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    with caplog.at_level(logging.INFO, logger="mcp_sql_server"):
        _reload_server(
            monkeypatch,
            mysql_db,
            analytics_db,
            allow_analytics_mutations=False,
        )
    try:
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Mutation routing policy:")
        ]
        assert len(messages) == 1
        message = messages[0]
        assert "mode=strict" in message
        assert "candidate_targets=analytics,mysql" in message
        assert "policy_enabled_targets=mysql" in message
        assert "analytics=disabled" in message
        assert "mysql=allowlist(update-order-status)" in message
        assert str(mysql_db) not in message
        assert str(analytics_db) not in message
    finally:
        _cleanup_modules()


def test_mutation_authorization_startup_summary_default_only_mode(
    tmp_path,
    monkeypatch,
    caplog,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    with caplog.at_level(logging.INFO, logger="mcp_sql_server"):
        _reload_server(
            monkeypatch,
            mysql_db,
            analytics_db,
            mutation_connections="",
        )
    try:
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Mutation routing policy:")
        ]
        assert len(messages) == 1
        message = messages[0]
        assert "mode=default-only" in message
        assert "candidate_targets=mysql" in message
        assert "policy_enabled_targets=mysql" in message
        assert "target_policy=mysql=compatibility-default" in message
        assert str(mysql_db) not in message
        assert str(analytics_db) not in message
    finally:
        _cleanup_modules()


def test_preview_returns_token_and_default_target_metadata(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        assert payload["success"] is True
        assert payload["mode"] == "preview"
        assert payload["connection_id"] == "mysql"
        assert payload["db_type"] == "sqlite"
        assert isinstance(payload["preview_token"], str)
        assert payload["preview_token"]
        assert meta["connection_id"] == "mysql"
        assert meta["preview_token_required"] is True
        assert meta["preview_token_validated"] is False
        assert str(mysql_db) not in str(payload)
        assert str(mysql_db) not in str(meta)
    finally:
        _cleanup_modules()


def test_preview_validation_failure_reports_explicit_token_metadata(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(order_id=999),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        assert payload["success"] is False
        assert payload["validation"]["valid"] is False
        assert meta["audit_logged"] is False
        assert meta["preview_token_required"] is False
        assert meta["preview_token_validated"] is False
        assert meta["preview_token_consumed"] is False
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
    finally:
        _cleanup_modules()


def test_preview_rejects_non_object_execution_binding(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        mutation_class = module.get_skills_cache()[
            "update-order-status"
        ]._mutation_class
        assert mutation_class is not None
        monkeypatch.setattr(
            mutation_class,
            "build_execution_binding",
            lambda self, params, validation, preview: ["not", "an", "object"],
        )

        with pytest.raises(module.ToolError, match="must be a JSON object"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                )
            )
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
    finally:
        _cleanup_modules()


def test_preview_rejects_execution_binding_over_utf8_byte_limit(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        mutation_class = module.get_skills_cache()[
            "update-order-status"
        ]._mutation_class
        assert mutation_class is not None
        monkeypatch.setattr(
            mutation_class,
            "build_execution_binding",
            lambda self, params, validation, preview: {"state": "界" * 2_000},
        )

        with pytest.raises(module.ToolError, match="4096-byte limit"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                )
            )
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
    finally:
        _cleanup_modules()


def test_execute_with_preview_token_updates_default_connection(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )

        assert payload["success"] is True
        assert payload["mode"] == "execute"
        assert payload["connection_id"] == "mysql"
        assert meta["connection_id"] == "mysql"
        assert meta["preview_token_required"] is True
        assert meta["preview_token_validated"] is True
        assert meta["preview_token_consumed"] is True
        assert _order_status(mysql_db, 1) == "confirmed"
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_same_request_previews_receive_unique_one_time_tokens(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        monkeypatch.setattr(module.time, "time", lambda: 1_000)
        first, first_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        second, second_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        assert first["preview_token"] != second["preview_token"]
        assert first_meta["preview_token_id"] != second_meta["preview_token_id"]
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 2
    finally:
        _cleanup_modules()


def test_preview_token_can_execute_only_once(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        first, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert first["success"] is True

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "confirmed"
    finally:
        _cleanup_modules()


def test_concurrent_execute_with_same_token_writes_exactly_once(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")
    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        check_schema_on_list=False,
    )
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        # Keep the race focused on token redemption and the real write path.
        # Schema-readiness discovery is an optional feature and SQLite's
        # StaticPool shares one DBAPI connection, so this test disables that
        # unrelated concurrent read via the supported configuration switch.
        adapter = module.get_adapter("mysql")
        original_execute_write = adapter.execute_write
        write_count = 0
        write_count_lock = threading.Lock()
        start_barrier = threading.Barrier(2)

        def counted_execute_write(*args, **kwargs):
            nonlocal write_count
            with write_count_lock:
                write_count += 1
            return original_execute_write(*args, **kwargs)

        monkeypatch.setattr(adapter, "execute_write", counted_execute_write)

        def execute_once(_index):
            start_barrier.wait(timeout=5)
            try:
                payload, meta = run_tool(
                    module.execute_mutation_skill(
                        skill_name="update-order-status",
                        params=_params(),
                        ctx=DummyContext(),
                        confirm=True,
                        preview_token=preview["preview_token"],
                    )
                )
                return "success", payload, meta
            except module.ToolError as exc:
                return "error", str(exc), {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute_once, range(2)))

        successes = [result for result in results if result[0] == "success"]
        errors = [result for result in results if result[0] == "error"]
        assert len(successes) == 1
        assert successes[0][1]["success"] is True
        assert successes[0][2]["preview_token_consumed"] is True
        assert len(errors) == 1
        assert "already been used" in errors[0][1]
        assert write_count == 1
        assert _order_status(mysql_db, 1) == "confirmed"
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
    finally:
        _cleanup_modules()


def test_store_capacity_fails_closed_without_evicting_valid_token(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_store_max_entries=1,
    )
    try:
        first, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        with pytest.raises(module.ToolError, match="could not be registered"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                )
            )

        payload, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=first["preview_token"],
            )
        )
        assert payload["success"] is True
    finally:
        _cleanup_modules()


def test_expired_store_entry_releases_capacity(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_ttl_seconds=1,
        preview_token_store_max_entries=1,
    )
    try:
        monkeypatch.setattr(module.time, "time", lambda: 1_000)
        run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        monkeypatch.setattr(module.time, "time", lambda: 1_001)
        second, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        assert second["success"] is True
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 1
    finally:
        _cleanup_modules()


def test_execute_rejects_token_for_different_connection(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
                connection_id="analytics",
            )
        )

        with pytest.raises(module.ToolError, match="connection|preview[_ -]?token"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    connection_id="mysql",
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
        assert _order_status(analytics_db, 1) == "pending"

        payload, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                connection_id="analytics",
                preview_token=preview["preview_token"],
            )
        )
        assert payload["success"] is True
        assert _order_status(mysql_db, 1) == "pending"
        assert _order_status(analytics_db, 1) == "confirmed"
    finally:
        _cleanup_modules()


def test_execute_rejects_token_when_params_change(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(order_id=1),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        with pytest.raises(module.ToolError, match="params|preview[_ -]?token"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(order_id=2),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
        assert _order_status(mysql_db, 2) == "pending"

        payload, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(order_id=1),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert payload["success"] is True
        assert _order_status(mysql_db, 1) == "confirmed"
    finally:
        _cleanup_modules()


def test_execute_uses_previewed_state_for_optimistic_lock(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    params = _params(new_status="cancelled")
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=params,
                ctx=DummyContext(),
                confirm=False,
            )
        )
        assert preview["preview"]["bound_params"]["expected_status"] == "pending"

        # confirmed -> cancelled is valid, so dynamic validation passes. The
        # write must still use the previewed pending status and fail its lock.
        _set_order_status(mysql_db, 1, "confirmed")
        with pytest.raises(
            module.ToolError,
            match="Optimistic lock failed.*preview_token has been consumed",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=params,
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "confirmed"

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=params,
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
    finally:
        _cleanup_modules()


def test_binding_uses_state_read_by_preview_not_earlier_validation(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    adapter = module.get_adapter("mysql")
    original_execute = adapter.execute
    state_changed = False

    def execute_with_interleaving(sql, *args, **kwargs):
        nonlocal state_changed
        result = original_execute(sql, *args, **kwargs)
        if "SELECT status FROM orders" in sql and not state_changed:
            state_changed = True
            _set_order_status(mysql_db, 1, "confirmed")
        return result

    monkeypatch.setattr(adapter, "execute", execute_with_interleaving)
    params = _params(new_status="cancelled")
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=params,
                ctx=DummyContext(),
                confirm=False,
            )
        )
        assert preview["preview"]["current_status"] == "confirmed"
        assert (
            preview["preview"]["bound_params"]["expected_status"]
            == "confirmed"
        )

        payload, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=params,
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert payload["success"] is True
        assert payload["result"]["previous_status"] == "confirmed"
        assert _order_status(mysql_db, 1) == "cancelled"
    finally:
        _cleanup_modules()


def test_preview_error_does_not_issue_token(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    adapter = module.get_adapter("mysql")
    original_execute = adapter.execute

    def fail_preview_lookup(sql, *args, **kwargs):
        if "SELECT id, status FROM orders" in sql:
            return []
        return original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(adapter, "execute", fail_preview_lookup)
    try:
        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        assert payload["success"] is False
        assert payload["preview"]["error"]
        assert "preview_token" not in payload
        assert meta["preview_token_required"] is False
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


@pytest.mark.parametrize(
    "preview_result",
    [
        {"error": ""},
        {"error": None},
        {"success": False},
        {"success": 0},
        {"success": None},
        {"success": "false"},
    ],
)
def test_declared_preview_failure_never_issues_token(
    tmp_path,
    monkeypatch,
    preview_result,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        mutation_class = module.get_skills_cache()[
            "update-order-status"
        ]._mutation_class
        assert mutation_class is not None
        monkeypatch.setattr(
            mutation_class,
            "preview",
            lambda self, params: preview_result,
        )

        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        assert payload["success"] is False
        assert payload["error"] == "Mutation preview reported failure."
        assert "preview_token" not in payload
        assert meta["preview_token_required"] is False
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_update_order_status_rejects_direct_unbound_execute(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        mutation = module.load_mutation(
            "update-order-status",
            module.get_adapter("mysql"),
            module._audit_logger,
        )
        with pytest.raises(module.ToolError, match="unbound execution is disabled"):
            mutation.execute(_params())
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_dynamic_validation_failure_still_consumes_token(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        _set_order_status(mysql_db, 1, "cancelled")

        rejected, rejected_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert rejected["success"] is False
        assert rejected["validation"]["valid"] is False
        assert rejected_meta["audit_logged"] is True
        assert rejected_meta["preview_token_consumed"] is True

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )

        audit_text = (tmp_path / "mutation-audit.jsonl").read_text(
            encoding="utf-8"
        )
        audit_entries = [json.loads(line) for line in audit_text.splitlines()]
        assert len(audit_entries) == 2
        assert audit_entries[0]["mode"] == "preview"
        assert audit_entries[0]["success"] is True
        assert audit_entries[1]["mode"] == "execute"
        assert audit_entries[1]["success"] is False
        assert "Validation failed" in audit_entries[1]["error"]
        assert "preview_token_id" not in audit_entries[0]
        assert "preview_token_id" not in audit_entries[1]
    finally:
        _cleanup_modules()


def test_dynamic_validation_audit_failure_is_reported_in_meta(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        _set_order_status(mysql_db, 1, "cancelled")
        monkeypatch.setattr(module._audit_logger, "log", lambda **_kwargs: False)

        rejected, rejected_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert rejected["success"] is False
        assert rejected_meta["audit_logged"] is False
        assert rejected_meta["preview_token_consumed"] is True

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
    finally:
        _cleanup_modules()


def test_dynamic_validation_toolerror_is_audited_once_after_consumption(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        mutation_class = module.get_skills_cache()[
            "update-order-status"
        ]._mutation_class
        assert mutation_class is not None

        def fail_dynamic_validation(_self, _params):
            raise module.ToolError("simulated dynamic validation failure")

        monkeypatch.setattr(mutation_class, "validate", fail_dynamic_validation)
        audit_calls: list[dict[str, Any]] = []
        original_audit_log = module._audit_logger.log

        def recording_audit_log(**kwargs):
            audit_calls.append(kwargs)
            return original_audit_log(**kwargs)

        monkeypatch.setattr(module._audit_logger, "log", recording_audit_log)

        with pytest.raises(
            module.ToolError,
            match=(
                "simulated dynamic validation failure.*"
                "No database write was attempted.*"
                "preview_token has been consumed"
            ),
        ) as exc_info:
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert "write outcome may be unknown" not in str(exc_info.value)

        assert len(audit_calls) == 1
        assert audit_calls[0]["mode"] == "execute"
        assert audit_calls[0]["result"] == {
            "success": False,
            "error": "simulated dynamic validation failure",
        }
        assert _order_status(mysql_db, 1) == "pending"

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert len(audit_calls) == 1
    finally:
        _cleanup_modules()


def test_audit_failure_does_not_restore_consumed_token(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        monkeypatch.setattr(module._audit_logger, "log", lambda **_kwargs: False)

        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
            )
        )
        assert payload["success"] is True
        assert meta["audit_logged"] is False

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
    finally:
        _cleanup_modules()


def test_database_write_failure_still_consumes_token(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        adapter = module.get_adapter("mysql")

        def fail_write(*_args, **_kwargs):
            raise RuntimeError("simulated database write failure")

        monkeypatch.setattr(adapter, "execute_write", fail_write)
        with pytest.raises(
            module.ToolError,
            match=(
                "preview_token has been consumed.*write outcome may be "
                "unknown.*verify the current database state"
            ),
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )

        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
        audit_text = (tmp_path / "mutation-audit.jsonl").read_text(
            encoding="utf-8"
        )
        audit_entries = [json.loads(line) for line in audit_text.splitlines()]
        assert sum(entry["mode"] == "execute" for entry in audit_entries) == 1
        assert audit_entries[-1]["success"] is False
    finally:
        _cleanup_modules()


def test_response_failure_after_write_keeps_single_success_audit(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)

    class FailAfterWriteContext(DummyContext):
        def __init__(self) -> None:
            self.info_calls = 0

        async def info(self, message: str) -> None:
            self.info_calls += 1
            if self.info_calls == 2:
                raise RuntimeError("simulated response notification failure")

    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        with pytest.raises(
            module.ToolError,
            match=(
                "Mutation execution completed, but the tool response failed.*"
                "verify the current database state"
            ),
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=FailAfterWriteContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )

        assert _order_status(mysql_db, 1) == "confirmed"
        with pytest.raises(module.ToolError, match="already been used"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )

        audit_entries = [
            json.loads(line)
            for line in (tmp_path / "mutation-audit.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        execute_entries = [
            entry for entry in audit_entries if entry["mode"] == "execute"
        ]
        assert len(execute_entries) == 1
        assert execute_entries[0]["success"] is True
    finally:
        _cleanup_modules()


def test_execute_rejects_token_at_expiry_boundary(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_ttl_seconds=300,
    )
    try:
        monkeypatch.setattr(module.time, "time", lambda: 1_000)
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )

        monkeypatch.setattr(module.time, "time", lambda: 1_300)
        with pytest.raises(
            module.ToolError,
            match="Expired preview_token",
        ) as exc_info:
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert preview["preview_token"] not in str(exc_info.value)
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_execute_rejects_altered_or_unknown_handle_without_echoing_it(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        original_token = preview["preview_token"]
        replacement = "A" if original_token[-1] != "A" else "B"
        altered_handle = original_token[:-1] + replacement

        with pytest.raises(
            module.ToolError,
            match="Invalid preview_token",
        ) as exc_info:
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=altered_handle,
                )
            )

        error_message = str(exc_info.value)
        assert original_token not in error_message
        assert altered_handle not in error_message
        assert _order_status(mysql_db, 1) == "pending"

        payload, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=original_token,
            )
        )
        assert payload["success"] is True
    finally:
        _cleanup_modules()


def test_execute_rejects_token_after_skill_version_changes(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        skill_meta = module.get_skills_cache()["update-order-status"]
        monkeypatch.setattr(skill_meta, "version", "999.0.0")

        with pytest.raises(
            module.ToolError,
            match="does not match this mutation request",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_memory_store_restart_invalidates_token(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
    finally:
        _cleanup_modules()

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        with pytest.raises(module.ToolError, match="not issued by this server process"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                )
            )
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_full_token_is_excluded_from_meta_and_audit(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    audit_path = tmp_path / "mutation-audit.jsonl"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        preview, preview_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
            )
        )
        preview_token = preview["preview_token"]

        assert len(preview_token) == 43
        assert "." not in preview_token
        assert "preview_token_expires_in_seconds" not in preview
        assert "hint" not in preview
        assert "requires_confirmation" not in preview["preview"]
        assert preview_token not in str(preview_meta)
        assert preview_meta["preview_token_id"] != preview_token
        assert len(preview_meta["preview_token_id"]) == 16

        _, execute_meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview_token,
            )
        )

        assert preview_token not in str(execute_meta)
        assert execute_meta["preview_token_id"] == preview_meta["preview_token_id"]
        audit_text = audit_path.read_text(encoding="utf-8")
        assert preview_token not in audit_text
        assert preview_meta["preview_token_id"] not in audit_text
    finally:
        _cleanup_modules()


def test_authorized_non_default_execute_updates_only_target_connection(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        catalog, _ = run_tool(
            module.list_skills(
                ctx=DummyContext(),
                connection_id="analytics",
                available_only=False,
            )
        )
        mutation_skill = next(
            skill
            for skill in catalog["skills"]
            if skill["name"] == "update-order-status"
        )
        assert mutation_skill["executable"] is True
        assert mutation_skill["policy_allowed"] is True
        assert mutation_skill["mutation_connection_supported"] is True
        assert mutation_skill["mutation_policy_allowed"] is True

        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
                connection_id="analytics",
            )
        )
        payload, meta = run_tool(
            module.execute_mutation_skill(
                skill_name="update-order-status",
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                connection_id="analytics",
                preview_token=preview["preview_token"],
            )
        )

        assert payload["success"] is True
        assert payload["mode"] == "execute"
        assert payload["connection_id"] == "analytics"
        assert meta["connection_id"] == "analytics"
        assert meta["preview_token_required"] is True
        assert meta["preview_token_validated"] is True
        assert _order_status(analytics_db, 1) == "confirmed"
        assert _order_status(mysql_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_mutation_skill_connection_scope_narrows_without_auto_routing(
    tmp_path,
    monkeypatch,
):
    """v3.7 scope is restrictive and omitted still means global default."""
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        meta = module.get_skills_cache()["update-order-status"]
        meta.connection_ids = ["analytics"]

        with pytest.raises(module.ToolError, match="allowed connection_ids"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name=meta.name,
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                )
            )

        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name=meta.name,
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
                connection_id="analytics",
            )
        )
        result, _ = run_tool(
            module.execute_mutation_skill(
                skill_name=meta.name,
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
                connection_id="analytics",
            )
        )

        assert result["success"] is True
        assert result["connection_id"] == "analytics"
        assert _order_status(mysql_db, 1) == "pending"
        assert _order_status(analytics_db, 1) == "confirmed"
    finally:
        _cleanup_modules()


def test_mutation_scope_rejects_before_adapter_construction(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        meta = module.get_skills_cache()["update-order-status"]
        meta.connection_ids = ["analytics"]

        def unexpected_adapter(_connection_id):
            raise AssertionError(
                "Mutation scope rejection must precede adapter construction"
            )

        monkeypatch.setattr(module, "get_adapter", unexpected_adapter)
        with pytest.raises(module.ToolError, match="allowed connection_ids"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name=meta.name,
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                    connection_id="mysql",
                )
            )
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
    finally:
        _cleanup_modules()


def test_scope_rejection_before_token_validation_does_not_consume_token(
    tmp_path,
    monkeypatch,
):
    """A transient metadata-scope rejection must not redeem a valid token."""
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        meta = module.get_skills_cache()["update-order-status"]
        meta.connection_ids = ["analytics", "mysql"]
        preview, _ = run_tool(
            module.execute_mutation_skill(
                skill_name=meta.name,
                params=_params(),
                ctx=DummyContext(),
                confirm=False,
                connection_id="mysql",
            )
        )

        meta.connection_ids = ["analytics"]
        with pytest.raises(module.ToolError, match="allowed connection_ids"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name=meta.name,
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=True,
                    preview_token=preview["preview_token"],
                    connection_id="mysql",
                )
            )
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 1

        meta.connection_ids = ["analytics", "mysql"]
        result, result_meta = run_tool(
            module.execute_mutation_skill(
                skill_name=meta.name,
                params=_params(),
                ctx=DummyContext(),
                confirm=True,
                preview_token=preview["preview_token"],
                connection_id="mysql",
            )
        )
        assert result["success"] is True
        assert result_meta["preview_token_consumed"] is True
        assert _order_status(mysql_db, 1) == "confirmed"
    finally:
        _cleanup_modules()


def test_mutation_connection_scope_never_grants_server_policy(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        allow_analytics_mutations=False,
    )
    try:
        meta = module.get_skills_cache()["update-order-status"]
        meta.connection_ids = ["analytics"]
        with pytest.raises(
            module.ToolError,
            match="(?i)mutation.*policy|not authorized|not allowed",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name=meta.name,
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                    connection_id="analytics",
                )
            )
        assert len(module._MUTATION_PREVIEW_TOKEN_STORE) == 0
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_policy_denies_disabled_non_default_connection(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        allow_analytics_mutations=False,
    )
    try:
        with pytest.raises(
            module.ToolError,
            match="(?i)mutation.*policy|not authorized|not allowed",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                    connection_id="analytics",
                )
            )
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_policy_denies_connection_missing_from_global_allowlist(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        mutation_connections="mysql",
    )
    try:
        with pytest.raises(
            module.ToolError,
            match="SKILLS_ALLOW_MUTATION_CONNECTIONS",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                    connection_id="analytics",
                )
            )
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_policy_denies_skill_missing_from_connection_allowlist(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        analytics_mutation_skills="close-ticket",
    )
    try:
        with pytest.raises(
            module.ToolError,
            match="not authorized by the target connection policy",
        ):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params=_params(),
                    ctx=DummyContext(),
                    confirm=False,
                    connection_id="analytics",
                )
            )
        assert _order_status(analytics_db, 1) == "pending"
    finally:
        _cleanup_modules()


def test_unknown_connection_id_fails_before_token_validation(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        with pytest.raises(module.ToolError, match="Unknown connection_id"):
            run_tool(
                module.execute_mutation_skill(
                    skill_name="update-order-status",
                    params={},
                    ctx=DummyContext(),
                    confirm=True,
                    connection_id="missing",
                    preview_token="not-a-real-token",
                )
            )
    finally:
        _cleanup_modules()
