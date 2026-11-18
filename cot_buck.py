"""Synchronous COT phase equilibrium, mismatch and bounded current sharing (SI)."""

import math

import numpy as np


SCOPE = ('逐相参数及采样失配、有限均流修正、源电阻压降和死区平均伏秒，固定活动相数；'
         '各相电流按伏秒/总负载联立求解，支路波形采用平均压降下的分段线性斜坡。'
         '均匀触发的事件频率为 N×fs，失配波形可含 fs 基波。轻载二极管模拟、保护和启停使用开关模型核对。')


def _solve(p, phases, dcr):
    from voltage_nodes import capacitor_voltage, input_drop, attach_nodes

    dcr = float(dcr)
    vin, vout, power = p['V_in'], p['V_out'], p['P_out']
    bus, cap = vin-input_drop(p), capacitor_voltage(p)
    f_target, inductance = p['f_sw'], p['L']
    output = power/vout
    current = output/phases
    r_h, r_l, sense = p['Rds_on'], p.get('Rds_aux', .1), p['Rs']
    v_on = bus-cap-current*(r_h+sense+dcr)
    v_off = cap+current*(r_l+dcr)  # magnitude of falling voltage
    if not v_on > 0 or not v_off > 0:
        raise ValueError('COT Buck 在该工况缺少降压余量，请核对母线、电容端电压和每相导通压降')
    duty = v_off/(v_on+v_off)
    off_duty = v_on/(v_on+v_off)
    configured = float(p.get('cot_ton_s', 0.))
    t_on = configured or cap/(bus*f_target)
    t_off = t_on*off_duty/duty
    min_off = float(p.get('cot_min_off_s', 0.))
    if t_off < min_off and not math.isclose(t_off, min_off, rel_tol=1e-12):
        raise ValueError(f'COT 所需关断时间 {t_off*1e9:.3g} ns 小于设置的最小关断时间 {min_off*1e9:.3g} ns')
    period = t_on+t_off
    frequency = 1./period
    delta = v_on*t_on/inductance
    peak, valley = current+delta/2., current-delta/2.
    mean_square = current**2+delta**2/12.
    high_rms = math.sqrt(duty*mean_square)
    low_rms = math.sqrt(off_duty*mean_square)
    # ND = whole simultaneously active phases plus an extra active phase
    # for a fraction of the aggregate period. The total current ramps over
    # that fraction with voltage slope (1-frac)(v_on+v_off)/L.
    phase_duty = phases*duty
    fraction = 0. if math.isclose(phase_duty, round(phase_duty), abs_tol=1e-12, rel_tol=0.) else phase_duty % 1.
    residual = (v_on+v_off)*period*fraction*(1.-fraction)/(phases*inductance)
    ripple_frequency = phases*frequency
    ripple_target = p.get('ripple_target', .01)*vout
    if ripple_target:
        capacitance_min = residual/(8.*ripple_frequency*ripple_target)
    else:
        capacitance_min = math.inf if residual else 0.
    efficiency = p.get('eta_guess', .93)
    estimated_input = power/efficiency
    ring = p.get('ring_margin', .30)
    high_block = bus+r_l*peak
    low_block = bus-(r_h+sense)*valley
    cot = dict(phases=phases, adaptive=not configured, ton_s=t_on, toff_s=t_off, min_off_s=min_off,
               target_frequency_Hz=f_target, ripple_frequency_Hz=ripple_frequency,
               phase_shift_deg=360./phases if phases > 1 else 0., overlap=phase_duty > 1.,
               phase_current_avg_A=current, phase_current_rms_A=math.sqrt(mean_square),
               phase_high_side_rms_A=high_rms, phase_low_side_rms_A=low_rms,
               phase_current_peak_A=peak, phase_current_valley_A=valley, phase_current_ripple_A=delta,
               total_output_current_ripple_A=residual, reverse_current=valley < 0.,
               phase_dcr_ohm=dcr, bus_voltage_V=bus, output_cap_voltage_V=cap,
               high_side_block_V=high_block, low_side_block_V=low_block, scope=SCOPE)
    from cot_engineering import equilibrium, aggregate_extrema, charge_ripple
    phase_data = equilibrium(p, cot, dcr)
    cot['phase_data'] = phase_data
    first=phase_data[0]
    frequency=first['frequency_Hz']; period=1/frequency
    duty=first['duty']; off_duty=1-duty
    current=first['current_avg_A']; delta=first['ripple_A']
    peak=first['current_peak_A']; valley=first['current_valley_A']
    high_rms=first['high_rms_A']; low_rms=first['low_rms_A']
    residual=aggregate_extrema(phase_data)
    capacitance_min=charge_ripple(phase_data)/ripple_target if ripple_target else math.inf
    high_block=max(r['high_block_V'] for r in phase_data)
    low_block=max(r['low_block_V'] for r in phase_data)
    cot.update(ton_s=first['ton_s'],base_ton_s=first['base_ton_s'],toff_s=first['toff_s'],
               bus_voltage_V=first['bus_voltage_V'],
               ripple_frequency_Hz=phases*frequency,phase_current_avg_A=current,
               phase_current_rms_A=first['current_rms_A'],phase_high_side_rms_A=high_rms,
               phase_low_side_rms_A=low_rms,phase_current_peak_A=peak,phase_current_valley_A=valley,
               phase_current_ripple_A=delta,total_output_current_ripple_A=residual,
               reverse_current=any(r['current_valley_A']<0 for r in phase_data),
               overlap=any(r['duty']>1/phases for r in phase_data),
               high_side_block_V=high_block,low_side_block_V=low_block)
    op = dict(topology='BUCK', cot=cot, V_in=vin, V_out=vout, V_out_equiv=cap,
              P_out=power, I_out=output, R=vout/output, R_equiv=cap/output,
              L=inductance, D=duty, Dp=off_duty, f_sw=frequency, Ts=period,
              mode='FCCM' if cot['reverse_current'] else 'CCM', I_L_avg=current, I_L_pk=peak, I_L_min=valley,
              I_L_rms=cot['phase_current_rms_A'], dI_L=delta,
              I_sw_rms=high_rms, I_sw_avg=duty*current, I_sw_pk=peak, I_sw_on=valley, I_sw_off=peak,
              V_sw_max=high_block*(1.+ring), I_d_rms=0., I_d_avg=0., I_d_pk=0., V_d_max=0.,
              I_in_avg=sum(r['current_avg_A']*r['duty'] for r in phase_data), rhp_zero=math.inf,
              L_min=first['rise_voltage_V']*first['ton_s']/(2.*current) if current>0 else math.inf, C_min=capacitance_min,
              Vf=p.get('Vf', .7), N=p.get('N', 1.), pwr_factor=1., ring_margin=ring,
              eta_guess=efficiency, P_in_est=estimated_input, I_in_est=estimated_input/vin,
              P_loss_budget=estimated_input-power, efficiency_model='explicit_cot_voltage_drops')
    for key in ('Rds_on', 'Rds_aux', 'C_out', 'Rc', 'ESL', 'C_out2', 'Rc2', 'ESL2', 'cout2_enable',
                'output_capacitors', 'tr', 'tf', 'Rs'):
        if key in p:
            op[key] = p[key]
    from cot_engineering import constraints
    cot['engineering']=constraints(p,op)
    op=attach_nodes(op, p)
    op['V_in_bus']=cot['bus_voltage_V']
    return op


