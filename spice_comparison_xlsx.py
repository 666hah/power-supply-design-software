"""Excel projection of the recorded circuit simulation comparison."""

import math
from pathlib import Path

import numpy as np

from engineering_workbook import band, index, note, page, picture, table, verdict
from report_docx import TOPOLOGY, _chart
from spice_analysis import minimum_phase_margin
from spice_black_box import PHASE_MARGIN_RULE, fra_phase_margin, phase_margin_conclusion
from spice_box_figures import (draw_excitation_ramps, draw_line_load, draw_load_step,
                               white_sections, white_startup_sections)
from spice_comparison_report import (_case_label, _component_subject,
                                     _full_band_q1_current, simulation_summary)
from xlsx_report_writer import save_workbook


def _value(value, scale=1):
    return float(value)*scale if isinstance(value, (int, float)) and math.isfinite(value) else '—'


def _plot(sheet, row, draw, caption, height=3.6):
    return picture(sheet,row,_chart((9.2,height),draw),caption)


def _finish(axes, xlabel):
    for axis in np.atleast_1d(axes).ravel():
        axis.grid(alpha=.2)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=8)
    np.atleast_1d(axes).ravel()[-1].set_xlabel(xlabel)


def _startup_plot(fig, data):
    t = np.asarray(data['time'])*1000
    axes = fig.subplots(2,1,sharex=True)
    for signal, values in data.items():
        if signal.startswith('v(out') and len(values)==len(t):
            axes[0].plot(t,values,label=signal[2:-1].upper(),lw=1.25)
    for signal, label in (('v(ss)','软启动 SS'),('v(fault)','保护 FAULT'),('v(en)','使能 EN'),('v(ref)','参考电压')):
        if signal in data and len(data[signal])==len(t):
            axes[1].plot(t,data[signal],label=label)
    axes[0].set_ylabel('端口输出 / V')
    axes[1].set_ylabel('控制电平 / V')
    _finish(axes,'时间 / ms')


def _ripple_plot(fig, data):
    time = np.asarray(data['time'])
    a = fig.subplots()
    for name, values in data.items():
        if name.startswith('v(out') and len(values)==len(time):
            y = np.asarray(values)
            average = np.trapezoid(y,time)/(time[-1]-time[0])
            a.plot((time-time[0])*1e6,(y-average)*1000,label=name[2:-1].upper())
    a.set_ylabel('去直流纹波 / mV')
    _finish(a,'相对时间 / µs')


def _loop_plot(fig, sources):
    axes = fig.subplots(2,1,sharex=True)
    for label, data in sources:
        loop = data.get('loop') or {}
        if all(loop.get(k) for k in ('f','db','phase')):
            for axis, field in zip(axes,('db','phase')):
                axis.semilogx(loop['f'],loop[field],label=label,lw=1.2)
    axes[0].set_ylabel('幅值 / dB')
    axes[1].set_ylabel('相位 / °')
    axes[0].axhline(0,color='.55',ls=':',lw=.7)
    axes[1].axhline(-180,color='.55',ls=':',lw=.7)
    _finish(axes,'频率 / Hz')


def _step_plot(fig, design):
    axes = fig.subplots(2,1,sharex=True)
    for axis, direction, side in zip(axes,('10%→90%','90%→10%'),('rise','fall')):
        result = design[side]
        axis.plot(np.asarray(design['time_s'])*1000,design[side+'_voltage_V'],label=direction,lw=1.2)
        target, radius = result['final_voltage_V'],result['settling_band_V']
        axis.axhspan(target-radius,target+radius,alpha=.1,color='tab:green',label='计算恢复观察带')
        axis.set_ylabel('反馈输出 / V')
    _finish(axes,'相对跳变时刻 / ms')


