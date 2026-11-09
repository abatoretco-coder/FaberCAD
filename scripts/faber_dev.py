"""Describe FABER's development feature selection; never build or launch anything."""
import argparse
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {'desktop': 'solidcraft', 'cli': 'solidcraft-cli'}


def plan(target='desktop', foreign_imports=False):
    package = PACKAGES[target]
    manifest_path = f'apps/{package}/Cargo.toml'
    manifest = tomllib.loads((ROOT / manifest_path).read_text(encoding='utf-8'))
    features = ['profile']
    if foreign_imports:
        features.append('foreign-cad-import')
    if manifest['package']['name'] != package or any(f not in manifest['features'] for f in features):
        raise ValueError('Development selection no longer matches the package manifest')
    return {
        'scope': 'plan_only',
        'package': package,
        'working_directory': str(ROOT),
        'default_features': False,
        'features': features,
        'cpu_raytracing': False,
        'foreign_cad_import': foreign_imports,
        'commands_executed': [],
        'native_validation': 'not_executed',
        'future_build_requires_separate_owner_authorization_and_resource_guard': True,
        'reconstruction_limits': {
            'attempts': 1,
            'timeout_seconds': 120,
            'aggregate_committed_memory_mb': 1024,
            'working_set_abort_mb': 768,
            'working_set_sample_interval_ms': 100,
            'working_set_is_sampled_not_a_hard_physical_ram_cap': True,
            'logical_processors': 1,
            'cargo_jobs': 1,
            'minimum_available_physical_memory_mb': 4096,
            'minimum_available_system_commit_mb': 2048,
            'automatic_retry': False,
            'automatic_budget_increase': False,
        },
        'execution_guard_status': {
            'aggregate_commit_and_deadline': 'existing_windows_job_guard',
            'cpu_affinity': 'implemented_and_synthetic_tests_passed',
            'working_set_and_system_headroom_watchdog': 'implemented_and_synthetic_tests_passed',
            'dependency_compile_allowlist': 'policy_implemented_and_fake_process_tests_passed',
            'cargo_request_interception': 'windows_adapter_implemented_fake_compilers_and_cached_scripts_qualified',
            'real_cargo_protocol': 'temporary_workspace_and_fake_compiler_qualified',
            'real_compilation_authorized': False,
            'ready_to_execute': False,
        },
        'proposed_build_argv': ['cargo', 'build', '--manifest-path', str(ROOT / manifest_path),
                                '--package', package, '--bin', package, '--offline', '--locked',
                                '--jobs', '1', '--no-default-features', '--features', ','.join(features)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=PACKAGES, default='desktop')
    parser.add_argument('--foreign-imports', action='store_true', help='Describe the optional secondary-decoder selection')
    args = parser.parse_args()
    print(json.dumps(plan(args.target, args.foreign_imports), indent=2))


if __name__ == '__main__':
    main()
