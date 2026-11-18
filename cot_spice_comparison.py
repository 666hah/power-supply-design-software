"""Single-unit COT transient and switching FRA evidence."""
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np

from cot_buck_spice import MODEL_VERSION, _SCOPE, project_files, transient_settings
from cot_acceptance import assess_case, assess_fra, transient_acceptance, LABELS


def _edge_times(t, signal):
    crossed = np.flatnonzero((signal[:-1] >= .5) != (signal[1:] >= .5))
    fraction = (.5-signal[crossed])/(signal[crossed+1]-signal[crossed])
    return t[crossed]+fraction*(t[crossed+1]-t[crossed]), signal[crossed+1] >= .5


def _quantity(name, unit, expected, actual, tolerance, *, comparable=True):
    delta = (100*(actual-expected)/abs(expected)
             if comparable and expected is not None and abs(expected) > 1e-12 else None)
    return dict(metric=name, unit=unit, design=expected, simulation=actual, delta_percent=delta,
                status='供观察' if delta is None else '偏差需复核' if abs(delta) > tolerance else '偏差在线内')


def _window_stats(raw, selection, start, stop, traces):
    from spice_analysis import statistics

    axis = raw.time[selection]
    return {name: statistics(axis, value, start, stop) for name, value in traces.items()}


def _summarize_case(case, raw, settings, *, white_box_probes=()):
    from spice_analysis import steady_quality

    op, wf = case['result']['op'], case['result']['wf']
    cot = op['cot']
    f_ref = op['f_sw']
    phases = cot['phases']
    step, stop = settings['step_ms']*1e-3, settings['stop_ms']*1e-3
    prior = step-(settings['soft_start_ms']+settings['enable_delay_ms'])*1e-3
    monitor_s = max(24/f_ref, min(prior/2, .0008))
    start = step-monitor_s-2/f_ref
    if start <= raw.time[0] or raw.time[-1] < stop*.9999:
        raise ValueError('瞬态记录未到达设定终点，或阶跃前稳态窗口过短')
    first, last = np.searchsorted(raw.time, [start, step])
    window = slice(first, last+1)
    axis = raw.time[window]
    currents = [raw.trace(f'i(l{i})')[window].astype(float) for i in range(1, phases+1)]
    gates = [raw.trace(f'v(gate{i})')[window].astype(float) for i in range(1, phases+1)]
    edges = [_edge_times(axis, gate) for gate in gates]
    rises1 = edges[0][0][edges[0][1]]
    if len(rises1) < 12:
        raise ValueError('阶跃前未取得至少 12 个完整 COT 周期')
    a, b = rises1[0], rises1[-1]
    freq = (len(rises1)-1)/(b-a)
    quality = steady_quality(raw, freq, step, 1, window=max(8/freq, min(monitor_s/2, .0005)), bins=8)
    tolerance = settings['comparison_tolerance_pct']
    output = raw.trace('v(out1)')[window].astype(float)
    total = np.sum(currents, axis=0)
    try:
        bus = raw.trace('v(vbus)')[window].astype(float)
    except (KeyError,ValueError):
        bus = cot['bus_voltage_V']
    vds_high = bus-raw.trace('v(sw1)')[window].astype(float)
    amounts = _window_stats(raw, window, a, b,
                            dict(output=output, total=total, vds=vds_high,
                                 input_current=-raw.trace('i(vin_source)')[window].astype(float)))
    measurements = dict(out1_before=amounts['output']['mean'],
                        out1_pre_ripple=amounts['output']['pp'], vds_peak=amounts['vds']['maximum'],
                        frequency_actual=float(freq), primary_avg=None, primary_rms=None, primary_peak=None)
    rows = [
        _quantity('OUT1 端口平均电压', 'V', op['V_out'], measurements['out1_before'], tolerance),
        _quantity('OUT1 端口峰峰纹波', 'V', wf['ripple_pp'], measurements['out1_pre_ripple'], tolerance,
                  comparable=wf['ripple_pp']>1e-6),
        _quantity('各相电感电流合计峰峰值', 'A', cot['total_output_current_ripple_A'], amounts['total']['pp'], tolerance,
                  comparable=cot['total_output_current_ripple_A']>1e-5),
        _quantity('单相实际频率', 'Hz', f_ref, float(freq), tolerance),
        _quantity('PH1 高侧阻断峰值', 'V', cot['high_side_block_V'], measurements['vds_peak'], tolerance),
    ]
    phase_table = []
    expected_ton = cot['ton_s']
    gates_ok = True
    for i, (current, (times, going_up)) in enumerate(zip(currents, edges), 1):
        phase = (cot.get('phase_data') or [{}]*phases)[i-1]
        expected_ton = phase.get('ton_s',cot['ton_s'])
        ri = times[going_up]
        fe = times[~going_up]
        match = np.searchsorted(fe, ri)
        complete = match < len(fe)
        falling = fe[match[complete]]
        rising = ri[complete]
        widths = falling - rising
        if len(widths) < 10:
            raise ValueError(f'PH{i} 有效导通时间记录不足')
        ton = float(np.median(widths))
        ton_spread = float(np.ptp(widths))
        shortest_off = float(np.min(rising[1:]-falling[:-1]))
        gates_ok &= (abs(ton-expected_ton) <= max(expected_ton*.05, 2e-9)
                     and ton_spread <= max(expected_ton*.05, 2e-9)
                     and shortest_off >= cot['min_off_s']-2e-9)
        result = _window_stats(raw, window, a, b, {'current': current})['current']
        phase_table.append(dict(phase=i, average_A=result['mean'], rms_A=result['rms'],
                                peak_A=result['maximum'], valley_A=result['minimum'],
                                ton_s=ton, ton_peak_to_peak_s=ton_spread,
                                minimum_off_s=shortest_off, pulse_count=len(widths)))
        if i == 1:
            measurements.update(primary_avg=result['mean'], primary_rms=result['rms'], primary_peak=result['maximum'])
        rows.extend([
            _quantity(f'PH{i} 电感电流均值', 'A', phase.get('current_avg_A',cot['phase_current_avg_A']), result['mean'], tolerance),
            _quantity(f'PH{i} 电感电流 RMS', 'A', phase.get('current_rms_A',cot['phase_current_rms_A']), result['rms'], tolerance),
            _quantity(f'PH{i} 电感电流峰值', 'A', phase.get('current_peak_A',cot['phase_current_peak_A']), result['maximum'], tolerance),
            _quantity(f'PH{i} 导通时间', 'ns', expected_ton*1e9, ton*1e9, tolerance),
        ])
    tail_size = min(4, phases)
    steady = raw.samples(['v(out1)']+[f'i(l{i})' for i in range(1, tail_size+1)], b-4/freq, b, points=1200)
    local = axis >= b-4.5/freq
    steady['i(total)'] = np.interp(steady['time'], axis[local], total[local]).tolist()
    startup = raw.samples(['v(out1)', 'v(ref)'], 0, stop, points=1500)
    nominal = bool(quality['passed'] and gates_ok)
    if not nominal:
        for row in rows:
            row.update(status='稳态或脉宽待复核', delta_percent=None)
    dynamic=transient_acceptance(case,raw,settings,phase_table)
    from spice_black_box import full_load_ports
    shutdown = (case['p'].get('cot_config') or {}).get('shutdown_s',0.)
    black_box = full_load_ports(raw,case,end_s=min(step,shutdown) if shutdown>0 else step,
                                frequency_hz=freq,return_node=None,comparable=nominal)
    from spice_white_box import collect, collect_startup
    white_box=collect(raw,white_box_probes,a,b,b-4/freq,comparable=nominal,tolerance=tolerance)
    startup_end=min(step,shutdown) if shutdown>0 else step
    white_box_startup=collect_startup(raw,white_box_probes,0.,startup_end) if white_box_probes else {}
    return dict(measurements=measurements, rows=rows, phase_table=phase_table,dynamic=dynamic,white_box=white_box,
                white_box_startup=white_box_startup,
                steady_before_step=quality, nominal_comparable=nominal, gate_widths_match=gates_ok,black_box=black_box,
                actual_end_s=float(raw.time[-1]), startup=startup, switching=steady, complete=True)


