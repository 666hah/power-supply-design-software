"""Inline figures for the derivation of power-stage and feedback models."""

import numpy as np
from matplotlib.patches import Arc, Circle, Polygon, Rectangle
from scipy.signal import TransferFunction, step

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


FIGURES = {}


def book_figure(key, title, caption):
    def register(draw):
        FIGURES[f'ctl_{key}'] = draw, title, caption
        return draw

    return register


def plots(rows=1, cols=1, *, sharex=False, height=4.55):
    fig = figure(height=height)
    axes = fig.subplots(rows, cols, squeeze=False, sharex=sharex).ravel()
    for ax in axes:
        ax.grid(True, color=MUTED, alpha=.15)
        ax.set_axisbelow(True)
    return fig, axes


def diagram(ax, xlim=(0, 11), ylim=(0, 3.25)):
    ax.set(xlim=xlim, ylim=ylim)
    ax.axis('off')


def wire(ax, points, color=MUTED, **kwargs):
    ax.plot(*zip(*points), color=color, lw=1.5, **kwargs)


def arrow(ax, start, end, color=INK):
    ax.annotate('', end, start, arrowprops=dict(arrowstyle='-|>', lw=1.5,
                                               color=color, shrinkA=0, shrinkB=0))


def block(ax, x, y, w, label, color=BLUE, height=.60):
    ax.add_patch(Rectangle((x, y-height/2), w, height, ec=color, fc='white', lw=1.3, zorder=3))
    ax.text(x+w/2, y, label, va='center', ha='center', color=color, zorder=4)


def node(ax, x, y, text=None, color=INK):
    ax.plot(x, y, '.', ms=8, color=color, zorder=5)
    if text:
        ax.text(x, y+.19, text, va='bottom', ha='center', color=color)


def lanes(ax, entries, y, color=BLUE):
    for x, width, label in entries:
        block(ax, x, y, width, label, color)
    for first, second in zip(entries, entries[1:]):
        arrow(ax, (first[0]+first[1], y), (second[0], y), color)


def reference(ax, x, y):
    for width, drop in [(.36, 0), (.23, .075), (.11, .15)]:
        wire(ax, [(x-width/2, y-drop), (x+width/2, y-drop)], INK)


def coil(ax, x, y, span=1.32, color=INK):
    for offset in (0.125, 0.375, 0.625, 0.875):
        ax.add_patch(Arc((x+offset*span, y), span/4, .35, theta1=0, theta2=180,
                         color=color, lw=1.5))


def diode(ax, x, y, color=INK):
    ax.add_patch(Polygon([(x-.19, y-.13), (x-.19, y+.13), (x+.12, y)],
                         closed=True, ec=color, fc='white', lw=1.5))
    wire(ax, [(x+.12, y-.16), (x+.12, y+.16)], color)


def output_branch(ax, x, y, bottom, color=INK):
    midpoint = (y+bottom)/2
    wire(ax, [(x, y), (x, midpoint+.08)], color)
    wire(ax, [(x-.24, midpoint+.08), (x+.24, midpoint+.08)], color)
    wire(ax, [(x-.24, midpoint-.08), (x+.24, midpoint-.08)], color)
    wire(ax, [(x, midpoint-.08), (x, bottom)], color)
    ax.text(x-.35, midpoint, 'C', ha='right', va='center', color=color)
    wire(ax, [(x+1.36, y), (x+1.36, midpoint+.30)], color)
    ax.add_patch(Rectangle((x+1.24, midpoint-.30), .24, .60, ec=color, fc='white', lw=1.5))
    wire(ax, [(x+1.36, midpoint-.30), (x+1.36, bottom)], color)
    ax.text(x+1.66, midpoint, 'R', ha='left', va='center', color=color)


@book_figure('buck_first_charge', '从关断边沿差积分到首周期电容充电',
             '灰线是标称关断，橙线是扰动后关断。下图阴影为 226.6 nC，只在首周期冻结端电压时成立。')
def buck_first_charge():
    fig, (voltage, current) = plots(2, sharex=True)
    edges = [0, 1.60, 1.68, 4]
    voltage.stairs([0, 12, 0], edges, color=BLUE, fill=True, alpha=.35)
    voltage.set(ylabel='差电感电压 / V', ylim=(-1, 14))
    panel_label(voltage, '先找仍处于高侧开通的 80 ns')
    current.plot(edges, [0, 0, 96, 96], color=ORANGE)
    current.fill_between(edges, [0, 0, 96, 96], color=ORANGE, alpha=.18)
    current.set(xlabel='周期内时刻 / µs', ylabel='差电感电流 / mA', xlim=(0, 4), ylim=(-3, 119))
    current.text(2.72, 43, '续流段积累电荷', ha='center', color=ORANGE)
    panel_label(current, '再用差电流曲线下的面积估算充电量')
    for ax in (voltage, current):
        ax.axvline(1.60, color=MUTED, ls='--', lw=.9)
        ax.axvline(1.68, color=ORANGE, ls=':', lw=1.2)
    return fig


@book_figure('buck_paths', 'Buck 的两种开关位置与同一个输出节点',
             '导通与续流均保留 L 到输出的路径。选输出节点流入为正，电容和负载电流取向下。')
def buck_paths():
    fig = figure(height=4.55)
    for ax, on in zip(fig.subplots(2), (True, False)):
        diagram(ax)
        path_color = BLUE if on else TEAL
        panel_label(ax, '高侧导通  ·  电感端电压 Vg − v' if on else '低侧续流  ·  电感端电压 −v')
        block(ax, .40, 2.05, 1.16, '输入 Vg')
        wire(ax, [(1.56, 2.05), (2.47, 2.05)], BLUE if on else MUTED)
        wire(ax, [(2.47, 2.05), (3.50, 2.05 if on else 2.40)], BLUE if on else MUTED)
        node(ax, 3.50, 2.05, 'SW')
        wire(ax, [(3.50, 2.05), (4.70, 2.05)], path_color)
        wire(ax, [(3.50, 2.05), (3.50, 1.40)], TEAL if not on else MUTED)
        wire(ax, [(3.50, 1.40), (3.50 if not on else 3.91, .91)], TEAL if not on else MUTED)
        wire(ax, [(3.50, .91), (3.50, .46), (9.42, .46)], TEAL if not on else MUTED)
        coil(ax, 4.70, 2.05, color=path_color)
        ax.text(5.35, 2.36, 'L', ha='center')
        wire(ax, [(6.02, 2.05), (9.42, 2.05)], path_color)
        arrow(ax, (6.09, 2.28), (7.26, 2.28), path_color)
        ax.text(6.71, 2.53, '电感电流 i', ha='center', color=path_color)
        node(ax, 8.06, 2.05, '电容端 v')
        output_branch(ax, 8.06, 2.05, .46)
        reference(ax, 3.50, .46)
    return fig


