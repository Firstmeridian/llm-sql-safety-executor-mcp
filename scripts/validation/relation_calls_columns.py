"""Validate relation calls and generated metadata via disposable child-stdio fixtures."""
from __future__ import annotations

import asyncio
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import sqlglot
import sql_safety_executor
from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.database.semantics import DialectContext

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "fts_docs", "substr", "ifnull", "char", "random", "iif", "replace",
    "strftime", "sleep", "get_lock", "load_file", "current_user", "printf",
    "lower", "abs", "count", "min", "max", "json_each", "json_tree", "a.b",
)


def snapshot():
    paths = list((ROOT / "src").rglob("*.py"))
    paths += [ROOT / "config" / name for name in ("server.toml", "connections.toml", "skills.toml")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def variants(name):
    quoted = quote(name)
    spelling = [("quoted", quoted), ("qualified", "main." + quoted)]
    if "." not in name:
        spelling.insert(0, ("bare", name))
    for style, reference in spelling:
        yield "from_" + style, f"SELECT body FROM {reference}('hello')"
        yield "join_" + style, f"SELECT f.body FROM orders JOIN {reference}('hello') AS f ON orders.n=7"
        yield "in_" + style, f"SELECT 'hello' IN {reference}('hello') AS matched"
    yield "match", f"SELECT body FROM {quoted} WHERE {quoted} MATCH 'hello'"


def truth(db, sql):
    try:
        cursor = db.execute(sql)
        columns = [item[0] for item in cursor.description]
        return {"data": [dict(zip(columns, row)) for row in cursor.fetchall()]}
    except sqlite3.Error as exc:
        return {"error": str(exc)}


def skill(folder, name, sql):
    directory = folder / "skills" / name
    directory.mkdir(parents=True)
    (directory / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\n"
        "description: Isolated external review assessment\nparams: {}\n---\n")
    (directory / "query.sql").write_text(sql)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=["source", "installed"], default="source")
    args = parser.parse_args()
    package = Path(sql_safety_executor.__file__).resolve().parent
    before = snapshot()
    output = {"scope": args.scope + ", disposable fixtures, auto/legacy child-stdio Client; not resident Host or model task",
              "package": str(package),
              "package_hashes": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in package.rglob('*') if p.is_file() and p.suffix in {'.py', '.md'}},
              "sqlite": sqlite3.sqlite_version, "sqlglot": sqlglot.__version__,
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "resources_before": before, "analysis": [], "calls": [], "truth": {}, "catalog": {}}
    with tempfile.TemporaryDirectory(prefix="v382-assess-") as temporary:
        folder = Path(temporary)
        database = folder / "fixture.sqlite"
        with sqlite3.connect(database) as db:
            db.executescript("CREATE TABLE orders(n);INSERT INTO orders VALUES(7);"
                "CREATE TABLE generated(id INTEGER PRIMARY KEY,base INTEGER NOT NULL,"
                "stored INTEGER GENERATED ALWAYS AS (base*2) STORED,"
                "virtual INTEGER GENERATED ALWAYS AS (base+3) VIRTUAL);"
                "INSERT INTO generated(id,base) VALUES(1,7);"
                "CREATE INDEX idx_generated ON generated(stored,virtual);"
                "CREATE VIEW generated_projection AS SELECT * FROM generated;")
            for name in NAMES:
                db.execute(f"CREATE VIRTUAL TABLE {quote(name)} USING fts5(body)")
                db.execute(f"INSERT INTO {quote(name)} VALUES('hello')")
                for variant, sql in variants(name):
                    key = name + ":" + variant
                    output["truth"][key] = truth(db, sql)
                    analysis = analyze_sql(sql, DialectContext("sqlite", default_schema="main"))
                    output["analysis"].append({"id": key, "sql": sql, "status": analysis.status,
                        "relations": [{"schema": ref.schema, "name": ref.name} for ref in analysis.relations],
                        "functions": sorted(analysis.functions), "unsupported": analysis.unsupported})
                skill(folder, "fts-" + name.replace("_", "-").replace(".", "-"),
                      f"SELECT body FROM {quote(name)}('hello')")
            skill(folder, "generated-report", "SELECT stored,virtual FROM generated")
            for table in ("generated", "generated_projection", "fts_docs"):
                output["catalog"][table] = {
                    "info": [list(row) for row in db.execute("SELECT * FROM pragma_table_info(?, 'main')", (table,))],
                    "xinfo": [list(row) for row in db.execute("SELECT * FROM pragma_table_xinfo(?, 'main')", (table,))],
                    "select_star": truth(db, "SELECT * FROM " + quote(table)),
                }
        initial_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        (folder / "server.toml").write_text(
            'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
            '[server]\ndefault_connection="scoped"\n[tools]\ntable_summary=true\n')
        granted = ["orders", "generated", "generated_projection", *NAMES]
        (folder / "connections.toml").write_text(
            'schema_version=1\n[connections.scoped]\ntype="sqlite"\nsqlite.path="fixture.sqlite"\n'
            'read.mode="allowlist"\nread.allow_union=true\nread.relations=[' +
            ','.join('{schema="main",name=' + json.dumps(name) + '}' for name in granted) + ']\n')
        (folder / "skills.toml").write_text(
            'schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n'
            '[skills.readiness]\ncheck_schema=true\n[skills.audit]\npath="audit.jsonl"\n')
        launcher = folder / "launcher.py"
        launcher.write_text("import sys\nfrom sql_safety_executor import create_server,load_config\n"
                            "create_server(load_config(sys.argv[1])).run(transport='stdio',show_banner=False)\n")
        for mode in ("auto", "legacy"):
            transport = StdioTransport(command=sys.executable,
                args=[str(launcher), str(folder / "server.toml")], cwd=str(folder))
            try:
                async with Client(transport, mode=mode) as client:
                    async def call(key, tool, arguments, expected=None):
                        result = await client.call_tool(tool, arguments, raise_on_error=False)
                        record = {"mode": mode, "id": key, "tool": tool, "arguments": arguments,
                                  "isError": result.is_error, "structured": result.structured_content}
                        if expected is not None:
                            record["expected"] = expected
                            record["matches_truth"] = bool(not result.is_error and isinstance(result.structured_content, dict)
                                and "data" in expected and result.structured_content.get("data") == expected["data"])
                        if result.is_error:
                            record["content"] = [item.model_dump(mode="json", exclude_none=True) for item in result.content]
                        output["calls"].append(record)
                        return result.structured_content

                    for name in NAMES:
                        for variant, sql in variants(name):
                            key = name + ":" + variant
                            await call(key, "query", {"sql": sql}, output["truth"][key])
                    await call("skills_available", "list_skills", {"detail_level": "full"})
                    await call("skills_all", "list_skills", {"detail_level": "full", "available_only": False})
                    for name in (*NAMES, "generated"):
                        name = "generated-report" if name == "generated" else "fts-" + name.replace("_", "-").replace(".", "-")
                        await call(name + ":detail", "get_skill_detail", {"skill_name": name})
                        await call(name + ":execute", "execute_query_skill", {"skill_name": name, "params": {}})
                    for table in ("generated", "generated_projection", "fts_docs"):
                        await call(table + ":query", "query", {"sql": "SELECT * FROM " + quote(table)},
                                   output["catalog"][table]["select_star"])
                        await call(table + ":describe", "describe_table", {"table_name": table})
                        await call(table + ":summary", "get_table_summary", {"table_name": table})
                    for level in ("compact", "full"):
                        await call("schema:" + level, "get_full_schema", {"detail_level": level, "group_identical": False})
                    for sql in ("SELECT SLEEP(0)", "SELECT GET_LOCK('x',0)", "SELECT LOAD_FILE('x')",
                                "SELECT * FROM fts_docs_idx", "SELECT * FROM generated WHERE stored=14"):
                        await call("control:" + sql, "query", {"sql": sql})
            finally:
                pass  # Client owns and closes the child stdio process.
        output["fixture_unchanged"] = initial_hash == hashlib.sha256(database.read_bytes()).hexdigest()
    after = snapshot()
    output["resources_unchanged"] = before == after
    output["fixture_cleaned"] = not Path(temporary).exists()
    counts = Counter()
    for record in output["calls"]:
        if "matches_truth" in record:
            counts[(record["mode"], "truth_match" if record["matches_truth"] else
                    (record["structured"] or {}).get("error_code", "other"))] += 1
    output["summary"] = [{"mode": key[0], "outcome": key[1], "count": value} for key, value in sorted(counts.items())]
    target = args.output.resolve()
    assert not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    assert output["fixture_unchanged"] and output["resources_unchanged"] and output["fixture_cleaned"]
    assert all(record["matches_truth"] for record in output["calls"] if "matches_truth" in record)
    for record in output["calls"]:
        assert not record["isError"], record["id"]
        payload = record["structured"]
        if record["tool"] == "get_skill_detail":
            assert payload["skill"]["executable"] and not payload["skill"]["missing_tables"]
        elif record["tool"] == "execute_query_skill":
            assert payload["success"]
        elif record["id"] in {"generated:describe", "generated:summary"}:
            assert payload["column_count"] == 4
            assert [c.get("generation_type") for c in payload["columns"]] == [None, None, "stored", "virtual"]
        elif record["id"] in {"schema:compact", "schema:full"}:
            assert payload["total_columns"] == 26
        elif record["id"] == "fts_docs:describe":
            assert payload["column_count"] == 1
        elif record["id"].startswith("control:") and not record["id"].startswith("control:SELECT * FROM generated"):
            assert payload["success"] is False
    print(json.dumps({"calls": len(output["calls"]), "summary": output["summary"],
                      "resources_unchanged": True, "fixture_unchanged": True, "fixture_cleaned": True,
                      "evidence": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
