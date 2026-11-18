"""Public-architecture COT switching behavior; no proprietary silicon model.

The legacy cadence deck remains byte-identical when enhanced options are absent.
Power and control cards are shared by standalone and power-tree experiments.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re


VERSION = 'GenericInterleavedBuckCOT-2.0'


def configuration(p):
    from cot_settings import configuration as normalize
    return normalize(p)


def enabled(cfg):
    from cot_settings import PHASE_DEFAULTS
    return (cfg['model'] != 'cadence_pi' or any(r != PHASE_DEFAULTS for r in cfg.get('phase_parameters', []))
            or any(cfg.get(k, 0) for k in ('phase_limit_A', 'uvlo_on_V', 'ovp_V',
                  'dead_time_s', 'source_resistance_ohm', 'source_inductance_H',
                  'prebias_V', 'shutdown_s', 'vcc_uvlo_V', 'source_rise_s','balance_gain_v_per_a'))
            or cfg.get('light_load', 'forced') != 'forced'
            or cfg.get('load_mode', 'resistance') != 'resistance'
            or cfg.get('load_rise_s',1e-6) != 1e-6
            or cfg.get('body_diode_V',.7) != .7)


def _f(v):
    return format(float(v), '.12g')


def _replace_params(data, updates):
    rows = data.decode('ascii').splitlines()
    for key, value in updates.items():
        card = f'.param {key}={value if isinstance(value,str) else _f(value)}'
        pattern = re.compile(r'^\.param '+re.escape(key)+r'=')
        indices = [i for i, row in enumerate(rows) if pattern.match(row)]
        if indices:
            rows[indices[0]] = card
        else:
            rows.append(card)
    return ('\n'.join(rows)+'\n').encode('ascii')


def enhance_project(files, p, op, settings, *, force=False):
    cfg = configuration(p)
    if not force and not enabled(cfg):
        return files
    from capacitor_banks import bank
    cot = op['cot']
    n = cot['phases']
    phase_rows = cfg.get('phase_parameters') or [{} for _ in range(n)]
    phases = [dict(L_scale=1., dcr_scale=1., rhigh_scale=1., rlow_scale=1.,
                   ton_scale=1., sense_gain=1., sense_offset_A=0.) | r for r in phase_rows]
    files = dict(files)
    updates = dict(DEAD=cfg.get('dead_time_s', 0.), ILIMIT=cfg.get('phase_limit_A', 0.),
                   LIMITDELAY=cfg.get('limit_delay_s', 20e-9),
                   FAULTDELAY=cfg.get('fault_delay_s', .0002), HICCUP=cfg.get('hiccup_s', .002),
                   FAULTMODE={'cycle':0,'hiccup':1,'latch':2}[cfg.get('fault_mode','cycle')],
                   UVON=cfg.get('uvlo_on_V',0.), UVOFF=cfg.get('uvlo_off_V',0.),
                   OVP=cfg.get('ovp_V',0.), VCCUV=cfg.get('vcc_uvlo_V',0.),
                   PREBIAS=cfg.get('prebias_V',0.), SHUTDOWN=cfg.get('shutdown_s',0.),
                   CFGAIN=cfg.get('current_feedback_hz_per_a',0.) if cfg['model']=='current_feedback' else 0.,
                   CFFREQ=cfg.get('current_filter_hz', 20000.),
                   BALGAIN=cfg.get('balance_gain_v_per_a',0.),
                   BALFREQ=cfg.get('balance_bandwidth_hz',2000.),
                   BALMAX=cfg.get('balance_max_duty', .02),
                   LOADRISE=cfg.get('load_rise_s',1e-6), VG=p.get('Vgs',5.), RSHUNT=p.get('Rs',0.),
                   DIODEMODE=1 if cfg.get('light_load')=='diode_emulation' else 0.,
                   EDGE='{min(TON/3,1/(PHASES*FMAX)/3)}',
                   FMAX='{min(FREQCAP,1/(TON*TONSCALEMAX+BALMAX/max(FREF,1)+2*DEAD+max(TOFFMIN,OFF_FLOOR)))}',
                   TONSCALEMAX=max(r['ton_scale'] for r in phases),
                   MAXSTEP='{min(TON,1/(PHASES*FMAX))/12}')
    files['design_params.inc'] = _replace_params(files['design_params.inc'],updates)
    # R/C timers reset through finite resistances; they do not reset accepted
    # integration history from a rejected Newton iteration.
    control = [
        '.model COT_RESET SW(Ron=1 Roff=1e12 Vt=.5 Vh=-.01)',
        'V_EN en 0 1', 'V_VCC vcc 0 {VG}',
        'A_UV vbus 0 0 0 0 0 uvready 0 SCHMITT Vt={(UVON+UVOFF)/2} Vh={max((UVON-UVOFF)/2,1u)} Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
        'B_ENABLED enabled 0 V=if((V(en)>.5)&(V(vcc)>VCCUV)&((UVON<=0)|(V(uvready)>.5))&(time>=TSTART)&((SHUTDOWN<=0)|(time<SHUTDOWN)),1,0)',
        'B_OVP ovp 0 V=if((OVP>0)&(V(cap1)>OVP),1,0)',
        'B_FAULT_RESET faultreset 0 V=if((V(enabled)<.5)|((FAULTMODE<1.5)&(V(offage)>=HICCUP)),1,0)',
        'B_FAULT_SET faultset 0 V=if((V(faultreset)<.5)&((V(ovp)>.5)|((FAULTMODE>.5)&(V(overage)>=FAULTDELAY))),1,0)',
        'A_FAULT faultset faultreset 0 0 0 0 fault 0 SRFLOP Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
        'C_OFFAGE offage 0 1n', 'B_OFFAGE 0 offage I=if(V(fault)>.5,1n,0)',
        'B_OFFRESET offreset 0 V=1-V(fault)', 'S_OFFRESET offage 0 offreset 0 COT_RESET',
        'B_RUN run 0 V=if((V(enabled)>.5)&(V(fault)<.5),1,0)',
        'C_SSAGE ssage 0 1n', 'B_SSAGE 0 ssage I=if(V(run)>.5,1n,0)',
        'B_SSRESET ssreset 0 V=1-V(run)', 'S_SSRESET ssage 0 ssreset 0 COT_RESET',
        'B_REF ref 0 V=VSET*limit(V(ssage)/max(TSS,1n),0,1)',
        'B_PRESET preset 0 V=if((V(run)>.5)&(V(ref)>=V(cap1)),1,0)',
        'A_PRE preset ssreset 0 0 0 0 pready 0 SRFLOP Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
        'B_ERR err 0 V=(V(ref)-V(cap1))/VSET',
        'B_BASETON baseton 0 V=if(FIXEDTON>0,FIXEDTON,VSET/(max(V(vbus),VSET+1m)*FREF))',
        'B_MAXRATE maxrate 0 V=min(FMAX,1/(V(baseton)*TONSCALEMAX+BALMAX/max(FREF,1)+2*DEAD+max(TOFFMIN,OFF_FLOOR)))',
        'B_UNLIMITED request 0 V=V(ref)/VSET*FBIAS+KP*V(err)+V(integral)-CFGAIN*(V(ifilter)-PHASES*IREF*V(ref)/VSET)',
        'B_INT integral 0 V=idt(if(V(run)>.5,KI*V(err)+2000*(limit(V(request),0,V(maxrate))-V(request)),0),0,V(run)<.5)',
        'B_RATE rate 0 V=if((V(run)>.5)&(V(pready)>.5)&((DIODEMODE<.5)|(V(cap1)<V(ref))),limit(V(request),0,V(maxrate)),0)',
        'C_TICKS ticks 0 1n ic=0', 'B_TICKS 0 ticks I=1n*V(rate)',
    ]
    control += ['B_ITOTAL itotal 0 V='+'+'.join(f'V(sensed{i})' for i in range(1,n+1)),
                'R_CFFILTER itotal ifilter 1', 'C_CFFILTER ifilter 0 {1/(2*pi*CFFREQ)}',
                'B_IPHMEAN iphmean 0 V=V(itotal)/PHASES']
    source=('VIN_SOURCE input 0 PWL(0 0 '+_f(cfg['source_rise_s'])+' {VIN})'
            if cfg.get('source_rise_s',0.)>0 else 'VIN_SOURCE input 0 {VIN}')
    power = [source,
             '.model COT_BODY D(Ron=5m Roff=1e10 Vfwd='+_f(cfg.get('body_diode_V',.7))+' epsilon=1u)']
    if p.get('d_in_enable'):
        power += ['.model COT_INPUT_D D(Ron=1u Roff=1e12 Vfwd={VF_IN} epsilon=1u)',
                  'D_INPUT_BLOCK input blocked COT_INPUT_D']
    else:power.append('B_INPUT_BLOCK input blocked V=0')
    resistance=cfg.get('source_resistance_ohm',0.)
    inductance=cfg.get('source_inductance_H',0.)
    if inductance>0:
        power += [f'R_SOURCE blocked feed {_f(max(resistance,1e-9))}',f'L_SOURCE feed vbus {_f(inductance)}']
    else:
        power += [f'R_SOURCE blocked vbus {_f(max(resistance,1e-9))}']
    for i,row in enumerate(phases,1):
        offset=(n-i)/n
        control += [
            f'B_SENSE{i} sensed{i} 0 V={_f(row["sense_gain"])}*I(L{i})+{_f(row["sense_offset_A"])}',
            f'B_BALERR{i} balerr{i} 0 V=BALGAIN*(V(iphmean)-V(sensed{i}))',
            f'R_BAL{i} balerr{i} bal{i} 1', f'C_BAL{i} bal{i} 0 {{1/(2*pi*BALFREQ)}}',
            f'B_TON{i} ton{i} 0 V=max(2n,V(baseton)*{_f(row["ton_scale"])}+limit(V(bal{i})/max(V(vbus),1m),-BALMAX,BALMAX)/max(V(rate),FREF/20))',
            f'B_EDGE{i} edge{i} 0 V=if(floor(V(ticks)+{offset:.12g})>floor(delay(V(ticks),{{EDGE}})+{offset:.12g}),1,0)',
            f'C_AGE{i} age{i} 0 1n',f'B_AGE{i} 0 age{i} I=if(V(gate{i})>.5,1m,0)',
            f'B_AGERESET{i} agereset{i} 0 V=1-V(gate{i})',f'S_AGERESET{i} age{i} 0 agereset{i} 0 COT_RESET',
            f'C_OFF{i} off{i} 0 1n',f'B_OFF{i} 0 off{i} I=if(V(gate{i})<.5,1m,0)',
            f'S_OFF{i} off{i} 0 gate{i} 0 COT_RESET',
            f'B_OCP{i} ocp{i} 0 V=if((ILIMIT>0)&(V(gate{i})>.5)&(V(sensed{i})>=ILIMIT),1,0)',
            f'B_RESET{i} reset{i} 0 V=if((V(run)<.5)|(delay(V(ocp{i}),{{LIMITDELAY}})>.5),1,limit((V(age{i})-1e6*V(ton{i}))*1000+.5,0,1))',
            f'B_EDGEOFF{i} edgeoff{i} 0 V=1-V(edge{i})',
            f'A_USED{i} set{i} edgeoff{i} 0 0 0 0 used{i} 0 SRFLOP Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
            f'B_SET{i} set{i} 0 V=if((V(edge{i})>.5)&(V(used{i})<.5)&(V(run)>.5)&(V(pready)>.5)&(V(reset{i})<.5)&(V(off{i})>=1e6*TOFFMIN),1,0)',
            f'A_Q{i} set{i} reset{i} 0 0 0 0 q{i} 0 SRFLOP Vhigh=1 Vlow=0 Td=0 Trise=1p Tfall=1p',
            f'B_GATECMD{i} gatecmd{i} 0 V=min(V(q{i}),delay(V(q{i}),{{DEAD}}))*V(run)',
            f'A_GATE{i} gatecmd{i} 0 0 0 0 0 gate{i} 0 BUF Vhigh=1 Vlow=0 Td=0 Trise=1n Tfall=1n',
            f'B_ZSET{i} zset{i} 0 V=if((V(q{i})<.5)&(I(L{i})<=0),1,0)',
            f'A_ZCD{i} zset{i} q{i} 0 0 0 0 zcd{i} 0 SRFLOP Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
            f'B_LO{i} lo{i} 0 V=if((V(run)>.5)&(V(pready)>.5)&((DIODEMODE<.5)|(V(zcd{i})<.5)),min(1-V(q{i}),delay(1-V(q{i}),{{DEAD}})),0)',
        ]
        power += [f'.model COT_H{i} SW(Ron={{(RH-RSHUNT)*{_f(row["rhigh_scale"])}+RSHUNT}} Roff=1e9 Vt=.5 Vh=-.01)',
                  f'.model COT_L{i} SW(Ron={{RL*{_f(row["rlow_scale"])}}} Roff=1e9 Vt=.5 Vh=-.01)',
                  f'SH{i} vbus sw{i} gate{i} 0 COT_H{i}', f'SL{i} sw{i} 0 lo{i} 0 COT_L{i}',
                  f'DH{i} sw{i} vbus COT_BODY', f'DL{i} 0 sw{i} COT_BODY',
                  f'L{i} sw{i} cap1 {{LP*{_f(row["L_scale"])}}} Rser={{DCR*{_f(row["dcr_scale"])}}}',
                  f'CH{i} vbus sw{i} {_f(max(p.get("Coss",0.),1e-15))}',
                  f'CL{i} sw{i} 0 {_f(max(p.get("Coss_aux",0.),1e-15))}']
    any_ocp='V(ocp1)'
    for i in range(2,n+1):any_ocp=f'max({any_ocp},V(ocp{i}))'
    control += ['B_ANYOCP anyocp 0 V='+any_ocp,
                'A_SEEN anyocp ssreset 0 0 0 0 ocpseen 0 SRFLOP Vhigh=1 Vlow=0 Td=1n Trise=1n Tfall=1n',
                'C_SINCE sinceocp 0 1n', 'B_SINCE 0 sinceocp I=1n',
                'B_SINCERESET sincereset 0 V=max(V(anyocp),V(ssreset))',
                'S_SINCERESET sinceocp 0 sincereset 0 COT_RESET',
                'B_OVER over 0 V=if((V(ocpseen)>.5)&(V(sinceocp)<2/FREF)&(V(run)>.5),1,0)',
                'C_OVERAGE overage 0 1n', 'B_OVERAGE 0 overage I=if(V(over)>.5,1n,0)',
                'B_OVERRESET overreset 0 V=1-V(over)',
                'S_OVERRESET overage 0 overreset 0 COT_RESET']
    for prefix,node,caps in (('CIN','vbus',bank(p,'input')),('COUT','cap1',bank(p))):
        for i,r in enumerate(caps,1):
            esl=r['ESL'] if settings['include_cap_esl'] else 0.
            initial=' IC={PREBIAS}' if prefix=='COUT' else ''
            power.append(f'{prefix}{i} {node} 0 {_f(r["C"])} Rser={_f(r["ESR"])} Lser={_f(esl)}'+initial)
    if p.get('d_out_enable'):
        power += ['.model COT_OUTPUT_D D(Ron=1u Roff=1e12 Vfwd={VF_OUT} epsilon=1u)',
                  'D_OUT cap1 out1 COT_OUTPUT_D']
    else:power.append('V_OUT cap1 out1 0')
    fraction='(1+(AFTER-1)*limit((time-TLOAD)/max(LOADRISE,1n),0,1))'
    load=('V(out1)/RLOAD' if cfg.get('load_mode','resistance')=='resistance' else
          f'{_f(op["I_out"])}*limit(V(out1)/max(.01*VSET,1m),0,1)')
    power.append(f'B_LOAD out1 0 I={load}*{fraction}')
    traces=['V(out1)','V(cap1)','V(ref)','V(rate)','V(request)','I(VIN_SOURCE)',
            'V(vbus)','V(run)','V(fault)','V(uvready)','V(ovp)','V(itotal)','V(iphmean)','V(anyocp)','V(overage)']
    for i in range(1,n+1):
        traces += [f'I(L{i})']+[f'V({k}{i})' for k in ('gate','lo','sw','ocp','sensed','ton','bal')]
    files['control.inc']=('\n'.join(control)+'\n').encode('ascii')
    files['power_stage.inc']=('\n'.join(power)+'\n').encode('ascii')
    files['analysis.inc']=(f'.options threads={int(settings["simulation_threads"])} method=trap reltol=0.001 plotwinsize=0\n'
                           '.tran 0 {TEND} 0 {MAXSTEP} uic\n.save '+' '.join(traces)+'\n').encode('ascii')
    meta=json.loads(files['manifest.json'])
    meta.update(model_version=VERSION,cot_config=cfg,
        controller_mode='public-architecture total-current-feedback COT' if cfg['model']=='current_feedback' else 'enhanced cadence COT',
        approximation_notes=[
            '原创公开结构参考：频率PI外环、总电流负反馈、逐相单稳态及低带宽均流。不是特定芯片完整硅模型。',
            '每相配置采样增益及偏移参与限流；延迟后截断高侧，每个触发沿至多接受一次。连续重复限流达到延时触发打嗝或锁存；两周期未再限流则延时复位。OVP关断两管，按故障模式复位。',
            '各相配置独立L/DCR/MOS/导通时间偏差。死区采用延迟开通立即关断；轻载二极管仿真在电流归零后锁定低侧，并在输出高于参考时暂停追加脉冲。活动相数固定。',
            '输入串联R/L为显式源阻抗；电源树运行由外部源承担。Coss为已填常数、体二极管为定压降近似；未建模Qg/Miller和动态结电容。',
            '预偏置以输出电容初始电压配置，参考赶上输出后才开始开关。恒流负载在目标电压1%以下线性退让，避免零伏恒流奇点。'])
    meta['resolved_controller']=dict(FSW=op['f_sw'],VG=p.get('Vgs',5.),TSS=settings['soft_start_ms']*1e-3,
                                    RSENSE=None,CS_LIM=cfg.get('phase_limit_A',0.))
    files['manifest.json']=json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
    files['README.md']=('# 多相 Buck COT 行为电路\n\n运行 Flyback.cir；ASC 为结构查看页。'
                        '\n\n'+'\n'.join('- '+t for t in meta['approximation_notes'])+'\n').encode('utf-8')
    return files


def compile_sequence_unit(p, namespace, bundle):
    """Wrap exactly the same generated COT cards, removing only test fixtures."""
    from cot_buck_spice import project_files, transient_settings
    cases=bundle['cases'];case=cases[0]
    files=project_files(p,bundle=bundle,case=case)
    files=enhance_project(files,case['p'],case['result']['op'],transient_settings(p.get('spice_config'),cases),force=True)
    cfg=configuration(p)
    # External canvas owns EN, its timing, source impedance and consumer loads.
    files['design_params.inc']=_replace_params(files['design_params.inc'],dict(TSTART=0.,SHUTDOWN=0.))
    name=namespace+'_UNIT'
    parameters=[x for x in files['design_params.inc'].decode('ascii').splitlines() if not x.startswith('.step')]
    cards=[];removed=[]
    for file in ('power_stage.inc','control.inc'):
        for card in files[file].decode('ascii').splitlines():
            ref=card.split()[0] if card.split() else ''
            if ref in ('VIN_SOURCE','V_EN','V_VCC','B_LOAD','R_SOURCE','L_SOURCE'):
                removed.append(ref);continue
            cards.append(card)
    cards.append('V_COT_INPUT blocked vbus 0')
    n=case['result']['op']['cot']['phases']
    currents={f'L{i}':f'seq_i_l{i}' for i in range(1,n+1)}
    currents['primary']='seq_i_l1'
    cards += [f'B_SEQ_I{i} seq_i_l{i} 0 V=I(L{i})' for i in range(1,n+1)]
    probes=dict(input='input',inputbus='vbus',en='en',vcc='vcc',gate='gate1',ss='ref',fault='fault',
                cap1='cap1',out1='out1',drain='sw1',currents=currents,
                controller=dict(run='run',uvlo='uvready',ocp='anyocp',ovp='ovp'),
                cot_phase_limits={f'phase{i}':f'ocp{i}' for i in range(1,n+1)},
                cot_phase_sensed={f'phase{i}':f'sensed{i}' for i in range(1,n+1)})
    # No fake sense resistor: these current signals are explicit 1 V/A probes.
    meta=json.loads(files['manifest.json'])
    minimum_ton=min(r.get('ton_scale',1.) for r in cfg['phase_parameters'])*case['result']['op']['cot']['ton_s']
    max_frequency=2*max(c['result']['op']['f_sw'] for c in cases)
    meta['sequence_unit']=dict(schema='power.sequence-unit/1',namespace=namespace,subckt_name=name,
        pins=['input','en','vcc','out1'],common_return='0',output_count=1,removed_cards=removed,libraries={},
        maximum_step_s=min(minimum_ton,1/(n*max_frequency))/12,
        thresholds=dict(nominal_vcc_v=p.get('Vgs',5.),vcc_uvlo_on_v=cfg.get('vcc_uvlo_V',0.),
                        cycle_cs_ceiling_v=None,sense_resistor_ohm=None,phase_current_limit_A=cfg.get('phase_limit_A',0.),
                        soft_start_s=meta['resolved_controller']['TSS'],gate_on_v=.5),
        source_hashes={k:hashlib.sha256(v).hexdigest() for k,v in files.items() if k.endswith('.inc')},
        limitations=meta['approximation_notes']+['电源树移除单元测试负载、输入源与串R/L，由画布源/连线提供；公共返回0。'],
        model_scope='shared-cot-switching-stage-public-architecture')
    text='\n'.join(['.subckt '+name+' input en vcc out1',*parameters,*cards,'.ends '+name,''])
    outputs=[dict(id=1,name='OUT1',V_out=float(p['V_out']),P_out=float(p['P_out']),cap_node='cap1',out_node='out1',return_node='0')]
    return dict(subckt_text=text,libraries={},manifest=meta,probes=probes,output_count=1,outputs=outputs)
