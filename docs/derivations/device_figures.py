"""Worked illustrations of capacitor, magnetic and semiconductor calculations."""

import numpy as np
from matplotlib.patches import Arc, Rectangle

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


def capacitor_charge():
    fig = figure(height=2.65)
    current, voltage = fig.subplots(1, 2)
    t = np.linspace(0, 10, 401)   # µs, two straight ramps over one switching cycle
    i = np.interp(t, [0, 2.5, 7.5, 10], [0, .6, -.6, 0])
    q = np.r_[0, np.cumsum(.5 * (i[:-1] + i[1:]) * np.diff(t))]  # µC
    panel_label(current, '（a）电容电流与电荷')
    current.axhline(0, lw=.8, color=MUTED)
    current.fill_between(t, 0, i, where=i >= 0, color=TEAL, alpha=.21)
    current.fill_between(t, 0, i, where=i <= 0, color=ORANGE, alpha=.18)
    current.plot(t, i, color=BLUE)
    current.text(2.5, .17, '+1.50 µC', ha='center', color=TEAL)
    current.text(7.5, -.19, '−1.50 µC', ha='center', va='top', color=ORANGE)
    current.set(ylabel='流入电容的电流 / A', ylim=(-.7, .7), yticks=[-.6, 0, .6])
    panel_label(voltage, '（b）电荷积累成为端电压')
    voltage.plot(t, q / 100 * 1000, color=BLUE)  # mV for 100 µF
    voltage.scatter([5], [15], color=TEAL, s=20, zorder=3)
    voltage.annotate('电流过零\n电压达到最高点', xy=(5, 15), xytext=(.18, 12.8),
                     color=TEAL, fontsize=8, arrowprops={'arrowstyle': '-', 'color': TEAL})
    voltage.set(ylabel='相对于周期起点的电压 / mV', ylim=(-1, 17.5), yticks=[0, 5, 10, 15])
    for ax in (current, voltage):
        ax.axvline(5, lw=.8, color=MUTED, ls=':', zorder=0)
        ax.set(xlabel='时间 / µs', xlim=(0, 10), xticks=[0, 2.5, 5, 7.5, 10])
    return fig


def capacitor_network():
    fig = figure(height=2.68)
    circuit, share = fig.subplots(1, 2, gridspec_kw={'width_ratios': [.97, 1.16]})
    panel_label(circuit, '（a）两颗电容共用端电压')
    circuit.axis('off')
    circuit.set(xlim=(-.2, 4), ylim=(0, 3.6))
    circuit.plot([.25, 2.65], [3, 3], color=INK, lw=1.1)
    circuit.plot([.25, 2.65], [.36, .36], color=INK, lw=1.1)
    circuit.annotate('', xy=(.92, 3), xytext=(.15, 3),
                     arrowprops={'arrowstyle': '->', 'color': INK})
    circuit.text(.23, 3.16, 'I', color=INK)
    for k, (x, col) in enumerate(((1.05, BLUE), (2.65, ORANGE)), 1):
        circuit.plot([x, x], [3, 2.63], color=col, lw=1.35)
        circuit.add_patch(Rectangle((x-.12, 2.22), .24, .41, ec=col, fc='none', lw=1.35))
        circuit.plot([x, x], [2.22, 2.02], color=col, lw=1.35)
        for y in np.linspace(1.88, 1.32, 3):
            circuit.add_patch(Arc((x, y), .27, .28, theta1=-90, theta2=90, color=col, lw=1.35))
        circuit.plot([x, x], [1.18, .98], color=col, lw=1.35)
        for y in (.98, .85):
            circuit.plot([x-.23, x+.23], [y, y], color=col, lw=1.5)
        circuit.plot([x, x], [.85, .36], color=col, lw=1.35)
        for y, label in [(2.42, 'R'), (1.57, 'L'), (.91, 'C')]:
            circuit.text(x+.3, y, f'{label}{k}', va='center', fontsize=8.5, color=col)
        circuit.scatter([x, x], [3, .36], color=INK, s=10, zorder=3)
    panel_label(share, '（b）同一交流激励的分配')
    f = np.geomspace(10e3, 10e6, 400)
    w = 2 * np.pi * f
    z1 = .060 + 1j * (w*8e-9 - 1/(w*100e-6))
    z2 = .010 + 1j * (w*1e-9 - 1/(w*1e-6))
    for b, h, c in [(1, z2/(z1+z2), BLUE), (2, z1/(z1+z2), ORANGE)]:
        share.semilogx(f/1000, abs(h), color=c, label=f'支路 {b}', ls='-' if b == 1 else '--')
    share.axhline(1, color=MUTED, ls=':', lw=.8)
    share.axvline(1000, color=MUTED, ls=':', lw=.8)
    share.legend(ncols=2, loc='lower left', bbox_to_anchor=(0, .10))
    share.set(xlabel='频率 / kHz', ylabel='支路电流幅值 / 总电流幅值',
              xlim=(10, 10000), ylim=(0, 1.55), yticks=[0, .5, 1, 1.5])
    return fig


