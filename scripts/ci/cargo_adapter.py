"""Pinned Cargo process-tree adapter. No public build CLI; tests use fake tools."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resource_budget as budget
from rebuild_policy import RebuildPolicy, RebuildDenied, digest
from windows_process_gate import supervise


SAFE_PROBES = {('-vV',), ('-V',), ('--version',), ('--print=sysroot',), ('--print=cfg',)}


def _write_receipt(path, value):
    pending = path.with_name(path.name+'.pending')
    pending.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(pending, path)


def read_only_probe(args):
    if tuple(args) in SAFE_PROBES:
        return True
    # Cargo's format/target probe reads stdin but never emits compiled output.
    prints, sources, i = [], [], 0
    while i < len(args):
        token = args[i]
        i += 1
        if token == '-':
            sources.append(token)
            continue
        if token == '-Wwarnings':
            continue
        if '=' in token:
            key, value = token.split('=', 1)
        elif token in ('--crate-name', '--crate-type', '--print', '--target', '-W') and i < len(args):
            key, value = token, args[i]
            i += 1
        else:
            return False
        if key == '--print' and value in ('file-names', 'sysroot', 'split-debuginfo', 'crate-name', 'cfg'):
            prints.append(value)
        elif (key == '--crate-name' and value == '___') or (key == '--crate-type' and value in ('bin', 'rlib', 'dylib', 'cdylib', 'staticlib', 'proc-macro')):
            pass
        elif (key == '--target' and value == 'x86_64-pc-windows-msvc') or (key == '-W' and value == 'warnings'):
            pass
        else:
            return False
    return bool(prints) and sources in ([], ['-'])


def pin_program(command):
    if not isinstance(command, list) or not command or any(not isinstance(a, str) or '\0' in a for a in command):
        raise ValueError('Invalid pinned tool command')
    image = Path(command[0]).resolve(strict=True)
    if not Path(command[0]).is_absolute():
        raise ValueError('Tool image must be absolute')
    hashes = {str(image): digest(image)}
    for value in command[1:]:
        path = Path(value)
        if path.is_absolute() and path.is_file():
            hashes[str(path.resolve(strict=True))] = digest(path)
    return dict(command=[str(image), *command[1:]], hashes=hashes)


def _match(tool, image, argv):
    command = tool['command']
    if image != Path(command[0]) or argv[1:len(command)] != command[1:]:
        return None
    for name, expected in tool['hashes'].items():
        if digest(Path(name)) != expected:
            raise RebuildDenied('pinned_tool_changed')
    return argv[len(command):]


def build_arguments(root):
    return ['build', '--manifest-path', str(Path(root)/'apps/solidcraft/Cargo.toml'),
            '--package', 'solidcraft', '--bin', 'solidcraft', '--offline', '--locked',
            '--jobs', '1', '--no-default-features', '--features', 'profile']


def sanitized_environment(config):
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('CARGO_BUILD_', 'CARGO_TARGET_', 'RUSTC', 'RUSTDOC'))
           and key.upper() not in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTUP_TOOLCHAIN')}
    env.update(CARGO_NET_OFFLINE='true', CARGO_BUILD_JOBS='1',
               CARGO_TARGET_DIR=str(Path(config['root'])/'target'),
               RUSTC=config['compiler']['command'][0], RUSTC_WRAPPER='', RUSTC_WORKSPACE_WRAPPER='')
    if config.get('synthetic'):
        env['CARGO_HOME'] = str(Path(config['root'])/'fake-cargo-home')
    # Test-only data, not an alternate executable selection for production Cargo.
    for key, value in config.get('test_environment', {}).items():
        if not config.get('synthetic') or not key.startswith('FABER_FAKE_'):
            raise ValueError('Unexpected adapter environment override')
        env[key] = value
    return env


class CargoProcessPolicy:
    def __init__(self, config):
        self.config = config
        self.policy = RebuildPolicy(config['root'], config.get('build_script_pins', {}))
        self.root_seen = False

    def authorize(self, image, argv, cwd, env, parent):
        if self.policy.denied:
            raise RebuildDenied('attempt_already_denied')
        try:
            self.policy._current()
            if parent is None:
                if self.root_seen or _match(self.config['cargo'], image, argv) != build_arguments(self.policy.root):
                    raise RebuildDenied('unapproved_root_cargo_command')
                if Path(cwd).resolve() != self.policy.root:
                    raise RebuildDenied('unexpected_cargo_working_directory')
                self.root_seen = True
                return dict(role='cargo')
            args = _match(self.config['compiler'], image, argv)
            delegated = False
            if args is None:
                for interpreter in self.config.get('compiler_interpreters', []):
                    args = _match(interpreter, image, argv)
                    if args is not None:
                        delegated = True
                        break
            if args is not None:
                if delegated:
                    if parent['role'] not in ('compiler', 'compiler-probe') or parent.get('arguments') != args:
                        raise RebuildDenied('unapproved_compiler_interpreter')
                elif parent['role'] != 'cargo':
                    raise RebuildDenied('compiler_not_started_by_cargo')
                if read_only_probe(args):
                    return dict(role='compiler-probe', arguments=args)
                if not env.get('CARGO_MANIFEST_DIR'):
                    raise RebuildDenied('unsupported_probe_or_missing_package_identity')
                unit = self.policy.authorize_compile(env.get('CARGO_MANIFEST_DIR'), cwd, args)
                if env.get('CARGO_PKG_NAME', unit.package) != unit.package:
                    raise RebuildDenied('cargo_package_environment_mismatch')
                return dict(role='compiler', package=unit.package, arguments=args)
            artifact = image
            script_args = argv[1:]
            for tool in self.config.get('script_launchers', []):
                args = _match(tool['program'], image, argv)
                if args is not None:
                    if args:
                        raise RebuildDenied('unexpected_build_script_arguments')
                    artifact = Path(tool['artifact']).resolve(strict=True)
                    script_args = []
                    break
            if artifact.is_relative_to(self.policy.root/'target/debug/build'):
                if script_args:
                    raise RebuildDenied('unexpected_build_script_arguments')
                if parent['role'] != 'cargo':
                    raise RebuildDenied('script_not_started_by_cargo')
                unit = self.policy.authorize_build_script(env.get('CARGO_MANIFEST_DIR'), artifact)
                if env.get('CARGO_PKG_NAME', unit.package) != unit.package:
                    raise RebuildDenied('cargo_package_environment_mismatch')
                return dict(role='build-script', package=unit.package)
            # No shell, linker, nested Cargo or helper can start by name alone.
            # Production helpers need an explicit pinned identity and parent role.
            for helper in self.config.get('helpers', []):
                args = _match(helper['program'], image, argv)
                if args is not None and parent['role'] in helper['parents']:
                    return dict(role='helper')
            raise RebuildDenied('unapproved_child_executable')
        except (OSError, ValueError, TypeError) as error:
            self.policy.denied = True
            raise RebuildDenied(str(error))


def _worker(config_path):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    root = Path(config['root']).resolve(strict=True)
    receipt = Path(config['receipt']).resolve()
    if not receipt.is_relative_to(root/'target'):
        raise ValueError('Receipt must stay in this attempt cache')
    events = []
    result = dict(result='refused', events=events, compilation_authorized=not config['synthetic'])
    try:
        if not config['synthetic'] and not config.get('real_tools_owner_authorized'):
            raise ValueError('No owner authorization for real tool execution')
        if sys.platform != 'win32':
            raise budget.BudgetSetupError('Cargo process interception is Windows-only; no fallback')
        budget.ensure_guarded(1024)
        api = budget._windows_api()
        if budget._process_affinity(api, api.GetCurrentProcess()).bit_count() != 1:
            raise budget.BudgetSetupError('Adapter requires the single-CPU guard')
        gate = CargoProcessPolicy(config)
        code = supervise([*config['cargo']['command'], *build_arguments(root)], root,
                         sanitized_environment(config), gate.authorize, events, config['timeout_seconds'])
        result.update(result='completed' if code == 0 else 'tool_failed', returncode=code)
        return code
    except (OSError, RuntimeError, ValueError) as error:
        result.update(reason=str(error), returncode=125)
        return 125
    finally:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        _write_receipt(receipt, result)


def run_guarded(config, timeout_seconds=120, memory_mb=1024, watchdog=None, *, owner_authorized=False):
    """No real tool run without explicit authorization. There is no execute CLI."""
    if not config.get('synthetic') and not owner_authorized:
        raise ValueError('Real Cargo execution requires separate owner authorization')
    if sys.platform != 'win32':
        raise budget.BudgetSetupError('Cargo process interception is Windows-only; no fallback')
    if not 0 < timeout_seconds <= 120 or not 1 <= memory_mb <= 1024:
        raise ValueError('Attempt exceeds the reconstruction plan')
    watchdog = watchdog or budget.WindowsWatchdog()
    if not config.get('synthetic') and (watchdog.working_set_mb > 768
            or watchdog.minimum_available_physical_mb < 4096
            or watchdog.minimum_available_commit_mb < 2048):
        raise ValueError('Real-tool watchdog cannot relax the reconstruction plan')
    root = Path(config['root']).resolve(strict=True)
    receipt_path = Path(config['receipt']).resolve()
    if not receipt_path.is_relative_to(root/'target'):
        raise ValueError('Receipt must stay in this attempt cache')
    config_path = root/'target/cargo-gate-config.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {**config, 'root': str(root), 'timeout_seconds': timeout_seconds,
            'real_tools_owner_authorized': bool(owner_authorized and not config.get('synthetic'))}
    # Validate identities before any process starts, not only at create events.
    CargoProcessPolicy(data)
    for tool in [data['cargo'], data['compiler'], *[h['program'] for h in data.get('helpers', [])],
                 *[s['program'] for s in data.get('script_launchers', [])], *data.get('compiler_interpreters', [])]:
        if _match(tool, Path(tool['command'][0]), tool['command']) != []:
            raise ValueError('Invalid tool pin')
    config_path.write_text(json.dumps(data), encoding='utf-8')
    # Clear any previous outcome before launch: a killed worker must never leave
    # an old successful receipt masquerading as this attempt's result.
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_receipt(receipt_path, dict(result='not_started', events=[]))
    outcome = budget.run_bounded([sys.executable, '-I', '-S', str(Path(__file__).resolve()), '--internal-worker', str(config_path)],
                                 root, timeout_seconds, memory_mb, watchdog=watchdog)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    receipt['resources'] = asdict(outcome)
    if outcome.returncode and receipt['result'] in ('not_started', 'completed'):
        receipt.update(result='stopped', returncode=outcome.returncode, reason=outcome.stop_reason or 'guarded_worker_failed')
    _write_receipt(receipt_path, receipt)
    return outcome


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--internal-worker':
        raise SystemExit('Internal guarded worker only; use faber_dev.py for a plan without execution.')
    raise SystemExit(_worker(sys.argv[2]))
