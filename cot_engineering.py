"""Per-phase COT equilibrium and engineering constraints, all quantities in SI.

The trim is a bounded proportional current-sharing voltage command, filtered
by a first-order pole in the small-signal and switching models. It is a public
behavioral contract, not a reproduction of a manufacturer's internal circuit.
"""
import math
import numpy as np
from cot_settings import configuration


def phase_hardware(p, dcr):
    cfg = configuration(p)
    return [dict(id=i+1, L_H=p['L']*r['L_scale'], dcr_ohm=dcr*r['dcr_scale'],
                 rhigh_ohm=p['Rds_on']*r['rhigh_scale'], rlow_ohm=p['Rds_aux']*r['rlow_scale'],
                 rs_ohm=p['Rs'], ton_scale=r['ton_scale'], sense_gain=r['sense_gain'],
                 sense_offset_A=r['sense_offset_A']) for i,r in enumerate(cfg['phase_parameters'])]


def equilibrium(p, base, dcr):
    """Solve shared frequency, phase currents and bounded pulse-width trims."""
    from scipy.optimize import least_squares

    cfg = configuration(p)
    rows = phase_hardware(p,dcr)
    n = len(rows)
    bus, cap = base['bus_voltage_V'], base['output_cap_voltage_V']
    total, ton = p['P_out']/p['V_out'], base['ton_s']
    gain, bound = cfg['balance_gain_v_per_a'], cfg['balance_max_duty']
    scales = np.array([r['ton_scale'] for r in rows])
    sensed_gain = np.array([r['sense_gain'] for r in rows])
    sensed_offset = np.array([r['sense_offset_A'] for r in rows])
    high = np.array([r['rhigh_ohm']+r['rs_ohm'] for r in rows])
    low = np.array([r['rlow_ohm'] for r in rows])
    resistance = np.array([r['dcr_ohm'] for r in rows])

    def state(x):
        currents=x[:n]
        local_bus=x[n+1]
        local_ton=p.get('cot_ton_s',0.) or cap/(local_bus*p['f_sw'])
        sensed=currents*sensed_gain+sensed_offset
        raw_trim=gain/local_bus*(sensed.mean()-sensed)
        trim=np.clip(raw_trim,-bound,bound)
        duty=x[n]*local_ton/ton*scales+trim
        return currents,sensed,raw_trim,trim,duty,local_bus,local_ton

    def residual(x):
        currents,_,_,_,duty,local_bus,_=state(x)
        v=duty*(local_bus-currents*(high-low))-cap-currents*(low+resistance)
        if cfg['dead_time_s']:
            frequency=x[n]/ton
            ripple=(local_bus-cap-currents*(high+resistance))*duty/frequency/np.array([r['L_H'] for r in rows])
            correction=np.zeros(n)
            # Same finite-body-diode resistance as the generic switching deck.
            # Two dead windows replace low-channel voltage. Edge polarity
            # chooses the low-side or high-side body diode respectively.
            for edge in (currents-ripple/2,currents+ripple/2):
                vf=cfg['body_diode_V']+.005*np.abs(edge)
                node=np.where(edge>=0,-vf,local_bus+vf)
                correction+=node+currents*low
            v+=cfg['dead_time_s']*frequency*correction
        source=local_bus-bus+cfg['source_resistance_ohm']*float(np.sum(duty*currents))
        return np.r_[v/bus,(currents.sum()-total)/max(total,1.),source/bus]

    nominal=base['phase_current_avg_A']
    d0=base['ton_s']/(base['ton_s']+base['toff_s'])
    seed=np.r_[np.full(n,nominal),d0,bus]
    # With exactly zero branch resistance and no trim, static sharing is not
    # determined electrically. The previous equal-current ideal convention is
    # retained only for perfectly identical ideal legs.
    ideal=not np.any(high+low+resistance) and gain==0 and cfg['dead_time_s']==0
    if ideal and not np.allclose(scales,scales[0],rtol=0,atol=1e-14):
        raise ValueError('零电阻理想支路存在导通时间失配，无有限直流均流解；请填写实际 DCR/Rds')
    solved=least_squares(residual,seed,xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=300)
    if not solved.success or np.max(np.abs(residual(solved.x)))>1e-7:
        raise ValueError('COT 各相伏秒/电流平衡未收敛，请检查失配和均流修正范围')
    currents,sensed,raw_trim,trim,duty,actual_bus,actual_ton=state(solved.x)
    if actual_bus<=cap:
        raise ValueError('源电阻压降后，COT 输入母线低于输出设定')
    frequency=solved.x[n]/ton
    if frequency<=0 or np.any(duty<=0) or np.any(duty>=1):
        raise ValueError('COT 各相要求的占空比超出 (0,1)，无法保持规定输出')
    for i,row in enumerate(rows):
        on=duty[i]/frequency
        off=(1-duty[i])/frequency
        if off < base['min_off_s']*(1-1e-10):
            raise ValueError(f'第 {i+1} 相关断时间小于最小关断时间')
        rise=actual_bus-cap-currents[i]*(high[i]+resistance[i])
        fall_channel=cap+currents[i]*(low[i]+resistance[i])
        fall=rise*on/off  # Average over channel and the two explicit dead windows.
        if rise<=0 or fall<=0:
            raise ValueError(f'第 {i+1} 相电感电压缺少升降斜率余量')
        ripple=rise*on/row['L_H']
        square=currents[i]**2+ripple**2/12
        hi_block=actual_bus+low[i]*(currents[i]+ripple/2)
        lo_block=actual_bus-high[i]*(currents[i]-ripple/2)
        if cfg['dead_time_s']:
            for edge in (currents[i]-ripple/2,currents[i]+ripple/2):
                diode_block=actual_bus+cfg['body_diode_V']+.005*abs(edge)
                if edge>=0:hi_block=max(hi_block,diode_block)
                else:lo_block=max(lo_block,diode_block)
        row.update(current_avg_A=float(currents[i]), sensed_current_A=float(sensed[i]),
                   current_peak_A=float(currents[i]+ripple/2),current_valley_A=float(currents[i]-ripple/2),
                   current_rms_A=math.sqrt(square), high_rms_A=math.sqrt(duty[i]*square),
                   low_rms_A=math.sqrt((1-duty[i])*square), duty=float(duty[i]), ton_s=float(on),
                   toff_s=float(off), ripple_A=float(ripple), trim_duty=float(trim[i]),
                   trim_saturated=bool(abs(raw_trim[i]) >= bound*(1-1e-9) and gain>0),
                   frequency_Hz=float(frequency), rise_voltage_V=float(rise),fall_voltage_V=float(fall),
                   fall_channel_voltage_V=float(fall_channel),
                   bus_voltage_V=float(actual_bus),base_ton_s=float(actual_ton),
                   dead_time_s=cfg['dead_time_s'],
                   high_block_V=float(hi_block),low_block_V=float(lo_block))
    return rows


