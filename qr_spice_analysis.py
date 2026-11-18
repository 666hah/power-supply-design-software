"""Gate-edge based statistics: a variable-frequency QR has no clock bins."""
import numpy as np


def excitation_ramps(switching, controller):
    """Select original I(LP) points for the flyback energy-storage interval.

    The shared flyback switch model reaches full enhancement at Vgs >= 0.7 VG.
    Use complete Vgs pulses, leave a display guard at turn-on, and omit the
    leading ringing before the current starts its sustained rise. The original
    waveform and its independent full-band stress measurements are unchanged.
    """
    result = dict(available=False, blank_s=None, segments=[], peak_A=None)
    try:
        time, gate, sense, current = (np.asarray(switching[key], dtype=float) for key in
            ('time', 'v(gate)', 'v(sense)', 'i(lp)'))
        drive = float(controller['VG'])
        blanking = float(controller.get('TLEB', controller.get('TBLANK', 0)))
    except (KeyError, TypeError, ValueError):
        return dict(result, reason='缺少原边电流、门极或前沿消隐设置')
    if (time.ndim != 1 or len(time) < 4 or any(v.shape != time.shape for v in (gate, sense, current))
            or not all(np.isfinite(v).all() for v in (time, gate, sense, current, drive, blanking))
            or (np.diff(time) < 0).any() or drive <= 0 or blanking < 0):
        return dict(result, reason='原边与门极波形的采样点、时间轴或驱动电压无效')

    blank = max(100e-9, blanking)
    result['blank_s'] = blank
    vgs = gate - sense
    threshold = .5 * drive
    on = vgs >= threshold
    rises = np.flatnonzero(~on[:-1] & on[1:]) + 1
    falls = np.flatnonzero(on[:-1] & ~on[1:]) + 1
    def crossing(index):
        ratio = (threshold - vgs[index-1]) / (vgs[index]-vgs[index-1])
        return time[index-1] + ratio * (time[index]-time[index-1])

    for rise, position in zip(rises, np.searchsorted(falls, rises)):
        if position == len(falls):
            break
        fall = falls[position]
        start_edge, end_edge = crossing(rise), crossing(fall)
        first = max(rise, int(np.searchsorted(time, start_edge+blank)))
        if fall-first < 3:
            continue
        enhanced = np.flatnonzero(vgs[first:fall] >= .7*drive) + first
        if len(enhanced) < 3:
            continue
        # Keep one contiguous fully enhanced interval. Exclude a pulse if a
        # later voltage interruption erases most of its normal rise.
        interruptions = np.flatnonzero(np.diff(enhanced) > 1)
        if interruptions.size:
            enhanced = enhanced[interruptions[-1]+1:]
        values = current[enhanced]
        if len(values) < 3:
            continue

        # A leading positive excursion followed by a valley is still turn-on
        # ringing. Trim its prefix only. A late major decline is not a ramp.
        tolerance = max(.001, .01*abs(values[-1]))
        later_min = np.minimum.accumulate(values[::-1])[::-1]
        ringing = np.flatnonzero(values-later_min > tolerance)
        if ringing.size:
            enhanced = enhanced[ringing[-1]+1:]
        if len(enhanced) < 3 or time[enhanced[0]] > (start_edge+end_edge)/2:
            continue
        points, values = time[enhanced], current[enhanced]
        if points[-1] <= points[0] or values[-1] <= values[0]:
            continue
        result['segments'].append(dict(time_s=points.tolist(),current_A=values.tolist(),
            turn_on_s=float(start_edge),turn_off_s=float(end_edge),peak_A=float(np.max(values)),
            start_A=float(values[0]),end_A=float(values[-1])))

    if not result['segments']:
        return dict(result,reason='记录窗口没有完整、可分辨的原边励磁上升段')
    return dict(result,available=True,peak_A=max(seg['peak_A'] for seg in result['segments']))


