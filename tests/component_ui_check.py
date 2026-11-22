"""Owned transparent Tk instance; never operates another application window."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import main
from parameter_panel_preview import capture


class ComponentUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk();cls.root.attributes('-alpha',0)
        cls.update_patch=patch.object(main.PowerSupplyAnalyzer,'schedule_update',return_value=None)
        cls.update_patch.start();cls.app=main.PowerSupplyAnalyzer(cls.root)
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.geometry('1440x920')
        cls.errors=[];cls.root.report_callback_exception=lambda *exc:cls.errors.append(exc)
        cls.original=copy.deepcopy(cls.app._config_dict())

    @classmethod
    def tearDownClass(cls):
        cls.app._closing=True;cls.app._work_cancel.set()
        for job in cls.root.tk.call('after','info'):cls.root.after_cancel(job)
        cls.root.destroy();cls.update_patch.stop()

    def test_editor_roundtrip_context_and_no_resolve(self):
        app=self.app;root=self.root
        app._apply_config(copy.deepcopy(self.original))
        self.assertTrue(app.update_all(),app.status_var.get())
        app.nb.select(app.tab_bom)
        root.update();editor=app._bom_editor
        self.assertIs(editor.winfo_toplevel(), root)
        editor.tree.selection_set('Q1');editor.select();root.update()
        self.assertTrue(editor.editors['current_rms_A'].winfo_ismapped())
        self.assertTrue(editor.editors['current_peak_A'].winfo_ismapped())
        self.assertFalse(editor.editors['current_avg_A'].winfo_ismapped())
        for key,value in dict(manufacturer='测试厂家',model='TEST-200V',package='DFN5x6',
                              voltage_V='200',current_rms_A='20',current_peak_A='40').items():editor.draft[key].set(value)
        eta=app._last['res']['eta']
        with patch('loss_model.compute_design',side_effect=AssertionError('metadata must not resolve')):
            self.assertTrue(editor.apply_item())
        self.assertEqual(app._last['res']['eta'],eta)
        self.assertEqual(app.get_params()['component_management']['items']['Q1']['voltage_V'],200)
        self.assertEqual(app.get_params()['component_management']['items']['Q1']['current_rms_A'],20)
        saved=json.loads(json.dumps(app._config_dict(),ensure_ascii=False,allow_nan=False))
        app._apply_config(saved);self.assertEqual(app._component_management['items']['Q1']['model'],'TEST-200V')
        self.assertEqual(app._component_management['items']['Q1']['current_peak_A'],40)
        self.assertTrue(app.update_all(),app.status_var.get())
        app.nb.select(app.tab_bom);root.update()
        editor=app._bom_editor
        editor.tree.selection_set('Q1');editor.select();root.update()
        out=ROOT/'artifacts/qa/component-management';out.mkdir(parents=True,exist_ok=True)
        capture(root,out/'desktop-bom.png')
        self.assertTrue(editor.tree.winfo_ismapped())
        full_rows = int(editor.tree.cget('height'))
        self.assertGreaterEqual(full_rows, 14)
        self.assertGreater(editor.detail.winfo_height(),60)
        editor.draft['model'].set('未应用草稿')
        editor.mark_stale()
        self.assertEqual(editor.tree.set('Q1','status'),'待重新计算')
        editor.refresh()
        self.assertEqual(editor.draft['model'].get(),'未应用草稿')
        editor.draft['model'].set('TEST-200V')
        app._parameter_pane_width = 350
        root.geometry('1040x620')
        root.update()
        app._resize_left()
        root.update()
        canvas = app._bom_scroll.canvas
        self.assertTrue(app.left.winfo_ismapped())
        self.assertEqual(editor._form_columns,2)
        compact_rows = int(editor.tree.cget('height'))
        self.assertGreaterEqual(compact_rows, 10)
        self.assertLess(compact_rows, full_rows)
        self.assertLess(canvas.yview()[1],1)
        canvas.yview_moveto(1);root.update()
        self.assertAlmostEqual(canvas.yview()[1], 1.)
        detail_bottom = editor.detail.winfo_rooty() + editor.detail.winfo_height()
        self.assertLessEqual(detail_bottom, canvas.winfo_rooty() + canvas.winfo_height())
        capture(root,out/'desktop-bom-small.png')
        # Invalid input is rejected without corrupting saved ratings.
        editor.draft['voltage_V'].set('-1')
        with patch('component_ui.messagebox.showerror') as alert:self.assertFalse(editor.apply_item())
        self.assertTrue(alert.called)
        self.assertEqual(app._component_management['items']['Q1']['voltage_V'],200)
        # Loading another file must clear earlier file's metadata, not inherit it.
        legacy=copy.deepcopy(self.original)
        legacy.pop('component_management',None)
        app._apply_config(legacy)
        self.assertNotIn('Q1',app._component_management.get('items',{}))
        root.update();self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
