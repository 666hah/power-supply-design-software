"""Illustrations integrated into the capacitor, magnetics and device chapters."""

import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


PALE = '#e6eff5'
WARM = '#faeee3'
GREEN = '#e1f0ed'


def board(ax, title, width=10, height=8):
    panel_label(ax, title)
    ax.set(xlim=(0, width), ylim=(0, height))
    ax.axis('off')


def pair(titles):
    fig = figure(height=4.0)
    axes = fig.subplots(1, 2)
    for ax, title in zip(axes, titles):
        panel_label(ax, title)
    return fig, axes


def box(ax, x, y, w, h, label='', fill=PALE, color=BLUE, fontsize=9):
    ax.add_patch(Rectangle((x, y), w, h, ec=color, fc=fill, lw=1.1))
    if label:
        ax.text(x + w / 2, y + h / 2, label, va='center', ha='center', color=color, fontsize=fontsize)


def wire(ax, xy, color=INK, lw=1.4, ls='-'):
    x, y = zip(*xy)
    ax.plot(x, y, c=color, lw=lw, ls=ls)


def arrow(ax, start, end, color=TEAL, style='-|>', rad=0):
    ax.add_patch(FancyArrowPatch(start, end, color=color, arrowstyle=style,
                                mutation_scale=11, lw=1.6, connectionstyle=f'arc3,rad={rad}'))


def note(ax, x, y, text, color=INK, align='left', fontsize=8.8):
    ax.text(x, y, text, ha=align, va='center', color=color, fontsize=fontsize)


def tag(ax, x, y, text, dx, dy, color=INK):
    ax.annotate(text, xy=(x, y), xytext=(dx, dy), textcoords='offset points', fontsize=8.5,
                color=color, arrowprops={'arrowstyle': '-', 'color': color, 'lw': .75})


def capsym(ax, x, top, bottom, color=BLUE):
    mid = (top + bottom) / 2
    wire(ax, ((x, top), (x, mid + .16)), color)
    wire(ax, ((x, mid - .16), (x, bottom)), color)
    for y in (mid - .16, mid + .16):
        wire(ax, ((x - .44, y), (x + .44, y)), color, lw=2)


def cap_paths():
    fig = figure(height=4)
    for index, (ax, source, active) in enumerate(zip(fig.subplots(1, 3),
            ('Buck 输出电感', '反激整流管截止', '反激整流管导通'), (True, False, True))):
        board(ax, f'（{"abc"[index]}）{source}', 8, 8)
        wire(ax, ((.4, 1.45), (7.5, 1.45), (7.5, 2.55)), MUTED)
        wire(ax, ((.4, 5.8), (7.5, 5.8), (7.5, 4.35)), MUTED)
        box(ax, 7.18, 2.55, .64, 1.8, fill=WARM, color=ORANGE)
        note(ax, 6.9, 3.45, '负载', ORANGE, 'right')
        capsym(ax, 3.45, 5.8, 1.45)
        ax.scatter([3.45], [5.8], s=14, c=INK, zorder=4)
        if active:
            arrow(ax, (.3, 5.8), (3.1, 5.8), BLUE)
            note(ax, .3, 6.45, '输入节点', BLUE)
            arrow(ax, (4.35, 5.1), (4.35, 4.08), TEAL)
            note(ax, 3.9, .78, '仅示充电时刻', TEAL, 'center')
        else:
            ax.plot([.6, 1.15], [6.22, 5.61], color=MUTED)
            ax.plot([.6, 1.15], [5.61, 6.22], color=MUTED)
            arrow(ax, (4.35, 4.08), (4.35, 5.1), TEAL)
            note(ax, 3.9, .78, '电容向负载供电', TEAL, 'center')
        arrow(ax, (5, 5.8), (7.1, 5.8), ORANGE)
        note(ax, 5.1, 6.45, '$i_{load}$', ORANGE)
        note(ax, 3.45, 3.05, 'C', BLUE, 'center')
    return fig


def cap_impedance():
    fig, (amp, phase) = pair(('（a）绕过自谐振点时的阻抗', '（b）同一支路相位翻转'))
    f = np.geomspace(1e4, 3e7, 700)
    w = 2 * np.pi * f
    for c, l, r, color, label in ((100e-6, 8e-9, .060, BLUE, '100 µF'),
                                 (1e-6, 1e-9, .010, ORANGE, '1 µF')):
        z = r + 1j * (w * l - 1 / (w * c))
        fr = 1 / (2 * np.pi * np.sqrt(l * c)) / 1e3
        amp.loglog(f / 1e3, abs(z) * 1e3, c=color, label=label)
        phase.semilogx(f / 1e3, np.angle(z, deg=True), c=color, label=label)
        amp.scatter([fr], [r * 1e3], c=color, s=25, zorder=3)
        phase.scatter([fr], [0], c=color, s=25, zorder=3)
        tag(phase, fr, 0, f'{fr:,.0f} kHz', 6, -24 if c > 1e-6 else 26, color)
    phase.axhline(0, lw=1, ls=':', c=MUTED)
    phase.set(ylabel='阻抗相位 / °', yticks=[-90, -45, 0, 45, 90])
    amp.set(ylabel='阻抗幅值 / mΩ')
    amp.legend(loc='upper right')
    for ax in (amp, phase):
        ax.set(xlabel='频率 / kHz')
        ax.grid(which='major', alpha=.2)
    return fig


def cap_phasors():
    fig, (ax, detail) = pair(('（a）复阻抗分压', '（b）两支路电流相量闭合'))
    board(ax, '（a）1 MHz 时的公共电压')
    w = 2 * np.pi * 1e6
    z1 = .060 + 1j * (w * 8e-9 - 1 / (w * 100e-6))
    z2 = .010 + 1j * (w * 1e-9 - 1 / (w * 1e-6))
    z = 1 / (1 / z1 + 1 / z2)
    h1, h2 = z / z1, z / z2
    box(ax, .4, 5.7, 9.2, 1.25, '总电流  1∠0° A RMS', fill=GREEN, color=TEAL)
    arrow(ax, (5, 5.7), (5, 4.9))
    box(ax, .4, 3.6, 9.2, 1.25, f'公共电压  {abs(z)*1e3:.1f}∠{np.angle(z, deg=True):.1f}° mV')
    for x, h, col in ((2.5, h1, BLUE), (7.5, h2, ORANGE)):
        arrow(ax, (x, 3.6), (x, 2.7), col)
        box(ax, x - 2.15, 1.2, 4.3, 1.45, f'除以 $Z_{1 if x < 5 else 2}$\n{abs(h):.2f} A RMS',
            fill=PALE if x < 5 else WARM, color=col)
    detail.set(xlim=(-.16, 1.36), ylim=(-.85, .36), xlabel='同相分量 / A', ylabel='正交分量 / A')
    detail.set_aspect('equal', anchor='N')
    detail.axhline(0, lw=.8, color=MUTED)
    detail.axvline(0, lw=.8, color=MUTED)
    arrow(detail, (0, 0), (1, 0), TEAL)
    arrow(detail, (0, 0), (h1.real, h1.imag), BLUE)
    arrow(detail, (h1.real, h1.imag), (1, 0), ORANGE)
    note(detail, .39, -.42, '$I_1$', BLUE)
    note(detail, 1.09, -.33, '$I_2$', ORANGE)
    note(detail, .45, .1, '$I$', TEAL)
    return fig


