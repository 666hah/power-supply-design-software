"""Shared Word and Excel output for LLC calculation and switched evidence."""

from math import ceil

import numpy as np

from docx_layout import figure, finalize_book_report, new_document, paragraph, table
from loop_acceptance import MIN_PHASE_MARGIN_DEG


def _show(value, scale=1.):
    if value is None:
        return '—'
    return f'{value*scale:.5g}' if np.isfinite(value) else '—'


def _scale(value, factor=1.):
    return float(value)*factor if value is not None and np.isfinite(value) else None


def _report_cell(value):
    return _show(value) if isinstance(value, (int, float, np.number)) else value or '—'


def _checks(cases):
    return [{check['id']:check for check in (case.get('result') or {}).get('checks',[])} for case in cases]


def _verdict(states):
    if 'review' in states:
        return '需复核'
    if 'undefined' in states or not states:
        return '待补充'
    return '模型满足' if 'pass' in states else '不适用'


def _word_rows(rows):
    return [tuple(_report_cell(value) for value in row) for row in rows]


def _turns(device, side):
    count = device.get('N'+side)
    if count is None:
        return '—'
    pitch = _show(device.get('d_wire_'+side), 1000.)
    return (f"{count} 匝，{device.get('parallel_wires_'+side, 1)} 束并绕，"
            f"每束 {device.get('n_strand_'+side, 1)} 股 × Ø{pitch} mm")


def _hardware_rows(result):
    tr, lr = (result['mag'].get(key) or {} for key in ('transformer','inductor'))
    rows = [
        ('磁芯型号', tr.get('core_label') or tr.get('core'), lr.get('core_label') or lr.get('core')),
        ('有效截面积 / mm²', _scale(tr.get('Ae'),1e6), _scale(lr.get('Ae'),1e6)),
        ('有效窗口 / mm²', _scale(tr.get('Wa'),1e6), _scale(lr.get('Wa'),1e6)),
        ('主要绕组', _turns(tr,'p'), _inductor_winding(lr)),
        ('副边绕组', _turns(tr,'s'), '不适用'),
        ('总等效气隙 / mm', _scale(tr.get('gap'),1000.), _scale(lr.get('gap'),1000.)),
        ('平均匝长来源', tr.get('MLT_source'), lr.get('MLT_source')),
        ('主要绕组 DCR / mΩ', _scale(tr.get('R_dc_p'),1000.), _scale(lr.get('R_dc'),1000.)),
        ('副边绕组 DCR / mΩ', _scale(tr.get('R_dc_s'),1000.), '不适用'),
        ('热模型输入',
         f"{_show(tr.get('Rth_transformer'))} K/W" if tr.get('Rth_transformer') is not None else None,
         f"{_show(lr.get('h_conv'))} W/(m²·K)" if lr.get('h_conv') is not None else None),
    ]
    for label, key, scale in (
        ('所用最小截面积 / mm²','min_Ae',1e6),
        ('绕制设计峰值电流 / A','design_peak_A',1.),
        ('设计电流对应峰值磁通 / mT','B_design_peak_T',1000.),
        ('按磁材 Bsat 估计的电流 / A','I_at_saturation_A',1.),
    ):
        value = _scale(lr.get(key),scale)
        if value is not None:
            rows.append((label,'—',value))
    return rows


def _inductor_winding(device):
    turns = device.get('N')
    if turns is None:
        return device.get('reason') or '—'
    strands = device.get('n_strand')
    if strands:
        return f"{turns} 匝，{strands} 股 × Ø{_show(device.get('d_strand',device.get('d_wire')),1000.)} mm"
    return f"{turns} 匝，等效裸铜直径 Ø{_show(device.get('d_wire'),1000.)} mm"


_MAG_METRICS = (
    ('T1', '原边绕组 RMS / A','I_rms_p',1.),
    ('T1', '副边绕组 RMS / A','I_rms_s',1.),
    ('T1', '峰值磁通密度 / mT','B_pk',1000.),
    ('T1', '磁通摆幅 / mTpp','dB',1000.),
    ('T1', '绕组铜损 / W','P_cu',1.),
    ('T1', '磁芯损耗 / W','P_core',1.),
    ('T1', '温升估算 / K','dT',1.),
    ('Lr', '绕组 RMS / A','I_rms',1.),
    ('Lr', '峰值磁通密度 / mT','B_pk',1000.),
    ('Lr', '磁通摆幅 / mTpp','dB',1000.),
    ('Lr', '绕组铜损 / W','P_cu',1.),
    ('Lr', '磁芯损耗 / W','P_core',1.),
    ('Lr', '温升估算 / K','dT',1.),
)


