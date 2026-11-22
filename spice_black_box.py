"""Terminal measurements from original transient samples and verified study records."""
import math

import numpy as np

from loop_acceptance import MIN_PHASE_MARGIN_DEG, phase_margin_passes
from spice_analysis import minimum_phase_margin


def fra_phase_margin(probe):
    """Return the measured minimum only after FRA verification."""
    return minimum_phase_margin((probe.get('simulation') or {}).get('loop') or {}) if probe.get('available') else None


def phase_margin_conclusion(margin):
    if margin is None:
        return '待补有效裕度'
    return '通过' if phase_margin_passes(margin) else '未达标'


PHASE_MARGIN_RULE = f'相位裕度验收要求严格大于 {MIN_PHASE_MARGIN_DEG:g}°，按原始数值判定。'


def _number(value):
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _chunks(raw, rail, return_node, start, end):
    axis = raw.time
    if len(axis) < 2 or start < axis[0] or end > axis[-1]+1e-12 or end <= start:
        raise ValueError('原始记录未覆盖指定测量窗口')
    output = raw.trace(f'v(out{rail})')
    ground = raw.trace(return_node) if return_node else None
    first = max(0, int(np.searchsorted(axis, start, side='right'))-1)
    last = min(len(axis), int(np.searchsorted(axis, end, side='left'))+1)
    while first+1 < last:
        stop = min(first+65537, last)
        times = axis[first:stop]
        values = np.asarray(output[first:stop], dtype=float)
        if ground is not None:
            values = values-np.asarray(ground[first:stop], dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError('端口电压含非有限值')
        lower, upper = max(start,times[0]), min(end,times[-1])
        if upper > lower:
            inside = (times > lower) & (times < upper)
            yield (np.r_[lower, times[inside], upper],
                   np.r_[np.interp(lower,times,values), values[inside], np.interp(upper,times,values)])
        first = stop-1


def _port_window(raw, rail, return_node, start, end, reference, band):
    low, high = math.inf, -math.inf
    crossings = {0.1: None, 0.9: None}
    integral = span = 0.
    last_out = start
    initial = None
    for times, values in _chunks(raw, rail, return_node, start, end):
        if initial is None:
            initial = float(values[0])
        low, high = min(low, float(np.min(values))), max(high, float(np.max(values)))
        span += times[-1]-times[0]
        integral += np.trapezoid(values, times)
        for ratio, when in crossings.items():
            if when is not None:
                continue
            target = ratio*reference
            hit = np.flatnonzero(values >= target)
            if len(hit):
                index = int(hit[0])
                crossings[ratio] = float(times[index] if index == 0 else
                    times[index-1] + (times[index]-times[index-1])*
                    (target-values[index-1])/(values[index]-values[index-1]))
        outside = np.flatnonzero(np.abs(values-reference) > band)
        if len(outside):
            index = int(outside[-1])
            if index == len(values)-1:
                last_out = times[-1]
            else:
                edge = reference+math.copysign(band, values[index]-reference)
                last_out = times[index] + (times[index+1]-times[index]) * (
                    edge-values[index])/(values[index+1]-values[index])
    if span <= 0:
        raise ValueError('窗口中没有可积分的原始样本')
    return dict(low=low, high=high, mean=float(integral/span), last_out=float(last_out),
                t10=crossings[.1], t90=crossings[.9], initial=initial)


def full_load_ports(raw, case, *, end_s, frequency_hz, return_node, comparable, band_pct=2.):
    from isolated_outputs import output_specs

    specs = output_specs(case['p']) or [case['p']]
    rows = []
    hold = 8/frequency_hz
    for rail, spec in enumerate(specs,1):
        reference = abs(float(spec['V_out']))
        row = dict(rail=rail, reference_v=reference)
        rows.append(row)
        try:
            result = _port_window(raw,rail,return_node,float(raw.time[0]),end_s,reference,reference*band_pct/100)
            t10,t90 = result['t10'],result['t90']
            row.update(t10_s=t10, t90_s=t90, rise_s=(t90-t10 if t10 is not None and t90 is not None
                       and result['initial']<.1*reference else None), peak_v=result['high'],
                       peak_above_reference_pct=100*max(0.,result['high']-reference)/reference,
                       in_band_s=result['last_out'] if end_s-result['last_out']>=hold else None)
        except (KeyError,ValueError) as exc:
            row['error'] = str(exc)
    return dict(ports=rows, band_pct=band_pct, sustained_s=hold, steady_qualified=bool(comparable))


def measure_load_steps(raw, events, *, reference_v, frequency_hz, stop_s, return_node=None, band_pct=2.):
    rows = []
    data = dict(available=False, events=rows, band_pct=band_pct, reference_v=reference_v,
                reason='缺少两个方向的完整原始阶跃记录')
    if reference_v <= 0 or frequency_hz <= 0 or band_pct <= 0:
        return data
    previous = float(raw.time[0])
    band = reference_v*band_pct/100
    hold = 8/frequency_hz
    for index, event in enumerate(events):
        start = event['time_s']
        end = min(event.get('end_s',stop_s),events[index+1]['time_s'] if index+1<len(events) else stop_s)
        row = dict(event)
        rows.append(row)
        rail = event['rail']
        try:
            half_window = min(10/frequency_hz,(start-previous)/2,(end-start)/2)
            if half_window < 2/frequency_hz or end-start < hold:
                raise ValueError('阶跃保持时间不足以分离基线及恢复窗口')
            first = _port_window(raw,rail,return_node,start-2*half_window,start-half_window,reference_v,band)
            prior = _port_window(raw,rail,return_node,start-half_window,start,reference_v,band)
            measured = _port_window(raw,rail,return_node,start,end,reference_v,band)
            final = _port_window(raw,rail,return_node,end-half_window,end,reference_v,band)
            row.update(min_v=measured['low'], max_v=measured['high'], before_v=prior['mean'],
                       final_v=final['mean'], droop_v=max(0.,prior['mean']-measured['low']),
                       overshoot_v=max(0.,measured['high']-prior['mean']),
                       recovery_s=measured['last_out']-start if end-measured['last_out']>=hold else None,
                       stable_before=abs(prior['mean']-first['mean'])<=.0025*reference_v,
                       observed_s=end-start, hold_s=hold)
        except (KeyError,ValueError) as exc:
            row['error'] = str(exc)
        previous = start
    directions = {(r['rail'], np.sign(r['after']-r['before'])) for r in rows if 'error' not in r}
    expected = {(r['rail'],sign) for r in rows for sign in (-1,1)}
    if rows and expected == directions and not any('error' in r for r in rows):
        data['available'] = all(r['stable_before'] for r in rows)
        data['reason'] = ('双向阶跃原始波形已测量' if data['available'] else '至少一次阶跃前的两窗口均值仍有漂移')
    return data


def _fmt(value, scale=1., missing='—'):
    number = _number(value)
    return missing if number is None else f'{number*scale:.4g}'


def black_box_sections(case, settings):
    """Return (title, headings, rows, scope) sections for either Word exporter."""
    if case.get('fault_test'):
        return []
    ports = case.get('black_box') or {}
    rows = ports.get('ports') or []
    measurements = case.get('measurements') or {}
    sections = []
    def section(title, headers, values, note):
        sections.append((title,headers,values,note))
    section('开机时间与过冲', ['端口','参考 / V','首次到 90% / ms','10%–90% / ms','峰值 / V','过冲 / %','持续入带 / ms'],
        [(f"OUT{r['rail']}",_fmt(r['reference_v']),_fmt(r.get('t90_s'),1000),_fmt(r.get('rise_s'),1000),
          _fmt(r.get('peak_v')),_fmt(r.get('peak_above_reference_pct')),_fmt(r.get('in_band_s'),1000)) for r in rows],
        ('从仿真零时刻观察最大功率启动；按各路端口参考电压计上升时间及过冲，持续进入 ±'+
         _fmt(ports.get('band_pct'))+'% 观察带并保持至窗末（至少 8 个周期）。' if rows else
         '未取得可用的原始启动测量。')+' 起机以电路模型的输入与使能激励为准。')
    steady = []
    calculated = case.get('rows') or []
    for r in rows:
        rail, reference = r['rail'], r['reference_v']
        voltage = _number(measurements.get(f'out{rail}_before'))
        design = next((v.get('design') for v in calculated if v['metric'] in
                       (f'OUT{rail} 输出平均电压',f'OUT{rail} 端口平均电压')),None)
        ripple = next(((branch.get('simulation_ripple') or {}).get('pp') for branch in case.get('branches',[])
                      if branch.get('id')==rail),None)
        if case.get('phase_table') and rail==1:
            ripple = measurements.get('out1_pre_ripple')
        qualified = ports.get('steady_qualified')
        steady.append((f'OUT{rail}',_fmt(reference),_fmt(design),_fmt(voltage),
                       _fmt(100*(voltage/reference-1) if qualified and voltage is not None and reference else None),
                       _fmt(ripple,1000),'稳态' if qualified else '待稳态'))
    section('满载稳压精度与纹波',['端口','参考 / V','计算 / V','仿真 / V','相对参考 / %','纹波 / mVpp','测量窗口'],
            steady,'偏差按（稳态端口均值 − 参考）/ 参考计算。开关模型端口纹波未施加示波器带宽限制。')
    transient = case.get('load_transient') or {}
    response = transient.get('response_by_port') or {}
    feedback = transient.get('feedback_output') or case.get('feedback_output') or 1
    steps = [event for port in sorted(response,key=int) for event in response[port]] if response else transient.get('events') or []
    section('双向负载阶跃与恢复',['端口 / 跳变','阶跃前 / V','最低 / V','最高 / V','压降 / mV','过冲 / mV','入带时间 / ms'],
        [(f"OUT{r['rail']} {'激励' if r['rail']==feedback else '观测'} · {_fmt(r['before'],100)}%→{_fmt(r['after'],100)}%",_fmt(r.get('before_v')),
          _fmt(r.get('min_v')),_fmt(r.get('max_v')),_fmt(r.get('droop_v'),1000),_fmt(r.get('overshoot_v'),1000),
          _fmt(r.get('recovery_s'),1000,'未取得')) for r in steps],
        (transient.get('error') or transient.get('reason') or '未执行或未取得独立阶跃测量')+
        f'。负载只在 OUT{feedback} 跳变，其余端口保持额定负载。压降和过冲相对各路阶跃前的实测均值。恢复要求回到参考电压 ±'+_fmt(transient.get('band_pct',2))+
        '% 并持续至观察窗末（至少 8 个周期）。该带宽用于读数，不是产品验收限值。')
    loop = case.get('loop') or {}
    designed = (loop.get('design') or {}).get('loop') or {}
    simulated = (loop.get('simulation') or {}).get('loop') or {}
    measured_pm = fra_phase_margin(loop)
    loop_note = ('FRA 注入复核通过。' + PHASE_MARGIN_RULE if loop.get('available') else
                 'FRA 未确认。' + str(loop.get('error') or ('未取得有效测量' if settings.get('fra_enabled') else '未选择该项')))
    section('额定负载环路',['指标','设计计算','开关闭环 FRA'],
            [('穿越频率 / Hz',_fmt(designed.get('fc')),_fmt(simulated.get('fc'))),
             ('最小相位裕度 / °',_fmt(minimum_phase_margin(designed)),_fmt(minimum_phase_margin(simulated))),
             ('增益裕度 / dB',_fmt(designed.get('gm_db')),_fmt(simulated.get('gm_db'))),
             ('FRA 相位裕度验收','—',phase_margin_conclusion(measured_pm))],loop_note)
    cross = case.get('cross') or {}
    envelopes = cross.get('summary') or {}
    reg_rows = []
    for item in envelopes.get('simulation',[]):
        design = next((r for r in envelopes.get('design',[]) if r['id']==item['id']),{})
        rail = item['id']
        records = [r for r in cross.get('records',[]) if r.get('settled') and r.get('simulation') is not None]
        matched = any(a['V_in']==b['V_in'] and a['powers'][rail-1]==b['powers'][rail-1]
                      and a['powers']!=b['powers'] for i,a in enumerate(records) for b in records[i+1:])
        reg_rows.append((f'OUT{rail}',_fmt(item.get('V_reference')),
            _fmt(item.get('deviation_min_pct'))+' ～ '+_fmt(item.get('deviation_max_pct')),
            _fmt(design.get('cross_only_pct')) if matched and design.get('complete') else '—',
            _fmt(item.get('cross_only_pct')) if matched else '无同载配对',
            '完整' if item.get('complete') else '部分'))
    section('负载组合下的稳压精度与交叉调整率',['端口','参考 / V','仿真稳压偏差范围 / %','计算交叉变化 / %','仿真交叉变化 / %','角点覆盖'],
        reg_rows,'稳压偏差相对本路参考电压；交叉变化只取同 Vin、同本路负载而其他路变化的收敛角点。'
        +(str(cross.get('error') or ('单路输出不适用。' if len(rows)==1 else '未取得有效角点。')) if not reg_rows else ''))
    return sections
