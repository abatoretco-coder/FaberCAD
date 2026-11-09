"""Small regression tests for CI scope and fail-closed policy; no native builds."""
import copy
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('faber_ci', ROOT / 'scripts/faber_ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class SourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ci.load_policy()

    def test_native_changes_never_generate_build_commands(self):
        result = ci.plan(['Cargo.toml', 'crates/engine/src/cmd/mod.rs'], self.policy)
        self.assertEqual(result['scope'], 'source_checks_only')
        self.assertEqual(result['native_tests'], 'not_executed')
        self.assertTrue(result['native_validation_required'])
        self.assertEqual(result['build_commands'], [])

    def test_working_tree_includes_untracked_and_tracked_changes(self):
        with patch.object(ci, 'command', side_effect=[b'a.rs\0', b'new.py\0a.rs\0']):
            self.assertEqual(ci.changed_paths(), ['a.rs', 'new.py'])

    def test_invalid_or_missing_base_cannot_produce_empty_success(self):
        for base in ['0' * 40, '--all', 'HEAD; echo bad']:
            with self.assertRaises(ValueError):
                ci.changed_paths(base)
        with patch.dict(ci.os.environ, {'FABER_FETCH_BASE': '0'}):
            with patch.object(ci, 'command', side_effect=RuntimeError('missing base')):
                with self.assertRaises(RuntimeError):
                    ci.changed_paths('a' * 40)

    def test_missing_shallow_base_fetches_only_exact_commit(self):
        with patch.dict(ci.os.environ, {'FABER_FETCH_BASE': '1'}):
            with patch.object(ci, 'command', side_effect=[RuntimeError('missing'), b'', b'', b'a.py\0']) as cmd:
                self.assertEqual(ci.changed_paths('a' * 40), ['a.py'])
                self.assertEqual(cmd.call_args_list[1].args[0],
                                 ['git', 'fetch', '--no-tags', '--depth=1', 'origin', 'a' * 40])

    def test_paths_and_change_count_are_bounded(self):
        with self.assertRaises(ValueError):
            ci.checked_file('../outside')
        with self.assertRaises(ValueError):
            ci.plan(['missing'] * (self.policy['max_changed_files'] + 1), self.policy)

    def test_structured_sources_reject_invalid_json_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ci, 'ROOT', Path(directory)):
            p = Path(directory) / 'bad.json'
            for text in ['{"a":1,"a":2}', '{"a":NaN}', '{']:
                p.write_text(text)
                with self.assertRaises(ValueError):
                    ci.validate_sources(['bad.json'], self.policy)
            p.write_text(' ' * 33)
            small = {**self.policy, 'max_file_bytes': 32}
            with self.assertRaises(ValueError):
                ci.validate_sources(['bad.json'], small)

    def test_workflow_rejects_schedules_matrices_extra_jobs_and_builds(self):
        ci.validate_workflows(self.policy)
        original = json.loads((ROOT / '.github/workflows/faber-ci.yml').read_text())
        mutations = [
            lambda w: w['on'].update(schedule=[]),
            lambda w: w['jobs'].update(native={}),
            lambda w: w['jobs']['source-checks'].update(strategy={'matrix': {'n': [1, 2]}}),
            lambda w: w.update(permissions={'contents': 'write'}),
            lambda w: w['jobs']['source-checks']['steps'][1].update(run='python scripts/faber_ci.py'),
            lambda w: w['jobs']['source-checks']['steps'][2].update(run='cargo test --workspace'),
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(ci, 'ROOT', Path(directory)):
            workflows = Path(directory) / '.github/workflows'
            workflows.mkdir(parents=True)
            for mutate in mutations:
                w = copy.deepcopy(original)
                mutate(w)
                (workflows / 'faber-ci.yml').write_text(json.dumps(w))
                with self.assertRaises(ValueError):
                    ci.validate_workflows(self.policy)
            (workflows / 'faber-ci.yml').write_text(json.dumps(original))
            (workflows / 'old.yml').write_text('{}')
            with self.assertRaises(ValueError):
                ci.validate_workflows(self.policy)

    def test_smoke_requires_existing_explicit_artifact_and_never_certifies_source(self):
        with self.assertRaises(ValueError):
            ci.artifact_smoke(None, self.policy)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'example.exe'
            binary.write_bytes(b'not executed')
            with patch.object(ci, 'command', return_value=b'') as cmd:
                result = ci.artifact_smoke(str(binary), self.policy)
            self.assertFalse(result['current_source_verified'])
            self.assertEqual(result['scope'], 'existing_artifact_only')
            self.assertEqual(len(result['sha256']), 64)
            self.assertNotIn('cargo', cmd.call_args.args[0])

    def test_missing_formatter_fails_without_install_or_build(self):
        with patch.object(ci, 'changed_paths', return_value=['xtask/src/main.rs']), \
                patch.object(ci, 'validate_workflows'), patch.object(ci, 'validate_sources'), \
                patch.object(ci, 'command', return_value=b''), patch.object(ci.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'rustfmt is missing'):
                ci.source_checks(None, self.policy)

    def test_public_worker_flag_cannot_bypass_launcher(self):
        with patch.object(ci.sys, 'argv', ['faber_ci.py', '--worker']), \
                contextlib.redirect_stderr(io.StringIO()), patch.object(ci.resource_budget, 'run_bounded') as run:
            with self.assertRaises(SystemExit) as error:
                ci.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_nonzero_exit_overwrites_even_a_premature_success_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ci, 'ROOT', Path(directory)):
            report = Path(directory) / 'target/faber-ci/report.json'
            def fail(*args, **kwargs):
                report.write_text('{"result":"source_checks_passed"}')
                return SimpleNamespace(returncode=124, timed_out=True)
            with patch.object(ci.sys, 'argv', ['faber_ci.py']), \
                    patch.object(ci.resource_budget, 'run_bounded', side_effect=fail), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ci.main(), 124)
            self.assertEqual(json.loads(report.read_text())['result'], 'failed_or_incomplete')


if __name__ == '__main__':
    unittest.main()