def _magnetic_rows(cases):
    def measure(case, ref, key):
        magnetics = (case.get('result') or {}).get('mag') or {}
        return (magnetics.get('transformer' if ref=='T1' else 'inductor') or {}).get(key)
    return [(ref, name, *[_scale(measure(c,ref,key),factor) for c in cases])
            for ref,name,key,factor in _MAG_METRICS]


def _winding_evidence(case):
    from winding_layout import assess_winding_window, transformer_windings

    p, result = case['p'], case['result']
    windows = []
    if p.get('winding_config'):
        try:
            tr = assess_winding_window(transformer_windings(result),p['winding_config'])
        except ValueError as exc:
            tr = dict(error=str(exc))
        if tr.get('configured') or tr.get('error'):
            windows.append(('T1',tr))
    lr = (result['mag'].get('inductor') or {}).get('winding_window')
    if lr and (lr.get('configured') or lr.get('error')):
        windows.append(('Lr',lr))
    return windows


def _winding_rows(windows):
    rows = []
    for ref,window in windows:
        if reason := window.get('error'):
            rows.append((ref,'布局数据需核对',reason))
            continue
        cfg = window['config']
        dimensions = f"{_show(cfg['window_width'],1000.)} × {_show(cfg['window_height'],1000.)} mm"
        rows.extend((
            (ref,'输入净窗口（轴向 × 径向）',dimensions),
            (ref,'指定绕组几何结果','模型可放下' if window['fits'] else '超出窗口'),
            (ref,'所需叠高 / 径向余量 / mm',
             f"{_show(window['required_height'],1000.)} / {_show(window['height_margin'],1000.)}"),
        ))
        for layer in window.get('physical_layers') or ():
            rows.append((ref,f"物理层 {layer['layer_index']}",
                         f"{layer['winding_id']} · {layer['turns']} 匝 · 前置绝缘 "
                         f"{_show(layer['insulation_before'],1000.)} mm"))
    return rows


def _gain_margin(loop):
    if loop.get('gm_db') is not None:
        return _scale(loop['gm_db'])
    if loop.get('gm_band_limited'):
        return '扫描带内未见相位交越'
    return '未取得有限增益裕度'


def _loop_rows(cases):
    def measure(case, kind):
        result = case.get('result') or {}
        loop = result.get('loop') or {}
        if not loop:
            return None
        if kind=='gm_db':
            return _gain_margin(loop)
        if kind=='pole':
            return '稳定' if loop.get('closed_loop_stable') else '需复核'
        if kind=='bandwidth':
            return _scale(loop['f'][-1])
        return _scale(loop.get(kind))
    return [(name,*[measure(c,key) for c in cases]) for name,key in (
        ('全部穿越的最小相位裕度 / °','min_pm'),('增益裕度 / dB','gm_db'),
        ('平均模型扫频上限 / Hz','bandwidth'),('闭环极点判定','pole'),
        ('最慢闭环极点实部 / s⁻¹','closed_loop_max_pole_real'))]


def _pi_rows(bundle, result):
    p = bundle.get('fixed_spec') or bundle['base_spec']
    loop = (result.get('loop') or {}).get('model') or {}
    mode = '混合滞环' if p['control_mode']=='Hybrid Hysteretic' else '电压变频'
    kp_unit, ki_unit = ('V/V','s⁻¹') if mode=='混合滞环' else ('Hz/V','Hz/(V·s)')
    kp = loop.get('llc_kp',p.get('llc_kp'))
    ki = loop.get('llc_ki',p.get('llc_ki'))
    return [
        ('控制方式', mode),
        (f'采用比例增益 Kp / {kp_unit}', _scale(kp) if ki else None),
        (f'采用积分增益 Ki / {ki_unit}', _scale(ki) if ki else None),
        ('目标穿越频率 / Hz', _scale(p.get('fc_target'))),
        ('整定目标相位裕度 / °', _scale(p.get('pm_target'))),
        ('最小相位裕度验收线', f'> {MIN_PHASE_MARGIN_DEG:g}°'),
    ]


