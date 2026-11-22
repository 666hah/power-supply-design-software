"""LLC topology plates and timing from the book's 300 W example designs."""

import json
from pathlib import Path

import numpy as np
from matplotlib.patches import Rectangle

from .visio_circuit import BLUE, INK, MUTED, ORANGE, TEAL, Circuit, timing_page


def _crossover(circuit, x, y, rise):
    angle = np.linspace(np.pi, 0, 25)
    arc_x, arc_y = x + .23*np.cos(angle), y + rise*np.sin(angle)
    crossing = abs(angle - np.pi/2) < .43
    circuit.wire(*zip(arc_x[crossing], arc_y[crossing]), color='white', lw=4.5, zorder=4)
    circuit.wire(*zip(arc_x, arc_y), zorder=5)


def _rectifier(circuit, secondary_x, secondary_top, secondary_bottom):
    left, right, midpoint = 13.0, 15.02, 3.02
    pos, neg = 4.97, 1.04
    circuit.wire((secondary_x, secondary_top), (11.98, secondary_top),
                 (11.98, midpoint), (left, midpoint))
    circuit.wire((secondary_x, secondary_bottom), (left-.23, secondary_bottom))
    _crossover(circuit, left, secondary_bottom, -.19)
    circuit.wire((left+.23, secondary_bottom), (14.12, secondary_bottom),
                 (14.12, midpoint), (right, midpoint))
    for x, high, low in ((left, 'D1', 'D2'), (right, 'D3', 'D4')):
        circuit.diode((x, midpoint), (x, pos), high)
        circuit.diode((x, neg), (x, midpoint), low)
        for y in (pos, midpoint, neg):
            circuit.node(x, y)

    circuit.wire((left, pos), (19.03, pos))
    circuit.wire((left, neg), (19.03, neg))
    circuit.cap((16.68, pos), (16.68, neg), '$C_o$', plus=True)
    circuit.resistor((18.10, pos), (18.10, neg))
    circuit.text(17.90, 3.75, '$R_{load}$', ha='right')
    for x in (16.68, 18.10):
        circuit.node(x, pos)
        circuit.node(x, neg)
    circuit.terminal(19.03, pos, '+', dx=.39, dy=0)
    circuit.terminal(19.03, neg, '−', dx=.39, dy=0)
    circuit.text(19.42, 3.18, '$v_o$', color=BLUE)
    circuit.text(18.69, .69, '副边参考点', fontsize=8, color=MUTED)
    circuit.node(16.68, pos, '$v_{cap}$', dy=.34)


def _schematic(full):
    circuit = Circuit(xlim=(0, 20.0), ylim=(0, 6.3), height=2.64)
    high, low, midpoint, tank, ret = 5.57, .79, 3.02, 4.43, 1.45
    a, b = 3.21, 5.50
    circuit.wire((.79, high), (b if full else a, high))
    circuit.wire((.79, low), (b if full else 6.21, low))
    circuit.source((.79, high), (.79, low))
    circuit.text(.52, 4.49, '$V_b$', color=BLUE)
    circuit.cap((1.84, high), (1.84, low), '$C_{in}$', plus=True)
    circuit.node(1.84, high)
    circuit.node(1.84, low)
    circuit.ground(1.84, low)
    circuit.mos((a, high), (a, midpoint), label='Q1')
    circuit.mos((a, midpoint), (a, low), label='Q2')
    circuit.node(a, midpoint, '$A$', dx=-.23, dy=.47)
    if full:
        circuit.mos((b, high), (b, midpoint))
        circuit.mos((b, midpoint), (b, low), label='Q4')
        circuit.text(b+.43, 3.82, 'Q3', ha='left')
        circuit.node(a, high)
        circuit.node(a, low)
        circuit.node(b, midpoint, '$B$', dx=.34)
        upper_route = 5.10
        circuit.wire((a, midpoint), (4.21, midpoint), (4.21, upper_route), (b-.23, upper_route))
        _crossover(circuit, b, upper_route, .19)
        circuit.wire((b+.23, upper_route), (6.22, upper_route), (6.22, tank))
        circuit.wire((b, midpoint), (6.54, midpoint), (6.54, ret), (9.71, ret))
    else:
        circuit.wire((a, midpoint), (4.21, midpoint), (4.21, tank), (6.22, tank))
        circuit.wire((6.21, low), (6.21, ret), (9.71, ret))
        circuit.node(a, low)

    circuit.cap((6.22, tank), (7.22, tank), '$C_r$')
    circuit.coil((7.22, tank), (8.70, tank), '$L_r$')
    circuit.wire((8.70, tank), (9.71, tank))
    circuit.coil((8.70, tank), (8.70, ret))
    circuit.text(8.43, 3.75, '$L_m$', ha='right')
    circuit.node(8.70, tank)
    circuit.node(8.70, ret)
    circuit.arrow((6.58, 5.43), (7.77, 5.43), '$i_r$')
    circuit.arrow((8.12, 3.31), (8.12, 2.60))
    circuit.text(7.78, 2.98, '$i_m$', color=TEAL)
    circuit.transformer((9.71, tank), (9.71, ret), (10.98, 4.64), (10.98, 1.53),
                        label='T1')
    circuit.text(10.35, .80, '$N_p:N_s$', color=MUTED)
    _rectifier(circuit, 10.98, 4.64, 1.53)
    return circuit.fig


