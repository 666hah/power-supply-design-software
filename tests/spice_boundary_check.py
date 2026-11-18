import json
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from design_engine.service import calculate
from spice_boundary import endpoint_cases, load_definition, prepare_load_deck, run_load_transient
from spice_export import normalize_settings, project_files
from spice_runtime import _run, find_ltspice


class BoundaryChecks(unittest.TestCase):
    def test_endpoints_exclude_interior_and_duplicates(self):
        p = dict(V_in=24., V_in_min=20., V_in_max=30.)
        cases = [dict(voltage=value) for value in (24.,30.,30.,20.)]
        self.assertEqual([c['voltage'] for c in endpoint_cases(p,cases)], [20.,30.])
        self.assertEqual(len(endpoint_cases(dict(p,V_in_min=30.),cases)),1)
        with self.assertRaisesRegex(ValueError,'缺少'):
            endpoint_cases(p,cases[:-1])

    def test_step_is_standardized_independent_of_cross_limits_and_asc(self):
        p=dict(topology='BUCK', V_out=12., P_out=12.)
        settings=normalize_settings()
        fractions=(.1,.9)
        for minimum, after in ((None,.5),(.6,.5),(12.,.04),(9.,.01),(12.,2.)):
            step=load_definition(dict(p,P_out_min=minimum),dict(settings,load_after=after))
            for actual, expected in zip((step['low_fraction'],step['high_fraction']),fractions):
                self.assertAlmostEqual(actual,expected)
            for event, before, after in zip(step['stimulus'],fractions,reversed(fractions)):
                self.assertAlmostEqual(event['before'],before)
                self.assertAlmostEqual(event['after'],after)
            self.assertAlmostEqual(step['stop_s'],.016)

    def test_feedback_only_and_unchanged_switching_timestep(self):
        for example in ('40W_CCM_3OUT_FLYBACK','90W_QR_L6565_252_442V_REFERENCE','96W_BUCK_COT_4PH','24W_BUCK_VM_TPS40200'):
            with self.subTest(example=example):
                design=json.loads((ROOT/'examples'/(example+'.json')).read_text('utf-8'))
                bundle=calculate(design,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
                p=bundle['base_spec']
                files=project_files(p,bundle=bundle)
                settings=normalize_settings(p.get('spice_config'))
                feedback=2 if example.startswith('40W') else 1
                definition=load_definition(dict(p,feedback_output=feedback),settings)
                self.assertEqual(definition['feedback_output'],feedback)
                step=prepare_load_deck(files,definition,cot='COT' in example)
                old=files['power_stage.inc'].splitlines()
                changed=[new for old_card,new in zip(old,step['power_stage.inc'].splitlines()) if old_card!=new]
                self.assertEqual(len(changed),1)
                self.assertTrue(changed[0].startswith((f'BLOAD{feedback} '.encode(),b'B_LOAD ')))
                self.assertEqual(changed[0].count(b'limit((time-'),2)
                self.assertIn(next(s for s in files['analysis.inc'].splitlines() if s.startswith(b'.tran ')),step['analysis.inc'])
                self.assertIn('stimulus.json',step)

    @unittest.skipUnless(os.environ.get('RUN_BOUNDARY_LTSPICE')=='1','opt-in LTspice fixture')
    def test_real_dual_edge_fixture(self):
        files={'Flyback.cir':b'Boundary RC fixture\n.include design_params.inc\n.include power_stage.inc\n.include analysis.inc\n.end\n',
               'design_params.inc':b'.param RLOAD1=12\n',
               'power_stage.inc':b'VIN vin 0 12\nRPATH vin out1 .1\nCOUT out1 0 47u\nVG sgnd 0 0\nBLOAD1 out1 sgnd I=V(out1,sgnd)/{RLOAD1}*(1+({LOAD_AFTER}-1)*limit((time-{TLOAD})/1e-6,0,1))\n',
               'analysis.inc':b'.options plotwinsize=300\n.tran 0 {TSTOP} 0 1u\n'}
        case=dict(p=dict(topology='BUCK',V_out=12.,P_out=12.),result=dict(op=dict(f_sw=100e3)))
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temp:
            record=run_load_transient(files,case,normalize_settings(),Path(temp)/'step',
                lambda folder,timeout:_run(find_ltspice(),folder,timeout,lambda:False))
        self.assertTrue(record['complete'],record)
        rise, fall=record['events']
        self.assertAlmostEqual(rise['droop_v'],.0793,delta=.001)
        self.assertAlmostEqual(fall['overshoot_v'],.0793,delta=.001)


if __name__=='__main__':unittest.main(verbosity=2)
