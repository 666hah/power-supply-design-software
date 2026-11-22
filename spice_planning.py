"""Cheap, explicit LTspice work plans. Never change the circuit or solver mesh."""
from __future__ import annotations

import math


def qr_charge_observation(parameters):
    """Scheduling hint for slow non-feedback rails, never a settling proof."""
    if parameters.get('topology')!='QR-FLYBACK':return []
    from isolated_outputs import output_specs
    from capacitor_banks import bank
    selected=int(parameters.get('feedback_output',1));rows=[]
    for n,rail in enumerate(output_specs(parameters),1):
        if n==selected or rail['P_out']<=0:continue
        capacitance=sum(c['C'] for c in bank(rail))
        tau=rail['V_out']**2/rail['P_out']*capacitance
        rows.append(dict(output=n,RC_s=tau,recommended_observation_s=2*tau))
    return rows


def recommend_settings(parameters, settings, scope=None):
    """Raise observation windows conservatively; do not pretend this proves settling.

    The lowest compensator zero is only a scheduling proxy, not a closed-loop
    pole. Actual transient/periodicity checks remain the acceptance authority.
    Existing longer windows, device parameters and FRA resolution are retained.
    """
    from spice_export import normalize_settings
    from isolated_outputs import output_specs
    from plants import resolve_controller_type
    s = normalize_settings(settings)
    if parameters.get('topology')=='LLC':
        start = (parameters.get('llc_soft_start',.008)+.005)*1000+s['enable_delay_ms']
        s['step_ms']=max(s['step_ms'],math.ceil(start))
        s['stop_ms']=max(s['stop_ms'],s['step_ms']+10.)
        s.update(cross_enabled=0.,line_load_enabled=0.,short_test=0.)
        if scope in ('quick','full'):
            s['fra_enabled']=float(scope=='full')
        elif scope is not None:
            raise ValueError('未知仿真任务范围')
        return normalize_settings(s)
    fs = s['frequency_hz'] or float(parameters['f_sw'])
    zeros = [s['fz1'] or float(parameters.get('fz1', 0))]
    if resolve_controller_type(parameters.get('controller_type','auto'),parameters.get('control_mode')) == 'type3':
        zeros.append(s['fz2'] or float(parameters.get('fz2', 0)))
    zeros = [f for f in zeros if f > 0]
    settling = max(.002, 420 / fs, 7 / (2 * math.pi * min(zeros)) if zeros else .004)
    # A feedback bandwidth estimate does not cover an unregulated, lightly
    # loaded auxiliary winding. Reserve two RC time scales as a first budget;
    # the actual per-cycle charge check still decides whether it has settled.
    settling=max([settling]+[r['recommended_observation_s'] for r in qr_charge_observation(parameters)])
    step = s['enable_delay_ms'] + s['soft_start_ms'] + settling * 1000 + 420000 / fs
    # Even-millisecond rounding makes the recommendation easy to edit.
    s['step_ms'] = max(s['step_ms'], math.ceil(step / 2) * 2)
    after = max(s['stop_ms'] - settings.get('step_ms', s['step_ms']), 4., 420000 / fs)
    s['stop_ms'] = max(s['stop_ms'], s['step_ms'] + after)
    if s['short_test']:
        s['stop_ms'] = max(s['stop_ms'], s['short_start_ms'] + s['short_duration_ms'] + after)
    if scope == 'quick':
        s.update(fra_enabled=0., cross_enabled=0., short_test=0., line_load_enabled=0.)
    elif scope == 'full':
        s.update(fra_enabled=1., cross_enabled=float(len(output_specs(parameters)) > 1), line_load_enabled=1.)
        if parameters.get('topology') == 'QR-FLYBACK':
            rails = output_specs(parameters)
            # An unchanged min/max load cannot measure cross regulation. Keep
            # the user's load range; never invent a light-load corner.
            if rails and not any(float(r.get('P_out_min', r['P_out'])) < float(r['P_out']) for r in rails):
                s['cross_enabled'] = 0.
    elif scope is not None:
        raise ValueError('未知仿真任务范围')
    return normalize_settings(s)