@book_figure('buck_lc_response', 'Buck 二阶分母的电阻阻尼',
             'R 改变虚部和共振幅值。5.03 kHz 竖线上的两点直接用 20 log₁₀(10Q) 求得。')
def buck_lc_response():
    fig, axes = plots(2, sharex=True)
    magnitude, phase = axes
    f = np.geomspace(300, 50000, 500)
    f0 = 1/(2*np.pi*np.sqrt(10e-6*100e-6))
    for load, color in [(2., BLUE), (.5, ORANGE)]:
        quality = load*np.sqrt(100e-6/10e-6)
        response = 10/(1-(f/f0)**2+1j*f/(f0*quality))
        magnitude.semilogx(f/1e3, 20*np.log10(np.abs(response)), color=color, label=f'R = {load:g} Ω')
        phase.semilogx(f/1e3, np.angle(response, deg=True), color=color)
        value = 20*np.log10(10*quality)
        magnitude.plot(f0/1e3, value, 'o', color=color)
        magnitude.annotate(f'{value:.2f} dB', (f0/1e3, value), xytext=(10, 2),
                           textcoords='offset points', color=color)
    for ax in axes:
        ax.axvline(f0/1e3, color=MUTED, ls=':', lw=1)
    magnitude.set(ylabel='幅值 / dB')
    magnitude.legend(loc='lower left')
    phase.set(xlabel='扰动频率 / kHz', ylabel='相位 / °', yticks=[-180, -135, -90, -45, 0])
    return fig


@book_figure('boost_paths', 'Boost 充磁与整流供能的两条路径',
             '蓝色充磁回路到 SW 后经过开关回流，绿色送能路径经过整流管到输出。关断占比 q 改变后者的权重。')
def boost_paths():
    fig = figure(height=4.55)
    for ax, on in zip(fig.subplots(2), (True, False)):
        diagram(ax)
        panel_label(ax, '充磁段  ·  整流管截止' if on else '送能段  ·  整流管导通')
        active = BLUE if on else TEAL
        side = MUTED if on else TEAL
        block(ax, .42, 2.12, 1.15, '输入 Vg')
        wire(ax, [(1.57, 2.12), (2.35, 2.12)], active)
        coil(ax, 2.35, 2.12, color=active)
        ax.text(3.01, 2.43, 'L', ha='center', color=active)
        wire(ax, [(3.67, 2.12), (4.68, 2.12)], active)
        node(ax, 4.68, 2.12, 'SW')
        wire(ax, [(4.68, 2.12), (4.68, 1.51), (4.68 if on else 5.14, .87)], BLUE if on else MUTED)
        wire(ax, [(4.68, .87), (4.68, .50)], BLUE if on else MUTED)
        wire(ax, [(4.68, 2.12), (6.04, 2.12)], side)
        diode(ax, 6.23, 2.12, side)
        wire(ax, [(6.35, 2.12), (9.52, 2.12)], side)
        wire(ax, [(4.68, .50), (9.52, .50)], MUTED)
        if on:
            arrow(ax, (5.00, 1.43), (5.00, .74), BLUE)
        else:
            arrow(ax, (6.55, 2.38), (7.66, 2.38), TEAL)
        node(ax, 8.16, 2.12, '输出 v')
        output_branch(ax, 8.16, 2.12, .50)
        reference(ax, 4.68, .50)
    return fig


@book_figure('boost_inverse', 'Boost 的占空比阶跃先向反方向变化',
             '整流注入立即减少，随后增长的电感电流使输出抬高。左端局部放大用于核对初始切线。')
def boost_inverse():
    fig, (full, edge) = plots(2)
    l, c, q, r, u = 100e-6, 100e-6, .5, 12, 24
    plant = TransferFunction([-(u/q)*l/(q*q*r), u/q], [l*c/q**2, l/(q*q*r), 1.])
    t, v = step(plant, T=np.linspace(0, 2600e-6, 2001))
    full.plot(t*1e6, .01*v*1e3, color=BLUE)
    full.axhline(480, color=TEAL, ls='--', lw=1, label='直流极限 +480 mV')
    full.axvspan(0, 105, color=ORANGE, alpha=.12)
    full.set(xlabel='占空比上升后的时间 / µs', ylabel='输出变化 / mV', xlim=(0, 2600))
    full.legend(loc='upper right')
    mask = t <= 105e-6
    edge.plot(t[mask]*1e6, 10*v[mask], color=BLUE, label='平均对象')
    edge.plot(t[mask]*1e6, -400*t[mask]*1e3, color=ORANGE, ls='--', label='初始切线 −400 V/s')
    edge.axhline(0, color=MUTED, lw=.7)
    edge.set(xlabel='同一轨迹放大的起始段 / µs', ylabel='输出变化 / mV', xlim=(0, 105))
    edge.legend(loc='lower left')
    return fig


@book_figure('flyback_references', '从反相输出到反激折返的方向约定',
             '上方保留端口的负电压。下方按副边正极性读量，折返电压和副边整流电流都要用同一个 N。')
def flyback_references():
    fig = figure(height=4.55)
    upper, lower = fig.subplots(2)
    for ax in (upper, lower):
        diagram(ax)
    panel_label(upper, '反相 Buck Boost：输出端的测量约定')
    lanes(upper, [(0.35, 2.60, '输出幅值 U > 0'), (4.00, 2.65, '端口方向 vₒ = −U'),
                  (7.83, 2.70, '占空比增加 → vₒ 下降')], y=1.76)
    upper.text(5.5, .79, '改变端口极性只改变传函的整体符号', ha='center', color=MUTED)
    panel_label(lower, '反激关断送能：原边与副边的折返')
    block(lower, .4, 1.70, 2.25, '原边励磁支路')
    block(lower, 8.35, 1.70, 2.25, '副边整流端口', TEAL)
    arrow(lower, (8.35, 2.38), (2.65, 2.38), BLUE)
    arrow(lower, (2.65, 1.06), (8.35, 1.06), TEAL)
    lower.text(5.5, 2.58, '电压折返：Vᵣ = Nv', ha='center', color=BLUE)
    lower.text(5.5, .77, '送能电流：iₛ = Ni', ha='center', color=TEAL)
    lower.text(5.5, 1.72, 'N = Np / Ns', ha='center', color=INK)
    return fig


