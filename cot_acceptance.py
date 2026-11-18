"""Evidence-based COT acceptance. Measurement validity and design limits are separate."""
import math

import numpy as np


DEFAULT_LIMITS = dict(pm_min_deg=45., gm_min_db=6., fc_error_pct=20., pm_error_deg=10.,
                      gain_error_db=3., phase_error_deg=15., overshoot_pct=5., undershoot_pct=5.,
                      settling_band_pct=2., recovery_s=.002, imbalance_pct=10., input_peak_A=0.)
LABELS = {'pass':'满足', 'fail':'超限', 'review':'待复核', 'not_covered':'未覆盖', 'observe':'供观察'}


def limits(parameters):
    config = parameters.get('cot_config') or {}
    configured = config.get('acceptance') or {}
    result = DEFAULT_LIMITS | {'imbalance_pct':config.get('phase_imbalance_limit_pct',10.)} | configured
    dynamic = config.get('dynamic') or {}
    voltage = parameters.get('V_out',0.)
    if voltage > 0:
        for field,key in [('droop_V','undershoot_pct'),('overshoot_V','overshoot_pct')]:
            if dynamic.get(field,0.) > 0:
                result[key] = dynamic[field]/voltage*100
    for key, val in result.items():
        if key not in DEFAULT_LIMITS or isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0:
            raise ValueError('COT 验收门限须为有限非负数：'+key)
    if result['settling_band_pct'] <= 0 or result['recovery_s'] <= 0:
        raise ValueError('COT 恢复带宽及时间须大于零')
    return result


def _row(key, label, value, limit, unit='', comparison='<=', *, missing='未取得有效测量', note=''):
    if value is None or not math.isfinite(value):
        status = 'not_covered'
        value = None
        note = missing
    elif limit is None:
        status = 'observe'
    else:
        status = 'pass' if (value <= limit if comparison == '<=' else value >= limit) else 'fail'
    return dict(id=key, label=label, value=value, limit=limit, comparison=comparison, unit=unit,
                status=status, note=note)


def summarize(rows):
    counts = {key:sum(row['status'] == key for row in rows) for key in LABELS}
    state = 'fail' if counts['fail'] else 'review' if counts['review'] or counts['not_covered'] else 'pass'
    return dict(rows=rows, counts=counts, status=state, passed=state == 'pass')


def assess_fra(probe, parameters):
    """A valid half-amplitude measurement alone never proves adequate margins."""
    thresholds = limits(parameters)
    if not probe.get('available'):
        return summarize([_row('fra_valid', 'FRA 测量有效性', None, 1., missing=probe.get('error') or '未运行 FRA')])
    sim = (probe.get('simulation') or {}).get('loop') or {}
    design = (probe.get('design') or {}).get('loop') or {}
    rows = [_row('pm', '实测相位裕度', sim.get('pm'), thresholds['pm_min_deg'], '°', '>=', missing='频带内未测得有效相位裕度'),
            _row('gm', '实测增益裕度', sim.get('gm_db'), thresholds['gm_min_db'], 'dB', '>=', missing='频带内未检出相位交越，增益裕度未覆盖')]
    fc, ref = sim.get('fc'), design.get('fc')
    fc_error = abs(fc/ref-1)*100 if fc is not None and ref and fc > 0 else None
    pm, pm_ref = sim.get('pm'), design.get('pm')
    pm_error = abs(pm-pm_ref) if pm is not None and pm_ref is not None else None
    rows += [_row('fc_error', '穿越频率计算与仿真偏差', fc_error, thresholds['fc_error_pct'], '%'),
             _row('pm_error', '相位裕度计算与仿真偏差', pm_error, thresholds['pm_error_deg'], '°')]
    for key, unit, threshold, title in [('db','dB','gain_error_db','同频点增益差'),('phase','°','phase_error_deg','同频点相位差')]:
        values, reference = sim.get(key), design.get(key)
        error = None
        if values is not None and reference is not None and len(values) == len(reference) and len(values):
            sf, df = sim.get('f'), design.get('f')
            if sf is not None and df is not None and np.shape(sf) == np.shape(df) and np.allclose(sf,df,rtol=1e-8,atol=0):
                delta = np.asarray(values)-np.asarray(reference)
                if key == 'phase':
                    delta = (delta+180)%360-180
                error = float(np.max(np.abs(delta)))
        rows.append(_row(key+'_error',title,error,thresholds[threshold],unit))
    result = summarize(rows)
    result['measurement_valid'] = True
    return result