def cap_measurement():
    fig, (ax, end) = pair(('（a）复平面上的仪表测点', '（b）插值权重从频率轴读取'))
    a, b = 30 - 50j, 18 + 14j
    mid = (a + b) / 2
    ax.plot([a.real, b.real], [a.imag, b.imag], c=BLUE)
    for z, f, offset in ((a, 20, (-85, 6)), (mid, 60, (12, -4)), (b, 180, (12, 9))):
        ax.scatter(z.real, z.imag, c=ORANGE if f == 60 else BLUE, s=25, zorder=3)
        tag(ax, z.real, z.imag, f'{f} kHz\n({z.real:.0f}, {z.imag:+.0f}) mΩ', *offset)
    ax.axhline(0, c=MUTED, ls=':', lw=.8)
    ax.set(xlim=(8, 43), ylim=(-64, 29), xlabel='实部 / mΩ', ylabel='虚部 / mΩ')
    board(end, '（b）在对数频率轴上定权重')
    arrow(end, (.7, 4.7), (9.5, 4.7), MUTED)
    for x, f, label in ((1.7, 20, '低频端'), (5, 60, '对数中点'), (8.3, 180, '高频端')):
        wire(end, ((x, 4.4), (x, 5.05)), BLUE)
        note(end, x, 5.6, f'{f} kHz', BLUE, 'center')
        note(end, x, 3.9, label, INK, 'center')
    box(end, 1, 1.25, 8, 1.45, '两段频率比均为 3\n复阻抗实部和虚部均取算术平均', fill=GREEN, color=TEAL)
    return fig


def cap_harmonics():
    fig, (ax, power) = pair(('（a）分频点取得端口 RMS 电流', '（b）支路逐频损耗账本'))
    f = np.array([100, 300, 500])
    current = np.array([3, 1, .5])
    # Purely resistive teaching values at each of the three sample frequencies.
    r1, r2 = np.array([20, 30, 60]), np.array([40, 30, 20])
    h1 = r2 / (r1 + r2)
    for k, (curr, r, color, label) in enumerate(((h1 * current, r1, BLUE, '支路 1'),
                                                 ((1 - h1) * current, r2, ORANGE, '支路 2'))):
        power.bar(np.arange(3) + .29 * (k - .5), curr**2 * r, width=.27, color=color, label=label)
    ax.bar(np.arange(3), current, color=TEAL, width=.46)
    for n, v in enumerate(current):
        note(ax, n, v + .1, f'{v:g} A', TEAL, 'center')
    for chart, yl in ((ax, '端口频点电流 / A RMS'), (power, '频点耗散 / mW')):
        chart.set(xticks=[0, 1, 2], xticklabels=f, xlabel='频率 / kHz', ylabel=yl)
        chart.grid(axis='y', alpha=.2)
    ax.set_ylim(0, 3.45)
    power.legend(loc='upper right')
    return fig


def cap_voltage_components():
    fig, (ax, edge) = pair(('（a）电流与电容积分的峰值错开', '（b）单支路端电压的三个分量'))
    t = np.linspace(0, 10, 501)
    i = np.interp(t, [0, 2.5, 7.5, 10], [0, .6, -.6, 0])
    q = np.r_[0, np.cumsum(.5 * (i[:-1] + i[1:]) * np.diff(t))]
    v_c = (q - q.mean()) / 100 * 1000
    v_r = i * 20
    v_l = np.gradient(i, t) * 8
    ax.plot(t, i, c=BLUE, label='流入电容的电流')
    ax.fill_between(t, 0, i, where=i >= 0, alpha=.18, color=TEAL)
    ax.axhline(0, color=MUTED, lw=.8)
    ax.axvline(5, color=MUTED, lw=.8, ls=':')
    ax.set(ylabel='电流 / A', ylim=(-.77, .77))
    for value, col, label, ls in ((v_c, BLUE, '电容', '--'), (v_r, ORANGE, 'ESR', ':'),
                                 (v_l, TEAL, 'ESL', '-.'), (v_c + v_r + v_l, INK, '合成', '-')):
        edge.plot(t, value, c=col, ls=ls, label=label)
    edge.legend(ncols=2, loc='upper right')
    edge.set(ylabel='交流端电压 / mV', ylim=(-21, 25))
    for chart in (ax, edge):
        chart.set(xlabel='时间 / µs', xlim=(0, 10), xticks=[0, 2.5, 5, 7.5, 10])
    return fig


