"""Device-level probes and RAW metrology for steady-state and startup."""
import re

import numpy as np

from capacitor_banks import output_ref
from spice_analysis import statistics


def prepare(files, case):
    """Instrument only physical power-stage parts in the actual generated CIR."""
    result = case['result']
    operating = result['op']
    outputs = result.get('outputs') or [result]
    devices = []
    params = dict(re.findall(r'(?im)^\.param\s+(\w+)=([-+.\deE]+)\s*$', files['design_params.inc'].decode('ascii')))
    cards = [line.split() for name in ('power_stage.inc', 'support.inc', 'parasitics.inc')
             for line in files.get(name, b'').decode('ascii').splitlines() if line.strip() and not line.startswith('*')]

    def add(ref, kind, trace, positive, negative, *, scale=1, rms=None, peak=None, voltage=None,
            note='', direct=True, current_label=None, voltage_label=None, startup_only=False):
        devices.append(dict(ref=ref, kind=kind, trace=trace.lower() if trace else None,
                            positive=positive.lower() if positive is not None else None,
                            negative=negative.lower() if negative is not None else None,
                            scale=scale, rms=rms, peak=peak, voltage=voltage, note=note, direct=direct,
                            current_label=current_label or {'mos':'Id（D→S）','diode':'If（A→K）','capacitor':'Ic'}.get(kind,'I'),
                            voltage_label=voltage_label or {'mos':'Vds','diode':'VR','capacitor':'Vc'}.get(kind,'V'),
                            startup_only=startup_only))

    for card in cards:
        if len(card)<4:
            continue
        ref, first, second = card[:3]
        if any(word.startswith('ACT=') and
               float(params.get(word[4:].strip('{}'), word[4:] if '{' not in word else '1'))<.5
               for word in card):
            continue
        cap_match = re.fullmatch(r'XC_IN(\d+)|CIN(\d+)|XC_O(\d+)(?:_(\d+))?|COUT(\d+)', ref)
        if cap_match:
            is_input = first.lower() in ('vbus','vin_bus')
            index = int(cap_match[1] or cap_match[2] or cap_match[4] or cap_match[5] or 1)
            rail = int(cap_match[3] or 1)
            name = 'C_IN'+str(index) if is_input else output_ref(rail,index,len(outputs)>1)
            group = result if is_input else outputs[rail-1]
            caps = (group.get('capacitors') or {}).get('input' if is_input else 'output',{}).get('caps') or []
            current = caps[index-1].get('total') if index<=len(caps) else None
            curve_group = any(cap.get('impedance_model')=='curve' for cap in caps)
            probe = f'i({ref}:cmain)' if ref.startswith('X') else f'i({ref})'
            note = '输入源阻抗影响实际分流；端口激励与设计纹波源并列' if is_input else '实际并联支路；仿真采用固定 C/ESR/ESL'
            if curve_group:
                note += '；设计分流使用阻抗曲线，开关模型使用固定参数'
            add(name,'capacitor',probe,first,second,rms=current,note=note,direct=not is_input and not curve_group)
        elif ref in ('C_ACTIVE','C_SN1') or re.fullmatch(r'C_PAR_(?:Q1|D\d+|P|S\d+)',ref):
            add(ref,'capacitor',f'i({ref})',first,second,
                rms=operating.get('I_clamp_rms') if ref=='C_ACTIVE' else None,
                note='绕组寄生电容的模型支路' if re.fullmatch(r'C_PAR_(?:P|S\d+)',ref) else '钳位／吸收电容实际支路')
        elif ref in ('XQ1','XQA'):
            aux = ref=='XQA'
            name = ref[1:]
            pm_buck = 'GNISO_PMOS' in card
            add(name,'mos',f'i({ref}:smain)',first,card[3],scale=1 if pm_buck else -1,
                rms=operating.get('I_aux_rms' if aux else 'I_sw_rms'),peak=operating.get('I_aux_pk' if aux else 'I_sw_pk'),
                voltage=operating.get('V_sw_max'),note='沟道导通电流，不含体二极管及位移支路；|Vds| 为端子阻断应力')
        elif ref.startswith('XD_') or ref in ('D_INPUT_BLOCK','D_OUT') or re.fullmatch(r'D[HL]\d+',ref):
            rail_match = re.fullmatch(r'XD_([OF])(\d+)',ref)
            rms = peak = voltage = None
            if rail_match:
                keys = ('I_free_rms','I_free_pk','V_free_max') if rail_match[1]=='F' else ('I_d_rms','I_d_pk','V_d_max')
                branch = outputs[int(rail_match[2])-1]['op']
                rms, peak, voltage = (branch.get(key) for key in keys)
            probe=f'i({ref}:dmain)' if ref.startswith('X') else f'i({ref})'
            add(ref.removeprefix('X'),'diode',probe,second,first,rms=rms,peak=peak,voltage=voltage,
                note='导通支路；反向电压 VR = VK − VA')
        elif re.fullmatch(r'S[HL]\d+',ref):
            phase = int(ref[2:])
            high = ref[1]=='H'
            phases = (operating.get('cot') or {}).get('phase_data') or []
            values = phases[phase-1] if phase<=len(phases) else {}
            add(ref,'mos',f'i({ref})',first,second,scale=-1,
                rms=values.get('high_rms_A' if high else 'low_rms_A'),peak=values.get('current_peak_A'),
                voltage=values.get('high_block_V' if high else 'low_block_V'),note=f'PH{phase} '+('上管' if high else '下管')+'沟道；体二极管另列')

    qr = 'GenericQR_L6565.lib' in files
    for card in cards:
        ref = card[0]
        if ref=='VIN_SOURCE':
            supply = ('固定理想输入源在直流工作点已加电。此处观察控制器使能后的输入电流，电源插接浪涌需另行建模'
                      if card[3]=='{VIN}' else '按网表设定的输入激励与源阻抗测量')
            add('输入端', 'aux', 'i(vin_source)', card[1], card[2], scale=-1,
                current_label='Iin（源送出）', voltage_label='Vin', startup_only=True,
                note=supply)
        elif qr and re.fullmatch(r'L(?:P|S\d+)',ref):
            add(ref, 'winding', f'i({ref})', card[1],card[2], current_label='绕组电流',
                voltage_label='绕组端电压', note='电流由网表的第一端流向第二端', startup_only=True)
        elif qr and ref=='XQ1':
            drain,gate,source=card[1:4]
            add('Q1 栅极', 'aux', 'i(xq1:cgate)', gate,source, current_label='栅电容电流',
                voltage_label='Vgs',note='栅极对源极电压与模型栅电容电流',startup_only=True)
            add('Q1 Coss', 'aux', 'i(xq1:coss)', None,None, current_label='位移电流',
                note='按 D→S 为正，独立于沟道电流',startup_only=True)
            add('Q1 体二极管', 'aux', 'i(xq1:xbody:dmain)', None,None, current_label='正向支路电流',
                note='按 S→D 为正，独立于沟道电流',startup_only=True)
            add('CS', 'aux', None, source,'0', voltage_label='采样端电压',
                note='原始采样电压，滤波后阈值另见控制器设置',startup_only=True)
        elif qr and (ref=='XD_SN1' or re.fullmatch(r'XD_O\d+',ref)):
            add(ref[1:]+' Cj', 'aux', f'i({ref}:cj)', None,None, current_label='结电容位移电流',
                note='按 A→K 为正，独立于二极管导通电流',startup_only=True)
    parameters = case.get('p')
    if parameters and parameters.get('component_management'):
        _attach_voltage_ratings(devices, parameters, len(outputs)>1)

    traces = set()
    for device in devices:
        if device['trace']:
            traces.add(device['trace'])
        traces.update(f'v({device[key]})' for key in ('positive','negative') if device[key] not in (None,'0'))
    existing = {trace.lower() for line in files['analysis.inc'].decode('ascii').splitlines()
                if line.lower().startswith('.save ') for trace in line.split()[1:]}
    missing = sorted(traces-existing)
    if missing:
        files['analysis.inc'] += ('\n'+'\n'.join('.save '+' '.join(missing[i:i+12]) for i in range(0,len(missing),12))+'\n').encode('ascii')
    return devices


