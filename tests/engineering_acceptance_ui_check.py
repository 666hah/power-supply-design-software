"""Owned Tk checks of acceptance groups, endpoint evidence, and project identity."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from engineering_acceptance_check import fixture
from engineering_acceptance_ui import AcceptancePanel
from engineering_acceptance import manual_measurement, normalize


class AcceptanceUIChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        # The headless Windows desktop advertises 512x384; permit a larger
        # review viewport, as the production app does.
        self.root.maxsize(3000, 2000)
        self.root.geometry('1000x740')
        self.p, self.bundle = fixture()
        self.saved, self.refreshes, self.errors = [], [], []
        self.root.report_callback_exception = lambda *exc: self.errors.append(str(exc))
        self.font = tkfont.nametofont('TkDefaultFont')
        self.original_font = self.font.actual()
        self.font.configure(size=13)
        self.panel = AcceptancePanel(self.root, get_spec=lambda: copy.deepcopy(self.p),
            get_range_result=lambda: self.bundle, on_apply=self.apply,
            on_refresh=lambda: self.refreshes.append(True))
        self.panel.pack(fill='both', expand=True)
        self.panel.refresh()
        self.root.update()

    def apply(self, value):
        self.saved.append(copy.deepcopy(value))
        self.p['engineering_acceptance'] = copy.deepcopy(value)

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.font.configure(**self.original_font)
        self.root.destroy()

    def select(self, cid):
        row = self.panel.rows[cid]
        tree = self.panel.trees[row['group']]
        tree.selection_set(cid)
        self.root.update()
        self.assertEqual(self.panel.selected, cid)
        return tree

    def test_fixed_groups_show_both_endpoints_and_scroll_at_large_font(self):
        panel = self.panel
        self.assertEqual({key: label.master.cget('text') for key, label in panel.group_labels.items()},
                         {'components': '器件规格', 'performance': '电源外特性'})
        for key, tree in panel.trees.items():
            expected = tuple(row['id'] for row in panel.snapshot['rows'] if row['group'] == key)
            self.assertEqual(tree.get_children(), expected)
            self.assertEqual(len(tree['columns']), 6)
            self.assertIn('待补 ', panel.group_labels[key].cget('text'))
            bounds = tree.bbox(expected[0], 'Vinmax_state')
            self.assertTrue(bounds)
            self.assertGreater(bounds[0], 0)
            self.assertLessEqual(bounds[0] + bounds[2], tree.winfo_width() + 3)
        self.assertIsNone(panel.evidence_window)
        self.font.configure(size=26)
        self.root.geometry('540x350')
        panel._reflow()
        self.root.update()
        tree = panel.trees['performance']
        first = tree.get_children()[0]
        line_count = max(text.count('\n') + 1 for text in tree.item(first, 'values'))
        self.assertGreater(tree.bbox(first)[3], self.font.metrics('linespace') * line_count)
        self.assertLess(panel.scroll.canvas.yview()[1], 1.)
        panel.scroll.canvas.yview_moveto(1)
        tree.xview_moveto(1)
        self.root.update()
        self.assertGreater(panel.scroll.canvas.yview()[0], 0.)
        bounds = tree.bbox(tree.get_children()[0], 'Vinmax_state')
        self.assertLessEqual(bounds[0] + bounds[2], tree.winfo_width() + 3)

    def test_taller_component_list_and_all_six_outputs_in_performance_list(self):
        self.p['outputs'] = [dict(Ns=7) for _ in range(6)]
        self.bundle['base_spec'] = copy.deepcopy(self.p)
        panel = self.panel
        panel.refresh()
        self.root.update()
        components = panel.trees['components']
        performance = panel.trees['performance']
        component_rows = components.get_children()
        self.assertGreater(len(component_rows), 9)
        self.assertEqual(components.yview(), (0., 9 / len(component_rows)))
        _, top, _, height = components.bbox(component_rows[8])
        self.assertLessEqual(top + height, components.winfo_height())
        self.assertEqual(performance.get_children(),
                         tuple(f'out{index}_ripple' for index in range(1, 7)) + ('phase_margin', 'eta'))
        self.assertEqual(performance.yview(), (0., 1.))

        canvas = panel.scroll.canvas
        components.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(components.yview()[0], 0.)
        self.assertEqual(canvas.yview()[0], 0.)
        components.yview_moveto(1.)
        components.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(canvas.yview()[0], 0.)
        canvas.yview_moveto(1.)
        self.root.update()
        self.assertTrue(performance.bbox('eta'))
        self.assertLessEqual(performance.winfo_rooty() + performance.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())

    def test_pending_reasons_are_visible_at_each_endpoint_with_large_font(self):
        for check in self.bundle['cases'][0]['checks']:
            if check['id'] == 'bom_C_O1_ripple':
                check['limit'] = None
            elif check['id'] == 'bom_D1_voltage':
                check['limit'] = check['value'] = None
        self.bundle['cases'][0]['result']['loop'] = None
        self.bundle['cases'][1]['result']['wf']['ripple_pp'] = 2.3748e-05
        self.font.configure(size=-26)
        self.root.geometry('540x350')
        self.panel.refresh()
        self.root.update()
        for row, expected in (('bom_C_O1_ripple', '缺限值'), ('phase_margin', '缺结果'),
                              ('bom_D1_voltage', '缺限值和结果')):
            with self.subTest(row=row):
                tree = self.select(row)
                lines = tree.set(row, 'Vinmin_state').splitlines()
                self.assertEqual(''.join(lines), expected)
                self.assertTrue(all(self.font.measure(line) <= tree.column('Vinmin_state', 'width') - 12
                                    for line in lines))
                self.assertEqual(tree.set(row, 'Vinmax_state'), '满足')
        self.panel.open_evidence()
        self.assertIn('缺限值和结果', self.panel.case_detail['Vinmin'].cget('text'))
        self.assertIn('满足', self.panel.case_detail['Vinmax'].cget('text'))
        performance = self.panel.trees['performance']
        evidence = performance.set('out1_ripple', 'Vinmax_values')
        self.assertEqual(evidence, '计算 2.3748e-05')
        self.assertLessEqual(self.font.measure(evidence), performance.column('Vinmax_values', 'width') - 12)

    def test_measurement_saves_one_endpoint_and_preserves_legacy_metadata(self):
        panel = self.panel
        old = manual_measurement(dict(self.p, L=31.e-6), 'eta', 'Vinmax', .87,
                                 source='旧功率计', conditions='30V/24W')
        self.p['engineering_acceptance'] = normalize(dict(
            criteria=[dict(id='eta', enabled=False, limit=.99)],
            issues=[dict(id='I1', title='启动尖峰待改进')],
            measurements=[old]))
        panel.refresh()
        tree = self.select('eta')
        self.assertEqual(tree.set('eta', 'Vinmin_state'), '满足')
        self.assertRegex(tree.set('eta', 'target'), r'≥ 0\.9\b')
        panel.detail_button.invoke()
        self.root.update()
        self.assertIn('效率', panel.evidence_title.cget('text'))
        fields = panel.measurement['Vinmin']
        for key, value in dict(value='.88', source='功率计', conditions='20V/24W/25°C',
                               evidence_ref='bench.csv').items():
            fields[key].set(value)
        with patch('loss_model.compute_design', side_effect=AssertionError('editor must not calculate')):
            with patch('engineering_acceptance_ui.messagebox.showerror') as error:
                self.assertFalse(panel.apply_measurement('Vinmin'))
                error.assert_called_once()
            panel.confirm_measurement['Vinmin'].set(True)
            self.assertTrue(panel.apply_measurement('Vinmin'))
        encoded = json.loads(json.dumps(self.p, ensure_ascii=False, allow_nan=False))
        config = encoded['engineering_acceptance']
        self.assertEqual(config, self.saved[-1])
        self.assertEqual(config['measurements'][0], old)
        self.assertEqual(config['criteria'][0]['limit'], .99)
        self.assertEqual(config['issues'][0]['title'], '启动尖峰待改进')
        self.assertIn('保存', panel.message.get())
        self.assertIn('超限', panel.case_detail['Vinmin'].cget('text'))
        self.assertIn('失效', panel.case_detail['Vinmax'].cget('text'))
        self.p = encoded
        panel.refresh()
        self.assertEqual(tree.set('eta', 'Vinmin_state'), '超限')
        self.assertEqual(panel.rows['eta']['cases']['Vinmin']['measurement'], .88)
        panel.request_refresh()
        self.assertEqual(len(self.refreshes), 1)
        imports = []
        panel.on_import_evidence = lambda: imports.append(True)
        panel.import_evidence()
        self.assertEqual(imports, [True])

    def test_case_limit_detail_uses_each_endpoint(self):
        self.bundle['cases'][0]['checks'].append(dict(id='ripple', limit=.09))
        self.bundle['cases'][1]['checks'].append(dict(id='ripple', limit=.07))
        self.panel.refresh()
        tree = self.select('out1_ripple')
        self.assertEqual(tree.set('out1_ripple', 'target'), '按工况')
        self.assertEqual(tree.set('out1_ripple', 'Vinmin_state'), '满足')
        self.assertEqual(tree.set('out1_ripple', 'Vinmax_state'), '超限')
        self.panel.open_evidence()
        self.assertIn('≤ 0.09', self.panel.case_detail['Vinmin'].cget('text'))
        self.assertIn('≤ 0.07', self.panel.case_detail['Vinmax'].cget('text'))

    def test_evidence_draft_survives_data_refresh_but_input_changes_require_reentry(self):
        self.select('phase_margin')
        panel = self.panel
        panel.open_evidence()
        panel.measurement['Vinmin']['value'].set('62.5')
        panel.confirm_measurement['Vinmin'].set(True)
        panel.refresh()
        self.root.update()
        self.assertEqual(panel.measurement['Vinmin']['value'].get(), '62.5')
        self.p['L'] *= 1.1
        with patch('engineering_acceptance_ui.messagebox.showerror') as error:
            self.assertFalse(panel.apply_measurement('Vinmin'))
            error.assert_called_once()
        self.root.update()
        self.assertEqual(panel.measurement['Vinmin']['value'].get(), '')
        self.assertFalse(panel.confirm_measurement['Vinmin'].get())
        self.assertEqual(self.saved, [])

    def test_invalid_current_input_clears_both_matrices_and_detail(self):
        self.panel.open_evidence()
        self.assertTrue(all(tree.get_children() for tree in self.panel.trees.values()))
        self.p['L'] = float('nan')
        self.panel.refresh()
        self.assertTrue(all(not tree.get_children() for tree in self.panel.trees.values()))
        self.assertIsNone(self.panel.snapshot)
        self.assertIsNone(self.panel.evidence_window)
        self.assertIn('未就绪', self.panel.summary.get())
        self.assertTrue(self.panel.detail_button.instate(('disabled',)))


class RealApplicationFingerprintChecks(unittest.TestCase):
    def test_loaded_ui_and_normalized_spec_match_without_solving(self):
        import main
        from design_engine.specification import load_spec
        from engineering_acceptance import input_fingerprint
        root = tk.Tk()
        root.attributes('-alpha', 0)
        root.maxsize(3000, 2000)
        app = None
        try:
            with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None), patch(
                    'loss_model.compute_design', side_effect=AssertionError('identity loading must not solve')):
                app = main.PowerSupplyAnalyzer(root)
                for name in ('40W_CCM_3OUT_FLYBACK.json', '33W_3OUT_ACF_MP6005_COMPACT.json', '90W_QR_L6565_300V.json'):
                    with self.subTest(example=name):
                        raw = json.loads((ROOT/'examples'/name).read_text('utf-8-sig'))
                        normalized = load_spec(copy.deepcopy(raw))
                        app._apply_config(copy.deepcopy(raw))
                        self.assertEqual(input_fingerprint(normalized), input_fingerprint(app._current_spec()))
        finally:
            if app is not None:
                app._closing = True
                app._work_cancel.set()
            for job in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(job)
            root.destroy()


if __name__ == '__main__':
    unittest.main()
