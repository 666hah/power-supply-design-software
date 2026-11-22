"""Build the companion textbook from the reviewed manuscripts.

Requires python-docx, Matplotlib and Pandoc 3 on the authoring machine.
Pass --pandoc or put pandoc on PATH. Runtime help only opens the finished DOCX.
"""

import argparse
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile

from lxml import etree

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Mm, Pt, RGBColor
from matplotlib import rc_context

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docs.calculation_reference_layout import _number_formula, _set_bookmark, _toc_link
from docs.derivations.illustrations import PRINT_STYLE

TITLE = '开关电源介绍与计算方法'
REFERENCE = ROOT / 'docs/reference/计算方法与公式说明.docx'
OUTPUT = ROOT / 'docs/reference' / (TITLE + '.docx')
PARTS = (
    ('foundations', '分析基础'),
    ('power', '开关状态与周期工作点'),
    ('parts', '器件与磁件'),
    ('control', '小信号与控制系统'),
    ('verification', '场提取、系统预算与工程复核'),
)
# Consecutive related chapters may share the tail of a page when their
# introduction fits. The five part openers still begin on a new page.
CONTINUOUS_CHAPTERS = {6, 7, 8, 11, 13}
FRONT_BOOKMARK = 100
FRONT_TITLE = '拓扑与开关时序'
PLATE_ORDER = (
    'buck', 'boost', 'buck_boost', 'flyback', 'qr_flyback', 'multi_flyback',
    'acf_forward', 'multiphase_buck', 'llc_half', 'llc_full',
)


