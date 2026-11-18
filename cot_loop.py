"""Balanced small-signal voltage loop of the generic Buck COT cadence model."""

import math
from types import SimpleNamespace

import numpy as np

from capacitor_banks import bank
from cot_settings import configured_gains, configuration


def recommended_fc_max(op):
    return op['f_sw']/20


def controller_gains(p, op):
    """Return cadence PI gains per unit error, shared with the switching model."""
    kp, ki = configured_gains(p)
    if ki:
        return kp, ki
    cot = op['cot']
    c_total = sum(row['C'] for row in bank(p))
    f_lc = 1 / (2*math.pi*math.sqrt(op['L']*c_total/cot['phases']))
    f_ref = cot['target_frequency_Hz']
    f_int = min(800., f_ref/50, f_lc/10)
    return .15*f_ref, 2*math.pi*f_ref*f_int


def _power_stage_legacy(p, op):
    import control as ct
    from output_capacitors import build_output_filters

    cot = op['cot']
    phases = cot['phases']
    ton = cot['ton_s']
    minimum_off = max(cot['min_off_s'], 2e-9, ton*.0001)
    if cot['toff_s'] <= minimum_off*(1 + 1e-12):
        raise ValueError('COT 已到最小关断时间，触发频率受限，无法计算双向小信号裕度')
    load = op['R']  # Port load slope also applies before a fixed forward drop.
    v_set = cot['output_cap_voltage_V']
    r_high = max(p['Rds_on'], 1e-6) + p.get('Rs', 0.)
    r_low = max(p['Rds_aux'], 1e-6)
    r_avg = (op['D']*r_high + op['Dp']*r_low + cot['phase_dcr_ohm'])/phases
    inductance = op['L']/phases
    v_delta = cot['bus_voltage_V'] - (r_high-r_low)*cot['phase_current_avg_A']

    include_esl = (p.get('spice_config') or {}).get('include_cap_esl') == 1
    caps = [dict(row, ESL=row['ESL'] if include_esl else 0.) for row in bank(p)]
    series_l = [row for row in caps if row['ESL']]
    series_rc = [row for row in caps if not row['ESL']]
    output_rc = (build_output_filters([{'output_capacitors': series_rc}], [load], [v_set])
                 if series_rc else None)
    rc_count = len(output_rc.A) if output_rc else 0
    esl_count = len(series_l)
    rc = slice(1, 1 + rc_count)
    n = 1 + rc_count + 2*esl_count
    esl_current = np.arange(1 + rc_count, 1 + rc_count + esl_count)
    esl_voltage = esl_current + esl_count

    a = np.zeros((n, n))
    b = np.zeros((n, 1))
    c = np.zeros(n)
    c[0] = output_rc.D[0, 0] if output_rc else load
    c[esl_current] = -c[0]
    if output_rc:
        c[rc] = output_rc.C[0]
        a[rc, rc] = output_rc.A
        a[rc, 0] = output_rc.B[:, 0]
        a[rc, esl_current] = -output_rc.B
    for current, voltage, row in zip(esl_current, esl_voltage, series_l):
        # v_cap1 = ESR * i_branch + ESL * di_branch/dt + v_internal.
        a[current] = c/row['ESL']
        a[current, current] -= row['ESR']/row['ESL']
        a[current, voltage] -= 1/row['ESL']
        a[voltage, current] = 1/row['C']
    # State 0 is the sum of all phase currents. During a cadence variation
    # at fixed input and reference, incremental duty = Ton * incremental rate.
    a[0] = -c/inductance
    a[0, 0] -= r_avg/inductance
    b[0, 0] = v_delta*ton/inductance
    plant = ct.ss(a, b, c[None, :], [[0.]])
    load_b=np.zeros((n,1)); feed=-float(output_rc.D[0,0] if output_rc else load)
    load_b[0,0]=-feed/inductance
    if output_rc:load_b[rc,0]=-output_rc.B[:,0]
    for current,row in zip(esl_current,series_l):load_b[current,0]=feed/row['ESL']
    plant._load_b=load_b; plant._load_d=feed
    return plant, caps


