"""LLC thermal, switched and feedback evidence in the shared Excel format."""
from engineering_workbook import band, index, note, page, picture, table, verdict
from loop_acceptance import phase_margin_passes
from spice_analysis import llc_fra_phase_margin
from spice_black_box import PHASE_MARGIN_RULE, phase_margin_conclusion
from xlsx_report_writer import save_workbook


def write_llc_comparison_xlsx(path, evidence):
    from llc_report import _draw_signals
    from report_docx import _chart

    cases = evidence.get('cases', [])
    title = 'LLC 仿真与设计计算对比'
    summary = page('评审结论', title, 'LTspice 开关仿真与周期计算 · '+evidence['model'], freeze_rows=0)
    records = []
    sheets = [summary]
    links = []
    tolerance = evidence.get('settings', {}).get('comparison_tolerance_pct', 5.)
    requested_fra = bool(evidence.get('settings', {}).get('fra_enabled'))
    for i, case in enumerate(cases, 1):
        name = f'{i:02d} 输入端点'
        label = case['label']
        sheet = page(name, label+' · 黑盒与白盒', '统计窗口以完整开关周期为准，启动和阶跃分别记录。')
        sheets.append(sheet)
        links.append((name,label,'稳压、启动、动态、环路和逐器件应力'))
        statuses = (case.get('status','未完成'), case.get('dynamic_status','未执行'),
                    case.get('fra_status','未启用'))
        margin = llc_fra_phase_margin(case)
        bad = case.get('out_of_tolerance',0)
        ready = statuses[:2] == ('完成','完成') and (phase_margin_passes(margin) or not requested_fra)
        state = 'pass' if ready and not bad else 'review' if case.get('measured') else 'missing'
        records.append((label,*statuses,bad,state))
        row = verdict(sheet,4,'端点状态　'+('本轮检查满足' if state=='pass' else '待复核'),
                      case.get('error',''),state)
        if not case.get('measured'):
            continue
        steady = case['measured']
        row = band(sheet,row+1,'黑盒 · 启动与额定稳态')
        row = table(sheet,row,('达到 95% / ms','启动输出峰值 / V','启动谐振峰值 / A','保护动作'),
            [(None if steady['startup'].get('target_95_s') is None else steady['startup']['target_95_s']*1000,
              steady['startup'].get('V_out_peak_V'),steady['startup'].get('I_res_peak_A'),
              '触发' if steady['startup'].get('fault') else '未触发')])
        metrics = case.get('metrics', ())
        def rows(is_white):
            return [(x['name'],x['unit'],x['expected'],x['observed'],x['error_pct'],
                     'review' if x['error_pct'] is not None and abs(x['error_pct'])>tolerance else
                     'pass' if x['error_pct'] is not None else 'na')
                    for x in metrics if bool(x.get('white'))==is_white]
        headers = ('指标','单位','计算','LTspice','偏差 / %','对比')
        row = table(sheet,row,headers,rows(False),spans=(3,1,1,1,1,1),state_col=5)
        def signal_plot(points, channels, caption, seconds, axis):
            return picture(sheet,row+1,_chart((7.7,3.4),
                lambda fig:_draw_signals(fig,points,channels,seconds_per_unit=seconds,xlabel=axis)),caption)
        if steady.get('startup_waveform'):
            row=signal_plot(steady['startup_waveform'],[('V',[('v(out)','输出')]),
                ('A',[('i(lr)','谐振'),('i(vrect)','整流')])],'启动输出与谐振支路',.001,'时间 / ms')
        dynamic = case.get('dynamic') or {}
        if dynamic.get('load_steps'):
            row=band(sheet,row+1,'黑盒 · 10% 与 90% 双向负载阶跃')
            row=table(sheet,row,('方向','阶跃前 / V','最低 / V','最高 / V','阶跃后 / V','±2% 恢复 / ms'),
                [(d['direction'],d['pre_V'],d['min_V'],d['max_V'],d['post_V'],
                  None if d['settle_2pct_s'] is None else d['settle_2pct_s']*1000) for d in dynamic['load_steps']])
            if dynamic.get('dynamic_waveform'):
                row=signal_plot(dynamic['dynamic_waveform'],[('V',[('v(out)','输出')]),
                    ('负载比例',[('v(load_profile)','负载')])],'双向阶跃的电压与负载',.001,'时间 / ms')
        else:
            row=note(sheet,row,'双向阶跃 · '+statuses[1])
        if requested_fra:
            row=band(sheet,row+1,'黑盒 · 开关时域 FRA')
            row=table(sheet,row,('带内最小相位裕度 / °','验收','验收依据'),
                      [(margin,phase_margin_conclusion(margin),PHASE_MARGIN_RULE)],spans=(2,2,4),state_col=1)
        if case.get('fra'):
            row=table(sheet,row,('频点 / Hz','计算 / dB','主幅 / dB','半幅 / dB','计算 / °','主幅 / °','半幅 / °','双幅'),
                [(f['frequency_Hz'],f.get('calc_db'),(f.get('main') or {}).get('gain_db'),
                   (f.get('half') or {}).get('gain_db'),f.get('calc_phase_deg'),
                   (f.get('main') or {}).get('phase_deg'),(f.get('half') or {}).get('phase_deg'),
                   'pass' if f.get('valid') else 'review') for f in case['fra']],state_col=7)
        else:
            row=note(sheet,row,'开关 FRA · '+statuses[2])
        row=band(sheet,row+1,'白盒 · 稳态谐振支路和逐器件对比')
        row=table(sheet,row,headers,rows(True),spans=(3,1,1,1,1,1),state_col=5)
        if steady.get('steady'):
            row=signal_plot(steady['steady'],[('A',[('i(lr)','谐振'),('i(lm)','励磁')]),
                ('V',[('v(vdrive)','桥激励'),('v(vcr)','Cr')])],'完整周期的电流与电压',1e-6,'时间 / µs')
        for text in case.get('notes', ()):
            row=note(sheet,row,text)
    needs_review=any(r[-1]!='pass' for r in records) or not records
    row=verdict(summary,4,'总体结论　'+('待复核' if needs_review else '已执行检查满足'),
        f'对比相对偏差门限 {tolerance:g}%。'+(PHASE_MARGIN_RULE if requested_fra else '')+
        '未取得或未要求的项目在各工况单列。','review' if needs_review else 'pass')
    row=table(summary,row+1,('工况','额定稳态','双向阶跃','FRA','超差项数','结论'),records,
              spans=(2,1,1,1,1,2),state_col=5)
    if links:
        index(summary,row+1,links)
    save_workbook(path,sheets)
