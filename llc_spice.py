"""Switched LLC LTspice fixture with the same tank and controller conventions as calculation."""
from __future__ import annotations

import json
import math
from pathlib import Path

from capacitor_banks import bank


MODEL_VERSION = 'GenericLLCSwitched-1.0'
MODEL_SCOPE = (
    '全桥整流、隔离理想匝比和独立励磁支路。每个半周期由两颗整流二极管导通。',
    '桥臂采用平滑受控电阻、等效栅极充放电、体二极管和等效 Coss。整流 Cj 可选。开通尖峰用于比较趋势，器件反向恢复、非线性电荷及布局寄生应结合器件模型复核。',
    '混合滞环按谐振电容折叠电压与定时斜坡触发交替半周期，外电压环修正阈值。开关环路试验从防反前电容端的电压取样点注入。',
    '输入纹波按有源阻抗试验夹具观察，源与母线之间设置 25 mΩ、1 µH。',
    '启动开关电流峰值含等效 Coss 的硬开通放电，谐振电流峰值另列作为能量传输对照。',
)


def _num(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('LLC 仿真参数必须有限')
    return f'{value:.12g}'


def _cap_banks(p):
    include_esl = bool((p.get('spice_config') or {}).get('include_cap_esl'))
    source = dict(Cin1=100e-6, Rcin1=.08, C_out=470e-6, Rc=.02) | p
    lines = []
    probes = {'input': [], 'output': []}
    for side, node, return_node, prefix in (
        ('input', 'bus', '0', 'CI'),
        ('output', 'cap', 'sgnd', 'CO'),
    ):
        for i, cap in enumerate(bank(source, side), 1):
            name = f'{prefix}{i}'
            esl = cap['ESL'] if include_esl else 0.
            lines.append(f'C{name} {node} {return_node} {_num(cap["C"])} '
                         f'Rser={_num(cap["ESR"])} Lser={_num(esl)}')
            probes[side].append(f'i(c{name.lower()})')
    return lines, probes


def _bridge(bridge, cox):
    lines = []
    switches = [('H1', 'bus', 'swa', 'gatep'), ('L1', 'swa', '0', 'gaten')]
    if bridge == 'full':
        switches += [('H2', 'bus', 'swb', 'gaten'), ('L2', 'swb', '0', 'gatep')]
    pairs = []
    for name, drain, source, gate in switches:
        lines += [f'VS{name} {drain} ds{name} 0',
                  f'S{name} ds{name} {source} {gate} 0 SWBR',
                  f'DB{name} {source} {drain} DBD',
                  f'COSS{name} {drain} {source} {_num(cox)}',
                  f'BVDS{name} vds{name} 0 V=V({drain},{source})']
        pairs.append((f'v(vds{name.lower()})', f'i(vs{name.lower()})', f'v({gate})'))
    return lines, pairs


def _controller(control):
    common = [
        'BSS ss 0 V=limit((time-TEN)/TSS,0,1)',
        'BERR err 0 V=VSET*V(ss)-V(cap,sgnd)-V(inj)',
        'BTRIP trip 0 V=if(V(active)>.5 & (((OCP>0)&(abs(I(LR))>=OCP)) | ((OVP>0)&(V(out,sgnd)>=OVP))),1,0)',
        'BENABLE active 0 V=if((time>TEN)&(V(bus)>UVLO),1,0)',
        'ARESET trip 0 0 0 0 0 fault 0 SRFLOP Vhigh=1 Vlow=0 Td=2n Trise=2n Tfall=2n',
        'BRUN run 0 V=if(V(active)>.5 & V(fault)<.5,1,0)',
    ]
    if control == 'Voltage Mode':
        return common + [
            'BBASE base 0 V=FMAX+(FBIAS-FMAX)*V(ss)',
            'BRAWC rawc 0 V=V(base)-KP*V(err)-V(vcint)',
            'BVCI vcint 0 V=idt(if(((V(rawc)>=FMAX)&(V(err)<0))|((V(rawc)<=FMIN)&(V(err)>0)),0,KI*V(err)),0,V(run)<.5)',
            'BFREQ freq 0 V=limit(V(rawc),FMIN,FMAX)',
            'BPHASE phase 0 V=idtmod(if(V(run)>.5,2*V(freq),0),0,2)',
            'BGP cmdp 0 V=if((V(run)>.5)&(V(phase)<1)&(V(phase)>2*V(freq)*TDEAD),1,0)',
            'BGN cmdn 0 V=if((V(run)>.5)&(V(phase)>1+2*V(freq)*TDEAD),1,0)',
            'BCTRL ctrl 0 V=V(freq)',
        ]
    return common + [
        'BBASE base 0 V=HHCSEED*V(ss)',
        'BRAWC rawc 0 V=V(base)+KP*V(err)+V(vcint)',
        'BVCI vcint 0 V=idt(if(((V(rawc)>=HHCUPPER)&(V(err)>0))|((V(rawc)<=HHCLOWER)&(V(err)<0)),0,KI*V(err)),0,V(run)<.5)',
        'BCTRL ctrl 0 V=limit(V(rawc),HHCLOWER,HHCUPPER)',
        # The phase latch also sets the start of the next dead interval. Timers
        # reset on the previous half-cycle, giving one event per transition.
        'BAP posage 0 V=idt(1,0,(V(qphase)<.5)|(V(run)<.5))',
        'BAN negage 0 V=idt(1,0,(V(qphase)>.5)|(V(run)<.5))',
        'BPOS poscmp 0 V=HHCS*(V(vcr)-CR_CENTER)+HHCRAMP*max(0,V(posage)-TDEAD)',
        'BNEG negcmp 0 V=-HHCS*(V(vcr)-CR_CENTER)+HHCRAMP*max(0,V(negage)-TDEAD)',
        'BSET qset 0 V=if((V(run)>.5)&(V(qphase)<.5)&((V(negage)>=THMAX)|((V(negage)>=THMIN)&(V(negcmp)>=V(ctrl)))),1,0)',
        'BRESET qreset 0 V=if((V(run)<.5)|((V(qphase)>.5)&((V(posage)>=THMAX)|((V(posage)>=THMIN)&(V(poscmp)>=V(ctrl))))),1,0)',
        'APHASE qset qreset 0 0 0 0 qphase 0 SRFLOP Vhigh=1 Vlow=0 Td=2n Trise=2n Tfall=2n',
        'BGP cmdp 0 V=if((V(run)>.5)&(V(qphase)>.5)&(V(posage)>TDEAD),1,0)',
        'BGN cmdn 0 V=if((V(run)>.5)&(V(qphase)<.5)&(V(negage)>TDEAD),1,0)',
    ]


def _time_schedule(p, tstop, load_step, fra_hz):
    cfg = p.get('spice_config') or {}
    enable = max(float(cfg.get('enable_delay_ms', 0.0))*1e-3, 60e-6)
    soft_start = float(p.get('llc_soft_start', 2e-3))
    soft_start = max(soft_start, 1e-6)
    start = max(float(cfg.get('step_ms', 0.0))*1e-3, enable + soft_start + (6e-3 if load_step else 3e-3))
    recovery = max(5e-3, 250 / p['llc_fmin'])
    preload = None
    if load_step and p.get('llc_bridge') == 'full':
        # Test regulated load steps independently of full-bridge cold light-load startup.
        preparation = max(3e-3, 130 / p['llc_fmin'])
        start = max(start, enable+soft_start+preparation+recovery+.5e-3)
        preload = start-recovery-.5e-3
    first = start if load_step else None
    second = start+recovery if load_step else None
    if load_step:
        earliest = second+recovery
    elif fra_hz:
        earliest = start+8/fra_hz
    else:
        earliest = start+2.5e-3
    stop = float(tstop) if tstop is not None else max(float(cfg.get('stop_ms', 0.))*1e-3, earliest)
    if not math.isfinite(stop) or stop <= enable+soft_start:
        raise ValueError('LLC 仿真结束时间需晚于使能及软启动')
    if (load_step or fra_hz) and stop+1e-12 < earliest:
        raise ValueError('LLC 仿真观察时间过短，无法包含全部阶跃或注入周期')
    return {'enable_s':enable,'soft_start_s':soft_start,'preload_s':preload,
            'step_up_s':first,'step_down_s':second,
            'injection_start_s':start if fra_hz else None,'stop_s':stop}


def _asc(bridge, control):
    lines = [
        'Version 4', 'SHEET 1 1256 680',
        f'TEXT 40 32 Left 3 ;LLC RESONANT CONVERTER - {bridge.upper()} BRIDGE',
        f'TEXT 40 92 Left 2 ;{control.upper()} | SWITCHED CIRCUIT',
        'TEXT 40 450 Left 2 ;Probe V(out), V(vcr), I(LR), I(LM), I(VRECT) and V(gatep), V(gaten).',
        'TEXT 40 502 Left 2 !.include llc_stage.inc',
        'TEXT 40 556 Left 2 ;The included circuit implements the signal path above. Keep both files together.',
    ]
    blocks = [('DC link','Vbus and input caps'),('Primary bridge','GATEP / GATEN'),
              ('Resonant tank','Cr / Lr / Lm'),('Isolation and rectifier','Np/Ns / D1-D4'),
              ('Output port','Cout / resistive load')]
    origins = [40,277,514,751,988]
    for index,(x,(title,detail)) in enumerate(zip(origins,blocks)):
        lines += [f'RECTANGLE Normal {x} 166 {x+210} 258 0',
                  f'TEXT {x+10} 185 Left 2 ;{title}',f'TEXT {x+10} 220 Left 1 ;{detail}']
        if index<len(blocks)-1:
            lines += _asc_arrow(x+210,212,origins[index+1],212)
    lines += [
        'RECTANGLE Normal 334 326 734 408 0',
        'TEXT 350 342 Left 2 ;Voltage feedback and LLC timing',
        'TEXT 350 376 Left 1 ;Switch timing, dead time, UVLO, OVP and tank OCP',
        'LINE Normal 1093 258 1093 366 0',
        'LINE Normal 382 326 382 272 0',
    ]
    lines += _asc_arrow(1093,366,734,366)
    lines += _asc_arrow(382,272,382,258)
    return '\r\n'.join(lines)+'\r\n'


def _asc_arrow(x0,y0,x1,y1):
    dx=(x1-x0)//max(abs(x1-x0),abs(y1-y0))
    dy=(y1-y0)//max(abs(x1-x0),abs(y1-y0))
    return [f'LINE Normal {x0} {y0} {x1} {y1} 0',
            f'LINE Normal {x1-6*dx-3*dy} {y1-6*dy+3*dx} {x1} {y1} 0',
            f'LINE Normal {x1-6*dx+3*dy} {y1-6*dy-3*dx} {x1} {y1} 0']


def project_files(p, op, *, tstop=None, load_step=False, fra_hz=None, fra_amplitude=.1):
    """Build the native ASC reader and its accompanying independent netlist."""
    from llc_model import configuration, controller_gains
    from voltage_nodes import input_drop, output_drop

    p = p | configuration(p)
    bridge = p['llc_bridge']
    control = p['control_mode']
    if fra_hz is not None and (load_step or not (0 < fra_hz <= p['llc_fmin']/5) or
                              not 0 < fra_amplitude <= p['V_out']*.1):
        raise ValueError('LLC FRA 注入频率或幅度超出弱扰动范围，且不能与阶跃合并')
    schedule = _time_schedule(p,tstop,load_step,fra_hz)
    llc = op.get('llc', op)
    freq = llc.get('frequency_Hz',op.get('f_sw',p['f_sw']))
    seed = float(llc.get('hhc_threshold_V') or max(p['llc_hhc_ramp']/(2*freq), .01))
    kp,ki = controller_gains(p,llc)
    qoss = float(p.get('llc_qoss',0.))
    din=input_drop(p)
    dout=output_drop(p)
    cox = max(qoss/(p['V_in']-din) if qoss > 0 else float(p.get('Coss',0.)), 1e-13)
    gate_tau=max(3e-9,float(p.get('Qg',30e-9))*4.7/max(1.,float(p.get('Vgs',10.))))
    from llc_settings import SOURCE_RESISTANCE as bus_r, SOURCE_INDUCTANCE as bus_l
    threads=min(8,max(1,int((p.get('spice_config') or {}).get('simulation_threads',2))))
    method = 'gear' if bridge=='full' else 'trap'
    fhi=p['llc_fmax']; flo=p['llc_fmin']
    threshold_margin=max(abs(seed),p['llc_hhc_ramp']/(2*flo),.1)*4
    vbias = (p['V_in']-din)*.5 if bridge == 'half' else 0.
    params = dict(
        VIN=p['V_in'], VSET=p['V_out']+dout, RLOAD=p['V_out']**2/p['P_out'],
        NTR=p['N'], LRVAL=p['llc_lr'], CRVAL=p['llc_cr'], LMVAL=p['llc_lm'],
        RTANK=max(p['llc_tank_r'], 1e-6), RSW=max(p['Rds_on'], 1e-6),
        VF=p['Vf_diode'], RRECT=max(p['llc_rect_r'], 1e-6), CJ=p.get('llc_diode_cj',0.),
        FMIN=flo, FMAX=fhi, FBIAS=min(max(freq,flo),fhi),
        THMIN=.5/fhi, THMAX=.5/flo, TDEAD=p['llc_dead_time'],
        KP=kp, KI=ki, HHCSEED=seed,
        HHCLOWER=-threshold_margin, HHCUPPER=threshold_margin,
        HHCS=p['llc_hhc_sense'], HHCRAMP=p['llc_hhc_ramp'], CR_CENTER=vbias,
        OCP=p['llc_ocp'], OVP=p.get('llc_ovp',0.), UVLO=p.get('llc_uvlo',0.), GTAU=gate_tau,
        TEN=schedule['enable_s'], TSS=schedule['soft_start_s'], TSTOP=schedule['stop_s'],
        RSRC=bus_r, LSRC=bus_l, TMAX=min(1/fhi/72, max(p['llc_dead_time']/4,2e-8)),
    )
    lines = ['* Independently switched LLC bridge, isolated ideal transformer and real rectifier timing.']
    for key,value in params.items():
        lines.append(f'.param {key}={_num(value)}')
    lines += [
        '.model SWBR SW(Ron={RSW} Roff=1G Vt=.5 Vh=-.25)',
        '.model DBD D(Ron=.015 Roff=1G Vfwd=.7 Epsilon=.01)',
        '.model DR D(Ron={RRECT} Roff=1G Vfwd={VF} Epsilon=.01)',
        'VIN src 0 PWL(0 0 45u {VIN})',
        'VINPUT src lin 0',
        'LSRC lin rin {LSRC} Rser={RSRC}',
        'VBUS rinb bus 0',
        'CR swa crn {CRVAL}',
        'LR crn p {LRVAL} Rser={RTANK}',
        'LM p swb {LMVAL} Rser=0',
        'ESEC secp secn p swb {1/NTR}',
        'FPRI p swb ESEC {-1/NTR}',
        'RISO secn sgnd 100Meg',
        'VSGND sgnd 0 0',
        'DR1 secp rec DR',
        'DR2 sgnd secp DR',
        'DR3 secn rec DR',
        'DR4 sgnd secn DR',
        'VRECT rec cap 0',
        'BVCR vcr 0 V=V(swa,crn)',
        'BVPRI vp 0 V=V(p,swb)',
        'BVDIFF vdrive 0 V=V(swa,swb)',
        'BVDR1 vr1 0 V=V(rec,secp)',
        'BVDR2 vr2 0 V=V(secp,sgnd)',
        'BVDR3 vr3 0 V=V(rec,secn)',
        'BVDR4 vr4 0 V=V(secn,sgnd)',
    ]
    for name,a,b,drop in (('IN','rin','rinb',din),('OUT','cap','out',dout)):
        if drop>0:
            lines.extend((f'.model DREV{name} D(Ron=.001 Roff=1G Vfwd={_num(drop)} Epsilon=.001)',
                          f'DBLOCK{name} {a} {b} DREV{name}'))
        else:
            lines.append(f'VLINK{name} {a} {b} 0')
    if bridge=='half':
        lines.append('VRET swb 0 0')
    if p.get('llc_diode_cj',0.)>0:
        lines.extend(f'CJR{i} {a} {b} {{CJ}}' for i,(a,b) in enumerate(
                     [('secp','rec'),('sgnd','secp'),('secn','rec'),('sgnd','secn')],1))
    bridge_lines,switches = _bridge(bridge,cox)
    lines.extend(bridge_lines)
    caps,cap_probes = _cap_banks(p)
    lines.extend(caps)
    if load_step:
        first=schedule['step_up_s']; second=schedule['step_down_s']
        ramp=max(1e-7,float((p.get('spice_config') or {}).get('edge_us',1.))*1e-6)
        schedule['step_edge_s'] = ramp
        preload = schedule['preload_s']
        load = [(0,.1)] if preload is None else [(0,1),(preload,1),(preload+ramp,.1)]
        load.extend(((first,.1),(first+ramp,.9),(second,.9),(second+ramp,.1)))
        points=' '.join(f'{_num(t)} {level}' for t,level in load)
        lines.extend((f'VPROFILE load_profile 0 PWL({points})',
                      'BLOAD out sgnd I=V(out,sgnd)*V(load_profile)/RLOAD'))
    else:
        lines.extend(('VPROFILE load_profile 0 1','RLOAD out sgnd {RLOAD}'))
    if fra_hz:
        start=_num(schedule['injection_start_s'])
        amplitude, tone = _num(fra_amplitude), _num(fra_hz)
        if bridge=='full':
            # Give LTspice an explicit source breakpoint after soft start.
            lines.append(f'VINJ inj 0 SINE(0 {amplitude} {tone} {start})')
        else:
            lines.append(f'BINJ inj 0 V=if(time>{start},{amplitude}*sin(2*pi*{tone}*(time-{start})),0)')
    else:
        lines.append('VINJ inj 0 0')
    lines.extend(_controller(control))
    lines.extend(('RGP cmdp gatep 1','CGP gatep 0 {GTAU}',
                  'RGN cmdn gaten 1','CGN gaten 0 {GTAU}'))
    probes=['v(out)','v(cap)','v(bus)','v(src)','i(vinput)','i(vbus)','v(vcr)','v(vp)','v(vdrive)',
            'i(lr)','i(lm)','i(vrect)','v(gatep)','v(gaten)','v(fault)','v(ctrl)','v(load_profile)','v(inj)']
    probes += [probe for pair in switches for probe in pair[:2]]
    probes += [f'v(vr{i})' for i in range(1,5)] + [f'i(dr{i})' for i in range(1,5)]
    probes += cap_probes['input']+cap_probes['output']
    if fra_hz:
        probes=['v(cap)','v(inj)','v(fault)','v(gatep)']
    elif load_step:
        probes=['v(out)','i(lr)','i(vrect)','v(load_profile)','v(ctrl)','v(fault)']
    lines += ['.save '+' '.join(probes),
              f'.options threads={threads} method={method} plotwinsize=0 reltol=.001 abstol=1n vntol=1u',
              '.tran 0 {TSTOP} 0 {TMAX} uic']
    meta = dict(model_version=MODEL_VERSION,topology='LLC',bridge=bridge,control=control,
                approximation_notes=MODEL_SCOPE, schedule=schedule,
                qoss_linearized_F=cox,source_r_ohm=bus_r,source_l_H=bus_l,
                drive_center_V=vbias,simulation_threads=threads,solver_method=method,gate_tau_s=gate_tau,
                switch_references=['Q1','Q2'] if bridge=='half' else ['Q1','Q2','Q3','Q4'],
                diode_references=['D1','D2','D3','D4'],
                cap_probes=cap_probes,switch_probes=switches,load_step=bool(load_step),
                fra_hz=fra_hz,fra_amplitude_V=fra_amplitude if fra_hz else None, probes=probes,
                llc_kp=kp,llc_ki=ki,V_in=p['V_in'], V_out=p['V_out'], P_out=p['P_out'])
    netlist = 'LLC switching verification\n.include llc_stage.inc\n.end\n'
    guide = '打开 LLC.asc 可在 LTspice 中执行本工况。\n\n'+'\n'.join('- '+x for x in MODEL_SCOPE)+'\n'
    return {
        'Flyback.cir': netlist.encode('ascii'),
        'LLC.asc': _asc(bridge,control).encode('ascii'),
        'llc_stage.inc': ('\n'.join(lines)+'\n').encode('ascii'),
        'manifest.json': (json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode('utf-8'),
        'README.md': guide.encode('utf-8'),
    }


def write_project(directory, p, op, **options):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    files = project_files(p,op,**options)
    for name,data in files.items():
        (directory/name).write_bytes(data)
    return dict(cir=directory/'Flyback.cir',asc=directory/'LLC.asc',files=files,
                manifest=json.loads(files['manifest.json']))


def measure_raw(raw_path, p, op, *, load_step=False, fra_hz=None):
    """Read the actual switched RAW and compare only complete gate periods."""
    import numpy as np
    from spice_runtime import TransientRaw

    raw_path = Path(raw_path)
    with (raw_path.parent/'manifest.json').open(encoding='utf-8') as stream:
        meta = json.load(stream)
    if meta['load_step'] != bool(load_step) or meta['fra_hz'] != fra_hz:
        raise ValueError('LLC 测量工况与生成的网表不一致')
    if any(not math.isclose(float(meta[key]),float(p[key]),rel_tol=1e-9)
           for key in ('V_in','V_out','P_out')):
        raise ValueError('LLC RAW 所对应的输入、输出或功率与当前工况不一致')
    schedule = meta['schedule']
    raw = TransientRaw(raw_path)
    try:
        t = raw.time
        t_end = float(t[-1])
        if t_end < schedule['stop_s']*(1-1e-4):
            raise ValueError(f'LLC 瞬态未到达计划结束时间，实际 {t_end*1e3:.4g} ms')
        if fra_hz:
            if np.max(raw.trace('v(fault)'))>.5:
                raise ValueError('LLC 开关环路注入触发保护，当前频点不能作为线性环路证据')
            return {'fra':_measure_fra(raw,fra_hz,schedule['injection_start_s'])}
        if load_step:
            result = _load_steps(raw,schedule,p['V_out'])
            result['fault'] = bool(np.max(raw.trace('v(fault)'))>.5)
            result['ready'] = bool(not result['fault'] and all(
                step['pre_in_band'] and step['post_in_band'] for step in result['load_steps']))
            return result
        gp=raw.trace('v(gatep)')
        gn=raw.trace('v(gaten)')
        rises=np.flatnonzero((gp[:-1]<=.5)&(gp[1:]>.5))+1
        nrises=np.flatnonzero((gn[:-1]<=.5)&(gn[1:]>.5))+1
        startup_end=float(t[rises[-25]]) if len(rises)>=25 else t_end
        result = _startup(raw,meta['switch_probes'],schedule,p['V_out'],startup_end)
        if len(rises)<25:
            return dict(result,ready=False,settled=False,V_out_V=None,
                        fault=bool(np.max(raw.trace('v(fault)'))>.5),
                        reason='开关周期不足，保留启动和保护证据。请核对 UVLO、OCP、OVP 与日志。')
        start,stop = int(rises[-25]),int(rises[-1])
        selection = slice(start,stop+1)
        ts = t[selection]
        width=ts[-1]-ts[0]
        values = {}

        def read(probe):
            if probe not in values:
                values[probe] = raw.trace(probe)[selection].astype(float)
            return values[probe]

        def average(values):
            return float(np.trapezoid(values,ts)/width)

        def rms(probe):
            return math.sqrt(max(0.,average(read(probe)**2)))

        def peak(probe):
            return float(np.max(np.abs(read(probe))))

        v=read('v(out)')
        f=float(24/width)
        nominal_load = p['V_out']**2/p['P_out']
        cap_probes = meta['cap_probes']
        switch_probes = meta['switch_probes']
        out_mean = average(v)
        out_pp = float(np.ptp(v))
        mean_first = float(np.trapezoid(v[:len(v)//2],ts[:len(v)//2])/
                          (ts[len(v)//2-1]-ts[0]))
        mean_last = float(np.trapezoid(v[len(v)//2:],ts[len(v)//2:])/
                         (ts[-1]-ts[len(v)//2]))
        peak_vds= [float(np.max(read(probe))) for probe,_,_ in switch_probes]
        median_vds = []
        worst_abs_vds = []
        zvs_fraction = []
        for probe,_,gate in switch_probes:
            edges = rises if gate=='v(gatep)' else nrises
            edges=edges[(edges>=start)&(edges<=stop)]
            before=raw.trace(probe)[edges-1]
            median_vds.append(float(np.median(before)) if len(before) else None)
            worst_abs_vds.append(float(np.max(np.abs(before))) if len(before) else None)
            zvs_fraction.append(float(np.mean(np.abs(before)<=5.)) if len(before) else None)
        half_pos=gp[selection]>.5
        half_neg=gn[selection]>.5
        final_periods=np.diff(t[rises[-25:]])
        target_tolerance=(p.get('ripple_target') or .02)*p['V_out']
        nominal_good = abs(out_mean-p['V_out']) <= max(.02*p['V_out'],target_tolerance)
        frequency_spread = float(np.ptp(final_periods)/np.mean(final_periods))
        fault_active = float(np.max(raw.trace('v(fault)')))>.5
        settled= abs(mean_first-mean_last)<max(.002*p['V_out'],1e-3) and frequency_spread<.06
        result.update(frequency_Hz=f, V_out_V=out_mean,ripple_Vpp=out_pp,
                    I_res_rms_A=rms('i(lr)'),I_res_peak_A=peak('i(lr)'),
                    V_cr_peak_V=peak('v(vcr)'), I_mag_rms_A=rms('i(lm)'),
                    I_rect_rms_A=rms('i(vrect)'),I_rect_peak_A=peak('i(vrect)'),
                    I_rect_mean_A=average(read('i(vrect)')),
                    switch_Vds_peak_V=peak_vds,
                    switch_Vds_pre_turnon_median_V=median_vds,
                    switch_Vds_pre_turnon_abs_max_V=worst_abs_vds,
                    switch_zvs_fraction_below_5V=zvs_fraction,
                    switch_I_rms_A=[rms(probe) for _,probe,_ in switch_probes],
                    diode_Vr_peak_V=[float(np.max(read(f'v(vr{i})'))) for i in range(1,5)],
                    diode_I_rms_A=[rms(f'i(dr{i})') for i in range(1,5)],
                    input_bank_rms_A=[rms(x) for x in cap_probes['input']],
                    output_bank_rms_A=[rms(x) for x in cap_probes['output']],
                    power_in_W=average(read('v(bus)')*read('i(vbus)')),
                    power_out_W=average(v*v*read('v(load_profile)')/nominal_load),
                    ready=bool(nominal_good and settled and not fault_active),
                    regulation_in_band=bool(nominal_good), settled=bool(settled),
                    fault=fault_active,
                    no_gate_overlap=bool(not np.any(half_pos & half_neg)),
                    frequency_spread=frequency_spread,
                    output_drift_V=mean_last-mean_first,
                    steady_window_s=[float(ts[0]),float(ts[-1])])
        # Keep original samples and extrema for the four-cycle visual evidence.
        signal_map={key:(key,None) for key in (
            'v(out)','v(vcr)','v(vp)','v(vdrive)','i(lr)','i(lm)','i(vrect)',
            'v(gatep)','v(gaten)','v(ctrl)')}
        evidence_start=float(t[rises[-5]])
        evidence_end=float(ts[-1])
        result['steady']=raw.plot_samples(signal_map,evidence_start,evidence_end,bins=240)
        stress_probes = ([probe for pair in switch_probes for probe in pair[:2]] +
                         [f'v(vr{i})' for i in range(1,5)] + [f'i(dr{i})' for i in range(1,5)] +
                         cap_probes['input']+cap_probes['output'])
        result['white_box_waveforms']=raw.plot_samples(
            {probe:(probe,None) for probe in stress_probes},evidence_start,evidence_end,bins=150)

        return result
    finally:
        raw.close()


def _startup(raw,switch_probes,schedule,setpoint,end):
    import numpy as np

    t=raw.time
    end=max(float(t[1]),end)
    k=int(np.searchsorted(t,end,'right'))
    output=raw.trace('v(out)')[:k]
    after_enable = t[:k]>=schedule['enable_s']
    crossing=np.flatnonzero((output>=.95*setpoint)&after_enable)
    tank=np.abs(raw.trace('i(lr)')[:k])

    peak=lambda probe: float(np.max(np.abs(raw.trace(probe)[:k])))
    max_probe=lambda probe: float(np.max(raw.trace(probe)[:k]))
    transfer_peaks = []
    for _,_,gate in switch_probes:
        enabled=raw.trace(gate)[:k]>.5
        transfer_peaks.append(float(np.max(tank[enabled])) if np.any(enabled) else None)
    summary=dict(
        target_95_s=float(t[crossing[0]]-schedule['enable_s']) if len(crossing) else None,
        V_out_peak_V=float(np.max(output)), I_res_peak_A=float(np.max(tank)), I_rect_peak_A=peak('i(vrect)'),
        I_mag_peak_A=peak('i(lm)'), V_cr_peak_V=peak('v(vcr)'), I_input_peak_A=peak('i(vinput)'),
        switch_Vds_peak_V=[max_probe(probe) for probe,_,_ in switch_probes],
        switch_I_peak_A=[peak(probe) for _,probe,_ in switch_probes],
        switch_I_transfer_peak_A=transfer_peaks,
        diode_Vr_peak_V=[max_probe(f'v(vr{i})') for i in range(1,5)],
        diode_I_peak_A=[peak(f'i(dr{i})') for i in range(1,5)],
        fault=bool(max_probe('v(fault)')>.5))
    signals={key:(key,None) for key in ('v(out)','v(fault)','i(lr)','i(lm)','i(vrect)','v(vcr)','i(vinput)')}
    signals.update({probe:(probe,None) for pair in switch_probes for probe in pair[:2]})
    signals.update({probe:(probe,None) for i in range(1,5) for probe in (f'v(vr{i})',f'i(dr{i})')})
    waveform=raw.plot_samples(signals,float(t[0]),end,bins=320)
    return dict(startup=summary,startup_waveform=waveform)


def _load_steps(raw,schedule,setpoint):
    import numpy as np

    t,vo=raw.time,raw.trace('v(out)')
    first=schedule['step_up_s'];second=schedule['step_down_s']
    records=[]
    for direction,edge,end in (('10→90%',first,second),('90→10%',second,float(t[-1]))):
        a,b=np.searchsorted(t,[edge,end])
        start=int(np.searchsorted(t,edge-.5e-3))
        before=float(np.trapezoid(vo[start:a],t[start:a])/(t[a-1]-t[start]))
        last=int(np.searchsorted(t,end-.5e-3))
        after=float(np.trapezoid(vo[last:b],t[last:b])/(t[b-1]-t[last]))
        by_order=vo[a:b]
        lows=float(np.min(by_order)); highs=float(np.max(by_order))
        outside=np.flatnonzero(np.abs(by_order-setpoint)>.02*setpoint)
        settle=a+outside[-1]+1 if len(outside) else a
        records.append(dict(direction=direction,time_s=edge,pre_V=before,post_V=after,
                            pre_in_band=bool(abs(before-setpoint)<=.02*setpoint),
                            post_in_band=bool(abs(after-setpoint)<=.02*setpoint),
                            min_V=lows,max_V=highs,undershoot_V=max(0.,before-lows),
                            overshoot_V=max(0.,highs-before),
                            settle_2pct_s=(0. if not len(outside) else float(t[settle]-edge))
                            if settle<b else None))
    signals={name:(name,None) for name in ('v(out)','i(lr)','i(vrect)','v(load_profile)','v(ctrl)')}
    waveform=raw.plot_samples(signals,max(float(t[0]),first-1e-3),float(t[-1]),
                              bins=700,markers=(first,second))
    return dict(load_steps=records,dynamic_waveform=waveform,preload_s=schedule.get('preload_s'),
                fault=bool(np.max(raw.trace('v(fault)'))>.5))


def _measure_fra(raw, hz, start):
    import numpy as np

    end=float(raw.time[-1])
    if end-start < 7.9/hz:
        raise ValueError('LLC FRA 稳态注入周期不足')
    axis=np.linspace(end-6/hz,end,2400,endpoint=False)
    probe=raw._samples_at(['v(cap)','v(inj)'],axis)
    carrier=np.exp(-2j*np.pi*hz*(axis-axis[0]))
    phasor=lambda signal: (2/len(axis))*np.dot(carrier, np.asarray(probe[signal])-np.mean(probe[signal]))
    vo,vi=phasor('v(cap)'),phasor('v(inj)')
    residual=vi+vo
    if abs(vi)<1e-9 or abs(residual)<.002*abs(vi):
        raise ValueError('LLC FRA 输出／注入残差过小，无法可靠还原环路增益')
    gain=-vo/residual
    return dict(frequency_Hz=hz,gain_db=float(20*np.log10(max(abs(gain),1e-30))),
                phase_deg=float(np.angle(gain,deg=True)),
                loop_real=float(gain.real),loop_imag=float(gain.imag),
                injection_V=float(abs(vi)),output_V=float(abs(vo)),residual_V=float(abs(residual)))
