"""Freeze independent read-only truth and collect public native Agent trials.

No model is invoked here. Parent orchestration uses fresh Luna subagents and
fixed follow-ups from plan.json. Never serialize internal reasoning or tokens.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/validation/v3.8/real_tasks_2026_10_15"
sys.path.insert(0, str(ROOT / "src"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_evidence(name: str, data: bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    if (OUT / 'manifest.json').exists() and (not target.exists() or target.read_bytes() != data):
        raise ValueError('Evidence batch is sealed; use a new --output-dir for new trials')
    target.write_bytes(data)


def save(name: str, data: object) -> None:
    write_evidence(name,(json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def sqlite_truth(alias: str, queries: dict[str, str], config) -> dict:
    path = Path(config.connections[alias].sqlite_database_path).resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = {name: [dict(r) for r in conn.execute(sql)] for name, sql in queries.items()}
        # Hash authorized data in deterministic order without exporting row data.
        names = {
            "union_test_sqlite": ["sales_2026_q1", "sales_2026_q2", "sales_2026_q3"],
            "rich_mutation_sqlite": ["customers", "order_items", "orders"],
            "analytics_demo_sqlite": ["orders"],
        }[alias]
        fingerprints = {}
        for name in names:
            values = [tuple(r) for r in conn.execute(f'SELECT * FROM "main"."{name}" ORDER BY id')]
            fingerprints[name] = {"rows": len(values), "data_sha256": digest(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode())}
        return {"queries": queries, "results": rows, "authorized_data": fingerprints,
                "access": "sqlite3 URI mode=ro, explicit main schema"}
    finally:
        conn.close()


def prepare(stage: str, mysql: bool) -> None:
    from sql_safety_executor import load_config, __version__
    config = load_config(ROOT / "config/server.toml")
    sales = " UNION ALL ".join(f"SELECT * FROM main.sales_2026_q{i}" for i in range(1, 4))
    prefix = "WITH sales AS (" + sales + ") "
    bill = "order_date >= '2026-09-01' AND order_date < '2026-10-01' AND status NOT IN ('cancelled','returned')"
    rich_prefix = ("WITH item_totals AS (SELECT order_id, SUM(quantity*unit_price) AS item_amount FROM main.order_items GROUP BY order_id), "
                   "eligible AS (SELECT o.id,o.customer_id,o.total_amount,i.item_amount FROM main.orders o LEFT JOIN item_totals i ON i.order_id=o.id WHERE " + bill + ") ")
    record = {"version": __version__, "stage": stage, "independent_of_mcp": True,
              "source_sha256": {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted((ROOT / "src/sql_safety_executor").rglob("*")) if p.is_file() and p.suffix in (".py", ".md")},
              "configured_database_writes": False, "connections": {}}
    record["connections"]["union_test_sqlite"] = sqlite_truth("union_test_sqlite", {
        "totals": prefix + "SELECT COUNT(*) records,COUNT(DISTINCT product_code) products,ROUND(SUM(amount),2) revenue FROM sales",
        "quarters": prefix + "SELECT substr(sold_on,1,4)||'-Q'||CASE WHEN substr(sold_on,6,2)<='03' THEN '1' WHEN substr(sold_on,6,2)<='06' THEN '2' ELSE '3' END quarter, COUNT(*) records,ROUND(SUM(amount),2) revenue FROM sales GROUP BY quarter ORDER BY quarter",
        "regions": prefix + "SELECT region,COUNT(*) records,ROUND(SUM(amount),2) revenue FROM sales GROUP BY region ORDER BY revenue DESC,region",
        "top_products": prefix + "SELECT product_code,ROUND(SUM(amount),2) revenue FROM sales GROUP BY product_code ORDER BY revenue DESC,product_code LIMIT 3",
        "without_east": prefix + "SELECT COUNT(*) records,COUNT(DISTINCT product_code) products,ROUND(SUM(amount),2) revenue FROM sales WHERE region!='east'",
        "without_east_top_products": prefix + "SELECT product_code,ROUND(SUM(amount),2) revenue FROM sales WHERE region!='east' GROUP BY product_code ORDER BY revenue DESC,product_code LIMIT 3",
    }, config)
    record["connections"]["rich_mutation_sqlite"] = sqlite_truth("rich_mutation_sqlite", {
        "all_orders": "SELECT COUNT(*) orders,ROUND(SUM(total_amount),2) amount FROM main.orders",
        "eligible_totals": rich_prefix + "SELECT COUNT(*) orders,ROUND(SUM(total_amount),2) header_amount,ROUND(SUM(COALESCE(item_amount,0)),2) item_amount,SUM(CASE WHEN ABS(total_amount-COALESCE(item_amount,0))>0.01 THEN 1 ELSE 0 END) mismatched_orders,ROUND(SUM(ABS(total_amount-COALESCE(item_amount,0))),2) absolute_difference FROM eligible",
        "eligible_regions": rich_prefix + "SELECT c.region,COUNT(*) orders,ROUND(SUM(e.total_amount),2) amount FROM eligible e JOIN main.customers c ON c.id=e.customer_id GROUP BY c.region ORDER BY amount DESC,c.region",
        "largest_differences": rich_prefix + "SELECT id,ROUND(total_amount,2) header_amount,ROUND(COALESCE(item_amount,0),2) item_amount,ROUND(ABS(total_amount-COALESCE(item_amount,0)),2) absolute_difference FROM eligible ORDER BY absolute_difference DESC,id LIMIT 3",
        "naive_join": "SELECT ROUND(SUM(o.total_amount),2) naive_amount FROM main.orders o JOIN main.order_items i ON i.order_id=o.id WHERE " + bill,
        "preview_subject": "SELECT id,status FROM main.orders WHERE id=4",
        "index_names": "SELECT name FROM main.sqlite_schema WHERE type='index' AND tbl_name='orders' ORDER BY name",
    }, config)
    record["connections"]["analytics_demo_sqlite"] = sqlite_truth("analytics_demo_sqlite", {
        "january": "SELECT COUNT(*) orders,ROUND(SUM(total_amount),2) revenue,ROUND(AVG(total_amount),2) average_order_value FROM main.orders WHERE order_date >= '2026-01-01' AND order_date < '2026-02-01'",
        "january_status": "SELECT status,COUNT(*) orders,ROUND(SUM(total_amount),2) revenue FROM main.orders WHERE order_date >= '2026-01-01' AND order_date < '2026-02-01' GROUP BY status ORDER BY status",
    }, config)
    if mysql:
        from sql_safety_executor.database.mysql import MySQLAdapter
        adapter = MySQLAdapter(config.connections["trade_analysis_mysql"])
        queries = {
            "all_orders": "SELECT COUNT(*) AS orders FROM orders",
            "january": "SELECT COUNT(*) AS orders,ROUND(COALESCE(SUM(total_amount),0),2) AS revenue FROM orders WHERE order_date >= '2026-01-01' AND order_date < '2026-02-01'",
        }
        try:
            values = {k: [dict(r._mapping) for r in adapter.execute(sql)] for k, sql in queries.items()}
            record["connections"]["trade_analysis_mysql"] = {"queries": queries, "results": values, "access": "Independent configured adapter; SELECT only; no driver/private details exported"}
        finally:
            adapter.close()
    # Decimal values have fixed string form; SQLite values remain numeric.
    save(f"truth_{stage}.json", json.loads(json.dumps(record, default=str)))
    print(json.dumps({"stage": stage, "aliases": list(record["connections"]), "source_files": len(record["source_sha256"])}))


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: ({"redacted": True, "sha256": digest(str(v).encode())} if k in {"preview_token", "token", "requestState", "request_state", "password", "dsn"} and v else sanitize(v)) for k, v in value.items()}
    if isinstance(value, str):
        # MCP tool text often embeds its JSON response inside a string.
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            # A Host wrapper may prepend a label to a complete JSON response.
            match = re.search(r'(?m)^[ \t]*[\[{]', value)
            if match:
                try:
                    decoded, end = json.JSONDecoder().raw_decode(value, match.start())
                    return value[:match.start()] + json.dumps(sanitize(decoded),ensure_ascii=False) + sanitize(value[end:])
                except (ValueError,TypeError):
                    pass
            return re.sub(r'("(?:preview_token|token|requestState|request_state)"\s*:\s*")([^"\n]+)(")',
                          lambda m: m[1] + '<redacted-sha256:' + digest(m[2].encode()) + '>' + m[3], value)
        if isinstance(decoded, (dict, list)):
            return json.dumps(sanitize(decoded), ensure_ascii=False)
    return value


def envelopes(value):
    """Locate actual public MCP response envelopes without double-counting text.

    Some wrappers print text plus structuredContent separately. Only in that
    case use unique business bodies within that one orchestration call, and
    label the observation. No model's self-reported call count is trusted.
    """
    if isinstance(value, str):
        try:
            yield from envelopes(json.loads(value))
        except (ValueError, TypeError):
            match=re.search(r'(?m)^[ \t]*[\[{]',value)
            if match:
                try:
                    decoded,_=json.JSONDecoder().raw_decode(value,match.start())
                    yield from envelopes(decoded)
                except (ValueError,TypeError):
                    pass
    elif isinstance(value, list):
        for item in value:
            yield from envelopes(item)
    elif isinstance(value, dict):
        if 'content' in value and ('structuredContent' in value or 'isError' in value):
            yield value
        else:
            for item in value.values():
                yield from envelopes(item)


def public_bodies(value):
    if isinstance(value,str):
        try:
            yield from public_bodies(json.loads(value))
        except (ValueError,TypeError):
            pass
    elif isinstance(value,list):
        for item in value:
            yield from public_bodies(item)
    elif isinstance(value,dict):
        if type(value.get('success')) is bool:
            yield value
        else:
            for item in value.values():
                yield from public_bodies(item)


def metrics(events):
    def business_value_key(value):
        # One wrapper can print 720.0 in content and 720 in structuredContent.
        # Deduplicate that representation in fallback statistics only; original
        # public events retain both spellings and all protocol field omissions.
        if isinstance(value, dict):
            return {key: business_value_key(item) for key, item in value.items()}
        if isinstance(value, list):
            return [business_value_key(item) for item in value]
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    pending, observations, local_discovery = {}, [], 0
    turn, user_turns = 0, 0
    for event in events:
        if event.get('kind')=='message' and event.get('role')=='user':
            text='\n'.join(x.get('text','') for x in event.get('content',[]))
            if 'SQLREAL-' in text or text in [t for c in json.loads((OUT/'plan.json').read_text())['cases'].values() for t in c['turns']]:
                user_turns+=1;turn=user_turns
        if event.get('kind') in ('function_call','custom_tool_call'):
            code=event.get('input',event.get('arguments',''))
            pending[event['call_id']]={'code':code,'turn':turn,'timestamp':event.get('timestamp')}
            if 'ALL_TOOLS' in code and 'await tools.mcp__' not in code:
                local_discovery+=1
        elif event.get('kind') in ('function_call_output','custom_tool_call_output'):
            call=pending.get(event['call_id'],{})
            code=call.get('code','')
            observed=list(envelopes(event.get('output')))
            profile='MCP response envelope'
            if not observed:
                bodies=list(public_bodies(event.get('output')))
                unique={json.dumps(business_value_key(x),sort_keys=True,ensure_ascii=False):x for x in bodies}
                observed=list(unique.values());profile='Distinct printed business body within one orchestration call'
            names=list(dict.fromkeys(re.findall(r'tools\.(mcp__sql_safety_executor_mcp__\w+)',code)))
            for item in observed:
                body=item.get('structuredContent')
                if body is None and 'content' in item:
                    bodies=list(public_bodies(item['content']))
                    body=bodies[0] if bodies else {}
                if body is None:body=item
                candidates=names
                if len(names)>1:
                    suffix=None
                    if 'skills' in body:suffix='list_skills'
                    elif 'schema' in body or 'schema_groups' in body:suffix='get_full_schema'
                    elif 'skill' in body:suffix='get_skill_detail'
                    elif 'indexes_status' in body:suffix='describe_table'
                    elif 'tables' in body:suffix='list_tables'
                    elif 'connections' in body:suffix='list_connections'
                    if suffix:
                        candidates=[n for n in names if n.endswith('__'+suffix)] or names
                observations.append({'turn':call.get('turn'),'timestamp':call.get('timestamp'),'returned_at':event.get('timestamp'),
                    'method_candidates':candidates,'profile':profile,'isError':item.get('isError'),
                    'success':body.get('success'),'connection_id':body.get('connection_id'),
                    'error_code':body.get('error_code'),'row_count':body.get('row_count'),'truncated':body.get('truncated'),
                    'body':body})
    return {'mcp_response_observations':observations,'observed_mcp_responses':len(observations),
            'local_tool_catalog_inspections':local_discovery,
            'count_scope':'Public returned MCP envelopes, with explicit distinct-business-body fallback; unknown or pre-return failures require manual review',
            'user_script_turns_observed':user_turns}


def collect(agent_id: str, case: str, trial: int, session_root: Path | None = None) -> None:
    session_root = session_root or Path.home() / '.codex/sessions'
    candidates = list(session_root.glob(f'*/*/*/*{agent_id}.jsonl'))
    if len(candidates) != 1:
        raise ValueError("Expected exactly one rollout for this unique agent ID")
    events, usage, last_usage, session, turn_models, lifecycle = [], None, [], {}, [], []
    for line in candidates[0].read_text().splitlines():
        event = json.loads(line)
        payload = event.get('payload', {})
        kind, typ = event.get('type'), payload.get('type')
        if kind == 'session_meta':
            session = {k: payload.get(k) for k in ('id','parent_thread_id','cli_version','agent_nickname','model_provider','history_mode','source')}
        elif kind == 'turn_context':
            turn_models.append({k: payload.get(k) for k in ('model','effort','summary','turn_id')})
        elif kind == 'event_msg' and typ == 'token_count':
            info = payload.get('info') or {}
            usage = info.get('total_token_usage') or usage
            if info.get('last_token_usage'):
                last_usage.append({'timestamp':event.get('timestamp'),'usage':info['last_token_usage']})
        elif kind == 'event_msg' and typ in ('task_started','task_complete','turn_aborted'):
            lifecycle.append({'timestamp':event.get('timestamp'),'type':typ,'turn_id':payload.get('turn_id')})
        elif kind == 'response_item':
            if typ == 'message' and payload.get('role') in ('user','assistant') and payload.get('channel') not in ('analysis','justify','confidence'):
                channel = payload.get('channel') or {'final_answer':'final','commentary':'commentary'}.get(payload.get('phase'))
                events.append({'timestamp':event.get('timestamp'),'kind':'message','role':payload.get('role'),'channel':channel,'phase':payload.get('phase'),'content':sanitize(payload.get('content'))})
            elif typ in ('function_call','function_call_output','custom_tool_call','custom_tool_call_output'):
                clean = {k: v for k,v in payload.items() if k not in ('internal_chat_message_metadata_passthrough',)}
                events.append({'timestamp':event.get('timestamp'),'kind':typ,**sanitize(clean)})
    active_seconds, began = 0.0, None
    for item in lifecycle:
        if item['type']=='task_started':
            began=datetime.fromisoformat(item['timestamp'].replace('Z','+00:00'))
        elif began is not None:
            active_seconds+=(datetime.fromisoformat(item['timestamp'].replace('Z','+00:00'))-began).total_seconds();began=None
    record = {'case':case,'trial':trial,'agent_id':agent_id,'session':session,'turn_models':turn_models,'usage':usage,
              'lifecycle':lifecycle,'active_turn_wall_seconds':round(active_seconds,3),
              'timing_scope':'Sum of Host task-start/completion intervals; excludes between-turn evaluator idle time; includes model/Host/tool latency and shared-service effects',
              'observations':metrics(events),
              'per_response_usage':last_usage,'events':events,
              'omitted':['Internal reasoning','Base/system instruction bodies','Rate limits/account metadata','Full approval/preview bearer values','Complete JSON-RPC transport frames'],
              'usage_scope':'Host-reported session token counts include inherited tool/environment overhead; cached_input_tokens is a subset of input_tokens; no invoice-cost claim'}
    data=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode()
    write_evidence(f'{case}_{trial}.json.gz',gzip.compress(data,mtime=0))
    finals=[e for e in events if e.get('kind')=='message' and e.get('role')=='assistant' and e.get('channel')=='final']
    print(json.dumps({'case':case,'trial':trial,'agent_id':agent_id,'public_events':len(events),'final_turns':len(finals),'usage':usage},ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=OUT)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('truth');p.add_argument('--stage',required=True);p.add_argument('--mysql',action='store_true')
    p=sub.add_parser('collect');p.add_argument('--agent-id',required=True);p.add_argument('--case',required=True);p.add_argument('--trial',required=True,type=int);p.add_argument('--session-root',type=Path)
    args=parser.parse_args()
    OUT=args.output_dir.resolve()
    if args.command=='truth':prepare(args.stage,args.mysql)
    else:collect(args.agent_id,args.case,args.trial,args.session_root)
