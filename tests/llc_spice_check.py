import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llc_model import solve
from llc_spice import measure_raw, project_files, write_project
from spice_runtime import _run, find_ltspice, read_log


def example(bridge='half',mode='Voltage Mode'):
    return dict(topology='LLC', V_in=390., V_out=48., P_out=300.,
                N=4. if bridge=='half' else 8., llc_bridge=bridge, control_mode=mode,
                f_sw=100e3,llc_lr=50e-6,llc_cr=50.66e-9,llc_lm=250e-6,
                llc_tank_r=.20,llc_rect_r=.015,Vf_diode=.55,Rds_on=.09,
                llc_fmin=55e3,llc_fmax=220e3,llc_dead_time=180e-9,llc_hhc_sense=.01,
                llc_hhc_ramp=4e5,llc_kp=0.,llc_ki=0.,llc_ocp=26.,llc_ovp=65.,
                Coss=220e-12,Qg=29e-9,llc_soft_start=.002,C_out=470e-6,Rc=.03)


class LLCSwitchedProject(unittest.TestCase):
    def test_physical_switches_and_timing_export_in_four_modes(self):
        for bridge in ('half','full'):
            for mode in ('Voltage Mode','Hybrid Hysteretic'):
                with self.subTest(bridge=bridge,mode=mode):
                    p=example(bridge,mode)
                    p['llc_ki']=1e7 if mode=='Voltage Mode' else 1200.
                    p.update(d_out_enable=True,Vf_dout=.25)
                    files=project_files(p,{'frequency_Hz':96e3,'hhc_threshold_V':2.8})
                    stage = files['llc_stage.inc'].decode('ascii')
                    meta = json.loads(files['manifest.json'])
                    self.assertIn('NTR='+('4' if bridge=='half' else '8'),stage)
                    self.assertIn('DBLOCKOUT cap out DREVOUT',stage)
                    self.assertIn('V(cap,sgnd)-V(inj)',stage)
                    for name in ('DR1','DR2','DR3','DR4'):
                        self.assertIn(f'{name} ',stage)
                    self.assertEqual(len(meta['switch_probes']),2 if bridge=='half' else 4)
                    self.assertIn('idtmod(' if mode=='Voltage Mode' else 'APHASE ',stage)
                    self.assertIn(b'!.include llc_stage.inc',files['LLC.asc'])

    def test_boundary_profiles_distinguish_load_step_and_small_signal_injection(self):
        p = dict(example(),llc_ki=1e7)
        op = {'frequency_Hz':96e3,'hhc_threshold_V':2.8}
        load=project_files(p,op,load_step=True)
        meta=json.loads(load['manifest.json'])
        self.assertGreater(meta['schedule']['step_down_s'],meta['schedule']['step_up_s'])
        self.assertIn(b' 0.1',load['llc_stage.inc'])
        self.assertIn(b' 0.9',load['llc_stage.inc'])
        full = project_files(dict(p,llc_bridge='full'),op,load_step=True)
        full_schedule = json.loads(full['manifest.json'])['schedule']
        self.assertLess(full_schedule['preload_s'],full_schedule['step_up_s'])
        self.assertIn(b'PWL(0 1 ',full['llc_stage.inc'])
        fra=project_files(p,op,fra_hz=1e3)
        fmeta=json.loads(fra['manifest.json'])
        self.assertEqual(fmeta['probes'],['v(cap)','v(inj)','v(fault)','v(gatep)'])
        full_fra = project_files(dict(p,llc_bridge='full'),op,fra_hz=1e3)
        self.assertIn(b'VINJ inj 0 SINE(0 0.1 1000 ',full_fra['llc_stage.inc'])
        self.assertRaises(ValueError,project_files,p,op,load_step=True,fra_hz=1e3)

    @unittest.skipUnless(find_ltspice(),'LTspice not installed')
    def test_native_switching_matches_case_after_startup(self):
        for bridge,mode in (('half','Voltage Mode'),('full','Hybrid Hysteretic')):
            with self.subTest(bridge=bridge,mode=mode), tempfile.TemporaryDirectory(prefix='llc-switched-') as tmp:
                p=example(bridge,mode)
                op=solve(p,points=100)
                write_project(tmp,p,op,tstop=.008)
                _run(find_ltspice(),tmp,75,lambda:False)
                _,_,errors,_=read_log(Path(tmp)/'Flyback.log')
                self.assertFalse(errors)
                measured=measure_raw(Path(tmp)/'Flyback.raw',p,op)
                self.assertTrue(measured['ready'])
                self.assertTrue(measured['no_gate_overlap'])
                self.assertFalse(measured['fault'])
                self.assertAlmostEqual(measured['V_out_V'],p['V_out'],delta=.5)
                for expected,actual in ((op['frequency_Hz'],measured['frequency_Hz']),
                                        (op['ir_rms_A'],measured['I_res_rms_A'])):
                    self.assertAlmostEqual(actual,expected,delta=.07*expected)
                self.assertGreater(measured['startup']['I_res_peak_A'],measured['I_res_peak_A'])
                self.assertIn('v(out)',measured['steady'])


if __name__ == '__main__':
    unittest.main()
