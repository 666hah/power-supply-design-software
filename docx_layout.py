"""Shared, lazy-loaded Word layout for engineering reports and the reference."""
from io import BytesIO
import re

from docx import Document
from docx.shared import Inches, Mm, Pt, RGBColor
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

LATIN_FONT = 'Cambria'
BODY_FONT = 'SimSun'
HEADING_FONT = 'Microsoft YaHei'
INK = '243547'
TABLE_HEADER = 'E5EBF2'


def _book_style(doc, name, size, *, heading=False):
    style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = doc.styles['Normal']
    _typeface(style.element.get_or_add_rPr(), size, HEADING_FONT if heading else BODY_FONT)
    style.font.size = Pt(size)
    style.font.bold = heading
    style.font.color.rgb = RGBColor.from_string('000000')
    style.paragraph_format.space_after = Pt(10 if heading else 3)
    style.paragraph_format.keep_with_next = heading
    return style


def _chapter_link(before, title, anchor, width, *, nested=False):
    entry = before.insert_paragraph_before(style='Report Contents Entry')
    if nested:
        entry.paragraph_format.left_indent = Mm(6)
    entry.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    link = OxmlElement('w:hyperlink')
    link.set(qn('w:anchor'), anchor)
    run = OxmlElement('w:r')
    label = OxmlElement('w:t')
    label.text = title
    run.append(label)
    link.append(run)
    entry._p.append(link)
    entry.add_run('\t')
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), f'PAGEREF {anchor} \\h')
    entry._p.append(field)


def _table_caption(block, doc, heading):
    """Use the data headers where they identify the table more clearly."""
    grid = Table(block, doc)
    headers = [
        ' '.join(cell.text.split()) for cell in grid.rows[0].cells
    ]
    generic = {'项目', '值', '设定', '参数', '指标', '名称', '工况', '单位', '说明', '结果', '当前值', '结论'}
    header = next((name for name in headers if name and name not in generic
                   and re.match(r'[\u4e00-\u9fff]', name)), '')
    if header and header not in heading:
        return f'{heading} · {header}' if heading else header
    return heading or '结果汇总'


