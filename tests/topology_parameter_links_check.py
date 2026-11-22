"""Desktop routing to exact existing rows under real Tk geometry."""
import json
from pathlib import Path
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from design_engine.specification import load_spec
from main import PowerSupplyAnalyzer


ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return load_spec(json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8')))


class TopologyParameterLinksCheck(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.geometry('1100x760')
        with patch.object(PowerSupplyAnalyzer, 'schedule_update'):
            self.app = PowerSupplyAnalyzer(self.root)
        self.addCleanup(self.root.destroy)
        self.addCleanup(self.app.dispose)
        self.reverse = []
        self.links = self.app._topology_links
        self.links.on_select = self.reverse.append

    def configure(self, parameters):
        with patch.object(self.app, 'schedule_update'):
            self.app._apply_config(parameters)
        self.assertTrue(self.app.update_all())
        self.settle()

    def settle(self):
        self.root.update()
        deadline = time.monotonic() + 5
        while self.app._param_layout_job is not None:
            if time.monotonic() >= deadline:
                self.fail('参数定位未完成排版确认')
            self.root.update()
            time.sleep(.005)

    def assert_centered(self, *widgets):
        canvas = self.app.left_canvas
        mapped = [widget for widget in widgets if widget.winfo_ismapped()]
        self.assertTrue(mapped)
        top = min(widget.winfo_rooty() for widget in mapped) - canvas.winfo_rooty()
        bottom = max(widget.winfo_rooty() + widget.winfo_height() for widget in mapped) - canvas.winfo_rooty()
        self.assertAlmostEqual((top + bottom)/2, canvas.winfo_height()/2, delta=3)

    def test_exact_capacitor_and_diode_link_with_folds_and_draft(self):
        parameters = example('40W_CCM_3OUT_FLYBACK.json')
        parameters['outputs'][1]['output_capacitors'] = [dict(C=100e-6, ESR=.03, ESL=2e-9) for _ in range(27)]
        self.configure(parameters)
        device = self.app._param_sections['device']
        caps = self.app._param_sections['capacitors']
        self.app._fold_section(device)
        self.app._fold_section(caps)
        self.app._set_parameter_pane_visible(False)
        self.assertTrue(self.app._select_topology_ref('C_O2_27'))
        self.settle()
        bank = self.app._inline_cap_editors[1]
        self.assertEqual(bank.index, 26)
        self.assertIn(device, self.app._folded_sections)
        self.assertNotIn(caps, self.app._folded_sections)
        self.assertTrue(bank.fields['C'][0].cget('style').startswith('TopologyLinked.'))
        capacitors = tuple(widget for field in bank.fields.values() for widget in field)
        self.assert_centered(*capacitors)
        self.assertEqual(self.reverse, [])
        at_center = self.app.left_canvas.canvasy(0)
        self.app._scroll_params('scroll', 2, 'units')
        after_scroll = self.app.left_canvas.canvasy(0)
        self.assertGreater(after_scroll, at_center)
        self.app._schedule_parameter_scrollregion()
        self.settle()
        self.assertEqual(self.app.left_canvas.canvasy(0), after_scroll)

        bank.variables['C'].set('-1')
        self.assertFalse(self.app._select_topology_ref('C_O2C'))
        self.assertEqual(bank.index, 26)
        self.assertEqual(bank.variables['C'].get(), '-1')
        bank.variables['C'].set('100')
        self.assertTrue(self.app._select_topology_ref('C_O2C'))
        bank.tree.selection_set('3')
        self.settle()
        self.assertEqual(self.reverse[-1], 'C_O2D')
        with patch.object(self.links, 'on_select', return_value=False):
            bank.tree.selection_set('4')
            self.settle()
        self.assertEqual(bank.index, 3)
        self.assertEqual(bank.tree.selection(), ('3',))

        self.app.param_search.set('暂时筛选其他输入')
        self.assertTrue(self.app._select_topology_ref('D_O2'))
        self.settle()
        target = self.app._inline_output_widgets[1, 'Vf_diode'][0]
        self.assertEqual(self.app.param_search.get(), '')
        diode_inputs = tuple(widget for key in ('Vf_diode', 'Qrr')
                             for widget in self.app._inline_output_widgets[1, key])
        self.assert_centered(*diode_inputs)
        target.event_generate('<ButtonRelease-1>', x=2, y=2)
        self.assertEqual(self.reverse[-1], 'D_O2')

    def test_shared_forward_diode_field_keeps_selected_device(self):
        self.configure(example('40W_ACF_FORWARD.json'))
        self.assertTrue(self.app._select_topology_ref('D2'))
        self.settle()
        self.app._param_widgets['Vf_diode'][0].event_generate('<ButtonRelease-1>', x=2, y=2)
        self.assertEqual(self.reverse[-1], 'D2')


if __name__ == '__main__':
    unittest.main()
