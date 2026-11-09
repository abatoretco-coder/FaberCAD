"""Typecheck the production UI source against explicitly selected cached metadata.

Default is a read-only plan. --check emits metadata only. The separate explicit
--dependencies-only mode checks Rust's source dependency file, not types. Neither
mode runs tests, linking, Cargo, downloads or a fallback build. Cached engine and
generated resources do not qualify the current registry, executable or rendering.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import resource_budget

spec = importlib.util.spec_from_file_location('qualification', Path(__file__).with_name('workshop-design-tests.py'))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
OUTPUT = ROOT / 'target/workshop/ui-source-qualification'


def prepare(cache):
    cache = Path(cache).resolve(strict=True)
    prefix = 'libsolidcraft_ui_egui-'
    if cache.suffix != '.rmeta' or not cache.stem.startswith(prefix):
        raise ValueError('An explicit cached libsolidcraft_ui_egui-HASH.rmeta is required')
    suffix = cache.stem.removeprefix(prefix)
    fingerprint_root = cache.parent.parent / '.fingerprint'
    info = json.loads((fingerprint_root / f'solidcraft-ui-egui-{suffix}/lib-solidcraft_ui_egui.json').read_text())
    index = {}
    for item in fingerprint_root.glob('*/lib-*'):
        if item.suffix or not item.is_file():
            continue
        value = item.read_text(encoding='ascii').strip()
        if len(value) == 16:
            index.setdefault((item.name.removeprefix('lib-'), int.from_bytes(bytes.fromhex(value), 'little')), []).append(item)
    externs, generated = {}, None
    for _, name, _, checksum in info['deps']:
        if name == 'build_script_build':
            matches = [p for p in fingerprint_root.glob('solidcraft-ui-egui-*/run-build-script-build-script-build')
                       if int.from_bytes(bytes.fromhex(p.read_text().strip()), 'little') == checksum]
            if len(matches) != 1:
                raise ValueError('Exact cached UI build-script output is unavailable')
            generated = cache.parent.parent / 'build' / matches[0].parent.name
            continue
        matches = index.get((name, checksum), [])
        if len(matches) != 1:
            raise ValueError(f'Exact cached dependency {name} is unavailable or ambiguous')
        artifact_suffix = matches[0].parent.name.rsplit('-', 1)[1]
        artifact = cache.parent / f'lib{name}-{artifact_suffix}.rmeta'
        if not artifact.is_file():
            raise ValueError(f'Matching standalone metadata for {name} is required')
        externs[name] = str(artifact)
    if generated is None:
        raise ValueError('Cached generated UI resources are required')
    for relative in ('out/locales/en.json', 'out/builtin_themes.rs', 'out/icon_data.rs'):
        if not (generated / relative).is_file():
            raise ValueError(f'Cached generated resource is missing: {relative}')
    env = {'CARGO_MANIFEST_DIR': str(ROOT / 'crates/ui-egui'),
           'CARGO_PKG_VERSION': str(tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']),
           'OUT_DIR': str(generated / 'out')}
    for line in (generated / 'output').read_text(encoding='utf-8').splitlines():
        if line.startswith('cargo:rustc-env='):
            key, value = line.removeprefix('cargo:rustc-env=').split('=', 1)
            if key in ('SOLIDCRAFT_COMMIT', 'SOLIDCRAFT_BUILD_DATE'):
                env[key] = value
    if not {'SOLIDCRAFT_COMMIT', 'SOLIDCRAFT_BUILD_DATE'} <= env.keys():
        raise ValueError('Cached build stamps are missing')
    features = tomllib.loads((ROOT / 'crates/ui-egui/Cargo.toml').read_text()).get('features', {})
    pending, enabled = (['default'] if 'default' in features else []), set()
    while pending:
        feature = pending.pop()
        if feature not in enabled:
            enabled.add(feature)
            pending.extend(features.get(feature, []))
    if 'legacy-embedded-assistant' in enabled:
        raise ValueError('The default UI must not enable the legacy assistant')
    return dict(cache=str(cache), externs=externs, env=env,
                features=sorted(enabled.intersection(features)), memory_mb=1024, timeout_seconds=45,
                scope='production_ui_metadata_only', native_tests='not_executed',
                current_engine_registry_verified=False, current_desktop_verified=False,
                generated_resources='cached_not_regenerated')


def source_hashes():
    paths = list((ROOT / 'crates/ui-egui/src').rglob('*.rs'))
    paths += [ROOT / 'crates/ui-egui/Cargo.toml', Path(__file__).resolve(),
              Path(__file__).with_name('workshop-design-tests.py')]
    return {str(path.relative_to(ROOT)): qualification.digest(path) for path in sorted(paths)}


def dependency_proof(path):
    text = path.read_text(encoding='utf-8').replace('\\\\', '/').replace('\\', '/')
    if '/agent_chat/' in text or '/ai_connect.rs' in text:
        raise ValueError('Production dependencies still load the legacy assistant implementation')
    if '/agent_preferences.rs' not in text:
        raise ValueError('Production dependencies must include the compatibility preference types')
    return dict(legacy_agent_chat_loaded=False, legacy_ai_connect_loaded=False,
                compatibility_preferences_loaded=True,
                dependency_file_sha256=qualification.digest(path))


def worker(cache, dependencies_only=False):
    resource_budget.ensure_guarded(1024)
    plan = prepare(cache)
    before = source_hashes()
    staged, dependencies = qualification.stage_dependency_closure(Path(cache).with_suffix('.rlib'),
                                                                 crate='solidcraft_ui_egui', metadata_only=True)
    emitted = OUTPUT / ('production-ui.d' if dependencies_only else 'production-ui.rmeta')
    args = [qualification.tool('rustc'), '--edition', '2024', '--crate-name', 'solidcraft_ui_egui',
            '--crate-type', 'rlib', '--emit', 'dep-info' if dependencies_only else 'metadata',
            str(ROOT / 'crates/ui-egui/src/lib.rs'), '-L', f'dependency={staged}',
            '-D', 'warnings', '-o', str(emitted)]
    for feature in plan['features']:
        args += ['--cfg', f'feature="{feature}"']
    for name, metadata in plan['externs'].items():
        args += ['--extern', f'{name}={metadata}']
    started = time.monotonic()
    with (OUTPUT / 'typecheck.log').open('wb') as log:
        result = subprocess.run(args, cwd=ROOT, env={**os.environ, **plan['env']},
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=40)
    if result.returncode:
        print((OUTPUT / 'typecheck.log').read_text(encoding='utf-8', errors='replace')[-12000:])
        return result.returncode
    if source_hashes() != before:
        raise ValueError('UI sources changed during typecheck; result is invalid')
    proof = dependency_proof(emitted) if dependencies_only else {}
    receipt = {**plan, **proof,
               'scope': 'production_ui_dependency_graph' if dependencies_only else plan['scope'],
               'result': 'production_ui_dependency_graph_passed' if dependencies_only else 'production_ui_source_typecheck_passed',
               'types_checked': not dependencies_only,
               'source_sha256': before, 'cache_sha256': qualification.digest(Path(cache)),
               'staged_metadata_artifacts': len(dependencies), 'dependency_lookup': 'exact_metadata_only',
               'elapsed_seconds': round(time.monotonic() - started, 3)}
    receipt.pop('env')
    (OUTPUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: receipt[k] for k in ('result', 'scope', 'types_checked', 'native_tests', 'elapsed_seconds')}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--dependencies-only', action='store_true')
    args = parser.parse_args()
    try:
        checking = args.check or args.dependencies_only
        if checking:
            if not OUTPUT.resolve().is_relative_to(ROOT) or OUTPUT.is_symlink():
                raise ValueError('Unsafe qualification output directory')
            OUTPUT.mkdir(parents=True, exist_ok=True)
            for name in ('receipt.json', 'typecheck.log', 'production-ui.rmeta', 'production-ui.d'):
                path = OUTPUT / name
                if path.is_symlink():
                    raise ValueError('Unsafe qualification output file')
                path.unlink(missing_ok=True)
        plan = prepare(args.cache)
        if not checking:
            print(json.dumps({k: v for k, v in plan.items() if k != 'env'}, indent=2))
            return 0
        bootstrap = "import runpy,sys;m=runpy.run_path(sys.argv[1]);sys.exit(m['worker'](sys.argv[2],sys.argv[3]=='dependencies-only'))"
        result = resource_budget.run_bounded([sys.executable, '-B', '-c', bootstrap,
                                             str(Path(__file__).resolve()), plan['cache'],
                                             'dependencies-only' if args.dependencies_only else 'metadata'], ROOT, 45, 1024,
                                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if result.returncode:
            (OUTPUT / 'receipt.json').write_text(json.dumps(dict(result='failed_or_incomplete',
                native_tests='not_executed', timed_out=result.timed_out, returncode=result.returncode)) + '\n')
        print(result)
        return result.returncode
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'UI metadata check refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
