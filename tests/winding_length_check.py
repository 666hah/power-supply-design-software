"""Electrical copper length follows the authored winding layout."""

import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winding_layout import assess_winding_window
from winding_length import resolve_winding_lengths


class WindingLengthCheck(unittest.TestCase):
    def simple(self, turns=3, **wire):
        p = dict(id='P', name='原边', turns=turns, strands=1, bare_diameter=.2e-3, **wire)
        config = dict(window_width=.0105, window_height=.004, margin_x=.25e-3, margin_y=0.,
            diameter_allowance=0., layer_plan=[dict(winding_id='P', turns=turns, section_id='P_A')],
            model_3d=dict(schema='power-transformer.model-input.v1',
                          frame=dict(r0_m_if_circular=.005), bobbin=dict(winding_route_type='circular')))
        return config, [p]

    def test_circular_helix_and_manual_axial_shift(self):
        config, wires = self.simple()
        original = copy.deepcopy((config, wires))
        result = resolve_winding_lengths('PQ32-30', {'MLT': .068}, wires, config)
        perimeter = math.tau * .0051
        pitch = (.010 - .0002) / 2
        expected_length = perimeter + 2 * math.hypot(perimeter, pitch)
        primary = result['windings']['P']
        self.assertEqual(result['method'], 'winding_geometry')
        self.assertAlmostEqual(primary['length_m'], expected_length, places=13)
        self.assertAlmostEqual(primary['mlt_m'], expected_length / 3, places=13)
        self.assertEqual(result['sections']['P_A']['winding_id'], 'P')
        self.assertEqual((config, wires), original)
        config['turn_positions'] = {'P_A': {'2:1': .00525 + .0005}}
        edited = resolve_winding_lengths('PQ32-30', {'MLT': .068}, wires, config)
        self.assertGreater(edited['windings']['P']['length_m'], primary['length_m'])

    def test_rounded_rectangle_and_explicit_leads(self):
        config, wires = self.simple(1)
        profile = config['model_3d']
        profile['bobbin'] = dict(winding_route_type='rounded_rectangle', rounded_rectangle_m=dict(
            center_xy_m=[0., 0.], width_m=.010, height_m=.006, corner_radius_m=.001))
        profile['ports'] = {'P': dict(dot_node='P1', other_node='P2')}
        profile['leads'] = [dict(node='P1', source='图纸', path_xyz_m=[[0.,0.,0.], [.003,.004,0.]])]
        winding = resolve_winding_lengths('EFD20', {'MLT': .032}, wires, config)['windings']['P']
        expected = 2 * (.010 + .006) + (math.tau - 8) * .001 + math.tau * .0001
        self.assertAlmostEqual(winding['mlt_m'], expected, places=13)
        self.assertAlmostEqual(winding['lead_length_m'], .005, places=13)
        self.assertAlmostEqual(winding['length_m'], expected + .005, places=13)

    def test_parallel_count_does_not_multiply_electrical_turns_or_length(self):
        config, wires = self.simple(1, parallel_wires=2)
        winding = resolve_winding_lengths('PQ32-30', {'MLT': .068}, wires, config)['windings']['P']
        self.assertEqual(winding['turns'], 1)
        self.assertAlmostEqual(winding['length_m'], math.tau * .0051, places=13)

    def test_interleaved_qr_sections_are_not_a_shared_mlt(self):
        cfg = json.loads((ROOT/'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_text(encoding='utf-8'))
        p = dict(id='P', name='原边', turns=cfg['Np'], strands=cfg['n_strand_p'], bare_diameter=cfg['d_wire_p'])
        wires = [p] + [dict(id=f'OUT{i}', name=r['name'], turns=r['Ns'], strands=r['n_strand_s'],
                           bare_diameter=r['d_wire_s']) for i, r in enumerate(cfg['outputs'],1)]
        lengths = resolve_winding_lengths(cfg['core_choice'], {'MLT': .068}, wires, cfg['winding_config'])
        self.assertEqual(lengths['method'], 'winding_geometry')
        layers = assess_winding_window(wires, cfg['winding_config'])['physical_layers']
        section_lengths = [lengths['sections'][layer['section_id']]['mlt_m'] for layer in layers]
        self.assertEqual(section_lengths, sorted(section_lengths))
        self.assertEqual(len({r['mlt_m'] for r in lengths['windings'].values()}), 3)
        self.assertTrue(all(r['lead_length_m'] == 0 for r in lengths['windings'].values()))

    def test_automatic_window_and_invalid_manual_layout(self):
        config, wires = self.simple()
        measured = resolve_winding_lengths('EE30', {'MLT': .059}, wires)
        self.assertEqual(measured['method'], 'core_geometry')
        self.assertNotEqual(measured['windings']['P']['mlt_m'], .059)
        config['layer_plan'][0]['turns'] = 2
        fallback = resolve_winding_lengths('EE30', {'MLT': .059}, wires, config)
        self.assertEqual(fallback['method'], 'catalog_estimate')
        self.assertAlmostEqual(fallback['windings']['P']['mlt_m'], .059)
        self.assertIn('手动排层', fallback['notes'][0])


if __name__ == '__main__':
    unittest.main()