def _power_stage(p,op):
    """N phase averaged plant, with measured-current feedback and finite sharing."""
    import control as ct
    from output_capacitors import build_output_filters
    cfg=configuration(p); cot=op['cot']; rows=cot.get('phase_data')
    if rows and cfg['phase_limit_A'] and any(r['sense_gain']*r['current_peak_A']+r['sense_offset_A']>=cfg['phase_limit_A'] for r in rows):
        raise ValueError('COT 工作点已触及逐相限流，小信号未限幅环路不适用')
    if rows and cfg['light_load']=='diode_emulation' and any(r['current_valley_A']<0 for r in rows):
        raise ValueError('COT 二极管模拟已进入零电流区，连续导通平均环路不适用')
    changed=any(any(abs(r[k]-v)>1e-14 for k,v in __import__('cot_settings').PHASE_DEFAULTS.items())
                for r in cfg['phase_parameters'])
    if not rows or (not changed and not cfg['balance_gain_v_per_a'] and cfg['model']=='cadence_pi'
                    and cfg['load_mode']=='resistance'):
        return _power_stage_legacy(p,op)
    if any(r['toff_s']<=max(cot['min_off_s'],2e-9)* (1+1e-12) for r in rows):
        raise ValueError('COT 某相已到最小关断时间，无法计算双向小信号裕度')
    if cfg['light_load']=='diode_emulation' and any(r['current_valley_A']<0 for r in rows):
        raise ValueError('COT 二极管模拟已进入零电流区，连续导通平均环路不适用')
    load=op['R'] if cfg['load_mode']=='resistance' else 1e15
    esl=(p.get('spice_config') or {}).get('include_cap_esl')==1
    caps=[dict(row,ESL=row['ESL'] if esl else 0.) for row in bank(p)]
    sl=[r for r in caps if r['ESL']]; sr=[r for r in caps if not r['ESL']]
    rc_model=build_output_filters([{'output_capacitors':sr}],[load],[cot['output_cap_voltage_V']]) if sr else None
    n=len(rows); nr=len(rc_model.A) if rc_model else 0; nl=len(sl)
    rc=slice(n,n+nr); il=np.arange(n+nr,n+nr+nl); vl=il+nl
    balance=cfg['balance_gain_v_per_a']>0
    base=n+nr+2*nl; trim=np.arange(base,base+n) if balance else np.array([],dtype=int)
    total_index=base+len(trim)
    current_feedback=cfg['model']=='current_feedback'
    size=total_index+int(current_feedback)
    a=np.zeros((size,size)); b=np.zeros((size,1)); c=np.zeros(size)
    rport=rc_model.D[0,0] if rc_model else load
    c[:n]=rport; c[il]=-rport
    if rc_model:
        c[rc]=rc_model.C[0]; a[rc,rc]=rc_model.A
        a[rc,:n]=np.tile(rc_model.B,(1,n)); a[rc,il]=-rc_model.B
    for ix,iv,row in zip(il,vl,sl):
        a[ix]=c/row['ESL']; a[ix,ix]-=row['ESR']/row['ESL']; a[ix,iv]-=1/row['ESL']
        a[iv,ix]=1/row['C']
    sensed=np.array([r['sense_gain'] for r in rows]); bus=cot['bus_voltage_V']
    for i,r in enumerate(rows):
        l=r['L_H']; d=r['duty']; rh=r['rhigh_ohm']+r['rs_ohm']; rl=r['rlow_ohm']
        vdelta=bus-r['current_avg_A']*(rh-rl)
        drive=vdelta*cot.get('base_ton_s',cot['ton_s'])*r['ton_scale']/l
        a[i]=-c/l; a[i,i]-=(d*rh+(1-d)*rl+r['dcr_ohm'])/l
        b[i,0]=drive
        if current_feedback:a[i,total_index]-=drive*cfg['current_feedback_hz_per_a']
        if balance:
            a[i,trim[i]]=vdelta/l
            pole=2*math.pi*cfg['balance_bandwidth_hz']; a[trim[i],trim[i]]=-pole
            if not r['trim_saturated']:
                a[trim[i],:n]=pole*cfg['balance_gain_v_per_a']/bus*sensed/n
                a[trim[i],i]-=pole*cfg['balance_gain_v_per_a']/bus*sensed[i]
    if current_feedback:
        pole=2*math.pi*cfg['current_filter_hz']; a[total_index,:n]=pole*sensed
        a[total_index,total_index]=-pole
    plant=ct.ss(a,b,c[None,:],[[0.]])
    load_b=np.zeros((size,1)); feed=-float(rport)
    for i,r in enumerate(rows):load_b[i,0]=-feed/r['L_H']
    if rc_model:load_b[rc,0]=-rc_model.B[:,0]
    for ix,row in zip(il,sl):load_b[ix,0]=feed/row['ESL']
    plant._load_b=load_b; plant._load_d=feed
    plant._phase_current_states=n
    return plant,caps


