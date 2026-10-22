"""Explicit live MySQL/InnoDB release gate in a disposable schema.

Requires CREATE/DROP DATABASE and TRIGGER for the configured test account.
Only connections opened by this harness may be killed. No global settings,
existing business tables, repository configuration or grants are changed.
Native PyMySQL observers do not use project analysis, authorization or results.
Client fault injections are labelled separately from actual server failures.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from unittest.mock import patch


CASES = [
    ("update", "UPDATE orders SET n=:n WHERE id=1", {"n":99}),
    ("cte-update", "WITH chosen AS(SELECT 1 AS id) UPDATE orders SET n=:n WHERE id IN(SELECT id FROM chosen)", {"n":99}),
    ("comment-update", "/* original */ UPDATE orders SET n=:n WHERE id=1", {"n":99}),
    ("cte-insert", "INSERT INTO orders(id,n,u) WITH chosen AS(SELECT 3 AS id) SELECT id,:n,'three' FROM chosen", {"n":99}),
    ("cte-delete", "WITH chosen AS(SELECT 1 AS id) DELETE FROM orders WHERE id IN(SELECT id FROM chosen)", {}),
    ("zero", "UPDATE orders SET n=:n WHERE id=999", {"n":99}),
    ("matched-unchanged", "UPDATE orders SET n=:n WHERE id=1", {"n":7}),
    ("multi", "UPDATE orders SET n=n+:n", {"n":100}),
    ("insert", "INSERT INTO orders(id,n,u) VALUES(3,:n,'three')", {"n":99}),
    ("ignore", "INSERT IGNORE INTO orders(id,n,u) VALUES(3,:n,'one')", {"n":99}),
    ("replace", "REPLACE INTO orders(id,n,u) VALUES(1,:n,'one')", {"n":99}),
    ("upsert", "INSERT INTO orders(id,n,u) VALUES(1,:n,'one') ON DUPLICATE KEY UPDATE n=VALUES(n)", {"n":99}),
    ("delete-cascade", "DELETE FROM orders WHERE id=1", {}),
    ("update-cascade", "UPDATE orders SET id=3 WHERE id=1", {}),
]


def redacted(value):
    if isinstance(value, dict):
        return {k:"<redacted>" if k in {"preview_token","preview_token_id"} else redacted(v) for k,v in value.items()}
    if isinstance(value, list): return [redacted(v) for v in value]
    if isinstance(value, str) and value.startswith("{"):
        try: return json.dumps(redacted(json.loads(value)),ensure_ascii=False)
        except (ValueError,TypeError): pass
    return value


class Fault:
    """Labelled application/driver-boundary intervention over a real engine."""
    def __init__(self, mode, fixture):
        self.mode, self.fixture, self.hit = mode, fixture, []
        self.connection = None

    def mark(self, name): self.hit.append(name)

    def engine(self, engine):
        fault = self
        class Engine:
            def connect(self):
                if fault.mode == "checkout":
                    fault.mark("checkout"); raise RuntimeError("injected checkout failure")
                real = engine.connect()
                fault.connection = real
                return Connection(real)
            def __getattr__(self, name): return getattr(engine,name)
        class Transaction:
            def __init__(self, real): self.real = real
            def __getattr__(self, name): return getattr(self.real,name)
            def commit(self):
                if fault.mode == "commit-before":
                    fault.mark("commit-before"); raise RuntimeError("injected commit uncertainty")
                self.real.commit()
                if fault.mode == "commit-after":
                    fault.mark("commit-after"); raise RuntimeError("injected acknowledgement loss after real commit")
            def rollback(self):
                if fault.mode == "rollback-before":
                    fault.mark("rollback-before"); raise RuntimeError("injected rollback failure")
                self.real.rollback()
                if fault.mode == "rollback-after":
                    fault.mark("rollback-after"); raise RuntimeError("injected rollback acknowledgement loss")
        class Result:
            def __init__(self, real): self.real = real
            def __getattr__(self, name): return getattr(self.real,name)
            @property
            def rowcount(self):
                fault.mark("rowcount"); raise RuntimeError("injected result/count access failure")
        class Connection:
            def __init__(self, real): self.real = real
            def __getattr__(self, name): return getattr(self.real,name)
            def begin(self):
                if fault.mode == "begin-before":
                    fault.mark("begin-before"); raise RuntimeError("injected begin failure")
                if fault.mode == "kill-before-begin":
                    fault.fixture.kill(self.real); fault.mark("kill-before-begin")
                tx = self.real.begin()
                if fault.mode == "begin-after":
                    fault.mark("begin-after"); raise RuntimeError("injected failure after real begin")
                return Transaction(tx)
            def execute(self, statement, params=None):
                business = str(statement).lstrip().startswith("UPDATE orders")
                if business and fault.mode == "execute-before":
                    fault.mark("execute-before"); raise RuntimeError("injected execute failure")
                result = self.real.execute(statement,params or {})
                if business and fault.mode == "execute-after":
                    fault.mark("execute-after"); raise RuntimeError("injected failure after real DML")
                if business and fault.mode == "kill-after-execute":
                    fault.fixture.kill(self.real); fault.mark("kill-after-execute")
                if business and fault.mode == "rowcount": return Result(result)
                return result
            def invalidate(self):
                if fault.mode == "invalidate":
                    fault.mark("invalidate"); raise RuntimeError("injected session retirement failure")
                return self.real.invalidate()
            def close(self):
                self.real.close()
                if fault.mode == "close":
                    fault.mark("close"); raise RuntimeError("injected close acknowledgement failure")
        return Engine()


class Fixture:
    def __init__(self, config):
        import pymysql
        from pymysql.constants import CLIENT
        from sql_safety_executor.database.models import ConnectionPolicy
        self.pymysql = pymysql
        self.schema = "mcp_contract_" + uuid.uuid4().hex[:16]
        assert re.fullmatch(r"mcp_contract_[0-9a-f]{16}", self.schema)
        self.original = config
        self.config = replace(config, connection_id="private", mysql_database=self.schema,
            query_timeout_seconds=10, policy=ConnectionPolicy(read_mode="all",allowed_tables=frozenset({"*"}),
                default_schema=self.schema,allow_mutations=True))
        self.options = dict(host=config.mysql_host,user=config.mysql_user,
            password=config.mysql_password.get_secret_value() if config.mysql_password else None,
            charset="utf8mb4",connect_timeout=5,read_timeout=15,write_timeout=15,client_flag=CLIENT.FOUND_ROWS)
        self.created = False
        self.owned = set()

    def connect(self, *, schema=True, autocommit=False):
        con = self.pymysql.connect(**self.options,database=self.schema if schema else self.original.mysql_database,
                                   autocommit=autocommit)
        if self.config.mysql_sql_mode is not None:
            with con.cursor() as cur: cur.execute("SET SESSION sql_mode=%s",(",".join(self.config.mysql_sql_mode),))
        return con

    def __enter__(self):
        with self.connect(schema=False,autocommit=True) as con:
            with con.cursor() as cur: cur.execute(f"CREATE DATABASE `{self.schema}` CHARACTER SET utf8mb4")
        self.created = True
        try:
            with self.connect(autocommit=True) as con:
                with con.cursor() as cur:
                    for sql in [
                        "CREATE TABLE orders(id INT PRIMARY KEY,n INT NOT NULL,u VARCHAR(32) UNIQUE) ENGINE=InnoDB",
                        "CREATE TABLE children(id INT PRIMARY KEY,order_id INT,FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE ON UPDATE CASCADE) ENGINE=InnoDB",
                        "CREATE TABLE audit_log(seq INT AUTO_INCREMENT PRIMARY KEY,kind CHAR(1),row_id INT,old_n INT,new_n INT) ENGINE=InnoDB",
                        "CREATE TABLE ballast(id INT PRIMARY KEY,n INT) ENGINE=InnoDB",
                        "CREATE TABLE sequence_probe(id INT AUTO_INCREMENT PRIMARY KEY,n INT) ENGINE=InnoDB",
                        "CREATE TRIGGER audit_u BEFORE UPDATE ON orders FOR EACH ROW BEGIN INSERT INTO audit_log(kind,row_id,old_n,new_n) VALUES('U',OLD.id,OLD.n,NEW.n); IF NEW.n=666 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='private trigger failure'; END IF; END",
                        "CREATE TRIGGER audit_i AFTER INSERT ON orders FOR EACH ROW INSERT INTO audit_log(kind,row_id,new_n) VALUES('I',NEW.id,NEW.n)",
                        "CREATE TRIGGER audit_d BEFORE DELETE ON orders FOR EACH ROW INSERT INTO audit_log(kind,row_id,old_n) VALUES('D',OLD.id,OLD.n)",
                    ]: cur.execute(sql)
                    cur.executemany("INSERT INTO ballast VALUES(%s,0)",[(i,) for i in range(1,129)])
            self.seed()
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def __exit__(self, *args):
        if self.created:
            with self.connect(schema=False,autocommit=True) as con:
                with con.cursor() as cur:
                    cur.execute(f"DROP DATABASE `{self.schema}`")
                    cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=%s",(self.schema,))
                    assert cur.fetchone()[0] == 0
            self.created = False

    def seed(self):
        with self.connect() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM children")
                cur.execute("DELETE FROM orders")
                cur.execute("INSERT INTO orders VALUES(1,7,'one'),(2,8,'two')")
                cur.execute("INSERT INTO children VALUES(10,1),(20,2)")
                cur.execute("DELETE FROM audit_log")
            con.commit()

    def observe(self):
        with self.connect(autocommit=True) as con:
            with con.cursor() as cur:
                result = {}
                for name,sql in [
                    ("orders","SELECT id,n,u FROM orders ORDER BY id"),
                    ("children","SELECT id,order_id FROM children ORDER BY id"),
                    ("audit","SELECT kind,row_id,old_n,new_n FROM audit_log ORDER BY seq"),
                ]:
                    cur.execute(sql); result[name] = [list(row) for row in cur.fetchall()]
                return result

    def adapter(self):
        from sql_safety_executor.database.mysql import MySQLAdapter
        adapter = MySQLAdapter(self.config)
        assert adapter.connect()
        return adapter

    def kill(self, connection):
        # Capture the exact physical session opened by this adapter, never a
        # process-list match or another Host's session. IDs never leave records.
        identifier = connection.connection.dbapi_connection.thread_id()
        self.owned.add(identifier)
        assert identifier in self.owned
        with self.connect(autocommit=True) as con:
            with con.cursor() as cur: cur.execute(f"KILL CONNECTION {int(identifier)}")


def execute(adapter, sql, params, expected):
    from sql_safety_executor.database.outcomes import WriteExecutionError
    try:
        value = adapter.execute_write(sql,params,expected_rowcount=expected)
        return {"outcome":value.execution_outcome.value,"rowcount":value["rowcount"]}
    except WriteExecutionError as error:
        record = {"outcome":error.execution_outcome.value,"error_code":error.error_code,"phase":error.phase.value}
        if hasattr(error,"actual_rowcount"): record["rowcount"] = error.actual_rowcount
        current = error.original_error
        errno = getattr(getattr(current,"orig",current),"args",())
        if errno and type(errno[0]) is int: record["mysql_errno"] = errno[0]
        return record


def matrix(fixture):
    records = []
    for name,sql,params in CASES:
        fixture.seed(); before = fixture.observe()
        # Native oracle has FOUND_ROWS like SQLAlchemy's documented contract,
        # but shares no project SQL analysis, transport or result conversion.
        with fixture.connect() as con:
            with con.cursor() as cur:
                cur.execute(re.sub(r":([a-z_]+)",r"%(\1)s",sql),params)
                count = cur.rowcount
            con.commit()
        after = fixture.observe()
        phases = []
        for expected in (count,count+1):
            fixture.seed()
            adapter = fixture.adapter()
            try: value = execute(adapter,sql,params,expected)
            finally: adapter.close()
            truth = fixture.observe()
            assert value["outcome"] == ("committed" if expected == count else "rolled_back"),(name,value)
            assert truth == (after if expected == count else before),(name,value,truth)
            phases.append({"expected":expected,"result":value,"post_cleanup_truth":truth})
        records.append({"case":name,"original_sql":sql,"bindings":params,"native_count":count,
                        "native_before":before,"native_after":after,"phases":phases})
    return records


def faults(fixture, checkpoint):
    records = []
    checkpoint["faults"] = records
    actual = [
        ("duplicate", "UPDATE orders SET u='two' WHERE id=1",1062),
        ("trigger", "UPDATE orders SET n=666 WHERE id=1",1644),
        ("foreign-key", "INSERT INTO children VALUES(30,999)",1452),
    ]
    for name,sql,errno in actual:
        fixture.seed(); before = fixture.observe(); adapter = fixture.adapter()
        try: value = execute(adapter,sql,{},1)
        finally: adapter.close()
        truth = fixture.observe()
        assert value["outcome"] == "rolled_back" and value.get("mysql_errno") == errno,(name,value)
        assert truth == before
        records.append({"case":name,"kind":"real-server-error","result":value,"post_cleanup_truth":truth})
    fixture.seed(); before = fixture.observe(); adapter = fixture.adapter()
    holder = fixture.connect()
    try:
        holder.begin()
        with holder.cursor() as cur: cur.execute("SELECT id FROM orders WHERE id=1 FOR UPDATE")
        # A one-second server row-lock timeout, not an environment timeout.
        from sql_safety_executor.database.outcomes import WriteExecutionError
        try:
            adapter.execute_write("UPDATE orders SET n=99 WHERE id=1",{},timeout=1,expected_rowcount=1)
            raise AssertionError("Expected actual InnoDB lock timeout")
        except WriteExecutionError as error:
            args = getattr(getattr(error.original_error,"orig",None),"args",())
            assert args and args[0] == 1205 and error.execution_outcome.value == "rolled_back"
            value = {"outcome":error.execution_outcome.value,"error_code":error.error_code,"mysql_errno":args[0]}
    finally:
        holder.rollback(); holder.close(); adapter.close()
    truth = fixture.observe(); assert truth == before
    records.append({"case":"lock-wait-timeout","kind":"real-server-error","result":value,"post_cleanup_truth":truth})
    records.append(deadlock(fixture))
    for mode in ["checkout","begin-before","begin-after","execute-before","execute-after","rowcount",
                 "commit-before","commit-after","rollback-before","rollback-after","invalidate","close",
                 "kill-before-begin","kill-after-execute"]:
        fixture.seed(); before = fixture.observe(); adapter = fixture.adapter()
        fault = Fault(mode,fixture)
        real_engine = adapter._engine
        adapter._engine = fault.engine(real_engine)
        expected = 2 if mode.startswith("rollback-") else 1
        try: value = execute(adapter,"UPDATE orders SET n=99 WHERE id=1",{},expected)
        finally:
            adapter._engine = real_engine
            # Separate final observation before and after test-harness cleanup.
            interim = fixture.observe()
            if fault.connection is not None and not fault.connection.closed:
                fault.connection.invalidate(); fault.connection.close()
            adapter.close()
        truth = fixture.observe()
        outcome = ("not_executed" if mode in {"checkout","begin-before","begin-after","kill-before-begin"} else
                   "unknown" if mode in {"commit-before","commit-after","rollback-before","rollback-after","kill-after-execute"} else
                   "committed" if mode in {"invalidate","close"} else "rolled_back")
        assert value["outcome"] == outcome,(mode,value)
        assert fault.hit,(mode,"fault was not reached")
        durable = mode in {"commit-after","invalidate","close"}
        if durable:
            assert truth["orders"] == [[1,99,"one"],[2,8,"two"]] and len(truth["audit"]) == 1
        else: assert truth == before,(mode,value,truth)
        assert truth == interim,(mode,"late cleanup changed business state")
        records.append({"case":mode,"kind":"real-own-session-disconnect" if mode.startswith("kill-") else "labelled-client-injection",
                        "injection_hits":fault.hit,"result":value,"before_harness_cleanup":interim,"post_cleanup_truth":truth})
    return records


def deadlock(fixture):
    """Make the adapter the lighter victim of a real two-session lock cycle."""
    from sqlalchemy import event
    fixture.seed(); before=fixture.observe()
    holder=fixture.connect(); adapter=fixture.adapter()
    reached=threading.Event(); session=[]
    def executing(connection,cursor,sql,params,context,many):
        if sql.startswith("UPDATE orders"):
            session.append(connection.connection.dbapi_connection.thread_id())
            reached.set()
    event.listen(adapter._engine,"before_cursor_execute",executing)
    try:
        holder.begin()
        with holder.cursor() as cur:
            cur.execute("UPDATE ballast SET n=n+1")
            cur.execute("UPDATE orders SET n=n+1 WHERE id=1")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(execute,adapter,"UPDATE orders SET n=n+100 WHERE id IN(1,2) ORDER BY id DESC",{},2)
            assert reached.wait(8),"adapter never reached deadlock statement"
            try:
                waiting=False; deadline=time.monotonic()+8
                with fixture.connect(autocommit=True) as watcher:
                    with watcher.cursor() as cur:
                        while time.monotonic()<deadline:
                            cur.execute("SELECT trx_state FROM INFORMATION_SCHEMA.INNODB_TRX WHERE trx_mysql_thread_id=%s",(session[0],))
                            row=cur.fetchone()
                            if row and row[0]=="LOCK WAIT": waiting=True; break
                            time.sleep(0.025)
                assert waiting,"no observed real lock wait; not counted as deadlock coverage"
                with holder.cursor() as cur: cur.execute("UPDATE orders SET n=n+1 WHERE id=2")
                value=future.result(timeout=12)
                assert value.get("mysql_errno")==1213 and value["outcome"]=="rolled_back",value
            finally:
                holder.rollback()
    finally:
        holder.close(); adapter.close()
    truth=fixture.observe(); assert truth==before
    return {"case":"deadlock-victim","kind":"real-server-error","observed_lock_wait":True,
            "result":value,"post_cleanup_truth":truth}


def concurrency(fixture):
    records = []
    for _ in range(3):
        fixture.seed()
        barrier = threading.Barrier(2)
        def worker(value):
            adapter = fixture.adapter()
            try:
                barrier.wait(timeout=10)
                return {"new":value,**execute(adapter,"UPDATE orders SET n=:new WHERE id=1 AND n=7",{"new":value},1)}
            finally: adapter.close()
        with ThreadPoolExecutor(max_workers=2) as executor: values = list(executor.map(worker,[99,100]))
        assert sorted(v["outcome"] for v in values) == ["committed","rolled_back"]
        winner = next(v["new"] for v in values if v["outcome"] == "committed")
        truth = fixture.observe()
        assert truth["orders"] == [[1,winner,"one"],[2,8,"two"]] and len(truth["audit"]) == 1
        records.append({"attempts":values,"post_cleanup_truth":truth})
    return records


def sequence_gap(fixture):
    with fixture.connect() as con:
        with con.cursor() as cur:
            cur.execute("INSERT INTO sequence_probe(n) VALUES(7)"); first = cur.lastrowid
        con.commit()
    adapter = fixture.adapter()
    try:
        value = execute(adapter,"INSERT INTO sequence_probe(n) VALUES(99)",{},2)
        assert value["outcome"] == "rolled_back"
    finally: adapter.close()
    with fixture.connect() as con:
        with con.cursor() as cur:
            cur.execute("INSERT INTO sequence_probe(n) VALUES(8)"); last = cur.lastrowid
        con.commit()
        with con.cursor() as cur:
            cur.execute("SELECT id,n FROM sequence_probe ORDER BY id"); rows = [list(r) for r in cur.fetchall()]
    assert rows == [[first,7],[last,8]] and last > first+1
    return {"result":value,"business_rows":rows,"rollback_gap_observed":True,
            "contract":"Only transactional business data is invariant; consumed AUTO_INCREMENT values need not be restored."}


def read_binding(fixture):
    from sql_safety_executor.core.analysis import analyze_sql
    from sql_safety_executor.database.errors import DatabaseQueryError
    adapter = fixture.adapter()
    records = []
    try:
        for stage in ("initial","pooled-reuse","reconnect"):
            if stage == "reconnect": adapter.close(); assert adapter.connect()
            context = adapter.resolve_analysis_context()
            sql = "SELECT 7 AS n"
            analysis = analyze_sql(sql,context)
            for _ in range(2): assert adapter.execute_read(sql,policy=fixture.config.policy,analysis=analysis)[0][0] == 7
            try:
                adapter.execute_read("SELECT 99 AS n",policy=fixture.config.policy,analysis=analysis)
                raise AssertionError("analysis/source mismatch reached executor")
            except DatabaseQueryError as error:
                assert error.error_code == "session_semantics_unavailable"
            records.append({"stage":stage,"matching_passes":2,"mismatch":"session_semantics_unavailable"})
    finally: adapter.close()
    return records


async def clients(fixture, args, checkpoint):
    from sql_safety_executor import create_server,load_config
    from sql_safety_executor.mcp.bootstrap import prepare_framework
    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    cases = [("commit",99,1,"committed"),("mismatch",99,2,"rolled_back"),
             ("trigger-error",666,1,"rolled_back")]
    fault_modes={"unknown-before":"commit-before","unknown-after":"commit-after"}
    if args.section == "unknown-clients":
        cases=[("unknown-before",99,1,"unknown"),("unknown-after",99,1,"unknown")]
    records = []
    checkpoint["client_records"] = records
    truths=[]
    checkpoint["client_truth"] = truths
    for transport_kind in (("inprocess",) if args.section=="unknown-clients" else ("inprocess","stdio")):
        for parser in ("sqlglot","sqlparse"):
            for mode in ("auto","legacy"):
                with tempfile.TemporaryDirectory(prefix="mysql-write-client-") as directory:
                    root = Path(directory)
                    for name,n,count,outcome in cases:
                        skill = root/"skills"/name; skill.mkdir(parents=True)
                        (skill/"skill_def.md").write_text(
                            f"---\nname: {name}\nversion: '1.0'\ndescription: Private InnoDB contract check\ntype: mutation\nsource: mutation.py\nrisk: medium\nrequires_confirmation: true\nidempotent: false\ndatabases: [mysql]\ntables: [orders]\nparams: {{}}\n---\nPrivate test only.\n")
                        (skill/"mutation.py").write_text(
                            "from sql_safety_executor.skills.mutation import ManagedMutationBase,ManagedMutationPlan\n"
                            "class Mutation(ManagedMutationBase):\n"
                            f"    managed_plan=ManagedMutationPlan('UPDATE orders SET n={n} WHERE id=1',(),{count})\n"
                            "    def validate(self,params): return {'valid':True}\n"
                            "    def preview(self,params): return {'affected_rows_estimate':1,'requires_confirmation':True}\n")
                    (root/"server.toml").write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="fixture"\n')
                    mysql = fixture.config
                    connection = ('schema_version=1\n[connections.fixture]\ntype="mysql"\nread.mode="all"\nmutation.enabled=true\nmutation.skills='+json.dumps([c[0] for c in cases])+'\n'+
                        '\n'.join('mysql.'+k+'='+json.dumps(v) for k,v in {
                            "host":mysql.mysql_host,"user":mysql.mysql_user,"database":fixture.schema}.items())+'\n'+
                        'mysql.password={value='+json.dumps(mysql.mysql_password.get_secret_value() if mysql.mysql_password else "")+'}\n')
                    (root/"connections.toml").write_text(connection)
                    (root/"connections.toml").chmod(0o600)
                    (root/"skills.toml").write_text('schema_version=1\n[skills]\nenabled=true\ndirectory="skills"\n[skills.readiness]\ncheck_schema=true\n[skills.mutation]\nenabled=true\nallowed_connections=["fixture"]\nmanaged_plan_parser="'+parser+'"\n[skills.mutation.mrtr]\nenabled=false\n[skills.audit]\npath="audit.jsonl"\n')
                    server = None
                    if transport_kind == "inprocess":
                        server=create_server(load_config(root/"server.toml")); transport=server
                    else:
                        environment=os.environ.copy(); environment.pop("PYTHONPATH",None)
                        if args.source: environment["PYTHONPATH"]=str(args.source.resolve())
                        transport=StdioTransport(command=sys.executable,args=["-m","sql_safety_executor","serve","--config",str(root/"server.toml")],cwd=str(root),env=environment)
                    try:
                        async with Client(transport,mode=mode,init_timeout=30,timeout=30) as client:
                            async def call(tool,arguments,*,allow_error=False):
                                response=await client.call_tool(tool,{"connection_id":"fixture",**arguments},raise_on_error=False)
                                assert not response.is_error or allow_error,(tool,"generic tool failure")
                                for block in response.content:
                                    if getattr(block,"type",None)=="text" and not response.is_error: assert json.loads(block.text)==response.structured_content
                                value=response.structured_content
                                records.append({"transport":transport_kind,"parser":parser,"mode":mode,"tool":tool,
                                                "arguments":redacted(arguments),"result":redacted(value),
                                                "isError":response.is_error,"meta":redacted(response.meta),
                                                "content":redacted([b.model_dump(mode="json",exclude_none=True) for b in response.content])})
                                return {"_tool_error":True} if response.is_error else value
                            for name,n,count,outcome in cases:
                                fixture.seed(); before=fixture.observe()
                                preview=await call("execute_mutation_skill",{"skill_name":name,"params":{}})
                                assert preview["mode"]=="preview" and preview["execution_outcome"]=="not_executed"
                                assert fixture.observe()==before
                                token=preview["preview_token"]
                                arguments={"skill_name":name,"params":{},"preview_token":token,"confirm":True}
                                writes=[]
                                if name in fault_modes:
                                    from sql_safety_executor.database.mysql import MySQLAdapter
                                    original=MySQLAdapter.execute_write
                                    def controlled(adapter,sql,params,*pos,**kw):
                                        assert adapter.metadata_schema==fixture.schema
                                        fault=Fault(fault_modes[name],fixture)
                                        engine=adapter._engine
                                        adapter._engine=fault.engine(engine)
                                        writes.append(fault)
                                        try: return original(adapter,sql,params,*pos,**kw)
                                        finally: adapter._engine=engine
                                    with patch.object(MySQLAdapter,"execute_write",controlled):
                                        result=await call("execute_mutation_skill",arguments)
                                    assert len(writes)==1 and writes[0].hit==[fault_modes[name]],"exactly one actual write attempt; no automatic retry"
                                else:
                                    result=await call("execute_mutation_skill",arguments)
                                assert result["execution_outcome"]==outcome,(name,result)
                                assert result["success"] is (outcome=="committed")
                                assert records[-1]["meta"]["preview_token_consumed"] is True
                                observed=fixture.observe()
                                if outcome=="committed" or name=="unknown-after": assert observed["orders"][0][1]==n and len(observed["audit"])==1
                                else: assert observed==before
                                if outcome=="unknown": assert result["error_code"]=="commit_outcome_unknown"
                                replay=await call("execute_mutation_skill",arguments,allow_error=True)
                                assert replay.get("_tool_error") is True
                                assert any("Invalid preview_token" in b.get("text","") for b in records[-1]["content"]),"target token rejection, not unrelated tool error"
                                assert fixture.observe()==observed
                                truths.append({"transport":transport_kind,"parser":parser,"mode":mode,"case":name,
                                               "native_before":before,"after_confirm_and_replay":observed,
                                               "adapter_write_attempts":1 if name in fault_modes else None,
                                               "kind":"labelled-client-commit-injection" if name in fault_modes else "real-server-lifecycle"})
                    finally:
                        if server is not None:
                            server.gateway_runtime.close()
                    assert fixture.observe()==observed
                    truths[-1]["after_server_cleanup"]=fixture.observe()
    return records


def legacy_tests(fixture, args):
    env=os.environ.copy()
    if args.source: env["PYTHONPATH"]=str(args.source.resolve())
    env.update(RUN_MYSQL_INTEGRATION_TESTS="1",DB_HOST=fixture.config.mysql_host,
               DB_USER=fixture.config.mysql_user,DB_PASSWORD=fixture.config.mysql_password.get_secret_value(),DB_NAME=fixture.schema)
    with tempfile.TemporaryDirectory(prefix="mysql-explicit-tests-") as directory:
        xml=Path(directory)/"tests.xml"
        value=subprocess.run([sys.executable,"-m","pytest","-q","--junitxml="+str(xml),
            "tests/test_db_adapter.py","tests/test_v372_write_outcomes.py",
            "-k","mysql_connection or mysql_check_connection or mysql_db_type or mysql_stale_conditional_updates"],
            cwd=args.repo,env=env,capture_output=True,text=True,timeout=60)
        # A green pytest exit may still mean skipped/unverified. Count actual cases.
        assert value.returncode==0,("legacy opt-in tests failed",value.returncode)
        cases=list(ET.parse(xml).iter("testcase"))
        names={case.get("name") for case in cases}
        assert names=={"test_mysql_connection","test_mysql_check_connection","test_mysql_db_type",
                       "test_mysql_stale_conditional_updates_allow_at_most_one_commit"}
        assert len(cases)==4 and all(not any(case.find(tag) is not None for tag in
                                            ("skipped","failure","error")) for case in cases)
    # Never export raw environment or failed-driver diagnostics with endpoints.
    return {"passed":4,"skipped":0,"stdout_summary":value.stdout.strip().splitlines()[-1]}


def run(args):
    if args.source: sys.path.insert(0,str(args.source.resolve()))
    import sql_safety_executor
    from sql_safety_executor import load_config
    package=Path(sql_safety_executor.__file__).resolve().parent
    assert package==args.source.resolve()/"sql_safety_executor" if args.source else package.is_relative_to(Path(sys.prefix))
    assert not args.output.exists()
    config=load_config(args.config).connections[args.alias]
    assert config.db_type=="mysql"
    record={"scope":__doc__,"passed":False,"package":str(package)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with Fixture(config) as fixture:
            with fixture.connect(autocommit=True) as con:
                with con.cursor() as cur:
                    cur.execute("SELECT VERSION(),@@session.transaction_isolation,@@global.innodb_rollback_on_timeout")
                    row=cur.fetchone()
                    record["server"]={"version":row[0],"isolation":row[1],"rollback_on_timeout":row[2]}
                    cur.execute("SELECT DISTINCT ENGINE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s",(fixture.schema,))
                    engines=[r[0] for r in cur.fetchall()]; assert engines==["InnoDB"]
            record["engines"]=engines
            if args.section=="all":
                record["read_binding"]=read_binding(fixture)
                record["matrix"]=matrix(fixture)
                record["faults"]=faults(fixture,record)
                record["concurrency"]=concurrency(fixture)
                record["sequence_gap"]=sequence_gap(fixture)
            record["client_records"]=asyncio.run(clients(fixture,args,record))
            if args.legacy_tests: record["legacy_integration"]=legacy_tests(fixture,args)
        record["disposable_schema_removed"]=True
        record["resources"]={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in package.rglob("*") if p.is_file() and p.suffix in {".py",".md"}}
        record["passed"]=True
    except BaseException as error:
        record["failure"]={"class":type(error).__name__,"stage_keys":list(record)}
        record["failure"]["frames"]=[{"file":Path(f.filename).name,"function":f.name,"line":f.lineno}
                                      for f in traceback.extract_tb(error.__traceback__)]
        # Fixed labels and assertions are safe; never serialize DBAPI reprs.
        if isinstance(error,AssertionError): record["failure"]["assertion"]=str(error).replace(getattr(locals().get("fixture"),"schema","<none>"),"<private-schema>")
        raise
    finally:
        raw=json.dumps(record,ensure_ascii=False,indent=2,default=str).encode()
        args.output.write_bytes(gzip.compress(raw,mtime=0) if args.output.suffix==".gz" else raw)
    print(json.dumps({"passed":True,"matrix":len(record.get("matrix",[])),"faults":len(record.get("faults",[])),
                      "races":len(record.get("concurrency",[])),"client_calls":len(record["client_records"]),"schema_removed":True}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--alias",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source",type=Path)
    parser.add_argument("--repo",type=Path,default=Path.cwd())
    parser.add_argument("--legacy-tests",action="store_true")
    parser.add_argument("--section",choices=["all","unknown-clients"],default="all")
    args=parser.parse_args()
    try: run(args)
    except BaseException as error:
        print(json.dumps({"passed":False,"failure_class":type(error).__name__,"details":"See sanitized stage evidence; no automatic retry."}))
        raise SystemExit(1) from None
