"""v3.6 mutation preview-token and multi-connection policy regressions."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import secrets
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
    preview_token_secret: str | None = "test-preview-token-secret",
    preview_token_ttl_seconds: int = 300,
    preview_token_store_max_entries: int = 10000,
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
        "MUTATION_PREVIEW_TOKEN_SECRET",
        preview_token_secret or "",
    )
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
    monkeypatch.delenv("SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

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


def test_memory_store_concurrent_consume_has_exactly_one_winner(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")
    module = _reload_server(monkeypatch, mysql_db, analytics_db)
    try:
        store = module.InMemoryPreviewTokenStore(max_entries=1)
        assert store.issue("digest", 2_000, "{}", now=1_000) is True

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(
                    lambda _index: store.consume("digest", 2_000, now=1_001),
                    range(16),
                )
            )

        assert sum(result is not None for result in results) == 1
        assert len(store) == 0
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


def test_execute_rejects_tampered_token_without_echoing_it(tmp_path, monkeypatch):
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
        tampered_token = original_token[:-1] + replacement

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
                    preview_token=tampered_token,
                )
            )

        error_message = str(exc_info.value)
        assert original_token not in error_message
        assert tampered_token not in error_message
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


def test_memory_store_restart_invalidates_token_even_with_same_secret(
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
        preview_token_secret="stable-test-secret",
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
    finally:
        _cleanup_modules()

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_secret="stable-test-secret",
    )
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


def test_token_is_invalid_after_signing_secret_changes(tmp_path, monkeypatch):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_secret="first-test-secret",
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
    finally:
        _cleanup_modules()


def test_generated_process_secret_invalidates_token_after_reload(
    tmp_path,
    monkeypatch,
):
    mysql_db = tmp_path / "mysql.db"
    analytics_db = tmp_path / "analytics.db"
    _create_orders_db(mysql_db, "mysql")
    _create_orders_db(analytics_db, "analytics")

    original_token_urlsafe = secrets.token_urlsafe
    monkeypatch.setattr(
        secrets,
        "token_urlsafe",
        lambda size: (
            "process-one-secret-key"
            if size == 32
            else original_token_urlsafe(size)
        ),
    )
    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_secret=None,
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
    finally:
        _cleanup_modules()

    monkeypatch.setattr(
        secrets,
        "token_urlsafe",
        lambda size: (
            "process-two-secret-key"
            if size == 32
            else original_token_urlsafe(size)
        ),
    )
    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_secret=None,
    )
    try:
        with pytest.raises(module.ToolError, match="Invalid preview_token"):
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

    module = _reload_server(
        monkeypatch,
        mysql_db,
        analytics_db,
        preview_token_secret="second-test-secret",
    )
    try:
        with pytest.raises(module.ToolError, match="Invalid preview_token"):
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
        encoded_payload = preview_token.split(".", 1)[0]
        token_payload = json.loads(
            module._b64url_decode(encoded_payload).decode("utf-8")
        )

        assert preview_token not in str(preview_meta)
        assert preview_meta["preview_token_id"] != preview_token
        assert len(preview_meta["preview_token_id"]) == 16
        assert token_payload["execution_binding_hash"]
        assert token_payload["jti"]
        assert "expected_status" not in token_payload

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
        assert preview_token not in audit_path.read_text(encoding="utf-8")
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