def _draw_half():
    return _schematic(False)


def _draw_full():
    return _schematic(True)


def _operating_point(full):
    from llc_model import solve

    name = 'FULL_VCO' if full else 'HALF_HHC'
    example = Path(__file__).resolve().parents[2] / 'examples' / f'300W_LLC_{name}.json'
    params = json.loads(example.read_text(encoding='utf-8-sig'))
    result = solve(dict(params, V_in=360, P_out=300), points=640)
    if not result['regulation_ok']:
        raise ValueError(f'LLC {name} 的 360 V／300 W 周期解未达到稳压条件')
    return params['llc_dead_time'], result


def _timing(full):
    dead, op = _operating_point(full)
    half = op['period_s']*5e5
    end = 2*half
    dead_us = dead*1e6
    t = op['time_s']*1e6
    title = (f'360 V 输入 · 48 V / 300 W 输出 · {op["frequency_Hz"]/1e3:.2f} kHz'
             f' · 每次死区 {dead*1e9:.0f} ns')
    fig, axes = timing_page(title, rows=4, height=4.28)
    gate_labels = (r'$g_1,\ g_4$', r'$g_2,\ g_3$') if full else ('$g_1$', '$g_2$')
    for axle, polarity, label, color in zip(axes[:2], (1, -1), gate_labels, (BLUE, TEAL)):
        gate = (op['gate_state'] == polarity).astype(int)
        # The last sample, exactly one period later, begins the next dead interval.
        gate[-1] = 0
        axle.step(t, gate, where='post', color=color, lw=1.55)
        axle.set(ylabel=label, yticks=[0, 1], ylim=(-.16, 1.23))
    vdrive = op['v_drive_V'] if full else op['v_drive_V'] + op['bridge_amplitude_V']
    voltage_ticks = [-360, 0, 360] if full else [0, 180, 360]
    axes[2].plot(t, vdrive, color=ORANGE, lw=1.55)
    axes[2].set(ylabel='$v_{AB}$ / V' if full else '$v_A$ / V',
                yticks=voltage_ticks, ylim=(voltage_ticks[0]-66, voltage_ticks[-1]+66))
    axes[3].plot(t, op['i_res_A'], color=BLUE, lw=1.55, label='$i_r$')
    axes[3].plot(t, op['i_mag_A'], color=TEAL, lw=1.45, ls='--', label='$i_m$')
    current_tick = 1 if full else 3
    max_current = op['ir_peak_A']*1.15
    axes[3].set(ylabel='电流 / A', xlabel='从换相关断起计时 / µs', xlim=(0, end),
                yticks=[-current_tick, 0, current_tick], ylim=(-max_current, max_current),
                xticks=[0, 2, 4, 6, 8, 10])
    axes[3].legend(loc='upper right', ncol=2, handlelength=1.4, columnspacing=1.0)
    for axle in axes:
        for turnoff in (0, half):
            axle.axvspan(turnoff, turnoff + dead_us, color=ORANGE, alpha=.13, lw=0)
            axle.axvline(turnoff, color=MUTED, ls=':', lw=.75, zorder=0)
    fig.align_ylabels(axes)
    return fig


