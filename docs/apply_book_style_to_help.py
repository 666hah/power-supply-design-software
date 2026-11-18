"""Apply the technical book style to the tutorial and automatic-design guide."""

import argparse
from copy import deepcopy
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs.calculation_reference_layout import (
    BODY, TABLE_TITLES, _number_caption, _number_formula, _set_bookmark, _toc_link,
    _typeface, add_symbols, prepare_book,
)
import word_math as wm


CHAPTER = re.compile(r'^(\d+|附录 [A-Z])\s+')
LEGACY_LABEL = re.compile(r'\s*\((?:练习)?\d+\)\s*$')
HELP_TABLE_TITLES = {
    ('项目', '本例输入'): '主反馈路与变压器的设计输入',
    ('输出', '参考电压'): '三路输出的负载设定',
    ('前缀', '倍率'): '单位前缀与换算示例',
    ('理想量', '20 V 输入'): '理想模型的占空比与导通时间',
    ('理想手算结果', '20 V 输入'): '理想模型的电流计算结果',
    ('MOS 电压量', '20 V 输入'): '主开关电压应力',
    ('按该端点初算', '20 V 输入'): '输入边界的 RCD 初选参数',
    ('导入入口', 'X 轴'): 'MOSFET 曲线的横纵轴',
    ('事件', '电流 A'): '两种输入工况的四个开关事件',
    ('阶段', '物理含义'): 'MOSFET 开关过程分段',
    ('时间', '20 V 输入'): '开关分段时间',
    ('Q1 损耗', '20 V 输入'): '主开关的损耗分项',
    ('参数', '计算值'): '补偿电路的元件参数',
    ('回代频率', '目标'): '补偿电路的零极点回代结果',
}

