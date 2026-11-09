"""Exercise actual MCP tools. --connect only reads the dedicated app's PLA fixture."""
import argparse
import json
import math
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connect', type=int)
    parser.add_argument('--body', default='PLA test plate PLA')
    parser.add_argument('--cli', type=Path, default=Path('target/debug/solidcraft-cli.exe'))
    parser.add_argument('--output', type=Path, default=Path('target/workshop'))
    parser.add_argument('--design-reference', action='store_true', help='Expanded reference recipe through existing commands; not new-handler qualification')
    args = parser.parse_args()
    if args.design_reference and args.connect:
        parser.error('--design-reference is headless only; it must not replace a user document')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [str(args.cli.resolve()), 'mcp', '--compact', '--allow-path', str(output)]
    command += ['--connect', f'127.0.0.1:{args.connect}'] if args.connect else ['--headless']
    records = []
    with open(output / 'mcp-stderr.log', 'w', encoding='utf-8') as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8')
        def request(method, params):
            number = len(records) + 1
            process.stdin.write(json.dumps(dict(jsonrpc='2.0', id=number, method=method, params=params)) + '\n')
            process.stdin.flush()
            while True:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError('MCP server stopped')
                reply = json.loads(line)
                if reply.get('id') == number:
                    assert 'error' not in reply, reply
                    records.append(dict(method=method, params=params, result=reply['result']))
                    return reply['result']
        def tool(name, arguments, error=False):
            result = request('tools/call', dict(name=name, arguments=arguments))
            assert bool(result.get('isError')) == error, result
            if error:
                return result
            return json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
        def execute(command, params, error=False):
            return tool('execute', dict(command=command, params=params), error)
        try:
            request('initialize', dict(protocolVersion='2025-06-18', capabilities={}, clientInfo=dict(name='FABER workshop qualification', version='1')))
            process.stdin.write(json.dumps(dict(jsonrpc='2.0', method='notifications/initialized')) + '\n')
            process.stdin.flush()
            catalogue = execute('workshop.library', {})
            assert len(catalogue['materials']) == 11 and len(catalogue['boards']) == 5
            assert len(catalogue['hardware']['families']) >= 12
            if args.design_reference:
                recipe = json.loads(Path(__file__).with_name('design-reference.json').read_text(encoding='utf-8'))
                built = tool('batch', dict(commands=recipe['commands'], verbose=False, expect=dict(bodies=6)))
                assert built['ok'] is True
                expected = 300 * 100 * 18 - 2 * math.pi * 3.1 ** 2 * 8
                measured = execute('inspect.measure', dict(bodies=['Lower', 'Upper']))
                assert all(b['closed'] and abs(b['volume_mm3'] - expected) < 0.001
                           and b['material'] == 'Workshop Pine' for b in measured['bodies'])
                execute('solid.scale', dict(bodies=['Lower'], factors=[1.2, 1, 1], origin=[0, 0, 0]))
                enlarged = execute('inspect.measure', dict(bodies=['Lower']))['bodies'][0]['bbox']
                assert abs(enlarged['max'][0] - enlarged['min'][0] - 360) < 1e-6
                tool('undo', {})
                restored = execute('inspect.measure', dict(bodies=['Lower']))['bodies'][0]['bbox']
                assert abs(restored['max'][0] - restored['min'][0] - 300) < 1e-6
                for joint, value in [('Hinge motion', 45), ('Slide motion', 120)]:
                    moved = execute('joint.drive', dict(joint=joint, value=value, quiet=True))
                    assert moved['moved'] and not moved['conflicts'] and not moved['errors']
                    assert abs(moved['values'][0]['value'] - value) < 1e-6
                slide = execute('inspect.measure', dict(bodies=['Slide moving']))['bodies'][0]['bbox']
                assert abs(slide['min'][0] - 120) < 1e-6
                for joint in ['Hinge motion', 'Slide motion']:
                    execute('joint.drive', dict(joint=joint, value=0, quiet=True))
                assert execute('assembly.bom', {})['total_occurrences'] == 6
                design = output / 'wood-furniture-reference.sc'
                tool('save', dict(path=str(design)))
                tool('open', dict(path=str(design)))
                assert execute('assembly.bom', {})['total_occurrences'] == 6
                tool('new_design', {})
                plate = execute('print.part', dict(name='Reference PLA', template='mounting_plate',
                    length_mm=60, width_mm=30, thickness_mm=6, hole_diameter_mm=4.5))
                preflight = execute('print.check', dict(bodies=[plate['body']]))
                assert preflight['ready_for_slicer'] is True and preflight['printable'] is None
                tool('save', dict(path=str(output / 'pla-reference.sc')))
                tool('export', dict(path=str(output / 'pla-reference.3mf'), bodies=[plate['body']]))
                destination = output / 'mcp-reference.json'
                destination.write_text(json.dumps(records, indent=2), encoding='utf-8')
                print(json.dumps(dict(ok=True, calls=len(records), scope='reference_recipe_existing_engine_commands',
                    new_handlers_verified=False, current_ui_verified=False, report=str(destination))))
                return
            if not args.connect:
                execute('wood.board', dict(name='MCP shelf', material='oak', length_mm=300, width_mm=200, thickness_mm=18, grain='length'))
                execute('edit.undo', {})
                execute('edit.redo', {})
                created = execute('print.part', dict(name='MCP plate', template='mounting_plate', length_mm=60, width_mm=30, thickness_mm=6, hole_diameter_mm=4.5))
                assert created['print_preflight']['ready_for_slicer'] is True
                body = created['body']
                execute('parts.insert', dict(family='washer', size='M4', point=[80, 20, 0]))
                bom = execute('assembly.bom', {})
                assert bom['total_occurrences'] == 3
                tool('save', dict(path=str(output / 'mcp-workshop.sc')))
                tool('export', dict(path=str(output / 'mcp-plate.3mf'), bodies=[body]))
                execute('wood.board', dict(name='Invalid', material='invented', length_mm=300, width_mm=200, thickness_mm=18), error=True)
            else:
                body = args.body
            report = execute('print.check', dict(bodies=[body], printer='bambu_a1_04'))
            assert report['ready_for_slicer'] is True and report['printable'] is None
            execute('print.check', dict(bodies=[body], layer_height_mm=0.5), error=True)
            destination = output / ('mcp-live.json' if args.connect else 'mcp-headless.json')
            destination.write_text(json.dumps(records, indent=2), encoding='utf-8')
            print(json.dumps(dict(ok=True, mode='live' if args.connect else 'headless', calls=len(records), report=str(destination))))
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()


if __name__ == '__main__':
    main()