def magnetic_gap():
    fig = figure(height=2.55)
    core, inductance = fig.subplots(1, 2)
    panel_label(core, '（a）沿一条闭合磁路观察气隙')
    core.axis('off')
    core.set(xlim=(0, 4), ylim=(.1, 3), aspect='equal')
    core.add_patch(Rectangle((.5, .42), 2.35, 2.13, lw=1, ec=INK, fc='#d6e4e8'))
    core.add_patch(Rectangle((1.06, .93), 1.23, 1.12, lw=1, ec=INK, fc='white'))
    core.add_patch(Rectangle((2.285, 1.48), .57, .17, lw=0, fc='white'))
    for y in np.linspace(1.12, 1.87, 5):
        core.plot([.36, 1.17], [y-.08, y+.08], lw=2.5, color=ORANGE, solid_capstyle='round')
    core.text(.32, .12, '绕组 N 匝', color=ORANGE)
    core.annotate('', xy=(2.27, 2.30), xytext=(1.10, 2.30),
                  arrowprops={'color': TEAL, 'arrowstyle': '->', 'lw': 1.8})
    core.text(1.32, 2.63, '磁通 Φ', color=TEAL)
    core.annotate('气隙 g', xy=(2.63, 1.56), xytext=(3.08, 1.80),
                  color=INK, fontsize=9, arrowprops={'arrowstyle': '-', 'color': INK})
    panel_label(inductance, '（b）气隙与励磁电感')
    gap = np.linspace(.2, 1.4, 300)  # mm
    factor = 4*np.pi*1e-7*120e-6*60**2
    lm = factor/((gap+.03125)*1e-3)
    inductance.plot(gap, lm*1e6, color=BLUE)
    mark = (factor/.0008 - .075/2400)*1e3
    inductance.plot([mark], [800], 'o', color=ORANGE)
    inductance.annotate('0.647 mm\n800 µH', xy=(mark, 800), xytext=(.87, 1250),
                        color=ORANGE, fontsize=8.5, arrowprops={'arrowstyle': '-', 'color': ORANGE})
    inductance.set(xlabel='总等效气隙 / mm', ylabel='励磁电感 / µH', xlim=(.2, 1.4),
                   ylim=(0, 2500), yticks=[0, 800, 1600, 2400])
    return fig


def winding_unwrapped():
    fig = figure(height=2.4)
    section, developed = fig.subplots(1, 2)
    panel_label(section, '（a）截面上的匝心')
    section.set(xlim=(0, 3.1), ylim=(0, 1.1), aspect='equal')
    section.axis('off')
    section.add_patch(Rectangle((.04, .13), 2.94, .24, ec=MUTED, fc='#d6e4e8'))
    section.text(1.51, .25, '骨架绕制面', va='center', ha='center', fontsize=8)
    for i, x in enumerate((.5, 1.35, 2.2), 1):
        section.add_patch(Arc((x,.54),.34,.34,theta1=0,theta2=360,color=ORANGE,lw=2.2))
        section.plot(x, .54, '.', color=ORANGE)
        section.text(x, .79, f'第 {i} 匝', ha='center', fontsize=8)
    section.annotate('', xy=(1.35,.54), xytext=(.5,.54),
                     arrowprops={'arrowstyle': '<->', 'color': BLUE, 'lw':1})
    section.text(.92, .97, '相邻匝中心距 Δx', ha='center', fontsize=8.4, color=BLUE)
    panel_label(developed, '（b）展开相邻匝间的一周')
    developed.set(xlim=(-.1, 2.90), ylim=(-.40, 1.05), aspect='equal')
    developed.axis('off')
    developed.plot([.16, 2.56, 2.56], [.04, .04, .80], color=MUTED, ls='--', lw=1)
    developed.plot([.16, 2.56], [.04,.80], color=ORANGE, marker='o', ms=3.5)
    developed.text(1.36, -.20, '周向长度 P', va='center', ha='center', color=MUTED)
    developed.text(2.61,.42, 'Δx', va='center', fontsize=9, color=BLUE)
    developed.text(1.25,.61,'导线中心线', color=ORANGE, ha='center', rotation=18)
    return fig


