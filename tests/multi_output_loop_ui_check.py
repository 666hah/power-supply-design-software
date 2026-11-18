"""Test-owned Tk integration: background loop, views, tuning and failure."""
from pathlib import Path
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from engineering_ui import Tooltip
from coupled_integration_check import configuration


class LoopUIChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk(); cls.root.attributes('-alpha', 0)
        cls.update_patch = patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None)
        cls.update_patch.start()
        cls.app = main.PowerSupplyAnalyzer(cls.root)
        cls.app._control_ready = True
        cls.root.unbind('<Configure>')
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.geometry('1400x900'); cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True; cls.app._calculation_worker.close()
        Tooltip.hide_all(cls.root)
        for job in cls.root.tk.splitlist(cls.root.tk.call('after', 'info')):
            cls.root.after_cancel(job)
        cls.root.destroy(); cls.update_patch.stop()

    def setUp(self):
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.app.nb.select(self.app.tab_topology)
        self.app._apply_config(configuration())
        self.app._loop_signature = None; self.app._loop_error = None
        self.app._loop_result = None
        self.assertTrue(self.app.update_all(), self.app.status_var.get())

    def tearDown(self):
        self.root.update()
        self.assertEqual(self.errors, [])

    def wait_loop(self):
        deadline = time.perf_counter()+15
        while self.app._loop_signature != main.parameter_signature(self.app._last['p']):
            self.root.update()
            self.assertLess(time.perf_counter(), deadline, self.app.loop_esr_note.get())
            time.sleep(.005)
        self.root.update()

    def test_background_loop_and_both_views_use_current_output_count(self):
        self.app.nb.select(self.app.tab_loop); self.root.update()
        self.wait_loop()
        self.assertIsNone(self.app._loop_error)
        self.assertTrue(self.app._loop_result['model']['esr_included'])
        self.assertIn('每颗 C+ESR',self.app.loop_esr_note.get())
        self.assertNotIn('有效频带 ≤', self.app.loop_esr_note.get())
        self.assertIn('带宽限制已停用', self.app.loop_esr_note.get())
        self.assertEqual(self.app.nb.tab(self.app.tab_loop, 'state'), 'normal')
        self.assertEqual(self.app.nb.tab(self.app.tab_comp, 'state'), 'normal')
        self.assertIs(self.app._last['res']['loop'], self.app._loop_result)
        self.app.loop_view.set('各路响应'); self.app.loop_load_output.set('OUT2')
        self.app._redraw_loop_view(); self.root.update()
        self.assertTrue(all(len(a.lines) == 3 for a in self.app.ax_loop.flat))
        self.assertIn('OUT2', self.app.ax_loop[1, 0].get_title())
        self.app.loop_view.set('反馈路负载阶跃'); self.app._redraw_loop_view(); self.root.update()
        self.assertTrue(self.app.canvas_loop_step.get_tk_widget().winfo_ismapped())
        self.assertFalse(self.app.loop_load_combo.winfo_ismapped())
        self.assertIn('10% → 90%', self.app.ax_loop_step[0].get_title())
        self.assertIn('90% → 10%', self.app.ax_loop_step[1].get_title())
        self.app.loop_view.set('主反馈 Bode'); self.app._redraw_loop_view()
        self.assertFalse(self.app.canvas_loop_step.get_tk_widget().winfo_manager())
        self.assertIn('开环', self.app.ax_loop[1, 0].get_title())

    def test_compact_loop_keeps_load_step_button_and_waveforms_visible(self):
        app = self.app
        self.addCleanup(self.root.geometry, self.root.winfo_geometry())
        self.addCleanup(app._apply_scale, app._font_k)
        self.root.geometry('1000x600')
        app._apply_scale(26/13)
        app.nb.select(app.tab_loop)
        self.root.update()
        self.wait_loop()

        # A long model explanation may wrap in a narrow results panel.
        # It must never consume the space needed for view selection.
        note = app.esr_note_label
        self.addCleanup(note.configure, wraplength=note.cget('wraplength'))
        note.configure(wraplength=185)
        app.loop_esr_note.set('反馈路使用平均模型。' * 35)
        self.root.update()
        self.assertIs(app.tab_loop.pack_slaves()[0], app.loop_view_row)
        self.assertTrue(app.loop_step_button.winfo_ismapped())
        self.assertGreaterEqual(app.loop_step_button.winfo_width(),
                                app.loop_step_button.winfo_reqwidth())

        app.loop_step_button.invoke()
        self.root.update()
        self.assertFalse(app.loop_bode_controls.winfo_ismapped())
        canvas = app.canvas_loop_step.get_tk_widget()
        self.assertTrue(canvas.winfo_ismapped())
        self.assertGreater(canvas.winfo_height(), app.tab_loop.winfo_height() * .55)
        self.assertIn('10% → 90%', app.ax_loop_step[0].get_title())
        self.assertIn('90% → 10%', app.ax_loop_step[1].get_title())

        app.loop_bode_button.invoke()
        self.root.update()
        self.assertTrue(app.loop_bode_controls.winfo_ismapped())
        self.assertFalse(canvas.winfo_ismapped())

    def test_auto_tune_preserves_requested_crossover_and_verifies_before_write(self):
        self.app.nb.select(self.app.tab_loop); self.root.update(); self.wait_loop()
        self.app.params['pm_target'].set(65)
        self.app.params['fc_target'].set(3.2); self.app.params['fc_target_unit'].set('k')
        # Match these presentation targets to the test snapshot, as a normal
        # successful design update would, without recomputing the same circuit.
        p = self.app.get_params(); p.update(self.app._rcd_parameters())
        self.app._last['p'] = p
        self.app._loop_signature = main.parameter_signature(p)
        self.app.run_auto_tune()
        self.assertNotIn('error', self.app.tune_result.get())
        self.assertAlmostEqual(self.app.get_param('fc_target'), 3200)
        self.assertNotIn('fc 降至', self.app.tune_result.get())
        self.assertIn('type type2', self.app.tune_result.get())

    def test_completed_model_error_does_not_requeue_forever(self):
        self.app.set_param('KP', self.app.get_param('KP')+.12345)
        p = self.app.get_params(); p.update(self.app._rcd_parameters())
        self.app._last['p'] = p
        with patch('plants.build_loop_models', side_effect=ValueError('测试导通边界')) as build:
            self.app.nb.select(self.app.tab_loop); self.root.update(); self.wait_loop()
            self.assertIn('测试导通边界', self.app.loop_esr_note.get())
            for _ in range(3):
                self.app._redraw_loop_view(); self.root.update()
            self.assertEqual(build.call_count, 1)
            self.assertIsNone(self.app._loop_result)

    def test_tuning_during_pending_design_never_solves_on_tk_thread(self):
        self.app._snapshot_valid = False
        with patch.object(self.app,'calculate_transfer_functions') as calculate:
            self.app.run_auto_tune()
        calculate.assert_not_called()
        self.assertIn('后台工作点',self.app.tune_result.get())


if __name__ == '__main__':
    unittest.main(verbosity=2)
