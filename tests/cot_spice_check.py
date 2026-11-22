"""COT routes to the synchronous phase deck instead of the old PWM prototype."""
import json
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cot_buck_spice import MODEL_VERSION, project_files as cot_project_files
from cot_spice_fra import prepare_fra, _verify_amplitude
from design_engine.service import calculate
from nonisolated import is_enabled
from spice_export import project_files
from system_sequence_units import compile_unit
import numpy as np


class CotSpiceTests(unittest.TestCase):
    def setUp(self):
        self.design = json.loads((ROOT/'examples/96W_BUCK_COT_4PH.json').read_text('utf-8'))

    def test_sixteen_phase_package_and_controller_selection(self):
        self.design.pop('cot_config',None)  # This is the unchanged legacy-deck contract.
        self.design.update(buck_phases=16, control_mode='Voltage Mode',
                           spice_config={'niso_profile':1})
        run = calculate(self.design, analysis='endpoints', include_loop=False,include_cross_regulation=False)
        bundle = run.runtime_bundle()
        p = bundle['base_spec']
        self.assertFalse(is_enabled(p))
        files = project_files(p,bundle=bundle)
        meta = json.loads(files['manifest.json'])
        self.assertEqual(meta['model_version'],MODEL_VERSION)
        self.assertEqual(meta['hardware']['phases'],16)
        self.assertIn(b'.step param VIN list 10 14',files['design_params.inc'])
        self.assertIn(b'PH16',files['Flyback.asc'])
        body, control = files['power_stage.inc'], files['control.inc']
        self.assertEqual(sum(line.startswith(b'L') for line in body.splitlines()),16)
        self.assertIn(b'SH16 vbus sw16 gate16',body)
        self.assertIn(b'SL16 sw16 0 lo16',body)
        self.assertEqual(control.count(b'delay(V(ticks),{TON})'),16)
        self.assertNotIn('GenericBuckBoostPWM.lib',files)
        self.assertEqual(meta['settings']['fra_enabled'],0.)
        self.assertEqual(meta['settings']['short_test'],0.)

    def test_cot_fra_preserves_pi_timing_and_feedback_injection_nodes(self):
        self.design.update(cot_kp_hz=1200., cot_ki_hz_per_s=560000.,
                           spice_config={'fra_enabled':1, 'fra_stop_hz':100000.})
        run = calculate(self.design, analysis='endpoints', include_loop=False,include_cross_regulation=False)
        bundle = run.runtime_bundle()
        case = bundle['cases'][0]
        files = cot_project_files(bundle['base_spec'],bundle=bundle,case=case)
        meta = json.loads(files['manifest.json'])
        self.assertEqual(meta['settings']['fra_enabled'],1.)
        self.assertEqual(meta['settings']['fra_cycles'],100.)
        self.assertIn(b'.tran ',files['analysis.inc'])
        self.assertNotIn(b'@1',files['control.inc'])
        primary, definition = prepare_fra(files,case,meta['settings'],300000.)
        half, second = prepare_fra(files,case,meta['settings'],300000.,amplitude_factor=.5)
        for deck in (primary,half):
            self.assertEqual(deck['power_stage.inc'],files['power_stage.inc'])
            self.assertIn(b'.fra dTmax={MAXSTEP}',deck['analysis.inc'])
            self.assertIn(b'B_ERR err 0 V=(V(ref)-V(sense))/VSET',deck['control.inc'])
            self.assertIn(b'@1 cap1 sense',deck['control.inc'])
            self.assertIn(b'.param AFTER=1\n',deck['design_params.inc'])
            self.assertIn(b'.param SHUTDOWN=0\n',deck['design_params.inc'])
            for key in (b'KP',b'KI',b'TON',b'FBIAS',b'FF',b'TSS'):
                original = next(line for line in files['design_params.inc'].splitlines()
                                if line.startswith(b'.param '+key+b'='))
                self.assertIn(original,deck['design_params.inc'])
        self.assertEqual(meta['controller_pi'],dict(kp_hz=1200.,ki_hz_per_s=560000.))
        self.assertAlmostEqual(definition['stop_hz'],30000.)
        self.assertAlmostEqual(second['amplitude_pp_v'],definition['amplitude_pp_v']/2)

    def test_half_amplitude_verifies_same_complex_frequencies(self):
        f = np.asarray([500.,1000.,2000.])
        gain = np.asarray([2.-1j,.9-.5j,.5-.3j])
        self.assertTrue(_verify_amplitude(f,gain,f,gain*.99)['passed'])
        self.assertFalse(_verify_amplitude(f,gain,f,gain*np.exp(1j*.15))['passed'])
        self.assertFalse(_verify_amplitude(f,gain,f,1.2*gain)['passed'])
        with self.assertRaisesRegex(ValueError,'频点'):
            _verify_amplitude(f,gain, f+1, gain)

    def test_system_startup_reuses_cot_power_and_phase_control(self):
        unit=compile_unit(self.design, 'xpsu')
        text=unit['subckt_text']
        self.assertIn('.subckt xpsu_UNIT input en vcc out1',text)
        self.assertIn('B_TICKS 0 ticks I=1n*V(rate)',text)
        self.assertIn('A_Q4 set4 reset4',text)
        self.assertIn('L4 sw4 cap1',text)
        for fixture in ('VIN_SOURCE ', 'V_EN ', 'V_VCC ', 'B_LOAD '):
            self.assertNotIn('\n'+fixture,text)
        self.assertEqual(unit['output_count'],1)
        self.assertIn('phase4',unit['probes']['cot_phase_limits'])

    def test_comparison_parallel_endpoints_keep_decks_and_stages_isolated(self):
        from cot_spice_comparison import compare_design

        self.design['spice_config'] = dict(fra_enabled=1, line_load_enabled=1, simulation_threads=2)
        bundle = calculate(self.design, analysis='endpoints', include_loop=False,
                           include_cross_regulation=False).runtime_bundle()
        started = Barrier(2, timeout=5)
        stages = {'Vinmin_COT': [], 'Vinmax_COT': []}

        def simulate(_executable, folder, _timeout, cancelled, **_):
            self.assertFalse(cancelled())
            if folder.name in stages:
                vin = 10 if folder.name == 'Vinmin_COT' else 14
                config = (folder/'design_params.inc').read_text('ascii')
                self.assertIn(f'.param VIN={vin}\n', config)
                started.wait()
                stages[folder.name].append('nominal')
            else:
                endpoint = next(p.name for p in folder.parents if p.name in stages)
                stages[endpoint].append(folder.name)
            return 0.01

        def step(_files, _case, settings, folder, execute, **_):
            execute(folder, settings['simulation_timeout_s'])
            return dict(complete=True)

        def fra(_files, _case, settings, _measured, folder, execute, *, progress):
            for name in ('primary', 'half_amplitude'):
                progress(name)
                execute(folder/name, settings['fra_timeout_s'])
            return dict(available=True)

        def line_load(files, _rails, voltages, *_args, **_):
            self.assertEqual(voltages, [10., 14.])
            self.assertIn(b'.param VIN=14\n', files['design_params.inc'])
            self.assertTrue(all(trace == ['nominal', 'load_step', 'primary', 'half_amplitude']
                                for trace in stages.values()))
            return dict(complete=True)

        nominal = dict(complete=True, nominal_comparable=True, measurements=dict(frequency_actual=400e3))
        progress = []
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temporary, \
                patch('spice_runtime.endpoint_workers', return_value=2), \
                patch('spice_runtime._run', new=simulate), \
                patch('spice_runtime.read_log', return_value=({}, '', [], [])), \
                patch('spice_runtime.TransientRaw'), \
                patch('cot_spice_comparison._summarize_case', side_effect=lambda *_args, **_kwargs: dict(nominal)), \
                patch('spice_boundary.run_load_transient', new=step), \
                patch('cot_spice_fra.run_fra', new=fra), \
                patch('spice_line_load.run_line_load', side_effect=line_load) as line, \
                patch('cot_spice_comparison._write_report', side_effect=lambda path, _: path.write_bytes(b'report')):
            result = compare_design(bundle, Path(temporary)/'test.docx', executable='test',
                                    cancelled=lambda:False, progress=lambda done,total,_:progress.append((done,total)))
            line.assert_called_once()
            with ZipFile(result['path']) as archive:
                evidence = json.loads(archive.read('comparison.json'))
                self.assertEqual(evidence['execution'], dict(endpoint_workers=2, threads_per_case=2))
                self.assertEqual([case['id'] for case in evidence['cases']], list(stages))
                self.assertTrue(all(f'{name}/Flyback.cir' in archive.namelist() for name in stages))
        self.assertEqual(result['successful'], 2)
        self.assertEqual(result['fra_successful'], 2)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], (9, 9))


if __name__ == '__main__':
    unittest.main(verbosity=2)