def cap_step():
    fig, (ax, trace) = pair(('（a）端口电流在阶跃后重分配', '（b）电压上跳与后续趋稳'))
    # A current step into one series ESR–C branch and a parallel 5-ohm load.
    t = np.linspace(0, 2.6, 301)
    e = 5 * (1 - np.exp(-t / .505))
    v = (1 + 20 * e) / (20 + .2)
    ax.plot(t, 1 - v / 5, c=BLUE, label='电容支路')
    ax.plot(t, v / 5, c=ORANGE, ls='--', label='电阻负载')
    ax.set(ylabel='支路小信号电流 / A', ylim=(0, 1.18))
    ax.legend(loc='upper right')
    trace.plot(t, v, c=BLUE, label='端口电压 $v$')
    trace.plot(t, e, c=ORANGE, ls='--', label='理想电容电压 $e$')
    trace.scatter([0, 0], [0, v[0]], s=22, color=[ORANGE, BLUE], zorder=3)
    trace.annotate('约 0.505 ms\n时间常数', xy=(.505, 5 - 5*np.exp(-1)), xytext=(.12, 4.72),
                   color=BLUE, fontsize=8.5, arrowprops={'arrowstyle': '-', 'color': BLUE, 'lw': .75})
    zoom = trace.inset_axes([.40, .34, .42, .22])
    start = np.linspace(0, .012, 90)
    inner_voltage = 5 * (1 - np.exp(-start / .505))
    zoom.plot(start * 1000, (1 + 20 * inner_voltage) / 20.2 * 1000, c=BLUE, lw=1)
    zoom.plot(start * 1000, inner_voltage * 1000, c=ORANGE, ls='--', lw=1)
    zoom.set(xlim=(0, 12), ylim=(0, 176), xticks=[0, 12], yticks=[0, 50, 150], title='首跳 / mV', xlabel='µs')
    zoom.title.set_fontsize(7)
    zoom.xaxis.label.set_size(7)
    zoom.tick_params(labelsize=6.5, pad=1)
    trace.set(ylabel='小信号电压 / V', ylim=(0, 5.7))
    trace.legend(loc='lower right')
    for a in (ax, trace):
        a.set(xlabel='输入增加 1 A 后的时间 / ms', xlim=(0, 2.6))
        a.grid(alpha=.2)
    return fig


def mag_window():
    fig, (ax, calc) = pair(('（a）磁芯截面和窗口对应两种约束', '（b）匝数取整后返回窗口校核'))
    board(ax, '（a）中心柱截面与绕组窗口')
    box(ax, .8, 1.1, 8.4, 5.6, fill=PALE, color=MUTED)
    for x in (2, 5.55):
        box(ax, x, 2.05, 2.45, 3.7, fill='white', color=MUTED)
    box(ax, 4.45, 3.35, 1.10, 1.2, '$A_e$', fill=GREEN, color=TEAL)
    note(ax, 3.22, 4.6, '绕组窗口', BLUE, 'center')
    note(ax, 3.22, 3.72, '$W_a$', BLUE, 'center')
    note(ax, 5, .57, '窗口按设计使用的磁芯目录口径', MUTED, 'center')
    board(calc, '（b）150 µH 电感的取值顺序')
    for y, label, color, fill in ((6.2, '磁密条件给出 25.57 匝', BLUE, PALE),
                                  (4.15, '回代整数   26 匝 → 0.216 T', TEAL, GREEN),
                                  (2.1, '每匝 0.50 mm² → 窗口 ≥ 43.3 mm²', ORANGE, WARM)):
        box(calc, .4, y, 9.2, 1.25, label, fill=fill, color=color)
        if y > 3:
            arrow(calc, (5, y), (5, y - .75), color)
    return fig


def mag_bias():
    fig, (ax, slopes) = pair(('（a）相同摆幅可以有不同峰值', '（b）磁化电压正比于磁密变化率'))
    t = [0, 4, 10]
    for valley, peak, color, label in ((.0889, .2222, BLUE, '有直流偏置'),
                                       (-.06665, .06665, TEAL, '以零磁密为中心')):
        ax.plot(t, [valley, peak, valley], c=color, label=label)
        ax.scatter([4], [peak], c=color, s=18)
    ax.axhline(.24, c=ORANGE, ls='--', lw=1, label='示意设计上限')
    ax.axhline(0, c=MUTED, lw=.8)
    ax.set(ylabel='磁密 / T', xlabel='时间 / µs', ylim=(-.10, .29), xlim=(0, 10), xticks=t)
    ax.legend(loc='lower center')
    slopes.stairs([240, -160], t, color=BLUE)
    slopes.fill_between([0, 4], 0, 240, color=TEAL, alpha=.23)
    slopes.fill_between([4, 10], 0, -160, color=ORANGE, alpha=.20)
    note(slopes, 2, 108, '+960 V·µs', TEAL, 'center')
    note(slopes, 7, -72, '−960 V·µs', ORANGE, 'center')
    slopes.axhline(0, c=MUTED, lw=.8)
    slopes.set(ylabel='磁化支路电压 / V', xlabel='时间 / µs', ylim=(-205, 280), xlim=(0, 10), xticks=t)
    return fig


def mag_e_core():
    fig, axes = pair(('（a）只在中心柱开隙', '（b）三柱都垫相同厚度'))
    for idx, ax in enumerate(axes):
        board(ax, ('（a）只在中心柱开隙', '（b）三柱同垫片厚度')[idx])
        box(ax, 1.2, 6.05, 7.55, .85, fill=PALE, color=MUTED)
        box(ax, 1.2, 1.1, 7.55, .85, fill=PALE, color=MUTED)
        for x, width in ((1.2, 1.02), (4.24, 1.50), (7.73, 1.02)):
            box(ax, x, 1.95, width, 2.05, fill=PALE, color=MUTED)
            bottom = 4.35 if idx or x == 4.24 else 4
            box(ax, x, bottom, width, 6.05 - bottom, fill=PALE, color=MUTED)
        arrow(ax, (4.99, 2.45), (4.99, 6.46), TEAL)
        for x in (1.71, 8.24):
            arrow(ax, (4.99, 6.46), (x, 6.46), TEAL)
            arrow(ax, (x, 6.46), (x, 2.32), TEAL)
            arrow(ax, (x, 1.53), (4.99, 1.53), TEAL)
        wire(ax, ((1.71, 2.32), (1.71, 1.53)), TEAL)
        wire(ax, ((8.24, 2.32), (8.24, 1.53)), TEAL)
        wire(ax, ((4.99, 1.53), (4.99, 2.47)), TEAL)
        note(ax, 5, .53, '外柱磁通分成两条并联回路', TEAL, 'center')
        note(ax, 5.93, 4.15, '$g_c$' if idx == 0 else '$t$', ORANGE)
        if idx:
            note(ax, 2.38, 4.15, '$t$', ORANGE)
            note(ax, 7.35, 4.15, '$t$', ORANGE, 'right')
    return fig


