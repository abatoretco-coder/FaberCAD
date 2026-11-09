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
        'proposed_build_argv': ['cargo', 'build', '--manifest-path', str(ROOT / manifest_path),
                                '--package', package, '--bin', package, '--offline', '--locked',
                                '--no-default-features', '--features', ','.join(features)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=PACKAGES, default='desktop')
    parser.add_argument('--foreign-imports', action='store_true', help='Describe the optional secondary-decoder selection')
    args = parser.parse_args()
    print(json.dumps(plan(args.target, args.foreign_imports), indent=2))


if __name__ == '__main__':
    main()
