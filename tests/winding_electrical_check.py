"""Automatic transformer DCR and frozen-gauge coupled-solve regressions."""
import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, compute_operating_point
from loss_model import compute_design
from winding_coupling import (default_coupling_config, resolve_winding_geometry,
                              resolve_winding_model)


def parameters():
    p = copy.deepcopy(DEFAULT_PARAMS)
    p.update(topology='FLYBACK', feedback_mode='SSR', feedback_output=1,
             Np=6, Ns=12, MLT=.04,
             outputs=[dict(V_out=30, P_out=30, Ns=12, d_wire_s=.0001, n_strand_s=30),
                      dict(V_out=999, P_out=.5, Ns=5, d_wire_s=.0001, n_strand_s=2),
                      dict(V_out=999, P_out=1, Ns=2, d_wire_s=.0001, n_strand_s=3)],
             coupling_config=default_coupling_config(3))
    p['coupling_config']['enabled'] = True
    return p


class GeometryDcrChecks(unittest.TestCase):
    def test_every_winding_uses_bare_copper_length_over_parallel_area(self):
        p = parameters()
        before = copy.deepcopy(p)
        model = resolve_winding_model(p)
        hw = model['transformer_hardware']
        expected = [p['rho'] * hw['copper_length_m'] /
                    (hw['n_strand_p'] * math.pi * hw['d_wire_p'] ** 2 / 4)]
        expected += [p['rho'] * w['copper_length_m'] /
                     (w['n_strand_s'] * math.pi * w['d_wire_s'] ** 2 / 4)
                     for w in hw['windings']]
        np.testing.assert_allclose(model['R'], expected, rtol=1e-13)
        self.assertEqual(model['dcr_source'], 'geometry')
        self.assertEqual(p, before)

    def test_legacy_mlt_is_ignored_and_wire_dimensions_change_dcr(self):
        p = parameters()
        reference = resolve_winding_model(p)
        old = reference['transformer_hardware']
        q = copy.deepcopy(p); q['MLT'] *= 2
        np.testing.assert_array_equal(resolve_winding_model(q)['R'], reference['R'])
        q = copy.deepcopy(p); q['d_wire_p'] *= 2
        new = resolve_winding_model(q)['transformer_hardware']
        self.assertAlmostEqual(new['R_dc_p'] / new['copper_length_m'], old['R_dc_p'] / (4 * old['copper_length_m']))
        q = copy.deepcopy(p); q['outputs'][1]['n_strand_s'] *= 2
        before = old['windings'][1]
        after = resolve_winding_model(q)['transformer_hardware']['windings'][1]
        self.assertAlmostEqual(after['R_dc'] / after['copper_length_m'], before['R_dc'] / (2 * before['copper_length_m']))

    def test_legacy_dcr_is_inactive_including_invalid_saved_entries(self):
        p = parameters()
        reference = resolve_winding_model(p)['R']
        for old in ([99, 88, 77, 66], [-1], 'old draft value', [True, None]):
            q = copy.deepcopy(p); q['coupling_config']['dcr'] = old
            np.testing.assert_array_equal(resolve_winding_model(q)['R'], reference)

    def test_missing_user_layout_uses_the_standard_core_geometry(self):
        p = parameters(); p['MLT'] = 0
        model = resolve_winding_model(p)
        hw = model['transformer_hardware']
        self.assertEqual(hw['winding_lengths']['method'], 'core_geometry')
        self.assertEqual(hw['MLT'], hw['winding_lengths']['windings']['P']['mlt_m'])
        self.assertEqual(len({w['MLT'] for w in hw['windings']}), 3)

    def test_fixed_hardware_geometry_is_not_resized_at_another_load(self):
        p = parameters()
        p.update(d_wire_p=0., d_wire_s=0.)
        for rail in p['outputs']: rail['d_wire_s'] = 0.
        nominal = compute_operating_point(dict(p, coupling_config=dict(enabled=False)))
        original = resolve_winding_geometry(p, nominal)
        q = copy.deepcopy(p)
        q['_fixed_transformer'] = copy.deepcopy(original)
        for rail, winding in zip(q['outputs'], original['windings']):
            rail.update(Ns=winding['Ns'], d_wire_s=winding['d_wire_s'],
                        n_strand_s=winding['n_strand_s'], P_out=rail['P_out'] * .5)
        other = compute_operating_point(dict(q, coupling_config=dict(enabled=False)))
        fixed = resolve_winding_geometry(q, other)
        self.assertEqual(fixed['core'], original['core'])
        self.assertEqual(fixed['Np'], original['Np'])
        self.assertEqual(fixed['R_dc_p'], original['R_dc_p'])
        self.assertEqual([w['R_dc'] for w in fixed['windings']],
                         [w['R_dc'] for w in original['windings']])

    def test_single_fixed_hardware_secondary_does_not_resize_at_half_load(self):
        p=copy.deepcopy(DEFAULT_PARAMS)
        p.update(Np=6,Ns=12,d_wire_p=0.,d_wire_s=0.)
        original=resolve_winding_geometry(p,compute_operating_point(p))
        q=dict(p,_fixed_transformer=copy.deepcopy(original),P_out=p['P_out']*.5)
        fixed=resolve_winding_geometry(q,compute_operating_point(q))
        for key in ('core','MLT','Np','Ns','d_wire_p','d_wire_s',
                    'n_strand_p','n_strand_s','R_dc_p','R_dc_s'):
            self.assertEqual(fixed[key],original[key],key)
        self.assertEqual(fixed['windings'][0]['R_dc'],original['windings'][0]['R_dc'])

    def test_qr_bobbin_radius_changes_geometry_once_for_both_endpoints(self):
        import json
        from design_engine.service import calculate
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root/'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_text(encoding='utf-8'))

        def run(spec):
            cases = calculate(spec, analysis='endpoints', include_loop=False,
                              include_cross_regulation=False).runtime_bundle()['cases']
            self.assertEqual(len(cases), 2)
            self.assertTrue(all(case['error'] is None for case in cases), [case['error'] for case in cases])
            records = [case['result']['mag']['transformer'] for case in cases]
            self.assertEqual(records[0]['winding_lengths'], records[1]['winding_lengths'])
            return records[0]

        original = run(p)
        changed = copy.deepcopy(p)
        changed['winding_config']['model_3d']['frame']['r0_m_if_circular'] += .00025
        enlarged = run(changed)
        self.assertEqual(original['winding_lengths']['method'], 'winding_geometry')
        self.assertGreater(enlarged['MLT'], original['MLT'])
        self.assertGreater(enlarged['R_dc_p'], original['R_dc_p'])
        self.assertTrue(all(after['R_dc'] > before['R_dc']
                        for before, after in zip(original['windings'], enlarged['windings'])))

    def test_psr_aux_winding_has_separate_copper_length(self):
        import json
        from design_engine.specification import load_spec
        root = Path(__file__).resolve().parents[1]
        p = load_spec(json.loads((root/'examples/MP6005_PSR_FLYBACK.json').read_text(encoding='utf-8')))
        item = compute_design(p)['mag']['transformer']
        aux = item['auxiliary']
        length = item['winding_lengths']['windings']['AUX']
        self.assertEqual(length['turns'], aux['Na'])
        self.assertEqual(length['mlt_m'], aux['MLT'])
        self.assertAlmostEqual(aux['R_dc'], p['rho']*length['length_m']/(math.pi*aux['d_wire']**2/4))


