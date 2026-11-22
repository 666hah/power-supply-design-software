"""Non-isolated converter circuits and ideal steady-state teaching waveforms."""

import numpy as np

from .illustrations import BLUE, INK, MUTED, ORANGE, TEAL
from .visio_circuit import Circuit, timing_page


_GATE_HIGH = 8
_SW = r'$v_\mathrm{SW}$'
_GATE = r'$v_\mathrm{GS}$'
_IL = r'$i_L$'
_IQ = r'$i_Q$'
_ID = r'$i_D$'
_TOP, _RETURN = 4.5, 1.05


def _positive_ports(circuit, vin, vout, resistance, capacitance):
    """Draw the shared positive-output input and output port branches."""
    circuit.wire((1.0, _TOP), (3.15, _TOP))
    circuit.wire((1.0, _RETURN), (13.0, _RETURN))
    circuit.source((2.2, _TOP), (2.2, _RETURN))
    circuit.wire((9.1, _TOP), (13.0, _TOP))
    circuit.cap((9.8, _TOP), (9.8, _RETURN), plus=True)
    circuit.text(9.34, (_TOP+_RETURN)/2, capacitance, ha='right')
    circuit.resistor((11.6, _TOP), (11.6, _RETURN), resistance)
    for x in (2.2, 9.8, 11.6):
        circuit.node(x, _TOP)
        circuit.node(x, _RETURN)
    circuit.terminal(1.0, _TOP, f'输入＋ {vin} V', dx=.45, dy=.38)
    circuit.terminal(1.0, _RETURN, '输入－', dy=-.38)
    circuit.terminal(13.0, _TOP, f'输出＋ {vout} V', dx=-.48, dy=.38)
    circuit.terminal(13.0, _RETURN, '输出－', dy=-.38)
    circuit.ground(7.75, _RETURN)
    circuit.node(7.75, _RETURN)
    circuit.text(8.11, .66, '0 V', color=BLUE, ha='left')


def buck_schematic():
    circuit = Circuit(height=2.60)
    _positive_ports(circuit, 24, 12, r'$R_o$ 6 Ω', r'$C_o$ 100 µF')
    circuit.mos((3.15, _TOP), (5.8, _TOP), gate_label=_GATE, label='Q1')
    circuit.diode((5.8, _RETURN), (5.8, _TOP), label='D1')
    circuit.coil((5.8, _TOP), (9.1, _TOP), label='L1  20 µH')
    circuit.node(5.8, _TOP, _SW, dy=.44)
    circuit.node(5.8, _RETURN)
    circuit.arrow((3.6, 5.38), (5.25, 5.38), _IQ)
    circuit.arrow((6.85, 5.38), (8.1, 5.38), _IL)
    circuit.arrow((5.13, 1.99), (5.13, 3.07))
    circuit.text(4.81, 2.52, _ID, color=TEAL)
    return circuit.fig


def boost_schematic():
    circuit = Circuit(height=2.60)
    _positive_ports(circuit, 12, 24, r'$R_o$ 64 Ω', r'$C_o$')
    circuit.coil((3.15, _TOP), (6.25, _TOP), label='L1  20 µH')
    circuit.mos((6.25, _TOP), (6.25, _RETURN), label='Q1')
    circuit.text(5.55, (_TOP+_RETURN)/2, _GATE, ha='right', color=TEAL, fontsize=8.5)
    circuit.diode((6.25, _TOP), (9.1, _TOP), label='D1')
    circuit.node(6.25, _TOP, _SW, dy=.44)
    circuit.node(6.25, _RETURN)
    circuit.arrow((4.0, 5.38), (5.45, 5.38), _IL)
    circuit.arrow((7.1, 5.38), (8.3, 5.38), _ID)
    circuit.arrow((7.19, 3.05), (7.19, 1.90))
    circuit.text(7.50, 2.52, _IQ, color=TEAL)
    return circuit.fig