def execution_plan(parameters, settings):
    """Describe selected work, not a promise about simulator wall-clock time."""
    from isolated_outputs import output_specs
    from spice_studies import corner_plan
    from spice_export import normalize_settings
    s = normalize_settings(settings)
    if parameters.get('topology')=='LLC':
        from llc_spice import _time_schedule
        from llc_spice_comparison import _fra_grid
        from spice_boundary import voltages as input_boundaries
        voltages=input_boundaries(parameters)
        p=dict(parameters,spice_config=s)
        nominal=_time_schedule(p,None,False,None)
        step=_time_schedule(p,None,True,None)
        grid=_fra_grid(s,p['llc_fmin']/5) if s['fra_enabled'] else []
        stages=[]
        for voltage in voltages:
            stages.extend([
                dict(vin=voltage,kind='transient',name='满载从零启动与稳态',
                     duration_s=nominal['stop_s'],timeout_s=s['simulation_timeout_s']),
                dict(vin=voltage,kind='load_step',name='10% ↔ 90% 双向负载阶跃',
                     duration_s=step['stop_s'],timeout_s=s['simulation_timeout_s']),
            ])
            if grid:
                stages.append(dict(vin=voltage,kind='fra',name='两档幅值的开关 FRA',
                                   points=len(grid),timeout_s=2*len(grid)*s['fra_timeout_s']))
        return dict(topology='LLC',voltages=voltages,output_count=1,stages=stages,
                    cross_count=0,cross_enabled=False,cross_requested=False,cross_skip_reason='',
                    cross_coverage='单路',fra_enabled=bool(grid),fra_points_approx=len(grid),
                    skipped=[] if grid else ['开关 FRA'],reuse=False,qr_charge_observation=[],
                    timeout_budget_s=sum(stage['timeout_s'] for stage in stages),
                    transient_duration_s=sum(stage.get('duration_s',0) for stage in stages),
                    step_ms=step['step_up_s']*1000,stop_ms=step['stop_s']*1000,
                    max_load_step=dict(feedback_output=1,low_fraction=.1,high_fraction=.9,stop_s=step['stop_s']))
    from spice_boundary import load_definition, voltages as input_boundaries
    voltages = input_boundaries(parameters)
    maximum_step = load_definition(parameters, s)
    rails = output_specs(parameters)
    cross_requested = bool(s['cross_enabled'] and len(rails) > 1)
    unchanged = bool(rails) and not any(float(r['P_out_min']) < float(r['P_out']) for r in rails)
    cross = cross_requested and not unchanged
    cross_skip_reason = ('各路最小功耗与额定功耗相同，未定义轻重载变化；请先填写各路实际最小功耗。'
                         if len(rails)>1 and unchanged else '')
    corners, coverage = corner_plan(rails, s['cross_mode']) if cross else ([], '未选择' if len(rails) > 1 else '单路不适用')
    fs = s['frequency_hz'] or float(parameters['f_sw'])
    stop = min(s['fra_stop_hz'], fs / 10)
    points = max(0, math.ceil(math.log2(stop / s['fra_start_hz']) * s['fra_oct']) + 1) if stop > s['fra_start_hz'] else 0
    stages = []
    for vin in voltages:
        for name in (['满载从零启动与稳态', '短路注入'] if s['short_test'] else ['满载从零启动与稳态']):
            stages.append(dict(vin=vin, kind='transient', name=name, duration_s=s['stop_ms'] / 1000,
                               timeout_s=s['simulation_timeout_s']))
        stages.append(dict(vin=vin, kind='load_step', name='反馈路 10% ↔ 90% 双向负载阶跃',
                           duration_s=maximum_step['stop_s'],timeout_s=s['simulation_timeout_s']))
        if s['fra_enabled']:
            stages.append(dict(vin=vin, kind='fra', name='环路 FRA 与半幅复核', points=points,
                               timeout_s=2 * s['fra_timeout_s']))
        if cross:
            stages.append(dict(vin=vin, kind='cross', name=f'{len(corners)} 组轻重载组合',
                               duration_s=max(s['step_ms'], 8.) / 1000 + (len(corners)-1) * s['cross_hold_ms'] / 1000,
                               timeout_s=s['cross_timeout_s']))
    if s['line_load_enabled']:
        stages.append(dict(kind='line_load',vin=voltages[0],name='线载联合动态稳定度',duration_s=s['step_ms']/1000+1.05,timeout_s=s['cross_timeout_s']))
    skipped = [] if s['line_load_enabled'] else ['线载联合动态稳定度']
    if not s['fra_enabled']:skipped.append('环路 FRA')
    if len(rails) > 1 and not cross:skipped.append('交叉调整率')
    if not s['short_test']:skipped.append('短路注入')
    return dict(voltages=voltages, output_count=max(1,len(rails)), stages=stages, cross_enabled=cross,
                cross_requested=cross_requested,cross_skip_reason=cross_skip_reason,
                cross_count=len(corners), cross_coverage=coverage, fra_enabled=bool(s['fra_enabled']),
                fra_points_approx=points, skipped=skipped,
                timeout_budget_s=sum(x['timeout_s'] for x in stages),
                transient_duration_s=sum(x.get('duration_s', 0) for x in stages),
                step_ms=s['step_ms'], stop_ms=s['stop_ms'], max_load_step=maximum_step, reuse=bool(s['simulation_reuse']),
                qr_charge_observation=qr_charge_observation(parameters))


