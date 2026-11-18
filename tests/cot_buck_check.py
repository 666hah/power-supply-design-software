"""Synchronous COT and interleaved phase accounting."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

import numpy as np

from analysis_workflows import pin_hardware
from design_engine.specification import load_spec
from loss_model import compute_design
from semiconductor import device_stress


class CotBuckChecks(unittest.TestCase):
    def spec(self, **overrides):
        core = dict(topology='BUCK', control_mode='Constant On-Time', V_in=12.,
                    V_out=3., P_out=48., L=10e-6, f_sw=300e3, buck_phases=4,
                    Rds_on=0., Rds_aux=0., Rs=0., d_in_enable=False,
                    d_out_enable=False, inductor_design_enabled=False)
        return load_spec(core | overrides)

    def test_adaptive_and_ideal_four_phase_cancellation(self):
        p = self.spec()
        snapshot = compute_design(p)
        op, wf = snapshot['op'], snapshot['wf']
        self.assertAlmostEqual(op['cot']['ton_s'], .25/300e3)
        self.assertAlmostEqual(op['f_sw'], 300e3)
        self.assertAlmostEqual(op['I_L_avg'], 4.)
        self.assertEqual(wf['iL_phases'].shape[0], 4)
        self.assertEqual(op['cot']['total_output_current_ripple_A'], 0.)
        self.assertLess(np.ptp(wf['iL_total']), 1e-11)
        self.assertLess(wf['ripple_pp'], 1e-12)
        self.assertEqual(snapshot['semi']['n_diodes'], 0)
        self.assertEqual(set(device_stress(op)), {'switch', 'auxiliary'})
        at_overlap = compute_design(dict(p, buck_phases=16))['wf']
        np.testing.assert_array_equal(at_overlap['gate_phases'].sum(axis=0), 4)
        self.assertLess(np.ptp(at_overlap['iL_total']), 1e-11)

    def test_sixteen_phase_overlap_and_power_partition(self):
        p = self.spec(buck_phases=16, control_mode='Voltage Mode', V_out=3.1,
                      Rds_on=.01, Rds_aux=.008, Rs=.003, inductor_dcr=.002)
        snapshot = compute_design(p)
        op, wf, semi = snapshot['op'], snapshot['wf'], snapshot['semi']
        self.assertEqual(p['control_mode'], 'Constant On-Time')
        self.assertEqual(op['cot']['phases'], 16)
        self.assertTrue(op['cot']['overlap'])
        self.assertEqual(wf['iL_phases'].shape[0], 16)
        np.testing.assert_allclose(wf['iL_total'], wf['iL_phases'].sum(axis=0))
        np.testing.assert_allclose(wf['i_in'], (wf['iL_phases']*wf['gate_phases']).sum(axis=0))
        self.assertAlmostEqual(snapshot['P_mag'], 16*snapshot['mag']['inductor']['P_total'])
        self.assertAlmostEqual(snapshot['P_sense'], 16*p['Rs']*op['I_sw_rms']**2)
        self.assertAlmostEqual(snapshot['P_semi'], 16*sum(semi[k]['P_total'] for k in ('switch','auxiliary')))
        self.assertAlmostEqual(op['cot']['total_output_current_ripple_A'],
                               np.ptp(wf['iL_total']), delta=.003)
        frozen = pin_hardware(p, snapshot)
        self.assertEqual(frozen['_fixed_inductor']['inductor_dcr'], .002)

    def test_single_phase_fixed_ton_and_reverse_current(self):
        p = self.spec(buck_phases=1, P_out=.2, cot_ton_s=400e-9)
        snapshot = compute_design(p)
        op, wf = snapshot['op'], snapshot['wf']
        self.assertAlmostEqual(op['f_sw'], .25/400e-9)
        self.assertTrue(op['cot']['reverse_current'])
        self.assertLess(wf['i_low'].min(), 0.)
        with self.assertRaisesRegex(ValueError, '最小关断时间'):
            compute_design(dict(p, cot_min_off_s=1400e-9))

    def test_bounds(self):
        with self.assertRaisesRegex(ValueError, '整数'):
            self.spec(buck_phases=16.5)
        with self.assertRaisesRegex(ValueError, '适用于 Buck'):
            self.spec(topology='BOOST', buck_phases=2)

    def test_fixed_design_and_api_snapshot_serialize(self):
        from design_engine.service import calculate
        p = self.spec(inductor_design_enabled=True, V_in_min=10., V_in_max=14.)
        run = calculate(p, analysis='endpoints', include_loop=True, include_efficiency=False)
        left, right = run.runtime_bundle()['cases']
        self.assertEqual(left['result']['mag']['inductor']['N'], right['result']['mag']['inductor']['N'])
        self.assertEqual(left['result']['op']['cot']['phase_dcr_ohm'],
                         right['result']['op']['cot']['phase_dcr_ohm'])
        for case in (left, right):
            loop = case['result']['loop']
            self.assertEqual(loop['model']['kind'], 'cot-cadence-pi')
            self.assertIsNotNone(loop['fc'])
            self.assertIsNotNone(loop['pm'])
        json.dumps(run.reports())


if __name__ == '__main__':
    unittest.main(verbosity=2)