def finalize_book_report(doc, *, nested_chapters_under=None):
    """Finish one assembled Word report; embedded modules keep their native blocks.

    The first page keeps the decision summary. The directory is authored
    before the first technical chapter, on the portrait side of any
    orientation transition. Chapter numbers drive all figure/table/OMML
    labels. Numbered second-level chapters under ``nested_chapters_under``
    also get their own labels and links.
    """
    if 'Report Contents Entry' in doc.styles:
        return
    chapters = [p for p in doc.paragraphs if p.style.name == 'Heading 1']
    if not chapters:
        return
    doc.styles['Title'].font.size = Pt(28)
    _typeface(doc.styles['Title'].element.get_or_add_rPr(), 28, HEADING_FONT)
    _book_style(doc, 'Report Contents Title', 20, heading=True)
    _book_style(doc, 'Report Contents Entry', 11)
    _book_style(doc, 'Report Table Caption', 9).paragraph_format.keep_with_next = True

    body = doc.element.body
    blocks = list(body)
    headings = {p._p: p for p in chapters}
    nested_prefix = re.compile(rf'^{nested_chapters_under}\.\d+\s+') if nested_chapters_under else None
    nested_headings = {p._p: p for p in doc.paragraphs
                       if nested_prefix and p.style.name == 'Heading 2' and nested_prefix.match(p.text.strip())}
    chapter_prefix = re.compile(r'^\d+\s+')
    numbered_title = re.compile(r'^\d+(?:\.\d+)*\s+')
    numbered_figure = re.compile(r'^((?:\[[^\]]+\]\s+|Vin(?:min|max)\s+)?)图\s+\d+-[\w.]+\s+')
    number, label, figure_count, table_count, formula_count = 0, '0', 0, 0, 0
    heading = '评审概览'
    links = []
    for block in blocks:
        nested = number == nested_chapters_under and block in nested_headings
        if block in headings or nested:
            p = nested_headings[block] if nested else headings[block]
            text = p.text.strip()
            if nested:
                label = text.split(maxsplit=1)[0]
            else:
                original = chapter_prefix.match(text)
                number = max(number + 1, int(original.group()) if original else 0)
                label = str(number)
            heading = numbered_title.sub('', text)
            text = f'{label} {heading}'
            # Section helpers carry direct fonts, so use the report role here.
            p.clear()
            _font(p.add_run(text), 19, True, heading=True)
            p.paragraph_format.keep_with_next = True
            index = len(links) + 1
            anchor = f'report_chapter_{index}'
            start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
            start.set(qn('w:name'), anchor)
            for marker in (start, end):
                marker.set(qn('w:id'), str(9000+index))
            p._p.insert(1, start)
            p._p.append(end)
            links.append((text, anchor, nested))
            figure_count = table_count = formula_count = 0
        elif block.tag == qn('w:tbl'):
            if block.xpath('.//w:drawing') or not block.xpath('./w:tr'):
                # Vinmin/Vinmax figures use a table as their layout container.
                continue
            table_count += 1
            caption = doc.add_paragraph(f'表 {label}-{table_count}  {_table_caption(block, doc, heading)}',
                                        style='Report Table Caption')
            block.addprevious(caption._p)
        elif block.tag == qn('w:p'):
            p = Paragraph(block, doc)
            if p.style.name.startswith('Heading'):
                heading = numbered_title.sub('', p.text.strip())
            elif p.style.name == 'Caption':
                figure_count += 1
                caption = numbered_figure.sub(r'\1', p.text.strip())
                p.clear()
                p.add_run(f'图 {label}-{figure_count}  ').bold = True
                p.add_run(caption)
            elif block.xpath('./m:oMath | ./m:oMathPara'):
                labels = block.xpath('./w:r[w:tab]/w:t')
                if labels and re.fullmatch(r'\(\d+\)', labels[-1].text or ''):
                    formula_count += 1
                    labels[-1].text = f'({label}-{formula_count})'

    before = chapters[min(1, len(chapters)-1)]
    if len(chapters) > 1:
        first = blocks.index(chapters[0]._p)
        second = blocks.index(before._p)
        for block in blocks[first+1:second]:
            if block.xpath('./w:pPr/w:sectPr'):
                before = Paragraph(block, doc)
                break
    directory = before.insert_paragraph_before('目录', 'Report Contents Title')
    directory.paragraph_format.page_break_before = len(chapters) >= 5
    sec = doc.sections[0]
    width = sec.page_width - sec.left_margin - sec.right_margin - Mm(2)
    for title, anchor, nested in links:
        _chapter_link(before, title, anchor, width, nested=nested)
    settings = doc.settings.element
    update = settings.find(qn('w:updateFields'))
    if update is None:
        update = OxmlElement('w:updateFields')
        settings.append(update)
    update.set(qn('w:val'), 'true')


def status_color(text):
    if text in ('满足', '通过', '模型内满足'):
        return '29633B'
    if text in ('需复核', '需整改', '超限', '超出限值', '不满足', '失败',
                '超过器件额定电压', '超过配置降额限值'):
        return 'A12D24'
    if text.startswith('待') or text == '未计算':
        return '8C5D16'
    return None


def _typeface(rpr, size, east_asia):
    fonts = rpr.get_or_add_rFonts()
    for attr in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme', 'csTheme'):
        fonts.attrib.pop(qn('w:'+attr), None)
    for attr in ('ascii', 'hAnsi', 'cs'):
        fonts.set(qn('w:'+attr), LATIN_FONT)
    fonts.set(qn('w:eastAsia'), east_asia)
    # The complex-script size must match the requested size for small notes.
    size_cs = rpr.find(qn('w:szCs'))
    if size_cs is None:
        size_cs = OxmlElement('w:szCs')
        rpr.append(size_cs)
    size_cs.set(qn('w:val'), str(round(size*2)))