def mag_gap_budget():
    fig, (ax, chart) = pair(('（a）800 µH 工况下磁动势的分配', '（b）研磨公差传给感量'))
    board(ax, '（a）每段磁阻分配的安匝数')
    box(ax, .56, 6, 8.87, 1.1, '激励 60 匝 × 2.0 A = 120 安匝', fill=GREEN, color=TEAL)
    arrow(ax, (5, 6), (5, 4.65))
    box(ax, .56, 3.35, 8.87, 1.22, '铁氧体 5.5 安匝   ＋   气隙 114.5 安匝')
    arrow(ax, (5, 3.35), (5, 2.0))
    box(ax, .56, .65, 8.87, 1.22, '对应磁密约 0.222 T', fill=WARM, color=ORANGE)
    g = np.linspace(.52, .78, 301)
    num = 4 * np.pi * 1e-7 * 120e-6 * 60**2 * 1e9
    g0 = num / 800 - .03125
    chart.plot(g, num / (g + .03125), c=BLUE)
    for x in (g0 - .03, g0, g0 + .03):
        l = num / (x + .03125)
        chart.scatter([x], [l], c=ORANGE, s=24, zorder=3)
        tag(chart, x, l, f'{l:.0f} µH', (7 if x < g0 else -43), (16 if x < g0 else -22), ORANGE)
    chart.axvspan(g0-.03, g0+.03, color=TEAL, alpha=.12)
    chart.set(xlabel='总等效气隙 / mm', ylabel='励磁电感 / µH', ylim=(650, 1020), xlim=(.52, .78))
    return fig


def mag_strand_paths():
    fig, (ax, end) = pair(('（a）并绕两根完整线同时连接', '（b）一个电气匝的实体截面'))
    board(ax, '（a）并绕完整线的端部连接')
    for y, color, label in ((5.8, BLUE, '完整线 A   6 匝'), (2.2, ORANGE, '完整线 B   6 匝')):
        wire(ax, ((1, 4), (1.55, 4), (1.55, y), (3.0, y)), color)
        wire(ax, ((7, y), (8.45, y), (8.45, 4), (9, 4)), color)
        box(ax, 3, y - .55, 4, 1.1, label, fill=PALE if y > 4 else WARM, color=color)
        arrow(ax, (2.02, y), (2.86, y), color)
    ax.scatter([1.55, 8.45], [4, 4], s=18, c=INK)
    note(ax, 1.75, 4, '同一始端', INK)
    note(ax, 8.25, 4, '同一末端', INK, 'right')
    board(end, '（b）两个线束的铜截面', 10, 8)
    end.set_aspect('equal', anchor='N')
    for x, color, label, fill in ((2.65, BLUE, 'A · 10 股', PALE), (7.35, ORANGE, 'B · 10 股', WARM)):
        end.add_patch(Circle((x, 4.65), 2.06, ec=color, fc=fill))
        for j, count in enumerate((3, 4, 3)):
            for i in range(count):
                end.add_patch(Circle((x + (i-(count-1)/2)*.86, 4.65 + (j-1)*.9), .34,
                                     ec=color, fc='white'))
        note(end, x, 1.7, label, color, 'center')
    note(end, 5, .64, '两束合计净铜 0.1571 mm²', TEAL, 'center')
    return fig


def mag_layer_stack():
    fig, (ax, detail) = pair(('（a）按电气匝宽核对轴向装配', '（b）按绝缘次序查径向厚度'))
    board(ax, '（a）一层有效宽度 10.0 mm', 12, 8)
    box(ax, .5, 2.05, 11, 3.3, fill='white', color=MUTED)
    for x in (.5, 11):
        box(ax, x, 2.05, .5, 3.3, fill=WARM, color=ORANGE)
    for j in range(10):
        box(ax, 1 + j, 2.22, .9, 2.5, fill=PALE if j % 2 else GREEN, color=BLUE)
        note(ax, 1.45 + j, 3.48, str(j+1), BLUE, 'center', 7.3)
    arrow(ax, (1, 6.0), (11, 6.0), TEAL, '<->')
    note(ax, 6, 6.6, '10.0 mm（扣除两侧留边后）', TEAL, 'center')
    note(ax, 6, 1.23, '10×0.90 + 9×0.10 = 9.90 mm', BLUE, 'center')
    board(detail, '（b）两个径向留边各 0.20 mm')
    offset = .7
    for thickness, label, col, fill in ((.20, '内留边', MUTED, 'white'), (.55, '原边第 1 层  0.55', BLUE, PALE),
                                       (.10, '', MUTED, 'white'), (.55, '原边第 2 层  0.55', BLUE, PALE),
                                       (.30, '绕组间绝缘  0.30', TEAL, GREEN), (.45, '副边  0.45', ORANGE, WARM),
                                       (.20, '外留边', MUTED, 'white')):
        box(detail, 1.0, offset, 7.65, thickness * 2.75, label, fill, col, fontsize=7.7)
        offset += thickness * 2.75
    arrow(detail, (9.05, .7), (9.05, offset), TEAL, '<->')
    note(detail, 5, 7.5, '总厚 2.35 mm，含层间胶带 0.10 mm', TEAL, 'center', fontsize=8.2)
    return fig


def mag_turn_segment():
    fig, (ax, net) = pair(('（a）同一物理层的逐匝位置', '（b）电阻先逐路径相加'))
    board(ax, '（a）串联段有确定的径向位置')
    box(ax, .8, 1.05, 8.5, .60, '骨架基面', fill=PALE, color=MUTED)
    ax.set_aspect('equal', anchor='N')
    for y, color, positions, name in ((2.26, BLUE, [2, 3, 4], 'P1 · 3 匝'),
                                      (3.45, ORANGE, [2.55, 4, 5.45, 6.9], 'S · 4 匝'),
                                      (4.64, BLUE, [5.9, 6.9, 7.9], 'P2 · 3 匝')):
        for x in positions:
            ax.add_patch(Circle((x, y), .31, ec=color, fc='white', lw=1.4))
            ax.scatter([x], [y], color=color, s=9)
        note(ax, .2, y, name, color, fontsize=7.9)
    arrow(ax, (4.2, 2.45), (5.85, 4.5), TEAL, rad=-.2)
    note(ax, 5.08, 6.3, 'P1 与 P2 串联为原边 6 匝', TEAL, 'center')
    note(ax, 5.08, 5.63, '连线示意跨层电气关系', MUTED, 'center')
    board(net, '（b）同截面并联路径的长度')
    for y, v, label, col, fill in ((5.6, 1.0, 'A', BLUE, PALE), (2.4, 1.2, 'B', ORANGE, WARM)):
        wire(net, ((.5, 4), (1.15, 4), (1.15, y), (2, y)), col)
        wire(net, ((8, y), (8.85, y), (8.85, 4), (9.5, 4)), col)
        box(net, 2, y-.65, 6, 1.3, f'路径 {label}   {v:.1f} m', fill=fill, color=col)
    note(net, 5.0, 4, '电导相加 → 1.0909 m', TEAL, 'center')
    return fig


