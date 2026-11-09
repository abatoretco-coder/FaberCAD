"""Protect FABER's external-only assistant boundary in the desktop build graph."""
from pathlib import Path
import tomllib
import re
import unittest
import importlib.util
import json
import subprocess
import sys
import tempfile


class DesktopFeatures(unittest.TestCase):
    def test_development_plan_from_another_directory_targets_this_repository(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, '-B', str(root / 'scripts/faber_dev.py'), '--target', 'cli'],
                                       cwd=directory, text=True, capture_output=True, timeout=5, check=True)
            plan = json.loads(completed.stdout)
            manifest = Path(plan['proposed_build_argv'][plan['proposed_build_argv'].index('--manifest-path') + 1])
            self.assertTrue(manifest.is_absolute(), 'A relative manifest can target a different checkout when invoked elsewhere')
            self.assertEqual(manifest, root / 'apps/solidcraft-cli/Cargo.toml')
            self.assertEqual(Path(plan['working_directory']), root)
            self.assertEqual(plan['commands_executed'], [])
            self.assertEqual(list(Path(directory).iterdir()), [], 'Planning must not write build files in the caller directory')

    def test_reconstruction_plan_preserves_strict_owner_limits_and_blocks_execution(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location('faber_dev_limits', root / 'scripts/faber_dev.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = json.loads((root / 'scripts/ci/faber_policy.json').read_text(encoding='utf-8'))
        plan = module.plan()
        limits = plan['reconstruction_limits']
        self.assertEqual(limits['attempts'], 1)
        self.assertGreater(limits['timeout_seconds'], 0)
        self.assertLessEqual(limits['timeout_seconds'], policy['timeout_seconds'])
        self.assertLessEqual(limits['aggregate_committed_memory_mb'], policy['memory_mb'])
        self.assertLess(limits['working_set_abort_mb'], limits['aggregate_committed_memory_mb'])
        self.assertTrue(limits['working_set_is_sampled_not_a_hard_physical_ram_cap'])
        self.assertFalse(limits['automatic_retry'])
        self.assertFalse(limits['automatic_budget_increase'])
        self.assertEqual(limits['logical_processors'], 1)
        argv = plan['proposed_build_argv']
        self.assertEqual(argv[argv.index('--jobs') + 1], str(limits['cargo_jobs']))
        self.assertFalse(plan['execution_guard_status']['ready_to_execute'])
        self.assertEqual(plan['commands_executed'], [])

    def test_secondary_importers_are_optional_through_every_host(self):
        root = Path(__file__).resolve().parents[2]
        io = tomllib.loads((root / 'crates/io/Cargo.toml').read_text(encoding='utf-8'))
        self.assertEqual(io['features']['default'], [])
        for dependency in ('cadmpeg-core', 'cadmpeg-ir', 'cadmpeg-registry'):
            self.assertTrue(io['dependencies'][dependency]['optional'])
            self.assertIn('dep:' + dependency, io['features']['foreign-cad-import'])
        engine = tomllib.loads((root / 'crates/engine/Cargo.toml').read_text(encoding='utf-8'))
        self.assertIn('solidcraft-io/foreign-cad-import', engine['features']['foreign-cad-import'])
        for package in ('solidcraft', 'solidcraft-cli', 'solidcraft-web'):
            manifest = tomllib.loads((root / 'apps' / package / 'Cargo.toml').read_text(encoding='utf-8'))
            self.assertIn('solidcraft-engine/foreign-cad-import', manifest['features']['foreign-cad-import'])
            enabled = set()
            pending = list(manifest['features'].get('default', []))
            while pending:
                feature = pending.pop()
                if feature not in enabled:
                    enabled.add(feature)
                    pending.extend(manifest['features'].get(feature, []))
            self.assertNotIn('foreign-cad-import', enabled)
            self.assertNotIn('solidcraft-engine/foreign-cad-import', enabled)

    def test_development_plans_are_scoped_offline_and_do_not_execute_builds(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location('faber_dev_plan', root / 'scripts/faber_dev.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for target in ('desktop', 'cli'):
            for foreign in (False, True):
                plan = module.plan(target, foreign)
                self.assertEqual(plan['scope'], 'plan_only')
                self.assertEqual(plan['commands_executed'], [])
                self.assertEqual(plan['native_validation'], 'not_executed')
                self.assertFalse(plan['cpu_raytracing'])
                argv = plan['proposed_build_argv']
                self.assertIn('--no-default-features', argv)
                self.assertIn('--offline', argv)
                self.assertIn('--locked', argv)
                self.assertNotIn('--workspace', argv)
                self.assertNotIn('--all-features', argv)
                self.assertEqual(plan['features'], ['profile'] + (['foreign-cad-import'] if foreign else []))
                manifest = tomllib.loads((root / f'apps/{plan["package"]}/Cargo.toml').read_text(encoding='utf-8'))
                expanded = set()
                pending = list(plan['features'])
                while pending:
                    feature = pending.pop()
                    if feature not in expanded:
                        expanded.add(feature)
                        pending.extend(manifest['features'].get(feature, []))
                self.assertNotIn('raytrace-cpu', expanded)
                self.assertNotIn('solidcraft-engine/raytrace-cpu', expanded)
                self.assertNotIn('bundled-render-library', expanded)
                self.assertNotIn('legacy-embedded-assistant', expanded)

    def test_default_build_cannot_enable_legacy_credentials_indirectly(self):
        root = Path(__file__).resolve().parents[2]
        manifest = tomllib.loads((root / 'apps/solidcraft/Cargo.toml').read_text(encoding='utf-8'))
        features = manifest['features']
        pending = list(features.get('default', []))
        enabled = set()
        while pending:
            feature = pending.pop()
            if feature not in enabled:
                enabled.add(feature)
                pending.extend(features.get(feature, []))
        self.assertNotIn('legacy-embedded-assistant', enabled)
        self.assertNotIn('dep:keyring', enabled)
        self.assertTrue(manifest['dependencies']['keyring']['optional'])
        self.assertIn('dep:keyring', features['legacy-embedded-assistant'])

    def test_ui_assistant_is_an_explicit_opt_in(self):
        root = Path(__file__).resolve().parents[2]
        ui = tomllib.loads((root / 'crates/ui-egui/Cargo.toml').read_text(encoding='utf-8'))
        desktop = tomllib.loads((root / 'apps/solidcraft/Cargo.toml').read_text(encoding='utf-8'))
        self.assertEqual(ui['features']['default'], [])
        self.assertIn('legacy-embedded-assistant', ui['features'])
        self.assertIn('solidcraft-ui-egui/legacy-embedded-assistant', desktop['features']['legacy-embedded-assistant'])

    def test_chat_implementation_is_compile_gated_instead_of_only_hidden(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / 'crates/ui-egui/src/lib.rs').read_text(encoding='utf-8')
        for module in ('agent_chat', 'ai_connect'):
            self.assertRegex(source, re.escape('#[cfg(any(test, feature = "legacy-embedded-assistant"))]')
                             + r'\s+pub mod ' + module + r';')
        data = (root / 'crates/ui-egui/src/agent_preferences.rs').read_text(encoding='utf-8')
        self.assertNotIn('agent_chat::', data)
        self.assertNotIn('std::process::', data)
        self.assertNotIn('std::net::', data)


if __name__ == '__main__':
    unittest.main()