@book_figure('rhp_phase', '只替换零点符号时的增益和相位',
             '这是零点因子单独作图。相同幅值下，右半平面和左半平面零点分别滞后和超前。')
def rhp_phase():
    fig, (gain, phase) = plots(2, sharex=True)
    f = np.geomspace(4, 300, 401)
    fzero = 1.44*10/(.4*100e-6*2*np.pi*1000)
    responses = [(1-1j*f/fzero, BLUE, '右半平面因子'), (1+1j*f/fzero, ORANGE, '左半平面因子')]
    for response, color, label in responses:
        gain.semilogx(f, 20*np.log10(abs(response)), color=color, label=label,
                      ls='-' if color == BLUE else '--')
        phase.semilogx(f, np.angle(response, deg=True), color=color, label=label)
    for ax in (gain, phase):
        ax.axvline(fzero, color=MUTED, ls=':', lw=1)
    gain.set(ylabel='因子幅值 / dB')
    gain.legend(loc='upper left')
    phase.set(ylabel='因子相位 / °', xlabel='频率 / kHz', yticks=[-90, -45, 0, 45, 90])
    phase.legend(loc='upper left')
    phase.plot([fzero, fzero], [-45, 45], '.', color=INK)
    return fig


@book_figure('pwm_signal_chain', '时钟置位与峰值比较器复位',
             '上面是三段比较信号链。下面的控制锁存器接受时钟与比较器两种事件，并把状态送到功率开关。')
def pwm_signal_chain():
    fig = figure(height=4.55)
    ax = fig.subplots()
    diagram(ax, ylim=(0, 6))
    lanes(ax, [(0.23, 2.21, '开通电流 i(t)'), (3.02, 2.18, '采样增益 Fᵢ'),
               (5.82, 2.18, '相加：Fᵢi + 斜坡'), (8.65, 2.08, '峰值比较器')], y=4.55)
    ax.text(7.00, 5.43, '人工斜坡 Fᵢ mₐt', ha='center', color=ORANGE)
    arrow(ax, (7.0, 5.23), (7.0, 4.85), ORANGE)
    ax.text(9.70, 5.43, '指令 u', ha='center', color=ORANGE)
    arrow(ax, (9.70, 5.23), (9.70, 4.85), ORANGE)
    block(ax, 4.48, 2.35, 2.6, 'RS 锁存器', TEAL)
    wire(ax, [(9.70, 4.25), (9.70, 2.79), (6.42, 2.79)], ORANGE)
    arrow(ax, (6.42, 2.79), (6.42, 2.65), ORANGE)
    ax.text(7.96, 3.01, '达到门限 → 复位 R', ha='center', color=ORANGE)
    block(ax, .53, 2.35, 2.06, '固定周期时钟')
    arrow(ax, (2.59, 2.35), (4.48, 2.35), BLUE)
    ax.text(3.52, 2.58, '置位 S', ha='center', color=BLUE)
    block(ax, 4.48, .75, 2.6, '驱动 → 功率开关', TEAL)
    arrow(ax, (5.78, 2.05), (5.78, 1.05), TEAL)
    return fig


@book_figure('pwm_edge_timing', '初值偏高如何把下一周期初值压低',
             '门限坐标折算为电流。按共同的 3 µs 周期末读数，+0.20 A 变为 −0.10 A。')
def pwm_edge_timing():
    fig, (sense, current) = plots(2, sharex=True)
    t = np.linspace(0, 3, 301)
    for i0, edge, color, label in [(1., 2., BLUE, '标称初值'), (1.2, 1.9, ORANGE, '初值 +0.20 A')]:
        running = t <= edge
        sense.plot(t[running], i0+2*t[running], color=color, label=label)
        current.plot(t, i0+np.minimum(t, edge)-2*np.maximum(0, t-edge), color=color)
        for ax in (sense, current):
            ax.axvline(edge, color=color, ls=':', lw=.9)
        current.plot(3, i0+edge-2*(3-edge), 'o', color=color)
    sense.axhline(5, color=TEAL, ls='--', lw=1, label='比较器等效门限')
    sense.set(ylabel='含补偿的比较量 / A', ylim=(.6, 6.2))
    sense.legend(loc='upper left')
    current.set(xlabel='周期内时刻 / µs', ylabel='电感电流 / A', xlim=(0, 3.11))
    current.text(2.53, 1.16, '末值差 −0.10 A', ha='right', color=ORANGE)
    return fig


@book_figure('dcm_charge_window', '完全退磁的定频周期分成三个时段',
             '副边只有 2–4 µs 的三角面积计入输出；其余时间输出负载由电容维持。')
def dcm_charge_window():
    fig, (primary, secondary) = plots(2, sharex=True)
    primary.plot([0, 2, 2, 10], [0, .48, 0, 0], color=BLUE)
    secondary.plot([0, 2, 2, 4, 10], [0, 0, .96, 0, 0], color=TEAL)
    secondary.fill_between([2, 4], [.96, 0], color=TEAL, alpha=.25)
    for ax in (primary, secondary):
        ax.axvline(2, color=MUTED, ls=':', lw=1)
        ax.axvline(4, color=MUTED, ls=':', lw=1)
    primary.set(ylabel='主开关电流 / A', ylim=(-.04, .60))
    secondary.set(ylabel='副边电流 / A', xlabel='周期内时刻 / µs', xlim=(0, 10), ylim=(-.07, 1.14))
    for x, label in [(1, '充磁'), (3, '送能'), (7, '静置')]:
        primary.text(x, .53, label, ha='center', color=INK)
    secondary.text(3.80, .53, '0.96 µC', color=TEAL)
    return fig


@book_figure('dcm_equilibrium', '整流注入、负载抽取与静态交点',
             '在 12 V 处取切线，注入减少和负载增加构成两份增量电导。下图以 mA 给出净电流。')
