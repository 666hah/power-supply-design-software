"""Shared evidence-first report structure and paired endpoint presentation.

This module only projects completed snapshots. It never runs a field/circuit
solver, tunes a controller, or fills missing evidence with a different case.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from io import BytesIO
import math
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from docx_layout import paragraph, set_a4_page, table, table_gap, _font

CASE_COLORS = {'Vinmin': '2068A0', 'Vinmax': 'A46118'}
MODULES = OrderedDict([
    ('overview', '需求与共同硬件'), ('topology', '拓扑与输出架构'),
    ('power', '功率级与开关过程'), ('devices', '器件应力与损耗'),
    ('caps', '电容分流与纹波'), ('magnetics', '磁件与绕制'),
    ('loop', '环路与补偿电路'), ('clamp', '钳位与复位'),
    ('efficiency', '损耗与效率'), ('psr', '原边反馈与控制'),
    ('review', '边界与工程复核'), ('inputs', '输入参数追溯'),
    ('cross_regulation', '交叉调整率'), ('bom', '关键器件与降额'),
])
CHAPTERS = (
    ('需求与共同硬件', ('overview', 'topology')),
    ('功率级与开关过程', ('power', 'clamp')),
    ('器件选型与损耗', ('devices', 'efficiency', 'bom')),
    ('电容分流与输出纹波', ('caps',)),
    ('磁件设计与绕制', ('magnetics',)),
    ('环路与反馈补偿', ('loop', 'psr')),
    ('负载边界与交叉调整率', ('cross_regulation',)),
    ('模型边界与待闭合事项', ('review',)),
    ('输入参数与追溯', ('inputs',)),
)
_CAPTURE_WIDTH = ContextVar('report_comparison_chart_width', default=None)


def report_cases(bundle):
    """Return only the distinct design cases needed for the printed report."""
    endpoints = bundle.get('cases', [])
    by_id = {case['id']: case for case in endpoints}
    if len(endpoints) != 2 or set(by_id) != {'Vinmin', 'Vinmax'}:
        raise ValueError('输入范围报告必须包含 Vinmin 与 Vinmax 两个具名工况')
    left, right = by_id['Vinmin'], by_id['Vinmax']
    a, b = left.get('result'), right.get('result')
    if (left['voltage'] == right['voltage'] and a and b and
            not (left.get('error') or right.get('error')) and
            left.get('loop_error') == right.get('loop_error')):
        from mos_manual import distinct_endpoints
        # The solver reuses the same result or relabels just the manual MOS
        # event. Keep separate snapshots if a caller supplied different data.
        shared = a is b or (a.get('op') is not None and a['op'] is b.get('op') and
                             a.get('wf') is not None and a['wf'] is b.get('wf'))
        if shared and not distinct_endpoints(bundle.get('base_spec') or {}):
            return [left]
    return [left, right]


def case_heading(case, count):
    label = '固定输入' if count == 1 else case['id']
    return f"{label}  {case['voltage']:.8g} V"


def review_findings(cases):
    """Lead with limit violations and group the same item across endpoints."""
    from report_docx import value
    exceeded, pending = OrderedDict(), set()
    for case in cases:
        result = case.get('result') or {}
        if case.get('error') or not result:
            continue
        for item in case.get('checks') or result.get('checks') or []:
            key = item['id']
            if item['state'] == 'undefined':
                pending.add(key)
            if item['state'] != 'review':
                continue
            actual, limit = item.get('value'), item.get('limit')
            if limit is None and not key.startswith('magnetics') and key != 'loop':
                continue
            name, observations = exceeded.setdefault(key, (item['name'], []))
            if limit is None:
                detail = item.get('note') or '请核对计算条件'
            else:
                unit = item.get('unit', '')
                detail = (f"{value(actual, unit)}，要求 {item['comparison']} "
                          f"{value(limit, unit)}")
            if len(cases) > 1:
                detail = case['id']+' '+detail
            observations.append(detail)
    return [(name, '\n'.join(details)) for name, details in exceeded.values()], len(pending)


def conclusion_line(doc, text, state):
    lead = paragraph(doc, text)
    color = {'review': 'A12D24', 'undefined': '8C5D16', 'pass': '29633B'}.get(state, '000000')
    for run in lead.runs:
        _font(run, 12, True, color)
    return lead


def shared_report_images(left, right):
    return bool(left and right and left['images'] == right['images'])


def module_key(title):
    """Stable mapping of the complete legacy author's section headings."""
    if title.startswith('1.4'): return 'bom'
    if title.startswith('1.3'): return 'cross_regulation'
    if title.startswith('附录'): return 'inputs'
    if title.startswith('1.2'):
        return 'psr' if 'PSR' in title or 'MP6005' in title else 'topology'
    if title.startswith('1.1'): return 'topology'
    match = re.match(r'^(\d+)(?:[.\s]|$)', title)
    if match:
        return {'0':'topology', '1':'overview', '2':'power', '3':'devices',
                '4':'caps', '5':'magnetics', '6':'loop', '7':'clamp',
                '8':'efficiency', '9':'review'}.get(match[1])
    return None