# A group follows the last equation introducing its terms.
BASIS_SYMBOLS = {
    2: ('Lmin=', (
        ('ΔIL、Iout', '目标电感峰峰值纹波、额定输出电流', 'A'),
        ('Lmin', '满足目标纹波的电感下限', 'H'),
        ('Vout、Vhigh', '输出电压、最高输入电压', 'V'),
        ('fs', '开关频率', 'Hz'),
    )),
    4: ('Cstep≥', (
        ('Ccharge、Cstep', '稳态充放电与负载阶跃分别给出的容量下限', 'F'),
        ('ΔVc、ΔVlim', '分配给电容量的纹波预算、负载阶跃允许的输出跌落', 'V'),
        ('ΔIstep', '最小负载至额定负载的电流差', 'A'),
    )),
    5: ('Cin≥', (
        ('Cin、ΔVin', '输入侧容量下限、分配给输入电容充放电的纹波预算', 'F、V'),
        ('Dstar', '在输入范围内使 D(1−D) 最大的占空比', '1'),
    )),
    7: ('RCS≤', (
        ('Rdc、Rcs', '电感直流电阻、限流采样电阻', 'Ω'),
        ('Pout', '额定端口输出功率', 'W'),
        ('Vcsmin、Ics', '电流检测比较器的最低门限、用来选采样电阻的峰值电流，必要时含斜坡折算量', 'V、A'),
    )),
    10: ('Lmin=', (
        ('Ilow、η', '最低输入电压处的满载输入电流初估、预设效率', 'A、1'),
        ('Vlow、Vin', '输入下限、区间内用于计算的输入电压', 'V'),
        ('D(Vin)', '指定输入点处的占空比初估', '1'),
    )),
    12: ('Ccharge≥', (
        ('Dmax', '在指定输入范围内用于估算输出电容的最大占空比', '1'),
        ('ΔVc', '分配给输出电容充放电的稳态电压纹波预算', 'V'),
    )),
    14: ('1.25·Ipk,est', (
        ('Vramp、Vrampmax', '占空比 D 时刻的典型补偿斜坡电压、整周期斜坡电压幅值的上限估计', 'V'),
        ('Rext', '外加在电流检测输入侧、用于调节斜坡的串联电阻', 'Ω'),
        ('Ipkb', '原边或电感的满载峰值电流初估，此处指 Boost 电感', 'A'),
    )),
    16: ('fc≤', (
        ('fRHP、fc', '右半平面零点频率、拟选择的环路交越频率', 'Hz'),
        ('Rload、L', '当前工况的负载电阻、已选电感感值', 'Ω、H'),
    )),
    17: ('KP,COMP=', (
        ('Kpin、KP', '外部补偿网络和软件环路分别使用的积分增益系数，分别以 COMP 和 CS 为输入口径', 's⁻¹'),
    )),
    20: ('Lm,DCM=', (
        ('Vr、δ', '关断期间折算到原边的反射电压、退磁结束后的空闲时间比例', 'V、1'),
        ('Lccm、Ldcm', 'CCM 纹波目标的励磁电感下限、DCM 每周期储能关系给出的励磁电感', 'H'),
        ('Pin、r', '预设效率给出的输入功率预算、目标原边纹波与开通段平均电流之比', 'W、1'),
    )),
    22: ('Prated≥', (
        ('Prated、Irms', '采样电阻的最低额定功率、原边电流的全周期均方根', 'W、A'),
        ('Rcs、Ipkb', '采样电阻、原边满载峰值电流初估', 'Ω、A'),
    )),
    23: ('Vw,j=', (
        ('Vwind、j', '第 j 路副边绕组侧的电压估值、输出索引', 'V、1'),
        ('Nsecj、Nsecfb', '第 j 路和反馈路的副边匝数', '匝'),
        ('Vcapfb、Vrectfb', '反馈路防反管前的电容端电压、反馈路整流管正向压降', 'V'),
    )),
}
TUTORIAL_SYMBOLS = {
    'Iload=': (
        ('Rload', '由额定要求折算的负载电阻', 'Ω'),
        ('Vtarget、V_j', '设定的输出电压、计算得到的第 j 路端口电压', 'V'),
        ('Prated、Pactual', '该路额定功率、按恒阻负载求得的实际功率', 'W'),
        ('Iload', '该路的实际直流负载电流', 'A'),
    ),
    'E=12·L·I2': (
        ('v、i、L', '电感端电压、电感电流和电感感值', 'V、A、H'),
        ('E、I', '电感储能、求储能时的瞬时电流', 'J、A'),
    ),
    'ΔIp=': (
        ('Vin、Vo、Vr', '输入电压、输出电压和副边电压折算到原边后的反射电压', 'V'),
        ('D、N', '开关导通时间比例和原边对副边的匝数比', '1'),
        ('fs、Ts', '开关频率和开关周期', 'Hz、s'),
        ('ΔIp', '原边电流的峰峰值', 'A'),
    ),
    'Irms2=': (
        ('Irms、Ipk、Imin', '全周期均方根电流、开关导通区间末端和起点的电流', 'A'),
        ('Ip,on,avg、Iin,est', '开通区间平均电流、按理想功率平衡估计的全周期平均输入电流', 'A'),
    ),
    'Irms=': (
        ('Iavg、Irms', '以完整开关周期为分母的平均电流和均方根电流', 'A'),
        ('i(t)、t', '所分析支路的瞬时电流、周期内时间', 'A、s'),
    ),
    'vCbank': (
        ('ic(t)、i_d(t)', '电容支路和整流支路的瞬时电流', 'A'),
        ('Δv_C(t)、v_Cbank(t)', '理想电容的电压变化、加入 ESR 和 ESL 后的端口电压变化', 'V'),
        ('Cmin、C', '初算的最小输出容量、用于积分的电容值', 'F'),
        ('ESR、ESL', '等效串联电阻和电感', 'Ω、H'),
    ),
    'ΔVc=': (
        ('Vc、ΔVc', '以输入母线为参考的钳位电压和允许的峰峰值纹波', 'V'),
        ('dC、Kc', '允许钳位纹波与钳位电压之比、钳位电压与反射电压之比', '1'),
        ('Rsnub、Csnub', 'RCD 钳位网络的电阻与电容', 'Ω、F'),
    ),
    'Roff=': (
        ('Ron、Roff', '开通、关断方向上的等效总栅极电阻', 'Ω'),
        ('Rg_drive、Rg', '驱动器输出等效电阻和 MOSFET 内部栅极电阻', 'Ω'),
        ('Rs_on、Rs_off', '外部开通和关断栅极串联电阻', 'Ω'),
    ),
    't8=': (
        ('t₁、t₂、t₃', '阈值延时、电流上升和开通米勒平台的时长', 's'),
        ('t₆、t₇、t₈', '关断米勒平台、电流下降和阈值以下的放电时长', 's'),
        ('Vth、Vgs', '栅极阈值电压和驱动高电平', 'V'),
        ('Vgp,on、Vgp,off', '开通与关断事件分别对应的米勒平台电压', 'V'),
        ('Qg_th、Qgs,on、Qgs,off', '阈值电荷及开通、关断条件下从零电压到平台的栅电荷', 'C'),
        ('Qgd,on、Qgd,off', '开通和关断条件下米勒平台区间对应的栅电荷', 'C'),
    ),
    'Jj=': (
        ('Astrand、Atotal', '单股裸铜截面积、并联路径的裸铜总截面积', 'm²'),
        ('b、nstrand、Nturn', '并绕数、每根导线的股数和绕组匝数', '1'),
        ('Rdc、ρ、MLT', '绕组直流电阻、铜电阻率和每匝平均长度', 'Ω、Ω·m、m'),
        ('J_j、Irms_j、Acu_j', '第 j 路绕组的电流密度、有效值电流和裸铜总截面积', 'A/m²、A、m²'),
    ),
    'Pcu=': (
        ('δ、dwire、x', '集肤深度、单股导线直径和直径除以集肤深度的比值', 'm、m、1'),
        ('μ₀、Fr', '真空磁导率和所用交流电阻修正倍数', 'H/m、1'),
        ('Pcu', '逐绕组合计的铜损功率', 'W'),
    ),
    'Hreq=': (
        ('H_req、m_y', '绕组及绝缘所需窗口高度、上方或下方各自的边距', 'm'),
        ('ℓ、h_layer、t_layer', '物理层索引、该层线束高度和该层前绝缘厚度', '1、m、m'),
    ),
    'ωz=': (
        ('Gc(s)、s', '二型补偿器传递函数、拉普拉斯复频率', 'V/V、s⁻¹'),
        ('KP', '带原点积分极点的增益系数', 's⁻¹'),
        ('ωz、ωp', '有限零点和有限极点的角频率', 'rad/s'),
        ('fz1、fp1', '有限零点和有限极点的频率', 'Hz'),
    ),
}