def bom_reference(ref, multi_output):
    """Resolve existing RAW/report labels to their physical BOM designator."""
    if ref.startswith('D_OUT'):
        return 'D_B'+(ref[5:] or '1') if multi_output else 'D_OUT'
    renamed = {'C_ACTIVE': 'C_CL1', 'QA': 'Q2', 'D_INPUT_BLOCK': 'D_IN'}
    if not multi_output:
        renamed.update(D_O1='D1', D_F1='D2')
    return renamed.get(ref, ref)


def _attach_voltage_ratings(devices, parameters, multi_output):
    from component_management import normalize_management, rule_for

    config = normalize_management(parameters['component_management'])
    for probe in devices:
        kind = probe['kind']
        if kind not in ('capacitor','diode','mos'):
            continue
        bom_ref = bom_reference(probe['ref'], multi_output)
        item = config['items'].get(bom_ref,{})
        rating = item.get('voltage_V')
        if not rating:
            continue
        ctype = item.get('capacitor_type','unknown')
        ctype = ctype if ctype in ('electrolytic','mlcc','film') else 'other'
        limit_factor = rule_for(config, (ctype if kind=='capacitor' else kind)+'_voltage')['factor']
        probe.update(voltage_rating=rating, voltage_limit=rating*limit_factor if limit_factor is not None else None)