def _trace(raw, name):
    try:
        value = np.asarray(raw.trace(name),dtype=float)
        return value if len(value) == len(raw.time) and np.all(np.isfinite(value)) else None
    except (KeyError, ValueError, IndexError):
        return None


def _settle(time, values, target, start, stop, band, hold):
    select = (time >= start) & (time <= stop)
    t, y = time[select], values[select]
    if len(t) < 2 or t[-1]-start < hold:
        return None
    bad = np.flatnonzero(np.abs(y-target) > band)
    index = int(bad[-1]+1) if len(bad) else 0
    if index >= len(t) or t[-1]-t[index] < hold:
        return None
    return float(max(0.,t[index]-start))


def transient_acceptance(case, raw, settings, phase_table):
    """Measure full-resolution traces; downsampled report plots never feed acceptance."""
    p, op = case['p'],case['result']['op']
    config = p.get('cot_config') or {}
    thresholds = limits(p)
    t = np.asarray(raw.time,dtype=float)
    v = _trace(raw,'v(out1)')
    if v is None or len(t) < 2:
        return summarize([_row('dynamic','动态记录',None,1.)])
    target, phases = op['V_out'],op['cot']['phases']
    step, soft_end = settings['step_ms']*1e-3,(settings['enable_delay_ms']+settings['soft_start_ms'])*1e-3
    shutdown = config.get('shutdown_s',0.)
    on_stop = min(t[-1],shutdown) if shutdown > 0 else t[-1]
    hold = max(8/op['f_sw'],50e-6)
    rows, events, phase_peaks = [],[],[]
    startup = (t >= settings['enable_delay_ms']*1e-3) & (t < min(step,on_stop))
    after = (t >= step) & (t < on_stop)
    for label, mask in [('startup',startup),('step',after)]:
        name = '启动' if label == 'startup' else '负载阶跃'
        over = max(0.,float(v[mask].max())-target)/target*100 if mask.any() else None
        rows.append(_row(label+'_overshoot',name+'过冲',over,thresholds['overshoot_pct'],'%'))
        if label == 'step':
            under = max(0.,target-float(v[mask].min()))/target*100 if mask.any() else None
            rows.append(_row('step_undershoot','负载阶跃跌落',under,thresholds['undershoot_pct'],'%'))
        start = soft_end if label == 'startup' else step
        end = min(step,on_stop) if label == 'startup' else on_stop
        recovery = _settle(t,v,target,start,end,target*thresholds['settling_band_pct']/100,hold)
        record = _row(label+'_recovery',name+'恢复时间',recovery,thresholds['recovery_s'],'s',
                      missing='观测结束前未取得持续稳定窗口')
        if recovery is None and end-start >= thresholds['recovery_s']+hold:
            record.update(status='fail',note='超出允许恢复时间且仍未稳定')
        rows.append(record)
    peak_in = _trace(raw,'i(vin_source)')
    rows.append(_row('input_peak','全程输入电流峰值',float((-peak_in).max()) if peak_in is not None else None,
                     thresholds['input_peak_A'] or None,'A',note=(
                         '输入为理想阶跃源，初始电容充电峰值受源阻抗与时间步影响'
                         if not config.get('source_resistance_ohm') and not config.get('source_inductance_H')
                         else '全程含输入电容初始充电；未指定上限时仅记录')))
    for i in range(1,phases+1):
        current = _trace(raw,f'i(l{i})')
        peak = float(current.max()) if current is not None else None
        valley = float(current.min()) if current is not None else None
        sensed = _trace(raw,f'v(sensed{i})')
        ocp_limit = float(config.get('phase_limit_A',0.))
        sensed_peak = float(sensed.max()) if sensed is not None else None
        phase_peaks.append(dict(phase=i,peak_A=peak,valley_A=valley,sensed_peak_A=sensed_peak,
                                limit_A=ocp_limit or None,
                                ocp_margin_A=ocp_limit-sensed_peak if ocp_limit>0 and sensed_peak is not None else None))
        phase_check = _row(f'phase{i}_limit',f'PH{i} 全程采样峰值',sensed_peak,ocp_limit or None,'A',
                           missing='未取得逐相采样记录')
        if ocp_limit <= 0:
            phase_check.update(status='not_covered',note='未配置逐相限流门限，电流仅作记录')
        rows.append(phase_check)
        trace = _trace(raw,f'v(ocp{i})')
        if trace is not None:
            starts = np.flatnonzero((trace[1:] >= .5) & (trace[:-1] < .5))+1
            if trace[0] >= .5: starts=np.r_[0,starts]
            events.append(dict(signal=f'ocp{i}',count=len(starts),first_s=float(t[starts[0]]) if len(starts) else None))
    means = [item['average_A'] for item in phase_table]
    mean = float(np.mean(means)) if means else 0.
    imbalance = 100*max(abs(x-mean) for x in means)/abs(mean) if abs(mean)>1e-9 else None
    rows.append(_row('imbalance','额定窗口最大相电流不平衡',imbalance,thresholds['imbalance_pct'],'%'))
    for name in ('fault','ovp'):
        signal = _trace(raw,'v('+name+')')
        if signal is not None:
            starts = np.flatnonzero((signal[1:]>=.5)&(signal[:-1]<.5))+1
            if signal[0]>=.5: starts=np.r_[0,starts]
            count=len(starts)
            events.append(dict(signal=name,count=count,first_s=float(t[starts[0]]) if count else None))
            rows.append(_row(name+'_events','故障动作次数' if name=='fault' else '过压动作次数',count,0,'次'))
    ocp_events = [x for x in events if x['signal'].startswith('ocp')]
    rows.append(_row('ocp_events','逐相限流动作总次数',sum(x['count'] for x in ocp_events) if len(ocp_events)==phases else None,
                     0,'次',missing='逐相限流事件记录不完整',note='额定启动与阶跃按不触发限流验收'))
    if shutdown > 0:
        mask=t>=shutdown
        rows.append(_row('shutdown_peak','关机后端口最高电压',float(v[mask].max()) if mask.any() else None,
                         target*(1+thresholds['overshoot_pct']/100),'V'))
        rows.append(_row('shutdown_tail','关机末端电压',float(v[-1]) if mask.any() else None,None,'V',note='放电时间受负载和输出电容决定'))
    else:
        rows.append(_row('shutdown','关机观察',None,None,missing='本次未配置关机时刻'))
    result=summarize(rows)
    result.update(phase_peaks=phase_peaks,events=events,limits=thresholds,
                  observation=dict(start_s=float(t[0]),end_s=float(t[-1]),shutdown_s=shutdown),
                  scope='全分辨率波形；启动恢复从软启动结束起计，阶跃恢复从负载变化起计。限流和故障判据用于正常工况。')
    return result


