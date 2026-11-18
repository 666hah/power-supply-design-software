"""Explanatory UI must match all exported fields and preserve model semantics."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from controller_logic import (HELP, acf_definition, cot_definition, definition, display_value,
                              nonisolated_definition, qr_definition, state_note)
from spice_export import SETTINGS,normalize_settings,mp6005_preset
from design_engine.contracts import json_value


class ControllerLogicChecks(unittest.TestCase):
    def test_all_settings_are_explained_and_scoped(self):
        self.assertEqual(set(HELP),set(SETTINGS))
        d=definition();nodes={n['id']:n for n in d['nodes']}
        self.assertEqual(json_value(d),d)
        for key,(node,purpose,meaning) in HELP.items():
            self.assertIn(node,nodes);self.assertTrue(purpose);self.assertTrue(meaning)
        for key in ('feedback_scale','kp','comp_voltage_max'):
            self.assertEqual(nodes[HELP[key][0]]['scope'],'external')
        self.assertEqual(HELP['diode_cj_pf'][0],'power')
        self.assertEqual(HELP['short_test'][0],'test')
        self.assertEqual(HELP['scp_threshold_v'][0],'protect')

    def test_inactive_controls_and_automatic_values_are_explicit(self):
        generic=normalize_settings();preset=mp6005_preset()
        self.assertIn('当前',state_note('ss_comp_start_v',generic))
        self.assertEqual(state_note('ss_comp_start_v',preset),'')
        self.assertIn('暂不生效',state_note('hiccup_off_ms',generic))
        self.assertEqual(state_note('hiccup_off_ms',preset),'')
        self.assertIn('250',display_value('frequency_hz',generic,{'f_sw':250000}))
        self.assertEqual(display_value('cs_limit',generic),'自动确定')
        self.assertEqual(display_value('kp',generic),'沿用软件')
        self.assertEqual(display_value('frequency_hz',{'frequency_hz':'1e-'}),'编辑中…')
        definition()['nodes'][0]['scope']='chip'
        self.assertEqual(definition()['nodes'][0]['scope'],'external')

    def test_schematic_coordinates_and_parameter_links(self):
        for function in (definition, qr_definition, acf_definition, nonisolated_definition, cot_definition):
            data = function()
            nodes = {node['id'] for node in data['nodes']}
            diagrams = [data['schematic'], *data.get('schematic_variants', {}).values()]
            if 'schematic_voltage' in data:
                diagrams.append(data['schematic_voltage'])
            for diagram in diagrams:
                with self.subTest(title=diagram['title']):
                    self.assertEqual(json_value(diagram), diagram)
                    width, height = diagram['width'], diagram['height']
                    items = diagram['items']
                    self.assertEqual(len(items), len({item['id'] for item in items}))
                    for item in items:
                        self.assertIn(item['key'], nodes)
                        self.assertLessEqual(item['x'] + item['w'], width)
                        self.assertLessEqual(item['y'] + item['h'], height)
                        if item.get('parameter'):
                            self.assertEqual(data['parameters'][item['parameter']]['node'], item['key'])
                        for field in item.get('focus_fields', []):
                            self.assertEqual(data['parameters'][field]['node'], item['key'])
                    for route in diagram['routes']:
                        points = route['points']
                        self.assertGreater(len(points), 1)
                        for x, y in points:
                            self.assertTrue(0 <= x <= width and 0 <= y <= height)
                        for (x1, y1), (x2, y2) in zip(points, points[1:]):
                            self.assertTrue((x1 == x2) != (y1 == y2))

    def test_qr_set_and_reset_use_separate_inputs(self):
        diagram = qr_definition()['schematic']
        items = {item['id']: item for item in diagram['items']}
        labels = {item['label'] for item in items.values() if item['kind'] == 'pin'}
        self.assertIn('ZCD ⑤', labels)
        self.assertIn('CS ④', labels)
        self.assertIn('⑦ GD', labels)
        self.assertNotIn('时钟', {item['label'] for item in items.values()})
        incoming = {tuple(wire['points'][-1]): wire['points'][0] for wire in diagram['routes']}
        latch = items['latch']
        set_position, reset_position = [pin['y'] for pin in latch['pins'] if pin['name'] in ('S', 'R')]
        self.assertEqual(incoming[latch['x'], set_position][0], items['permit']['x'] + items['permit']['w'])
        self.assertEqual(incoming[latch['x'], reset_position][0], items['reset']['x'] + items['reset']['w'])
        self.assertNotEqual(items['zcd_cmp']['key'], items['pwm']['key'])

if __name__=='__main__':unittest.main()
