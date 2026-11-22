"""Verify stress and compensation for the curated Buck, Boost and LLC upgrades."""

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_resources import configure_numeric_threads

configure_numeric_threads()

from component_management import evaluate_components
from design_engine.specification import load_spec
from input_voltage_range import calculate_input_endpoints
from web_app.metadata import read_example


class ExampleRatingMarginChecks(unittest.TestCase):
    def endpoints(self, spec):
        cases = calculate_input_endpoints(
            spec, include_loop=True, include_cross_regulation=False
        )['cases']
        for case in cases:
            self.assertIsNone(case['error'])
            self.assertIsNone(case['loop_error'])
        return cases

    def minimum_margin(self, cases, key):
        checks = [
            next(row for row in evaluate_components(case['p'], case['result'])['checks'] if row['id'] == key)
            for case in cases
        ]
        self.assertTrue(all(row['state'] == 'pass' for row in checks))
        return min(row['margin'] for row in checks)

    def check_phase_margin(self, cases, degrees):
        margins = [
            next(row for row in case['checks'] if row['id'] == 'phase_margin')
            for case in cases
        ]
        self.assertTrue(all(row['state'] == 'pass' and row['value'] >= degrees for row in margins))

    def test_single_phase_inductor_and_ripple_margins(self):
        for name, ripple_ref in (
            ('24W_BUCK_VM_TPS40200.json', 'C_IN1'),
            ('24W_BUCK_PCM_LTC3864.json', 'C_IN1'),
            ('24W_BUCK_CAP_IMPEDANCE.json', None),
            ('24W_BOOST_PCM_LM5022.json', 'C_O1'),
        ):
            with self.subTest(example=name):
                spec = load_spec(read_example(name))
                self.assertAlmostEqual(spec['L'], 47e-6)
                self.assertEqual(spec['inductor_dcr'], spec['spice_config']['niso_inductor_dcr'])
                self.assertEqual(spec['inductor_dcr'], 0.0469)
                cases = self.endpoints(spec)
                for case in cases:
                    peak = next(row for row in case['checks'] if row['id'] == 'inductor_peak')
                    self.assertGreater(peak['limit'] - peak['value'], 4.0)
                self.check_phase_margin(cases, 69.0)
                if ripple_ref:
                    self.assertGreater(self.minimum_margin(cases, f'bom_{ripple_ref}_ripple'), 1.7)
                else:
                    self.assertTrue(all(cap.get('impedance_curve') for cap in spec['output_capacitors']))

    def test_cot_input_cap_passes_with_same_derating_and_low_capacitance(self):
        spec = load_spec(read_example('96W_BUCK_COT_4PH.json'))
        self.assertTrue(all(cap['C'] == 330e-6 for cap in spec['input_capacitors']))
        reduced = copy.deepcopy(spec)
        for side in ('input_capacitors', 'output_capacitors'):
            for cap in reduced[side]:
                cap['C'] *= 0.9
        cases = self.endpoints(reduced)
        self.check_phase_margin(cases, 82.0)
        for index in range(1, 5):
            self.assertGreater(self.minimum_margin(cases, f'bom_C_IN{index}_voltage'), 6.0)
            self.assertGreater(self.minimum_margin(cases, f'bom_C_IN{index}_ripple'), 1.6)

    def test_llc_input_and_output_voltage_reserve(self):
        for name in ('300W_LLC_HALF_HHC.json', '300W_LLC_FULL_VCO.json'):
            with self.subTest(example=name):
                spec = load_spec(read_example(name))
                cases = self.endpoints(spec)
                self.check_phase_margin(cases, 64.0)
                self.assertGreater(self.minimum_margin(cases, 'bom_C_IN1_voltage'), 74.0)
                self.assertGreater(self.minimum_margin(cases, 'bom_C_O1_voltage'), 19.0)


if __name__ == '__main__':
    unittest.main()