def _draw_half_timing():
    return _timing(False)


def _draw_full_timing():
    return _timing(True)


def _block(circuit, left, right, y, title, detail=None, *, height=.94):
    circuit.ax.add_patch(Rectangle((left, y-height/2), right-left, height,
                                   ec=BLUE, fc='#ecf3f9', lw=1.25))
    mid = (left+right)/2
    circuit.text(mid, y+.16 if detail else y, title, fontsize=8.8, color=BLUE)
    if detail:
        circuit.text(mid, y-.18, detail, fontsize=8, color=INK)


def _control_symbols():
    circuit = Circuit(xlim=(0, 20.6), ylim=(0, 9.7), height=3.82)
    circuit.text(.37, 9.04, '电压变频', ha='left', fontweight='bold', color=BLUE)
    vp, vm, err = circuit.amplifier(3.10, 7.53, '误差放大器')
    circuit.terminal(1.12, vp[1])
    circuit.terminal(1.12, vm[1])
    circuit.text(.97, vp[1], '$V_{set}$', ha='right')
    circuit.text(.97, vm[1], '$V_{fb}$', ha='right')
    circuit.wire((1.12, vp[1]), vp)
    circuit.wire((1.12, vm[1]), vm)
    circuit.arrow(err, (4.14, 7.53))
    _block(circuit, 4.14, 6.35, 7.53, '电压 PI', '降频指令 $u_f$')
    circuit.arrow((6.35, 7.53), (7.06, 7.53))
    _block(circuit, 7.06, 10.86, 7.53, '限频振荡器', '$f_s=f_{bias}-u_f$')
    circuit.arrow((10.86, 7.53), (11.73, 7.53))
    _block(circuit, 11.73, 14.70, 7.53, '半周定时', '每 $1/(2f_s)$ 翻转')
    circuit.arrow((14.70, 7.53), (15.60, 7.53))
    _block(circuit, 15.60, 18.35, 7.53, '死区驱动', '两组交替开通')
    circuit.arrow((18.35, 7.53), (19.38, 7.53))
    circuit.text(19.87, 7.53, '门极', color=TEAL)
    circuit.text(4.14, 6.52, '$V_{fb}$ 取自隔离输出的电容端', ha='left', color=MUTED, fontsize=8.2)
    circuit.wire((.37, 5.94), (20.20, 5.94), color=MUTED, lw=.70)

    circuit.text(.37, 5.46, '混合滞环', ha='left', fontweight='bold', color=BLUE)
    sample_y, ramp_y, sum_y = 4.25, 3.00, 3.58
    circuit.terminal(.82, sample_y)
    circuit.text(2.14, 4.64, r'$2k_s\sigma_h(v_{Cr}-V_{bias})$', color=TEAL)
    circuit.wire((.82, sample_y), (3.74, sample_y))
    circuit.resistor((3.74, sample_y), (5.73, sample_y), '$R$')
    circuit.resistor((3.74, ramp_y), (5.73, ramp_y), '$R$')
    circuit.wire((5.73, sample_y), (6.22, sample_y), (6.22, ramp_y), (5.73, ramp_y))
    circuit.arrow((1.23, 3.72), (1.23, ramp_y))
    circuit.text(1.39, 3.66, '$I_s$', ha='left', color=TEAL)
    circuit.cap((1.23, ramp_y), (1.23, 1.46), '$C_s$')
    circuit.switch((2.53, ramp_y), (2.53, 1.46))
    circuit.wire((1.23, 1.46), (2.53, 1.46))
    circuit.ground(1.23, 1.46)
    circuit.wire((1.23, ramp_y), (3.74, ramp_y))
    circuit.node(1.23, ramp_y)
    circuit.node(2.53, ramp_y)
    circuit.text(2.53, 1.14, '复位', fontsize=8, color=MUTED)
    circuit.text(4.32, 2.54, r'$2m_s\max(0,t-t_d)$', color=TEAL, fontsize=8.4)
    circuit.text(2.87, 1.56, r'$I_s/C_s=2m_s$', ha='left', color=MUTED, fontsize=8.3)
    cmp_p, cmp_n, cmp_out = circuit.amplifier(7.97, sum_y-.22, '比较器')
    circuit.wire((6.22, sum_y), cmp_p)
    circuit.node(6.22, sum_y)
    circuit.wire(cmp_n, (7.02, cmp_n[1]), (7.02, 2.35))
    circuit.terminal(7.02, 2.35)
    circuit.text(7.02, 1.98, '电压 PI 的阈值 $u_h$', fontsize=8.3)
    circuit.arrow(cmp_out, (9.11, cmp_out[1]))
    _block(circuit, 9.11, 12.30, cmp_out[1], '相位选通与限频', '负半周 S · 正半周 R', height=1.08)
    s, r, q = circuit.latch(14.06, cmp_out[1], 'RS 相位锁存')
    circuit.arrow((12.30, s[1]), s)
    circuit.arrow((12.30, r[1]), r)
    _block(circuit, 15.60, 18.35, cmp_out[1], '死区驱动', '两组交替开通')
    circuit.arrow(q, (15.60, q[1]))
    circuit.arrow((18.35, q[1]), (19.38, q[1]))
    circuit.text(19.87, q[1], '门极', color=TEAL)
    circuit.node(15.16, q[1])
    circuit.wire((15.16, q[1]), (15.16, .56), (.41, .56), (.41, sample_y),
                 color=TEAL, ls='--', lw=1)
    circuit.arrow((.41, sample_y), (.81, sample_y))
    circuit.text(9.70, .91, r'Q 确定半周符号 $\sigma_h$，翻转后复位斜坡，斜坡在死区结束后上升',
                 color=TEAL, fontsize=8.4)
    return circuit.fig