def mag_skin():
    fig, (ax, chart) = pair(('（a）平面扩散模型的电流密度', '（b）铜的集肤深度随频率减小'))
    x = np.linspace(0, 4, 301)
    ax.plot(x, np.exp(-x), c=BLUE)
    ax.fill_between(x, 0, np.exp(-x), alpha=.18, color=TEAL)
    ax.scatter([1], [np.exp(-1)], c=ORANGE, s=25, zorder=3)
    tag(ax, 1, np.exp(-1), '深度 δ 处为表面的 36.8%', 13, 20, ORANGE)
    ax.set(xlabel='离表面深度 / δ', ylabel='电流密度幅值 / 表面幅值', xlim=(0, 4), ylim=(0, 1.1))
    f = np.geomspace(1e4, 1e6, 251)
    d = np.sqrt(1.72e-8 / (np.pi * f * (4*np.pi*1e-7))) * 1e3
    chart.loglog(f / 1e3, d, c=BLUE)
    chart.axhline(.10, c=ORANGE, ls='--', lw=1, label='裸铜股线直径 0.10 mm')
    for j in (0, 125, 250):
        chart.scatter([f[j] / 1e3], [d[j]], c=TEAL, s=18)
        tag(chart, f[j]/1e3, d[j], f'{d[j]:.3f} mm', 8 if j < 250 else -65, 8 if j < 250 else -1, TEAL)
    chart.set(xlim=(8, 1250), ylim=(.048, .90), ylabel='集肤深度 / mm', xlabel='频率 / kHz')
    chart.legend(loc='upper right')
    return fig


def mag_nse_shape():
    fig, (ax, chart) = pair(('（a）固定 0.16 T 摆幅，改变充磁时间', '（b）按各段时间积分损耗权重'))
    for duty, col in ((.5, BLUE), (.25, ORANGE)):
        ax.plot([0, duty, 1], [-.08, .08, -.08], c=col, label=f'D = {duty:.2f}')
    ax.axhline(0, color=MUTED, lw=.8)
    ax.set(xlim=(0, 1), ylim=(-.101, .116), xlabel='归一化周期 / T', ylabel='磁密 / T', xticks=[0,.25,.5,.75,1])
    ax.legend(loc='lower center')
    d = np.array([.5, .25])
    up, down = d**(-.5), (1 - d)**(-.5)
    chart.bar([0, 1], up, width=.51, color=BLUE, label='上升段')
    chart.bar([0, 1], down, bottom=up, width=.51, color=TEAL, label='下降段')
    for x, y in enumerate(up + down):
        note(chart, x, y+.12, f'{y:.3f}', INK, 'center')
    chart.set(xticks=[0, 1], xticklabels=['0.50', '0.25'], xlabel='上升段占空比 D',
              ylabel='无量纲斜率权重', ylim=(0, 4.2))
    chart.legend(ncols=2, loc='upper center')
    return fig


def mag_thermal():
    fig, (ax, chart) = pair(('（a）同一磁件的两路热源', '（b）绕组电阻随铜温度升高'))
    board(ax, '（a）整体至环境的集总热路')
    for x, label, fill, col in ((.4, '绕组\n1.20 W', PALE, BLUE), (5.1, '磁芯\n0.80 W', WARM, ORANGE)):
        box(ax, x, 5.8, 4.5, 1.3, label, fill=fill, color=col)
        arrow(ax, (x+2.25, 5.8), (5, 4.42), col)
    box(ax, 1.7, 3.13, 6.6, 1.28, '整体等效热源 2.00 W', fill=GREEN, color=TEAL)
    arrow(ax, (5, 3.13), (5, 1.85))
    note(ax, 5.31, 2.45, '12 K/W', TEAL)
    box(ax, 1.7, .48, 6.6, 1.25, '环境温度  ＋  24 K', fill=GREEN, color=TEAL)
    t = np.linspace(20, 110, 100)
    chart.plot(t, 100 * (1 + .00393*(t-20)), c=BLUE)
    chart.scatter([20, 80], [100, 123.58], c=ORANGE, s=22, zorder=3)
    tag(chart, 80, 123.58, '80 °C → 123.6 mΩ', -105, 25, ORANGE)
    chart.set(xlabel='代表性铜温度 / °C', ylabel='绕组直流电阻 / mΩ', xlim=(16, 111), ylim=(95, 142))
    chart.grid(alpha=.2)
    return fig


def fet_events():
    fig, (ax, chart) = pair(('（a）每个斜坡的起点和终点', '（b）四行事件参数分别冻结'))
    for turn_on, turn_off, color, label in ((3, 5, BLUE, '低线示例'), (1.5, 3, ORANGE, '高线示例')):
        ax.plot([0, .46, 1], [turn_on, turn_off, turn_on], c=color, label=label)
        ax.scatter([0, .46], [turn_on, turn_off], c=color, s=24)
        tag(ax, 0, turn_on, f'{turn_on:g} A', 6, 11, color)
        tag(ax, .46, turn_off, f'{turn_off:g} A', 10, 6, color)
    ax.set(xlim=(-.04, 1.05), ylim=(.84, 5.95), xlabel='相位 / 周期', ylabel='连续储能支路电流 / A',
           xticks=[0, .46, 1], xticklabels=['开通', '关断', '下一开通'])
    ax.legend(loc='upper right')
    board(chart, '（b）按输入端点和边沿索引')
    for j, (name, current, color, fill) in enumerate((('低线 · 开通', 3, BLUE, PALE), ('低线 · 关断', 5, BLUE, PALE),
                                                     ('高线 · 开通', 1.5, ORANGE, WARM), ('高线 · 关断', 3, ORANGE, WARM))):
        y = 6.3 - 1.44 * j
        box(chart, .45, y, 4.1, 1.02, name, fill=fill, color=color)
        box(chart, 5.0, y, 4.45, 1.02, f'{current:g} A → 查平台与电荷', fill=fill, color=color, fontsize=8.5)
    return fig


