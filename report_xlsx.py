"""Module-per-sheet Excel reports for the same two solved input endpoints.

Reuses the existing engineering-report authoring path in memory, so the Excel
and Word versions cannot drift to different loss, ripple or compensation
formulas. No intermediate Word file is written. Only the final XLSX is saved.
"""
from collections import OrderedDict
import math
import re

from xlsx_report_writer import (Sheet, WIDTHS, SIDE_PX, fitted_height,
                                numeric_text, number_format, save_workbook)
from report_architecture import (acceptance_columns, acceptance_snapshot, block_pairs,
                                 case_heading, missing_evidence_note, paired_table_data, report_cases, review_findings,
                                 shared_report_images)


MODULES = OrderedDict([
    ('overview', '01 需求与工况总览'), ('topology', '02 拓扑与多路输出'),
    ('power', '03 功率级与开关波形'), ('devices', '04 功率器件与损耗'),
    ('caps', '05 电容纹波'), ('magnetics', '06 磁件与绕制'),
    ('loop', '07 环路与补偿电路'), ('clamp', '08 钳位与复位'),
    ('efficiency', '09 损耗与效率'), ('psr', '10 MP6005 PSR'),
    ('review', '11 模型与评审'), ('inputs', '12 输入参数快照'),
    ('cross_regulation', '13 交叉调整率'),
    ('bom', '14 关键器件BOM与降额'),
])


def _module(title):
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


def _math_text(element):
    """Readable equation descriptions, not misleading executable cell formulas."""
    local = element.tag.rsplit('}',1)[-1]
    children = {child.tag.rsplit('}',1)[-1]:child for child in element}
    def part(name):
        child = children.get(name)
        return '' if child is None else _math_text(child)
    def property_value(group, name, default):
        properties = children.get(group)
        if properties is not None:
            for child in properties:
                if child.tag.rsplit('}',1)[-1] == name:
                    return next((v for k,v in child.attrib.items() if k.endswith('}val')),default)
        return default
    if local in ('t',): return element.text or ''
    if local == 'f': return '('+part('num')+')/('+part('den')+')'
    if local == 'sSub': return part('e')+'_{'+part('sub')+'}'
    if local == 'sSup': return part('e')+'^('+part('sup')+')'
    if local == 'sSubSup': return part('e')+'_{'+part('sub')+'}^('+part('sup')+')'
    if local == 'd':
        expressions = [_math_text(child) for child in element if child.tag.rsplit('}',1)[-1] == 'e']
        return property_value('dPr','begChr','(')+property_value('dPr','sepChr',',').join(expressions)+property_value('dPr','endChr',')')
    if local == 'nary':
        return (property_value('naryPr','chr','∑')+('_{'+part('sub')+'}' if part('sub') else '')
                +('^('+part('sup')+')' if part('sup') else '')+' '+part('e'))
    if local == 'rad':
        return ('root['+part('deg')+']' if part('deg') else 'sqrt')+'('+part('e')+')'
    return ''.join(_math_text(child) for child in element if not child.tag.endswith('Pr'))