def _cross_plot(fig, cross):
    a = fig.subplots()
    data = cross['waveform']
    time = np.asarray(data['time'])*1000
    for key, values in data.items():
        if key!='time' and len(values)==len(time):
            a.plot(time,values,label=key,lw=1.1)
    for row in cross.get('records',()):
        if row.get('end_s') is not None:
            a.axvline(row['end_s']*1000,c='.72',lw=.65)
    a.set_ylabel('端口电压 / V')
    _finish(a,'时间 / ms')


def _case_state(case):
    if not case.get('complete'):
        return '未完成'
    if case.get('fault_test'):
        return '保护试验'
    stable = (case.get('periodicity') or {}).get('stable',case.get('nominal_comparable'))
    if stable is True and case.get('nominal_comparable') is not False:
        return '通过'
    return '待复核' if stable is not None else '证据不足'


def _summary(evidence):
    summary = simulation_summary(evidence)
    cot = evidence.get('cot')
    findings = [] if cot else summary['findings']
    pending = [] if cot else summary['pending']
    settings = evidence.get('settings') or {}
    parameters = evidence.get('parameters') or {}
    failed = False
    for case in evidence.get('cases',()):
        label = _case_label(case,summary['single_label_voltage'])
        if cot:
            from cot_acceptance import assess_case
            assessment = assess_case(case,parameters,fra_requested=bool(settings.get('fra_enabled')))
            failed |= assessment['status']=='fail'
            for row in assessment['rows']:
                if row['status']=='pass':
                    continue
                destination = findings if row['status']=='fail' else pending
                destination.append((label+' · '+row['label'],row.get('note') or row.get('status','')))
            findings.extend((label+' · '+row['metric'],str(row['status'])) for row in case.get('rows',())
                            if row.get('status') in ('偏差待复核','偏差需复核'))
        if case.get('fault_test') or not case.get('complete'):
            continue
        for key,field,name in (('black_box','ports','开机与端口指标'),('white_box','rows','稳态器件应力')):
            sample = case.get(key) or {}
            if not sample.get(field):
                pending.append((label+' · '+name,sample.get('reason') or '缺少记录。'))
        startup = case.get('white_box_startup') or {}
        if not startup.get('complete_window'):
            pending.append((label+' · 启动器件应力',startup.get('reason') or '缺少完整起机窗口。'))
    line = evidence.get('line_load_stability') or {}
    if cot and settings.get('line_load_enabled') and not line.get('complete'):
        pending.append(('线载联合试验',line.get('error') or '未完成。'))
    if cot and not evidence.get('cases'):
        pending.extend(summary['pending'])
    state = 'fail' if failed else 'review' if findings else 'missing' if pending else 'pass'
    summary.update(findings=findings,pending=pending,
        state=state,
        conclusion=('各输入端点已执行的 COT 验收项通过。' if cot else summary['conclusion'])
        if state=='pass' else f'重点复核 {len(findings)} 项，待补数据 {len(pending)} 项。')
    return summary


def _flag(enabled, result, key='complete', *, applicable=True):
    if not applicable:
        return '不适用'
    if not enabled:
        return '未启用'
    if result and result.get(key):
        return '完成'
    return '待复核' if result else '未取得'


