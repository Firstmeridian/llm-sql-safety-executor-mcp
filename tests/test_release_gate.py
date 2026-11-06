"""Gate reporting and invalidation tests; these mocks are not live-DB evidence."""
import argparse
from contextlib import nullcontext
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.validation import release_gate as gate


def identity():
    return {'python': {'version': '3.12'}, 'sqlite': {'version': '3.45'},
            'runtime': {'module.py': 'same'}, 'validation': {}, 'dependency_files': {},
            'distributions': {'sqlglot': ['30.22.0']}}


@pytest.mark.parametrize('component', [
    'sqlglot', 'sqlalchemy', 'pymysql', 'pydantic', 'pydantic-core', 'fastmcp', 'mcp',
    'unknown-transitive', 'sqlite', 'python', 'runtime', 'validation', 'dependency_files',
])
def test_changed_inputs_require_rechecks_without_product_source_change(component):
    before = identity()
    after = deepcopy(before)
    if component in before and component != 'distributions':
        after[component]['changed'] = True
    else:
        after['distributions'][component] = ['new-version']
    change = gate.dependency_changes(before, after)
    assert change['changed_components']
    assert 'fast' in change['required_scenarios']
    if component != 'sqlite':
        assert 'mysql_writes' in change['required_scenarios']
    assert change['reuse_permitted'] is False
    if component not in {'runtime', 'validation', 'dependency_files'}:
        assert before['runtime'] == after['runtime']


def test_matching_identity_still_does_not_authorize_automatic_reuse():
    change = gate.dependency_changes(identity(), identity())
    assert change['changed_components'] == change['required_scenarios'] == []
    assert change['reuse_permitted'] is False


@pytest.mark.parametrize('relative', [
    'skills/sample/mutation.py', 'skills/sample/query.sql',
    'skills/sample/skill_def.md', 'skills/sample/references/transitions.md',
    'tests/fixtures/scoped/query.sql', 'tests/fixtures/scoped/skill_def.md',
])
@pytest.mark.parametrize('operation', ['modify', 'add', 'remove'])
def test_skill_and_fixture_inputs_invalidate_real_fingerprint(tmp_path, relative, operation):
    target = tmp_path/relative
    target.parent.mkdir(parents=True)
    if operation != 'add':
        target.write_text('original input\n')
    before = gate.fingerprint(tmp_path)
    if operation == 'remove':
        target.unlink()
    else:
        target.write_text('changed input\n')
    after = gate.fingerprint(tmp_path)

    assert before['runtime'] == after['runtime']
    assert before['validation'] != after['validation']
    assert (relative in before['validation']) is (operation != 'add')
    assert (relative in after['validation']) is (operation != 'remove')
    change = gate.dependency_changes(before, after)
    assert change['changed_components'] == ['validation']
    assert set(change['required_scenarios']) == set(gate.SCENARIOS)
    assert change['reuse_permitted'] is False


@pytest.mark.parametrize('relative', [
    'skills/sample/__pycache__/mutation.cpython-313.pyc',
    'skills/sample/audit.jsonl', 'config/connections.toml',
])
def test_generated_outputs_and_private_config_are_not_validation_inputs(tmp_path, relative):
    before = gate.fingerprint(tmp_path)
    target = tmp_path/relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b'not a release input')
    assert gate.fingerprint(tmp_path) == before


@pytest.mark.parametrize('directory', ['skills', 'tests/fixtures'])
def test_validation_directory_links_are_part_of_input_identity(tmp_path, directory):
    base = tmp_path/directory
    for version, value in [('A', 'SELECT 1'), ('B', 'SELECT 2')]:
        target = base/'_deployment'/version
        target.mkdir(parents=True)
        (target/'query.sql').write_text(value)
    absent = gate.fingerprint(tmp_path)
    active = base/'active'
    active.symlink_to('_deployment/A', target_is_directory=True)
    before = gate.fingerprint(tmp_path)
    active.unlink()
    active.symlink_to('_deployment/B', target_is_directory=True)
    assert (active/'query.sql').read_text() == 'SELECT 2'
    after = gate.fingerprint(tmp_path)
    assert absent != before != after
    assert gate.dependency_changes(before, after)['changed_components'] == ['validation']
    active.unlink()
    assert gate.fingerprint(tmp_path) == absent


def test_selected_file_link_still_tracks_target_content(tmp_path):
    base = tmp_path/'skills'
    base.mkdir()
    target = base/'payload'
    target.write_text('SELECT 1')
    (base/'query.sql').symlink_to('payload')
    before = gate.fingerprint(tmp_path)
    target.write_text('SELECT 2')
    assert gate.fingerprint(tmp_path) != before