def read_manuscripts():
    blocks = []
    for filename, part in PARTS:
        path = ROOT / 'docs/derivations' / (filename + '.txt')
        lines = [line.strip() for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        if not lines or not lines[0].startswith('# '):
            raise ValueError(f'{path} 缺少章标题')
        blocks.append((part, lines))
    return blocks


def native_formulas(blocks, pandoc):
    formulas = [line[2:] for _, lines in blocks for line in lines if line.startswith('= ')]
    markdown = '\n\n'.join('$$' + formula + '$$' for formula in formulas)
    result = subprocess.run([pandoc, '-f', 'markdown+tex_math_dollars', '-t', 'docx', '-o', '-',
                             '--fail-if-warnings'], input=markdown.encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    word = Document(BytesIO(result.stdout))
    equations = word.element.body.xpath('.//m:oMath')
    if len(equations) != len(formulas):
        raise ValueError(f'原生公式转换数量不一致 {len(equations)} / {len(formulas)}')
    return iter(equations)


def ramp_figure():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib import rc_context

    with rc_context({'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
                     'axes.unicode_minus': False, 'font.size': 9}):
        figure = Figure(figsize=(6.5, 2.1))
        FigureCanvasAgg(figure)
        ax = figure.add_subplot(111)
        ax.plot([0, 0, .4, .4, 1], [0, 1, 3, 0, 0], color='#17537c', lw=2)
        ax.fill_between([0, .4], [1, 3], color='#d2e6f1')
        ax.axhline(.8, color='#985b20', lw=1, ls='--')
        ax.text(.52, .95, '整周期平均 0.800 A', color='#784518')
        ax.text(.12, .62, '导通区', color='#25536c')
        ax.text(.57, .19, '关断区', color='#53626a')
        ax.set(xlabel='归一化时间 t / T', ylabel='电流 / A', xlim=(-.015, 1.015),
               ylim=(-.08, 3.35), xticks=[0, .2, .4, .6, .8, 1], yticks=[0, 1, 2, 3])
        ax.spines[['top', 'right']].set_visible(False)
        figure.tight_layout()
        return figure


def qr_figure():
    import math
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib import rc_context

    vin, reflected, lm, ce, power = 300., 120., 800e-6, 100e-12, 100.
    wait = math.pi * math.sqrt(lm * ce)
    slope_time = lm * (1 / vin + 1 / reflected)
    peak = (power * slope_time + math.sqrt((power * slope_time)**2 + 2*lm*power*wait)) / lm
    on, demag = lm * peak / vin * 1e6, lm * peak / reflected * 1e6
    with rc_context({'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
                     'axes.unicode_minus': False, 'font.size': 8.5}):
        fig = Figure(figsize=(7.1, 2.5), layout='constrained')
        FigureCanvasAgg(fig)
        left, right = fig.subplots(1, 2, gridspec_kw={'width_ratios': [1.5, 1.]})
        left.plot([0, on, on+demag], [0, peak, 0], lw=2, color='#17537c')
        left.axvline(on, color='#688392', ls=':', lw=1)
        left.axvspan(on+demag, on+demag+wait*1e6, color='#f6d69e')
        left.set(xlim=(0, on+demag+wait*1e6), ylim=(0, 2.85), xlabel='从开通起算 / µs',
                 ylabel='折算到原边的储能电流 / A', title='开通充磁与关断传能')
        left.text(on+.6, peak, f'{peak:.2f} A')
        times = np.linspace(0, wait, 120)
        right.plot(times*1e6, vin+reflected*np.cos(times/math.sqrt(lm*ce)), lw=2, color='#985b20')
        right.axhline(vin, color='#688392', ls=':', lw=1)
        right.set(xlabel='从退磁结束起算 / µs', ylabel='理想漏源电压 / V',
                  title='展开首谷等待段', xlim=(0, wait*1e6), ylim=(160, 450))
        for axis in (left, right):
            axis.spines[['top', 'right']].set_visible(False)
        return fig


def teaching_figures():
    from docs.derivations import control_figures, device_figures, power_figures, system_figures
    from docs.derivations import (
        control_text_figures, parts_text_figures, power_text_figures, system_text_figures,
    )

    entries = {
        'ramp': (ramp_figure, '单一导通段对整周期平均值的贡献',
                 '蓝色阴影的面积等于归一化周期乘以 0.800 A。计算发热时，要先将各时刻的电流平方再积分。'),
        'qr': (qr_figure, '名义 QR 首谷周期及退磁后的自由振荡',
               '左图将励磁电流折算到原边。沿浅橙色时间段读到右图末端，可找到这个无阻尼教学模型的第一个漏源电压谷底。'),
    }
    for volume in (system_figures, power_figures, device_figures, control_figures,
                   system_text_figures, power_text_figures, parts_text_figures, control_text_figures):
        if entries.keys() & volume.FIGURES.keys():
            raise ValueError(f'重复插图标识 {volume.__name__}')
        entries.update(volume.FIGURES)
    from docs.derivations.intro_llc import LLC_CONTROL
    from docs.derivations.visio_controls import FIGURES as ELECTRICAL_CONTROL

    entries.update(ELECTRICAL_CONTROL)
    entries['ctl_llc_modulators'] = LLC_CONTROL
    return entries


def add_illustration(doc, entry, label, width_mm=174):
    draw, title, reading = entry
    with rc_context(PRINT_STYLE):
        fig = draw()
        image = BytesIO()
        fig.savefig(image, format='png', dpi=240)
        image.seek(0)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.keep_with_next = True
    pic = p.add_run().add_picture(image, width=Mm(width_mm))
    title = title.rstrip('。')
    pic._inline.docPr.set('descr', f'{title}。{reading}')
    caption = doc.add_paragraph(style='Caption')
    caption.paragraph_format.keep_together = True
    caption.paragraph_format.left_indent = Mm(4)
    caption.paragraph_format.right_indent = Mm(4)
    caption.add_run(f'{label}　{title}。').bold = True
    caption.add_run(reading)


def practice(doc, text, question):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Mm(4)
    p.paragraph_format.space_before = Pt(5 if question else 0)
    p.paragraph_format.space_after = Pt(2 if question else 6)
    p.paragraph_format.keep_with_next = question
    p.paragraph_format.keep_together = True
    tag = p.add_run('自测　' if question else '解答　')
    tag.bold = True
    tag.font.color.rgb = RGBColor.from_string('185077' if question else '087369')
    p.add_run(text)


QUANTITY_SPACE = re.compile(r'(?<=\d) (?=(?:[pnumkMGµμ]?(?:Hz|H|F|W|J|s|V|A|Ω|C|T|m)|K|°C)(?![A-Za-z]))')
SOURCE_SENTENCE = re.compile(
    r'(?:(?<=。)|^)(?:实现入口(?:为|见)|实施入口为|实现见|对应实现见|代码见|对应|见)\s*'
    r'([a-zA-Z_][^。]*[./][a-zA-Z_][^。]*。)$'
)


def add_body(doc, line, source_index, section):
    # Keep implementation-specific reasoning in place. Collect standalone
    # pointers in an appendix so the reader can follow the derivation.
    match = SOURCE_SENTENCE.search(line)
    if match:
        source_index.append((section, match.group(1).rstrip('。')))
        line = line[:match.start()]
    if line:
        p = doc.add_paragraph(QUANTITY_SPACE.sub('\u00a0', line))
        p.paragraph_format.space_after = Pt(4)
        if section.endswith('.0'):
            p.paragraph_format.keep_with_next = True


def add_book_table(doc, rows, widths):
    t = doc.add_table(rows=0, cols=len(widths))
    t.style = 'Light Shading Accent 1'
    t.autofit = False
    for index, values in enumerate(rows):
        row = t.add_row()
        props = row._tr.get_or_add_trPr()
        props.append(OxmlElement('w:cantSplit'))
        if index == 0:
            props.append(OxmlElement('w:tblHeader'))
        for cell, value in zip(row.cells, values):
            p = cell.paragraphs[0]
            p.style = 'Reference Table'
            p.add_run(value)
    for i, width in enumerate(widths):
        t.columns[i].width = Mm(width)
        for cell in t.columns[i].cells:
            cell.width = Mm(width)


def add_cover(doc):
    from docs.derivations.system_figures import flyback_ports

    doc.add_paragraph(TITLE, 'Title')
    doc.add_paragraph('电路拓扑　开关时序　设计推导', 'Subtitle')
    doc.add_paragraph('电源为什么能降压、升压或隔离供电？先看开关接通时电流走哪条路，再看关断后由哪个器件接手。卷首把各拓扑的原理图、门极信号、电压和电流放在一起。正文沿着这些波形，求出电压比、纹波、器件应力和控制环路。')
    add_illustration(doc, (flyback_ports, '三路共用一个变压器，只有一路参与稳压',
                           '反馈在第一路电容两端取样。三路电压均读在各自负载两端，对应第 4 章的 X004 工况。黑点为绕组同名端。'), '卷首图', width_mm=164)
    doc.add_paragraph('初次阅读', 'Contents Group')
    doc.add_paragraph('在卷首选一种拓扑，用笔标出电压测点和电流方向。在时序图圈出一个周期，找出驱动翻转、电感电流过零或次级开始导通的位置。第 1 章由测点和时段建立守恒方程，第 2–7 章用同样的方法读各类开关变换器。')
    doc.add_paragraph('带着设计问题阅读', 'Contents Group')
    doc.add_paragraph('电容发热，沿第 1、9 章从平方积分查到逐频分流。变压器漏感与预期不同，沿第 10、15 章把绕组几何、场能与短路测量接起来。输出加载后跌落，沿第 12 至 14 章求闭环输出阻抗，再用第 18 章的方法在波形上读取下冲和恢复时间。')
    doc.add_paragraph('配套阅读时，《计算方法与公式说明》可用来查公式，《自动计算参数依据》解释初选目标，《多路反激电源设计入门教程》给出具体操作与复算步骤。')
    doc.add_paragraph('版本依据为 2026 年 11 月的桌面设计工具与共享 Python 计算内核。算例的输入条件随正文给出。', 'Reference Note')


def add_contents(doc, groups):
    title = doc.add_paragraph('目录', 'Contents Title')
    title.paragraph_format.page_break_before = True
    add_contents_entry(doc, FRONT_TITLE, FRONT_BOOKMARK)
    i = 0
    for part, titles in groups:
        group = doc.add_paragraph(part, 'Contents Group')
        group.paragraph_format.keep_with_next = True
        for subindex, text in enumerate(titles):
            i += 1
            label = f'附录 {chr(65 + subindex)}' if part == '附录' else str(i)
            add_contents_entry(doc, f'{label}　{text}', i)


def add_contents_entry(doc, title, bookmark):
    p = doc.add_paragraph(style='Contents Entry')
    p.paragraph_format.left_indent = Mm(4)
    p.paragraph_format.tab_stops.add_tab_stop(Mm(173), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    _toc_link(p, title, f'calculation_chapter_{bookmark}')


def topology_plates():
    from docs.derivations import intro_isolated, intro_llc, intro_nonisolated

    entries = intro_nonisolated.PLATES | intro_isolated.PLATES | intro_llc.PLATES
    if set(entries) != set(PLATE_ORDER):
        raise ValueError('卷首拓扑图版与目录清单不一致')
    return [entries[key] for key in PLATE_ORDER]


def add_topology_introduction(doc, plates):
    h = doc.add_heading(FRONT_TITLE, level=1)
    h.paragraph_format.page_break_before = True
    _set_bookmark(h, FRONT_BOOKMARK)
    doc.add_paragraph('选一张电路图，先确认输入、输出和参考地，再沿导通器件找闭合回路。有隔离的电路分别使用原边和副边参考点。同一张时序图中的竖线表示同一事件，可以沿竖线从门极读到开关节点，再读电感或绕组电流。')
    for index, plate in enumerate(plates, start=1):
        add_contents_entry(doc, f'{index:02d}　{plate[0]}', FRONT_BOOKMARK+index)
    doc.add_paragraph('电路符号和观测量', 'Heading 2')
    add_book_table(doc, [
        ('对象', '读法'),
        ('连接点和同名端', '导线交会处实心点表示连接。变压器点号标在绕组旁，用于判断同向的瞬时感应电压。'),
        ('门极驱动', 'VGS 以本管源极为参考。高侧栅极和低侧栅极各使用自己的参考点。'),
        ('电压和电流', 'VDS 为漏极相对源极，桥电压按指定两个中点互减。电流以箭头方向为正。'),
        ('时序', '每张图给出一组工作条件。标明理想或简化的波形用于解释正常传能、退磁和换流。'),
    ], [42,135])
    for index, (name, intro, schematic, sch_note, timing, timing_note, chapter) in enumerate(plates, start=1):
        h = doc.add_heading(f'{index:02d}　{name}', level=2)
        h.paragraph_format.page_break_before = True
        _set_bookmark(h, FRONT_BOOKMARK+index)
        p = doc.add_paragraph(intro)
        p.paragraph_format.keep_with_next = True
        add_illustration(doc, (schematic, '功率电路与测点', sch_note), f'图 0-{2*index-1}')
        add_illustration(doc, (timing, '驱动、电压和电流的同周期对照', timing_note), f'图 0-{2*index}')
        add_contents_entry(doc, f'第 {chapter} 章　对应计算方法', chapter)


def build(reference, output, pandoc):
    blocks = read_manuscripts()
    equations = native_formulas(blocks, pandoc)
    figures = teaching_figures()
    used_figures = set()
    doc = Document(reference)
    body = doc.element.body
    for child in list(body):
        if child.tag != qn('w:sectPr'):
            body.remove(child)
    for rid, rel in list(doc.part.rels.items()):
        if rel.reltype in (RT.IMAGE, RT.HYPERLINK):
            doc.part.drop_rel(rid)
    head = doc.sections[0].header.paragraphs[0]
    head.clear()
    head.add_run('开关电源设计与环路分析　｜　' + TITLE)
    doc.core_properties.title = TITLE
    doc.core_properties.subject = '开关电源的电路拓扑、时序、控制原理和设计计算'
    doc.core_properties.author = 'szj'
    add_cover(doc)
    groups = [(part, [s[2:] for s in lines if s.startswith('# ')]) for part, lines in blocks]
    end_title = '原计算说明对照与参考资料'
    source_title = '按推导小节查找计算程序'
    add_contents(doc, [*groups, ('附录', [end_title, source_title])])
    plates = topology_plates()
    add_topology_introduction(doc, plates)
    source_index = []
    chapter = 0
    for part_number, (part, lines) in enumerate(blocks, 1):
        opener = doc.add_paragraph(f'第{"一二三四五"[part_number-1]}篇　{part}', 'Contents Group')
        opener.paragraph_format.page_break_before = True
        opener.paragraph_format.keep_with_next = True
        for line in lines:
            if line.startswith('# '):
                chapter += 1
                section = number = figure_number = 0
                h = doc.add_paragraph(f'{chapter}　{line[2:]}', 'Heading 1')
                h.paragraph_format.page_break_before = (
                    line != lines[0] and chapter not in CONTINUOUS_CHAPTERS
                )
                h.paragraph_format.space_before = Pt(16 if line == lines[0] else 24)
                _set_bookmark(h, chapter)
            elif line.startswith('## '):
                section += 1
                doc.add_heading(f'{chapter}.{section}　{line[3:]}', level=2)
            elif line.startswith('### '):
                doc.add_heading(line[4:], level=3)
            elif line.startswith('@plate '):
                index = PLATE_ORDER.index(line.removeprefix('@plate '))
                add_contents_entry(
                    doc, f'卷首原理图与时序　{plates[index][0]}', FRONT_BOOKMARK+index+1,
                )
            elif line.startswith('= '):
                number += 1
                p = doc.add_paragraph(style='Formula Display')
                p._p.append(deepcopy(next(equations)))
                _number_formula(p, chapter, number, Mm(177))
            elif line.startswith('@fig ') or line in ('@ramp', '@qr'):
                key = line.removeprefix('@fig ').removeprefix('@')
                if key in used_figures:
                    raise ValueError(f'重复插入教学图 {key}')
                figure_number += 1
                add_illustration(doc, figures[key], f'图 {chapter}-{figure_number}')
                used_figures.add(key)
            elif line.startswith('!check '):
                practice(doc, line[7:], True)
            elif line.startswith('!answer '):
                practice(doc, line[8:], False)
            elif line == '@x004':
                p = doc.add_paragraph(f'表 {chapter}-1　X004 的电荷与负载端电压回代（T = 4 µs）', 'Caption')
                p.paragraph_format.keep_with_next = True
                add_book_table(doc, [
                    ('端口', '周期电荷 / µC', '平均电流 / A', '负载 / Ω', '端电压 / V'),
                    ('OUT1', '4.00000', '1.00000', '30.000', '30.0000'),
                    ('OUT2', '0.0202057', '0.00505143', '2648.835', '13.3804'),
                    ('OUT3', '1.12206', '0.280514', '13.516', '3.79145'),
                ], [22, 42, 43, 35, 35])
            elif line.startswith('@'):
                raise ValueError('未知插图或表格标记 ' + line)
            else:
                add_body(doc, line, source_index, f'{chapter}.{section}')
    if used_figures != set(figures):
        raise ValueError(f'未排入正文的插图 {set(figures) - used_figures}')
    h = doc.add_heading(f'附录 A　{end_title}', level=1)
    h.paragraph_format.page_break_before = True
    _set_bookmark(h, chapter+1)
    doc.add_paragraph('查找同一计算量时，原说明可以按拓扑或模块查公式，本书可以按建模步骤查推导。下列章号左侧为原说明；右侧给出本书入口，章内小节可在 Word 导航窗格展开。')
    rows = [
        ('1', '端口、输入负担、斜坡面积与有效值', '1、11.6'),
        ('2', '定频 PWM 的 CCM、DCM 与临界电感', '2、3.1'),
        ('3', 'QR 首谷、周期与功率', '3.2、13.3'),
        ('4', '正激输出电感、磁复位与钳位电容', '5'),
        ('5', '时域电荷、频谱、并联电容与纹波', '1.3、9'),
        ('6', 'MOS 电压与电流、栅荷及开关损耗', '11'),
        ('7', '磁件选型、磁密、磁损与温升', '10'),
        ('8', '平均模型、采样内环与等效对象', '12、13'),
        ('9', '开环增益与裕度、K 因子整定', '14.1'),
        ('10', '运放、跨导、TL431 光耦的正反向阻容计算', '14.2–14.3'),
        ('11', '反激 RCD 的电荷、峰值与耗散', '3.3、11.4–11.5'),
        ('12', '效率曲线、参数优化、角点和阶跃估算', '11.6、17、18.2'),
        ('13', '同一硬件和报告判据', '1.1、18.3–18.4'),
        ('14', '多路整数匝比、电荷与支路功率', '4、5.3'),
        ('15', 'MP6005 原边取样、轻载能量与物理 COMP', '13.4–13.5'),
        ('16', '逐对耦合、有限漏感与周期开关过程', '4.1–4.2、11.5、15'),
        ('17', '可绕制性、实际匝长与窗口', '10.4–10.6'),
        ('18', '多路对象、共同闭环分母及扰动传递', '13.2、14.4'),
        ('19', '三路反激的逐段电荷与交叉调整率算例', '4.2–4.4'),
        ('20', 'QR 多路绕组退磁、逐路电荷和角点', '3.2、4、13.3'),
        ('21', 'COT、多相交错与均流对象', '6、13.6'),
        ('22', 'LLC 半桥与全桥、变频与混合滞环', '7、8.4、13.7'),
    ]
    doc.add_paragraph('表 A-1　原说明主题与本书推导入口', 'Caption').paragraph_format.keep_with_next = True
    add_book_table(doc, [('原说明章号', '计算对象', '本书章号'), *rows], [32, 106, 39])
    doc.add_heading('理论阅读与实现依据', level=2)
    doc.add_paragraph('Robert W. Erickson、Dragan Maksimović 著，Fundamentals of Power Electronics，第 3 版，Springer，2020。第 2、5 章讨论稳态与断续导通，第 7–9 章讨论小信号建模与控制器设计，第 10–12 章讨论磁件设计。本书采用自主编写的推导与算例，软件特有的工作点、数值约束和经验判据见各节所列实现。')
    doc.add_paragraph('DOI　10.1007/978-3-030-43881-4', 'Reference Note')
    doc.add_paragraph('控制器和磁件的器件资料可按推导主题查阅。ST 的 L6565 数据手册与应用笔记 AN1326 说明退磁检测、ZCD 及谷底时序。TI 的 SLUA535A 说明有源钳位复位，SLVA882B 讨论多相 Buck 与交错纹波，UCC256403 数据手册描述 LLC 混合滞环。onsemi 的 TND381-D 给出 TL431 和光耦补偿网络。对应的软件近似写在相应章节。')
    h = doc.add_heading(f'附录 B　{source_title}', level=1)
    h.paragraph_format.page_break_before = True
    _set_bookmark(h, chapter+2)
    doc.add_paragraph('复算时可先在正文确定端口、工况和模型，再按小节号查对应模块或函数。例如，第 4 章的换流、电荷平衡与负载组合分属不同步骤，核对时宜沿各自入口查看。')
    doc.add_paragraph('表 B-1　推导与程序入口', 'Caption').paragraph_format.keep_with_next = True
    add_book_table(doc, [('小节', '计算模块与函数'), *source_index], [23,154])
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    print(f'{output} | {chapter} chapters, {len(plates)} topology plates, '
          f'{len(used_figures)+1+2*len(plates)} illustrations')


def cache_printed_pages(output, layout_pdf):
    """Keep page references visible on first open, including in read-only viewers."""
    import pymupdf

    document = Document(output)
    paragraphs = document.paragraphs
    with pymupdf.open(layout_pdf) as pdf:
        printed = {name: page for _, name, page in pdf.get_toc()}
        page_count = len(pdf)
    pages = {}
    for p in paragraphs:
        for anchor in p._p.xpath('./w:bookmarkStart'):
            name = anchor.get(qn('w:name'))
            title = ''.join(p._p.xpath('.//w:t/text()'))
            pages[name] = printed[title]
    with ZipFile(output) as book:
        word = etree.fromstring(book.read('word/document.xml'))
        for field in word.xpath('.//w:fldSimple', namespaces=word.nsmap):
            match = re.search(r'PAGEREF\s+(\w+)', field.get(qn('w:instr'), ''))
            if match:
                for child in list(field):
                    field.remove(child)
                run, value = OxmlElement('w:r'), OxmlElement('w:t')
                value.text = str(pages[match.group(1)])
                run.append(value)
                field.append(run)
        app = etree.fromstring(book.read('docProps/app.xml'))
        app.find('{*}Pages').text = str(page_count)
        staged = output.with_suffix('.paginated.docx')
        replacements = {'word/document.xml': word, 'docProps/app.xml': app}
        with ZipFile(staged, 'w') as finished:
            for item in book.infolist():
                part = replacements.get(item.filename)
                data = book.read(item) if part is None else etree.tostring(
                    part, encoding='UTF-8', xml_declaration=True, standalone=True)
                finished.writestr(item, data)
    staged.replace(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=REFERENCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--pandoc', default=shutil.which('pandoc'))
    parser.add_argument('--cache-pages-from', type=Path, metavar='RENDERED_PDF',
                        help='从已排版的同版 PDF 写回当前 Word 的目录页码与总页数')
    args = parser.parse_args()
    if args.cache_pages_from:
        cache_printed_pages(args.output, args.cache_pages_from)
    elif not args.pandoc:
        parser.error('请用 --pandoc 指定 Pandoc 3 可执行文件')
    else:
        build(args.reference, args.output, args.pandoc)
