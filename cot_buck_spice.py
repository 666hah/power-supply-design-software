"""Original COT cadence model and synchronous 1–16 phase switching project."""
from cot_settings import active as is_cot

MODEL_VERSION = 'GenericInterleavedBuckCOT-1.1'
_FILES = ('design_params.inc', 'power_stage.inc', 'control.inc', 'analysis.inc')
FRA_KEYS = ('fra_enabled', 'fra_start_hz', 'fra_stop_hz', 'fra_oct',
            'fra_amplitude_pct', 'fra_cycles', 'fra_timeout_s')
_SCOPE = (
    '通用 COT 行为模型。电压误差通过有界 PI 改变触发间隔，相位顺序由共享相位累加器安排。'
    '每次触发经独立延迟形成恒定导通脉冲。相同器件和均匀交错近似稳态均流。',
    '软启动为参考电压缓升。当前假定同步双向电感电流，未实现真实 D-CAP+ 内部纹波注入、'
    '自动均流补偿、减相、跳脉冲或逐周期保护。FRA 对应本通用模型的额定负载。',
    '功率管用可控电阻和体二极管代表。输出电容保留单颗 C/ESR 及已启用的 ESL。'
    '观察每相电流、阶跃及总输出纹波，尖峰和开关损耗另用器件模型核对。',
)


def normalize_cot_settings(raw, nominal):
    from spice_export import normalize_settings
    if raw is not None and not isinstance(raw, dict):
        return normalize_settings(raw)  # Preserve the common settings validation message.
    # Preserve the existing short comparison for projects saved before COT FRA.
    defaults = dict(fra_enabled=0., fra_stop_hz=6000., fra_oct=3., fra_amplitude_pct=.4, fra_cycles=100.)
    raw = raw or {}
    if not {'soft_start_ms', 'step_ms', 'stop_ms', 'enable_delay_ms'}.intersection(raw):
        # Leave enough actual switching periods to verify two quiet windows.
        start = max(1., 12000 / max(nominal, 1.))
        defaults.update(soft_start_ms=start, step_ms=3*start, stop_ms=4*start)
    current = normalize_settings(dict(defaults | raw, cross_enabled=0., short_test=0.))
    if current['step_ms'] <= current['soft_start_ms']+current['enable_delay_ms']:
        raise ValueError('COT 负载阶跃需安排在软启动及使能延时之后')
    return current


def transient_settings(raw, cases):
    nominal = min(c['result']['op']['f_sw'] for c in cases)
    return normalize_cot_settings(raw, nominal)


def _sheet(phases):
    text = [
        'Version 4', 'SHEET 1 1240 920',
        f'TEXT 32 8 Left 3 ;SYNCHRONOUS BUCK - {phases} PHASE COT',
        'TEXT 32 64 Left 2 ;Power stage and controller are editable in the included SPICE files.',
        'TEXT 32 112 Left 2 ;Voltage feedback -> firing cadence -> phase dispatch -> COT one-shots',
        'TEXT 32 144 Left 2 ;Each switch cell drives its own inductor. All inductors feed OUT1.',
        'LINE Normal 80 208 1088 208', 'LINE Normal 80 352 1088 352',
        'TEXT 32 186 Left 2 ;VIN', 'TEXT 32 360 Left 2 ;OUT1: shared output capacitor bank and load',
    ]
    for i in range(phases):
        x = 96+i*60
        text.extend((f'LINE Normal {x+16} 208 {x+16} 240',
                     f'RECTANGLE Normal {x-5} 240 {x+44} 312',
                     f'TEXT {x} 264 Left 1 ;PH{i+1}', f'TEXT {x+2} 286 Left 1 ;L{i+1}',
                     f'LINE Normal {x+16} 312 {x+16} 352'))
    for i, name in enumerate(_FILES):
        text.append(f'TEXT 32 {440+28*i} Left 2 !.include {name}')
    return '\r\n'.join(text)+'\r\n'