def _overview(sheet, evidence, summary, destinations):
    cases = evidence.get('cases') or ()
    settings = evidence.get('settings') or {}
    voltage_statuses = {row.get('status') for case in cases if not case.get('fault_test')
                        for row in (case.get('white_box_startup') or {}).get('rows',())}
    exceed_rating = '超过器件额定电压' in voltage_statuses
    exceed_derating = '超过配置降额限值' in voltage_statuses
    state = 'fail' if exceed_rating or exceed_derating else summary['state']
    exceed_label = ('器件启动应力超额定电压' if exceed_rating else '器件启动应力超降额限值'
                    if exceed_derating else '发现验收超限')
    label = {'fail':exceed_label,'pass':'已取得标称稳态结果',
             'review':'需要工程复核','missing':'证据待补齐'}[state]
    r = verdict(sheet,5,label,summary['conclusion'],state=state)
    case_name = lambda case:_case_label(case,summary['single_label_voltage'])
    nominal = [case for case in cases if not case.get('fault_test')]
    def readings(case):
        m = case.get('measurements') or {}
        ref = case.get('feedback_output',1)
        return (f'OUT{ref}',_value(m.get(f'out{ref}_before')),_value(m.get('frequency_actual'),.001),
                _value(m.get('vds_peak')),_case_state(case))
    r = band(sheet,r,'主要稳态读数')
    metrics = ('主反馈端口','端口电压 / V','开关频率 / kHz','Vds 峰值 / V','稳态判定')
    if len(nominal) in (1,2):
        r = table(sheet,r,('指标',*map(case_name,nominal)),zip(metrics,*map(readings,nominal)),
                  spans=(4,2,2) if len(nominal)==2 else (4,4))
    elif nominal:
        r = table(sheet,r,('工况',*metrics),[(case_name(case),*readings(case)) for case in nominal],
                  spans=(2,1,1,1,1,2),state_col=5)
    else:
        r = note(sheet,r,'未取得标称负载工况。')
    if summary['findings']:
        r = band(sheet,r,'优先复核')
        r = table(sheet,r,('项目','观测与判定'),summary['findings'],
                  spans=(3,5))
    if summary['pending']:
        r = band(sheet,r,'仍待补的证据')
        r = table(sheet,r,('项目','说明'),summary['pending'],spans=(3,5))
    r = band(sheet,r,'试验覆盖')
    coverage = []
    plan = evidence.get('plan') or {}
    for case in nominal:
        startup = case.get('white_box_startup') or {}
        cross = case.get('cross') or {}
        coverage.append((case_name(case),_flag(True,startup,'complete_window'),_case_state(case),
            _flag(True,case.get('load_transient')),
            _flag(settings.get('fra_enabled'),case.get('loop'),'available'),
            _flag(settings.get('cross_enabled'),cross,applicable=(
                not plan.get('cross_skip_reason') and cross.get('supported',True)
                and evidence.get('topology') not in ('BUCK','BOOST')))))
    r = table(sheet,r,('工况','开机波形','满载稳态','双向阶跃','开关 FRA','交叉调整率'),
              coverage,spans=(2,1,1,1,1,2))
    r = note(sheet,r,'线载联合试验 '+_flag(settings.get('line_load_enabled'),evidence.get('line_load_stability'))
             +'。保护试验记录另见「工况与依据」。')
    if summary['comparison_tolerance_pct'] is not None:
        r = note(sheet,r,f"计算与仿真相对偏差复核线为 {summary['comparison_tolerance_pct']:g}%。稳态读数、器件额定及瞬态要求分别判定。")
    index(sheet,r,destinations)


