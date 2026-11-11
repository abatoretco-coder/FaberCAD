"""Explicit small native catalogue smoke using an existing CLI; never build."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/ci'))
import resource_budget as budget

spec = importlib.util.spec_from_file_location('faber_catalog', ROOT/'scripts/faber_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def main():
    output = ROOT/'target/furniture-catalogue'
    output.mkdir(parents=True, exist_ok=True)
    cli = ROOT/'target/debug/solidcraft-cli.exe'
    if not cli.is_file():
        raise SystemExit('Existing CLI required; no build or installation fallback')
    data = catalog.load_catalogue()
    ids = ['pine-1200x300x18', 'socket_head_cap_screw-m4x20', 'hex_nut-m6', 'washer-m6',
           'wood-dowel-8x30', 'wood-screw-4x25', 'shelf-pin-5x16', 'angle-bracket-40',
           'butt-hinge-60x40', 'drawer-slide-350', 'foot-pad-40']
    commands = [dict(command='file.new', params=dict(name='FABER catalogue smoke; disposable'))]
    for identifier in ids:
        commands.extend(catalog.recipe(data, identifier)['commands'])
    for joint, value in [('butt-hinge-60x40 motion', 45), ('drawer-slide-350 motion', 100),
                         ('butt-hinge-60x40 motion', 0), ('drawer-slide-350 motion', 0)]:
        commands.append(dict(command='joint.drive', params=dict(joint=joint, value=value, quiet=True)))
    commands.extend([dict(command='assembly.bom', params=dict(path=str(output/'bom.json')))])
    script = output/'smoke.json'
    script.write_text(json.dumps(dict(commands=commands), indent=2), encoding='utf-8')
    guard = budget.WindowsWatchdog(192, 4096, 2048, 50)
    receipt_path = output/'receipt.json'
    receipt_path.write_text(json.dumps(dict(result='not_started', real_compilation=False)), encoding='utf-8')
    with cli.open('rb') as stream:
        cli_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    try:
        result = budget.run_bounded([str(cli), 'run', str(script), '--save', str(output/'catalogue.sc'),
                                    '--json-out', str(output/'measurements.json')], ROOT, 30, 256, watchdog=guard)
    except budget.BudgetSetupError as error:
        (output/'receipt.json').write_text(json.dumps(dict(result='not_started', reason=str(error),
            real_compilation=False, cli_sha256=cli_hash), indent=2), encoding='utf-8')
        raise SystemExit(str(error))
    receipt = dict(resources=asdict(result), cli_sha256=cli_hash,
                   real_compilation=False, checked_ids=ids, result='failed')
    try:
        if result.returncode == 0:
            measured = json.loads((output/'measurements.json').read_text())
            assert len(measured['bodies']) == 13, measured
            assert all(b['closed'] and b['volume_mm3'] > 0 for b in measured['bodies']), measured
            bom = json.loads((output/'bom.json').read_text())
            assert bom['total_occurrences'] == 13, bom
            receipt.update(result='passed', closed_bodies=13, bom_occurrences=13,
                           sc_sha256=hashlib.sha256((output/'catalogue.sc').read_bytes()).hexdigest())
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