def available_width(doc):
    sec = doc.sections[-1]
    return (sec.page_width-sec.left_margin-sec.right_margin)/914400


def module_section(doc, title, *, level=1, size=None, new_page=True):
    p = doc.add_heading(title, level)
    p.paragraph_format.page_break_before = bool(new_page)
    for run in p.runs: _font(run, size or {1:17,2:13}.get(level,11), True, heading=True)
    return p


@contextmanager
def comparison_charts(width=4.72):
    """Render graphs at their final physical width instead of shrinking text."""
    token = _CAPTURE_WIDTH.set(width)
    try: yield
    finally: _CAPTURE_WIDTH.reset(token)


def chart_size(size,draw=None):
    width = _CAPTURE_WIDTH.get()
    if getattr(draw,'__name__','')=='topology':return size
    return size if width is None else (width, min(max(size[1], 2.1), 5.0))


def prepare_chart(fig,draw=None):
    """Keep final-width plots readable, including long switching titles."""
    if _CAPTURE_WIDTH.get() is None or getattr(draw,'__name__','')=='topology':return
    def wrap(text,budget):
        lines=[]
        for source in text.replace(' · ','\n').splitlines():
            current='';used=0
            for char in source:
                weight=2 if ord(char)>255 else 1
                if current and used+weight>budget:
                    lines.append(current.strip());current='';used=0
                current+=char;used+=weight
            if current:lines.append(current.strip())
        return '\n'.join(lines)
    for ax in fig.axes:
        # The complete wire and physical-layer identities are in the adjacent
        # report tables. At final two-column width an outside legend collides
        # with the per-layer labels; keep those spatial labels on the drawing.
        if '净窗口' in ax.get_title() and ax.get_legend() is not None:
            ax.get_legend().remove()
        if ax.get_xlabel().startswith('阶段展开'):
            # Actual duration remains in the immediately following native
            # table; five stage labels plus nanoseconds cannot fit in 2 inches.
            labels=[label.get_text().splitlines()[0].replace('钳位恢复','钳位\n恢复') for label in ax.get_xticklabels()]
            if labels:
                ax.set_xticks(ax.get_xticks(),labels)
                ax.tick_params(axis='x',labelsize=6)
            ax.set_xlabel('阶段展开（非等时长；时长见分段表）',fontsize=7)
        budget=max(18,int(ax.get_position().width*fig.get_figwidth()*72/4.5))
        if ax.get_title():ax.set_title(wrap(ax.get_title(),budget),fontsize=9)
        for label in ax.get_xticklabels():
            if '\n' not in label.get_text() and len(label.get_text())>12:
                label.set_text(wrap(label.get_text(),12))


def component_check_label(check):
    """Disambiguate a blocking platform from its separately checked envelope."""
    name=check['name']
    if str(check.get('ref','')).startswith('Q'):
        if check.get('metric')=='voltage':
            return check['ref']+' MOS 阻断平台 Vds'
        if check.get('metric')=='peak':
            return check['ref']+(' MOS 钳位/峰值包络 Vds' if '稳态' in name else ' MOS 窄尖峰包络 Vds')
    return name


def _cell_text(value):
    if value is None: return '未计算'
    if isinstance(value, float):
        return f'{value:.6g}' if math.isfinite(value) else '未定义'
    return str(value)