def compute_operating_point(p):
    """Resolve one physical phase inductor and use its DCR for the power point."""
    from cot_settings import validate
    from inductor_selection import hardware, purchased
    from magnetics import design_inductor

    phases = validate(p)
    fixed = p.get('_fixed_inductor') or {}
    if purchased(p):
        return _solve(p, phases, fixed.get('inductor_dcr', p.get('inductor_dcr', 0.)))
    initial = _solve(p, phases, 0.)
    rows=initial['cot']['phase_data']
    worst=dict(initial,I_L_pk=max(max(abs(r['current_peak_A']),abs(r['current_valley_A'])) for r in rows),
               I_L_rms=max(r['current_rms_A'] for r in rows),dI_L=max(r['ripple_A'] for r in rows))
    inductor = design_inductor(worst, p)
    if not inductor['ok']:
        return initial
    op = _solve(p, phases, inductor['R_dc'])
    op['cot']['inductor_hardware'] = hardware(inductor)
    return op


def phase_waveforms(op, t, points_per_period, wf):
    """One phase for device plots, every phase and aggregate for bank ripple."""
    cot = op['cot']
    phase_count = cot['phases']
    duty = op['D']
    # Integer ticks put all phases on the same boundary convention. Comparing
    # floating time modulo T can create a spurious overlapping/missing sample
    # when one pulse ends at the exact tick where another phase starts.
    ticks = np.arange(len(t), dtype=np.int64)
    offsets = np.arange(phase_count, dtype=np.int64)*(points_per_period//phase_count)
    local_ticks = (ticks[None, :]-offsets[:, None]) % points_per_period
    cycle = local_ticks/points_per_period
    phase_data=cot.get('phase_data')
    if phase_data:
        duty=np.array([r['duty'] for r in phase_data])[:,None]
        valley=np.array([r['current_valley_A'] for r in phase_data])[:,None]
        delta=np.array([r['ripple_A'] for r in phase_data])[:,None]
        high=cycle<duty
        sign=np.where(high,cycle/duty,(1-cycle)/(1-duty))
        currents=valley+delta*sign
        input_currents=np.where(high,currents,0.)
        representative=currents[0]
        bus=cot['bus_voltage_V']; r=phase_data[0]
        wf.update(iL=representative,iL_phases=currents,iL_total=currents.sum(axis=0),
                  i_p=representative,i_in=input_currents.sum(axis=0),i_sw=input_currents[0],
                  i_low=np.where(high[0],0.,representative),gate_phases=high,
                  i_d=np.zeros_like(t),v_d=np.zeros_like(t),
                  v_sw=np.where(high[0],r['rhigh_ohm']*representative,bus+r['rlow_ohm']*representative),
                  v_low=np.where(high[0],bus-(r['rhigh_ohm']+r['rs_ohm'])*representative,-r['rlow_ohm']*representative),
                  i_c=currents.sum(axis=0)-op['I_out'])
        return
    pulse_ticks = duty*points_per_period
    edge = round(pulse_ticks)
    if math.isclose(pulse_ticks, edge, abs_tol=1e-10, rel_tol=0.):
        pulse_ticks = edge
    high = local_ticks < pulse_ticks
    sign = np.where(high, cycle/duty, (1.-cycle)/op['Dp'])
    currents = op['I_L_min']+op['dI_L']*sign
    input_currents = np.where(high, currents, 0.)
    output_sum = currents.sum(axis=0)
    representative = currents[0]
    bus = cot['bus_voltage_V']
    r_h, r_l = op['Rds_on'], op.get('Rds_aux', .1)
    wf.update(iL=representative, iL_phases=currents, iL_total=output_sum,
              i_p=representative, i_in=input_currents.sum(axis=0), i_sw=input_currents[0],
              i_low=np.where(high[0], 0., representative), gate_phases=high,
              i_d=np.zeros_like(t), v_d=np.zeros_like(t),
              v_sw=np.where(high[0], r_h*representative, bus+r_l*representative),
              v_low=np.where(high[0], bus-(r_h+op['Rs'])*representative, -r_l*representative),
              i_c=output_sum-op['I_out'])
