"""Independent resonant inductor winding, flux and thermal screening for LLC."""
import math

import numpy as np


def design_resonant_inductor(op, p):
    from core_shape_catalog import get_core_shape
    from magnetics import ac_factor, core_loss_nse_waveform, estimated_core_mlt, resolve_core, wire_diameter
    from transformer_geometry_contract import profile_template
    from transformer_gap import estimate as estimate_gap
    from transformer_preview_scene import nominal_winding_window
    from winding_layout import assess_winding_window
    from winding_length import resolve_winding_lengths

    x = op['llc']
    leakage = p['llc_lr_leakage_H']
    inductance = p['llc_lr']-leakage
    current_pk, current_rms = x['ir_peak_A'], x['ir_rms_A']
    design_peak = max(current_pk, p['llc_lr_design_peak'])
    b_design, density, ku = p['Bmax'], p['J'], p['Ku']
    ap = inductance * design_peak * current_rms / (b_design * density * ku)
    core_params = dict(p, core_choice=p.get('core_choice_L','auto'), custom_core=p.get('custom_core_L',{}))
    fixed = p.get('_fixed_inductor') or {}
    name, core = resolve_core(core_params, ap, fixed)
    if not core:
        return dict(ok=False,reason='没有满足 Lr 面积乘积的磁芯',ap=ap)

    ae,ve,wa = core['Ae'],core['Ve'],core['Wa']
    min_ae = p['llc_lr_min_ae'] or ae
    if min_ae > ae:
        raise ValueError('Lr 磁路最小截面积不可大于当前选芯有效截面积 Ae')
    turns = int(fixed.get('N') or p['llc_lr_turns'] or math.ceil(inductance*design_peak/(b_design*min_ae)))
    strands = int(p['llc_lr_strands'])
    diameter = float(fixed.get('d_wire') or p['llc_lr_wire_diameter'] or wire_diameter(current_rms/strands,density))
    copper = strands*math.pi*diameter**2/4
    row = dict(id='LR',name='L_R 谐振绕组',turns=turns,strands=strands,bare_diameter=diameter,parallel_wires=1)
    wire_type = 'litz' if strands>1 else 'solid'
    winding = dict(window_width=p['llc_lr_window_width'],window_height=p['llc_lr_window_height'],
                   overrides={'LR':{'wire_type':wire_type,'flatten_ratio':1.}})
    if p['llc_lr_bobbin_radius']:
        profile = profile_template()
        profile['frame']['r0_m_if_circular'] = p['llc_lr_bobbin_radius']
        profile['bobbin'].update(winding_route_type='circular',status='assumed',
                                 source='Lr 净绕线窗口与圆形骨架设计尺寸')
        winding['model_3d'] = profile

    mlt, reference = estimated_core_mlt(name, core)
    cable_lengths = resolve_winding_lengths(name, dict(core,MLT=mlt,MLT_source=reference),[row],winding)
    conductor = cable_lengths['windings']['LR']
    try:
        shape = get_core_shape(name) or {}
    except (OSError,ValueError):
        shape = {}
    fit, _ = nominal_winding_window(winding,shape)
    window = assess_winding_window([row],fit)
    resistance = p['rho']*conductor['length_m']/copper
    rac_factor = ac_factor(diameter,op['f_sw'],p['rho'])
    copper_loss = resistance*rac_factor*current_rms**2
    time = np.asarray(x['time_s'])
    flux = inductance*np.asarray(x['i_res_A'])/(turns*ae)
    core_loss = core_loss_nse_waveform(p['k_core'],p['a_core'],p['b_core'],time,flux,ve)
    loss = copper_loss+core_loss
    area = 2.0*(1.5*ve**(1/3))**2
    convection = p.get('h_conv',10.)
    gap = estimate_gap(dict(p,topology='BUCK',L=inductance),core,turns)
    return dict(ok=True,core=name,core_label=core.get('name') or name,core_geometry=core,
        Ae=ae,Ve=ve,Wa=wa,min_Ae=min_ae,L=inductance,L_total=p['llc_lr'],L_leakage=leakage,
        N=turns,d_wire=diameter,n_strand=strands,A_wire=copper,
        R_dc=resistance,Fr=rac_factor,P_cu=copper_loss,P_core=core_loss,P_total=loss,
        MLT=conductor['mlt_m'],copper_length_m=conductor['length_m'],MLT_source=conductor['source'],
        winding_lengths=cable_lengths,winding_window=window,ap=ap,fill=turns*copper/wa,
        gap=gap['gap_m'],gap_design=gap,I_rms=current_rms,I_pk=current_pk,design_peak_A=design_peak,
        B_pk=inductance*current_pk/(turns*min_ae),dB=float(np.ptp(flux)),
        B_design_peak_T=inductance*design_peak/(turns*min_ae),
        I_at_design_B_A=b_design*turns*min_ae/inductance,
        I_at_saturation_A=p['Bsat']*turns*min_ae/inductance,
        h_conv=convection,A_surf=area,dT=loss/(convection*area),J_actual=current_rms/copper,
        winding_notes='铜损按单股趋肤系数估算；未计邻近效应、气隙边缘磁通与未声明的引线。')
