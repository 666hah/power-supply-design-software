"""Fixed-design tolerance sweeps and the distinction between 4σ statistics and tails."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

import numpy as np

from calculation_scheduler import CalculationCancelled
from design_engine.specification import load_spec
from tolerance_analysis import _event_status, _measurements, _search_boundary, analyze, available_variables, resume_monte_carlo
from tolerance_defaults import default_variables
from tolerance_metrics import measurements, resolve_external_limits
from tolerance_report import report_sections
from tolerance_statistics import normalize_variables, sample_variables, summarize_samples


class ToleranceChecks(unittest.TestCase):
    def test_fixed_phase_margin_threshold_in_both_workflows_and_report(self):
        from tolerance_ui import normalize_profile

        params = dict(pm_target=80., V_out=12., P_out=24.)
        old_overrides = dict(phase_margin=70., outputs={'1': {'ripple_pp': .15}})
        imported = normalize_profile({'external_limits': old_overrides})
        self.assertEqual(imported['external_limits'], {'outputs': old_overrides['outputs']})
        limits = resolve_external_limits(params, old_overrides)
        self.assertEqual(limits['phase_margin'], 45.)
        legacy_criterion = dict(enabled=False, comparison='>=', limit=80.)
        for value, event in ((44.9, True), (45., True), (45.1, False), (None, None)):
            with self.subTest(value=value):
                op = dict(V_out=12.)
                snapshot = dict(p=params, op=op, res={'op': op, 'loop': {'min_pm': value}}, checks=[])
                legacy = _measurements(snapshot, {'phase_margin': legacy_criterion})['phase_margin']
                with patch('tolerance_metrics._component_measurements'):
                    staged = measurements(snapshot, limits)['phase_margin']
                for row in (legacy, staged):
                    self.assertEqual((row['limit'], row['strict']), (45., True))
                    self.assertIs(_event_status([row], 1), event)
        tables = list(report_sections({'rows': [staged]}))
        self.assertEqual(tables[0][2][0][1], '> 45 °')

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
        # Force a review threshold independent of the example's selected MOSFET rating.
        inputs['engineering_acceptance'] = {
            'criteria': [dict(metric='vds_peak', comparison='<=', limit=500.)],
        }
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
        self.assertEqual(rows['vds_peak']['limit'], 500.)
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

    def test_staged_exhaustive_pass_does_not_draw_samples(self):
        inputs = load_spec(dict(V_in_min=16., V_in_max=16., P_out=24., P_out_min=12.))
        value = inputs['Rds_on']
        variable = dict(path='Rds_on', low=.9*value, high=1.1*value, distribution='bounds')

        def measurements(snapshot, _limits, *, context):
            return {'stress': self.measure('stress', 'components', snapshot['p']['Rds_on'], 2*value),
                    'voltage': self.measure('voltage', 'external', 0., 1.)}

        model = self.fake_tolerance_model(measurements)
        with patch.dict(sys.modules, {'tolerance_metrics': model}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot), \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p), \
             patch('tolerance_analysis.sample_variables') as draw:
            study = analyze(inputs, [variable], staged=True, samples=20, load_fracs=(1.,))
            boundary_result, plan = analyze(inputs, [variable], staged=True, load_fracs=(1.,), retain_plan=True)
            with self.assertRaisesRegex(ValueError, '发现超限'):
                resume_monte_carlo(inputs, boundary_result, plan, samples=20, seed=1)
        draw.assert_not_called()
        self.assertEqual(study['boundary']['status'], 'within')
        self.assertEqual(study['boundary']['tested_corners'], 2)
        self.assertEqual(study['monte_carlo']['status'], 'skipped_within')
        self.assertIn(.5, [condition['load_fractions'][0] for condition in study['conditions']])

    def test_staged_risk_counts_unknowns_separately(self):
        inputs = load_spec(dict(V_in_min=16., V_in_max=16., P_out=24., P_out_min=12.))
        value = inputs['Rds_on']
        variable = dict(path='Rds_on', low=.9*value, high=1.1*value, distribution='uniform')

        def measurements(snapshot, _limits, *, context):
            ratio = snapshot['p']['Rds_on']/value
            return {'stress': self.measure('stress', 'components', ratio, 1.05, complete=False),
                    'voltage': self.measure('voltage', 'external', ratio, 1.)}

        draws = np.array([[.99*value], [1.025*value], [1.08*value]])
        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot), \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p), \
             patch('tolerance_analysis.sample_variables', return_value=draws):
            study = analyze(inputs, [variable], staged=True, samples=3, load_fracs=(1.,))
        self.assertEqual(study['boundary']['status'], 'review')
        risks = study['monte_carlo']['groups']
        self.assertEqual(risks['external']['probability'], 2/3)
        self.assertEqual(risks['external']['unknown_units'], 0)
        self.assertIsNone(risks['components']['probability'])
        self.assertEqual(risks['components']['observed_bounds'], [1/3, 1.])
        self.assertEqual(risks['components']['unknown_units'], 2)
        self.assertEqual(risks['components']['exceedances'], 1)
        json.dumps(study, allow_nan=False)

    def test_monte_carlo_resumes_with_frozen_hardware_and_independent_budget(self):
        inputs = load_spec(dict(V_in_min=16., V_in_max=16., P_out=24., P_out_min=12.))
        value = inputs['Rds_on']
        variable = dict(path='Rds_on', low=.9*value, high=1.1*value, distribution='uniform')

        def measurements(snapshot, _limits, *, context):
            self.assertEqual(snapshot['p']['frozen_transformer'], 'nominal turns')
            ratio = snapshot['p']['Rds_on']/value
            if context['id'].startswith('MC-0001') and ratio < 1.:
                raise RuntimeError('抽样工况未收敛')
            return {'stress': self.measure('stress', 'components', ratio, 2.),
                    'voltage': self.measure('voltage', 'external', ratio, 1.)}

        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot) as solve, \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: dict(
                 p, frozen_transformer='nominal turns')) as freeze, \
             patch('tolerance_analysis.sample_variables', return_value=np.array([[.95*value], [1.08*value]])) as draw:
            boundary_result, plan = analyze(inputs, [variable], staged=True, load_fracs=(1.,), retain_plan=True)
            before = deepcopy(boundary_result)
            draw.assert_not_called()
            self.assertEqual(before['boundary']['status'], 'review')
            self.assertEqual(before['monte_carlo']['status'], 'required_not_run')
            self.assertEqual(solve.call_count, before['deterministic_cases'] + 1)

            with patch('tolerance_analysis._search_boundary', side_effect=AssertionError('boundary executed twice')):
                budget = 2*len(before['conditions'])
                merged = resume_monte_carlo(inputs, boundary_result, plan, samples=5, seed=10,
                                             max_evaluations=budget)
            freeze.assert_called_once()
            draw.assert_called_once_with(merged['variables'], 2, 10)
            self.assertEqual(solve.call_count, before['deterministic_cases'] + budget + 1)

        self.assertEqual(boundary_result, before)
        self.assertEqual(merged['boundary'], before['boundary'])
        self.assertEqual(merged['conditions'], before['conditions'])
        self.assertEqual(merged['deterministic_cases'], before['deterministic_cases'])
        self.assertEqual(merged['evaluations'], before['evaluations'] + budget)
        self.assertEqual(merged['failure_count'], len(before['conditions']))
        self.assertTrue(all(case['id'].startswith('MC-0001') for case in merged['failures']))
        self.assertEqual(merged['samples'], 2)
        self.assertEqual(merged['boundary']['seed'], 1)
        self.assertEqual(merged['monte_carlo']['seed'], 10)
        self.assertEqual(merged['monte_carlo']['evaluations'], budget)
        self.assertTrue(merged['monte_carlo']['budget_limited'])
        risks = merged['monte_carlo']['groups']
        self.assertEqual(risks['external']['exceedances'], 1)
        self.assertEqual(risks['components']['unknown_units'], 1)
        json.dumps(merged, allow_nan=False)

    def test_monte_carlo_rejects_changed_design_or_boundary_and_honors_cancel(self):
        inputs = load_spec(dict(V_in_min=16., V_in_max=16., P_out=24., P_out_min=12.))

        def measurements(_snapshot, _limits, *, context):
            return {'stress': self.measure('stress', 'components', 2., 1.),
                    'voltage': self.measure('voltage', 'external', 0., 1.)}

        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot), \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p), \
             patch('tolerance_analysis.sample_variables') as draw:
            boundary_result, plan = analyze(inputs, [], staged=True, load_fracs=(1.,), retain_plan=True)

            for changed in (dict(inputs, V_in_max=18.),
                            dict(inputs, __comp={'key': 'gm3'}),
                            dict(inputs, engineering_acceptance={'criteria': [{'metric': 'out1_voltage'}]})):
                with self.assertRaisesRegex(ValueError, '输入已变更'):
                    resume_monte_carlo(changed, boundary_result, plan, samples=2, seed=1)
            other_result = dict(boundary_result, external_limits={'phase_margin': 45.})
            with self.assertRaisesRegex(ValueError, '先计算当前配置'):
                resume_monte_carlo(inputs, other_result, plan, samples=2, seed=1)
            with self.assertRaises(CalculationCancelled):
                resume_monte_carlo(inputs, boundary_result, plan, samples=2, seed=1, cancelled=lambda: True)
            draw.assert_not_called()

    def test_search_tests_metric_specific_opposite_mixed_corners(self):
        signs = (1, 1, -1, -1, 1, -1, 1, -1)
        variables = [dict(nominal=0., low=-1., high=1.) for _ in signs]

        def measurements(values, _index):
            score = sum(v*s for v, s in zip(values, signs))
            return {'one': self.measure('one', 'components', score, 6.),
                    'two': self.measure('two', 'external', -score, 6.)}

        observations, covered, total, strategy = _search_boundary(variables, 42, measurements, 2)
        self.assertEqual(strategy, 'metric_guided')
        self.assertLess(covered, total)
        self.assertEqual(observations[signs]['one']['value'], len(signs))
        self.assertEqual(observations[tuple(-value for value in signs)]['two']['value'], len(signs))

    def test_theory_guided_boundary_has_a_fixed_cost_and_keeps_candidate_evidence(self):
        inputs = load_spec(dict(topology='BUCK', V_in_min=18., V_in_max=30., V_out=12., P_out=24.))
        variables = default_variables(inputs)
        self.assertGreater(len(variables), 4)

        def measurements(_snapshot, _limits, *, context):
            return {'stress': self.measure('stress', 'components', .5, 1.),
                    'voltage': self.measure('voltage', 'external', .5, 1.)}

        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis._search_boundary', side_effect=AssertionError('legacy sweep was called')), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot) as solve, \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p), \
             patch('tolerance_analysis.sample_variables') as draw:
            limited = analyze(inputs, variables, staged=True, boundary_strategy='theory_guided', max_evaluations=5)
            self.assertLessEqual(limited['deterministic_cases'], 5)
            solve.reset_mock()
            result, plan = analyze(inputs, variables, staged=True, boundary_strategy='theory_guided', retain_plan=True)
            with self.assertRaisesRegex(ValueError, '发现超限'):
                resume_monte_carlo(inputs, result, plan, samples=8, seed=11)
        draw.assert_not_called()
        boundary = result['boundary']
        self.assertEqual(boundary['search'], 'theory_guided')
        self.assertEqual(boundary['status'], 'incomplete')
        self.assertFalse(boundary['exhaustive'])
        self.assertEqual(result['monte_carlo']['status'], 'blocked_incomplete')
        self.assertLessEqual(boundary['hardware_cases'], 8)
        self.assertLessEqual(result['deterministic_cases'], 48)
        self.assertEqual(solve.call_count, result['deterministic_cases'] + 1)
        self.assertEqual({row['status'] for row in result['rows']}, {'candidate_ok'})
        self.assertNotIn('feedback_divider_static', {item['id'] for item in boundary['theory_checks']})
        json.dumps(result, allow_nan=False)

    def test_theory_divider_exact_bounds_do_not_certify_end_port(self):
        inputs = load_spec(dict(topology='BUCK', V_in_min=18., V_in_max=30., V_out=12., P_out=24.))
        inputs['tolerance_feedback_divider'] = dict(upper_ohm=38000., lower_ohm=10000., reference_V=2.5,
                                                   output=1, source='opamp3', nominal_voltage_V=12.)
        upper, lower = ('tolerance_feedback_divider.upper_ohm', 'tolerance_feedback_divider.lower_ohm')
        variables = [dict(path=upper, low=37620., high=38380., distribution='uniform'),
                     dict(path=lower, low=9900., high=10100., distribution='uniform')]

        def measurements(_snapshot, _limits, *, context):
            return {'port_with_step': self.measure('port_with_step', 'external', .5, 1.)}

        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot), \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p):
            result = analyze(inputs, variables, staged=True, boundary_strategy='theory_guided')

        proof, = result['boundary']['theory_checks']
        self.assertEqual(proof['id'], 'feedback_divider_static')
        self.assertAlmostEqual(proof['low'], 2.5*(1. + 37620./10100.))
        self.assertAlmostEqual(proof['high'], 2.5*(1. + 38380./9900.))
        self.assertEqual(proof['low_parameters'], {upper: 37620., lower: 10100.})
        self.assertEqual(proof['high_parameters'], {upper: 38380., lower: 9900.})
        self.assertEqual(result['rows'][0]['status'], 'candidate_ok')
        self.assertEqual(result['boundary']['status'], 'incomplete')

    def test_theory_guided_breach_permits_sampling_on_the_full_operating_grid(self):
        inputs = load_spec(dict(topology='BUCK', V_in_min=18., V_in_max=30., V_out=12., P_out=24.))
        variables = default_variables(inputs)

        def measurements(_snapshot, _limits, *, context):
            return {'stress': self.measure('stress', 'components', 1.2, 1.),
                    'voltage': self.measure('voltage', 'external', .5, 1.)}

        with patch.dict(sys.modules, {'tolerance_metrics': self.fake_tolerance_model(measurements)}), \
             patch('tolerance_analysis.build_snapshot', side_effect=self.fake_snapshot), \
             patch('tolerance_analysis._hardware_fixed', side_effect=lambda p, _: p) as freeze:
            result, plan = analyze(inputs, variables, staged=True, boundary_strategy='theory_guided',
                                   retain_plan=True)
            self.assertEqual(result['boundary']['status'], 'review')
            self.assertEqual(result['monte_carlo']['status'], 'required_not_run')
            full_count = len(result['conditions'])
            merged = resume_monte_carlo(inputs, result, plan, samples=2, seed=11,
                                        max_evaluations=2*full_count)
        freeze.assert_called_once()
        self.assertEqual(merged['conditions'], result['conditions'])
        self.assertEqual(merged['deterministic_cases'], result['deterministic_cases'])
        self.assertEqual(merged['monte_carlo']['evaluations'], 2*full_count)
        self.assertEqual(merged['monte_carlo']['groups']['components']['exceedances'], 2)

    def test_theory_guided_buck_recalculates_input_ripple_at_interior_voltage(self):
        example = ROOT/'examples/24W_BUCK_VM_TPS40200.json'
        inputs = load_spec(json.loads(example.read_text('utf-8')))
        lo, hi = inputs['V_in_min'], inputs['V_in_max']
        result = analyze(inputs, default_variables(inputs), staged=True, boundary_strategy='theory_guided',
                         load_fracs=(1.,))
        self.assertEqual(result['failure_count'], 0, result['failures'])
        self.assertTrue(any(lo < case['voltage'] < hi and case['voltage'] != (lo+hi)/2
                            and case['load_fractions'] == [1.]
                            for case in result['boundary']['conditions']))
        proof = next(item for item in result['boundary']['theory_checks'] if item['id'] == 'buck_ideal_capacitive_ripple')
        capacitance = sum(proof['high_parameters'][f'output_capacitors.{i}.C']
                          for i in range(len(inputs['output_capacitors'])))
        expected = inputs['V_out']*(1-inputs['V_out']/hi)/(8*inputs['L']*inputs['f_sw']**2*capacitance)
        self.assertAlmostEqual(proof['high'], expected)
        self.assertGreater(proof['high'], proof['low'])

    @staticmethod
    def measure(name, group, value, limit, *, complete=True):
        return dict(id=name, name=name, unit='', direction='max', value=value,
                    limit=limit, strict=False, group=group, complete=complete)

    @staticmethod
    def fake_snapshot(p, **_kwargs):
        return dict(p=p, op={'mode': 'CCM'})

    @staticmethod
    def fake_tolerance_model(measurements):
        return SimpleNamespace(resolve_external_limits=lambda *_args: {}, measurements=measurements)


if __name__ == '__main__':
    unittest.main(verbosity=2)
