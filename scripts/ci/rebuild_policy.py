"""Fail-closed authorization for a future scoped rebuild; never execute a tool.

This module executes no tools. cargo_adapter.py connects it to compiler and
cached build-script creation events under the Windows resource guard.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import tomllib


ALLOWED_PACKAGES = {
    'solidcraft-io': 'crates/io',
    'solidcraft-render': 'crates/render',
    'solidcraft-doc': 'crates/doc',
    'solidcraft-engine': 'crates/engine',
    'solidcraft-ui-egui': 'crates/ui-egui',
    'solidcraft': 'apps/solidcraft',
}
ALLOWED_FEATURES = frozenset({'profile', 'default'})


class RebuildDenied(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    package: str
    crate: str
    kind: str
    manifest: Path
    source: Path
    source_sha256: str


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(path, directory):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(directory):
        raise RebuildDenied('path_outside_authorized_directory')
    return resolved


class RebuildPolicy:
    def __init__(self, root, build_script_pins=None):
        self.root = Path(root).resolve(strict=True)
        self.denied = False
        self.units = []
        self.frozen = {}
        for name in ('Cargo.toml', 'Cargo.lock'):
            path = contained(self.root / name, self.root)
            self.frozen[path] = digest(path)
        for package, relative in ALLOWED_PACKAGES.items():
            directory = contained(self.root / relative, self.root)
            manifest = contained(directory / 'Cargo.toml', directory)
            data = tomllib.loads(manifest.read_text(encoding='utf-8'))
            if data['package']['name'] != package:
                raise RebuildDenied('manifest_package_identity_mismatch')
            self.frozen[manifest] = digest(manifest)
            if package == 'solidcraft':
                bins = [b for b in data.get('bin', []) if b['name'] == package]
                source = bins[0].get('path', 'src/main.rs') if bins else 'src/main.rs'
                self._unit(package, package, 'bin', manifest, directory / source)
            else:
                lib = data.get('lib', {})
                self._unit(package, lib.get('name', package.replace('-', '_')), 'lib', manifest, directory / lib.get('path', 'src/lib.rs'))
            build = data['package'].get('build', 'build.rs')
            if build is not False:
                source = directory / build
                if source.exists():
                    self._unit(package, 'build_script_build', 'build-script', manifest, source)
        self.script_pins = {}
        for artifact, (package, expected_digest) in (build_script_pins or {}).items():
            if package not in ALLOWED_PACKAGES or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
                raise RebuildDenied('invalid_build_script_pin')
            if not Path(artifact).is_absolute() or not Path(artifact).resolve(strict=True).is_relative_to(self.root / 'target' / 'debug' / 'build'):
                raise RebuildDenied('build_script_artifact_outside_cache')
            self.script_pins[Path(artifact).resolve(strict=True)] = (package, expected_digest)

    def _unit(self, package, crate, kind, manifest, source):
        source = contained(source, manifest.parent)
        if not source.is_file():
            raise RebuildDenied('source_is_not_a_file')
        self.units.append(Unit(package, crate, kind, manifest, source, digest(source)))

    def _refuse(self, reason):
        self.denied = True
        raise RebuildDenied(reason)

    def _current(self):
        if self.denied:
            self._refuse('attempt_already_denied')
        try:
            if any(digest(path) != expected for path, expected in self.frozen.items()):
                self._refuse('manifest_or_lockfile_changed')
        except OSError:
            self._refuse('manifest_or_lockfile_unavailable')

    def _manifest(self, directory):
        directory = contained(Path(directory), self.root)
        manifests = {unit.manifest for unit in self.units}
        manifest = directory / 'Cargo.toml'
        if manifest not in manifests:
            self._refuse('package_not_allowed')
        return manifest

    def authorize_compile(self, manifest_dir, cwd, argv):
        self._current()
        try:
            return self._compile(manifest_dir, cwd, argv)
        except (OSError, ValueError, TypeError) as error:
            self._refuse(str(error))

    def _compile(self, manifest_dir, cwd, argv):
        manifest = self._manifest(manifest_dir)
        cwd = Path(cwd).resolve(strict=True)
        if cwd not in (self.root, manifest.parent):
            self._refuse('unexpected_compiler_working_directory')
        if (not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= 4096
                or any(not isinstance(a, str) or not a or '\0' in a or len(a) > 32768 or a.startswith('@') for a in argv)
                or sum(len(a) for a in argv) > 65536):
            self._refuse('invalid_or_hidden_compiler_arguments')
        values, sources, outputs = {}, [], []
        takes_value = {'--crate-name', '--crate-type', '--edition', '--emit', '--cfg', '--check-cfg', '--out-dir', '-o',
                       '--extern', '--error-format', '--json', '--color', '--target', '--cap-lints', '--diagnostic-width',
                       '--remap-path-prefix', '-C', '-L', '-l', '-A', '-W', '-D', '-F'}
        index = 0
        while index < len(argv):
            token = argv[index]
            index += 1
            if token.startswith('--') and '=' in token:
                option, value = token.split('=', 1)
            elif token in takes_value:
                option = token
                if index >= len(argv):
                    self._refuse('missing_compiler_option_value')
                value = argv[index]
                index += 1
            elif token.startswith(('-C', '-L', '-l', '-A', '-W', '-D', '-F')) and len(token) > 2:
                option, value = token[:2], token[2:]
            elif token.startswith('-'):
                self._refuse('unknown_or_forbidden_compiler_option')
            else:
                sources.append(token)
                continue
            if option not in takes_value or not value:
                self._refuse('unknown_or_empty_compiler_option')
            if option in ('--crate-name', '--crate-type'):
                if option in values:
                    self._refuse('duplicate_compiler_identity_option')
                values[option] = value
            if option == '--cfg':
                value = value.strip()
                feature = re.fullmatch(r'feature\s*=\s*"([a-zA-Z0-9_-]+)"', value)
                # Unknown cfg forms (including raw identifiers) require review;
                # accepting them by prefix could re-enable test/legacy modules.
                if not feature or feature[1] not in ALLOWED_FEATURES:
                    self._refuse('disabled_feature_or_test_requested')
            if option == '--emit' and not set(value.split(',')) <= {'dep-info', 'link', 'metadata'}:
                self._refuse('unexpected_or_redirected_compiler_emit')
            if option == '--target' and value != 'x86_64-pc-windows-msvc':
                self._refuse('unexpected_compilation_target')
            if option in ('--out-dir', '-o'):
                outputs.append(value)
        if len(sources) != 1:
            self._refuse('exactly_one_explicit_source_required')
        source = contained(cwd / sources[0], manifest.parent)
        matches = [unit for unit in self.units if unit.manifest == manifest and unit.source == source and unit.crate == values.get('--crate-name')]
        if len(matches) != 1:
            self._refuse('crate_name_source_manifest_mismatch')
        unit = matches[0]
        types = set(values.get('--crate-type', '').split(','))
        if not types or not types <= ({'lib', 'rlib'} if unit.kind == 'lib' else {'bin'}):
            self._refuse('unexpected_crate_type')
        if digest(source) != unit.source_sha256:
            self._refuse('source_changed_since_plan')
        if not outputs:
            self._refuse('explicit_cache_output_required')
        cache = self.root / 'target' / 'debug'
        for output in outputs:
            if not (cwd / output).resolve().is_relative_to(cache):
                self._refuse('compiler_output_outside_debug_cache')
        return unit

    def authorize_build_script(self, manifest_dir, artifact):
        self._current()
        try:
            manifest = self._manifest(manifest_dir)
            artifact = contained(Path(artifact), self.root / 'target' / 'debug' / 'build')
            pin = self.script_pins.get(artifact)
            matches = [u for u in self.units if u.manifest == manifest and u.kind == 'build-script']
            if len(matches) != 1 or pin != (matches[0].package, digest(artifact)):
                self._refuse('build_script_not_pinned_for_this_package')
            if digest(matches[0].source) != matches[0].source_sha256:
                self._refuse('build_script_source_changed')
            return matches[0]
        except (OSError, ValueError, TypeError) as error:
            self._refuse(str(error))
