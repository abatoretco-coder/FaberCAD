"""Local UI control and genuine MCP/stdio qualification probes (development only)."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def control(port, method, params):
    token = (Path(os.environ['LOCALAPPDATA']) / 'SolidCraft/control' / f'{port}.token').read_text().strip()
    with socket.create_connection(('127.0.0.1', port), timeout=90) as connection:
        stream = connection.makefile('rwb')
        stream.write((json.dumps(dict(id=1, method=method, params=params, token=token)) + '\n').encode())
        stream.flush()
        reply = json.loads(stream.readline())
        if not reply.get('ok'):
            raise RuntimeError(reply)
        return reply['result']


def mcp(port, output):
    cli = Path('target/debug/solidcraft-cli.exe').resolve()
    with open(output.with_suffix('.stderr.log'), 'w', encoding='utf-8') as errors:
        process = subprocess.Popen([str(cli), 'mcp', '--connect', f'127.0.0.1:{port}', '--compact', '--allow-path', str(output.parent.resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8')
        records = []
        def request(method, params):
            number = len(records) + 1
            process.stdin.write(json.dumps(dict(jsonrpc='2.0', id=number, method=method, params=params)) + '\n')
            process.stdin.flush()
            while True:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError('MCP server closed unexpectedly')
                reply = json.loads(line)
                if reply.get('id') == number:
                    if 'error' in reply:
                        raise RuntimeError(reply['error'])
                    records.append(dict(method=method, params=params, result=reply['result']))
                    return reply['result']
        try:
            request('initialize', dict(protocolVersion='2025-06-18', capabilities={}, clientInfo=dict(name='FABER motion qualification', version='1')))
            process.stdin.write(json.dumps(dict(jsonrpc='2.0', method='notifications/initialized')) + '\n')
            process.stdin.flush()
            tools = request('tools/list', {})
            assert any(tool['name'] == 'execute' for tool in tools['tools'])
            for command, params in [('joint.list', {}), ('motion.play', dict(study='Headboard opening', step=10)), ('motion.play', dict(study='Headboard opening', step=0)), ('motion.interference', dict(study='Headboard opening', occurrences=['TL-06G', 'TL-12G'], samples=41, budget_s=30))]:
                result = request('tools/call', dict(name='execute', arguments=dict(command=command, params=params)))
                assert not result.get('isError'), result
                payload = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
                if command == 'motion.play':
                    assert payload['moved'] and payload['conflicts'] == 0, payload
                    expected = 0 if params['step'] == 0 else 27.5
                    assert abs(payload['values'][0]['values'][0]['value'] - expected) < 1e-8
                if command == 'motion.interference':
                    assert not payload['truncated'] and payload['samples'] == 41
                    assert payload['collisions'][0]['first_step'] == 0.5
            output.write_text(json.dumps(records, indent=2), encoding='utf-8')
            print(json.dumps(dict(mcp_calls=len(records), output=str(output))))
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()


def ui_probe(port, output):
    def call(method, **params):
        return control(port, method, params)
    def click_handle(name):
        handles = call('ui.handles', prefix=name)
        point = next(item for item in handles if item['name'] == name)
        call('ui.click', x=point['x'], y=point['y'])
    def shot(name):
        path = output.parent.resolve() / f'live-{name}.png'
        call('ui.inspect')
        time.sleep(1)
        call('ui.screenshot', path=str(path))
        return str(path)
    def wait_pending(clear):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            count = call('ui.capture')['pending_moves']
            if (count == 0) == clear:
                return
            time.sleep(0.1)
        raise AssertionError(f'Unexpected preview transforms: {count}; expected clear={clear}')
    call('ui.start', command='motion.study', params={'study': 'Headboard opening'})
    time.sleep(0.3)
    screenshots = [shot('closed')]
    click_handle('motion:play')
    time.sleep(0.4)
    screenshots.append(shot('playing'))
    click_handle('motion:stop')
    screenshots.append(shot('paused'))
    click_handle('motion:start')
    wait_pending(clear=True)
    handles = call('ui.handles', prefix='motion:slider_')
    start = next(item for item in handles if item['name'].endswith('start'))
    end = next(item for item in handles if item['name'].endswith('end'))
    call('ui.drag', x0=start['x']+8, y0=start['y'], x1=(start['x']+end['x'])/2, y1=end['y'], steps=10)
    screenshots.append(shot('scrubbed'))
    wait_pending(clear=False)
    click_handle('motion:check')
    time.sleep(0.3)
    screenshots.append(shot('collisions'))
    collisions = call('ui.handles', prefix='motion:collision:')
    assert collisions, 'No clickable collision rows were exposed'
    click_handle(collisions[0]['name'])
    screenshots.append(shot('first-collision'))
    wait_pending(clear=True)
    output.write_text(json.dumps(dict(screenshots=screenshots, collision_rows=len(collisions), inspected=call('ui.inspect')), indent=2), encoding='utf-8')
    print(json.dumps(dict(ui_probe='passed', collision_rows=len(collisions), output=str(output))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=27915)
    parser.add_argument('--method', default='ui.inspect')
    parser.add_argument('--params', default='{}')
    parser.add_argument('--mcp', action='store_true')
    parser.add_argument('--ui', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('target/headboard-comparison/live-mcp.json'))
    args = parser.parse_args()
    if args.mcp:
        mcp(args.port, args.output)
    elif args.ui:
        ui_probe(args.port, args.output)
    else:
        print(json.dumps(control(args.port, args.method, json.loads(args.params)), ensure_ascii=False))