def dcm_equilibrium():
    fig, (branches, net) = plots(2)
    v = np.linspace(8, 16, 320)
    branches.plot(v, 12/v, color=BLUE, label='整流注入 12 W / v')
    branches.plot(v, v/12, color=ORANGE, label='电阻负载 v / 12 Ω')
    branches.plot(v, 1-(v-12)/12, color=TEAL, ls='--', label='注入工作点切线')
    branches.plot(12, 1, 'o', color=INK)
    branches.set(xlabel='电容端电压 / V', ylabel='周期平均电流 / A')
    branches.legend(loc='upper center')
    volts = np.linspace(11.78, 12.25, 220)
    net.plot(volts, 1e3*(12/volts-volts/12), color=BLUE)
    net.axhline(0, color=MUTED, lw=.8)
    net.plot(12.12, 1e3*(12/12.12-12.12/12), 'o', color=ORANGE)
    net.annotate('提高 120 mV 后，净注入约 −19.9 mA', (12.12, -19.9), (11.81, -30),
                 arrowprops=dict(arrowstyle='->', color=MUTED))
    net.set(xlabel='交点附近的电容端电压 / V', ylabel='净注入 / mA')
    return fig


@book_figure('cycle_map_reading', '周期切面读终值，周期内积分读平均值',
             '两条幅值示意以同一初值出发，控制改变开关边沿。微分取状态终值之差与输出积分之差。')
def cycle_map_reading():
    fig, (state, avg) = plots(2, sharex=True)
    t = np.linspace(0, 1, 401)
    for edge, color, mark, label in [(.40, BLUE, '-', '命令 u₀−ε'), (.48, ORANGE, '--', '命令 u₀+ε')]:
        y = 1+1.4*np.minimum(t, edge)-.8*np.maximum(0, t-edge)
        state.plot(t, y, color=color, ls=mark, label=label)
        state.plot(1, y[-1], 'o', color=color)
        state.axvline(edge, color=color, ls=':', lw=.9)
        duty_signal = np.where(t <= edge, y, 0.)
        avg.plot(t, duty_signal, color=color, ls=mark)
        avg.fill_between(t, duty_signal, color=color, alpha=.12)
    state.set(ylabel='一维状态示意')
    state.legend(loc='lower center')
    state.text(.81, 1.18, '同一切面读终值', ha='center', color=INK)
    avg.set(xlabel='周期内相对时间 t / Ts', ylabel='输出信号示意', xlim=(0, 1.07))
    avg.text(.67, 1.0, '按两条轨迹各自的面积求 Y', ha='center', color=INK)
    return fig


@book_figure('period_pole_reading', '同模的正周期根与负周期根',
             '误差包络相同，负根引起逐周期的正负交替。下图给出它们在连续等效实轴的位置。')
def period_pole_reading():
    fig, (samples, mapping) = plots(2, height=4.18)
    n = np.arange(9)
    for pole, color, style in [(.8, BLUE, '-'), (-.8, ORANGE, '--')]:
        samples.plot(n, pole**n, style+'o', color=color, label=f'z = {pole:g}')
    samples.axhline(0, color=MUTED, lw=.8)
    samples.set(xlabel='周期切面序号', ylabel='相对初始误差', xticks=n)
    samples.legend()
    z = np.linspace(-.88, .92, 400)
    sigma = -(2/10e-6)*(z-1)/(z+1)
    mapping.semilogy(z, sigma, color=TEAL)
    mapping.plot([-.8, .8], [1.8e6, 2e5/9], '.', color=INK, ms=8)
    mapping.set(xlabel='周期根 z', ylabel='等效极点绝对值 / s⁻¹')
    mapping.annotate('−0.8 → 1.8 × 10⁶', (-.8, 1.8e6), (-.55, 1.6e6),
                     arrowprops=dict(arrowstyle='->', color=MUTED))
    mapping.annotate('+0.8 → 2.22 × 10⁴', (.8, 2e5/9), (.12, 2.9e4),
                     arrowprops=dict(arrowstyle='->', color=MUTED))
    return fig


@book_figure('multi_feedback_nodes', '两路共用占空比时的电容端和负载端',
             '选 OUT1 防反管前作 SSR 反馈。两路负载电流和端口电压均在各自防反管后计量。')
def multi_feedback_nodes():
    fig = figure(height=4.55)
    ax = fig.subplots()
    diagram(ax, ylim=(0, 6))
    block(ax, .32, 3.17, 1.90, '共享变压器', BLUE, height=2.08)
    for idx, y in enumerate((4.54, 2.07), start=1):
        src_y = 3.5 if idx == 1 else 2.84
        wire(ax, [(2.22, src_y), (2.7, src_y), (2.7, y), (3.35, y)], BLUE)
        diode(ax, 3.54, y, BLUE)
        wire(ax, [(3.66, y), (6.91, y)], BLUE)
        diode(ax, 7.10, y, TEAL)
        wire(ax, [(7.22, y), (9.09, y)], TEAL)
        arrow(ax, (9.09, y), (10.55, y), TEAL)
        ax.text(3.56, y+.29, '整流', ha='center')
        ax.text(7.10, y+.29, '输出防反', ha='center')
        node(ax, 5.45, y, f'C{idx} 正端')
        node(ax, 9.09, y, f'OUT{idx} 端口', TEAL)
        wire(ax, [(5.45, y), (5.45, y-.38)], BLUE)
        for offset in (.38, .53):
            wire(ax, [(5.22, y-offset), (5.68, y-offset)], BLUE)
        wire(ax, [(5.45, y-.53), (5.45, y-.87)], BLUE)
        reference(ax, 5.45, y-.87)
        ax.text(10., y-.35, '负载', ha='center', color=TEAL)
    block(ax, 7.65, 5.48, 2.55, 'SSR：仅选 OUT1', ORANGE)
    wire(ax, [(5.45, 4.54), (6.18, 4.54), (6.18, 5.48)], ORANGE)
    arrow(ax, (6.18, 5.48), (7.65, 5.48), ORANGE)
    return fig


@book_figure('cross_load_column', '一列负载扰动的闭环回代',
             'OUT2 单独增加 1 A。一次命令修正同时作用于两路，反馈路可逐步消除偏差。')
