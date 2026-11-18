"""Independent checks of the read-only 3D projection and winding ownership."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transformer_preview_scene import build_scene
from winding_layout import assess_winding_window, iter_bundle_records


def example():
    config = json.loads((ROOT / 'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_text(encoding='utf8'))
    rows = [dict(id='P', name='原边', turns=config['Np'], strands=config['n_strand_p'],
                 parallel_wires=config.get('parallel_wires_p', 1), bare_diameter=config['d_wire_p'])]
    rows.extend(dict(id=f'OUT{i}', name=o['name'], turns=o['Ns'], strands=o['n_strand_s'],
                     parallel_wires=o.get('parallel_wires_s', 1), bare_diameter=o['d_wire_s'])
                for i, o in enumerate(config['outputs'], 1))
    return config, rows


def points(scene):
    return {t['id']: t for w in scene['windings'] for s in w['sections'] for t in s['turns']}


class PreviewSceneTests(unittest.TestCase):
    def test_qr_all_reference_layers_have_exact_shared_positions_and_dimensions(self):
        config, rows = example()
        original = copy.deepcopy((config, rows))
        scene = build_scene(config['core_choice'], rows, config['winding_config'])
        assessment = assess_winding_window(rows, config['winding_config'])
        drawn = points(scene)
        self.assertEqual(scene['summary']['layer_count'], 5)
        self.assertEqual(len(drawn), 92)
        self.assertEqual(scene['placement']['r0_mm'], 7.4)
        self.assertAlmostEqual(scene['placement']['z0_mm'], -8.8)
        for row in assessment['windings']:
            for box in iter_bundle_records(row, assessment['config']):
                actual = drawn[box['id']]
                self.assertEqual(actual['center_mm'], [(box['x'] + box['width'] / 2) * 1000,
                                                       (box['y'] + box['height'] / 2) * 1000])
                self.assertEqual(actual['width_mm'], box['width'] * 1000)
                self.assertEqual(actual['height_mm'], box['height'] * 1000)
        self.assertEqual((config, rows), original)
        json.dumps(scene, allow_nan=False)

    def test_manual_turn_position_changes_only_one_center_and_signature(self):
        config, rows = example()
        before = build_scene(config['core_choice'], rows, config['winding_config'])
        point = next(turn for turn in points(before).values() if turn['id'].startswith('OUT2_'))
        sid, turn, bundle = point['id'].split(':')
        config['winding_config']['turn_positions'] = {sid: {turn + ':' + bundle: (point['center_mm'][0] + .02) / 1000}}
        after = build_scene(config['core_choice'], rows, config['winding_config'])
        changed = [key for key, value in points(before).items() if value['center_mm'] != points(after)[key]['center_mm']]
        self.assertEqual(changed, [point['id']])
        self.assertNotEqual(before['signature'], after['signature'])
        self.assertAlmostEqual(points(after)[point['id']]['center_mm'][0] - point['center_mm'][0], .02)

    def test_parallel_wires_and_sub_bundles_do_not_change_electrical_turn_count(self):
        rows = [dict(id='P', name='原边', turns=6, strands=20, parallel_wires=2, bare_diameter=.0001)]
        cfg = dict(window_width=.03, window_height=.02,
                   overrides={'P': dict(parallel_bundles=2)},
                   model_3d={'schema': 'power-transformer.model-input.v1',
                             'frame': {'r0_m_if_circular': .008, 'z0_m': -.015},
                             'bobbin': {'winding_route_type': 'circular'}})
        scene = build_scene('PQ32-30', rows, cfg)
        self.assertEqual(scene['windings'][0]['turns'], 6)
        self.assertEqual(len(points(scene)), 24)
        self.assertEqual({t['wire_index'] for t in points(scene).values()}, {1, 2})
        self.assertEqual({t['sub_bundle_index'] for t in points(scene).values()}, {1, 2})

    def test_missing_window_keeps_core_without_guessing_windings(self):
        config, rows = example()
        scene = build_scene(config['core_choice'], rows, {})
        self.assertEqual(scene['windings'], [])
        self.assertIn('窗口净宽', ' '.join(scene['notes']))
        self.assertEqual(scene['summary']['status'], 'core_only')

    def test_unknown_core_can_use_explicit_path_without_fabricating_core(self):
        config, rows = example()
        scene = build_scene('不存在的型号', rows, config['winding_config'])
        self.assertEqual(scene['core']['status'], 'dimensions_pending')
        self.assertIsNone(scene['core']['dimensions_mm'])
        self.assertEqual(len(points(scene)), 92)

    def test_estimated_gap_is_not_a_physical_gap_but_declared_gap_is(self):
        config, rows = example()
        scene = build_scene(config['core_choice'], rows, config['winding_config'], gap={'gap_m': .0005})
        self.assertEqual(scene['gap_mm'], 0)
        self.assertIn('0.5 mm', ' '.join(scene['notes']))
        config['winding_config']['model_3d']['core']['gap_geometry'] = dict(
            type='center_leg_ground', length_m=.00035, source='测试图纸')
        scene = build_scene(config['core_choice'], rows, config['winding_config'])
        self.assertEqual(scene['gap_mm'], .35)
        self.assertEqual(scene['gap_kind'], 'center_leg_ground')

    def test_unconfirmed_datums_and_stale_snapshot_are_visible(self):
        config, rows = example()
        cfg = config['winding_config']
        cfg.pop('model_3d')
        scene = build_scene(config['core_choice'], rows, cfg, stale=True)
        self.assertTrue(scene['placement']['assumed'])
        self.assertTrue(scene['stale'])
        self.assertIn('上一有效计算', ' '.join(scene['notes']))
        self.assertNotIn('model_3d', cfg)

    def test_custom_path_preserved_in_millimetres(self):
        config, rows = example()
        profile = config['winding_config']['model_3d']
        profile['bobbin'].update(winding_route_type='custom_closed', winding_path_xy_m=[
            [-.009, -.008], [.009, -.008], [.009, .008], [-.009, .008], [-.009, -.008]])
        scene = build_scene(config['core_choice'], rows, config['winding_config'])
        self.assertEqual(scene['placement']['path_xy_mm'][0], [-9., -8.])
        self.assertEqual(scene['placement']['route_type'], 'custom_closed')

    def test_oversized_preview_is_explicit_not_silently_truncated(self):
        from unittest.mock import patch
        config, rows = example()
        with patch('transformer_preview_scene.MAX_PREVIEW_BUNDLES', 90):
            scene = build_scene(config['core_choice'], rows, config['winding_config'])
        self.assertEqual(scene['windings'], [])
        self.assertEqual(scene['summary']['bundle_count'], 92)
        self.assertIn('超过逐匝预览容量', ' '.join(scene['notes']))


if __name__ == '__main__':
    unittest.main()
