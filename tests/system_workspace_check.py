"""System-tree persistence, electrical interfaces and actual Tk return lifecycle."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_workspace as w


class SystemChecks(unittest.TestCase):
    def test_legacy_config_metadata_and_roundtrip(self):
        raw = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p = w.normalize_project(w.fresh_project(raw))
        self.assertEqual(p['units'][0]['spec']['__comp'], raw['__comp'])
        self.assertEqual(len(p['units'][0]['rails']), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'系统工程.json'
            w.save_project(p, path)
            self.assertEqual(w.load_project(path), p)
            path.write_text(json.dumps(raw), encoding='utf-8')
            imported = w.load_project(path)
            self.assertEqual(imported['units'][0]['spec']['__comp'], raw['__comp'])

    def test_cascade_budget_sync_and_cycle_rejection(self):
        p = w.normalize_project(w.fresh_project())
        buck = json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
        p['units'].append(dict(id='PSU-02', name='下级 Buck', source=w.disconnected(), spec=buck))
        p = w.normalize_project(p)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=1))
        w.sync_input(p, 'PSU-02')
        self.assertEqual(p['units'][1]['spec']['V_in_min'], 30)
        self.assertEqual(p['units'][1]['spec']['V_in_max'], 30)
        rows = w.checks(p)
        self.assertTrue(rows['interfaces'][1]['ok'])
        demand = p['units'][1]['spec']['P_out']/p['units'][1]['spec']['eta_guess']
        self.assertAlmostEqual(next(r['allocated'] for r in rows['capacity'] if r['port']=='PSU-01/OUT1'), demand)
        before = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            w.connect(p, 'PSU-01', dict(kind='unit', id='PSU-02', output=1))
        self.assertEqual(p, before)

    def test_port_reduction_delete_and_restore_preserve_child(self):
        raw = json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p = w.normalize_project(w.fresh_project(raw))
        p['units'].append(dict(id='PSU-02', name='下级', source=dict(kind='unit', id='PSU-01', output=3), spec=w.fresh_project()['units'][0]['spec']))
        p = w.normalize_project(p)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=3))
        child = copy.deepcopy(p['units'][1]['spec'])
        detached = w.set_unit_config(p, 'PSU-01', w.fresh_project()['units'][0]['spec'])
        self.assertEqual(detached, ['PSU-02'])
        self.assertEqual(w.incoming(p, 'PSU-02'), [])
        self.assertEqual(p['units'][1]['spec'], child)
        w.connect(p, 'PSU-02', dict(kind='unit', id='PSU-01', output=1))
        record = w.remove_node(p, 'unit', 'PSU-01')
        self.assertEqual(p['units'][0]['spec'], child)
        w.restore_node(p, record)
        self.assertEqual(w.incoming(p, 'PSU-02')[0]['source']['id'], 'PSU-01')


class DesktopLifecycle(unittest.TestCase):
    def test_first_screen_and_two_independent_calculators_return(self):
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        import tkinter as tk
        from system_workspace_ui import SystemWorkspace
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            shell = SystemWorkspace(root, recovery=False)
            shell.initialize()
            root.maxsize(1920, 1080)
            root.geometry('1440x900')
            root.update()
            self.assertIn('szj', shell._github_button.cget('text'))
            with patch('project_identity.webbrowser.open_new_tab', return_value=True) as open_tab:
                shell._github_button.invoke()
                open_tab.assert_called_once_with('https://github.com/sunzhanjie2-sudo/power-supply-design-software')
            self.assertIsNone(shell.calculator)
            self.assertEqual(len(shell.project['units']), 1)
            shell.add_unit()
            shell.project['units'][1]['name'] = '独立 Buck'
            buck = json.loads((ROOT/'examples/24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
            w.set_unit_config(shell.project, 'PSU-02', buck)
            shell.set_zoom(2)
            root.update()
            shell.canvas.xview_moveto(.27)
            view = shell.canvas.xview()
            for identity in ('PSU-01','PSU-02','PSU-01'):
                shell.open_unit(identity)
                app = shell.calculator
                self.assertIsNotNone(app)
                self.assertIs(app.root, root)
                self.assertTrue(root.winfo_ismapped())
                self.assertFalse(shell._architecture.winfo_manager())
                self.assertEqual(app.container.winfo_manager(), 'grid')
                self.assertEqual(shell._github_button.winfo_manager(), 'grid')
                self.assertEqual(app._topo_key(), 'BUCK' if identity=='PSU-02' else 'FLYBACK')
                if identity=='PSU-01':
                    app.set_param('P_out', 42)
                    app.restore_result_page('mag')
                app.on_close()
                self.assertTrue(root.winfo_exists())
                self.assertIsNone(shell.calculator)
                self.assertEqual(shell._architecture.winfo_manager(), 'grid')
                self.assertAlmostEqual(shell.canvas.xview()[0], view[0], places=2)
                self.assertEqual(w.unit_by_id(shell.project, identity)['spec']['P_out'], 24 if identity=='PSU-02' else 42)
            shell.open_unit('PSU-01')
            self.assertIs(shell.calculator, app)
            self.assertEqual(app.selected_result_page(), 'mag')

            with tempfile.TemporaryDirectory() as directory:
                saved = str(Path(directory)/'system.json')
                app.set_param('P_out', 43)
                with patch('system_workspace_ui.filedialog.asksaveasfilename', return_value=saved):
                    self.assertTrue(shell.save())
                self.assertIs(shell.calculator, app)
                self.assertEqual(w.unit_by_id(w.load_project(saved), 'PSU-01')['spec']['P_out'], 43)
                self.assertEqual(shell._save_state.get(), '已保存到工程文件')

            field = app._param_widgets['P_out'][1]
            field.delete(0, 'end')
            field.insert(0, 'pending')
            with patch('system_workspace_ui.messagebox.showerror') as show_error:
                self.assertFalse(shell.back_to_architecture())
                show_error.assert_called_once()
            self.assertIs(shell.calculator, app)
            self.assertEqual(w.unit_by_id(shell.project, 'PSU-01')['spec']['P_out'], 43)
            app.set_param('P_out', 43)
            self.assertTrue(shell.back_to_architecture())
            root.update()
            # No dangling bind_all handlers referring to destroyed Toplevels.
            root.event_generate('<MouseWheel>', delta=-120)
            root.update()
            self.assertEqual(errors, [])
        finally:
            if shell.calculator:
                shell.calculator._workspace_return = lambda app: True
                shell.calculator.on_close()
            root.destroy()

    def test_system_simulation_returns_after_unit_navigation(self):
        import tkinter as tk
        from tkinter import ttk
        from simulation_center import show
        from system_workspace_ui import SystemWorkspace

        root = tk.Tk()
        shell = SystemWorkspace(root, recovery=False)
        shell.initialize()
        try:
            window = show(shell, 'unit', system=True)
            page = shell._simulation_center.pages['unit']
            next(widget for widget in page.winfo_children() if isinstance(widget, ttk.Button)).invoke()
            calculator = shell.calculator
            self.assertIsNotNone(calculator)
            self.assertIs(calculator.root, root)
            self.assertEqual(window.state(), 'withdrawn')
            self.assertFalse(calculator._simulation_center.closed)
            self.assertTrue(shell.back_to_architecture())
            root.update()
            self.assertEqual(window.state(), 'normal')
            self.assertTrue(calculator._simulation_center.closed)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
