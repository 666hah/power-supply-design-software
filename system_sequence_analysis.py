"""Full-RAW startup/shutdown observations for a composed switching experiment.

These statistics describe the supplied transient, not hardware qualification.
Plot sampling is separate: no peak, event count or threshold result is computed
from the at-most-2400-point display waveforms. No simulator is launched here.
"""
from __future__ import annotations

import math
import numpy as np

from spice_runtime import TransientRaw

_CHUNK = 250_000
_EVENT_LIMIT = 10_000
_FORWARD_DISPLAY_A = .001


def _value(time, values, when):
    right = int(np.clip(np.searchsorted(time, when, side='right'), 1, len(time) - 1))
    left = right - 1
    width = float(time[right] - time[left])
    fraction = min(1., max(0., (when - float(time[left])) / width)) if width > 0 else 0.
    return float(values[left] + (values[right] - values[left]) * fraction)


def _stats(time, values, sign=1.):
    low, high, low_index, high_index = math.inf, -math.inf, 0, 0
    for start in range(0, len(time), _CHUNK):
        chunk = values[start:start + _CHUNK] * sign
        a, b = int(np.argmin(chunk)), int(np.argmax(chunk))
        if chunk[a] < low:
            low, low_index = float(chunk[a]), start + a
        if chunk[b] > high:
            high, high_index = float(chunk[b]), start + b
    return dict(minimum=low, maximum=high, minimum_s=float(time[low_index]),
                maximum_s=float(time[high_index]), final=float(values[-1]) * sign)


def _power_stats(time, voltage, current, sign=1.):
    peak, peak_index, energy = -math.inf, 0, 0.
    for start in range(0, len(time), _CHUNK):
        stop = min(len(time), start + _CHUNK)
        # One shared boundary integrates every interval exactly once.
        begin = max(0, start - 1)
        power = voltage[begin:stop].astype(float) * current[begin:stop] * sign
        index = int(np.argmax(power))
        if power[index] > peak:
            peak, peak_index = float(power[index]), begin + index
        if len(power) > 1:
            energy += float(np.trapezoid(power, time[begin:stop]))
    return dict(peak_W=peak, peak_s=float(time[peak_index]), energy_J=energy)


def _first_threshold(time, values, threshold, *, below=False, start=None):
    begin = 0 if start is None else int(np.searchsorted(time, start, side='left'))
    if begin >= len(time):
        return None
    if start is not None:
        at_start = _value(time, values, start)
        if (at_start <= threshold) if below else (at_start >= threshold):
            return float(start)
    for offset in range(begin, len(time), _CHUNK):
        chunk = values[offset:offset + _CHUNK]
        hits = np.flatnonzero(chunk <= threshold if below else chunk >= threshold)
        if not len(hits):
            continue
        index = offset + int(hits[0])
        if index == 0:
            return float(time[0])
        left, right = float(values[index - 1]), float(values[index])
        fraction = (threshold - left) / (right - left) if right != left else 1.
        when = float(time[index - 1] + np.clip(fraction, 0., 1.) * (time[index] - time[index - 1]))
        return max(float(start), when) if start is not None else when
    return None


def _forward_window(time, values, threshold=_FORWARD_DISPLAY_A):
    """First/last positive-current crossings, not a claim of continuous flow."""
    first, last = None, None
    for start in range(0, len(time), _CHUNK):
        hits = np.flatnonzero(values[start:start + _CHUNK] > threshold)
        if len(hits):
            if first is None:
                first = start + int(hits[0])
            last = start + int(hits[-1])
    if first is None:
        return None, None

    def crossing(left, right):
        a, b = float(values[left]), float(values[right])
        fraction = np.clip((threshold - a) / (b - a), 0., 1.) if b != a else 1.
        return float(time[left] + fraction * (time[right] - time[left]))

    begin = float(time[0]) if first == 0 else crossing(first - 1, first)
    end = float(time[-1]) if last == len(time) - 1 else crossing(last, last + 1)
    return begin, end


