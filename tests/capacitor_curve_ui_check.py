"""Test the instrument importer and the desktop import-to-result path."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()

from capacitor_curve_io import parse_curve


CSV = '频率 / Hz,阻抗幅值 / Ω,相位 / °\n1000,0.8,-85\n100000,0.04,-25\n10000000,0.12,70\n'


class CapacitorCurveChecks(unittest.TestCase):
    def test_instrument_columns_and_validation(self):
        text = ('Instrument export;Room A\n"Φ [rad]";"Frequency (kHz)";"|Z| [mΩ]";Marker\n'
                '0.5;100;82;peak\n-0.5;5;135;\n')
        curve = parse_curve(text.encode('utf-16'), name=r'C:\data\capture.csv')
        self.assertEqual(curve['source'], 'capture.csv')
        self.assertEqual([row[:2] for row in curve['points']], [[5000., .135], [100000., .082]])
        self.assertAlmostEqual(curve['points'][1][2], 28.6478897565)
        self.assertEqual(parse_curve('100\t.2\t-30\n200\t.1\t20'),
                         {'points': [[100., .2, -30.], [200., .1, 20.]]})
        self.assertEqual(parse_curve('[[10,1,-90],[20,2,90]]')['points'][1], [20., 2., 90.])
        for bad in ('100,0.1,0\n100,0.2,1', '100,0.1,92\n200,0.2,0',
                    '100,0.1,0\n200,0.2,0,51', '{"source":false,"points":[[10,1,0],[20,1,0]]}',
                    'f_Hz,Z_ohm,phase_grad\n100,0.1,0\n200,0.1,0'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_curve(bad, name='invalid.csv')

    def test_desktop_import_edit_save_result_and_remove(self):
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        import tkinter as tk
        import main

        context = ROOT / 'artifacts'
        context.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=context) as temporary:
            path = Path(temporary) / 'example.csv'
            path.write_text(CSV, encoding='utf-8-sig')
            root = tk.Tk()
            root.geometry('1150x800')
            root.attributes('-alpha', 0)
            callback_errors = []
            root.report_callback_exception = lambda *args: callback_errors.append(args[1])
            try:
                example = json.loads((ROOT / 'examples/40W_CCM_3OUT_FLYBACK.json').read_text('utf-8'))
                with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
                    app = main.PowerSupplyAnalyzer(root)
                    app._apply_config(example)
                    editor = app._inline_cap_editors[1]
                    picker = app._cap_model_picker
                    self.assertIs(picker.master, app._param_sections['curves'])
                    self.assertEqual(editor.tree.cget('columns'), ('C', 'ESR', 'ESL'))
                    self.assertEqual(picker.port.cget('values'), ('输入', 'OUT1', 'OUT2', 'OUT3'))
                    picker.port.set('OUT2')
                    picker.refresh()
                    self.assertEqual(picker.device.get(), 'C_O2A')
                    initial = editor.get()
                    self.assertEqual(picker.model.cget('values'), ('固定参数 RLC',))
                    dialog = editor.open_curve_data()
                    self.assertIs(editor.data_button.master, editor)
                    self.assertTrue(dialog.clear_button.instate(['disabled']))
                    dialog.destroy()
                    self.assertEqual(editor.get(), initial)

                    dialog = editor.open_curve_data()
                    with patch('capacitor_ui.filedialog.askopenfilename', return_value=str(path)):
                        self.assertTrue(dialog.import_curve())
                    root.update()
                    self.assertEqual(len(dialog.axes[0].lines), 1)
                    self.assertEqual(len(dialog.axes[1].lines), 2)
                    self.assertIn('3 点', dialog.status.get())
                    self.assertTrue(dialog.winfo_ismapped())
                    plot_widget = dialog.plot.get_tk_widget()
                    self.assertEqual(dialog.plot.get_width_height(physical=True),
                                     (plot_widget.winfo_width(), plot_widget.winfo_height()))
                    dialog.thermal.set('nan')
                    self.assertFalse(dialog.apply())
                    self.assertIn('热阻', dialog.error.get())
                    self.assertEqual(editor.get(), initial)
                    dialog.thermal.set('30')
                    self.assertTrue(dialog.apply())
                    editor.variables['ESR'].set('32')
                    saved = json.loads(json.dumps(app._config_dict(), ensure_ascii=False))
                    branch = saved['outputs'][1]['output_capacitors']
                    self.assertEqual(branch[0]['impedance_curve']['source'], 'example.csv')
                    self.assertEqual(branch[0]['impedance_mode'], 'fixed')
                    self.assertEqual(branch[0]['thermal_resistance_K_per_W'], 30.)
                    self.assertAlmostEqual(branch[0]['ESR'], .032)
                    self.assertEqual(branch[1:], initial[1:])
                    self.assertEqual(saved['outputs'][0]['output_capacitors'], example['outputs'][0]['output_capacitors'])

                    path.unlink()
                    app._apply_config(saved)
                    self.assertEqual(editor.get(), branch)
                    self.assertEqual(picker.model.get(), '固定参数 RLC')
                    fixed = json.loads(json.dumps(app._config_dict(), ensure_ascii=False))
                    app._apply_config(fixed)
                    self.assertEqual(editor.get()[0]['impedance_curve'], branch[0]['impedance_curve'])
                    self.assertEqual(editor.get()[0]['impedance_mode'], 'fixed')
                    app.nb.select(app.tab_cap)
                    self.assertTrue(app.update_all())
                    root.update()
                    tree = app.cap_results_table.tree
                    values = [tree.item(i, 'values') for i in tree.get_children()]
                    self.assertEqual(next(row for row in values if row[0] == 'C_O2A')[2], '固定 RLC')

                    self.assertIn('阻抗曲线', picker.model.cget('values'))
                    picker.model.current(1)
                    picker.choose_mode()
                    app._curve_global.set('fixed')
                    app._choose_global_curve_mode()
                    self.assertEqual(editor.get()[0], dict(branch[0], impedance_mode='curve'))
                    app.nb.select(app.tab_cap)
                    self.assertTrue(app.update_all())
                    root.update()
                    tree = app.cap_results_table.tree
                    values = [tree.item(i, 'values') for i in tree.get_children()]
                    row = next(row for row in values if row[0] == 'C_O2A')
                    self.assertEqual(row[2], '阻抗曲线')
                    self.assertGreater(float(row[5]), 0.)
                    self.assertAlmostEqual(float(row[6]), float(row[5]) * .03, places=3)
                    self.assertTrue(row[7].endswith('%'))
                    self.assertEqual(sum(row[0].startswith('C_IN') for row in values), len(app._cap_editors['input'].get()))

                    dialog = editor.open_curve_data()
                    self.assertTrue(dialog.clear_button.instate(['disabled']))
                    dialog.clear_curve()
                    self.assertIsNotNone(dialog.curve)
                    dialog.destroy()
                    picker.model.current(0)
                    picker.choose_mode()
                    dialog = editor.open_curve_data()
                    dialog.clear_curve()
                    dialog.thermal.set('')
                    self.assertTrue(dialog.apply())
                    row = editor.get()[0]
                    self.assertEqual(row['impedance_mode'], 'fixed')
                    self.assertNotIn('impedance_curve', row)
                    self.assertNotIn('thermal_resistance_K_per_W', row)
                    self.assertAlmostEqual(row['ESR'], .032)
                    buck = json.loads((ROOT / 'examples/24W_BUCK_CAP_IMPEDANCE.json').read_text('utf-8'))
                    app._apply_config(buck)
                    self.assertEqual(picker.port.cget('values'), ('输入', '输出'))
                    picker.port.set('输出')
                    picker.refresh()
                    self.assertEqual(picker.device.cget('values'), ('C_O1', 'C_O2', 'C_O3'))
                    self.assertEqual(picker.model.get(), '阻抗曲线')
                    self.assertFalse(callback_errors, callback_errors)
            finally:
                if 'app' in locals():
                    app._calculation_worker.close()
                for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.after_cancel(timer)
                root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
