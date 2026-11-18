from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spice_black_box import black_box_sections, full_load_ports, measure_load_steps


class Raw:
    def __init__(self, points, voltages, ground=0.):
        self.time = np.asarray(points)
        self.signals = {'v(out1)':np.asarray(voltages)+ground,'v(sgnd)':np.full_like(self.time,ground)}

    def trace(self, name):
        return self.signals[name]


class BlackBox(unittest.TestCase):
    def test_startup_threshold_interpolation_and_sustained_reentry(self):
        raw = Raw([0.,.001,.002,.0025,.003,.01],[0,5,10,11,10,10],ground=40.)
        case = {'p':{'topology':'BUCK','V_out':10}}
        black = full_load_ports(raw,case,end_s=.009,frequency_hz=1e5,return_node='v(sgnd)',comparable=True)
        port = black['ports'][0]
        self.assertAlmostEqual(port['rise_s'],.0016)
        self.assertAlmostEqual(port['t90_s'],.0018)
        self.assertAlmostEqual(port['peak_above_reference_pct'],10.)
        self.assertAlmostEqual(port['in_band_s'],.0029)

    def test_two_directions_full_resolution_minimum_and_sustained_recovery(self):
        raw = Raw([0,.009,.010,.01001,.01002,.011,.020,.02001,.02002,.021,.030],
                  [10,10,10,8.5,10,10,10,11,10,10,10],ground=50.)
        events = [dict(time_s=.010,before=.1,after=.9,rail=1),dict(time_s=.020,before=.9,after=.1,rail=1)]
        measured = measure_load_steps(raw,events,reference_v=10,frequency_hz=1e5,stop_s=.03,return_node='v(sgnd)')
        self.assertTrue(measured['available'])
        self.assertAlmostEqual(measured['events'][0]['droop_v'],1.5)
        self.assertAlmostEqual(measured['events'][1]['overshoot_v'],1.)
        self.assertAlmostEqual(measured['events'][1]['recovery_s'],18e-6)
        self.assertFalse(measure_load_steps(raw,events[:1],reference_v=10,frequency_hz=1e5,stop_s=.03)['available'])
        self.assertFalse(measure_load_steps(raw,events,reference_v=10,frequency_hz=1e5,stop_s=.05)['available'])

    def test_missing_input_and_last_sample_not_settled(self):
        raw = Raw([0.,.01,.02,.03],[10,10,10,10.5])
        events = [dict(time_s=.01,before=.1,after=.9,rail=1),dict(time_s=.02,before=.9,after=.1,rail=1)]
        result = measure_load_steps(raw,events,reference_v=10,frequency_hz=1e5,stop_s=.03)
        self.assertIsNone(result['events'][1]['recovery_s'])
        result = measure_load_steps(raw,events,reference_v=10,frequency_hz=1e5,stop_s=.03,return_node='missing')
        self.assertFalse(result['available'])
        self.assertTrue(result['events'][0]['error'])

    def test_voltage_accuracy_distinct_from_cross_span(self):
        row = dict(id=1,V_reference=10.,cross_only_pct=2.,deviation_min_pct=-1.,deviation_max_pct=1.,complete=True)
        def corner(loads):
            return dict(V_in=12.,powers=loads,settled=True,simulation=[10.,5.])
        case = dict(cross=dict(summary=dict(simulation=[row],design=[row]),records=[corner([5.,1.]),corner([5.,2.])]))
        title,_,rows,_ = black_box_sections(case,{})[-1]
        self.assertIn('交叉',title)
        self.assertEqual(rows[0][2:5],('-1 ～ 1','2','2'))
        case['cross']['records'][1]['settled']=False
        self.assertEqual(black_box_sections(case,{})[-1][2][0][4],'无同载配对')


if __name__ == '__main__':
    unittest.main()
