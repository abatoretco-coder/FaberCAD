"""Browse furniture templates and emit existing FABER commands; never execute CAD."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT/'catalogue/furniture.json'
TYPES = {'board', 'standard', 'wood_dowel', 'wood_screw', 'shelf_pin', 'angle_bracket',
         'butt_hinge', 'drawer_slide', 'foot_pad'}


def load_catalogue():
    data = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    if data['schema_version'] != 1 or data['units'] != 'mm':
        raise ValueError('Unsupported furniture catalogue')
    ids = set()
    for entry in data['entries']:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,95}', entry['id']) or entry['id'] in ids:
            raise ValueError('Invalid or duplicate catalogue id')
        ids.add(entry['id'])
        if entry['type'] not in TYPES or entry['category'] not in ('board', 'hardware'):
            raise ValueError('Unsupported furniture entry')
        if entry['geometry_kind'] not in ('procedural_standard', 'envelope_proxy'):
            raise ValueError('Invalid geometry provenance')
    return data


def find(data, identifier):
    for entry in data['entries']:
        if entry['id'] == identifier:
            return entry
    raise ValueError(f'Unknown furniture catalogue id: {identifier}')


def recipe(data, identifier, name=None, fresh=False):
    entry = find(data, identifier)
    name = name or entry['id']
    if not name.strip() or len(name) > 60 or any(ord(c) < 32 for c in name) or name == 'root':
        raise ValueError('Choose a unique component name of 1..60 printable characters, other than root')
    p = entry['parameters']
    kind = entry['type']
    commands, components, bodies = [], [], []

    def emit(command, **params):
        commands.append(dict(command=command, params=params))

    def component(label, grounded=False):
        emit('component.activate', component='root')
        emit('component.create', name=label, grounded=grounded)
        components.append(label)
        bodies.append(label+' envelope')
        return bodies[-1]

    def box(body, corner, length, width, height, join=False):
        params = dict(corner=corner, length=length, width=width, height=height)
        params.update(dict(operation='join', targets=[body]) if join else dict(body_name=body))
        emit('solid.box', **params)

    def cylinder(body, base, radius, height, join=False):
        params = dict(base=base, radius=radius, height=height)
        params.update(dict(operation='join', targets=[body]) if join else dict(body_name=body))
        emit('solid.cylinder', **params)

    if fresh:
        emit('file.new', name='FABER catalogue '+identifier)
    emit('component.activate', component='root')
    if kind == 'board':
        emit('wood.board', name=name, **deepcopy(p))
        components.append(name)
        bodies.append(name+' stock')
    elif kind == 'standard':
        emit('parts.insert', name=name, point=[0, 0, 0], **deepcopy(p))
        components.append(name)
    else:
        l, w, t = (p.get(k) for k in ('length_mm', 'width_mm', 'thickness_mm'))
        body = component(name+' fixed' if kind in ('butt_hinge', 'drawer_slide') else name,
                         grounded=kind in ('butt_hinge', 'drawer_slide'))
        if kind in ('wood_dowel', 'shelf_pin', 'wood_screw'):
            d = p['diameter_mm']
            cylinder(body, [0, 0, 0], d/2, l)
            if kind == 'wood_screw':
                cylinder(body, [0, 0, l-0.5], d, d*0.6+0.5, join=True)
        elif kind == 'angle_bracket':
            box(body, [0, 0, 0], l, w, t)
            box(body, [0, 0, 0], t, w, l, join=True)
        elif kind == 'foot_pad':
            box(body, [0, 0, 0], l, w, t)
        elif kind == 'butt_hinge':
            clearance = p['clearance_mm']
            box(body, [-w/2, -t/2, 0], w/2, t, l)
            cylinder(body, [0, 0, 0], 1.5*t, l, join=True)
            body = component(name+' moving')
            start = 1.5*t+clearance
            box(body, [start, -t/2, 0], w/2-start, t, l)
        elif kind == 'drawer_slide':
            clearance = p['clearance_mm']
            box(body, [0, 0, 0], l, (w-clearance)/2, t)
            body = component(name+' moving')
            box(body, [0, (w+clearance)/2, 0], l, (w-clearance)/2, t)

        material = ('Workshop Beech', 0.71, '#C49A74') if kind == 'wood_dowel' else (
            ('Catalogue Polymer Estimate', 1.0, '#353535') if kind == 'foot_pad' else ('Workshop Generic Steel', 7.85, '#9CA3AF'))
        # Existing names are not overwritten; FABER rejects conflicting names.
        # Catalogue-only names avoid changing a user's workshop material presets.
        material = ('Catalogue '+name+' material', material[1], material[2])
        emit('material.create', name=material[0], density_g_cm3=material[1], color=material[2])
        emit('material.assign', bodies=bodies, material=material[0])
        if kind in ('butt_hinge', 'drawer_slide'):
            emit('joint.as_built', name=name+' motion', type='revolute' if kind == 'butt_hinge' else 'slider',
                 a=components[0], b=components[1], at=dict(occurrence=components[0], point=[0, 0, 0],
                 z=[0, 0, 1] if kind == 'butt_hinge' else [1, 0, 0]), limits=[[0, p['travel']]], quiet=True)
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    properties = dict(catalogue_id=identifier, catalogue_source='catalogue/furniture.json',
                      recipe_sha256=digest, geometry_provenance=entry['geometry_kind'], units='mm',
                      geometry_source=data['provenance']['source'],
                      fidelity='nominal editable geometry; supplier details and mounting pattern unverified',
                      generated_from_evidence='false', manufacturer_reference_status='none; generic design template',
                      license_or_usage_status=data['provenance']['license_or_usage_status'],
                      limitations='; '.join(data['provenance']['limitations']))
    if kind != 'board':
        properties['density_status'] = 'nominal mass estimate; not product data'
    for label in components:
        emit('component.metadata.set', component=label, description=entry['name'], properties=properties)
    emit('component.activate', component='root')
    return dict(commands=commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--category', choices=('board', 'hardware'))
    listing.add_argument('--search', default='')
    showing = sub.add_parser('show')
    showing.add_argument('id')
    emitting = sub.add_parser('recipe')
    emitting.add_argument('id')
    emitting.add_argument('--name')
    emitting.add_argument('--fresh', action='store_true', help='Explicitly start a new design; omit to insert in the current design')
    args = parser.parse_args()
    try:
        data = load_catalogue()
        if args.action == 'list':
            result = [dict(id=e['id'], label_fr=e['label_fr'], category=e['category'], kind=e['geometry_kind'])
                      for e in data['entries'] if (not args.category or e['category'] == args.category)
                      and args.search.casefold() in (e['name']+' '+e['label_fr']+' '+e['id']).casefold()]
        elif args.action == 'show':
            result = dict(entry=find(data, args.id), provenance=data['provenance'])
        else:
            result = recipe(data, args.id, args.name, args.fresh)
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    main()