def fet_gate_rc():
    fig, (ax, scope) = pair(('（a）驱动路径与电压参考', '（b）平台之前的指数充电'))
    board(ax, '（a）栅极电流由总栅阻决定')
    box(ax, .70, 3.03, 2.2, 2.2, '驱动器\n10 V', fill=GREEN, color=TEAL)
    box(ax, 3.75, 4.31, 2.13, .68, '8 Ω', fill=WARM, color=ORANGE)
    wire(ax, ((2.9, 4.65), (3.75, 4.65)))
    wire(ax, ((5.88, 4.65), (8.4, 4.65)))
    arrow(ax, (3.22, 5.73), (6.73, 5.73))
    note(ax, 4.98, 6.28, '$i_G=(10-v_G)/8$', TEAL, 'center')
    capsym(ax, 8.4, 4.65, 2.06)
    wire(ax, ((8.4, 2.06), (2.22, 2.06), (2.22, 3.03)), MUTED)
    note(ax, 8.02, 3.35, '1 nF', BLUE, 'right')
    note(ax, 5.32, 1.36, '源极为 0 V 参考点', MUTED, 'center')
    t = np.linspace(0, 6.3, 301)
    gv = 10 * (1 - np.exp(-t/8))
    scope.plot(t, gv, c=BLUE)
    for v in (2, 4):
        at = -8*np.log(1-v/10)
        scope.plot([0, at, at], [v, v, 0], c=MUTED, lw=.9, ls=':')
        scope.scatter([at], [v], c=ORANGE, s=22, zorder=4)
        tag(scope, at, v, f'{v} V · {at:.2f} ns', 8, (-21 if v == 2 else 15), ORANGE)
    scope.set(xlabel='从驱动跳高起算 / ns', ylabel='栅源电压 / V', xlim=(0, 6.3), ylim=(0, 6.1))
    return fig


def fet_gate_timing():
    fig = figure(height=4)
    axes = fig.subplots(2, 1)
    for ax, title, points, vg, cols in (
        (axes[0], '（a）开通段从本次充电起点计算', [0, 1.79, 4.09, 12.09, 20.09],
         [0, 2, 4, 4, 9.7], (PALE, GREEN, WARM, PALE)),
        (axes[1], '（b）关断段从本次放电起点计算', [0, 5.55, 15.15, 20.04, 44.04],
         [10, 5, 5, 2, .1], (PALE, WARM, GREEN, PALE))):
        panel_label(ax, title)
        begin = 1 if ax is axes[0] else 5
        for k, (a, b, color) in enumerate(zip(points[:-1], points[1:], cols), begin):
            ax.axvspan(a, b, color=color)
            note(ax, (a+b)/2, 11.5, f'$t_{k}$', INK, 'center')
        ax.plot(points, vg, c=BLUE, marker='o', markersize=3)
        ax.set(ylabel='$v_{GS}$ / V', ylim=(-.2, 13), xlim=(0, points[-1]),
               xticks=points, xlabel='从本次边沿开始的时间 / ns')
    return fig


def fet_overlap():
    fig, (ax, energy) = pair(('（a）阻性线性换流的电流与电压', '（b）面积产生形状系数'))
    u = np.linspace(0, 1, 201)
    ax.plot(u, 1-u, c=BLUE, label='$v_{DS}/V_{DS}$')
    ax.plot(u, u, c=ORANGE, ls='--', label='$i_D/I$')
    ax.legend(loc='upper center')
    ax.set(xlabel='换流进程 u', ylabel='无量纲电压或电流', xlim=(0, 1), ylim=(0, 1.14))
    energy.plot(u, u * (1-u), c=TEAL, label='$u(1-u)$')
    energy.fill_between(u, 0, u * (1-u), color=TEAL, alpha=.23)
    note(energy, .5, .115, '归一化面积 1/6', TEAL, 'center')
    energy.set(xlabel='换流进程 u', ylabel='瞬时功率 / ($V_{DS}I$)', ylim=(0, .33), xlim=(0, 1))
    energy.legend(loc='upper right')
    return fig


def diode_event():
    fig, (ax, chart) = pair(('（a）一次导通与恢复的两个时间尺度', '（b）单次反恢复的累积电荷'))
    ax.plot([0, 5, 5, 10], [2, 2, 0, 0], c=BLUE)
    ax.fill_between([0, 5], 0, 2, color=TEAL, alpha=.2)
    ax.axvline(5, c=ORANGE, ls=':', lw=1.2)
    tag(ax, 5, .02, '此处放大至右图\n恢复时间 20 ns', 12, 40, ORANGE)
    note(ax, 2.5, .86, '正向电荷 10 µC', TEAL, 'center')
    ax.set(xlabel='主周期时间 / µs', ylabel='正向电流 / A', xlim=(0, 10), ylim=(-.2, 2.5))
    tx = [0, 6, 20]
    chart.plot(tx, [0, -1, 0], c=ORANGE)
    chart.fill_between(tx, 0, [0, -1, 0], color=ORANGE, alpha=.25)
    chart.axhline(0, c=MUTED, lw=.8)
    note(chart, 9, -.34, '$Q_{rr}$ = 10 nC', ORANGE, 'center')
    chart.set(xlabel='相对电流过零的时间 / ns', ylabel='恢复电流 / A', xlim=(0, 20), ylim=(-1.15, .18))
    return fig


def clamp_paths():
    fig, axes = pair(('（a）关断后先给等效端口电容充电', '（b）钳位管导通时向钳位电容送电'))
    for idx, ax in enumerate(axes):
        board(ax, ('（a）漏感电流给端口电容充电', '（b）钳位导通后电流改道')[idx])
        wire(ax, ((1.0, 1.3), (9.0, 1.3)), MUTED)
        box(ax, .55, 3.43, 2.2, 1.40, '漏感\n＋反射源', fill=PALE, color=BLUE)
        wire(ax, ((1.65, 3.43), (1.65, 1.3)), MUTED)
        wire(ax, ((1.65, 4.83), (1.65, 6.0), (6.15, 6.0)))
        capsym(ax, 4.98, 6.0, 1.3, TEAL if idx == 0 else MUTED)
        note(ax, 4.47, 3.63, '$C_{oss}$', TEAL if idx == 0 else MUTED, 'right')
        box(ax, 6.15, 5.53, 1.6, .94, '钳位管', fill=WARM if idx else 'white', color=ORANGE if idx else MUTED, fontsize=8.2)
        wire(ax, ((7.75, 6.0), (8.66, 6.0)))
        capsym(ax, 8.66, 6.0, 1.3, ORANGE if idx else MUTED)
        note(ax, 8.16, 3.63, '$C_{cl}$', ORANGE if idx else MUTED, 'right')
        ax.scatter([4.98], [6.0], s=18, c=INK, zorder=4)
        arrow(ax, (2.42, 6.22), (4.48, 6.22), TEAL if idx == 0 else ORANGE)
        if idx:
            arrow(ax, (5.25, 6.72), (8.52, 6.72), ORANGE)
            arrow(ax, (9.13, 5.47), (9.13, 4.56), ORANGE)
        else:
            arrow(ax, (5.36, 5.45), (5.36, 4.48), TEAL)
        note(ax, 5.05, .61, '母线参考节点', MUTED, 'center')
    return fig


