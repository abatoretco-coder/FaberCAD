"""Authorization regressions and fake compiler processes; never invoke Cargo/rustc."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CI_SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts/ci'
sys.path.insert(0, str(CI_SCRIPTS))
import rebuild_policy as policy
import resource_budget as budget


class RebuildPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='faber-policy-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root/'Cargo.toml').write_text('[workspace]\n')
        (self.root/'Cargo.lock').write_text('# synthetic lock, no dependency resolution\n')
        for package, relative in policy.ALLOWED_PACKAGES.items():
            folder = self.root/relative
            (folder/'src').mkdir(parents=True)
            (folder/'Cargo.toml').write_text(f'[package]\nname="{package}"\nversion="0.1.0"\n')
            (folder/'src'/('main.rs' if package == 'solidcraft' else 'lib.rs')).write_text('// placeholder; never compiled\n')
            (folder/'build.rs').write_text('// placeholder build script; never compiled\n')
        self.external = self.root/'external/solidcore'
        (self.external/'src').mkdir(parents=True)
        (self.external/'Cargo.toml').write_text('[package]\nname="solidcore"\nversion="0.1.0"\n')
        (self.external/'src/lib.rs').write_text('// forbidden placeholder\n')

    def request(self, package='solidcraft-io', build=False):
        folder = self.root/policy.ALLOWED_PACKAGES[package]
        source = 'build.rs' if build else ('src/main.rs' if package == 'solidcraft' else 'src/lib.rs')
        return dict(manifest_dir=str(folder), cwd=str(folder), argv=[
            '--crate-name', 'build_script_build' if build else package.replace('-', '_'),
            '--crate-type', 'bin' if build or package == 'solidcraft' else 'lib', source,
            '--edition=2024', '--emit=dep-info,link', '--out-dir', str(self.root/'target/debug/deps')])

    def test_only_exact_local_packages_and_entry_points_are_allowed(self):
        guard = policy.RebuildPolicy(self.root)
        for package in policy.ALLOWED_PACKAGES:
            for build in (False, True):
                with self.subTest(package=package, build=build):
                    unit = guard.authorize_compile(**self.request(package, build))
                    self.assertEqual(unit.package, package)
                    self.assertEqual(unit.kind, 'build-script' if build else ('bin' if package == 'solidcraft' else 'lib'))

    def test_external_package_cannot_claim_an_allowed_crate_name(self):
        request = self.request()
        request['manifest_dir'] = request['cwd'] = str(self.external)
        with self.assertRaisesRegex(policy.RebuildDenied, 'package_not_allowed'):
            policy.RebuildPolicy(self.root).authorize_compile(**request)

    def test_source_substitution_path_escape_and_extra_sources_are_refused(self):
        for source in (str(self.external/'src/lib.rs'), '../../render/src/lib.rs', '-'):
            request = self.request()
            request['argv'][4] = source
            with self.subTest(source=source), self.assertRaises(policy.RebuildDenied):
                policy.RebuildPolicy(self.root).authorize_compile(**request)
        request = self.request()
        request['argv'].append('src/another.rs')
        with self.assertRaisesRegex(policy.RebuildDenied, 'exactly_one_explicit_source'):
            policy.RebuildPolicy(self.root).authorize_compile(**request)

    def test_hidden_identity_features_tests_and_unknown_flags_are_refused(self):
        extras = [['@hidden.rsp'], ['--crate-name', 'solidcraft_io'], ['--test'], ['--cfg', 'test'],
                  ['--cfg', 'feature="raytrace-cpu"'], ['--cfg', ' feature="foreign-cad-import" '],
                  ['--cfg', 'feature="solver-profiling"'], ['--cfg', 'feature="legacy-embedded-assistant"'],
                  ['--cfg', 'r#test'], ['--cfg', 'r#feature="raytrace-cpu"'], ['--cfg', 'unknown_cfg'],
                  ['--emit=link=outside.exe'], ['--target', 'wasm32-unknown-unknown'], ['--unknown'], ['--crate-type=proc-macro']]
        for extra in extras:
            request = self.request()
            request['argv'].extend(extra)
            with self.subTest(extra=extra), self.assertRaises(policy.RebuildDenied):
                policy.RebuildPolicy(self.root).authorize_compile(**request)

    def test_output_cannot_replace_reviewed_executable(self):
        for output in (self.root/'target/workshop/faber-atelier-reviewed.exe', self.root/'elsewhere'):
            request = self.request()
            request['argv'][-1] = str(output)
            with self.subTest(output=output), self.assertRaisesRegex(policy.RebuildDenied, 'output_outside_debug_cache'):
                policy.RebuildPolicy(self.root).authorize_compile(**request)

    def test_manifest_lockfile_or_source_changes_refuse_the_attempt(self):
        for relative in ('Cargo.lock', 'Cargo.toml', 'crates/io/Cargo.toml', 'crates/io/src/lib.rs'):
            path = self.root/relative
            original = path.read_bytes()
            guard = policy.RebuildPolicy(self.root)
            path.write_bytes(original+b'\n// changed after planning')
            with self.subTest(path=relative), self.assertRaises(policy.RebuildDenied):
                guard.authorize_compile(**self.request())
            path.write_bytes(original)

    def test_a_denial_latches_and_blocks_later_allowed_requests(self):
        guard = policy.RebuildPolicy(self.root)
        request = self.request()
        request['argv'].append('--test')
        with self.assertRaises(policy.RebuildDenied):
            guard.authorize_compile(**request)
        with self.assertRaisesRegex(policy.RebuildDenied, 'attempt_already_denied'):
            guard.authorize_compile(**self.request('solidcraft-engine'))

    def test_cached_build_scripts_need_package_bound_frozen_artifact_hashes(self):
        artifact = self.root/'target/debug/build/solidcraft-io-fake/build-script-build.exe'
        artifact.parent.mkdir(parents=True)
        artifact.write_text('inert artifact bytes, not an executable')
        request = dict(manifest_dir=self.request()['manifest_dir'], artifact=artifact)
        with self.assertRaisesRegex(policy.RebuildDenied, 'not_pinned'):
            policy.RebuildPolicy(self.root).authorize_build_script(**request)
        pins = {str(artifact): ('solidcraft-io', policy.digest(artifact))}
        guard = policy.RebuildPolicy(self.root, pins)
        self.assertEqual(guard.authorize_build_script(**request).package, 'solidcraft-io')
        with self.assertRaises(policy.RebuildDenied):
            policy.RebuildPolicy(self.root, pins).authorize_build_script(self.request('solidcraft-engine')['manifest_dir'], artifact)
        artifact.write_text('changed artifact')
        with self.assertRaises(policy.RebuildDenied):
            guard.authorize_build_script(**request)
        with self.assertRaisesRegex(policy.RebuildDenied, 'package_not_allowed'):
            policy.RebuildPolicy(self.root).authorize_build_script(self.external, artifact)

    def test_symlinked_source_cannot_escape_its_package(self):
        source = self.root/'crates/io/src/lib.rs'
        source.unlink()
        try:
            source.symlink_to(self.external/'src/lib.rs')
        except OSError:
            self.skipTest('Symlink creation requires unavailable Windows privileges')
        with self.assertRaisesRegex(policy.RebuildDenied, 'path_outside_authorized_directory'):
            policy.RebuildPolicy(self.root)

    def fake_process_requests(self, requests):
        request_file = self.root/'requests.json'
        request_file.write_text(json.dumps(requests))
        # The fake compiler is fixed Python code. No caller-supplied executable,
        # real compiler, Cargo or Rust source is ever executed by this harness.
        worker = """import sys,json,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from rebuild_policy import RebuildPolicy,RebuildDenied
