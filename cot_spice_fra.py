"""Switching FRA for the shared COT voltage-feedback path."""
import json
import math
import time

import numpy as np

from spice_analysis import FrequencyRaw, loop_metrics, steady_quality
from spice_studies import override_parameters, write_study


METHOD = 'LTspice 原生时域 FRA，在 OUT1 防反前电容端与反馈输入之间串联注入。T = −V̂(cap1)/V̂(sense)。'
DB_LIMIT = 1.
PHASE_LIMIT = 8.


def prepare_fra(files, case, settings, measured_hz, *, amplitude_factor=1.):
    """Preserve the nominal power stage and cadence PI, with fixed rated load."""
    op = case['result']['op']
    frequency = min(float(measured_hz), op['f_sw'])
    start = settings['fra_start_hz']
    stop = min(settings['fra_stop_hz'], frequency/10)
    if stop <= start:
        raise ValueError('按单相开关频率十分之一限制后没有可用频带，请降低 FRA 起始频率')
    phase_count = op['cot']['phases']
    amplitude = op['cot']['output_cap_voltage_V']*settings['fra_amplitude_pct']/100*amplitude_factor
    delay = max(settings['step_ms']*1e-3,
                (settings['enable_delay_ms']+settings['soft_start_ms'])*1e-3+100/frequency)
    average_time = settings['fra_cycles']/frequency
    settle_time = max(.0003, 60/frequency)
    prepared = override_parameters(files, {'AFTER':1., 'TLOAD':1e6, 'SHUTDOWN':0.})
    control = prepared['control.inc'].decode('ascii')
    nominal_sense = 'B_ERR err 0 V=(V(ref)-V(cap1))/VSET'
    if control.count(nominal_sense) != 1:
        raise ValueError('COT 电压反馈入口缺失或重复')
    injection = (f'@1 cap1 sense fstart={start:.12g} fend={stop:.12g} oct={settings["fra_oct"]:g} '
                 f'delay={delay:.12g} pp0={amplitude:.12g} tavgmin={average_time:.12g} '
                 f'tsettle={settle_time:.12g} nmax=1')
    control = control.replace(nominal_sense, nominal_sense.replace('V(cap1)', 'V(sense)')+'\n'+injection)
    prepared['control.inc'] = control.encode('ascii')
    prepared['analysis.inc'] = (
        f'.options threads={int(settings["simulation_threads"])} method=trap reltol=0.001 plotwinsize=300\n'
        '.fra dTmax={MAXSTEP}\n.save V(out1) V(cap1) V(sense) V(rate) V(request)\n').encode('ascii')
    definition = dict(method=METHOD, start_hz=start, stop_hz=stop, delay_s=delay,
                      amplitude_pp_v=amplitude, settling_per_point_s=settle_time,
                      averaging_per_point_s=average_time, minimum_averaging_cycles=settings['fra_cycles'],
                      points_per_octave=settings['fra_oct'], maximum_simultaneous_tones=1,
                      phase_count=phase_count, measured_phase_switching_hz=float(measured_hz),
                      design_phase_switching_hz=op['f_sw'], voltage_injection=['cap1', 'sense'],
                      load='额定恒流，固定' if (case['p'].get('cot_config') or {}).get('load_mode')=='current' else '额定电阻，固定')
    manifest = json.loads(prepared['manifest.json'])
    manifest['fra'] = definition
    prepared['manifest.json'] = json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    return prepared, definition


def _measure(folder, definition):
    from spice_runtime import TransientRaw, read_log

    _, _, errors, warnings = read_log(folder/'Flyback.log')
    if errors:
        raise ValueError('；'.join(errors[:5]))
    paths = list(folder.glob('Flyback.fra_*.raw'))
    if len(paths) != 1:
        raise ValueError('需要 LTspice 17.1 或更新版本生成唯一的原生 FRA 复数 RAW')
    raw = FrequencyRaw(paths[0])
    gain = -raw.traces['gain_1']
    if np.any(np.abs(gain) < 1e-15):
        raise ValueError('FRA 返回接近零的环路信号，请核对注入或饱和')
    if not (math.isclose(raw.frequency[0], definition['start_hz'], rel_tol=1e-4)
            and math.isclose(raw.frequency[-1], definition['stop_hz'], rel_tol=1e-4)):
        raise ValueError('FRA 复数 RAW 未覆盖完整的设定频带')
    if not np.allclose(np.abs(raw.traces['v(stimulus_1)']), definition['amplitude_pp_v'], rtol=1e-4, atol=1e-10):
        raise ValueError('FRA 复数 RAW 中的激励幅值与配置不一致')
    transient = TransientRaw(folder/'Flyback.raw')
    try:
        frequency = definition['measured_phase_switching_hz']
        quality = steady_quality(transient, frequency, definition['delay_s'], 1,
                                 window=max(32/frequency, .0001), bins=8)
        if not quality['passed']:
            raise ValueError('FRA 注入前未达到额定稳态，请延后负载阶跃时刻')
        injection_index = np.searchsorted(transient.time, definition['delay_s'])
        rate = transient.trace('v(rate)')[injection_index:]
        request = transient.trace('v(request)')[injection_index:]
        if rate.size < 2 or np.max(np.abs(request-rate)) > max(1., frequency*1e-5):
            raise ValueError('FRA 期间触发频率达到限幅，请检查最小关断时间或减小注入幅值')
    finally:
        transient.close()
    return raw.frequency, gain, quality, warnings


