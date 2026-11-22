"""Introductory circuits and synchronized waveforms for isolated topologies."""

import json
from pathlib import Path

import numpy as np

from .visio_circuit import BLUE, MUTED, ORANGE, TEAL, Circuit, timing_page


def _input(circuit, high, low, primary, with_block=False):
    left, capacitor = .58, 1.55
    circuit.terminal(left, high, 'Vin+' if with_block else 'Vbus+', dy=.40)
    circuit.terminal(left, low, 'PGND', dy=-.35)
    circuit.wire((left, low), (primary, low))
    if with_block:
        circuit.wire((left, high), (.78, high))
        circuit.diode((.78, high), (2.23, high), 'D_IN')
        capacitor = 2.33
        circuit.wire((2.23, high), (primary, high))
        circuit.node(capacitor, high, 'Vbus', dx=.26, dy=.39)
    else:
        circuit.wire((left, high), (primary, high))
        circuit.node(capacitor, high)
    circuit.cap((capacitor, high), (capacitor, low), plus=True)
    circuit.text(capacitor-.32, (high+low)/2-.27, 'Cin', ha='right')
    circuit.node(capacitor, low)


def _rcd(circuit, bus, drain, primary, left=2.62, right=3.92):
    clamp = bus-1.41
    diode = (left+right)/2
    circuit.resistor((left, bus), (left, clamp))
    circuit.cap((right, clamp), (right, bus), plus=True)
    circuit.text(left-.28, (bus+clamp)/2, 'Rcl', ha='right')
    circuit.text(right+.36, (bus+clamp)/2, 'Ccl', ha='left')
    circuit.wire((left, clamp), (right, clamp))
    circuit.diode((diode, drain), (diode, clamp))
    circuit.text(diode+.36, (drain+clamp)/2, 'Dcl', ha='left')
    circuit.wire((diode, drain), (primary, drain))
    for x, y in ((left, bus), (right, bus), (diode, clamp)):
        circuit.node(x, y)


def _secondary_load(circuit, high, low, start, cap, load, terminal, tag='', block=False):
    circuit.cap((cap, high), (cap, low), plus=True)
    circuit.text(cap-.34, (high+low)/2-.24, f'C{tag}' if tag else 'Co', ha='right')
    circuit.wire((start, high), (cap, high))
    if block:
        circuit.diode((cap, high), (load, high), f'DB{tag}')
    else:
        circuit.wire((cap, high), (load, high))
    circuit.wire((load, high), (terminal, high))
    circuit.resistor((load, high), (load, low))
    circuit.text(load+.34, (high+low)/2-.10, f'R{tag}' if tag else 'Ro', ha='left')
    circuit.wire((start, low), (terminal, low))
    circuit.node(cap, high)
    circuit.node(cap, low)
    circuit.node(load, high)
    circuit.node(load, low)
    circuit.terminal(terminal, high, f'OUT{tag}+' if tag else 'Vo+', dy=.4)
    if tag:
        circuit.terminal(terminal, low, '−', dx=.35, dy=0)
    else:
        circuit.terminal(terminal, low, 'Vo−', dy=-.36)


def _single_flyback(qr=False):
    c = Circuit(ylim=(0, 6.36))
    low, high, drain = .76, 5.43, 2.48
    xp, xs = 5.24, 7.17
    _input(c, high, low, xp)
    _rcd(c, high, drain, xp)
    c.transformer((xp, high), (xp, 2.89), (xs, high), (xs, 2.89),
                  label='T1', secondary_dot_top=False)
    c.wire((xp, 2.89), (xp, drain))
    c.mos((xp, drain), (xp, low), 'G1', None if qr else 'Q1')
    c.node(xp, drain, 'D', dx=.28, dy=.24)
    c.node(xp, low, 'S', dx=.26, dy=-.25)
    c.diode((xs, high), (9.23, high), 'D1')
    c.arrow((9.28, high+.39), (10.18, high+.39), '$i_{D1}$')
    c.wire((xs, 2.89), (xs, low), (9.23, low))
    _secondary_load(c, high, low, 9.23, 10.24, 12.10, 13.41)
    if qr:
        c.text(4.75, 1.05, 'Q1', ha='right')
        c.cap((3.94, drain), (3.94, low))
        c.text(3.60, (drain+low)/2-.25, 'Ce', ha='right')
        c.node(3.94, drain)
        c.node(3.94, low)
        # The detection winding shares the core and returns to primary ground.
        c.coil((6.05, 2.10), (6.05, low), flip=True)
        core_x = (xp+xs)/2
        for x in (core_x-.06, core_x+.06):
            c.wire((x, 3.31), (x, 1.10), color=MUTED, lw=1)
        c.wire((xp, low), (6.05, low))
        c.node(6.05, low)
        c.node(5.81, 1.00)
        c.terminal(6.05, 2.10)
        c.text(5.95, 2.20, 'ZCD', ha='right', color=TEAL, fontsize=8.3)
    return c.fig