def test_junit_counts_actual_cases_including_skips_and_failures(tmp_path):
    xml = tmp_path/'tests.xml'
    xml.write_text('<testsuites><testsuite><testcase name="ok"/>'
                   '<testcase name="not-run"><skipped message="database absent"/></testcase>'
                   '<testcase name="bad"><failure/></testcase></testsuite></testsuites>')
    assert gate.pytest_summary(xml) == {'passed': 1, 'failed': 1, 'skipped': 1,
                                      'skipped_names': ['not-run']}


def arguments(output, **kwargs):
    import sql_safety_executor
    source = Path(sql_safety_executor.__file__).resolve().parents[1]
    values = dict(profile='release', output=output, source=source, config=None,
                  alias=None, mysql_env=False, baseline=None)
    return argparse.Namespace(**(values | kwargs))


@pytest.mark.parametrize('use_env', [False, True])
def test_missing_live_environment_is_unverified_nonzero_before_any_command(tmp_path, monkeypatch, use_env):
    for name in ('RELEASE_MYSQL_HOST', 'RELEASE_MYSQL_USER', 'RELEASE_MYSQL_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gate, 'fingerprint', identity)
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **k: pytest.fail('No subprocess expected'))
    args = arguments(tmp_path/'new', mysql_env=use_env)
    assert gate.run(args) == 2
    value = json.loads((args.output/'report.json').read_text())
    assert value['status'] == 'unverified' and value['release_ready'] is False
    assert all(check['status'] == 'not_run' for check in value['checks'].values())
    assert 'UNVERIFIED' in (args.output/'summary.md').read_text()


def test_fast_success_does_not_claim_release_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'fingerprint', identity)

    def process(*args, **kwargs):
        (output/'pytest.xml').write_text('<testsuites><testsuite><testcase name="ok"/>'
            '<testcase name="test_mysql_connection"><skipped/></testcase></testsuite></testsuites>')
        assert 'RUN_MYSQL_INTEGRATION_TESTS' not in kwargs['env']
        assert 'PYTEST_ADDOPTS' not in kwargs['env']
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv('RUN_MYSQL_INTEGRATION_TESTS', '1')
    monkeypatch.setenv('PYTEST_ADDOPTS', '-k silently_narrowed')
    monkeypatch.setattr(gate.subprocess, 'run', process)
    output = tmp_path/'fast'
    assert gate.run(arguments(output, profile='fast')) == 0
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == 'passed' and report['release_ready'] is False
    assert report['checks']['fast']['passed'] == 1 and report['checks']['fast']['skipped'] == 1
    assert report['checks']['mysql_writes']['status'] == 'not_run'


def test_interrupted_stage_is_failed_and_never_release_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'fingerprint', identity)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(gate.subprocess, 'run', interrupted)
    output = tmp_path/'interrupted'
    assert gate.run(arguments(output, profile='fast')) == 130
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == report['checks']['fast']['status'] == 'failed'
    assert report['release_ready'] is False and report['failure_class'] == 'KeyboardInterrupt'


@pytest.mark.parametrize('profile', ['fast', 'release'])
@pytest.mark.parametrize('relative', [
    'skills/sample/mutation.py', 'skills/sample/query.sql',
    'tests/fixtures/scoped/skill_def.md',
])
def test_input_drift_during_run_is_failed_not_release_ready(tmp_path, monkeypatch, profile, relative):
    # Real file hashes and the real run/final-check/report path; stage execution
    # is synthetic and must not be reported as a live database acceptance.
    checkout = tmp_path/'checkout'
    target = checkout/relative
    target.parent.mkdir(parents=True)
    target.write_text('original input\n')
    fingerprint = gate.fingerprint
    monkeypatch.setattr(gate, 'fingerprint', lambda: fingerprint(checkout))
    monkeypatch.setattr(gate, 'mysql_configuration', lambda args: nullcontext((None, 'fixture')))
    stages = []

    def execute(name, command, output, report, env):
        stages.append(name)
        report['checks'][name]['status'] = 'passed'
        if name == 'fast':
            target.write_text('changed during acceptance\n')

    monkeypatch.setattr(gate, 'execute', execute)
    output = tmp_path/'result'
    assert gate.run(arguments(output, profile=profile)) == 1
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == 'failed' and report['release_ready'] is False
    assert report['failure_class'] == 'AssertionError'
    assert stages == (['fast'] if profile == 'fast' else list(gate.SCENARIOS))