def _capacitor_rows(cases, components):
    ratings = {row['ref']:row for row in components if row['kind']=='capacitor'}
    all_checks = _checks(cases)

    def loss(case, ref):
        res = case.get('result') or {}
        if ref=='C_R':
            return None
        side = 'input' if ref.startswith('C_IN') else 'output'
        bank = (res.get('capacitors') or {}).get(side, {}).get('caps',[])
        index = int(ref.removeprefix('C_IN' if side=='input' else 'C_O'))-1
        return _scale(bank[index].get('loss_W')) if index < len(bank) else None

    rows = []
    for ref, rating in ratings.items():
        if ref!='C_R' and not (ref.startswith('C_IN') or ref.startswith('C_O')):
            continue
        for metric,name,key in (('voltage','工作电压 / V','voltage_V'),
                                ('ripple','纹波 RMS / A','ripple_A')):
            checks = [cs.get(f'bom_{ref}_{metric}', {}) for cs in all_checks]
            limit = next((check['limit'] for check in checks if check.get('limit') is not None),None)
            rows.append((ref,name,_scale(rating.get(key)),_scale(limit),
                         *[_scale(check.get('value')) for check in checks],
                         _verdict([check.get('state','undefined') for check in checks])))
        if ref!='C_R':
            rows.append((ref,'ESR 损耗 / W',None,None,*[loss(c,ref) for c in cases],None))
    return rows


def _report_checks(result, capacitors):
    covered = {f'bom_{ref}_{metric}' for ref in capacitors for metric in ('voltage','ripple')}
    return [check for check in result.get('checks',[]) if check['id'] not in covered]


def _cases(bundle):
    return bundle['cases'][:1] if bundle.get('same_voltage') else bundle['cases']


def _label(case):
    return f"{case['id']} {case['voltage']:g} V"


def _heading(doc, text, level=2):
    return doc.add_heading(text,level)


def _topology(doc, p, op):
    from report_docx import _chart
    from topology_diagram import draw_topology
    figure(doc,_chart((7.1,4.25),lambda fig: draw_topology(fig.subplots(),p,op)),
           '原边桥式功率级、串联谐振腔、隔离变压器和副边四二极管整流')


def _draw_signals(fig, points, rows, *, seconds_per_unit, xlabel):
    axes = fig.subplots(len(rows), 1, sharex=True, squeeze=False).ravel()
    t = np.asarray(points['time'])
    t = (t-t[0])/seconds_per_unit
    for ax, (unit, entries) in zip(axes, rows):
        for key, label in entries:
            if key in points:
                ax.plot(t,points[key],lw=1.,label=label)
        ax.set_ylabel(unit)
        ax.grid(alpha=.24)
        if ax.lines:
            ax.legend(loc='upper right',fontsize=7,ncol=min(len(ax.lines),3))
    axes[-1].set_xlabel(xlabel)


def _device_figures(doc, points, *, startup=False):
    from report_docx import _chart

    mos = ('h1','l1','h2','l2')
    prefix = '启动 · ' if startup else '稳态 · '
    categories = [
        ('MOS 漏源电压和沟道电流',
         [('V',[(f'v(vds{name})',f'Q{i}') for i,name in enumerate(mos,1)]),
          ('A',[(f'i(vs{name})',f'Q{i}') for i,name in enumerate(mos,1)])]),
        ('整流二极管反压和电流',
         [('V',[(f'v(vr{i})',f'D{i}') for i in range(1,5)]),
          ('A',[(f'i(dr{i})',f'D{i}') for i in range(1,5)])]),
    ]
    if not startup:
        capacitors = []
        for tag, label in (('cci','输入'),('cco','输出')):
            entries = [(key,label+' '+key[len(tag)+2:-1]) for key in points if key.startswith(f'i({tag}')]
            capacitors.append(('A',entries))
        categories.append(('逐颗输入／输出电容纹波电流',capacitors))
    for label, sources in categories:
        groups = [(unit,[(key,tag) for key,tag in entries if key in points]) for unit,entries in sources]
        groups = [(unit,entries) for unit,entries in groups if entries]
        if groups:
            figure(doc,_chart((7.1,3.15 if len(groups)==2 else 2.3),
                lambda fig:_draw_signals(fig,points,groups,seconds_per_unit=.001 if startup else 1e-6,
                    xlabel='启动相对时间 / ms' if startup else '稳态相对时间 / µs')),prefix+label)


def _bode(doc, loop, fra=None):
    if not loop:
        paragraph(doc,'当前工况的小信号环路不可用。')
        return
    from report_docx import _chart
    def draw(fig):
        axes = fig.subplots(2,1,sharex=True)
        f=loop['f']
        amplitude=20*np.log10(np.maximum(abs(loop['gains'][2]),1e-30))
        phase=loop['phases'][2]
        pltrows=(amplitude,phase)
        for i, (name,array,ax) in enumerate(zip(('增益 / dB','相位 / °'),pltrows,axes)):
            ax.semilogx(f,array,lw=1.1,label='计算')
            if fra:
                field = ('gain_db','phase_deg')[i]
                for method,title in (('main','LTspice 主幅'),('half','LTspice 半幅')):
                    rows = [entry[method] for entry in fra if entry.get(method)]
                    if rows:
                        hz = [row['frequency_Hz'] for row in rows]
                        values = np.asarray([row[field] for row in rows])
                        if i:
                            expected = np.interp(np.log(hz),np.log(f),array)
                            values += 360*np.round((expected-values)/360)
                        ax.semilogx(hz,values,'.-',label=title)
            ax.set_ylabel(name)
            ax.grid(alpha=.25,which='both')
            ax.legend(loc='best',fontsize=8)
        axes[0].axhline(0.,lw=.6,color='#64748b')
        axes[1].axhline(-180.,lw=.6,color='#64748b')
        low=min(100.,min(row['frequency_Hz'] for row in fra) if fra else 100.)
        axes[1].set(xlabel='频率 / Hz',xlim=(low,f[-1]))
    figure(doc,_chart((7.1,4.0),draw),'开环增益及相位')


