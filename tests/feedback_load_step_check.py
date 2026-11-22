"""Verify signed closed-loop load-step propagation and rail selection."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import control as ct
import numpy as np

from loop_load_step import _closed_loop, _step_samples, closed_loop_load_ports, feedback_load_step


class FeedbackLoadStepChecks(unittest.TestCase):
    def test_negative_feedback_matches_the_load_impedance_formula(self):
        plant = ct.ss([[-300]], [[80, -150]], [[1.5]], [[.04, -.012]])
        comp = ct.ss([[0]], [[20]], [[1]], [[.8]])
        a, b, c, d = _closed_loop(plant, comp)
        closed = ct.ss(a, b[:, None], c[None, :], [[d]])
        for s in (10j, 280j, 1200j):
            expected = plant[0, 1](s) / (1 + plant[0, 0](s)*comp(s))
            self.assertAlmostEqual(closed(s), expected)
        time, step, dc = _step_samples(a, b, c, d, 100e3)
        self.assertLess(step[0], 0)
        self.assertAlmostEqual(dc, 0)
        self.assertTrue(np.all(np.diff(time) > 0))
        _, reference = ct.step_response(closed, np.linspace(0, time[-1], 2001))
        self.assertAlmostEqual(step[-1], reference[-1], places=10)

    def test_feedback_output_sets_load_range_and_sampled_voltage(self):
        full = ct.ss([[-60, 0], [0, -100]], [[20, -10, -900], [30, -550, -50]],
                     np.eye(2), [[0, -.4, -.8], [0, -.7, -.02]])
        gvc = full[1, 0]
        gvc._multi_output_system = full
        loop = (gvc, ct.tf([10], [1, 0]), None)
        p = {'f_sw': 100e3, 'feedback_output': 2}
        outputs = [{'V_out': 50, 'P_out': 500}, {'V_out': 12, 'P_out': 24}]
        op = {**p, 'outputs': outputs, 'output_ops': [{}, {'V_out': 11.9, 'I_out': 1.9}]}
        result = feedback_load_step(p, loop, op)
        self.assertTrue(result['available'])
        self.assertEqual(result['feedback_output'], 2)
        self.assertEqual((result['current_low_A'], result['current_high_A']), (.2, 1.8))
        self.assertEqual(result['rise_voltage_V'][0], 11.9)
        self.assertAlmostEqual(result['rise_delta_V'][2], -.02*1.6)
        self.assertAlmostEqual(result['fall_delta_V'][2], .02*1.6)
        np.testing.assert_allclose(result['rise_delta_V'], -result['fall_delta_V'])
        self.assertAlmostEqual(result['rise']['final_voltage_V'], 11.9)
        self.assertGreater(result['rise']['settling_s'], 0)

    def test_coupled_load_ports_keep_independent_and_cross_responses(self):
        plant = ct.ss([[-60, 0], [0, -100]], [[20, -10, -900], [30, -550, -50]],
                      np.eye(2), [[.07, -.4, -.8], [.04, -.7, -.02]])
        comp = ct.ss([[0]], [[20]], [[1]], [[.8]])
        a, b, c, d = closed_loop_load_ports(plant, comp, feedback_index=1)
        model = ct.ss(a, b, c, d)
        for s in (10j, 280j, 1200j):
            matrix = plant(s)
            gain = comp(s)/(1+matrix[1, 0]*comp(s))
            expected = matrix[:, 1:]-np.outer(matrix[:, 0], gain*matrix[1, 1:])
            np.testing.assert_allclose(model(s), expected, atol=1e-12)
        _, step, dc = _step_samples(a, b, c, d, 100e3)
        self.assertEqual(step.shape[1:], (2, 2))
        np.testing.assert_allclose(dc[1], 0., atol=1e-10)
        self.assertGreater(abs(dc[0, 1]), .1)

    def test_proportional_controller_uses_distinct_loaded_equilibria(self):
        gvc = ct.tf([1], [1, 5])
        gvc._load_plant = ct.ss([[-5]], [[1, -1]], [[1]], [[0, 0]])
        op = {'V_out': 10, 'I_out': 5, 'f_sw': 100e3}
        result = feedback_load_step(op, (gvc, ct.tf([1], [1]), None), op)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['rise']['start_voltage_V'], 10.75)
        self.assertAlmostEqual(result['rise']['final_voltage_V'], 10+0.5/6)
        self.assertAlmostEqual(result['fall']['final_voltage_V'], 10.75)

    def test_unsupported_and_unstable_models_report_reasons(self):
        op = {'V_out': 12, 'I_out': 2, 'f_sw': 100e3}
        gvc = ct.tf([1], [1, -30])
        comp = ct.tf([1], [1])
        self.assertFalse(feedback_load_step(op, (gvc, comp, None), op)['available'])
        gvc._load_plant = ct.ss([[30]], [[1, -1]], [[1]], [[0, 0]])
        self.assertIn('不衰减', feedback_load_step(op, (gvc, comp, None), op)['reason'])


if __name__ == '__main__':
    unittest.main()
