"""Worked figures for the small-signal and compensation chapters."""

import numpy as np
from matplotlib.patches import Circle, Rectangle

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


def buck_perturbation():
    fig = figure(height=2.75)
    voltage, current = fig.subplots(1, 2)
    period_us, inductance_uh, vin, vout = 4, 10, 12, 4.8
    for duty, color, style in [(0.40, BLUE, '-'), (0.42, ORANGE, '--')]:
        edge = period_us * duty
        peak = edge * (vin - vout) / inductance_uh
        end = peak - (period_us - edge) * vout / inductance_uh
        voltage.plot([0, edge, edge, period_us], [vin-vout, vin-vout, -vout, -vout],
                     color=color, ls=style, label=f'D = {duty:.2f}')
        current.plot([0, edge, period_us], [0, peak, end], color=color, ls=style)
    voltage.fill_between([1.60, 1.68], -vout, vin-vout, color=ORANGE, alpha=.2)
    voltage.annotate('额外伏秒', xy=(1.64, 1.5), xytext=(2.08, 4),
                     arrowprops={'arrowstyle':'->', 'color':MUTED}, color=INK)
    voltage.set(ylabel='电感电压 / V', ylim=(-7.3, 9.8), yticks=[-4.8, 0, 7.2])
    current.annotate('末值相差 96 mA', xy=(4, .096), xytext=(2.0, 1.26),
                     arrowprops={'arrowstyle':'->', 'color':MUTED})
    current.set(ylabel='相对周期初值的电流 / A', ylim=(-.12, 1.48))
    for ax, title in [(voltage, '关断边沿向右移 0.08 µs'), (current, '同一初值分别积分')]:
        panel_label(ax, title)
        ax.axhline(0, color=MUTED, lw=.6, zorder=0)
        ax.set(xlabel='周期内时间 / µs', xlim=(0, 4.15), xticks=[0, 1, 2, 3, 4])
    voltage.legend(loc='center left', bbox_to_anchor=(0, .41), borderaxespad=.1)
    return fig


def sampled_peak():
    fig = figure(height=2.42)
    axes = fig.subplots(1, 2)
    periods = np.arange(5)
    for ax, pole, color, title, scale in zip(
            axes, [-2., -.5], [ORANGE, BLUE], ['无补偿斜坡', '增加 1 A/µs 补偿斜坡'], [180, 12]):
        points = 10 * pole ** periods
        ax.axhline(0, color=MUTED, lw=.8)
        ax.vlines(periods, 0, points, color=color, lw=2)
        ax.scatter(periods, points, s=26, color=color, zorder=3)
        ax.set(xticks=periods, xlim=(-.3, 4.3), ylim=(-scale, scale),
               xlabel='周期序号 k', ylabel='起始电流偏差 / mA')
        panel_label(ax, title)
    return fig


def qr_cycle_and_slope():
    fig = figure(height=2.65)
    pulse, average = fig.subplots(1, 2)
    lm, vin, reflected, ratio = 800e-6, 300., 120., 2.
    def timings(peak):
        return lm*peak/vin, lm*peak/reflected
    base_on, base_demag = timings(2.)
    base_period = base_on + base_demag
    for peak, color, style in [(2., BLUE, '-'), (2.2, ORANGE, '--')]:
        on, demag = timings(peak)
        t = np.array([0, on, on, on+demag])*1e6
        pulse.plot(t, [0, 0, ratio*peak, 0], color=color, ls=style,
                   label=f'原边峰值 {peak:g} A')
        pulse.fill_between(t, [0, 0, ratio*peak, 0], color=color, alpha=.08)
    pulse.set(xlabel='周期内时间 / µs', ylabel='副边整流电流 / A', xlim=(0, 22), ylim=(-.25, 5.1))
    pulse.legend(loc='upper right', borderaxespad=.1)
    panel_label(pulse, '副边电流的三角形面积')
    peak = np.linspace(1.7, 2.3, 100)
    on, demag = timings(peak)
    charge = .5*ratio*peak*demag
    average.plot(peak, charge/(on+demag), color=BLUE, label='用每点实际周期')
    average.plot(peak, charge/base_period, color=ORANGE, ls='--', label='固定标称周期作对照')
    average.scatter(2, .5*ratio*2*base_demag/base_period, s=23, color=INK, zorder=3)
    average.set(xlabel='原边峰值电流 / A', ylabel='整流平均电流 / A', xlim=(1.7, 2.3))
    average.legend(loc='upper left', borderaxespad=0)
    panel_label(average, '两种算法在标称点的斜率')
    return fig