def export_design(path, bundle, *, document=None, save=True, chapter_level=1, include_acceptance=True):
    from report_docx import _chart
    from llc_design import draw_waveforms
    from report_architecture import (acceptance_group_line, acceptance_snapshot, add_acceptance_report,
                                     conclusion_line)

    doc = document or new_document('LLC 谐振变换器设计计算','周期解、应力、磁件与环路','LLC 设计计算')
    cases = _cases(bundle)
    good = [case for case in cases if case.get('result')]
    failed = [dict(id=case['id'],error=case.get('error')) for case in cases if not case.get('result')]
    p = bundle['base_spec']
    acceptance = acceptance_snapshot(p, bundle) if include_acceptance else None
    bridge = '半桥' if p['llc_bridge']=='half' else '全桥'
    control = '混合滞环' if p['control_mode']=='Hybrid Hysteretic' else '电压变频'
    _heading(doc,'设计结论与输入边界',chapter_level)
    paragraph(doc,f'原边{bridge}、{control}控制。输出目标 {p["V_out"]:g} V / {p["P_out"]:g} W，副边采用四二极管全桥整流。')
    if acceptance is not None:
        summary = acceptance['summary']
        conclusion_line(doc, '工程验收 ' + summary['label'], summary['state'])
        if group_line := acceptance_group_line(acceptance):
            paragraph(doc, group_line, True)
    def metrics(case):
        res=case.get('result')
        if not res:
            return ['求解失败']+['—']*10
        op,x=res['op'],res['op']['llc']
        loop=res.get('loop') or {}
        states = [check['state'] for check in res.get('checks',[])]
        return ['稳压' if x['regulation_ok'] else '需复核',_show(op['V_out']),_show(op['f_sw'],.001),
                _show(op['I_L_pk']),_show(op['I_L_rms']),_show(x['v_zvs']),
                _show(res['wf']['ripple_pp'],1000.),_show(res['eta'],100),
                _show(loop.get('fc')),_show(loop.get('pm')),
                f"{states.count('review')} / {states.count('undefined')}"]
    keys=('工作点','输出 / V','开关频率 / kHz','谐振电流峰值 / A','谐振电流 RMS / A',
          '开通前单管残压 / V','输出纹波 / mVpp','计算效率 / %','环路穿越 / Hz','相位裕度 / °',
          '计算诊断需复核 / 待补充项数')
    table(doc,['量',*map(_label,cases)],list(zip(keys,*map(metrics,cases))))
    for case in failed:
        paragraph(doc,f"{case['id']} 求解未完成。{case['error']}")
    capacitor_refs=set()
    if good:
        from component_management import evaluate_components,rating_text

        first = good[0]
        result = first['result']
        op=result['op']
        _heading(doc,'功率级与冻结硬件',chapter_level)
        table(doc,['项目','采用值'],[
            ('变压器原副边匝比',_show(op['N'])),('Lr / µH',_show(p['llc_lr'],1e6)),
            ('Cr / nF',_show(p['llc_cr'],1e9)),('Lm / µH',_show(p['llc_lm'],1e6)),
            ('串联谐振频率 / kHz',_show(op['llc']['fr_Hz'],.001)),
            ('开路谐振频率 / kHz',_show(op['llc']['fm_Hz'],.001)),
            ('桥臂死区 / ns',_show(p['llc_dead_time'],1e9))])
        _topology(doc,p,op)
        components = evaluate_components(first['p'],result).get('rows',[])
        if components:
            table(doc,['位号','用途','厂家 / 型号','资料额定值'],[
                (item['ref'],item['role'],' / '.join(str(item.get(k)) for k in ('manufacturer','model') if item.get(k)) or '—',
                 rating_text(item)) for item in components],[.68,2.25,2.1,2.07])

        _heading(doc,'隔离变压器与谐振电感',chapter_level)
        table(doc,['结构参数','变压器 T1','谐振电感 Lr'],_word_rows(_hardware_rows(result)),[2.2,2.45,2.45])
        windows = _winding_evidence(first)
        if windows:
            table(doc,['磁件','绕制项目','当前工程'],_winding_rows(windows),[.64,2.2,4.26])
        table(doc,['磁件','计算量',*map(_label,cases)],_word_rows(_magnetic_rows(cases)),[.66,2.75]+[3.69/len(cases)]*len(cases))
        paragraph(doc,'总等效气隙用于线性磁路回代。初版以绕组几何和温升核查结构，样件按实际线束、加工气隙和热点温度复核。')

        if caps := _capacitor_rows(cases,components):
            capacitor_refs = {row[0] for row in caps}
            _heading(doc,'逐颗电容应力与纹波电流',chapter_level)
            table(doc,['位号','量','额定值','降额限值',*map(_label,cases),'结论'],
                  _word_rows(caps),[.74,1.6,.72,.86]+[2.15/len(cases)]*len(cases)+[1.03])
            paragraph(doc,'输入与输出电容按本颗支路的稳态电流统计 ESR 损耗。C_R 承受全谐振电流，半桥的 C_R 峰值包含直流偏置。')

        _heading(doc,'固定补偿器与双端点环路',chapter_level)
        pi_table = table(doc,['调节量','采用值'],_word_rows(_pi_rows(bundle,result)),[4.,3.1])
        for row in pi_table.rows[:-1]:
            for cell in row.cells:
                cell.paragraphs[-1].paragraph_format.keep_with_next = True
        table(doc,['小信号环路量',*map(_label,cases)],_word_rows(_loop_rows(cases)),[3.45]+[3.65/len(cases)]*len(cases))
        paragraph(doc,'以低输入端的同一组 PI 校核所有端点。环路稳定性依据当前周期线性化模型，各端点 Bode 图保留有效频带。')
    details=[]
    for case in good:
        res=case['result']
        op=res['op']
        tag=_label(case)
        _heading(doc,tag+' 周期波形与损耗',chapter_level)
        figure(doc,_chart((7.1,5.1),lambda fig:draw_waveforms(fig.subplots(3,2).ravel(),op,res['wf'])),
               '周期波形与磁件电气量')
        table(doc,['损耗项','W'],[(k,_show(res[key])) for k,key in (
            ('桥臂与整流','P_semi'),('谐振腔串联支路','P_tank'),('磁芯增量','P_mag'),
            ('输入电容','P_cap_in'),('输出电容','P_cap'),('输入防反','P_din'),
            ('输出防反','P_dout'),('总损耗','P_total'))])
        _heading(doc,'半导体应力')
        table(doc,['对象','电压 / V','峰值电流 / A','有效值电流 / A'],[
            ('每颗 MOS',_show(op['V_sw_max']),_show(op['I_sw_pk']),_show(op['I_sw_rms'])),
            ('每颗整流管',_show(op['V_d_max']),_show(op['I_d_pk']),_show(op['I_d_rms']))])
        _heading(doc,'小信号环路与工程核查')
        _bode(doc,res.get('loop'))
        if case.get('loop_error'):
            paragraph(doc,case['loop_error'])
        checks=_report_checks(res,capacitor_refs)
        table(doc,['项目','计算值','限值','结论'],[(check['name'],
              _show(check['value'])+' '+check['unit'],_show(check['limit']),_verdict([check['state']]))
              for check in checks],[3.9,1.13,1.,1.07])
        all_checks = res.get('checks',[])
        details.append(dict(id=case['id'],checks=len(all_checks),
                             needs_review=sum(check['state'] in ('review','undefined') for check in all_checks)))
    if acceptance is not None:
        add_acceptance_report(doc, p, bundle, title='工程验收与证据', snapshot=acceptance, level=chapter_level)
    if document is None:
        finalize_book_report(doc)
    if save:
        doc.save(path)
    return dict(path=str(path),case_count=len(cases),displayed_case_count=len(cases),
                successful_cases=len(good),failed_cases=failed,incomplete=bool(failed),
                hardware_fixed=bool(bundle.get('fixed_hardware')),cross_regulation_complete=None,case_errors=failed,
                figure_count=len(doc.inline_shapes),check_count=sum(d['checks'] for d in details),
                cases=details,loop_available=bool(good) and all(c['result'].get('loop') for c in good),
                acceptance_summary=(acceptance or {}).get('summary'))