def flyback_schematic():
    return _single_flyback()


def qr_schematic():
    return _single_flyback(qr=True)


def multi_schematic():
    c = Circuit(xlim=(0, 14), ylim=(0, 7.8), height=2.85)
    low, high, drain = .75, 6.84, 2.97
    xp, xs = 5.04, 7.01
    _input(c, high, low, xp, with_block=True)
    _rcd(c, high, drain, xp, left=3.02, right=4.15)
    c.coil((xp, high), (xp, drain), flip=True)
    c.node(xp+.32, 6.19)
    c.node(xp, drain, 'D', dx=.24, dy=.30)
    c.mos((xp, drain), (xp, 1.63), 'G1', 'Q1')
    c.node(xp, 1.63, 'S', dx=.26, dy=.10)
    c.resistor((xp, 1.63), (xp, low), 'Rs')
    for x in (5.97, 6.14):
        c.wire((x, .83), (x, high), color=MUTED, lw=1)
    c.text(5.72, 7.22, 'T1')
    c.text(xp-.35, 5.44, '6 匝', ha='right', fontsize=8.3)
    for tag, turns, plus in ((1, 12, high), (2, 5, 4.75), (3, 2, 2.66)):
        minus = plus-1.31
        c.coil((xs, plus), (xs, minus))
        c.node(xs-.29, minus+.12)
        c.text(xs+.38, (plus+minus)/2, f'{turns} 匝', ha='left', fontsize=8.2)
        c.diode((xs, plus), (8.88, plus), f'D{tag}')
        c.wire((xs, minus), (8.88, minus))
        _secondary_load(c, plus, minus, 8.88, 9.55, 12.05, 13.34, str(tag), block=True)
    c.wire((9.55, high), (9.55, high+.43), color=TEAL, ls='--', lw=1.0)
    c.text(9.55, high+.64, 'SSR 取样', color=TEAL, fontsize=8.4)
    return c.fig


def acf_schematic():
    c = Circuit(ylim=(0, 6.36))
    low, high, drain = .76, 5.43, 2.69
    xp, xs, aux, vx = 5.24, 7.20, 3.38, 9.08
    _input(c, high, low, xp)
    c.transformer((xp, high), (xp, 3.05), (xs, high), (xs, 3.05))
    c.wire((xp, 3.05), (xp, drain))
    c.mos((xp, drain), (xp, low), 'G1', 'Q1 (N)')
    c.node(xp, drain, 'D', dx=.25, dy=.20)
    c.node(xp, low, 'S', dx=.25, dy=-.25)
    c.text(4.48, 4.22, '$v_p$', color=BLUE)
    c.text(4.48, 4.63, '+', color=BLUE)
    c.text(4.48, 3.80, '−', color=BLUE)
    c.wire((xp, drain), (aux, drain))
    c.cap((aux, drain), (aux, 1.79), plus=True)
    c.text(aux+.35, 2.24, 'Ccl', ha='left')
    c.mos((aux, 1.79), (aux, low), 'G2', 'Q2 (P)', p_channel=True)
    c.node(aux, low)
    c.diode((xs, high), (vx, high), 'D1')
    c.wire((xs, 3.05), (xs, low), (10.95, low))
    c.diode((vx, low), (vx, high))
    c.text(vx-.34, 3.10, 'D2', ha='right')
    c.node(vx, low)
    c.node(vx, high, 'X', dx=.29, dy=-.36)
    c.coil((vx, high), (10.95, high), 'Lo')
    c.arrow((9.62, high-.62), (10.55, high-.62), '$i_L$')
    _secondary_load(c, high, low, 10.95, 11.43, 12.59, 13.52)
    return c.fig