def example_loop():
    """Unity-feedback teaching example with a crossing at 1 kHz and PM of 60°."""
    omega_c = 2*np.pi*1000
    tau_p = 1/(np.sqrt(3)*omega_c)
    k_int = omega_c*np.sqrt(1+(omega_c*tau_p)**2)
    return tau_p, k_int


def bode_reading():
    fig = figure(height=2.58)
    mag, phase = fig.subplots(1, 2)
    tau, gain = example_loop()
    f = np.geomspace(100, 10000, 401)
    s = 2j*np.pi*f
    loop = gain/(s*(1+s*tau))
    for ax in (mag, phase):
        ax.axvline(1000, color=MUTED, ls=':', lw=1)
        ax.set(xscale='log', xlim=(100, 10000), xlabel='频率 / Hz')
    mag.semilogx(f, 20*np.log10(np.abs(loop)), color=BLUE)
    mag.axhline(0, color=MUTED, lw=.8)
    mag.plot(1000, 0, 'o', color=ORANGE)
    mag.annotate('1 kHz，0 dB', xy=(1000, 0), xytext=(1300, 14),
                 arrowprops={'arrowstyle':'->', 'color':MUTED})
    mag.set(ylabel='开环增益 / dB')
    phase.semilogx(f, np.angle(loop,deg=True), color=BLUE)
    phase.axhline(-180, color=MUTED, lw=.9)
    phase.annotate('', xy=(1000,-120), xytext=(1000,-180),
                   arrowprops={'arrowstyle':'<->','color':ORANGE,'lw':2})
    phase.plot(1000, -120, 'o', color=ORANGE)
    phase.text(710, -153, '60°', ha='right', color=ORANGE)
    phase.set(ylabel='开环相位 / °', ylim=(-185,-85), yticks=[-180,-150,-120,-90])
    panel_label(mag, '先读单位增益穿越频率')
    panel_label(phase, '在同一频率上读相位')
    return fig


def feedback_disturbance():
    fig = figure(height=2.18)
    ax = fig.subplots()
    ax.set(xlim=(0, 11), ylim=(0, 3.2), aspect='equal')
    ax.axis('off')
    def arrow(a, b, color=INK):
        ax.annotate('', xy=b, xytext=a, arrowprops={'arrowstyle':'-|>', 'color':color,
                                                    'shrinkA':0, 'shrinkB':0, 'lw':1.5})
    def block(x, y, w, name, color):
        ax.add_patch(Rectangle((x,y-.31),w,.62, ec=color, fc='white', lw=1.4))
        ax.text(x+w/2,y,name,ha='center',va='center',color=color)
    def adder(x,y):
        ax.add_patch(Circle((x,y),.19,fc='white',ec=INK,lw=1.3))
        ax.text(x,y,'Σ',ha='center',va='center',color=INK)
    y=1.48
    ax.text(.15,y+.19,'参考增量 r',va='bottom')
    arrow((.18,y),(1.38,y))
    adder(1.57,y)
    ax.text(1.28,y+.11,'+')
    ax.text(1.67,y-.45,'−')
    arrow((1.76,y),(2.4,y))
    block(2.4,y,1.9,'补偿器 Gc',BLUE)
    arrow((4.3,y),(5.0,y))
    ax.text(4.66,y+.12,'u',ha='center')
    block(5.,y,2.1,'功率级 Pu',BLUE)
    arrow((7.1,y),(8.0,y))
    adder(8.19,y)
    ax.text(7.88,y+.09,'+')
    ax.text(8.30,y+.28,'+')
    arrow((8.38,y),(10.68,y))
    ax.text(9.33,y+.18,'输出电压 v',ha='center')
    ax.plot([9.5,9.5,1.57],[y,.42,.42],color=TEAL,lw=1.6)
    ax.scatter(9.5,y,color=TEAL,s=18,zorder=3)
    arrow((1.57,.42),(1.57,y-.19),TEAL)
    ax.text(5.45,.57,'取样端电压反馈',color=TEAL,ha='center')
    ax.text(2.8,2.79,'负载增量 ℓ',color=ORANGE,va='center')
    arrow((4.12,2.79),(5.,2.79),ORANGE)
    block(5.,2.79,2.1,'扰动通道 Pℓ',ORANGE)
    ax.plot([7.1,8.19],[2.79,2.79],color=ORANGE,lw=1.5)
    arrow((8.19,2.79),(8.19,y+.19),ORANGE)
    return fig


