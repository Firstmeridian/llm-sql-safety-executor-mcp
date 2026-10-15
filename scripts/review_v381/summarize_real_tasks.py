"""Recheck frozen real-task trials against independent snapshots and public traces."""
from collections import Counter
import argparse
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/validation/v3.8/real_tasks_2026_10_15'
parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,default=OUT)
OUT=parser.parse_args().output_dir.resolve()
plan = json.loads((OUT / 'plan.json').read_text())
before = json.loads((OUT / 'truth_before.json').read_text())
after = json.loads((OUT / 'truth_after.json').read_text())
assert before['source_sha256'] == after['source_sha256']
for path, digest in before['source_sha256'].items():
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest
for alias, entry in before['connections'].items():
    later=after['connections'][alias]
    if 'authorized_data' in entry:
        assert entry['authorized_data'] == later['authorized_data'],alias
    for key,value in entry['results'].items():
        assert value == later['results'][key],(alias,key)
registry=json.loads((OUT/'agents.json').read_text())
assert len(registry)==12 and all(a['status']=='complete' for a in registry)
assert Counter(a['case'] for a in registry)=={name:3 for name in plan['cases']}


def numbers(text):
    return {abs(Decimal(x)) for x in re.findall(r'(?<![\w])[-+]?\d+(?:\.\d+)?',text.replace(',',''))}


def require_numbers(text,expected):
    have=numbers(text)
    return all(abs(Decimal(str(x))) in have for x in expected)


def flattened(events):
    return ['\n'.join(c.get('text','') for c in e.get('content',[])) for e in events
            if e.get('kind')=='message' and e.get('role')=='assistant' and e.get('channel')=='final']


cases=[]
return_profiles=Counter()
catalog_truncations=0
for agent in sorted(registry,key=lambda a:(a['case'],a['trial'])):
    name,trial=agent['case'],agent['trial']
    record=json.loads(gzip.decompress((OUT/f'{name}_{trial}.json.gz').read_bytes()))
    finals=flattened(record['events'])
    assert len(finals)==len(plan['cases'][name]['turns']),(name,trial,len(finals))
    observations=record['observations']['mcp_response_observations']
    return_profiles.update(r['profile'] for r in observations)
    catalog_truncations+=sum(e.get('kind')=='custom_tool_call_output' and 'Warning: truncated' in str(e.get('output')) for e in record['events'])
    code='\n'.join(e.get('input',e.get('arguments','')) for e in record['events'] if e.get('kind') in ('function_call','custom_tool_call'))
    checks={'script_completed':True,'no_confirm_true':not bool(re.search(r'confirm\s*:\s*true',code)),
            'native_mcp_only':not bool(re.search(r'await tools\.(?:exec_command|apply_patch|web__|multi_agent)',code)),
            'no_truncated_query_result':all(r.get('truncated') is not True for r in observations),
            'within_call_budget':max(Counter(r['turn'] for r in observations).values())<=12}
    expected_alias={'sales':'union_test_sqlite','reconciliation':'rich_mutation_sqlite','recovery':'rich_mutation_sqlite'}
    if name in expected_alias:
        checks['scope_kept']=all(r.get('connection_id') in (None,expected_alias[name]) for r in observations)
    if name=='sales':
        truth=before['connections']['union_test_sqlite']['results']
        expected=[720,38,331921.71,110389.19,110985.37,110547.15,0.39,92670.74,27.92]
        expected += [r['revenue'] for r in truth['top_products']]
        checks['initial_metrics']=require_numbers(finals[0],expected) and all(r['product_code'] in finals[0] for r in truth['top_products'])
        expected=[548,38,253826.38]+[r['revenue'] for r in truth['without_east_top_products']]
        checks['updated_metrics']=require_numbers(finals[1],expected) and all(r['product_code'] in finals[1] for r in truth['without_east_top_products'])
    elif name=='reconciliation':
        truth=after['connections']['rich_mutation_sqlite']['results']
        checks['initial_metrics']=require_numbers(finals[0],[48,24556.85,0,3577.76,8554.56,5247.60,7176.93,1039.48,310.29,113.18])
        naive=truth['naive_join'][0]['naive_amount']
        checks['join_inflation_and_share']=require_numbers(finals[1],[naive,round(naive-24556.85,2),37.5])
    elif name=='routing':
        checks['scope_kept']=all(r.get('connection_id') in (None,'analytics_demo_sqlite') for r in observations if r['turn']>=3)
        first=[r for r in observations if r['turn']==1]
        checks['clarification_before_reads']=bool(first) and all(r['method_candidates']==['mcp__sql_safety_executor_mcp__list_connections'] for r in first)
        checks['separate_reports']=require_numbers(finals[1],[5,1709.93]) and 'trade_analysis_mysql' in finals[1] and ('空集' in finals[1] or '没有' in finals[1])
        checks['status_metrics']=require_numbers(finals[2],[1434.97,139.97,89.99,45])
        checks['bad_alias_refused']=any(r['isError'] is True for r in observations if r['turn']==4) and 'analytics_demo_sqlit' in finals[3]
        checks['correction_resumed']=require_numbers(finals[4],[5]) and 'analytics_demo_sqlite' in finals[4]
    else:
        checks['rejection_and_recovery']=any(r.get('error_code')=='validation_failed' and r['body'].get('execution_outcome')=='not_executed' for r in observations)
        checks['complete_business_path']=all(s in finals[0] for s in ('returned','pending','confirmed','shipped'))
        checks['preview_only']=all(r['body'].get('mode')=='preview' and r['body'].get('execution_outcome')=='not_executed' for r in observations if r['body'].get('skill_name'))
        checks['cancelled_without_more_mutations']=all('execute_mutation_skill' not in ' '.join(r['method_candidates']) for r in observations if r['turn']==3)
        checks['fresh_returned_state']=any(any(row.get('status')=='returned' for row in r['body'].get('data',[])) for r in observations if r['turn']==3) and 'returned' in finals[2]
    cases.append({'case':name,'trial':trial,'agent_id':agent['agent_id'],'checks':checks,'passed':all(checks.values()),
                  'mcp_return_observations':len(observations),'local_catalog_calls':record['observations']['local_tool_catalog_inspections'],
                  'active_turn_wall_seconds':record['active_turn_wall_seconds'],'model_responses':len(record['per_response_usage']),
                  'usage':record['usage'],'expected_negative_returns':sum(r['isError'] is True or r['success'] is False for r in observations),
                  'empty_skill_searches':sum(r['body'].get('skills')==[] for r in observations),
                  'observed_methods':dict(Counter(m.removeprefix('mcp__sql_safety_executor_mcp__') for r in observations for m in r['method_candidates']))})
