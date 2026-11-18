"""Current metrology checks independent of QR physical-model agreement."""
from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qr_spice_analysis import cycle_current_statistics,charge_balance,excitation_ramps


class Raw:
    def __init__(self):
        self.time=np.r_[np.linspace(0,.1,1000),.5,1.,2.,3.,4.,5.,6.,7.,8.]
    def trace(self,name):
        return {'i(lp)':self.time,'i(ls1)':self.time*.5,
                'i(xd_o1:dmain)':self.time*.4,'i(xd_o1:cj)':self.time*.1,
                'v(rect1)':self.time*0+2,'v(cap1)':self.time*0+1}[name]


class QRCurrentMetrology(unittest.TestCase):
    def quality(self):return {'cycles':[dict(start_s=i,end_s=i+1.) for i in range(8)]}

    def test_excitation_ramp_retains_only_real_points_and_separates_pulses(self):
        time = np.arange(81)*25e-9
        gate = np.where(((time>=100e-9)&(time<800e-9)) | ((time>=950e-9)&(time<1750e-9)),10.,0.)
        sense = time*3e5 + .1
        current = np.where(time<950e-9,time-100e-9,time-950e-9)*2e6
        original = current.copy()
        current[[6,10,40,44]] = 50.
        result = excitation_ramps({'time':time,'v(gate)':gate+sense,'v(sense)':sense,'i(lp)':current},
                                  {'VG':10.,'TLEB':150e-9})
        self.assertEqual(result['blank_s'],150e-9)
        self.assertEqual(len(result['segments']),2)
        self.assertLess(result['peak_A'],2.)
        for segment in result['segments']:
            t = segment['time_s']
            self.assertGreaterEqual(t[0], segment['turn_on_s']+result['blank_s'])
            self.assertLess(t[-1],segment['turn_off_s'])
            np.testing.assert_array_equal(segment['current_A'],original[np.searchsorted(time,t)])
        self.assertEqual(max(current),50.)

    def test_excitation_ramp_excludes_short_pulses_and_late_dips(self):
        time = np.arange(41)*100e-9
        gate = np.where((time>=.1e-6)&(time<2e-6),10.,0.)
        current = time*1e6
        result = excitation_ramps({'time':time,'v(gate)':gate,'v(sense)':gate*0.,'i(lp)':current},
                                  {'VG':10.,'TBLANK':2e-6})
        self.assertFalse(result['available'])
        short = excitation_ramps({'time':time,'v(gate)':gate,'v(sense)':gate*0.}, {'VG':10.})
        self.assertFalse(short['available'])
        current[12] = -2.
        dip = excitation_ramps({'time':time,'v(gate)':gate,'v(sense)':gate*0.,'i(lp)':current}, {'VG':10.})
        self.assertFalse(dip['available'])
    def test_exact_linear_square_with_adaptive_sampling(self):
        r=cycle_current_statistics(Raw(),self.quality(),1)
        self.assertAlmostEqual(r['measurements']['primary_avg'],4.,12)
        self.assertAlmostEqual(r['measurements']['primary_rms'],8/np.sqrt(3),12)
        self.assertEqual(r['measurements']['primary_peak'],8.)
        self.assertEqual((r['periods'],r['frequency_hz']),(8,1.))
    def test_conduction_and_displacement_are_separate(self):
        r=cycle_current_statistics(Raw(),self.quality(),1)
        self.assertAlmostEqual(r['measurements']['out1_winding_avg'],2.)
        self.assertAlmostEqual(r['measurements']['out1_rectifier_avg'],1.6)
        row=next(x for x in r['signals'] if x['signal']=='i(xd_o1:cj)')
        self.assertAlmostEqual(row['mean_A'],.4)
        self.assertAlmostEqual(row['mean_power_W'],.4)
        missing=next(x for x in r['signals'] if x['signal']=='i(xq1:smain)')
        self.assertFalse(missing['available'])
        self.assertNotIn('switch_rms',r['measurements'])
    def test_discontinuous_or_short_cycle_set_has_no_fake_complete_window(self):
        q=self.quality();q['cycles'][4]['start_s']+=.1
        self.assertFalse(cycle_current_statistics(Raw(),q,1)['available'])
        self.assertFalse(cycle_current_statistics(Raw(),{'cycles':[]},1)['available'])
    def test_flat_looking_voltage_does_not_hide_capacitor_charge(self):
        case={'result':{'op':{'R':300.}}}
        audit={'outputs':[{'id':1,'mean_voltage_V':15.}],
               'measurements':{'out1_winding_avg':.054}}
        result=charge_balance(audit,case)
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['rows'][0]['relative_percent'],8.)
        audit['measurements']['out1_winding_avg']=.0501
        self.assertTrue(charge_balance(audit,case)['passed'])

    def test_switch_probe_direction_is_explicit_and_missing_metadata_is_not_guessed(self):
        class SwitchRaw(Raw):
            def trace(self,name):
                extra={'i(xq1:smain)':-.5*self.time,'v(drain)':self.time*0+1.,
                       'v(sense)':self.time*0}
                return extra[name] if name in extra else super().trace(name)
        raw=SwitchRaw()
        unknown=cycle_current_statistics(raw,self.quality(),1)
        self.assertNotIn('switch_rms',unknown['measurements'])
        probe=next(s for s in unknown['signals'] if s['signal']=='i(xq1:smain)')
        self.assertTrue(probe['raw_probe_present']);self.assertFalse(probe['available'])
        result=cycle_current_statistics(raw,self.quality(),1,
            current_observation={'mos_channel_direction_scale':-1.,'mos_channel_direction_note':'Verified S→D RAW'})
        self.assertAlmostEqual(result['measurements']['switch_avg'],2.)
        self.assertAlmostEqual(result['measurements']['switch_peak'],4.)
        row=next(s for s in result['signals'] if s['signal']=='i(xq1:smain)')
        self.assertAlmostEqual(row['mean_power_W'],2.)
        self.assertEqual(row['direction_scale'],-1.)

    def test_full_bandwidth_channel_peak_is_not_passed_as_energy_transfer_peak(self):
        from spice_runtime import _comparison_rows
        op=dict(f_sw=50000.,D=.3,I_sw_rms=1.,I_sw_pk=2.,I_sw_avg=.5,
                V_sw_max=500.,V_out=60.,I_d_rms=2.,I_d_pk=4.,I_d_avg=1.,V_d_max=200.)
        case=dict(voltage=300.,p=dict(f_sw=50000.,Rs=.33),result=dict(op=op,wf=dict(ripple_pp=.1)))
        meta=dict(topology='QR-FLYBACK',settings=dict(comparison_tolerance_pct=5.),hardware=dict(windings=[{}]))
        measured=dict(out1_earlier=60.,out1_before=60.,fault_max=0.,switch_rms=1.1,switch_avg=.5,switch_peak=39.)
        rows,ready=_comparison_rows(case,measured,meta)
        self.assertTrue(ready)
        peak=next(r for r in rows if r['metric']=='MOS Q1 沟道电流 峰值')
        rms=next(r for r in rows if r['metric']=='MOS Q1 沟道电流 RMS')
        self.assertIsNone(peak['delta_percent']);self.assertIn('口径不同',peak['status'])
        self.assertEqual(peak['simulation'],39.)
        self.assertAlmostEqual(rms['delta_percent'],10.)


if __name__=='__main__':unittest.main(verbosity=2)
