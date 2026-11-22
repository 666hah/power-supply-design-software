"""Book typography and navigation for the calculation reference only."""

import re

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from word_math import element, math_nodes


LATIN = 'Cambria'
BODY = 'SimSun'
HEADING = 'Microsoft YaHei'
INK = '243547'
EQUATION_NUMBER = re.compile(r'\s*\((?:CR|QRCR)?\d+(?:-\d+)?\)\s*$')
TABLE_TITLES = {
    ('变量', '含义 / 内部单位'): '常用符号与内部单位',
    ('拓扑', 'Lmin 的软件表达式'): '各拓扑的最小电感初选值',
    ('40 W 计算示例', '输入 / 计算值'): '有源钳位正激的输入与计算值',
    ('系数', '值'): '平顶窗系数',
    ('拓扑', '主开关电压应力'): '器件电压应力的基础估算',
    ('拓扑', 'Gd0'): '低频单极点模型系数',
    ('对象', '代码中的 M₁'): '峰值电流比较器的等效斜率',
    ('对象', 'Gc0'): '峰值电流模型的直流增益与阻尼项',
    ('选择', '有限零点'): '补偿器零极点及输入项',
    ('复核步骤', '为什么需要'): '环路复核项目',
    ('检查', '本模型中“满足”的含义'): '设计报告的检查口径',
    ('Rreg+Rs 范围', '补偿跨导 / μA·mV⁻¹'): 'MP6005 线损补偿档位',
    ('项目', '本练习输入'): '算例输入条件',
    ('输出', '参考 / V'): '各路参考电压与轻重载电阻',
    ('绕组', '匝数'): '绕组几何及直流电阻',
    ('步', 'D'): '求解器的接受更新记录',
    ('最终量', '求解值'): 'X004 的最终工作点',
    ('段', '开始 / μs'): '周期内的导通段和绕组电流',
    ('段', 'OUT1 电荷 / μC'): '各导通段输送的电荷',
    ('输出', '总电荷 / μC'): '电荷平衡与输出功耗',
    ('残差项目', 'OUT1'): '周期稳态的最终残差',
    ('RL 模型损耗项目', '功率 / W'): 'RL 模型的损耗分解',
    ('角点', 'Vin / V'): '十六个角点的输出电压',
    ('输出', 'Vin / V'): '固定输入和本路负载时的分组跨度',
    ('输出', '全部角点范围 / V'): '各路全包络与纯交叉调整率',
    ('输入组', '需要的数据及含义'): '准谐振多路求解的输入',
    ('计算项目', 'Vinmin 10 V'): '四相 COT 同一硬件的两端计算结果',
    ('文件', '主要入口'): '主要计算和验证入口',
}


def _typeface(properties, east_asia, latin=LATIN):
    fonts = properties.get_or_add_rFonts()
    for key in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        fonts.attrib.pop(qn('w:' + key), None)
    for key, value in (('ascii', latin), ('hAnsi', latin), ('cs', latin), ('eastAsia', east_asia)):
        fonts.set(qn('w:' + key), value)


def _style(doc, name, size, *, face=BODY, bold=False, color='000000',
           before=0, after=0, spacing=1.17):
    styles = doc.styles
    s = styles[name] if name in styles else styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    _typeface(s.element.get_or_add_rPr(), face)
    s.font.size, s.font.bold, s.font.italic = Pt(size), bold, False
    s.font.color.rgb = RGBColor.from_string(color)
    rpr = s.element.rPr
    cs = rpr.find(qn('w:szCs'))
    if cs is None:
        cs = OxmlElement('w:szCs')
        rpr.append(cs)
    cs.set(qn('w:val'), str(round(2 * size)))
    fmt = s.paragraph_format
    fmt.space_before, fmt.space_after, fmt.line_spacing = Pt(before), Pt(after), spacing
    fmt.widow_control = True
    return s


def add_symbols(doc, *definitions):
    """Keep definitions beside their equations with the same native notation."""
    for start in range(0, len(definitions), 5):
        paragraph = doc.add_paragraph()
        paragraph.style = doc.styles['Formula Symbols']
        label = '式中　' if start == 0 else '　　　'
        paragraph.add_run(label).bold = start == 0
        for index, (symbol, meaning, unit) in enumerate(definitions[start:start + 5]):
            if index:
                paragraph.add_run('。')
            paragraph._p.append(element('oMath', *math_nodes(symbol)))
            paragraph.add_run(' 为 ' + meaning + (f'（{unit}）' if unit else ''))
        paragraph.add_run('。')
        paragraph.paragraph_format.keep_with_next = start + 5 < len(definitions)


