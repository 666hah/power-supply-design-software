"""Enhanced COT contracts and real power-tree deck ownership boundaries."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.service import calculate
from cot_buck_spice import project_files, MODEL_VERSION
from cot_advanced_spice import VERSION
from system_sequence_units import compile_unit


class AdvancedCotChecks(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((ROOT/'examples/96W_BUCK_COT_4PH.json').read_text('utf-8'))
        self.p['cot_config']={}

    def generate(self,p=None):
        b=calculate(p or self.p,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
        return project_files(b['base_spec'],bundle=b,case=b['cases'][0])

    def test_absent_engineering_config_preserves_original_cadence(self):
        files=self.generate();meta=json.loads(files['manifest.json'])
        self.assertEqual(meta['model_version'],MODEL_VERSION)
        self.assertIn(b'delay(V(ticks),{TON})',files['control.inc'])
        self.assertNotIn(b'A_Q1',files['control.inc'])

    def test_current_feedback_mismatch_protection_and_fixture_are_explicit(self):
        self.p['cot_config']=dict(model='current_feedback',current_feedback_hz_per_a=2000.,
            phase_parameters=[dict(L_scale=1.1),dict(dcr_scale=.9),dict(sense_gain=1.02),dict(ton_scale=.99)],
            phase_limit_A=30.,dead_time_s=20e-9,light_load='diode_emulation',fault_mode='hiccup',
            prebias_V=.4,source_rise_s=.001,source_resistance_ohm=.01,source_inductance_H=100e-9,
            shutdown_s=.009,load_mode='current')
        files=self.generate();meta=json.loads(files['manifest.json'])
        self.assertEqual(meta['model_version'],VERSION)
        control=files['control.inc'];stage=files['power_stage.inc']
        for text in (b'CFGAIN*(V(ifilter)',b'A_USED4',b'A_Q4',b'A_ZCD4',b'delay(V(ocp4),{LIMITDELAY})',b'V(off4)>=1e6*TOFFMIN'):
            self.assertIn(text,control)
        self.assertIn(b'VIN_SOURCE input 0 PWL',stage)
        self.assertIn(b'IC={PREBIAS}',stage)
        self.assertIn(b'L_SOURCE feed vbus',stage)
        self.assertIn(b'L1 sw1 cap1 {LP*1.1}',stage)
        self.assertIn(b'Rser={DCR*0.9}',stage)

    def test_sequence_owns_sources_enable_and_consumers(self):
        self.p['cot_config']=dict(model='current_feedback',current_feedback_hz_per_a=1000.,
                                 source_resistance_ohm=.01,shutdown_s=.002)
        u=compile_unit(self.p,'COT1');text=u['subckt_text'];s=u['manifest']['sequence_unit']
        self.assertIn('.param SHUTDOWN=0',text)
        self.assertIn('.param TSTART=0',text)
        self.assertIn('V_COT_INPUT blocked vbus 0',text)
        self.assertIn('B_SEQ_I4 seq_i_l4 0 V=I(L4)',text)
        self.assertNotIn('\nB_LOAD ',text)
        self.assertNotIn('\nVIN_SOURCE ',text)
        self.assertNotIn('\nR_SOURCE ',text)
        self.assertNotIn('\nV_EN ',text)
        self.assertNotIn('GenericBuckBoostPWM',text)
        self.assertEqual(s['source_hashes'].keys(),{'power_stage.inc','control.inc','design_params.inc','analysis.inc'})
        self.assertLess(s['maximum_step_s'],1/(400000*4))


if __name__=='__main__':unittest.main(verbosity=2)
