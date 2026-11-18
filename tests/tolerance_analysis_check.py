"""Fixed-design tolerance sweeps and the distinction between 4σ statistics and tails."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

import numpy as np

from calculation_scheduler import CalculationCancelled
from design_engine.specification import load_spec
from tolerance_analysis import analyze, available_variables
from tolerance_statistics import normalize_variables, sample_variables, summarize_samples


class ToleranceChecks(unittest.TestCase):
    def test_distribution_seed_and_tail_reporting(self):
        variables = normalize_variables([
            dict(path='a', nominal=5., low=1., high=9., distribution='uniform', group='lot'),
            dict(path='b', nominal=2., low=1., high=3., distribution='triangular', group='lot'),
            dict(path='c', nominal=5., low=4., high=7., distribution='normal', sigma=1.),
        ])
        samples = sample_variables(variables, 1500, 32)
        np.testing.assert_array_equal(samples, sample_variables(variables, 1500, 32))
        np.testing.assert_array_equal(np.argsort(samples[:, 0]), np.argsort(samples[:, 1]))
        self.assertTrue(np.all((4 <= samples[:, 2]) & (samples[:, 2] <= 7)))
        r = summarize_samples(samples[:, 0], 1500)
        self.assertIsNone(r['quantile_4sigma_high'])
        self.assertEqual(r['tail_status'], 'insufficient_samples')
        self.assertGreater(r['moment_4sigma_high'], r['percentile_95'])
        self.assertEqual(sum(r['histogram']['counts']), 1500)
        self.assertEqual(summarize_samples(samples[:, 0], 1501)['tail_status'], 'incomplete')
        count = 640_000
        large = summarize_samples(np.linspace(0., 1., count), count)
        self.assertEqual(large['tail_status'], 'available')
        self.assertAlmostEqual(large['quantile_4sigma_high'], 0.9999683, places=6)

    def test_actual_qr_corners_keep_input_and_probe_each_virtual_unit(self):
        inputs = load_spec(json.loads((ROOT/'examples/90W_QR_L6565_252_442V_REFERENCE.json').read_text('utf-8')))
        before = json.dumps(inputs, ensure_ascii=False, sort_keys=True)
        options = {row['path']: row for row in available_variables(inputs)}
        name = 'outputs.0.output_capacitors.0.C'
        nominal = options[name]['nominal']
        study = analyze(inputs, [dict(path=name, low=.8*nominal, high=1.2*nominal, distribution='uniform')],
                        samples=7, load_fracs=(1.,))
        self.assertEqual(json.dumps(inputs, ensure_ascii=False, sort_keys=True), before)
        self.assertEqual(study['evaluations'], 30)
        self.assertEqual(study['failure_count'], 0)
        self.assertEqual({case['voltage'] for case in study['conditions']}, {252., 347., 442.})
        rows = {row['id']: row for row in study['rows']}
        ripple = rows['OUT1_ripple']
        self.assertEqual(ripple['case']['parameters'][name], .8*nominal)
        self.assertEqual(ripple['statistics']['count'], 7)
        self.assertEqual(rows['vds_peak']['case']['voltage'], 442.)
        self.assertEqual(rows['vds_peak']['status'], 'review')
        self.assertAlmostEqual(rows['vds_peak']['margin'], rows['vds_peak']['limit']-rows['vds_peak']['worst'])
        json.dumps(study, allow_nan=False)

    def test_budget_distribution_and_cancel(self):
        inputs = load_spec({})
        nominal = inputs['Rds_on']
        bounds = dict(path='Rds_on', low=.8*nominal, high=1.2*nominal, distribution='bounds')
        with self.assertRaisesRegex(ValueError, '声明分布'):
            analyze(inputs, [bounds], samples=10)
        with self.assertRaisesRegex(ValueError, '超过上限'):
            analyze(inputs, [bounds], max_evaluations=2)
        with self.assertRaises(CalculationCancelled):
            analyze(inputs, [bounds], cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
