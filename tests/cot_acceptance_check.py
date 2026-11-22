"""COT acceptance regressions: valid FRA is not the same as a safe margin."""
from pathlib import Path
import sys
import unittest
from copy import deepcopy
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cot_acceptance import assess_fra, transient_acceptance, assess_case, limits


def probe():
    record=dict(f=[100.,1000.,10000.],db=[20.,0.,-20.],phase=[-90.,-120.,-180.],fc=1000.,pm=60.,gm_db=20.)
    return dict(available=True,simulation={'loop':deepcopy(record)},design={'loop':deepcopy(record)})


class Raw:
    def __init__(self):
        self.time=np.linspace(0,.006,6001)
        self.values={'v(out1)':np.minimum(self.time/.001,1.),'i(vin_source)':np.full(6001,-2.),
                     'v(sensed1)':np.full(6001,10.),'v(sensed2)':np.full(6001,10.),
                     'i(l1)':np.full(6001,10.),'i(l2)':np.full(6001,10.),
                     'v(ocp1)':np.zeros(6001),'v(ocp2)':np.zeros(6001),
                     'v(fault)':np.zeros(6001),'v(ovp)':np.zeros(6001)}
    def trace(self,name): return self.values[name]


def dynamic(raw):
    p={'V_out':1.,'cot_config':{'phase_limit_A':20.}}
    case={'p':p,'result':{'op':{'V_out':1.,'f_sw':400000.,'cot':{'phases':2}}}}
    return transient_acceptance(case,raw,dict(step_ms=3.,soft_start_ms=1.,enable_delay_ms=0.),
                                [dict(average_A=10.),dict(average_A=10.)])


class AcceptanceTests(unittest.TestCase):
    def test_valid_fra_with_inadequate_margin_fails(self):
        p=probe(); p['simulation']['loop']['pm']=18.
        result=assess_fra(p,{})
        self.assertFalse(result['passed']);self.assertEqual(result['status'],'fail')
        self.assertEqual(next(r for r in result['rows'] if r['id']=='pm')['status'],'fail')

    def test_phase_margin_acceptance_checks_smallest_crossing_against_fixed_limit(self):
        for margin, expected in ((45., 'fail'), (45.01, 'pass')):
            with self.subTest(margin=margin):
                data = probe()
                data['simulation']['loop']['crossings'] = [dict(pm=60.), dict(pm=margin)]
                result = assess_fra(data, {'cot_config': {'acceptance': {'pm_min_deg': 80.}}})
                row = next(r for r in result['rows'] if r['id'] == 'pm')
                self.assertEqual((row['comparison'], row['limit'], row['value'], row['status']),
                                 ('>', 45., margin, expected))

    def test_missing_gain_margin_cannot_become_infinite_or_pass(self):
        p=probe(); p['simulation']['loop']['gm_db']=None
        result=assess_fra(p,{})
        self.assertEqual(result['status'],'review')
        self.assertEqual(next(r for r in result['rows'] if r['id']=='gm')['status'],'not_covered')
        self.assertTrue(assess_fra(probe(),{})['passed'])

    def test_valid_measurement_with_model_discrepancy_fails(self):
        p=probe(); p['simulation']['loop']['fc']=1500.
        self.assertFalse(assess_fra(p,{})['passed'])
        p=probe(); p['simulation']['loop']['db'][1]=4.
        self.assertEqual(assess_fra(p,{})['status'],'fail')

    def test_full_resolution_peak_and_protection_event_are_preserved(self):
        raw=Raw();raw.values['i(l2)'][3151]=26.;raw.values['v(sensed2)'][3151]=26.
        raw.values['v(ocp2)'][3151:3153]=1.
        report=dynamic(raw)
        self.assertEqual(report['phase_peaks'][1]['peak_A'],26.)
        self.assertEqual(report['events'][1]['count'],1)
        self.assertEqual(report['status'],'fail')

    def test_dynamic_failures_and_nonsettling_are_not_hidden_by_steady_window(self):
        raw=Raw(); raw.values['v(out1)'][3000:]=.8
        report=dynamic(raw)
        self.assertEqual(next(r for r in report['rows'] if r['id']=='step_undershoot')['status'],'fail')
        self.assertEqual(next(r for r in report['rows'] if r['id']=='step_recovery')['status'],'fail')
        record=dict(nominal_comparable=True,dynamic=report,loop={})
        self.assertEqual(assess_case(record,{},fra_requested=False)['status'],'fail')

    def test_explicit_voltage_limits_and_missing_traces(self):
        configured=limits({'V_out':1.2,'cot_config':{'dynamic':{'droop_V':.024}}})
        self.assertAlmostEqual(configured['undershoot_pct'],2.)
        raw=Raw();del raw.values['v(sensed2)']
        self.assertEqual(dynamic(raw)['status'],'review')

    def test_disabled_limit_and_missing_event_are_not_passes(self):
        raw=Raw()
        case={'p':{'V_out':1.,'cot_config':{}},'result':{'op':{'V_out':1.,'f_sw':400000.,'cot':{'phases':2}}}}
        result=transient_acceptance(case,raw,dict(step_ms=3.,soft_start_ms=1.,enable_delay_ms=0.),
                                   [dict(average_A=10.),dict(average_A=10.)])
        self.assertEqual(next(r for r in result['rows'] if r['id']=='phase1_limit')['status'],'not_covered')
        del raw.values['v(ocp2)']
        self.assertEqual(next(r for r in dynamic(raw)['rows'] if r['id']=='ocp_events')['status'],'not_covered')


if __name__=='__main__': unittest.main(verbosity=2)
