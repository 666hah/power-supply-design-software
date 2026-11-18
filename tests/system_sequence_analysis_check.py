"""Synthetic RAW-shaped arrays only: these tests are not circuit simulations."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_sequence_analysis as analysis


class SyntheticRaw:
    """A mocked reader, deliberately not an LTspice verification result."""
    def __init__(self, time, traces):
        self.time = time
        self.traces = {key.casefold(): np.asarray(value) for key, value in traces.items()}
        self.names = {key: i for i, key in enumerate(self.traces)}
        self.closed = False

    def trace(self, name):
        return self.traces[name.casefold()]

    def close(self):
        self.closed = True


def synthetic_case():
    time = np.linspace(0., .01, 10001)
    en = (((time >= .001) & (time < .005)) | ((time >= .006) & (time < .009))).astype(float)
    output = np.where(time < .009, np.clip((time - .001) / .001, 0., 1.) * 12.,
                      np.maximum(0., 1. - (time - .009) / .001) * 12.)
    source = np.full_like(time, -1.)
    source[4321] = -15.
    incoming = np.full_like(time, .5)
    incoming[2345] = 4.
    raw_cs = np.full_like(time, .1)
    raw_cs[200] = .5  # An off-state spike does not itself prove cycle limiting.
    filtered = np.full_like(time, .1)
    filtered[3445] = .22
    raw_cs[3445] = .25
    gate = np.where((en > .5) & (np.mod(time, 20e-6) < 10e-6), 10., 0.)
    primary = np.full_like(time, .7)
    primary[2222] = 6.
    fault = ((time >= .004) & (time < .0042)).astype(float)
    state = (output > 8.).astype(float)
    traces = {'V(bus)': np.full_like(time, 24.), 'I(vsource)': source,
              'V(en)': en, 'V(uvlo)': en, 'I(vunitin)': incoming,
              'V(x:vin_bus)': np.full_like(time, 23.5), 'V(x:sense)': raw_cs,
              'V(x:filtered)': filtered, 'V(x:gate)': gate, 'V(x:ilim)': np.full_like(time, .2),
              'V(x:fault)': fault, 'V(x:ss)': np.clip((time - .001) / .001, 0., 1.),
              'V(out)': output, 'I(vout)': state * 1., 'I(x:lp)': primary,
              'I(x:rs1)': raw_cs / .1, 'V(loadstate)': state, 'I(load)': state * 1.}
    compiled = dict(topology='FLYBACK', resolved_controller=dict(RSENSE=.1),
                    sequence_unit=dict(thresholds=dict(gate_on_v=5., cycle_blank_s=1e-6,
                        minimum_on_s=1e-6, cycle_cs_ceiling_v=.2, sense_resistor_ohm=.1)))
    probes = dict(inputbus='V(x:vin_bus)', sense='V(x:sense)', gate='V(x:gate)',
                  fault='V(x:fault)', ss='V(x:ss)',
                  controller=dict(filtered_cs='V(x:filtered)', cycle_limit='V(x:ilim)'),
                  currents=dict(primary='I(x:lp)', sense='I(x:rs1)'))
    manifest = dict(settings=dict(stop_s=.01),
        sources={'BUS': dict(voltage_probe='V(bus)', current_probe='I(vsource)', capacity_W=50.,
                             config=dict(current_limit_A=10.))},
        units={'PSU': dict(instance='X', compiled_manifest=compiled, probes=probes,
                          input_current_probe='I(vunitin)', en_probe='V(en)', uvlo_probe='V(uvlo)',
                          outputs=[dict(id=1, voltage_probe='V(out)', current_probe='I(vout)',
                                        reference_V=12., name='12V')], config=dict(vin_on_V=10.))},
        loads={'LOAD': dict(voltage_probe='V(out)', current_probe='I(load)', state_probe='V(loadstate)',
                            config=dict(mode='R', power_W=12.))}, ports={})
    return SyntheticRaw(time, traces), manifest


class SequenceAnalysisChecks(unittest.TestCase):
    def run_case(self, raw, manifest):
        with patch('system_sequence_analysis.TransientRaw', return_value=raw):
            result = analysis.analyze('synthetic-not-a-simulation.raw', manifest)
        self.assertTrue(raw.closed)
        return result

    def test_full_raw_peaks_signs_startup_shutdown_and_real_branch_currents(self):
        raw, manifest = synthetic_case()
        result = self.run_case(raw, manifest)
        self.assertEqual(result['status'], 'completed')
        source = result['summary']['sources'][0]
        unit = result['summary']['units'][0]
        self.assertEqual(source['supply_current_peak_A'], 15.)
        self.assertEqual(source['supply_current_peak_s'], raw.time[4321])
        self.assertTrue(source['current_limit_exceeded'])
        self.assertEqual(unit['input_current_peak_A'], 4.)
        self.assertEqual(unit['branch_current_peaks']['primary']['peak_A'], 6.)
        self.assertEqual(unit['ocp']['raw_cs_peak_V'], .5)
        self.assertEqual(unit['ocp']['equivalent_sense_current_peak_A'], 5.)
        self.assertEqual(unit['enable']['on_count'], 2)
        self.assertEqual(unit['enable']['off_count'], 2)
        output = unit['outputs'][0]
        self.assertAlmostEqual(output['first_90pct_s'], .0019, places=10)
        self.assertAlmostEqual(output['residual_V'], 0., places=10)
        self.assertGreater(output['shutdown_observation_s'], .001)
        self.assertAlmostEqual(output['decay_10pct_s'], .0099, places=10)
        self.assertEqual(unit['ocp']['fault_events']['on_count'], 1)
        self.assertTrue(unit['ocp']['fault_observed'])
        self.assertTrue(result['summary']['loads'][0]['first_power_s'] > .001)

    def test_cot_uses_phase_current_thresholds_and_dedicated_limit_events(self):
        raw, manifest = synthetic_case()
        unit=manifest['units']['PSU'];unit['compiled_manifest'].update(topology='BUCK',cot={'phases':2},resolved_controller={'RSENSE':None})
        unit['compiled_manifest']['sequence_unit']['thresholds']={'phase_current_limit_A':20.}
        unit['probes']={'inputbus':'V(x:vin_bus)','fault':'V(x:fault)',
            'currents':{'L1':'V(i1)','L2':'V(i2)'},
            'cot_phase_sensed':{'phase1':'V(s1)','phase2':'V(s2)'},
            'cot_phase_limits':{'phase1':'V(o1)','phase2':'V(o2)'}}
        for i in (1,2):
            raw.traces[f'v(i{i})']=np.full_like(raw.time,10.)
            raw.traces[f'v(s{i})']=np.full_like(raw.time,10.)
            raw.traces[f'v(o{i})']=np.zeros_like(raw.time)
        raw.traces['v(i2)'][4321]=22.
        raw.traces['v(s2)'][4321]=24.
        raw.traces['v(o2)'][4321:4323]=1.
        result=self.run_case(raw,manifest)
        unit=result['summary']['units'][0];ocp=unit['ocp']
        self.assertIsNone(ocp['sense_resistor_ohm'])
        self.assertIsNone(ocp['equivalent_sense_current_peak_A'])
        self.assertTrue(ocp['observations_complete'])
        self.assertEqual(ocp['phases'][1]['sample_margin_A'],-4.)
        self.assertEqual(ocp['phases'][1]['current_peak_A'],22.)
        self.assertEqual(ocp['cycle_limit']['observed_phase_event_count'],1)
        self.assertTrue(ocp['cycle_limit']['hit'])
        from system_sequence_report import sections
        report_manifest=copy.deepcopy(manifest);report_result=copy.deepcopy(result)
        report_manifest.update(sources={},loads={})
        report_result['summary'].update(sources=[],loads=[])
        report_manifest['units']['PSU']['config'].update(vin_off_V=8.,enable_s=0.,disable_s=None,soft_start_s=None)
        text=str(list(sections(report_manifest,report_result)))
        self.assertIn('COT 电流与保护观察',text)
        self.assertNotIn('CS / Rs 等效采样',text)
        del raw.traces['v(o2)'];raw.closed=False
        missing=self.run_case(raw,manifest)['summary']['units'][0]['ocp']
        self.assertFalse(missing['observations_complete'])
        self.assertIsNone(missing['cycle_limit']['hit'])

    def test_plot_sampling_is_bounded_and_never_used_for_the_spike_peak(self):
        raw, manifest = synthetic_case()
        result = self.run_case(raw, manifest)
        plot = result['waveforms']
        self.assertEqual(len(plot['time']), 2400)
        self.assertIn('v(x:ss)', plot)
        self.assertLess(max(-np.asarray(plot['i(vsource)'])), 15.)
        self.assertEqual(result['summary']['sources'][0]['supply_current_peak_A'], 15.)
        for values in plot.values():
            self.assertEqual(len(values), len(plot['time']))

    def test_fault_zero_does_not_erase_observed_cycle_limiting(self):
        raw, manifest = synthetic_case()
        raw.traces['v(x:fault)'][:] = 0.
        result = self.run_case(raw, manifest)
        ocp = result['summary']['units'][0]['ocp']
        self.assertFalse(ocp['fault_observed'])
        self.assertTrue(ocp['cycle_limit']['hit'])
        self.assertEqual(ocp['cycle_limit']['observed_cycle_count'], 1)
        self.assertIsNone(ocp['protection_passed'])

    def test_no_filtered_or_dynamic_limit_keeps_cycle_result_unknown(self):
        raw, manifest = synthetic_case()
        del raw.traces['v(x:filtered)']
        raw.traces['v(x:fault)'][:] = 0.
        result = self.run_case(raw, manifest)
        ocp = result['summary']['units'][0]['ocp']
        self.assertIsNone(ocp['cycle_limit']['hit'])
        self.assertIsNone(ocp['cycle_limit']['observed_cycle_count'])
        self.assertFalse(ocp['fault_observed'])
        self.assertEqual(ocp['raw_cs_peak_V'], .5)
        self.assertEqual(result['status'], 'completed')

    def test_no_sampled_limit_hit_does_not_create_a_negative_pass(self):
        raw, manifest = synthetic_case()
        raw.traces['v(x:filtered)'][:] = .1
        result = self.run_case(raw, manifest)
        cycle = result['summary']['units'][0]['ocp']['cycle_limit']
        self.assertIsNone(cycle['hit'])
        self.assertEqual(cycle['observed_cycle_count'], 0)
        self.assertIn('不能证明', cycle['reason'])

    def test_ldo_without_switching_probes_is_explicitly_unknown(self):
        raw, manifest = synthetic_case()
        row = manifest['units']['PSU']
        row['compiled_manifest'] = dict(topology='LDO')
        row['probes'] = dict(inputbus='V(x:vin_bus)')
        result = self.run_case(raw, manifest)
        ocp = result['summary']['units'][0]['ocp']
        self.assertEqual(result['status'], 'completed')
        for key in ('raw_cs_peak_V', 'filtered_cs_peak_V', 'equivalent_sense_current_peak_A', 'fault_observed'):
            self.assertIsNone(ocp[key])
        self.assertIsNone(ocp['cycle_limit']['hit'])

    def test_short_raw_is_failed_and_does_not_report_residual_during_restart(self):
        raw, manifest = synthetic_case()
        raw.time = raw.time[:7001]
        raw.traces = {key: values[:7001] for key, values in raw.traces.items()}
        result = self.run_case(raw, manifest)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['simulation_complete'])
        self.assertTrue(result['failure_reasons'])
        self.assertIsNone(result['summary']['units'][0]['outputs'][0]['residual_V'])

    def test_missing_or_nonfinite_required_probe_is_failed_not_zero(self):
        raw, manifest = synthetic_case()
        raw.traces['i(vunitin)'][100] = np.nan
        result = self.run_case(raw, manifest)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['summary']['units'][0]['input_current_peak_A'])
        self.assertIn('I(vunitin)', ''.join(result['failure_reasons']))

    def test_chunk_boundaries_and_event_display_cap_preserve_full_counts(self):
        raw, manifest = synthetic_case()
        with patch('system_sequence_analysis._CHUNK', 701), patch('system_sequence_analysis._EVENT_LIMIT', 2):
            result = self.run_case(raw, manifest)
        self.assertEqual(result['summary']['units'][0]['enable']['on_count'], 2)
        self.assertEqual(result['summary']['units'][0]['enable']['off_count'], 2)
        self.assertEqual(result['summary']['units'][0]['ocp']['cycle_limit']['observed_cycle_count'], 1)
        self.assertGreater(result['events_omitted_count'], 0)
        self.assertEqual(len(result['events']), 2)
        self.assertIn('计数仍使用完整RAW', ''.join(result['limitations']))

    def test_reader_failure_is_explicit_and_never_fabricates_summary(self):
        with patch('system_sequence_analysis.TransientRaw', side_effect=ValueError('incomplete synthetic RAW')):
            result = analysis.analyze('invalid.raw', dict(settings=dict(stop_s=.01)))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['summary']['units'], [])
        self.assertEqual(result['waveforms']['time'], [])
        self.assertIn('incomplete synthetic RAW', result['failure_reasons'][0])

    def test_connection_windows_and_port_peaks_use_full_raw_with_no_ripple_event_spam(self):
        raw, manifest = synthetic_case()
        t = raw.time
        current = np.zeros_like(t)
        current[2000:4000] = .1
        current[6000:7000] = .1
        current[4321] = -.03
        current[6234] = .8  # A peak independent of the plotting grid.
        raw.traces['i(or-main)'] = current
        raw.traces['v(or-port)'] = np.full_like(t, 11.5)
        raw.traces['v(or-port)'][4321] = 12.1
        manifest['ports'] = {'OR': dict(voltage_probe='V(or-port)', name='OR母线')}
        manifest['connections'] = {'MAIN-OR': dict(current_probe='I(or-main)', source='PSU/OUT1', target='OR')}
        with patch('system_sequence_analysis._CHUNK', 701):
            result = self.run_case(raw, manifest)
        self.assertEqual(result['status'], 'completed')
        connection = result['summary']['connections'][0]
        self.assertEqual(connection['source'], 'PSU/OUT1')
        self.assertEqual(connection['current_peak_A'], .8)
        self.assertEqual(connection['reverse_current_peak_A'], .03)
        self.assertEqual(connection['forward_display_threshold_A'], .001)
        self.assertAlmostEqual(connection['first_forward_s'], .00199901, places=11)
        self.assertAlmostEqual(connection['last_forward_s'], .00699999, places=11)
        self.assertEqual(result['summary']['ports'][0]['voltage_peak_V'], 12.1)
        self.assertEqual(result['summary']['ports'][0]['voltage_min_V'], 11.5)
        self.assertIn('i(or-main)', result['waveforms'])
        self.assertIn('v(or-port)', result['waveforms'])
        self.assertFalse(any(event['id'] == 'MAIN-OR' for event in result['events']))
        self.assertIn('不表示连续导通', ''.join(result['limitations']))

    def test_reverse_only_and_subthreshold_connections_do_not_claim_forward_flow(self):
        raw, manifest = synthetic_case()
        raw.traces['i(reverse)'] = np.full_like(raw.time, -.1)
        raw.traces['i(leakage)'] = np.full_like(raw.time, .0009)
        manifest['connections'] = {
            'REVERSE': dict(current_probe='I(reverse)', source='OR', target='SOURCE'),
            'LEAKAGE': dict(current_probe='I(leakage)', source='SOURCE', target='OR')}
        result = self.run_case(raw, manifest)
        reverse, leakage = result['summary']['connections']
        self.assertEqual(reverse['current_peak_A'], 0.)
        self.assertEqual(reverse['reverse_current_peak_A'], .1)
        for row in (reverse, leakage):
            self.assertIsNone(row['first_forward_s'])
            self.assertIsNone(row['last_forward_s'])
            self.assertTrue(row['observed'])

    def test_missing_declared_optional_observations_are_unknown_and_incomplete(self):
        raw, manifest = synthetic_case()
        manifest['ports'] = {'OR': dict(voltage_probe='V(missing-port)')}
        manifest['connections'] = {'LINK': dict(current_probe='I(missing-link)', source='SOURCE', target='OR')}
        result = self.run_case(raw, manifest)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['simulation_complete'])
        self.assertFalse(result['analysis_complete'])
        self.assertFalse(result['port_observations_complete'])
        self.assertFalse(result['connection_observations_complete'])
        self.assertIsNone(result['summary']['ports'][0]['voltage_peak_V'])
        self.assertIsNone(result['summary']['connections'][0]['current_peak_A'])
        self.assertIsNone(result['summary']['connections'][0]['first_forward_s'])
        self.assertEqual(result['summary']['sources'][0]['supply_current_peak_A'], 15.)

    def test_source_behavior_status_duration_and_fault_are_not_current_comparison(self):
        raw, manifest = synthetic_case()
        source=manifest['sources']['BUS']
        source['config'].update(protection_mode='hiccup')
        source.update(limit_active_probe='V(source-limit)',fault_probe='V(source-fault)')
        t=raw.time
        raw.traces['v(source-limit)']=(((t>=.001)&(t<.002))|((t>=.004)&(t<.005))).astype(float)
        # Exact sample ranges avoid float-comparison drift at t=0.007.
        raw.traces['v(source-fault)']=np.zeros_like(t)
        raw.traces['v(source-fault)'][2000:4000]=1.
        raw.traces['v(source-fault)'][5000:7000]=1.
        raw.traces['i(vsource)'][:]=-1.  # Never exceeds the static 10A ceiling.
        with patch('system_sequence_analysis._CHUNK',701):
            result=self.run_case(raw,manifest)
        source=result['summary']['sources'][0]
        self.assertFalse(source['current_limit_exceeded'])
        self.assertTrue(source['protection_model_executed'])
        self.assertTrue(source['protection_observations_complete'])
        self.assertEqual(source['limit_state']['on_count'],2)
        self.assertEqual(source['fault_state']['on_count'],2)
        self.assertEqual(source['fault_state']['off_count'],2)
        self.assertAlmostEqual(source['limit_state']['active_time_s'],.002,places=10)
        self.assertAlmostEqual(source['fault_state']['active_time_s'],.004,places=10)
        self.assertIsNone(source['protection_passed'])
        self.assertTrue(any(e['type']=='source_fault_on' for e in result['events']))

    def test_declared_source_protection_missing_state_is_failure_not_pass(self):
        raw,manifest=synthetic_case()
        manifest['sources']['BUS']['config']['protection_mode']='cc'
        result=self.run_case(raw,manifest)
        self.assertEqual(result['status'],'failed')
        source=result['summary']['sources'][0]
        self.assertIsNone(source['limit_state']['on_count'])
        self.assertFalse(source['protection_observations_complete'])
        self.assertIsNone(source['protection_passed'])

    def test_stages_reset_reenter_and_separate_active_current_full_raw(self):
        raw,manifest=synthetic_case()
        t=raw.time;row=manifest['loads']['LOAD']
        row['config']['stages']=[dict(name='固件启动',after_s=0.,mode='I',power_W=1.,ramp_s=.0001),
                                 dict(name='通信运行',after_s=.001,mode='I',power_W=2.,ramp_s=.0001)]
        row.update(stage_probe='V(stage)',ready_probe='V(ready)',age_probe='V(age)',active_current_probe='V(active)')
        stage=np.zeros_like(t)
        stage[(t>=.002)&(t<.003)]=1
        stage[(t>=.003)&(t<.005)]=2
        stage[(t>=.007)&(t<.008)]=1
        stage[(t>=.008)&(t<.009)]=2
        ready=(((t>=.001)&(t<.005))|((t>=.006)&(t<.009))).astype(float)
        raw.traces['v(stage)']=stage;raw.traces['v(ready)']=ready
        raw.traces['v(age)']=np.where((t>=.001)&(t<.005),t-.001,np.where((t>=.006)&(t<.009),t-.006,0.))
        raw.traces['v(active)']=stage*.1
        raw.traces['v(active)'][4321]=.9
        with patch('system_sequence_analysis._CHUNK',701),patch('system_sequence_analysis._EVENT_LIMIT',3):
            result=self.run_case(raw,manifest)
        self.assertEqual(result['status'],'completed')
        load=result['summary']['loads'][0];stages=load['stage_observations']
        self.assertTrue(stages['observed'])
        self.assertEqual(stages['reset_count'],2)
        self.assertEqual(stages['restart_count'],1)
        self.assertEqual(stages['final_index'],0)
        self.assertEqual(stages['skipped_stage_count'],0)
        self.assertEqual([s['entry_count'] for s in stages['stages']],[2,2])
        self.assertAlmostEqual(stages['stages'][1]['first_entry_s'],.0029995,places=10)
        self.assertAlmostEqual(stages['stages'][1]['first_ready_age_s'],.0019995,places=10)
        self.assertEqual(load['active_current_peak_A'],.9)
        self.assertEqual(load['current_peak_A'],1.)
        self.assertGreater(load['active_power']['energy_J'],0.)
        self.assertLess(max(result['waveforms']['v(active)']),.9)
        self.assertGreater(result['events_omitted_count'],0)

    def test_staged_load_missing_or_invalid_index_cannot_complete(self):
        for invalid in (False,True):
            with self.subTest(invalid=invalid):
                raw,manifest=synthetic_case();row=manifest['loads']['LOAD']
                row['config']['stages']=[dict(name='运行',after_s=0.,mode='I',power_W=1.,ramp_s=.001)]
                if invalid:
                    row.update(stage_probe='V(stage)',age_probe='V(age)')
                    raw.traces['v(stage)']=np.full_like(raw.time,2.)
                    raw.traces['v(age)']=raw.time
                result=self.run_case(raw,manifest)
                self.assertEqual(result['status'],'failed')
                self.assertFalse(result['summary']['loads'][0]['stage_observations']['observed'])
                self.assertIsNone(result['summary']['loads'][0]['stage_observations']['restart_count'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
