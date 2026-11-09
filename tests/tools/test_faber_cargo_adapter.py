"""Real Windows process interception with fake Cargo/compiler/script payloads."""
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile
from unittest import mock

CI_SCRIPTS = Path(__file__).resolve().parents[2]/'scripts/ci'
sys.path.insert(0, str(CI_SCRIPTS))
import cargo_adapter as adapter
import resource_budget as budget
import test_faber_rebuild_policy as fixtures


@unittest.skipUnless(sys.platform == 'win32', 'Windows debug-event interception')
class CargoAdapterTests(unittest.TestCase):
    def setUp(self):
        fixtures.RebuildPolicyTests.setUp(self)
        self.compiler = self.root/'fake-compiler.py'
        self.compiler.write_text("import os;from pathlib import Path;Path(os.environ['FABER_FAKE_MARKER']).write_text('fake compiler ran')")
        self.cargo = self.root/'fake-cargo.py'
        self.cargo.write_text('''import json,os,subprocess
from pathlib import Path
root=Path.cwd()
for request in json.loads((root/'requests.json').read_text()):
 env=os.environ.copy()
 env.update(request['env'])
 subprocess.run(request['command'],cwd=request['cwd'],env=env,check=True)
''')
        self.config = dict(root=str(self.root), synthetic=True,
                           cargo=adapter.pin_program([sys.executable, '-I', '-S', str(self.cargo)]),
                           compiler=adapter.pin_program([sys.executable, '-I', '-S', str(self.compiler)]),
                           receipt=str(self.root/'target/receipt.json'))

    def compile_request(self, package='solidcraft-io', marker='compiler-ran'):
        request = fixtures.RebuildPolicyTests.request(self, package)
        return dict(command=[*self.config['compiler']['command'], *request['argv']], cwd=request['cwd'],
                    env=dict(CARGO_MANIFEST_DIR=request['manifest_dir'], CARGO_PKG_NAME=package,
                             FABER_FAKE_MARKER=str(self.root/marker)))

    def run_requests(self, requests):
        (self.root/'requests.json').write_text(json.dumps(requests))
        outcome = adapter.run_guarded(self.config, timeout_seconds=5, memory_mb=192,
                                      watchdog=budget.WindowsWatchdog(128, 0, 0, 20))
        receipt = json.loads((self.root/'target/receipt.json').read_text())
        self.assertTrue(outcome.cleanup_verified, outcome)
        self.assertTrue(receipt['resources']['cleanup_verified'])
        self.assertEqual(receipt['resources']['cpu_affinity_mask'].bit_count(), 1)
        return outcome, receipt

    def test_local_compiler_runs_only_after_create_event_authorization(self):
        outcome, receipt = self.run_requests([self.compile_request()])
        self.assertEqual(outcome.returncode, 0, receipt)
        self.assertTrue((self.root/'compiler-ran').is_file())
        self.assertEqual([r['role'] for r in receipt['events']], ['cargo', 'compiler'])

    def test_external_compiler_request_is_stopped_before_its_first_instruction(self):
        forbidden = self.compile_request(marker='forbidden-ran')
        forbidden['env'].update(CARGO_MANIFEST_DIR=str(self.external), CARGO_PKG_NAME='solidcore')
        outcome, receipt = self.run_requests([self.compile_request(), forbidden, self.compile_request(marker='later-ran')])
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertTrue((self.root/'compiler-ran').exists())
        self.assertFalse((self.root/'forbidden-ran').exists())
        self.assertFalse((self.root/'later-ran').exists())
        self.assertEqual(receipt['events'][-1]['decision'], 'denied_before_user_code')
        self.assertIn('package_not_allowed', receipt['events'][-1]['reason'])

    def script_request(self, external=False, pinned=False, spawn_rogue=False):
        script = self.root/'target/debug/build/fake-local/cached-script.py'
        script.parent.mkdir(parents=True, exist_ok=True)
        marker = self.root/'script-ran'
        code = f"from pathlib import Path;Path({str(marker)!r}).write_text('script ran')"
        if spawn_rogue:
            code += (f";import subprocess,sys;subprocess.run([sys.executable,'-c',"
                     f"{('from pathlib import Path;Path('+repr(str(self.root/'rogue-ran'))+').touch()')!r}],check=True)")
        script.write_text(code)
        tool = adapter.pin_program([sys.executable, '-I', '-S', str(script)])
        self.config['script_launchers'] = [dict(program=tool, artifact=str(script))]
        if pinned:
            self.config['build_script_pins'] = {str(script): ['solidcraft-io', adapter.digest(script)]}
        return dict(command=tool['command'], cwd=str(self.root),
                    env=dict(CARGO_MANIFEST_DIR=str(self.external if external else self.root/'crates/io'),
                             CARGO_PKG_NAME='solidcore' if external else 'solidcraft-io'))

    def test_cached_script_without_a_compiler_call_is_intercepted(self):
        outcome, receipt = self.run_requests([self.script_request(external=True)])
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertFalse((self.root/'script-ran').exists())
        self.assertIn('package_not_allowed', receipt['events'][-1]['reason'])

    def test_local_cached_script_requires_a_pin_and_runs_after_authorization(self):
        outcome, receipt = self.run_requests([self.script_request(pinned=True)])
        self.assertEqual(outcome.returncode, 0, receipt)
        self.assertTrue((self.root/'script-ran').exists())
        self.assertEqual([r['role'] for r in receipt['events']], ['cargo', 'build-script'])

    def test_unpinned_local_cached_script_cannot_start(self):
        outcome, receipt = self.run_requests([self.script_request()])
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertFalse((self.root/'script-ran').exists())
        self.assertIn('not_pinned', receipt['events'][-1]['reason'])

    def test_build_script_child_cannot_bypass_the_gate(self):
        outcome, receipt = self.run_requests([self.script_request(pinned=True, spawn_rogue=True)])
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertTrue((self.root/'script-ran').exists())
        self.assertFalse((self.root/'rogue-ran').exists())
        self.assertEqual(receipt['events'][-1]['reason'], 'unapproved_child_executable')

    def test_a_new_shell_or_wrapper_is_not_trusted_by_process_name(self):
        marker = self.root/'unapproved-ran'
        request = dict(command=[sys.executable, '-c', f"from pathlib import Path;Path({str(marker)!r}).touch()"],
                       cwd=str(self.root), env={})
        outcome, receipt = self.run_requests([request])
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertFalse(marker.exists())

    def test_pinned_tool_change_refuses_before_process_creation(self):
        self.compiler.write_text('changed after pinning')
        with mock.patch.object(adapter.budget, 'run_bounded') as launch:
            with self.assertRaisesRegex(ValueError, 'pinned_tool_changed'):
                adapter.run_guarded(self.config)
            launch.assert_not_called()

    def test_real_tools_require_explicit_owner_authorization(self):
        self.config['synthetic'] = False
        with mock.patch.object(adapter.budget, 'run_bounded') as launch:
            with self.assertRaisesRegex(ValueError, 'owner authorization'):
                adapter.run_guarded(self.config)
            launch.assert_not_called()

    def test_real_tools_cannot_relax_watchdog_headroom(self):
        self.config['synthetic'] = False
        with mock.patch.object(adapter.budget, 'run_bounded') as launch:
            with self.assertRaisesRegex(ValueError, 'cannot relax'):
                adapter.run_guarded(self.config, owner_authorized=True,
                                    watchdog=budget.WindowsWatchdog(768, 0, 0, 20))
            launch.assert_not_called()

    def run_installed_cargo(self, external=False):
        cargo = Path.home()/'.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin/cargo.exe'
        launcher = Path(sys.executable).parent/'Lib/site-packages/pip/_vendor/distlib/t64.exe'
        if not cargo.is_file() or not launcher.is_file():
            self.skipTest('Installed Cargo and prebuilt Python console launcher required; never install them')
        # Only this temporary workspace is resolved. No FABER dependency graph.
        (self.root/'Cargo.toml').write_text('[workspace]\nmembers=["apps/solidcraft","crates/io"]\nresolver="3"\n')
        (self.root/'apps/solidcraft/Cargo.toml').write_text(
            '[package]\nname="solidcraft"\nversion="0.1.0"\nedition="2024"\n'
            '[dependencies]\nsolidcraft-io={path="../../crates/io"}\n[features]\nprofile=[]\n')
        (self.root/'crates/io/Cargo.toml').write_text('[package]\nname="solidcraft-io"\nversion="0.1.0"\nedition="2024"\n')
        (self.root/'Cargo.lock').write_text('version = 4\n[[package]]\nname="solidcraft"\nversion="0.1.0"\n'
                                          'dependencies=["solidcraft-io"]\n[[package]]\nname="solidcraft-io"\nversion="0.1.0"\n')
        if external:
            manifest = self.root/'apps/solidcraft/Cargo.toml'
            manifest.write_text(manifest.read_text().replace('[dependencies]',
                '[dependencies]\nsolidcore={path="../../external/solidcore"}'))
            lock = self.root/'Cargo.lock'
            lock.write_text(lock.read_text().replace('dependencies=["solidcraft-io"]',
                'dependencies=["solidcraft-io","solidcore"]')+'\n[[package]]\nname="solidcore"\nversion="0.1.0"\n')
            workspace = self.root/'Cargo.toml'
            workspace.write_text(workspace.read_text().replace('"crates/io"]', '"crates/io","external/solidcore"]'))
        for relative in ('apps/solidcraft/build.rs', 'crates/io/build.rs'):
            (self.root/relative).unlink()
        compiler = self.root/'fake-rustc.exe'
        # Append a Python zip payload to a prebuilt launcher, without compilation.
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('__main__.py', (Path(__file__).parent/'fake_rustc_payload.py').read_text())
        compiler.write_bytes(launcher.read_bytes()+f'#!"{sys.executable}"\n'.encode('utf-8')+payload.getvalue())
        (self.root/'fake-sysroot/lib/rustlib/x86_64-pc-windows-msvc/lib').mkdir(parents=True)
        self.config.update(cargo=adapter.pin_program([str(cargo)]), compiler=adapter.pin_program([str(compiler)]),
                           compiler_interpreters=[adapter.pin_program([sys.executable, str(compiler)])])
        outcome = adapter.run_guarded(self.config, timeout_seconds=10, memory_mb=192,
                                      watchdog=budget.WindowsWatchdog(192, 0, 0, 20))
        receipt = json.loads((self.root/'target/receipt.json').read_text())
        self.assertTrue(outcome.cleanup_verified, outcome)
        requests = [json.loads(line) for line in (self.root/'fake-rustc-invocations.jsonl').read_text().splitlines()]
        return outcome, receipt, requests

    def test_installed_cargo_protocol_with_fake_native_compiler_only(self):
        outcome, receipt, requests = self.run_installed_cargo()
        self.assertEqual(outcome.returncode, 0, receipt)
        compiled = [args[args.index('--crate-name')+1] for args in requests if '--out-dir' in args]
        self.assertCountEqual(compiled, ['solidcraft_io', 'solidcraft'])
        self.assertIn('compiler-probe', [event.get('role') for event in receipt['events']])
        self.assertIn('not compiled', (self.root/'target/debug/solidcraft.exe').read_text())

    def test_installed_cargo_external_dependency_denied_before_fake_compiler(self):
        outcome, receipt, requests = self.run_installed_cargo(external=True)
        self.assertEqual(outcome.returncode, 125, receipt)
        self.assertIn('package_not_allowed', receipt['events'][-1]['reason'])
        compiled = [args[args.index('--crate-name')+1] for args in requests if '--out-dir' in args]
        self.assertNotIn('solidcore', compiled)
        self.assertFalse((self.root/'target/debug/solidcraft.exe').exists())