root=Path(sys.argv[2]);guard=RebuildPolicy(root);denied=False
for index,request in enumerate(json.loads((root/'requests.json').read_text())):
 try:
  kind=request.pop('kind','compile')
  if kind=='build-script':guard.authorize_build_script(**request)
  else:guard.authorize_compile(**request)
 except RebuildDenied:denied=True;continue
 marker=root/('fake-compiler-'+str(index))
 subprocess.run([sys.executable,'-c','import sys;from pathlib import Path;Path(sys.argv[1]).write_text("fake invocation")',str(marker)],check=True)
sys.exit(125 if denied else 0)
"""
        watchdog = budget.WindowsWatchdog(96, 0, 0, 20) if sys.platform == 'win32' else None
        outcome = budget.run_bounded([sys.executable, '-B', '-c', worker, str(CI_SCRIPTS), str(self.root)],
                                     self.root, timeout_seconds=5, memory_mb=192, watchdog=watchdog)
        if watchdog:
            self.assertTrue(outcome.cleanup_verified)
        return outcome

    def test_fake_compiler_process_is_not_started_after_a_denied_request(self):
        requests = [self.request(), self.request('solidcraft-engine'), self.request('solidcraft-render')]
        requests[1]['manifest_dir'] = requests[1]['cwd'] = str(self.external)
        outcome = self.fake_process_requests(requests)
        self.assertEqual(outcome.returncode, 125)
        self.assertTrue((self.root/'fake-compiler-0').is_file())
        self.assertFalse((self.root/'fake-compiler-1').exists())
        self.assertFalse((self.root/'fake-compiler-2').exists(), 'Refusal must stop subsequent local work too')

    def test_cached_external_script_process_is_refused_before_execution(self):
        artifact = self.root/'target/debug/build/solidcore-fake/build-script-build.exe'
        artifact.parent.mkdir(parents=True)
        artifact.write_text('inert stand-in for a cached executable; never executed')
        outcome = self.fake_process_requests([dict(kind='build-script', manifest_dir=str(self.external), artifact=str(artifact))])
        self.assertEqual(outcome.returncode, 125)
        self.assertFalse((self.root/'fake-compiler-0').exists(), 'Cached executable execution needs its own authorization gate')


if __name__ == '__main__':
    unittest.main()
