"""Bounded exact-source typecheck over an already built engine; tests are opt-in.

No Cargo, package builds, tool downloads or dependency guessing. This does not
qualify the current desktop, registry dispatch, MCP routing or outer undo wrapper.
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
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import resource_budget

SOURCE_PATHS = (
    'examples/faber/workshop-design-tests.py',
    'examples/faber/workshop-design-tests.rs',
    'crates/engine/src/cmd/workshop_wood.rs',
    'crates/engine/src/cmd/workshop_wood_tests.rs',
    'crates/engine/src/cmd/workshop_hardware.rs',
    'crates/engine/src/cmd/workshop_hardware_tests.rs',
)
DEPENDENCIES = ('serde', 'serde_json', 'schemars', 'solidcraft_doc', 'solidcore_record', 'solidcraft_geom')
OUTPUT = ROOT / 'target/workshop/design-qualification'
TIMEOUT_SECONDS = 170


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_hashes():
    return {relative: digest(ROOT / relative) for relative in SOURCE_PATHS}


def dependencies_for(engine):
    """Resolve exact cached dependency identities from Cargo fingerprint receipts.

    Cargo stores each dependency's fingerprint as a little-endian u64. Match that
    identifier to its existing fingerprint directory and require the exact rlib.
    Never choose arbitrary latest versions or retry combinations until one links.
    """
    name = engine.stem
    if not name.startswith('libsolidcraft_engine-'):
        raise ValueError('Expected an explicit cached libsolidcraft_engine-HASH.rlib')
    suffix = name.removeprefix('libsolidcraft_engine-')
    fingerprints = engine.parent.parent / '.fingerprint'
    receipt = fingerprints / f'solidcraft-engine-{suffix}' / 'lib-solidcraft_engine.json'
    engine_info = json.loads(receipt.read_text(encoding='utf-8'))
    wanted = {d[1]: d[3] for d in engine_info['deps']}
    selected = {}
    for crate in DEPENDENCIES:
        expected = wanted[crate]
        matches = []
        # Package names use hyphens except serde_json, whose package retains '_'.
        package = crate if crate == 'serde_json' else crate.replace('_', '-')
        for fingerprint in fingerprints.glob(f'{package}-*/lib-{crate}'):
            value = fingerprint.read_text(encoding='ascii').strip()
            if len(value) != 16 or int.from_bytes(bytes.fromhex(value), 'little') != expected:
                continue
            artifact_hash = fingerprint.parent.name.removeprefix(package + '-')
            artifact = engine.parent / f'lib{crate}-{artifact_hash}.rlib'
            if artifact.is_file():
                matches.append(artifact.resolve())
        if len(matches) != 1:
            raise ValueError(f'Exactly one existing matching {crate} rlib is required; found {len(matches)}')
        selected[crate] = matches[0]
    return selected


def stage_dependency_closure(engine, crate='solidcraft_engine', metadata_only=False):
    """Hardlink one exact cached graph; metadata-only mode never falls back to rlibs."""
    engine = Path(engine).resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', crate) or not engine.stem.startswith(f'lib{crate}-'):
        raise ValueError('Cached artifact must match the explicit crate name')
    fingerprint_root = engine.parent.parent / '.fingerprint'
    index = {}
    for path in fingerprint_root.glob('*/lib-*'):
        if path.suffix or not path.is_file():
            continue
        value = path.read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-f]{16}', value):
            continue
        key = (path.name.removeprefix('lib-'), int.from_bytes(bytes.fromhex(value), 'little'))
        index.setdefault(key, []).append(path)
    suffix = engine.stem.removeprefix(f'lib{crate}-')
    pending = [fingerprint_root / f'{crate.replace("_", "-")}-{suffix}' / f'lib-{crate}']
    selected = {}
    visited = set()
    while pending:
        fingerprint = pending.pop()
        if fingerprint in visited:
            continue
        visited.add(fingerprint)
        crate = fingerprint.name.removeprefix('lib-')
        suffix = fingerprint.parent.name.rsplit('-', 1)[1]
        metadata = engine.parent / f'lib{crate}-{suffix}.rmeta'
        artifacts = ([metadata] if metadata_only else [engine.parent / f'lib{crate}-{suffix}.rlib']) + [
            engine.parent / f'{crate}-{suffix}.dll', engine.parent / f'lib{crate}-{suffix}.dll']
        artifact = next((p for p in artifacts if p.is_file()), None)
        if artifact is None:
            kind = 'metadata/proc-macro' if metadata_only else 'artifact'
            raise ValueError(f'Missing exact cached {kind} for {fingerprint.parent.name}')
        selected[artifact.name] = artifact
        # Matching rmeta avoids opening a much larger archive during metadata lookup.
        if metadata.is_file():
            selected[metadata.name] = metadata
        info = json.loads(fingerprint.with_suffix('.json').read_text(encoding='utf-8'))
        for _, name, _, checksum in info['deps']:
            if name == 'build_script_build':
                continue  # Cargo build-script records are not rustc library dependencies.
            matches = index.get((name, checksum), [])
            if not matches:
                # Cargo dependency aliases (e.g. digest's `common` for
                # crypto_common) retain the exact fingerprint identity.
                matches = [p for (_, value), entries in index.items()
                           if value == checksum for p in entries]
            if len(matches) != 1:
                raise ValueError(f'A unique exact transitive fingerprint for {name} in {fingerprint.parent.name} is required; found {len(matches)}')
            pending.append(matches[0])
    if not OUTPUT.resolve().is_relative_to(ROOT) or OUTPUT.is_symlink():
        raise ValueError('Unsafe dependency-staging directory')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    directory = OUTPUT / ('dependencies-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    for name, path in selected.items():
        os.link(path, directory / name)
    return directory, selected


def tool(name):
    rustup = shutil.which('rustup')
    if rustup:
        result = subprocess.run([rustup, 'which', '--toolchain', 'stable', name],
                                cwd=ROOT, check=True, capture_output=True, text=True, timeout=10)
        path = Path(result.stdout.strip())
        if path.is_file():
            return str(path)
        raise ValueError(f'Installed stable {name} not found; no automatic installation')
    found = shutil.which(name)
    if not found:
        raise ValueError(f'Installed {name} not found; no automatic installation')
    return found


def worker(engine, run_tests=False):
    resource_budget.ensure_guarded(1024)
    engine = Path(engine).resolve(strict=True)
    started = time.monotonic()
    before = source_hashes()
    deps = dependencies_for(engine)
    staged, closure = stage_dependency_closure(engine)
    executable = OUTPUT / ('workshop-design-tests.exe' if sys.platform == 'win32' else 'workshop-design-tests')
    compile_log = OUTPUT / 'compile.log'
    tests_log = OUTPUT / 'tests.log'
    args = [tool('rustc'), '--edition', '2024', '--test', str(ROOT / 'examples/faber/workshop-design-tests.rs'),
            '--crate-name', 'faber_workshop_design_tests', '--extern', f'solidcraft_engine={engine}',
            '-L', f'dependency={staged}', '-C', 'debuginfo=0', '-C', 'opt-level=0',
            '-o', str(executable)]
    for crate, artifact in deps.items():
        args += ['--extern', f'{crate}={artifact}']
    metadata_args = list(args)
    for index, value in enumerate(metadata_args):
        if index > 0 and metadata_args[index - 1] == '--extern':
            crate, path = value.split('=', 1)
            metadata_path = Path(path).with_suffix('.rmeta')
            if metadata_path.is_file():
                metadata_args[index] = f'{crate}={metadata_path}'
    output_index = metadata_args.index('-o')
    metadata_args[output_index + 1] = str(OUTPUT / 'handlers.rmeta')
    metadata_args += ['--emit', 'metadata']
    with (OUTPUT / 'metadata.log').open('wb') as output:
        metadata = subprocess.run(metadata_args, cwd=ROOT, stdin=subprocess.DEVNULL,
                                  stdout=output, stderr=subprocess.STDOUT, timeout=30,
                                  env={**os.environ, 'RUSTC_LOG': 'rustc_metadata::locator=info'})
    if metadata.returncode:
        print((OUTPUT / 'metadata.log').read_text(encoding='utf-8', errors='replace')[-16000:])
        return metadata.returncode
    if source_hashes() != before:
        raise ValueError('Sources changed during metadata qualification')
    metadata_receipt = dict(result='source_typecheck_passed', scope='exact_source_typecheck_over_cached_engine',
                            native_tests='not_executed', current_engine_registry_verified=False,
                            current_desktop_verified=False, current_mcp_dispatch_verified=False,
                            source_sha256=before, engine=str(engine),
                            engine_metadata_sha256=digest(engine.with_suffix('.rmeta')),
                            staged_dependency_artifacts=len(closure), memory_mb=1024,
                            timeout_seconds=TIMEOUT_SECONDS if run_tests else 45)
    (OUTPUT / 'metadata-receipt.json').write_text(json.dumps(metadata_receipt, indent=2) + '\n', encoding='utf-8')
    print('Exact-source native metadata typecheck passed; runtime tests not yet executed.', flush=True)
    if not run_tests:
        (OUTPUT / 'receipt.json').write_text(json.dumps(metadata_receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(metadata_receipt, indent=2))
        return 0
    with compile_log.open('wb') as output:
        result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        print(compile_log.read_text(encoding='utf-8', errors='replace')[-12000:])
        return result.returncode
    with tests_log.open('wb') as output:
        result = subprocess.run([str(executable), '--test-threads=1', '--nocapture'], cwd=ROOT,
                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=15)
    test_output = tests_log.read_text(encoding='utf-8', errors='replace')
    print(test_output[-12000:])
    if result.returncode:
        return result.returncode
    tests_passed = re.search(r'test result: ok\. ([1-9][0-9]*) passed;', test_output)
    if tests_passed is None:
        raise ValueError('Qualification must actually execute at least one passing test')
    if source_hashes() != before:
        raise ValueError('Sources changed during qualification; result is not valid')
    receipt = dict(result='handler_tests_passed', scope='exact_source_handlers_over_cached_engine',
                   current_desktop_verified=False, current_mcp_dispatch_verified=False,
                   current_engine_registry_verified=False, outer_session_undo_verified=False,
                   engine=str(engine), engine_sha256=digest(engine),
                   engine_mtime_ns=engine.stat().st_mtime_ns, source_sha256=before,
                   dependencies={name: str(path) for name, path in deps.items()},
                   staged_dependency_artifacts=len(closure),
                   tests_passed=int(tests_passed.group(1)),
                   elapsed_seconds=round(time.monotonic() - started, 3),
                   memory_mb=1024, timeout_seconds=TIMEOUT_SECONDS, cargo_build='not_executed')
    (OUTPUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path, help='Explicit existing cached engine rlib')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--typecheck-only', action='store_true', help='Only typecheck exact sources; this is the default')
    mode.add_argument('--run-tests', action='store_true', help='Explicitly compile/link and run tests within the same budget')
    opts = parser.parse_args()
    try:
        engine = opts.engine.resolve(strict=True)
        # Reject an escaped/symlinked output location before writing or deleting receipts.
        if not OUTPUT.resolve().is_relative_to(ROOT) or OUTPUT.is_symlink():
            raise ValueError('Unsafe qualification output path')
        OUTPUT.mkdir(parents=True, exist_ok=True)
        receipt = OUTPUT / 'receipt.json'
        if receipt.is_symlink():
            raise ValueError('Unsafe qualification receipt path')
        receipt.unlink(missing_ok=True)
        metadata_receipt = OUTPUT / 'metadata-receipt.json'
        if metadata_receipt.is_symlink():
            raise ValueError('Unsafe metadata qualification receipt path')
        metadata_receipt.unlink(missing_ok=True)
        bootstrap = ("import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                     "sys.exit(m['worker'](sys.argv[2],sys.argv[3]=='run-tests'))")
        outcome = resource_budget.run_bounded([sys.executable, '-B', '-c', bootstrap,
                                               str(Path(__file__).resolve()), str(engine),
                                               'run-tests' if opts.run_tests else 'typecheck-only'],
                                              ROOT, TIMEOUT_SECONDS if opts.run_tests else 45, 1024,
                                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if outcome.returncode:
            receipt.write_text(json.dumps(dict(result='failed_or_incomplete', timed_out=outcome.timed_out,
                                               returncode=outcome.returncode)) + '\n', encoding='utf-8')
        print(outcome)
        return outcome.returncode
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Qualification refused: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