def _records(headers, rows):
    """Unfold the author's two metric/value pairs without dropping a field."""
    result = []
    if len(rows)==1 and len(headers)>2 and headers[0] not in ('核查项','位号 / 检查项','位号','器件','参数','过程'):
        # A one-record summary uses its column headers as metric names; a
        # numerical fc or a mode string is not a stable row identifier.
        return [(str(h),_cell_text(v)) for h,v in zip(headers,rows[0])]
    repeated = len(headers) == 4 and headers[0] == headers[2] and headers[1] == headers[3]
    for row in rows:
        if repeated:
            result.extend((str(row[i]), str(row[i+1])) for i in (0,2))
        else:
            values = [(_cell_text(v)) for v in row[1:]]
            text = values[0] if len(values) == 1 else '\n'.join(
                str(h)+'  '+v for h,v in zip(headers[1:], values))
            result.append((_cell_text(row[0]), text))
    return result


def comparison_rows(headers, left_rows, right_rows):
    def keyed(rows):
        counts, output = {}, OrderedDict()
        for name, value in _records(headers, rows):
            counts[name] = counts.get(name, 0)+1
            output[name, counts[name]] = value
        return output
    left, right = keyed(left_rows), keyed(right_rows)
    return [(key[0], left.get(key, '未提供此项'), right.get(key, '未提供此项'))
            for key in dict.fromkeys([*left, *right])]


def paired_table_data(headers, left_rows, right_rows, left_label='Vinmin', right_label='Vinmax'):
    if headers[0]=='角点 / Vin' and len(headers)>=4:
        # IDs are global across Vin; the physical comparison key is the same
        # declared load vector. Retain each original ID/Vin as endpoint data.
        headers=[headers[1],headers[0],*headers[2:]]
        left_rows=[(row[1],row[0],*row[2:]) for row in left_rows]
        right_rows=[(row[1],row[0],*row[2:]) for row in right_rows]
    rows = comparison_rows(headers, left_rows, right_rows)
    output_headers=[headers[0],left_label,right_label]
    # Long thresholds/ratings are common hardware or model conditions. Give
    # them one readable column instead of repeating them in both endpoint cells.
    if headers[0] in ('核查项','位号 / 检查项') and len(headers) in (4,6):
        def keyed(values):
            counts,result={},OrderedDict()
            for row in values:
                name=row[0];counts[name]=counts.get(name,0)+1
                result[name,counts[name]]=row
            return result
        a,b=keyed(left_rows),keyed(right_rows);rows=[]
        for key in dict.fromkeys([*a,*b]):
            pair=[a.get(key),b.get(key)]
            shared=[];cells=[[],[]]
            for j in range(1,len(headers)):
                values=[_cell_text(row[j]) if row else '未提供此项' for row in pair]
                common=j in ((2,) if len(headers)==4 else (2,4)) and values[0]==values[1]
                if common:shared.append(str(headers[j])+' '+values[0])
                else:
                    for k in (0,1):cells[k].append(str(headers[j])+' '+values[k])
            rows.append((key[0],'\n'.join(shared) or '两端条件分别列示',*['\n'.join(c) for c in cells]))
        output_headers=[headers[0],'共同阈值与额定条件',left_label,right_label]
    return output_headers, rows


def add_comparison_table(doc, headers, left_rows, right_rows, *, title=None,
                         left_label='Vinmin', right_label='Vinmax'):
    if title:
        module_section(doc, title, level=2, new_page=False)
    output_headers, rows = paired_table_data(headers, left_rows, right_rows, left_label, right_label)
    width = available_width(doc)
    widths = [width*f for f in ((.22,.32,.23,.23) if len(output_headers)==4 else (.24,.38,.38))]
    endpoint_columns = (len(output_headers)-2, len(output_headers)-1)
    result = table(doc, output_headers, rows, widths)
    # Endpoint colours belong to the comparison header, not document headings.
    for index,label in zip(endpoint_columns,('Vinmin','Vinmax')):
        for run in result.rows[0].cells[index].paragraphs[0].runs:
            _font(run, 10, True, 'FFFFFF', heading=True)
        shade=result.rows[0].cells[index]._tc.get_or_add_tcPr().find(qn('w:shd'))
        if shade is not None: shade.set(qn('w:fill'), CASE_COLORS[label])
    if headers[-1] == '结论':
        for row in result.rows[1:]:
            for index in endpoint_columns:
                cell = row.cells[index]
                for line in cell.text.splitlines():
                    if line.startswith('结论 '):
                        from docx_layout import status_color
                        color = status_color(line.removeprefix('结论 '))
                        if color:
                            for run in cell.paragraphs[0].runs:
                                _font(run, 10, True, color)
                        break
    return result