def _timing(ticks, spans, rows=4):
    fig, axes = timing_page(rows=rows)
    fig.set_layout_engine('constrained', hspace=.035)
    for ax in axes:
        for index, (start, stop, _) in enumerate(spans):
            ax.axvspan(start, stop, color=('#edf5fa', '#edf6f3', '#f8f0e9', '#edf5fa')[index],
                       lw=0, zorder=0)
        for _, stop, _ in spans[:-1]:
            ax.axvline(stop, color=MUTED, ls=(0, (2, 2)), alpha=.65, lw=.8)
        ax.axhline(0, color=MUTED, lw=.6, alpha=.65)
        ax.set_xlim(spans[0][0], spans[-1][1])
    for start, stop, label in spans:
        if label:
            axes[0].text((start+stop)/2, 1.03, label, transform=axes[0].get_xaxis_transform(),
                         ha='center', va='bottom', color=BLUE, fontsize=9)
    axes[-1].set(xticks=ticks, xlabel='同一时间轴  t / µs')
    return fig, axes


def _drive(ax, edges, states):
    ax.step(edges, states, where='post', color=BLUE, lw=1.65)
    ax.set(ylabel='Q1 驱动', yticks=[0, 1], yticklabels=['关', '开'], ylim=(-.24, 1.27))


def flyback_timing():
    ton, demag_end, period = 2, 4, 10
    fig, ax = _timing([0, 2, 4, 6, 8, 10],
                      [(0, ton, 'Q1 储能'), (ton, demag_end, 'D1 传能'),
                       (demag_end, period, '断续驻留')])
    _drive(ax[0], [0, ton, period], [1, 0, 0])
    ax[1].step([0, ton, demag_end, period], [0, 48, 24, 24], where='post', color=TEAL)
    ax[1].set(ylabel=r'$v_{DS}$ / V', yticks=[0, 24, 48], ylim=(-6, 57))
    ax[2].plot([0, ton, ton, period], [0, 1, 0, 0], color=BLUE)
    ax[2].set(ylabel=r'$i_{Q1}$ / A', yticks=[0, 1], ylim=(-.12, 1.24))
    ax[3].plot([0, ton, ton, demag_end, period], [0, 0, 2, 0, 0], color=ORANGE)
    ax[3].set(ylabel=r'$i_{D1}$ / A', yticks=[0, 1, 2], ylim=(-.24, 2.4))
    fig.align_ylabels()
    return fig


def _first_valley():
    bus, reflected, lm, ce, power = 300, 120, 800, 100, 100
    # Here microhenries and microseconds keep V·µs/µH in amperes.
    wait = np.pi*np.sqrt(lm*1e-6*ce*1e-12)*1e6
    a = lm*(1/bus+1/reflected)
    peak = (power*a+np.sqrt((power*a)**2+2*lm*power*wait))/lm
    on = lm*peak/bus
    demag = lm*peak/reflected
    return bus, reflected, peak, on, on+demag, on+demag+wait


def qr_timing():
    bus, reflected, peak, ton, demag_end, period = _first_valley()
    stop = period+1.48
    fig, ax = _timing([0, 5, 10, 15, 20, period],
                      [(0, ton, 'Q1 储能'), (ton, demag_end, 'D1 传能'),
                       (demag_end, period, ''), (period, stop, '')])
    ax[-1].set_xticklabels(['0', '5', '10', '15', '20', f'{period:.2f}'])
    _drive(ax[0], [0, ton, period, stop], [1, 0, 1, 1])
    tr = np.linspace(demag_end, period, 145)
    ring = bus+reflected*np.cos(np.pi*(tr-demag_end)/(period-demag_end))
    ax[1].plot([0, ton, ton, demag_end], [0, 0, bus+reflected, bus+reflected], color=TEAL)
    ax[1].plot(tr, ring, color=ORANGE, lw=2)
    ax[1].plot([period, period, stop], [ring[-1], 0, 0], color=TEAL)
    ax[1].plot(period, ring[-1], 'o', color=ORANGE, ms=4.5)
    ax[1].set(ylabel=r'$v_{DS}$ / V', yticks=[0, 180, 420], ylim=(-40, 510))
    ax[1].annotate('退磁后的首谷 180 V', (period, ring[-1]), xytext=(period-1.6, 170),
                   ha='right', va='center', fontsize=8.5, color=ORANGE,
                   arrowprops=dict(arrowstyle='->', color=ORANGE))
    ax[2].plot([0, ton, ton, period, stop], [0, peak, 0, 0, peak*(stop-period)/ton], color=BLUE)
    ax[2].set(ylabel=r'$i_{Q1}$ / A', yticks=[0, 1, 2], ylim=(-.28, 3.07))
    ax[3].plot([0, ton, ton, demag_end, stop], [0, 0, 2*peak, 0, 0], color=ORANGE)
    ax[3].set(ylabel=r'$i_{D1}$ / A', yticks=[0, 2, 4], ylim=(-.51, 5.89))
    ax[3].annotate('D1 归零', (demag_end, 0), xytext=(demag_end-2.1, 2.8),
                   ha='right', va='center', fontsize=8.4, color=ORANGE,
                   arrowprops=dict(arrowstyle='->', color=ORANGE))
    fig.align_ylabels()
    return fig