def cycle_current_statistics(raw, quality, output_count, *, current_observation=None):
    """Unfiltered current evidence on complete observed gate periods.

    Adaptive RAW samples describe piecewise-linear waveforms. Integrate their
    square analytically per segment; do not average sample counts or discard
    displacement-current peaks. Optional internal probes are never invented.
    """
    cycles=quality.get('cycles') or []
    if len(cycles)<8:
        return dict(available=False,reason='不足八个完整门极周期')
    if any(abs(a['end_s']-b['start_s'])>1e-12 for a,b in zip(cycles[:-1],cycles[1:])):
        return dict(available=False,reason='门极周期记录不连续，不能宣称整周期电流积分')
    start,end=float(cycles[0]['start_s']),float(cycles[-1]['end_s'])
    first,last=np.searchsorted(raw.time,[start,end])
    times=np.asarray(raw.time[max(0,first-1):min(len(raw.time),last+1)],float)
    axis=np.r_[start,times[(times>start)&(times<end)],end]
    dt=np.diff(axis); span=end-start
    def trace(name):
        try:
            y=np.asarray(raw.trace(name)[max(0,first-1):min(len(raw.time),last+1)],float)
        except KeyError:return None
        if not np.all(np.isfinite(y)):return None
        return np.interp(axis,times,y)
    def integral_product(a,b):
        return float(np.sum(dt*(2*a[:-1]*b[:-1]+a[:-1]*b[1:]+a[1:]*b[:-1]+2*a[1:]*b[1:])/6)/span)
    signals=[];measurements={}
    def add(name,label,role,voltage=None,keys=None,*,direction_scale=1.,direction_note=None):
        y=trace(name)
        row=dict(signal=name,label=label,role=role,raw_probe_present=y is not None,
                 available=y is not None and direction_scale in (-1.,1.))
        if direction_note:row['direction_note']=direction_note
        if y is not None and direction_scale not in (-1.,1.):
            row['reason']='缺少已验证的探针参考方向；不作为正向电流统计'
            y=None
        elif y is not None:
            row['direction_scale']=float(direction_scale)
            y=y*direction_scale
        if y is not None:
            mean=float(np.sum(dt*(y[:-1]+y[1:])/2)/span)
            rms=float(np.sqrt(max(0.,integral_product(y,y))))
            row.update(mean_A=mean,rms_A=rms,peak_A=float(np.max(y)),valley_A=float(np.min(y)),
                       charge_C=mean*span)
            if voltage is not None:
                va,vb=trace(voltage[0]),trace(voltage[1])
                if va is not None and vb is not None:
                    row['mean_power_W']=integral_product(va-vb,y)
            if keys:
                for key,value in zip(keys,(mean,rms,row['peak_A'])):measurements[key]=value
        signals.append(row)
        return y
    primary=add('i(lp)','原边绕组 LP','winding',('v(vin_bus)','v(drain)'),keys=('primary_avg','primary_rms','primary_peak'))
    observation=current_observation or {}
    add('i(xq1:smain)','Q1 沟道 D→S','conduction',('v(drain)','v(sense)'),
        ('switch_avg','switch_rms','switch_peak'),
        direction_scale=observation.get('mos_channel_direction_scale'),
        direction_note=observation.get('mos_channel_direction_note'))
    add('i(xq1:coss)','Q1 Coss 位移电流','displacement',('v(drain)','v(sense)'))
    add('i(xq1:xbody:dmain)','Q1 体二极管导通','conduction',('v(sense)','v(drain)'))
    add('i(xq1:cgate)','Q1 栅电容电流','gate')
    add('i(rs1)','采样电阻总电流','sense_total')
    add('i(xd_sn1:dmain)','RCD 钳位二极管导通','clamp')
    add('i(xd_sn1:cj)','RCD 二极管 Cj 位移电流','displacement')
    add('i(c_par_p)','原边绕组电容位移电流','displacement')
    add('i(r_par_q1)','Q1 外接 RC 支路','snubber')
    outputs=[]
    for n in range(1,output_count+1):
        add(f'i(ls{n})',f'OUT{n} 绕组 LS{n}','winding',('v(sgnd)',f'v(rect{n})'),keys=(f'out{n}_winding_avg',f'out{n}_winding_rms',f'out{n}_winding_peak'))
        add(f'i(xd_o{n}:dmain)',f'OUT{n} 整流管导通','conduction',(f'v(rect{n})',f'v(cap{n})'),
            (f'out{n}_rectifier_avg',f'out{n}_rectifier_rms',f'out{n}_rectifier_peak'))
        add(f'i(xd_o{n}:cj)',f'OUT{n} 整流管 Cj 位移电流','displacement',(f'v(rect{n})',f'v(cap{n})'))
        add(f'i(c_par_s{n})',f'OUT{n} 绕组电容位移电流','displacement')
        add(f'i(r_par_d{n})',f'OUT{n} 整流 RC 支路','snubber')
        vo,sg=trace(f'v(out{n})'),trace('v(sgnd)')
        outputs.append(dict(id=n,mean_voltage_V=(float(np.sum(dt*((vo-sg)[:-1]+(vo-sg)[1:])/2)/span)
            if vo is not None and sg is not None else None)))
    return dict(available=primary is not None,start_s=start,end_s=end,periods=len(cycles),
        frequency_hz=len(cycles)/span,measurements=measurements,signals=signals,outputs=outputs,
        scope='完整实际门极周期；原始自适应采样分段线性积分，保留全部峰值和负电流。绕组、沟道导通和电容位移电流分别统计；电容支路有功可正可负。')