def cross_load_column():
    fig, (curve, result) = plots(2)
    g = np.linspace(0, 12, 300)
    for pu, pl, label, color in [(4, -.12, 'OUT1 取样路', BLUE), (2, -.30, 'OUT2 抽流路', ORANGE)]:
        curve.plot(g, 1e3*(pl+pu*g*.12/(1+4*g)), color=color, label=label)
    curve.axvline(2, color=MUTED, ls=':', lw=.9)
    curve.axhline(0, color=MUTED, lw=.8)
    curve.set(xlabel='补偿器直流增益 / (V/V)', ylabel='端口电压变化 / mV')
    curve.legend(loc='center right')
    changes = [[-120, -300], [106.67, 53.33], [-13.33, -246.67]]
    for index, values in enumerate(changes):
        result.bar(np.arange(2)+(index-1)*.23, values, width=.22,
                   color=[MUTED, TEAL, ORANGE][index], label=['直接负载', '共享控制补回', '合计'][index])
    result.axhline(0, color=MUTED, lw=.8)
    result.set(ylabel='Gᶜ(0) = 2 时电压变化 / mV', xticks=[0, 1], xticklabels=['OUT1', 'OUT2'])
    result.legend(loc='lower left')
    return fig


@book_figure('acf_stage_windows', '有源钳位正激的分段积分',
             '导通、死区和钳位复位各自推进状态。下图比较两条梯形，其面积差为 22 nC。')
def acf_stage_windows():
    fig, (stages, charge) = plots(2)
    stages.broken_barh([(0, .40)], (2.05, .54), facecolors=BLUE)
    stages.broken_barh([(.44, .51)], (1.05, .54), facecolors=TEAL)
    for start, end in [(.40, .44), (.95, 1.)]:
        stages.axvspan(start, end, color=ORANGE, alpha=.21)
    stages.set(xlim=(0, 1), ylim=(.6, 3.03), yticks=[1.32, 2.32],
               yticklabels=['钳位复位', '主开关导通'], xlabel='相对周期 t / Ts')
    stages.text(.426, 2.80, '死区', ha='center', color=ORANGE)
    stages.text(.970, 2.80, '死区', ha='center', color=ORANGE)
    charge.plot([0, .20], [2., 2.4], color=BLUE, label='原积分区间')
    charge.fill_between([0, .20], [2., 2.4], color=BLUE, alpha=.18)
    charge.plot([0, .21], [2., 2.4], color=ORANGE, ls='--', label='冻结端点的时长对照')
    charge.fill_between([.20, .21], [2.+.4*.20/.21, 2.4], color=ORANGE, alpha=.2)
    charge.text(.066, 1.10, '原面积 0.44 µC', color=BLUE)
    charge.set(xlabel='一个积分小步 / µs', ylabel='支路电流 / A', xlim=(0, .237), ylim=(0, 2.92))
    charge.legend(loc='upper left')
    return fig


@book_figure('qr_zcd_sequence', '退磁结束、检测穿越和首谷开通',
             '理想辅助绕组副本过零后再等四分之一周期。实际触发的位置由阈值、RC 和传播延时共同决定。')
def qr_zcd_sequence():
    fig, (vds, zcd, gate) = plots(3, sharex=True)
    tau_us = np.sqrt(800e-6*120e-12)*1e6
    t = np.linspace(-.38, 1.22, 500)
    ring = np.cos(np.maximum(t, 0)/tau_us)
    until_valley = t <= np.pi*tau_us
    vds.plot(t[until_valley], (300+120*ring)[until_valley], color=BLUE)
    vds.axhline(300, color=MUTED, ls='--', lw=.8)
    zcd.plot(t[until_valley], ring[until_valley], color=TEAL)
    zcd.axhline(0, color=MUTED, ls='--', lw=.8)
    gate.step(t, t >= np.pi*tau_us, where='post', color=ORANGE)
    vds.set(ylabel='理想 VDS / V')
    zcd.set(ylabel='归一化 ZCD 副本')
    gate.set(ylabel='开通指令', yticks=[0, 1], xlabel='从退磁结束起算 / µs')
    for x, label in [(0, '退磁结束'), (.5*np.pi*tau_us, '下降穿越'), (np.pi*tau_us, '首谷')]:
        for ax in (vds, zcd, gate):
            ax.axvline(x, color=MUTED, ls=':', lw=.85)
        vds.text(x-.027, 430, label, ha='right', color=INK)
    vds.set_ylim(160, 470)
    return fig


@book_figure('psr_pickoff', '从副边整流平台读到原边 FB',
             '上图是比例与分压的信号路径，下图的绿色区域为示意可用采样窗口。')
def psr_pickoff():
    fig = figure(height=4.55)
    chain, timing = fig.subplots(2, gridspec_kw={'height_ratios': [.88, 1.2]})
    diagram(chain)
    lanes(chain, [(0.13, 2.32, '副边平台 12 V'), (3.0, 2.31, '匝比 Nₐ/Nₛ = 0.75'),
                  (5.84, 2.13, '辅助平台 9 V'), (8.53, 2.31, 'Rh、Rl → FB 2 V')], y=1.63)
    chain.text(9.68, 2.76, '补偿注流 Ireg', ha='center', color=ORANGE)
    arrow(chain, (9.68, 2.57), (9.68, 1.94), ORANGE)
    t = np.linspace(-.6, 2.5, 420)
    splat = 9+5*np.exp(-np.maximum(t, 0)/.09)*np.cos(31*np.maximum(t, 0))
    post = 9*np.exp(-3*np.maximum(t-1.8, 0))*np.cos(16*np.maximum(t-1.8, 0))
    va = np.where(t < 0, -5, np.where(t < 1.8, splat, post))
    timing.plot(t, va, color=BLUE)
    timing.axvspan(0, .3, color=ORANGE, alpha=.18, label='消隐 0.3 µs')
    timing.axvspan(.3, 1.8, color=TEAL, alpha=.16, label='副边导通的有效部分')
    timing.axhline(9, color=MUTED, ls=':', lw=.8)
    timing.set(xlabel='从主开关关断起算 / µs', ylabel='辅助绕组端电压 / V', ylim=(-6, 16))
    timing.legend(loc='upper right')
    return fig


@book_figure('psr_mode_boundary', '最低峰值门限与降频边界的功率回代',
             '旁侧虚线给出若继续按每周期 2.448 µJ 输出所需的频率。浅橙区低于参考频率下限。')
