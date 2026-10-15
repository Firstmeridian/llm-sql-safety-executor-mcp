"""Controlled native model trace with task-only required stdio MCP settings."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from sql_safety_executor import load_config
parser=argparse.ArgumentParser()
parser.add_argument("--source",type=Path,required=True)
parser.add_argument("--stage",required=True)
parser.add_argument("--trial",type=int,required=True)
args=parser.parse_args()
OUT=ROOT/"docs/validation/v3.8/phase123_2026_10_14"
plan=json.loads((OUT/"luna_plan.json").read_text())
cfg=load_config(ROOT/"config/server.toml").connections["analytics_demo_sqlite"]
assert cfg.db_type=="sqlite" and Path(cfg.sqlite_database_path).is_file()
with tempfile.TemporaryDirectory(prefix="v381-luna-cli-") as directory:
    fixture=Path(directory)
    (fixture/"server.toml").write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="analytics_demo_sqlite"\n')
    (fixture/"connections.toml").write_text('schema_version=1\n[connections.analytics_demo_sqlite]\ntype="sqlite"\n[connections.analytics_demo_sqlite.sqlite]\npath='+json.dumps(cfg.sqlite_database_path)+'\n[connections.analytics_demo_sqlite.read]\nmode="allowlist"\ntables=["orders"]\n')
    (fixture/"skills.toml").write_text('schema_version=1\n[skills]\nenabled=false\n')
    overrides={
        "model_reasoning_effort":"medium","features.mcp_2026_07_28":True,
        "features.shell_tool":False,
        "mcp_servers.sql-safety-executor-mcp":{
            "command":sys.executable,"args":["-m","sql_safety_executor","serve","--config",str(fixture/"server.toml")],
            "env":{"PYTHONPATH":str(args.source)},"cwd":str(fixture),"required":True,
            "enabled":True,"enabled_tools":["query"],"startup_timeout_sec":60,"tool_timeout_sec":30}}
    # TOML inline values, rather than shell interpolation. JSON strings/arrays
    # are valid TOML here; dictionaries are rendered as inline tables.
    def toml(value):
        if isinstance(value,dict):return "{ "+", ".join(json.dumps(k)+" = "+toml(v) for k,v in value.items())+" }"
        if isinstance(value,list):return "["+", ".join(toml(v) for v in value)+"]"
        return json.dumps(value)
    command=["codex","exec","--ignore-user-config","--ephemeral","--json","--sandbox","read-only","--model","gpt-6-luna"]
    for key,value in overrides.items():command.extend(["-c",key+"="+toml(value)])
    command.extend(["--cd",str(ROOT),plan["prompt"]])
    result=subprocess.run(command,text=True,capture_output=True,timeout=240,cwd=ROOT)
    public=[]
    for line in result.stdout.splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get("item",{}).get("type") in {"reasoning","analysis"}:continue
        public.append(event)
    record={"stage":args.stage,"trial":args.trial,"model":"gpt-6-luna","reasoning_effort":"medium",
        "prompt":plan["prompt"],"return_code":result.returncode,"events":public,
        "source_policy_sha256":hashlib.sha256((args.source/"sql_safety_executor/core/policy.py").read_bytes()).hexdigest(),
        "task_overrides":{"required":True,"enabled_tools":["query"],"single_sqlite_alias":"analytics_demo_sqlite",
            "sandbox":"read-only","ignore_user_config":True,"ephemeral":True,"startup_timeout_sec":60},
        "scope":"Actual native CLI stdio MCP, task-local config only; no resident restart/global config change",
        "omitted":["Internal reasoning","Temporary absolute fixture/source paths","Non-JSON stderr"],
        "stderr_indicators":{"mcp": "mcp" in result.stderr.lower(),"error":"error" in result.stderr.lower()}}
    path=OUT/f"luna_cli_{args.stage}_{args.trial}.json"
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"stage":args.stage,"trial":args.trial,"return_code":result.returncode,
        "event_types":[x.get("type") for x in public]}))
    if result.returncode:
        print(result.stderr[-1500:])
        raise SystemExit(result.returncode)
