"""One Word report for the distinct input conditions.

The input is a solved ``calculate_input_endpoints`` snapshot. This module never
resizes hardware, tunes compensation or changes the selected UI operating case.
Complete case blocks are captured in memory and paired by engineering module.
"""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

from docx_layout import finalize_book_report, new_document, paragraph, table
from report_docx import TOPOLOGY, export_design_docx, value


def _finite(number):
    try:
        return number is not None and math.isfinite(float(number))
    except (TypeError, ValueError):
        return False


def _result(case):
    return case.get('result') if not case.get('error') else None


def _magnetic_devices(result):
    mag = (result or {}).get('mag', {})
    devices = [mag[key] for key in ('transformer', 'inductor')
               if mag.get(key) and mag[key].get('ok')]
    devices += [dev for dev in mag.get('inductors', []) if dev.get('ok')]
    return devices


def _metrics(case):
    result = _result(case)
    if not result:
        return {}
    op, wf = result['op'], result['wf']
    loop = result.get('loop') or {}
    caps = result.get('capacitors') or {}
    devices = _magnetic_devices(result)
    return dict(eta=result.get('eta'), P_total=result.get('P_total'),
                D=op.get('D'), f_sw=op.get('f_sw'),
                I_L_pk=op.get('I_L_pk'), I_L_min=op.get('I_L_min'),
                I_sw_rms=op.get('I_sw_rms'), V_sw_max=op.get('V_sw_max'),
                V_d_max=op.get('V_d_max'), ripple_pp=wf.get('ripple_pp'),
                cap_in_rms=caps.get('input', {}).get('total_bank'),
                B_pk=max((dev['B_pk'] for dev in devices if dev.get('B_pk') is not None), default=None),
                dT=max((dev['dT'] for dev in devices if dev.get('dT') is not None), default=None),
                fc=loop.get('fc'), min_pm=loop.get('min_pm'),
                gm_db=loop.get('gm_db'))


def _worse(a, b, direction):
    """Compare only two valid endpoints, never certify the whole interval."""
    if not direction:
        return '仅对比'
    if not (_finite(a) and _finite(b)):
        return '未完整计算'
    if math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-12):
        return '两端相同'
    lower = a < b
    return 'Vinmin' if lower == (direction == 'min') else 'Vinmax'


# direction describes which numerical extreme warrants greater attention. It
# does not imply that device voltage/current ratings have been supplied.
METRICS = (
    ('eta', '模型效率', '%', 100, 'min'),
    ('P_total', '总损耗', 'W', 1, 'max'),
    ('I_L_pk', '电感或原边峰值电流', 'A', 1, 'max'),
    ('I_sw_rms', '主开关有效值电流', 'A', 1, 'max'),
    ('V_sw_max', '主开关电压应力', 'V', 1, 'max'),
    ('V_d_max', '所选路整流反压', 'V', 1, 'max'),
    ('ripple_pp', '主反馈路低频纹波', 'V', 1, 'max'),
    ('cap_in_rms', '输入电容组纹波 RMS', 'A', 1, 'max'),
    ('B_pk', '最高磁件峰值磁密', 'T', 1, 'max'),
    ('dT', '最高磁件估算温升', 'K', 1, 'max'),
    ('min_pm', '所有穿越最小相位裕度', '°', 1, 'min'),
    ('gm_db', '增益裕度', 'dB', 1, 'min'),
    ('fc', '所选下降穿越频率', 'Hz', 1, None),
    ('f_sw', '实际开关频率', 'Hz', 1, None),
    ('D', '导通占空比', '', 1, None),
    ('I_L_min', '电感或原边谷值电流', 'A', 1, None),
)