def _xlsx_grid(sheet, row, title, headers, rows, spans=None):
    from xlsx_report_writer import WIDTHS, fitted_height, number_format

    spans = spans or (1,)*len(headers)
    verdict_style = {'需复核':10,'待补充':8,'模型满足':11}
    sheet.span(row,0,sum(spans),title,2)
    for index, values in enumerate((headers,*rows),1):
        col = 0
        height = 24
        for value,width in zip(values,spans):
            actual = value if value is not None else '—'
            fmt = number_format(value) if isinstance(value,(int,float,np.number)) else None
            style = 2 if index==1 else verdict_style.get(actual,6 if index%2==0 else 0)
            sheet.span(row+index,col,width,actual,style,fmt)
            height = max(height,fitted_height(_report_cell(value),sum(WIDTHS[col:col+width])))
            col += width
        sheet.heights[row+index] = height
    return row+len(rows)+3


def export_xlsx(path, bundle):
    import engineering_workbook as layout
    from report_architecture import acceptance_group_line, acceptance_snapshot, acceptance_columns
    from report_docx import _chart
    from report_xlsx import write_acceptance_details
    from topology_diagram import draw_topology
    from xlsx_report_writer import SIDE_PX, WIDTHS, Sheet, save_workbook

    cases=_cases(bundle)
    acceptance = acceptance_snapshot(bundle['base_spec'], bundle)
    labels, acceptance_rows = acceptance_columns(acceptance, bundle)
    width = 8 if len(labels) == 1 else 17
    checks = layout.page('00 工程验收', 'LLC 谐振变换器 · 工程验收', widths=WIDTHS[:width])
    summary = acceptance['summary']
    state = 'fail' if summary['state'] == 'review' else summary['state']
    row = layout.verdict(checks, 5, '工程验收 ' + summary['label'], acceptance_group_line(acceptance), state)
    write_acceptance_details(checks, row+1, acceptance, labels, acceptance_rows)
    overview=Sheet('LLC 两端总览',column_count=8)
    sheets=[checks, overview]
    overview.span(1,0,8,'LLC 周期计算与工程核查',1)
    labels=tuple(map(_label,cases))
    overview_fields=(('输出端口 / V','V_out',1.),('输出功率 / W','P_out',1.),
                     ('开关频率 / kHz','f_sw',.001),('谐振峰值 / A','I_L_pk',1.),
                     ('谐振 RMS / A','I_L_rms',1.),('整流单管 RMS / A','I_d_rms',1.))
    summary_values=[]
    for case in cases:
        result=case.get('result') or {}
        op=result.get('op') or {}
        loop=result.get('loop') or {}
        states=[check['state'] for check in result.get('checks',[])]
        summary_values.append([
            *[_scale(op.get(key),scale) for _,key,scale in overview_fields],
            _scale(op.get('llc',{}).get('v_zvs')),_scale(loop.get('pm')),_scale(loop.get('fc')),
            _scale(result.get('eta'),100.),
            f"{states.count('review')} / {states.count('undefined')}" if result else '求解失败',
        ])
    summary_titles=[field[0] for field in overview_fields]+[
        '开通前单管残压 / V','相位裕度 / °','穿越频率 / Hz','效率 / %','计算诊断需复核 / 待补充项数']
    topology_row=_xlsx_grid(overview,3,'输入边界与稳态结果',('工程量',*labels),
                            list(zip(summary_titles,*summary_values)),(4,)+((2,2) if len(cases)==2 else (4,)))
    failed=[]
    check_count=0
    capacitor_refs=set()
    good=next((case for case in cases if case.get('result')),None)
    if good:
        from component_management import evaluate_components,rating_text

        first=good['result']
        components=evaluate_components(good['p'],first).get('rows',[])
        project=Sheet('LLC 冻结硬件',column_count=8)
        sheets.append(project)
        project.span(1,0,8,'同一套磁件与功率器件',1)
        row=_xlsx_grid(project,3,'绕组硬件',('结构参数','变压器 T1','谐振电感 Lr'),
                       _hardware_rows(first),(2,3,3))
        if windows := _winding_evidence(good):
            row=_xlsx_grid(project,row,'绕制窗口与物理层序',('磁件','绕制项目','当前工程'),
                           _winding_rows(windows),(1,2,5))
        _xlsx_grid(project,row,'实装器件资料',('位号','用途','厂家 / 型号','额定值'),
                   [(item['ref'],item['role'],' / '.join(str(item.get(k)) for k in ('manufacturer','model') if item.get(k)) or '—',
                     rating_text(item)) for item in components],(1,3,2,2))

        proof=Sheet('LLC 磁件与 PI 核算',column_count=8)
        sheets.append(proof)
        proof.span(1,0,8,'磁件波形、固定补偿与稳定裕度',1)
        row=_xlsx_grid(proof,3,'磁件双端点比较',('磁件','计算量',*labels),_magnetic_rows(cases),
                       (1,3)+((2,2) if len(cases)==2 else (4,)))
        row=_xlsx_grid(proof,row,'两端点共用 PI',('调节量','采用值'),_pi_rows(bundle,first),(4,4))
        _xlsx_grid(proof,row,'小信号环路量',('指标',*labels),_loop_rows(cases),
                   (4,)+((2,2) if len(cases)==2 else (4,)))

        if caps := _capacitor_rows(cases,components):
            capacitor_refs={row[0] for row in caps}
            detail=Sheet('LLC 电容逐颗核算',column_count=8)
            detail.span(1,0,8,'电压、有效值纹波电流与 ESR 损耗',1)
            _xlsx_grid(detail,3,'电容应力与降额',
                       ('位号','量','额定值','降额限值',*labels,'结论'),caps,
                       (1,2,1,1)+((1,1) if len(cases)==2 else (2,))+(1,))
            sheets.append(detail)
    for case in cases:
        result=case.get('result')
        detail=Sheet(case['id']+' 工程明细',column_count=8)
        sheets.append(detail)
        detail.span(1,0,8,_label(case),1)
        if not result:
            failed.append(case['id'])
            detail.cell(3,0,case.get('error','求解失败'))
            continue
        check_count+=len(result.get('checks',[]))
        _xlsx_grid(detail,3,'工程核查',('项目','计算值','限值','单位','结论','备注'),[
            (check['name'],_scale(check['value']),_scale(check['limit']),check['unit'],
             _verdict([check['state']]),check['note'])
            for check in _report_checks(result,capacitor_refs)],(2,1,1,1,1,2))
    if good:
        overview.span(topology_row,0,8,'桥式 LLC 功率级',2)
        first_image_row=topology_row+1
        height = overview.image(first_image_row,0,_chart((7.1,4.1),
                       lambda fig:draw_topology(fig.subplots(),good['p'],good['result']['op'])),
                                '桥式 LLC 功率级',width=SIDE_PX-20)
        for row in range(first_image_row,first_image_row+ceil((height+12)/32)):
            overview.heights[row] = 24
    save_workbook(path,sheets)
    return dict(path=str(path),case_count=len(cases),displayed_case_count=len(cases),
                successful_cases=len(cases)-len(failed),failed_cases=failed,incomplete=bool(failed),
                hardware_fixed=bool(bundle.get('fixed_hardware')),figure_count=int(bool(good)),check_count=check_count,
                cross_regulation_complete=None, acceptance_summary=summary)


