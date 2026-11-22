"""Desktop LLC modes and stable schematic/BOM designators."""

import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from matplotlib.figure import Figure

from component_management import component_registry
from llc_settings import CONTROL_MODES
from llc_ui import SimulationLogicPanel
from main import CTRL_LABEL, TOPO_LABEL, PowerSupplyAnalyzer
from parameter_panel import LLC_BRIDGE_LABELS
from power_stage import DEFAULT_PARAMS
from topology_diagram import draw_topology, topology_components


class LLCGeometryChecks(unittest.TestCase):
    def test_all_bridge_modes_match_physical_bom_and_hit_areas(self):
        for bridge, count in (('half', 2), ('full', 4)):
            for control in CONTROL_MODES:
                with self.subTest(bridge=bridge, control=control):
                    p = dict(DEFAULT_PARAMS, topology='LLC', llc_bridge=bridge, control_mode=control,
                             d_in_enable=True, d_out_enable=True,
                             output_capacitors=[dict(C=22e-6, ESR=.025, ESL=3e-9)] * 6)
                    ax = Figure().subplots()
                    hits = {}
                    refs = {row['ref'] for row in draw_topology(ax, p, interactive=True, hits=hits)}
                    components = component_registry(p)
                    self.assertEqual(refs, set(hits))
                    self.assertEqual({row['ref'] for row in components}, refs - {'R_LOAD'})
                    self.assertEqual(sum(row['kind'] == 'mos' for row in components), count)
                    self.assertTrue({'L_R', 'C_R', 'T1', 'D1', 'D2', 'D3', 'D4',
                                     'D_IN', 'D_OUT', 'U_CTRL', 'C_O6'} <= refs)
                    self.assertTrue(all(a.axes is ax for parts in hits.values() for a in parts))


class LLCInputChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.geometry('1320x900')
        self.addCleanup(self.root.destroy)
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        scheduled = patch.object(PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        scheduled.start()
        self.addCleanup(scheduled.stop)
        self.app = PowerSupplyAnalyzer(self.root)
        self.addCleanup(self.app.dispose)
        self.app.params['topology'].set(TOPO_LABEL['LLC'])
        self.root.update()

    def tearDown(self):
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_bridge_and_controller_values_survive_config_round_trip(self):
        app = self.app
        self.assertEqual(tuple(app.ctrl_combo['values']), tuple(CTRL_LABEL[x] for x in CONTROL_MODES))
        self.assertTrue(app.llc_bridge_combo.winfo_manager())
        self.assertFalse(app._param_widgets['llc_hhc_sense'][1].winfo_manager())
        app.llc_bridge_combo.set(LLC_BRIDGE_LABELS['full'])
        app.llc_bridge_combo.event_generate('<<ComboboxSelected>>')
        app.ctrl_combo.set(CTRL_LABEL['Hybrid Hysteretic'])
        app.ctrl_combo.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(app.params['llc_bridge'].get(), 'full')
        self.assertTrue(app._param_widgets['llc_hhc_sense'][1].winfo_manager())
        self.assertIn('V/V', app._param_widgets['llc_kp'][0].cget('text'))
        self.assertFalse(app._param_widgets['Vm'][1].winfo_manager())
        baseline = app._config_dict()
        app.params['llc_bridge'].set('half')
        app.params['topology'].set(TOPO_LABEL['BUCK'])
        app._apply_config(baseline)
        self.assertEqual(app._topo_key(), 'LLC')
        self.assertEqual(app._ctrl_key(), 'Hybrid Hysteretic')
        self.assertEqual(app.params['llc_bridge'].get(), 'full')
        self.assertEqual(app.llc_bridge_combo.get(), LLC_BRIDGE_LABELS['full'])

    def test_capacitor_and_full_bridge_switch_link_to_editors(self):
        app = self.app
        p = dict(DEFAULT_PARAMS, topology='LLC', llc_bridge='full', control_mode='Voltage Mode')
        app.params['llc_bridge'].set('full')
        links = app._topology_links
        links.set_rows(topology_components(p))
        for ref, key in (('C_R', 'llc_cr'), ('Q4', 'Rds_on'), ('D4', 'Vf_diode')):
            with self.subTest(ref=ref):
                self.assertTrue(links.locate(ref))
                links.select(ref)
                self.assertTrue(app._param_widgets[key][0].cget('style').startswith('TopologyLinked.'))

    def test_turns_define_readonly_ratio_in_llc(self):
        app = self.app
        app.params['N'].set(4)
        app.params['Np'].set(32)
        app.params['Ns'].set(8)
        self.assertEqual(str(app._param_widgets['N'][1].cget('state')), 'readonly')
        self.assertEqual(app._param_display_vars['N'].get(), '4')
        app.params['Ns'].set(4)
        self.assertEqual(app._param_display_vars['N'].get(), '8')
        self.assertFalse(app._scalar_parameter_active('N'))
        app.params['Np'].set(0)
        self.assertEqual(str(app._param_widgets['N'][1].cget('state')), 'normal')
        self.assertEqual(app._param_display_vars['N'].get(), '4')

    def test_simulation_panel_resizes_and_explains_selected_setting(self):
        popup = tk.Toplevel(self.root)
        popup.attributes('-alpha', 0)
        popup.geometry('640x470')
        p = dict(DEFAULT_PARAMS, topology='LLC', llc_bridge='half', control_mode='Hybrid Hysteretic')
        panel = SimulationLogicPanel(popup, p)
        panel.pack(fill='both', expand=True)
        self.root.update()
        done = tk.BooleanVar(value=False)
        popup.after(70, lambda: done.set(True))
        popup.wait_variable(done)
        self.assertIsNotNone(panel._photo)
        self.assertIn('半桥', panel.spec.cget('text'))
        panel.select('step_ms')
        self.assertIn('收敛', panel.description.cget('text'))
        fitted = panel._image_size
        panel._resize(1.2)
        done.set(False)
        popup.after(70, lambda: done.set(True))
        popup.wait_variable(done)
        self.assertGreater(panel._image_size[0], fitted[0])
        popup.destroy()

    def test_initial_design_form_uses_current_bridge_and_forwards_locked_tank(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / '300W_LLC_FULL_VCO.json'
        self.app._apply_config(json.loads(path.read_text(encoding='utf-8')))

        def children(parent):
            for child in parent.winfo_children():
                yield child
                yield from children(child)

        with (patch('initial_design_ui.generate', return_value={'topology': 'LLC'}) as generate,
              patch('initial_design_ui.describe', return_value='测试规格已送达')):
            window = self.app.open_initial_design()
            window.attributes('-alpha', 0)
            widgets = list(children(window))
            topology = next(w for w in widgets if isinstance(w, ttk.Combobox) and 'LLC' in w['values'])
            bridge = next(w for w in widgets if isinstance(w, ttk.Combobox) and '全桥' in w['values'])
            lock = next(w for w in widgets if isinstance(w, ttk.Checkbutton) and w.cget('text') == '锁定 Lr')
            start = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == '生成并校核')
            close = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == '关闭')
            self.assertEqual(topology.get(), 'LLC')
            self.assertEqual(bridge.get(), '全桥')
            self.assertEqual(str(bridge['state']), 'readonly')
            lock.invoke()
            start.invoke()
            deadline = time.monotonic() + 3
            while not generate.called and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.02)
            request = generate.call_args.args[0]
            self.assertEqual(request['topology'], 'LLC')
            self.assertEqual(request['control_mode'], 'Voltage Mode')
            self.assertEqual(request['bridge'], 2.)
            self.assertEqual(request['locked']['llc_lr'], self.app.get_param('llc_lr'))
            close.invoke()


if __name__ == '__main__':
    unittest.main()