def aggregate_extrema(rows):
    """Exact extrema of the piecewise-linear periodic aggregate current."""
    n=len(rows)
    knots=sorted(set([0.,1.]+[i/n for i in range(n)]+[(i/n+r['duty'])%1 for i,r in enumerate(rows)]))
    samples=[]
    for t in knots:
        value=0.
        for i,row in enumerate(rows):
            u=(t-i/n)%1
            shape=u/row['duty'] if u<row['duty'] else (1-u)/(1-row['duty'])
            value+=row['current_valley_A']+row['ripple_A']*shape
        samples.append(value)
    return max(samples)-min(samples)


def charge_ripple(rows):
    """Exact peak-to-peak capacitor charge, including imperfect cancellation."""
    n=len(rows); total=sum(r['current_avg_A'] for r in rows)
    knots=sorted(set([0.,1.]+[i/n for i in range(n)]+[(i/n+r['duty'])%1 for i,r in enumerate(rows)]))
    def current(t):
        value=0.
        for i,row in enumerate(rows):
            u=(t-i/n)%1
            shape=u/row['duty'] if u<row['duty'] else (1-u)/(1-row['duty'])
            value+=row['current_valley_A']+row['ripple_A']*shape
        return value-total
    frequency=rows[0]['frequency_Hz']; charge=0.; extremes=[0.]
    for a,b in zip(knots,knots[1:]):
        ia,ib=current(a),current(b); dt=(b-a)/frequency
        if ia*ib<0:
            fraction=-ia/(ib-ia)
            extremes.append(charge+.5*ia*dt*fraction)
        charge+=(ia+ib)*dt/2; extremes.append(charge)
    return max(extremes)-min(extremes)


