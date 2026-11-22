"""Native geometry preparation without an old extractor project or old ZIP."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from calculation_scheduler import CalculationCancelled
from portable_transformer_project import automatic_field_inputs, prepare_portable_reference
from transformer_geometry import read_geometry_package, resolve_geometry, strict_json
from transformer_sim_runner import bind_solver_project
from transformer_simulation import _calculate
from winding_layout import validate_winding_config


class PortableProjectChecks(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'artifacts/portable-transformer-project-check'
        base.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.core = self.root / 'selected.step'
        # The input builder checks a STEP header; independent CAD checks own
        # solid content. This fixture intentionally never starts a solver.
        self.core.write_bytes(b'ISO-10303-21;\nHEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;')
        (self.root / 'elmer/bin').mkdir(parents=True)
        for name in ('ElmerSolver.exe', 'ElmerGrid.exe'):
            (self.root / 'elmer/bin' / name).write_bytes(b'not executed')
        self.env = dict(elmer_home=str(self.root / 'elmer'), core_path=str(self.core),
            core_mode='half_center_gap', brep_unit='mm', translation_mm=[0., 0., 0.],
            rotation_deg=[0., 0., 0.], center_leg_radius_m=.0044, gap_center_z_m=0.,
            r0_m=.006, z0_m=-.006, mesh_profile='standard', air_radius_m=.05,
            timeout_s=1200, core_source='仅用于输入合同测试的参考半芯，不代表CAD实体已通过')
        self.cfg = strict_json((ROOT / 'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes())

    def prepare(self, config=None, environment=None):
        return prepare_portable_reference(config or self.cfg, environment=environment or self.env,
                                          output_directory=self.root / 'output')

    def geometry(self, result):
        settings = Path(result['project_file'])
        project = strict_json(settings.read_bytes())
        package = settings.parent / project['package_path']
        return read_geometry_package(package), package

    def canonical(self):
        config = deepcopy(self.cfg)
        # Give the synthetic fixture room for layer splits; this is not a CAD
        # clearance claim and the fake STEP/solver are never executed here.
        config['winding_config'].update(window_width=.025, window_height=.012)
        config['winding_config'] = validate_winding_config(config['winding_config'])
        return self.prepare(config)

    def assert_sync_notice(self, result):
        alternatives = ('已自动同步', '已按当前层序重建')
        self.assertTrue(any(note in result['summary'] for note in alternatives), result['summary'])
        assumptions = result['config']['winding_config']['model_3d']['assumptions']
        self.assertTrue(any(note in text for note in alternatives for text in assumptions), assumptions)

    def assert_current_membership(self, result):
        geometry, _ = self.geometry(result)
        winding = result['config']['winding_config']
        plan = winding['layer_plan']
        expected = [(s['section_id'], s['winding_id'], s['turns']) for s in plan]
        actual = [(s['section_id'], s['winding_id'], s['turns']) for s in geometry['physical_sections']]
        self.assertEqual(actual, expected)
        self.assertEqual(set(winding['model_3d']['sections']), {s[0] for s in expected})
        for port in geometry['connections']:
            ids = [sid for sid, owner, _turns in expected if owner == port['winding_id']]
            self.assertEqual(port['section_order'], ids)
            self.assertTrue(port['turns_match_calculator'])
        self.assertTrue(geometry['ready']['geometry_3d'])
        self.assertIsNotNone(geometry['connection_matrix']['values'])
        return geometry

    def manual(self):
        result = self.canonical()
        config = result['config']
        profile = config['winding_config']['model_3d']
        for section in profile['sections'].values():
            section.update(status='confirmed', source='Synthetic manually reviewed wiring', direction='cw')
            for key in ('start_node', 'end_node', 'dot_node'):
                section[key] = 'MANUAL_' + section[key]
        for port in profile['ports'].values():
            port.update(status='confirmed', source='Synthetic manually reviewed wiring')
            for key in ('dot_node', 'other_node'):
                port[key] = 'MANUAL_' + port[key]
        for terminal in profile['terminals']:
            terminal.update(node='MANUAL_' + terminal['node'], pin='USER_' + terminal['pin'],
                            position_xyz_m=[.012, .003, -.007], status='confirmed',
                            source='Synthetic terminal location')
        profile['leads'] = [dict(node=profile['ports']['P']['dot_node'],
            path_xyz_m=[[.01, 0., -.005], [.012, 0., -.007]], source='Synthetic explicit lead')]
        return config

    def test_blank_connections_are_explicit_assumptions_and_do_not_modify_design(self):
        before = deepcopy(self.cfg)
        result = self.prepare()
        self.assertEqual(self.cfg, before)
        candidate = result['config']
        profile = candidate['winding_config']['model_3d']
        self.assertEqual(candidate['winding_config']['layer_plan'], before['winding_config']['layer_plan'])
        self.assertTrue(all(s['status'] == 'assumed' for s in profile['sections'].values()))
        self.assertEqual(profile['frame'], dict(r0_m_if_circular=.006, z0_m=-.006))
        project = strict_json(Path(result['project_file']).read_bytes())
        package = Path(result['project_file']).parent / project['package_path']
        geometry = read_geometry_package(package)
        self.assertEqual(geometry['connection_matrix']['column_ports'], ['P', 'OUT1', 'OUT2', 'OUT3'])
        self.assertTrue(all(p['turns_match_calculator'] for p in geometry['connections']))
        self.assertEqual(project['material']['name'], 'DMR44')
        self.assertEqual(project['material']['relative_permeability'], 2400.)
        self.assertEqual(project['core']['total_gap_m'], geometry['design_targets']['air_gap']['gap_m'])
        self.assertEqual(project['core']['total_gap_m'], profile['core']['gap_geometry']['length_m'])
        self.assertIn('后续仍须', result['summary'])

    def test_generated_project_is_relocatable_and_existing_connections_are_preserved(self):
        first = self.prepare()
        candidate = first['config']
        old_profile = deepcopy(candidate['winding_config']['model_3d'])
        second = self.prepare(candidate)
        self.assertEqual(second['config']['winding_config']['model_3d']['sections'], old_profile['sections'])
        self.assertEqual(second['config']['winding_config']['model_3d']['ports'], old_profile['ports'])
        original = Path(second['project_file']).parent
        moved = self.root / 'other-computer-input'
        shutil.move(original, moved)
        self.core.unlink()  # The original selected model is no longer available.
        settings = moved / Path(second['project_file']).name
        p = strict_json(settings.read_bytes())
        self.assertFalse(Path(p['core']['path']).is_absolute())
        self.assertFalse(Path(p['package_path']).is_absolute())
        bound = bind_solver_project(moved / p['package_path'], settings, moved / 'run')
        self.assertEqual(Path(bound['core']['path']).parent, moved / 'models')
        self.assertEqual(bound['connections']['sections'], old_profile['sections'])

    def test_missing_window_and_frame_are_not_guessed(self):
        c = deepcopy(self.cfg)
        c['winding_config'].pop('window_width')
        with self.assertRaisesRegex(ValueError, '骨架净窗口宽度'):
            self.prepare(c)
        for key in ('r0_m', 'z0_m'):
            env = dict(self.env, **{key: None})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '不能自动猜测'):
                self.prepare(environment=env)

    def test_preflight_uses_current_qr_frame_and_catalog_without_creating_files(self):
        design = strict_json((ROOT / 'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_bytes())
        untouched = deepcopy(design)
        env = dict(elmer_home=str(self.root / 'elmer'))
        result = automatic_field_inputs(design, env)
        self.assertTrue(result['ready'], result['missing'])
        self.assertTrue(result['generated_core'])
        self.assertEqual(result['environment']['r0_m'], .0074)
        self.assertEqual(result['environment']['z0_m'], -.0088)
        self.assertEqual(result['environment']['core_mode'], 'assembled')
        self.assertEqual(design, untouched)
        self.assertEqual(env, dict(elmer_home=str(self.root / 'elmer')))

    def test_shipped_qr_reference_gets_missing_internal_series_terminals(self):
        design = strict_json((ROOT / 'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_bytes())
        original = deepcopy(design)
        prepared = self.prepare(design, dict(self.env, r0_m=.0074, z0_m=-.0088))
        profile = prepared['config']['winding_config']['model_3d']
        self.assertEqual(profile['ports'], original['winding_config']['model_3d']['ports'])
        self.assertEqual({item['node'] for item in profile['terminals']}, {'P_N1', 'OUT1_N1'})
        self.assertTrue(all(item['external_connection'] == 'none' for item in profile['terminals']))
        self.assertEqual(design, original)

    def test_generated_reference_fills_only_missing_nominal_dimensions(self):
        design = deepcopy(self.cfg)
        design['winding_config'].pop('window_width')
        result = automatic_field_inputs(design, {})
        self.assertTrue(result['ready'], result['missing'])
        self.assertTrue(result['generated_core'])
        self.assertGreater(result['winding']['window_width'], 0)
        self.assertEqual(result['winding']['window_height'], design['winding_config']['window_height'])
        self.assertIn('估算', result['summary'])
        design['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            bobbin=dict(winding_route_type='rounded_rectangle'))
        result = automatic_field_inputs(design, {})
        self.assertFalse(result['ready'])
        self.assertTrue(any('非圆形' in msg for msg in result['missing']))

    def test_explicit_cad_has_priority_without_changing_engineering_input(self):
        env = dict(self.env, core_model='PQ20-20')
        result = automatic_field_inputs(self.cfg, env)
        self.assertTrue(result['ready'], result['missing'])
        self.assertFalse(result['generated_core'])
        self.assertEqual(result['environment']['core_path'], self.env['core_path'])
        self.assertEqual(result['environment']['r0_m'], self.env['r0_m'])
        broken = automatic_field_inputs(self.cfg, dict(env, core_path=str(self.root / 'missing.step')))
        self.assertFalse(broken['ready'])
        self.assertFalse(broken['generated_core'])

    def test_manual_turn_centers_and_complete_parallel_wires_survive_preparation(self):
        from transformer_simulation import _calculate
        from winding_layout import assess_winding_window, transformer_windings
        c = deepcopy(self.cfg)
        c['parallel_wires_p'] = 2
        c['winding_config']['window_width'] = .025
        run = _calculate(c, None)
        case = run.runtime_bundle()['cases'][0]
        assessment = assess_winding_window(transformer_windings(case['result']), c['winding_config'])
        point = next(p for p in assessment['cross_sections']
                     if p['winding_id'] == 'P' and p['turn'] == 1 and p['bundle'] == 2)
        center = point['x'] + point['width'] / 2 + .01e-3
        positions = {point['section_id']: {point['position_key']: center}}
        c['winding_config']['turn_positions'] = positions
        result = self.prepare(c)
        self.assertEqual(result['config']['winding_config']['turn_positions'], positions)
        project = strict_json(Path(result['project_file']).read_bytes())
        geometry = read_geometry_package(Path(result['project_file']).parent / project['package_path'])
        winding = next(w for w in geometry['windings'] if w['id'] == 'P')
        self.assertEqual(winding['parallel_wires'], 2)
        boxes = [b for s in geometry['physical_sections'] if s['winding_id'] == 'P' for b in s['bundles']]
        self.assertEqual(len(boxes), 12)
        self.assertAlmostEqual(boxes[1]['center_uv_m'][0], center)

    def test_conflicting_frame_is_not_silently_overwritten(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
                                               frame=dict(r0_m_if_circular=.007, z0_m=-.006))
        with self.assertRaisesRegex(ValueError, '与当前工程不一致'):
            self.prepare(c)

    def test_unknown_mode_wrong_file_and_invalid_solver_stop_before_work(self):
        cases = [('core_mode', 'guess'), ('brep_unit', 'cm'), ('mesh_profile', 'fast'),
                 ('translation_mm', [0, 0]), ('rotation_deg', [0, float('nan'), 0]),
                 ('center_leg_radius_m', 0.), ('gap_center_z_m', .001),
                 ('timeout_s', 0), ('core_source', ''), ('elmer_home', str(self.root))]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.prepare(environment=dict(self.env, **{key: value}))
        self.core.write_bytes(b'<html>not a STEP model</html>')
        with self.assertRaisesRegex(ValueError, '只修改文件后缀'):
            self.prepare()
        stl = self.root / 'mesh.stl'; stl.touch()
        with self.assertRaisesRegex(ValueError, 'STL'):
            self.prepare(environment=dict(self.env, core_path=str(stl)))

    def test_partial_connections_non_circular_path_and_sealed_cad_are_not_replaced(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            ports={'P': dict(connection='series')})
        with self.assertRaisesRegex(ValueError, '已部分填写'):
            self.prepare(c)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            bobbin=dict(winding_route_type='rounded_rectangle'))
        with self.assertRaisesRegex(ValueError, '已有非圆形'):
            self.prepare(c)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            core=dict(geometry_sha256='a' * 64))
        with self.assertRaisesRegex(ValueError, 'SHA-256不符'):
            self.prepare(c)

    def test_physical_gap_processing_and_position_must_match_existing_design(self):
        c = deepcopy(self.cfg)
        c['winding_config']['model_3d'] = dict(schema='power-transformer.model-input.v1',
            core=dict(gap_geometry=dict(type='spacer', length_m=.0003, source='试验用已确认垫片',
                                        center_xyz_m=[0., 0., 0.])))
        with self.assertRaisesRegex(ValueError, '加工方式'):
            self.prepare(c)
        c['winding_config']['model_3d']['core']['gap_geometry'].update(type='center_leg_ground',
                                                                      center_xyz_m=[.001, 0., 0.])
        with self.assertRaisesRegex(ValueError, '气隙中心'):
            self.prepare(c)

    def test_cancel_is_honored_before_environment_or_calculation(self):
        with self.assertRaises(CalculationCancelled):
            prepare_portable_reference(self.cfg, environment={}, output_directory=self.root,
                                       cancelled=lambda: True)

    def test_assumed_wiring_rebuilds_after_split_reorder_delete_or_reassignment(self):
        base = self.canonical()['config']
        for edit in ('split', 'reorder', 'delete', 'reassign'):
            with self.subTest(edit=edit):
                config = deepcopy(base)
                plan = config['winding_config']['layer_plan']
                if edit == 'split':
                    index = next(i for i, s in enumerate(plan) if s['winding_id'] == 'P')
                    plan[index]['turns'] = 3
                    plan.insert(index + 1, dict(plan[index], section_id='P_SPLIT'))
                elif edit == 'reorder':
                    plan.insert(0, plan.pop())
                elif edit == 'delete':
                    removed = plan.pop()
                    next(s for s in plan if s['winding_id'] == removed['winding_id'])['turns'] += removed['turns']
                else:
                    source = next(s for s in plan if s['winding_id'] == 'P')
                    target = next(s for s in plan if s['winding_id'] == 'OUT1')
                    self.assertEqual(source['turns'], target['turns'])
                    source['winding_id'], target['winding_id'] = target['winding_id'], source['winding_id']
                original = deepcopy(config)
                result = self.prepare(config)
                self.assertEqual(config, original)
                geometry = self.assert_current_membership(result)
                self.assert_sync_notice(result)
                profile = result['config']['winding_config']['model_3d']
                self.assertTrue(all(s['status'] == 'assumed' for s in profile['sections'].values()))
                nodes = {s[key] for s in geometry['physical_sections'] for key in ('start_node', 'end_node')}
                self.assertTrue(all(t['node'] in nodes for t in profile['terminals']))

    def test_manual_turn_redistribution_preserves_wiring_and_terminal_evidence(self):
        config = self.manual()
        winding = config['winding_config']
        pair = [s for s in winding['layer_plan'] if s['winding_id'] == 'OUT1']
        pair[0]['turns'] -= 1
        pair[1]['turns'] += 1
        original = deepcopy(config)
        old = deepcopy(winding['model_3d'])
        result = self.prepare(config)
        self.assertEqual(config, original)
        geometry = self.assert_current_membership(result)
        new = result['config']['winding_config']['model_3d']
        for name in ('ports', 'terminals', 'leads'):
            self.assertEqual(new[name], old[name])
        for row in winding['layer_plan']:
            sid = row['section_id']
            self.assertEqual(new['sections'][sid], dict(old['sections'][sid], turns=row['turns']))
        self.assertTrue(all(s['direction'] == 'cw' and s['status'] == 'confirmed'
                            for s in geometry['physical_sections']))
        self.assert_sync_notice(result)

    def test_manual_section_deletion_or_reassignment_stays_blocked(self):
        base = self.manual()
        for edit in ('delete', 'reassign'):
            with self.subTest(edit=edit):
                config = deepcopy(base)
                plan = config['winding_config']['layer_plan']
                if edit == 'delete':
                    removed = plan.pop()
                    sid = removed['section_id']
                    next(s for s in plan if s['winding_id'] == removed['winding_id'])['turns'] += removed['turns']
                else:
                    source = next(s for s in plan if s['winding_id'] == 'P')
                    target = next(s for s in plan if s['winding_id'] == 'OUT1')
                    sid = target['section_id']
                    source['winding_id'], target['winding_id'] = target['winding_id'], source['winding_id']
                original = deepcopy(config)
                with self.assertRaisesRegex(ValueError, sid):
                    self.prepare(config)
                self.assertEqual(config, original)

    def test_position_and_insulation_edit_preserves_existing_wiring(self):
        prepared = self.canonical()
        before_geometry, _ = self.geometry(prepared)
        config = prepared['config']
        winding = config['winding_config']
        profile = deepcopy(winding['model_3d'])
        section = before_geometry['physical_sections'][0]
        bundle = section['bundles'][2]
        center = bundle['center_uv_m'][0] + .02e-3
        winding['turn_positions'] = {section['section_id']: {'3:1': center}}
        winding['layer_insulation'] += .02e-3
        winding['interwinding_insulation'] += .03e-3
        original = deepcopy(config)
        result = self.prepare(config)
        self.assertEqual(config, original)
        after = self.assert_current_membership(result)
        for name in ('sections', 'ports', 'terminals', 'leads'):
            self.assertEqual(result['config']['winding_config']['model_3d'].get(name), profile.get(name))
        self.assertAlmostEqual(after['physical_sections'][0]['bundles'][2]['center_uv_m'][0], center)
        self.assertNotEqual(after['source']['geometry_sha256'], before_geometry['source']['geometry_sha256'])
        self.assertEqual(result['config']['winding_config']['turn_positions'], winding['turn_positions'])
        self.assertEqual(result['config']['winding_config']['layer_insulation'], winding['layer_insulation'])

    def test_unprepared_resolver_and_old_solver_settings_remain_strict(self):
        before = self.canonical()
        config = deepcopy(before['config'])
        pair = [s for s in config['winding_config']['layer_plan'] if s['winding_id'] == 'OUT1']
        pair[0]['turns'] -= 1
        pair[1]['turns'] += 1
        run = _calculate(config, None)
        with self.assertRaisesRegex(ValueError, pair[0]['section_id']):
            resolve_geometry(run.runtime_bundle()['cases'], '0' * 64, '0' * 64, 'strict-test')
        after = self.prepare(config)
        _, package = self.geometry(after)
        with self.assertRaises(ValueError):
            bind_solver_project(package, before['project_file'], self.root / 'old-settings-rejected')

    @unittest.skipUnless((ROOT / 'examples/90W_QR_L6565_252_442V.json').exists(),
                         'Optional local QR geometry is not distributed')
    def test_local_qr_redistribution_prepares_current_geometry_without_rewriting_source(self):
        path = ROOT / 'examples/90W_QR_L6565_252_442V.json'
        original_bytes = path.read_bytes()
        config = strict_json(original_bytes)
        winding = config['winding_config']
        primary = [s for s in winding['layer_plan'] if s['winding_id'] == 'P']
        primary[0]['turns'] -= 1
        primary[-1]['turns'] += 1
        original = deepcopy(config)
        frame = winding['model_3d']['frame']
        environment = dict(self.env, r0_m=frame['r0_m_if_circular'], z0_m=frame['z0_m'])
        result = self.prepare(config, environment)
        self.assertEqual(config, original)
        self.assertEqual(path.read_bytes(), original_bytes)
        geometry = self.assert_current_membership(result)
        original_profile = winding['model_3d']
        updated_profile = result['config']['winding_config']['model_3d']
        for name in ('ports', 'terminals', 'leads'):
            self.assertEqual(updated_profile[name], original_profile[name])
        physical = {s['section_id']: s for s in geometry['physical_sections']}
        for row in winding['layer_plan']:
            section = physical[row['section_id']]
            self.assertEqual(section['turns'], row['turns'])
            old = original_profile['sections'][row['section_id']]
            for name in ('start_node', 'end_node', 'dot_node', 'direction'):
                self.assertEqual(section[name], old[name])
        self.assert_sync_notice(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
