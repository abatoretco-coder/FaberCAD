"""Exercise actual MCP tools. --connect only reads the dedicated app's PLA fixture."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connect', type=int)
    parser.add_argument('--body', default='PLA test plate PLA')
    parser.add_argument('--cli', type=Path, default=Path('target/debug/solidcraft-cli.exe'))
    parser.add_argument('--output', type=Path, default=Path('target/workshop'))
    args = parser.parse_args()
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