def inverting_schematic():
    circuit = Circuit(height=2.60)
    top, return_in, return_out, negative = 4.78, 2.01, 3.27, .75
    circuit.wire((1.0, top), (3.15, top))
    circuit.wire((1.0, return_in), (6.2, return_in))
    circuit.source((2.2, top), (2.2, return_in))
    circuit.terminal(1.0, top, '输入＋ 12 V', dx=.45, dy=.36)
    circuit.terminal(1.0, return_in, '输入－', dy=-.37)
    circuit.node(2.2, top)
    circuit.node(2.2, return_in)
    circuit.mos((3.15, top), (6.2, top), gate_label=_GATE, label='Q1')
    circuit.arrow((3.95, 5.52), (5.4, 5.52), _IQ)
    circuit.coil((6.2, top), (6.2, return_in), label='L1  20 µH')
    circuit.node(6.2, top, _SW, dy=.41)
    circuit.arrow((5.49, 3.70), (5.49, 2.82))
    circuit.text(5.17, 3.27, _IL, color=TEAL)
    circuit.ground(6.2, return_in)
    circuit.node(6.2, return_in)
    circuit.text(6.57, 1.66, '0 V', color=BLUE, ha='left')

    circuit.wire((6.2, top), (8.6, top))
    circuit.diode((8.6, negative), (8.6, top))
    circuit.text(8.16, (negative+top)/2, 'D1', ha='right')
    circuit.arrow((7.91, 1.40), (7.91, 2.51))
    circuit.text(7.58, 1.97, _ID, color=TEAL)
    circuit.wire((8.6, negative), (13.0, negative))
    circuit.wire((9.29, return_out), (13.0, return_out))
    circuit.ground(9.29, return_out)
    circuit.text(9.29, 3.68, '0 V', color=BLUE)
    circuit.cap((10.1, return_out), (10.1, negative), r'$C_o$', plus=True)
    circuit.resistor((11.6, return_out), (11.6, negative), r'$R_o$ 64 Ω')
    for x in (10.1, 11.6):
        circuit.node(x, return_out)
        circuit.node(x, negative)
    circuit.terminal(13.0, return_out, '输出＋ 0 V', dx=-.45, dy=.36)
    circuit.terminal(13.0, negative, '输出－ −12 V', dx=-.56, dy=-.38)
    return circuit.fig


def multiphase_schematic():
    circuit = Circuit(ylim=(0, 6.28), height=2.72)
    top, lower, return_y = 5.04, 2.16, .67
    circuit.terminal(.95, top, '输入＋ 12 V', dx=.49, dy=.38)
    circuit.wire((.95, top), (2.55, top))
    circuit.wire((1.67, top), (1.67, lower), (2.55, lower))
    circuit.node(1.67, top)
    circuit.terminal(.95, return_y, '输入－', dy=.38)
    circuit.wire((.95, return_y), (1.67, return_y))
    circuit.ground(1.67, return_y)
    circuit.wire((9.2, lower), (9.2, top), (13.0, top))
    circuit.node(9.2, top)
    circuit.wire((9.2, return_y), (13.0, return_y))
    circuit.cap((9.9, top), (9.9, return_y), r'$C_o$', plus=True)
    circuit.resistor((11.65, top), (11.65, return_y), r'$R_o$ 30 mΩ')
    for x in (9.9, 11.65):
        circuit.node(x, top)
        circuit.node(x, return_y)
    circuit.ground(9.2, return_y)
    circuit.arrow((10.45, 5.49), (11.38, 5.49), r'$i_\Sigma$')
    circuit.terminal(13.0, top, '输出＋ 1.2 V', dx=-.35, dy=.38)
    circuit.terminal(13.0, return_y, '输出－ 0 V', dx=-.40, dy=-.37)
    for phase, rail in (('A', top), ('B', lower)):
        circuit.mos((2.55, rail), (5.55, rail),
                    gate_label=rf'$v_{{\mathrm{{GS,H{phase}}}}}$', label=f'QH{phase}')
        circuit.mos((5.55, rail), (5.55, rail-1.55), label=f'QL{phase}')
        circuit.wire((5.02, rail-.775), (4.74, rail-.775), (4.74, rail-1.18))
        circuit.text(4.74, rail-1.40, rf'$v_{{\mathrm{{GS,L{phase}}}}}$', color=TEAL, fontsize=8.5)
        circuit.ground(5.55, rail-1.55)
        circuit.coil((5.55, rail), (9.2, rail), label=f'L{phase}  300 nH')
        circuit.node(5.55, rail, rf'$v_{{\mathrm{{SW,{phase}}}}}$', dy=.42)
        circuit.arrow((6.71, rail+.85), (8.02, rail+.85), rf'$i_{{L{phase}}}$')
    return circuit.fig