def _capture_document(doc):
    """Extract ordered content blocks without rasterizing tables or equations."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    sections = {key:OrderedDict() for key in MODULES}
    module, section = 'overview', '设计概览'
    def add(block):
        sections[module].setdefault(section, []).append(block)
    for element in doc.element.body:
        if element.tag == qn('w:tbl'):
            t = Table(element, doc)
            add(dict(kind='table', rows=[[c.text for c in row.cells] for row in t.rows]))
            continue
        if element.tag != qn('w:p'): continue
        p = Paragraph(element, doc)
        text = p.text.strip()
        if p.style.name.startswith('Heading'):
            if text == '当前工况完整设计核算': continue
            new_module = _module(text)
            if new_module is not None: module = new_module
            section = text
            sections[module].setdefault(section, [])
        elif p.style.name == 'Caption':
            add(dict(kind='caption', text=text))
        elif element.xpath('.//m:oMath'):
            equations = '； '.join(_math_text(e) for e in element.xpath('.//m:oMath'))
            lead = re.sub(r'\s*\(\d+\)\s*$', '', text).strip()
            add(dict(kind='equation', text=(lead+' ' if lead else '')+equations))
        elif element.xpath('.//a:blip'):
            pictures = []
            for blip in element.xpath('.//a:blip'):
                rid = blip.get(qn('r:embed'))
                if rid: pictures.append(doc.part.related_parts[rid].blob)
            if pictures: add(dict(kind='image', images=pictures))
        elif text:
            if text.startswith('本部分所有参数、表格和波形对应'): continue
            text = text.replace('上述为原生 Word 数学对象。', '上述为公式文本；Word 报告使用原生数学对象。')
            add(dict(kind='note', text=text))
        else:
            # Hyperlink-only paragraphs (for example the PSR source link).
            link_text = ''.join(element.xpath('.//w:hyperlink//w:t/text()'))
            if link_text: add(dict(kind='note', text=link_text))
    return sections


def _spans(count):
    # Every report table currently has at most eight columns. Never silently
    # omit data if a future module exceeds the reserved comparison-panel width.
    if not 1 <= count <= 8:
        raise ValueError(f'Excel 报告表格有 {count} 列，需调整模块布局后导出')
    if count == 2: return [3,5]
    if count == 3: return [3,2,3]
    if count == 4: return [2,2,2,2]
    result = [1]*count
    result[0] += 8-count
    return result


def _state_style(text):
    if any(term in text for term in ('需复核','需整改','超限','超出限值','不满足','失败')):
        return 10
    if any(term in text for term in ('待','未计算','未评估','失效')):
        return 8
    if text in ('满足','通过','模型内满足') or '结论 满足' in text:
        return 11
    return None


def _write_block(sheet, row, offset, block, label, columns=8):
    kind = block['kind']
    if kind == 'table':
        spans = _spans(len(block['rows'][0]))
        if len(block['rows'][0])==5 and block['rows'][0][1]=='直流范围 / V':
            spans=[1,2,2,1,2]
        if columns==17:
            spans=[2*span for span in spans]
            spans[0]+=1
        for i, values in enumerate(block['rows']):
            col = offset
            for j, (text, span) in enumerate(zip(values, spans)):
                value, fmt = (str(text), None) if i == 0 else numeric_text(text)
                header = block['rows'][0][j]
                style = (3 if label == 'Vinmax' or header == 'Vinmax' else 2) if i == 0 else (6 if i%2 else 0)
                if i and (header.endswith('结论') or header in ('固定输入','Vinmin','Vinmax')):
                    status = _state_style(str(text))
                    if status is not None:
                        style = status
                sheet.span(row+i, col, span, value, style, fmt)
                width = sum(WIDTHS[col:col+span])
                height = fitted_height(text, width)
                sheet.heights[row+i] = max(sheet.heights.get(row+i,24),height)
                col += span
        return len(block['rows'])+1
    if kind == 'image':
        blobs = block['images']
        available = SIDE_PX*1.4 if columns==17 and block.get('topology') else SIDE_PX
        width = (available-12*(len(blobs)-1))/len(blobs)
        height = max(sheet.image(row,offset,blob,label+' 工程图',width,index*(width+12))
                     for index, blob in enumerate(blobs))
        rows = math.ceil((height+12)/32)
        for r in range(row,row+rows): sheet.heights[r] = max(sheet.heights.get(r,24),24)
        return rows
    text = block.get('text','')
    style = 4 if kind == 'caption' else 9 if kind == 'equation' else 7
    sheet.span(row, offset, columns, text, style)
    height = fitted_height(text, sum(WIDTHS[offset:offset+columns]))
    sheet.heights[row] = max(sheet.heights.get(row,24),height)
    return 2


def _shared_block(left, right):
    if not left or not right:
        return False
    kind = left['kind']
    if kind == 'image':
        return shared_report_images(left, right)
    if kind == 'table':
        return left['rows'] == right['rows']
    return left.get('text') == right.get('text')


def _headers(sheet, cases, note):
    sheet.heights.update({1:12, 2:34, 3:36, 4:30})
    sheet.span(2,0,sheet.column_count,sheet.name,1)
    sheet.span(3,0,sheet.column_count,note,7)
    for offset, case in zip((0,9),cases):
        text = case_heading(case, len(cases))
        if case.get('error') or not case.get('result'): text += '  计算不可用'
        sheet.span(4,offset,8,text,2 if offset == 0 else 3)


def export_input_range_xlsx(path, range_result, *, compensation_state=None,
                            mos_real_time=False, comparison=None, corners=None,
                            tolerance_result=None):
    """Write an offline XLSX report; never change parameters or auto-tune.

    Worksheets display each distinct input operating point once.
    The workbook is a report snapshot, not a second implementation of the
    switching solver. Graphs and mathematical descriptions use the Word
    report's exact source. Numeric single quantities remain numeric in Excel.
    """
    cases = report_cases(range_result)
    endpoints = range_result['cases']
    single = len(cases) == 1
    column_count = 8 if single else 17
    from docx import Document
    from report_docx import export_design_docx
    from input_range_report import _metrics, METRICS, _worse
    content, details = [], []
    for case in cases:
        if case.get('error') or not case.get('result'):
            content.append({key:OrderedDict() for key in MODULES}); continue
        res = case['result']; doc = Document()
        details.append(export_design_docx('',case['p'],res['op'],res['wf'],res,
            models=case.get('models'),loop_error=case.get('loop_error'),
            corners=case.get('corners') or (corners if case['id']=='Vinmin' else None),
            comparison=comparison if case['id']=='Vinmin' else None,
            mos_real_time=mos_real_time,efficiency_curve=case.get('efficiency_curve'),
            compensation_state=compensation_state,document=doc,save=False,include_conclusion=False))
        content.append(_capture_document(doc))
        del doc
    fixed = bool(range_result.get('fixed_hardware',range_result.get('hardware')))
    common = '固定输入，列出一次计算结果。' if single else '左侧 Vinmin，右侧 Vinmax。'
    common += '磁件待核对。' if not fixed else '' if single else '两端采用同一套磁件与补偿。'
    if not single and cases[0]['voltage'] == cases[1]['voltage'] and len(details) == 2:
        common += '输入电压相同，各工况结果分别列出。'
    acceptance=acceptance_snapshot(range_result['base_spec'],range_result)
    evidence_labels, evidence_rows = acceptance_columns(acceptance, range_result)
    evidence_width = 8 if len(evidence_labels) == 1 else 17
    acceptance_sheet=Sheet('00 工程验收', column_count=evidence_width)
    _headers(acceptance_sheet,cases,common)
    summary=acceptance.get('summary') or {}
    findings, pending = review_findings(cases)
    failure_lines = [case['id']+' 求解失败 '+str(case.get('error') or '无结果')
                     for case in endpoints if case.get('error') or not case.get('result')]
    conclusion = [f"工程验收 {summary.get('label','待评估')}",
                  f"重点复核 {len(findings)} 项，待补数据 {pending} 项", *failure_lines]
    missing = missing_evidence_note(acceptance)
    if missing:
        conclusion.append(missing)
    cross = range_result.get('cross_regulation') or {}
    if cross.get('supported') and not cross.get('complete'):
        conclusion.append('交叉调整率部分角点待核对。')
    summary_style = 10 if findings or failure_lines or summary.get('state')=='review' else 11 if summary.get('state')=='pass' else 8
    summary_text = '\n'.join(conclusion)
    acceptance_sheet.span(5,0,evidence_width,summary_text,summary_style)
    acceptance_sheet.heights[5]=fitted_height(summary_text,sum(WIDTHS[:evidence_width]))
    row=7
    if findings:
        row += _write_block(acceptance_sheet,row,0,dict(kind='table',
            rows=[['优先复核','当前值与要求'],*findings[:5]]),'共同',evidence_width)
    if evidence_rows:
        row += _write_block(acceptance_sheet,row,0,dict(kind='table',
            rows=[['验收指标','需求阈值',*evidence_labels],*evidence_rows]),'共同',evidence_width)
    for note in acceptance.get('evidence_notes') or []:
        acceptance_sheet.span(row,0,evidence_width,str(note),7)
        acceptance_sheet.heights[row]=max(30,fitted_height(note,sum(WIDTHS[:evidence_width])))
        row+=2
    sheets = [acceptance_sheet]
    if tolerance_result is not None:
        from tolerance_report import TITLE, report_sections, result_summary, result_notes

        sheet = Sheet(TITLE, column_count=17)
        notes = result_notes(tolerance_result)
        _headers(sheet, cases, result_summary(tolerance_result))
        row = 6
        for note in notes:
            row += _write_block(sheet, row, 0, dict(kind='note', text=note), '共同', 17)
        for title, headers, data, _ in report_sections(tolerance_result):
            sheet.span(row, 0, 17, title, 4)
            row += 2
            row += _write_block(sheet, row, 0, dict(kind='table', rows=[headers, *data]), '共同', 17)
        sheets.append(sheet)
    for module, name in MODULES.items():
        left = content[0][module]
        right = {} if single else content[1][module]
        if module != 'overview' and not left and not right: continue
        sheet = Sheet(name, column_count=column_count)
        _headers(sheet,cases,common)
        row, page_start = 6, 6
        if module == 'overview':
            metrics = [_metrics(case) for case in cases]
            for index, (key,label,unit,scale,direction) in enumerate(METRICS):
                vals = [m.get(key) for m in metrics]
                worse = _worse(*vals, direction) if not single else ''
                sheet.heights[row] = 30
                for side, value in enumerate(vals):
                    offset = side*9
                    sheet.span(row,offset,4,label,6 if index%2 else 0)
                    valid = value is not None and math.isfinite(float(value))
                    numeric = value if valid else '未定义'
                    fmt = number_format(value,unit) if valid else None
                    sheet.span(row,offset+4,2,numeric,6 if index%2 else 0,fmt if valid else None)
                    sheet.span(row,offset+6,2,'较不利端' if worse == cases[side]['id'] else worse if worse in ('两端相同','未完整计算') else '',7)
                row += 1
            row += 2
        for title in dict.fromkeys([*left,*right]):
            # Keep corresponding subsection starts at identical vertical rows.
            if sum(sheet.heights.get(r,24) for r in range(page_start,row)) > 520:
                sheet.breaks.append(row); page_start=row
            sheet.span(row,0,column_count,title,4)
            sheet.heights[row]=30; row+=2
            for a,b in block_pairs(left.get(title,[]),right.get(title,[])):
                if single or _shared_block(a,b):
                    block = a or b
                    # The topology caption and drawing describe the shared circuit.
                    if block['kind']=='image' and title.startswith('0 '):
                        block = dict(block, topology=True)
                    row += _write_block(sheet,row,0,block,'固定输入' if single else '共同',column_count)
                    continue
                if a and b and a['kind']=='table' and a['rows'][0][0]=='位号 / 检查项':
                    headers, rows = paired_table_data(a['rows'][0],a['rows'][1:],b['rows'][1:])
                    row += _write_block(sheet,row,0,dict(kind='table',rows=[headers,*rows]),'共同',column_count)
                    continue
                used=0
                for side, block in enumerate((a,b)):
                    if block:
                        used=max(used,_write_block(sheet,row,side*9,block,cases[side]['id']))
                row+=used
        for side,case in enumerate(cases):
            if case.get('error') or not case.get('result'):
                sheet.span(5,side*9,8,'本工况计算不可用：'+str(case.get('error') or '没有有效结果'),8)
                sheet.heights[5]=max(sheet.heights.get(5,24),fitted_height(str(case.get('error','')),100))
        sheets.append(sheet)
    save_workbook(path,sheets)
    failed=[case['id'] for case in endpoints if case.get('error') or not case.get('result')]
    cross = range_result.get('cross_regulation')
    cross_incomplete = bool(cross and cross.get('supported') and not cross.get('complete'))
    return dict(path=str(path),case_count=2,successful_cases=2-len(failed),failed_cases=failed,
                displayed_case_count=len(cases),
                incomplete=bool(failed) or not fixed or cross_incomplete,hardware_fixed=fixed,
                cross_regulation_complete=cross.get('complete') if cross else None,
                acceptance_summary=acceptance.get('summary'),
                sheet_count=len(sheets),sheet_names=[sheet.name for sheet in sheets],
                figure_count=sum(len(sheet.images) for sheet in sheets),
                check_count=sum(detail['checks'] for detail in details))
