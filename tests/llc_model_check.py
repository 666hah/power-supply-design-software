"""Cross-check the LLC periodic solver and both physical control models."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.integrate import trapezoid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llc_model import HYBRID_MODE, VOLTAGE_MODE, build_loop, fha_gain, solve
from loop_tuning import analyze_loop


SPEC = dict(V_in=390., V_out=48., P_out=300., N=4., C_out=.001, Rc=.020,
            Rds_on=.09, Coss=200e-12, Vf_diode=.55, f_sw=100e3)


class LLCModelChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for bridge, turns in (('half', 4.), ('full', 8.)):
            for control in (VOLTAGE_MODE, HYBRID_MODE):
                spec = dict(SPEC, llc_bridge=bridge, control_mode=control, N=turns)
                cls.results[bridge, control] = spec, solve(spec)

    def test_periodic_power_and_rectifier_charge_balance(self):
        for (bridge, control), (_, op) in self.results.items():
            with self.subTest(bridge=bridge, control=control):
                self.assertTrue(op['regulation_ok'])
                self.assertAlmostEqual(op['output_voltage_V'], 48., delta=.001)
                self.assertLess(op['residual'], 2.1e-6)
                t = op['time_s']
                irect = trapezoid(op['i_rect_A'], t)/op['period_s']
                self.assertAlmostEqual(irect, op['output_current_A'], delta=.015)
                tank_power = trapezoid(op['v_drive_V']*op['i_res_A'], t)/op['period_s']
                circuit_power = op['input_power_W'] - op['loss_W']['gate_drive']
                self.assertAlmostEqual(tank_power, circuit_power, delta=1.2)
                self.assertGreater(op['ir_peak_A'], op['ir_rms_A'])
                self.assertTrue(op['zvs_ok'])

    def test_actual_bridge_voltages_and_half_bridge_cap_bias(self):
        for bridge, multiplier in (('half', .5), ('full', 1.)):
            _, op = self.results[bridge, VOLTAGE_MODE]
            np.testing.assert_allclose(np.max(abs(op['v_drive_V'])), multiplier*SPEC['V_in'], rtol=1e-10)
            np.testing.assert_allclose(op['v_cr_V']-op['v_res_V'],
                SPEC['V_in']/2 if bridge == 'half' else 0.)
            self.assertEqual(op['switch_peak_V'], SPEC['V_in'])

    def test_two_real_actuators_and_stable_auto_loop(self):
        for (bridge, control), (spec, op) in self.results.items():
            with self.subTest(bridge=bridge, control=control):
                if control == HYBRID_MODE:
                    self.assertAlmostEqual(op['hhc_turnoff_s'], .5/op['frequency_Hz'], delta=20e-9)
                    self.assertGreater(op['hhc_crossing_slew_V_per_s'], 0.)
                models, info = build_loop(spec, op)
                self.assertIsNotNone(models[0]._load_disturbance)
                self.assertGreater(float(np.real(models[0](0.))), 0.)
                self.assertLess(info.loop_metadata['inner_spectral_radius'], 1.)
                scan = analyze_loop(spec, models, n=1600)
                self.assertTrue(scan['closed_loop_stable'])
                self.assertGreater(scan['pm'], 45.)

    def test_frequency_limit_and_overcurrent_mark_availability(self):
        constrained = solve(dict(SPEC, llc_fmin=155e3, llc_fmax=165e3))
        self.assertFalse(constrained['regulation_ok'])
        self.assertFalse(constrained['loop_valid'])
        with self.assertRaises(ValueError):
            build_loop(SPEC, constrained)
        limit = solve(dict(SPEC, llc_ocp=.2))
        self.assertFalse(limit['regulation_ok'])
        self.assertTrue(limit['protection_hit'])

    def test_instant_opposite_rectifier_commutation_keeps_clamp(self):
        # A deliberately mismatched ratio drives large resonant current. The
        # report must retain OCP and avoid a fictitious floating-node spike.
        op = solve(dict(SPEC, N=.5, llc_ocp=8.))
        self.assertTrue(op['protection_hit'])
        self.assertLess(op['rectifier_reverse_peak_V'], 60.)

    def test_fha_series_resonance_unity_ideal_gain(self):
        lr, cr, lm = 50e-6, 50.66e-9, 250e-6
        frequency = 1/(2*np.pi*np.sqrt(lr*cr))
        self.assertAlmostEqual(float(fha_gain(frequency, lr, cr, lm, 100.)), 1., places=10)

    def test_examples_have_one_complete_hardware_and_loop_design_per_voltage_range(self):
        from design_engine.specification import load_spec
        from input_voltage_range import calculate_input_endpoints

        examples = Path(__file__).resolve().parents[1] / 'examples'
        for name, primary_turns, tank_turns in (('HALF_HHC',24,28), ('FULL_VCO',48,50)):
            with self.subTest(example=name):
                path = examples / f'300W_LLC_{name}.json'
                p = load_spec(json.loads(path.read_text(encoding='utf-8')))
                self.assertTrue(p['winding_config']['layer_plan'])
                self.assertGreater(p['llc_ki'], 0.)
                self.assertEqual(len(p['output_capacitors']), 4)
                components = p['component_management']['items']
                for ref in ('T1','L_R','U_CTRL','U_FB','C_R','C_IN3','C_O4'):
                    self.assertTrue(components[ref]['model'], ref)
                result = calculate_input_endpoints(p, include_cross_regulation=False)
                self.assertTrue(result['fixed_hardware'])
                for case in result['cases']:
                    self.assertIsNone(case['error'])
                    self.assertEqual((case['p']['llc_kp'],case['p']['llc_ki']), (p['llc_kp'],p['llc_ki']))
                    solved = case['result']
                    transformer, tank = solved['mag']['transformer'], solved['mag']['inductor']
                    self.assertEqual((transformer['Np'],transformer['Ns'],tank['N']), (primary_turns,6,tank_turns))
                    self.assertLess(transformer['dT'],40.)
                    self.assertLess(tank['B_design_peak_T'],p['Bmax'])
                    self.assertGreaterEqual(tank['design_peak_A'],p['llc_ocp'])
                    self.assertTrue(solved['loop']['closed_loop_stable'])
                    self.assertGreaterEqual(solved['loop']['min_pm'], 64.)
                light_high = solve(dict(p,V_in=p['V_in_max'],P_out=p['P_out_min']))
                self.assertTrue(light_high['regulation_ok'])
                self.assertTrue(light_high['zvs_ok'])


if __name__ == '__main__':
    unittest.main()