def transient_response(p,op):
    """Closed-loop small-signal load step, independently of charge sizing screen."""
    import control as ct
    cfg=configuration(p); dyn=cfg['dynamic']
    if dyn['step_A']<=0:return None
    plant,_=_power_stage(p,op); kp,ki=controller_gains(p,op)
    vset=op['cot']['output_cap_voltage_V']; a,b,c=plant.A,plant.B,plant.C
    n=len(a); load_b=plant._load_b; load_d=plant._load_d
    acl=np.zeros((n+1,n+1)); acl[:n,:n]=a-b@(kp/vset*c); acl[:n,n]=b[:,0]
    acl[n,:n]=-ki/vset*c[0]
    bcl=np.zeros((n+1,1)); bcl[:n]=load_b-b*(kp/vset*load_d); bcl[n,0]=-ki/vset*load_d
    cc=np.r_[c[0],0.][None,:]
    poles=np.linalg.eigvals(acl)
    if max(poles.real)>=0:return dict(available=False,reason='负载响应的平均闭环存在非稳定极点')
    slow=max(.01,float(-max(poles.real)))
    stop=min(.5,max(200/op['f_sw'],8/slow,20*dyn['rise_s']))
    t=np.linspace(0,stop,1201)
    step=dyn['step_A']*np.minimum(t/max(dyn['rise_s'],1e-12),1.)
    sys=ct.ss(acl,bcl,cc,[[load_d]])
    response=ct.forced_response(sys,t,step)
    voltage=np.asarray(response.outputs).reshape(-1)
    zout=sys(2j*np.pi*np.geomspace(1,max(1.1,op['f_sw']/10),120))
    tolerance=max(dyn['droop_V']*.02,op['V_out']*.001)
    indices=np.flatnonzero(np.abs(voltage)>tolerance)
    settling=float(t[min(indices[-1]+1,len(t)-1)]) if len(indices) else 0.
    return dict(available=True,time_s=t.tolist(),voltage_delta_V=voltage.tolist(),
                droop_V=float(max(0,-min(voltage))),overshoot_V=float(max(0,max(voltage))),
                settling_s=settling,settled=bool(not len(indices) or indices[-1]<len(t)-1),
                zout_frequency_Hz=np.geomspace(1,max(1.1,op['f_sw']/10),120).tolist(),
                zout_magnitude_ohm=np.abs(zout).tolist(),
                note='连续导通平均闭环小信号负载增量；降载响应反号。不含保护/触发限幅，延迟电荷边界另列。')


def build_loop(p, op):
    import control as ct

    plant, caps = _power_stage(p, op)
    cot = op['cot']
    cfg=configuration(p)
    kp, ki = controller_gains(p, op)
    v_set = cot['output_cap_voltage_V']
    # Command in Hz from a physical voltage error. A zero Kp is a pure integrator.
    compensator = ct.ss([[0.]], [[ki/v_set]], [[1.]], [[kp/v_set]])
    fs = op['f_sw']
    esl = any(row['ESL'] > 0 for row in caps)
    note = ('通用 Buck COT 电压环低频平均模型。逐相电感/电阻/采样失配与有限带宽均流，固定活动相数，'
            'PI 以防反管前电容端电压误差改变每相触发频率。'
            '按本工况的导通时间线性化，保留每颗输出电容的 ESR'
            + (' 和已启用的 ESL。' if esl else '。') +
            '适用于未触及频率限幅的连续导通小扰动。输入R/L/C动态互动、死区换流、减相、跳脉冲及芯片专用纹波注入未包含。'
            + ('总电流负反馈采用公开电流反馈结构的低频行为等效，非原厂芯片模型。' if cfg['model']=='current_feedback' else ''))
    c_total = sum(row['C'] for row in caps)
    low_esr = sum(row['ESR']*row['C']**2 for row in caps)/c_total**2
    capacitor_states=_capacitor_state_count(caps,op['R'])
    bank_summary = dict(output=1, branches=caps, states=capacitor_states, capacitance=c_total,
                        low_frequency_esr=low_esr,
                        esr_zero_estimate_hz=1/(2*math.pi*c_total*low_esr) if low_esr else None)
    details = dict(
        kind='cot-cadence-pi', assumptions=note, frequency_limit=fs/10,
        recommended_fc_max=recommended_fc_max(op), bandwidth_limit_enabled=True, experimental=False,
        feedback_output=1, outputs=[dict(id=1, name='OUT1', voltage=op['V_out'], current=op['I_out'])],
        plant_input='cadence_Hz', plant_output='output_cap_voltage_V',
        phases=cot['phases'], phase_frequency_hz=fs, ton_s=cot['ton_s'], feedback_voltage_V=v_set,
        cot_kp_hz=kp, cot_ki_hz_per_s=ki, gain_source='manual' if configured_gains(p)[1] else 'default',
        control_structure=cfg['model'],controller_reference=cfg['controller_reference'],
        current_feedback_hz_per_a=cfg['current_feedback_hz_per_a'],
        balance_bandwidth_hz=cfg['balance_bandwidth_hz'],
        phase_current_states=getattr(plant,'_phase_current_states',1),
        esr_included=True, esl_included=esl, capacitor_banks=[bank_summary],
        capacitor_states=capacitor_states, state_count=plant.nstates,
    )
    plant._loop_metadata = details
    all_esl = all(row['ESL'] > 0 for row in caps)
    if cfg['load_mode'] == 'current' and all_esl:
        # With no resistive shunt, the ideal current step forces a jump in
        # an inductive branch current. The legacy finite-shunt approximation
        # is ill-conditioned for a load-disturbance waveform in this case.
        plant._load_response_unavailable_reason = (
            '恒流负载且各电容支路均含 ESL，理想电流阶跃在输出端形成冲激。')
    else:
        # Positive disturbance current is drawn at the load. The feedback
        # voltage is observed at the pre-diode capacitor node.
        plant._load_disturbance = ct.ss(plant.A, plant._load_b, plant.C, [[plant._load_d]])
    plant._load_response_note = ('COT 固定活动相数并按当前导通时间线性化，'
                                 '沿用当前均流、负载和电容模型。')
    if all_esl and cfg['load_mode'] == 'resistance':
        plant._load_response_note += '各电容支路均含 ESL，理想阶跃边沿的电压跳变取决于负载电阻。'
    return (plant, compensator, plant*compensator), SimpleNamespace(
        model_note=note, loop_metadata=details, mode=op['mode'])


