"""Recheck frozen SQLite inputs and native MySQL mode/name truth.

Only private SQLite and disposable MySQL session/temporary objects are changed.
Results are observations, not a certification of all SQL grammar or vendors.
Never overwrite an earlier batch. Run from an installed project environment.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import uuid

from sql_safety_executor import load_config
from sql_safety_executor.core.analysis import analyze_sql
from sql_safety_executor.core.policy import _validate_sql_query_policy
from sql_safety_executor.database.models import ConnectionPolicy
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.mysql import MySQLAdapter
from sql_safety_executor.database.semantics import DialectContext

ROOT = Path(__file__).resolve().parents[2]


def sqlite_matrix():
    archive = ROOT / "docs/validation/v3.8/cte_analysis_2026_10_15"
    names = ["window", "offset", "lock", "filter", "over", "for", "key", "index", "returning", "lımıt", "offſet", "wındow", "unıon", "ınsert", "f", "main.orders", " f ", "[f]"]
    groups, inputs = {}, {}
    for name in ("adjacent_audit", "boundary_context_audit", "impact_matrix", "header_scan_matrix"):
        path = archive / (name + ".json.gz")
        inputs[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        groups[name] = json.loads(gzip.decompress(path.read_bytes()))["records"]
    records = []
    with sqlite3.connect(":memory:") as native:
        native.executescript("CREATE TABLE orders(n);INSERT INTO orders VALUES(7);CREATE TABLE other(n);INSERT INTO other VALUES(99);CREATE TABLE private_orders(n);INSERT INTO private_orders VALUES(99);")
        for name in ("SLEEP", "BENCHMARK", "GET_LOCK", "LOAD_FILE", "USER", "CURRENT_ROLE"):
            native.create_function(name, -1, lambda *args: 7)
        for group, cases in groups.items():
            if group == "adjacent_audit":
                for name in sorted({r["name"] for r in cases} - {"orders", "other", "private_orders"}):
                    quoted = '"' + name.replace('"', '""') + '"'
                    native.execute(f"CREATE TABLE {quoted}(n)")
                    native.execute(f"INSERT INTO {quoted} VALUES(99)")
            elif group == "boundary_context_audit":
                for name in sorted({r["name"] for r in groups["adjacent_audit"]} - {"orders", "other", "private_orders"}):
                    native.execute('DROP TABLE "' + name.replace('"', '""') + '"')
                for name in names:
                    native.execute('CREATE INDEX "' + name.replace('"', '""') + '" ON orders(n)')
            for old in cases:
                sql = old["sql"]
                try:
                    truth = [list(row) for row in native.execute(sql)]
                except sqlite3.Error as exc:
                    records.append({"group": group, "sql": sql, "native_valid": False, "native_error": type(exc).__name__})
                    continue
                grants = {"orders", "other"} if group == "boundary_context_audit" else {"orders", old.get("name", "orders")}
                no = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset({"orders"}), allow_union=True))
                refs = frozenset(RelationReference(name, schema) for name in grants for schema in (None, "main"))
                yes = _validate_sql_query_policy(None, sql, ConnectionPolicy(allowed_tables=frozenset(ref.display_name for ref in refs), allowed_relations=refs, allow_union=True))
                analysis = analyze_sql(sql, DialectContext("sqlite"))
                records.append({"group": group, "sql": sql, "native_valid": True, "rows": truth,
                                "restricted": asdict(no), "approved": asdict(yes),
                                "analysis_status": analysis.status, "unsupported": analysis.unsupported,
                                "relations": [asdict(ref) for ref in analysis.relations],
                                "prior_expected_code": old.get("after_code", old.get("unapproved_code"))})
    return {"input_sha256": inputs, "records": records,
            "limits": "Frozen inputs rerun against independent private sqlite3. Different fixtures can change row values; never infer native MCP/model results."}


def mysql_matrix(config_path: Path, alias: str):
    config = load_config(config_path).connections[alias]
    probe = MySQLAdapter(config, diagnostic=True)
    try:
        # Direct DBAPI cursor independently observes column labels and values.
        assert probe.connect() and probe._engine is not None
        with probe._engine.connect() as connection:
            raw = connection.connection.dbapi_connection
            with raw.cursor() as cursor:
                cursor.execute("SELECT VERSION(),@@lower_case_table_names,@@SESSION.sql_mode")
                version, case_rule, mode_text = cursor.fetchone()
        baseline = frozenset(mode_text.split(",")) - {"", "ANSI_QUOTES", "NO_BACKSLASH_ESCAPES", "PIPES_AS_CONCAT"}
    finally:
        probe.close()
    records = []
    for enabled in itertools.product((False, True), repeat=3):
        flags = {name for name, yes in zip(("ANSI_QUOTES", "NO_BACKSLASH_ESCAPES", "PIPES_AS_CONCAT"), enabled) if yes}
        adapter = MySQLAdapter(replace(config, mysql_sql_mode=tuple(sorted(baseline | flags))), diagnostic=True)
        try:
            assert adapter.connect() and adapter._engine is not None
            with adapter._engine.connect() as connection:
                raw = connection.connection.dbapi_connection
                with raw.cursor() as cursor:
                    def observe(label, sql):
                        row = {"flags": sorted(flags), "case": label, "sql": sql}
                        analysis = analyze_sql(sql, adapter.analysis_context)
                        row["analysis"] = {"status": analysis.status, "kind": analysis.statement_kind,
                                           "relations": [asdict(ref) for ref in analysis.relations], "unsupported": analysis.unsupported}
                        try:
                            cursor.execute(sql)
                            row.update(success=True, rows=cursor.fetchall(), labels=[item[0] for item in cursor.description or ()])
                        except Exception as exc:
                            row.update(success=False, error_class=type(exc).__name__, errno=exc.args[0] if exc.args and type(exc.args[0]) is int else None)
                        records.append(row)
                        return row
                    for name in [r"a\b", "a`b", r"a\`b", " f ", "  f  "]:
                        observe("result_alias", "SELECT 7 AS `" + name.replace("`", "``") + "`")
                    for sql in ["SELECT 'a'||'b' AS n", 'SELECT "n" AS label', r"SELECT 'a\nb' AS label"]:
                        observe("mode_expression", sql)
                    table = "v382_" + uuid.uuid4().hex[:16]
                    for name in [table, table + " ", table + "_K", table + "_a`b"]:
                        quoted = "`" + name.replace("`", "``") + "`"
                        row = observe("temporary_relation_definition", f"CREATE TEMPORARY TABLE {quoted}(n INTEGER)")
                        if row["success"]:
                            cursor.execute(f"INSERT INTO {quoted} VALUES(7)")
                            observe("temporary_relation_read", f"SELECT n FROM {quoted}")
                            if name == table:
                                observe("nonrecursive_self_physical", f"WITH {quoted} AS (SELECT n FROM {quoted}) SELECT n FROM {quoted}")
                                observe("forward_physical", f"WITH first_cte AS (SELECT n FROM {quoted}), {quoted} AS (SELECT 99 AS n) SELECT n FROM first_cte")
                                observe("explicit_recursive", f"WITH RECURSIVE {quoted}(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM {quoted} WHERE n<3) SELECT n FROM {quoted}")
                            cursor.execute(f"DROP TEMPORARY TABLE {quoted}")
        finally:
            adapter.close()  # Session-only objects cannot survive this NullPool.
    return {"version": version, "lower_case_table_names": case_rule, "records": records,
            "limits": "One configured Oracle MySQL instance. No global modes/permanent/business data modified; temporary objects and private session modes only. Other case settings/MariaDB unmeasured."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config/server.toml")
    parser.add_argument("--mysql-alias")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new evidence path")
    result = {"sqlite_version": sqlite3.sqlite_version, "sqlite": sqlite_matrix()}
    if args.mysql_alias:
        result["mysql"] = mysql_matrix(args.config, args.mysql_alias)
    result["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "src/sql_safety_executor").rglob("*.py"))}
    result["recording_profile"] = "Native fixture truth and application policy; no protocol frames or model usage"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress((json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n").encode(), mtime=0))
    print(json.dumps({"sqlite_records": len(result["sqlite"]["records"]), "mysql_records": len(result.get("mysql", {}).get("records", []))}))


if __name__ == "__main__":
    main()