def _write_report(path, evidence):
    from design_theme import style_figure
    from docx_layout import new_document, paragraph, equation, table, figure, finalize_book_report, set_a4_page
    from docx.enum.section import WD_SECTION_START
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.text import Text
    from report_architecture import available_width, module_section, conclusion_line
    from spice_black_box import black_box_sections
    from spice_box_figures import (STARTUP_HEADERS, STARTUP_WIDTHS, draw_load_step, draw_line_load,
                                  white_sections, white_startup_sections)

    def fmt(v):
        return '—' if v is None else '0' if abs(v)<1e-9 else f'{v:.4g}'

    def evidence_chart(caption, draw, height=3.1):
        chart = Figure(figsize=(7.1,height),layout='constrained')
        FigureCanvasAgg(chart)
        draw(chart)
        for text in chart.findobj(Text):
            text.set_fontfamily(['Microsoft YaHei','DejaVu Sans'])
        style_figure(chart)
        stream=BytesIO()
        chart.savefig(stream,format='png',dpi=150)
        figure(doc,stream.getvalue(),caption)

    model = evidence['model']
    doc = new_document('Buck COT 仿真与设计计算对比报告', model, 'Buck COT · 电路仿真对比')
    module_section(doc, '1 评审结论', new_page=False)
    cases = evidence['cases']
    parameters = evidence.get('parameters') or {}
    for c in cases:
        c['acceptance'] = assess_case(c,parameters,fra_requested=bool(evidence['settings']['fra_enabled']))
    rows = [(c['id'], fmt(c['voltage']), fmt(c.get('measurements', {}).get('out1_before')),
             '完成且额定窗口通过' if c.get('nominal_comparable') else c.get('error', '额定窗口需复核'))
            for c in cases]
    pending = sum(not c.get('nominal_comparable') for c in cases)
    deviations = sum(r['status']=='偏差需复核' for c in cases for r in c.get('rows', ()))
    fra_requested = evidence['settings']['fra_enabled']
    fra_complete = sum(c['loop']['available'] for c in cases)
    fra_pending = sum(not c['acceptance']['fra']['passed'] for c in cases) if fra_requested else 0
    failed=sum(c['acceptance']['status']=='fail' for c in cases)
    reviews=sum(any(r['status'] in ('review','not_covered') for r in c['acceptance']['rows']) for c in cases)
    white_rows=[row for case in cases for row in (case.get('white_box') or {}).get('rows',[])]
    white_missing=sum(row['simulation'] is None for row in white_rows)
    white_deviations=sum(row['status']=='偏差待复核' for row in white_rows)
    missing_inventory=any(not (case.get('white_box') or {}).get('rows') for case in cases)
    state = 'fail' if failed else 'review' if pending or deviations or fra_pending or reviews or white_missing or white_deviations or missing_inventory else 'pass'
    conclusion_line(doc, f'{len(cases)} 个输入端点：{failed} 个超限，{reviews} 个证据或验收待复核；{deviations} 项计算与仿真偏差待复核。', 'review' if state == 'fail' else state)
    paragraph(doc,'稳态、动态和环路分别验收。半幅 FRA 一致性表示测量有效；稳定裕度与模型偏差另按所列门限判定。未测得增益裕度列为未覆盖。')
    table(doc, ['工况', 'Vin / V', 'OUT1 / V', '额定窗口'], rows, [1.2,.85,1.0,4.05])
    paragraph(doc,('白盒测量：已取得 '+str(len(white_rows)-white_missing)+'/'+str(len(white_rows))+' 项器件统计，'
                   +str(white_deviations)+' 项偏差需复核。') if white_rows else '白盒测量：未取得逐器件证据。')
    if fra_requested:
        qualified=sum(all(r['status']=='pass' for r in c['acceptance']['fra']['rows'] if r['id']!='gm')
                      and bool(c['loop'].get('available')) for c in cases)
        gm_uncovered=sum(any(r['id']=='gm' and r['status']=='not_covered' for r in c['acceptance']['fra']['rows']) for c in cases)
        conclusion_line(doc, f'开关 FRA 半幅复核 {fra_complete}/{len(cases)} 端点有效；'
                        f'{qualified}/{len(cases)} 端点的相位裕度及计算偏差满足门限。',
                        'pass' if qualified==len(cases) else 'review')
        if gm_uncovered:
            paragraph(doc,f'{gm_uncovered} 个端点未测到 −180° 相位交越，增益裕度保留为未覆盖。')
    else:
        paragraph(doc,'本次运行额定瞬态与负载阶跃。可在仿真设置中加做开关 FRA。')
    paired = len(cases) == 2
    def check_table(checks):
        table(doc,['验收指标','测量值','限值','结论与说明'],[
            (r['label'],fmt(r['value'])+' '+r['unit'],
             (r['comparison']+' '+fmt(r['limit'])+' '+r['unit']) if r['limit'] is not None else '未指定',
             LABELS[r['status']]+('；'+r['note'] if r.get('note') else '')) for r in checks],
            [2.2,1.05,1.25,2.6])
    for c in cases:
        module_section(doc,fmt(c['voltage'])+' V 验收结果',level=2,new_page=False)
        review=[r for r in c['acceptance']['rows'] if r['status'] in ('fail','review','not_covered')]
        if review:
            failed_rows=[r for r in review if r['status']=='fail']
            if failed_rows:
                paragraph(doc,'；'.join(r['label']+' '+fmt(r['value'])+' '+r['unit']+
                          ('，限值 '+fmt(r['limit'])+' '+r['unit'] if r['limit'] is not None else '')
                          for r in failed_rows)+'。')
            missing=[r for r in review if r['status']!='fail']
            if missing:
                phase_missing=[r for r in missing if r['id'].startswith('phase')]
                description=([str(len(phase_missing))+' 相采样限流记录'] if phase_missing else [])
                description += [r['label'] for r in missing if r not in phase_missing]
                paragraph(doc,'待补充或复核：'+'、'.join(description)+'。')
        else:
            paragraph(doc,'已执行的稳态、动态和所选环路项目均满足配置门限。')
    module_section(doc,'2 黑盒 · 端口性能',new_page=True)
    paragraph(doc,'在额定负载下观察启动和稳态。瞬态试验施加 10%→90% 与 90%→10% 两个负载边沿。')
    line_load=evidence.get('line_load_stability') or {}
    module_section(doc,'线载联合动态稳定度',level=2,new_page=False)
    if line_load.get('complete'):
        measured=' → '.join(fmt(value)+' V' for value in line_load['line_plateaux_V'])
        paragraph(doc,'输入实测平台：'+measured+'。负载按 10 ms 驻留时间重复跳变。'
                  +('单一输入，观测重复负载。' if len(line_load.get('voltages',[]))==1 else '输入边界按 500 ms 切换。'))
        table(doc,['输出','最低电压 / V','最高电压 / V','保护动作'],
              [('OUT'+str(row['rail']),fmt(row['min_V']),fmt(row['max_V']),
                '模型未提供' if line_load.get('protection') is None else '已触发' if line_load['protection'] else '未触发')
               for row in line_load.get('rows',[])])
        if line_load.get('waveform'):
            evidence_chart('输入与负载重复切换波形',lambda chart:draw_line_load(chart,line_load),4.0)
    else:
        paragraph(doc,'未覆盖：'+str(line_load.get('error') or '本次未选择线载联合试验')+'。不以固定输入负载阶跃代替。')
    for c in cases:
        title=fmt(c['voltage'])+' V'
        module_section(doc,title+' · 端口测试',level=2,new_page=False)
        for name,headers,values,note in black_box_sections(c,evidence['settings']):
            module_section(doc,name,level=3,new_page=False)
            paragraph(doc,note)
            if values:
                table(doc,headers,values)
            if name=='开机时间与过冲' and c.get('startup',{}).get('time'):
                def startup_chart(chart):
                    axis=chart.subplots()
                    trace=c['startup']
                    axis.plot(np.asarray(trace['time'])*1000,trace['v(out1)'],label='OUT1')
                    axis.plot(np.asarray(trace['time'])*1000,trace['v(ref)'],':',label='参考（电容端）')
                    axis.set(xlabel='时间 / ms',ylabel='电压 / V')
                    axis.grid(True,alpha=.22)
                    axis.legend()
                evidence_chart(title+' 额定负载开机',startup_chart,2.5)
            if name=='双向负载阶跃与恢复':
                transient=c.get('load_transient') or {}
                wave=transient.get('waveform') or {}
                if wave.get('time') and len(wave['time'])==len(wave.get('voltage',())):
                    evidence_chart(title+' 负载升降与端口响应',lambda chart:draw_load_step(chart,transient),4.0)
    module_section(doc,'3 白盒 · 器件电流与电压应力',new_page=True)
    paragraph(doc,'按输入端点分别列出满载启动峰值和稳态有效值。')
    for c in cases:
        title=fmt(c['voltage'])+' V'
        module_section(doc,title+' · 器件测试',level=2,new_page=False)
        for scope, sections in [('启动应力',white_startup_sections(c)),('稳态应力',white_sections(c))]:
            module_section(doc,scope,level=3,new_page=False)
            for name,headers,values,note,draw in sections:
                module_section(doc,name,level=4,new_page=False)
                if values:
                    widths = None
                    if headers == STARTUP_HEADERS:
                        widths = [w * available_width(doc) / sum(STARTUP_WIDTHS) for w in STARTUP_WIDTHS]
                    table(doc,headers,values,widths)
                if note:
                    paragraph(doc,note)
                if draw:
                    evidence_chart(title+' '+name,draw)
    if paired:
        set_a4_page(doc.add_section(WD_SECTION_START.NEW_PAGE), landscape=True)
    module_section(doc, '3.1 逐相时序、均流与保护复核', new_page=False)
    if paired:
        left, right = cases
        metrics = [{r['metric']:r for r in case['rows']} for case in cases]
        compared = []
        for metric in dict.fromkeys([*metrics[0], *metrics[1]]):
            pair = [values.get(metric,{}) for values in metrics]
            unit = next(row['unit'] for row in pair if row)
            values = [fmt(r.get(k)) for r in pair for k in ('design','simulation','delta_percent')]
            status = ' / '.join(r.get('status','待补') for r in pair)
            compared.append((metric,unit,*values,status))
        paragraph(doc,'左列 '+fmt(left['voltage'])+' V，右列 '+fmt(right['voltage'])+' V。偏差按百分比。')
        table(doc, ['指标','单位','低端计算','低端仿真','低端偏差','高端计算','高端仿真','高端偏差','低端／高端判定'],
              compared,[1.8,.5,1,1,.85,1,1,.85,2])
        if all(c.get('dynamic') for c in cases):
            paragraph(doc,'动态验收采用全程原始采样；以下按输入两端并列。')
            checks=[{r['id']:r for r in c['dynamic']['rows'] if not r['id'].startswith('phase')} for c in cases]
            dynamic_rows=[]
            for key in dict.fromkeys([*checks[0],*checks[1]]):
                pair=[v.get(key) for v in checks]
                r=next(x for x in pair if x)
                dynamic_rows.append((r['label'],(r['comparison']+' '+fmt(r['limit'])+' '+r['unit']) if r['limit'] is not None else '供观察',
                    *[s for x in pair for s in ((fmt(x['value'])+' '+x['unit'],LABELS[x['status']]) if x else ('—','未覆盖'))]))
            table(doc,['动态指标','限值',fmt(left['voltage'])+' V','结论',fmt(right['voltage'])+' V','结论'],dynamic_rows,[2.4,1.5,1.7,1.,1.7,1.])
        set_a4_page(doc.add_section(WD_SECTION_START.NEW_PAGE),landscape=False)
    for case_index,c in enumerate(cases):
        module_section(doc, c['id']+' · '+fmt(c['voltage'])+' V', level=2, new_page=paired and case_index>0)
        if not c.get('complete'):
            paragraph(doc,c['error'])
            continue
        paragraph(doc, c['steady_before_step']['reason']+'。实际模拟至 '+fmt(c['actual_end_s']*1e3)+' ms。')
        dynamic=c.get('dynamic')
        if dynamic:
            module_section(doc,'动态与逐相电流',level=3,new_page=False)
            paragraph(doc,dynamic['scope'])
            if not paired:
                check_table([r for r in dynamic['rows'] if not r['id'].startswith('phase')])
            phase_checks={r['id']:r for r in dynamic['rows'] if r['id'].startswith('phase')}
            phase_grid=table(doc,['相号','全程峰值 / 谷值 / A','采样峰值 / A','限值 / A','限流余量 / A','验收'],[
                (r['phase'],fmt(r['peak_A'])+' / '+fmt(r['valley_A']),
                 fmt(phase_checks[f"phase{r['phase']}_limit"]['value']),fmt(phase_checks[f"phase{r['phase']}_limit"]['limit']),
                 fmt(r.get('ocp_margin_A')),LABELS[phase_checks[f"phase{r['phase']}_limit"]['status']])
                 for r in dynamic['phase_peaks']],[.5,1.4,1.2,.9,1.,1.])
            # Short engineering tables should move as a unit. This also avoids
            # LibreOffice losing continuation rows at a following figure.
            for row in phase_grid.rows[:-1]:
                for cell in row.cells:
                    for paragraph_item in cell.paragraphs:
                        paragraph_item.paragraph_format.keep_with_next=True
            if any(e['count'] for e in dynamic['events']):
                table(doc,['保护信号','动作次数','首次动作 / ms'],[
                    (e['signal'],e['count'],fmt(e['first_s']*1e3) if e['first_s'] is not None else '—')
                    for e in dynamic['events'] if e['count']],[2.5,1.5,2.])
        if not c['gate_widths_match']:
            paragraph(doc,'稳态脉宽与模型设定不一致，现保留观测数据供定位。')
        if not paired:
            table(doc, ['指标','单位','计算','LTspice','偏差 / %','判定'],
                  [(r['metric'],r['unit'],fmt(r['design']),fmt(r['simulation']),fmt(r['delta_percent']),r['status'])
                   for r in c['rows']], [2.2,.55,1.05,1.05,.85,1.4])
        chart = Figure(figsize=(7.1,4.25),layout='constrained')
        FigureCanvasAgg(chart)
        axes=chart.subplots(2,2)
        switching = c['switching']
        phases=c['phase_table']
        axes[0,0].bar([r['phase'] for r in phases],[r['average_A'] for r in phases],label='整周期平均')
        axes[0,0].set(title='各相平均电流',xlabel='相号',ylabel='A',xticks=[r['phase'] for r in phases])
        time_us = (np.asarray(switching['time'])-switching['time'][0])*1e6
        for key, curve in switching.items():
            if key.startswith('i(l'):
                axes[0,1].plot(time_us,curve,label=key[2:-1].upper())
        axes[0,1].set(title='前四相电感电流' if len(c['phase_table'])>4 else '每相电感电流',
                      xlabel='时间 / μs', ylabel='A')
        axes[1,0].plot(time_us,switching['i(total)'],label='所有相合计')
        axes[1,0].set(title='电感电流合计', xlabel='时间 / μs', ylabel='A')
        v = np.array(switching['v(out1)'])
        axes[1,1].plot(time_us,(v-v.mean())*1e3,label='OUT1')
        axes[1,1].set(title='OUT1 去直流纹波', xlabel='时间 / μs', ylabel='mV')
        for axis in axes.flat:
            axis.grid(True,alpha=.22)
            axis.legend(fontsize=7)
        for text in chart.findobj(Text):
            text.set_fontfamily(['Microsoft YaHei', 'DejaVu Sans'])
        style_figure(chart)
        stream=BytesIO()
        chart.savefig(stream,format='png',dpi=150)
        figure(doc,stream.getvalue(),c['id']+' 相间均流、逐相及合计波形')
    if fra_requested:
        module_section(doc, '4 环路附录 · 设计计算与实际开关 FRA', new_page=True)
        paragraph(doc,'LTspice 在 OUT1 防反管前的电容端与反馈输入之间串联注入。两次扫描保持同一额定负载，按配置采用电阻或恒流负载，半幅复核每个频点。')
        equation(doc,'T = −','V₁','V₂')
        paragraph(doc,'T 为无量纲环路增益。V₁ 和 V₂ 分别为反馈电容节点 cap1 与控制器反馈输入节点 sense 在注入频率处的复数电压分量，单位为 V。')
        measures = [
            ('0 dB 穿越频率', 'fc', 'Hz'),
            ('相位裕度', 'pm', '°'),
            ('增益裕度', 'gm_db', 'dB'),
        ]
        headlines = ['指标', '单位']
        comparison = []
        for c in cases:
            title = fmt(c['voltage'])+' V'
            headlines.extend([title+' 计算', title+' LTspice', title+' 偏差'])
        for label, key, unit in measures:
            vals = []
            for c in cases:
                probe = c['loop']
                analytical = (probe.get('design') or {}).get('loop', {}).get(key)
                simulated = (probe.get('simulation') or {}).get('loop', {}).get(key)
                delta = simulated-analytical if simulated is not None and analytical is not None else None
                if key == 'fc' and delta is not None:
                    delta = 100*delta/analytical
                vals.extend([fmt(analytical), fmt(simulated), fmt(delta)+('%' if key=='fc' and delta is not None else '')])
            comparison.append((label,unit,*vals))
        if paired:
            compact=[(r[0],r[1],r[2]+' / '+r[3],r[5]+' / '+r[6],r[4]+' / '+r[7]) for r in comparison]
            table(doc,['指标','单位',fmt(cases[0]['voltage'])+' V 计算 / 仿真',fmt(cases[1]['voltage'])+' V 计算 / 仿真','低端 / 高端偏差'],compact,[1.2,.45,1.65,1.65,1.4])
        else:
            table(doc, headlines, comparison, [1.6,.6]+[1.05,1.05,.95]*len(cases))
        paragraph(doc,'解析与 FRA 裕度按同一离散频点插值。未扫到 −180° 相位交越时，增益裕度留空。')
        for c in cases:
            probe = c['loop']
            module_section(doc, fmt(c['voltage'])+' V · '+('半幅复核有效' if probe['available'] else 'FRA 待复核'),
                           level=2, new_page=False)
            definition = probe.get('definition')
            check = probe.get('amplitude_check')
            if definition:
                paragraph(doc, f"扫描 {fmt(definition['start_hz'])}–{fmt(definition['stop_hz'])} Hz，"
                               f"主扫描注入 {fmt(definition['amplitude_pp_v']*1e3)} mVpp。")
            if check:
                paragraph(doc, f"半幅与主扫描最大差 {fmt(check['max_db_error'])} dB、"
                               f"{fmt(check['max_phase_error'])}°，阈值为 1 dB、8°。")
            check_table(c['acceptance']['fra']['rows'])
            if not probe['available']:
                paragraph(doc, probe['error'])
                continue
            charts = Figure(figsize=(7.1,3.05),layout='constrained')
            FigureCanvasAgg(charts)
            axes = charts.subplots(2,1,sharex=True)
            for records,name,style in ((probe['design'],'平均计算','-'),(probe['simulation'],'实际开关 FRA','o--')):
                loop = records['loop']
                axes[0].semilogx(loop['f'],loop['db'],style,label=name,markersize=3)
                axes[1].semilogx(loop['f'],loop['phase'],style,label=name,markersize=3)
            axes[0].axhline(0.,color='.6',linewidth=.8)
            axes[1].axhline(-180.,color='.6',linewidth=.8)
            axes[0].set(ylabel='幅值 / dB')
            axes[1].set(ylabel='相位 / °',xlabel='频率 / Hz')
            for axis in axes:
                axis.grid(True,alpha=.22,which='both')
                axis.legend(fontsize=8)
            for txt in charts.findobj(Text):
                txt.set_fontfamily(['Microsoft YaHei','DejaVu Sans'])
            style_figure(charts)
            stream = BytesIO()
            charts.savefig(stream,format='png',dpi=150)
            figure(doc,stream.getvalue(),fmt(c['voltage'])+' V 环路幅相对照')
            if probe['simulation']['loop']['fc'] is None:
                paragraph(doc,'本频带未测得 0 dB 向下交越，因此没有该端点的相位裕度。')
    module_section(doc, f"{5 if fra_requested else 4} 控制逻辑、测量与适用范围", new_page=False)
    for text in evidence.get('approximation_notes') or _SCOPE:
        paragraph(doc,text)
    paragraph(doc,'电流与输出纹波取阶跃前 PH1 完整周期窗口。计算与仿真的相数、各相电感、DCR、'
                  '高低侧导通电阻、带载输入和输出电容一致。证据 ZIP 保留各输入端点的可编辑电路和仿真日志。')
    finalize_book_report(doc)
    doc.save(path)