def add_paired_figure(doc, left_blob, right_blob, caption, *,
                      left_label='Vinmin', right_label='Vinmax', landscape=False):
    """Compare figures at readable physical scale and show missing evidence.

    Uses the current section width. On request, temporarily uses landscape
    A4. Both supplied images are retained; no endpoint borrows the other.
    """
    from docx.enum.section import WD_SECTION_START
    if landscape:
        sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
        set_a4_page(sec, landscape=True)
    width=available_width(doc); each=width/2-.16
    grid=table(doc,[left_label,right_label],[['','']],[width/2,width/2])
    # docx_layout.table inserts a five-point spacer. The image row must stay
    # with that spacer AND its caption, otherwise Writer can orphan captions.
    spacer=grid._tbl.getnext()
    if spacer is not None and spacer.tag==qn('w:p'):
        spacer.get_or_add_pPr().append(OxmlElement('w:keepNext'))
    for index,label in enumerate(('Vinmin','Vinmax')):
        cell=grid.rows[0].cells[index]
        for run in cell.paragraphs[0].runs:
            _font(run, 10, True, 'FFFFFF', heading=True)
        shade=cell._tc.get_or_add_tcPr().find(qn('w:shd'))
        if shade is not None:shade.set(qn('w:fill'),CASE_COLORS[label])
    for i,(blob,label) in enumerate(((left_blob,left_label),(right_blob,right_label))):
        p=grid.rows[1].cells[i].paragraphs[0]
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing=1.0
        p.paragraph_format.space_before=p.paragraph_format.space_after=Pt(0)
        p.paragraph_format.keep_with_next=True
        if blob:
            run=p.add_run();run.add_picture(BytesIO(blob),width=Inches(each))
            run._r.xpath('.//wp:docPr')[0].set('descr',label+' '+caption)
        else:
            _font(p.add_run(label+' 图像未提供'),11)
    p=doc.add_paragraph(caption,'Caption');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    if landscape:
        sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
        set_a4_page(sec)
    return p


def acceptance_snapshot(p, bundle=None, *, joint_record=None, spice_evidence=None):
    from engineering_acceptance import report_snapshot
    if spice_evidence is None and isinstance(bundle,dict):
        spice_evidence=bundle.get('engineering_acceptance_evidence')
    return report_snapshot(p, range_result=bundle, joint_record=joint_record,
                           spice_evidence=spice_evidence)


_ACCEPTANCE_SOURCES = {'calculation': '计算', 'simulation': '仿真', 'measurement': '实测'}


def _acceptance_number(item, value, *, margin=False):
    from report_docx import value as engineering_value
    if isinstance(value, dict):
        value = value.get('value')
    if value is None:
        return '—'
    if item.get('metric') == 'eta':
        return engineering_value(value * 100, '个百分点' if margin else '%')
    unit = item.get('unit') or ''
    return engineering_value(value, '°' if unit == 'deg' else unit)


def _acceptance_threshold(item, values):
    relation = values.get('comparison')
    if relation == 'range' and values.get('lower') is not None and values.get('upper') is not None:
        return _acceptance_number(item, values['lower']) + ' 至 ' + _acceptance_number(item, values['upper'])
    if values.get('limit') is not None:
        return (relation or '') + ' ' + _acceptance_number(item, values['limit'])
    return '待补限值'


