"""Measured impedance, complex harmonic splitting, and design integration."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads

configure_numeric_threads()
import numpy as np

from capacitor_banks import normalize, validate
from capacitor_impedance import impedance, validate_curve
from capripple import capacitor_ripple_analysis
from design_engine.specification import load_spec
from loss_model import compute_design
from plants import build_loop_models
from waveforms import cap_bank_ripple


class CapacitorImpedanceChecks(unittest.TestCase):
    def test_sort_interpolate_and_fall_back_to_fixed_rlc(self):
        cap = validate([dict(C=1e-4, ESR=.035, ESL=8e-9, impedance_curve={
            'points': [[1e5, .3, 90], [1e3, .1, 0]], 'source': ' sweep A ',
        })])[0]
        self.assertEqual(cap['impedance_curve']['points'][0], [1e3, .1, 0])
        self.assertEqual(cap['impedance_curve']['source'], 'sweep A')
        f = np.array([500, 1e3, 1e4, 1e5, 2e5])
        z, coverage = impedance(f, cap, return_coverage=True)
        self.assertEqual(coverage.tolist(), [False, True, True, True, False])
        expected_edges = cap['ESR'] + 1j * (2*np.pi*f*cap['ESL'] - 1/(2*np.pi*f*cap['C']))
        np.testing.assert_allclose(z, [expected_edges[0], .1, .05 + .15j, .3j, expected_edges[-1]])
        self.assertAlmostEqual(impedance(1e4, cap).item(), .05 + .15j)
        projected = normalize({'output_capacitors': [cap]})
        self.assertEqual(projected['C_out'], cap['C'])
        self.assertEqual(projected['Rc'], cap['ESR'])
        self.assertEqual(projected['ESL'], cap['ESL'])
        self.assertEqual(projected['output_capacitors'], [cap])

    def test_invalid_sweeps_and_thermal_resistance_are_rejected(self):
        for invalid in (
            [[1, .2, 20]],
            [[1, .2, 20], [1, .3, 10]],
            [[1, 0, 0], [2, .1, 30]],
            [[1, .2, -91], [2, .1, 30]],
            [[1, .2, -10], [float('inf'), .1, 30]],
            [[False, .2, 20], [2, .1, 30]],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_curve({'points': invalid})
        for bad in (False, 0, -1, np.nan, '12'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate([dict(C=1e-4, thermal_resistance_K_per_W=bad)])
        for bad in (None, False, 'unknown', {}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '模型只能选择'):
                validate([dict(C=1e-4, impedance_mode=bad)])
        with self.assertRaisesRegex(ValueError, '需要先导入曲线'):
            validate([dict(C=1e-4, impedance_mode='curve')])

    def test_fixed_mode_disables_but_preserves_stored_sweep(self):
        from design_engine.service import calculate
        from spice_export import project_files

        blank = dict(C=220e-6, ESR=.035, ESL=5e-9, thermal_resistance_K_per_W=12)
        curve = {'points': [[1e3, .2, -10], [1e7, .08, 15]], 'source': 'synthetic'}
        stored = dict(blank, impedance_curve=curve, impedance_mode='fixed')
        saved = json.loads(json.dumps(dict(output_capacitors=[stored])))
        self.assertEqual(normalize(saved)['output_capacitors'], [stored])

        spec = json.loads((ROOT / 'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
        spec['output_capacitors'] = [blank]
        baseline = compute_design(load_spec(spec))
        for mode in ('fixed', 'curve'):
            with self.subTest(mode=mode):
                spec['output_capacitors'] = [dict(stored, impedance_mode=mode)]
                run = calculate(spec, analysis='endpoints', include_cross_regulation=False)
                cases = run.runtime_bundle()['cases']
                active = mode == 'curve'
                first = cases[0]['result']
                branch = first['capacitors']['output']['caps'][0]
                self.assertEqual(cases[0]['p']['output_capacitors'][0]['impedance_curve'], curve)
                self.assertEqual(branch['impedance_model'], 'curve' if active else 'fixed_rlc')
                self.assertEqual('vout_ripple_impedance' in first['wf'], active)
                self.assertEqual(branch['curve_range_hz'] is not None, active)
                self.assertEqual(branch['curve_source'] is not None, active)
                if active:
                    self.assertNotEqual(first['P_cap'], baseline['P_cap'])
                    self.assertIsNotNone(branch['curve_coverage_fraction'])
                else:
                    self.assertEqual(first['capacitors'], baseline['capacitors'])
                    self.assertEqual(first['P_cap'], baseline['P_cap'])
                    self.assertEqual(first['wf']['ripple_pp_total'], baseline['wf']['ripple_pp_total'])
                self.assertEqual(branch['temperature_rise_K'], 12 * branch['loss_W'])

                payload = run.to_dict(include_waveforms=False, include_details=False)
                self.assertEqual('output_capacitors.1' in payload['provenance']['curve_hashes'], active)
                files = project_files(load_spec(spec), bundle=run.runtime_bundle())
                notes = json.loads(files['manifest.json'])['approximation_notes']
                self.assertEqual(any('扫频阻抗' in note for note in notes), active)

    def test_harmonic_loss_coverage_and_ripple_match_complex_divider(self):
        f = 10e3
        t = np.arange(1024) / (1024 * f)
        i = 1.2*np.cos(2*np.pi*f*t) + .8*np.cos(4*np.pi*f*t)
        cap_a, cap_b = validate([
            dict(C=100e-6, ESR=.9, ESL=1e-9, thermal_resistance_K_per_W=12,
                 impedance_curve={'points': [[.9*f, .1, -60], [1.1*f, .1, -60]]}),
            dict(C=330e-6, ESR=.035, ESL=6e-9),
        ])
        freqs = np.array([f, 2*f])
        w = 2*np.pi*freqs
        z_a = np.array([.05 - .05j*np.sqrt(3), .9 + 1j*(w[1]*1e-9 - 1/(w[1]*100e-6))])
        z_b = .035 + 1j*(w*6e-9 - 1/(w*330e-6))
        z_parallel = z_a*z_b/(z_a + z_b)
        i_ac = np.array([1.2, .8])
        a_expected = (i_ac**2/2)*np.abs(z_parallel/z_a)**2
        b_expected = (i_ac**2/2)*np.abs(z_parallel/z_b)**2
        data = capacitor_ripple_analysis(t, i, i, f, [cap_a, cap_b], [cap_a, cap_b])
        a, b = data['input']['caps']
        for row, energy, z in [(a, a_expected, z_a), (b, b_expected, z_b)]:
            np.testing.assert_allclose(np.array(row['bands'][1:3])**2, energy)
            self.assertAlmostEqual(row['total']**2, energy.sum())
            self.assertAlmostEqual(row['loss_W'], np.sum(energy*z.real))
        self.assertAlmostEqual(a['equivalent_esr_ohm'], a['loss_W']/a['total']**2)
        self.assertAlmostEqual(a['temperature_rise_K'], 12*a['loss_W'])
        self.assertAlmostEqual(a['curve_coverage_fraction'], a_expected[0]/a_expected.sum())
        self.assertIsNone(b['temperature_rise_K'])
        self.assertIsNone(b['curve_coverage_fraction'])
        self.assertAlmostEqual(data['input']['loss_W'], a['loss_W'] + b['loss_W'])
        self.assertAlmostEqual(data['total_in']**2, np.sum(i_ac**2/2))
        voltage = cap_bank_ripple(t, i, [cap_a, cap_b])
        voltage_expected = np.real(np.exp(2j*np.pi*t[:, None]*freqs) @ (i_ac*z_parallel))
        np.testing.assert_allclose(voltage, voltage_expected, atol=1e-15)

    def test_curve_routes_through_nonisolated_and_independent_rail_models(self):
        curve = {'points': [[1e3, .11, -35], [1e7, .09, 20]], 'source': 'synthetic'}
        paths = [
            ('24W_BUCK_VM_TPS40200.json', False),
            ('40W_CCM_3OUT_FLYBACK.json', True),
        ]
        for filename, multiple in paths:
            with self.subTest(filename=filename):
                config = load_spec(json.loads((ROOT/'examples'/filename).read_text(encoding='utf-8')))
                if multiple:
                    config['coupling_config']['enabled'] = False
                cap = dict(C=330e-6, ESR=.012, ESL=4e-9, thermal_resistance_K_per_W=12)
                config['input_capacitors'] = [dict(cap, impedance_curve=curve)]
                rail = config['outputs'][1] if multiple else config
                rail['output_capacitors'] = [dict(cap, impedance_curve=curve), cap]
                design = compute_design(config)
                self.assertEqual(design['capacitors']['input']['caps'][0]['impedance_model'], 'curve')
                self.assertEqual(design['P_cap_in'], design['capacitors']['input']['loss_W'])
                rows = design['outputs'][1] if multiple else design
                wave = design['wf']['outputs'][1] if multiple else design['wf']
                self.assertEqual(rows['capacitors']['output']['caps'][0]['impedance_model'], 'curve')
                self.assertEqual(rows['P_cap'], rows['capacitors']['output']['loss_W'])
                self.assertEqual(wave['ripple_impedance_model'], 'curve')
                self.assertEqual(wave['ripple_pp_total'], np.ptp(wave['vout_ripple_impedance']))
                _, plant = build_loop_models(config, design['op'])
                self.assertIn('环路沿用', plant.model_note)
                without = copy.deepcopy(config)
                without['input_capacitors'][0].pop('impedance_curve')
                (without['outputs'][1] if multiple else without)['output_capacitors'][0].pop('impedance_curve')
                baseline = compute_design(without)
                self.assertAlmostEqual(design['op']['D'], baseline['op']['D'])
                self.assertNotAlmostEqual(design['P_cap_in'], baseline['P_cap_in'])
                self.assertNotAlmostEqual(design['P_cap'], baseline['P_cap'])

                config['input_capacitors'][0]['impedance_mode'] = 'fixed'
                rail['output_capacitors'][0]['impedance_mode'] = 'fixed'
                paused = compute_design(config)
                self.assertEqual(paused['capacitors'], baseline['capacitors'])
                wave = paused['wf']['outputs'][1] if multiple else paused['wf']
                self.assertEqual(wave['ripple_impedance_model'], 'fixed_rlc')
                self.assertNotIn('vout_ripple_impedance', wave)
                self.assertEqual(paused['P_cap'], baseline['P_cap'])
                _, plant = build_loop_models(config, paused['op'])
                self.assertNotIn('阻抗曲线用于', getattr(plant, 'model_note', '') or '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