def _verify_amplitude(primary_f, primary_gain, half_f, half_gain):
    if primary_f.shape != half_f.shape or not np.allclose(primary_f, half_f, rtol=1e-8, atol=0.):
        raise ValueError('FRA 半幅复核的频点与主扫描不同')
    ratio = half_gain/primary_gain
    db_error = 20*np.log10(np.abs(ratio))
    phase_error = np.degrees(np.angle(ratio))
    return dict(f=primary_f.tolist(), db_error=db_error.tolist(), phase_error=phase_error.tolist(),
                max_db_error=float(np.max(np.abs(db_error))),
                max_phase_error=float(np.max(np.abs(phase_error))),
                maximum_allowed_db_error=DB_LIMIT, maximum_allowed_phase_error=PHASE_LIMIT,
                passed=bool(np.max(np.abs(db_error)) <= DB_LIMIT and np.max(np.abs(phase_error)) <= PHASE_LIMIT))


def run_fra(files, case, settings, measured_hz, folder, execute, *, progress=None):
    """Run two independent switching experiments in a single endpoint budget."""
    from calculation_scheduler import CalculationCancelled
    from cot_loop import build_loop

    result = dict(available=False, complete=False, error=None, simulation=None, design=None)
    started = time.monotonic()
    deadline = started+settings['fra_timeout_s']
    explanation = '# COT 额定负载开关 FRA\n\n'+METHOD+'\n\n运行 Flyback.cir，读取 Flyback.fra_1.raw。\n'
    sweeps = []
    try:
        for label, factor in (('primary', 1.), ('half_amplitude', .5)):
            sweep = folder/label
            prepared, definition = prepare_fra(files, case, settings, measured_hz, amplitude_factor=factor)
            if factor == 1.:
                result['definition'] = definition
            write_study(sweep, prepared, explanation)
            if progress:
                progress('主 FRA 扫描' if factor == 1. else '相同频点半幅复核')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('本端点 FRA 主扫与半幅复核超出合计时间预算')
            elapsed = execute(sweep, remaining)
            frequency, gain, quality, warnings = _measure(sweep, definition)
            result[label] = dict(elapsed_s=elapsed, definition=definition, startup_steady=quality,
                                 warnings=warnings, real=gain.real.tolist(), imag=gain.imag.tolist())
            sweeps.append((frequency, gain))
        (f, gain), (half_f, half_gain) = sweeps
        result['amplitude_check'] = check = _verify_amplitude(f, gain, half_f, half_gain)
        result['complete'] = True
        models, _ = build_loop(case['p'], case['result']['op'])
        comparison = np.asarray(models[2](2j*np.pi*f)).ravel()
        if len(comparison) != len(f) or not np.all(np.isfinite(comparison)):
            raise ValueError('COT 同频点解析环路计算异常')
        result['design'] = dict(loop=loop_metrics(f, comparison))
        if not check['passed']:
            raise ValueError('半幅复测幅相差异超过 1 dB 或 8°，待复核')
        result['simulation'] = dict(loop=loop_metrics(f, gain))
        result['available'] = True
    except CalculationCancelled:
        raise
    except (ValueError, TypeError, RuntimeError, OSError, KeyError, IndexError, TimeoutError) as exc:
        result['error'] = str(exc)
    result['wall_elapsed_s'] = time.monotonic()-started
    from cot_acceptance import assess_fra
    result['acceptance'] = assess_fra(result,case['p'])
    return result
