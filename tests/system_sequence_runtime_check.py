"""Runtime ownership/failure receipts with explicit simulator substitutes only.

No LTspice executable is launched, RAW fixture bytes are deliberately invalid,
and the analyzer/report dependencies are substituted. These tests do not prove
any electrical waveform, protection action, convergence or physical result.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculation_scheduler import CalculationCancelled
import system_sequence_runtime as runtime

LABEL = 'TEST FIXTURE ONLY - NO SIMULATOR WAS EXECUTED'


class SequenceRuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        base = ROOT/'artifacts'/'system-sequence-runtime-check'
        base.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=base)))
        self.output = self.scratch/'runs'
        self.executable = self.scratch/'LTspice.exe'
        self.executable.write_text(LABEL, encoding='ascii')
        self.project = dict(title=LABEL, units=[dict(id='PSU-01', spec=dict(C_in=123e-6))],
                            sequence_config=dict(settings=dict(stop_s=.04)))
        self.manifest = dict(schema='test-fixture-not-simulation', settings=dict(timeout_s=123., stop_s=.04),
                             sources={}, units={}, loads={}, limitations=[LABEL])
        self.messages = []
        self.export = self.stack.enter_context(patch('system_sequence_export.export_project', side_effect=self.fake_export))
        self.runner = self.stack.enter_context(patch('spice_runtime._run', side_effect=self.fake_runner))
        self.find = self.stack.enter_context(patch('spice_runtime.find_ltspice', return_value=str(self.executable)))
        self.read_log = self.stack.enter_context(patch('spice_runtime.read_log', return_value=({}, LABEL, [], ['fixture warning'])))
        self.analyze = self.stack.enter_context(patch('system_sequence_analysis.analyze', side_effect=self.fake_analysis))
        self.report = self.stack.enter_context(patch('system_sequence_report.write', side_effect=self.fake_report))

    def tearDown(self):
        self.stack.close()

    def fake_export(self, project, folder, *, cancelled, progress):
        folder = Path(folder)
        self.assertTrue(folder.is_dir())
        self.assertFalse((folder/'Flyback.raw').exists(), 'new run must not start with old RAW')
        self.assertFalse((folder/'Flyback.log').exists(), 'new run must not start with old simulator log')
        if cancelled():
            raise CalculationCancelled()
        (folder/'Flyback.cir').write_text('* '+LABEL+'\n.end\n', encoding='ascii')
        (folder/'SystemNetwork.inc').write_text('* '+LABEL+'\nRfixture a 0 1e9\n', encoding='ascii')
        (folder/'project.json').write_text(json.dumps(copy.deepcopy(project), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (folder/'manifest.json').write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        progress('替身：仅导出标识夹具，未生成实际电源电路。')
        return copy.deepcopy(self.manifest)

    def fake_runner(self, executable, folder, timeout, cancelled, *, progress, simulation_end):
        self.assertEqual(executable, str(self.executable.resolve()))
        self.assertEqual(timeout, 123.)
        self.assertEqual(simulation_end, .04)
        self.assertFalse(cancelled())
        folder = Path(folder)
        (folder/'Flyback.log').write_text(LABEL+'\n', encoding='utf-8')
        (folder/'Flyback.raw').write_bytes(b'INVALID RAW BY DESIGN: '+LABEL.encode('ascii'))
        progress('替身：未执行 LTspice，不构成真实仿真证据。')
        return .125

    def fake_analysis(self, path, manifest):
        self.assertEqual(Path(path).name, 'Flyback.raw')
        self.assertTrue(Path(path).read_bytes().startswith(b'INVALID RAW BY DESIGN:'))
        self.assertEqual(manifest, self.manifest)
        return dict(status='completed', simulation_complete=True, analysis_complete=True,
                    summary=dict(sources=[], units=[], loads=[]), waveforms=dict(time=[]),
                    failure_reasons=[], events=[], limitations=[LABEL])

    def fake_report(self, folder, manifest, result):
        folder = Path(folder)
        path = folder/'TEST_FIXTURE_RECEIPT.txt'
        path.write_text(LABEL+'\nstatus='+result['status']+'\n'+
                        '\n'.join(result.get('failure_reasons', []))+'\n', encoding='utf-8')
        return dict(report_path=str(path), fixture_only=True)

    def run_fixture(self, **options):
        return runtime.run(self.project, self.output, progress=self.messages.append, **options)

    def saved(self, outcome):
        path = Path(outcome['result_path'])
        self.assertTrue(path.is_file())
        value = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(value['schema'], 'power.system-sequence-result/1')
        self.assertEqual(value['directory'], outcome['directory'])
        self.assertGreaterEqual(value['total_elapsed_s'], 0.)
        self.assertIsInstance(value['failure_reasons'], list)
        self.assertTrue((path.parent/'progress.log').is_file())
        self.assertFalse(list(path.parent.glob('*.writing')), 'atomic JSON write must not leave temporary files')
        return value

    def assert_readable_failure(self, outcome, expected, status='failed'):
        self.assertEqual(outcome['status'], status)
        saved = self.saved(outcome)
        self.assertEqual(saved['status'], status)
        self.assertIn(expected, ' '.join(saved['failure_reasons']))
        receipt = Path(outcome['report_path']).read_text('utf-8')
        self.assertIn(LABEL, receipt)
        self.assertIn(expected, receipt)
        return saved

    def test_completed_substitute_is_explicit_and_retains_exact_evidence_hashes(self):
        outcome = self.run_fixture()
        self.assertEqual(outcome['status'], 'completed')
        saved = self.saved(outcome)
        self.assertEqual(saved['simulation_elapsed_s'], .125)
        self.assertEqual(saved['log_warnings'], ['fixture warning'])
        self.assertEqual(saved['limitations'], [LABEL])
        self.assertEqual(saved['waveforms'], {'time': []}, 'no synthetic physical waveform is supplied')
        root = Path(outcome['directory'])
        expected = {'Flyback.cir', 'SystemNetwork.inc', 'project.json', 'manifest.json', 'Flyback.log'}
        self.assertEqual(set(saved['evidence_files']), expected)
        for name, digest in saved['evidence_files'].items():
            self.assertEqual(digest, hashlib.sha256((root/name).read_bytes()).hexdigest())
        self.export.assert_called_once()
        self.runner.assert_called_once()
        self.read_log.assert_called_once_with(root/'Flyback.log')
        self.analyze.assert_called_once_with(root/'Flyback.raw', self.manifest)
        self.report.assert_called_once()
        self.assertIn(LABEL, Path(outcome['report_path']).read_text('utf-8'))

    def test_invalid_raw_analysis_cannot_become_completed(self):
        self.analyze.side_effect = None
        self.analyze.return_value = dict(status='failed', simulation_complete=False, analysis_complete=False,
            failure_reasons=['替身：RAW损坏或未覆盖终止时间'], summary=dict(sources=[], units=[], loads=[]),
            waveforms=dict(time=[]), events=[], limitations=[LABEL])
        outcome = self.run_fixture()
        saved = self.assert_readable_failure(outcome, 'RAW损坏')
        self.assertFalse(saved['simulation_complete'])
        self.assertFalse(saved['analysis_complete'])
        self.assertTrue(any('不给出通过' in message for message in self.messages))
        self.assertFalse(any('瞬态完成；' in message for message in self.messages))

    def test_analyzer_exception_retains_readable_failed_receipt(self):
        self.analyze.side_effect = ValueError('替身：RAW头部无效')
        outcome = self.run_fixture()
        self.assert_readable_failure(outcome, 'RAW头部无效')

    def test_timeout_retains_partial_files_without_analyzing_them(self):
        def timeout(executable, folder, *args, **kwargs):
            (Path(folder)/'Flyback.log').write_text(LABEL+' partial log\n', encoding='utf-8')
            (Path(folder)/'Flyback.raw').write_bytes(b'INCOMPLETE FIXTURE ONLY')
            raise TimeoutError('替身：LTspice超过超时上限，本工况未完成')
        self.runner.side_effect = timeout
        outcome = self.run_fixture()
        self.assert_readable_failure(outcome, '超时')
        self.assertTrue((Path(outcome['directory'])/'Flyback.raw').is_file())
        # A failed/timeout log is read for diagnostics, never for a completed
        # measurement result. Partial RAW must still not reach the analyzer.
        self.read_log.assert_called_once_with(Path(outcome['directory'])/'Flyback.log')
        self.analyze.assert_not_called()

    def test_cancel_before_export_completion_does_not_launch_simulator(self):
        outcome = self.run_fixture(cancelled=lambda: True)
        self.assert_readable_failure(outcome, '用户取消', status='cancelled')
        self.runner.assert_not_called()
        self.analyze.assert_not_called()
        self.find.assert_not_called()

    def test_cancel_owned_runner_keeps_diagnostics_without_analysis(self):
        def stop(_executable, folder, *args, **kwargs):
            (Path(folder)/'Flyback.log').write_text(LABEL+' cancelled\n', encoding='utf-8')
            raise CalculationCancelled()
        self.runner.side_effect = stop
        outcome = self.run_fixture()
        self.assert_readable_failure(outcome, '用户取消', status='cancelled')
        self.analyze.assert_not_called()

    def test_cancel_after_runner_does_not_publish_complete_analysis(self):
        state = {'cancelled': False}
        def finish(*args, **kwargs):
            elapsed = self.fake_runner(*args, **kwargs)
            state['cancelled'] = True
            return elapsed
        self.runner.side_effect = finish
        outcome = self.run_fixture(cancelled=lambda: state['cancelled'])
        self.assert_readable_failure(outcome, '用户取消', status='cancelled')
        self.analyze.assert_not_called()

    def test_no_ltspice_keeps_export_and_readable_failure(self):
        self.find.return_value = None
        outcome = self.run_fixture()
        self.assert_readable_failure(outcome, '未找到LTspice')
        self.assertTrue((Path(outcome['directory'])/'Flyback.cir').is_file())
        self.runner.assert_not_called()
        self.analyze.assert_not_called()

    def test_missing_explicit_program_does_not_fall_back_to_other_install(self):
        outcome = self.run_fixture(ltspice=str(self.scratch/'does-not-exist.exe'))
        self.assert_readable_failure(outcome, '未找到LTspice')
        self.find.assert_not_called()
        self.runner.assert_not_called()

    def test_export_failure_keeps_partial_deck_and_readable_diagnostic(self):
        def export_failure(_project, folder, **_options):
            (Path(folder)/'Flyback.cir').write_text('* '+LABEL+'\n* export interrupted\n', encoding='ascii')
            raise ValueError('替身：输出端口配置不完整，拒绝导出')
        self.export.side_effect = export_failure
        outcome = self.run_fixture()
        saved = self.assert_readable_failure(outcome, '拒绝导出')
        self.assertEqual(set(saved['evidence_files']), {'Flyback.cir'})
        self.runner.assert_not_called()
        self.find.assert_not_called()
        self.analyze.assert_not_called()

    def test_report_failure_preserves_json_and_progress_log(self):
        self.report.side_effect = RuntimeError('替身：报告输出失败')
        outcome = self.run_fixture()
        saved = self.saved(outcome)
        # The independent analysis status remains distinguishable from a
        # failed report operation; its error must remain visible in JSON.
        self.assertEqual(saved['status'], 'completed')
        self.assertIn('报告输出失败', saved['report_error'])
        self.assertNotIn('report_path', outcome)
        self.assertIn('报告写入失败', (Path(outcome['directory'])/'progress.log').read_text('utf-8'))

    def test_old_completed_files_are_not_reused_when_new_log_is_missing(self):
        self.output.mkdir()
        old = self.output/'old-completed-run'
        old.mkdir()
        files = {}
        for folder in (self.output, old):
            for name in ('Flyback.log', 'Flyback.raw', 'result.json'):
                path = folder/name
                content = ('OLD FILE MUST NOT BE REUSED '+name+'\n').encode('ascii')
                path.write_bytes(content)
                files[path] = content
        self.runner.side_effect = None
        self.runner.return_value = .1  # Deliberately produces no new log/RAW.
        outcome = self.run_fixture()
        self.assertNotEqual(Path(outcome['directory']), old)
        self.assertNotEqual(Path(outcome['directory']), self.output)
        self.assert_readable_failure(outcome, '未生成日志')
        self.analyze.assert_not_called()
        self.read_log.assert_not_called()
        for path, content in files.items():
            self.assertEqual(path.read_bytes(), content)

    def test_each_call_uses_a_unique_owned_directory(self):
        one = self.run_fixture()
        first_bytes = Path(one['result_path']).read_bytes()
        two = self.run_fixture()
        self.assertNotEqual(one['directory'], two['directory'])
        self.assertEqual(Path(one['directory']).parent, self.output)
        self.assertEqual(Path(two['directory']).parent, self.output)
        self.assertEqual(Path(one['result_path']).read_bytes(), first_bytes)
        self.assertEqual(self.saved(two)['status'], 'completed')

    def test_frozen_project_and_exported_input_are_not_mutated(self):
        original = copy.deepcopy(self.project)
        outcome = self.run_fixture()
        self.assertEqual(self.project, original)
        supplied = self.export.call_args.args[0]
        self.assertIsNot(supplied, self.project)
        self.assertIsNot(supplied['units'], self.project['units'])
        self.assertIsNot(supplied['units'][0]['spec'], self.project['units'][0]['spec'])
        frozen = json.loads((Path(outcome['directory'])/'project.json').read_text('utf-8'))
        self.assertEqual(frozen, original)
        self.project['units'][0]['spec']['C_in'] = 9.
        self.project['title'] = 'caller edited after run'
        self.assertEqual(json.loads((Path(outcome['directory'])/'project.json').read_text('utf-8')), original)

    def test_caller_edits_during_export_cannot_change_owned_snapshot(self):
        original = copy.deepcopy(self.project)
        def edit_caller(owned, folder, **options):
            self.project['units'][0]['spec']['C_in'] = 9.
            self.project['title'] = 'caller editing while worker is running'
            self.assertEqual(owned, original)
            return self.fake_export(owned, folder, **options)
        self.export.side_effect = edit_caller
        outcome = self.run_fixture()
        self.assertEqual(json.loads((Path(outcome['directory'])/'project.json').read_text('utf-8')), original)
        self.assertEqual(self.project['units'][0]['spec']['C_in'], 9.)

    def test_log_reported_solver_error_blocks_raw_analysis(self):
        self.read_log.return_value = ({}, LABEL, ['替身：timestep too small'], [])
        outcome = self.run_fixture()
        self.assert_readable_failure(outcome, 'timestep too small')
        self.analyze.assert_not_called()

    def test_progress_observer_failure_does_not_destroy_result_receipt(self):
        def broken_observer(_message):
            raise RuntimeError('fixture observer failed')
        outcome = runtime.run(self.project, self.output, progress=broken_observer)
        self.assertEqual(outcome['status'], 'completed')
        saved = self.saved(outcome)
        self.assertEqual(saved['limitations'], [LABEL])
        self.assertIn('结果目录', (Path(outcome['directory'])/'progress.log').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
