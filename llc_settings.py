"""Common SI parameters and validation for the isolated LLC converter."""

import math


TOPOLOGY = 'LLC'
VOLTAGE_MODE = 'Voltage Mode'
HYBRID_MODE = 'Hybrid Hysteretic'
CONTROL_MODES = (VOLTAGE_MODE, HYBRID_MODE)
SOURCE_RESISTANCE = .025
SOURCE_INDUCTANCE = 1e-6

DEFAULTS = {
    'llc_bridge': 'half',
    'llc_lr': 50e-6,
    'llc_lr_leakage_H': 0.,
    'llc_lr_turns': 0,
    'llc_lr_strands': 1,
    'llc_lr_wire_diameter': 0.,
    'llc_lr_design_peak': 0.,
    'llc_lr_min_ae': 0.,
    'llc_lr_window_width': 0.,
    'llc_lr_window_height': 0.,
    'llc_lr_bobbin_radius': 0.,
    'llc_cr': 50.66e-9,
    'llc_lm': 250e-6,
    'llc_fmin': 60e3,
    'llc_fmax': 180e3,
    'llc_dead_time': 250e-9,
    'llc_tank_r': 0.24,
    'llc_rect_r': 0.025,
    'llc_hhc_sense': 0.008,
    'llc_hhc_ramp': 150e3,
    'llc_kp': 0.0,
    'llc_ki': 0.0,
    'llc_ocp': 8.0,
    'llc_qoss': 0.0,
    'llc_diode_cj': 35e-12,
    'llc_uvlo': 0.0,
    'llc_ovp': 0.0,
    'llc_soft_start': 8e-3,
}


def effective(p):
    """Overlay only missing values. The transformer ratio follows integer turns when set."""
    result = dict(DEFAULTS, **p)
    np, ns = result.get('Np', 0), result.get('Ns', 0)
    if np and ns:
        result['N'] = np / ns
    return result


def validate(p):
    """Check topology-dependent electrical inputs before starting a solve."""
    q = effective(p)
    if q['llc_bridge'] not in ('half', 'full'):
        raise ValueError('LLC 原边桥型应为半桥或全桥')
    if q['control_mode'] not in CONTROL_MODES:
        raise ValueError('LLC 支持变频电压控制和混合滞环控制')
    if q.get('feedback_mode', 'SSR') != 'SSR' or q.get('outputs'):
        raise ValueError('LLC 采用单路全桥整流及输出侧隔离反馈')
    if q.get('coupling_config', {}).get('enabled', False):
        raise ValueError('LLC 使用显式 Lr 与 Lm，请关闭多绕组耦合矩阵')
    positive = ('llc_lr', 'llc_cr', 'llc_lm', 'llc_fmin', 'llc_fmax', 'N')
    if q['control_mode'] == HYBRID_MODE:
        positive += ('llc_hhc_sense', 'llc_hhc_ramp')
    for key in positive:
        if not isinstance(q[key], (int, float)) or not math.isfinite(q[key]) or q[key] <= 0:
            raise ValueError(f'{key} 应为大于零的有限数值')
    for key in DEFAULTS.keys() - {'llc_bridge', *positive}:
        if isinstance(q[key], bool) or not isinstance(q[key], (int, float)) or not math.isfinite(q[key]) or q[key] < 0:
            raise ValueError(f'{key} 应为非负有限数值')
    for key, minimum, maximum in (('llc_lr_turns', 0, 1000), ('llc_lr_strands', 1, 5000)):
        if int(q[key]) != q[key] or not minimum <= q[key] <= maximum:
            raise ValueError(f'{key} 应为 {minimum} 至 {maximum} 的整数')
    if bool(q['llc_lr_window_width']) != bool(q['llc_lr_window_height']):
        raise ValueError('Lr 净绕线窗口轴宽与径深须同时填写，均为零时采用磁芯目录估计')
    if q['llc_lr_leakage_H'] >= q['llc_lr']:
        raise ValueError('计入 Lr 的原边折算漏感必须小于总谐振电感 Lr')
    if q['llc_fmin'] >= q['llc_fmax']:
        raise ValueError('LLC 最低开关频率须小于最高频率')
    if q['llc_dead_time'] >= 0.25 / q['llc_fmax']:
        raise ValueError('LLC 死区须小于最高频率四分之一周期')
    if q['llc_kp'] > 0.0 and q['llc_ki'] == 0.0:
        raise ValueError('LLC 手动 PI 的积分增益须大于零；Kp 与 Ki 均为零时采用自动值')
    if q['llc_ovp'] and q['llc_ovp'] <= q['V_out']:
        raise ValueError('LLC 输出过压阈值须高于稳压设定值')
    if q['llc_uvlo'] and q['llc_uvlo'] >= q.get('V_in_min', q['V_in']):
        raise ValueError('LLC 输入 UVLO 应低于设计输入下限')
    for key in ('Np', 'Ns'):
        if int(q.get(key, 0)) != q.get(key, 0) or q.get(key, 0) < 0:
            raise ValueError('LLC 匝数应为非负整数，零表示由匝比初选')
    return q