def register_basis_notation():
    wm.ALIASES.update({
        'Vhigh': 'V_in,max', 'Vlow': 'V_in,min', 'ΔVlim': 'ΔV_o,pp',
        'Ccharge': 'C_charge', 'Cstep': 'C_step', 'Cin': 'C_in', 'ΔIstep': 'ΔI_step',
        'Vcsmin': 'V_CS,min', 'Rcs': 'R_CS', 'Ics': 'I_CS', 'Iload': 'I_load',
        'Dstar': 'D_*', 'ΔVin': 'ΔV_in', 'ΔVc': 'ΔV_C', 'Dmax': 'D_max', 'Ilow': 'I_in,ref',
        'Ipkb': 'I_pk,est', 'Vramp': 'V_ramp', 'Vcsmax': 'V_CS,max', 'Rext': 'R_ext',
        'Vrampmax': 'V_ramp,max', 'fRHP': 'f_RHP', 'Kpin': 'K_P,COMP',
        'Lccm': 'L_m,CCM', 'Ldcm': 'L_m,DCM', 'Prated': 'P_rated', 'Vwind': 'V_w,j',
        'Nsecj': 'N_s,j', 'Nsecfb': 'N_s,fb', 'Vcapfb': 'V_cap,fb', 'Vrectfb': 'V_F,fb',
    })
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)


