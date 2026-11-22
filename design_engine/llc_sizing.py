"""Specification-driven LLC tank initial choice and fixed-hardware verification."""

import math


def generate_llc(request):
    from .specification import load_spec
    from .sizing_basis import SOURCES, TOPOLOGY_MODES, fields_for
    from app_resources import resource_path
    from capacitor_banks import validate as validate_bank
    from input_voltage_range import calculate_input_endpoints
    from llc_model import solve
    from calculation_scheduler import check_calculation_cancelled
    import json

    defaults={key:value*scale for key,_,scale,value in fields_for('LLC')}
    if set(request)-defaults.keys()-{'topology','control_mode','locked'}:
        raise ValueError('LLC 初版含未知规格字段')
    s={key:request.get(key,value) for key,value in defaults.items()}
    if s['imin'] is None:
        s['imin']=0.
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in s.values()):
        raise ValueError('LLC 初版规格应为有限数值')
    mode=request.get('control_mode','Hybrid Hysteretic')
    if mode not in TOPOLOGY_MODES['LLC'] or s['bridge'] not in (1,2):
        raise ValueError('请选择有效的 LLC 桥型和控制方式')
    lo,hi,vo,io,fs=(s[k] for k in ('vin_min','vin_max','vout','iout','fs'))
    power=vo*io
    if not (200<=lo<=hi<=440 and 24<=vo<=80 and 50<=power<=600 and
            50e3<=fs<=220e3 and 0<=s['imin']<=io and .001<=s['ripple']<=.05
            and 30<=s['pm']<=80 and .15<=s['q']<=.65 and 3<=s['ratio']<=10):
        raise ValueError('LLC 初版范围为 200–440 V、24–80 V 输出、50–600 W、50–220 kHz，核对 Q 和 Lm/Lr。')
    bridge='full' if s['bridge']==2 else 'half'
    template='300W_LLC_FULL_VCO.json' if bridge=='full' else '300W_LLC_HALF_HHC.json'
    p=json.loads(resource_path('examples/'+template).read_text(encoding='utf-8'))
    # The 300 W example's winding is designed for its frozen turns and tank.
    # A new specification sizes its own magnetics unless explicitly locked.
    for key in tuple(p):
        if key in ('component_management','custom_core','custom_core_L','winding_config') or key.startswith('llc_lr_'):
            p.pop(key)
    ns=6
    alpha=1. if bridge=='full' else .5
    np=max(1,round(ns*alpha*math.sqrt(lo*hi)/(vo + 2*p['Vf_diode'])))
    n=np/ns
    rac=8*n*n*vo/(math.pi**2*io)
    impedance=s['q']*rac
    omega=2*math.pi*fs
    lr=impedance/omega
    cr=1/(omega*impedance)
    lm=s['ratio']*lr
    p.update(V_in=lo,V_in_min=lo,V_in_max=hi,V_out=vo,P_out=power,P_out_min=vo*s['imin'],
             f_sw=fs,N=n,Np=np,Ns=ns,llc_bridge=bridge,control_mode=mode,
             llc_lr=lr,llc_cr=cr,llc_lm=lm,llc_fmin=.65*fs,llc_fmax=2.0*fs,
             llc_dead_time=400e-9 if bridge=='full' else 250e-9,
             llc_hhc_ramp=4*fs,llc_uvlo=.8*lo,llc_ovp=1.2*vo,llc_ocp=0.,
             llc_kp=0.,llc_ki=0.,core_choice='auto',core_choice_L='auto',
             d_wire_p=0.,d_wire_s=0.,n_strand_p=40,n_strand_s=160,
             fc_target=min(700.,fs/100),pm_target=s['pm'],ripple_target=s['ripple'])
    # Start with a charge budget equal to half a commutation interval.
    c=io/(4*fs*vo*s['ripple']*.55)
    p['output_capacitors']=[dict(C=max(c*.5,100e-6),ESR=min(.06,.5*vo*s['ripple']/io),ESL=8e-9) for _ in range(2)]
    locked=request.get('locked') or {}
    if set(locked)-{'llc_lr','llc_cr','llc_lm','input_capacitors','output_capacitors'}:
        raise ValueError('LLC 初版支持锁定 Lr、Cr、Lm 与输入／输出电容组')
    for key,value in locked.items():
        p[key]=validate_bank(value) if key.endswith('capacitors') else float(value)
    p=load_spec(p)
    rated=calculate_input_endpoints(p,include_cross_regulation=False)
    full=[cse for cse in rated['cases'] if cse['result']]
    p.update(llc_kp=(rated.get('fixed_spec') or p)['llc_kp'],llc_ki=(rated.get('fixed_spec') or p)['llc_ki'])
    if full:
        p['llc_ocp']=max(4*case['result']['op']['I_L_pk'] for case in full)
    rows=[]
    for case in rated['cases'][:1] if rated['same_voltage'] else rated['cases']:
        vin=case['voltage']
        result=case.get('result')
        if result:
            op, loop = result['op'], result.get('loop') or {}
            issues = []
            if not op['llc']['regulation_ok']: issues.append('增益或限频待复核')
            if not op['llc']['zvs_ok']: issues.append('ZVS 换流电荷待复核')
            if not loop.get('closed_loop_stable') or (loop.get('min_pm') or 0)<s['pm']-1:
                issues.append('环路裕度待复核')
            if result['wf']['ripple_pp'] > vo*s['ripple']: issues.append('输出纹波待核对')
            rows.append(dict(vin=vin,current=io,fs=op['f_sw'],mode=op['mode'],issues=issues))
        else:
            rows.append(dict(vin=vin,current=io,issues=[case.get('error') or '工作点未建立']))
        if 0<s['imin']<io:
            check_calculation_cancelled()
            try:
                light=solve(dict(p,V_in=vin,P_out=vo*s['imin']))
                issues=['轻载频率范围或 ZVS 待复核'] if not light['regulation_ok'] or not light['zvs_ok'] else []
                rows.append(dict(vin=vin,current=s['imin'],fs=light['frequency_Hz'],issues=issues))
            except ValueError as error:
                rows.append(dict(vin=vin,current=s['imin'],issues=[str(error)]))
    p['__auto_design_basis']=dict(revision='2026-11-19-llc',topology='LLC',mode=mode,
        specification=s,rules=dict(Rac_ohm=rac,Zr_ohm=impedance),sources=[SOURCES['LLC'][2],SOURCES['HHC'][2]],
        corners=rows,model_ok=all(not row['issues'] for row in rows),
        pending=['按实际 Coss、温度和容差核对 ZVS、启动限流与轻载频率上限。'])
    return p


def describe_llc(p):
    basis=p['__auto_design_basis']
    answer=[('全部已计算工况满足初筛' if basis['model_ok'] else '有工况待复核'),
            f"匝数 {p['Np']}:{p['Ns']}，Lr {p['llc_lr']*1e6:.3g} µH，"
            f"Cr {p['llc_cr']*1e9:.3g} nF，Lm {p['llc_lm']*1e6:.3g} µH。"]
    for case in basis['corners']:
        answer.append(f"{case['vin']:g} V／{case['current']:g} A　"
                      + (f"{case['fs']/1000:.3g} kHz　" if 'fs' in case else '')
                      + ('；'.join(case['issues']) or '通过'))
    return '\n'.join(answer+basis['pending'])