def feedback_step_pair():
    fig = figure(height=2.42)
    ax = fig.subplots()
    tau, gain = example_loop()
    alpha = 1/(2*tau)
    beta = np.sqrt(gain/tau-alpha**2)
    t = np.linspace(0, .00125, 801)
    edge_ohms, dc_ohms = .020, .100
    h = -np.exp(-alpha*t)*(edge_ohms*np.cos(beta*t)
                           + (dc_ohms/tau-alpha*edge_ohms)/beta*np.sin(beta*t))
    t_ms = np.r_[-.10, 0, t*1000]
    for step, color, style, label in [(1.6,BLUE,'-','10% → 90% 加载'),
                                      (-1.6,ORANGE,'--','90% → 10% 卸载')]:
        ax.plot(t_ms,np.r_[0,0,1000*step*h],color=color,ls=style,label=label)
    ax.axhline(0,color=MUTED,lw=.6)
    ax.annotate('加载最低点约 −98 mV', xy=(.1095,-98.19),xytext=(.35,-86),
                arrowprops={'arrowstyle':'->','color':MUTED})
    ax.set(xlabel='距负载跳变的时间 / ms', ylabel='相对 12 V 的偏差 / mV',
           xlim=(-.10,1.25),ylim=(-120,120),yticks=[-100,-50,0,50,100])
    ax.legend(loc='upper right')
    return fig


FIGURES = {
    'buck_perturbation': (buck_perturbation, '占空比微调怎样改变周期末电流',
                         '左图两条电压阶梯之间的窄条面积，除以电感后就是右图末端的电流差。'),
    'sampled_peak': (sampled_peak, '同一初始电流误差在五个周期边界的演变',
                    '从左向右读各采样点。两图起点相同，纵轴量程分别适应发散和衰减的幅值。'),
    'qr_cycle_slope': (qr_cycle_and_slope, 'QR 峰流变化同时移动退磁终点和周期终点',
                      '左图取零等待的理想边界。右图两线交于同一工作点，局部斜率由每次使用的周期决定。'),
    'bode_reading': (bode_reading, '由同一条开环传函读出穿越频率与相位裕度',
                    '左图的圆点给出穿越频率。沿同一频率移到右图，双向箭头就是距 −180° 的相位余量。'),
    'feedback_disturbance': (feedback_disturbance, '负载电流扰动和稳压反馈的两条信号路径',
                            '橙色支路把外加抽流换算为带符号的电压扰动。绿色支路把合成后的输出送回误差加法点。'),
    'feedback_step_pair': (feedback_step_pair, '同一线性闭环的加载与卸载响应',
                          '波形由正文的二阶教学模型计算。跳变瞬间、最深偏差与恢复过程分别由曲线的三个位置读出。'),
}