def _x004():
    from analysis_workflows import pin_hardware
    from design_api import load_spec
    from loss_model import compute_design
    from power_stage import compute_operating_point

    path = Path(__file__).resolve().parents[2]/'examples'/'3_OUTPUT_CROSS_REGULATION.json'
    parameters = load_spec(json.loads(path.read_text(encoding='utf-8-sig')))
    parameters.update(V_in=20.0, input_voltage_case='min')
    fixed = pin_hardware(parameters, compute_design(parameters))
    powers = (30.0, .05, .95)
    for rail, power in zip(fixed['outputs'], powers):
        rail.update(P_out=power, P_out_min=min(rail['P_out_min'], power))
    fixed['P_out'] = sum(powers)
    return compute_operating_point(fixed)


def multi_timing():
    point = _x004()
    solution = point['coupled_solution']
    t = solution['t']*1e6
    period = point['Ts']*1e6
    ton = point['D']*period
    fig, ax = _timing([0, 1, 2, 3, 4], [(0, ton, 'Q1 导通'), (ton, period, '各副边独立传能')], rows=5)
    _drive(ax[0], [0, ton, period], [1, 0, 0])
    ax[1].plot(t, solution['v_sw'], color=TEAL)
    ax[1].set(ylabel=r'$v_{DS}$ / V', yticks=[0, 20, 40], ylim=(-5, 51))
    ax[2].plot(t, solution['i_sw'], color=BLUE)
    ax[2].set(ylabel=r'$i_{Q1}$ / A', yticks=[0, 3, 6], ylim=(-.75, 7.45))
    i_d1, i_d2, i_d3 = solution['i_winding'][1:]
    ax[3].plot(t, i_d1, color=BLUE, lw=1.58)
    ax[3].plot(t, i_d3, color=ORANGE, lw=1.58)
    ax[3].text(2.34, 3.68, r'$i_{D1}$', color=BLUE, ha='left', fontsize=8.6)
    peak_d3 = np.argmax(i_d3)
    ax[3].annotate(r'$i_{D3}$', (t[peak_d3], i_d3[peak_d3]), xytext=(2.34, 6.2), fontsize=8.6, color=ORANGE,
                   arrowprops=dict(arrowstyle='-', color=ORANGE))
    ax[3].set(ylabel='整流 / A', yticks=[0, 4, 8], ylim=(-.88, 8.9))
    ax[4].plot(t, i_d2, color=ORANGE, lw=1.68)
    ax[4].set(ylabel=r'$i_{D2}$ / A', yticks=[0, .3, .6], ylim=(-.12, .78))
    peak = np.argmax(i_d2)
    stop = t[np.flatnonzero(i_d2 > 1e-9)[-1]+1]
    ax[4].annotate(f'OUT2 补电约 {(stop-ton)*1e3:.1f} ns', (t[peak], i_d2[peak]), xytext=(2.34, .55),
                   ha='left', va='center', fontsize=8.3, color=ORANGE,
                   arrowprops=dict(arrowstyle='->', color=ORANGE))
    fig.align_ylabels()
    return fig


