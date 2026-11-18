"""Single review catalog. A model check is not hardware certification."""
import math

STATE_LABELS = {'pass': '满足', 'review': '需复核', 'undefined': '未计算',
                'na': '不适用', 'reference': '初选参考'}


def check_catalog(p, res, loop=None, loop_error=None):
    from isolated_outputs import selected_params
    source = p
    p = selected_params(p)
    op, wf = res['op'], res['wf']
    checks = []

    def add(cid, name, actual, limit=None, comparison='<=', unit='', state=None, note=''):
        if state is None:
            if actual is None or not math.isfinite(actual):
                state = 'undefined'
            else:
                ok = {'<=': lambda: actual <= limit, '>=': lambda: actual >= limit,
                      '<': lambda: actual < limit, '>': lambda: actual > limit}[comparison]()
                state = 'pass' if ok else 'review'
        margin = (limit-actual if comparison in ('<=', '<') else actual-limit) if (
            state not in ('reference', 'na') and isinstance(actual, (int, float)) and limit is not None) else None
        checks.append(dict(id=cid, name=name, value=actual, limit=limit,
                           comparison=comparison, unit=unit, margin=margin,
                           pass_=state == 'pass', state=state, note=note))

    cot = op.get('cot')
    if cot:
        add('L_min', '每相电感与零谷值临界值', op['L'], op['L_min'], '参考', 'H',
            state='reference', note='同步强制开关可出现负谷值。')
        add('cot_phase_valley', '每相电感电流谷值', op['I_L_min'], 0., '>=', 'A',
            note='负谷值提示回流。轻载减相及二极管模拟模式需单独核对。')
        if cot['min_off_s'] > 0:
            add('cot_min_off', '每相关断时间', cot['toff_s'], cot['min_off_s'], '>=', 's')
        eng=cot.get('engineering') or {}; cfg=eng.get('configuration') or {}
        if eng:
            add('cot_imbalance','最大相均流偏差',eng['phase_imbalance_pct'],cfg['phase_imbalance_limit_pct'],unit='%',
                note='以全相平均电流为基准，含每相导通压降、定时、采样失配及有界均流修正。')
            add('cot_trim','均流调节未触及修正限幅',int(eng['trim_saturated']),0.,unit='',
                note='达到限幅后，继续增大均流增益不能消除该相偏差。')
            dyn=eng['dynamic']
            if dyn['enabled']:
                for key,name,limit in (('droop','负载增加电压跌落','droop_limit_V'),('overshoot','掉载电压上冲','overshoot_limit_V')):
                    add('cot_dynamic_'+key,name,dyn[key+'_bound_V'],dyn[limit] or None,unit='V',
                        state=None if dyn[limit]>0 else 'undefined',note=dyn['note'])
                response=dyn.get('closed_loop') or {}
                if response.get('available'):
                    excursion=max(response['droop_V'],response['overshoot_V'])
                    for key,title in (('droop','加负载平均闭环最大偏差'),('overshoot','掉载平均闭环最大偏差')):
                        limit=dyn[key+'_limit_V']
                        add('cot_closed_loop_'+key,title,excursion,limit or None,unit='V',
                            state=None if limit>0 else 'undefined',note=response['note'])
                elif response:
                    add('cot_closed_loop_transient','平均闭环负载响应',None,state='undefined',note=response.get('reason','不可用'))
            else:
                add('cot_dynamic_configuration','输出电容动态约束',None,state='undefined',
                    note='填写负载阶跃、响应延迟、允许跌落及上冲；稳态交错抵消不构成动态容量通过依据。')
            for row in eng['protection']:
                add(f'cot_phase_{row["id"]}_ocp',f'第 {row["id"]} 相采样峰值与限流阈值',row['sampled_peak_A'],
                    row['limit_A'],unit='A',state=None if row['limit_A'] else 'undefined',
                    note='阈值在采样电流口径；保护延迟后的峰值另与电感饱和能力核对。')
                saturation=p.get('inductor_saturation_current',0.)
                if row['delayed_trip_peak_A'] is not None and saturation>0:
                    add(f'cot_phase_{row["id"]}_trip_peak',f'第 {row["id"]} 相延迟限流峰值与 Isat',
                        row['delayed_trip_peak_A'],saturation,unit='A')
            for row in cot['phase_data']:
                if p.get('inductor_rated_current',0)>0:
                    add(f'cot_phase_{row["id"]}_rms',f'第 {row["id"]} 相电感 RMS',row['current_rms_A'],p['inductor_rated_current'],unit='A')
                if p.get('inductor_saturation_current',0)>0:
                    add(f'cot_phase_{row["id"]}_peak',f'第 {row["id"]} 相电感峰值',max(abs(row['current_valley_A']),abs(row['current_peak_A'])),p['inductor_saturation_current'],unit='A')
            if cfg['light_load']=='diode_emulation' and cot['reverse_current']:
                add('cot_light_load','二极管模拟零电流区',None,state='undefined',
                    note='连续导通计算已越过零电流；此工况使用开关模型核对，当前 FCCM 波形不能作为二极管模拟结果。')
            if cfg['uvlo_on_V']:
                add('cot_uvlo','输入满足启动欠压阈值',op['V_in'],cfg['uvlo_on_V'],'>=','V')
            if cfg['ovp_V']:
                add('cot_ovp','输出低于过压阈值',cot['output_cap_voltage_V'],cfg['ovp_V'],'<','V')
            if cfg['dead_time_s']:
                shortest=min(min(r['ton_s'],r['toff_s']) for r in cot['phase_data'])
                add('cot_deadtime','死区短于最短导通或关断窗口',cfg['dead_time_s'],shortest,'<','s',
                    note='死区损耗一阶估算；时序与换流仍在开关模型验证。')
            if cfg['source_inductance_H'] or cfg['source_resistance_ohm']:
                add('cot_input_network','输入阻抗与滤波互动',None,state='review',
                    note='源电阻直流压降与损耗已计入；当前平均电压环按刚性母线，输入 R/L/C 动态在开关 FRA 和阶跃中核对。')
    elif op['topology'] == 'FLYBACK':
        add('L_min', '励磁电感 Lm 初选参考', op['L'], op.get('L_min'), '参考', 'H',
            state='reference' if op['mode'] == 'CCM' else 'na',
            note='CCM 初选采用 40% 原边电流纹波和 1.5 倍系数。工作模式按原边谷值判定，选型核对峰值电流、磁密、气隙及温升。')
    elif op['topology'] == 'QR-FLYBACK':
        add('L_min', '励磁电感 Lm', op['L'], unit='H', state='na',
            note='按退磁、谷底延迟和实际工作频率检查。')
    else:
        add('L_min', '电感量与设计初选建议', op['L'], op.get('L_min', 0), '>=', 'H',
            state='na' if op.get('L_min', 0) <= 0 else None,
            note='初选值为 CCM 临界电感的 1.5 倍。工作模式按实际谷值电流判定。')
    from capacitor_banks import bank,total
    ctot = total(p)
    target = p['ripple_target'] * op['V_out']
    add('C_charge', '电荷纹波所需输出容量', ctot, op['C_min'], '>=', 'F')
    # ESR-only screening is separate from capacitance; use the Buck current
    # swing (not the diode peak). Parallel screening neglects frequency/ESL.
    rs=[c['ESR'] for c in bank(p)]
    r=0. if 0 in rs else 1/sum(1/x for x in rs)
    di = (cot['total_output_current_ripple_A'] if cot else op['dI_L']
          if op['topology'] in ('BUCK', 'ACF-FORWARD') else op['I_d_pk'])
    add('ESR_ripple', 'ESR 纹波初筛', di*r, target, unit='V',
        note='低频并联 ESR 初筛；最终以复阻抗分流后的输出纹波检查为准。')
    add('ripple', '低频输出纹波', wf['ripple_pp'], target, unit='V',
        note='ESL 尖峰不计入此项。')
    add('efficiency', '模型效率目标', res['eta'], p.get('target_eta', .92), '>=',
        note='输入/输出电容 ESR 已计入；未计辅助电源、热态参数等系统损耗。')
    add('efficiency_preset_gap', '预设与最终效率差值', abs(res['eta_delta'])*100, 2., unit='pp',
        note='2 个百分点为设计复核提示，不是模型精度保证；偏差较大请调整预设并重新设计/整定。最终效率不覆盖输入值。')
    devices = [(k, (res.get('mag') or {}).get(k)) for k in ('inductor', 'transformer')]
    devices = [(k, d) for k, d in devices if d]
    if not devices:
        add('magnetics', '磁件选芯', None, state='review',
            note=(res.get('mag') or {}).get('reason') or '没有有效磁件计算结果。')
    for kind, dev in devices:
        suffix = ('_T' if kind == 'transformer' else '_L') if len(devices) > 1 else ''
        title = '变压器' if kind == 'transformer' else '电感'
        if not dev.get('ok'):
            add('magnetics'+suffix, title+'选芯', None, state='review', note=dev.get('reason', '选芯失败'))
            continue
        if dev.get('design_enabled') is False:
            for cid, label, actual, key in (
                    ('inductor_rms', '成品电感 RMS 电流能力', dev['I_rms'], 'inductor_rated_current'),
                    ('inductor_peak', '成品电感饱和电流能力', dev['I_pk'], 'inductor_saturation_current')):
                rating = dev[key]
                add(cid, label, actual, rating if rating > 0 else None, unit='A',
                    state=None if rating > 0 else 'undefined',
                    note='与用户填写的厂家额定值比较，未含温度降额或 L(I) 曲线；0 表示未提供。')
            add('inductor_dcr', '成品电感 DCR 损耗覆盖', dev['R_dc'] or None,
                unit='Ω', state='pass' if dev['R_dc'] > 0 else 'undefined',
                note='仅确认已填入 DCR，不代表选型通过；直流铜损 Irms²×DCR。')
            add('inductor_extra_loss', '成品电感附加损耗覆盖', dev['P_extra'] or None,
                unit='W', state='review' if dev['P_extra'] > 0 else 'undefined', note=dev['note'])
            add('inductor_thermal', '成品电感温升', None, state='undefined',
                note='未输入经过验证的热模型，须按厂家温升曲线或实测核对；不使用虚构的磁芯尺寸估温升。')
            continue
        add('B_sat'+suffix, title+'峰值磁密', dev['B_pk'], p['Bsat'], '<', unit='T')
        add('temp_rise'+suffix, title+'估算温升', dev['dT'], p.get('temp_rise_limit', 40), unit='K')
        add('window_fill'+suffix, title+'裸铜窗口填充率', dev['fill'], 1., note='未含绝缘、骨架、工艺余量。')
        if kind == 'transformer' and dev.get('gap_design'):
            gap = dev['gap_design']
            add('transformer_gap', '线性磁路下目标励磁电感的可实现性', gap['target_inductance_H'],
                gap['L_ungapped_H'], unit='H',
                state='pass' if gap['status']=='estimated' else 'review' if gap['status']=='infeasible' else 'undefined',
                note=gap['note'])
    if loop is None:
        add('loop', '环路结果', None, state='undefined', note=loop_error or '环路依赖加载后计算。')
    elif loop['fc'] is None:
        add('loop', '环路 0 dB 下降穿越', None, state='review', note='扫描范围内无下降穿越，PM 未定义，不能据此判稳定。')
    else:
        add('phase_margin', '全部穿越的最小相位裕度', loop['min_pm'], p.get('pm_target', 60)-1., '>=', 'deg', note='目标容差 1°。')
        highest = max(v['fc'] for v in loop['all_crosses'])
        model_limit = loop.get('model', {}).get('recommended_fc_max')
        add('fc_vs_fsw', '最高穿越与模型带宽建议' if model_limit else '最高穿越与开关频率建议', highest,
            model_limit or op.get('fc_recommended_max', op['f_sw']/6), unit='Hz')
        rhp = (loop['model'].get('rhp_zero_estimate') or math.inf) if loop.get('model',{}).get('experimental') else op.get('rhp_zero', math.inf)
        add('rhp_bandwidth', 'RHP 零点带宽建议', highest, rhp/5, unit='Hz',
            state='na' if not math.isfinite(rhp) else None)
        add('gain_margin', '有限增益裕度', loop['gm_db'], 0, '>', 'dB',
            state='na' if loop['gm_infinite'] else None,
            note='仅检查扫描范围；未检出不代表无限裕量。' if loop.get('gm_scan_limited') or loop.get('gm_band_limited') else
                 '没有有限相位穿越，不表示无限硬件稳定裕量。')
    if loop and loop.get('model'):
        model = loop['model']
        model_label = 'COT 电压外环模型适用性' if model.get('kind') == 'cot-cadence-pi' else '多路环路模型适用性'
        add('loop_model', model_label, None, state='review', note=model['assumptions'])
        add('loop_closed_poles', '近似闭环极点实部最大值', loop['closed_loop_max_pole_real'], 0, '<', 'rad/s',
            note='近似模型的极点检查，不替代所有角点、控制器与样机 FRA 验证。')
        if model.get('experimental') and 'derivative_error' in model:
            add('loop_derivative', '周期映射差分一致性', model['derivative_error'], .03,
                note='两档微扰的雅可比矩阵相对差异上限 3%。')
        if model.get('experimental') and 'inner_spectral_radius' in model:
            add('loop_inner_map', '内环及功率级周期谱半径', model['inner_spectral_radius'], 1., '<',
                note='大于等于 1 时不得只凭外环 PM 判断稳定，自动整定拒绝写回。')
    if op.get('f_max'):
        add('f_sw_max', 'QR 工作频率上限', op['f_sw'], op['f_max'], unit='Hz')
    if p.get('Kc', 0) > 1 and op['topology'] in ('FLYBACK', 'QR-FLYBACK'):
        vr = op['V_r']
        add('rcd_margin', 'RCD 钳位高于反射电压', p['Kc']*vr, vr, '>', 'V')
    if op['topology'] == 'ACF-FORWARD':
        add('forward_duty', '正激占空比上限', op['D'], op['forward_d_max'], '<')
        add('clamp_cap', '钳位电容隆起预算', op['C_clamp'], op['C_clamp_min'], '>=', 'F')
    for rail in res.get('outputs',[]):
        spec, child = rail['spec'],rail['op']
        tag = f"OUT{rail['id']}"
        add(tag+'_ripple',tag+' 低频纹波',rail['ripple_pp'],spec['ripple_target']*spec['V_out'],unit='V')
        add(tag+'_cap',tag+' 电荷所需容量',total(spec),child['C_min'],'>=','F')
        if op.get('coupled_model') or op.get('acf_model'):
            add(tag+'_dc_voltage',tag+' 解算相对反馈设定/匝比估算偏差',abs(child['V_out']/spec['V_out']-1)*100,2.,unit='%',
                note='非反馈路基准由实际副边匝数比估算；固定电阻负载，主反馈约束解算。2% 仅为复核提示，不是实测稳压精度。')
            add(tag+'_small_ripple',tag+' 小纹波近似适用性',rail['ripple_pp']/child['V_out']*100,10.,unit='%',
                note='直流解算把输出电容视为刚性电压；纹波超过 10% 时不应使用此近似。')
    for winding in (res.get('mag',{}).get('transformer') or {}).get('windings',[]):
        tag = f"OUT{winding['id']}"
        add(tag+'_turns',tag+' 匝比近似电压',winding['V_turns_est'],unit='V',state='review',
            note='由主反馈电压和整数副边匝数比计算，不是独立输入或稳压精度通过项；压降、耦合及交叉调整率需另行复核。')
    if res.get('outputs') and not (op.get('coupled_model') or op.get('acf_model')):
        add('cross_regulation','未反馈输出交叉调整率',None,state='undefined',
            note='标称功率比例模型不验证交叉调整率；独立负载变化、空载和压降须仿真/实测。')
    if op.get('coupled_model'):
        add('coupled_scope','逐对耦合模型的适用边界',None,state='review',
            note='定频 SSR、线性 L 矩阵、恒阻负载、刚性输出电压与理想电压钳位。未含 Coss/Cj 振铃、磁饱和。环路页可按已收敛周期解作低频实验性线性化；不是旧功率比例 Bode。')
    if op.get('acf_model'):
        add('acf_periodic_scope','正激周期计算模型边界',None,state='review',note=op['acf_model']['assumptions'])
        add('acf_periodic_residual','正激周期与电荷平衡残差',op['acf_model']['normalized_residual'],1e-6)
        add('acf_energy_balance','正激周期数值能量残差',op['acf_model']['energy_balance_relative']*100,2.,unit='%',note='隐式时间步引入的数值耗散；不作为真实器件损耗。')
    for i,dev in enumerate(res.get('mag',{}).get('inductors',[]),1):
        if dev.get('ok'):
            add(f'OUT{i}_L_B',f'OUT{i} 输出电感峰值磁密',dev['B_pk'],p['Bsat'],'<','T')
            add(f'OUT{i}_L_T',f'OUT{i} 输出电感温升',dev['dT'],p.get('temp_rise_limit',40),unit='K')
    for dev in res.get('mag',{}).get('phase_inductors',[]):
        if dev.get('ok') and dev.get('design_enabled') is not False:
            i=dev['id']
            add(f'cot_phase_{i}_B',f'第 {i} 相电感峰值磁密',dev['B_pk'],p['Bsat'],'<','T')
            add(f'cot_phase_{i}_T',f'第 {i} 相电感温升',dev['dT'],p.get('temp_rise_limit',40),unit='K')
    psr = res.get('psr')
    if psr:
        add('psr_vin_low','MP6005 输入下限',op['V_in'],8.,'>=','V')
        add('psr_vin_high','MP6005 输入上限',op['V_in'],80.,unit='V')
        add('psr_duty','MP6005 最大占空比',op['D'],.7)
        add('psr_cs','MP6005 采样电压设计裕量',psr['Vcs_peak'],.128,unit='V',note='0.8×160mV 的初选建议。')
        add('psr_limit','MP6005 电流限值低端',psr['Vcs_peak'],.140,unit='V')
        add('psr_L','MP6005 最低采样电流下电感',op['L'],psr['Lpri_min'],'>=','H')
        add('psr_t33','MP6005 33mV 最短退磁导通',psr['tcon_min33'],.7e-6,'>=','s')
        add('psr_tcon','MP6005 当前次级导通窗口',psr['tcon'],.6e-6,'>=','s')
        add('psr_fbneg','MP6005 负向 FB 电流',psr['Ifb_negative'],.001,'<','A')
        add('psr_rh','MP6005 分压上电阻上限',psr['RfbH'],100e3,'<','Ω')
        add('psr_reg','MP6005 Rreg+Rs 档位',source.get('psr_Rreg',6800)+p['Rs'],state='pass' if psr['compensation_gain'] is not None else 'review',
            note='仅手册规定的阻值范围有效；空档不能确定补偿/抖频配置。')
        add('psr_divider','MP6005 标称分压设定偏差',abs(psr['Vout_error'])/op['V_out']*100,2.,unit='%',note='不含 Vref 容差和实际输出调整率。')
        add('psr_vcc','MP6005 VCC 上限',psr['Vcc'],16.,unit='V')
        add('psr_gate','MOS 驱动不超过 VCC',p['Vgs'],psr['Vcc'],unit='V')
        add('psr_model','MP6005 控制动态验证',None,state='undefined',note=psr['note'])
    from component_management import evaluate_components
    for item in evaluate_components(source, res)['checks']:
        checks.append(dict({key:item[key] for key in
            ('id','name','value','limit','comparison','unit','margin','pass_','state')},
            note='额定值、比例与未覆盖项详见关键器件 BOM 与降额表；此项仅作模型内初筛。'))
    return checks