def _font(run, size=11, bold=False, color='000000', *, heading=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    _typeface(run._element.get_or_add_rPr(), size, HEADING_FONT if heading else BODY_FONT)


def set_a4_page(section, *, landscape=False):
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = (Mm(297), Mm(210)) if landscape else (Mm(210), Mm(297))


def new_document(title, subtitle, running_title):
    from design_theme import is_pcs,report_name
    pcs = is_pcs()
    if pcs and report_name(): title='PCS 辅源设计报告 '+report_name()
    doc = Document()
    sec = doc.sections[0]
    set_a4_page(sec)
    sec.top_margin, sec.bottom_margin = Mm(18), Mm(17)
    # Preserve the 7.1-inch usable width of existing images and tables.
    sec.left_margin = sec.right_margin = Mm(14.8)
    sec.header_distance = sec.footer_distance = Mm(8)
    for name, size in [('Normal',11), ('Title',25), ('Subtitle',11),
                       ('Heading 1',17), ('Heading 2',13), ('Heading 3',11),
                       ('Caption',9), ('Header',8), ('Footer',8)]:
        s = doc.styles[name]
        heading = name == 'Title' or name.startswith('Heading')
        s.font.size, s.font.bold, s.font.italic = Pt(size), heading, False
        s.font.color.rgb = RGBColor.from_string(INK if name in ('Subtitle','Caption','Header','Footer') else '000000')
        _typeface(s.element.get_or_add_rPr(), size, HEADING_FONT if heading else BODY_FONT)
        s.paragraph_format.space_after = Pt(6)
        s.paragraph_format.line_spacing = 1.12
        s.paragraph_format.widow_control = True
        if name.startswith('Heading'):
            s.font.bold = True
            s.paragraph_format.space_before = Pt(12)
            s.paragraph_format.keep_with_next = True
    # The bundled default template can carry decorative paragraph borders.
    # Strip them explicitly rather than inheriting a rule below the title.
    for border in list(doc.styles.element.xpath('.//w:pBdr')):
        border.getparent().remove(border)
    doc.styles['Title'].paragraph_format.space_after = Pt(12)
    h = sec.header.paragraphs[0]
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT if pcs else WD_ALIGN_PARAGRAPH.RIGHT
    h.add_run(('PCS 技术货架  /  辅源工作区  /  ' if pcs else '')+running_title)
    f = sec.footer.paragraphs[0]
    f.alignment = WD_ALIGN_PARAGRAPH.RIGHT if pcs else WD_ALIGN_PARAGRAPH.CENTER
    if pcs:
        f.add_run('研发设计评审  ·  ')
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'),'PAGE')
    f._p.append(field)
    doc.core_properties.title = title
    doc.core_properties.author = 'PCS 技术货架' if pcs else '开关电源设计与环路分析工具'
    doc.core_properties.subject = '计算结果、设计核查与模型边界'
    doc.add_paragraph(title,'Title')
    doc.add_paragraph(subtitle,'Subtitle')
    return doc


def paragraph(doc, text, small=False):
    p = doc.add_paragraph()
    _font(p.add_run(text),9 if small else 11,color=INK if small else '000000')
    return p


def table_gap(doc):
    gap = doc.add_paragraph()
    gap.paragraph_format.space_before = gap.paragraph_format.space_after = Pt(0)
    gap.paragraph_format.line_spacing = Pt(5)
    _font(gap.add_run(''), 1)
    return gap


def table(doc, headers, rows, widths=None, math_columns=(), *, column_groups=()):
    """Real data tables only: fixed widths, repeated header, no split rows."""
    from design_theme import is_pcs
    pcs = is_pcs()
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    section=doc.sections[-1]
    available=(section.page_width-section.left_margin-section.right_margin)/914400
    widths = widths or [available/len(headers)]*len(headers)
    for col,w in zip(t.columns,widths):
        col.width = Inches(w)
    pr = t._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top','left','bottom','right','insideH','insideV'):
        e = OxmlElement('w:'+edge)
        for k,v in [('val','single'),('sz','4'),('color','D9D9D9')]:
            e.set(qn('w:'+k),v)
        borders.append(e)
    pr.append(borders)
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'),'fixed')
    pr.append(layout)
    groups = tuple(column_groups)
    if groups and (sum(span for _, span, _ in groups) != len(headers) or any(span < 1 for _, span, _ in groups)):
        raise ValueError('分组表头的列跨度与字段数不一致')
    header_rows = 1 + bool(groups)
    group_row = [item for label, span, _ in groups for item in [label]+['']*(span-1)]
    all_rows = ([group_row] if groups else [])+[headers]+list(rows)
    for i,vals in enumerate(all_rows):
        row = t.rows[0] if i==0 else t.add_row()
        rpr = row._tr.get_or_add_trPr()
        rpr.append(OxmlElement('w:cantSplit'))
        is_header = i < header_rows
        if is_header:
            rpr.append(OxmlElement('w:tblHeader'))
        for j,(cell,val,w) in enumerate(zip(row.cells,vals,widths)):
            cell.width = Inches(w)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp = cell._tc.get_or_add_tcPr()
            sh = OxmlElement('w:shd')
            sh.set(qn('w:fill'), ('0D1726' if pcs else TABLE_HEADER) if is_header
                   else ('F3F6FA' if pcs and i%2 else 'FFFFFF'))
            cp.append(sh)
            margins = OxmlElement('w:tcMar')
            for edge,amount in [('top',65),('bottom',65),('left',90),('right',90)]:
                e=OxmlElement('w:'+edge); e.set(qn('w:w'),str(amount)); e.set(qn('w:type'),'dxa'); margins.append(e)
            cp.append(margins)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(13.5)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
            if is_header:
                p.paragraph_format.keep_with_next = True
            if is_header or (j>0 and len(str(val))<22):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if not is_header and j in math_columns:
                from word_math import math_nodes, element
                # Exact line height clips stacked numerators/denominators.
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                math = element('oMath', *math_nodes(str(val)))
                for run in math.iter(qn('m:r')):
                    props = run.find(qn('w:rPr'))
                    if props is None:
                        props = OxmlElement('w:rPr'); run.insert(1, props)
                    size = OxmlElement('w:sz'); size.set(qn('w:val'), '20')
                    props.append(size)
                p._p.append(math)
            elif not (groups and i == 0 and val == ''):
                color = status_color(str(val)) if not is_header and headers[j] in ('结论','判定') else None
                _font(p.add_run(str(val)),10,is_header or bool(color),'FFFFFF' if is_header and pcs
                      else INK if is_header else color or '000000',heading=is_header)
    start = 0
    for _, span, fill in groups:
        cell = t.cell(0,start)
        if span > 1:
            cell = cell.merge(t.cell(0,start+span-1))
        if fill and not pcs:
            cell._tc.get_or_add_tcPr().find(qn('w:shd')).set(qn('w:fill'),fill)
            for col in range(start,start+span):
                t.cell(1,col)._tc.get_or_add_tcPr().find(qn('w:shd')).set(qn('w:fill'),fill)
        start += span
    table_gap(doc)
    return t


def figure(doc, blob, caption, width=7.1):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_after = Pt(3)
    run=p.add_run()
    run.add_picture(BytesIO(blob),width=Inches(width))
    alt = run._r.xpath('.//wp:docPr')
    if alt:
        alt[0].set('descr',caption)
    p = doc.add_paragraph(caption,'Caption')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def figure_pair(doc,left,right,caption):
    p=doc.add_paragraph()
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next=True
    for i,blob in enumerate((left,right)):
        if i: p.add_run('  ')
        run=p.add_run(); run.add_picture(BytesIO(blob),width=Inches(3.3))
        run._r.xpath('.//wp:docPr')[0].set('descr',caption+('（左）' if i==0 else '（右）'))
    p=doc.add_paragraph(caption,'Caption')
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER


def equation(doc, text, numerator=None, denominator=None):
    """Numbered structured OMML: scripts, fractions, radicals and operators."""
    from word_math import math_nodes, element
    from docx.enum.text import WD_TAB_ALIGNMENT
    p = doc.add_paragraph()
    p.paragraph_format.space_after=Pt(4)
    p.paragraph_format.line_spacing=1.0
    import re
    label = re.match(r'^(.*?[：:])\s*(.*)$', text)
    if label:
        _font(p.add_run(label[1]+' '),11)
        text=label[2]
    m=element('oMath', *math_nodes(text))
    if numerator is not None:
        m.append(element('f', element('num', *math_nodes(numerator)),
                         element('den', *math_nodes(denominator))))
    p._p.append(m)
    count=getattr(doc, '_equation_count', 0)+1
    doc._equation_count=count
    sec=doc.sections[-1]
    usable=(sec.page_width-sec.left_margin-sec.right_margin)/914400
    p.paragraph_format.tab_stops.add_tab_stop(Inches(usable-.1), WD_TAB_ALIGNMENT.RIGHT)
    _font(p.add_run(f'\t({count})'),9)
    return p


def section(doc,title):
    p=doc.add_heading(title,1)
    from design_theme import is_pcs
    p.paragraph_format.page_break_before=not is_pcs()
    return p