def export_comparison(path, results):
    from report_docx import _chart
    from spice_analysis import llc_fra_phase_margin
    from spice_black_box import PHASE_MARGIN_RULE, phase_margin_conclusion

    doc = new_document('LLC 仿真与设计计算对比','黑盒性能与白盒应力','LLC 开关级对比')
    _heading(doc,'结论与运行状态',1)
    def margin_result(row):
        if row.get('fra_status', '未启用') == '未启用':
            return '未启用'
        margin = llc_fra_phase_margin(row)
        return phase_margin_conclusion(margin) if margin is None else _show(margin)+'° · '+phase_margin_conclusion(margin)

    table(doc,['输入端点','标称稳态','双向阶跃','FRA 测量','FRA 相位裕度','超差与状态说明'],[
        (row['label'],row['status'],row.get('dynamic_status','—'),row.get('fra_status','—'),margin_result(row),
         row.get('error') or ('需对齐 '+str(row['out_of_tolerance'])+' 项' if row.get('out_of_tolerance') else '—'))
        for row in results])
    if any(row.get('fra_status', '未启用') != '未启用' for row in results):
        paragraph(doc,PHASE_MARGIN_RULE+'按双幅复核通过的测点插值，取带内各交越的最小值。')
    paragraph(doc,'计算采用周期功率级；LTspice 采用独立开关网络与实际门极时序。稳态以整数个开关周期统计。启动和切换边沿的峰值按原始时间采样提取。')
    paragraph(doc,'电容对比采用与电路仿真相同的固定 C／ESR 和 ESL 选择，输入分流补入仿真所用的源阻抗。实测阻抗曲线的分流另见设计计算。',True)
    for row in results:
        _heading(doc,row['label']+' 黑盒性能',1)
        measured = row.get('measured')
        if not measured:
            paragraph(doc,row.get('error','此工况未得到有效数据。'))
            continue
        table(doc,['稳态指标','单位','计算','LTspice','偏差'],[
            (q['name'],q['unit'],_show(q['expected']),_show(q['observed']),
             ('—' if q['error_pct'] is None else f"{q['error_pct']:+.2f}%"))
            for q in row['metrics'] if not q.get('white')])
        startup=measured['startup']
        table(doc,['启动指标','结果'],[
            ('达到设定值 95% 的时间 / ms',_show(startup.get('target_95_s'),1000)),
            ('输出电压峰值 / V',_show(startup.get('V_out_peak_V'))),
            ('启动保护触发','是' if startup.get('fault') else '否')])
        figure(doc,_chart((7.1,3.5),lambda fig:_draw_signals(fig,measured['startup_waveform'],
                    [('V',[('v(out)','输出')]),('A',[('i(lr)','谐振'),('i(vrect)','整流')])],
                    seconds_per_unit=.001,xlabel='启动相对时间 / ms')),'从零启动与谐振电流')
        if row.get('dynamic'):
            dynamic=row['dynamic']
            if dynamic.get('preload_s') is not None:
                paragraph(doc,'全桥阶跃试验先带额定负载启动，随后降至 10%。以下从稳压的 10% 负载点开始测量。')
            table(doc,['方向','阶跃前 / V','最低 / V','最高 / V','阶跃后 / V','±2% 恢复 / ms'],[
                (q['direction'],_show(q['pre_V']),_show(q['min_V']),_show(q['max_V']),
                 _show(q['post_V']),_show(q.get('settle_2pct_s'),1000)) for q in dynamic['load_steps']])
            figure(doc,_chart((7.1,3.8),lambda fig:_draw_signals(fig,dynamic['dynamic_waveform'],
                        [('V',[('v(out)','输出')]),('A',[('i(lr)','谐振'),('i(vrect)','整流')]),
                         ('负载比例',[('v(load_profile)','负载')])],seconds_per_unit=.001,xlabel='相对时间 / ms')),
                   '10%→90%→10% 双向最大跳变')
        _bode(doc,row.get('loop'),row.get('fra'))
        if row.get('fra'):
            table(doc,['频率 / Hz','计算 / dB','主幅 / dB','半幅 / dB','主幅－计算 / dB','幅度复核'],[
                (_show(e['frequency_Hz']),_show(e.get('calc_db')),_show((e.get('main') or {}).get('gain_db')),
                 _show((e.get('half') or {}).get('gain_db')),_show(e.get('calculation_gain_error_db')),
                 '通过' if e.get('valid') else e.get('error','复核'))
                 for e in row['fra']])
            table(doc,['频率 / Hz','计算 / °','主幅 / °','半幅 / °','主幅－计算 / °','双幅相差 / °'],[
                (_show(e['frequency_Hz']),_show(e.get('calc_phase_deg')),_show((e.get('main') or {}).get('phase_deg')),
                 _show((e.get('half') or {}).get('phase_deg')),_show(e.get('calculation_phase_error_deg')),
                 _show(e.get('phase_delta_deg')))
                for e in row['fra']])
        _heading(doc,row['label']+' 白盒应力与稳态波形',1)
        table(doc,['稳态指标','单位','计算','LTspice','偏差'],[
            (q['name'],q['unit'],_show(q['expected']),_show(q['observed']),
             ('—' if q['error_pct'] is None else f"{q['error_pct']:+.2f}%"))
            for q in row['metrics'] if q.get('white')])
        rows=[]
        transfer = startup.get('switch_I_transfer_peak_A',[])
        for prefix,vkey,ikey in (('Q','switch_Vds_peak_V','switch_I_peak_A'),('D','diode_Vr_peak_V','diode_I_peak_A')):
            rows.extend((f'{prefix}{i}',_show(v),_show(a),
                         _show(transfer[i-1]) if prefix=='Q' and i<=len(transfer) else '—')
                        for i,(v,a) in enumerate(zip(startup.get(vkey,[]),startup.get(ikey,[])),1))
        table(doc,['启动应力位号','峰值电压 / V','峰值电流 / A','导通窗谐振峰值 / A'],rows)
        paragraph(doc,'MOS 电流的窄脉冲包含所用等效 Coss 的放电分量；谐振电流用于检查传能支路及限流阈值。',True)
        _device_figures(doc,measured['startup_waveform'],startup=True)
        figure(doc,_chart((7.1,5.1),lambda fig:_draw_signals(fig,measured['steady'],
                    [('A',[('i(lr)','谐振'),('i(lm)','励磁'),('i(vrect)','整流')]),
                     ('V',[('v(vcr)','Cr'),('v(vp)','原边绕组'),('v(vdrive)','桥激励')]),
                     ('V',[('v(out)','输出')]),('逻辑',[('v(gatep)','正向'),('v(gaten)','反向')])],
                    seconds_per_unit=1e-6,xlabel='稳态相对时间 / µs')),'实际开关周期波形')
        white = measured.get('white_box_waveforms')
        if white:
            _device_figures(doc,white)
        for note in row.get('notes',[]):
            paragraph(doc,note,True)
    doc.save(path)