def charge_balance(audit, case, relative_limit=.01, absolute_limit_A=1e-6):
    """Steady current comparison requires zero mean capacitor charging.

    The exported nominal fixture is resistive. Compare winding charge with
    actual port voltage / the frozen resistance, not its nominal power/V.
    Parallel parasitic capacitors carry zero mean current in periodic state.
    """
    result=case['result'];ops=[o['op'] for o in result.get('outputs') or []] or [result['op']]
    rows=[]
    for voltage,op in zip(audit.get('outputs') or [],ops):
        n=voltage['id'];v=voltage['mean_voltage_V'];r=op.get('R')
        current=audit['measurements'].get(f'out{n}_winding_avg')
        valid=v is not None and r and r>0 and current is not None
        load=v/r if valid else None
        residual=current-load if valid else None
        limit=max(absolute_limit_A,abs(load)*relative_limit) if valid else None
        rows.append(dict(id=n,winding_mean_A=current,load_mean_A=load,charging_mean_A=residual,
            limit_A=limit,relative_percent=100*abs(residual)/max(abs(load),absolute_limit_A) if valid else None,
            passed=bool(valid and abs(residual)<=limit)))
    passed=len(rows)==len(ops) and all(r['passed'] for r in rows)
    return dict(passed=passed,rows=rows,relative_limit_percent=relative_limit*100,absolute_limit_A=absolute_limit_A,
                reason='逐路周期电荷平衡通过' if passed else '输出电容仍有净充放电或缺少电荷证据，电流稳态对比待完成')


def startup_gate_current(raw, step_s, gate_voltage, *, output_count=1, feedback_output=1):
    """Maximum observed winding current 50 ns before a resolved startup turn-on.

    Both interpolation intervals must be at most 100 ns and the measured gate
    must still be low. Stream the adaptive RAW in blocks. This diagnostic is
    independent of the post-startup periodicity and FRA acceptance checks.
    """
    offset = 50e-9
    time = raw.time
    end = min(float(time[-1]), step_s)
    stop = int(np.searchsorted(time, end, side='right'))
    chunk = 65536
    if not 1<=feedback_output<=output_count<=6:
        raise ValueError('QR开通检查的输出路数/反馈编号无效')
    info = dict(available=False, offset_s=offset, end_s=end, total_edges=0, observed_edges=0,
                feedback_output=feedback_output, windings={})
    try:
        drain, sense = raw.trace('v(drain)'), raw.trace('v(sense)')
    except KeyError:
        drain = None
    if drain is not None:
        peak_v = -np.inf
        for first in range(0, len(time), chunk):
            vds = np.subtract(drain[first:first+chunk], sense[first:first+chunk], dtype=float)
            if not np.isfinite(vds).all():
                break
            peak = int(np.argmax(vds))
            if vds[peak] > peak_v:
                peak_v, peak_t = float(vds[peak]), float(time[first+peak])
        else:
            info.update(vds_peak_full_v=peak_v, vds_peak_full_s=peak_t)
    try:
        softstart = raw.trace('v(ss)')
        gate, sense = raw.trace('v(gate)'), raw.trace('v(sense)')
    except KeyError as exc:
        info['reason'] = '启动开通检查缺少探针 '+str(exc)
        return info
    windings={}
    for index in range(1,output_count+1):
        row=info['windings'][f'OUT{index}']=dict(available=False)
        try:windings[index]=raw.trace(f'i(ls{index})')
        except KeyError:row['reason']=f'缺少副边电流探针 i(ls{index})'
    for first in range(0, stop, chunk):
        full = np.flatnonzero(softstart[first:min(first+chunk, stop)] >= .999)
        if full.size:
            stop = first + int(full[0]) + 1
            end = float(time[stop-1])
            break
    info['end_s'] = end
    threshold = gate_voltage / 2
    for first in range(1, stop, chunk):
        last = min(first + chunk, stop)
        vgs = gate[first-1:last] - sense[first-1:last]
        local = np.flatnonzero((vgs[:-1] < threshold) & (vgs[1:] >= threshold))
        info['total_edges'] += int(local.size)
        if not local.size:
            continue
        left = first - 1 + local
        rise_gap = time[left+1] - time[left]
        edges = time[left] + rise_gap * (threshold-vgs[local])/(vgs[local+1]-vgs[local])
        probe = edges - offset
        right = np.clip(np.searchsorted(time, probe, side='right'), 1, len(time)-1)
        gap = time[right] - time[right-1]
        weight = np.divide(probe-time[right-1], gap, out=np.zeros_like(gap), where=gap>0)
        g0 = gate[right-1] - sense[right-1]
        vgs_pre = g0 + weight*(gate[right]-sense[right]-g0)
        resolved = ((rise_gap <= 2*offset) & (gap > 0) & (gap <= 2*offset)
                    & (probe >= time[0]) & (vgs_pre < .1*gate_voltage))
        info['observed_edges'] += int(np.count_nonzero(resolved))
        if not resolved.any():
            continue
        for index,winding in windings.items():
            row=info['windings'][f'OUT{index}']
            i0 = winding[right-1]
            current = (i0 + weight*(winding[right]-i0))[resolved]
            peak = int(np.argmax(current))
            if not row['available'] or current[peak] > row['max_pre_current_a']:
                row.update(available=True,max_pre_current_a=float(current[peak]),
                           max_gate_rise_s=float(edges[resolved][peak]))
                if index==feedback_output:
                    info.update(available=True,max_pre_current_a=row['max_pre_current_a'],
                                max_gate_rise_s=row['max_gate_rise_s'])
    info['all_windings_observed']=all(r['available'] for r in info['windings'].values())
    if not info['available']:
        info['reason'] = '启动窗内未取得可分辨的开通前副边电流'
    return info