def clamp_energy():
    fig, (chart, ax) = pair(('（a）首波瓣与钳位接收的能量分配', '（b）从每次能量到泄放值'))
    for x, parts in enumerate((((.64, TEAL), (3.36, BLUE)), ((3.36, BLUE), (4.20, ORANGE)))):
        bottom = 0
        for value, col in parts:
            chart.bar([x], [value], bottom=[bottom], width=.52, color=col)
            ax_label = f'{value:g}'
            if value > 1:
                note(chart, x, bottom + value/2, ax_label, 'white', 'center')
            else:
                tag(chart, x-.23, .37, ax_label, -29, 12, TEAL)
            bottom += value
    chart.set(xticks=[0, 1], xticklabels=['漏感初始储能', '钳位接收能量'], ylabel='能量 / µJ',
              ylim=(0, 8.45), xlim=(-.65, 1.61))
    note(chart, 1, 7.98, '7.56 µJ', ORANGE, 'center')
    board(ax, '（b）100 kHz 固定工况的 R、C')
    for y, label, col, fill in ((6.10, '每次接收 7.56 µJ', BLUE, PALE), (4.08, '平均功率 0.756 W', TEAL, GREEN),
                                 (2.06, '180 V  →  42.9 kΩ', ORANGE, WARM), (.34, '42.0 nC ÷ 18 V  →  2.33 nF', ORANGE, WARM)):
        box(ax, .5, y, 9, 1.08, label, fill=fill, color=col)
        if y > 1:
            arrow(ax, (5, y), (5, y - .61), col)
    return fig


def ringing_local():
    fig, (ax, chart) = pair(('（a）在同一电压参考下列方程', '（b）串联损耗改变振铃包络'))
    board(ax, '（a）集中参数换流端口')
    box(ax, .48, 5.5, 2.23, 1.00, '$L$', fill=PALE, color=BLUE)
    box(ax, 3.05, 5.5, 2.0, 1.00, '$R$', fill=WARM, color=ORANGE)
    wire(ax, ((.48, 6), (.22, 6), (.22, 1.3), (9.20, 1.3)))
    wire(ax, ((2.71, 6), (3.05, 6)))
    wire(ax, ((5.05, 6), (8.58, 6)))
    capsym(ax, 6.18, 6, 1.3)
    note(ax, 5.7, 3.6, '$C$', BLUE, 'right')
    wire(ax, ((8.58, 6), (8.58, 5.35)), ORANGE)
    box(ax, 8.06, 4.37, 1.04, .98, '$R_s$', fill=WARM, color=ORANGE)
    capsym(ax, 8.58, 4.37, 1.3, ORANGE)
    note(ax, 8.01, 2.8, '$C_s$', ORANGE, 'right')
    ax.scatter([6.18, 6.18], [6, 1.3], c=INK, s=16)
    note(ax, 6.18, 6.52, '$u$ 对平台', INK, 'center')
    arrow(ax, (1.32, 6.92), (3.74, 6.92), TEAL)
    note(ax, 2.5, 7.32, '$i$', TEAL, 'center')
    t = np.linspace(0, 210e-9, 701)
    l, c = 500e-9, 200e-12
    for r, col, label in ((0, BLUE, 'R = 0 Ω'), (20, ORANGE, 'R = 20 Ω')):
        damp = r/(2*l)
        wd = np.sqrt(1/(l*c) - damp**2)
        u = np.exp(-damp*t)*np.sin(wd*t)/(c*wd)
        chart.plot(t*1e9, u, color=col, label=label)
    chart.axhline(0, c=MUTED, lw=.8)
    chart.set(xlabel='换流开始后 / ns', ylabel='相对平台电压 / V', xlim=(0, 210), ylim=(-62, 67))
    chart.legend(loc='upper right')
    return fig


def ringing_probe():
    fig, axes = pair(('（a）长地线会围出较大环面积', '（b）缩短回路并保留时间参考'))
    for j, ax in enumerate(axes):
        board(ax, ('（a）探头附加环路面积较大', '（b）同一点采用短回路')[j])
        box(ax, .5, 2.05, 8.93, 1.14, '试验板', fill=PALE, color=MUTED)
        for x, label in ((3.27, '漏极焊盘'), (5.28, '源极焊盘')):
            ax.scatter([x], [3.2], c=INK, s=30, zorder=5)
            note(ax, x, 1.45, label, INK, 'center')
        box(ax, 1.25, 4.88, 4.7, 1.28, '探头本体', fill=GREEN, color=TEAL)
        wire(ax, ((3.27, 4.88), (3.27, 3.20)), BLUE, lw=2)
        if j == 0:
            wire(ax, ((5.95, 5.51), (8.35, 5.51), (8.35, 3.74), (5.28, 3.2)), ORANGE, lw=2)
            ax.fill([3.27, 3.27, 8.35, 8.35, 5.28], [3.2, 5.51, 5.51, 3.74, 3.2],
                    color=ORANGE, alpha=.19)
            note(ax, 6.6, 6.45, '长地线引回源极', ORANGE, 'center')
        else:
            wire(ax, ((5.29, 4.88), (5.29, 3.2)), TEAL, lw=2.4)
            ax.fill_between([3.27, 5.28], 3.2, 4.88, color=TEAL, alpha=.17)
            note(ax, 6.7, 4.12, '短回路', TEAL)
        note(ax, 5.0, .54, '图中标出同一对测量节点', MUTED, 'center')
    return fig


