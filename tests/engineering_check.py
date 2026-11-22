"""Shared-engine, snapshot, fixed-hardware and real GUI workflow regressions."""
import copy
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import tkinter as tk
import numpy as np
import control as ct

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from power_stage import DEFAULT_PARAMS, compute_operating_point
from config_io import decode_config, read_default_config
from design_api import load_spec, run_design
from loss_model import compute_design
from plants import build_loop_models
from loop_tuning import analyze_loop
from capripple import _divide_and_band, analyze_capacitors
from waveforms import make_waveforms
from analysis_workflows import evaluate, corners, pin_hardware, compare
from design_checks import check_catalog


class EngineChecks(unittest.TestCase):
    def test_startup_defaults(self):
        decoded=decode_config(read_default_config())
        for key in ('V_in','V_out','P_out','f_sw','L','Rs','A_sense','KP','fz1','fz2','fp1','fp2','K','Kc'):
            self.assertEqual(DEFAULT_PARAMS[key],decoded[key])
        self.assertEqual(DEFAULT_PARAMS['topology'],'FLYBACK')
        self.assertEqual(DEFAULT_PARAMS['sweep_min'],50e3)
        snap=evaluate(DEFAULT_PARAMS)
        self.assertEqual(snap['op']['mode'],'CCM')
        lcheck=next(c for c in snap['checks'] if c['id']=='L_min')
        self.assertIn('40%',lcheck['note'])
        self.assertIn('原边谷值',lcheck['note'])
        self.assertLess(lcheck['value'], lcheck['limit'])
        self.assertEqual(lcheck['state'], 'reference')
        self.assertIsNone(lcheck['margin'])
        self.assertNotIn('L_min', run_design(DEFAULT_PARAMS)['failed_checks'])
        # The saved compensator is preserved; the changed plant needs review,
        # not a silent retune to its historical target.
        from design_api import loop_margins_for
        self.assertAlmostEqual(snap['res']['loop']['fc'],loop_margins_for(DEFAULT_PARAMS)['fc'],places=3)

    def test_capacitance_dimensions(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=dict(DEFAULT_PARAMS,topology=topo,V_in=30,V_out=15 if topo=='BUCK' else 30 if topo=='ACF-FORWARD' else 40,
                   P_out=40,L=68e-6)
            a=compute_operating_point(p); b=compute_operating_point(dict(p,Rc=10))
            self.assertEqual(a['C_min'],b['C_min'],topo)

    def test_parseval_and_dc(self):
        f=100e3; N=4096; t=np.arange(N)/(N*f/2)
        x=3+np.sin(2*np.pi*f*t)+.4*np.sin(20*np.pi*f*t)
        cap=[dict(C=100e-6,ESR=.02,ESL=2e-9)]
        r=_divide_and_band(x,t[1]-t[0],f,cap)
        self.assertEqual(r['spectrum_method'],'coherent DFT')
        self.assertAlmostEqual(r['caps'][0]['total'],math.sqrt(.5+.08),places=12)
        self.assertAlmostEqual(sum(x*x for x in r['caps'][0]['bands']),r['total_bank']**2,places=12)
        nyquist=(-1.)**np.arange(N)
        self.assertAlmostEqual(_divide_and_band(nyquist,t[1]-t[0],f,cap)['caps'][0]['total'],1,places=12)

    def test_shared_caps_and_sampling(self):
        p=dict(DEFAULT_PARAMS); res=compute_design(p)
        caps=analyze_capacitors(p,res['op'],res['wf'])
        self.assertEqual(caps,res['capacitors'])
        loss=sum(c['ESR']*c['total']**2 for c in caps['output']['caps'])
        self.assertAlmostEqual(loss,res['P_cap'],places=12)
        doubled=analyze_capacitors(p,res['op'],make_waveforms(res['op'],n_pts=4096))
        for a,b in zip(caps['output']['caps'],doubled['output']['caps']):
            self.assertLess(abs(a['total']-b['total'])/b['total'],.005)

    def test_no_and_multiple_crossovers(self):
        one=ct.tf([1],[1]); tiny=ct.tf([.1],[1])
        r=analyze_loop(DEFAULT_PARAMS,(one,one,tiny))
        self.assertIsNone(r['fc']); self.assertIsNone(r['pm'])
        snap=compute_design(DEFAULT_PARAMS)
        c=next(c for c in check_catalog(DEFAULT_PARAMS,snap,r) if c['id']=='loop')
        self.assertEqual(c['state'],'review')
        band=ct.tf([100,0],[1,11,10])
        r=analyze_loop(DEFAULT_PARAMS,(one,one,band))
        self.assertEqual({c['direction'] for c in r['all_crosses']},{'up','down'})
        self.assertEqual(r['min_pm'],min(c['pm'] for c in r['all_crosses']))

    def test_api_catalog_matches(self):
        for topo in ('BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'):
            p=load_spec(dict(topology=topo,V_in=30,V_out=15 if topo=='BUCK' else 30 if topo=='ACF-FORWARD' else 40,P_out=40,L=68e-6))
            snap=evaluate(p); r=run_design(p)
            self.assertTrue(r['ok'],r.get('error'))
            self.assertEqual(r['checks'],snap['checks'],topo)
            self.assertEqual(r['loop']['fc'],snap['res']['loop']['fc'])
            self.assertEqual(r['operating_point']['f_sw'],snap['op']['f_sw'])

    def test_frozen_hardware(self):
        for topo in ('BUCK','FLYBACK','ACF-FORWARD'):
            p=dict(DEFAULT_PARAMS,topology=topo,V_out=15 if topo=='BUCK' else 30,L=68e-6,
                   core_choice='auto',core_shape='auto',Np=0,Ns=0,d_wire_p=0,d_wire_s=0,MLT=0)
            a=evaluate(p); pinned=pin_hardware(p,a['res'])
            b=evaluate(dict(pinned,P_out=p['P_out']*.1,V_in=p['V_in']*1.1))
            for kind in ('inductor','transformer'):
                if '_fixed_'+kind in pinned:
                    for key,val in pinned['_fixed_'+kind].items():
                        self.assertEqual(val,b['res']['mag'][kind][key],f'{topo} {kind} {key}')

    def test_corner_cancellation_and_worst(self):
        p=dict(DEFAULT_PARAMS); events=[]
        result=corners(p,progress=lambda *e:events.append(e))
        self.assertEqual(len(result['corners']),15)
        self.assertEqual(events[-1][:2],(15,15))
        self.assertTrue(result['fixed_hardware'])
        self.assertEqual(result['worst']['min_eta'],min(c['eta'] for c in result['corners'] if not c['skipped']))
        self.assertIn(result['worst_cases']['min_eta']['id'],[c['id'] for c in result['corners']])
        with self.assertRaises(InterruptedError): corners(p,cancelled=lambda:True)
        with self.assertRaises(ValueError): corners(p,35,25)

    def test_comparison_independence(self):
        p=dict(DEFAULT_PARAMS); a=evaluate(p); saved=copy.deepcopy(a['p'])
        b=evaluate(dict(p,C_out=p['C_out']*2))
        r=compare(a,b)
        self.assertEqual(a['p'],saved)
        self.assertEqual(p,DEFAULT_PARAMS)
        self.assertTrue(r['same_requirements'])
        self.assertEqual([d['key'] for d in r['differences']],['C_out'])
        eta=next(m for m in r['metrics'] if m['key']=='eta')
        self.assertAlmostEqual(eta['delta'],(b['res']['eta']-a['res']['eta'])*100)

    def test_gui_config_api_alias(self):
        cfg=read_default_config(); cfg['topology']={'v':'FLYBACK-QR (准谐振反激)','u':''}
        self.assertEqual(load_spec(cfg)['topology'],'QR-FLYBACK')

    def test_dcm_flyback_not_failed_by_ccm_sizing(self):
        import main
        p=dict(DEFAULT_PARAMS,P_out=.4); res=compute_design(p)
        self.assertEqual(res['op']['mode'],'DCM')
        catalog=check_catalog(p,res)
        self.assertEqual(next(c for c in catalog if c['id']=='L_min')['state'],'na')
        strip=main.PowerSupplyAnalyzer._power_checks(res['op'],res['wf'],res,p)
        self.assertIn('不适用',strip)
        markdown=main.build_markdown_report(p,res['op'],res['wf'],res)
        self.assertIn('励磁电感 Lm 初选参考',markdown)
        self.assertIn('不适用',markdown)


class GUIChecks(unittest.TestCase):
    def setUp(self):
        import main
        self.main=main; self.root=tk.Tk(); self.root.withdraw()
        self.app=main.PowerSupplyAnalyzer(self.root)
        self.app._control_ready=True; self.assertTrue(self.app.update_all())

    def tearDown(self):
        self.app.dispose()
        self.root.destroy()

    def wait(self):
        deadline=time.monotonic()+20
        while self.app._work_running and time.monotonic()<deadline:
            self.root.update(); time.sleep(.02)
        self.assertFalse(self.app._work_running,'worker did not complete')

    def test_search_and_fold(self):
        a=self.app
        self.assertTrue(a._param_widgets['eta_guess'][1].grid_info())
        self.assertEqual(a.get_params()['eta_guess'], .93)
        saved=a._config_dict()
        a.set_param('eta_guess', .85)
        self.assertTrue(a.update_all())
        self.assertEqual(a._last['op']['eta_guess'], .85)
        modified=a._config_dict()
        self.assertEqual(decode_config(modified)['eta_guess'], .85)
        a._apply_config(saved)
        self.assertTrue(a.update_all())
        self.assertEqual(a._last['op']['eta_guess'], .93)
        self.assertEqual(a._current_spec()['KP'],DEFAULT_PARAMS['KP'])
        a.param_search.set('ESL')
        self.assertTrue(a._param_widgets['ESL'][1].grid_info())
        self.assertFalse(a._param_widgets['V_in_min'][1].grid_info())
        a.param_search.set(''); frame=a._param_sections['spec']
        a._fold_section(frame); self.assertFalse(a._param_widgets['V_in_min'][1].grid_info())
        a._fold_section(frame); self.assertTrue(a._param_widgets['V_in_min'][1].grid_info())
        self.assertFalse(a._param_widgets['V_in'][1].grid_info())

    def test_acceptance_uses_current_endpoint_evidence(self):
        a = self.app
        a.restore_result_page('review')
        a._refresh_visible_tab()
        panel = a.acceptance_panel
        self.assertTrue(panel.trees['components'].get_children())
        self.assertEqual(panel.trees['performance'].get_children(), ('out1_ripple', 'phase_margin', 'eta'))
        eta = panel.rows['eta']
        self.assertEqual(eta['limit'], a._last['p']['target_eta'])
        self.assertEqual(eta['cases']['Vinmin']['calculation'], a._last['res']['eta'])
        self.assertEqual(eta['cases']['Vinmax']['pending_reason'], '缺结果')

        a.set_param('L', -1)
        self.assertFalse(a.update_all())
        panel.refresh()
        self.assertIsNone(panel.rows['eta']['cases']['Vinmin']['calculation'])

    def test_acceptance_uses_per_output_ripple_and_exact_phase_target(self):
        a = self.app
        path = Path(__file__).resolve().parents[1] / 'examples' / '40W_CCM_3OUT_FLYBACK.json'
        a._apply_config(json.loads(path.read_text(encoding='utf-8-sig')))
        a.restore_result_page('review')
        self.assertTrue(a.update_all())
        panel = a.acceptance_panel
        self.assertEqual(panel.trees['performance'].get_children(),
                         ('out1_ripple', 'out2_ripple', 'out3_ripple', 'phase_margin', 'eta'))
        last = a._last
        for index, rail in enumerate(last['res']['outputs'], 1):
            row = panel.rows[f'out{index}_ripple']['cases']['Vinmin']
            self.assertEqual(row['calculation'], rail['ripple_pp'])
            self.assertEqual(row['limit'], rail['spec']['ripple_target'] * rail['spec']['V_out'])

        target = last['p']['pm_target']
        near_target = target - 0.5
        diagnostics = [{'id': 'phase_margin', 'value': near_target, 'state': 'pass', 'limit': target - 1}]
        with patch.dict(last, res=dict(last['res'], loop=dict(min_pm=near_target)), checks=diagnostics):
            panel.refresh()
            row = panel.rows['phase_margin']['cases']['Vinmin']
            self.assertEqual(row['calculation'], near_target)
            self.assertEqual(row['limit'], target)
            self.assertEqual(row['status'], 'review')

        with patch.dict(last, res=dict(last['res'], loop=None)):
            panel.refresh()
            row = panel.rows['phase_margin']['cases']['Vinmin']
            self.assertIsNone(row['calculation'])
            self.assertEqual(row['pending_reason'], '缺结果')

    def run_tolerance(self, profile_path, *, samples=0):
        from tolerance_ui import PROFILE_SCHEMA

        a = self.app
        a.restore_result_page('tolerance')
        panel = a._tolerance_panel
        nominal = a.get_param('Rds_on')
        profile = dict(schema=PROFILE_SCHEMA, variables=[dict(path='Rds_on', low=.9 * nominal,
                       high=1.1 * nominal, distribution='uniform', source='回归样例')],
                       external_limits={'outputs': {'1': {'ripple_pp': 1e-6}}},
                       samples=samples, seed=4, load_fracs=[1.], max_evaluations=100)
        profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8')
        with patch.object(self.main.messagebox, 'showerror') as error:
            with patch.object(self.main.filedialog, 'askopenfilename', return_value=str(profile_path)):
                panel.import_profile()
            self.assertEqual(panel.param_tree.get_children(), ('Rds_on',))
            self.assertTrue(panel.mc_button.instate(('disabled',)))
            panel.run_button.invoke()
            self.assertTrue(panel.running, panel.status.get())
            self.wait()
            self.assertEqual(panel.result['samples'], 0)
            self.assertEqual(panel.result['monte_carlo']['status'], 'required_not_run')
            self.assertTrue(panel.mc_button.instate(('!disabled',)))
            if samples:
                boundary = panel.result['boundary']
                panel.mc_button.invoke()
                self.assertTrue(panel.running, panel.status.get())
                self.wait()
                self.assertEqual(panel.result['boundary'], boundary)
            error.assert_not_called()
        self.assertFalse(panel.running)
        self.assertIsNotNone(panel.result, panel.status.get())
        return panel.result

    def test_tolerance_units_switch_and_save_in_si(self):
        from tolerance_ui import normalize_profile

        a = self.app
        a.set_param('L', 40e-6)
        self.assertTrue(a.update_all())
        a.restore_result_page('tolerance')
        panel = a._tolerance_panel
        old_row = dict(path='L', low=36e-6, high=44e-6, distribution='normal', sigma=1.25e-6)
        panel.load_project_profile(normalize_profile({'variables': [old_row]}))
        panel._refresh_catalog()
        panel.param_tree.selection_set('L')
        self.root.attributes('-alpha', 0)
        self.root.deiconify()
        panel.edit_variable()
        self.root.update()
        dialog = next(child for child in panel.winfo_children() if isinstance(child, tk.Toplevel))

        def field(label):
            caption = next(w for w in dialog.grid_slaves(column=0)
                           if isinstance(w, self.main.ttk.Label) and w.cget('text') == label)
            return dialog.grid_slaves(row=caption.grid_info()['row'], column=1)[0]

        unit = field('输入单位')
        low, high, sigma = (field(label) for label in ('容差下限', '容差上限', '正态分布 σ'))
        nominal = dialog.grid_slaves(row=1)[0]
        self.assertEqual(unit.get(), 'µH')
        self.assertEqual((low.get(), high.get(), sigma.get()), ('36', '44', '1.25'))
        unit.set('mH')
        unit.event_generate('<<ComboboxSelected>>')
        self.assertEqual((low.get(), high.get(), sigma.get()), ('0.036', '0.044', '0.00125'))
        self.assertEqual(nominal.cget('text'), '标称值 0.04 mH')
        sigma_row = dialog.grid_slaves(row=sigma.grid_info()['row'])
        next(w for w in sigma_row if isinstance(w, self.main.ttk.Button)).invoke()
        self.assertAlmostEqual(float(sigma.get()), .008 / 6)
        sigma.delete(0, 'end')
        sigma.insert(0, '0.00125')

        low.delete(0, 'end')
        low.insert(0, '1e')
        with patch.object(self.main.messagebox, 'showerror') as error:
            unit.set('µH')
            unit.event_generate('<<ComboboxSelected>>')
            error.assert_called_once()
        self.assertEqual((unit.get(), low.get(), high.get()), ('mH', '1e', '0.044'))
        low.delete(0, 'end')
        low.insert(0, '0.036')

        buttons = [w for frame in dialog.grid_slaves() if isinstance(frame, self.main.ttk.Frame)
                   for w in frame.winfo_children()]
        next(w for w in buttons if w.cget('text') == '应用').invoke()
        self.assertEqual(panel.project_profile()['variables'], [old_row])

    def test_tolerance_background_runs_and_exports_from_its_page(self):
        a = self.app
        vin_min = a.get_param('V_in_min')
        a.set_param('V_in_max', vin_min + 2.)
        self.assertTrue(a.update_all())
        panel = a._tolerance_panel
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            result = self.run_tolerance(directory / 'profile.json', samples=4)
            self.assertEqual(result['failure_count'], 0, result['failures'])
            corners = len(result['conditions'])
            self.assertEqual(result['boundary']['search'], 'theory_guided')
            self.assertLess(result['deterministic_cases'], corners*3)
            self.assertEqual(result['evaluations'], result['deterministic_cases'] + corners*4)
            self.assertEqual(sorted({case['voltage'] for case in result['conditions']}),
                             [vin_min, vin_min + 1., vin_min + 2.])
            self.assertEqual(len(panel.result_tree.get_children()), len(result['rows']))
            ripple = next(row for row in result['rows'] if row['id'] == 'out1_ripple')
            self.assertEqual(ripple['evaluated_cases'], result['deterministic_cases'])
            self.assertEqual(ripple['statistics']['count'], 4)
            self.assertEqual(result['monte_carlo']['status'], 'completed')
            self.assertEqual(result['monte_carlo']['groups']['external']['exceedances'], 4)
            self.assertIsNone(next((row for row in result['rows'] if row['id'] == 'efficiency'), None))
            a.schedule_update()
            self.assertIs(panel.result, result)

            json_path, csv_path = directory / 'result.json', directory / 'result.csv'
            with patch.object(self.main.messagebox, 'showerror') as error, \
                    patch.object(self.main.filedialog, 'asksaveasfilename', side_effect=[str(json_path), str(csv_path)]):
                panel.json_button.invoke()
                panel.csv_button.invoke()
                error.assert_not_called()
            exported = json.loads(json_path.read_text(encoding='utf-8'))
            self.assertEqual(exported['input_fingerprint'], result['input_fingerprint'])
            self.assertEqual(exported['rows'], result['rows'])
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual([row['指标'] for row in csv_rows], [row['name'] for row in result['rows']])
            self.assertEqual({row['证据'] for row in csv_rows}, {'设计计算'})

            panel.seed.set('5')
            self.assertEqual(panel.result['samples'], 0)
            self.assertEqual(panel.result['boundary'], result['boundary'])
            self.assertTrue(panel.mc_button.instate(('!disabled',)))
            panel.load_percents.set('50, 100')
            self.assertIsNone(panel.result)
            self.assertFalse(panel.result_tree.get_children())
            self.assertTrue(all(button.instate(('disabled',)) for button in
                                (panel.mc_button, panel.csv_button, panel.json_button)))

    def test_design_report_uses_only_current_tolerance_result(self):
        a = self.app
        report_summary = dict(figure_count=0, check_count=0, sheet_count=1,
                              failed_cases=[], incomplete=False)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(self.main.messagebox, 'showerror') as error, \
                patch.object(self.main.messagebox, 'showinfo'), \
                patch('input_range_report.export_input_range_docx', return_value=report_summary) as word, \
                patch('report_xlsx.export_input_range_xlsx', return_value=report_summary) as excel:
            directory = Path(folder)
            expected = self.run_tolerance(directory / 'profile.json')
            for stale in (False, True):
                if stale:
                    a.set_param('P_out', a.get_param('P_out') * .95)
                    self.assertIsNone(a._tolerance_panel.result)
                for suffix, exporter in (('docx', word), ('xlsx', excel)):
                    with self.subTest(stale=stale, suffix=suffix), \
                            patch.object(self.main.filedialog, 'asksaveasfilename',
                                         return_value=str(directory / f'design.{suffix}')):
                        a.export_report()
                        error.assert_not_called()
                        if stale:
                            self.assertIsNone(exporter.call_args.kwargs.get('tolerance_result'))
                        else:
                            self.assertIs(exporter.call_args.kwargs['tolerance_result'], expected)

    def test_thermal_label_uses_shared_threshold(self):
        a=self.app; a.params['temp_rise_limit'].set(20)
        self.assertTrue(a.update_all())
        a._update_mag(a._last['op'],a._last['p'],a._last['res'],a._last['wf'])
        self.assertIn('20 K',a.mag_check.get())
        self.assertNotIn('40K',a.mag_check.get())
        a.params['temp_rise_limit'].set(100)
        self.assertTrue(a.update_all())
        a._update_mag(a._last['op'],a._last['p'],a._last['res'],a._last['wf'])
        self.assertIn('100 K',a.mag_check.get())
        self.assertEqual(next(c for c in a._last['checks'] if c['id']=='temp_rise')['state'],'pass')


if __name__=='__main__':unittest.main(verbosity=2)
