"""Actual Tk lifecycle checks; simulator substitutes are explicitly labelled."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_sequence_ui as ui
import system_workspace as model
from system_workspace_ui import SystemWorkspace


class SequenceDesktopChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch('ui_preferences.font_size', return_value=14))
        self.stack.enter_context(patch('spice_runtime.find_ltspice', return_value=''))
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.shell = SystemWorkspace(self.root, recovery=False)
        self.shell.initialize()
        self.directory = ROOT/'artifacts'/'system-sequence-ui'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=self.directory)))
        self.root.update()

    def tearDown(self):
        dialog = self.shell._sequence_dialog
        if dialog and dialog.job is not None:
            dialog.stop_event.set()
            self.drain(dialog)
        # Child toplevels own their idle/scroll callbacks; close them through
        # their normal lifecycle before cancelling the root's remaining jobs.
        if dialog and not dialog.closed:
            dialog.close()
        for task in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(task)
        self.root.destroy()
        self.stack.close()
        self.assertEqual(self.errors, [])

    def dialog(self):
        self.shell.show_sequence()
        dialog = self.shell._sequence_dialog
        dialog.output.set(str(self.scratch))
        self.root.update()
        return dialog

    def runner(self, function):
        self.stack.enter_context(patch.dict(sys.modules, system_sequence_runtime=SimpleNamespace(run=function)))

    def drain(self, dialog):
        deadline = time.monotonic()+5
        while dialog.job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(dialog.job, '后台任务未按时停止')

    def test_apply_and_si_roundtrip_without_running(self):
        self.runner(lambda *_args, **_kwargs: self.fail('应用不能启动仿真'))
        dialog = self.dialog()
        original_spec = copy.deepcopy(self.shell.project['units'][0]['spec'])
        dialog.setting_variables['stop_s'].set('70')
        source, unit, load, edge = dialog.editors
        source.variables['on_s'].set('3')
        source.variables['off_s'].set('45')
        source.variables['resistance_ohm'].set('80')
        self.assertFalse(source.variables['sink_current'].get())
        source.variables['sink_current'].set(True)
        unit.variables['enable_s'].set('8')
        unit.variables['disable_s'].set('55')
        unit.variables['vin_on_V'].set('20')
        unit.variables['vin_off_V'].set('18')
        unit.variables['soft_start_s'].set('4')
        load.variables['mode'].set('I')
        load.variables['on_V'].set('24')
        load.variables['off_V'].set('20')
        load.variables['delay_s'].set('3')
        load.variables['input_capacitance_F'].set('22')
        edge.variables['inductance_H'].set('2.4')
        self.assertTrue(dialog.apply())
        config = self.shell.project['sequence_config']
        self.assertAlmostEqual(config['settings']['stop_s'], .07)
        self.assertAlmostEqual(config['sources']['BUS-01']['on_s'], .003)
        self.assertAlmostEqual(config['sources']['BUS-01']['resistance_ohm'], .08)
        self.assertIs(config['sources']['BUS-01']['sink_current'], True)
        self.assertAlmostEqual(config['units']['PSU-01']['soft_start_s'], .004)
        self.assertAlmostEqual(config['rail_loads']['PSU-01/OUT1']['input_capacitance_F'], 22e-6)
        self.assertAlmostEqual(config['connections']['LINK-001']['inductance_H'], 2.4e-6)
        self.assertEqual(self.shell.project['units'][0]['spec'], original_spec)
        self.assertIsNone(dialog.job)
        path = self.scratch/'saved.json'
        model.save_project(self.shell.project, path)
        reopened = model.load_project(path)
        self.assertEqual(reopened['sequence_config'], config)
        dialog.close()
        self.shell.project = reopened
        again = self.dialog()
        self.assertEqual(again.editors[0].variables['on_s'].get(), '3')
        self.assertTrue(again.editors[0].variables['sink_current'].get())
        self.assertEqual(again.editors[2].variables['mode'].get(), 'I')

    def test_joint_switching_capacitance_default_and_saved_override(self):
        self.runner(lambda *_args, **_kwargs: self.fail('切换寄生电容设置不能启动仿真'))
        original = copy.deepcopy(self.shell.project)
        old_settings = ui.normalize(self.shell.project)
        old_settings['settings'].pop('include_switching_capacitance')
        upgraded = ui.normalize(self.shell.project, old_settings)
        self.assertIs(upgraded['settings']['include_switching_capacitance'], True)
        self.assertNotIn('include_switching_capacitance', old_settings['settings'])
        self.assertEqual(self.shell.project, original)
        for bad in (0, 1, 'false', None):
            invalid = copy.deepcopy(upgraded)
            invalid['settings']['include_switching_capacitance'] = bad
            with self.assertRaisesRegex(ValueError, '布尔值'):
                ui.normalize(self.shell.project, invalid)
        dialog = self.dialog()
        self.assertTrue(dialog.setting_variables['include_switching_capacitance'].get())
        self.assertNotIn('sequence_config', self.shell.project)
        setting = next(row for row in ui.SETTINGS if row[0] == 'include_switching_capacitance')
        self.assertIn('推荐', setting[1])
        for term in ('Coss', 'Qg', 'Cj', '旧工程', '可能卡顿', '不改写单元设计'):
            self.assertIn(term, setting[4])
        for enabled in (False, True):
            dialog.setting_variables['include_switching_capacitance'].set(enabled)
            self.assertTrue(dialog.apply())
            self.assertIs(self.shell.project['sequence_config']['settings']['include_switching_capacitance'], enabled)
            if not enabled:
                self.assertIn('DCM', dialog.status.get())
                self.assertIn('卡顿', dialog.status.get())
            self.assertEqual(self.shell.project['units'], original['units'])
            path = self.scratch/'joint-capacitance.json'
            model.save_project(self.shell.project, path)
            reopened = model.load_project(path)
            self.assertIs(reopened['sequence_config']['settings']['include_switching_capacitance'], enabled)
            self.assertEqual(reopened['units'], original['units'])
            dialog.close()
            self.shell.project = reopened
            dialog = self.dialog()
            self.assertIs(dialog.setting_variables['include_switching_capacitance'].get(), enabled)
            self.assertIsNone(dialog.job)

    def test_frozen_worker_inputs_progress_and_result(self):
        started, release = threading.Event(), threading.Event()
        observed = []
        def runner(project, folder, **options):
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            observed.append(copy.deepcopy(project))
            started.set()
            release.wait(3)
            self.assertFalse(options['cancelled']())
            options['progress']({'message': '替身运行器：不代表真实 SPICE 验证'})
            project['units'][0]['name'] = 'worker-only'
            report = Path(folder)/'README.md'
            report.write_text('Fixture report: simulator was substituted.', encoding='utf-8')
            return dict(status='complete', report_path=str(report), summary='模型边界：输入 UVLO 未知')
        self.runner(runner)
        dialog = self.dialog()
        append = dialog.append
        def append_on_main(value):
            self.assertIs(threading.current_thread(), threading.main_thread())
            append(value)
        dialog.append = append_on_main
        dialog.start()
        self.assertTrue(started.wait(2))
        self.assertTrue(dialog.run_button.instate(['disabled']))
        self.shell.project['units'][0]['name'] = '用户运行中编辑'
        release.set()
        self.drain(dialog)
        self.assertNotEqual(observed[0]['units'][0]['name'], '用户运行中编辑')
        self.assertEqual(self.shell.project['units'][0]['name'], '用户运行中编辑')
        self.assertIn('判定', dialog.status.get())
        self.assertIn('UVLO 未知', dialog.log.get('1.0', 'end'))
        self.assertFalse(dialog.open_report.instate(['disabled']))
        self.assertFalse(dialog.open_folder.instate(['disabled']))
        with patch.object(ui.os, 'startfile') as opened:
            dialog.view_report()
            opened.assert_called_once_with(str(self.scratch/'README.md'))

    def test_cancel_keeps_ownership_until_worker_exits(self):
        started, cancelled, release = threading.Event(), threading.Event(), threading.Event()
        def runner(_project, folder, **options):
            started.set()
            while not options['cancelled']():
                time.sleep(.005)
            cancelled.set()
            release.wait(2)
            return dict(status='cancelled', directory=folder)
        self.runner(runner)
        dialog = self.dialog()
        dialog.start()
        self.assertTrue(started.wait(2))
        dialog.close()
        self.assertTrue(cancelled.wait(2))
        self.root.update()
        self.assertTrue(dialog.win.winfo_exists())
        self.assertIsNotNone(dialog.job)
        release.set()
        self.drain(dialog)
        self.assertFalse(dialog.win.winfo_exists())
        self.assertTrue(dialog.closed)

    def test_invalid_values_and_unknown_fields_stay_explicit(self):
        dialog = self.dialog()
        dialog.editors[1].variables['vin_on_V'].set('20')
        self.assertFalse(dialog.apply())
        self.assertNotIn('sequence_config', self.shell.project)
        self.assertIn('同时', dialog.status.get())
        dialog.editors[1].variables['vin_on_V'].set('')
        dialog.editors[0].variables['resistance_ohm'].set('nan')
        self.assertFalse(dialog.apply())
        dialog.editors[0].variables['resistance_ohm'].set('50')
        self.assertTrue(dialog.apply())
        self.assertIsNone(self.shell.project['sequence_config']['units']['PSU-01']['vin_on_V'])
        self.assertIsNone(self.shell.project['sequence_config']['sources']['BUS-01']['current_limit_A'])
        self.assertEqual(self.shell.project['sequence_config']['units']['PSU-01']['vcc_mode'], 'ideal')

    def test_single_instance_and_changed_project_refusal(self):
        dialog = self.dialog()
        self.assertIs(dialog.win, self.shell.show_sequence())
        self.shell.new()
        self.assertFalse(dialog.apply())
        self.assertIn('切换工程', dialog.status.get())
        self.assertNotIn('sequence_config', self.shell.project)
        dialog.close()
        self.assertIsNot(dialog, self.dialog())

    def test_current_and_power_load_modes_require_positive_consumption_thresholds(self):
        dialog = self.dialog()
        load = dialog.editors[2]
        for mode in ('I', 'P'):
            load.variables['mode'].set(mode)
            load.variables['on_V'].set('')
            load.variables['off_V'].set('')
            self.assertFalse(dialog.apply())
            self.assertIn('耗功', dialog.status.get())
            self.assertNotIn('sequence_config', self.shell.project)
            load.variables['on_V'].set('8')
            load.variables['off_V'].set('0')
            self.assertFalse(dialog.apply())
        load.variables['mode'].set('I')
        load.variables['off_V'].set('6')
        load.variables['off_current_A'].set('.023')
        self.assertTrue(dialog.apply())
        saved = self.shell.project['sequence_config']['rail_loads']['PSU-01/OUT1']
        self.assertEqual(saved['mode'], 'I')
        self.assertEqual(saved['on_V'], 8.)
        self.assertEqual(saved['off_V'], 6.)
        self.assertEqual(saved['off_current_A'], .023)
        self.assertIsNone(dialog.job)

    def test_ldo_specific_fields_and_pg_dependency_can_be_saved(self):
        self.shell.project = model.load_project(ROOT/'examples'/'SYSTEM_LDO.json')
        dialog = self.dialog()
        unit = dialog.editors[1]
        self.assertIn('ldo_output_current_limit_A', unit.variables)
        self.assertEqual(unit.variables['ldo_output_current_limit_A'].get(), '')
        unit.variables['ldo_output_current_limit_A'].set('0.52')
        unit.variables['ldo_output_resistance_ohm'].set('0.12')
        unit.variables['wait_for_port'].set('BUS-01')
        unit.variables['pg_threshold_V'].set('4')
        unit.variables['pg_delay_s'].set('2')
        self.assertEqual(unit.variables['pg_hysteresis_V'].get(), '0')
        for invalid in ('4', '4.1'):
            unit.variables['pg_hysteresis_V'].set(invalid)
            self.assertFalse(dialog.apply())
            self.assertIn('迟滞', dialog.status.get())
        unit.variables['pg_hysteresis_V'].set('.3')
        self.assertTrue(dialog.apply())
        config = self.shell.project['sequence_config']['units']['LDO-01']
        self.assertEqual(config['ldo_output_current_limit_A'], .52)
        self.assertAlmostEqual(config['pg_delay_s'], .002)
        self.assertEqual(config['pg_hysteresis_V'], .3)
        path = self.scratch/'pg-hysteresis.json'
        model.save_project(self.shell.project, path)
        self.assertEqual(model.load_project(path)['sequence_config']['units']['LDO-01']['pg_hysteresis_V'], .3)

    def test_failure_keeps_logs_and_does_not_claim_completion(self):
        def runner(_project, folder, **_options):
            error = ValueError('替身：真实开关电路未收敛')
            error.directory = folder
            raise error
        self.runner(runner)
        dialog = self.dialog()
        dialog.start()
        self.drain(dialog)
        self.assertIn('未收敛', dialog.status.get())
        self.assertNotIn('运行完成', dialog.status.get())
        self.assertTrue(dialog.open_report.instate(['disabled']))
        self.assertFalse(dialog.open_folder.instate(['disabled']))
        self.assertFalse(dialog.run_button.instate(['disabled']))

    def test_structured_stages_conditions_and_source_profile_roundtrip(self):
        self.runner(lambda *_args, **_kwargs: self.fail('列表编辑不能运行仿真'))
        dialog = self.dialog()
        source, unit, load, _ = dialog.editors
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['hiccup'])
        source.variables['current_limit_A'].set('2')
        source.variables['trip_delay_s'].set('1.5')
        source.variables['retry_s'].set('7')
        self.assertIn('BUS-01', dialog.ports)
        profile = source.edit_list('voltage_profile')
        for ms, level in ((0, 0), (2, 1), (12, 1), (13, 0), (18, 0), (20, 1)):
            profile.variables['time_s'].set(str(ms))
            profile.variables['level'].set(str(level))
            self.assertTrue(profile.add())
        self.assertTrue(profile.save())
        self.assertNotIn('sequence_config', self.shell.project)
        conditions = unit.edit_list('ready_conditions')
        conditions.variables['port'].set('BUS-01')
        conditions.variables['on_V'].set('20')
        conditions.variables['off_V'].set('18')
        self.assertTrue(conditions.add())
        self.assertTrue(conditions.save())
        load.variables['on_V'].set('24')
        load.variables['off_V'].set('20')
        load.variables['delay_s'].set('1.2')
        stages = load.edit_list('stages')
        for name, ms, power, mode in (('固件启动', 0, 1., 'I'), ('正常运行', 3, 3., 'P')):
            for key, value in dict(name=name, after_s=str(ms), power_W=str(power), mode=mode, ramp_s='.5').items():
                stages.variables[key].set(value)
            self.assertTrue(stages.add())
        self.assertTrue(stages.save())
        self.assertTrue(dialog.apply(), dialog.status.get())
        cfg = self.shell.project['sequence_config']
        self.assertEqual(cfg['sources']['BUS-01']['protection_mode'], 'hiccup')
        self.assertEqual(cfg['sources']['BUS-01']['voltage_profile'][-1], dict(time_s=.020, level=1.))
        self.assertAlmostEqual(cfg['sources']['BUS-01']['retry_s'], .007)
        self.assertEqual(cfg['units']['PSU-01']['ready_conditions'][0]['port'], 'BUS-01')
        self.assertEqual(cfg['rail_loads']['PSU-01/OUT1']['stages'][1]['name'], '正常运行')
        self.assertAlmostEqual(cfg['rail_loads']['PSU-01/OUT1']['stages'][1]['after_s'], .003)
        path = self.scratch/'staged.json'
        model.save_project(self.shell.project, path)
        reopened = model.load_project(path)
        self.assertEqual(cfg, reopened['sequence_config'])
        dialog.close()
        self.shell.project = reopened
        again = self.dialog()
        editor = again.editors[2].edit_list('stages')
        self.assertEqual(editor.rows, cfg['rail_loads']['PSU-01/OUT1']['stages'])
        editor.cancel()

    def test_list_transaction_validation_and_protection_visibility(self):
        dialog = self.dialog()
        source = dialog.editors[0]
        dialog.tabs.select(source.page)
        for mode, expected in (('monitor', set()), ('cc', set()),
                               ('foldback', {'foldback_short_A'}), ('hiccup', {'trip_delay_s', 'retry_s'})):
            source.variables['protection_mode'].set(ui.PROTECTION_LABELS[mode])
            self.root.update()
            for key in ('foldback_short_A', 'trip_delay_s', 'retry_s'):
                self.assertEqual(source.form.sequence_field_boxes[key].winfo_manager() == 'grid', key in expected)
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['monitor'])
        profile = source.edit_list('voltage_profile')
        profile.variables['level'].set('1')
        self.assertFalse(profile.save())
        self.assertIn('未加入', profile.status.get())
        self.assertTrue(profile.add())
        profile.variables['time_s'].set('0')
        profile.variables['level'].set('0')
        self.assertTrue(profile.add())
        self.assertFalse(profile.save())
        self.assertIn('递增', profile.status.get())
        profile.cancel()
        self.assertEqual(dialog.draft['sources']['BUS-01']['voltage_profile'], [])
        stages = dialog.editors[2].edit_list('stages')
        stages.variables['name'].set('启动')
        self.assertTrue(stages.add())
        self.assertTrue(stages.save())
        self.assertEqual(len(dialog.draft['rail_loads']['PSU-01/OUT1']['stages']), 1)
        again = dialog.editors[2].edit_list('stages')
        again.table.selection_set('0')
        again.select()
        again.variables['name'].set('启动修订')
        self.assertTrue(again.update())
        self.assertEqual(again.rows[0]['name'], '启动修订')
        again.delete()
        self.assertTrue(again.save())
        self.assertEqual(dialog.draft['rail_loads']['PSU-01/OUT1']['stages'], [])

    def test_staged_editor_font_scroll_and_footer(self):
        dialog = self.dialog()
        dialog._apply_fonts(28)
        self.root.update()
        editor = dialog.editors[2].edit_list('stages')
        editor.win.geometry(f'{min(980, self.root.winfo_screenwidth()-80)}x{min(760, self.root.winfo_screenheight()-200)}+0+0')
        editor.win.lift()
        self.root.update()
        # Let the Windows compositor finish its transient-window animation;
        # a single Tk update can otherwise capture a translucent transition.
        deadline = time.monotonic()+.4
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        editor.scroll.sync()
        self.root.update()
        self.assertLess(editor.scroll.canvas.yview()[1]-editor.scroll.canvas.yview()[0], 1.)
        self.assertGreater(editor.scroll.canvas.winfo_height(), 70)
        self.assertGreater(editor.table.winfo_height(), 75)
        for button in editor.buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), editor.win.winfo_rootx()+editor.win.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), editor.win.winfo_rooty()+editor.win.winfo_height())
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(editor.win.winfo_rootx(), editor.win.winfo_rooty(),
                            editor.win.winfo_rootx()+editor.win.winfo_width(),
                            editor.win.winfo_rooty()+editor.win.winfo_height())).save(self.directory/'stages-font-28.png')
        (self.directory/'stages-ui-receipt.json').write_text(json.dumps(dict(
            screen=[self.root.winfo_screenwidth(), self.root.winfo_screenheight()],
            window=[editor.win.winfo_rootx(), editor.win.winfo_rooty(), editor.win.winfo_width(), editor.win.winfo_height()],
            table_height=editor.table.winfo_height(), form_height=editor.scroll.winfo_height(),
            callback_errors=self.errors), ensure_ascii=False, indent=2), encoding='utf-8')
        editor.cancel()

    def test_profile_requires_two_points_before_list_is_saved(self):
        dialog = self.dialog()
        source = dialog.editors[0]
        profile = source.edit_list('voltage_profile')
        profile.variables['time_s'].set('0')
        profile.variables['level'].set('0')
        self.assertTrue(profile.add())
        self.assertFalse(profile.save())
        self.assertIn('至少需要两个点', profile.status.get())
        self.assertFalse(profile.closed)
        self.assertEqual(dialog.draft['sources']['BUS-01']['voltage_profile'], [])
        profile.variables['time_s'].set('2')
        profile.variables['level'].set('1')
        self.assertTrue(profile.add())
        self.assertTrue(profile.save())
        self.assertTrue(dialog.apply())
        self.assertEqual(len(self.shell.project['sequence_config']['sources']['BUS-01']['voltage_profile']), 2)

    def test_source_output_capacitor_legacy_default_modes_and_si_roundtrip(self):
        self.runner(lambda *_args, **_kwargs: self.fail('编辑源端电容不能运行仿真'))
        dialog = self.dialog()
        source = dialog.editors[0]
        self.assertEqual(source.variables['output_capacitance_F'].get(), '0')
        self.assertEqual(source.variables['output_esr_ohm'].get(), '0.1')
        self.assertNotIn('sequence_config', self.shell.project)
        for mode in ('monitor', 'cc', 'foldback', 'hiccup'):
            source.variables['protection_mode'].set(ui.PROTECTION_LABELS[mode])
            for key in ('output_capacitance_F', 'output_esr_ohm'):
                self.assertEqual(source.form.sequence_field_boxes[key].winfo_manager(), 'grid')
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['monitor'])
        source.variables['output_capacitance_F'].set('10')
        source.variables['output_esr_ohm'].set('0')
        self.assertTrue(dialog.apply(), dialog.status.get())
        row = self.shell.project['sequence_config']['sources']['BUS-01']
        self.assertAlmostEqual(row['output_capacitance_F'], 10e-6)
        self.assertEqual(row['output_esr_ohm'], 0.)
        path = self.scratch/'source-output-capacitor.json'
        model.save_project(self.shell.project, path)
        reopened = model.load_project(path)
        self.assertEqual(reopened['sequence_config']['sources']['BUS-01'], row)
        for key, bad in (('output_capacitance_F', '-1'), ('output_esr_ohm', '-.1'), ('output_esr_ohm', 'nan')):
            original = source.variables[key].get()
            source.variables[key].set(bad)
            self.assertFalse(dialog.apply())
            self.assertEqual(self.shell.project['sequence_config']['sources']['BUS-01'], row)
            source.variables[key].set(original)
        # Direct JSON normalization must use the same finite/nonnegative rules.
        for key, bad in (('output_capacitance_F', -1e-6), ('output_esr_ohm', -.1), ('output_capacitance_F', float('inf'))):
            invalid = copy.deepcopy(dialog.draft)
            invalid['sources']['BUS-01'][key] = bad
            with self.assertRaises(ValueError):
                ui.normalize(self.shell.project, invalid)

    def test_inactive_invalid_protection_draft_keeps_legal_values_and_explains(self):
        dialog = self.dialog()
        source = dialog.editors[0]
        original = copy.deepcopy(dialog.draft['sources']['BUS-01'])
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['hiccup'])
        source.variables['current_limit_A'].set('2')
        source.variables['trip_delay_s'].set('')
        source.variables['retry_s'].set('0')
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['cc'])
        self.assertTrue(dialog.apply(), dialog.status.get())
        self.assertIn('无效草稿未应用', dialog.status.get())
        row = self.shell.project['sequence_config']['sources']['BUS-01']
        self.assertEqual(row['trip_delay_s'], original['trip_delay_s'])
        self.assertEqual(row['retry_s'], original['retry_s'])
        self.assertEqual(row['protection_mode'], 'cc')
        # A form rebuild must not silently delete the pending text.
        source._show(source.current)
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['hiccup'])
        self.assertEqual(source.variables['trip_delay_s'].get(), '')
        self.assertEqual(source.variables['retry_s'].get(), '0')
        self.assertFalse(dialog.apply())
        source.variables['trip_delay_s'].set('2.5')
        source.variables['retry_s'].set('7')
        self.assertTrue(dialog.apply(), dialog.status.get())
        self.assertNotIn('无效草稿', dialog.status.get())
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['monitor'])
        self.assertTrue(dialog.apply())
        source._show(source.current)
        source.variables['protection_mode'].set(ui.PROTECTION_LABELS['hiccup'])
        self.assertEqual(source.variables['trip_delay_s'].get(), '2.5')
        self.assertEqual(source.variables['retry_s'].get(), '7')
        self.assertTrue(dialog.apply())
        self.assertAlmostEqual(self.shell.project['sequence_config']['sources']['BUS-01']['trip_delay_s'], .0025)
        self.assertAlmostEqual(self.shell.project['sequence_config']['sources']['BUS-01']['retry_s'], .007)

    def test_large_font_scroll_and_controls_remain_accessible(self):
        dialog = self.dialog()
        height = min(760, self.root.winfo_screenheight()-190)
        dialog.win.geometry(f'980x{height}+0+0')
        dialog._apply_fonts(28)
        self.root.update()
        for index, editor in enumerate(dialog.editors, 1):
            dialog.tabs.select(index)
            self.root.update()
            editor.scroll.sync()
            self.root.update()
            self.assertLess(editor.scroll.canvas.yview()[1]-editor.scroll.canvas.yview()[0], 1.)
            self.assertGreater(editor.scroll.canvas.winfo_height(), 50)
            for button in dialog.action_buttons:
                self.assertGreaterEqual(button.winfo_x(), 0)
                self.assertLessEqual(button.winfo_x()+button.winfo_width(), dialog.footer.winfo_width()+1)
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), dialog.win.winfo_rooty()+dialog.win.winfo_height())
        dialog.tabs.select(2)
        self.root.update()
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(dialog.win.winfo_rootx(), dialog.win.winfo_rooty(),
                            dialog.win.winfo_rootx()+dialog.win.winfo_width(),
                            dialog.win.winfo_rooty()+dialog.win.winfo_height())).save(self.directory/'large-font.png')
        dialog._apply_fonts(40)
        self.root.update()
        editor = dialog.editors[1]
        editor.scroll.canvas.yview_moveto(1.)
        self.root.update()
        self.assertGreater(editor.scroll.canvas.winfo_height(), 40)
        for button in dialog.action_buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), dialog.win.winfo_rooty()+dialog.win.winfo_height())
            self.assertLessEqual(button.winfo_x()+button.winfo_width(), dialog.footer.winfo_width()+1)
        ImageGrab.grab(bbox=(dialog.win.winfo_rootx(), dialog.win.winfo_rooty(),
                            dialog.win.winfo_rootx()+dialog.win.winfo_width(),
                            dialog.win.winfo_rooty()+dialog.win.winfo_height())).save(self.directory/'font-40.png')
        receipt = dict(check='real Tk controls and scroll geometry; simulator substituted in worker tests',
                       callback_errors=self.errors, font_px=[28, 40], window=[980, height])
        (self.directory/'ui-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