def gate_charge():
    fig = figure(height=2.45)
    ax = fig.subplots()
    panel_label(ax, '一次开通，按栅极累计电荷读出电压变化')
    # Teaching segments, linear interpolation between charge-plot endpoints.
    ax.axvspan(2, 4, color=TEAL, alpha=.09)
    ax.axvspan(4, 10, color=ORANGE, alpha=.12)
    ax.plot([0, 2, 4, 10, 14], [0, 2, 4, 4, 10], color=BLUE, marker='o', ms=3.5)
    ax.text(1.05, 5.9, '至阈值\n2 nC', ha='center', va='center', fontsize=8.8)
    ax.text(3, 7.6, '至平台\n再充 2 nC', ha='center', fontsize=8.8, color=TEAL)
    ax.text(7, 5.2, 'Miller 平台 4 V\n转移电荷 6 nC', ha='center', color=ORANGE)
    ax.text(12.3, 3.2, '平台后\n栅压继续上升', ha='center', fontsize=8.8)
    ax.set(xlabel='累计栅极电荷 / nC', ylabel='栅源电压 / V', xticks=[0, 2, 4, 6, 8, 10, 12, 14],
           xlim=(-.25, 14.25), yticks=[0,2,4,6,8,10], ylim=(-.4, 10.7))
    return fig


def leakage_clamp():
    fig = figure(height=2.54)
    volt, curr = fig.subplots(1, 2)
    l, c, i0, vref, vcl = 2e-6, 200e-12, 2., 100., 180.
    tau, z = np.sqrt(l*c), np.sqrt(l/c)
    angle = np.arcsin((vcl-vref)/(i0*z))
    a = tau*angle
    ic = i0*np.cos(angle)
    b = a+l*ic/(vcl-vref)
    t1, t2 = np.linspace(0, a, 120), np.linspace(a, b, 120)
    panel_label(volt, '（a）钳位支路何时接通')
    volt.plot(t1*1e9, vref+i0*z*np.sin(t1/tau), color=BLUE)
    volt.plot(t2*1e9, np.full_like(t2, vcl), color=ORANGE)
    volt.scatter([a*1e9], [vcl], color=ORANGE, s=18)
    volt.text(26, 168, '钳位导通', color=ORANGE)
    volt.set(ylabel='相对输入母线的漏极电压 / V', ylim=(92,195), yticks=[100,140,180])
    panel_label(curr, '（b）导通面积就是钳位电荷')
    curr.plot(t1*1e9, i0*np.cos(t1/tau), color=BLUE, label='漏感电流')
    curr.plot(t1*1e9, np.zeros_like(t1), color=ORANGE, ls='--')
    curr.plot([a*1e9,a*1e9], [0,ic], color=ORANGE, lw=1, ls=':')
    i2=ic-(vcl-vref)/l*(t2-a)
    curr.fill_between(t2*1e9, 0, i2, color=ORANGE, alpha=.19)
    curr.plot(t2*1e9, i2, color=ORANGE, label='导通后的钳位电流')
    curr.text(21,.47, '42.0 nC', color=ORANGE, fontsize=9)
    curr.legend(loc='upper right')
    curr.set(ylabel='电流 / A', ylim=(-.14, 2.17), yticks=[0,1,2])
    for ax in (volt,curr):
        ax.axvline(a*1e9, lw=.8, ls=':', color=MUTED, zorder=0)
        ax.set(xlim=(-1,55), xticks=[0, 8.23, 30, 54.1], xticklabels=['0','8.23','30','54.1'],
               xlabel='从漏感首波瓣起点算起 / ns')
    return fig


FIGURES = {
    'cap-charge': (capacitor_charge, '三角电流的面积与电压纹波',
                   '正半周送入的电荷等于阴影面积，电压峰值出现在电流由正变负时。'),
    'cap-network': (capacitor_network, '并联电容的支路阻抗与频率分流',
                    '在同一频率上比较两条曲线，纵坐标读出每颗电容承担的电流幅值比例。'),
    'magnetic-gap': (magnetic_gap, '磁芯和气隙串联的磁路及计算感量',
                     '沿箭头走一周要经过磁芯和气隙，右图用同一副磁芯和同一匝数改变总等效气隙。'),
    'winding-unwrapped': (winding_unwrapped, '从匝心间距读出螺旋导线的长度',
                          '右图将一个周向周期展开，虚线是周长和轴向位移，实线是导线。'),
    'gate-charge': (gate_charge, '开通栅荷曲线上的阈值与平台',
                    '从横轴读平台两端之差，再用这一段的栅极电流把电荷换算为时间。'),
    'leakage-clamp': (leakage_clamp, '反激钳位首波瓣的电压与电流',
                      '竖虚线标出理想二极管接通时刻，右图只对其后流入钳位支路的电流求面积。'),
}
