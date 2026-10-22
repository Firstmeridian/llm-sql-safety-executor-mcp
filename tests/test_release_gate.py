"""Gate reporting and invalidation tests; these mocks are not live-DB evidence."""
import argparse
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
    'sqlparse', 'unknown-transitive', 'sqlite', 'python', 'runtime', 'validation', 'dependency_files',
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


def test_dependency_changes_trigger_explicit_live_workflow():
    import yaml
    workflow = yaml.load((gate.ROOT/'.github/workflows/release-contracts.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'workflow_dispatch' in workflow['on']
    for event in ('push', 'pull_request'):
        assert {'pyproject.toml', 'uv.lock', '.python-version', '.github/workflows/ci.yml'} <= set(workflow['on'][event]['paths'])
    steps = workflow['jobs']['release-contracts']['steps']
    assert any('--profile release --mysql-env' in step.get('run', '') for step in steps)