def collect(raw, probes, start, end, plot_start, *, comparable, tolerance):
    """Time-weighted full-window metrology; plot samples do not enter metrics."""
    first = max(0, int(np.searchsorted(raw.time,start))-1)
    last = min(len(raw.time),int(np.searchsorted(raw.time,end,side='right'))+1)
    selected = slice(first,last)
    time = np.asarray(raw.time[selected],dtype=float)
    if len(time)<2 or not time[0]<=start<end<=time[-1]:
        return dict(available=False,reason='缺少完整额定稳态测量窗',rows=[],devices=[],time_s=[])
    if end > plot_start >= start:
        shown = np.r_[plot_start,time[(time>plot_start)&(time<end)],end]
    else:
        shown = time[(time>=start)&(time<=end)]
    rows, devices = [], []
    def values(name):
        try:
            signal = np.asarray(raw.trace(name)[selected],dtype=float)
        except KeyError:
            return None
        return signal if np.all(np.isfinite(signal)) else None

    def node(name):
        return 0. if name=='0' else values(f'v({name})')

    def row(probe,metric,unit,expected,actual,same):
        delta = None
        if actual is None:
            status = '缺少 RAW 探针'
        elif not comparable:
            status = '未稳态，仅观察'
        elif expected is None:
            status = '无对应计算值'
        elif not same:
            status = '模型口径不同，仅并列'
        elif expected==0:
            status = '零基准，列绝对值'
        else:
            delta = 100*(actual-expected)/abs(expected)
            status = '偏差待复核' if abs(delta)>tolerance else '偏差在提示阈值内'
        rows.append(dict(ref=probe['ref'],kind=probe['kind'],metric=probe['ref']+' '+metric,unit=unit,
                         design=expected,simulation=actual,delta_percent=delta,status=status,scope=probe['note']))

    for probe in probes:
        if probe.get('startup_only'):
            continue
        signal = values(probe['trace'])
        if signal is not None:
            signal = signal*probe['scale']
        stats = statistics(time,signal,start,end) if signal is not None else {}
        positive, negative = node(probe['positive']),node(probe['negative'])
        voltage = positive-negative if positive is not None and negative is not None else None
        if probe['kind']=='capacitor':
            row(probe,'纹波 AC RMS','A',probe['rms'],stats.get('ac_rms'),probe['direct'])
            if voltage is None:
                peak_voltage = None
            elif np.isscalar(voltage):
                peak_voltage = abs(voltage)
            else:
                volts = statistics(time,voltage,start,end)
                peak_voltage = max(abs(volts['minimum']),abs(volts['maximum']))
            row(probe,'端电压绝对峰值','V',probe['voltage'],peak_voltage,False)
        else:
            volts = statistics(time,voltage,start,end) if voltage is not None else {}
            mos = probe['kind']=='mos'
            current_peak = (max(abs(stats['minimum']),abs(stats['maximum'])) if mos else max(0.,stats['maximum'])) if stats else None
            peak_voltage = (max(abs(volts['minimum']),abs(volts['maximum'])) if mos else max(0.,volts['maximum'])) if volts else None
            row(probe,'沟道电流 RMS' if mos else '导通电流 RMS','A',probe['rms'],stats.get('rms'),True)
            row(probe,'|Id| 峰值' if mos else 'If 峰值','A',probe['peak'],current_peak,not mos)
            row(probe,'|Vds| 峰值' if mos else '反向电压峰值','V',probe['voltage'],peak_voltage,False)
        devices.append(dict(ref=probe['ref'],kind=probe['kind'],current_label=probe['current_label'],voltage_label=probe['voltage_label'],
                            current_A=np.interp(shown,time,signal).tolist() if signal is not None else [],
                            voltage_V=np.interp(shown,time,np.broadcast_to(voltage,time.shape)).tolist() if voltage is not None else []))
    return dict(available=any(row['simulation'] is not None for row in rows), rows=rows,devices=devices,
                start_s=float(start),end_s=float(end),time_s=shown.tolist())


def _startup_trace(time, traces, scale, start, end, bounds):
    """Preserve the min/max raw samples in each time bin, including narrow spikes."""
    if any(trace is None for trace in traces):
        return None

    def read(first,last):
        y = np.asarray(traces[0][first:last],dtype=float)
        if len(traces)>1:
            y = y-traces[1][first:last]
        return y if scale==1 else scale*y

    def at(t):
        right = int(np.searchsorted(time,t,side='right'))
        first = max(0,right-1)
        return float(np.interp(t,time[first:right+1],read(first,right+1)))

    t_points, values = [start], [at(start)]
    for first,last in zip(bounds[:-1],bounds[1:]):
        if first==last:
            continue
        y = read(first,last)
        if not np.isfinite(y).all():
            return None
        offsets = sorted({int(np.argmin(y)), int(np.argmax(y))})
        t_points.extend(float(time[first+offset]) for offset in offsets)
        values.extend(float(y[offset]) for offset in offsets)
    t_points.append(end)
    values.append(at(end))
    if not np.isfinite([values[0],values[-1]]).all():
        return None
    return t_points,values


