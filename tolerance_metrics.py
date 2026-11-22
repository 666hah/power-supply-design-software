"""Project shared design results onto the two tolerance acceptance groups."""

import math
from numbers import Real

import numpy as np

from isolated_outputs import output_specs
from loop_acceptance import MIN_PHASE_MARGIN_DEG


VOLTAGE_KEYS = ('voltage_min', 'voltage_max')
OUTPUT_KEYS = (*VOLTAGE_KEYS, 'ripple_pp', 'transient_pp')


def _number(value):
    return float(value) if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) else None


def _limit(value, label, *, nonnegative=False):
    if value is None or value == '':
        return None
    parsed = _number(value)
    if parsed is None or (nonnegative and parsed < 0):
        raise ValueError(f'{label} 必须为'+('非负' if nonnegative else '')+'有限数值或空值')
    return parsed


def resolve_external_limits(p, overrides=None):
    """Resolve SI limits once on nominal hardware, before any sample is perturbed."""
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict) or not isinstance(overrides.get('outputs', {}), dict):
        raise ValueError('容差外特性规格及其各路输出应为对象')
    inputs = {str(index): row for index, row in overrides.get('outputs', {}).items()}
    legacy = {row.get('metric', row.get('id')): row for row in
              (p.get('engineering_acceptance') or {}).get('criteria', ())
              if row.get('enabled', True)}
    outputs = output_specs(p) if p.get('outputs') else [p]
    limits = {'outputs': {}}
    for index, output in enumerate(outputs, 1):
        row = inputs.get(str(index), {})
        if not isinstance(row, dict):
            raise ValueError(f'OUT{index} 外特性规格应为对象')
        voltage = legacy.get(f'out{index}_voltage', {})
        # Existing generic voltage criteria used the model's magnitude. Signed
        # inverting voltage limits require explicit entries in the new group.
        transfer_range = (voltage.get('comparison') == 'range' and p.get('topology') != 'BUCK-BOOST')
        ratio = _number(output.get('ripple_target', p.get('ripple_target')))
        volts = _number(output.get('V_out'))
        defaults = {
            'voltage_min': voltage.get('lower') if transfer_range else None,
            'voltage_max': voltage.get('upper') if transfer_range else None,
            'ripple_pp': abs(volts)*ratio if volts is not None and ratio is not None else None,
            'transient_pp': None,
        }
        result = {key: _limit(row.get(key, defaults[key]), f'OUT{index} {key}', nonnegative=key not in VOLTAGE_KEYS)
                  for key in OUTPUT_KEYS}
        low, high = (result[key] for key in VOLTAGE_KEYS)
        if low is not None and high is not None and low > high:
            raise ValueError(f'OUT{index} 输出电压下限不能大于上限')
        limits['outputs'][str(index)] = result
    limits['phase_margin'] = MIN_PHASE_MARGIN_DEG
    return limits


def _component_measurements(snapshot, group, add):
    from engineering_acceptance import _acceptance_metrics

    p = snapshot['p']
    checks = {row['id']: row for row in snapshot['checks']}
    for criterion in _acceptance_metrics(p, {'case': checks}):
        if criterion['group'] != group:
            continue
        row = checks.get(criterion['id'], {})
        comparison = row.get('comparison', criterion['comparison'])
        add(criterion['id'], criterion['name'], criterion['unit'],
            'min' if comparison in ('>', '>=') else 'max', row.get('value'),
            row.get('limit', criterion['limit']), group=group,
            strict=comparison in ('<', '>'), reason=row.get('note', criterion['note']))
    # Purchased inductors expose current limits as ratings, separately from
    # magnetic-density and temperature estimates in engineering acceptance.
    for key in ('inductor_peak', 'inductor_rms'):
        if key in checks:
            row = checks[key]
            add(key, row['name'], row.get('unit', 'A'), 'max', row.get('value'), row.get('limit'),
                group=group, strict=row.get('comparison') == '<', reason=row.get('note', ''))