def _metric_rows(cases, metric_keys=None):
    metrics = [_metrics(case) for case in cases]
    rows = []
    for key, label, unit, scale, direction in METRICS:
        if metric_keys is not None and key not in metric_keys:
            continue
        if key in ('B_pk','dT') and all(((_result(case) or {}).get('mag',{}).get('inductor') or {}).get('design_enabled') is False for case in cases):
            continue
        numbers = [m.get(key) for m in metrics]
        cells = [value(n*scale if _finite(n) else None, unit) for n in numbers]
        if len(cases) == 2:
            cells.append(_worse(*numbers, direction))
        rows.append((label, *cells))
    return rows


def _add_hardware(doc, range_result):
    hardware = range_result.get('hardware') or {}
    rows = []
    for key, label in (('transformer', '共享变压器'), ('inductor', '电感')):
        dev = hardware.get(key)
        if not isinstance(dev, dict):
            continue
        if dev.get('design_enabled') is False:
            rows.append((label, '外购成品电感', value(dev['L'], 'H'),
                         'DCR '+value(dev['inductor_dcr'], 'Ω')))
            continue
        turns = (f"Np {dev['Np']} / Ns {dev['Ns']}" if key == 'transformer'
                 else f"N {dev['N']}")
        wire = (value(dev['d_wire_p'], 'm')+' / '+value(dev['d_wire_s'], 'm')
                if key == 'transformer' else value(dev['d_wire'], 'm'))
        rows.append((label, str(dev.get('core', '未定义')), turns, wire))
    for index, dev in enumerate(hardware.get('inductors', []), 1):
        rows.append((f'OUT{index} 电感', str(dev.get('core', '未定义')),
                     f"N {dev['N']}", value(dev['d_wire'], 'm')))
    if rows:
        table(doc, ['共用磁件', '磁芯 / 来源', '固定匝数 / L', '线径 / 成品 DCR'], rows,
              [1.2, 1.45, 2.05, 2.4])
    else:
        paragraph(doc, '待核对磁件选型。')