def apply_boundary_step(record, parameters):
    dynamic = record.get('dynamic')
    if not dynamic:
        return
    limits_used = limits(parameters)
    study = record['load_transient']
    rows = [row for row in dynamic['rows'] if not row['id'].startswith('step_')]
    for index, label in enumerate(('升载','降载')):
        events = study.get('events', [])
        event = events[index] if study.get('available') and index < len(events) else {}
        ref = study.get('reference_v') or parameters['V_out']
        for key, name, limit, value, unit in (
            ('overshoot','过冲','overshoot_pct',max(0.,event['max_v']/ref-1)*100 if event else None,'%'),
            ('undershoot','跌落','undershoot_pct',max(0.,1-event['min_v']/ref)*100 if event else None,'%'),
            ('recovery','恢复时间','recovery_s',event.get('recovery_s'),'s')):
            rows.append(_row(f'step_{index+1}_{key}',label+name,value,limits_used[limit],unit,
                        missing=study.get('error') or '未在观测窗内持续进入恢复带'))
    dynamic.update(summarize(rows),scope='满载开机与额定窗口取基础实验；双向负载阶跃另用独立实验的原始波形。')


def assess_case(record, parameters, *, fra_requested):
    rows = [_row('nominal','额定稳态与脉宽',1. if record.get('nominal_comparable') else None,1.,
                 missing=record.get('error') or '额定窗口未通过')]
    dynamic=record.get('dynamic')
    rows.extend(dynamic['rows'] if dynamic else [_row('dynamic','动态验收',None,1.,missing='未取得动态量化记录')])
    fra=assess_fra(record.get('loop') or {},parameters)
    if fra_requested:
        rows.extend(fra['rows'])
    result=summarize(rows)
    result['fra']=fra if fra_requested else dict(status='not_covered',passed=False,rows=[])
    result['fra_requested']=bool(fra_requested)
    return result