def _step_extrema(response, dc, port_voltages, case_currents, rated_currents):
    """Apply each 10↔90% rated load step and shared simultaneous step when modeled."""
    inputs = len(rated_currents)
    extrema = np.full((len(port_voltages), 3), (np.inf, -np.inf, 0.))
    excitations = np.eye(inputs)
    if inputs > 1:
        excitations = np.vstack((excitations, np.ones(inputs)))
    for active in excitations:
        pair_lows = np.full(len(port_voltages), np.inf)
        pair_highs = np.full(len(port_voltages), -np.inf)
        for start, stop in ((.1, .9), (.9, .1)):
            baseline = port_voltages + dc @ (active*(start*rated_currents - case_currents))
            increment = active * (stop-start) * rated_currents
            trace = baseline + response @ increment
            final = baseline + dc @ increment
            low = np.minimum(np.minimum(trace.min(axis=0), baseline), final)
            high = np.maximum(np.maximum(trace.max(axis=0), baseline), final)
            pair_lows = np.minimum(pair_lows, low)
            pair_highs = np.maximum(pair_highs, high)
        extrema[:, 0] = np.minimum(extrema[:, 0], pair_lows)
        extrema[:, 1] = np.maximum(extrema[:, 1], pair_highs)
        extrema[:, 2] = np.maximum(extrema[:, 2], pair_highs-pair_lows)
    return [tuple(row) if np.all(np.isfinite(row)) else None for row in extrema]


def _transient_extrema(snapshot, rails, context):
    loop = snapshot['res'].get('loop') or {}
    step = loop.get('load_step') or {}
    missing = [None] * len(rails)
    rated_loads = context.get('rated_loads_W')
    rated_voltages = context.get('rated_voltages_V')
    if rated_loads is None or rated_voltages is None:
        specs = snapshot['op'].get('outputs') or [snapshot['p']]
        rated_loads = [rail.get('P_out') for rail in specs]
        rated_voltages = [rail.get('V_out') for rail in specs]
    powers = np.asarray(rated_loads, dtype=float)
    rated_abs = np.abs(np.asarray(rated_voltages, dtype=float))
    if (powers.shape != (len(rails),) or rated_abs.shape != powers.shape
            or not (np.all(np.isfinite(powers)) and np.all(powers >= 0) and np.any(powers > 0)
                    and np.all(np.isfinite(rated_abs)) and np.all(rated_abs > 0))):
        return missing, '缺少每路额定输出电压或额定负载电流。'
    rated = powers/rated_abs
    models = snapshot.get('models')
    full = getattr(models[0], '_multi_output_system', None) if models else None
    if full is not None and full.noutputs == len(rails) and full.ninputs == len(rails)+1:
        import control as ct
        from loop_load_step import _step_samples, closed_loop_load_ports

        feedback = int(loop.get('model', {}).get('feedback_output', snapshot['p'].get('feedback_output', 1))) - 1
        operating_volts = np.asarray([rail.get('V_out') for rail in rails], dtype=float)
        operating_currents = np.asarray([rail.get('I_out') for rail in rails], dtype=float)
        try:
            _, response, dc = _step_samples(*closed_loop_load_ports(full, ct.ss(models[1]), feedback),
                                            snapshot['op']['f_sw'])
        except (ValueError, np.linalg.LinAlgError) as exc:
            return missing, str(exc)
        return _step_extrema(response, dc, operating_volts, operating_currents, rated), (
            '各路负载分别及同时施加额定电流的 10%↔90% 阶跃。沿用工作点的低频线性模型。')
    if not step.get('available'):
        return missing, step.get('reason') or snapshot.get('loop_error') or '该工况无闭环端口负载模型。'
    index = int(step['feedback_output']) - 1
    delta = step['current_high_A'] - step['current_low_A']
    if not 0 <= index < len(rails) or delta <= 0 or rated[index] <= 0:
        return missing, '反馈路或负载阶跃电流无效。'
    response = np.asarray(step['rise_delta_V'], dtype=float).reshape(-1, 1, 1)/delta
    rise = step['rise']
    dc = np.asarray([[(rise['final_voltage_V'] - rise['start_voltage_V'])/delta]])
    missing[index] = _step_extrema(response, dc, np.asarray([step['output_voltage_V']]),
                                   np.asarray([step['rated_current_A']]), rated[[index]])[0]
    return missing, ('10%↔90% 双向额定电流阶跃；沿用当前低频线性模型。' if len(rails) == 1 else
                     '当前低频模型只提供主反馈路的负载动态，其他输出暂无独立端口响应。')