def device_ledger():
    fig, (chart, ax) = pair(('（a）55 W 输入的实际分配', '（b）只将端口输出计为有用功率'))
    cats = ['半导体', '磁件', '电容', '钳位及其他']
    vals = [2.60, 1.30, .20, .90]
    chart.barh(np.arange(4), vals, color=[BLUE, TEAL, MUTED, ORANGE], height=.6)
    for i, v in enumerate(vals):
        note(chart, v+.07, i, f'{v:.2f}', INK)
    chart.set(yticks=np.arange(4), yticklabels=cats, xlabel='损耗 / W', xlim=(0, 3.45))
    chart.invert_yaxis()
    board(ax, '（b）按同一套物理边界结算')
    box(ax, .6, 6.05, 8.8, 1.16, '输入端口 55.00 W', fill=GREEN, color=TEAL)
    arrow(ax, (4.84, 6.05), (2.73, 4.53), BLUE)
    arrow(ax, (5.16, 6.05), (7.26, 4.53), ORANGE)
    box(ax, .38, 3.2, 4.62, 1.3, '输出 50.00 W', fill=PALE, color=BLUE)
    box(ax, 5.18, 3.2, 4.45, 1.3, '耗散 5.00 W', fill=WARM, color=ORANGE)
    note(ax, 5, 1.34, '50.00 ÷ 55.00 = 90.91%', TEAL, 'center', fontsize=10)
    return fig


FIGURES = {
    'parts-cap-paths': (cap_paths, 'Buck 与反激的输出节点电流路径',
                        '箭头在电容充电时向下。反激整流管截止时，负载电流由输出电容供给。'),
    'parts-cap-impedance': (cap_impedance, '串联 RLC 的阻抗幅值与相位',
                            '每个圆点均在本支路的自谐振点，幅值为名义 ESR，相位由负变正。'),
    'parts-cap-measurement': (cap_measurement, '实测复阻抗的对数频率插值',
                              '合成测点示例。位于对数频率中点的 60 kHz 对应复平面线段中点。'),
    'parts-cap-phasors': (cap_phasors, '并联电容的相量求和',
                          '计算采用两颗名义串联 RLC。右图两支路箭头依次连接，末端落在总电流的端点。'),
    'parts-cap-harmonics': (cap_harmonics, '从频点电流柱到支路损耗柱',
                            '三个频点各自计算电流分配及耗散，每颗电容的柱高再求和。'),
    'parts-cap-voltage': (cap_voltage_components, '同一电流驱动的 C、ESR 和 ESL 纹波',
                          '图用单颗串联 RLC 的理想三角电流。斜率转折处的 ESL 台阶来自理想化的边沿。'),
    'parts-cap-step': (cap_step, '输出节点亲历的电压上跳和电荷积累',
                       '输入激励增加 1 A。端口电压可立即跨过 ESR 上跳，理想电容的内电压保持连续。'),
    'parts-mag-window': (mag_window, '面积乘积初筛后的两个方向校核',
                         '中心柱标记表示垂直于磁通方向的有效截面。绕线窗口在磁芯正视图中可见，匝数取整后再核算。'),
    'parts-mag-bias': (mag_bias, '磁密偏置、磁密摆幅和正反伏秒',
                       '两条磁密曲线的摆幅相同，正向最高点和最大绝对值随偏置改变。'),
    'parts-mag-e-core': (mag_e_core, '中心柱研磨与三柱同厚垫片',
                         '示意磁通从中心柱分流到对称外柱。外柱气隙的磁阻按并联等效处理。'),
    'parts-mag-gap-budget': (mag_gap_budget, '安匝分配和气隙加工公差',
                             '图中把加工误差折算为总有效气隙 ±0.03 mm，其他输入保持固定。'),
    'parts-mag-strand-paths': (mag_strand_paths, '并绕完整线的接线与铜截面',
                               '两个完整线各自绕 6 匝，始端互接、末端互接。截面同时包含两组 10 股。'),
    'parts-mag-layer-stack': (mag_layer_stack, '轴向放匝与径向绝缘堆叠',
                              '左图编号表示一个层内逐匝占宽，右图各层厚度以 mm 表示。'),
    'parts-mag-turn-segment': (mag_turn_segment, '物理层、串联段和电阻并联路径',
                               '左图按径向次序摆放段，右图先取得两条完整的电流路径长度。'),
    'parts-mag-skin': (mag_skin, '集肤电流密度的衰减及铜的集肤深度',
                       '左图采用半无限良导体的理想扩散解，右图铜电阻率取 1.72×10⁻⁸ Ω·m。'),
    'parts-mag-nse-shape': (mag_nse_shape, '固定磁密摆幅时的非正弦斜率权重',
                            '斜率指数取 α=1.5。两种工况仅改变上升与下降时间的分配。'),
    'parts-mag-thermal': (mag_thermal, '磁件的整体温升与铜温修正',
                          '左图使用给定整体热阻，右图用 20 °C 时 100 mΩ 的绕组示意铜温修正。'),
    'parts-fet-events': (fet_events, '同一只 MOSFET 的四个换流事件索引',
                         '电流为教学示意。开通、关断和输入端点分别有自己的查表条件。'),
    'parts-fet-gate-rc': (fet_gate_rc, '栅电流路径和平台前的两次读时',
                          '教学算例中两次从零起算均使用 1 nF，平台前电压呈指数增长。'),
    'parts-fet-gate-timing': (fet_gate_timing, '栅压八段的时序与起算点',
                              '两张图各用本次边沿作为零时刻。折线连接事件时刻，相邻端点之间的实际曲线由分段模型给定。'),
    'parts-fet-overlap': (fet_overlap, '阻性线性换流的交叠积分',
                          '将电流、电压乘积的归一化面积乘回电压、电流和时间，得到能量。'),
    'parts-diode-event': (diode_event, '二极管正向导通与反恢复的两个时间尺度',
                          '左图以微秒计整周期，右图以纳秒计反恢复电流。两段都按面积求电荷。'),
    'parts-clamp-paths': (clamp_paths, '钳位门槛前后的瞬态电流路径',
                          '母线作交流参考，图中省略慢时间尺度的泄放电阻。颜色跟踪两个阶段的电流路径。'),
    'parts-clamp-energy': (clamp_energy, '首波瓣与反射源如何共同决定钳位损耗',
                           '蓝色为钳位接通时剩余漏感能量。反射源在钳位导通阶段继续向钳位支路送入能量。'),
    'parts-ringing-local': (ringing_local, '寄生换流回路和串联阻尼的影响',
                             '左图含可配置的 RC 吸收支路，右图将该支路断开以单独比较串联 R 的作用。'),
    'parts-ringing-probe': (ringing_probe, '相同器件测点的探头回路示意',
                             '两图比较感应回路面积。选用满足实际共模及差模范围的测量系统。'),
    'parts-device-ledger': (device_ledger, '端口效率的损耗分项和能量边界',
                             '左图是 5.00 W 耗散的四项分配，右图将其与 50.00 W 的有用输出合并。'),
}