def compare_design(bundle, destination, *, executable, cancelled, progress):
    from calculation_scheduler import CalculationCancelled
    from engineering_acceptance import input_fingerprint
    from spice_runtime import _run, read_log, TransientRaw
    from cot_spice_fra import run_fra
    from spice_boundary import endpoint_cases, run_load_transient
    from cot_acceptance import apply_boundary_step

    start = time.monotonic()
    base = bundle['base_spec']
    cases = endpoint_cases(base,bundle['cases'])
    bundle = dict(bundle,cases=cases)
    settings = transient_settings(base.get('spice_config'),cases)
    destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    report_path, zip_path = destination.with_suffix('.docx'), destination.with_suffix('.zip')
    evidence = dict(schema='powerdesign-spice-comparison-2', model=MODEL_VERSION, topology='BUCK',
                    cot=True, cases=[], input_fingerprint=input_fingerprint(base), settings=settings,
                    parameters={'V_out':base['V_out'],'cot_config':base.get('cot_config') or {}},
                    input_range_V=[c['voltage'] for c in cases])
    distinct = cases
    fra_requested = bool(settings['fra_enabled'])
    tasks = len(distinct)*(4 if fra_requested else 2)+int(bool(settings.get('line_load_enabled')))
    with tempfile.TemporaryDirectory(prefix='cot-spice-',dir=destination.parent) as temporary:
        root=Path(temporary)
        for i,case in enumerate(distinct,1):
            if cancelled():
                raise CalculationCancelled()
            label=case['id']+'_COT'
            folder=root/label
            folder.mkdir()
            generated=project_files(dict(base,spice_config=dict(settings,load_after=1.)),bundle=bundle,case=case)
            generated_meta=json.loads(generated['manifest.json'])
            from spice_white_box import prepare
            white_box_probes=prepare(generated,case)
            evidence['model']=generated_meta.get('model_version',MODEL_VERSION)
            evidence['approximation_notes']=generated_meta.get('approximation_notes',list(_SCOPE))
            for name,payload in generated.items():
                (folder/name).write_bytes(payload)
            record=dict(id=label,voltage=case['voltage'],fault_test=False,complete=False,
                        nominal_comparable=False,measurements={},rows=[],feedback_output=1,
                        loop=dict(available=False,error='未启用 COT FRA'),
                        approximation_notes=generated_meta.get('approximation_notes',list(_SCOPE)))
            first = (i-1)*(4 if fra_requested else 2)+1
            try:
                if progress:
                    progress(first,tasks,label+' · LTspice 运行')
                record['elapsed_s']=_run(executable,folder,settings['simulation_timeout_s'],cancelled,
                    simulation_end=settings['stop_ms']*1e-3,
                    progress=lambda text:progress(first,tasks,label+' · '+text) if progress else None)
                _, _, errors, warnings = read_log(folder/'Flyback.log')
                record['warnings']=warnings
                if errors:
                    raise ValueError('；'.join(errors[:5]))
                raw=TransientRaw(folder/'Flyback.raw')
                try:
                    record.update(_summarize_case(case,raw,settings,white_box_probes=white_box_probes))
                finally:
                    raw.close()
            except CalculationCancelled:
                raise
            except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
                record['error']=str(exc)
            if record['nominal_comparable']:
                if progress:progress(first+1,tasks,label+' · 反馈路 10% ↔ 90% 双向阶跃')
                def execute_step(study, timeout):
                    return _run(executable,study,timeout,cancelled,
                        progress=lambda note: progress(first+1,tasks,label+' · '+note) if progress else None)
                record['load_transient']=run_load_transient(generated,case,settings,folder/'load_step',execute_step,
                    cot=True,frequency_hz=record['measurements']['frequency_actual'])
            else:
                record['load_transient']=dict(available=False,complete=False,error='满载基础工况未通过，跳过双向阶跃')
            apply_boundary_step(record,case['p'])
            if fra_requested:
                if record['nominal_comparable']:
                    stage = [first+1]

                    def next_stage(note):
                        stage[0] += 1
                        if progress:
                            progress(stage[0],tasks,label+' · '+note)

                    def execute_sweep(sweep, timeout):
                        return _run(executable,sweep,timeout,cancelled,
                                    progress=lambda note: progress(stage[0],tasks,label+' · '+note) if progress else None)

                    record['loop']=run_fra(generated,case,settings,record['measurements']['frequency_actual'],
                                           folder/'fra',execute_sweep,progress=next_stage)
                else:
                    record['loop']['error']='标称工况未通过稳态或脉宽检查，跳过 FRA'
            record['acceptance']=assess_case(record,base,fra_requested=fra_requested)
            evidence['cases'].append(record)
        if settings.get('line_load_enabled'):
            if all(case.get('nominal_comparable') for case in evidence['cases']):
                from cot_line_load import prepare_cot_line_load
                from spice_line_load import run_line_load
                if progress:
                    progress(tasks,tasks,'COT 线载联合动态稳定度')
                def execute_line(study,timeout):
                    return _run(executable,study,timeout,cancelled,simulation_end=settings['step_ms']*.001+1.05,
                                progress=lambda note:progress(tasks,tasks,'COT 线载联合 · '+note) if progress else None)
                evidence['line_load_stability']=run_line_load(generated,[base],[case['voltage'] for case in distinct],
                    settings,base['f_sw'],root/'line_load',execute_line,prepare=prepare_cot_line_load)
            else:
                evidence['line_load_stability']=dict(complete=False,error='满载边界未通过，未运行 COT 线载联合')
        if cancelled():
            raise CalculationCancelled()
        if progress:
            progress(tasks,tasks,'整理 COT 对比报告与工程包')
        pending_report, pending_zip = root/'comparison.docx',root/'comparison.zip'
        evidence['simulation_wall_s']=time.monotonic()-start
        evidence_json=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
        with ZipFile(pending_zip,'w',ZIP_DEFLATED) as archive:
            archive.writestr('comparison.json',evidence_json)
            for folder in root.iterdir():
                if folder.is_dir():
                    for item in folder.rglob('*'):
                        if item.is_file() and (item.suffix.lower()!='.raw' or '.fra_' in item.name):
                            archive.write(item,item.relative_to(root).as_posix())
            try:
                _write_report(pending_report,evidence)
            except Exception as exc:
                recovery=destination.with_name(destination.stem+f'-evidence-{time.time_ns()}.zip')
                archive.close()
                os.replace(pending_zip,recovery)
                raise RuntimeError('报告排版未完成，实际仿真证据已保留：'+str(recovery)) from exc
            archive.write(pending_report,report_path.name)
        if cancelled():
            raise CalculationCancelled()
        os.replace(pending_report,report_path)
        os.replace(pending_zip,zip_path)
    return dict(path=str(zip_path),report_path=str(report_path),successful=sum(c['complete'] for c in evidence['cases']),
                total=len(distinct),fra_successful=sum(c['loop']['available'] for c in evidence['cases']),
                fra_total=len(distinct) if fra_requested else 0,cross_successful=0,cross_total=0,
                incomplete=any(not c['acceptance']['passed'] or any(r['status']=='偏差需复核' for r in c['rows'])
                               for c in evidence['cases']) or bool(settings.get('line_load_enabled') and
                               (not evidence['line_load_stability']['complete'] or evidence['line_load_stability'].get('protection'))),
                elapsed_s=time.monotonic()-start)