def psr_mode_boundary():
    fig, (frequency, peak) = plots(2, sharex=True)
    energy_out = .85*.5*100e-6*.24**2
    pb, floor = energy_out*100e3, energy_out*30e3
    p = np.linspace(.01, .6, 450)
    below, pfm, pwm = p < floor, (p >= floor) & (p <= pb), p >= pb
    for ax in (frequency, peak):
        ax.axvline(pb*1000, color=MUTED, ls=':', lw=1)
        ax.axvspan(0, floor*1000, color=ORANGE, alpha=.15)
    frequency.plot(p[below]*1000, p[below]/energy_out/1000, color=ORANGE, ls='--')
    frequency.plot(p[pfm]*1000, p[pfm]/energy_out/1000, color=TEAL, label='定峰值降频')
    frequency.plot(p[pwm]*1000, np.full(np.count_nonzero(pwm), 100), color=BLUE, label='定频调峰值')
    frequency.scatter([floor*1000, pb*1000], [30, 100], color=INK)
    frequency.set(ylabel='开关频率 / kHz')
    frequency.legend(loc='lower right')
    peak.plot(p[pfm]*1000, np.full(np.count_nonzero(pfm), .24), color=TEAL)
    peak.plot(p[pwm]*1000, np.sqrt(p[pwm]/(.85*.5*100e-6*100e3)), color=BLUE)
    peak.set(xlabel='输出功率 / mW', ylabel='原边峰值 / A', xlim=(0, 600), ylim=(.17, .42))
    return fig


@book_figure('cot_shared_signals', '多相 COT 的公共电压指令与差模均流',
             '频率指令同向送到各相，均流校正使用本相电流与平均电流之差，功率端叠加各相电流。')
def cot_shared_signals():
    fig = figure(height=4.55)
    ax = fig.subplots()
    diagram(ax, xlim=(-.55, 11.1), ylim=(0, 6))
    block(ax, .30, 4.92, 2.23, '电压误差 → PI')
    block(ax, 4.05, 4.92, 2.48, '公共频率指令 f')
    arrow(ax, (2.53, 4.92), (4.05, 4.92), BLUE)
    wire(ax, [(5.29, 4.62), (5.29, 4.21), (2.17, 4.21)], BLUE)
    wire(ax, [(5.29, 4.21), (8.79, 4.21)], BLUE)
    for x, index in [(2.17, 1), (8.79, 2)]:
        arrow(ax, (x, 4.21), (x, 3.71), BLUE)
        block(ax, x-1.30, 3.41, 2.60, f'第 {index} 相：tₒₙf + dᵦ', BLUE)
        arrow(ax, (x, 3.11), (x, 2.52), BLUE)
        block(ax, x-1.30, 2.21, 2.60, f'电感 L{index}，电流 i{index}', TEAL)
        wire(ax, [(x, 1.91), (x, 1.25), (5.48, 1.25)], TEAL)
    block(ax, 4.10, .57, 2.76, '电流和 → 输出电压', TEAL)
    arrow(ax, (5.48, 1.25), (5.48, .87), TEAL)
    wire(ax, [(4.10, .57), (-.15, .57), (-.15, 4.92)], TEAL)
    arrow(ax, (-.15, 4.92), (.30, 4.92), TEAL)
    block(ax, 4.10, 2.70, 2.76, '均流：平均值 − 本相', ORANGE)
    arrow(ax, (4.10, 2.88), (3.47, 3.35), ORANGE)
    arrow(ax, (6.86, 2.88), (7.49, 3.35), ORANGE)
    arrow(ax, (3.47, 2.21), (4.10, 2.52), ORANGE)
    arrow(ax, (7.49, 2.21), (6.86, 2.52), ORANGE)
    return fig


@book_figure('cot_charge_deficit', '负载增加时的电流缺额与电容跌落',
             '上图的矩形和三角形分别是 2 µC、4 µC。下图只展示预算模型中输出被补足前的跌落。')
def cot_charge_deficit():
    fig, (deficit, droop) = plots(2, sharex=True)
    t = np.linspace(0, 3, 601)
    elapsed = np.minimum(np.maximum(0, t-.5), 2)
    current = np.maximum(0, 4-2*elapsed)
    accumulated = 4*np.minimum(t, .5)+4*elapsed-elapsed**2
    deficit.plot(t, current, color=BLUE)
    deficit.fill_between(t, current, where=t <= .5, color=ORANGE, alpha=.27)
    deficit.fill_between(t, current, where=t >= .5, color=TEAL, alpha=.24)
    deficit.text(.21, 1.7, '2 µC', color=ORANGE, ha='center')
    deficit.text(1.05, 1.4, '4 µC', color=TEAL, ha='center')
    deficit.set(ylabel='总电流缺额 / A', ylim=(-.2, 4.9))
    droop.plot(t, -10*accumulated, color=TEAL, label='只计电荷面积除以 C')
    droop.plot(t, -10*accumulated-40, color=ORANGE, ls='--', label='预算加上 40 mV 边沿项')
    droop.set(xlabel='加载后的时间 / µs', ylabel='预算电压变化 / mV', xlim=(0, 2.5), ylim=(-116, 6))
    droop.legend(loc='lower left')
    return fig


@book_figure('llc_modulators', 'LLC 变频先定时刻，混合滞环由轨迹定时刻',
             '上图的边沿由频率取倒数给出；下图沿比较电压第一次向上通过所选阈值的时刻关断。')
def llc_modulators():
    fig, (freq, event) = plots(2)
    t = np.linspace(5.38, 5.81, 430)
    for f, color in [(90, BLUE), (89, ORANGE)]:
        h = 500/f
        freq.step(t, t < h, where='post', color=color, label=f'{f} kHz，H = {h:.3f} µs')
        freq.axvline(h, color=color, lw=.8, ls=':')
    freq.set(xlabel='半周期末尾的时刻 / µs', ylabel='变频驱动命令', yticks=[0, 1], ylim=(-.12, 1.22))
    freq.legend(loc='lower left')
    comparison = 1+.2*(t-5.55)
    event.plot(t, comparison, color=TEAL, label='比较信号局部斜率 0.20 V/µs')
    for voltage, color in [(1., BLUE), (1.01, ORANGE)]:
        h = 5.55+(voltage-1)/.2
        event.axhline(voltage, color=color, lw=1, ls=':')
        event.plot(h, voltage, 'o', color=color)
    event.annotate('门限增加 10 mV 后推迟 50 ns', (5.60, 1.01), (5.39, 1.041),
                   arrowprops=dict(arrowstyle='->', color=MUTED))
    event.set(xlabel='交点邻域的时刻 / µs', ylabel='比较电压 / V', ylim=(.957, 1.065))
    event.legend(loc='lower right')
    return fig


@book_figure('lead_phase_vectors', '一对零极点在设计中心的相位贡献',
             '向量角度相减后得到 40°，两个相同因子提供 80°。右图为单对因子的全频相位曲线。')