def _black_ports(sheet, cases, case_name):
    r = 5
    for case in cases:
        r = band(sheet,r,case_name(case))
        if not case.get('complete'):
            r = note(sheet,r,case.get('error') or '运行未完成。')
        ports = (case.get('black_box') or {})
        records = ports.get('ports') or ()
        r = band(sheet,r,'额定负载开机性能')
        if records:
            r = table(sheet,r,('端口','参考 / V','首次 90% / ms','10%→90% / ms','峰值 / V',
                              '过冲 / %','持续入带 / ms'),
                [(f"OUT{x['rail']}",_value(x.get('reference_v')),_value(x.get('t90_s'),1000),
                  _value(x.get('rise_s'),1000),_value(x.get('peak_v')),
                  _value(x.get('peak_above_reference_pct')),_value(x.get('in_band_s'),1000))
                 for x in records],spans=(2,1,1,1,1,1,1))
            r = note(sheet,r,f"从仿真零时刻计时。持续入带指回到参考电压 ±{ports.get('band_pct',2):g}% 后保持到启动窗末。")
        else:
            r = note(sheet,r,'本次未取得原始开机指标。')
        startup = case.get('startup_window') or case.get('startup') or {}
        if startup.get('time'):
            r = _plot(sheet,r,lambda fig:_startup_plot(fig,startup),'端口启动与软启动／保护状态')
        if not case.get('complete'):
            continue
        m = case.get('measurements') or {}
        r = band(sheet,r,'满载稳压精度与端口纹波')
        out = []
        for port in records:
            rail, reference = port['rail'],port['reference_v']
            expected = next((x.get('design') for x in case.get('rows',())
                             if x['metric'] in (f'OUT{rail} 输出平均电压',f'OUT{rail} 端口平均电压')),None)
            actual = m.get(f'out{rail}_before')
            branch = next((x for x in case.get('branches',()) if x['id']==rail),{})
            pp = (branch.get('simulation_ripple') or {}).get('pp')
            if rail==1 and case.get('phase_table'):
                pp = m.get('out1_pre_ripple')
            ok = bool(ports.get('steady_qualified'))
            deviation = (actual/reference-1)*100 if ok and isinstance(actual,(int,float)) and reference else None
            out.append((f'OUT{rail}',_value(reference),_value(expected),_value(actual),_value(deviation),_value(pp,1000),
                        '通过' if ok else '待复核'))
        if out:
            r = table(sheet,r,('端口','参考 / V','计算 / V','仿真 / V','相对参考 / %','纹波 / mVpp','状态'),
                      out,spans=(2,1,1,1,1,1,1),state_col=6)
        else:
            r = note(sheet,r,'未取得合格的满载端口测量。')
        r = note(sheet,r,'稳压偏差以输出端口参考值为分母。开关模型纹波沿用原测量带宽。')
        w = case.get('switching') or {}
        if len(w.get('time',()))>1 and w['time'][-1]>w['time'][0] and any(s.startswith('v(out') for s in w):
            r = _plot(sheet,r,lambda fig:_ripple_plot(fig,w),'满载稳态局部纹波',2.6)
    if not cases:
        note(sheet,r,'未取得额定负载的开机和稳态记录。')


