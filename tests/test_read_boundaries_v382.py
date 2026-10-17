"""Data-reading metadata and non-executing plans share SQLite read ownership."""
import sqlite3
from dataclasses import replace

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.errors import DatabaseQueryError
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("function,code", [
    ("SLEEP", "expensive_function_denied"),
    ("BENCHMARK", "expensive_function_denied"),
    ("GET_LOCK", "lock_function_denied"),
    ("RELEASE_LOCK", "lock_function_denied"),
    ("RELEASE_ALL_LOCKS", "lock_function_denied"),
    ("LOAD_FILE", "file_operation_denied"),
    ("USER", "server_state_denied"),
    (None, "server_state_denied"),
])
async def test_view_data_reads_keep_guards_and_metadata(bundle, tmp_path, mode, qualified, function, code):
    settings, connections, _, save = bundle
    settings["tools"] = {"schema": True, "table_summary": True}
    names = ["report", "normal"]
    prefix = "main." if qualified else ""
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": [prefix + n for n in names]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE VIEW normal AS SELECT n FROM orders;")
        body = f'SELECT n FROM orders WHERE "{function}"()=0' if function else "SELECT seq AS n FROM pragma_database_list"
        db.execute("CREATE VIEW report AS " + body)
    server = create_server(load_config(save()))
    calls = []
    try:
        async with Client(server, mode=mode) as client:
            adapter = server.gateway_runtime.registry.get_adapter("demo")
            assert adapter.connect()
            if function:
                with adapter._engine.connect() as db:
                    db.connection.dbapi_connection.create_function(function, 0, lambda: calls.append(True) or 0)
            for tool, arguments in [
                ("query", {"sql": f"SELECT n FROM {prefix}report"}),
                ("sample", {"table_name": "report"}),
                ("get_table_summary", {"table_name": "report", "exact_count": True}),
            ]:
                payload = (await client.call_tool(tool, arguments)).structured_content
                assert payload["success"] is False and payload["error_code"] == code
                assert calls == []
            for tool in ["get_table_summary", "describe_table"]:
                payload = (await client.call_tool(tool, {"table_name": "report"})).structured_content
                assert payload["success"] and payload["row_count"] is None
                assert payload["columns"] and calls == []
            described = (await client.call_tool("describe_table", {"table_name": "report"})).structured_content
            assert described["indexes_status"] == "complete" and described["indexes"] == []
            # A view grant authorizes its reviewed source chain, not direct base reads.
            for tool, arguments in [
                ("query", {"sql": f"SELECT n FROM {prefix}normal"}),
                ("query", {"sql": f"SELECT COUNT(*) AS n FROM {prefix}normal"}),
                ("query", {"sql": f"WITH selected AS (SELECT n FROM {prefix}normal) SELECT COUNT(*) AS n FROM selected"}),
                ("sample", {"table_name": "normal"}),
                ("get_table_summary", {"table_name": "normal", "exact_count": True}),
                ("get_table_summary", {"table_name": "normal"}),
                ("describe_table", {"table_name": "normal"}),
            ]:
                payload = (await client.call_tool(tool, arguments)).structured_content
                assert payload["success"] and payload["row_count"] == 1
            assert adapter.get_row_estimate("orders") is None
            policy = server.gateway_runtime.registry.get_config("demo").policy
            # A view's extra source-less count event must not authorize an
            # independently requested base, even without frontend validation.
            with pytest.raises(DatabaseQueryError) as denied:
                adapter.execute_read("SELECT COUNT(*) FROM main.normal WHERE (SELECT COUNT(*) FROM main.orders)>0", policy=policy)
            assert denied.value.error_code == "table_access_denied"
            for tool in ["list_tables", "get_full_schema"]:
                payload = (await client.call_tool(tool, {})).structured_content
                assert payload["success"] and payload["total_tables"] == 0
            assert calls == [] and adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("prefix", ["EXPLAIN", "EXPLAIN QUERY PLAN"])
@pytest.mark.parametrize("body", ["UPDATE {table} SET n=99", "DELETE FROM {table}", "INSERT INTO {table} VALUES(99)", "REPLACE INTO {table} VALUES(99)"])
async def test_nonexecuting_dml_plan_preserves_data_and_scope(bundle, tmp_path, mode, qualified, prefix, body):
    _, connections, _, save = bundle
    table = "main.orders" if qualified else "orders"
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": [table]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13);")
    server = create_server(load_config(save()))
    try:
        async with Client(server, mode=mode) as client:
            sql = f"{prefix} " + body.format(table=table)
            planned = (await client.call_tool("query", {"sql": sql})).structured_content
            assert planned["success"]  # QUERY PLAN DELETE may correctly return no rows.
            denied = (await client.call_tool("query", {"sql": body.format(table=table)})).structured_content
            assert denied["error_code"] == "read_only_required"
            hidden = (await client.call_tool("query", {"sql": f"{prefix} " + body.format(table="hidden")})).structured_content
            assert hidden["error_code"] == "table_access_denied"
            adapter = server.gateway_runtime.registry.get_adapter("demo")
            assert adapter.execute("SELECT n FROM main.orders") == [(7,)]
            assert adapter.execute("SELECT n FROM main.hidden") == [(13,)]
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


