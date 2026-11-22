"""Add control-model figures and the COT chapter to the calculation reference."""

import argparse
from pathlib import Path
import sys

from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docx_layout import figure, paragraph
from docs.calculation_reference_layout import finish_book


DIAGRAM_NAME_PREFIX = 'Calculation control diagram '
FIGURES = (
    ('3  ', 1, 'qr_l6565',
     '准谐振反激的峰值电流关断与谷底开通',
     '所选反馈路的电容端信号经隔离补偿，形成峰值电流指令。CS 比较复位驱动。ZCD 由退磁信号启动谷底定时，再置位驱动。',
     '图中分开标出两个开关事件。ZCD 通道确定下一次允许开通的时刻，CS 通道确定当次脉冲的关断时刻。'),
    ('4  ', 1, 'acf_timing',
     '有源钳位正激的固定周期控制与双管驱动',
     '固定频率主 PWM 受反馈调节。互补驱动在主、辅开关交接时插入死区。主开关供能，钳位支路复位变压器。',
     '主 PWM 的关断命令进入双管时序，随后按设定死区切换至辅助支路。控制至输出模型及适用工况见第 8 章。'),
    ('8.1  ', 2, 'voltage_pwm',
     '固定频率电压模式 PWM',
     '参考与取样比较后进入电压补偿器。控制电压与周期锯齿比较，产生驱动占空比。输出电压反馈构成外环。',
     '固定时钟确定周期，锯齿幅值决定控制电压到占空比的增益。对 TPS40200 参考配置，斜坡幅值随输入母线变化。'),
    ('8.3  ', 1, 'peak_current_pwm',
     '固定频率峰值电流模式 PWM',
     '时钟置位 PWM。选定的电流经采样并叠加斜坡，与外环电流指令比较后复位 PWM。电压反馈闭合外环。',
     'CS 取样对象随拓扑而变。Buck 对应单相电感电流，Boost 对应主开关导通时的电感电流，反激对应原边主开关电流。隔离 SSR 的反馈电压取自所选输出的防反管前电容端。'),
    ('15.4  ', 2, 'mp6005_psr',
     'MP6005 原边反馈的退磁采样与 PWM／PFM 路径',
     '退磁时从辅助绕组分压取得反馈，经 COMP 调节峰值电流。较轻负载时按最小峰值与每周期能量关系估算变频。',
     'PWM 小信号使用辅助绕组反馈增益和 COMP 网络。轻载 PFM 分支根据最低峰值电流处理功率与频率关系，见第 15.3 节。'),
)


def add_control_figure(doc, key, caption, alt):
    from docs.calculation_control_diagrams import render_control_figure

    figure(doc, render_control_figure(key).getvalue(), caption, width=14.8 / 2.54)
    shape = doc.inline_shapes[-1]
    shape._inline.docPr.set('name', DIAGRAM_NAME_PREFIX + key)
    shape._inline.docPr.set('descr', alt)


def add_control_reference(doc):
    from docs.cot_calculation_chapter import add_cot_chapter

    if any(p.style.name == 'Heading 1' and p.text.startswith('21  ') for p in doc.paragraphs):
        raise ValueError('第 21 章已存在。请以原稿执行增补，或用完整构建入口重建。')

    intro = next(p for p in doc.paragraphs if p.text.startswith('第 1 至 7 章给出'))
    guide = intro.insert_paragraph_before(
        '各控制方式的信号方向见第 3、4、8、15 与 21 章。第 21 章从固定活动相数的稳态出发，建立同步 Buck 的 COT 外环与逐相均流模型，并用同一套四相硬件比较输入两端。'
    )
    intro._p.addnext(guide._p)

    for prefix, after, key, caption, alt, note in FIGURES:
        paragraphs = doc.paragraphs
        index = next(i for i, p in enumerate(paragraphs)
                     if p.style.name.startswith('Heading') and p.text.startswith(prefix))
        anchor = paragraphs[index + after]._p
        paragraph(doc, note)
        add_control_figure(doc, key, caption, alt)
        for block in doc.paragraphs[-3:]:
            anchor.addnext(block._p)
            anchor = block._p

    appendix = next(p._p for p in doc.paragraphs
                    if p.style.name == 'Heading 1' and p.text.startswith('附录 A'))
    existing = set(doc.element.body)
    add_cot_chapter(doc, add_control_figure)
    for node in list(doc.element.body):
        if node not in existing and node.tag != qn('w:sectPr'):
            appendix.addprevious(node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    doc = Document(options.source)
    add_control_reference(doc)
    finish_book(doc)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(options.output)


if __name__ == '__main__':
    main()