def _dynamic(sheet, cases, case_name, evidence):
    r = 5
    for case in cases:
        r = band(sheet,r,case_name(case))
        transient = case.get('load_transient') or {}
        response = transient.get('response_by_port') or {}
        events = [x for port in sorted(response,key=int) for x in response[port]] if response else transient.get('events',())
        feedback = transient.get('feedback_output') or case.get('feedback_output',1)
        if events:
            r = table(sheet,r,('端口 · 负载跳变','阶跃前 / V','最低 / V','最高 / V','压降 / mV','过冲 / mV','入带时间 / ms'),
                [(f"OUT{x['rail']} · {x['before']:.0%}→{x['after']:.0%}",_value(x.get('before_v')),
                  _value(x.get('min_v')),_value(x.get('max_v')),_value(x.get('droop_v'),1000),
                  _value(x.get('overshoot_v'),1000),_value(x.get('recovery_s'),1000)) for x in events],
                spans=(2,1,1,1,1,1,1))
            r = note(sheet,r,f"OUT{feedback} 为激励端口，其余路保持记录规定的负载。相对阶跃前均值读压降与过冲。"
                f"恢复观察带为参考电压 ±{transient.get('band_pct',2):g}%。「—」表示没有合格的入带时间读数。")
        else:
            r = note(sheet,r,transient.get('error') or transient.get('reason') or '未取得独立阶跃记录。')
        wave = transient.get('waveform') or {}
        if wave.get('time') and wave.get('voltage'):
            r = _plot(sheet,r,lambda fig:draw_load_step(fig,transient),'实际双向阶跃与各路响应',4.15)
        design = transient.get('design_step') or {}
        if design.get('available'):
            r = band(sheet,r,'反馈路平均模型响应')
            r = table(sheet,r,('方向','压降 / mV','过冲 / mV','±入带 / mV','入带时间 / ms'),
                [(label,_value(d.get('droop_V'),1000),_value(d.get('overshoot_V'),1000),
                  _value(d.get('settling_band_V'),1000),_value(d.get('settling_s'),1000))
                 for label,d in (('10%→90%',design['rise']),('90%→10%',design['fall']))],spans=(2,1,1,2,2))
            r = note(sheet,r,'平均模型使用末级反馈端口的恒流阶跃。开关仿真使用网表中的负载与动作时序。')
            if design.get('time_s'):
                r = _plot(sheet,r,lambda fig:_step_plot(fig,design),'平均模型双向阶跃')
    r = band(sheet,r,'线载联合动态稳定度')
    line = evidence.get('line_load_stability') or {}
    if line.get('complete'):
        voltages = line.get('line_plateaux_V') or line.get('voltages') or ()
        state = ('观察窗内触发保护' if line.get('protection') else '观察窗内未触发保护'
                 if line.get('protection') is False else '未保存保护信号')
        r = note(sheet,r,'输入平台 '+' → '.join(f'{value:g} V' for value in voltages)+'。'+state+'。')
        schedule = {s['rail']:s for s in line.get('schedule',())}
        r = table(sheet,r,('输出','负载范围','每档停留 / ms','最低 / V','最高 / V'),
            [(f"OUT{x['rail']}",f"{schedule[x['rail']]['low_fraction']:.0%} ↔ {schedule[x['rail']]['high_fraction']:.0%}"
              if x['rail'] in schedule else '—',_value(schedule.get(x['rail'],{}).get('dwell_ms')),
              _value(x.get('min_V')),_value(x.get('max_V'))) for x in line.get('rows',())],
            spans=(2,2,2,1,1))
    else:
        r = note(sheet,r,line.get('error') or ('配置已启用，未取得合格试验结果。'
                 if (evidence.get('settings') or {}).get('line_load_enabled') else '本次未启用。'))
    line_wave = line.get('waveform') or {}
    if line_wave.get('time') and line_wave.get('input_V'):
        _plot(sheet,r,lambda fig:draw_line_load(fig,line_wave),'实际线载联合试验')


