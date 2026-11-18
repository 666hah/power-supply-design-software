import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from design_engine.service import calculate
from spice_export import normalize_settings, project_files
from spice_line_load import prepare_line_load,run_line_load
from spice_runtime import _run,find_ltspice,read_log


class CombinedStudyChecks(unittest.TestCase):
    def test_tps40200_feedforward_uses_instantaneous_bus(self):
        design=json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text('utf-8'))
        bundle=calculate(design,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
        p=bundle['base_spec']
        source=project_files(p,bundle=bundle)
        deck,_=prepare_line_load(source,[p],[18.,30.],normalize_settings(p['spice_config']),p['f_sw'])
        self.assertIn(b'fault 0 vin_bus GNISO_CTRL ',deck['power_stage.inc'])
        self.assertIn(b'V(VIN_FF,COM)*{RAMP_RATIO}',deck['GenericBuckBoostPWM.lib'])
        self.assertIn(b'{1/FSW/60}',deck['analysis.inc'])
        if os.environ.get('RUN_BOUNDARY_LTSPICE')=='1':
            from spice_studies import write_study
            bench = {name: deck[name] for name in ('GenericFlybackPWM.lib','GenericBuckBoostPWM.lib')}
            bench['Flyback.cir'] = b'TPS40200 feedforward fixture\n.include GenericFlybackPWM.lib\n.include GenericBuckBoostPWM.lib\n.param RAMP_RATIO=0.1\nVFB fb 0 0\nVEN en 0 1\nVVCC vcc 0 10\nVINPUT feed 0 PWL(0 18 100u 18 101u 30 180u 30)\nXU_CTRL fb 0 en vcc gate comp ramp ss fault 0 feed GNISO_CTRL FSW=100k MODE=0 VM=1\n.tran 0 180u 0 100n\n.options plotwinsize=0\n.save V(ramp)\n.meas tran lowamp MAX V(ramp) FROM 40u TO 80u\n.meas tran highamp MAX V(ramp) FROM 120u TO 160u\n.end\n'
            with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temp:
                folder=Path(temp)
                write_study(folder,bench,'Timed feedforward boundary check.')
                _run(find_ltspice(),folder,30,lambda:False)
                measurements,_,errors,_=read_log(folder/'Flyback.log')
                self.assertFalse(errors,errors)
                self.assertAlmostEqual(measurements['lowamp'],1.8,delta=.02)
                self.assertAlmostEqual(measurements['highamp'],3.0,delta=.02)

    @unittest.skipUnless(os.environ.get('RUN_BOUNDARY_LTSPICE')=='1','opt-in LTspice fixture')
    def test_full_window_pattern_and_both_input_plateaux(self):
        files={'Flyback.cir':b'Combined line-load test fixture\n.include design_params.inc\n.include power_stage.inc\n.include analysis.inc\n.end\n',
               'design_params.inc':b'.param RLOAD1=12 RLOAD2=20\n',
               'power_stage.inc':b'VIN_SOURCE input 0 {VIN}\nVZERO sgnd 0 0\nVFAULT fault 0 0\nRS1 input out1 1\nRS2 input out2 1\nBLOAD1 out1 sgnd I=0\nBLOAD2 out2 sgnd I=0\n',
               'analysis.inc':b'.tran 0 {TSTOP} 0 100u\n'}
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temp:
            for inputs in ([12.,24.],[12.]):
                folder=Path(temp)/f'line-{len(inputs)}'
                result=run_line_load(files,[dict(P_out=12.),dict(P_out=1.,P_out_min=.05)],inputs,
                    normalize_settings(),1e3,folder,
                    lambda directory,timeout:_run(find_ltspice(),directory,timeout,lambda:False))
                log=read_log(folder/'Flyback.log')
                self.assertTrue(result['complete'],(result,log[1][-2200:]))
                self.assertEqual(result['line_plateaux_V'],[12.,max(inputs),12.])
                self.assertFalse(result['protection'])
                self.assertAlmostEqual(result['actual_end_s'],1.058)
                self.assertAlmostEqual(result['rows'][0]['min_V'],12/(1+.9/12),places=4)
                self.assertAlmostEqual(result['rows'][0]['max_V'],max(inputs)/(1+.1/12),places=4)
                values=log[0]
                self.assertAlmostEqual(values['patt2_min'],.1)
                self.assertAlmostEqual(values['patt2_max'],.9)
                self.assertEqual(set(result['waveform']['ports']),{'1','2'})


if __name__=='__main__':unittest.main(verbosity=2)