def acceptance_rows(snapshot):
    from engineering_acceptance import STATE_LABELS

    rows=[]
    for item in snapshot.get('rows',[]):
        varies = item.get('limits_vary')
        criterion = '分端点列示' if varies else _acceptance_threshold(item, item)
        if item.get('note'):
            criterion += '\n' + item['note']
        values=[]
        for case in ('Vinmin','Vinmax'):
            cell=(item.get('cases') or {}).get(case) or {}
            parts = ['限值 ' + _acceptance_threshold(item, cell)] if varies else []
            for source,name in _ACCEPTANCE_SOURCES.items():
                value=cell.get(source)
                state=(cell.get('states') or {}).get(source,'undefined')
                if source!='calculation' and value is None:continue
                detail = name + ' ' + _acceptance_number(item, value)
                if state in ('review','stale'):detail+='  '+STATE_LABELS[state]
                if source=='simulation' and cell.get('delta_simulation') is not None:
                    detail+='  偏差 '+_cell_text(cell['delta_simulation'])+'%'
                elif source=='measurement' and cell.get('delta_measurement') is not None:
                    detail+='  偏差 '+_cell_text(cell['delta_measurement'])+'%'
                parts.append(detail)
            parts.append('结论 '+STATE_LABELS.get(cell.get('status'),'未评估'))
            if cell.get('margin') is not None:
                parts.append('最小裕量 '+_acceptance_number(item, cell['margin'], margin=True))
            reasons = str(cell.get('reason') or '').split('；')
            parts.extend(reason for reason in reasons if reason and not reason.startswith((
                '同电压且MOS事件相同，复用 ', '同电压、同 MOS 事件，沿用 ')) and reason != '未重新仿真')
            values.append('\n'.join(parts))
        rows.append((str(item.get('name') or item.get('metric') or item.get('id')),criterion,*values))
    return rows


def missing_evidence_note(snapshot):
    evidence = [cell for row in snapshot.get('rows', []) for cell in (row.get('cases') or {}).values()]
    return '，'.join(label+'待补' for source,label in (('simulation','仿真'),('measurement','实测'))
                     if evidence and all(cell.get(source) is None for cell in evidence))


def acceptance_columns(snapshot, bundle, parameters=None):
    """Keep distinct evidence even for one calculated operating point."""
    rows = acceptance_rows(snapshot)
    endpoints = (bundle or {}).get('cases') or []
    if len(endpoints) == 2:
        same_case = len(report_cases(bundle)) == 1
    elif not endpoints and parameters:
        from input_voltage_range import normalize_input_voltage_spec
        from mos_manual import distinct_endpoints
        try:
            spec = normalize_input_voltage_spec(parameters)
        except ValueError:
            same_case = False
        else:
            same_case = spec['V_in_min'] == spec['V_in_max'] and not distinct_endpoints(spec)
    else:
        same_case = False
    if same_case and all(row[2] == row[3] for row in rows):
        for item in snapshot.get('rows', []):
            a = (item.get('cases') or {}).get('Vinmin') or {}
            b = (item.get('cases') or {}).get('Vinmax') or {}
            if (a.get('measurement_record') or b.get('measurement_record')) and (
                    a.get('measurement_record') != b.get('measurement_record')):
                break
            if any(a.get(key) != b.get(key) for key in ('calculation', 'simulation', 'measurement')):
                break
        else:
            return ['固定输入'], [row[:3] for row in rows]
    return ['Vinmin', 'Vinmax'], rows


def acceptance_sections(snapshot, rows):
    groups = snapshot.get('groups') or []
    if not groups:
        return [('', {}, rows)]
    by_group = {group['id']: [] for group in groups}
    for item, row in zip(snapshot.get('rows', []), rows):
        by_group[item['group']].append(row)
    return [(group['title'], group.get('summary') or {}, by_group[group['id']]) for group in groups]


def acceptance_group_line(snapshot):
    return '。'.join(f"{group['title']} {group['summary']['label']}"
                    for group in snapshot.get('groups') or [])