def constraints(p,op):
    """Dynamic capacitor screen and phase-aware protection margins."""
    from capacitor_banks import bank
    cfg=configuration(p); rows=op['cot']['phase_data']; dyn=cfg['dynamic']
    capacitors=bank(p); total_c=sum(r['C'] for r in capacitors)
    # Instantaneous parallel ESR is the high-frequency series-resistance bound
    # for this charge calculation; ESL is separately checked by time response.
    esr=0. if any(r['ESR']==0 for r in capacitors) else 1/sum(1/r['ESR'] for r in capacitors)
    delta=dyn['step_A']; delay=dyn['delay_s']; rise=dyn['rise_s']
    up=sum(r['rise_voltage_V']/r['L_H'] for r in rows)
    down=sum(r['fall_voltage_V']/r['L_H'] for r in rows)
    # Conservative step bound. Slew is recorded but a zero-rise edge is used
    # for sizing; a finite edge can only reduce the charge deficit for a
    # monotonically increasing/decreasing load under this slew model.
    q_up=delta*delay+delta*delta/(2*up)
    q_down=delta*delay+delta*delta/(2*down)
    def required(q,limit):
        available=limit-delta*esr
        return (q/available if available>0 else None) if delta and limit else None
    transient=dict(enabled=delta>0,step_A=delta,rise_s=rise,delay_s=delay,
                   droop_limit_V=dyn['droop_V'],overshoot_limit_V=dyn['overshoot_V'],
                   capacitance_F=total_c,esr_ohm=esr,
                   charge_deficit_C=q_up,charge_surplus_C=q_down,
                   slew_up_A_per_s=up,slew_down_A_per_s=down,
                   droop_bound_V=delta*esr+q_up/total_c,
                   overshoot_bound_V=delta*esr+q_down/total_c,
                   required_droop_F=required(q_up,dyn['droop_V']),
                   required_overshoot_F=required(q_down,dyn['overshoot_V']),
                   note='假设响应延迟后立即按电感最大斜率调节的电荷初筛；负载边沿按突变。实际控制器恢复由闭环时域与开关仿真另核对。')
    peak=max(r['current_peak_A'] for r in rows)
    mean=op['I_out']/len(rows)
    protection=[]
    for r in rows:
        sampled=r['sense_gain']*r['current_peak_A']+r['sense_offset_A']
        threshold=cfg['phase_limit_A']
        delay_extra=r['rise_voltage_V']/r['L_H']*cfg['limit_delay_s']
        trip=(threshold-r['sense_offset_A'])/r['sense_gain'] if threshold else None
        protection.append(dict(id=r['id'],sampled_peak_A=sampled,limit_A=threshold or None,
                               sample_margin_A=threshold-sampled if threshold else None,
                               effective_trip_A=trip,delay_overshoot_A=delay_extra,
                               delayed_trip_peak_A=trip+delay_extra if trip is not None else None,
                               steady_limit_active=bool(threshold and sampled>=threshold)))
    if delta>0 and not p.get('_skip_cot_transient'):
        from cot_loop import transient_response
        try: transient['closed_loop']=transient_response(p,op)
        except (ValueError,ArithmeticError) as exc: transient['closed_loop']=dict(available=False,reason=str(exc))
    return dict(dynamic=transient,protection=protection,phase_imbalance_pct=100*max(abs(r['current_avg_A']-mean) for r in rows)/mean,
                max_phase_peak_A=peak,max_phase_rms_A=max(r['current_rms_A'] for r in rows),
                max_phase_id=max(rows,key=lambda r:r['current_peak_A'])['id'],
                trim_saturated=any(r['trim_saturated'] for r in rows),configuration=cfg)
