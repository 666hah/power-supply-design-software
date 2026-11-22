"""Adapt the LLC periodic tank and loss ledger to the shared design snapshot."""

import math

import numpy as np

from llc_settings import validate


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def _peak(values):
    return float(np.max(np.abs(values)))


def operating_point(p):
    from llc_model import solve
    from voltage_nodes import attach_nodes

    p = validate(p)
    x = solve(p)
    t = np.asarray(x['time_s'])
    ir = np.asarray(x['i_res_A'])
    im = np.asarray(x['i_mag_A'])
    rect = np.abs(np.asarray(x['i_rect_A']))
    positive = np.asarray(x['gate_state']) > 0
    ii = np.asarray(x['i_in_A'])
    fs = float(x['frequency_Hz'])
    v = float(x['output_voltage_V'])
    io = float(x['output_current_A'])
    bus = float(x['input_voltage_V'])
    bridge = p['llc_bridge']
    leg_count = 1 if bridge == 'half' else 2
    x['switch_count'] = 2 * leg_count
    x['fr_Hz'] = 1 / (2 * math.pi * math.sqrt(p['llc_lr'] * p['llc_cr']))
    x['fm_Hz'] = 1 / (2 * math.pi * math.sqrt((p['llc_lr'] + p['llc_lm']) * p['llc_cr']))
    i_cap = rect - io
    cap_target = p['ripple_target'] * p['V_out']
    charge = np.r_[0., np.cumsum((i_cap[1:]+i_cap[:-1])*.5*np.diff(t))]
    charge_pp = float(np.ptp(charge))
    warnings = list(x['notes'])
    if not x['setpoint_reached']:
        warnings.append('工作点触及给定频率范围，按实际输出列示；请检查增益裕量或调整谐振腔。')
    if p.get('d_in_enable') or p.get('d_out_enable'):
        warnings.append('串联防反器件采用恒定压降；外部整流/PFC 不属于 LLC。')
    po = x['output_power_W']
    estimated = po / p['eta_guess']
    op = dict(topology='LLC', llc=x, control_mode=p['control_mode'], V_in=p['V_in'],
              V_in_bus=bus, V_out=v, V_out_equiv=v, P_out=po, I_out=io,
              R=p['V_out']**2 / p['P_out'], R_equiv=p['V_out']**2 / p['P_out'],
              L=p['llc_lr'], Lm=p['llc_lm'], L_min=0., N=p['N'], f_sw=fs, Ts=1/fs,
              D=float(x['duty']), Dp=float(x['duty']), mode=x.get('mode', 'LLC'),
              I_L_avg=float(np.mean(ir)), I_L_pk=_peak(ir), I_L_min=float(np.min(ir)),
              I_L_rms=x['ir_rms_A'], dI_L=float(np.ptp(ir)), I_p_rms=x['ir_rms_A'],
              I_s_rms=x['rectifier_rms_A'], I_in_avg=float(np.trapezoid(ii,t)/t[-1]),
              I_sw_rms=x['switch_rms_A'], I_sw_pk=_peak(ir * positive),
              I_sw_avg=float(np.trapezoid(abs(ir) * positive,t)/t[-1]),
              I_sw_on=abs(x['switch_ion_A']), I_sw_off=abs(x['switch_ioff_A']),
              V_sw_max=bus*(1+p['ring_margin']), V_d_max=x['rectifier_reverse_peak_V'],
              I_d_rms=x['diode_rms_A'], I_d_pk=x['rectifier_peak_A'], I_d_avg=io/2,
              C_min=charge_pp/cap_target if cap_target else 0.,
              ring_margin=p['ring_margin'], rhp_zero=math.inf, Rs=0.,
              eta_guess=p['eta_guess'], P_in_est=estimated, I_in_est=estimated/p['V_in'],
              P_loss_budget=estimated-po, V_reflect=p['N']*v,
              V_f=p['Vf_diode'], warnings=warnings,
              efficiency_model='periodic_tank_explicit_loss')
    for key in ('C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable','output_capacitors'):
        op[key] = p[key]
    attach_nodes(op, p)
    op['V_in_bus'] = bus
    return op


def waveforms(op, n_cycles, n_pts):
    from waveforms import cap_bank_ripple_fields

    x = op['llc']
    period = op['Ts']
    t = np.linspace(0, period*n_cycles, n_cycles*n_pts, endpoint=False)
    sample_time = np.asarray(x['time_s'])
    tau = t % period
    def interp(field):
        return np.interp(tau, sample_time, x[field])
    i_res, i_mag = interp('i_res_A'), interp('i_mag_A')
    i_rect = np.abs(interp('i_rect_A'))
    v_cr, v_drive = interp('v_cr_V'), interp('v_drive_V')
    inp = interp('i_in_A')
    # Zero-order hold for switch state, continuous interpolation for tank states.
    index = np.maximum(0, np.searchsorted(sample_time, tau, side='right') - 1)
    bridge = np.asarray(x['gate_state'])[index] > 0
    diode = i_res > i_mag + 1e-9
    v_port = interp('v_out_V')
    ic = i_rect - v_port/op['R']
    wf = dict(t=t, dt=t[1]-t[0], f_sw=op['f_sw'], topology='LLC', iL=i_res,
              i_p=i_res, i_mag=i_mag, i_s=op['N']*(i_res-i_mag), i_rect=i_rect,
              i_sw=np.where(bridge,i_res,0.), i_d=np.where(diode,i_rect,0.),
              v_sw=np.where(bridge,0.,op['V_in_bus']), v_d=np.where(diode,0.,op['V_d_max']),
              v_cr=v_cr,
              v_drive=v_drive, v_primary=interp('v_primary_V'),
              gate_positive=bridge.astype(float), i_c=ic,
              i_in=inp, i_cin=inp-np.mean(inp), vout_switched=v_port)
    wf.update(cap_bank_ripple_fields(t, ic, op))
    wf['i_cin_rms'] = _rms(wf['i_cin'])
    return wf