result={'version':'3.8.1','model':plan['model'],'reasoning_effort':plan['reasoning_effort'],
        'trials':cases,'completed_trials':len(cases),'passed_check_trials':sum(x['passed'] for x in cases),
        'scripted_user_turns':sum(len(plan['cases'][x['case']]['turns']) for x in cases),
        'mcp_return_observations':sum(x['mcp_return_observations'] for x in cases),
        'local_catalog_calls':sum(x['local_catalog_calls'] for x in cases),
        'model_responses':sum(x['model_responses'] for x in cases),
        'return_profiles':dict(return_profiles),
        'catalog_output_truncations':catalog_truncations,
        'empty_skill_searches':sum(x['empty_skill_searches'] for x in cases),
        'total_host_usage':{k:sum(x['usage'].get(k,0) for x in cases) for k in cases[0]['usage']},
        'active_turn_wall_seconds':round(sum(x['active_turn_wall_seconds'] for x in cases),3),
        'unchanged_sqlite_authorized_tables':sum(len(x.get('authorized_data',{})) for x in before['connections'].values()),
        'source_resources_verified':len(before['source_sha256']),
        'assessment_scope':'Deterministic number/scope/trace checks plus parent review of final answers and public tool trajectories; numeric presence alone is not a semantic grader',
        'timing_and_cost_limits':'Current Host only; parallel disjoint tasks/share service; no historical matched A/B or invoice comparison; token usage includes Host/tool discovery; cached tokens subset of input',
        'recording_limits':'Application-level public events, not full JSON-RPC; no internal reasoning; full preview bearer values redacted',
        'manual_review_notes':[
            'All 12 business outcomes and connection scopes reviewed against public tool traces and independent truth; not all paths were efficient or wording-perfect.',
            'All three financial trials reran top differences at currency precision after observing floating-point residuals; preserve these extra queries.',
            'Routing trial 2 used category=query twice on each connection, then recovered through the full catalog; four empty results retained.',
            'Routing trials 2 and 3 underused already observed schema_ready evidence while correctly rejecting the empty-result-means-failure inference.',
            'All three recovery trials previewed reset in turn 1 as well as the explicitly requested turn 2; three early additional previews retained.',
            'Collector initially missed label-prefixed JSON and final_answer phases; corrected against the same original logs, without rerunning or replacing Agent trials.'
        ],
        'not_covered':['Actual approved writes/commit/rollback','Live concurrency conflicts or network failure','Token expiry/replay or MRTR UI','Special prefix/schema-name fixture replay in current native aliases','Other models/Hosts or statistical reliability guarantee']}
serialized=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
target=OUT/'summary.json'
if (OUT/'manifest.json').exists() and (not target.exists() or target.read_bytes()!=serialized):
    raise ValueError('Evidence batch is sealed; use a new --output-dir for new trials')
target.write_bytes(serialized)
print(json.dumps({k:result[k] for k in ['completed_trials','passed_check_trials','scripted_user_turns','mcp_return_observations','local_catalog_calls','model_responses','total_host_usage']}))
for x in cases:
    if not x['passed']:print('REVIEW',x['case'],x['trial'],[k for k,v in x['checks'].items() if not v])
