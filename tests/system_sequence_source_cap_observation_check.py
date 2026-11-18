"""Synthetic source-capacitor observation contracts; not solver evidence."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_sequence_analysis as analysis
import system_sequence_report as report
from tools import check_staged_sequence_evidence as evidence


class SyntheticRaw:
    def __init__(self, traces):
        self.time = np.linspace(0., .01, 1001)
        self.traces = {key.casefold(): np.asarray(value) for key, value in traces.items()}
        self.names = {key: index for index, key in enumerate(self.traces)}

    def trace(self, name):
        return self.traces[name.casefold()]

    def close(self):
        pass


def fixture(capacitance=10e-6, port=True):
    time = np.linspace(0., .01, 1001)
    inside = np.full_like(time, -.5)
    terminal = np.full_like(time, .5)
    terminal[387] = 2.
    terminal[800] = -.25
    traces = {'V(src)': np.full_like(time, 12.), 'I(vsrc)': inside,
              'I(port)': terminal, 'I(cap)': -inside-terminal}
    source = dict(voltage_probe='V(src)', current_probe='I(vsrc)', capacity_W=24.,
        config=dict(current_limit_A=1., protection_mode='monitor', rise_s=.001,
                    off_s=.02, resistance_ohm=.05, output_capacitance_F=capacitance,
                    output_esr_ohm=.1))
    if port:
        source.update(port_current_probe='I(port)', output_capacitor_current_probe='I(cap)')
    manifest = dict(settings=dict(stop_s=.01), sources={'BUS': source})
    return SyntheticRaw(traces), manifest


def analyze(raw, manifest):
    with patch.object(analysis, 'TransientRaw', return_value=raw):
        return analysis.analyze('synthetic-not-a-simulation.raw', manifest)


class SourceCapObservationChecks(unittest.TestCase):
    def test_kcl_peak_promotes_raw_float32_before_subtraction(self):
        raw,manifest=fixture(port=False)
        row=manifest['sources']['BUS']
        row.update(output_capacitor_current_probe='I(cap)',port_current_derivation='source-minus-capacitor')
        raw.traces['i(vsrc)']=np.full(1001,-2.,dtype=np.float32)
        raw.traces['i(cap)']=np.full(1001,-.052940726,dtype=np.float32)
        expected=-float(raw.traces['i(vsrc)'][0])-float(raw.traces['i(cap)'][0])
        self.assertEqual(analyze(raw,manifest)['summary']['sources'][0]['port_supply_current_peak_A'],expected)

    def test_terminal_discharge_spike_does_not_become_internal_overcurrent(self):
        raw, manifest = fixture()
        result = analyze(raw, manifest)
        source = result['summary']['sources'][0]
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(source['supply_current_peak_A'], .5)
        self.assertEqual(source['limiter_supply_current_peak_A'], .5)
        self.assertEqual(source['port_supply_current_peak_A'], 2.)
        self.assertEqual(source['port_supply_current_peak_s'], raw.time[387])
        self.assertEqual(source['port_reverse_current_peak_A'], .25)
        self.assertFalse(source['current_limit_exceeded'])
        self.assertIsNone(source['protection_passed'])
        self.assertIn('i(cap)', result['waveforms'])
        self.assertIn('port_power', source)

    def test_old_no_cap_source_keeps_existing_probe_sign(self):
        raw, manifest = fixture(capacitance=0., port=False)
        result = analyze(raw, manifest)
        source = result['summary']['sources'][0]
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(source['separate_port_current_probe'])
        self.assertEqual(source['port_supply_current_peak_A'], source['supply_current_peak_A'])
        self.assertEqual(source['port_reverse_current_peak_A'], source['reverse_current_peak_A'])

    def test_explicit_kcl_derivation_has_same_full_raw_peaks_without_port_sensor(self):
        raw, manifest = fixture()
        source_manifest=manifest['sources']['BUS']
        del source_manifest['port_current_probe']
        source_manifest['port_current_derivation']='source-minus-capacitor'
        del raw.traces['i(port)']
        result=analyze(raw,manifest)
        source=result['summary']['sources'][0]
        self.assertEqual(result['status'],'completed')
        self.assertTrue(source['derived_port_current'])
        self.assertFalse(source['separate_port_current_probe'])
        self.assertEqual(source['port_current_method'],'source-minus-capacitor')
        self.assertEqual(source['port_supply_current_peak_A'],2.)
        self.assertEqual(source['port_reverse_current_peak_A'],.25)
        self.assertFalse(source['current_limit_exceeded'])
        self.assertTrue(any('不作为独立电流守恒验证' in text for text in result['limitations']))
        self.assertIn('按KCL组合派生',repr(list(report.sections(manifest,result))))
        waves=dict(result['waveforms'])
        key, label, sign=report.source_port_plot('BUS',source_manifest,waves)
        self.assertEqual(sign,1)
        self.assertIn('探针组合',label)
        expected=-np.array(waves['i(vsrc)'])-np.array(waves['i(cap)'])
        np.testing.assert_allclose(waves[key],expected)

    def test_kcl_derivation_with_missing_cap_probe_is_unknown_not_fallback(self):
        raw, manifest=fixture(port=False)
        manifest['sources']['BUS']['port_current_derivation']='source-minus-capacitor'
        result=analyze(raw,manifest)
        self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['summary']['sources'][0]['port_supply_current_peak_A'])

    def test_explicit_direct_port_sensor_takes_priority_over_legacy_derivation(self):
        raw, manifest=fixture()
        manifest['sources']['BUS']['port_current_derivation']='source-minus-capacitor'
        raw.traces['i(port)'][387]=1.75
        result=analyze(raw,manifest)
        source=result['summary']['sources'][0]
        self.assertFalse(source['derived_port_current'])
        self.assertEqual(source['port_current_method'],'direct-probe')
        self.assertEqual(source['port_supply_current_peak_A'],1.75)

    def test_new_energy_store_cannot_silently_fallback_to_internal_probe(self):
        raw, manifest = fixture(port=False)
        result = analyze(raw, manifest)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['summary']['sources'][0]['port_supply_current_peak_A'])

    def test_declared_missing_port_or_cap_probe_is_analysis_failure(self):
        for missing in ('i(port)', 'i(cap)'):
            with self.subTest(missing=missing):
                raw, manifest = fixture()
                del raw.traces[missing]
                result = analyze(raw, manifest)
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['analysis_complete'])

    def test_report_distinguishes_both_sensors_and_declared_storage(self):
        raw, manifest = fixture()
        result = analyze(raw, manifest)
        sections = list(report.sections(manifest, result))
        text = repr(sections)
        self.assertIn('限流器供流峰 A', text)
        self.assertIn('源端口供流峰 A', text)
        self.assertIn('10 µF / 100 mΩ', text)
        findings = '\n'.join(report.findings(result))
        self.assertIn('不单独判为过流', findings)
        self.assertNotIn('超过本例内部门限', findings)

    def charge_fixture(self):
        time = np.linspace(0., .01, 1001)
        capacitance, esr = .001, .1
        cap_current = .2-40*time
        voltage = 10.+(.2*time-20*time**2)/capacitance+esr*cap_current
        supply = np.full_like(time, .5)
        return time, voltage, supply, supply-cap_current, cap_current, capacitance, esr

    def test_charge_and_kcl_with_esr_use_full_samples_and_chunk_boundaries(self):
        args = self.charge_fixture()
        full = evidence.source_capacitor_balance(*args)
        with patch.object(evidence, 'CHUNK', 37):
            chunked = evidence.source_capacitor_balance(*args)
        for result in (full, chunked):
            self.assertTrue(result['kcl_passed'])
            self.assertTrue(result['charge_passed'])
            self.assertLess(result['max_charge_residual_C'], 1e-14)
        self.assertAlmostEqual(full['capacitor_charge_integral_C'], chunked['capacitor_charge_integral_C'], places=14)

    def test_wrong_cap_current_sign_is_not_accepted(self):
        args = list(self.charge_fixture())
        args[4] *= -1
        result = evidence.source_capacitor_balance(*args)
        self.assertFalse(result['kcl_passed'])
        self.assertFalse(result['charge_passed'])

    def test_wrong_capacitance_or_esr_cannot_pass_charge_balance(self):
        for field, value in ((5, .002), (6, 1.)):
            with self.subTest(field=field):
                args = list(self.charge_fixture())
                args[field] = value
                result = evidence.source_capacitor_balance(*args)
                self.assertTrue(result['kcl_passed'])
                self.assertFalse(result['charge_passed'])


if __name__ == '__main__':
    unittest.main()