def _high_duration(time, values, threshold=.5):
    """Duration above a threshold using every interval, including chunk edges."""
    if values is None:
        return None
    duration = 0.
    for start in range(1, len(time), _CHUNK):
        stop = min(len(time), start + _CHUNK)
        a, b = values[start - 1:stop - 1], values[start:stop]
        high_a, high_b = a > threshold, b > threshold
        crossing = high_a != high_b
        fraction = np.divide(threshold - a, b - a,
                             out=np.zeros_like(a, dtype=float), where=crossing)
        high_part = np.where(crossing, np.where(high_a, fraction, 1. - fraction), high_a)
        duration += float(np.sum(np.diff(time[start - 1:stop]) * np.clip(high_part, 0., 1.)))
    return duration


class _Observations:
    def __init__(self, raw, manifest):
        self.raw, self.manifest = raw, manifest
        self.time = np.asarray(raw.time)
        self.signals, self.missing, self.required_missing = {}, set(), set()
        self.events, self.omitted_events = [], 0
        self.limitations = [
            'completed 仅表示本次 RAW 与分析完成，不代表启动、保护或实物方案通过。',
            '所有峰值、事件和残压使用完整 RAW；显示波形独立插值，最多2400点。',
            '周期限流与 FAULT 分开统计；FAULT=0 不能证明未触发逐周期限流。',
            '源保护及负载阶段事件按完整RAW离散采样识别，时刻在相邻点间插值；极短未采到事件不可排除，计数为可观察下界。',
        ]

    def signal(self, probe, *, required=False):
        if not isinstance(probe, str) or not probe:
            if required:
                self.required_missing.add('未配置必要探针')
            return None
        key = probe.casefold()
        if key in self.signals:
            return self.signals[key]
        if key in self.missing:
            if required:
                self.required_missing.add(probe)
            return None
        try:
            values = np.asarray(self.raw.trace(probe))
            if values.ndim != 1 or len(values) != len(self.time):
                raise ValueError('trace length')
            for start in range(0, len(values), _CHUNK):
                if not np.all(np.isfinite(values[start:start + _CHUNK])):
                    raise ValueError('non-finite trace')
        except (KeyError, IndexError, ValueError, TypeError):
            self.missing.add(key)
            if required:
                self.required_missing.add(probe)
            return None
        self.signals[key] = values
        return values

    def event(self, identity, kind, when, **extra):
        if len(self.events) < _EVENT_LIMIT:
            self.events.append(dict(id=identity, type=kind, time_s=float(when), **extra))
        else:
            self.omitted_events += 1

    def transitions(self, identity, kind, values, threshold=.5):
        if values is None:
            return dict(on_count=None, off_count=None, first_on_s=None, first_off_s=None,
                        last_on_s=None, last_off_s=None, final_on=None, active_time_s=None)
        result = dict(on_count=0, off_count=0, first_on_s=None, first_off_s=None,
                      last_on_s=None, last_off_s=None, final_on=bool(values[-1] > threshold),
                      active_time_s=_high_duration(self.time, values, threshold))
        previous = False
        for start in range(0, len(values), _CHUNK):
            chunk = values[start:start + _CHUNK]
            high = chunk > threshold
            before = np.r_[previous, high[:-1]]
            for relative in np.flatnonzero(high != before):
                index = start + int(relative)
                on = bool(high[relative])
                when = float(self.time[index])
                if index:
                    a, b = float(values[index - 1]), float(values[index])
                    fraction = np.clip((threshold - a) / (b - a), 0., 1.) if b != a else 1.
                    when = float(self.time[index - 1] + fraction * (self.time[index] - self.time[index - 1]))
                suffix = 'on' if on else 'off'
                result[suffix + '_count'] += 1
                if result['first_' + suffix + '_s'] is None:
                    result['first_' + suffix + '_s'] = when
                result['last_' + suffix + '_s'] = when
                self.event(identity, kind + '_' + suffix, when)
            previous = bool(high[-1])
        return result

    def load_stages(self, identity, row):
        """Discrete stage observations; never infer stages from chart samples."""
        plan = row.get('config', {}).get('stages', [])
        values = self.signal(row.get('stage_probe'), required=bool(plan))
        age = self.signal(row.get('age_probe'), required=bool(plan))
        records = [dict(index=i, name=s['name'], after_s=s['after_s'], mode=s['mode'],
                        power_W=s['power_W'], ramp_s=s['ramp_s'], entry_count=None,
                        first_entry_s=None, last_entry_s=None, first_ready_age_s=None)
                   for i, s in enumerate(plan, 1)]
        answer = dict(observed=False, stages=records, final_index=None,
                      reset_count=None, restart_count=None, skipped_stage_count=None)
        if not plan or values is None or age is None:
            return answer
        # Intermediate values during solver-resolved logic edges are rounded;
        # an index outside the declared stage set is corrupt evidence.
        if np.any(values < -.01) or np.any(values > len(plan) + .01):
            self.required_missing.add(identity + ':阶段索引超出声明范围')
            return answer
        for record in records:
            record['entry_count'] = 0
        previous, resets, first_entries, skipped = 0, 0, 0, 0
        for start in range(0, len(values), _CHUNK):
            indices = np.floor(values[start:start + _CHUNK] + .5).astype(int)
            before = np.r_[previous, indices[:-1]]
            for relative in np.flatnonzero(indices != before):
                index = start + int(relative)
                stage, old = int(indices[relative]), int(before[relative])
                when = float(self.time[index])
                if index:
                    boundary = (old + stage) / 2.
                    a, b = float(values[index - 1]), float(values[index])
                    fraction = np.clip((boundary-a)/(b-a), 0., 1.) if b != a else 1.
                    when = float(self.time[index-1] + fraction*(self.time[index]-self.time[index-1]))
                if stage == 0:
                    resets += 1
                    self.event(identity, 'load_stage_reset', when, previous_index=old,
                               previous_name=plan[old-1]['name'])
                else:
                    record = records[stage-1]
                    record['entry_count'] += 1
                    record['last_entry_s'] = when
                    if record['first_entry_s'] is None:
                        record['first_entry_s'] = when
                        record['first_ready_age_s'] = _value(self.time, age, when)
                    if old == 0:
                        first_entries += 1
                    if stage > old + 1:
                        skipped += stage-old-1
                    self.event(identity, 'load_stage_enter', when, stage_index=stage,
                               stage_name=record['name'], configured_after_s=record['after_s'],
                               ready_age_s=_value(self.time, age, when))
            previous = int(indices[-1])
        answer.update(observed=True, final_index=previous, reset_count=resets,
                      restart_count=max(0, first_entries-1), skipped_stage_count=skipped)
        if skipped:
            self.limitations.append(identity+'阶段探针跳过部分索引；只报告实际观察到的阶段，不能补造未采到的进入时刻。')
        return answer

    def plots(self):
        count = min(2400, len(self.time))
        axis = np.linspace(float(self.time[0]), float(self.time[-1]), count)
        neighbours = np.searchsorted(self.time, axis, side='right')
        right = np.clip(neighbours, 0, len(self.time) - 1)
        left = np.clip(neighbours - 1, 0, len(self.time) - 1)
        width = self.time[right] - self.time[left]
        fraction = np.divide(axis - self.time[left], width, out=np.zeros_like(axis), where=width > 0)
        fraction = np.clip(fraction, 0., 1.)
        result = dict(time=axis.tolist())
        for probe, values in self.signals.items():
            a, b = values[left].astype(float), values[right].astype(float)
            result[probe] = (a + (b - a) * fraction).tolist()
        return result


