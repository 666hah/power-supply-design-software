"""Engineering comparison pages based on real switching, FRA and load corners."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import math
import numpy as np

from loop_acceptance import MIN_PHASE_MARGIN_DEG, phase_margin_passes
from spice_analysis import minimum_phase_margin
from spice_black_box import PHASE_MARGIN_RULE, fra_phase_margin, phase_margin_conclusion


def _endpoint(case):
    """Use the stored endpoint identity, never infer it from voltage ordering."""
    name = str(case.get('id', ''))
    for endpoint in ('Vinmin', 'Vinmax'):
        if name == endpoint or name.startswith(endpoint+'_'):
            return endpoint, name[len(endpoint):].strip('_ ') or '标称工况'
    return None, name or '未命名工况'


def _fixed_supply(evidence):
    limits = evidence.get('input_range_V') or ()
    if len(limits) == 2 and limits[0] is not None and limits[0] == limits[1]:
        return limits[0]
    if not limits:
        planned = (evidence.get('plan') or {}).get('voltages') or ()
        if len(planned) == 1:
            return planned[0]
    return None


def _format(value, unit=''):
    if value is None:
        return '未取得'
    if isinstance(value, str):
        return value
    number = float(value)
    return f'{number:.5g}'+(' '+unit if unit else '') if math.isfinite(number) else '无有效值'


def _case_label(case, fixed_voltage):
    endpoint, family = _endpoint(case)
    if fixed_voltage is not None:
        return family
    voltage = _format(case.get('voltage'), 'V')
    return f'{endpoint} {voltage} · {family}' if endpoint else f'{family} · {voltage}'


def _component_subject(metric):
    if metric.startswith('MOS '):
        return 'mos'
    if '管反压' in metric or '二极管 D1 电流' in metric or '整流管电流' in metric:
        return 'diode'
    if '电容' in metric:
        return 'capacitor'
    return None


def _full_band_q1_current(row):
    return row.get('unit') == 'A' and (row.get('ref') == 'Q1' and row.get('kind') == 'mos'
                                      or row.get('metric', '').startswith('MOS Q1 沟道电流'))


def _startup_peak(case, ref, channel):
    rows = (case.get('white_box_startup') or {}).get('rows', ())
    return next((row for row in rows if row.get('ref') == ref and row.get('channel') == channel
                 and row.get('simulation') is not None), {})


def simulation_summary(evidence):
    """Project recorded simulation checks and comparisons for either cover."""
    cases = evidence.get('cases') or []
    settings = evidence.get('settings') or {}
    plan = evidence.get('plan') or {}
    fixed_voltage = _summary_voltage(evidence)
    families = [_endpoint(case)[1] for case in cases]
    # Named endpoints distinguish independent saved runs at the same voltage.
    single = fixed_voltage if len(families) == len(set(families)) else None
    findings, pending, deviations = [], [], {}
    nominal = [case for case in cases if not case.get('fault_test')]
    steady = 0
    if not nominal:
        pending.append(('标称工况', '未取得运行记录'))
    voltages = plan.get('voltages') or evidence.get('input_range_V') or ()
    if len(voltages) == 2 and voltages[0] is not None and voltages[1] is not None and voltages[0] != voltages[1]:
        present = {_endpoint(case)[0] for case in nominal}
        for endpoint, voltage in zip(('Vinmin', 'Vinmax'), voltages):
            if endpoint not in present:
                pending.append((f"{endpoint} · 标称工况", f"{_format(voltage, 'V')} 未取得运行记录"))
    for case in cases:
        label = _case_label(case, single)
        startup = case.get('white_box_startup') or {}
        for row in startup.get('rows', ()):
            if row.get('status') not in ('超过器件额定电压', '超过配置降额限值'):
                continue
            limit = row.get('rating') if row['status'] == '超过器件额定电压' else row.get('limit')
            findings.append((f"{label} · 启动 {row['ref']} {row['metric']}",
                f"{_format_stress(row)}。{row['status']} {_format(limit, row['unit'])}。"))
        if not case.get('complete'):
            reason = case.get('error') or '未取得完整结果'
            findings.append((label+' · 运行未完成', str(reason)))
            continue
        quality = case.get('periodicity') or {}
        if case.get('fault_test'):
            continue
        steady_quality = case.get('steady_before_step') or {}
        if quality.get('stable') is False:
            findings.append((label+' · 逐周期复核', quality.get('reason') or '末段未稳态'))
        elif steady_quality.get('passed') is False or case.get('nominal_comparable') is False:
            findings.append((label+' · 稳态复核', steady_quality.get('reason') or '标称窗口待复核'))
        elif quality.get('stable') is True:
            steady += 1
        else:
            pending.append((label+' · 逐周期检查', '未取得周期检查记录'))
        events = case.get('fault_events_s') or ()
        if events:
            findings.append((label+' · 保护动作', '首次发生于 '+_format(events[0]*1000, 'ms')))
        if settings.get('fra_enabled'):
            loop = case.get('loop') or {}
            margin = fra_phase_margin(loop)
            if margin is None:
                pending.append((label+' · 环路 FRA', loop.get('error') or '待补有效相位裕度'))
            elif not phase_margin_passes(margin):
                findings.append((label+' · FRA 最小相位裕度',
                                 f'{_format(margin, "°")} 未达标，要求 > {MIN_PHASE_MARGIN_DEG:g}°。'))
        if (settings.get('cross_enabled') and not plan.get('cross_skip_reason') and
                evidence.get('topology') not in ('BUCK', 'BOOST') and
                not (case.get('cross') or {}).get('complete')):
            pending.append((label+' · 交叉调整率', (case.get('cross') or {}).get('error') or '待补有效角点'))
        transient = case.get('load_transient')
        if transient is not None and not transient.get('complete'):
            pending.append((label+' · 双向负载阶跃', transient.get('error') or transient.get('reason') or '未完成'))
        elif transient:
            for event in transient.get('events',[]):
                if event.get('recovery_s') is None:
                    findings.append((label+f" · OUT{event['rail']} {event['before']:.0%}→{event['after']:.0%}",
                        f"在 {event.get('observed_s',0)*1000:.4g} ms 观察窗内未持续回到参考电压 ±{transient.get('band_pct',2):g}% 带内"))
        for row in list(case.get('rows') or ()) + list((case.get('white_box') or {}).get('rows') or ()):
            if evidence.get('topology') in ('FLYBACK','QR-FLYBACK') and _full_band_q1_current(row):
                continue
            delta = row.get('delta_percent')
            if row.get('status') == '偏差待复核' and isinstance(delta, (int, float)) and math.isfinite(delta):
                metric = row['metric']
                deviations.setdefault(metric, []).append((abs(delta), f'{label} {delta:+.2f}%'))
    line = evidence.get('line_load_stability') or {}
    if settings.get('line_load_enabled'):
        if not line.get('complete'): pending.append(('线载联合动态稳定度',line.get('error') or '未取得完整试验'))
        elif line.get('protection'): findings.append(('线载联合动态稳定度','观察窗口内出现保护动作'))
    tolerance = settings.get('comparison_tolerance_pct')
    deviation_rows = sorted(deviations.items(), key=lambda pair: -max(item[0] for item in pair[1]))
    for metric, observations in deviation_rows:
        findings.append((metric, '\n'.join(item[1] for item in observations)))
    state = 'review' if findings else 'undefined' if pending else 'pass'
    if state == 'pass':
        conclusion = f'标称逐周期检查通过 {steady}/{len(nominal)} 个工况'
    else:
        conclusion = f'重点复核 {len(findings)} 项，待补数据 {len(pending)} 项'
    return dict(conclusion=conclusion, state=state, findings=findings, pending=pending,
                review_count=len(findings), pending_count=len(pending), fixed_voltage=fixed_voltage,
                single_label_voltage=single, comparison_tolerance_pct=tolerance)


def _format_stress(row):
    value = _format(row.get('simulation'), row.get('unit', ''))
    time = row.get('time_s')
    return f"{value} / {_format(time*1000, 'ms')}" if time is not None else value


def _summary_voltage(evidence):
    declared = _fixed_supply(evidence)
    cases = evidence.get('cases') or []
    voltages = {case.get('voltage') for case in cases}
    if voltages == {declared} and declared is not None:
        return declared
    endpoints = {_endpoint(case)[0] for case in cases}
    if endpoints == {'Vinmin', 'Vinmax'} and len(voltages) == 1 and None not in voltages:
        return voltages.pop()
    return None


def _render_endpoint_modules(doc, modules, make_table, paragraph, page, *,
                             fixed_voltage=None, show_scope=True):
    """Recompose complete evidence by test family and physical subject.

    A declared fixed supply needs one result per test family. If old evidence
    contains two distinct runs at the same voltage, retain both records.
    """
    from collections import OrderedDict, defaultdict
    from itertools import zip_longest
    from docx_layout import figure
    from report_architecture import add_paired_figure, available_width
    from spice_box_figures import STARTUP_HEADERS, STARTUP_WIDTHS

    def is_comparison(headers):
        return (len(headers) == 6 and tuple(headers[:3]) == ('指标','单位','设计计算')
                and headers[3] in ('LTspice 实测','LTspice 仿真') and headers[4] == '偏差')

    families, groups = OrderedDict(), OrderedDict()
    for module in modules:
        endpoint, family = _endpoint(module['case'])
        if endpoint is None:
            # Nonstandard saved IDs remain explicitly unbound and readable.
            family = '未绑定端点 '+family
            endpoint = 'record'
        cases = families.setdefault(family, {})
        cases[endpoint] = module['case']
        key = (family, module['title'])
        bucket = groups.setdefault(key, {})
        if endpoint in bucket:
            raise ValueError('同一端点与模块存在重复证据：'+module['case']['id']+' / '+module['title'])
        bucket[endpoint] = module

    def missing(family, endpoint):
        case = families[family].get(endpoint)
        if not case:
            return '未执行：本次未提供该具名端点的证据'
        if not case.get('complete'):
            return '工况未完成：'+str(case.get('error') or '未取得有效结果')
        return '该模块未取得'

    def records(module):
        result, counts = OrderedDict(), defaultdict(int)
        for block in module.get('blocks', []) if module else []:
            if block['kind'] != 'table': continue
            headers = tuple(block['headers']); counts[headers] += 1
            result[(headers, counts[headers])] = block
        return result

    def render_single(module, title):
        for block in module['blocks']:
            if block['kind'] == 'paragraph':
                paragraph(block['text'])
            elif block['kind'] == 'table':
                widths = [25.8 / len(block['headers'])] * len(block['headers'])
                if is_comparison(block['headers']):
                    widths = [5.9, 1.6, 3.1, 3.9, 3.0, 8.3]
                elif tuple(block['headers']) == STARTUP_HEADERS:
                    widths = STARTUP_WIDTHS
                make_table(block['headers'], block['rows'], widths)
            else:
                from PIL import Image
                with Image.open(BytesIO(block['blob'])) as image:
                    width = min(available_width(doc), 5.3 * image.width / image.height)
                figure(doc, block['blob'], block.get('caption') or title, width=width)

    previous_family = None
    family_order = {family: index for index, family in enumerate(families)}
    ordered_groups = sorted(groups.items(), key=lambda item: family_order[item[0][0]])
    for (family, title), sides in ordered_groups:
        first_in_family = family != previous_family
        heading = page(f'{family}  {title}' if first_in_family and show_scope else title)
        if heading is not None:
            heading.paragraph_format.page_break_before = False
        previous_family = family
        if 'record' in sides:
            module = sides['record']
            paragraph('独立记录，未绑定端点。')
            make_table(['记录', '实际输入 / V'], [(module['case']['id'], module['case'].get('voltage', '未取得'))], [12.9, 12.9])
            render_single(module, title)
            continue
        left, right = sides.get('Vinmin'), sides.get('Vinmax')
        family_cases = families[family]
        if (fixed_voltage is not None and len(family_cases) == 1 and
                next(iter(family_cases.values())).get('voltage') == fixed_voltage):
            render_single(left or right, title)
            continue
        equal_voltage = (
            len(family_cases) == 2 and family_cases['Vinmin'].get('voltage') is not None and
            family_cases['Vinmin'].get('voltage') == family_cases['Vinmax'].get('voltage')
        )
        if equal_voltage and left and right and left['blocks'] == right['blocks']:
            render_single(left, title)
            continue
        labels = {}
        for name, module in (('Vinmin', left), ('Vinmax', right)):
            case = module['case'] if module else families[family].get(name)
            labels[name] = name if equal_voltage else name+('  '+f"{case.get('voltage', '未取得')} V" if case else '  未提供')
        if first_in_family and show_scope:
            make_table(['对照范围', labels['Vinmin'], labels['Vinmax']], [
                ('本次工况', left['case']['id'] if left else missing(family, 'Vinmin'),
                 right['case']['id'] if right else missing(family, 'Vinmax'))], [5.9, 9.95, 9.95])

        lt, rt = records(left), records(right)
        for key in list(lt)+[k for k in rt if k not in lt]:
            a, b = lt.get(key), rt.get(key)
            headers = list(key[0]); lrows = a['rows'] if a else []; rrows = b['rows'] if b else []
            def keyed(rows):
                result, counts = OrderedDict(), defaultdict(int)
                for row in rows:
                    identity = str(row[0]); counts[identity] += 1
                    result[(identity, counts[identity])] = row
                return result
            la, rb = keyed(lrows), keyed(rrows)
            ids = list(la)+[k for k in rb if k not in la]
            if is_comparison(headers):
                rows = []
                for row_id in ids:
                    x, y = la.get(row_id), rb.get(row_id)
                    base = x or y
                    def cells(row, endpoint):
                        return (row[2], row[3], str(row[4])+'\n'+str(row[5])) if row else ('未取得', '未取得', missing(family,endpoint))
                    unit = base[1] if not (x and y) or x[1] == y[1] else 'Vinmin '+str(x[1])+' / Vinmax '+str(y[1])
                    rows.append((base[0], unit, *cells(x,'Vinmin'), *cells(y,'Vinmax')))
                make_table(['指标','单位',labels['Vinmin']+'\n计算',labels['Vinmin']+'\n仿真','偏差与状态',
                            labels['Vinmax']+'\n计算',labels['Vinmax']+'\n仿真','偏差与状态'],
                           rows,[5.4,1.5,2.6,2.6,4.25,2.6,2.6,4.25])
            elif tuple(headers) == STARTUP_HEADERS:
                def startup_cells(row):
                    return tuple(row[2:]) if row else ('—','—','—','—','未取得')
                rows, mixed_units = [], False
                for row_id in ids:
                    x, y = la.get(row_id), rb.get(row_id)
                    base = x or y
                    unit = base[1]
                    if x and y and x[1] != y[1]:
                        unit = f'{x[1]} / {y[1]}'
                        mixed_units = True
                    rows.append((base[0], unit, *startup_cells(x), *startup_cells(y)))
                count = len(headers)-2
                make_table(headers[:2]+headers[2:]*2, rows, STARTUP_WIDTHS+STARTUP_WIDTHS[2:],
                           column_groups=(('测量对象',2,None),(labels['Vinmin'],count,'E0EDF9'),
                                          (labels['Vinmax'],count,'F9EDD9')))
                if mixed_units:
                    paragraph('同一行的单位有两项时，按 Vinmin、Vinmax 顺序列示。')
                for endpoint, block in (('Vinmin',a),('Vinmax',b)):
                    if block is None:
                        paragraph(f'{labels[endpoint]}：{missing(family,endpoint)}。')
            else:
                def detail(row, endpoint):
                    if row is None: return missing(family, endpoint)
                    if len(headers)==2: return row[1]
                    fields = [f'{header} {value}' for header,value in zip(headers[1:],row[1:])]
                    lines = []
                    for field in fields:
                        if lines and len(lines[-1])+len(field) <= 32 and len(headers)>4:
                            lines[-1] += '  |  '+field
                        else:
                            lines.append(field)
                    return '\n'.join(lines)
                rows = [(str((la.get(k) or rb[k])[0]), detail(la.get(k),'Vinmin'), detail(rb.get(k),'Vinmax')) for k in ids]
                make_table([headers[0],labels['Vinmin'],labels['Vinmax']],rows,[5.9,9.95,9.95])

        pictures = [[b for b in (m or {}).get('blocks',[]) if b['kind']=='chart'] for m in (left,right)]
        multiple = max(map(len, pictures)) > 1
        for image_index, (a,b) in enumerate(zip_longest(*pictures), 1):
            caption = (a or b).get('caption')
            series = f'（第 {image_index} 组）' if multiple else ''
            left_blob, right_blob = (a or {}).get('blob'), (b or {}).get('blob')
            if left_blob and left_blob == right_blob:
                figure(doc, left_blob, caption or f'{title}（两端共用）{series}', width=4.9)
                continue
            # Each source plot is drawn at its final physical width, retaining
            # readable fonts rather than shrinking an existing full-page plot.
            add_paired_figure(doc,left_blob,right_blob,caption or f'{title}{series}',
                left_label=labels['Vinmin'],right_label=labels['Vinmax'])

        notes = [[b['text'] for b in (m or {}).get('blocks',[]) if b['kind']=='paragraph'] for m in (left,right)]
        for a,b in zip_longest(*notes):
            if a==b and a: paragraph(a)
            else:
                if a: paragraph('Vinmin '+a)
                if b: paragraph('Vinmax '+b)


def write_report(path,evidence,*,chart_images=None,document=None,save=True,
                 include_conclusion=True,section_number=5):
    """Render actual evidence, optionally append to an existing joint report.

    Appending creates a landscape section in the same package. Figures,
    relationships and native equations remain owned by one Document; no
    second simulation, XML package merge or global style rewrite is needed.
    """
    from docx.shared import Inches, Pt
    from docx.enum.section import WD_SECTION_START
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx_layout import (_font, equation, finalize_book_report, new_document,
                             figure, paragraph as write_paragraph, set_a4_page, table as write_table)
    from report_architecture import available_width, conclusion_line, module_section
    from spice_black_box import black_box_sections
    from spice_box_figures import (draw_excitation_ramps, draw_line_load, draw_load_step, draw_step_edges,
                                  white_sections, white_startup_sections)
    from spice_export import SETTINGS,CHOICES
    # Images in older ZIPs are not keyed by experiment. Their sequence cannot
    # identify the new black/white-box sections; redraw from measured data.
    prepared=None
    # Existing measurement/plot builders remain the single content source.
    # Case modules are collected as data, then compared by named endpoint.
    paired_modules = []
    active_case = None
    active_box = 'black'
    active_topic = ''
    active_module = None
    def collecting():
        return active_case is not None and active_module is not None
    from report_docx import TOPOLOGY
    model = evidence.get('model', 'LTspice')
    topology = evidence.get('topology', '')
    flyback_ramp = topology in ('FLYBACK','QR-FLYBACK')
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %Z')
    subtitle = f"{TOPOLOGY.get(topology, topology)}  |  {model}  |  {stamp}"
    title = '有源钳位正激计算精度复核报告' if evidence.get('precision_summary') else '仿真与设计计算对比报告'
    doc = new_document(title, subtitle, '开关电源设计与环路分析  电路仿真评审') if document is None else document

    def landscape(*, embedded=False):
        sec = doc.add_section(WD_SECTION_START.NEW_PAGE)
        set_a4_page(sec, landscape=True)
        if embedded:
            sec.footer.is_linked_to_previous = False
            footer = sec.footer.paragraphs[0]
            footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _font(footer.add_run('研发设计评审  ·  '), 8)
            field = OxmlElement('w:fldSimple')
            field.set(qn('w:instr'), 'PAGE')
            footer._p.append(field)

    def paragraph(text, small=False):
        if collecting():
            active_module['blocks'].append(dict(kind='paragraph', text=str(text)))
            from types import SimpleNamespace
            return SimpleNamespace(paragraph_format=SimpleNamespace(space_after=None))
        return write_paragraph(doc, str(text), small=small)

    fmt = _format

    def table(headers,rows,widths,*,compact=False,column_groups=()):
        rows = list(rows)
        if collecting():
            active_module['blocks'].append(dict(kind='table', headers=list(headers), rows=rows))
            return None
        if not rows:
            return None
        names = {'LTspice 实测': 'LTspice 仿真', '判定口径': '结论'}
        headers = [names.get(header, header) for header in headers]
        width = available_width(doc)
        grid = write_table(doc, headers, rows, [value*width/sum(widths) for value in widths],
                           column_groups=column_groups)
        endpoint_fill = {'Vinmin': 'E0EDF9', 'Vinmax': 'F9EDD9'}
        for header, cell in zip(headers, grid.rows[0].cells) if not column_groups else ():
            endpoint = header.split(maxsplit=1)[0] if header else ''
            if endpoint in endpoint_fill:
                shade = cell._tc.get_or_add_tcPr().find(qn('w:shd'))
                shade.set(qn('w:fill'), endpoint_fill[endpoint])
        if len(rows) <= 7 and sum(len(str(cell)) for row in rows for cell in row) < 1000:
            for row in grid.rows[:-1]:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.keep_with_next = True
        if compact:
            for row in grid.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.line_spacing = Pt(12)
        return grid
    def page(title):
        nonlocal active_module
        if active_case is not None:
            prefix=active_case['id']+'  Vin '+fmt(active_case['voltage'],'V')
            label=title[len(prefix):].strip() if title.startswith(prefix) else title
            active_module=dict(case=active_case, title=label, box=active_box, topic=active_topic, blocks=[])
            paired_modules.append(active_module)
            return
        return module_section(doc, title, level=2 if document is None else 3, new_page=False)
    def chart(draw,height,caption=None):
        if prepared is not None:
            blob=next(prepared)
            if collecting(): active_module['blocks'].append(dict(kind='chart',blob=blob,caption=caption))
            else: doc.add_picture(BytesIO(blob),width=Inches(available_width(doc)))
            return
        from matplotlib import rc_context
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        with rc_context({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'font.size':9,'axes.unicode_minus':False}):
            paired = collecting() and not single_chart
            chart_width = min(9.6, available_width(doc))
            fig=Figure(figsize=(4.72,min(height,4.85)) if paired else (chart_width,min(height,5.3)),layout='constrained');FigureCanvasAgg(fig);draw(fig)
            if paired:
                import textwrap
                for axis in fig.axes:
                    axis.set_title('\n'.join(textwrap.wrap(axis.get_title(),16)),fontsize=9)
                    axis.tick_params(labelsize=8)
                    axis.xaxis.label.set_size(8);axis.yaxis.label.set_size(8)
            stream=BytesIO();fig.savefig(stream,format='png',dpi=170);stream.seek(0)
            if collecting(): active_module['blocks'].append(dict(kind='chart',blob=stream.getvalue(),caption=caption))
            else: figure(doc,stream.getvalue(),caption or 'LTspice 波形',width=chart_width)
    def axes_format(axes):
        for axis in np.asarray(axes,dtype=object).ravel():
            axis.grid(alpha=.2);handles,_=axis.get_legend_handles_labels()
            if handles:axis.legend(fontsize=7,loc='best')
    def startup_plot(fig, data):
        axes = fig.subplots(3 if 'v(input)' in data else 2, 1, sharex=True)
        time = np.asarray(data['time'])*1000
        for key, values in data.items():
            if key.startswith('v(out'):
                axes[0].plot(time, values, label=key[2:-1].upper())
        axes[0].set(title='各路端口输出', ylabel='V')
        for key, label in (('v(ss)', '软启动 SS'), ('v(fault)', '保护 FAULT'), ('v(en)', '使能 EN')):
            if key in data:
                axes[1].plot(time, data[key], label=label)
        axes[1].set(title='启动与保护', ylabel='电平 / V')
        if len(axes) == 3:
            axes[2].plot(time, data['v(input)'], color='tab:purple', label='输入端口')
            axes[2].set(ylabel='V')
        axes[-1].set_xlabel('时间 / ms')
        axes_format(axes)

    def startup_control(fig, data):
        axes = fig.subplots(2, 1, sharex=True)
        time = np.asarray(data['time'])*1000
        for axis, group in zip(axes, (
                (('v(vcc)', 'VCC'), ('v(comp)', 'COMP'), ('v(zcd)', 'ZCD')),
                (('v(xu_ctrl:filtered)', '滤波 CS'), ('v(xu_ctrl:trip)', '限流判据'), ('v(cs)', 'CS')))):
            for key, label in group:
                if key in data:
                    axis.plot(time, data[key], label=label)
            axis.set_ylabel('V')
        axes[0].set_title('启动供电、补偿与过零检测')
        axes[1].set_title('启动电流采样与限流')
        axes[1].set_xlabel('时间 / ms')
        axes_format(axes)

    def port_ripple(fig, data, branches):
        times = np.asarray(data['time'])
        axis = fig.subplots()
        for branch in branches:
            rail = branch['id']
            key = f'v(out{rail})'
            if key not in data:
                continue
            actual = np.asarray(data[key], dtype=float).copy()
            actual -= np.trapezoid(actual, times)/(times[-1]-times[0])
            axis.plot((times-times[0])*1e6, actual*1000, label=f'OUT{rail} 仿真')
            if branch.get('design_ripple') is not None:
                expected = np.asarray(branch['design_ripple'], dtype=float).copy()
                expected -= np.mean(expected)
                axis.plot((times-times[0])*1e6, expected*1000, '--', label=f'OUT{rail} 计算')
        axis.set(xlabel='相对时间 / μs', ylabel='去直流纹波 / mV')
        axes_format([axis])

    def design_step_plot(fig, design):
        time = np.asarray(design['time_s'])*1000
        axes = fig.subplots(2, 1, sharex=True)
        for axis, direction, key in zip(axes, ('10%→90%', '90%→10%'), ('rise', 'fall')):
            metrics = design[key]
            axis.plot(time, design[key+'_voltage_V'],label=direction)
            target, band = metrics['final_voltage_V'], metrics['settling_band_V']
            axis.axhspan(target-band, target+band, alpha=.1, color='tab:green',label='计算恢复观察带')
            axis.axvline(0., color='.36', linestyle='--', linewidth=.7)
            axis.set_ylabel('反馈端口 / V')
        axes[-1].set_xlabel('相对阶跃时刻 / ms')
        axes_format(axes)
    def row_values(rows):
        return [(r['metric'],r['unit'] or '—',fmt(r['design']),fmt(r['simulation']),
            '不判差' if r['delta_percent'] is None else f"{r['delta_percent']:+.2f}%",r['status']) for r in rows]
    def metric_table(rows):
        table(['指标','单位','设计计算','LTspice 实测','偏差','判定口径'],row_values(rows),[6.4,1.1,3.1,3.1,2.2,9.9])
    def entry(value):return fmt(value) if value is not None else '未测到交越'
    settings=evidence['settings'];qr=evidence.get('topology')=='QR-FLYBACK';forward=evidence.get('topology')=='ACF-FORWARD'
    noniso=evidence.get('topology') in ('BUCK','BOOST');buck=evidence.get('topology')=='BUCK'
    plan = evidence.get('plan') or {}
    fixed_voltage = _fixed_supply(evidence)
    summary = simulation_summary(evidence)
    summary_voltage = summary['fixed_voltage']
    single_chart = summary['single_label_voltage'] is not None
    def chapter(number, title):
        heading = f'{number} {title}' if document is None else f'{section_number}.{number-1} {title}'
        return module_section(doc, heading, level=1 if document is None else 2, new_page=False)

    if document is not None:
        current = doc.sections[-1]
        if not single_chart and current.page_width <= current.page_height:
            landscape(embedded=True)
        module_section(doc, f'{section_number} 电路仿真与设计对照', new_page=False)
        paragraph(subtitle, True)
    if include_conclusion:
        module_section(doc, '1 评审结论' if document is None else '评审结论',
                       level=1 if document is None else 2, new_page=False)
        conclusion_line(doc, summary['conclusion'], summary['state'])
        table(['优先复核', '本次记录'], summary['findings'][:4], [2.8, 4.3])
        table(['待补数据', '缺项'], summary['pending'][:2], [2.8, 4.3])
        if summary['comparison_tolerance_pct'] is not None:
            paragraph('计算与仿真偏差复核线 '+fmt(summary['comparison_tolerance_pct'], '%')+'。', True)
        key_rows = []
        startup_rows = []
        available = [case for case in evidence['cases'] if case.get('complete') and not case.get('fault_test')]
        full_peak = any((case.get('qr_startup') or {}).get('vds_peak_full_v') is not None for case in available)
        if any(_startup_peak(case, 'Q1', 'voltage') for case in available):
            full_peak = False
        for case in available:
            m = case.get('measurements') or {}
            feedback = case.get('feedback_output', 1)
            voltage_peak = fmt(m.get('vds_peak'))
            if full_peak:
                voltage_peak += ' / '+fmt((case.get('qr_startup') or {}).get('vds_peak_full_v'))
            key_rows.append((_case_label(case, summary['single_label_voltage']),
                             f"OUT{feedback} {fmt(m.get(f'out{feedback}_before'))}",
                             voltage_peak,
                             fmt(m['frequency_actual']/1000 if m.get('frequency_actual') is not None else None)))
            mos, line = _startup_peak(case, 'Q1', 'voltage'), _startup_peak(case, '输入端', 'current')
            if mos or line:
                startup_rows.append((_case_label(case, summary['single_label_voltage']),
                    _format_stress(mos), _format_stress(line),
                    '覆盖完整' if case['white_box_startup'].get('complete_window') else '部分窗口'))
        table(['工况', '主反馈输出 / V', '稳态 / 全程 Vds 峰值（V）' if full_peak else 'Vds 峰值 / V',
               '开关频率 / kHz'], key_rows, [2.2,1.45,1.9,1.55])
        table(['额定负载启动', 'Q1 Vds 峰值与时刻', '输入峰值电流与时刻', '启动窗口'],
              startup_rows, [2, 1.7, 1.7, 1.4])
    if summary_voltage is not None:
        paragraph('固定输入 '+fmt(summary_voltage,'V')+'。')
    if document is None:
        paragraph('第 2 章列端口黑盒试验，第 3 章列启动和稳态器件白盒试验，第 4 章记录模型与判定依据。', True)
        if not single_chart and evidence['cases']:
            landscape()
    chapter(2, '黑盒测试 端口性能')
    page('试验范围与执行状态')
    table(['工况','逐周期检查','环路 FRA','交叉调整率'], [
        (_case_label(c, summary['single_label_voltage']),
         '保护动作' if c.get('protection_stop') else c.get('periodicity',{}).get('reason','未完成'),
         '不适用' if c.get('fault_test') else '未选' if not settings['fra_enabled'] else
         '已复核' if c.get('loop',{}).get('available') else '待补结果',
         '不适用' if noniso or c.get('fault_test') else '待补负载范围' if plan.get('cross_skip_reason') else
         '未选' if not settings['cross_enabled'] else '完成' if c.get('cross',{}).get('complete') else
         '仿真完成，计算待补' if c.get('cross',{}).get('simulation_complete') else '待补结果')
        for c in evidence['cases']
    ], [7.0,8.0,5.0,5.8])
    if evidence.get('calculation_revision_note'):
        paragraph(evidence['calculation_revision_note'])
    if evidence.get('review_origin'):
        paragraph(evidence['review_origin'])
    if evidence.get('evidence_note'):
        paragraph(evidence['evidence_note'])
    input_count = len({case.get('voltage') for case in evidence['cases'] if not case.get('fault_test')})
    stimuli = [event for case in evidence['cases'] for event in (case.get('load_transient') or {}).get('stimulus', [])]
    step_note = ('双向阶跃在独立工况中施加 10% 与 90% 额定负载。'
                 if stimuli and all({event['before'], event['after']} == {.1, .9} for event in stimuli)
                 else '双向阶跃的负载上下限按各试验记录列示。')
    paragraph(('开机与满载稳态在固定输入执行。' if input_count == 1 else
               '额定负载开机和满载稳态在两个输入端点分别测试。')+
              step_note)
    if evidence.get('precision_summary'):
        page('计算模型修订与精度复核')
        paragraph('同一硬件、同一 LTspice 实际结果；仅重算独立预测。表中各项按原单位列出，百分偏差仍在后续完整表逐项展示。')
        table(['Vin / V','指标','修订前计算','本版计算','LTspice'],[(fmt(r['voltage']),r['metric'],fmt(r['before']),fmt(r['after']),fmt(r['simulation'])) for r in evidence['precision_summary']],[2,9,5,5,4.8])
        paragraph('高频尖峰受恒定 Coss/Cj、理想边沿和网格影响；与稳态电压、电流 RMS 分开评价。角点末段收敛不表示启动品质合格。')

    def emit_excitation(ramp, *, startup=False):
        title = 'Q1 启动励磁电流爬升' if startup else 'Q1 稳态励磁电流爬升'
        page(title)
        if not ramp.get('available'):
            paragraph(ramp.get('reason') or '本次未保存可分辨的启动原边和门极短窗。')
            return
        starts=[(row['time_s'][0]-row['turn_on_s'])*1e6 for row in ramp['segments']]
        table(['观察项目','LTspice 仿真'],[
            ('导通段峰值 / A',fmt(ramp['peak_A'])),('最小前沿排除 / ns',fmt(ramp['blank_s']*1e9)),
            ('实际爬升起点范围 / µs',fmt(min(starts))+' ～ '+fmt(max(starts))),
            ('有效导通段数',str(len(ramp['segments'])))],[1.4,1])
        paragraph(('图取启动原边峰值附近的实际开关周期。' if startup else '图取满载测量窗口内的实际开关周期。')+
                  '以门极开通为时间零点。曲线取前沿振铃之后、关断之前的原边绕组 I(LP) 样点，灰区标明最小排除时间。',True)
        chart(lambda fig:draw_excitation_ramps(fig,ramp),3.1,title)

    def emit_startup_stress(case):
        nonlocal active_box, active_topic
        active_box, active_topic = 'white', '启动过程应力'
        for subject, headers, rows, note, draw in white_startup_sections(case,flyback_ramp=flyback_ramp):
            page(subject)
            if rows:
                table(headers, rows, [1]*len(headers))
            if note:
                paragraph(note, True)
            if draw:
                chart(draw, 4.0)
        if flyback_ramp:
            emit_excitation(case.get('startup_excitation') or {},startup=True)

    for case in evidence['cases']:
        active_case=case
        active_box='black'
        active_topic='运行记录'
        title=case['id']+'  Vin '+fmt(case['voltage'],'V')
        page(title+' 运行与稳态检查')
        cache=case.get('cache',{})
        if case.get('evidence_origin'):
            paragraph(case['evidence_origin'])
        else:
            paragraph(('复用通过检查的既有仿真，原运行时间 '+cache.get('created_at','未记录')+'；本次未重新启动 LTspice。' if cache.get('hit') else '实际 LTspice 运行记录，执行时间以原证据为准。')+
                f" 原始批处理耗时 {case.get('elapsed_s',0):.1f} s；该记录的工况处理耗时 {case.get('wall_elapsed_s',0):.1f} s。")
        if not case['complete']:
            paragraph(case.get('error','工况未完成'))
            trip=case.get('protection_stop')
            if trip:
                ctrl=case['controller']
                table(['现场量','观测值'],[
                    ('瞬态记录终点',fmt(case['actual_end_s']*1000,' ms')),
                    ('首次 FAULT 动作',fmt(trip['first_trip_s']*1000,' ms')),
                    ('动作支路',trip['cause']),
                    ('触发前一周期内滤波 CS 峰值',fmt(trip.get('filtered_cs_peak_v'),' V')),
                    ('触发前一周期内原边绕组电流峰值',fmt(trip.get('primary_peak_a'),' A')),
                    ('阶跃前窗口占空比',fmt(case['measurements'].get('duty_avg'))),
                ],[14,11.8])
                if ctrl.get('SCMODE')==1:
                    paragraph('打嗝关断设定为 '+fmt(ctrl['TOFF']*1000,' ms')+'。请先核对上电时的最小导通时间、逐周期复位及磁件峰值电流。')
                data=case['startup']
                def protection_chart(fig):
                    axes=fig.subplots(1,2)
                    times=np.asarray(data['time'])*1000
                    for key in data:
                        if key.startswith('v(out'):axes[0].plot(times,data[key],label=key)
                    axes[0].set(title='保护动作前后的各路输出',xlabel='时间 / ms',ylabel='V')
                    axes[1].plot(times,data['v(fault)'],label='FAULT')
                    axes[1].plot(times,data['v(ss)'],label='SS')
                    axes[1].set(title='首次保护动作',xlabel='时间 / ms',ylabel='归一化电平',
                                xlim=(0,min(times[-1],max(trip['first_trip_s']*1600,.05))))
                    axes_format(axes)
                chart(protection_chart,2.6)
            if not case.get('fault_test'):
                emit_startup_stress(case)
            continue
        quality=case['periodicity'];ctrl=case['controller']
        paragraph('实际运行至 '+fmt(case['actual_end_s']*1000,'ms')+'。'+quality['reason']+'；脉宽范围 '+fmt(quality['duty_min']*100,'%')+' 至 '+fmt(quality['duty_max']*100,'%')+'，峰值电流周期间跨度 '+fmt(quality['peak_span_percent'],'%')+'。')
        paragraph(('QR 无固定时钟人工斜坡；' if qr else '设计斜坡 '+fmt(case['slope']['design'],'V/s')+'；实际仿真斜坡 '+fmt(case['slope']['resolved'],'V/s')+'。')+('故障测试只观察保护行为，不对标称设计判差。' if case['fault_test'] else '同一输入端点比较，非反馈路不被强制为名义电压。'))
        rows_by_subject = {subject: [] for subject in ('mos', 'diode', 'capacitor', None)}
        for row in case['rows']:
            if flyback_ramp and _full_band_q1_current(row):
                continue
            rows_by_subject[_component_subject(row['metric'])].append(row)
        main_rows = rows_by_subject[None]
        if case.get('steady_before_step'):
            steady=case['steady_before_step']
            paragraph('满载稳态测量窗口为 '+fmt(steady['window_s']*1000,'ms')+'。'+steady['reason']+'。')
        if case.get('fault_events_s'):paragraph('检测到保护触发：'+', '.join(fmt(t*1000,'ms') for t in case['fault_events_s'][:8]))
        startup = case.get('startup_window') or case.get('startup') or {}
        if case['fault_test'] and startup.get('time'):
            chart(lambda fig: startup_plot(fig, startup), 3.3, '保护工况端口与控制波形')
        topics = ('额定负载开机','满载稳压精度与纹波','双向负载阶跃','环路','交叉调整率')
        transient = case.get('load_transient') or {}
        if not case['fault_test']:
            for active_topic, (subject,headers,rows,note) in zip(topics, black_box_sections(case,settings), strict=True):
                if active_topic == '环路' and settings.get('fra_enabled') and (case.get('loop') or {}).get('simulation'):
                    continue
                page(title+' '+subject)
                if rows:
                    table(headers,rows,[1]*len(headers))
                if note:
                    paragraph(note,True)
                if active_topic == '额定负载开机' and startup.get('time'):
                    graphic_title = '额定负载启动端口波形' if case.get('startup_window') else '启动与随后运行的端口波形'
                    chart(lambda fig: startup_plot(fig, startup), 4 if 'v(input)' in startup else 3.2, graphic_title)
                if active_topic == '满载稳压精度与纹波' and case.get('switching', {}).get('time') and case.get('branches'):
                    chart(lambda fig: port_ripple(fig, case['switching'], case['branches']), 2.6, '满载端口纹波波形')
                wave = transient.get('waveform') or {}
                if active_topic == '双向负载阶跃' and wave.get('time'):
                    current = wave.get('load_current_A')
                    if current is not None and len(current):
                        paragraph(f"OUT{transient.get('feedback_output', 1)} 阶跃采用{transient.get('load_model') or '本次网表配置'}。"
                                  +f"负载电流波形范围为 {fmt(min(current), 'A')} 至 {fmt(max(current), 'A')}。", True)
                    chart(lambda fig: draw_load_step(fig, transient), 4.3, '双向阶跃负载设定与各路端口响应')
                    if transient.get('stimulus'):
                        chart(lambda fig: draw_step_edges(fig, transient), 3.5, '双向阶跃边沿局部波形')
                design = transient.get('design_step') or {}
                if active_topic == '双向负载阶跃' and design:
                    page(title+' 反馈路平均模型的负载响应')
                    if design.get('available'):
                        table(['方向','压降 / mV','过冲 / mV','恢复观察带 / mV','入带时间 / ms'],
                              [(direction,fmt(metrics['droop_V']*1e3),fmt(metrics['overshoot_V']*1e3),
                                '±'+fmt(metrics['settling_band_V']*1e3),
                                fmt(metrics['settling_s']*1e3 if metrics.get('settling_s') is not None else None))
                               for direction, metrics in (('10%→90%',design['rise']), ('90%→10%',design['fall']))],
                              [1.4,1,1,1.3,1.2])
                        paragraph(f"平均模型向反馈端口施加恒流阶跃 {fmt(design['current_low_A'], 'A')} ↔ {fmt(design['current_high_A'], 'A')}。"
                                  "上节开关仿真使用实际网表负载和电压恢复带。各自按表内口径读数。", True)
                        chart(lambda fig: design_step_plot(fig, design), 3.8, '设计计算双向恒流负载响应')
                    else:
                        paragraph(design.get('reason') or '未取得当前平均模型的时域响应。')
            emit_startup_stress(case)
            control_keys = (('v(vcc)', 'VCC'), ('v(comp)', 'COMP'), ('v(zcd)', 'ZCD'),
                            ('v(xu_ctrl:filtered)', '滤波 CS'), ('v(xu_ctrl:trip)', '限流判据'), ('v(cs)', 'CS'))
            if startup.get('time') and any(key in startup for key, _ in control_keys):
                page(title+' 启动控制信号')
                table(['信号','绘图窗最小值 / V','绘图窗最大值 / V'],
                    [(label,fmt(min(startup[key])),fmt(max(startup[key])))
                     for key,label in control_keys if key in startup and len(startup[key])], [2,1,1])
                chart(lambda fig: startup_control(fig, startup), 3.8,'启动控制信号与电流采样')
            active_box, active_topic = 'white', '稳态器件应力'
            for subject,headers,rows,note,draw in white_sections(case,flyback_ramp=flyback_ramp):
                page(title+' '+subject)
                if rows: table(headers,rows,[1]*len(headers))
                if note: paragraph(note,True)
                if draw: chart(draw,3.5)
            if flyback_ramp:
                from qr_spice_analysis import excitation_ramps
                emit_excitation(excitation_ramps(case.get('switching') or {},ctrl))
        active_box, active_topic = 'white', '开关与磁件波形'
        page(title+(' 电感电流与控制过程' if noniso else ' 原边电流与控制过程'))
        metric_table([r for r in main_rows if not r['metric'].startswith('OUT')])
        def primary(fig):
            axes=fig.subplots(2,2);data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6;design=case.get('design_switching')
            axes[0,0].plot(t,data['i(lp)'],label='LTspice 电感 L1' if noniso else 'LTspice 原边绕组')
            if design:axes[0,0].plot(t,design['i_p'],'--',label='计算 电感 L1' if noniso else '计算 原边绕组')
            axes[0,0].set(title='电感电流对比' if noniso else '原边电流对比',xlabel='时间 / μs',ylabel='A')
            cycles=quality['cycles'];x=np.arange(len(cycles))
            axes[0,1].plot(x,[100*r['duty'] for r in cycles],marker='.',lw=.7,label='每周期占空比')
            axes[0,1].set(title='QR 实际边沿占空比' if qr else '连续时钟脉宽重复性',xlabel='实际周期序号' if qr else '末段时钟序号',ylabel='占空比 / %')
            axes[1,0].plot(t,np.array(data['v(drain)'])-data['v(sense)'],label='LTspice |Vsd|（P-MOS）' if buck else 'LTspice Vds')
            axes[1,0].plot(t,np.array(data['v(gate)'])-data['v(sense)'],label='LTspice Vsg（P-MOS）' if buck else 'LTspice Vgs')
            if design:axes[1,0].plot(t,design['v_sw'],'--',label='计算 Vds 包络')
            axes[1,0].set(title='开关电压',xlabel='时间 / μs',ylabel='V')
            axes[1,1].plot(t,np.array(data['v(comp)'])-ctrl['COFF'],label='COMP − 零电流偏置')
            axes[1,1].plot(t,data['v(ramp)'],label='滤波 CS × 增益' if qr else '滤波 CS × 增益 + 人工斜坡')
            axes[1,1].set(title='实际 PWM 比较信号',xlabel='时间 / μs',ylabel='V');axes_format(axes)
        chart(primary,5.5)
        if not forward and not noniso:
            paragraph('耦合计算的原边电流取 i_primary。理想反激取开关导通电流。')
        audit=case.get('qr_current_audit')
        if qr and audit and audit.get('available'):
            page(title+' 电流测量口径与能量分项')
            paragraph(audit['scope'])
            paragraph('统计 '+str(audit['periods'])+' 个完整门极周期，时间窗 '+
                      fmt(audit['start_s']*1000,'ms')+' 至 '+fmt(audit['end_s']*1000,'ms')+
                      '，实际频率 '+fmt(audit['frequency_hz']/1000,'kHz')+'。表格不使用图中重采样数据。')
            balance=case.get('qr_charge_balance')
            if balance:
                paragraph(balance['reason']+'。各路净充放电允许值取负载电流的1%与1µA中的较大值。')
                table(['输出','绕组均值 / A','实际负载 / A','净充放电 / A','相对残差','状态'],[
                    ('OUT'+str(r['id']),fmt(r['winding_mean_A']),fmt(r['load_mean_A']),fmt(r['charging_mean_A']),
                     fmt(r['relative_percent'],'%'),'满足' if r['passed'] else '待稳态') for r in balance['rows']],
                     [2.8,4.8,4.8,4.8,4.2,3.4])
            shown=[r for r in audit['signals'] if not r['signal'].startswith('i(xq1:')]
            available=[r for r in shown if r['available']]
            table(['电流对象','平均 / A','RMS / A','最大值 / A','最小值 / A','平均功率 / W'],[
                (r['label'],fmt(r['mean_A']),fmt(r['rms_A']),fmt(r['peak_A']),fmt(r['valley_A']),
                 fmt(r.get('mean_power_W')) if 'mean_power_W' in r else '—') for r in available],
                 [8.,3.4,3.4,3.4,3.4,4.2])
            missing=[r['label'] for r in shown if not r['available'] and not r.get('raw_probe_present')]
            if missing:paragraph('未配置或本次未保存的支路：'+'、'.join(missing)+'。不将缺少探针解释为电流为零。')
            unresolved=[r['label']+'：'+r.get('reason','参考方向待核对') for r in shown if not r['available'] and r.get('raw_probe_present')]
            if unresolved:paragraph('已有探针但尚未用于电流判定：'+'；'.join(unresolved)+'。')
            paragraph('原边绕组含钳位换流与谐振电流；MOS沟道、体二极管和Coss电流各有独立路径。副边绕组电流包含整流与并联寄生支路，不能直接当作整流管导通电流。位移电流的周期平均值接近零，仍可能明显增加峰值和RMS。')
            paragraph('电容支路的平均v·i用于检查周期能量交换与数值闭合，不直接当作电容或MOS的耗散损耗；吸收电阻损耗另按i²R统计。')
            paragraph('原始 MOS 沟道和 Coss 电流保存在工程包的 comparison.json。正文的 Q1 电流使用正常导通期间的原边励磁爬升视图。')
        startup_info = case.get('qr_startup') or {}
        if rows_by_subject['mos'] or startup_info.get('vds_peak_full_v') is not None:
            page(title+' MOS 应力')
            metric_table(rows_by_subject['mos'])
            if startup_info.get('vds_peak_full_v') is not None:
                table(['指标','LTspice 仿真'], [
                    ('全程 Vds 峰值 / 时刻', fmt(startup_info['vds_peak_full_v'], 'V')+' / '+
                     fmt(startup_info['vds_peak_full_s']*1000, 'ms'))], [12.9,12.9])
        if rows_by_subject['diode'] or forward:
            page(title+' 二极管反压与电流')
            metric_table(rows_by_subject['diode'])
            if forward:
                table(['指标','LTspice 仿真'], [
                    (f"OUT{branch['id']} 续流管反压 / V",fmt(case['measurements'].get(f"out{branch['id']}_free_reverse")))
                    for branch in case.get('branches',[])
                ], [12.9,12.9])
                paragraph('续流管反压为仿真瞬态值，设计口径为稳态反压。')
        if rows_by_subject['capacitor'] or forward:
            page(title+' 电容电压与纹波')
            metric_table(rows_by_subject['capacitor'])
            ripple = []
            for branch in case.get('branches', []):
                current = branch.get('simulation_ripple') or {}
                if current:
                    label = f"OUT{branch['id']} 端口纹波电压"
                    ripple.append((label+' AC RMS / V', fmt(current.get('ac_rms'))))
                    ripple.append((label+' 峰峰值 / V', fmt(current.get('pp'))))
            if forward:
                ripple.extend((label,fmt(case['measurements'].get(key))) for label, key in [
                    ('钳位电容平均电压 / V', 'clamp_mean'),
                    ('钳位电容电压峰峰值 / V', 'clamp_ripple'),
                    ('钳位电容电流 RMS / A', 'clamp_current_rms')])
            table(['指标','LTspice 仿真'], ripple, [15.8,10.0])
        if qr:
            page(title+' QR 变频与谷底开通检查')
            model=case.get('qr_calculation_model') or {}
            if model.get('independent_winding_commutation') is False:
                paragraph('当前多路计算采用标称分配近似，未独立求解各路漏感换流；电路仿真保留完整绕组和整流支路。辅助路电流峰值与RMS的差异还包含这项模型范围差别。')
            stress_rows=[]
            if startup_info.get('available'):
                stress_rows.append((f'启动期门极上升沿前 50 ns 主反馈OUT{startup_info.get("feedback_output",1)}副边电流最大值 / 边沿时刻',
                    fmt(startup_info['max_pre_current_a'],'A')+' / '+fmt(startup_info['max_gate_rise_s']*1000,'ms')))
            for name,item in startup_info.get('windings',{}).items():
                if item.get('available'):
                    stress_rows.append((name+' 启动期门极上升沿前50 ns副边电流最大值 / 边沿时刻',
                        fmt(item['max_pre_current_a'],'A')+' / '+fmt(item['max_gate_rise_s']*1000,'ms')))
            table(['项目','测量或设计值'],[
                ('设计频率上限 / Hz',fmt(case['qr']['frequency_limit_hz'])),
                ('计算实际频率 / Hz',fmt(case['qr']['design_frequency_hz'])),
                ('仿真实际频率 均值 / 最小 / 最大 Hz',' / '.join(fmt(quality.get(k)) for k in ('frequency_mean_hz','frequency_min_hz','frequency_max_hz'))),
                ('开通前 Vds 平均值 / V',fmt(quality.get('turnon_vds_mean_v'))),
                ('关断后半段低门极期间最低 Vds 均值 / V' if quality.get('valley_window') else '旧版关断窗口最低 Vds 均值 / V',fmt(quality.get('valley_vds_mean_v'))),
                ('设计 Coss / 网表 Q1 Coss 参数 (pF)',fmt(case['qr']['design_coss_f']*1e12)+' / '+fmt(case['qr']['cds_f']*1e12)),
                ('ZCD 解析附加延时 / ns',fmt(ctrl['ZDELAY']*1e9)),
            ]+stress_rows,[13,12.8],compact=True)
            if case['qr'].get('extra_body_cj_f'):
                paragraph('此兼容网表另含 MOS 体二极管结电容 '+fmt(case['qr']['extra_body_cj_f']*1e12,' pF')+'。')
            if startup_info.get('available'):
                paragraph('门极开通前仍有较大的正向副边电流时，请同步核对对应各路 I(LSn)、ZCD 和 Vds，判断是否在退磁完成前被换流振铃触发；辅助绕组不因不是主反馈而省略检查。')
            paragraph('开通前 Vds 取门极达到切换阈值前 50 ns 的电压。'
                +('另一栏取同一关断后半段、Vgs 低于驱动幅值 10% 时实际观测到的最低 Vds。是否在自然谷底开通，还需对照门极边沿和 Vds 波形。' if quality.get('valley_window')
                else '本次存档的旧版最低值窗口可能包含前一次关断边沿，需结合波形复核。')
                +' ZCD 负载、非线性 Coss 与布局寄生需实物复核。')
            if case.get('switching',{}).get('v(zcd)') is not None:
                def qr_signals(fig):
                    axes=fig.subplots(2,1);data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6
                    axes[0].plot(t,np.array(data['v(drain)'])-data['v(sense)'],label='Vds')
                    axes[0].set(ylabel='V',title='退磁后的漏极谐振与实际开通位置')
                    for key in ('v(zcd)','v(gate)'):axes[1].plot(t,data[key],label=key)
                    axes[1].set(xlabel='时间 / μs',ylabel='V',title='ZCD 下降触发与门极脉冲');axes_format(axes)
                chart(qr_signals,2.5)
            paragraph('计算与仿真波形保留各自周期。QR 环路使用峰值电流控制的周期平均低频近似，实际时域 FRA 用于核对模型和工作点。')
            if case['qr'].get('primary_snubber_c_f'):
                page(title+' 电阻耗散')
                table(['指标','值'], [
                    ('Q1 串联 RC 吸收 R', fmt(case['qr']['primary_snubber_r_ohm'], 'Ω')),
                    ('Q1 串联 RC 吸收 C', fmt(case['qr']['primary_snubber_c_f']*1e12, 'pF')),
                    ('额定负载电阻耗散', fmt(case['measurements'].get('qr_rc_loss'), 'W'))], [15.8,10.0])
        if forward:
            page(title+' 有源钳位时序与磁复位')
            check=case.get('acf_timing',{})
            table(['核对项','LTspice 结果'],[
                ('门极交叠','未检测到' if check.get('overlap') is False else '存在／未完成'),
                ('主管开通前最小死区 / ns',fmt(check.get('main_dead_min_s')*1e9 if check.get('main_dead_min_s') is not None else None)),
                ('辅助管开通前最小死区 / ns',fmt(check.get('aux_dead_min_s')*1e9 if check.get('aux_dead_min_s') is not None else None)),
                ('励磁伏秒残差 / 等效平均 V',fmt(check.get('flux_residual_mean_v'))),
            ],[13,12.8])
            def clamp_signals(fig):
                axes=fig.subplots(1,2);d=case['switching'];t=(np.array(d['time'])-d['time'][0])*1e6
                axes[0].plot(t,np.array(d['v(gate)'])-d['v(sense)'],label='主 MOS Vgs')
                axes[0].plot(t,d['v(auxgate)'],label='P-MOS Vgs（负压开通）');axes[0].plot(t,d['v(sync)'],'--',label='SYNC 引脚')
                axes[0].set(title='两管驱动与死区',xlabel='时间 / μs',ylabel='V')
                axes[1].plot(t,np.array(d['v(drain)'])-d['v(aclamp)'],label='钳位电容电压')
                axes[1].plot(t,np.array(d['v(vin_bus)'])-d['v(drain)'],label='变压器原边电压')
                axes[1].set(title='物理钳位电容与双极性磁复位',xlabel='时间 / μs',ylabel='V');axes_format(axes)
            chart(clamp_signals,3.)
            paragraph('SYNC 高电平关断 P 管，低电平允许导通。辅助栅极采用理想电平移位。伏秒检查扣除原边 DCR 压降，积分窗口为完整 64 周期。ZVS 需结合实际驱动及结电容验证。')
        elif noniso:paragraph('L1 为物理储能／滤波电感，D1 为实际续流／整流支路；不存在变压器原副边。所有 RMS/平均值均统计完整周期。')
        for branch in case.get('branches',[]):
            i = branch['id']
            port = f'OUT{i}'
            name = branch.get('name')
            label = f'{port} {name}' if name and name != port else port
            page(f'{title} {label} ' + ('二极管电流' if noniso else '副边绕组电流'))
            metric_table([r for r in main_rows if r['metric'].startswith(f'OUT{i} ')
                          and ('电流' in r['metric'] or not (case.get('black_box') or {}).get('ports'))])
            def output(fig):
                axis=fig.subplots();data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6
                axis.plot(t,data[f'i(ls{i})'],label=f'LTspice D{i}' if noniso else f'LTspice LS{i}')
                if branch.get('design_current') is not None:axis.plot(t,branch['design_current'],'--',label='计算 二极管 D1' if noniso else '计算 副边绕组')
                axis.set(xlabel='相对时间 / μs',ylabel='电流 / A')
                axes_format([axis])
            chart(output,2.65, f'{port} 电流波形对比')
            if forward:
                page(title+f' OUT{i} 输出电感与续流回路')
                table(['指标','设计计算','LTspice'],[
                    ('输出电感 / μH',fmt(case['acf']['output_inductors_h'][i-1]*1e6),'同一电感'),
                    ('电感电流 RMS / A',fmt(branch.get('choke_design_rms')),fmt(case['measurements'].get(f'out{i}_choke_rms'))),
                    ('电感电流峰值 / A',fmt(branch.get('choke_design_peak')),fmt(case['measurements'].get(f'out{i}_choke_peak'))),
                    ('电感电流谷值 / A',fmt(branch.get('choke_design_valley')),fmt(case['measurements'].get(f'out{i}_choke_valley'))),
                ],[11,7.4,7.4])
                def choke_signals(fig):
                    axes=fig.subplots(1,2);d=case['switching'];t=(np.array(d['time'])-d['time'][0])*1e6
                    axes[0].plot(t,d[f'i(lo{i})'],label='LTspice 输出电感')
                    if branch.get('design_choke') is not None:axes[0].plot(t,branch['design_choke'],'--',label='计算 输出电感')
                    axes[0].set(title='输出电感电流',xlabel='时间 / μs',ylabel='A')
                    axes[1].plot(t,d[f'i(lo{i})'],label='电感电流')
                    axes[1].plot(t,d[f'i(ls{i})'],label='正激整流 / 绕组电流')
                    axes[1].plot(t,np.maximum(np.array(d[f'i(lo{i})'])-d[f'i(ls{i})'],0),label='续流电流近似')
                    axes[1].set(title='整流与续流电流分配',xlabel='时间 / μs',ylabel='A');axes_format(axes)
                chart(choke_signals,3.4)
                paragraph('续流电流按输出电感电流减去整流绕组电流估算。器件峰值反压待样机复核。')
        boundary=case.get('capacitor_boundary')
        if boundary and not case['fault_test']:
            page(title+' 副边电流与电容动态复算')
            if boundary.get('available'):
                paragraph('每颗并联电容分别储存电荷，并按自身 ESR 分流。复算联立绕组互感、二极管换流和电容周期电荷平衡，只使用设计参数。')
                rows=[]
                current_rows={r['metric'].replace(' ',''):r for r in case['rows']}
                for branch in case['branches']:
                    rail=branch['id']
                    supplemental=branch.get('capacitor_boundary',{})
                    for metric,key in [('平均值','average_a'),('RMS','rms_a'),('峰值','peak_a')]:
                        row=current_rows.get(f'OUT{rail}副边电流'+metric,{})
                        rows.append((f'OUT{rail}',metric,fmt(row.get('design')),fmt(supplemental.get(key)),fmt(row.get('simulation'))))
                table(['绕组','电流统计','原设计 / A','逐颗 C+ESR 复算 / A','LTspice / A'],rows,[3,4.2,5.8,6.8,6])
                shapes=[]
                for b in case['branches']:
                    shape=b.get('current_shape',{})
                    if all(shape.get(k) is not None for k in ('design_fraction','simulation_fraction')):
                        shapes.append(f"OUT{b['id']} 为 {100*shape['design_fraction']:.1f}% / {100*shape['simulation_fraction']:.1f}%")
                if shapes:
                    paragraph('在图示的五个周期中，电流超过各自正峰 5% 的时间占比（原设计 / LTspice）为 '+ '，'.join(shapes)+'。')
                paragraph('平均电流主要受负载与每周期传输电荷约束。即使平均值接近，换流时的脉冲宽度、长尾和波峰仍会影响 RMS 与峰值。')
                paragraph('复算沿用固定二极管压降与理想 Kc 钳位。实际导出的开关电路还包含 RCD 充放电、有限开关边沿及结电容。表中保留各自预测，便于判断哪些差异仍待复核。')
            else:
                paragraph('本工况未取得有效的动态复算。'+str(boundary.get('error','请查看模型适用范围。')))
        active_box, active_topic = 'black', '环路'
        if case['fault_test']:continue
        # The cover records omitted studies; quick preflight needs no empty
        # FRA/cross-regulation pages for each input endpoint.
        if not settings['fra_enabled'] and not settings['cross_enabled']:continue
        loop=case.get('loop',{})
        if settings['fra_enabled']:
            page(title+' 环路增益与裕度对比')
        if settings['fra_enabled'] and not loop.get('simulation'):
            paragraph('没有有效的开关闭环 FRA 数据：'+str(loop.get('error') or '未执行'))
        elif settings['fra_enabled']:
            sim=loop['simulation'];design=loop['design'];original=loop.get('original')
            reconstructed=loop.get('measured_reconstruction')
            paragraph(loop['definition']['method']+'。频带 '+fmt(loop['definition']['start_hz'],'Hz')+' 至 '+fmt(loop['definition']['stop_hz'],'Hz')+'。'+('半幅关键点复核通过。' if loop.get('available') else 'FRA 待复核。'+str(loop.get('error') or '')))
            if loop.get('diagnosis'):
                paragraph(loop['diagnosis'])
            def metric(data, key):
                if not data:
                    return '未取得'
                return entry(minimum_phase_margin(data) if key == 'min_pm' else data.get(key))
            table(['指标','原始计算环路','按导出参数重建','LTspice FRA'],[
                (label,*(metric(data,key) for data in (original,design['loop'],sim['loop'])))
                for label,key in [('穿越频率 / Hz','fc'),('所选穿越相位裕度 / °','pm'),
                                  ('最小相位裕度 / °','min_pm'),('增益裕度 / dB','gm_db')]]+
                [('FRA 相位裕度验收','—','—',phase_margin_conclusion(fra_phase_margin(loop)))],
                [6.6,6.4,6.4,6.4])
            if reconstructed:
                pt=reconstructed['point']
                paragraph('仿真工作点复核。Ipk '+fmt(pt['ipk'],'A')+'、频率 '+fmt(1/pt['period'],'Hz')+
                          '、电容端 '+fmt(pt['vcap'],'V')+'、输出电流校正比例 '+fmt(pt['current_scale'])+'。重建曲线用于分析差异。')
            def bode(fig):
                axes=fig.subplots(1,2)
                curves=[('实际参数的计算环路',design['loop'],'--'),('LTspice 开关闭环 FRA',sim['loop'],'-')]
                if reconstructed:curves.insert(1,('仿真稳态点重建（非独立预测）',reconstructed['loop'],'-.'))
                if original:curves.insert(0,('原始计算环路',original,':'))
                for label,data,style in curves:
                    axes[0].semilogx(data['f'],data['db'],style,label=label);axes[1].semilogx(data['f'],data['phase'],style,label=label)
                axes[0].axhline(0,c='gray',lw=.7);axes[1].axhline(-180,c='gray',lw=.7)
                axes[0].set(title='开环增益幅值',xlabel='Hz',ylabel='dB');axes[1].set(title='开环增益相位',xlabel='Hz',ylabel='deg');axes_format(axes)
            chart(bode,2.7)
            paragraph(PHASE_MARGIN_RULE+'多个 0 dB 交越取最小相位裕度。频带内未测得相位交越时，增益裕度记为待测。')
            page(title+' 功率级与补偿器频率响应')
            def components(fig):
                axes=fig.subplots(2,2)
                for j,(key,label) in enumerate((('plant','Gvc 功率级'),('compensator','Gc 补偿器'))):
                    sources=[(design,'设计点计算','--'),(sim,'LTspice FRA','-')]
                    if reconstructed:sources.insert(1,(reconstructed,'仿真稳态点重建','-.'))
                    for source,name,style in sources:
                        data=source[key];axes[j,0].semilogx(data['f'],data['db'],style,label=name);axes[j,1].semilogx(data['f'],data['phase'],style,label=name)
                    axes[j,0].set(title=label+' 幅值',xlabel='Hz',ylabel='dB');axes[j,1].set(title=label+' 相位',xlabel='Hz',ylabel='deg')
                axes_format(axes)
            chart(components,4.2)
            check=loop.get('amplitude_check')
            if check:
                checks=[(fmt(f),fmt(db),fmt(phase)) for f,db,phase in zip(check['f'],check['db_error'],check['phase_error'])]
                if len(checks)>16:page(title+' 半幅注入复核')
                middle=(len(checks)+1)//2
                paired=[(*checks[i],*(checks[i+middle] if i+middle<len(checks) else ('—','—','—'))) for i in range(middle)]
                table(['半幅频率 / Hz','Δ幅值 / dB','Δ相位 / deg']*2,paired,[4.3]*6)
            paragraph('注入点为理想隔离反馈输出至控制器输入；补偿器探针去除负反馈符号。原始与半幅工程、日志及 FRA 复数 RAW 均附于 ZIP，可在 LTspice 复核。')
        if not settings['cross_enabled']:
            continue
        active_topic = '交叉调整率'
        cross=case.get('cross',{})
        if not cross.get('supported'):
            continue
        page(title+' 交叉调整率与电压包络')
        if not cross.get('supported') or not cross.get('summary') or not cross.get('records'):
            paragraph('未取得交叉调整率结果：'+str(cross.get('error') or '未执行或不适用'))
        else:
            paragraph(cross['coverage']+'。'+cross['note'])
            if cross.get('error'):paragraph('本次角点任务未完整结束：'+str(cross['error']))
            if cross.get('design_note'):
                paragraph('计算侧采用与标称相同的完整 kij 周期解、钳位与各路电荷平衡；不拟合仿真值。电压网格与高频电流网格分别检查，电流敏感的角点仅对直流电压包络给出有效结果。模型边界见前文。' if case.get('calculation_model') else cross['design_note'])
            paragraph(f"计划 {cross.get('total_cases',len(cross['records']))} 组，实际完成 {cross.get('simulated_cases',len(cross['records']))} 组；末段收敛 {cross.get('settled_cases',sum(r['settled'] for r in cross['records']))} 组，计算解有效 {cross.get('design_valid_cases',sum(r.get('design') is not None for r in cross['records']))} 组。")
            paragraph(('计划内角点的计算与仿真均完成且收敛。' if cross['complete'] else
                '角点仿真已完成，计算对比尚不完整。' if cross.get('simulation_complete') else
                '角点计算已完成，实际仿真尚不完整。' if cross.get('design_complete') else
                '计算与仿真覆盖或收敛尚不完整。')+
                '以下仅统计各自有效的角点；重点角点和离散包络不构成连续负载区间的严格极值承诺。')
            summary=cross['summary'];rows=[]
            for calc,actual in zip(summary['design'],summary['simulation']):
                rows.append((f"OUT{calc['id']}"+(' 主反馈' if calc['feedback'] else ''),
                    fmt(calc['V_min'])+' ～ '+fmt(calc['V_max']),fmt(actual['V_min'])+' ～ '+fmt(actual['V_max']),
                    fmt(0 if calc['cross_only_pct'] is not None and abs(calc['cross_only_pct'])<1e-8 else calc['cross_only_pct']),fmt(actual['cross_only_pct']),
                    '完整' if calc['complete'] and actual['complete'] else '部分'))
            table(['输出','计算 Vmin 至 Vmax / V','仿真 Vmin 至 Vmax / V','计算交叉变化 / %','仿真交叉变化 / %','覆盖'],rows,[3.2,6,6,4,4,2.6])
            paragraph('交叉变化为固定本路负载及 Vin 时，由其余负载变化引起的最大电压跨度，占本路参考电压的比例。电压包络包含本路负载变化。')
            def cross_wave(fig):
                axis=fig.subplots();data=cross['waveform'];t=np.array(data['time'])*1000
                for key,y in data.items():
                    if key!='time':axis.plot(t,y,label=key)
                for record in cross['records']:
                    axis.axvline(record['end_s']*1000,c='gray',lw=.5,alpha=.5)
                axis.set(title='各路负载角点切换与输出平均电压的收敛过程',xlabel='时间 / ms',ylabel='V');axes_format([axis])
            if cross.get('waveform'):chart(cross_wave,2.7 if len(rows)<=3 else 2.2)
            else:paragraph('未取得角点切换过程波形；已保存的独立有效测量仍按其来源列出。')
            page(title+' 交叉调整率角点明细')
            rows=[]
            for record in cross['records']:
                vector=lambda x:' / '.join(fmt(v) for v in x) if x is not None else '未取得'
                status='收敛' if record['settled'] else record.get('error') or '未收敛'
                if record.get('retry'):status+='；独立长时间复核'
                if record.get('periodicity') and not record['periodicity']['stable']:status+='；'+record['periodicity']['reason']
                if record.get('design_error'):status+='；计算：'+record['design_error']
                if record.get('design_point',{}).get('current_mesh_verified') is False:status+='；高频电流仅参考'
                rows.append((record['id'],vector(record['powers']),vector(record.get('design')),vector(record.get('simulation')),
                    fmt(max(record.get('drift_percent',[float('nan')]))),status))
            table(['角点','OUT 顺序负载 / W','计算 OUT 顺序电压 / V','仿真 OUT 顺序电压 / V','末段漂移 / %','状态'],rows,[1.5,3.7,6.2,6.2,2,6.2])
            paragraph('最坏角点按实际测得的均值筛选。末段仍漂移的角点需延长保持时间后复核。')
            for record in cross['records']:
                if not record.get('retry'):continue
                page(title+' '+record['id']+' 独立角点复核')
                paragraph('原扫描过程保留在前图。此角点的最终均值来自独立固定负载、从零启动的长时间复核；电路、互感及控制器不变。数据与日志在 '+record['retry']['folder']+'，并未平移或修整原扫描曲线。')
                def retry_chart(fig):
                    a=fig.subplots();d=record['retry']['waveform'];t=np.array(d['time'])*1000
                    for key,y in d.items():
                        if key!='time':a.plot(t,y,label=key)
                    a.set(title='固定负载从零启动与末段收敛',xlabel='时间 / ms',ylabel='V');axes_format([a])
                chart(retry_chart,4.)
    active_case = active_module = None
    def subsection(title):
        return module_section(doc,title,level=2 if document is None else 3,new_page=False)

    def detail(title):
        return module_section(doc,title,level=3 if document is None else 4,new_page=False)

    def render_topic(box, title):
        subsection(title)
        modules = [module for module in paired_modules if module['box'] == box and module['topic'] == title]
        if modules:
            _render_endpoint_modules(doc,modules,table,paragraph,detail,
                                     fixed_voltage=fixed_voltage,show_scope=(title == '运行记录'))
        else:
            paragraph('本次未取得该试验的有效记录。')

    for topic in ('运行记录', '额定负载开机','满载稳压精度与纹波','双向负载阶跃'):
        render_topic('black', topic)
    subsection('动态稳定度')
    line = evidence.get('line_load_stability') or {}
    if line.get('complete'):
        voltage_sequence = line.get('line_plateaux_V') or line['voltages']
        paragraph('仿真输入平台为 '+' → '.join(fmt(v,'V') for v in voltage_sequence)+'。'+
                  ('检测到保护动作。' if line.get('protection') else '观察窗内未检测到保护动作。'
                   if line.get('protection') is False else '当前模型未保存保护状态。'))
        if len(set(line['voltages'])) > 1:
            paragraph('前两档输入各保持 '+fmt(line.get('input_hold_s', .5)*1000,'ms')+
                      '，返回低压后继续观察 '+fmt(line.get('tail_s', .05)*1000,'ms')+'。', True)
        schedule={s['rail']:s for s in line['schedule']}
        table(['输出','负载范围','每档停留 / ms','最低 / V','最高 / V'],
              [(f"OUT{r['rail']}",f"{schedule[r['rail']]['low_fraction']:.0%} ↔ {schedule[r['rail']]['high_fraction']:.0%}",
                schedule[r['rail']]['dwell_ms'],fmt(r['min_V']),fmt(r['max_V'])) for r in line['rows']],[1]*5)
    else:
        paragraph(line.get('error') or ('本次未取得有效的线载联合试验。' if settings.get('line_load_enabled') else '本次未启用线载联合试验。'))
    line_wave = line.get('waveform') or {}
    if line_wave.get('time'):
        chart(lambda fig: draw_line_load(fig, line_wave), 4.2, '输入电压和各路负载联合变化时的端口波形')
    elif line.get('waveform_error'):
        paragraph('波形未取得。'+str(line['waveform_error']))
    for topic in ('环路', '交叉调整率'):
        render_topic('black', topic)
    chapter(3, '白盒测试 器件应力')
    paragraph('分别列启动时间窗与满载稳态时间窗。每组位号数据和波形使用同一仿真工况。'
              '器件峰值采用原始样本，波形用于定位时序。')
    for topic in ('启动过程应力', '稳态器件应力', '开关与磁件波形'):
        render_topic('white', topic)
    chapter(4, '配置与判定依据')
    page('控制器与仿真配置')
    keys=('frequency_hz','soft_start_mode','soft_start_ms','enable_delay_ms','cs_limit','comp_offset_v',
        'ss_comp_start_v','ss_comp_end_v','short_mode','scp_threshold_v','olp_enabled','olp_ms','ocp_hold_us','hiccup_off_ms',
        'slope_mode','slope','cs_filter_ns','comp_voltage_max','fra_start_hz','fra_stop_hz','fra_oct','fra_amplitude_pct',
        'fra_cycles','cross_hold_ms','cross_mode','cycle_tolerance_pct','fra_enabled','cross_enabled')
    if qr:
        from qr_spice_settings import applicable_keys
        keys=tuple(applicable_keys('QR-FLYBACK'))
    elif forward:keys=keys+('acf_dead_ns','acf_sync_resistance')
    elif noniso:
        from qr_spice_settings import applicable_keys
        keys=tuple(applicable_keys(evidence['topology']))
    values=[]
    for key in keys:
        number=settings[key];label=CHOICES.get(key,{}).get(int(number),fmt(number))
        if key not in CHOICES and SETTINGS[key][4]:label+=' '+SETTINGS[key][4]
        values.append((SETTINGS[key][3],label))
    chunks=[values[i:i+36] for i in range(0,len(values),36)] if noniso else [values]
    for chunk_index,chunk in enumerate(chunks):
        if chunk_index:page('控制器与仿真配置续')
        if len(chunk)%2:chunk.append(('',''))
        half=len(chunk)//2
        table(['配置项','配置','配置项','配置'],[(*chunk[i],*chunk[i+half]) for i in range(half)],[6.4,6.5,6.4,6.5],compact=qr)
    if qr:
        page('QR 模型与参数来源')
        paragraph('主界面的 f_sw 是 QR 设计频率上限；导出参数 FSW 仅用于测量窗口、步长和 FRA 设置，没有固定频率振荡器。ZCD 经 RC、钳位与检测延时触发开通，CS 比较触发关断。')
        paragraph('L6565 阈值与时序取自 ST 数据手册 https://www.st.com/resource/en/datasheet/l6565.pdf。')
        for note in (evidence['cases'][0].get('approximation_notes',[]) if evidence['cases'] else []):
            paragraph(note).paragraph_format.space_after=Pt(1)
    elif noniso:
        page('Buck / Boost 控制器与计算口径')
        for note in (evidence['cases'][0].get('approximation_notes',[]) if evidence['cases'] else []):paragraph(note)
        paragraph('计算模型求解 iL(T)=iL(0) 及各颗电容的周期电荷平衡，再联立峰值比较条件。二／三型补偿在比较器指令域；实际管脚电压由明示的比例与偏置换算。输入前馈与斜坡在计算和仿真共用；并联电容的两个 ESR 状态分别保留。')
        equation(doc,'VCOMP = Voffset + ','uCS','kCOMP')
        paragraph('式中，VCOMP 为 COMP 引脚电压，Voffset 为零电流偏置，uCS 为电流比较器指令，三者均以 V 计。kCOMP 为 COMP 电压到比较器的无量纲换算增益。', True)
        equation(doc,'vL = L·','diL','dt')
        paragraph('式中，vL 为按电感电流正方向定义的端电压（V），L 为电感（H），iL 为电感电流（A），t 为时间（s）。', True)
        if buck:
            paragraph('Buck 高侧 P-MOS 波形按正幅值 Vsg 和 Vsd 对比。')
    else:
        paragraph('自动斜坡取设计设定与 0.75 倍最大副边反射下降斜率的较大值。环路同时列设计斜坡及仿真斜坡下的计算值。')
        paragraph('MP6005 参考模型在软启动期间将 COMP 上限从 1.5 V 升至 3.5 V。打嗝重启以实际观测为准。')
    if forward:
        page('有源钳位正激电路与计算口径')
        first=next((c for c in evidence['cases'] if c.get('acf')),None)
        if first:
            detail=first['acf'];hw=first.get('hardware',{})
            table(['电路项','同一套冻结硬件'],[
                ('变压器原边匝数',fmt(hw.get('Np'))),
                ('各路副边匝数',' / '.join(fmt(w['Ns']) for w in hw.get('windings',[]))),
                ('变压器励磁电感 / μH',fmt(detail['magnetizing_inductance_h']*1e6)),
                ('各路输出电感 / μH',' / '.join(fmt(x*1e6) for x in detail['output_inductors_h'])),
                ('低侧钳位电容 / nF',fmt(detail['clamp_capacitance_f']*1e9)),
                ('设计双边沿死区 / ns',fmt(detail['dead_time_s']*1e9)),
            ],[11,14.8])
        paragraph('主 N-MOS 导通时向副边传能，关断后每路输出电感通过各自的续流二极管维持电流。低侧 P-MOS 与钳位电容实现磁复位；输出电感不能当作变压器励磁电感。所有两两 kij 进入 LTspice，主副边同名端按正激方向连接。')
        equation(doc,'D≈','Np(Vout+Vf+Vblock)','Ns·Vinbus')
        equation(doc,'Vclamp≈','Vinbus','1−D')
        paragraph('式中，D 为无量纲的主开关占空比，Np、Ns 分别为原边和所选副边的匝数。Vout 为负载端口电压，Vf、Vblock 为整流和防反二极管的正向压降，Vinbus 为输入母线电压，Vclamp 为钳位电压，均以 V 计。', True)
        if first and first.get('calculation_model'):
            equation(doc,'v − R·i = L·','di','dt')
            equation(doc,'⟨iL⟩ = ','Vout','Rload')
            paragraph('式中，v 为绕组端电压向量（V），i 为按模型参考方向定义的绕组电流向量（A），R 为绕组电阻矩阵（Ω），L 为电感矩阵（H），t 为时间（s）。⟨iL⟩ 为整个周期内该路输出电感的平均电流（A），Rload 为端口负载电阻（Ω）。', True)
            paragraph('前两式仅用于预设计；正式值来自完整两两互感 MNA 周期解与各路电荷平衡，约束 i(T)=i(0)、钳位电压周期重复及单路主反馈。绕组方程还含几何 DCR 的 R·i 压降；不按功率比例分配副边电流。')
            paragraph(first['calculation_model']['assumptions'])
            paragraph('环路从同一周期解线性化，联立各路每颗 C+ESR 独立状态；共享仿真控制器的斜坡定义。高频电流网格敏感时仍可列已收敛的直流电压，但不发布该点有效裕度。')
        else:
            paragraph('上述为 CCM、固定压降和小钳位纹波近似。计算器标称工作点仍保留预设效率的等效负担；物理 SPICE 直接计算实际器件损耗，不额外乘预设效率。漏感换流会减少副边有效传能时间，轻载路还可能进入 DCM，因此不应期待各路电压、占空比和电流按理想匝比严格吻合。')
            paragraph('交叉负载表另列独立直流近似，包含 CCM/DCM、DCR 与一阶换流损失；它不是完整两两矩阵解。实际开关闭环 FRA、各支路电流和纹波分别作为验证证据，不用直流近似代替开关仿真。')
    heading = page('判定依据与证据')
    heading.paragraph_format.page_break_before = False
    equation(doc,'δ=100%×','S−C','|C|')
    paragraph('式中，δ 为相对偏差（%）。S 为仿真值，C 为设计值，两者单位见各指标栏。偏差只对同工况、同量纲且有效的非零设计基准计算。平均值、RMS 和极值优先取 .meas，纹波 AC RMS 取 RAW 时间加权积分。图为重采样概览。')
    paragraph('QR 逐周期检查以实际门极上升沿为起点，统计脉宽、频率和谷底开通电压。' if qr else '逐周期检查统计末段 64 个时钟的脉宽、峰值电流、停脉冲及周期二交替。')
    paragraph('FRA 采用时域注入，半幅复核关键频点。有效频带至 fsw/10。交叉调整率使用末段收敛、无保护的角点均值。')
    paragraph('纹波尖峰和二极管反压按各自模型并列展示，样机尖峰待测。')
    if not noniso:
        paragraph('输出和交叉调整率取防反管后端口，反馈取电容端。主反馈目标含该路固定防反压降。')
    if noniso:
        paragraph('反馈采用理想分压及二型或三型误差放大器。快速闭环省略 Coss、Cj 和门电容边沿。尖峰与开关损耗需使用完整器件模型复核。')
        paragraph('ZIP 附输入、模型、工况工程、日志、FRA RAW 和 comparison.json。')
    else:
        for text in (
            ('QR 使用 L6565 参考时序、理想 VCC 及辅助电压映射。启用耦合矩阵且变频周期有效时，交叉负载计算考虑各绕组换流、退磁和电荷平衡。环路采用低频折算。' if qr else '定频 SSR 采用 MP6005 参考时序。人工斜坡、外部 CS 滤波和 SCP 消隐使用工程设定。'),
            'MOS 使用受控开关、Ron 和等效电容。二极管使用固定 Vf 与通用结电容。磁芯采用线性模型。反向恢复、非线性、饱和及温度效应需另行评估。',
            ('正激矩阵周期解和 SPICE 均考虑 kij 与钳位。计算采用刚性电容端和理想门极边沿。' if forward else '计算与 SPICE 对输出电容变化、ESR、ESL 和开关寄生的处理不同。'),
            '隔离反馈采用理想模型。CTR、光耦与 TL431 延时以及样机 FRA 待实测。',
            'ZIP 附输入、模型、工况工程、日志、FRA RAW 和 comparison.json。'):
            paragraph(text)
    if save:
        if document is None:
            finalize_book_report(doc)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        doc.save(path)
    return doc