def _loop_cross(sheet, cases, case_name, settings):
    r = 5
    for case in cases:
        r = band(sheet,r,case_name(case))
        loop = case.get('loop') or {}
        r = band(sheet,r,'额定负载开关环路 FRA')
        sources = [(label,loop.get(key) or {}) for label,key in (
            ('设计计算','design'),('仿真点重建','measured_reconstruction'),('LTspice FRA','simulation'))]
        data = [source.get('loop') or {} for _,source in sources]
        metrics = [(label,[item.get(key) for item in data]) for label,key in (
            ('穿越频率 / Hz','fc'),('所选穿越相位裕度 / °','pm'),('增益裕度 / dB','gm_db'))]
        metrics.insert(2, ('最小相位裕度 / °', list(map(minimum_phase_margin,data))))
        if any(value is not None for _,values in metrics for value in values):
            rows = [(name,*map(_value,vals)) for name,vals in metrics]
            rows.append(('FRA 相位裕度验收','—','—',phase_margin_conclusion(fra_phase_margin(loop))))
            r = table(sheet,r,('指标',*(s[0] for s in sources)),
                rows,spans=(2,2,2,2))
        status = _flag(settings.get('fra_enabled'),loop,'available')
        if status=='完成':
            msg = 'FRA 注入通过本次复核。'
        elif status=='未启用':
            msg = '本次未启用开关 FRA。'
        else:
            msg = loop.get('error') or '未取得合格的开关 FRA 结果。'
        r = note(sheet,r,msg+' '+PHASE_MARGIN_RULE+' 未覆盖相位交越时，增益裕度留空位。')
        if any((d.get('loop') or {}).get('f') for _,d in sources):
            r = _plot(sheet,r,lambda fig:_loop_plot(fig,sources),'设计计算、工作点重建与实际注入的开环响应')
        check = loop.get('amplitude_check') or {}
        if check.get('f'):
            r = table(sheet,r,('半幅复核频率 / Hz','Δ幅值 / dB','Δ相位 / °'),
                list(zip(check['f'],check['db_error'],check['phase_error'])),spans=(4,2,2))
        r = band(sheet,r,'负载角点及交叉调整率')
        cross = case.get('cross') or {}
        envelopes = cross.get('summary') or {}
        records = cross.get('records') or ()
        designs = {d['id']:d for d in envelopes.get('design',())}
        if envelopes.get('simulation'):
            rows = []
            for actual in envelopes['simulation']:
                rail = actual['id']
                estimate = designs.get(rail,{})
                fixed_load = {}
                for record in records:
                    loads = tuple(record.get('powers') or ())
                    if record.get('settled') and record.get('simulation') is not None and len(loads)>=rail:
                        fixed_load.setdefault((record.get('V_in'),loads[rail-1]),set()).add(loads)
                comparable = any(len(v)>1 for v in fixed_load.values())
                rows.append((f'OUT{rail}',_value(estimate.get('V_min')),_value(estimate.get('V_max')),
                    _value(actual.get('V_min')),_value(actual.get('V_max')),
                    _value(estimate.get('cross_only_pct')) if comparable and estimate.get('complete') else '—',
                    _value(actual.get('cross_only_pct')) if comparable else '无同载配对',
                    '完整' if estimate.get('complete') and actual.get('complete') else '部分'))
            r = table(sheet,r,('输出','计低 / V','计高 / V','仿低 / V','仿高 / V','计交叉 / %','仿交叉 / %','覆盖'),rows,state_col=7)
        if records:
            counts = (cross.get('total_cases',len(records)),len(records),sum(bool(x.get('settled')) for x in records))
            r = note(sheet,r,'计划角点 %d，已记录 %d，末段收敛 %d。交叉变化固定本路负载及输入电压。'%counts)
            powers = lambda vals:' / '.join(f'{x:.5g}' if isinstance(x,(int,float)) and math.isfinite(x) else '—'
                                           for x in vals) if vals is not None else '未取得'
            r = table(sheet,r,('角点','负载 / W','计算端口 / V','仿真端口 / V','角点状态'),
                [(x['id'],powers(x.get('powers')),powers(x.get('design')),powers(x.get('simulation')),
                  '收敛' if x.get('settled') else (x.get('error') or '未收敛')) for x in records],
                spans=(1,2,2,2,1),state_col=4)
        status = _flag(settings.get('cross_enabled'),cross,applicable=cross.get('supported',True))
        r = note(sheet,r,'覆盖 '+status+'。'+str(cross.get('error') or cross.get('note') or ''))
        if (cross.get('waveform') or {}).get('time'):
            r = _plot(sheet,r,lambda fig:_cross_plot(fig,cross),'原始角点扫描中的端口电压',3.0)
    if not cases:
        note(sheet,r,'未取得额定运行对应的环路或负载角点记录。')


def _white_status(text):
    if text in ('超过器件额定电压','超过配置降额限值'):
        return text,'fail'
    if text.startswith('超过') or '待复核' in text or '待稳态' in text:
        return text,'review'
    if text.startswith('未超过') or text.startswith('满足'):
        return text,'pass'
    if '缺' in text or '未取得' in text or '未配置' in text:
        return text,'missing'
    return text,'na'


