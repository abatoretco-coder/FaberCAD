#!/usr/bin/env python3
"""Bounded FABER source checks. Never compiles Cargo packages or downloads tools.

Native artifact smoke is a separate explicit mode and does not certify current source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))
import resource_budget

POLICY_PATH = ROOT / 'scripts' / 'ci' / 'faber_policy.json'


def load_policy():
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    if not (0 < policy['timeout_seconds'] <= 180 and 128 <= policy['memory_mb'] <= 1024):
        raise ValueError('CI budget exceeds the owner ceiling (180 seconds / 1024 MiB)')
    if not 0 < policy['step_timeout_seconds'] <= 30:
        raise ValueError('Invalid step timeout')
    if policy['native_compilation'] != 'never':
        raise ValueError('Automatic native compilation is forbidden')
    return policy


def command(args, timeout=20):
    result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    output = result.stdout.decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}):\n{output[-6000:]}')
    return result.stdout


def changed_paths(base=None):
    if base is not None:
        if not re.fullmatch(r'[A-Za-z0-9_./^~\-]+', base) or base.startswith('-') or set(base) == {'0'}:
            raise ValueError('A valid, existing Git base is required; no full-workspace fallback')
        try:
            command(['git', 'rev-parse', '--verify', f'{base}^{{commit}}'])
        except RuntimeError:
            if os.environ.get('FABER_FETCH_BASE') != '1' or not re.fullmatch(r'[0-9a-fA-F]{40}', base):
                raise
            # A push may contain more than checkout's two commits. Fetch just its
            # exact base, under the same time/memory guard; never broaden the diff.
            command(['git', 'fetch', '--no-tags', '--depth=1', 'origin', base])
            command(['git', 'rev-parse', '--verify', f'{base}^{{commit}}'])
        raw = command(['git', 'diff', '--name-only', '-z', base, 'HEAD', '--'])
    else:
        raw = command(['git', 'diff', '--name-only', '-z', 'HEAD', '--'])
        raw += command(['git', 'ls-files', '--others', '--exclude-standard', '-z'])
    return sorted(set(p.decode('utf-8') for p in raw.split(b'\0') if p))


def checked_file(relative):
    candidate = (ROOT / relative).resolve()
    if not candidate.is_relative_to(ROOT):
        raise ValueError(f'Path escapes the workspace: {relative}')
    return candidate


def plan(paths, policy):
    if len(paths) > policy['max_changed_files']:
        raise ValueError('Change set exceeds the bounded source-check budget; narrow it explicitly')
    files = [p for p in paths if checked_file(p).is_file()]
    rust = [p for p in files if p.endswith('.rs')]
    native_required = any(p.endswith('.rs') or p.endswith('Cargo.toml') or p.endswith('Cargo.lock')
                          or p.startswith(('.cargo/', 'rust-toolchain')) for p in paths)
    return dict(scope='source_checks_only', files=files, changed_files=len(paths),
                rust_files=rust, native_tests='not_executed',
                native_validation_required=native_required,
                build_commands=[], timeout_seconds=policy['timeout_seconds'], memory_mb=policy['memory_mb'])


def validate_workflows(policy):
    directory = ROOT / '.github' / 'workflows'
    active = sorted(p.name for p in directory.iterdir() if p.suffix.lower() in ('.yml', '.yaml'))
    if active != policy['active_workflows']:
        raise ValueError(f'Unexpected active workflow(s): {active}')
    # JSON is a YAML subset: inspect the entire workflow without an extra YAML dependency.
    workflow = json.loads((directory / 'faber-ci.yml').read_text(encoding='utf-8'))
    if set(workflow['on']) != {'push', 'pull_request', 'workflow_dispatch'}:
        raise ValueError('Only push/PR/explicit dispatch are allowed; no schedules or chained workflows')
    if workflow['permissions'] != {'contents': 'read'}:
        raise ValueError('CI permissions must remain read-only')
    if workflow['concurrency'].get('cancel-in-progress') is not True:
        raise ValueError('Superseded CI runs must be cancelled')
    jobs = workflow['jobs']
    if set(jobs) != {'source-checks'}:
        raise ValueError('Only one source-check job is permitted')
    job = jobs['source-checks']
    if set(job) - {'name', 'runs-on', 'timeout-minutes', 'steps'}:
        raise ValueError('No additional job services, containers or execution settings are allowed')
    if job['runs-on'] != 'ubuntu-24.04' or not 0 < job['timeout-minutes'] <= 5 or 'strategy' in job:
        raise ValueError('Unexpected runner, timeout or matrix')
    steps = job['steps']
    if (len(steps) != 3
            or steps[0].get('uses') != 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
            or steps[0].get('with', {}).get('persist-credentials') is not False
            or steps[0].get('with', {}).get('fetch-depth') != 2):
        raise ValueError('Checkout must not persist credentials; no extra build/upload/install steps')
    if (set(steps[0]) != {'uses', 'with'} or set(steps[1]) != {'name', 'env', 'run'}
            or set(steps[2]) != {'name', 'if', 'run'} or steps[2]['if'] != 'always()'):
        raise ValueError('Unexpected workflow step settings')
    run = steps[1]['run']
    required = ('systemd-run', '--wait', '--pipe', '--collect', '--service-type=exec',
                'MemoryMax=1073741824', 'MemorySwapMax=0', 'RuntimeMaxSec=180',
                'KillMode=control-group', 'OOMPolicy=kill', 'CPUQuota=100%', 'TasksMax=64',
                'TimeoutStopSec=5', '--uid=', '--gid=',
                'scripts/faber_ci.py check', '--setenv=PATH=', '--setenv=HOME=',
                '--setenv=RUSTUP_HOME=', '--setenv=CARGO_HOME=')
    if any(flag not in run for flag in required) or '--scope' in run:
        raise ValueError('GitHub process-tree resource protection is incomplete')
    all_runs = '\n'.join(step.get('run', '') for step in steps)
    if any(word in all_runs for word in ('cargo ', 'pip install', 'apt-get', 'docker ', 'workflow_dispatch')):
        raise ValueError('Native builds/downloads/recursive workflows are forbidden in automatic CI')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def validate_sources(files, policy):
    for relative in files:
        path = checked_file(relative)
        if path.stat().st_size > policy['max_file_bytes']:
            raise ValueError(f'Source file exceeds the check budget: {relative}')
        if path.suffix == '.json':
            def reject_constant(value):
                raise ValueError(f'Non-finite JSON constant: {value}')
            data = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
            if relative.startswith('assets/locales/pending/'):
                if not isinstance(data, dict) or any(not isinstance(messages, dict) for messages in data.values()):
                    raise ValueError(f'Invalid pending locale structure: {relative}')
                if any(not isinstance(text, str) for messages in data.values() for text in messages.values()):
                    raise ValueError(f'Locale messages must be strings: {relative}')
        elif path.suffix == '.toml' or path.name == 'Cargo.lock':
            tomllib.loads(path.read_text(encoding='utf-8'))
        elif path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')


def rust_edition(path):
    for directory in path.parents:
        manifest = directory / 'Cargo.toml'
        if manifest.is_file():
            data = tomllib.loads(manifest.read_text(encoding='utf-8'))
            edition = data.get('package', {}).get('edition')
            if isinstance(edition, str):
                return edition
            break
        if directory == ROOT:
            break
    return str(tomllib.loads((ROOT / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']['package']['edition'])


def source_checks(base, policy):
    paths = changed_paths(base)
    report = plan(paths, policy)
    report['base'] = base or 'working_tree_against_HEAD'
    validate_workflows(policy)
    validate_sources(report['files'], policy)
    args = ['git', 'diff', '--check'] + ([base, 'HEAD'] if base else ['HEAD']) + ['--']
    command(args, policy['step_timeout_seconds'])
    rustfmt = shutil.which('rustfmt')
    if report['rust_files'] and rustfmt is None:
        raise ValueError('rustfmt is missing; install it explicitly. CI never downloads tools.')
    if report['rust_files'] and (rustup := shutil.which('rustup')):
        # Resolve an installed binary, bypassing rustup shims which could install
        # a toolchain selected by a newly changed rust-toolchain file.
        rustfmt = command([rustup, 'which', '--toolchain', 'stable', 'rustfmt']).decode().strip()
        if not Path(rustfmt).is_file():
            raise ValueError('An installed stable rustfmt binary is required')
    for relative in report['rust_files']:
        path = checked_file(relative)
        command([rustfmt, '--edition', rust_edition(path), '--check', '--config', 'skip_children=true', str(path)],
                policy['step_timeout_seconds'])
    tests = command([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests/tools', '-p', 'test_faber_*.py'],
                    policy['step_timeout_seconds'])
    print(tests.decode('utf-8', errors='replace').strip())
    report['result'] = 'source_checks_passed'
    return report


def artifact_smoke(cli, policy):
    if not cli:
        raise ValueError('Artifact smoke requires an explicit --cli path; CI never builds or guesses a binary')
    binary = Path(cli).resolve(strict=True)
    if not binary.is_file():
        raise ValueError('CLI must be an existing file')
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output = ROOT / 'target' / 'faber-ci' / 'artifact-smoke'
    command([sys.executable, 'examples/faber/check-workshop-mcp.py', '--cli', str(binary), '--output', str(output)], 60)
    return dict(result='artifact_smoke_passed', scope='existing_artifact_only', binary=str(binary),
                sha256=digest, current_source_verified=False, native_compilation='not_executed')


def worker(args, policy):
    resource_budget.ensure_guarded(policy['memory_mb'])
    started = time.monotonic()
    try:
        if args.mode == 'plan':
            report = plan(changed_paths(args.base), policy)
        elif args.mode == 'smoke':
            report = artifact_smoke(args.cli, policy)
        else:
            report = source_checks(args.base, policy)
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        destination = checked_file('target/faber-ci/' + ('plan.json' if args.mode == 'plan' else 'report.json'))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report if args.mode == 'plan' else
                         {k: v for k, v in report.items() if k not in ('files', 'rust_files')}, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'FABER CI FAILED: {error}', file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'plan', 'smoke'), nargs='?', default='check')
    parser.add_argument('--base')
    parser.add_argument('--cli')
    args = parser.parse_args()
    try:
        policy = load_policy()
        report_path = ROOT / 'target' / 'faber-ci' / 'report.json'
        if not report_path.parent.resolve().is_relative_to(ROOT) or report_path.is_symlink():
            raise ValueError('Unsafe CI report path')
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.unlink(missing_ok=True)
        # No publicly routable worker mode: every CLI invocation enters the
        # bounded launcher. The child calls the internal function directly.
        bootstrap = ("import sys,runpy; from argparse import Namespace; "
                     "m=runpy.run_path(sys.argv[1]); "
                     "sys.exit(m['worker'](Namespace(mode=sys.argv[2],base=sys.argv[3] or None,"
                     "cli=sys.argv[4] or None),m['load_policy']()))")
        child = [sys.executable, '-B', '-c', bootstrap, str(Path(__file__).resolve()),
                 args.mode, args.base or '', args.cli or '']
        outcome = resource_budget.run_bounded(child, ROOT, policy['timeout_seconds'], policy['memory_mb'],
                                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                                    'CARGO_BUILD_JOBS': '1', 'RUST_TEST_THREADS': '1'})
        if outcome.timed_out:
            print('FABER CI stopped: time budget exceeded; no validation success.', file=sys.stderr)
        if outcome.returncode:
            report_path.write_text(json.dumps(dict(result='failed_or_incomplete', native_tests='not_executed',
                                                  timed_out=outcome.timed_out, returncode=outcome.returncode)) + '\n', encoding='utf-8')
        return outcome.returncode
    except (ValueError, OSError, RuntimeError) as error:
        print(f'FABER CI refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