def _cycle_limit(observed, probes, compiled, filtered, gate, sense):
    """Positive sampled evidence only; absence is never a proof of no limiting."""
    unknown = dict(hit=None, observed_cycle_count=None, first_observed_s=None,
                   scope='conservative sampled lower-bound; no negative pass conclusion')
    thresholds = compiled.get('sequence_unit', {}).get('thresholds', {})
    values = compiled.get('resolved_controller', {})
    controller = probes.get('controller', {})
    dynamic = observed.signal(controller.get('cycle_limit'))
    constant = None
    if dynamic is None and compiled.get('topology') == 'QR-FLYBACK':
        constant = thresholds.get('cycle_cs_ceiling_v')
    if filtered is None or gate is None or sense is None or (dynamic is None and not constant):
        return dict(unknown, reason='缺少滤波CS、动态/明确常数限流或实际门极探针，周期限流保持未知。')
    gate_threshold = thresholds.get('gate_on_v')
    blank = thresholds.get('cycle_blank_s')
    minimum_on = thresholds.get('minimum_on_s')
    if gate_threshold is None or blank is None or minimum_on is None:
        return dict(unknown, reason='缺少实际门极阈值或消隐/最小导通信息，周期限流保持未知。')
    count, first, last_counted, pulse_id, previous_high, last_rise = 0, None, -1, 0, False, -math.inf
    time = observed.time
    for start in range(0, len(time), _CHUNK):
        stop = min(len(time), start + _CHUNK)
        high = gate[start:stop] - sense[start:stop] > gate_threshold
        rises = high & ~np.r_[previous_high, high[:-1]]
        ids = pulse_id + np.cumsum(rises)
        rise_time = np.maximum.accumulate(np.where(rises, time[start:stop], last_rise))
        limit = dynamic[start:stop] if dynamic is not None else float(constant)
        eligible = high & (time[start:stop] - rise_time >= max(blank, minimum_on))
        hits = np.flatnonzero(eligible & (filtered[start:stop] >= limit))
        if len(hits):
            unique = np.unique(ids[hits])
            count += int(np.count_nonzero(unique != last_counted))
            last_counted = int(unique[-1])
            if first is None:
                first = float(time[start + int(hits[0])])
        pulse_id = int(ids[-1])
        previous_high = bool(high[-1])
        last_rise = float(rise_time[-1])
    reason = ('在门极有效且消隐后观察到滤波CS达到限流门限；次数为可观察下界。' if count else
              '完整RAW未取得消隐后达到门限的采样证据；离散采样不能证明未发生逐周期限流。')
    if values.get('LIMIT_RAMP'):
        reason += ' LM5022斜坡参与限流，未加入斜坡的比较只给正向证据下界。'
    return dict(unknown, hit=True if count else None, observed_cycle_count=count,
                first_observed_s=first, reason=reason)