def _register_tutorial_notation():
    wm.ALIASES.update({
        'Vtarget': 'V_target', 'Prated': 'P_rated', 'Pactual': 'P_actual', 'Iload': 'I_load',
        'i_d': 'i_d', 'Δv_C': 'Δv_C', 'v_Cbank': 'v_Cbank', 'dC': 'd_C',
        'Astrand': 'A_strand', 'Atotal': 'A_total', 'Nturn': 'N_turn',
        'ωz': 'ω_z', 'fz1': 'f_z1', 'fp1': 'f_p1', 'ESR': 'ESR', 'ESL': 'ESL',
    })
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)


def _explain_formulas(doc, *, tutorial):
    pending = set(TUTORIAL_SYMBOLS)
    for paragraph in doc.paragraphs:
        formula = paragraph._p.xpath('./m:oMath')
        label = paragraph.text.strip(' ()\t')
        if not formula or not label.isdecimal():
            continue
        content = ''.join(part.text or '' for part in formula[0].iter(qn('m:t')))
        if tutorial:
            prefix = next((key for key in pending if content.startswith(key)), None)
            if prefix is None:
                continue
            pending.remove(prefix)
            definitions = TUTORIAL_SYMBOLS[prefix]
        else:
            if int(label) not in BASIS_SYMBOLS:
                continue
            prefix, definitions = BASIS_SYMBOLS[int(label)]
            if not content.startswith(prefix):
                raise ValueError(f'第 {label} 式内容变更，需同步复核符号释义：{content}')
        last = doc.element.body[-2]
        add_symbols(doc, *definitions)
        for node in list(doc.element.body)[doc.element.body.index(last) + 1:-1][::-1]:
            paragraph._p.addnext(node)
        paragraph.paragraph_format.keep_with_next = True
    if tutorial and pending:
        raise ValueError('教程公式变更，需同步复核符号释义：' + '、'.join(sorted(pending)))


def _strip_run_layout(paragraph):
    for run in paragraph.runs:
        props = run._element.rPr
        if props is None or run._element.xpath('.//w:drawing'):
            continue
        for key in ('rFonts', 'sz', 'szCs', 'color'):
            child = props.find(qn('w:' + key))
            if child is not None:
                props.remove(child)


def _format_table(table, width):
    total = sum(c.width for c in table.columns)
    if total > width:
        for column in table.columns:
            column.width = int(column.width * width / total)
            for cell in column.cells:
                cell.width = column.width
    for row_number, row in enumerate(table.rows):
        for cell in row.cells:
            shade = cell._tc.tcPr.find(qn('w:shd'))
            if shade is not None:
                shade.set(qn('w:fill'), 'E5EBF2' if row_number == 0 else 'FFFFFF')
            for paragraph in cell.paragraphs:
                paragraph.style = 'Reference Table'
                paragraph.paragraph_format.line_spacing = None
                for run in paragraph.runs:
                    _typeface(run._element.get_or_add_rPr(), BODY)
                    run.font.color.rgb = RGBColor(0, 0, 0)


