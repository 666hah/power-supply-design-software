"""Configuration and generated-circuit contracts, not simulator evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import power_network
from system_sequence_config import normalize
from system_sequence_export import project_files


def sample():
    return power_network.normalize(dict(schema_version='power.system-network/2',title='source and load fixture',revision='A',
        sources=[dict(id='SRC',name='source',min=5.,max=5.,capacity=10.,enabled=True),
                 dict(id='PG',name='other rail',min=3.3,max=3.3,capacity=1.,enabled=True)],
        units=[],junctions=[],loads=[dict(id='LOAD',name='board',power=1.,min=0,max=6.,enabled=True)],
        connections=[dict(id='E1',source=dict(kind='bus',id='SRC',output=1),target='LOAD',mode='direct',vf=0.,enabled=True)],
        layout=dict(nodes={})))


def staged():
    p=sample();c=normalize(p);p['sequence_config']=c
    c['loads']['LOAD'].update(mode='I',on_V=4.2,off_V=3.8,off_current_A=.001,
        stages=[dict(name='boot',after_s=0.,mode='I',power_W=.5,ramp_s=.001),
                dict(name='run',after_s=.003,mode='I',power_W=1.5,ramp_s=.001)],
        ready_conditions=[dict(port='PG',on_V=3.,off_V=2.7)])
    return p,c


class Behaviors(unittest.TestCase):
    def test_empty_defaults_retain_monitor_and_one_stage_legacy(self):
        c=normalize(sample())
        self.assertEqual(c['sources']['SRC']['protection_mode'],'monitor')
        self.assertEqual(c['loads']['LOAD']['stages'],[])

    def test_profile_overrides_old_order_and_keeps_copies_isolated(self):
        p=sample();c=normalize(p);p['sequence_config']=c
        row=c['sources']['SRC'];row.update(off_s=0.,rise_s=1.,voltage_profile=[dict(time_s=0,level=0),dict(time_s=.001,level=1)])
        d=normalize(p);d['sources']['SRC']['voltage_profile'][0]['level']=.5
        self.assertEqual(row['voltage_profile'][0]['level'],0)
        files,_=project_files(p);self.assertIn('PWL(0 0 0.001 5)',files['SystemNetwork.inc'].decode())

    def test_bad_profiles_are_rejected(self):
        for profile in ([dict(time_s=.001,level=0),dict(time_s=.002,level=1)],
                        [dict(time_s=0,level=0),dict(time_s=0,level=1)],
                        [dict(time_s=0,level=float('nan')),dict(time_s=.001,level=1)]):
            p=sample();p['sequence_config']=normalize(p);p['sequence_config']['sources']['SRC']['voltage_profile']=profile
            with self.assertRaises(ValueError):normalize(p)

    def test_active_limit_requires_current_and_explicit_inductive_path(self):
        p=sample();c=normalize(p);p['sequence_config']=c;row=c['sources']['SRC'];row['protection_mode']='cc'
        with self.assertRaisesRegex(ValueError,'填写'):normalize(p)
        row.update(current_limit_A=1.,inductance_H=1e-6)
        with self.assertRaisesRegex(ValueError,'续流'):normalize(p)

    def test_foldback_order(self):
        p=sample();c=normalize(p);p['sequence_config']=c
        c['sources']['SRC'].update(protection_mode='foldback',current_limit_A=1.,foldback_short_A=2.)
        with self.assertRaises(ValueError):normalize(p)

    def test_hiccup_probes_and_timers(self):
        p=sample();c=normalize(p);p['sequence_config']=c
        c['sources']['SRC'].update(protection_mode='hiccup',current_limit_A=1.)
        files,m=project_files(p);deck=files['SystemNetwork.inc'].decode()
        self.assertIn('SRFLOP',deck);self.assertNotIn('idt(',deck)
        self.assertIn(m['sources']['SRC']['limit_active_probe'],deck)
        self.assertIn(m['sources']['SRC']['fault_probe'],deck)

    def test_or_transition_preserves_user_drop_and_records_approximation(self):
        p=sample();p['connections'][0].update(mode='diode',vf=.57)
        before=copy.deepcopy(p)
        files,m=project_files(p);deck=files['SystemNetwork.inc'].decode()
        self.assertIn('Vfwd=0.57 epsilon=1u',deck)
        self.assertEqual(m['interconnect_model']['diode_transition_V'],1e-6)
        self.assertEqual(m['interconnect_model']['diode_on_resistance_ohm'],.001)
        self.assertEqual(p,before)

    def test_source_output_capacitor_has_separate_port_current(self):
        p=sample();p['sequence_config']=normalize(p)
        p['sequence_config']['sources']['SRC'].update(protection_mode='cc',current_limit_A=1.,
            output_capacitance_F=10e-6,output_esr_ohm=0.)
        files,m=project_files(p);deck=files['SystemNetwork.inc'].decode()
        row=m['sources']['SRC']
        self.assertIn('CS01_OUTPUT N001 0 1e-05 Rser=0',deck)
        self.assertNotIn('VS01_PORT',deck)
        self.assertEqual(row['port_current_derivation'],'source-minus-capacitor')
        self.assertEqual(row['output_capacitor_current_probe'],'I(CS01_OUTPUT)')
        self.assertEqual(row['current_probe'],'I(VS01)')
        p['sequence_config']['sources']['SRC']['output_capacitance_F']=0.
        files,m=project_files(p)
        self.assertNotIn('CS01_OUTPUT',files['SystemNetwork.inc'].decode())
        self.assertNotIn('port_current_probe',m['sources']['SRC'])

    def test_stage_probes_and_persistent_capacitor(self):
        p,c=staged();c['loads']['LOAD']['input_capacitance_F']=47e-6
        files,m=project_files(p);deck=files['SystemNetwork.inc'].decode()
        for key in ('stage_probe','ready_probe','age_probe','active_current_probe'):
            self.assertIn(m['loads']['LOAD'][key],deck)
        self.assertIn('CLD001 LD001_port 0 4.7e-05',deck)
        self.assertNotIn('idt(',deck)

    def test_stage_overlap_and_initial_offset(self):
        for change in (dict(after_s=.0005),dict(after_s=0)):
            p,c=staged();c['loads']['LOAD']['stages'][1].update(change)
            with self.assertRaises(ValueError):normalize(p)
        p,c=staged();c['loads']['LOAD']['stages'][0]['after_s']=.001
        with self.assertRaises(ValueError):normalize(p)

    def test_stage_current_needs_local_brownout(self):
        p,c=staged();c['loads']['LOAD'].update(mode='R',on_V=None,off_V=None)
        with self.assertRaisesRegex(ValueError,'耗功启停'):normalize(p)

    def test_missing_condition_is_preserved_but_export_rejected(self):
        p,c=staged();c['loads']['LOAD']['ready_conditions'][0]['port']='missing'
        self.assertEqual(normalize(p)['loads']['LOAD']['ready_conditions'][0]['port'],'missing')
        with self.assertRaisesRegex(ValueError,'不存在'):project_files(p)


if __name__=='__main__':unittest.main(verbosity=2)
