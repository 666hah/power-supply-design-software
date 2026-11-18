"""Optional real LTspice evidence for MOS/diode transitions and PWM age timing.

Runs the three shipped reference prototypes at Vinmin for 16 ms. This is a
short startup/load-step regression, not a complete FRA or protection sign-off.
Every exported input and full RAW/log are retained under the chosen directory.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
from design_engine.specification import load_spec
from nonisolated_spice import MODEL_VERSION, project_files
from spice_runtime import _run, find_ltspice, read_log, TransientRaw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120.)
    args = parser.parse_args()
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=True)
    executable = find_ltspice()
    if not executable:
        raise RuntimeError('LTspice executable not configured')
    evidence = dict(scope='16 ms standalone startup/load step at Vinmin; not full FRA/protection validation',
                    hardware_changes=[], model_change=MODEL_VERSION+' continuous MOS/diode transitions and exact-slope finite age reset',
                    cases=[])
    for name in ('24W_BUCK_VM_TPS40200', '24W_BUCK_PCM_LTC3864', '24W_BOOST_PCM_LM5022'):
        folder = target / name
        if folder.exists():
            raise FileExistsError(f'Will not overwrite evidence: {folder}')
        folder.mkdir()
        original = (ROOT / 'examples' / (name + '.json')).read_bytes()
        p = copy.deepcopy(load_spec(json.loads(original)))
        vin = p['V_in_min']
        p.update(V_in=vin, V_in_min=vin, V_in_max=vin)
        p['spice_config'].update(stop_ms=16., step_ms=12., simulation_threads=1.)
        (folder / 'test-input.json').write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
        files = project_files(p)
        # Observe the actual internal ramp so a changed modulation gain cannot
        # pass merely because the closed loop eventually regulates its output.
        files['analysis.inc'] += b'\n.save V(xu_ctrl:xcore:age)\n'
        for filename, content in files.items():
            (folder / filename).write_bytes(content)
        meta = json.loads(files['manifest.json'])
        case = dict(example=name, source_sha256=hashlib.sha256(original).hexdigest(),
                    model_version=meta['model_version'], voltage=vin, stop_s=.016,
                    test_overrides=dict(V_in_min=vin, V_in_max=vin, stop_ms=16., step_ms=12., simulation_threads=1.),
                    library_sha256=meta['library_sha256'], oscillator_age=meta['oscillator_age'],
                    observation_overrides=['save internal oscillator age'])
        print(f'Running {name}', flush=True)
        try:
            case['wall_seconds'] = _run(executable, folder, args.timeout, lambda: False)
            measures, log, errors, warnings = read_log(folder / 'Flyback.log')
            case.update(errors=errors, warning_count=len(warnings), warnings=warnings[:8], measurements=measures)
            elapsed = re.search(r'Total elapsed time:\s*([\d.]+)', log)
            case['solver_seconds'] = float(elapsed[1]) if elapsed else None
            raw = TransientRaw(folder / 'Flyback.raw')
            try:
                t = raw.time
                voltage = np.asarray(raw.trace('v(out1)'), dtype=float)
                current = np.asarray(raw.trace('i(l1)'), dtype=float)
                fault = np.asarray(raw.trace('v(fault)'), dtype=float)
                mask = t >= .015
                mean = float(np.trapezoid(voltage[mask], t[mask]) / (t[mask][-1] - t[mask][0]))
                age = np.asarray(raw.trace('v(xu_ctrl:xcore:age)'), dtype=float)
                period = meta['oscillator_age']['period_s']
                phase = np.remainder(t, period)
                active_window = ((t > 2*period) & (phase > 2e-9)
                                 & (phase < meta['resolved_controller']['DMAX']*period-2e-9))
                age_samples = int(np.count_nonzero(active_window))
                age_error = (float(np.max(np.abs(age[active_window]-phase[active_window])))
                             if age_samples else float('inf'))
                case.update(points=len(t), end_s=float(t[-1]), output_last_1ms_average_V=mean,
                            output_final_V=float(voltage[-1]), inductor_peak_A=float(np.max(current)),
                            fault_peak=float(np.max(fault)), target_V=p['V_out'],
                            age_active_window_samples=age_samples, age_max_absolute_error_s=age_error)
                case['passed'] = bool(not errors and not warnings and t[-1] >= .016 - 1e-12
                                      and np.all(np.isfinite(voltage)) and np.all(np.isfinite(current))
                                      and np.max(fault) < .5 and mean > .8*p['V_out']
                                      and age_samples > 100 and age_error < 4e-12)
            finally:
                raw.close()
        except Exception as exc:
            case.update(passed=False, failure=str(exc))
        evidence['cases'].append(case)
        (target / 'receipt.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in case.items() if k not in ('measurements',)}, ensure_ascii=False), flush=True)
    evidence['passed'] = all(c['passed'] for c in evidence['cases'])
    (target / 'receipt.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
