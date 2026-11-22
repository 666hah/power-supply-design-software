"""One curated example catalog, valid shipped configurations and menu commands."""
import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from compensation_report import network_key
from example_catalog import EXAMPLES, PERSONAL_QR, PUBLIC_QR, available_examples, example_feedback_defaults
from web_app.metadata import read_example,bootstrap
from design_engine.service import calculate_parameters
from design_engine.specification import load_spec


SSR_NETWORKS = {
    '33W_3OUT_ACF_MP6005_COMPACT.json': 'tl431f',
    '40W_CCM_3OUT_FLYBACK.json': 'tl431f',
    PUBLIC_QR: 'tl431nf',
    PERSONAL_QR: 'tl431nf',
    '300W_LLC_HALF_HHC.json': 'tl431nf',
    '300W_LLC_FULL_VCO.json': 'tl431nf',
}


class CatalogChecks(unittest.TestCase):
    def test_curated_isolated_and_nonisolated_examples(self):
        self.assertEqual(bootstrap()['examples'],available_examples())
        self.assertEqual([load_spec(read_example(n))['topology'] for n in EXAMPLES],
                         ['ACF-FORWARD','FLYBACK','QR-FLYBACK','BUCK','BUCK','BUCK','LLC','LLC','BOOST','BUCK'])
        with self.assertRaises(ValueError):read_example('../main.py')

    def test_personal_qr_replaces_only_the_menu_entry_when_installed(self):
        with TemporaryDirectory() as temporary, patch('example_catalog.ROOT',Path(temporary)):
            self.assertEqual(available_examples(),EXAMPLES)
            with self.assertRaises(ValueError):
                read_example(PERSONAL_QR)
            local = Path(temporary)/'examples'/PERSONAL_QR
            local.parent.mkdir()
            local.write_text(json.dumps(dict(Np=42, outputs=[dict(Ns=21),dict(Ns=5)])),encoding='utf-8')
            selected = available_examples()
            self.assertEqual(list(selected),[PERSONAL_QR if key==PUBLIC_QR else key for key in EXAMPLES])
            example=read_example(PERSONAL_QR)
            self.assertEqual([example['Np'],*(r['Ns'] for r in example['outputs'])],[42,21,5])
            public=read_example(PUBLIC_QR)
            self.assertEqual([public['Np'],*(r['Ns'] for r in public['outputs'])],[56,28,8])

    def test_flyback_preserves_user_requirements_and_winding_structure(self):
        data=(ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes()
        p=load_spec(json.loads(data))
        # Device scalars/ratings intentionally change as real components are
        # selected; electrical requirements and user winding arrangement do
        # not. A whole-file SHA would forbid precisely the requested update.
        self.assertEqual([r['Ns'] for r in p['outputs']],[12,5,2])
        self.assertEqual((p['V_in_min'],p['V_in_max']),(20,30))
        self.assertEqual((p['V_out'],p['P_out'],p['f_sw']),(30.,40.,250e3))
        self.assertEqual((p['feedback_mode'],p['feedback_output']),('SSR',1))
        self.assertEqual((p['control_mode'],p['Np'],p['N']),('Peak Current Mode',6,.5))
        self.assertEqual([r['P_out'] for r in p['outputs']],[30.,1.,2.])
        self.assertEqual([r['P_out_min'] for r in p['outputs']],[2.,.3,.5])
        self.assertEqual([r['n_strand_s'] for r in p['outputs']],[30,10,20])
        self.assertEqual([r['parallel_wires_s'] for r in p['outputs']],[1,1,1])
        self.assertEqual((p['d_wire_p'],p['n_strand_p'],p['parallel_wires_p']),(100e-6,40,1))
        self.assertEqual([r['d_wire_s'] for r in p['outputs']],[100e-6]*3)
        winding=p['winding_config']
        self.assertEqual((winding['window_width'],winding['window_height']),(.012,.0033))
        self.assertEqual([(s['winding_id'],s['turns'],s['section_id']) for s in winding['layer_plan']],
                         [('OUT1',6,'OUT1_A'),('P',6,'P_A'),('OUT2',5,'OUT2_A'),('OUT3',2,'OUT3_A'),('OUT1',6,'OUT1_B')])
        self.assertTrue(all(s['winding_style']=='sparse' for s in winding['layer_plan']))
        self.assertEqual(winding['turn_positions'],{})

    def test_compact_chokes_and_both_endpoints(self):
        p=load_spec(read_example('33W_3OUT_ACF_MP6005_COMPACT.json'))
        self.assertEqual([r['L'] for r in p['outputs']],[100e-6,330e-6,47e-6])
        self.assertEqual(p['L'],p['outputs'][0]['L'])
        before=copy.deepcopy(p)
        cases=calculate_parameters(p,analysis='endpoints',include_loop=True,
                                   include_cross_regulation=False).runtime_bundle()['cases']
        self.assertEqual(p,before)
        for case in cases:
            self.assertFalse(case.get('error'));self.assertFalse(case.get('loop_error'))
            op=case['result']['op']
            self.assertTrue(op['acf_model']['current_mesh_verified'])
            self.assertTrue(all(c['mode']=='CCM' and c['I_L_pk']<2 for c in op['output_ops']))

    def test_public_qr_example_calculates_with_interleaved_reference_transformer(self):
        from winding_layout import assess_winding_window, transformer_windings

        name='90W_QR_L6565_252_442V_REFERENCE.json'
        self.assertIn(name,EXAMPLES)
        p=load_spec(read_example(name))
        self.assertEqual((p['V_in'],p['V_in_min'],p['V_in_max']),(252.,252.,442.))
        self.assertEqual((p['Np'],p['Ns'],p['A_sense']),(56,28,1))
        self.assertEqual([(r['Ns'],r['P_out']) for r in p['outputs']],[(28,92.),(8,.75)])
        self.assertAlmostEqual(p['L'],800e-6)
        winding=p['winding_config']
        self.assertEqual((winding['window_width'],winding['window_height']),(.0176,.0048))
        self.assertEqual([(s['winding_id'],s['turns']) for s in winding['layer_plan']],
                         [('P',28),('OUT1',14),('OUT2',8),('OUT1',14),('P',28)])
        self.assertTrue(winding['model_3d'])

        cases=calculate_parameters(p,analysis='endpoints',include_loop=True,
                                   include_cross_regulation=False).runtime_bundle()['cases']
        self.assertEqual([case['p']['V_in'] for case in cases],[252.,442.])
        for case in cases:
            self.assertFalse(case.get('error'))
            self.assertFalse(case.get('loop_error'))
            layout=assess_winding_window(transformer_windings(case['result']),winding)
            self.assertTrue(layout['fits'])

    def test_ssr_network_uses_selected_rail_and_includes_31_volts_in_fast_lane(self):
        data = dict(topology={'v': 'QR-FLYBACK'}, feedback_mode={'v': 'SSR'},
                    V_out=60., outputs=[dict(V_out=60.), dict(V_out={'v': .031, 'u': 'k'})],
                    feedback_output={'v': 2}, __comp=dict(topo='opamp3'))
        before = copy.deepcopy(data)
        self.assertEqual(network_key(example_feedback_defaults(data)['__comp']['topo']), 'tl431f')
        self.assertEqual(data, before)
        data['outputs'][1]['V_out'] = 31.001
        self.assertEqual(network_key(example_feedback_defaults(data)['__comp']['topo']), 'tl431nf')
        self.assertIs(example_feedback_defaults(dict(data, feedback_mode='PSR-MP6005'))['__comp'],
                      data['__comp'])
        self.assertIs(example_feedback_defaults(dict(data, topology='BUCK'))['__comp'], data['__comp'])

    def test_desktop_menu_callbacks_load_their_own_example(self):
        import tkinter as tk
        import main
        root=tk.Tk();root.withdraw()
        try:
            with patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None), \
                    patch.object(main.PowerSupplyAnalyzer,'request_update',return_value=None):
                app=main.PowerSupplyAnalyzer(root)
                self.assertEqual(app._comp_key(), 'tl431f')
                bar=root.nametowidget(root.cget('menu'))
                example_index=next(i for i in range(bar.index('end')+1)
                                   if bar.type(i)=='cascade' and bar.entrycget(i,'label')=='示例')
                menu=root.nametowidget(bar.entrycget(example_index,'menu'))
                entries=[i for i in range(menu.index('end')+1)
                         if menu.type(i)=='command']
                catalog=available_examples()
                self.assertEqual(len(entries),len(catalog))
                self.assertEqual([menu.entrycget(i,'label') for i in entries],list(catalog.values()))
                with patch.object(app,'load_isolated_example') as loader:
                    for index,name in zip(entries,catalog):
                        menu.invoke(index)
                        loader.assert_called_with(name)
                for name in catalog:
                    example=load_spec(read_example(name))
                    topology=example['topology']
                    app.load_isolated_example(name)
                    p=app.get_params()
                    self.assertEqual(p['topology'],topology)
                    self.assertEqual(app._comp_key(), SSR_NETWORKS.get(name, 'opamp3'))
                    if name==PERSONAL_QR:
                        self.assertEqual(p['Np'],example['Np'])
                        self.assertEqual([r['Ns'] for r in p['outputs']],[r['Ns'] for r in example['outputs']])
                    if topology in ('ACF-FORWARD','FLYBACK'):
                        self.assertEqual(len(p['outputs']),3)
                    if topology=='ACF-FORWARD':
                        self.assertEqual([r['L'] for r in p['outputs']],[100e-6,330e-6,47e-6])
                    if name=='96W_BUCK_COT_4PH.json':
                        self.assertEqual((p['buck_phases'], p['control_mode']), (4, 'Constant On-Time'))
                        self.assertTrue(app.ctrl_combo.instate(['disabled']))
                    if topology=='BOOST':
                        self.assertEqual((p['buck_phases'], p['control_mode']), (1, 'Peak Current Mode'))
                    if name=='24W_BUCK_CAP_IMPEDANCE.json':
                        self.assertEqual(len(p['output_capacitors']),3)
                        self.assertTrue(all(cap['impedance_curve']['points'] for cap in p['output_capacitors']))
        finally:
            for job in root.tk.splitlist(root.tk.call('after','info')):
                try:root.after_cancel(job)
                except tk.TclError:pass
            root.destroy()


if __name__=='__main__':unittest.main()
