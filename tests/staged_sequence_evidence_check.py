"""Synthetic tests of the independent audit mechanics, not simulator evidence."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.check_staged_sequence_evidence import digital_observations, stage_observations, active_demand_deviation, resolve_run, audit, circuit_model_identity, restart_window
from tools.package_staged_sequence_example import audit_conclusions, digest, LABELS


class IndependentEvidenceTests(unittest.TestCase):
    def test_restart_precondition_uses_command_schedule_not_residual_reset(self):
        def manifest(drop,recovery):
            return {'sources':{'source':{'config':{'voltage_profile':[
                {'time_s':0,'level':0},{'time_s':.002,'level':1},
                {'time_s':drop,'level':1},{'time_s':drop+.0005,'level':0},
                {'time_s':recovery,'level':0},{'time_s':recovery+.002,'level':1}]}}}}
        old,new=restart_window(manifest(.018,.028)),restart_window(manifest(.022,.032))
        first_full=.018754885117417578
        self.assertFalse(first_full<old[0])
        self.assertTrue(first_full<new[0])
        self.assertEqual(new,(.022,.032))
        with self.assertRaisesRegex(ValueError,'缺少明确'):
            restart_window({'sources':{'source':{'config':{'voltage_profile':[]}}}})

    def test_mixed_model_results_cannot_pass_same_hardware(self):
        # Two individually successful runs with the same components can still
        # be incomparable if one used an older controller/linear-regulator.
        cases = {name:dict(scenario_expectations_met=True, hardware_sha256='same',
            model_sha256=model) for name,model in [('normal','old'),('weak_hiccup','new')]}
        with patch('tools.check_staged_sequence_evidence.resolve_run',return_value=ROOT), \
             patch('tools.check_staged_sequence_evidence.audit_case',side_effect=lambda root,name,run:cases[name]):
            result=audit(ROOT,['normal','weak_hiccup'])
        self.assertFalse(result['all_selected_expectations_met'])
        self.assertEqual([c['name'] for c in result['checks'] if not c['passed']],['各场景沿用同一仿真模型'])

    def test_model_identity_includes_ldo_but_not_scenario_netlist(self):
        manifest=dict(files={'U01_model.lib':dict(sha256='lib'), 'U03_unit.inc':dict(sha256='ldo'),
            'SystemNetwork.inc':dict(sha256='scenario-A')},interconnect_model={'version':'1'},
            settings={'include_switching_capacitance':True,'stop_s':.045})
        first=circuit_model_identity(manifest)
        manifest['files']['SystemNetwork.inc']['sha256']='scenario-B'
        manifest['settings']['stop_s']=.055
        self.assertEqual(first,circuit_model_identity(manifest))
        manifest['files']['U03_unit.inc']['sha256']='different-LDO'
        self.assertNotEqual(first,circuit_model_identity(manifest))

    def test_all_short_fault_events_survive(self):
        time=np.arange(10001,dtype=float)*1e-6
        values=np.zeros(len(time));values[173:175]=1;values[9001:9004]=1
        found=digital_observations(time,values)
        self.assertEqual(found['on_count'],2)
        self.assertEqual(found['off_count'],2)
        self.assertAlmostEqual(found['active_time_s'],5e-6)
        self.assertAlmostEqual(found['rise_s'][0],172.5e-6)

    def test_high_at_end_is_censored(self):
        found=digital_observations(np.array([0.,1.,2.]),np.array([0.,1.,1.]))
        self.assertEqual(found['on_count'],1)
        self.assertEqual(found['off_count'],0)
        self.assertEqual(found['active_time_s'],1.5)
        self.assertTrue(found['right_censored'])

    def test_stage_reset_is_not_later_global_time(self):
        time=np.arange(10,dtype=float)
        stages=np.array([0,0,1,2,2,0,0,1,2,2.])
        ready=np.array([0,1,1,1,1,0,1,1,1,1.])
        age=np.array([0,0,1,2,3,0,0,1,2,3.])
        plan=[dict(name='boot'),dict(name='run')]
        found=stage_observations(time,stages,ready,age,plan)
        self.assertEqual(found['entry_counts'],[2,2])
        self.assertEqual(found['restart_count'],1)
        self.assertEqual(len(found['resets']),1)
        second=found['entries'][2]
        self.assertEqual(second['time_s'],7)
        self.assertEqual(second['age_s'],1)
        self.assertEqual(second['ready_since_s'],5.5)

    def test_invalid_stage_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'索引'):
            stage_observations(np.array([0.,1.]),np.array([0.,3.]),np.array([0.,1.]),np.array([0.,1.]),[dict(name='one')])

    def test_stage_current_is_total_not_accumulated(self):
        time=np.arange(5,dtype=float);voltage=np.full(5,5.);ready=np.ones(5)
        config=dict(delay_s=0.,nominal_voltage_V=5.,off_V=4.,stages=[
            dict(mode='I',power_W=1.,after_s=0.,ramp_s=1.),
            dict(mode='P',power_W=2.,after_s=2.,ramp_s=1.)])
        expected=np.array([0.,.2,.2,.4,.4])
        result=active_demand_deviation(time,voltage,time,ready,expected,config)
        self.assertEqual(result['max_error_A'],0.)
        wrong=np.array([0.,.2,.2,.6,.6])
        result=active_demand_deviation(time,voltage,time,ready,wrong,config)
        self.assertGreater(result['max_allowance_ratio'],1.)

    def test_registry_pending_does_not_use_old_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            root=Path(directory);old=root/'normal'/'old';old.mkdir(parents=True)
            (old/'result.json').write_text('{}')
            (root/'validation.json').write_text(json.dumps(dict(cases=dict(normal=dict(status='not_run')))))
            with self.assertRaisesRegex(ValueError,'历史成功'):
                resolve_run(root,'normal')
            self.assertEqual(resolve_run(root,'normal',old),old.resolve())

    def test_ambiguous_unregistered_runs_require_selection(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            root=Path(directory)
            for name in ('one','two'):
                child=root/'normal'/name;child.mkdir(parents=True)
                (child/'result.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'明确指定'):
                resolve_run(root,'normal')

    def test_missing_evidence_fails_explicitly(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            found=audit(directory,['weak_hiccup'])
            self.assertFalse(found['all_selected_expectations_met'])
            self.assertFalse(found['cases']['weak_hiccup']['scenario_expectations_met'])
            self.assertIsNone(found['hardware_passed'])

    def test_package_without_audit_stays_unknown(self):
        states,info=audit_conclusions(None,{})
        self.assertIsNone(info)
        self.assertTrue(all(row['passed'] is None and not row['bound'] for row in states.values()))

    def test_package_binds_raw_and_preserves_expected_fault_label(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            root=Path(directory);runs={};cases={}
            for name in LABELS:
                run=root/name;run.mkdir();runs[name]=run
                hashes={}
                for file in ('project.json','manifest.json','result.json','Flyback.log','Flyback.raw'):
                    (run/file).write_text('synthetic binding test only '+name)
                    hashes[file]=digest(run/file)
                cases[name]=dict(sha256=hashes,scenario_expectations_met=True,checks=[])
            path=root/'audit.json'
            path.write_text(json.dumps(dict(schema='power.staged-sequence-independent-evidence/1',cases=cases,checks=[],all_selected_expectations_met=True)))
            states,info=audit_conclusions(path,runs)
            self.assertTrue(all(state['bound'] for state in states.values()))
            self.assertEqual(states['weak_hiccup']['text'],'符合故障预期')
            (runs['normal']/'Flyback.raw').write_text('different synthetic raw')
            states,info=audit_conclusions(path,runs)
            self.assertFalse(states['normal']['bound'])
            self.assertIsNone(states['normal']['passed'])
            self.assertIn('Flyback.raw',states['normal']['details'])


if __name__=='__main__':unittest.main()
