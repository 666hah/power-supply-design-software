"""Editable source for the native LLC reference figures."""

from docs.calculation_control_diagrams import _Diagram, SIGNAL
from llc_settings import HYBRID_MODE, VOLTAGE_MODE


def _voltage_control():
    diagram = _Diagram(421)
    diagram.main_chain(165, (
        ('电压误差', 'Vref − Vcap', 'control'),
        ('PI 电压环', '误差增大时频率下降', 'control'),
        ('变频振荡器', '频率钳位 fmin／fmax', 'timing'),
        ('桥臂时序', '交替导通与死区', 'control'),
        ('LLC 功率级', '桥臂、谐振腔与整流', 'plant'),
    ))
    diagram.box(3, 45, '启动与保护', '高频软启动／停脉冲', 'sense')
    diagram.route((829, 123), (829, 165))
    diagram.voltage_feedback(165, 311, '副边电容端取样', '隔离电压反馈', output='Vcap')
    return diagram


def _hybrid_hysteretic_control():
    diagram = _Diagram(426)
    diagram.main_chain(174, (
        ('电压误差', 'Vref − Vcap', 'control'),
        ('PI 电压环', '输出滞环阈值指令', 'control'),
        ('阈值比较', '达到阈值时换相', 'control'),
        ('桥臂时序', '极性交替与死区', 'control'),
        ('LLC 功率级', '桥臂、谐振腔与整流', 'plant'),
    ))
    diagram.box(2, 45, 'Cr 取样与补偿', '半周反号／补偿斜坡', 'sense')
    diagram.box(3, 45, '半周期限制', '软启动、限频及保护', 'timing')
    diagram.route((599, 123), (599, 174))
    diagram.route((829, 123), (829, 174))
    diagram.route((1156, 213), (1180, 213), (1180, 18), (599, 18), (599, 45))
    diagram.label(1048, 40, 'Cr 电压', color=SIGNAL)
    diagram.voltage_feedback(174, 317, '副边电容端取样', '隔离电压反馈', output='Vcap')
    return diagram


def render_llc_control(mode):
    """Return a high-resolution PNG positioned at the start of the stream."""
    draws = {VOLTAGE_MODE: _voltage_control, HYBRID_MODE: _hybrid_hysteretic_control}
    return draws[mode]().png()
