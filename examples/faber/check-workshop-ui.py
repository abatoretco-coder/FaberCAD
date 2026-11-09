"""Pointer/keyboard qualification on a fresh dedicated workshop app window."""
import argparse
import atexit
import json
import math
from pathlib import Path
import time
from live_motion_probe import control


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=27916)
    parser.add_argument('--send-to-bambu', action='store_true')
    parser.add_argument('--review-only', action='store_true')
    args = parser.parse_args()
    output = Path('target/workshop').resolve()
    records = []
    destination=output/('ui-review-qualification.json' if args.review_only else 'ui-qualification.json')
    atexit.register(lambda: destination.write_text(json.dumps(records,indent=2),encoding='utf-8'))
    def call(method, **params):
        value = control(args.port, method, params)
        records.append(dict(method=method, params=params, result=value))
        return value
    def execute(command, **params):
        return call('engine.execute', command=command, params=params)
    def handle(name):
        deadline = time.monotonic() + 5
        previous=None
        stable=0
        while time.monotonic() < deadline:
            found = [item for item in call('ui.handles', prefix=name) if item['name'] == name]
            if found:
                point=found[0]
                stable=stable+1 if point==previous else 0
                previous=point
                if stable>=2:return point
            time.sleep(0.1)
        raise AssertionError(f'Missing native UI handle: {name}')
    def click(name):
        point = handle(name)
        call('ui.click', x=point['x'], y=point['y'])
        time.sleep(0.15)
    def option(suffixes):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            choices=call('ui.handles',prefix='dialog:')
            found=next((item for item in choices if item['name'].endswith(suffixes)),None)
            if found:return handle(found['name'])
            time.sleep(0.1)
        raise AssertionError(f'No native dropdown option matching {suffixes}')
    def wait_absent(prefix):
        deadline=time.monotonic()+5
        while call('ui.handles',prefix=prefix):
            assert time.monotonic()<deadline,f'Stale UI handles remained: {prefix}'
            time.sleep(0.1)
    def field(key, value):
        click(f'workshop:field:{key}')
        call('ui.key', key='A', ctrl=True)
        call('ui.text', text=value)
        time.sleep(0.15)
    def shot(name):
        time.sleep(0.5)
        call('ui.screenshot', path=str(output / f'ui-{name}.png'))
    def current():
        return call('ui.inspect')['dialog']
    def wait_dialog(predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=current()
            if predicate(state):return state
            time.sleep(0.1)
        raise AssertionError(f'Unexpected dialog state: {state}')
    def confirm():
        call('ui.key', key='Enter')
        wait_dialog(lambda state:state is None)
    def start():
        call('ui.start', command='workshop.library')
        time.sleep(0.2)
    def cancel():
        call('ui.key', key='Escape')
    def isolate(body, point, target, distance):
        names = [item['name'] for item in execute('inspect.measure', names_only=True)['bodies']]
        execute('browser.visibility', items=names, visible=False)
        execute('browser.visibility', items=[body], visible=True)
        call('ui.camera', target=target, yaw=0.4, pitch=0.8, distance=distance)
        call('ui.set', showGrid=False, showOrigin=False)
        return point
    def pick(point):
        call('ui.dialogInput', index=0)
        screen = call('ui.at', world=point)
        call('ui.click', x=screen[0], y=screen[1])
        wait_dialog(lambda state:state and state['inputs'][0]['items'])

    # Startup replaces the per-process token. Wait using a read-only request before mutations.
    deadline=time.monotonic()+15
    while True:
        try:
            call('ui.inspect')
            break
        except (OSError, RuntimeError):
            if time.monotonic()>=deadline:raise
            time.sleep(0.2)
    if args.review_only:
        if current() is not None:
            cancel()
            wait_dialog(lambda state:state is None)
        start()
        click('workshop:tab:pla')
        field('width', 'invalid')
        click('workshop:template')
        spacer=option(('Entretoise · trou traversant', 'Spacer · through bore'))
        call('ui.click', x=spacer['x'], y=spacer['y'])
        wait_absent(spacer['name'])
        state=current()
        assert state.get('commands') and state['commands'][0]['command']=='print.part', ('Hidden width blocked spacer',state)
        field('name', 'UI regression spacer')
        field('diameter', '12')
        field('height', '8')
        field('hole', '4,5')
        confirm()
        measured=execute('inspect.measure', bodies=['UI regression spacer PLA'])
        expected=math.pi*(6**2-2.25**2)*8
        assert abs(measured['bodies'][0]['volume_mm3']-expected)<0.01
        execute('edit.undo')
        print(json.dumps(dict(ok=True,actions=len(records),regression='hidden spacer width')))
        return
    start()
    field('name', 'UI shelf')
    field('length', '450')
    click('workshop:tab:pla')
    wait_dialog(lambda d:d and d.get('commands') and d['commands'][0]['command']=='print.part' and d['commands'][0]['params']['length_mm']==60)
    click('workshop:tab:wood')
    wait_dialog(lambda d:d and d.get('commands') and d['commands'][0]['command']=='wood.board' and d['commands'][0]['params']['length_mm']==450)
    field('width', '250')
    field('thickness', '18')
    shot('wood')
    confirm()
    measured = execute('inspect.measure', bodies=['UI shelf stock'])
    assert abs(measured['total']['volume_mm3'] - 2025000) < 0.01

    start()
    click('workshop:tab:hardware')
    wait_dialog(lambda d:d and d.get('commands') and d['commands'][0]['params'].get('family')=='socket_head_cap_screw')
    shot('hardware')
    click('workshop:tab:pla')
    field('name', 'UI printed plate')
    field('hole', '4,6')
    wait_dialog(lambda d:d and d.get('commands') and d['commands'][0]['params'].get('hole_diameter_mm')==4.6)
    shot('pla')
    confirm()
    measured = execute('inspect.measure', bodies=['UI printed plate PLA'])
    assert abs(measured['total']['volume_mm3'] - (60*30*6-2*math.pi*2.3**2*6)) < 0.01

    point = isolate('UI shelf stock', [225, 125, 18], [400, 125, 9], 1100)
    start()
    click('workshop:tab:materials')
    pick(point)
    click('workshop:material')
    oak = option((':Chêne', ':Oak'))
    call('ui.click', x=oak['x'], y=oak['y'])
    wait_absent(oak['name'])
    click('workshop:apply_material')
    deadline=time.monotonic()+5
    while execute('inspect.measure', bodies=['UI shelf stock'])['bodies'][0]['material'] != 'Workshop Oak':
        assert time.monotonic()<deadline,'Material assignment did not reach the selected body'
        time.sleep(0.1)
    shot('material')
    cancel()

    point = isolate('PLA test plate PLA', [30, 15, 6], [70, 15, 3], 120)
    start()
    click('workshop:tab:preflight')
    pick(point)
    click('workshop:check')
    handle('workshop:send_bambu')
    shot('preflight')
    field('layer', '0,5')
    wait_absent('workshop:send_bambu')
    click('workshop:check')
    shot('invalid-layer')
    field('layer', '0,2')
    click('workshop:check')
    shot('ready-for-slicer')
    if args.send_to_bambu:
        click('workshop:send_bambu')
        deadline=time.monotonic()+30
        while True:
            status = call('ui.inspect')['status']
            if status and (status['error'] or 'Bambu' in status['text']):break
            assert time.monotonic()<deadline, status
            time.sleep(0.2)
        assert status and not status['error'] and 'Bambu' in status['text'], status
    else:
        # Verify keyboard dismissal without starting another desktop application.
        cancel()
    destination = output / 'ui-qualification.json'
    destination.write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(dict(ok=True, actions=len(records), report=str(destination))))


if __name__ == '__main__':
    main()