def _collect_startup_window(raw, probes, start, end, bins):
    time = raw.time
    if len(time)<2 or not np.isfinite([start,end]).all() or end<=start or bins<1:
        return dict(available=False,complete_window=False,reason='启动测量时间范围无效',rows=[],devices=[])
    actual_start = max(float(start),float(time[0]))
    actual_end = min(float(end),float(time[-1]))
    if actual_start>=actual_end:
        return dict(available=False,complete_window=False,reason='RAW 缺少启动测量窗',rows=[],devices=[])
    complete_window = abs(actual_start-start)<=1e-10 and abs(actual_end-end)<=1e-10
    edges = np.linspace(actual_start,actual_end,bins+1)
    bounds = np.searchsorted(time,edges)
    bounds[-1] = np.searchsorted(time,actual_end,side='right')

    def trace(name):
        try:
            return raw.trace(name)
        except KeyError:
            return None

    rows, devices = [], []
    for probe in probes:
        kind = probe['kind']
        positive,negative = probe['positive'],probe['negative']
        channels = []
        if probe['trace']:
            channels.append(('current',probe['current_label'],'A',(trace(probe['trace']),),probe['scale']))
        if positive is not None and negative is not None and positive!=negative:
            if positive=='0':
                sources, sign = (trace(f'v({negative})'),), -1
            elif negative=='0':
                sources, sign = (trace(f'v({positive})'),), 1
            else:
                sources, sign = (trace(f'v({positive})'),trace(f'v({negative})')), 1
            channels.append(('voltage',probe['voltage_label'],'V',sources,sign))
        elif positive is not None and negative is not None:
            channels.append(('voltage',probe['voltage_label'],'V',(),1))
        record = dict(ref=probe['ref'],kind=kind)
        for channel,label,unit,sources,scale in channels:
            measurement = _startup_trace(time,sources,scale,actual_start,actual_end,bounds) if sources else (
                [actual_start,actual_end],[0.,0.])
            rating = probe.get('voltage_rating') if channel=='voltage' else None
            limit = probe.get('voltage_limit') if channel=='voltage' else None
            magnitude = observed_s = None
            if measurement is None:
                status = '缺少有效 RAW 探针'
            else:
                t_points,values = measurement
                score = np.asarray(values) if kind=='diode' else np.abs(values)
                i_peak = int(np.argmax(score))
                magnitude = float(max(0.,score[i_peak]))
                observed_s = t_points[i_peak] if magnitude>0 else None
                record[channel] = dict(time_s=t_points,values=values,label=label,unit=unit,
                                       peak_s=observed_s,peak_value=values[i_peak] if observed_s is not None else None)
                if rating is not None and magnitude>rating:
                    status = '超过器件额定电压'
                elif limit is not None and magnitude>limit:
                    status = '超过配置降额限值'
                elif not complete_window:
                    status = '启动测量窗不完整'
                elif limit is not None:
                    status = '观察峰值未超限'
                else:
                    status = '记录观察峰值'
            rows.append(dict(ref=probe['ref'],kind=kind,channel=channel,metric=label,unit=unit,simulation=magnitude,
                             time_s=observed_s,rating=rating,limit=limit,status=status,scope=probe['note']))
        devices.append(record)
    return dict(available=any(row['simulation'] is not None for row in rows),complete_window=complete_window,rows=rows,
                devices=devices,start_s=actual_start,end_s=actual_end,requested_end_s=float(end),
                reason='' if complete_window else '启动测量窗只覆盖了现有的 RAW 数据')


def collect_startup(raw, probes, start, end, *, bins=420):
    """Record startup peaks and plot raw bin extrema at their actual times."""
    summary = _collect_startup_window(raw,probes,start,end,bins)
    mos = next((d for d in summary['devices'] if d['ref']=='Q1' and d['kind']=='mos'),{})
    peak = mos.get('voltage',{}).get('peak_s')
    if peak is not None and any(probe['ref']=='Q1 栅极' for probe in probes):
        zoomed_probes = [probe for probe in probes if probe['ref'] in ('Q1','Q1 栅极','Q1 Coss')]
        detail = _collect_startup_window(raw,zoomed_probes,max(summary['start_s'],peak-10e-6),
                                         min(summary['end_s'],peak+10e-6),bins)
        summary['qr_peak_detail'] = dict(peak_s=peak,start_s=detail['start_s'],end_s=detail['end_s'],
                                          devices=detail['devices'],rows=detail['rows'])
    return summary