def acceptance_findings(snapshot, labels):
    """Summarize only failed acceptance comparisons using their own endpoint limits."""
    endpoints = ('Vinmin',) if len(labels) == 1 else ('Vinmin', 'Vinmax')
    findings = []
    for item in snapshot.get('rows') or []:
        details = []
        for label, case in zip(labels, endpoints):
            cell = (item.get('cases') or {}).get(case) or {}
            if cell.get('status') != 'review':
                continue
            failed = [name + ' ' + _acceptance_number(item, cell.get(source))
                      for source, name in _ACCEPTANCE_SOURCES.items()
                      if (cell.get('states') or {}).get(source) == 'review']
            threshold = _acceptance_threshold(item, cell if item.get('limits_vary') else item)
            details.append(('' if len(labels) == 1 else label + ' ')
                           + (' / '.join(failed) or '超限') + '，要求 ' + threshold)
        if details:
            findings.append((item.get('name') or item.get('metric') or item.get('id'), '\n'.join(details)))
    return findings


def add_acceptance_report(doc,p,bundle=None,*,joint_record=None,spice_evidence=None,
                          title='工程验收',short_summary=False,snapshot=None,level=1):
    if snapshot is None:
        snapshot=acceptance_snapshot(p,bundle,joint_record=joint_record,spice_evidence=spice_evidence)
    module_section(doc,title,level=level,new_page=False)
    summary=snapshot.get('summary') or {}
    labels, rows = acceptance_columns(snapshot, bundle, p)
    if summary:
        from engineering_acceptance import STATE_LABELS
        counts=summary.get('counts') or {}
        if len(labels) == 1:
            counts = {state: sum((row.get('cases') or {}).get('Vinmin', {}).get('status') == state
                                 for row in snapshot.get('rows', [])) for state in counts}
        pieces = ['总体判定 ' + str(summary.get('label') or '待评估')]
        pieces.extend(f"{STATE_LABELS.get(k,k)} {v} 项" for k,v in counts.items() if v and k != 'na')
        lead = conclusion_line(doc, '，'.join(pieces), summary.get('state'))
        lead.paragraph_format.keep_with_next = True
        if summary.get('scope'):
            paragraph(doc, summary['scope'], True)
    missing = missing_evidence_note(snapshot)
    if missing:
        note = paragraph(doc, missing, True)
        note.paragraph_format.keep_with_next = True
    for note in snapshot.get('evidence_notes') or []:
        paragraph(doc,str(note),True)
    width = available_width(doc)
    if short_summary:
        group_line = acceptance_group_line(snapshot)
        if group_line:
            paragraph(doc, group_line, True)
        if reviews := acceptance_findings(snapshot, labels):
            table(doc, ['超限项目', '当前值与限值'], reviews, [width*.33, width*.67])
    else:
        for group, group_summary, group_rows in acceptance_sections(snapshot, rows):
            if group:
                module_section(doc, group, level=level+1, new_page=False)
            if group_summary:
                lead = conclusion_line(doc, group_summary['label'], group_summary['state'])
                lead.paragraph_format.keep_with_next = True
            if group_rows:
                table(doc,['验收指标与证据','限值与依据',*labels],group_rows,
                      [width*.25,width*.24,*([width*.51/len(labels)]*len(labels))])
            else:
                paragraph(doc, '未取得适用的验收检查。')
        issues=snapshot.get('issues') or []
        if issues:
            module_section(doc,'补充记录 · 整改',level=level+1,new_page=False)
            for issue in issues:
                paragraph(doc,'；'.join(str(issue[k]) for k in ('id','title','description','effective_status','evidence') if issue.get(k)))
    return snapshot


def capture_document(doc):
    """Capture native blocks and image bytes from the complete single-case author."""
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    sections={key:OrderedDict() for key in MODULES}
    module,heading='overview','设计概览'
    for element in doc.element.body:
        block={'xml':deepcopy(element),'part':doc.part}
        if element.tag==qn('w:tbl'):
            t=Table(element,doc)
            widths=[float(c.width or 1) for c in t.columns]
            block.update(kind='table',rows=[[c.text for c in r.cells] for r in t.rows],
                         width_ratios=[w/sum(widths) for w in widths])
        elif element.tag==qn('w:p'):
            p=Paragraph(element,doc);text=p.text.strip()
            if p.style.name.startswith('Heading'):
                if text in ('当前工况完整设计核算','完整设计核算'):continue
                mapped=module_key(text)
                if mapped:module=mapped
                heading=text;sections[module].setdefault(heading,[]);continue
            if text.startswith('本部分所有参数、表格和波形对应'):continue
            images=[]
            for blip in element.xpath('.//a:blip'):
                rid=blip.get(qn('r:embed'))
                if rid:images.append(doc.part.related_parts[rid].blob)
            if images:block.update(kind='image',images=images)
            elif p.style.name=='Caption':block.update(kind='caption',text=text)
            elif element.xpath('.//m:oMath'):block.update(kind='equation',text=text)
            elif text or element.xpath('.//w:hyperlink'):block.update(kind='note',text=text)
            else:continue
        else:continue
        target_module,target_heading=module,heading
        if block['kind']=='table' and block['rows'][0][0]=='核查项':
            target_module,target_heading='review','完整设计核查明细'
        sections[target_module].setdefault(target_heading,[]).append(block)
    return sections