def _contents(doc, anchor, chapters):
    title = doc.add_paragraph('目录', 'Contents Title')
    anchor._p.addprevious(title._p)
    anchor = title
    anchor.paragraph_format.page_break_before = True
    anchor.paragraph_format.keep_with_next = True
    cursor = anchor._p
    for index, heading in enumerate(chapters, 1):
        entry = doc.add_paragraph(style='Contents Entry')
        entry.paragraph_format.left_indent = Mm(5)
        entry.paragraph_format.tab_stops.add_tab_stop(Mm(177), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        _toc_link(entry, heading.text, _set_bookmark(heading, index))
        cursor.addnext(entry._p)
        cursor = entry._p


def _tutorial_contents(doc, chapters):
    heading = next(p for p in doc.paragraphs if p.text == '阅读路线')
    heading.style = 'Contents Title'
    heading.paragraph_format.space_before = None
    heading.paragraph_format.page_break_before = True
    heading.paragraph_format.keep_with_next = True
    table = next(t for t in doc.tables if t.cell(0, 0).text == '章节')
    appendix = table.rows[-1]
    description = appendix.cells[1].text
    for _ in chapters[-2:]:
        table._tbl.append(deepcopy(appendix._tr))
    for index, (row, chapter) in enumerate(zip(table.rows[1:], chapters), 1):
        p = row.cells[0].paragraphs[0]
        label = p.text if index <= len(chapters) - 3 else chapter.text
        if index > len(chapters) - 3:
            label = CHAPTER.match(chapter.text)[1]
            row.cells[1].text = description if index == len(chapters) - 2 else CHAPTER.sub('', chapter.text)
        p.clear()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.tab_stops.add_tab_stop(Mm(49), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        _toc_link(p, label, _set_bookmark(chapter, index))


def apply_book_style(doc, *, kind):
    """Style the help body in place and retain the input's native content."""
    if any(p.style.name == 'Formula Display' for p in doc.paragraphs):
        return doc
    tutorial = kind == 'tutorial'
    old_subject = doc.core_properties.subject
    prepare_book(doc)
    doc.core_properties.subject = old_subject
    title = next(p for p in doc.paragraphs if p.style.name == 'Title')
    header = doc.sections[0].header.paragraphs[0]
    header.runs[0].text = '开关电源设计与环路分析　｜　' + title.text
    title.paragraph_format.space_before = Pt(72 if tutorial else 8)
    if tutorial:
        _register_tutorial_notation()
    else:
        register_basis_notation()
    _explain_formulas(doc, tutorial=tutorial)
    chapters = [p for p in doc.paragraphs if p.style.name == 'Heading 1' and CHAPTER.match(p.text)]
    if tutorial:
        _tutorial_contents(doc, chapters)
    else:
        _contents(doc, chapters[0], chapters)

    width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin
    chapter, subsection = '0', ''
    formula_index = table_index = figure_index = 0
    for block in list(doc.iter_inner_content()):
        if isinstance(block, Table):
            _format_table(block, width)
            columns = tuple(c.text for c in block.rows[0].cells[:2])
            if columns == ('章节', '要解决的问题'):
                continue
            if columns == ('设计例程', '输入、输出与规格'):
                for row, chapters_text in zip(block.rows[1:], ('第 1–3 章', '第 4–6 章', '第 7–9 章')):
                    p = row.cells[2].paragraphs[0]
                    p.runs[0].text = re.sub(r'^第 \d+–\d+ 页', chapters_text, p.runs[0].text)
            table_index += 1
            context = HELP_TABLE_TITLES.get(columns, TABLE_TITLES.get(columns, subsection or columns[0]))
            caption = doc.add_paragraph(context, 'Caption')
            _number_caption(caption, f'表 {chapter}-{table_index}' if chapter != '0' else f'表 {table_index}')
            caption.paragraph_format.keep_with_next = True
            block._tbl.addprevious(caption._p)
            continue
        p = block
        name = p.style.name
        _strip_run_layout(p)
        match = CHAPTER.match(p.text)
        if name == 'Heading 1' and match:
            chapter = match[1].split()[-1].lstrip('0')
            subsection = p.text[match.end():]
            formula_index = table_index = figure_index = 0
            p.paragraph_format.page_break_before = chapter in (
                ('1', '9', '16') if tutorial else ('1', '4', '7', '10')
            )
        elif name == 'Heading 2':
            subsection = re.sub(r'^\w+(?:\.\d+)?\s+', '', p.text)
            p.paragraph_format.page_break_before = False
        elif name == 'Caption':
            figure_index += 1
            if not p.text.startswith('图 '):
                _number_caption(p, f'图 {chapter}-{figure_index}')
        elif name == 'Normal' and p._p.xpath('./m:oMath'):
            formula_index += 1
            if p.runs and LEGACY_LABEL.fullmatch(p.runs[-1].text):
                p._p.remove(p.runs[-1]._r)
            _number_formula(p, chapter, formula_index, width)
        elif name == 'Normal' and not tutorial:
            for run in p.runs:
                if '反激补充资料见第 8–10 页' in run.text:
                    run.text = run.text.replace('反激补充资料见第 8–10 页', '反激补充资料见第 7–9 章')
    for shape in doc.inline_shapes:
        if shape.width > width:
            shape.height = int(shape.height * width / shape.width)
            shape.width = width
    return doc


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('tutorial', 'basis'), required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('请先写入候选文档并检查版面')
    doc = apply_book_style(Document(args.source), kind=args.kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