def _cot_phase_limits(observed, identity, probes, compiled):
    """Read dedicated COT current/event probes without inventing a CS resistor."""
    threshold = compiled.get('sequence_unit', {}).get('thresholds', {}).get('phase_current_limit_A')
    configured = isinstance(threshold, (int, float)) and threshold > 0
    count = int((compiled.get('cot') or {}).get('phases') or
                (compiled.get('hardware') or {}).get('phases') or len(probes.get('cot_phase_limits', {})))
    phases, first, total = [], None, 0
    complete = bool(count)
    for i in range(1,count+1):
        key = f'phase{i}'
        current = observed.signal((probes.get('currents') or {}).get(f'L{i}'))
        sensed = observed.signal((probes.get('cot_phase_sensed') or {}).get(key))
        state = observed.signal((probes.get('cot_phase_limits') or {}).get(key))
        event = observed.transitions(identity, 'cot_'+key+'_limit', state)
        current_stat = _stats(observed.time,current) if current is not None else None
        sense_stat = _stats(observed.time,sensed) if sensed is not None else None
        phase_complete = current is not None and sensed is not None and state is not None
        complete &= phase_complete
        if event['on_count']:
            total += event['on_count']
            first = event['first_on_s'] if first is None else min(first,event['first_on_s'])
        phases.append(dict(phase=i,observed=phase_complete,
                           current_peak_A=current_stat['maximum'] if current_stat else None,
                           current_peak_s=current_stat['maximum_s'] if current_stat else None,
                           current_min_A=current_stat['minimum'] if current_stat else None,
                           sampled_peak_A=sense_stat['maximum'] if sense_stat else None,
                           threshold_A=threshold if configured else None,
                           sample_margin_A=threshold-sense_stat['maximum'] if configured and sense_stat else None,
                           limit_events=event))
    controller_states={name:observed.transitions(identity,'cot_'+name,
                        observed.signal((probes.get('controller') or {}).get(name)))
                       for name in ('run','uvlo','ovp')}
    return dict(kind='cot_phase_current',phase_current_limit_A=threshold if configured else None,
                phases=phases,observations_complete=complete,limit_configured=configured,
                controller_states=controller_states,
                cycle_limit=dict(hit=True if total else False if complete and configured else None,
                    observed_cycle_count=total if complete else None,first_observed_s=first,
                    observed_phase_event_count=total,
                    reason='逐相限流状态直接取控制器事件探针，计数为完整 RAW 可观察下界；未配置门限或缺失探针时保持未知。',
                    scope='dedicated COT phase-event probes; current monitor 1 V/A'),
                sense_definition='各相电感电流和含增益/偏置的采样电流分别记录；行为探针为 1 V/A，未设置虚拟采样电阻。')


