"""Read-only fixture CLI for the 2026-09-22 Agent trials; not a production Host.

Each invocation opens a fresh in-memory FastMCP client/server session. The
SQLite fixtures and Agent conversation persist between calls. This does not
exercise process-long admission, cancellation or cleanup-latch state.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--single-connection-fixture", action="store_true")
    parser.add_argument("--trial", default="coordinator")
    parser.add_argument("--turn", type=int, default=0)
    parser.add_argument("action", choices=["metadata", "call"])
    parser.add_argument("--tool")
    parser.add_argument("--arguments", default="{}")
    args = parser.parse_args()
    allowed = {"list_connections", "check_connection", "check_connections", "list_tables", "describe_table", "get_full_schema", "query"}
    if args.action == "call" and args.tool not in allowed:
        parser.error("Only the read-only core tool set is allowed")
    args.fixture_root.mkdir(parents=True, exist_ok=True)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    for key in list(os.environ):
        if key.startswith(("DB_", "SKILLS_", "MCP_", "ENABLE_", "TOOL_TELEMETRY")) or key in {"DEFAULT_DB_CONNECTION", "SQLITE_DATABASE_PATH", "ALLOWED_TABLES", "DENIED_TABLES", "READONLY"}:
            del os.environ[key]
    os.environ.update({"PYTHON_DOTENV_DISABLED": "1", "DB_CONNECTIONS": "trade_analysis_mysql,analytics_demo_sqlite,live_test_sqlite", "DEFAULT_DB_CONNECTION": "trade_analysis_mysql", "ENABLE_SKILLS": "0", "SKILLS_ALLOW_MUTATIONS": "0", "ENABLE_SCHEMA_TOOLS": "1", "ENABLE_TABLE_SUMMARY": "0", "ENABLE_TOOL_TELEMETRY": "0", "MCP_TOOL_TIMEOUT_SECONDS": "120", "READONLY": "1", "ALLOWED_TABLES": "orders,future_orders", "DENIED_TABLES": ""})
    if args.single_connection_fixture:
        os.environ["DB_CONNECTIONS"] = "analytics_demo_sqlite"
        os.environ["DEFAULT_DB_CONNECTION"] = "analytics_demo_sqlite"
    for alias in os.environ["DB_CONNECTIONS"].split(","):
        database = args.fixture_root / f"{alias}.db"
        if not database.exists():
            with sqlite3.connect(database) as connection:
                connection.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT, order_date TEXT, total_amount REAL); CREATE TABLE hidden_internal(id INTEGER PRIMARY KEY);")
                connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [(1, "completed", "2026-09-01", 100), (2, "completed", "2026-09-02", 200), (3, "confirmed", "2026-09-03", 300), (4, "pending", "2026-09-04", 400), (5, "shipped", "2026-09-05", 500)])
        prefix = f"DB_{alias.upper()}_"
        os.environ.update({prefix + "TYPE": "sqlite", prefix + "SQLITE_DATABASE_PATH": str(database), prefix + "ALLOWED_TABLES": "orders,future_orders", prefix + "DENIED_TABLES": "", prefix + "MUTATION_SKILLS": ""})
    import dotenv
    dotenv.load_dotenv = lambda *_args, **_kwargs: False
    sys.path.insert(0, str(args.source))
    module = importlib.import_module("mcp_sql_server")
    # Enforce the fixture boundary before Client enters the server lifespan.
    # Fail closed if any environment/configuration path could select a real DB.
    fixture_root = args.fixture_root.resolve(strict=True)
    configs = module.list_connection_configs()
    expected_aliases = set(os.environ["DB_CONNECTIONS"].split(","))
    if {config.connection_id for config in configs} != expected_aliases:
        raise RuntimeError("Fixture aliases do not match the isolated configuration")
    for config in configs:
        if config.db_type != "sqlite" or config.sqlite_database_path is None:
            raise RuntimeError("Only synthetic SQLite fixtures may be accessed")
        database_path = Path(config.sqlite_database_path).resolve(strict=True)
        expected_path = fixture_root / f"{config.connection_id}.db"
        if database_path != expected_path or not database_path.is_relative_to(fixture_root):
            raise RuntimeError("Database path escapes the isolated fixture directory")
    from fastmcp import Client

    async def scenario() -> None:
        async with Client(module.mcp) as client:
            hashes = {name: hashlib.sha256((args.source / name).read_bytes()).hexdigest() for name in ("mcp_sql_server.py", "connection_diagnostics.py", "db_adapter.py", "sql_safety_checker.py")}
            if args.action == "metadata":
                result = {"stage": args.stage, "transport": "FastMCP in-memory; fresh Python process per CLI invocation", "source_sha256": hashes, "initialize": client.initialize_result.model_dump(mode="json") if client.initialize_result else None, "tools": [tool.model_dump(mode="json") for tool in await client.list_tools()], "fixture": {"all_db_types": "sqlite", "aliases": os.environ["DB_CONNECTIONS"].split(","), "default": os.environ["DEFAULT_DB_CONNECTION"], "skills_enabled": False, "visible_rows": 5, "dotenv_disabled": True}}
                (args.evidence_dir / f"UNIFIED_DIAGNOSTICS_METADATA_{args.stage}_2026_09_22.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            else:
                arguments = json.loads(args.arguments)
                started = time.monotonic()
                response = await client.call_tool(args.tool, arguments, raise_on_error=False)
                result = {"stage": args.stage, "trial": args.trial, "turn": args.turn, "tool": args.tool, "arguments": arguments, "elapsed_ms": round((time.monotonic() - started) * 1000, 3), "is_error": response.is_error, "structured_content": response.structured_content, "content": [item.model_dump(mode="json") for item in response.content], "meta": response.meta, "source_sha256": hashes}
                with (args.evidence_dir / f"UNIFIED_DIAGNOSTICS_TRACE_{args.stage}_2026_09_22.jsonl").open("a") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(json.dumps(result, ensure_ascii=False))
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