def plan_text(plan):
    if plan.get('topology')=='LLC':
        text=f"{len(plan['voltages'])} 个输入端点，分别执行满载启动、满载稳态和 10% ↔ 90% 双向负载阶跃。"
        return text+(f"每端开关 FRA 约 {plan['fra_points_approx']} 点，并以半幅复核。"
                     if plan['fra_enabled'] else '快速预检仅运行时域。')
    dynamic = plan['max_load_step']
    text = (f"{len(plan['voltages'])} 个输入边界 · 各路满载开机与稳态 · OUT{dynamic['feedback_output']} "
            f"{dynamic['low_fraction']:.0%} ↔ {dynamic['high_fraction']:.0%} 独立双向阶跃，结束 {dynamic['stop_s']*1000:g} ms")
    if plan['fra_enabled']:text += f"；FRA 约 {plan['fra_points_approx']} 点/端点 + 半幅复核"
    if plan['cross_enabled']:text += f"；负载角点 {plan['cross_count']} 组/端点"
    if any(stage['kind']=='line_load' for stage in plan['stages']):text += '；线载联合动态 1 次（输入每档 500 ms）'
    if plan['skipped']:text += '。本次不含：' + '、'.join(plan['skipped'])
    if plan.get('cross_skip_reason'):text += '。' + plan['cross_skip_reason']
    if plan.get('qr_charge_observation'):
        text+='。辅助路观察预算：'+ '、'.join('OUT'+str(r['output'])+' 约 '+f'{r["recommended_observation_s"]*1000:.0f} ms'
            for r in plan['qr_charge_observation'])+'（两倍负载RC时间尺度，完成后仍须逐路电荷平衡）'
    text += '。建议先快速预检。FRA 和交叉调整率需要通过额定稳态检查。'
    return text


def resource_text(parameters, settings):
    from spice_boundary import voltages
    from spice_runtime import endpoint_workers

    threads = int(settings['simulation_threads'])
    endpoints = len(voltages(parameters))
    workers = endpoint_workers(endpoints, threads)
    if workers == 2:
        schedule = '高低压端点并行'
    else:
        schedule = '单输入端点' if endpoints == 1 else '端点依次运行'
    return f'CPU 分配　{schedule}，单个 LTspice 工况最多 {threads} 线程。'