def _unit(observed, identity, row):
    probes = row.get('probes', {})
    compiled = row.get('compiled_manifest', {})
    thresholds = compiled.get('sequence_unit', {}).get('thresholds', {})
    resolved = compiled.get('resolved_controller', {})
    en = observed.signal(row.get('en_probe') or probes.get('en'), required=True)
    enable = observed.transitions(identity, 'enable', en)
    uvlo = observed.signal(row.get('uvlo_probe'))
    uvlo_state = observed.transitions(identity, 'input_uvlo_ready', uvlo)
    current = observed.signal(row.get('input_current_probe'), required=True)
    inputbus = observed.signal(probes.get('inputbus') or probes.get('input'), required=True)
    raw_cs = observed.signal(probes.get('sense'))
    filtered = observed.signal(probes.get('controller', {}).get('filtered_cs') or probes.get('filtered_cs'))
    gate = observed.signal(probes.get('gate'))
    fault = observed.signal(probes.get('fault'))
    fault_events = observed.transitions(identity, 'fault', fault)
    cs_peak = _stats(observed.time, raw_cs) if raw_cs is not None else None
    filtered_peak = _stats(observed.time, filtered) if filtered is not None else None
    sense_resistance = resolved.get('RSENSE', thresholds.get('sense_resistor_ohm'))
    ceiling = thresholds.get('cycle_cs_ceiling_v')
    equivalent = (cs_peak['maximum'] / sense_resistance if cs_peak is not None and
                  isinstance(sense_resistance, (float, int)) and sense_resistance > 0 else None)
    cot = _cot_phase_limits(observed,identity,probes,compiled) if probes.get('cot_phase_limits') else None
    limit = cot['cycle_limit'] if cot else _cycle_limit(observed, probes, compiled, filtered, gate, raw_cs)
    if limit['hit']:
        observed.event(identity, 'cycle_limit_observed', limit['first_observed_s'],
                       observed_cycle_count=limit['observed_cycle_count'])
    ocp = dict(raw_cs_peak_V=None if cs_peak is None else cs_peak['maximum'],
               raw_cs_peak_s=None if cs_peak is None else cs_peak['maximum_s'],
               filtered_cs_peak_V=None if filtered_peak is None else filtered_peak['maximum'],
               filtered_cs_peak_s=None if filtered_peak is None else filtered_peak['maximum_s'],
               sense_resistor_ohm=sense_resistance, equivalent_sense_current_peak_A=equivalent,
               cycle_ceiling_V=ceiling,
               raw_ceiling_margin_V=None if cs_peak is None or ceiling is None else ceiling - cs_peak['maximum'],
               filtered_ceiling_margin_V=None if filtered_peak is None or ceiling is None else ceiling - filtered_peak['maximum'],
               cycle_limit=limit, fault_observed=None if fault is None else bool(fault_events['on_count']),
               fault_events=fault_events, protection_passed=None)
    if cot:
        ocp.update(cot)
    outputs = []
    shutdown = enable['last_off_s'] if enable['final_on'] is False else None
    for output in row.get('outputs', []):
        voltage = observed.signal(output.get('voltage_probe'), required=True)
        draw = observed.signal(output.get('current_probe'), required=True)
        data = dict(id=output.get('id'), name=output.get('name'), reference_V=output.get('reference_V'),
                    first_90pct_s=None, startup_90pct_delay_s=None, voltage_peak_V=None,
                    voltage_peak_s=None, voltage_final_V=None, residual_V=None,
                    shutdown_observation_s=None, decay_10pct_s=None)
        if voltage is not None:
            stats = _stats(observed.time, voltage)
            data.update(voltage_peak_V=stats['maximum'], voltage_peak_s=stats['maximum_s'],
                        voltage_min_V=stats['minimum'], voltage_final_V=stats['final'])
            reference = output.get('reference_V')
            if isinstance(reference, (float, int)) and reference > 0:
                reached = _first_threshold(observed.time, voltage, .9 * reference)
                data['first_90pct_s'] = reached
                if reached is not None:
                    observed.event(identity, 'output_90pct', reached, output=output.get('id'))
                    if enable['first_on_s'] is not None:
                        data['startup_90pct_delay_s'] = reached - enable['first_on_s']
                        data['precharged_before_enable'] = reached < enable['first_on_s']
                if shutdown is not None:
                    data['decay_10pct_s'] = _first_threshold(observed.time, voltage, .1 * reference,
                                                           below=True, start=shutdown)
            if shutdown is not None:
                data.update(residual_V=stats['final'], voltage_at_disable_V=_value(observed.time, voltage, shutdown),
                            shutdown_observation_s=float(observed.time[-1]) - shutdown)
        if draw is not None:
            data['output_current_peak_A'] = _stats(observed.time, draw)['maximum']
        outputs.append(data)
    branch = {}
    for key, probe in probes.get('currents', {}).items():
        values = observed.signal(probe)
        if values is not None:
            stats = _stats(observed.time, values)
            branch[key] = dict(peak_A=stats['maximum'], peak_s=stats['maximum_s'], minimum_A=stats['minimum'])
    for value in probes.values():
        if isinstance(value, str):
            observed.signal(value)
        elif isinstance(value, dict):
            for probe in value.values():
                if isinstance(probe, str):
                    observed.signal(probe)
    current_stats = None if current is None else _stats(observed.time, current)
    return dict(id=identity, topology=compiled.get('topology'), enable=enable, input_uvlo_ready=uvlo_state,
                input_uvlo_configured=row.get('config', {}).get('vin_on_V') is not None,
                input_current_peak_A=None if current_stats is None else current_stats['maximum'],
                input_current_peak_s=None if current_stats is None else current_stats['maximum_s'],
                input_voltage_min_V=None if inputbus is None else _stats(observed.time, inputbus)['minimum'],
                input_voltage_peak_V=None if inputbus is None else _stats(observed.time, inputbus)['maximum'],
                outputs=outputs, ocp=ocp, branch_current_peaks=branch)


