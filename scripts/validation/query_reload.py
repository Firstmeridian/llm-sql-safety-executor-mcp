"""Isolated same-process stdio workflow; never opens configured databases."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def definition(root, name, sql, parameter=False):
    target = root / name
    target.mkdir(exist_ok=True)
    (target / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\n"
        "description: Isolated reload acceptance\n"
        + ("params:\n  n: {type: int, required: true}\n" if parameter else "params: {}\n")
        + "---\n", encoding="utf-8")
    (target / "query.sql").write_text(sql, encoding="utf-8")


async def workflow(python, package_root, mode):
    with tempfile.TemporaryDirectory(prefix="query-reload-stdio-") as temporary:
        root = Path(temporary)
        skills = root / "skills"
        skills.mkdir()
        definition(skills, "report", "SELECT :n AS n", True)
        database = root / "db.sqlite"
        with sqlite3.connect(database) as db:
            db.executescript("CREATE TABLE orders(amount INTEGER); INSERT INTO orders VALUES(700),(9900);")
        (root / "server.toml").write_text(
            'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
            '[server]\ndefault_connection="demo"\n')
        (root / "connections.toml").write_text(
            'schema_version=1\n[connections.demo]\ntype="sqlite"\n'
            '[connections.demo.sqlite]\npath="db.sqlite"\n[connections.demo.read]\nmode="all"\n')
        (root / "skills.toml").write_text(
            'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n')
        environment = dict(os.environ)
        # Explicitly select artifact first. PYTHONPATH does not execute editable
        # .pth hooks in the reused dependency directory.
        dependencies = subprocess.check_output(
            [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
        environment["PYTHONPATH"] = os.pathsep.join([str(package_root), dependencies])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        origin = subprocess.check_output(
            [python, "-c", "import sql_safety_executor; print(sql_safety_executor.__file__)"],
            env=environment, cwd=root, text=True).strip()
        if not Path(origin).is_relative_to(package_root):
            raise RuntimeError("Wrong product import origin")
        ledger = []
        transport = StdioTransport(
            command=python, args=["-m", "sql_safety_executor", "serve", "--config", str(root / "server.toml")],
            env=environment, cwd=str(root))
        async with Client(transport, mode=mode) as client:
            tools_before = [tool.name for tool in await client.list_tools()]
            if "reload_skills" not in tools_before:
                raise RuntimeError("Missing reload tool")
            async def call(label, tool, arguments):
                started = time.perf_counter()
                result = (await client.call_tool(tool, arguments)).structured_content
                ledger.append({"label": label, "tool": tool, "success": result.get("success"),
                               "client_ms": round((time.perf_counter()-started)*1000, 3)})
                return result
            args = {"skill_name": "report", "params": {"n": 7}}
            assert (await call("initial", "execute_query_skill", args))["data"] == [{"n": 7}]
            definition(skills, "totals", "SELECT SUM(amount) AS cents FROM orders")
            before = await call("before_publish", "list_skills", {})
            assert not any(item["name"] == "totals" for item in before["skills"])
            assert (await call("add", "reload_skills", {}))["added"] == ["totals"]
            detail = await call("detail", "get_skill_detail", {"skill_name": "totals"})
            assert detail["skill"]["name"] == "totals"
            assert (await call("business_total", "execute_query_skill", {"skill_name": "totals", "params": {}}))["data"] == [{"cents": 10600}]
            definition(skills, "report", "SELECT :n+1 AS n", True)
            assert (await call("still_old", "execute_query_skill", args))["data"] == [{"n": 7}]
            published = await call("change", "reload_skills", {})
            assert published["changed"] == ["report"]
            assert (await call("new_definition", "execute_query_skill", args))["data"] == [{"n": 8}]
            (skills / "report/query.sql").write_text("DELETE FROM orders")
            assert not (await call("reject_candidate", "reload_skills", {}))["success"]
            assert (await call("old_survives_failure", "execute_query_skill", args))["data"] == [{"n": 8}]
            definition(skills, "report", "SELECT :n+1 AS n", True)
            entry, parked = skills / "report", root / "parked-report"
            for replacement in ("file", "dangling"):
                entry.rename(parked)
                try:
                    if replacement == "file":
                        entry.write_text("incomplete deployment")
                    else:
                        entry.symlink_to("missing-target", target_is_directory=True)
                    rejected = await call(f"reject_{replacement}_entry", "reload_skills", {})
                    assert not rejected["success"] and rejected["reason"] == "skill_directory_unavailable"
                    assert rejected["revision"] == published["revision"]
                    assert (await call(f"cached_after_{replacement}", "execute_query_skill", args))["data"] == [{"n": 8}]
                finally:
                    entry.unlink()
                    parked.rename(entry)
            (skills / "totals/query.sql").unlink()
            (skills / "totals/skill_def.md").unlink()
            (skills / "totals").rmdir()
            removed = await call("real_directory_removal", "reload_skills", {})
            assert removed["success"] and removed["removed"] == ["totals"]
            assert (await call("live_read", "query", {"sql": "SELECT COUNT(*) AS n FROM orders"}))["data"] == [{"n": 2}]
            assert [tool.name for tool in await client.list_tools()] == tools_before
        with sqlite3.connect(database) as db:
            truth = db.execute("SELECT COUNT(*), SUM(amount) FROM orders").fetchone()
            assert truth == (2, 10600)
        return {"mode": mode, "origin": origin, "calls": ledger, "independent_truth": list(truth)}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    if sys.flags.optimize:
        parser.error("Validation requires assertions; optimized Python is unsupported")
    parser.add_argument("--python", required=True)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    reports = [await workflow(args.python, args.package_root.resolve(), mode) for mode in ("auto", "legacy")]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump({"reports": reports, "business_calls": sum(len(item["calls"]) for item in reports)}, output, indent=2)
    print(json.dumps({"modes": len(reports), "business_calls": sum(len(item["calls"]) for item in reports)}))


if __name__ == "__main__":
    asyncio.run(main())