def export_input_range_docx(path, range_result, *, compensation_state=None,
                            mos_real_time=False, comparison=None, corners=None,
                            document=None, save=True, include_acceptance=True,
                            include_conclusion=True, chapter_start=2, chapter_prefix='',
                            chapter_level=1, tolerance_result=None):
    """Author by engineering module, comparing the same hardware side by side.

    The complete single-case author remains the content/OMML authority. Its
    native blocks are captured in memory and aligned by module; no case is
    recalculated, retuned or substituted during report generation.
    """
    from contextlib import nullcontext
    from report_architecture import (add_acceptance_report, capture_document,
        comparison_charts, write_paired_modules, module_section, acceptance_snapshot,
        report_cases, case_heading, review_findings, conclusion_line)
    cases = report_cases(range_result)
    endpoints = range_result['cases']
    base=range_result['base_spec']
    failed=[case['id'] for case in endpoints if _result(case) is None]
    fixed=bool(range_result.get('fixed_hardware',range_result.get('hardware')))
    cross=range_result.get('cross_regulation')
    cross_incomplete=bool(cross and cross.get('supported') and not cross.get('complete'))
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %Z')
    subtitle=f"{TOPOLOGY.get(base['topology'],base['topology'])}  |  {stamp}"
    if document is None:
        doc=new_document('开关电源设计评审报告',subtitle,'开关电源设计与环路分析  设计评审')
    else:
        doc=document
    acceptance=acceptance_snapshot(base,range_result) if include_conclusion or include_acceptance else None
    if include_conclusion:
        title = f'{chapter_prefix}1 计算评审结论' if chapter_prefix else '1 评审结论'
        module_section(doc, title, level=chapter_level, new_page=False)
        findings, pending = review_findings(cases)
        if failed:
            conclusion_line(doc,'计算不完整，'+'、'.join(failed)+' 求解失败','review')
        elif not fixed:
            conclusion_line(doc,'硬件未闭合，待核对磁件选型','review')
            if range_result.get('hardware_note'):
                paragraph(doc, str(range_result['hardware_note']), True)
        if cross_incomplete:
            paragraph(doc, '交叉调整率部分角点待核对。', True)
        summary = acceptance['summary']
        state = 'review' if findings else summary.get('state')
        conclusion_line(doc, f"重点复核 {len(findings)} 项，待补数据 {pending} 项", state)
        if include_acceptance:
            paragraph(doc, '工程验收 '+str(summary.get('label') or '待评估'), True)
        if findings:
            table(doc, ['优先复核', '当前值与要求'], findings[:5], [2.8, 4.3])
        labels = [case_heading(case, len(cases)) for case in cases]
        table(doc,['关键指标',*labels,*(['较不利端'] if len(cases)==2 else [])],
              _metric_rows(cases,{'eta','I_L_pk','V_sw_max','ripple_pp','dT','min_pm'}),
              [2.35,1.6,1.6,1.55] if len(cases)==2 else [3.8,3.3])
        module_section(doc, '共同磁件配置', level=chapter_level+1, size=13, new_page=False)
        _add_hardware(doc,range_result)
        if fixed and len(cases)==2:
            paragraph(doc,'两端使用同一套已确定硬件与补偿。',True)
        if len(cases)==2 and cases[0]['voltage']==cases[1]['voltage'] and not failed:
            paragraph(doc,'输入电压相同。各自的工况结果分别列出。', True)
    for case in cases:
        if case.get('error'):
            paragraph(doc, case['id']+' '+str(case['error']), True)
    # Keep the complete author as the single source for data, equations and
    # plots. The paired capture renders graphics at their final physical width.
    contents=[];details=[]
    for case in cases:
        temp=new_document('', '', '')
        result=_result(case)
        if result is not None:
            # Use the portrait chart scale for a single displayed endpoint.
            with comparison_charts() if len(cases)==2 else nullcontext():
                details.append(export_design_docx('',case['p'],result['op'],result['wf'],result,
                    models=case.get('models'),loop_error=case.get('loop_error'),
                    corners=case.get('corners') or (corners if case['id']=='Vinmin' else None),
                    comparison=comparison if case['id']=='Vinmin' else None,
                    mos_real_time=mos_real_time,efficiency_curve=case.get('efficiency_curve'),
                    compensation_state=compensation_state,document=temp,save=False,include_conclusion=False))
        # Temporary shell titles are for page geometry and style only.
        for item in temp.paragraphs[:2]:
            item._p.getparent().remove(item._p)
        contents.append(capture_document(temp))
    structure=write_paired_modules(doc,contents,cases,chapter_start=chapter_start,
                                  chapter_prefix=chapter_prefix,chapter_level=chapter_level)
    if include_acceptance:
        add_acceptance_report(doc,base,range_result,title='工程验收与证据',snapshot=acceptance)
    if tolerance_result is not None:
        from tolerance_report import TITLE, add_word_chapter
        number = chapter_start + structure['chapters']
        title = f'{chapter_prefix}{number} {TITLE}' if chapter_prefix else TITLE
        add_word_chapter(doc, tolerance_result, title, level=chapter_level)
    if save:
        finalize_book_report(doc)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(path)
    incomplete=bool(failed) or not fixed or cross_incomplete
    return dict(path=str(path),case_count=2,successful_cases=2-len(failed),failed_cases=failed,
        displayed_case_count=len(cases),
        incomplete=incomplete,hardware_fixed=fixed,
        cross_regulation_complete=cross.get('complete') if cross else None,
        figure_count=len(doc.inline_shapes),check_count=sum(d['checks'] for d in details),
        cases=details,figures=len(doc.inline_shapes),checks=sum(d['checks'] for d in details),
        needs_review=sum(d['needs_review'] for d in details),
        loop_available=all((_result(c) or {}).get('loop') is not None for c in cases),
        report_architecture='module-paired-v1',acceptance_summary=(acceptance or {}).get('summary'),**structure)