def lead_phase_vectors():
    fig, (vectors, phase) = plots(1, 2)
    k = np.tan(np.deg2rad(65))
    for height, color, name in [(k, BLUE, '零点因子 1 + jK'), (1/k, ORANGE, '极点因子 1 + j/K')]:
        arrow(vectors, (0, 0), (1, height), color)
        vectors.plot([1, 1], [0, height], ls=':', color=color, lw=.8)
        vectors.text(.98, height+.18, name, color=color, va='center', ha='right')
    for radius, angle, color in [(.49, 65, BLUE), (.78, 25, ORANGE)]:
        vectors.add_patch(Arc((0, 0), radius, radius, theta1=0, theta2=angle, color=color, lw=1.1))
    vectors.text(.14, .28, '65°', color=BLUE)
    vectors.text(.46, .12, '25°', color=ORANGE)
    vectors.set(xlim=(-.24, 1.22), ylim=(-.15, 2.62), xlabel='实部', ylabel='虚部', aspect='equal')
    f = np.geomspace(.08, 12, 401)
    phi = np.angle((1+1j*f*k)/(1+1j*f/k), deg=True)
    phase.semilogx(f, phi, color=TEAL)
    phase.axvline(1, color=MUTED, ls=':', lw=1)
    phase.plot(1, 40, 'o', color=INK)
    phase.set(xlabel='频率与目标中心频率之比 f / fc', ylabel='单对相位 / °', ylim=(0, 46))
    phase.annotate('中心最大提升 40°', (1, 40), (.95, 34),
                   arrowprops=dict(arrowstyle='->', color=MUTED))
    return fig


@book_figure('crossover_interpolation', '对数频率上的穿越插值',
             '先用增益计算 λ，再以同一个 λ 插值展开后的相位。竖线标出同一个频率。')
def crossover_interpolation():
    fig, (gain, phase) = plots(2, sharex=True)
    points = [900, 1100]
    crossing = 900**.4*1100**.6
    for ax, values, result, color in [(gain, [1.2, -.8], 0., BLUE), (phase, [-116, -124], -120.8, ORANGE)]:
        ax.semilogx(points, values, 'o-', color=color)
        ax.axvline(crossing, color=MUTED, ls=':', lw=.9)
        ax.plot(crossing, result, 'o', color=TEAL)
    gain.set(ylabel='增益 / dB', ylim=(-1.21, 1.5))
    gain.axhline(0, color=MUTED, lw=.8)
    gain.annotate('约 1015 Hz', (crossing, 0), (919, -.7),
                  arrowprops=dict(arrowstyle='->', color=MUTED))
    phase.set(xlabel='对数轴频率 / Hz', ylabel='展开相位 / °', xlim=(878, 1130),
              ylim=(-125.5, -114.5), xticks=points, xticklabels=['900', '1100'])
    phase.minorticks_off()
    phase.annotate('−120.8°，裕度 59.2°', (crossing, -120.8), (915, -123.7),
                   arrowprops=dict(arrowstyle='->', color=MUTED))
    return fig


@book_figure('opamp_branches', '普通运放的输入和反馈阻容支路',
             '虚地位于两组阻容中间。用同一对节点收集并联支路导纳，便能依次读取积分和两个转折。')
def opamp_branches():
    fig = figure(height=4.55)
    network, response = fig.subplots(2, gridspec_kw={'height_ratios': [1.10, 1.]})
    diagram(network, ylim=(0, 3.5))
    panel_label(network, '三型运放的阻抗连接')
    for x, left, first, second, color in [(1.1, 4.75, 'R₁', 'R₃ 串联 C₃', BLUE),
                                         (4.75, 9.90, 'R₂ 串联 C₁', 'C₂', ORANGE)]:
        for y, label in [(2.32, first), (1.28, second)]:
            center = .5*(x+left)
            wire(network, [(x, y), (center-.89, y)], color)
            wire(network, [(center+.89, y), (left, y)], color)
            block(network, center-.89, y, 1.78, label, color, height=.46)
        wire(network, [(x, 1.28), (x, 2.32)], color)
        wire(network, [(left, 1.28), (left, 2.32)], color)
    node(network, 1.1, 2.32, '输入 vᵢ')
    node(network, 4.75, 2.32, '反相端虚地')
    node(network, 9.90, 2.32, '输出 vₒ')
    network.text(2.93, .57, '输入导纳 Yᵢ', color=BLUE, ha='center')
    network.text(7.31, .57, '反馈阻抗 Zf', color=ORANGE, ha='center')
    f = np.geomspace(40, 12000, 401)
    s = 2j*np.pi*f
    g = 1000/s*(1+s/(2*np.pi*200))/(1+s/(2*np.pi*2000))
    response.semilogx(f, 20*np.log10(abs(g)), color=BLUE)
    for frequency in (200, 2000):
        response.axvline(frequency, color=MUTED, ls=':', lw=1)
    response.set(xlabel='二型计算例频率 / Hz', ylabel='补偿增益 / dB')
    panel_label(response, '去掉输入串联支路后的二型响应')
    return fig


@book_figure('optocoupler_paths', '从 TL431 副边到光耦原边的信号路径',
             '慢路通过误差节点。快车道开启时，输出扰动还可以直接改变 LED 电流。两路在同一光耦汇合。')
def optocoupler_paths():
    fig = figure(height=4.55)
    ax = fig.subplots()
    diagram(ax, ylim=(0, 6))
    lanes(ax, [(.20, 2.05, '副边电容端 v'), (2.81, 2.32, '分压与 TL431'),
               (5.69, 2.02, 'LED 电流相加'), (8.38, 2.26, 'CTR：LED → Ic')], y=3.80)
    block(ax, 2.98, 5.12, 2.15, '经 Rled 直接耦合', ORANGE)
    wire(ax, [(1.23, 4.10), (1.23, 5.12)], ORANGE)
    arrow(ax, (1.23, 5.12), (2.98, 5.12), ORANGE)
    wire(ax, [(5.13, 5.12), (6.70, 5.12)], ORANGE)
    arrow(ax, (6.70, 5.12), (6.70, 4.10), ORANGE)
    block(ax, 8.04, 2.01, 2.95, 'Rpull 与并联电容', TEAL)
    arrow(ax, (9.51, 3.49), (9.51, 2.31), TEAL)
    block(ax, 4.67, 2.01, 2.42, '原边命令电压', TEAL)
    arrow(ax, (8.04, 2.01), (7.09, 2.01), TEAL)
    ax.text(7.88, .83, '抽流增量乘以负跨阻得到上拉电压增量', color=TEAL, ha='center')
    return fig