def project_files(parameters, *, bundle=None, case=None):
    """Export the same COT switching model to standalone CIR and ASC wrappers."""
    from capacitor_banks import bank
    from cot_loop import controller_gains
    from spice_export import _json, _number

    if not is_cot(parameters):
        raise ValueError('当前工程未选用 Buck COT 控制')
    if bundle is None:
        from design_engine.service import calculate_parameters
        bundle = calculate_parameters(parameters, analysis='endpoints', include_loop=False,
                                      include_cross_regulation=False).runtime_bundle()
    cases = bundle.get('cases') or []
    if not cases or any(c.get('error') or not c.get('result', {}).get('op', {}).get('cot') for c in cases):
        raise ValueError('COT 端点计算未取得有效同构模型')
    current = case or cases[0]
    p, op = current['p'], current['result']['op']
    cot = op['cot']
    phases = cot['phases']
    settings = transient_settings(parameters.get('spice_config'), cases)
    # Initial feed-forward follows the analytical DC loss estimate. Time-varying
    # pulse cadence uses this feed-forward plus normalized voltage feedback.
    r_h, r_l = max(p['Rds_on'], 1e-6)+p.get('Rs', 0.), max(p['Rds_aux'], 1e-6)
    dcr = cot['phase_dcr_ohm']
    cap_in, cap_out = bank(p, 'input'), bank(p)
    f_ref = cot['target_frequency_Hz']
    kp, ki = controller_gains(p, op)
    on_floor = max(2e-9, cot['ton_s']*.0001)
    params = dict(VIN=current['voltage'], PHASES=phases, VSET=cot['output_cap_voltage_V'],
                  IREF=op['I_out']/phases, LP=p['L'], DCR=dcr, RH=r_h, RL=r_l,
                  VF_IN=p['Vf_din'] if p.get('d_in_enable') else 0.,
                  VF_OUT=p['Vf_dout'] if p.get('d_out_enable') else 0.,
                  FREF=f_ref, FIXEDTON=p.get('cot_ton_s', 0.), TOFFMIN=p.get('cot_min_off_s', 0.),
                  OFF_FLOOR=on_floor, KP=kp, KI=ki,
                  FREQCAP=2*max(c['result']['op']['f_sw'] for c in cases),
                  RLOAD=p['V_out']**2/p['P_out'], AFTER=settings['load_after'],
                  TSTART=settings['enable_delay_ms']*1e-3, TSS=settings['soft_start_ms']*1e-3,
                  TLOAD=settings['step_ms']*1e-3, TEND=settings['stop_ms']*1e-3)
    literals = [f'.param {key}={_number(value)}' for key, value in params.items()]
    statements = [
        '.param VBUS={VIN-VF_IN}',
        '.param TON={if(FIXEDTON>0,FIXEDTON,VSET/(VBUS*FREF))}',
        '.param FF={FREF*(VSET+IREF*(RL+DCR))/VSET*VBUS/(VBUS-IREF*(RH-RL))}',
        '.param FBIAS={FF*VSET/(VBUS*FREF*TON)}',
        '.param FMAX={min(FREQCAP,1/(TON+max(TOFFMIN,OFF_FLOOR)))}',
        '.param MAXSTEP={min(TON,1/(PHASES*FMAX))/9}',
    ]
    voltages = list(dict.fromkeys(c['voltage'] for c in cases))
    if case is None and len(voltages) > 1:
        statements.append('.step param VIN list '+' '.join(_number(v) for v in voltages))
    settings_inc = '\n'.join(literals+statements)+'\n'
    control = [
        'B_REF ref 0 V=VSET*limit((time-TSTART)/max(TSS,1n),0,1)',
        'B_ERR err 0 V=(V(ref)-V(cap1))/VSET',
        'B_UNLIMITED request 0 V=V(ref)/VSET*FBIAS+KP*V(err)+V(integral)',
        'B_INT integral 0 V=idt(KI*V(err)+2000*(limit(V(request),0,FMAX)-V(request)),0,time<TSTART)',
        'B_RATE rate 0 V=if(time<TSTART,0,limit(V(request),0,FMAX))',
        'C_TICKS ticks 0 1n ic=0',
        'B_TICKS 0 ticks I=1n*V(rate)',
    ]
    power = [
        'VIN_SOURCE input 0 {VIN}',
        'B_INPUT_BLOCK input vbus V={VF_IN}',
        # Generic switch utilization: body diodes only provide dead-time path.
        '.model COT_H SW(Ron={RH} Roff=1e9 Vt=.51 Vh=-.005)',
        '.model COT_L SW(Ron={RL} Roff=1e9 Vt=.51 Vh=-.005)',
        '.model COT_BODY D(Is=1n Rs=5m N=1)',
    ]
    for i in range(1, phases+1):
        offset = (phases-i)/phases
        control += [
            f'B_GATE{i} gate{i} 0 V=if(floor(V(ticks)+{offset:.12g})>floor(delay(V(ticks),{{TON}})+{offset:.12g}),1,0)',
            f'B_LO{i} lo{i} 0 V=if(time<TSTART,0,1-V(gate{i}))',
        ]
        power += [
            f'SH{i} vbus sw{i} gate{i} 0 COT_H',
            f'SL{i} sw{i} 0 lo{i} 0 COT_L',
            f'DH{i} sw{i} vbus COT_BODY',
            f'DL{i} 0 sw{i} COT_BODY',
            f'L{i} sw{i} cap1 {{LP}} Rser={{DCR}}',
        ]
    for prefix, node, caps in (('CIN', 'vbus', cap_in), ('COUT', 'cap1', cap_out)):
        for i, row in enumerate(caps, 1):
            esl = row['ESL'] if settings['include_cap_esl'] else 0.
            power.append(f'{prefix}{i} {node} 0 {_number(row["C"])} Rser={_number(row["ESR"])} Lser={_number(esl)}')
    if p.get('d_out_enable'):
        # The port is a resistive test load. Match the preset fixed drop when
        # forward-biased and block an impossible negative DC startup port.
        power.append('B_OUT out1 0 V=max(0,V(cap1)-VF_OUT)')
        power.append('B_OUT_CURRENT cap1 0 I=I(B_OUT)*(-1)')
    else:
        power.append('V_OUT cap1 out1 0')
    power.append('B_LOAD out1 0 I=V(out1)/RLOAD*(1+(AFTER-1)*limit((time-TLOAD)/1u,0,1))')
    traces = ['V(out1)', 'V(cap1)', 'V(ref)', 'V(rate)', 'I(VIN_SOURCE)']
    traces += [f'{prefix}{i}{suffix}' for i in range(1, phases+1)
               for prefix, suffix in (('I(L', ')'), ('V(gate', ')'), ('V(sw', ')'))]
    analysis = [
        f'.options threads={int(settings["simulation_threads"])} method=trap reltol=0.001 plotwinsize=0',
        '.tran 0 {TEND} 0 {MAXSTEP} uic',
        '.save '+' '.join(traces),
    ]
    meta = dict(schema='powerdesign-ltspice-1', model_version=MODEL_VERSION, topology='BUCK',
                controller_mode='Constant On-Time', settings=settings, voltages=voltages,
                controller_pi=dict(kp_hz=kp, ki_hz_per_s=ki),
                hardware=dict(kind='interleaved-synchronous-buck', phases=phases, phase_L_H=p['L'],
                              phase_dcr_ohm=dcr), cot=cot, approximation_notes=list(_SCOPE))
    readme = '# Buck COT 交错仿真\n\n打开 Flyback.asc 或 Flyback.cir。原理图使用结构视图。'
    readme += '电路卡片与元件数值可在对应的 .inc 文件编辑。稳态请观察每相 I(Ln)、V(gaten)、V(swn) 与 V(out1)。\n\n'
    readme += '\n'.join('- '+note for note in _SCOPE)+'\n'
    data = {
        'Flyback.cir': ('Synchronous interleaved Buck COT\n'
                        +'\n'.join('.include '+name for name in _FILES)+'\n.end\n').encode('ascii'),
        'Flyback.asc': _sheet(phases).encode('ascii'),
        'design_params.inc': settings_inc.encode('ascii'),
        'power_stage.inc': ('\n'.join(power)+'\n').encode('ascii'),
        'control.inc': ('\n'.join(control)+'\n').encode('ascii'),
        'analysis.inc': ('\n'.join(analysis)+'\n').encode('ascii'),
        'manifest.json': _json(meta).encode('utf-8'),
        'design.json': _json({k:v for k,v in parameters.items() if not k.startswith('_')}).encode('utf-8'),
        'README.md': readme.encode('utf-8'),
    }
    from cot_advanced_spice import enhance_project
    return enhance_project(data, p, op, settings)
