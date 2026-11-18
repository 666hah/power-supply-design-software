"""COT cadence PI, common-mode power stage and feasible automatic tuning."""

import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

import numpy as np

from capacitor_banks import bank
from cot_buck import compute_operating_point
from cot_loop import controller_gains, tune
from design_engine.specification import load_spec
from loop_tuning import analyze_loop, plant_phase_unwrapped
from plants import build_loop_models


def spec(**overrides):
    return load_spec(dict(topology='BUCK', control_mode='Constant On-Time', V_in=12., V_out=3.,
                          P_out=48., L=10e-6, f_sw=300e3, buck_phases=4,
                          Rds_on=.015, Rds_aux=.010, Rs=.002, inductor_dcr=.006,
                          d_in_enable=True, Vf_din=.25, d_out_enable=True, Vf_dout=.30,
                          inductor_design_enabled=False) | overrides)


class CotLoopChecks(unittest.TestCase):
    def test_multi_branch_power_stage_matches_impedance_formula(self):
        branches = [dict(C=330e-6, ESR=.022, ESL=5e-9),
                    dict(C=22e-6, ESR=0., ESL=0.),
                    dict(C=47e-6, ESR=.03, ESL=30e-9)]
        for phases, enable_esl, ton in ((1, 0, 0.), (4, 1, 0.), (16, 1, 1e-6)):
            with self.subTest(phases=phases, include_esl=enable_esl):
                rows = branches if phases != 16 else branches[::2]
                p = spec(buck_phases=phases, cot_ton_s=ton, output_capacitors=rows,
                         cot_kp_hz=50000., cot_ki_hz_per_s=8e8,
                         spice_config={'include_cap_esl': enable_esl})
                op = compute_operating_point(p)
                (plant, pi, loop), info = build_loop_models(p, op)
                self.assertEqual(info.loop_metadata['esl_included'], bool(enable_esl))
                self.assertEqual(len(info.loop_metadata['capacitor_banks'][0]['branches']), len(rows))
                self.assertEqual(info.loop_metadata['frequency_limit'], op['f_sw']/10)
                self.assertEqual(info.loop_metadata['feedback_voltage_V'], 3.3)
                load = p['V_out']**2/p['P_out']
                rh, rl = p['Rds_on']+p['Rs'], p['Rds_aux']
                r_avg = (op['D']*rh+op['Dp']*rl+p['inductor_dcr'])/phases
                dv = p['V_in']-p['Vf_din']-(rh-rl)*p['P_out']/p['V_out']/phases
                t_on = ton or (p['V_out']+p['Vf_dout'])/((p['V_in']-p['Vf_din'])*p['f_sw'])
                self.assertAlmostEqual(float(np.real(plant(0.))), dv*t_on*load/(load+r_avg), places=13)
                s = 2j*np.pi*np.array([57., 600., 2900., 10000.])
                admittance = sum(1/(1/(s*row['C'])+row['ESR']+s*row['ESL']*enable_esl) for row in rows)
                z_out = 1/(1/load+admittance)
                impedance_l = s*p['L']/phases+r_avg
                expected_plant = t_on*dv*z_out/(impedance_l+z_out)
                expected_pi = (p['cot_kp_hz'] + p['cot_ki_hz_per_s']/s)/3.3
                np.testing.assert_allclose(plant(s), expected_plant, rtol=1e-10)
                np.testing.assert_allclose(pi(s), expected_pi, rtol=1e-10)
                np.testing.assert_allclose(loop(s), expected_plant*expected_pi, rtol=1e-10)
                # A load-current sink drives the parallel impedance of the
                # capacitor bank, load resistance, and phase inductors.
                expected_load = -z_out*impedance_l/(impedance_l+z_out)
                np.testing.assert_allclose(plant._load_disturbance(s), expected_load, rtol=1e-10)

    def test_ideal_current_load_excludes_impulsive_all_esl_step(self):
        p = spec(output_capacitors=[dict(C=330e-6, ESR=.022, ESL=5e-9)],
                 cot_config={'load_mode': 'current'}, spice_config={'include_cap_esl': 1})
        plant = build_loop_models(p, compute_operating_point(p))[0][0]
        self.assertFalse(hasattr(plant, '_load_disturbance'))
        self.assertIn('冲激', plant._load_response_unavailable_reason)

    def test_default_tuning_and_unavailable_goals(self):
        p = spec()
        op = compute_operating_point(p)
        gains = controller_gains(p, op)
        f_lc = 1/(2*math.pi*math.sqrt(p['L']*sum(r['C'] for r in bank(p))/4))
        self.assertEqual(gains, (.15*p['f_sw'], 2*math.pi*p['f_sw']*min(800., p['f_sw']/50, f_lc/10)))
        models, _ = build_loop_models(p, op)
        scan = analyze_loop(p, models, op)
        self.assertTrue(scan['closed_loop_stable'])
        self.assertTrue(scan['gm_band_limited'])
        self.assertFalse(scan['gm_infinite'])
        phases = plant_phase_unwrapped(models[0], 500.)
        for target in (90.+phases, 95.+phases):
            tuned = tune(p, op, 500., target)
            self.assertAlmostEqual(tuned['fc'], 500., delta=.5)
            self.assertAlmostEqual(tuned['pm'], target, delta=.1)
            self.assertIs(type(tuned['cot_kp_hz']), float)
            self.assertIs(type(tuned['cot_ki_hz_per_s']), float)
            self.assertGreater(tuned['cot_ki_hz_per_s'], 0.)
            if target == 90.+phases:
                self.assertEqual(tuned['cot_kp_hz'], 0.)
        with self.assertRaisesRegex(ValueError, '可达到'):
            tune(p, op, 500., 60.)
        with self.assertRaisesRegex(ValueError, '1/20'):
            tune(p, op, op['f_sw']/10, 70.)
        self.assertEqual(p['cot_kp_hz'], 0.)
        self.assertEqual(p['cot_ki_hz_per_s'], 0.)

    def test_saturation_and_missing_manual_integral_are_reported(self):
        p = spec()
        op = compute_operating_point(p)
        saturated = dict(op, cot=dict(op['cot'], min_off_s=op['cot']['toff_s']))
        with self.assertRaisesRegex(ValueError, '最小关断时间'):
            build_loop_models(p, saturated)
        with self.assertRaisesRegex(ValueError, 'Ki'):
            spec(cot_kp_hz=1.)
        with self.assertRaisesRegex(ValueError, '非负数'):
            spec(cot_kp_hz=-1., cot_ki_hz_per_s=1.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