@book_figure('optocoupler_cap_rolloff', '光耦集电极电容决定原边跨阻极点',
             '三条曲线统一以直流跨阻为参考。每条线的点同时对应幅值下跌 3.01 dB 和相位 −45°。')
def optocoupler_cap_rolloff():
    fig, (gain, phase) = plots(2, sharex=True)
    f = np.geomspace(.15, 26, 400)
    for cap, color in [(0, BLUE), (1.98, TEAL), (6, ORANGE)]:
        fp = 1/(2*np.pi*20e3*(2+cap)*1e-9)/1e3
        h = 1/(1+1j*f/fp)
        gain.semilogx(f, 20*np.log10(abs(h)), color=color, label=f'C₂ = {cap:g} nF')
        phase.semilogx(f, np.angle(h, deg=True), color=color)
        gain.plot(fp, -3.0103, 'o', color=color)
        phase.plot(fp, -45, 'o', color=color)
    gain.axhline(-3.0103, color=MUTED, ls=':', lw=.8)
    phase.axhline(-45, color=MUTED, ls=':', lw=.8)
    gain.set(ylabel='相对直流增益 / dB')
    gain.legend(loc='lower left')
    phase.set(xlabel='频率 / kHz', ylabel='跨阻相位 / °', yticks=[-90, -45, 0])
    return fig


@book_figure('sensitivity_vectors', '单位增益时的反馈灵敏度取决于矢量和',
             '从 +1 的向量末端再加 T。1+T 越短，同一个开环负载扰动被放大得越多。')
def sensitivity_vectors():
    fig = figure(height=4.55)
    for ax, angle, color in zip(fig.subplots(1, 2), (-120, -150), (BLUE, ORANGE)):
        ax.grid(True, color=MUTED, alpha=.13)
        ax.axhline(0, color=MUTED, lw=.8)
        ax.axvline(0, color=MUTED, lw=.8)
        response = np.exp(1j*np.deg2rad(angle))
        endpoint = (1+response.real, response.imag)
        arrow(ax, (0, 0), (1, 0), MUTED)
        arrow(ax, (1, 0), endpoint, color)
        arrow(ax, (0, 0), endpoint, TEAL)
        ax.text(.5, .065, '+1', ha='center', color=MUTED)
        ax.text((1+endpoint[0])/2+.05, endpoint[1]/2, 'T', color=color)
        ax.text(.05, endpoint[1]/2-.16, '1 + T', color=TEAL)
        ax.set(xlim=(-.16, 1.20), ylim=(-1.12, .28), xlabel='实部', ylabel='虚部', aspect='equal')
        panel_label(ax, f'相位 {angle}°，|S| = {1/abs(1+response):.2f}')
    return fig


@book_figure('fra_pickoff', 'FRA 串联注入和两侧复相量读法',
             '上图保留直流反馈通路。下图对应 V₂=10 mV∠0°、V₁=9.8 mV∠59°，先比值再取负号。')
def fra_pickoff():
    fig = figure(height=4.55)
    wiring, vectors = fig.subplots(2)
    diagram(wiring)
    block(wiring, .38, 1.86, 2.12, '低阻返回源')
    block(wiring, 8.26, 1.86, 2.30, '高阻取样入口')
    wire(wiring, [(2.50, 1.86), (5.13, 1.86)], BLUE)
    wire(wiring, [(5.79, 1.86), (8.26, 1.86)], BLUE)
    wiring.add_patch(Circle((5.46, 1.86), .33, fc='white', ec=BLUE, lw=1.5))
    wiring.text(5.46, 1.86, '∿', ha='center', va='center', color=BLUE, fontsize=15)
    wiring.text(5.46, 2.58, '小正弦串联注入', ha='center', color=BLUE)
    for x, label in [(3.53, 'V₁'), (7.23, 'V₂')]:
        node(wiring, x, 1.86)
        arrow(wiring, (x, 1.86), (x, .99), ORANGE)
        wiring.text(x, .70, label, ha='center', color=ORANGE)
    vectors.set(xlim=(-6.7, 11.6), ylim=(-1.4, 9.6), xlabel='复相量实部 / mV', ylabel='虚部 / mV')
    vectors.axhline(0, color=MUTED, lw=.7)
    vectors.axvline(0, color=MUTED, lw=.7)
    v1 = 9.8*np.exp(1j*np.deg2rad(59))
    arrow(vectors, (0, 0), (10, 0), BLUE)
    arrow(vectors, (0, 0), (v1.real, v1.imag), ORANGE)
    vectors.text(8.8, .7, 'V₂', color=BLUE)
    vectors.text(v1.real+.55, v1.imag, 'V₁', color=ORANGE)
    vectors.text(-5.9, 6.8, 'T = −V₁ / V₂\n0.98∠−121°', color=TEAL, va='center')
    return fig


@book_figure('llc_map_flow', 'LLC 稳态求根与环路输出的半周期计算路径',
             '返回状态前先变换到同一参考方向。输出电压从另外一条读出支路取得。')
def llc_map_flow():
    fig = figure(height=4.55)
    ax = fig.subplots()
    diagram(ax, ylim=(0, 6.25))
    lanes(ax, [(.28, 2.10, '切面初值 xₖ'), (3.06, 2.19, '半周期积分'),
               (5.94, 2.02, '反对称量换号'), (8.70, 2.06, '返回 xₖ₊₁')], y=3.48)
    block(ax, 2.75, 5.21, 2.83, 'VCO 周期或滞环事件', ORANGE)
    arrow(ax, (4.15, 4.91), (4.15, 3.78), ORANGE)
    wire(ax, [(9.73, 3.18), (9.73, 2.68), (1.33, 2.68)], BLUE)
    arrow(ax, (1.33, 2.68), (1.33, 3.18), BLUE)
    ax.text(6.4, 2.3, '求根残差：返回状态减切面初值', color=BLUE, ha='center')
    wire(ax, [(4.15, 3.18), (4.15, 1.21)], TEAL)
    arrow(ax, (4.15, 1.21), (5.56, 1.21), TEAL)
    block(ax, 5.56, 1.21, 3.42, '整流及滤波的周期输出 Yₕ', TEAL)
    ax.text(7.27, .57, '另一条支路分别对状态与控制微分', ha='center', color=TEAL)
    return fig