@pytest.mark.parametrize('profile', ['fast', 'release'])
def test_link_retarget_during_run_cannot_report_success(tmp_path, monkeypatch, profile):
    checkout = tmp_path/'checkout'
    base = checkout/'skills'
    for version, value in [('A', 'SELECT 1'), ('B', 'SELECT 2')]:
        target = base/'_deployment'/version
        target.mkdir(parents=True)
        (target/'query.sql').write_text(value)
    active = base/'active'
    active.symlink_to('_deployment/A', target_is_directory=True)
    fingerprint = gate.fingerprint
    monkeypatch.setattr(gate, 'fingerprint', lambda: fingerprint(checkout))
    monkeypatch.setattr(gate, 'mysql_configuration', lambda args: nullcontext((None, 'fixture')))

    def execute(name, command, output, report, env):
        report['checks'][name]['status'] = 'passed'
        if name == 'fast':
            active.unlink()
            active.symlink_to('_deployment/B', target_is_directory=True)

    monkeypatch.setattr(gate, 'execute', execute)
    output = tmp_path/'result'
    assert gate.run(arguments(output, profile=profile)) == 1
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == 'failed' and report['release_ready'] is False
    assert report['failure_class'] == 'AssertionError'


@pytest.mark.parametrize('skipped', ['unrelated-case', 'test_mysql_connection'])
def test_release_skip_accounting(tmp_path, monkeypatch, skipped):
    (tmp_path/'pytest.xml').write_text('<testsuites><testsuite><testcase name="ok"/>'
        f'<testcase name="{skipped}"><skipped/></testcase></testsuite></testsuites>')
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    report = {'profile': 'release', 'checks': {}}
    if skipped == 'unrelated-case':
        with pytest.raises(AssertionError, match='Unexpected release skip'):
            gate.execute('fast', ['not-executed'], tmp_path, report, {})
    else:
        gate.execute('fast', ['not-executed'], tmp_path, report, {})
        assert report['checks']['fast']['skipped'] == 1


@pytest.mark.parametrize('name', gate.SCENARIOS[1:])
def test_empty_or_green_flag_only_artifact_cannot_pass(name):
    with pytest.raises((AssertionError, KeyError)):
        gate.check_artifact(name, {'passed': True})


def write_artifact(name):
    """Synthetic coverage records only; never represent live transaction proof."""
    from scripts.validation import mysql_writes, sqlite_writes
    if name == 'sqlite_writes':
        cases = [case[0] for case in sqlite_writes.CASES]
        runs = [{'transport': transport, 'client_mode': mode}
                for transport in ('inprocess', 'stdio') for mode in ('auto', 'legacy')]
        records = [{**run, 'tool': 'execute_mutation_skill', 'arguments': {'skill_name': case}}
                   for run in runs for case in cases for _ in range(3)]
        records.extend({**run, 'tool': 'query'} for run in runs for _ in range(3))
        return {'passed': True, 'records': records, 'runs': runs,
                'independent_truth': [{**run, 'case': case} for run in runs for case in cases]}
    transports = ('inprocess', 'stdio') if name == 'mysql_writes' else ('inprocess',)
    cases = ('commit', 'mismatch', 'trigger-error') if name == 'mysql_writes' else ('unknown-before', 'unknown-after')
    runs = [{'transport': transport, 'mode': mode} for transport in transports for mode in ('auto', 'legacy')]
    return {'passed': True, 'disposable_schema_removed': True,
            'client_records': [{**run, 'arguments': {'skill_name': case}} for run in runs for case in cases for _ in range(3)],
            'client_truth': [{**run, 'case': case} for run in runs for case in cases],
            'matrix': [{'case': case[0]} for case in mysql_writes.CASES],
            'faults': [{'case': case} for case in (
                'duplicate', 'trigger', 'foreign-key', 'lock-wait-timeout', 'deadlock-victim',
                'checkout', 'begin-before', 'begin-after', 'execute-before', 'execute-after',
                'rowcount', 'commit-before', 'commit-after', 'rollback-before', 'rollback-after',
                'invalidate', 'close', 'kill-before-begin', 'kill-after-execute')],
            'concurrency': [None] * 3, 'read_binding': [None] * 3,
            'engines': ['InnoDB'], 'legacy_integration': {'passed': 4, 'skipped': 0}}


@pytest.mark.parametrize('name', ['sqlite_writes', 'mysql_writes', 'mysql_unknown'])
def test_single_classifier_write_matrix_retains_all_contract_dimensions(name):
    gate.check_artifact(name, write_artifact(name))