def cycle_quality(raw,frequency,start,end,gate_voltage=10,cycles=64,tolerance_pct=5):
    lo,hi=np.searchsorted(raw.time,[start,end]);t=raw.time[lo:hi]
    gate=raw.trace('v(gate)')[lo:hi]-raw.trace('v(sense)')[lo:hi]
    current=raw.trace('i(lp)')[lo:hi]
    vds=raw.trace('v(drain)')[lo:hi]-raw.trace('v(sense)')[lo:hi]
    indices=np.flatnonzero(np.diff((gate>gate_voltage/2).astype(np.int8)))
    edges=t[indices]+(gate_voltage/2-gate[indices])*(t[indices+1]-t[indices])/(gate[indices+1]-gate[indices])
    rising=edges[gate[indices+1]>gate_voltage/2];falling=edges[gate[indices+1]<gate_voltage/2]
    rising=rising[-cycles-1:];rows=[]
    for number,(a,b) in enumerate(zip(rising[:-1],rising[1:])):
        fall=falling[(falling>a)&(falling<b)]
        if len(fall)!=1:continue
        f=float(fall[0]);i,j=np.searchsorted(t,[a,f]);k=np.searchsorted(t,b)
        # Both measurements refer to the next turn-on (b). A clock-based
        # window can include the previous turn-off, when Vds is still low.
        before=b-50e-9
        v_before=float(np.interp(before,t,vds)) if before>f else None
        tail=np.searchsorted(t,(f+b)/2)
        off_vds=vds[tail:k][gate[tail:k]<.1*gate_voltage]
        rows.append(dict(clock=number,start_s=float(a),end_s=float(b),ton_s=f-a,period_s=float(b-a),
            frequency_hz=float(1/(b-a)),duty=float((f-a)/(b-a)),peak=float(max(current[i:j],default=0)),pulses=1,
            turnon_vds_v=v_before,valley_vds_v=float(np.min(off_vds)) if off_vds.size else None))
    empty=dict(stable=False,reason='QR 门极有效周期不足',cycles=rows,duty_min=0.,duty_max=0.,
        duty_span_percent=0.,peak_span_percent=0.,alternation_percent=0.)
    if len(rows)<8:return empty
    duty=np.array([r['duty'] for r in rows]);peak=np.array([r['peak'] for r in rows]);freq=np.array([r['frequency_hz'] for r in rows])
    def spread(x):return float(np.ptp(x)/max(abs(float(np.mean(x))),1e-9)*100)
    alternation=float(abs(np.mean(peak[::2])-np.mean(peak[1::2]))/max(float(np.mean(peak)),1e-9)*100)
    # Regular valley skipping is valid nonlinear operation, but not a single-
    # periodic linearisation point for FRA. Report it without a stability claim.
    repeat=max(spread(duty),spread(peak),spread(freq))<tolerance_pct
    def observed_mean(key):
        values=[r[key] for r in rows if r[key] is not None]
        return float(np.mean(values)) if values else None
    return dict(stable=repeat,reason='QR 实际边沿逐周期重复性通过' if repeat else 'QR 变频／跳谷或周期波动，需复核',
        cycles=rows,duty_min=float(min(duty)),duty_max=float(max(duty)),duty_span_percent=spread(duty),
        peak_span_percent=spread(peak),alternation_percent=alternation,
        frequency_mean_hz=float(len(rows)/sum(r['period_s'] for r in rows)),frequency_min_hz=float(min(freq)),
        frequency_max_hz=float(max(freq)),turnon_vds_mean_v=observed_mean('turnon_vds_v'),
        valley_vds_mean_v=observed_mean('valley_vds_v'),valley_window='off_tail_gate_low',
        note='QR 周期取实际门极上升沿；变频或跳谷并不直接等于环路不稳定。')