def _white(sheet, cases, case_name, flyback, *, startup):
    from qr_spice_analysis import excitation_ramps

    r = 5
    renderer = white_startup_sections if startup else white_sections
    for case in cases:
        r = band(sheet,r,case_name(case))
        raw = case.get('white_box_startup' if startup else 'white_box') or {}
        for title,headers,rows,description,draw in renderer(case,flyback_ramp=flyback):
            r = band(sheet,r,title)
            if rows and startup:
                source = raw.get('qr_peak_detail',{}) if title.startswith('Q1 漏源峰值') else raw
                raw_by_name = {x['ref']+' '+x['metric']:x for x in source.get('rows',())}
                typed = []
                for label,*_ in rows:
                    x = raw_by_name[label]
                    status,state = _white_status(x.get('status',''))
                    typed.append((label,x['unit'],_value(x.get('simulation')),
                                  _value(x.get('time_s'),1000),_value(x.get('rating')),
                                  _value(x.get('limit')),status,state))
                r = table(sheet,r,(*headers,'级别'),typed,state_col=7)
            elif rows:
                raw_by_name = {x['metric']:x for x in raw.get('rows',())}
                typed = []
                for label,*_ in rows:
                    x = raw_by_name[label]
                    status,state = _white_status(x.get('status',''))
                    typed.append((label,x['unit'],_value(x.get('design')),_value(x.get('simulation')),
                                  _value(x.get('delta_percent')),status,state,x.get('scope','')))
                r = table(sheet,r,('器件与指标','单位','设计计算','LTspice 仿真','偏差 / %','判定说明','级别','测量说明'),
                          typed,state_col=6)
            if description:
                r = note(sheet,r,description)
            if draw:
                r = _plot(sheet,r,draw,title,4.05 if startup else 3.55)
        if flyback:
            if startup:
                ramp = case.get('startup_excitation') or {}
            else:
                ramp = excitation_ramps(case.get('switching') or {},case.get('controller') or {})
            r = band(sheet,r,'Q1 导通励磁电流爬升')
            if ramp.get('available'):
                r = table(sheet,r,('峰值 / A','前沿排除 / ns','观察段数'),[(
                    _value(ramp.get('peak_A')),_value(ramp.get('blank_s'),1e9),len(ramp.get('segments',())))],spans=(3,3,2))
                r = note(sheet,r,'原边绕组 I(LP) 按门极有效导通分段，排除前沿振铃，保留正常励磁斜率。')
                r = _plot(sheet,r,lambda fig:draw_excitation_ramps(fig,ramp),'从门极开通计时的原边电流',2.7)
            else:
                r = note(sheet,r,ramp.get('reason') or '未取得对应绕组电流短窗。')
        if not startup:
            other = [x for x in case.get('rows',()) if _component_subject(x['metric']) is None
                     and (not flyback or not _full_band_q1_current(x))]
            if other:
                r = band(sheet,r,'计算与开关仿真对照')
                r = table(sheet,r,('量','单位','计算','仿真','偏差 / %','结论'),
                    [(x['metric'],x.get('unit',''),_value(x.get('design')),_value(x.get('simulation')),
                      _value(x.get('delta_percent')),x.get('status','—')) for x in other],
                    spans=(2,1,1,1,1,2),state_col=5)
    if not cases:
        note(sheet,r,'本次没有可用的标称负载器件探针证据。')


