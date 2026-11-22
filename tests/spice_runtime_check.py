"""Validate actual-evidence parsing and cancellation without launching user apps."""
import os
import sys
from pathlib import Path
import tempfile
from threading import Barrier
import time
import unittest
from unittest.mock import patch,MagicMock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from spice_runtime import (TransientRaw,read_log,_run,compare_design,_comparison_rows,partial_transient_time,
                           endpoint_workers,run_endpoint_cases)
from calculation_scheduler import CalculationCancelled


class RuntimeChecks(unittest.TestCase):
    def test_original_short_window_retains_narrow_current_peak(self):
        from types import SimpleNamespace
        raw=SimpleNamespace(time=np.array([0.,.1,.10001,.10002,.2]),
                            trace=lambda _:np.array([0.,0.,8.,0.,0.]))
        shown=TransientRaw.samples(raw,['i(ls2)'],.099,.101,None)
        self.assertEqual(max(shown['i(ls2)']),8.)
        self.assertIn(.10001,shown['time'])
        self.assertEqual((shown['time'][0],shown['time'][-1]),(.099,.101))
        coarse=TransientRaw.samples(raw,['i(ls2)'],.099,.101,3)
        self.assertEqual(max(coarse['i(ls2)']),0.)

    def test_protection_reason_uses_only_evidence_at_first_trip(self):
        from spice_analysis import protection_stop
        t=np.arange(12)*1e-7
        channels={'v(fault)':np.array([0]*6+[1]*6), 'v(xu_ctrl:xsuper:scp)':np.array([0]*5+[1]+[0]*6),
            'v(xu_ctrl:olpt)':np.array([0]*10+[1,1]), 'v(xu_ctrl:cs_filtered)':np.linspace(0,.6,12),
            'i(lp)':np.arange(12.)}
        raw=MagicMock(time=t,names=channels);raw.trace.side_effect=channels.__getitem__
        trip=protection_stop(raw,{'fault_max':1},250000)
        self.assertAlmostEqual(trip['first_trip_s'],6e-7)
        self.assertIn('SCP',trip['cause']);self.assertNotIn('OLP',trip['cause'])
        self.assertEqual(trip['primary_peak_a'],6.)
        del channels['v(xu_ctrl:xsuper:scp)']
        self.assertIn('待核对',protection_stop(raw,{'fault_max':1},250000)['cause'])
        self.assertIsNone(protection_stop(raw,{'fault_max':0},250000))

    def test_single_and_multi_result_contracts(self):
        import json
        from runtime_resources import configure_numeric_threads
        configure_numeric_threads()
        from design_engine.service import calculate
        from spice_export import project_files
        for filename in ('40W_CCM_FLYBACK.json','3_OUTPUT_COUPLED_FLYBACK.json'):
            run=calculate(json.loads((ROOT/'examples'/filename).read_text(encoding='utf-8')),analysis='endpoints',include_loop=False,include_cross_regulation=False)
            bundle=run.runtime_bundle();case=bundle['cases'][0]
            meta=json.loads(project_files(bundle['base_spec'],bundle=bundle)['manifest.json'])
            measured=dict(fault_max=0)
            for i in range(1,len(meta['hardware']['windings'])+1):measured.update({f'out{i}_earlier':30.,f'out{i}_before':30.})
            rows,ready=_comparison_rows(case,measured,meta)
            self.assertTrue(ready);self.assertTrue(all(r['design'] is not None for r in rows))
            self.assertTrue(any(r['status']=='测量缺失' for r in rows))

    def test_meas_log_scalar_period_and_param(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'result.log'
            path.write_text('primary_rms: RMS(i(lp))=2.56 FROM 0.01 TO 0.02\n'
                'switching_period=4e-06 FROM 0.01 TO 0.010004\n'
                'frequency_actual: 1/switching_period=250000\n'
                'analysis.inc(7): Voltage not found.\n',encoding='utf-8')
            measures,_,errors,_=read_log(path)
            self.assertEqual(measures,dict(primary_rms=2.56,switching_period=4e-6,frequency_actual=250000))
            self.assertTrue(errors)

    def test_raw_breakpoint_times_and_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'result.raw'
            header='Title: bench\nFlags: real forward\nNo. Variables: 2\nNo. Points: 3\nVariables:\n\t0\ttime\ttime\n\t1\tV(out1)\tvoltage\nBinary:\n'.encode('utf-16-le')
            data=np.zeros(3,dtype=[('time','<f8'),('values','<f4',(1,))]);data['time']=[0,-.1,.2];data['values'][:,0]=[0,1,2]
            path.write_bytes(header+data.tobytes())
            raw=TransientRaw(path)
            np.testing.assert_allclose(raw.time,[0,.1,.2]);self.assertEqual(raw.samples(['v(out1)'],0,.2,3)['v(out1)'],[0,1,2]);raw.close()
            path.write_bytes(path.read_bytes()[:-1])
            self.assertAlmostEqual(partial_transient_time(path),.1)
            with self.assertRaisesRegex(ValueError,'不完整'):TransientRaw(path)

    def test_cancel_terminates_only_owned_process(self):
        process=MagicMock();process.poll.return_value=None
        with patch('spice_runtime.subprocess.Popen',return_value=process) as launch:
            with self.assertRaises(CalculationCancelled):
                _run('LTspice.exe',Path('.'),180,MagicMock(side_effect=[False,True]))
        process.terminate.assert_called_once();process.wait.assert_called_once()
        self.assertEqual(launch.call_args.args[0][1],'-b')

    def test_cancelled_job_never_launches_another_simulator(self):
        with patch('spice_runtime.subprocess.Popen') as launch:
            with self.assertRaises(CalculationCancelled):
                _run('LTspice.exe',Path('.'),180,lambda:True)
            launch.assert_not_called()

    def test_endpoint_budget_leaves_capacity_and_uses_affinity(self):
        counter = 'process_cpu_count' if hasattr(os,'process_cpu_count') else 'cpu_count'
        with patch('spice_runtime.os.'+counter, return_value=16):
            self.assertEqual(endpoint_workers(2, 2), 2)
            self.assertEqual(endpoint_workers(2, 8), 1)
            self.assertEqual(endpoint_workers(1, 2), 1)
            self.assertEqual(endpoint_workers(2, 2, parallel=False), 1)
        with patch('spice_runtime.os.'+counter, return_value=4):
            self.assertEqual(endpoint_workers(2, 1), 1)

    def test_endpoint_error_cancels_other_worker_before_cleanup(self):
        started = Barrier(2, timeout=3)
        exits = []

        def solve(case, stopped, notify):
            started.wait()
            if case == 'low':
                raise ValueError('low endpoint failed before launch')
            limit = time.monotonic() + 3
            while not stopped() and time.monotonic() < limit:
                time.sleep(.01)
            exits.append(stopped())
            raise CalculationCancelled()

        with self.assertRaisesRegex(ValueError, 'low endpoint failed'):
            run_endpoint_cases(['low', 'high'], solve, workers=2, cancelled=lambda:False,
                               progress=None, stages_per_case=1, total=2)
        self.assertEqual(exits, [True])

    def test_no_simulator_never_writes_or_fakes_results(self):
        with tempfile.TemporaryDirectory() as td,patch('spice_runtime.find_ltspice',return_value=None):
            path=Path(td)/'comparison.docx'
            with self.assertRaisesRegex(ValueError,'未检测到'):compare_design(None,path)
            self.assertFalse(path.exists());self.assertEqual(list(Path(td).iterdir()),[])


if __name__=='__main__':unittest.main()
