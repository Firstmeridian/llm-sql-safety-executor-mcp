"""Live private-session initialization/retirement checks, without business writes."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from sqlalchemy import event
from sql_safety_executor import load_config
from sql_safety_executor.database.mysql import MySQLAdapter


def run(config):
    records = []
    for explicit in (False, True):
        target = replace(config, mysql_sql_mode=("STRICT_TRANS_TABLES", "NO_ENGINE_SUBSTITUTION", "ANSI_QUOTES", "NO_BACKSLASH_ESCAPES") if explicit else None)
        adapter = MySQLAdapter(target)
        connected = []
        try:
            assert adapter.connect()
            event.listen(adapter._engine, "connect", lambda connection, record: connected.append(True))
            contract = adapter.resolve_analysis_context().sql_modes
            assert adapter.execute_read("SELECT 7 AS n", policy=config.policy)[0][0] == 7
            contract = adapter.analysis_context.sql_modes
            def inspect_pair():
                with adapter._engine.connect() as first, adapter._engine.connect() as second:
                    assert first.connection.dbapi_connection is not second.connection.dbapi_connection
                    values = []
                    for connection in (first, second):
                        mode = connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one()
                        values.append(frozenset(mode.split(",")) - {""})
                    assert all(value == contract for value in values)
                    return [sorted(value) for value in values]
            first_modes = inspect_pair()
            before = len(connected)
            # Only this private session changes; never global or business data.
            result = adapter.execute_write("SET SESSION sql_mode = :modes", {"modes": "NO_ENGINE_SUBSTITUTION"})
            assert result.execution_outcome.value == "committed"
            after_modes = inspect_pair()
            assert len(connected) > before  # The changed session was retired.
            stable_connections = len(connected)
            for _ in range(3):
                assert adapter.execute_read("SELECT 7 AS n", policy=config.policy)[0][0] == 7
            assert stable_connections == len(connected)
            adapter.execute("SELECT 11 AS n")  # Arbitrary trusted reader retires too.
            inspect_pair()
            assert len(connected) > stable_connections
            adapter.close()
            # An inherited profile stays the adapter contract after pool rebuild.
            assert adapter.analysis_context.sql_modes == contract
            assert adapter.execute_read("SELECT 7 AS n", policy=config.policy)[0][0] == 7
            assert adapter.analysis_context.sql_modes == contract
            records.append({"explicit": explicit, "contract": sorted(contract), "initial_pair": first_modes,
                            "after_retirement_pair": after_modes, "physical_sessions_before_rebuild": len(connected), "passed": True})
        finally:
            adapter.close()
    return {"records": records, "scope": "Actual configured MySQL private pool sessions; SET SESSION only, no business/global writes. No Host/protocol/model claim; host/account/connection IDs omitted."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new batch")
    value = run(load_config(args.config).connections[args.alias])
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print("Live session contracts passed:", len(value["records"]))
