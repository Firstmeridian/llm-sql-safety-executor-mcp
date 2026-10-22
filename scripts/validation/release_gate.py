"""Run deterministic regression or explicit disposable-MySQL release contracts.

No automatic evidence reuse. Every invocation has a new output directory and
captures actual runtime/dependency identity. Release requires explicit MySQL
fixture configuration; missing environment is UNVERIFIED, never a green skip.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
OPTIONAL_MYSQL = {
    'test_mysql_connection', 'test_mysql_check_connection', 'test_mysql_db_type',
    'test_mysql_stale_conditional_updates_allow_at_most_one_commit',
}
SCENARIOS = ('fast', 'sqlite_semantics', 'sqlite_reads', 'sqlite_writes',
             'mysql_writes', 'mysql_unknown', 'mysql_reads')


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(root=ROOT):
    import sql_safety_executor
    package = Path(sql_safety_executor.__file__).resolve().parent
    with sqlite3.connect(':memory:') as db:
        options = sorted(row[0] for row in db.execute('PRAGMA compile_options'))
    distributions = {}
    for dist in metadata.distributions():
        name = dist.metadata.get('Name')
        if name:
            key = name.lower().replace('_', '-').replace('.', '-')
            distributions.setdefault(key, set()).add(dist.version)
    return {
        'python': {'implementation': platform.python_implementation(),
                   'version': platform.python_version(), 'system': platform.system(),
                   'machine': platform.machine()},
        'sqlite': {'version': sqlite3.sqlite_version, 'threadsafety': sqlite3.threadsafety,
                   'compile_options': options},
        'distributions': {key: sorted(value) for key, value in sorted(distributions.items())},
        'runtime': {str(p.relative_to(package)): file_hash(p) for p in sorted(package.rglob('*'))
                    if p.is_file() and p.suffix in {'.py', '.md'}},
        'validation': {str(p.relative_to(root)): file_hash(p)
                       for directory in ('tests', 'scripts/validation', '.github/workflows')
                       for p in sorted((root/directory).rglob('*'))
                       if p.is_file() and p.suffix in {'.py', '.yml', '.yaml'}},
        'dependency_files': {name: file_hash(root/name) for name in ('pyproject.toml', 'uv.lock')
                             if (root/name).is_file()},
    }


def dependency_changes(before, after):
    """Plan relevant rechecks; never authorize reuse or skip a release stage."""
    changed = []
    gates = set()
    for field in ('python', 'sqlite', 'runtime', 'validation', 'dependency_files'):
        if before.get(field) != after.get(field):
            changed.append(field)
            gates.update(SCENARIOS if field != 'sqlite' else SCENARIOS[:4])
    old, new = before.get('distributions', {}), after.get('distributions', {})
    for name in sorted(set(old) | set(new)):
        if old.get(name) == new.get(name):
            continue
        changed.append('distribution:' + name)
        # Unknown/transitive dependencies conservatively require all contracts.
        gates.update(SCENARIOS)
    return {'changed_components': changed, 'required_scenarios': sorted(gates),
            'reuse_permitted': False,
            'note': 'Comparison is planning only; this runner always reruns its selected profile.'}


def pytest_summary(path):
    tree = ET.parse(path)
    cases = list(tree.iter('testcase'))
    skipped = [case.get('name', '') for case in cases if case.find('skipped') is not None]
    failures = sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
    return {'passed': len(cases)-len(skipped)-failures, 'failed': failures,
            'skipped': len(skipped), 'skipped_names': skipped}


def check_artifact(name, value):
    """Require expected matrix cardinality and cleanup, not just process exit 0."""
    if name == 'sqlite_semantics':
        assert len(value['records']) == 130
    elif name == 'sqlite_reads':
        assert len(value['records']) == 74 and value['expected'] == 'after'
        assert value['data_unchanged'] is True
    elif name == 'sqlite_writes':
        assert value['passed'] is True and len(value['records']) == 432
        assert len(value['independent_truth']) == 136 and len(value['runs']) == 8
    elif name in {'mysql_writes', 'mysql_unknown'}:
        assert value['passed'] is True and value['disposable_schema_removed'] is True
        assert len(value['client_records']) == (72 if name == 'mysql_writes' else 24)
        if name == 'mysql_writes':
            assert len(value['matrix']) == 14 and len(value['faults']) == 19
            assert len(value['concurrency']) == 3 and len(value['read_binding']) == 3
            assert value['engines'] == ['InnoDB']
            legacy = value['legacy_integration']
            assert legacy['passed'] == 4 and legacy['skipped'] == 0
    elif name == 'mysql_reads':
        assert value['passed'] is True and len(value['calls']) == 128
        assert value['disposable_schema_removed'] is True
        assert value['transactional_business_truth_unchanged'] is True
    else:
        raise ValueError('Unknown contract artifact')


@contextmanager
def mysql_configuration(args):
    if args.config is not None and args.alias and not args.mysql_env:
        from sql_safety_executor import load_config
        config = load_config(args.config.resolve())
        if args.alias not in config.connections or config.connections[args.alias].db_type != 'mysql':
            raise ValueError('An explicit MySQL fixture alias is required')
        yield args.config.resolve(), args.alias
        return
    if args.config is not None or args.alias or not args.mysql_env:
        raise ValueError('Release requires --config/--alias together, or --mysql-env')
    names = ['RELEASE_MYSQL_HOST', 'RELEASE_MYSQL_USER', 'RELEASE_MYSQL_PASSWORD']
    if any(not os.environ.get(name) for name in names):
        raise ValueError('Required RELEASE_MYSQL environment is missing')
    with tempfile.TemporaryDirectory(prefix='release-mysql-config-') as directory:
        root = Path(directory)
        (root/'server.toml').write_text('schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n[server]\ndefault_connection="fixture"\n')
        values = {'host': os.environ[names[0]], 'user': os.environ[names[1]], 'database': 'mysql'}
        # The production adapter and existing fixtures use the default port.
        text = 'schema_version=1\n[connections.fixture]\ntype="mysql"\nread.mode="all"\n'
        text += '\n'.join('mysql.'+key+'='+json.dumps(value) for key, value in values.items())
        text += '\nmysql.password={env="RELEASE_MYSQL_PASSWORD"}\n'
        (root/'connections.toml').write_text(text)
        (root/'connections.toml').chmod(0o600)
        (root/'skills.toml').write_text('schema_version=1\n[skills]\nenabled=false\n')
        yield root/'server.toml', 'fixture'


def execute(name, command, output, report, env):
    artifact = output/(name+'.json.gz')
    log = output/(name+'.log')
    entry = report['checks'][name] = {'status': 'running', 'log': log.name}
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    entry['returncode'] = result.returncode
    if result.returncode:
        entry['status'] = 'failed'
        raise RuntimeError('Contract subprocess failed: ' + name)
    if name == 'fast':
        summary = pytest_summary(output/'pytest.xml')
        assert summary['passed'] > 0 and summary['failed'] == 0
        entry.update(summary)
        if report['profile'] == 'release':
            assert set(summary['skipped_names']) <= OPTIONAL_MYSQL, 'Unexpected release skip'
        entry['status'] = 'passed'
    else:
        value = json.loads(gzip.decompress(artifact.read_bytes()))
        check_artifact(name, value)
        resources = value.get('resources', value.get('source_sha256', value.get('installed_source_sha256')))
        assert resources == report['fingerprint']['runtime'], 'Artifact product identity differs from this run'
        entry.update(status='passed', artifact=artifact.name)
        if name.startswith('mysql_') and name != 'mysql_reads':
            entry['server'] = value['server']


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    report = {'format': 1, 'time_utc': datetime.now(timezone.utc).isoformat(),
              'profile': args.profile, 'status': 'unverified', 'release_ready': False,
              'checks': {name: {'status': 'not_run'} for name in SCENARIOS},
              'automatic_reuse': False}
    env = os.environ.copy()
    env.pop('RUN_MYSQL_INTEGRATION_TESTS', None)
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTHONPATH', None)
    if args.source:
        args.source = args.source.resolve()
        env['PYTHONPATH'] = str(args.source)
        sys.path.insert(0, str(args.source))
    code = 1
    try:
        if sys.flags.optimize:
            raise ValueError('Contract assertions must remain enabled')
        import sql_safety_executor
        package = Path(sql_safety_executor.__file__).resolve().parent
        if args.source:
            assert package == args.source/'sql_safety_executor', 'Selected source was not imported'
        else:
            assert package.is_relative_to(Path(sys.prefix)) and 'site-packages' in str(package), 'Use --source for editable installs'
        report['fingerprint'] = fingerprint()
        if args.baseline:
            old = json.loads(args.baseline.read_text())
            report['baseline_comparison'] = dependency_changes(old['fingerprint'], report['fingerprint'])
        if args.profile == 'release':
            # Validate intent/environment before running any fixture or matrix.
            with mysql_configuration(args) as (config, alias):
                report['mysql_requested'] = True
                code = run_checks(args, output, report, env, config, alias)
        else:
            code = run_checks(args, output, report, env)
    except (Exception, KeyboardInterrupt) as error:
        # No driver repr, account, endpoint, config contents or credentials.
        report['failure_class'] = type(error).__name__
        report['status'] = 'failed' if any(v['status'] != 'not_run' for v in report['checks'].values()) else 'unverified'
        for value in report['checks'].values():
            if value['status'] == 'running':
                value['status'] = 'failed'
        code = 130 if isinstance(error, KeyboardInterrupt) else (1 if report['status'] == 'failed' else 2)
    finally:
        for path in output.iterdir():
            if path.is_file():
                path.chmod(0o600)
        report['files'] = {p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file()}
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        summary = ['# Contract gate', '', f"Profile: {args.profile}; status: {report['status']}",
                   f"Release ready: {report['release_ready']}", '', '| Scenario | Status |', '| --- | --- |']
        summary.extend(f"| {name} | {value['status']} |" for name, value in report['checks'].items())
        summary.extend(['', 'not_run means UNVERIFIED, not passed. Fast regression alone is not release acceptance.',
                        'Actual dependency/runtime identity is recorded; no automatic reuse of prior results.'])
        (output/'summary.md').write_text('\n'.join(summary)+'\n')
        (output/'report.json').chmod(0o600)
        (output/'summary.md').chmod(0o600)
    print(json.dumps({'profile': args.profile, 'status': report['status'],
                      'release_ready': report['release_ready']}))
    return code


def run_checks(args, output, report, env, config=None, alias=None):
    execute('fast', [sys.executable, '-m', 'pytest', '-q', '-ra', '--junitxml='+str(output/'pytest.xml')],
            output, report, env)
    if args.profile == 'fast':
        assert report['fingerprint'] == fingerprint(), 'Inputs/environment changed during regression'
        report['status'] = 'passed'
        return 0
    for name, script, extra in [
        ('sqlite_semantics', 'installed_semantics.py', []),
        ('sqlite_reads', 'read_boundaries.py', []),
        ('sqlite_writes', 'sqlite_writes.py', []),
        ('mysql_writes', 'mysql_writes.py', ['--config', str(config), '--alias', alias,
                                         '--repo', str(ROOT), '--legacy-tests']),
        ('mysql_unknown', 'mysql_writes.py', ['--config', str(config), '--alias', alias,
                                          '--section', 'unknown-clients']),
        ('mysql_reads', 'stabilization_mysql_reads.py', ['--config', str(config), '--alias', alias]),
    ]:
        command = [sys.executable, str(ROOT/'scripts/validation'/script),
                   '--output', str(output/(name+'.json.gz')), *extra]
        if args.source:
            command += ['--source', str(args.source)]
        execute(name, command, output, report, env)
    after = fingerprint()
    assert report['fingerprint'] == after, 'Inputs/environment changed during acceptance'
    report.update(status='passed', release_ready=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['fast', 'release'], default='fast')
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwrite evidence')
    parser.add_argument('--source', type=Path, help='Explicit source tree; omit for a normally installed package')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--alias')
    parser.add_argument('--mysql-env', action='store_true', help='Use explicit RELEASE_MYSQL_* fixture credentials')
    parser.add_argument('--baseline', type=Path, help='Compare identity for planning only; never skip checks')
    args = parser.parse_args()
    raise SystemExit(run(args))