def _track(ax, quantity, unit, ticks, margin=.13):
    ax.set_ylabel(f'{quantity} / {unit}', rotation=0, ha='right', va='center', labelpad=9)
    ax.set_yticks(ticks, [f'{value:g}'.replace('-', '−') for value in ticks])
    span = ticks[-1] - ticks[0]
    ax.set_ylim(ticks[0]-margin*span, ticks[-1]+margin*span)


def _windows(axes, edges, names=None, active=None):
    fills = ('#eaf3f8', '#faf0e8', '#f0f3f4')
    spans = zip(edges, edges[1:]) if active is None else active
    windows = tuple(enumerate(spans))
    for ax in axes:
        ax.set_xlim(edges[0], edges[-1])
        for idx, (start, stop) in windows:
            ax.axvspan(start, stop, facecolor=fills[idx], lw=0, zorder=0)
        for edge in edges[1:-1]:
            ax.axvline(edge, color=MUTED, linewidth=.65, alpha=.56, ls='--')
    if names:
        top = axes[0]
        for (_, (start, stop)), name in zip(windows, names):
            top.text((start+stop)/2, 1.105, name, color=INK, fontsize=8.5,
                     ha='center', va='bottom', transform=top.get_xaxis_transform())
    axes[-1].set_xlabel('时间 / µs')


def _steps(ax, x, levels, *, color=BLUE, ls='-'):
    ax.step(x, [*levels, levels[-1]], where='post', color=color, lw=1.65, ls=ls)


def _device_currents(ax, on_end, release_end, period, valley, peak):
    release_final = valley if release_end == period else 0.0
    ax.plot((0, on_end, on_end, period), (valley, peak, 0, 0), color=BLUE, lw=1.65)
    ax.plot((0, on_end, on_end, release_end, period),
            (0, 0, peak, release_final, 0 if release_end < period else release_final),
            color=ORANGE, lw=1.65, ls='--')
    ax.text(on_end*.55, peak*.75, _IQ, color=BLUE, fontsize=8.5, ha='center')
    ax.text(on_end+(release_end-on_end)*.68, peak*.77, _ID,
            color=ORANGE, fontsize=8.5, ha='center')


def buck_timing():
    fig, axes = timing_page(rows=4, height=4.22)
    _windows(axes, (0, 5, 10), ('Q1 导通', 'D1 续流'))
    axes[-1].set_xticks((0, 2.5, 5, 7.5, 10))
    _steps(axes[0], (0, 5, 10), (_GATE_HIGH, 0))
    _track(axes[0], _GATE, 'V', [0, 8])
    _steps(axes[1], (0, 5, 10), (24, 0))
    _track(axes[1], _SW, 'V', [0, 24])
    axes[2].plot((0, 5, 10), (.5, 3.5, .5), color=TEAL, lw=1.65)
    _track(axes[2], _IL, 'A', [.5, 2, 3.5])
    _device_currents(axes[3], 5, 10, 10, .5, 3.5)
    _track(axes[3], f'{_IQ}，{_ID}', 'A', [0, 3.5])
    return fig


def _dcm_timing(edges, switch_voltage, peak, blocking=None):
    fig, axes = timing_page(rows=4 if blocking is None else 5, height=4.22)
    _windows(axes, edges, ('Q1 导通', 'D1 传能', '零电流驻留'))
    axes[-1].set_xticks(edges, [f'{edge:.3f}'.rstrip('0').rstrip('.') for edge in edges])
    _steps(axes[0], edges, (_GATE_HIGH, 0, 0))
    _track(axes[0], _GATE, 'V', [0, 8])
    _steps(axes[1], edges, switch_voltage)
    _track(axes[1], _SW, 'V', sorted(switch_voltage))
    if blocking is not None:
        _steps(axes[2], edges, blocking)
        _track(axes[2], r'$v_\mathrm{DS}$', 'V', sorted(blocking))
    axes[-2].plot(edges, (0, peak, 0, 0), color=TEAL, lw=1.65)
    rounded_peak = round(peak, 3)
    _track(axes[-2], _IL, 'A', [0, rounded_peak])
    _device_currents(axes[-1], edges[1], edges[2], edges[3], 0, peak)
    _track(axes[-1], f'{_IQ}，{_ID}', 'A', [0, rounded_peak])
    return fig


def boost_timing():
    on_end = 10 / np.sqrt(8)
    return _dcm_timing((0, on_end, 2*on_end, 10), (0, 24, 12), .6*on_end)


def inverting_timing():
    return _dcm_timing((0, 2.5, 5, 10), (12, -12, 0), 1.5, blocking=(0, 24, 12))