def acf_timing():
    period, bus, equivalent, n = 4, 30, 30/.93, .5
    main_voltage = bus/n
    ton = period*equivalent/main_voltage
    reset = bus*ton/(period-ton)
    dead = .08
    imag_peak = bus*ton/(2*220)
    average_il = 40/30
    amplitude_il = (main_voltage-equivalent)*ton/(2*68)
    lo, hi = average_il-amplitude_il, average_il+amplitude_il
    fig, ax = _timing([0, 1, 2, 3, 4], [(0, ton, '正向整流与传能'), (ton, period, '磁芯复位与输出续流')])
    ax[0].step([0, ton, period], [10, 0, 0], where='post', color=BLUE, label=r'$v_{GS1}$')
    ax[0].step([0, ton+dead, period-dead, period], [0, -10, 0, 0], where='post', color=ORANGE,
               label=r'$v_{GS2}$')
    for left, right in ((ton, ton+dead), (period-dead, period)):
        ax[0].axvspan(left, right, color='#edcfb9', alpha=.65, lw=0)
    ax[0].text(ton+.18, 8, '死区 80 ns', color=ORANGE, fontsize=8.2, va='center')
    ax[0].legend(loc='lower left', ncol=2, handlelength=1.6, borderaxespad=.12)
    ax[0].set(ylabel='栅源 / V', yticks=[-10, 0, 10], ylim=(-15, 15))
    ax[1].step([0, ton, period], [bus, -reset, -reset], where='post', color=ORANGE, label=r'$v_p$')
    ax[1].step([0, ton, period], [0, bus+reset, bus+reset], where='post', color=TEAL, label=r'$v_{DS1}$')
    ax[1].legend(loc='center right', ncol=2, handlelength=1.6, borderaxespad=.18)
    ax[1].set(ylabel='原边 / V', yticks=[-35, 0, 30, 65], ylim=(-49, 78))
    ax[2].plot([0, ton, period], [-imag_peak, imag_peak, -imag_peak], color=ORANGE)
    ax[2].set(ylabel=r'$i_m$ / A', yticks=[-.15, 0, .15], ylim=(-.20, .2))
    ax[3].plot([0, ton, period], [lo, hi, lo], color=BLUE, lw=2.5, label=r'$i_L$')
    ax[3].plot([0, ton, ton, period], [lo, hi, 0, 0], ls='--', color=ORANGE, lw=1.4, label=r'$i_{D1}$')
    ax[3].plot([0, ton, ton, period], [0, 0, hi, lo], ls='--', color=TEAL, lw=1.4, label=r'$i_{D2}$')
    ax[3].legend(loc='lower right', ncol=3, handlelength=1.6, borderaxespad=.13)
    ax[3].set(ylabel='副边 / A', yticks=[0, 1, 2], ylim=(-.20, 2.2))
    fig.align_ylabels()
    return fig


PLATES = {
    'flyback': (
        '定频反激',
        '以 24 V 母线、12 V／2.4 W 输出、100 kHz 的理想断续工况为例。先找原边母线侧与副边回流侧的同名端，再沿同一时间轴读 Q1 储能、D1 传能和两管电流均为零的驻留段。',
        flyback_schematic, '定频反激功率级。Dcl 从漏极向钳位支路导通，Rcl 与 Ccl 并联回到母线正端。',
        flyback_timing, '定频反激的断续周期。漏极电压以 Q1 源极为基准，忽略漏感尖峰和驻留振铃。',
        3,
    ),
    'qr_flyback': (
        '准谐振反激',
        '母线 300 V、反射电压 120 V、传输 100 W，匝比 2∶1，励磁电感 800 µH，等效漏极电容 100 pF。先分辨漏感钳位与退磁检测绕组，再看 D1 归零后漏极电压怎样进入首谷。',
        qr_schematic, '准谐振反激功率级。Cₑ 表示折算到漏极的有效电容，辅助绕组提供退磁检测信号。',
        qr_timing, '首谷开通的名义周期。模型忽略关断尖峰及谷底开通时的电容放电脉冲。',
        3,
    ),
    'multi_flyback': (
        '三路输出反激',
        '沿第 4 章 X004 工况读图。输入端 20 V、防反后 19.2 V，三路负载按 30、0.05、0.95 W 换算。先认唯一的 OUT1 电容端取样，再看三路整流电流的导通区与周期电荷。',
        multi_schematic, '三路反激的独立整流、滤波与防反。OUT1 防反管前的电容节点接入隔离反馈。',
        multi_timing, 'X004 的 RL 周期解。OUT2 整流脉冲用独立的安培刻度，开关关断后约 63.8 ns 内完成补电。',
        4,
    ),
    'acf_forward': (
        '低侧有源钳位正激',
        '取 30 V 到 30 V／40 W、250 kHz 的连续工况。先辨 Ccl 与 P 沟道辅助管的低侧复位支路，再沿时间轴读主辅驱动、原边正负伏秒，以及输出电感在 D1 与 D2 之间换流。',
        acf_schematic, '低侧钳位正激。D1 接变压器同名端，D2 从次级回流端向输出电感续流。',
        acf_timing, '栅压为示意值，两管有 80 ns 死区。功率波形采用第 5 章的理想换流与固定复位电压近似。',
        5,
    ),
}