PLATES = {
    'llc_half': (
        '半桥 LLC 谐振变换器',
        '360 V 直流母线供电，输出 48 V／300 W。Q1、Q2 交替导通。半桥节点 A 对原边地测量，'
        '谐振电容 Cr 承担平均约 180 V 的直流偏置。观察死区时两路门极关断，谐振电流仍持续换流。',
        _draw_half,
        'Q1、Q2 构成半桥，Cr 与 Lr 串联，Lm 与 T1 原边并联。箭头定义正向电流。',
        _draw_half_timing,
        '内置半桥混合滞环例程的一个周期解。门极用逻辑电平表示，1 为开通指令。橙色阴影标出死区。',
        7,
    ),
    'llc_full': (
        '全桥 LLC 谐振变换器',
        '360 V 直流母线供电，输出 48 V／300 W。Q1 与 Q4、Q2 与 Q3 分别同相驱动。'
        '桥压为 A 对 B 的电压，两组对角管轮流施加正、负母线电压。沿图中箭头的方向读取带符号的电流。',
        _draw_full,
        '两桥臂的中点 A、B 接谐振腔两端。跨线拱桥表示两导线各自连续，实心圆点表示接通。',
        _draw_full_timing,
        '内置全桥电压变频例程的一个周期解。门极用逻辑电平表示，1 为开通指令。橙色阴影标出死区。',
        7,
    ),
}


LLC_CONTROL = (
    _control_symbols,
    'LLC 的振荡器边沿与混合滞环阈值边沿',
    '电压变频由振荡器确定换相时刻。混合滞环把电容采样和时基斜坡各放大两倍，经等值电阻求平均，'
    '得到两者之和。比较事件在频率边界内置位或复位相位锁存，Q 翻转后进入死区。'
    '半桥的采样偏置 Vbias 取母线电压的一半，全桥取零。',
)