def multiphase_timing():
    fig, axes = timing_page(rows=5, height=4.22)
    edges = (0, .20, 1.0, 1.20, 2.0)
    _windows(axes, edges, ('A 相开通', 'B 相开通'), active=((0, .20), (1.0, 1.20)))
    axes[-1].set_xticks(edges)
    for on, color, style in (((1, 0, 0, 0), BLUE, '-'), ((0, 0, 1, 0), ORANGE, '--')):
        _steps(axes[0], edges, [_GATE_HIGH * value for value in on], color=color, ls=style)
        _steps(axes[1], edges, [_GATE_HIGH * (1 - value) for value in on], color=color, ls=style)
        _steps(axes[2], edges, [12 * value for value in on], color=color, ls=style)
    _track(axes[0], r'$v_\mathrm{GS,H}$', 'V', [0, 8])
    _track(axes[1], r'$v_\mathrm{GS,L}$', 'V', [0, 8])
    _track(axes[2], _SW, 'V', [0, 12])

    time = np.asarray(edges)
    elapsed_a = time % 2
    elapsed_b = (time - 1) % 2
    current_a = np.interp(elapsed_a, (0, .2, 2), (16.4, 23.6, 16.4))
    current_b = np.interp(elapsed_b, (0, .2, 2), (16.4, 23.6, 16.4))
    axes[3].plot(time, current_a, color=BLUE, lw=1.65)
    axes[3].plot(time, current_b, color=ORANGE, lw=1.65, ls='--')
    _track(axes[3], _IL, 'A', [16.4, 23.6])
    axes[4].plot(time, current_a+current_b, color=TEAL, lw=1.65)
    _track(axes[4], r'$i_\Sigma$', 'A', [36.8, 43.2])
    return fig


PLATES = {
    'buck': (
        'Buck 降压',
        '以 24 V 输入、12 V／2 A 输出的理想连续导电工况为例。先看开关节点在两种状态下接到哪里，再从波形量取 5 µs 上升段与续流段。两段电感电流都流向输出。',
        buck_schematic,
        'Buck 的主开关与续流支路。D1 阳极接公共 0 V，门极电压按 Q1 的栅极对源极测量。',
        buck_timing,
        'Buck 的一个 100 kHz 周期。电感电流在 0.5–3.5 A 之间变化，开通时由 Q1 承担，关断时换至 D1。门极 0／8 V 为示意。',
        2,
    ),
    'boost': (
        'Boost 升压',
        '以 12 V 输入、24 V／0.375 A 输出的理想断续导电工况为例。先沿输入找串联电感，再区分开通储能、关断传能和零电流驻留。只有 D1 导通时才向输出注入电流。',
        boost_schematic,
        'Boost 的低侧主开关与串联输出整流支路。开关节点电压对公共 0 V 测量。',
        boost_timing,
        'Boost 的一个 100 kHz 周期。电流在 3.536 µs 达 2.121 A，于 7.071 µs 回零。门极 0／8 V 为示意，开关节点驻留在 12 V。',
        2,
    ),
    'buck_boost': (
        '反相 Buck-Boost',
        '以 12 V 输入、−12 V 输出、0.1875 A 负载的理想断续导电工况为例。先认清输出正端与输入负端共地，再用下图的开关节点和漏源电压，辨认整流传能与回零驻留。',
        inverting_schematic,
        '反相输出的电容正极接公共 0 V。D1 的阳极接 −12 V 端，整流电流由输出负端流向开关节点。',
        inverting_timing,
        '反相 Buck-Boost 的一个 100 kHz 周期。D1 在 2.5–5 µs 传能，Q1 此段阻断 24 V。门极 0／8 V 为示意。',
        2,
    ),
    'multiphase_buck': (
        '双相同步 Buck（COT）',
        '以 12 V 输入、1.2 V／40 A 输出的理想双相交错工况为例。先找两个独立开关节点和共享的输出端，再对齐两相的定时脉冲、电感电流与总电流，观察输出电容看到的纹波。',
        multiphase_schematic,
        '双相同步 Buck 功率级。每相上管驱动以本相开关节点为参考，下管驱动以公共 0 V 为参考。',
        multiphase_timing,
        '每相 500 kHz、导通 0.20 µs，相位间隔 1 µs。A 相为蓝色实线，B 相为橙色虚线。门极 0／8 V 为示意，理想互补驱动省略死区。',
        6,
    ),
}