def block_pairs(left,right):
    def keyed(blocks):
        count,out={},OrderedDict()
        for block in blocks:
            kind=block['kind']
            key=(kind,tuple(block['rows'][0])) if kind=='table' else (kind,)
            count[key]=count.get(key,0)+1;out[key+(count[key],)]=block
        return out
    a,b=keyed(left),keyed(right)
    for key in dict.fromkeys([*a,*b]):yield a.get(key),b.get(key)


def _append_native(doc,block):
    node=deepcopy(block['xml'])
    for element in node.iter():
        for attr in (qn('r:id'),qn('r:embed'),qn('r:link')):
            rid=element.get(attr)
            if rid and rid in block['part'].rels:
                rel=block['part'].rels[rid]
                if rel.is_external:
                    new=doc.part.relate_to(rel.target_ref,rel.reltype,is_external=True)
                elif rel.reltype.endswith('/image'):
                    new,_=doc.part.get_or_add_image(BytesIO(rel.target_part.blob))
                else:continue
                element.set(attr,new)
    pictures = node.xpath('.//wp:docPr')
    if pictures:
        for number, prop in enumerate(pictures, start=doc.part.next_id):
            prop.set('id', str(number))
    # Most captured pages become flowing module sections. The QR RCD review
    # is an intentional subsection: keep its explanation and corner table on
    # a fresh page instead of leaving one final row isolated on the next page.
    if not block.get('text','').startswith('QR固定RCD：'):
        for page_break in list(node.xpath('.//w:pageBreakBefore')):
            page_break.getparent().remove(page_break)
    if block['kind']=='equation':
        count=getattr(doc,'_equation_count',0)+1;doc._equation_count=count
        labels=node.xpath('./w:r/w:t')
        if labels and re.fullmatch(r'\(\d+\)',labels[-1].text or ''):
            labels[-1].text=f'({count})'
        ppr=node.get_or_add_pPr()
        for old in list(ppr.findall(qn('w:tabs'))):ppr.remove(old)
        tabs=OxmlElement('w:tabs');stop=OxmlElement('w:tab')
        stop.set(qn('w:val'),'right');stop.set(qn('w:pos'),str(round((available_width(doc)-.1)*1440)))
        tabs.append(stop);ppr.append(tabs)
    body = doc.element.body
    if node.tag == qn('w:tbl') and len(body) > 1 and body[-2].tag == qn('w:tbl'):
        # Adjacent Word tables may merge and repeat the wrong header after a page break.
        table_gap(doc).paragraph_format.keep_with_next = True
    body.insert(len(body)-1, node)


