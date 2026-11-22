"""Independent checks of the read-only 3D projection and winding ownership."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transformer_preview_scene import build_scene
from winding_layout import assess_winding_window, iter_bundle_records
from winding_length import resolve_winding_lengths


def example():
    config = json.loads((ROOT / 'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_text(encoding='utf8'))
    return config, winding_rows(config)


def winding_rows(config):
    rows = [dict(id='P', name='原边', turns=config['Np'], strands=config['n_strand_p'],
                 parallel_wires=config.get('parallel_wires_p', 1), bare_diameter=config['d_wire_p'])]
    rows.extend(dict(id=f'OUT{i}', name=o['name'], turns=o['Ns'], strands=o['n_strand_s'],
                     parallel_wires=o.get('parallel_wires_s', 1), bare_diameter=o['d_wire_s'])
                for i, o in enumerate(config['outputs'], 1))
    return rows


def points(scene):
    return {t['id']: t for w in scene['windings'] for s in w['sections'] for t in s['turns']}


def series_fixture(*, interleaved=True, parallel_wires=1, sub_bundles=1, strands=1):
    """Small synthetic geometry, independent of the optional private QR file."""
    plan = [dict(winding_id='P', turns=2, section_id='P_A')]
    if interleaved:
        plan.extend([dict(winding_id='OUT1', turns=2, section_id='S_A'),
                     dict(winding_id='OUT2', turns=1, section_id='AUX_A')])
    plan.extend([dict(winding_id='P', turns=2, section_id='P_B'),
                 dict(winding_id='P', turns=2, section_id='P_C')])
    rows = [dict(id='P', name='Primary', turns=6, strands=strands,
                 parallel_wires=parallel_wires, bare_diameter=.0001)]
    if interleaved:
        rows.extend([dict(id='OUT1', name='Secondary', turns=2, strands=1, bare_diameter=.0001),
                     dict(id='OUT2', name='Auxiliary', turns=1, strands=1, bare_diameter=.0001)])
    sections = {
        key: dict(winding_id='P', turns=2, start_node=start, end_node=end,
                  dot_node=start, direction='ccw', status='confirmed', source='Synthetic test')
        for key, start, end in [('P_A', 'P0', 'P1'), ('P_B', 'P1', 'P2'), ('P_C', 'P2', 'P3')]
    }
    cfg = dict(window_width=.012, window_height=.008, margin_x=.0002, margin_y=.0002,
               layer_plan=plan, overrides={'P': dict(parallel_bundles=sub_bundles)},
               model_3d=dict(schema='power-transformer.model-input.v1',
                   frame=dict(z0_m=-.006, r0_m_if_circular=.008),
                   bobbin=dict(winding_route_type='circular', status='confirmed', source='Synthetic test'),
                   sections=sections,
                   ports={'P': dict(connection='series', section_order=['P_A', 'P_B', 'P_C'],
                                    dot_node='P0', other_node='P3', status='confirmed', source='Synthetic test')}))
    return cfg, rows


def primary(scene):
    return next(w for w in scene['windings'] if w['id'] == 'P')


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

    def assert_shared_positions_unchanged(self, scene, rows, cfg):
        assessment = assess_winding_window(rows, cfg)
        expected = {}
        for row in assessment['windings']:
            for box in iter_bundle_records(row, assessment['config']):
                expected[box['id']] = [(box['x'] + box['width'] / 2) * 1000,
                                       (box['y'] + box['height'] / 2) * 1000]
        self.assertEqual({key: turn['center_mm'] for key, turn in points(scene).items()}, expected)

    def test_interleaved_l1_l4_l5_has_return_then_adjacent_crossover(self):
        cfg, rows = series_fixture()
        original = copy.deepcopy((cfg, rows))
        before_lengths = resolve_winding_lengths('PQ32-30', {'MLT': .068}, rows, cfg)
        scene = build_scene('PQ32-30', rows, cfg)
        p = primary(scene)
        self.assertEqual([s['layer_index'] for s in p['sections']], [1, 4, 5])
        self.assertEqual([s['axial_start'] for s in p['sections']], ['lower', 'lower', 'upper'])
        self.assertEqual(p['crossovers'], [
            dict(from_section='P_A', to_section='P_B', kind='pin_return', node='P1'),
            dict(from_section='P_B', to_section='P_C', kind='adjacent', node='P2')])
        self.assert_shared_positions_unchanged(scene, rows, cfg)
        self.assertEqual(resolve_winding_lengths('PQ32-30', {'MLT': .068}, rows, cfg), before_lengths)
        self.assertEqual((cfg, rows), original)

    def test_adjacent_layers_alternate_axial_start_without_reversing_declared_circulation(self):
        cfg, rows = series_fixture(interleaved=False)
        p = primary(build_scene('PQ32-30', rows, cfg))
        self.assertEqual([s['axial_start'] for s in p['sections']], ['lower', 'upper', 'lower'])
        self.assertEqual([s['direction'] for s in p['sections']], ['ccw'] * 3)
        self.assertEqual([s['kind'] for s in p['crossovers']], ['adjacent', 'adjacent'])

    def test_declared_reverse_traversal_does_not_reorder_physical_sections_or_turns(self):
        cfg, rows = series_fixture()
        before = build_scene('PQ32-30', rows, cfg)
        cfg['model_3d']['ports']['P'].update(
            section_order=['P_C', 'P_B', 'P_A'], dot_node='P3', other_node='P0')
        original = copy.deepcopy(cfg)
        after = build_scene('PQ32-30', rows, cfg)
        p = primary(after)
        self.assertEqual([s['id'] for s in p['sections']], ['P_A', 'P_B', 'P_C'])
        self.assertEqual([s['direction'] for s in p['sections']], ['cw'] * 3)
        self.assertEqual([s['axial_start'] for s in p['sections']], ['lower', 'upper', 'lower'])
        self.assertEqual(p['crossovers'], [
            dict(from_section='P_C', to_section='P_B', kind='adjacent', node='P2'),
            dict(from_section='P_B', to_section='P_A', kind='pin_return', node='P1')])
        self.assertEqual(points(before), points(after))
        self.assertNotEqual(before['signature'], after['signature'])
        self.assertEqual(cfg, original)

    def test_declared_crossover_route_is_rendered_and_counted_once(self):
        cfg, rows = series_fixture()
        path_m = [[.008, 0., .004], [.013, 0., -.007], [.018, 0., -.007], [.010, 0., -.005]]
        terminal_path_m = [[.008, 0., -.005], [.010, 0., -.008]]
        cfg['model_3d']['leads'] = [
            dict(node='P1', path_xyz_m=path_m, source='Synthetic routed interlayer lead'),
            dict(node='P0', path_xyz_m=terminal_path_m, source='Synthetic terminal lead')]
        original = copy.deepcopy(cfg)
        before_lengths = resolve_winding_lengths('PQ32-30', {'MLT': .068}, rows, cfg)
        scene = build_scene('PQ32-30', rows, cfg)
        p = primary(scene)
        self.assertEqual(p['crossovers'][0], dict(from_section='P_A', to_section='P_B',
            kind='declared', node='P1', path_xyz_mm=[[x * 1000 for x in pt] for pt in path_m]))
        self.assertEqual([s['axial_start'] for s in p['sections']], ['lower', 'lower', 'upper'])
        self.assertEqual(scene['leads'], [dict(node='P0',
            path_xyz_mm=[[x * 1000 for x in pt] for pt in terminal_path_m])])
        all_leads = p['crossovers'] + scene['leads']
        actual_length = sum(math.dist(a, b) for lead in all_leads
                            for a, b in zip(lead.get('path_xyz_mm', []), lead.get('path_xyz_mm', [])[1:]))
        expected_length = 1000 * sum(math.dist(a, b) for path in [path_m, terminal_path_m]
                                     for a, b in zip(path, path[1:]))
        self.assertAlmostEqual(actual_length, expected_length, places=12)
        self.assertEqual(resolve_winding_lengths('PQ32-30', {'MLT': .068}, rows, cfg), before_lengths)
        self.assertEqual(cfg, original)

    def test_missing_topology_uses_tagged_assumption_without_changing_positions(self):
        cfg, rows = series_fixture()
        cfg['model_3d'].pop('ports')
        cfg['model_3d'].pop('sections')
        scene = build_scene('PQ32-30', rows, cfg)
        p = primary(scene)
        self.assertEqual([s['kind'] for s in p['crossovers']], ['pin_return', 'adjacent'])
        self.assertEqual([s['node'] for s in p['crossovers']], [None, None])
        self.assertTrue(all(s['direction_assumed'] for s in p['sections']))
        self.assertTrue(any(note.startswith('P 的预览') and '示意连续绕制' in note
                            and '工程声明' in note for note in scene['notes']))
        self.assert_shared_positions_unchanged(scene, rows, cfg)

    def test_parallel_disconnected_and_branched_topology_does_not_fake_series_join(self):
        for kind in ['parallel', 'disconnected', 'external_tap', 'other_winding_branch', 'multiple_leads']:
            with self.subTest(kind=kind):
                cfg, rows = series_fixture()
                profile = cfg['model_3d']
                if kind == 'parallel':
                    profile['ports']['P']['connection'] = 'parallel'
                elif kind == 'disconnected':
                    profile['sections']['P_B'].update(start_node='UNCONNECTED', dot_node='UNCONNECTED')
                elif kind == 'external_tap':
                    profile['terminals'] = [dict(node='P1', pin='TAP', position_xyz_m=None,
                        external_connection='net', net='LOAD', status='confirmed', source='Synthetic tap')]
                elif kind == 'other_winding_branch':
                    profile['sections']['S_A'] = dict(winding_id='OUT1', turns=2,
                        start_node='P1', end_node='S_END', dot_node='P1', direction='ccw',
                        status='confirmed', source='Synthetic branch')
                else:
                    profile['leads'] = [dict(node='P1', path_xyz_m=path, source='Synthetic branch')
                        for path in ([[.01, 0., 0.], [.012, 0., -.005]],
                                     [[.01, 0., 0.], [.014, 0., -.005]])]
                scene = build_scene('PQ32-30', rows, cfg)
                p = primary(scene)
                self.assertEqual(p['crossovers'], [])
                self.assertTrue(all(s['axial_start'] == 'lower' for s in p['sections']))
                self.assertTrue(any('P' in note and ('并联' in note or '分支' in note)
                                    for note in scene['notes']), scene['notes'])
                self.assert_shared_positions_unchanged(scene, rows, cfg)
                if kind == 'multiple_leads':
                    self.assertEqual(len(scene['leads']), 2)

    def test_parallel_complete_wires_and_sub_bundles_keep_one_logical_crossover(self):
        cfg, rows = series_fixture(parallel_wires=2, sub_bundles=2, strands=20)
        p = primary(build_scene('PQ32-30', rows, cfg))
        self.assertEqual(p['turns'], 6)
        self.assertEqual(p['parallel_wires'], 2)
        self.assertEqual(len(p['crossovers']), 2)
        for section in p['sections']:
            self.assertEqual(section['turn_count'], 2)
            self.assertEqual(len(section['turns']), 8)
            tracks = {(t['wire_index'], t['sub_bundle_index']) for t in section['turns']}
            self.assertEqual(tracks, {(1, 1), (1, 2), (2, 1), (2, 2)})
            for wire, bundle in tracks:
                self.assertEqual([t['turn_index'] for t in section['turns']
                                  if (t['wire_index'], t['sub_bundle_index']) == (wire, bundle)], [1, 2])

    def test_single_section_mono_wire_has_no_crossover_or_litz_claim(self):
        cfg, rows = series_fixture(interleaved=False)
        cfg['layer_plan'] = [dict(winding_id='P', turns=6, section_id='P_A')]
        cfg['model_3d']['sections'] = {}
        cfg['model_3d']['ports'] = {}
        scene = build_scene('PQ32-30', rows, cfg)
        p = primary(scene)
        self.assertEqual(p['crossovers'], [])
        self.assertEqual(p['strands'], 1)
        self.assertEqual(p['sections'][0]['axial_start'], 'lower')
        self.assertEqual({(t['wire_index'], t['sub_bundle_index']) for t in points(scene).values()}, {(1, 1)})
        self.assertNotIn('利兹线', ' '.join(scene['notes']))

    @unittest.skipUnless((ROOT / 'examples/90W_QR_L6565_252_442V.json').exists(),
                         'Optional local QR geometry is not distributed')
    def test_optional_local_qr_preserves_authored_geometry_and_follows_declared_ports(self):
        path = ROOT / 'examples/90W_QR_L6565_252_442V.json'
        original_bytes = path.read_bytes()
        cfg = json.loads(original_bytes)
        rows = winding_rows(cfg)
        original = copy.deepcopy(cfg)
        scene = build_scene(cfg['core_choice'], rows, cfg['winding_config'])
        assessment = assess_winding_window(rows, cfg['winding_config'])
        self.assertEqual(scene['summary']['layer_count'], len(assessment['physical_layers']))
        self.assert_shared_positions_unchanged(scene, rows, cfg['winding_config'])
        physical = {layer['section_id']: layer for layer in assessment['physical_layers']}
        for winding in scene['windings']:
            order = cfg['winding_config']['model_3d']['ports'][winding['id']]['section_order']
            self.assertEqual([(c['from_section'], c['to_section']) for c in winding['crossovers']],
                             list(zip(order, order[1:])))
            self.assertEqual([s['id'] for s in winding['sections']],
                             [sid for sid, layer in physical.items() if layer['winding_id'] == winding['id']])
        p = primary(scene)
        self.assertEqual([c['kind'] for c in p['crossovers']], ['pin_return', 'adjacent'])
        self.assertEqual([s['axial_start'] for s in p['sections']], ['lower', 'lower', 'upper'])
        self.assertEqual(cfg, original)
        self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == '__main__':
    unittest.main()
