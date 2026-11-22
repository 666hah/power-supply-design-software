"""Append the LLC sizing method to the existing styled Word guide."""

import argparse
from pathlib import Path
import sys

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, RGBColor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from design_engine.sizing_basis import SCOPE, SOURCES
from docx_layout import equation, paragraph, section, table
from docs.apply_book_style_to_help import _format_table, _strip_run_layout
from docs.calculation_reference_layout import _number_caption, _number_formula, _set_bookmark, _toc_link, add_symbols
import word_math as wm


TITLE = '11  LLC 从规格到首组谐振器件'


def _sources(doc):
    p = doc.add_paragraph(style='Reference Note')
    for index, key in enumerate(('LLC', 'HHC')):
        if index:
            p.add_run('　·　')
        name, scope, url = SOURCES[key]
        hyperlink = OxmlElement('w:hyperlink')
        hyperlink.set(qn('r:id'), p.part.relate_to(url, RT.HYPERLINK, is_external=True))
        run = p.add_run(name)
        run.font.color.rgb = RGBColor.from_string('175898')
        run.underline = True
        hyperlink.append(run._r)
        p._p.append(hyperlink)
        p.add_run('　' + scope)


def append_llc_basis(doc):
    headings = [p for p in doc.paragraphs if p.style.name == 'Heading 1']
    if any(p.text.startswith('11  ') for p in headings):
        raise ValueError('自动计算参数依据已经包含 LLC 章节')
    width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin

    for grid in doc.tables:
        text = grid.cell(0, 0).text
        if text == '设计例程':
            row = grid.add_row()
            for cell, value in zip(row.cells, ('LLC 谐振', '360–420 V → 48 V，0.625–6.25 A，100 kHz 谐振',
                                               '第 11 章。由桥型和品质因数选择谐振腔，再校核两端与轻载。')):
                cell.text = value
            _format_table(grid, width)
        elif text == '拓扑':
            row = next((row for row in grid.rows if row.cells[0].text == 'LLC'), None)
            if row is None:
                row = grid.add_row()
            row.cells[0].text = 'LLC'
            row.cells[1].text = '已接入。' + SCOPE['LLC']
            _format_table(grid, width)
    for p in doc.paragraphs:
        if p.style.name == 'Subtitle':
            p.add_run('　·　LLC 增补')
        for run in p.runs:
            for before, after in (
                ('截至规则版 2026-11-04.3，以下三类拓扑可按规格生成初版。反激自动选型采用固定频率 SSR。',
                 'Buck、Boost、定频反激和 LLC 可按规格生成初版。反激采用固定频率 SSR。'),
                ('文件 → 按规格生成初版', '自动设计 → 按规格生成初版'),
                ('末页列出各拓扑覆盖范围和资料索引', '第 10 章列出拓扑覆盖范围和资料索引'),
            ):
                if before in run.text:
                    run.text = run.text.replace(before, after)
    if 'LLC' not in doc.core_properties.subject:
        doc.core_properties.subject += '、LLC 谐振元件初选与边界复核'

    for name in ('N_p', 'N_s', 'V_b,g', 'V_min', 'V_max', 'V_o', 'V_f', 'I_o',
                 'R_ac', 'Z_r', 'f_r', 'L_r', 'C_r', 'L_m', 'k_m', 'C_min',
                 'r_v', 'I_pk', 'I_OCP'):
        wm.ALIASES[name] = name
    wm.NAMES = sorted(wm.ALIASES, key=len, reverse=True)

    heading = section(doc, TITLE)
    heading.paragraph_format.page_break_before = True
    cursor = [p for p in doc.paragraphs if p.style.name == 'Contents Entry'][-1]
    entry = doc.add_paragraph(style='Contents Entry')
    entry.paragraph_format.left_indent = Mm(5)
    entry.paragraph_format.tab_stops.add_tab_stop(Mm(177), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    _toc_link(entry, TITLE, _set_bookmark(heading, len(headings)+1))
    cursor._p.addnext(entry._p)

    equation_index = 0
    table_index = 0

    def E(text):
        nonlocal equation_index
        equation_index += 1
        p = equation(doc, text)
        _strip_run_layout(p)
        _number_formula(p, 11, equation_index, width)

    def T(label, headers, rows, widths):
        nonlocal table_index
        table_index += 1
        p = doc.add_paragraph(label, 'Caption')
        _number_caption(p, f'表 11-{table_index}')
        p.paragraph_format.keep_with_next = True
        _format_table(table(doc, headers, rows, widths), width)

    paragraph(doc, '桌面「自动设计 → 按规格生成初版」选择 LLC，填写直流母线范围、输出电压和额定电流。'
                   '可填最小负载电流、串联谐振频率、输出纹波、目标相位裕度、桥型、Q 与 Lm/Lr。'
                   '计算区间为 200–440 V 输入、24–80 V 输出、50–600 W 和 50–220 kHz 串联谐振。'
                   '本章的桥型和控制方式可分别选择，示例采用半桥混合滞环（HHC）和全桥电压变频（VCO）。')

    doc.add_heading('由母线中点和阻抗决定匝比及谐振器件', 2)
    paragraph(doc, '以输入上下限的几何平均值作为额定母线估值。首选副边 6 匝，用桥激励幅值除以输出设定与两颗整流管门槛之和，'
                   '将原边匝数取为就近的正整数。由实际整数比和额定负载求基波折算电阻，再按指定 Q 和频率分配谐振电感、电容。')
    E('V_b,g = √(V_min·V_max)；n = N_p/N_s')
    E('N_p = max(1,round(N_s·α·V_b,g/(V_o+2V_f)))')
    E('R_ac = 8n²·V_o/(π²·I_o)；Z_r = Q·R_ac；ω = 2πf_r')
    E('L_r = Z_r/ω；C_r = 1/(ω·Z_r)；L_m = k_m·L_r')
    add_symbols(doc,
        ('V_min、V_max、V_b,g', '输入下限、上限与几何平均母线估值', 'V'),
        ('α、N_p、N_s、n', '桥幅系数（半桥 0.5，全桥 1）、原副边匝数和整数匝比', '1、匝、匝、1'),
        ('V_o、V_f、I_o', '端口目标电压、单颗整流管门槛和额定输出电流', 'V、V、A'),
        ('R_ac、Z_r、Q', '额定折算负载、特征阻抗和品质因数', 'Ω、Ω、1'),
        ('f_r、ω、k_m', '串联谐振频率、对应角频率和 Lm/Lr', 'Hz、rad/s、1'))
    paragraph(doc, '当输出目标相同且全桥匝比为半桥两倍时，折算负载为四倍。按相同 Q 及谐振频率，'
                   '全桥 Lr 与 Lm 约为四倍，Cr 约为四分之一。模型允许锁定谐振器件和输入、输出电容组，'
                   '实际改值后沿用同一硬件复算全部角点。')

    doc.add_heading('从周期电荷和控制范围复核初选', 2)
    paragraph(doc, '两个输出电容的总容量用额定电流在四分之一谐振周期内的电荷作预算，并把纹波预算的 55% 分给电容充放电。'
                   '每颗至少 100 µF，单颗 ESR 初值取 60 mΩ 与半份纹波预算除以额定电流中的较小值。')
    E('C_min = I_o/(4f_r·V_o·r_v·0.55)')
    paragraph(doc, 'rv 为允许的端口纹波占比。初始频限取 0.65fr 和 2fr。HHC 斜率以 4 V 乘以 fr 初选，'
                   'VCO 以频率下降量驱动；两者以低线线性化整定 PI，再把相同增益固定到高线。'
                   '周期解校核两端满载及给定轻载，检查稳压、换流电荷、纹波和满载环路裕度。'
                   '限流初筛按额定两端最大谐振峰值的四倍设置，需以实际器件脉冲能力和启动波形复核。')

    doc.add_heading('300 W 自动首组选值和四个角点', 2)
    paragraph(doc, '按规则 2026-11-19-llc 生成。输入 360–420 V，输出 48 V、0.625–6.25 A，'
                   '串联谐振 100 kHz、Q=0.315、Lm/Lr=5，纹波上限 0.5%，目标相位裕度 60°。'
                   '两列为各自按规格生成的一套硬件，列内高低线不重新选器件。')
    T('自动生成的器件首选', ['设计参数', '半桥 HHC 初版', '全桥 VCO 初版'], [
        ('原边 : 副边匝数', '24 : 6', '48 : 6'),
        ('Lr / Cr / Lm', '49.93 µH / 50.73 nF / 249.67 µH', '199.74 µH / 12.68 nF / 998.69 µH'),
        ('输出电容与死区', '2 × 100 µF，250 ns', '2 × 100 µF，400 ns'),
    ], [1.65, 2.55, 2.55])
    T('自动初版逐角点频率和状态', ['输入与负载', '半桥 HHC', '全桥 VCO'], [
        ('360 V / 6.25 A', '85.171 kHz　通过初筛', '85.537 kHz　通过初筛'),
        ('360 V / 0.625 A', '87.432 kHz　通过初筛', '87.436 kHz　通过初筛'),
        ('420 V / 6.25 A', '113.624 kHz　通过初筛', '113.332 kHz　通过初筛'),
        ('420 V / 0.625 A', '123.502 kHz　通过初筛', '123.241 kHz　频限或 ZVS 待复核'),
    ], [1.72, 2.48, 2.55])
    paragraph(doc, '全桥自动初版以 400 ns 起算。内置例程使用整取的 200 µH、12.665 nF、1 mH，'
                   '根据器件电荷与高线轻载换流另行整定死区，再用 LTspice 核对。'
                   '上表是自动生成器件值的周期解，420 V 轻载保留待复核。打开仿真配置中心，按选定原型检查开通前漏源电压、'
                   '稳态应力、启动和双向负载跳变。')
    doc.add_paragraph('谐振腔折算用公开的基波近似，HHC 取样与斜坡参考原厂结构。'
                      '电容裕量、频率上下限、限流倍率和候选初值为本项目选型规则。', 'Reference Note')
    _sources(doc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('请先生成候选文档并检查版面')
    basis = Document(args.source)
    append_llc_basis(basis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    basis.save(args.output)