def draw_waveforms(axes, op, wf):
    """Use one full-cycle timebase for tank, bridge and rectifier waveforms."""
    profiles = (
        ('谐振与励磁电流', 'A', [('iL','谐振'), ('i_mag','励磁')]),
        ('谐振电容与原边电压', 'V', [('v_cr','Cr'), ('v_primary','绕组')]),
        ('整流输出与电容组电流', 'A', [('i_rect','整流汇流'), ('i_c','电容组')]),
        ('输出电压', 'V', [('vout_switched','周期解'), ('vout','频域阻抗重构')]),
        ('原边桥的差模激励', 'V', [('v_drive','差模激励')]),
        ('母线电流与开关窗口', 'A / 1', [('i_in','母线电流'), ('gate_positive','正向脉冲')]),
    )
    for axis, (title, unit, traces) in zip(axes, profiles):
        axis.clear()
        for key, label in traces:
            axis.plot(wf['t']*1e6, wf[key], lw=1.15, label=label)
        axis.set(title=title, xlabel='时间 / µs', ylabel=unit)
        if len(traces)>1:
            axis.legend(loc='upper right', fontsize='small')
        axis.grid(alpha=.25)


def comparison_capacitors(p,op,wf,include_esl):
    """Match the independent SPICE input feed and capacitor settings."""
    from capacitor_banks import bank
    from capacitor_impedance import impedance, parallel_response
    from capripple import capacitor_ripple_analysis
    from llc_settings import SOURCE_INDUCTANCE, SOURCE_RESISTANCE

    def fixed(side):
        return [dict(C=row['C'],ESR=row['ESR'],ESL=row['ESL'] if include_esl else 0.)
                for row in bank(p,side)]
    incoming, outgoing = fixed('input'), fixed('output')
    ripple = wf['i_cin']
    spectrum = np.fft.rfft(ripple)
    frequencies = np.fft.rfftfreq(len(ripple),wf['dt'])[1:]
    source_z = SOURCE_RESISTANCE + 2j*math.pi*frequencies*SOURCE_INDUCTANCE
    bank_z, _ = parallel_response(np.array([impedance(frequencies,row) for row in incoming]))
    spectrum[0] = 0.
    spectrum[1:] *= source_z/(source_z+bank_z)
    current = np.fft.irfft(spectrum,n=len(ripple))
    return capacitor_ripple_analysis(wf['t'],current,wf['i_c'],op['f_sw'],incoming,outgoing)


def losses(op, p, wf):
    """Separate modeled conduction, charge-related, magnetic and ESR losses."""
    from capripple import analyze_capacitors
    from llc_magnetics import design_resonant_inductor
    from magnetics import design_transformer

    p = validate(p)
    x = op['llc']
    q = x['switch_count']
    ledger = x['loss_W']
    mos_cond = ledger['switch_conduction']/q
    gate = ledger['gate_drive']/q
    available, required = x['zvs_available_charge_C'], x['zvs_required_charge_C']
    coss = ledger['coss_turn_on']/q
    sw = dict(P_cond=mos_cond, P_gate=gate, P_coss=coss, P_sw_on=0., P_sw_off=0.,
              P_total=mos_cond+gate+coss, zvs_charge_ratio=available/required if required else None)
    diode_cond = ledger['rectifier']/4
    diode = dict(P_cond=diode_cond, P_rr=0., P_total=diode_cond)
    semi = dict(switch=sw, diode=diode, P_total=q*sw['P_total']+4*diode_cond)
    time = np.asarray(x['time_s'])
    flux_op = dict(op, periodic_flux=(time, p['llc_lm']*np.asarray(x['i_mag_A'])),
                   L=p['llc_lm'], I_L_pk=_peak(x['i_mag_A']))
    tr = design_transformer(flux_op, p, op['I_p_rms'], op['I_s_rms'], n_ratio=op['N'])
    lr = design_resonant_inductor(op,p)
    # The series tank resistor already includes measured winding resistance.
    # Only incremental core losses are added here to avoid duplicate copper.
    mag_core = sum(dev.get('P_core',0.) for dev in (tr,lr) if dev.get('ok'))
    mag = dict(ok=bool(tr.get('ok') and lr.get('ok')), transformer=tr, inductor=lr,
               P_total=mag_core, reason=tr.get('reason') or lr.get('reason'))
    capacitors = analyze_capacitors(p,op,wf)
    cap_in, cap_out = (capacitors[rail]['loss_W'] for rail in ('input','output'))
    tank, din, dout = (ledger[key] for key in ('tank_copper','input_block','output_block'))
    total = semi['P_total']+mag_core+tank+cap_in+cap_out+din+dout
    power = op['P_out']
    eta = power / (power+total)
    return dict(op=op,wf=wf,mag=mag,semi=semi,capacitors=capacitors,diode_models=[],
                P_semi=semi['P_total'],P_mag=mag_core,P_cap=cap_out,P_cap_in=cap_in,
                P_parasitic=tank,P_tank=tank,P_sense=0.,P_rcd=0.,P_clamp=0.,P_controller=0.,
                P_din=din,P_dout=dout,P_source=0.,P_total=total,eta=eta,
                P_in=power+total,P_out=power,eta_guess=op['eta_guess'],P_in_est=op['P_in_est'],
                P_loss_budget=op['P_loss_budget'],eta_delta=eta-op['eta_guess'],
                P_in_delta=power+total-op['P_in_est'],outputs=[],psr=None)
