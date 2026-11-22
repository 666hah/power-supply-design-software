"""Coverage of the built-in tolerance assumptions and special model inputs."""

from copy import deepcopy
from math import pi
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capacitor_impedance import impedance
from design_engine.specification import load_spec
from example_catalog import EXAMPLES, PERSONAL_QR, example_path
from tolerance_analysis import _variables
from tolerance_defaults import TRANSFORMER_SCALE, apply_special_tolerance, default_variables, example_tolerance_defaults
from web_app.metadata import read_example


class ToleranceDefaultsChecks(unittest.TestCase):
    def test_advertised_examples_apply_three_sigma_nominal_relative_presets(self):
        names = [*EXAMPLES, '40W_CCM_FLYBACK.json']
        if example_path(PERSONAL_QR).is_file():
            names.append(PERSONAL_QR)
        transformer = {'FLYBACK': 'L', 'QR-FLYBACK': 'L', 'ACF-FORWARD': 'Lm_forward', 'LLC': 'llc_lm'}
        for name in names:
            with self.subTest(name=name):
                config = read_example(name)
                self.assertTrue(config['__tolerance']['automatic_defaults'])
                spec = load_spec(config)
                rows = _variables(spec, default_variables(spec))
                self.assertTrue(rows)
                self.assertTrue(any(row['path'].startswith('input_capacitors.') for row in rows))
                self.assertTrue(any('output_capacitors.' in row['path'] for row in rows))
                if spec['topology'] in transformer:
                    self.assertIn(transformer[spec['topology']], {row['path'] for row in rows})
                for row in rows:
                    path = row['path']
                    fraction = (.10 if path.endswith('.C') or path in ('C_clamp', 'llc_cr', 'qr_rcd_C_scale') else
                                .05 if path == transformer.get(spec['topology']) else .01)
                    nominal = row['nominal']
                    self.assertEqual(row['distribution'], 'normal')
                    self.assertAlmostEqual(row['low']/nominal, 1-fraction)
                    self.assertAlmostEqual(row['high']/nominal, 1+fraction)
                    self.assertAlmostEqual(row['sigma']/nominal, fraction/3)

    def test_explicit_saved_profile_has_precedence_over_preset(self):
        custom = {'__tolerance': {'automatic_defaults': False, 'variables': [{'path': 'Rs'}]}}
        self.assertIs(example_tolerance_defaults(custom), custom)

    def test_measured_capacitor_changes_capacitive_reactance_in_and_outside_measured_band(self):
        cap = dict(C=47e-6, ESR=.05, ESL=4e-9, impedance_mode='curve', impedance_curve={
            'source': 'synthetic fixture', 'points': [[100., 30., -89.], [1000., 3., -88.]]})
        spec = dict(input_capacitors=[cap])
        trial = deepcopy(spec)
        sampled = .9 * cap['C']
        self.assertTrue(apply_special_tolerance(trial, 'input_capacitors.0.C', sampled))
        varied = trial['input_capacitors'][0]
        frequencies = np.array([100., 1000., 10000.])
        delta = impedance(frequencies, varied) - impedance(frequencies, cap)
        np.testing.assert_allclose(delta.real, 0., atol=1e-12)
        np.testing.assert_allclose(delta.imag, (1/cap['C']-1/sampled)/(2*pi*frequencies), rtol=1e-12)
        self.assertEqual(varied['impedance_curve']['source'], 'synthetic fixture')
        self.assertEqual(spec['input_capacitors'][0]['C'], 47e-6)

    def test_adopted_transformer_scales_as_one_component(self):
        spec = dict(topology='ACF-FORWARD', Lm_forward=4e-4, coupling_config={
            'enabled': True, 'self_inductances_H': [4e-4, 1e-4], 'kij': [[1., .97], [.97, 1.]]})
        self.assertTrue(apply_special_tolerance(spec, TRANSFORMER_SCALE, 1.05))
        np.testing.assert_allclose(spec['coupling_config']['self_inductances_H'], [4.2e-4, 1.05e-4])
        self.assertAlmostEqual(spec['Lm_forward'], 4.2e-4)
        self.assertEqual(spec['coupling_config']['kij'], [[1., .97], [.97, 1.]])

    def test_derived_physical_parts_change_the_pinned_values(self):
        spec = dict(psr_RfbL=5600., _qr_rcd_hardware={'R_ohm': 40000., 'C_F': .01e-6})
        self.assertTrue(apply_special_tolerance(spec, 'psr_RfbL_scale', .99))
        self.assertTrue(apply_special_tolerance(spec, 'qr_rcd_R_scale', 1.01))
        self.assertTrue(apply_special_tolerance(spec, 'qr_rcd_C_scale', .90))
        self.assertAlmostEqual(spec['psr_RfbL'], 5544.)
        self.assertAlmostEqual(spec['_qr_rcd_hardware']['R_ohm'], 40400.)
        self.assertAlmostEqual(spec['_qr_rcd_hardware']['C_F'], 9e-9)


if __name__ == '__main__':
    unittest.main()