def prepare_book(doc):
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin, section.right_margin = Mm(15), Mm(15)
    section.top_margin, section.bottom_margin = Mm(20), Mm(19)
    section.header_distance, section.footer_distance = Mm(8), Mm(8)
    section.different_first_page_header_footer = True

    _style(doc, 'Normal', 11, after=5)
    _style(doc, 'Title', 30, face=HEADING, bold=True, after=13)
    _style(doc, 'Subtitle', 13, color=INK, after=32)
    _style(doc, 'Heading 1', 20, face=HEADING, bold=True, before=21, after=13)
    _style(doc, 'Heading 2', 13, face=HEADING, bold=True, before=12, after=5)
    _style(doc, 'Heading 3', 11, face=HEADING, bold=True, before=8, after=4)
    _style(doc, 'Caption', 9, color=INK, before=2, after=8)
    _style(doc, 'Header', 9, color=INK)
    _style(doc, 'Footer', 9, color=INK)
    _style(doc, 'Formula Display', 11, before=3, after=5, spacing=1.06)
    symbols = _style(doc, 'Formula Symbols', 10.5, color=INK, after=5, spacing=1.14)
    symbols.paragraph_format.left_indent = Mm(4)
    symbols.paragraph_format.keep_together = True
    _style(doc, 'Reference Note', 10, color=INK, after=6)
    _style(doc, 'Reference Table', 10, after=0, spacing=1.12)
    _style(doc, 'Contents Title', 22, face=HEADING, bold=True, after=14)
    _style(doc, 'Contents Group', 11, face=HEADING, bold=True, color=INK, before=8, after=2)
    _style(doc, 'Contents Entry', 11, after=2)

    header = section.header.paragraphs[0]
    header.clear()
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.add_run('开关电源设计与环路分析　｜　计算方法与公式说明')
    footer = section.footer.paragraphs[0]
    footer.clear()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    settings = doc.settings.element
    update = settings.find(qn('w:updateFields'))
    if update is None:
        update = OxmlElement('w:updateFields')
        settings.append(update)
    update.set(qn('w:val'), 'true')
    doc.core_properties.subject = '开关电源的稳态、损耗、磁件与环路计算'


def _set_bookmark(paragraph, index):
    for start in paragraph._p.xpath('./w:bookmarkStart'):
        if start.get(qn('w:name'), '').startswith('calculation_chapter_'):
            ident = start.get(qn('w:id'))
            paragraph._p.remove(start)
            for end in paragraph._p.xpath('./w:bookmarkEnd'):
                if end.get(qn('w:id')) == ident:
                    paragraph._p.remove(end)
    name = f'calculation_chapter_{index}'
    start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
    start.set(qn('w:name'), name)
    for tag in (start, end):
        tag.set(qn('w:id'), str(10000 + index))
    paragraph._p.insert(1, start)
    paragraph._p.append(end)
    return name


def _toc_link(paragraph, heading, anchor):
    link = OxmlElement('w:hyperlink')
    link.set(qn('w:anchor'), anchor)
    run, text = OxmlElement('w:r'), OxmlElement('w:t')
    text.text = heading
    run.append(text)
    link.append(run)
    paragraph._p.append(link)
    paragraph.add_run('\t')
    page = OxmlElement('w:fldSimple')
    page.set(qn('w:instr'), f'PAGEREF {anchor} \\h')
    paragraph._p.append(page)