@pytest.mark.parametrize('name', ['sqlite_writes', 'mysql_writes', 'mysql_unknown'])
def test_former_double_classifier_evidence_is_not_the_new_matrix(name):
    value = write_artifact(name)
    key = 'records' if name == 'sqlite_writes' else 'client_records'
    value[key] *= 2
    with pytest.raises(AssertionError):
        gate.check_artifact(name, value)


@pytest.mark.parametrize('name', ['sqlite_writes', 'mysql_writes', 'mysql_unknown'])
def test_duplicate_lifecycle_cannot_replace_a_missing_case_with_same_count(name):
    value = write_artifact(name)
    key = 'records' if name == 'sqlite_writes' else 'client_records'
    value[key][0] = deepcopy(value[key][3])
    with pytest.raises(AssertionError):
        gate.check_artifact(name, value)


@pytest.mark.parametrize('name', ['sqlite_writes', 'mysql_writes', 'mysql_unknown'])
def test_duplicate_truth_cannot_replace_missing_transport_or_case(name):
    value = write_artifact(name)
    key = 'independent_truth' if name == 'sqlite_writes' else 'client_truth'
    value[key][-1] = deepcopy(value[key][0])
    with pytest.raises(AssertionError):
        gate.check_artifact(name, value)


def test_sqlite_duplicate_run_does_not_cover_both_protocol_modes():
    value = write_artifact('sqlite_writes')
    value['runs'][-1] = deepcopy(value['runs'][0])
    with pytest.raises(AssertionError):
        gate.check_artifact('sqlite_writes', value)


@pytest.mark.parametrize('key', ['matrix', 'faults'])
def test_mysql_missing_statement_or_fault_cannot_hide_behind_unchanged_size(key):
    value = write_artifact('mysql_writes')
    value[key][-1] = deepcopy(value[key][0])
    with pytest.raises(AssertionError):
        gate.check_artifact('mysql_writes', value)


def test_output_reuse_is_refused(tmp_path):
    with pytest.raises(FileExistsError):
        gate.run(arguments(tmp_path))


def test_stale_artifact_cannot_pass_on_exit_code_and_counts_alone(tmp_path, monkeypatch):
    artifact = {'passed': True, 'calls': [None]*128, 'resources': {'stale.py': 'old'},
                'disposable_schema_removed': True, 'transactional_business_truth_unchanged': True}
    (tmp_path/'mysql_reads.json.gz').write_bytes(gzip.compress(json.dumps(artifact).encode()))
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    report = {'profile': 'release', 'checks': {}, 'fingerprint': identity()}
    with pytest.raises(AssertionError, match='Artifact product identity'):
        gate.execute('mysql_reads', ['not-executed'], tmp_path, report, {})


def test_optimized_python_cannot_disable_contract_assertions(tmp_path):
    import subprocess
    import sys
    output = tmp_path/'optimized'
    result = subprocess.run([sys.executable, '-O', str(Path(gate.__file__).resolve()),
                             '--profile', 'fast', '--output', str(output)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == 'unverified' and report['release_ready'] is False
    assert all(check['status'] == 'not_run' for check in report['checks'].values())


def test_mysql_env_config_is_temporary_and_loads_without_exporting_secret(tmp_path, monkeypatch):
    from sql_safety_executor import load_config
    for name, value in [('HOST', '127.0.0.1'), ('USER', 'private-fixture'), ('PASSWORD', 'fixture-only')]:
        monkeypatch.setenv('RELEASE_MYSQL_'+name, value)
    with gate.mysql_configuration(arguments(tmp_path, mysql_env=True)) as (path, alias):
        config = load_config(path)
        assert config.connections[alias].db_type == 'mysql'
        assert config.connections[alias].mysql_password.get_secret_value() == 'fixture-only'
        assert 'fixture-only' not in (path.parent/'connections.toml').read_text()
        directory = path.parent
    assert not directory.exists()


@pytest.mark.parametrize('event', ['push', 'pull_request'])
def test_dependency_and_source_changes_trigger_explicit_live_workflow(event):
    import yaml
    workflow = yaml.load((gate.ROOT/'.github/workflows/release-contracts.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'workflow_dispatch' in workflow['on']
    assert {'pyproject.toml', 'uv.lock', '.python-version', '.github/workflows/ci.yml',
            'src/**', 'skills/**', 'tests/fixtures/**'} <= set(workflow['on'][event]['paths'])
    steps = workflow['jobs']['release-contracts']['steps']
    assert any('--profile release --mysql-env' in step.get('run', '') for step in steps)
