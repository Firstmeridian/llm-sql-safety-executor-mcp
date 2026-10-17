"""Matched source-selectable policy/Client costs; never infer model tokens.

Run A/B/A as separate processes, selecting a frozen baseline and current src.
Each batch uses its own disposable SQLite fixture and cannot overwrite results.
"""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import replace
import gzip
import hashlib
import json
import logging
from pathlib import Path
import resource
import sqlite3
import statistics
import sys
import tempfile
import time
from types import MappingProxyType


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new batch")
    sys.path.insert(0, str(args.source.resolve()))
    logging.disable(logging.CRITICAL)  # Same no-log benchmark setup in A/B/A.
    began = time.perf_counter()
    import sql_safety_executor
    from sql_safety_executor import create_server, load_config
    from sql_safety_executor.core.policy import _validate_sql_query_policy
    from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
    assert Path(sql_safety_executor.__file__).is_relative_to(args.source.resolve())
    policy_import_ms = (time.perf_counter() - began) * 1000
    from fastmcp import Client
    queries = [
        "SELECT 7 AS n",
        "SELECT COUNT(*) AS n FROM orders",
        "WITH selected AS (SELECT id,amount FROM orders WHERE amount>=10) SELECT SUM(amount) AS n FROM selected",
        "WITH sums AS (SELECT order_id,SUM(amount) AS n FROM items GROUP BY order_id) SELECT SUM(s.n) AS n FROM orders o JOIN sums s ON s.order_id=o.id",
        "SELECT SUM(n) AS n FROM report",
        "SELECT SLEEP(0) AS n",
    ]
    policy = ConnectionPolicy(allowed_tables=frozenset({"orders", "items", "report"}), allow_union=True)
    samples = {sql: [] for sql in queries}
    decisions = {}
    for _ in range(81):
        for sql in queries:
            start = time.perf_counter_ns()
            verdict = _validate_sql_query_policy(None, sql, policy)
            samples[sql].append((time.perf_counter_ns() - start) / 1e6)
            decisions[sql] = {"allowed": verdict.allowed, "code": verdict.error_code}

    def stats(values):
        return {"median_ms": statistics.median(values), "p95_ms": sorted(values)[max(0, int(len(values) * .95) - 1)], "raw_ms": values}

    base = load_config(args.config)
    results = []
    with tempfile.TemporaryDirectory(prefix="v382-cost-") as temporary:
        path = Path(temporary)
        database = path / "fixture.sqlite"
        with sqlite3.connect(database) as conn:
            conn.executescript("CREATE TABLE orders(id INTEGER,amount REAL);CREATE TABLE items(order_id INTEGER,amount REAL);CREATE VIEW report AS SELECT amount AS n FROM orders;")
            conn.executemany("INSERT INTO orders VALUES(?,?)", [(i, i + 10) for i in range(1, 201)])
            conn.executemany("INSERT INTO items VALUES(?,?)", [(i, (i + 10) / 2) for i in range(1, 201) for _ in range(2)])
            truth = [[list(row) for row in conn.execute(sql)] for sql in queries[:-1]]
        directory = path / "skills" / "cost-report"
        directory.mkdir(parents=True)
        (directory / "skill_def.md").write_text("---\nname: cost-report\ntype: query\nsource: query.sql\nrisk: low\ndescription: Matched report\nparams: {}\n---\n")
        (directory / "query.sql").write_text(queries[3])
        config = replace(base,
            server=base.server.model_copy(update={"server": base.server.server.model_copy(update={"default_connection": "probe"})}),
            skills=base.skills.model_copy(update={"enabled": True, "directory": str(directory.parent),
                "mutation": base.skills.mutation.model_copy(update={"enabled": False}),
                "audit": base.skills.audit.model_copy(update={"enabled": False, "path": str(path / "audit.jsonl")})}),
            connections=MappingProxyType({"probe": DatabaseConfig("probe", "sqlite", 30, 5, policy, sqlite_database_path=str(database))}))

        async def run():
            for mode in ("auto", "legacy"):
                start = time.perf_counter()
                server = create_server(config)
                try:
                    async with Client(server, mode=mode) as client:
                        startup_ms = (time.perf_counter() - start) * 1000
                        tools = await client.list_tools()
                        metadata = {"instructions": client.instructions, "tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in tools]}
                        compact = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
                        trace, rounds = [], []
                        calls = [("query", {"sql": sql}) for sql in queries] + [("execute_query_skill", {"skill_name": "cost-report", "params": {}})]
                        for repeat in range(13):
                            elapsed = []
                            for i, (tool, parameters) in enumerate(calls):
                                start = time.perf_counter_ns()
                                result = await client.call_tool(tool, parameters, raise_on_error=False)
                                elapsed.append((time.perf_counter_ns() - start) / 1e6)
                                payload = result.structured_content
                                if i < 5:
                                    assert payload["success"] and [list(row.values()) for row in payload["data"]] == truth[i], payload
                                elif i == 5:
                                    assert payload["error_code"] == "expensive_function_denied", payload
                                else:
                                    assert payload["success"]
                                if repeat == 0:
                                    trace.append({"tool": tool, "arguments": parameters, "structured": payload,
                                        "content": [c.model_dump(mode="json", exclude_none=True) for c in result.content], "isError": result.is_error})
                            rounds.append(elapsed)
                        results.append({"protocol": client.protocol_version, "startup_ms": startup_ms,
                            "metadata_characters": len(compact), "metadata_sha256": hashlib.sha256(compact.encode()).hexdigest(),
                            "trace": trace, "warm_trace": stats([sum(values) for values in rounds[1:]]), "rounds_ms": rounds})
                finally:
                    server.gateway_runtime.close()
        asyncio.run(run())
        cache = {}
        for size in (128, 0):
            with sqlite3.connect(database, cached_statements=size) as conn:
                for sql in queries[:4]:
                    values = []
                    for _ in range(101):
                        start = time.perf_counter_ns()
                        conn.execute(sql).fetchall()
                        values.append((time.perf_counter_ns() - start) / 1e6)
                    cache[f"{size}:{sql}"] = stats(values[1:])
    data = {"stage": args.stage, "version": sql_safety_executor.__version__, "policy_import_ms": policy_import_ms,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "source_sha256": {str(p.relative_to(args.source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.source.rglob("*")) if p.is_file() and p.suffix in {".py", ".md"}},
        "policy": [{"sql": sql, **decisions[sql], **stats(values[1:])} for sql, values in samples.items()],
        "clients": results, "native_statement_cache": cache,
        "limits": "Single-process local matched workload; timings include real in-process Client but no transport network/model. Characters are not tokens. No configured DB writes. Warm samples exclude first round; startup separate. No full protocol-frame capture."}
    data["benchmark_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data["logging"] = "Disabled identically in all stages; production logging overhead not measured"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode(), mtime=0))
    print(json.dumps({"stage": args.stage, "clients": len(results), "calls": 13 * 7 * len(results)}))


if __name__ == "__main__":
    main()