def measurements(snapshot, external_limits, *, context=None):
    """Produce ratings and four external metrics with explicit missing coverage."""
    results = {}

    def add(key, name, unit, direction, value, limit, *, group='external', strict=False, complete=True, reason=''):
        results[key] = dict(id=key, name=name, unit=unit, direction=direction,
                            value=_number(value), limit=_number(limit), strict=strict,
                            group=group, complete=complete, reason=reason)

    _component_measurements(snapshot, 'components', add)
    op, res = snapshot['op'], snapshot['res']
    rails = op.get('output_ops') or [op]
    outputs = res.get('outputs') or []
    waveform = res.get('wf') or {}
    waves = waveform.get('outputs') or [waveform]
    transients, transient_scope = _transient_extrema(snapshot, rails, context or {})
    polarity = -1. if snapshot['p'].get('topology') == 'BUCK-BOOST' else 1.
    for index, (rail, transient) in enumerate(zip(rails, transients), 1):
        limits = external_limits['outputs'][str(index)]
        wave = waves[index-1] if index <= len(waves) else {}
        point = outputs[index-1] if index <= len(outputs) else {}
        ripple = wave.get('ripple_pp', point.get('ripple_pp'))
        add(f'out{index}_ripple', f'OUT{index} 稳态输出纹波 Vpp', 'V', 'max', ripple, limits['ripple_pp'],
            reason='采用设计计算的低频纹波峰峰值。')
        add(f'out{index}_transient', f'OUT{index} 双向负载阶跃 Vpp', 'V', 'max',
            transient[2] if transient else None, limits['transient_pp'],
            reason=transient_scope + 'Vpp 取升载与降载整对波形的最高值减最低值。')
        voltage = _number(rail.get('V_out'))
        ripple_trace = np.asarray(wave.get('vout_ripple', ()), dtype=float)
        ripple_available = bool(ripple_trace.size and np.all(np.isfinite(ripple_trace)))
        low, high = voltage, voltage
        if voltage is not None:
            if transient:
                low, high = min(low, transient[0]), max(high, transient[1])
            if ripple_available:
                low += float(np.min(ripple_trace))
                high += float(np.max(ripple_trace))
            low, high = sorted((polarity*low, polarity*high))
        coverage = transient is not None and ripple_available
        reason = ('取各已建模稳态和阶跃电压极值，并叠加本工况低频纹波包络。' if coverage else
                  '当前仅覆盖已取得的端口电压和纹波，完整的阶跃/纹波极值仍待补。')
        add(f'out{index}_voltage_low', f'OUT{index} 端口电压最小值', 'V', 'min', low,
            limits['voltage_min'], complete=coverage, reason=reason)
        add(f'out{index}_voltage_high', f'OUT{index} 端口电压最大值', 'V', 'max', high,
            limits['voltage_max'], complete=coverage, reason=reason)
    loop = res.get('loop') or {}
    add('phase_margin', '最小相位裕度', 'deg', 'min', loop.get('min_pm'), external_limits['phase_margin'], strict=True,
        reason=snapshot.get('loop_error') or ('相位裕度取当前模型全部 0 dB 穿越的最小值。' if _number(loop.get('min_pm')) is not None
                                            else '当前模型相位裕度未定义。'))
    return results