def _contents(doc, chapters):
    for paragraph in doc.paragraphs:
        if paragraph.style.name in ('Contents Title', 'Contents Group', 'Contents Entry'):
            doc.element.body.remove(paragraph._p)
    anchor = chapters[0]._p
    title = doc.add_paragraph('目录', 'Contents Title')
    title.paragraph_format.page_break_before = True
    title.paragraph_format.keep_with_next = True
    anchor.addprevious(title._p)
    groups = {
        '1': '工作点与拓扑',
        '5': '波形、损耗与磁件',
        '8': '小信号模型与补偿',
        '11': '保护、效率与设计评审',
        '14': '隔离电源与多路算例',
        '21': 'COT 控制与 LLC 谐振变换器',
        '附录 A': '附录',
    }
    for index, heading in enumerate(chapters, 1):
        key = heading.text.split('  ', 1)[0]
        if key in groups:
            group = doc.add_paragraph(groups[key], 'Contents Group')
            group.paragraph_format.keep_with_next = True
            group.paragraph_format.space_before = Pt(6)
            anchor.addprevious(group._p)
        entry = doc.add_paragraph(style='Contents Entry')
        entry.paragraph_format.left_indent = Mm(5)
        entry.paragraph_format.line_spacing = Pt(17)
        entry.paragraph_format.space_after = Pt(1)
        entry.paragraph_format.tab_stops.add_tab_stop(Mm(177), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        _toc_link(entry, heading.text, _set_bookmark(heading, index))
        anchor.addprevious(entry._p)


def _number_formula(paragraph, chapter, sequence, width):
    runs = paragraph.runs
    if runs and EQUATION_NUMBER.fullmatch(runs[-1].text):
        paragraph._p.remove(runs[-1]._r)
    paragraph.style = 'Formula Display'
    fmt = paragraph.paragraph_format
    fmt.space_before, fmt.space_after, fmt.line_spacing = None, None, None
    fmt.left_indent = Mm(4)
    fmt.keep_together = True
    fmt.tab_stops.clear_all()
    fmt.tab_stops.add_tab_stop(width - Mm(5), WD_TAB_ALIGNMENT.RIGHT)
    label = paragraph.add_run(f'\t({chapter}-{sequence})')
    label.font.size = Pt(9)
    label.font.color.rgb = RGBColor.from_string(INK)


def _number_caption(paragraph, prefix):
    original = paragraph.text
    paragraph.clear()
    paragraph.add_run(prefix + '　').bold = True
    paragraph.add_run(original)


def finish_book(doc):
    """Style the generated chapters, including worked-example insertions."""
    paragraphs = doc.paragraphs
    chapters = [p for p in paragraphs if p.style.name == 'Heading 1']
    width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin
    chapter, sequence, table_sequence, figure_sequence = '', 0, 0, 0
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    previous = None
    for block in list(doc.iter_inner_content()):
        if isinstance(block, Paragraph) and block.style.name == 'Heading 1':
            chapter = block.text.split('  ', 1)[0].removeprefix('附录 ')
            table_sequence, figure_sequence = 0, 0
        elif isinstance(block, Table):
            table_sequence += 1
            if not (isinstance(previous, Paragraph) and previous.text.startswith('表 ')):
                columns = tuple(cell.text for cell in block.rows[0].cells[:2])
                caption = doc.add_paragraph(TABLE_TITLES[columns], 'Caption')
                _number_caption(caption, f'表 {chapter}-{table_sequence}')
                caption.paragraph_format.keep_with_next = True
                block._tbl.addprevious(caption._p)
        elif isinstance(block, Paragraph) and block.style.name == 'Caption' and not block.text.startswith('表 '):
            figure_sequence += 1
            if not block.text.startswith('图 '):
                _number_caption(block, f'图 {chapter}-{figure_sequence}')
        previous = block

    paragraphs = doc.paragraphs
    chapter = ''
    for index, p in enumerate(paragraphs):
        name = p.style.name
        for run in p.runs:
            props = run._element.rPr
            if props is not None and not run._element.xpath('.//w:drawing'):
                # Retain emphasis. Inherit size and color from the book style.
                for child in ('rFonts', 'sz', 'szCs', 'color', 'i'):
                    item = props.find(qn('w:' + child))
                    if item is not None:
                        props.remove(item)
        if name == 'Title':
            p.paragraph_format.space_before = Pt(115)
        elif name == 'Heading 1':
            chapter = p.text.split('  ', 1)[0].removeprefix('附录 ')
            sequence = 0
            p.paragraph_format.page_break_before = chapter in ('1', '5', '8', '11', '14', '19', '20', '21', '22', 'A', 'B')
        elif name == 'Heading 2':
            p.paragraph_format.page_break_before = False
        elif chapter and name != 'Formula Symbols' and p._p.xpath('./m:oMath'):
            sequence += 1
            _number_formula(p, chapter, sequence, width)
        if name == 'Formula Symbols' and index and paragraphs[index - 1].style.name == 'Formula Display':
            paragraphs[index - 1].paragraph_format.keep_with_next = True

    for table in doc.tables:
        total = sum(column.width for column in table.columns)
        if total > width:
            for column in table.columns:
                column.width = int(column.width * width / total)
                for cell in column.cells:
                    cell.width = column.width
        for row_index, row in enumerate(table.rows):
            for cell in row.cells:
                shade = cell._tc.tcPr.find(qn('w:shd'))
                if shade is not None:
                    shade.set(qn('w:fill'), 'E5EBF2' if row_index == 0 else 'FFFFFF')
                for p in cell.paragraphs:
                    p.style = 'Reference Table'
                    p.paragraph_format.line_spacing = None
                    for run in p.runs:
                        _typeface(run._element.get_or_add_rPr(), BODY)
                        run.font.color.rgb = RGBColor(0, 0, 0)
    for shape in doc.inline_shapes:
        if shape.width > width:
            shape.height = int(shape.height * width / shape.width)
            shape.width = width
    _contents(doc, chapters)
