"""Actual Tk interactions across the desktop diagram, BOM and input rows."""
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import tkinter as tk
from tkinter import font, ttk

ROOT = Path(__file__).resolve().parents[1]


def buttons_below(widget):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            yield child
        yield from buttons_below(child)


class TopologyCanvasChecks(TestCase):
    def setUp(self):
        from main import PowerSupplyAnalyzer

        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.attributes('-alpha', 0)
        self.root.maxsize(1920, 1080)
        self.root.geometry('1440x900')
        scheduled = patch.object(PowerSupplyAnalyzer, 'schedule_update')
        self.schedule = scheduled.start()
        self.addCleanup(scheduled.stop)
        self.app = PowerSupplyAnalyzer(self.root)
        self.addCleanup(self.app.dispose)

        spec = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        spec['coupling_config'] = dict(enabled=False)
        caps = [dict(C=(100+i)*1e-6, ESR=.032, ESL=3e-9) for i in range(8)]
        spec['input_capacitors'] = caps[:5]
        spec['outputs'][1]['output_capacitors'] = caps
        self.app._apply_config(spec)
        self.assertTrue(self.app.update_all(), self.app.status_var.get())
        self.root.update()
        self.schedule.reset_mock()

    def click_ref(self, ref):
        view = self.app.topology_view
        canvas = view.canvas
        view.reveal(ref)
        self.root.update()
        label = next(item for item, _, _ in view._refs[ref] if canvas.type(item) == 'text')
        x, y = canvas.coords(label)
        pixel = dict(x=round(x-canvas.canvasx(0)), y=round(y-canvas.canvasy(0)))
        canvas.event_generate('<ButtonPress-1>', **pixel)
        canvas.event_generate('<ButtonRelease-1>', **pixel)
        self.root.update()

    def test_full_banks_and_three_way_selection_without_recalculation(self):
        app = self.app
        view = app.topology_view
        refs = set(view._refs)
        self.assertTrue({f'C_IN{i}' for i in range(1, 6)} <= refs)
        self.assertTrue({f'C_O2{letter}' for letter in 'ABCDEFGH'} <= refs)

        self.click_ref('C_O2D')
        self.assertEqual(app._topology_ref, 'C_O2D')
        self.assertEqual(app._inline_cap_editors[1].index, 3)
        self.assertIsNone(app._bom_editor)
        self.assertIn('C_O2D', app.topology_selection.get())

        app.restore_result_page('bom')
        self.root.update()
        editor = app._bom_editor
        self.assertTrue(editor.winfo_ismapped())
        self.assertIs(editor.winfo_toplevel(), self.root)
        self.assertEqual(editor.tree.selection(), ('C_O2D',))
        editor.tree.selection_set('C_O2G')
        self.root.update()
        self.assertEqual(app.selected_result_page(), 'bom')
        self.assertEqual(app._topology_ref, 'C_O2G')
        self.assertEqual(app._inline_cap_editors[1].index, 6)

        app._focus_inline_section('device')
        self.root.update()
        field = app._inline_output_widgets[1, 'Vf_diode'][0]
        field.event_generate('<ButtonRelease-1>')
        self.root.update()
        self.assertEqual(app.selected_result_page(), 'bom')
        self.assertEqual(app._topology_ref, 'D_O2')
        self.assertEqual(editor.current, 'D_O2')

        jump = next(button for button in buttons_below(app.tab_bom)
                    if button.cget('text') == '在拓扑中查看')
        jump.invoke()
        self.root.update()
        self.assertEqual(app.selected_result_page(), 'topology')
        self.assertEqual(view.selection, 'D_O2')

        app.restore_result_page('bom')
        self.root.update()
        self.assertIs(app._bom_editor, editor)
        self.assertEqual(editor.tree.selection(), ('D_O2',))
        self.schedule.assert_not_called()

    def test_pan_zoom_and_fit_keep_vector_items(self):
        view = self.app.topology_view
        canvas = view.canvas
        scene = canvas.find_withtag('scene')
        view.fit('power')
        self.root.update()
        scale = view.scale
        view.zoom(1.45, 140, 120)
        self.root.update()
        self.assertGreater(view.scale, scale)
        x_before = canvas.canvasx(0)
        canvas.event_generate('<ButtonPress-1>', x=95, y=105)
        canvas.event_generate('<B1-Motion>', x=195, y=115)
        canvas.event_generate('<ButtonRelease-1>', x=195, y=115)
        self.root.update()
        self.assertLess(canvas.canvasx(0), x_before)
        self.assertIsNone(self.app._topology_ref)
        view.fit()
        self.root.update()
        self.assertLess(view.scale, scale)
        self.assertEqual(canvas.find_withtag('scene'), scene)
        view.fit('power')
        self.root.update()
        self.assertAlmostEqual(view.scale, scale, places=4)
        self.assertEqual(canvas.find_withtag('scene'), scene)
        self.schedule.assert_not_called()

    def test_bom_navigation_and_banner_simulation_remain_accessible(self):
        app = self.app
        self.root.maxsize(1920, 1080)
        self.root.geometry('1040x700')
        app.set_font_size(26)
        self.root.update()
        self.assertEqual(app.tab_topology.winfo_children(), [app._isolated_result_book])
        self.assertEqual(app.nb.index(app.tab_bom), app.nb.index(app.tab_topology) + 1)
        self.assertEqual(app.nb.tab(app.tab_bom, 'text').strip(), '② 器件 BOM 与规格')
        simulation_buttons = [button for button in buttons_below(app.container)
                              if button.cget('text').rstrip('…') == '仿真配置中心'
                              and button.winfo_ismapped()]
        self.assertEqual(len(simulation_buttons), 1)
        simulation, = simulation_buttons
        self.assertGreaterEqual(simulation.winfo_width(), simulation.winfo_reqwidth())
        self.assertLess(simulation.winfo_rooty(), app._result_navigation.winfo_rooty())
        with patch('simulation_center.show') as open_center:
            simulation.invoke()
        open_center.assert_called_once_with(app, 'circuit', comparison=False)

        bom_button = app._result_buttons[str(app.tab_bom)]
        if bom_button.winfo_ismapped():
            bom_button.invoke()
        else:
            combo = app._result_nav_combo
            self.assertTrue(combo.winfo_ismapped())
            combo.current(tuple(combo['values']).index('② 器件 BOM 与规格'))
            combo.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(app.selected_result_page(), 'bom')
        self.assertTrue(app._bom_editor.tree.winfo_ismapped())

    def test_selected_topology_ink_and_input_caption_restore_on_switch(self):
        app = self.app
        view = app.topology_view
        canvas = view.canvas
        items = [item for item, _, _ in view._refs['C_O2D']]
        line = next(item for item in items if canvas.type(item) == 'line')
        text = next(item for item in items if canvas.type(item) == 'text')
        caption = app._inline_cap_editors[1].fields['C'][0]
        style = ttk.Style(self.root)
        original_width = float(canvas.itemcget(line, 'width'))
        original_ink = canvas.itemcget(line, 'fill')
        original_font = canvas.itemcget(text, 'font')
        original_caption = caption.cget('style')

        self.click_ref('C_O2D')
        self.assertEqual(canvas.itemcget(line, 'fill'), '#0b3d86')
        self.assertGreater(float(canvas.itemcget(line, 'width')), original_width)
        self.assertEqual(style.lookup(caption.cget('style'), 'background'), '#224b89')
        self.assertEqual(style.lookup(caption.cget('style'), 'foreground'), '#ffffff')
        selected_font = font.nametofont(canvas.itemcget(text, 'font'), root=self.root)
        original_size = abs(selected_font.cget('size'))
        self.assertEqual(selected_font.cget('weight'), 'bold')
        view.zoom(65. / view.scale)
        self.root.update()
        self.assertGreater(abs(selected_font.cget('size')), original_size)
        self.assertEqual(canvas.itemcget(line, 'fill'), '#0b3d86')

        view.fit()
        self.click_ref('D_O2')
        self.assertEqual(view.selection, 'D_O2')
        self.assertEqual(float(canvas.itemcget(line, 'width')), original_width)
        self.assertEqual(canvas.itemcget(line, 'fill'), original_ink)
        self.assertEqual(canvas.itemcget(text, 'font'), original_font)
        self.assertEqual(caption.cget('style'), original_caption)