async def test_plan_context_cannot_leak_to_other_sql_or_trigger_targets(bundle, tmp_path):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["orders", "main.orders"]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(n); INSERT INTO orders VALUES(7); CREATE TABLE hidden(n); INSERT INTO hidden VALUES(13);")
    server = create_server(load_config(save()))
    try:
        async with Client(server) as client:
            adapter = server.gateway_runtime.registry.get_adapter("demo")
            policy = server.gateway_runtime.registry.get_config("demo").policy
            plan_sql = "EXPLAIN UPDATE main.orders SET n=99"
            analysis = analyze_sql(plan_sql, adapter.analysis_context)
            assert analysis.explain_payload == "update"
            with pytest.raises(DatabaseQueryError) as denied:
                adapter.execute_read("UPDATE main.orders SET n=99", policy=policy, analysis=analysis)
            assert denied.value.error_code == "session_semantics_unavailable"
            assert adapter.execute_read(plan_sql, policy=policy, analysis=analysis)
            calls = []
            with adapter._engine.begin() as db:
                db.connection.dbapi_connection.create_function("SLEEP", 0, lambda: calls.append(True) or 0)
                db.exec_driver_sql("CREATE TRIGGER mirror AFTER INSERT ON orders BEGIN INSERT INTO hidden VALUES(new.n); END")
                db.exec_driver_sql("CREATE TEMP TABLE orders(n)")
            for sql, code in [
                ("EXPLAIN UPDATE main.orders SET n=SLEEP()", "expensive_function_denied"),
                ("EXPLAIN INSERT INTO main.orders SELECT n FROM main.hidden", "table_access_denied"),
            ]:
                with pytest.raises(DatabaseQueryError) as denied:
                    adapter.execute_read(sql, policy=policy)
                assert denied.value.error_code == code and calls == []
            for sql in ["EXPLAIN INSERT INTO main.orders VALUES(99)", "EXPLAIN UPDATE orders SET n=99"]:
                denied = (await client.call_tool("query", {"sql": sql})).structured_content
                assert denied["error_code"] == "table_access_denied"
            for sql in ["EXPLAIN PRAGMA user_version=99", "EXPLAIN CREATE TABLE changed(n)", "EXPLAIN ATTACH ':memory:' AS changed"]:
                denied = (await client.call_tool("query", {"sql": sql})).structured_content
                assert not denied["success"]
            assert adapter.execute("PRAGMA user_version") == [(0,)]
            assert adapter.execute("SELECT name FROM main.sqlite_master WHERE name='changed'") == []
            assert adapter.execute("SELECT n FROM main.orders") == [(7,)]
            assert adapter.execute("SELECT n FROM main.hidden") == [(13,)]
            assert adapter._active_guard is None and adapter._read_request is None
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("kind", ["TABLE", "VIEW"])
@pytest.mark.parametrize("name", ["__mcp_row_estimate", "__mcp_row_estimate_"])
async def test_estimate_template_name_does_not_reserve_business_names(bundle, tmp_path, kind, name):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": [name]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        if kind == "TABLE":
            db.executescript(f'CREATE TABLE "{name}"(n);INSERT INTO "{name}" VALUES(7);')
        else:
            db.execute(f'CREATE VIEW "{name}" AS SELECT 7 AS n')
    server = create_server(load_config(save()))
    try:
        adapter = server.gateway_runtime.registry.get_adapter("demo")
        assert adapter.get_row_estimate(name) == 1
    finally:
        server.gateway_runtime.close()


def test_estimate_does_not_read_catalog_or_data_for_ungranted_objects(bundle, monkeypatch):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["orders"]}
    server = create_server(load_config(save()))
    try:
        adapter = server.gateway_runtime.registry.get_adapter("demo")
        monkeypatch.setattr(adapter, "_execute_metadata", lambda *_a, **_k: pytest.fail("Unexpected metadata read"))
        assert adapter.get_row_estimate("hidden") is None
        adapter._config = replace(adapter._config, policy=replace(adapter._config.policy, read_mode="deny"))
        assert adapter.get_row_estimate("orders") is None
    finally:
        server.gateway_runtime.close()