class CargoAdapterContractTests(unittest.TestCase):
    def test_read_only_probe_cannot_hide_compilation_or_features(self):
        probe = ['-', '--crate-name', '___', '--print=file-names', '--crate-type', 'bin',
                 '--print=sysroot', '--print=cfg', '-Wwarnings']
        self.assertTrue(adapter.read_only_probe(probe))
        for extra in (['--emit=link'], ['source.rs'], ['--cfg', 'test'], ['--extern', 'malicious=x'],
                      ['@hidden.rsp'], ['--out-dir', 'target/debug'], ['-C', 'linker=rogue']):
            with self.subTest(extra=extra):
                self.assertFalse(adapter.read_only_probe([*probe, *extra]))

    def test_attempt_environment_removes_compiler_and_wrapper_overrides(self):
        inherited = dict(RUSTC='rogue.exe', RUSTC_WRAPPER='rogue.exe', RUSTDOC='rogue.exe',
                         RUSTFLAGS='--cfg test', CARGO_ENCODED_RUSTFLAGS='rogue', CARGO_BUILD_JOBS='99',
                         CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUNNER='rogue', RUSTUP_TOOLCHAIN='rogue',
                         SystemRoot='C:\\Windows')
        with mock.patch.dict(adapter.os.environ, inherited, clear=True):
            env = adapter.sanitized_environment(dict(root='fixture', compiler=dict(command=['pinned.exe'])))
        self.assertEqual(env['RUSTC'], 'pinned.exe')
        self.assertEqual(env['RUSTC_WRAPPER'], '')
        self.assertEqual(env['CARGO_BUILD_JOBS'], '1')
        self.assertEqual(env['CARGO_NET_OFFLINE'], 'true')
        for key in ('RUSTFLAGS', 'RUSTDOC', 'CARGO_ENCODED_RUSTFLAGS',
                    'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUNNER', 'RUSTUP_TOOLCHAIN'):
            self.assertNotIn(key, env)

    def test_unsupported_platform_has_no_process_or_configuration_fallback(self):
        with mock.patch.object(adapter.sys, 'platform', 'linux'), mock.patch.object(adapter.budget, 'run_bounded') as launch:
            with self.assertRaisesRegex(budget.BudgetSetupError, 'Windows-only'):
                adapter.run_guarded(dict(synthetic=True))
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