def _capacitor_state_count(caps,load):
    from output_capacitors import build_output_filters
    rc=[r for r in caps if not r['ESL']]
    states=len(build_output_filters([{'output_capacitors':rc}],[load],[1.]).A) if rc else 0
    return states+2*sum(r['ESL']>0 for r in caps)


def tune(p, op, fc, pm):
    """Fit nonnegative PI gains to the requested crossover and phase margin."""
    from loop_tuning import analyze_loop, plant_phase_unwrapped

    max_fc = recommended_fc_max(op)
    if not math.isfinite(fc) or not .01 < fc <= max_fc:
        raise ValueError(f'COT 目标穿越频率需大于 0.01 Hz 且不高于 {max_fc:.4g} Hz（每相开关频率的 1/20）')
    if not math.isfinite(pm) or not 0 < pm < 180:
        raise ValueError('COT 目标相位裕度须在 0° 与 180° 之间')
    plant, _ = _power_stage(p, op)
    phase = plant_phase_unwrapped(plant, fc)
    # A PI with Ki > 0 can contribute between -90° (Kp=0) and 0° (exclusive).
    required = pm - 180 - phase
    if not -90-1e-8 <= required < 0:
        raise ValueError(f'COT PI 在 {fc:.4g} Hz 可达到的相位裕度为 '
                         f'{90+phase:.1f}° 至 {180+phase:.1f}°（上限不含），请调整目标')
    w = 2*math.pi*fc
    gain = op['cot']['output_cap_voltage_V']/float(abs(plant(1j*w)))
    angle = -math.pi/2 if math.isclose(required, -90., abs_tol=1e-8) else math.radians(required)
    kp = 0. if angle == -math.pi/2 else gain*math.cos(angle)
    ki = -w*gain*math.sin(angle)
    tuned = dict(p, cot_kp_hz=kp, cot_ki_hz_per_s=ki, fc_target=fc)
    models, _ = build_loop(tuned, op)
    margins = analyze_loop(tuned, models, op)
    measured_fc, measured_pm = margins['fc'], margins['pm']
    if (not margins['closed_loop_stable'] or measured_fc is None or
            not math.isclose(measured_fc, fc, rel_tol=.005) or
            not math.isclose(measured_pm, pm, abs_tol=.5) or
            margins['min_pm'] < pm-.5):
        raise ValueError('该 COT PI 目标未通过闭环稳定性与交越复核，请调整穿越频率或相位裕度')
    return dict(cot_kp_hz=kp, cot_ki_hz_per_s=ki, fc=measured_fc, pm=measured_pm, gm_db=margins['gm_db'])
