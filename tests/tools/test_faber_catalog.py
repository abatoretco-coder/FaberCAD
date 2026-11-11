"""Portable catalogue recipes: no CAD invocation or compilation during source CI."""
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('faber_furniture_catalogue', ROOT/'scripts/faber_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class FurnitureCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.data = catalog.load_catalogue()

    def test_every_entry_has_an_insertable_recipe_and_provenance(self):
        for entry in self.data['entries']:
            with self.subTest(entry=entry['id']):
                result = catalog.recipe(self.data, entry['id'])
                commands = result['commands']
                self.assertFalse(any(c['command'].startswith(('file.', 'document.')) for c in commands))
                metadata = [c['params']['properties'] for c in commands if c['command'] == 'component.metadata.set']
                self.assertGreater(len(metadata), 0)
                for props in metadata:
                    self.assertEqual(props['catalogue_id'], entry['id'])
                    self.assertEqual(props['units'], 'mm')
                    self.assertEqual(props['generated_from_evidence'], 'false')
                    self.assertEqual(len(props['recipe_sha256']), 64)
                    self.assertIn('no third-party CAD', props['license_or_usage_status'])
                self.assertEqual(commands[-1], dict(command='component.activate', params=dict(component='root')))

    def test_stock_materials_match_existing_workshop_ids_and_positive_dimensions(self):
        source = (ROOT/'crates/engine/src/cmd/workshop.rs').read_text()
        materials = set()
        for entry in self.data['entries']:
            if entry['type'] != 'board':
                continue
            p = entry['parameters']
            materials.add(p['material'])
            self.assertIn('("'+p['material']+'",', source)
            self.assertEqual(p['grain'], 'length')
            for key in ('length_mm', 'width_mm', 'thickness_mm'):
                self.assertGreater(p[key], 0)
                self.assertLessEqual(p[key], 10000)
        self.assertEqual(len(materials), 10)

    def test_existing_standard_part_handler_is_reused_without_fabricated_products(self):
        for entry in self.data['entries']:
            if entry['type'] == 'standard':
                commands = catalog.recipe(self.data, entry['id'], name='Chosen name')['commands']
                insertion = next(c for c in commands if c['command'] == 'parts.insert')
                self.assertEqual(insertion['params']['name'], 'Chosen name')
                for key, value in entry['parameters'].items():
                    self.assertEqual(insertion['params'][key], value)
                self.assertEqual(entry['geometry_kind'], 'procedural_standard')
        self.assertIsNone(self.data['provenance']['manufacturer_reference'])
        self.assertIsNone(self.data['provenance']['procurement_snapshot'])

    def test_hinges_and_slides_have_two_components_and_explicit_motion(self):
        for identifier, joint_type, axis in [('butt-hinge-60x40', 'revolute', [0, 0, 1]), ('drawer-slide-350', 'slider', [1, 0, 0])]:
            commands = catalog.recipe(self.data, identifier, name='Hardware')['commands']
            components = [c['params'] for c in commands if c['command'] == 'component.create']
            self.assertEqual([c['grounded'] for c in components], [True, False])
            joint = next(c['params'] for c in commands if c['command'] == 'joint.as_built')
            self.assertEqual(joint['type'], joint_type)
            self.assertEqual(joint['at']['z'], axis)
            self.assertEqual([joint['a'], joint['b']], [c['name'] for c in components])

    def test_unknown_ids_and_invalid_names_are_refused_and_reset_requires_opt_in(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            catalog.recipe(self.data, 'invented-product')
        for name in (' ', 'root', 'bad\nname', 'x'*61):
            with self.subTest(name=name), self.assertRaises(ValueError):
                catalog.recipe(self.data, 'wood-dowel-8x30', name=name)
        result = catalog.recipe(self.data, 'wood-dowel-8x30', fresh=True)
        self.assertEqual(result['commands'][0]['command'], 'file.new')

    def test_cli_search_and_unknown_id_have_explicit_results(self):
        script = str(ROOT/'scripts/faber_catalog.py')
        result = subprocess.run([sys.executable, '-B', script, 'list', '--category', 'board', '--search', 'mdf'],
                                capture_output=True, text=True, timeout=3, check=True)
        self.assertEqual(len(json.loads(result.stdout)), 5)
        missing = subprocess.run([sys.executable, '-B', script, 'recipe', 'invented-product'],
                                 capture_output=True, text=True, timeout=3)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(missing.stdout, '')

    def test_workshop_catalogue_messages_resolve_in_english_and_french_without_duplicate_ids(self):
        source = (ROOT/'crates/ui-egui/src/dialogs_workshop.rs').read_text(encoding='utf-8')
        required = {'workshop.'+key for key in re.findall(r'tr\("(catalogue_[a-z_]+)"\)', source)}
        required |= {'cmd.workshop.insert', 'workshop.catalogue', 'workshop.catalogue_search',
                     'workshop.catalogue_category', 'workshop.catalogue_count', 'workshop.catalogue_inserted'}
        for language in ('en', 'fr'):
            messages = json.loads((ROOT/f'assets/locales/{language}.json').read_text(encoding='utf-8'))
            for path in (ROOT/'assets/locales/pending').glob('*.json'):
                pending = json.loads(path.read_text(encoding='utf-8')).get(language, {})
                self.assertFalse(set(messages) & set(pending), f'Duplicate {language} messages in {path.name}')
                messages.update(pending)
            self.assertFalse(required-set(messages), f'Missing {language} messages: {required-set(messages)}')


if __name__ == '__main__':
    unittest.main()