def _analyze(raw, manifest):
    observed = _Observations(raw, manifest)
    time = observed.time
    if len(time) < 2 or time[-1] <= time[0]:
        raise ValueError('RAW时间轴无效或不足两个有效时间点')
    for start in range(0, len(time), _CHUNK):
        chunk = time[max(0, start - 1):start + _CHUNK]
        if not np.all(np.isfinite(chunk)) or np.any(np.diff(chunk) < 0):
            raise ValueError('RAW时间轴无效或不足两个有效时间点')
    sources, units, loads, ports, connections = [], [], [], [], []
    for identity, row in manifest.get('sources', {}).items():
        voltage = observed.signal(row.get('voltage_probe'), required=True)
        current = observed.signal(row.get('current_probe'), required=True)
        stats = None if current is None else _stats(time, current, -1.)
        config = row.get('config', {})
        capacitance = config.get('output_capacitance_F', 0.)
        port_probe = row.get('port_current_probe')
        derived_port = not port_probe and row.get('port_current_derivation') == 'source-minus-capacitor'
        capacitor_current = observed.signal(row.get('output_capacitor_current_probe'), required=derived_port) if row.get('output_capacitor_current_probe') or derived_port else None
        if port_probe:
            port_current = observed.signal(port_probe, required=True)
            port_sign = 1.
        elif derived_port:
            # RAW ordinates are float32. Promote before KCL subtraction so
            # derived peaks retain the precision of both original probes.
            port_current = None if current is None or capacitor_current is None else -np.asarray(current,dtype=float)-np.asarray(capacitor_current,dtype=float)
            port_sign = 1.
        elif capacitance > 0:
            # Capacitive sources need a direct sensor or explicit KCL contract.
            # Only legacy sources without an energy store may reuse I(Vsource).
            port_current = observed.signal(None, required=True)
            port_sign = 1.
        else:
            port_current, port_sign = current, -1.
        port_stats = None if port_current is None else _stats(time, port_current, port_sign)
        result = dict(id=identity, capacity_W=row.get('capacity_W'),
                      supply_current_peak_A=None if stats is None else max(0., stats['maximum']),
                      supply_current_peak_s=None if stats is None else stats['maximum_s'],
                      reverse_current_peak_A=None if stats is None else max(0., -stats['minimum']),
                      limiter_supply_current_peak_A=None if stats is None else max(0., stats['maximum']),
                      limiter_supply_current_peak_s=None if stats is None else stats['maximum_s'],
                      port_supply_current_peak_A=None if port_stats is None else max(0., port_stats['maximum']),
                      port_supply_current_peak_s=None if port_stats is None else port_stats['maximum_s'],
                      port_reverse_current_peak_A=None if port_stats is None else max(0., -port_stats['minimum']),
                      separate_port_current_probe=bool(port_probe),
                      derived_port_current=derived_port,
                      port_current_method='direct-probe' if port_probe else 'source-minus-capacitor' if derived_port else 'legacy-internal-probe' if capacitance == 0 else 'unavailable',
                      output_capacitance_F=capacitance,output_esr_ohm=config.get('output_esr_ohm',0.),
                      voltage_peak_V=None if voltage is None else _stats(time, voltage)['maximum'],
                      voltage_final_V=None if voltage is None else float(voltage[-1]))
        if voltage is not None and current is not None:
            result.update(_power_stats(time, voltage, current, -1.))
        if voltage is not None and port_current is not None:
            result['port_power'] = _power_stats(time, voltage, port_current, port_sign)
        # Capacitor discharge may exceed the regulator current ceiling at the
        # external port. Only the internal probe is a limiter/OCP comparison.
        current_limit = config.get('current_limit_A')
        result['current_limit_A'] = current_limit
        result['current_limit_exceeded'] = None if stats is None or current_limit is None else stats['maximum'] > current_limit
        result['first_current_limit_exceeded_s'] = None
        if result['current_limit_exceeded']:
            first_exceeded = _first_threshold(time, current, -current_limit, below=True)
            result['first_current_limit_exceeded_s'] = first_exceeded
            observed.event(identity, 'source_current_limit_exceeded', first_exceeded, peak_A=stats['maximum'])
        mode = row.get('config', {}).get('protection_mode', 'monitor')
        active = mode != 'monitor'
        limit_trace = observed.signal(row.get('limit_active_probe'), required=active)
        fault_trace = observed.signal(row.get('fault_probe'), required=active)
        result.update(protection_mode=mode, protection_model_executed=active,
                      protection_observations_complete=active and limit_trace is not None and fault_trace is not None,
                      limit_state=observed.transitions(identity, 'source_limiting', limit_trace),
                      fault_state=observed.transitions(identity, 'source_fault', fault_trace),
                      protection_passed=None)
        if active:
            observed.limitations.append(identity+'源限流/故障事件来自声明的行为模型状态；阈值、折返及重试需按真实电源验证，不能自动判硬件保护合格。')
        if capacitance > 0:
            observed.limitations.append(identity+'源端输出电容位于限流器之后；端口电流包含电容放电，可能瞬间超过内部限流值。内部供流与端口供流分别统计，只用内部电流检查所配限流门限。休眠时电容仍可供电，不能把端口有电流误判保护失效。')
        if derived_port:
            observed.limitations.append(identity+'源端口电流按冻结网表明确声明的KCL关系，由完整RAW的 −I(内部源)−I(源端电容) 求得；未额外串联理想电压源传感器。此关系是计算定义，不作为独立电流守恒验证。')
        for field in ('output_capacitor_current_probe',):
            if row.get(field):observed.signal(row[field],required=True)
        sources.append(result)
    for identity, row in manifest.get('units', {}).items():
        units.append(_unit(observed, identity, row))
    for identity, row in manifest.get('loads', {}).items():
        voltage = observed.signal(row.get('voltage_probe'), required=True)
        current = observed.signal(row.get('current_probe'), required=True)
        state = observed.signal(row.get('state_probe'), required=True)
        result = dict(id=identity, mode=row.get('config', {}).get('mode'),
                      state=observed.transitions(identity, 'load_active', state, threshold=.001),
                      state_threshold=.001, first_power_s=None,
                      current_peak_A=None if current is None else _stats(time, current)['maximum'])
        staged = bool(row.get('config', {}).get('stages'))
        ready = observed.signal(row.get('ready_probe'), required=staged or bool(row.get('ready_probe')))
        active_current = observed.signal(row.get('active_current_probe'), required=staged or bool(row.get('active_current_probe')))
        result.update(ready=observed.transitions(identity, 'load_ready', ready),
                      stage_observations=observed.load_stages(identity, row),
                      active_current_peak_A=None if active_current is None else _stats(time, active_current)['maximum'],
                      active_current_peak_s=None if active_current is None else _stats(time, active_current)['maximum_s'])
        if voltage is not None and active_current is not None:
            result['active_power'] = _power_stats(time, voltage, active_current)
        if voltage is not None and current is not None:
            result.update(_power_stats(time, voltage, current))
            power_threshold = max(1e-9, row.get('config', {}).get('power_W', 0.) * 1e-6)
            result['power_detection_threshold_W'] = power_threshold
            for start in range(0, len(time), _CHUNK):
                power = voltage[start:start + _CHUNK].astype(float) * current[start:start + _CHUNK]
                hits = np.flatnonzero(power > power_threshold)
                if len(hits):
                    result['first_power_s'] = float(time[start + int(hits[0])])
                    observed.event(identity, 'load_power_observed', result['first_power_s'], threshold_W=power_threshold)
                    break
        loads.append(result)
    # These manifest groups are optional for older exports. Once an entry is
    # declared, absent data cannot masquerade as a zero or a complete result.
    for identity, row in manifest.get('ports', {}).items():
        voltage = observed.signal(row.get('voltage_probe'), required=True)
        stats = None if voltage is None else _stats(time, voltage)
        ports.append(dict(id=identity, name=row.get('name'), observed=stats is not None,
                          voltage_peak_V=None if stats is None else stats['maximum'],
                          voltage_min_V=None if stats is None else stats['minimum'],
                          voltage_final_V=None if stats is None else stats['final']))
    for identity, row in manifest.get('connections', {}).items():
        current = observed.signal(row.get('current_probe'), required=True)
        stats = None if current is None else _stats(time, current)
        first, last = (None, None) if current is None else _forward_window(time, current)
        connections.append(dict(id=identity, source=row.get('source'), target=row.get('target'),
            observed=stats is not None, current_peak_A=None if stats is None else max(0., stats['maximum']),
            reverse_current_peak_A=None if stats is None else max(0., -stats['minimum']),
            first_forward_s=first, last_forward_s=last, forward_display_threshold_A=_FORWARD_DISPLAY_A))
    if connections:
        observed.limitations.append(
            '连接正向首末时刻按1mA工程显示阈值由完整RAW取交点，不是器件导通物理门限；首末之间可能有停流或OR反复切换，不表示连续导通。')
    expected = manifest.get('settings', {}).get('stop_s')
    duration_complete = (isinstance(expected, (float, int)) and math.isfinite(expected) and expected > 0 and
                         float(time[0]) <= max(1e-12, expected * 1e-8) and
                         float(time[-1]) >= expected - max(1e-12, expected * 1e-6))
    reasons = []
    if not duration_complete:
        reasons.append('RAW未覆盖要求的完整0至stop_s区间；本次启停分析失败，已有统计仅供诊断。')
    if observed.required_missing:
        reasons.append('RAW缺少或损坏必要探针：' + '、'.join(sorted(observed.required_missing)))
    if observed.missing:
        observed.limitations.append('缺少/无效探针保持未知：' + '、'.join(sorted(observed.missing)))
    if observed.omitted_events:
        observed.limitations.append(f'事件展示上限为{_EVENT_LIMIT}条，另{observed.omitted_events}条未列出；各项事件计数仍使用完整RAW。')
    observed.events.sort(key=lambda event: event['time_s'])
    return dict(status='completed' if not reasons else 'failed', simulation_complete=duration_complete,
                analysis_complete=not reasons, failure_reasons=reasons,
                summary=dict(sources=sources, units=units, loads=loads, ports=ports, connections=connections),
                port_observations_complete=all(row['observed'] for row in ports),
                connection_observations_complete=all(row['observed'] for row in connections),
                waveforms=observed.plots(), events=observed.events, events_omitted_count=observed.omitted_events,
                limitations=observed.limitations + reasons,
                observed_start_s=float(time[0]), observed_end_s=float(time[-1]), expected_end_s=expected)


def analyze(raw_path, manifest):
    """Read one real transient RAW; return observations or an explicit failure."""
    raw = None
    try:
        raw = TransientRaw(raw_path)
        return _analyze(raw, manifest)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return dict(status='failed', simulation_complete=False, analysis_complete=False,
                    failure_reasons=[str(exc)], summary=dict(sources=[], units=[], loads=[], ports=[], connections=[]),
                    port_observations_complete=False, connection_observations_complete=False,
                    waveforms=dict(time=[]), events=[], limitations=['RAW读取或分析失败：' + str(exc)])
    finally:
        if raw is not None:
            raw.close()