def _basis(sheet, evidence, case_name):
    from spice_export import SETTINGS

    r = band(sheet,5,'源记录及运行边界')
    context = tuple((label,evidence[key]) for label,key in (
        ('证据格式','schema'),('电路模型','model'),('计算说明','calculation_revision_note'),
        ('来源说明','evidence_note'),('归档来源','review_origin')) if evidence.get(key))
    r = table(sheet,r,('条目','记录'),context,spans=(2,6))
    cases = evidence.get('cases') or ()
    r = table(sheet,r,('输入与工况','有效终点 / ms','实际运行 / s','状态','来源或失败原因'),[
        (case_name(c),_value(c.get('actual_end_s'),1000),_value(c.get('elapsed_s')),_case_state(c),
         c.get('error') or c.get('evidence_origin') or c.get('source_relative_folder') or
         ('复用校验通过的既有波形' if (c.get('cache') or {}).get('hit') else 'LTspice 证据记录'))
        for c in cases],spans=(2,1,1,1,3),state_col=3)
    if evidence.get('cot'):
        from cot_acceptance import assess_case
        settings = evidence.get('settings') or {}
        for case in cases:
            checks = assess_case(case,evidence.get('parameters') or {},
                                 fra_requested=bool(settings.get('fra_enabled')))
            r = band(sheet,r,case_name(case)+' · COT 验收限值')
            r = table(sheet,r,('量','数值','限值','单位','关系','判定','依据'),[
                (x['label'],_value(x.get('value')),_value(x.get('limit')),x.get('unit',''),
                 x.get('comparison',''),{'not_covered':'na'}.get(x['status'],x['status']),x.get('note',''))
                for x in checks['rows']],spans=(2,1,1,1,1,1,1),state_col=5)
    settings = evidence.get('settings') or {}
    keys = ('soft_start_ms','enable_delay_ms','stop_ms','step_ms','cycle_tolerance_pct',
            'comparison_tolerance_pct','fra_enabled','fra_start_hz','fra_stop_hz','fra_amplitude_pct',
            'cross_enabled','cross_hold_ms','line_load_enabled','simulation_threads')
    r = band(sheet,r,'关键运行设置')
    r = table(sheet,r,('设置','数值','单位','字段'),[(SETTINGS[key][3],settings[key],SETTINGS[key][4],key)
              for key in keys if key in settings and key in SETTINGS],spans=(3,1,1,3))
    if evidence.get('topology')=='QR-FLYBACK':
        r = note(sheet,r,'准谐振模型按 ZCD 过零和 CS 比较决定开关时序。设计频率参数用于计算边界及测量设置。')
    notes = dict.fromkeys(n for case in cases for n in case.get('approximation_notes',()) if n)
    if notes:
        r = band(sheet,r,'模型和工程判据的使用边界')
        for entry in notes:
            r = note(sheet,r,entry)


def build_sheets(evidence, *, prefix='', include_summary=True):
    """Build reusable component sheets for standalone and joint Excel reports."""
    settings = evidence.get('settings') or {}
    topo = evidence.get('topology','')
    context = '　·　'.join(filter(None,(TOPOLOGY.get(topo,topo),evidence.get('model','LTspice'))))
    summary = _summary(evidence)
    nominal = [case for case in evidence.get('cases',()) if not case.get('fault_test')]
    def case_name(case):
        return _case_label(case,summary['single_label_voltage'])
    pages = (
        ('启动与稳态','黑盒 · 启动与满载稳态','启动时间、输出过冲、稳压精度与端口纹波'),
        ('阶跃与动态','黑盒 · 双向阶跃与线载动态','负载跳变、恢复时间、线载联合测试'),
        ('环路与角点','黑盒 · 环路 FRA 与负载角点','频率响应、角点分布与交叉调整率'),
        ('启动器件应力','白盒 · 启动器件应力','启动峰值、发生时刻、额定与降额上限'),
        ('稳态器件应力','白盒 · 稳态器件应力','半导体、逐颗电容和开关波形'),
        ('工况与依据','工况与判定依据','源记录、运行配置与模型边界'),
    )
    sheets = [page(prefix+short,title,context) for short,title,_ in pages]
    _black_ports(sheets[0],nominal,case_name)
    _dynamic(sheets[1],nominal,case_name,evidence)
    _loop_cross(sheets[2],nominal,case_name,settings)
    flyback = topo in ('FLYBACK','QR-FLYBACK')
    _white(sheets[3],nominal,case_name,flyback,startup=True)
    _white(sheets[4],nominal,case_name,flyback,startup=False)
    _basis(sheets[5],evidence,case_name)
    if include_summary:
        overview = page(prefix+'评审结论','仿真与设计计算对比',context)
        _overview(overview,evidence,summary,[(prefix+short,title,desc) for short,title,desc in pages])
        sheets.insert(0,overview)
    return sheets


def write_spice_xlsx(path, evidence):
    """Export a standalone comparison workbook while preserving numeric evidence."""
    path = Path(path)
    save_workbook(path,build_sheets(evidence))
    return path