class IdealGeometryChecks(unittest.TestCase):
    def assert_ideal_hardware(self,p):
        before=copy.deepcopy(p)
        result=compute_design(p)
        self.assertEqual(p,before)
        op=result['op']; meta=op['coupled_model']
        hardware=meta['transformer_hardware']; tr=result['mag']['transformer']
        self.assertTrue(meta['ideal_fallback'])
        self.assertNotIn('coupled_solution',op)
        self.assertEqual(meta['L_leak'],0.)
        self.assertEqual(result['P_rcd'],0.)
        for key in ('core','MLT','Np','Ns','d_wire_p','d_wire_s',
                    'n_strand_p','n_strand_s','R_dc_p','R_dc_s'):
            if key.startswith('R_dc'):
                self.assertAlmostEqual(tr[key],hardware[key],places=13,msg=key)
            else:
                self.assertEqual(tr[key],hardware[key],key)
        self.assertAlmostEqual(meta['R'][0],tr['R_dc_p'],places=13)
        self.assertAlmostEqual(meta['ratios'][1],tr['Np']/hardware['windings'][0]['Ns'])
        if op.get('outputs'):
            for i,(child,winding) in enumerate(zip(op['output_ops'],tr['windings']),1):
                self.assertAlmostEqual(meta['ratios'][i],child['N'])
                self.assertAlmostEqual(meta['R'][i],winding['R_dc'],places=13)
                self.assertEqual(winding['d_wire_s'],hardware['windings'][i-1]['d_wire_s'])
        else:
            self.assertAlmostEqual(op['N'],meta['ratios'][1])
            self.assertAlmostEqual(meta['R'][1],tr['R_dc_s'],places=13)
        return result

    def test_single_manual_turns_override_old_n_and_auto_gauges_stay_consistent(self):
        p=copy.deepcopy(DEFAULT_PARAMS)
        p.update(Np=6,Ns=10,N=.5,d_wire_p=0.,d_wire_s=0.)
        p['coupling_config']=dict(enabled=True,k=[[1.,1.],[1.,1.]])
        result=self.assert_ideal_hardware(p)
        self.assertAlmostEqual(result['op']['N'],.6)

    def test_auto_primary_and_secondary_resolve_once_in_single_and_multi_ideal(self):
        for multiple in (False,True):
            for ratio in (.37,.5,.83):
                with self.subTest(multiple=multiple,N=ratio):
                    p=copy.deepcopy(DEFAULT_PARAMS)
                    p.update(Np=0,Ns=0,N=ratio,d_wire_p=0.,d_wire_s=0.)
                    if multiple:
                        p.update(feedback_output=2,outputs=[
                            dict(V_out=30.,P_out=30.,Ns=0,d_wire_s=0.),
                            dict(V_out=12.,P_out=10.,Ns=0,d_wire_s=0.)])
                    count=2 if multiple else 1
                    p['coupling_config']=dict(enabled=True,k=np.ones((count+1,count+1)).tolist())
                    predesign=resolve_winding_model(p)['transformer_hardware']
                    result=self.assert_ideal_hardware(p)
                    self.assertEqual(result['mag']['transformer']['Np'],predesign['Np'])
                    self.assertEqual([w['Ns'] for w in result['op']['coupled_model']['transformer_hardware']['windings']],
                                     [w['Ns'] for w in predesign['windings']])


class CoupledGeometryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = parameters()
        cls.p.update(d_wire_p=0., d_wire_s=0.)
        for rail in cls.p['outputs']: rail['d_wire_s'] = 0.
        cls.result = compute_design(cls.p)

    def test_solver_and_display_use_identical_frozen_conductors_and_dcr(self):
        result = self.result
        meta = result['op']['coupled_model']
        hw, tr = meta['transformer_hardware'], result['mag']['transformer']
        self.assertEqual(meta['auto_wire_sizing'], 'nominal-predesign-frozen')
        self.assertEqual(tr['dcr_source'], 'geometry')
        self.assertEqual(tr['d_wire_p'], hw['d_wire_p'])
        self.assertEqual(tr['Np'], hw['Np'])
        self.assertAlmostEqual(tr['R_dc_p'], meta['R'][0], places=13)
        self.assertAlmostEqual(tr['R_dc_p'], tr['R_dc_p_geometry'], places=13)
        for i, (w, frozen) in enumerate(zip(tr['windings'], hw['windings']), 1):
            self.assertEqual(w['d_wire_s'], frozen['d_wire_s'])
            self.assertEqual(w['Ns'], frozen['Ns'])
            self.assertEqual(w['n_strand_s'], frozen['n_strand_s'])
            self.assertAlmostEqual(w['R_dc'], meta['R'][i], places=13)
            self.assertAlmostEqual(w['R_dc'], w['R_dc_geometry'], places=13)

    def test_current_density_uses_actual_winding_rms_not_nominal_target_j(self):
        result = self.result
        tr, meta = result['mag']['transformer'], result['op']['coupled_model']
        area = tr['n_strand_p'] * math.pi * tr['d_wire_p'] ** 2 / 4
        self.assertAlmostEqual(tr['J_actual_p'], meta['winding_rms'][0] / area)
        for i, winding in enumerate(tr['windings'], 1):
            area = winding['n_strand_s'] * math.pi * winding['d_wire_s'] ** 2 / 4
            self.assertAlmostEqual(winding['J_actual'], meta['winding_rms'][i] / area)
        self.assertTrue(any(abs(w['J_actual'] / self.p['J'] - 1) > .01
                            for w in tr['windings']))

    def test_automatic_dcr_energy_balance_and_loss_ledger_remain_single_counted(self):
        result = self.result
        tr, meta = result['mag']['transformer'], result['op']['coupled_model']
        expected = tr['Fr_p'] * meta['R'][0] * meta['winding_rms'][0] ** 2
        expected += sum(w['Fr'] * r * i ** 2 for w, r, i in
                        zip(tr['windings'], meta['R'][1:], meta['winding_rms'][1:]))
        self.assertAlmostEqual(tr['P_cu'], expected, places=10)
        self.assertAlmostEqual(result['P_mag'], tr['P_cu'] + tr['P_core'], places=10)
        self.assertLess(meta['energy_balance_relative'], 1e-5)
        ledger = sum(result[key] for key in ('P_semi', 'P_mag', 'P_cap', 'P_cap_in',
            'P_sense', 'P_rcd', 'P_din', 'P_dout', 'P_clamp', 'P_controller'))
        self.assertAlmostEqual(result['P_total'], ledger, places=10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