def write_paired_modules(doc,contents,cases,*,chapter_start=2,chapter_prefix='',chapter_level=1):
    """Same module first, then both endpoints; common prose/equations once."""
    if not any(content[module] for content in contents for module in MODULES):
        return dict(paired_tables=0,paired_figures=0,chapters=0)
    single = len(cases) == 1
    if not single and doc.sections[-1].page_width < doc.sections[-1].page_height:
        from docx.enum.section import WD_SECTION_START
        sec=doc.add_section(WD_SECTION_START.NEW_PAGE)
        set_a4_page(sec, landscape=True)
    pictures=0;tables=0;chapter=chapter_start
    for name,modules in CHAPTERS:
        if not any(content[module] for content in contents for module in modules):continue
        module_section(doc,f'{chapter_prefix}{chapter} {name}',level=chapter_level,new_page=False)
        chapter+=1
        for module in modules:
            left = contents[0][module]
            right = {} if single else contents[1][module]
            for heading in dict.fromkeys([*left,*right]):
                title=re.sub(r'^(?:\d+(?:\.\d+)*\s*|附录\s*[AB]\s*)','',heading).strip()
                module_section(doc, title, level=chapter_level+1, size=13, new_page=False)
                if single:
                    for block in left[heading]:
                        _append_native(doc, block)
                        pictures += len(block.get('images', ()))
                        tables += block['kind'] == 'table'
                    continue
                pairs=list(block_pairs(left.get(heading,[]),right.get(heading,[])))
                for index,(a,b) in enumerate(pairs):
                    sample=a or b;kind=sample['kind']
                    if kind=='caption':continue
                    if kind=='image':
                        caption=next(((x or y).get('text','') for x,y in pairs[index+1:index+2]
                                      if (x or y)['kind']=='caption'),'两端点图像对照')
                        n=max(len(a['images']) if a else 0,len(b['images']) if b else 0)
                        if shared_report_images(a, b):
                            from docx_layout import figure
                            for blob in a['images']:
                                figure(doc, blob, caption, width=7.1 if caption.startswith('图 0-1') else 4.72)
                                pictures += 1
                            continue
                        for j in range(n):
                            if caption.startswith('图 0-1'):
                                # Dense circuit designators need one full-width
                                # engineering view per endpoint; a small pair
                                # would force unreadable labels. Same module,
                                # adjacent endpoint figures, all data retained.
                                from docx_layout import figure
                                for block,case in ((a,cases[0]),(b,cases[1])):
                                    label=paragraph(doc,case['id']+' '+str(case['voltage'])+' V')
                                    label.paragraph_format.keep_with_next=True
                                    if block and j<len(block['images']):
                                        figure(doc,block['images'][j],case['id']+' '+caption,width=min(8.4,available_width(doc)))
                                        pictures+=1
                                    else:paragraph(doc,'本端拓扑图未提供')
                                continue
                            add_paired_figure(doc,a['images'][j] if a and j<len(a['images']) else None,
                                b['images'][j] if b and j<len(b['images']) else None,
                                caption,left_label=cases[0]['id']+' '+str(cases[0]['voltage'])+' V',
                                right_label=cases[1]['id']+' '+str(cases[1]['voltage'])+' V')
                            pictures += int(bool(a and j < len(a['images']))) + int(bool(b and j < len(b['images'])))
                    elif kind=='table':
                        if a and b and a['rows']==b['rows']:
                            width=available_width(doc);cols=len(a['rows'][0])
                            # Common hardware/model tables appear once.
                            ratios=a.get('width_ratios') or [1/cols]*cols
                            table(doc,a['rows'][0],a['rows'][1:],[width*r for r in ratios])
                        else:
                            add_comparison_table(doc,sample['rows'][0],a['rows'][1:] if a else [],
                                                 b['rows'][1:] if b else [])
                        tables+=1
                    elif a and b and a['xml'].xml==b['xml'].xml:
                        _append_native(doc,a)
                    else:
                        # Identical equations carry independent original
                        # counters/relationships. Compare the native math XML,
                        # not a rendered plain-text transcription.
                        same_math=kind=='equation' and a and b and [x.xml for x in a['xml'].xpath('.//m:oMath')]==[x.xml for x in b['xml'].xpath('.//m:oMath')]
                        if same_math:_append_native(doc,a)
                        else:
                            for block,case in ((a,cases[0]),(b,cases[1])):
                                if block:
                                    p=doc.add_paragraph();_font(p.add_run(case['id']),9,True,CASE_COLORS[case['id']])
                                    p.paragraph_format.keep_with_next=True
                                    _append_native(doc,block)
                    if (a is None or b is None) and kind not in ('image','caption'):
                        absent=cases[0] if a is None else cases[1]
                        if absent.get('error') or not absent.get('result'):
                            paragraph(doc,absent['id']+' 本工况不可用  '+str(absent.get('error') or '没有有效计算结果'),True)
    return dict(paired_tables=tables,paired_figures=pictures,chapters=chapter-chapter_start)
