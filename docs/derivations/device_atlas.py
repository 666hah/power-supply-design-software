"""器件篇的逐题推导与原理图。各算例的单位和适用条件在题内给出。"""

import numpy as np
from matplotlib.patches import Rectangle

from docs.derivations.illustrations import BLUE, ORANGE, TEAL, INK, MUTED, figure


def _axes(xlabel, ylabel):
    fig = figure(height=2.65)
    ax = fig.subplots()
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.grid(axis='y', alpha=.18)
    return fig, ax


def input_pulse():
    fig, ax = _axes('占空比 D', '电容电流有效值 / A')
    d = np.linspace(0, 1, 301)
    ax.plot(d, 4*np.sqrt(d*(1-d)), color=BLUE, label='导通电流 4 A')
    ax.plot([.25, .5, .75], [np.sqrt(3), 2, np.sqrt(3)], 'o', color=ORANGE)
    ax.set(ylim=(0, 2.3), xticks=[0, .25, .5, .75, 1])
    ax.text(.5, 2.08, '两段时间相等', ha='center')
    ax.legend(loc='lower center')
    return fig


def esr_peaks():
    fig, ax = _axes('时间 / µs', '纹波电压 / mV')
    t = np.linspace(0, 10, 401)
    i = np.interp(t, [0, 5, 10], [-.5, .5, -.5])
    vc = 10*np.r_[0, np.cumsum((i[:-1]+i[1:])/2*np.diff(t))]
    ax.plot(t, vc, '--', color=TEAL, label='电容内部')
    ax.plot(t, 20*i, ':', color=ORANGE, label='串联电阻')
    ax.plot(t, vc+20*i, color=BLUE, label='两端合成')
    ax.scatter([.5, 5.5], [-10.25, 10.25], color=BLUE)
    ax.legend(ncol=3, loc='lower center', bbox_to_anchor=(.5, 1))
    return fig


def self_resonance():
    fig, ax = _axes('频率 / kHz', '阻抗幅值 / mΩ')
    f = np.geomspace(5e4, 5e6, 400)
    w = 2*np.pi*f
    xc, xl = 1/(w*10e-6), w*5e-9
    ax.loglog(f/1e3, xc*1e3, ':', color=TEAL, label='容抗幅值')
    ax.loglog(f/1e3, xl*1e3, '--', color=ORANGE, label='感抗幅值')
    ax.loglog(f/1e3, 1e3*np.hypot(.012, xl-xc), color=BLUE, label='端口阻抗')
    ax.scatter([711.76], [12], color=BLUE, zorder=3)
    ax.legend(ncol=3)
    return fig


def measured_impedance():
    fig, ax = _axes('实部 / mΩ', '虚部 / mΩ')
    z = np.array([30-40j, 20-10j, 10+20j])
    ax.axhline(0, color=MUTED, lw=.8)
    ax.plot(z.real, z.imag, color=BLUE, lw=1.4)
    for index, label in enumerate(('10 kHz', '100 kHz', '1 MHz')):
        ax.scatter(z.real[index], z.imag[index], color=ORANGE if index == 1 else TEAL)
        ax.annotate(label, (z.real[index], z.imag[index]), xytext=(8, 2), textcoords='offset points')
    ax.set(xlim=(0, 40), ylim=(-48, 31))
    return fig


def spectral_heating():
    fig = figure(height=2.65)
    left, right = fig.subplots(1, 2)
    for ax, y, label, color in ((left, [1.2, .6, .2], '电流有效值 / A', BLUE),
                                (right, [28.8, 10.8, 2.4], '该线贡献的损耗 / mW', ORANGE)):
        bars = ax.bar([1, 2, 3], y, width=.45, color=color)
        ax.set(xlabel='谐波次数', ylabel=label, xticks=[1, 2, 3], ylim=(0,max(y)*1.25))
        ax.bar_label(bars, fmt='%g', padding=2)
    return fig


def load_step():
    fig, ax = _axes('负载增加后的时间 / µs', '相对原工作点的电压 / mV')
    t = np.linspace(0, 4, 101)
    ax.plot([-1, 0], [0, 0], color=BLUE)
    ax.plot(t, -8*t, '--', color=TEAL, label='两颗理想电容的内电压')
    ax.plot(np.r_[0,t], np.r_[0,-16-8*t], color=BLUE, label='并联端口')
    ax.annotate('瞬时下降 16 mV', (.04,-16), (.65,-12), arrowprops={'arrowstyle':'->'})
    ax.legend(loc='lower left')
    return fig


def lesson(chapter, title, paragraphs, formula, plot, caption):
    return dict(chapter=chapter, title=title, paragraphs=paragraphs, formula=formula,
                figure=plot, caption=caption)


LESSONS = [
    lesson(9, '输入电容为何在中等占空比承受最大的交流电流', [
        '取连续导通的降压变换器，把输入电容正端作为电流观察点。为看清占空比的作用，设输出电感很大，一个周期内负载电流近似固定为 4 A。输入线只供应周期平均电流。开关导通时从母线取走 4 A，关断时取电为零。暂且忽略输入滤波器在开关频率上的交流供电。',
        '设 D 为导通时间与周期 T 之比。电源均值是 4D A，流入电容的电流在前段为 4D−4 A，后段为 4D A。两个矩形面积代数相加为零。计算发热时先将各自的高度平方，再用所占时长加权。整理后得到下式，I 表示导通段近似恒定的开关电流。图的左右两半关于 D=0.5 对称。',
        '在 100 kHz、D=0.25 下，前 2.5 µs 电容输出 3 A，后 7.5 µs 吸收 1 A，充放电量各为 7.5 µC。100 µF 理想电容的端电压摆幅为 75 mV。均方电流为 0.25×9+0.75×1=3 A²，有效值约 1.73 A。同样的 4 A 导通电流在 D=0.5 时给出 2 A 有效值。',
        '把占空比推到 0 或 1，断续取电消失，图上交流有效值也降到零。比较不同输入电压的实际算例时，还要检查边沿电流与电感纹波是否改变。项目的波形和电容分流计算以实际交流波形为输入，本图只给出平顶取电时的手算基准。'],
        r'I_{C,\mathrm{rms}}=I\sqrt{D(1-D)}', input_pulse, '恒定导通电流时，占空比与输入电容交流负担的关系'),
    lesson(9, '在时间轴上寻找含 ESR 的纹波峰值', [
        '在降压电路的一个 10 µs 周期内，让流入输出电容的电流从 −0.5 A 线性升到 +0.5 A，再线性降回原值，两段各占半周期。取电容 C 为 100 µF，串联电阻 R 为 20 mΩ，暂忽略引线电感。输出端测得的纹波含内部电容的电压变化和电阻上的瞬时压降。',
        '以起点内电压为零参考。三角形电流积分后是分段抛物线，电阻压降仍是三角形。把两条曲线逐点相加，峰谷出现在合成曲线的斜率过零处。电容项的斜率为 i/C，电阻项的斜率为 R 乘以电流斜率。图中虚线各自的峰值发生在不同的时刻。',
        '上升段的电流斜率为 0.2 A/µs，两项斜率相抵时电流为 −0.4 A，时刻为 0.5 µs。此时内电压变化 −2.25 mV，电阻压降 −8 mV，合成为 −10.25 mV。下降段的对应时刻为 5.5 µs，合成为 +10.25 mV，得到实际峰峰值 20.5 mV。',
        '分别读取两个分量，理想电容纹波为 12.5 mV，电阻项为 20 mV。两者峰峰值相加给出 32.5 mV 的上界。减小 R 时，合成曲线的极值逐渐靠近电流过零处。若极值方程给出的电流超出本段范围，须回到分段端点比较电压；带 ESL 时还须考虑真实上升时间。'],
        r'\frac{dv}{dt}=\frac{i}{C}+R\frac{di}{dt}', esr_peaks, '理想容性纹波、电阻压降及其逐点和'),
    lesson(9, '用阻抗最低点识别串联自谐振', [
        '取一颗等效电容为 10 µF、串联电感为 5 nH、串联电阻为 12 mΩ 的电容。用正弦小信号逐频激励端口，电流和电压均取同一频率的复幅值。这里的 L 已包含设定的串联引线电感；把另一个装配位置的布线电感并入模型，会改变图中的谷底位置。',
        '电阻压降与电流同相，电感压降超前 90°，电容压降滞后 90°。在复平面上将三项相加，虚部等于感抗减去容抗。扫频到两者相等时，端口只剩实部 R，图中两条渐近线的交点与蓝线的最低点位于同一频率。此结论假设 ESR 在所示频带内恒定。',
        '将 5×10⁻⁹ H 和 10×10⁻⁶ F 代入，得到 711.8 kHz。此处两种电抗大小均约 22.36 mΩ，合成后端口幅值为 12 mΩ。频率加倍时，感抗增为 44.72 mΩ，容抗减为 11.18 mΩ，与电阻按正交分量合成，端口幅值约为 35.6 mΩ。',
        '若向单颗器件注入固定的 1 A RMS 单频电流，谐振点的端电压为 12 mV RMS，耗散为 12 mW。离开谐振点后，端电压随阻抗变化，本例的有功损耗仍由 12 mΩ 实部决定。固定参数对应 capacitor_impedance.py 的串联模型，有实测频变数据时应另查各频点实部。'],
        r'f_0=\frac{1}{2\pi\sqrt{LC}}', self_resonance, '容抗与感抗相抵时的端口阻抗'),
    lesson(9, '在两个阻抗测点之间重建复数', [
        '阻抗分析仪常把每个频点写成幅值与相角。设某颗电容在 10 kHz 的测量结果为 50 mΩ、−53.13°，在 1 MHz 为 22.36 mΩ、+63.43°。为了估算中间频率的分流，需要找回与电流同相的实部及相差四分之一周期的虚部。下文取正虚部代表感性。',
        '将两个极坐标还原成图上的点，坐标分别约为 (30,−40) 与 (10,20)，横纵单位均为 mΩ。连接两点。程序用对数频率给这条线段分配位置，横向移动多少决定实部变化，纵向移动多少决定虚部变化。下式中 Z₁、Z₂ 为测点复阻抗，f₁、f₂ 为对应正频率。',
        '100 kHz 的左、右邻点各相距十倍频率，所以权重恰为二分之一。得到 20−j10 mΩ，回到极坐标为 22.36 mΩ、−26.57°。若该支路流过 2 A RMS 单频电流，则端电压幅值为 44.72 mV RMS，有功耗散取实部计算，结果为 80 mW。',
        '把查询频率依次放回两端，线性组合应逐点还原原测量。对于频带外的激励，项目按该颗电容设定的名义 C、ESR、ESL 重新求复阻抗；带外各谱线的负担仍留在总损耗内。查阅报告时应同时查看实测覆盖的均方电流份额。'],
        r'Z(f)=Z_1+(Z_2-Z_1)\frac{\ln(f/f_1)}{\ln(f_2/f_1)}', measured_impedance, '对数频率上的插值在复阻抗平面形成线段'),
    lesson(9, '从三条谐波谱线重建一颗电容的发热', [
        '假设已经按并联网络求出某颗电容的支路电流，基频和第二、第三次谐波的有效值依次为 1.2 A、0.6 A、0.2 A，其余谱线为零。阻抗测量给出这三个频点的实部分别为 20 mΩ、30 mΩ、60 mΩ。考察的是整周期稳态下这一颗器件的平均耗散。',
        '图左每根柱代表一个单频有效值。不同整数次正弦在整周期上正交，平方后积分，交叉项相互抵消，故各次均方电流可以相加。求有功时给每一项乘上同频的实部，形成右图。高频谱线即便电流较小，如果耗散电阻较大，仍会改变损耗分配。',
        '三项功率依次为 1.2²×20=28.8 mW、0.6²×30=10.8 mW、0.2²×60=2.4 mW，合计 42.0 mW。该颗电容的总均方电流为 1.84 A²，有效值约 1.36 A。反算本工况的有效 ESR 得 42.0/1.84=22.83 mΩ，按 25 K/W 的热阻计算温升为 1.05 K。',
        '若仪器标注的是单边正弦峰值，先除以根号二再代入；把峰值直接平方将把损耗放大一倍。有效 ESR 随实际谱线权重改变。项目 capripple.py 在频点分流后累加各颗的功率，因此操作点或电容组合改变后应重新求权重。'],
        r'R_{\mathrm{eff}}=\frac{\sum_h I_{h,\mathrm{rms}}^2\operatorname{Re} Z_h}{\sum_h I_{h,\mathrm{rms}}^2}', spectral_heating, '电流谱线和按各频点阻抗实部加权后的耗散'),
    lesson(9, '负载阶跃后的瞬时跳变与随后斜坡', [
        '把 100 µF、20 mΩ 的第一支路和 25 µF、80 mΩ 的第二支路并接到同一端口。起始时两颗内部电容均为 5 V，净支路电流为零。负载突然多取 1 A，在随后 4 µs 内功率级供给电流近似维持原值。该教学边界便于单独观察 ESR 与电容量。',
        '负载跳变瞬间内部储存的电荷连续，两颗内电压都保持原值。端口可沿串联电阻立刻下降，使两个支路放电电流之和补足 1 A。之后两支路 RC 时间常数均为 2 µs，初始电流之比 4∶1 正好等于容量之比，所以两颗内电压有相同的下降斜率，电流比例持续不变。',
        '两电阻并联为 16 mΩ，瞬时跌落 16 mV。第一支路放电 0.8 A，第二支路放电 0.2 A，各自的电阻降都是 16 mV。总容量为 125 µF，内电压每微秒下降 8 mV。在 4 µs 时端口总共下降 48 mV，剩余 4.952 V，电容累计释放 4 µC。',
        '图上实线与虚线之间的垂直间距始终为 16 mV。若两支路 RC 乘积改变成不同的数值，内部电压会分离，电流分配也将随时间变化。项目支持逐颗 C 与 ESR 的动态路径在每个时刻联立节点方程；此封闭解可用来检查初始跳变的方向和积分步长。'],
        r'\Delta v(t)=-\Delta I\left(R_{\parallel}+\frac{t}{C_1+C_2}\right)', load_step, '相同支路时间常数下，端口阶跃与储能电压斜坡'),
]


def integer_turns():
    fig, ax = _axes('匝数', '所需净铜面积 / mm²')
    n = np.arange(20,26)
    ax.bar(n, .75*n, color=[MUTED]*3+[BLUE,TEAL,TEAL], width=.58)
    ax.axhline(17.1, color=ORANGE, ls='--', label='57 mm² 窗口可用铜面积')
    ax.axvline(22.727, color=INK, ls=':', label='满足磁密的连续下限')
    ax.set(ylim=(14, 20), xticks=n)
    ax.legend(ncol=2, loc='upper center')
    return fig


def flux_offset():
    fig = figure(height=2.65)
    left, right = fig.subplots(1, 2)
    left.plot([0,4,4,10], [120,120,-80,-80], color=BLUE)
    left.fill_between([0,4], 0, 120, color=BLUE, alpha=.16)
    left.fill_between([4,10], 0, -80, color=ORANGE, alpha=.16)
    left.set(xlabel='时间 / µs', ylabel='励磁电压 / V', xticks=[0,4,10], ylim=(-105,150))
    right.plot([0,4,10],[80,200,80], color=TEAL)
    right.fill_between([0,4,10], [80,200,80],80,color=TEAL,alpha=.22)
    right.axhline(80, color=MUTED, ls=':')
    right.set(xlabel='时间 / µs', ylabel='磁通密度 / mT', xticks=[0,4,10], ylim=(0,235))
    right.text(4.3,196,'峰值 200 mT',va='bottom')
    return fig


def gap_tolerance():
    fig, ax = _axes('总等效气隙 / mm', '励磁电感 / µH')
    g = np.linspace(.30,.7,240)
    def microhenries(gap):
        return 4e-7*np.pi*100e-6*40**2/((gap+.025)*1e-3)*1e6
    ax.plot(g, microhenries(g), color=BLUE)
    ax.axvspan(.45,.55,color=TEAL,alpha=.13,label='示例加工范围')
    for gap in [.45,.50,.55]:
        value = microhenries(gap)
        ax.scatter(gap, value, color=ORANGE, zorder=3)
        ax.annotate(f'{value:.0f}', (gap,value), xytext=(5,6), textcoords='offset points')
    ax.legend()
    return fig


def layer_packing():
    fig, ax = _axes('可用窗口宽度内的位置 / mm', '从骨架内沿起的高度 / mm')
    colors = (BLUE, TEAL, ORANGE)
    for row, count in enumerate([10,10,4]):
        y = .2+.6*row
        for turn in range(count):
            ax.add_patch(Rectangle((turn*.95,y), .85, .5, facecolor=colors[row], alpha=.78))
        ax.text(9.72, y+.25, f'{count} 匝', va='center')
    for y in [.7,1.3]:
        ax.add_patch(Rectangle((0,y),9.6,.1,facecolor=MUTED, alpha=.32))
    ax.plot([0,9.6,9.6,0,0],[0,0,2.1,2.1,0],lw=1,color=INK)
    ax.set(xlim=(-.2,10.9),ylim=(-.1,2.26),yticks=[0,.2,.7,1.3,1.9,2.1])
    return fig


def unequal_paths():
    fig = figure(height=2.48)
    ax = fig.subplots()
    ax.axis('off')
    for y, name, col, current in [(1.75,'1.0 m    172 mΩ',BLUE,'1.20 A'),
                                  (.65,'1.5 m    258 mΩ',ORANGE,'0.80 A')]:
        ax.plot([1,1,2.5],[1.2,y,y],color=INK, lw=1.4)
        ax.add_patch(Rectangle((2.5,y-.16),1.45,.32, ec=col, fc='white', lw=2))
        ax.text(3.225,y,name,va='center',ha='center',fontsize=9)
        ax.plot([3.95,5.2,5.2],[y,y,1.2],color=INK, lw=1.4)
        ax.annotate('',(2.25,y),(1.42,y),arrowprops={'arrowstyle':'->','color':col,'lw':2})
        ax.text(1.85,y+.09,current,color=col,ha='center')
    ax.plot([.33,1],[1.2,1.2],color=INK)
    ax.plot([5.2,5.9],[1.2,1.2],color=INK)
    ax.scatter([1,5.2],[1.2,1.2],color=INK)
    ax.text(.33,1.32,'2.00 A'); ax.text(3.1,.13,'端电压差 206.4 mV',ha='center')
    ax.set(xlim=(0,6.2),ylim=(0,2.25))
    return fig


def strand_skin():
    from magnetics import ac_factor
    fig, ax = _axes('频率 / kHz', '圆线经验比值  Rac / Rdc')
    frequencies = np.geomspace(1e4,1e6,240)
    for d, color in [(.10,TEAL),(.40,ORANGE)]:
        factors = [ac_factor(d/1000,f) for f in frequencies]
        ax.semilogx(frequencies/1000,factors,color=color,label=f'单股直径 {d:.2f} mm')
        ax.scatter(100, ac_factor(d/1000,1e5),color=color,zorder=3)
    ax.axvline(100,color=MUTED,ls=':')
    ax.legend()
    return fig


def asymmetric_core():
    fig, ax = _axes('上升段占整周期的比例 D', '磁芯损耗 / W')
    d = np.linspace(.08,.92,281)
    p = .8*(d**(-.5)+(1-d)**(-.5))/(2*np.sqrt(2))
    ax.plot(d,p,color=BLUE)
    ax.scatter([.2,.5,.8],[.8*3*np.sqrt(5)/2/(2*np.sqrt(2)),.8,.8*3*np.sqrt(5)/2/(2*np.sqrt(2))],color=ORANGE)
    ax.axhline(.8,color=MUTED,lw=1,ls=':')
    ax.set(xticks=[.1,.2,.35,.5,.65,.8,.9],ylim=(.74,1.38))
    ax.text(.5,.82,'上下坡等时',ha='center')
    return fig


LESSONS += [
    lesson(10, '面积乘积初选后仍须检查整数匝数', [
        '设计一只 100 µH 滤波电感，峰值电流 4 A、有效值 3 A。磁芯有效截面 80 mm²，允许磁密 0.22 T。取允许电流密度 4 A/mm²、允许裸铜占窗口面积的比例 0.30。磁密约束决定匝数的下界，铜占窗约束给出装得下的匝数上界，两个条件需要落到同一个整数上。',
        '将 Li 与磁链 NAₑB 相等，并把每匝铜面积按有效电流除以电流密度求出。图中竖线给出连续匝数下界，柱高表示各整数匝数占用的净铜面积，横线是本磁芯的预算。下式中 Wₐ 为窗口面积，Kᵤ 为铜利用系数，向上取整符号将磁密约束转为可制造的电气匝数。',
        '计算得到 N≥22.73，因此至少绕 23 匝，每匝铜面积 0.75 mm²，总计 17.25 mm²。若窗口为 57 mm²，其可用铜面积只有 17.10 mm²。连续面积乘积判断为 80×57=4560 mm⁴，刚好超过未取整的需求 4545 mm⁴，却仍放不下这 23 匝所需的裸铜。',
        '将窗口改为 58 mm²，净铜预算升到 17.40 mm²。复核峰值磁密为 100 µH×4 A/(23×80 mm²)=0.2174 T。此时两个代数约束都满足，再到绕组截面核对边距、骨架、漆层及层间带厚。项目磁件初选按面积乘积排序，初选值应与最终绕组几何分别阅读。'],
        r'\left\lceil\frac{L I_{\mathrm{pk}}}{A_e B_{\mathrm{lim}}}\right\rceil\frac{I_{\mathrm{rms}}}{J}\le K_u W_a', integer_turns, '磁密下界与窗口铜面积预算在整数匝数上的相交条件'),
    lesson(10, '伏秒平衡能确定摆幅，直流偏置从哪里来', [
        '取一副线性反激磁件，原边 40 匝，有效截面 100 mm²，励磁电感 400 µH。为简化观察，导通 4 µs 时励磁电压为 +120 V，随后 6 µs 恒为 −80 V。电压正方向使同名端流入的磁化电流增大，已知周期起点电流为 0.8 A。忽略剩磁与磁滞。',
        '左图正负矩形的伏秒面积相等，所以磁通密度在整周期结束时回到起点。只做电压积分尚缺一个积分常数，须用起点电流通过磁链 Lₘi₀ 确定。右图阴影标出了在一周期内反复扫过的磁密范围；阴影下沿离横轴的距离就是在该线性假设下的谷值磁密。',
        '正伏秒为 480 V·µs，除以 40×100 mm² 得到 ΔB=0.12 T。起点磁通密度为 400 µH×0.8 A/(40×100 mm²)=0.08 T，故最高点为 0.20 T。由电流斜率再算一次，正向 4 µs 内增加 1.2 A，峰值电流 2 A，对应的峰值磁密仍为 0.20 T。',
        '如果只看零均值的积分曲线，峰值会随所选参考线移动，不能与饱和上限直接比较。若进入明显非线性区，固定 Lₘ 的磁链电流关系需改用器件的实测磁化特性。项目可使用给定周期磁链计算峰值与摆幅，检查数据时应保留模型的磁链零点和绕组方向。'],
        r'B(t)=\frac{L_m i_0+\int_0^t v_m(u)\,du}{N_p A_e}', flux_offset, '伏秒确定磁密变化，谷值磁化电流确定起始高度'),
    lesson(10, '将有效气隙的公差换算成电感范围', [
        '取有效截面 100 mm²、有效体积 6000 mm³ 的磁芯，绕 40 匝，线性相对磁导率取 2400。由体积除以截面得有效磁路长度 60 mm，假定气隙与磁芯截面相同。设装配后总等效气隙的名义值为 0.50 mm，可能在 0.45 至 0.55 mm 间变化。',
        '用磁通作流量，沿磁路把磁芯和全部气隙的磁阻串联。磁芯相当于 60/2400=0.025 mm 长的空气，将其加到实际气隙上，再用匝数平方除以总磁阻。图中的带状区域表示气隙容差，曲线在该带两端的高度给出电感边界。μ₀ 表示真空磁导率。',
        '名义总等效空气长度为 0.525 mm，代入得 383.0 µH。气隙减到 0.45 mm 时为 423.3 µH，增到 0.55 mm 时为 349.7 µH。相对名义点分别约为 +10.5% 与 −8.7%。精确的上下偏差不对称，原因是电感与总磁阻的倒数成正比。',
        '在名义点用微分估算，0.05 mm 气隙偏差对应约 0.05/0.525=9.5% 的反向相对变化，和两端精算结果的量级相符。transformer_gap.py 的线性磁路估计以总等效气隙为对象，实物测量需记录拼接位置、紧固条件及量测偏置；边缘磁通会改变有效截面。'],
        r'L(g)=\frac{\mu_0 A_e N^2}{g+\ell_e/\mu_r}', gap_tolerance, '线性磁路下的气隙容差带与电感上下界'),
    lesson(10, '一束线的几何宽度怎样决定跨层位置', [
        '一组 24 匝绕组用两根相同完整线并绕，每根含 8 股直径 0.10 mm 的铜丝。将每个电气匝的两根完整线排好后，实测合计宽 0.85 mm、高 0.50 mm，已计其包覆。可用轴向宽度为 9.60 mm，相邻电气匝留 0.10 mm。图中一个色块代表整个电气匝。',
        '沿第一层从左到右放置，n 匝占用 n 个匝宽和 n−1 个间隙。把总宽不等式移项并向下取整就得到每层容量。其中 W 已扣轴向留边，w 是一匝宽，s 是相邻匝净间隙。底层装满才换到下一层，各层间增加 0.10 mm 绝缘带，径向内外侧各预留 0.20 mm。',
        '10 匝共需 10×0.85+9×0.10=9.40 mm，放第 11 匝则需 10.35 mm，因而层计划为 10、10、4 匝。合计径向需求为 3×0.50+2×0.10+2×0.20=2.10 mm。每匝裸铜面积约 0.1257 mm²，总裸铜占窗约 3.02 mm²，可与几何图的绝缘占用分别核对。',
        '若把每根线中的 8 股再拆成两个几何小束，总铜仍是两根完整线所含的 16 股。电气匝数也仍是 24。应按新的束形重新测量或估计实际宽和高，再排一次图。项目绕组窗口计算分别检查轴向边界、径向堆叠与各段匝数，净铜面积一个指标无法说明能否装入。'],
        r'n_{\mathrm{layer}}=\left\lfloor\frac{W+s}{w+s}\right\rfloor', layer_packing, '24 个电气匝分成三层后的轴向余量和径向堆叠'),
    lesson(10, '两根实际长度不同的并绕线如何分流', [
        '取同一绕组的两根并行完整线，串联层与引线折算后的各自铜长为 1.0 m 和 1.5 m。每根铜截面 0.10 mm²，电阻率取 1.72×10⁻⁸ Ω·m，两端分别接在同一对端子。只分析直流的电阻分流，暂时忽略两根线之间的交流电势差及温度分布。',
        '从端子往里看是两只电阻并联。单路电阻为电阻率乘长度除以该路径截面。两路电压相同，较短线上的电流较大。将两路电导相加，再用两路铜截面之和定义等效长度，得到下式的调和平均。图中两个箭头方向都从高电位端指向低电位端。',
        '支路电阻分别为 172 mΩ 与 258 mΩ，端口等效值为 103.2 mΩ。通入 2 A 总电流时，端电压为 206.4 mV，两支路分别承担 1.20 A 与 0.80 A。调和平均长度为 1.20 m；以总截面 0.20 mm²、相同电阻率代入单线公式，也得到 103.2 mΩ。',
        '逐线计算功耗分别约 247.7 mW 与 165.1 mW，合计 412.8 mW，与总电流平方乘以端口电阻一致。若两路截面不同，直接按各路 A/ℓ 汇总电导。项目的绕组长度处理保留实际路径和可归属引线，输入改变时还应核对哪一条路径承担了较高电流密度。'],
        r'\ell_{\mathrm{eq}}=\frac{2}{1/\ell_1+1/\ell_2}', unequal_paths, '同截面并行路径在公共端电压下的电阻性分流'),
    lesson(10, '等铜面积时单股线径如何影响交流修正', [
        '比较一根直径 0.40 mm 的裸铜线与 16 股直径 0.10 mm 的导线，设每股有效，长度均为 1.00 m，电阻率取 1.72×10⁻⁸ Ω·m。两种方案的铜截面均为 0.1257 mm²，因此有相同的直流电阻。为隔离集肤项的作用，本例暂取各股均流，省略邻近导体磁场。',
        '在非磁性良导体中，表面交变场向铜内部衰减的特征长度为集肤深度 δ。项目的圆线经验式用单股直径 d 与 δ 的比值 x 估算交流电阻系数 Fᵣ。横轴每前进一个十倍频程，δ 缩短到原来的约 0.316 倍，粗线曲线因而更早向上弯。图中竖线标记算例频率。',
        '在 100 kHz 下 δ 约为 0.209 mm。两种线的直流电阻均为 136.9 mΩ。由经验式得粗线系数 1.2294、细股系数 1.0011。按项目用单个开关频率修正整个绕组 RMS 的口径，当有效电流为 2 A 时，估算铜损分别约为 0.673 W 和 0.548 W。',
        '将频率降低，两条曲线都趋向 1，结果回到相同的直流损耗。截面相同仅说明铜量，绝缘与绞合可能改变成品外径和路径长度。这里的模型也没有解析邻近效应、股线换位与不同谐波的场分布。实物对照需说明测量频率和是否装在实际磁芯窗口内。'],
        r'F_r=1+\frac{x^4}{48+0.8x^4},\qquad x=d\sqrt{\frac{\pi f\mu_0}{\rho}}', strand_skin, '在相同直流铜截面下比较粗线和分股导线的经验交流系数'),
    lesson(10, '相同磁密摆幅下，快升慢降为何改变磁损', [
        '设磁芯材料的非正弦损耗指数 α 为 1.5，周期固定，磁通密度在同一对上下界之间作线性往返。上升段占周期 D，下降段占 1−D，中间无停顿。选对称三角波的芯损 0.80 W 作校准，绕组铜损固定为 1.20 W，本题只比较改变上升时间后斜率权重的影响。',
        '上升阶段把同一摆幅压缩至 DT，斜率的大小按 1/D 放大。将斜率的 α 次幂对这段时间积分，又乘回 D，得到 D 的 1−α 次幂。下降段同理，两段相加。图中曲线除以 D=0.5 时的对应值完成归一化，所用材料系数、磁芯体积与磁密摆幅因相同而约去。',
        'D=0.20 时，两段权重分别为 1/√0.2=2.236 与 1/√0.8=1.118，合计 3.354。对称波的权重为 2.828，所以芯损变为 0.80×3.354/2.828≈0.949 W。整体热阻取 12 K/W 时，对称波给出 24.0 K 温升，改用快升慢降后约为 25.8 K。',
        '交换上升与下降时间，曲线关于 D=0.5 对称，计算的损耗相同。真实变换器改占空比往往也改变电流、磁密摆幅与绕组损耗，需分别重算。magnetics.py 的非正弦波形入口可用周期磁密样点累加斜率贡献；本例的一对直线段提供了便于独立核对的解析比值。'],
        r'\frac{P(D)}{P(1/2)}=\frac{D^{1-\alpha}+(1-D)^{1-\alpha}}{2^\alpha}', asymmetric_core, '固定频率和摆幅时，斜率不对称对非正弦芯损估计的影响'),
]


def gate_lookup():
    fig = figure(height=2.65)
    transfer, charge = fig.subplots(1,2)
    transfer.plot([2.5,3.5,4.5],[0,2,6],'-o',color=BLUE)
    transfer.plot([2.5,4,4],[4,4,0],':',color=ORANGE)
    transfer.set(xlabel='栅源电压 / V',ylabel='漏极电流 / A',xticks=[2.5,3.5,4,4.5])
    charge.plot([2.5,3.5,4],[3,8,10.5],'-o',color=TEAL)
    charge.axvline(4,ls=':',color=ORANGE)
    charge.set(xlabel='阈值至平台的栅压 / V',ylabel='从零起累计的电荷 / nC',
               xticks=[2.5,3.5,4],yticks=[3,8,10.5])
    return fig


def plateau_time():
    fig, ax = _axes('平台开始后的时间 / ns', '转移电荷的绝对值 / nC')
    for duration, color, label in [(9,TEAL,'关断，3 Ω'),(12,BLUE,'开通，6 Ω、10 V'),
                                   (18,ORANGE,'开通，6 Ω、8 V')]:
        ax.plot([0,duration],[0,12], color=color,label=label)
        ax.scatter(duration,12,color=color)
    ax.axhline(12,color=MUTED,ls=':',lw=1)
    ax.set(xticks=[0,3,6,9,12,15,18],ylim=(0,14))
    ax.legend(loc='lower right')
    return fig


def switching_overlap():
    fig = figure(height=2.65)
    slopes, power = fig.subplots(1,2)
    u = np.linspace(0,1,301)
    slopes.plot(30*u,1-u,color=BLUE,label='漏源电压 / 100 V')
    slopes.plot(30*u,u,'--',color=ORANGE,label='漏极电流 / 4 A')
    slopes.set(xlabel='时间 / ns',ylabel='归一化幅值')
    slopes.legend(loc='upper center')
    p = 400*u*(1-u)
    power.fill_between(30*u,p,color=TEAL,alpha=.21)
    power.plot(30*u,p,color=TEAL)
    power.text(15,42,'积分 2.00 µJ',ha='center')
    power.set(xlabel='时间 / ns',ylabel='瞬时损耗 / W',ylim=(0,116))
    return fig


def diode_pulses():
    fig = figure(height=2.65)
    current, power = fig.subplots(1,2)
    for ax, vals, label, color in [(current,[1,3,0,0],'正向电流 / A',BLUE),
                                   (power,[.6,2.4,0,0],'瞬时导通损耗 / W',ORANGE)]:
        t = [0,.25,.5,1]
        ax.step(t,vals,where='post',color=color)
        ax.fill_between(t,vals,step='post',alpha=.16,color=color)
        ax.set(xlabel='归一化时间 t / T',ylabel=label,xticks=[0,.25,.5,1],ylim=(0,max(vals)*1.22))
    power.axhline(.75,color=MUTED,ls=':')
    power.text(.58,.86,'平均 0.75 W')
    return fig


def ring_damping():
    fig, ax = _axes('换流后的时间 / ns', '端口电压 / V')
    t = np.linspace(0,130e-9,901)
    for r, color, style in [(0,MUTED,':'),(2,BLUE,'-')]:
        alpha = r/(2*40e-9)
        omega = np.sqrt(1/(40e-9*1e-9)-alpha**2)
        v = 48 + 2/(1e-9*omega)*np.exp(-alpha*t)*np.sin(omega*t)
        ax.plot(t*1e9,v,style,color=color,label=f'回路串阻 {r} Ω')
    ax.scatter(9.044,58.089,color=ORANGE,zorder=3)
    ax.axhline(48,color=TEAL,ls='--',lw=1,label='阻断平台')
    ax.legend(ncol=3,loc='lower center',bbox_to_anchor=(.5,1))
    return fig


def clamp_threshold():
    fig = figure(height=2.65)
    peak, power = fig.subplots(1,2)
    initial = np.linspace(0,2,301)
    peak.plot(initial,260+np.minimum(80,100*initial),color=BLUE)
    power.plot(initial, .5*180*2e-6/80*np.maximum(initial**2-.8**2,0)*100e3,color=ORANGE)
    for ax in [peak,power]:
        ax.axvline(.8,color=TEAL,ls=':')
        ax.set(xlabel='换流起始电流 / A',xticks=[0,.4,.8,1.2,1.6,2])
    peak.set(ylabel='相对母线负端的峰值 / V',ylim=(250,355))
    power.set(ylabel='钳位功率 / W')
    power.scatter(1,.081,color=ORANGE)
    return fig


def efficiency_load():
    fig = figure(height=2.65)
    loss, efficiency = fig.subplots(1,2)
    i = np.linspace(.5,4.5,301)
    loss.stackplot(i, np.full_like(i,.65), .12*i, .15*i**2, colors=[MUTED,TEAL,ORANGE],
                   labels=['固定项','一次项','平方项'],alpha=.82)
    loss.set(xlabel='端口负载电流 / A',ylabel='耗散 / W')
    loss.legend(loc='upper left')
    eta = 100*12*i/(12*i+.65+.12*i+.15*i**2)
    efficiency.plot(i,eta,color=BLUE)
    efficiency.axvline(np.sqrt(.65/.15),ls=':',color=ORANGE)
    efficiency.set(xlabel='端口负载电流 / A',ylabel='效率 / %',ylim=(88,95))
    for ax in (loss, efficiency):
        ax.set_xlim(.5,4.5)
    return fig


LESSONS += [
    lesson(11, '用同一个换流电流依次读取栅压与电荷', [
        '给一只 MOSFET 指定某测试温度、漏源电压下的教学转移曲线。线性坐标上有三个点，栅压依次为 2.5、3.5、4.5 V，漏极电流依次为 0、2、6 A。取一个需要承担 4 A 的切换事件，驱动高电平为 10 V。先求该电流对应的栅压，再估算从零充到这一平台所需的电荷。',
        '在左图从纵轴的 4 A 水平移动，碰到曲线后向下读横轴。此值用作等效平台电压。右图给定阈值 2.5 V 处累计电荷 3 nC，参考平台 3.5 V 处累计电荷 8 nC。把这两个点的割线斜率视作阈值以上的增量电容，可将对应平台映射到累积电荷。',
        '4 A 恰在 2 A 与 6 A 中间，线性内插给出平台 4.0 V。电荷斜率为 (8−3) nC/(3.5−2.5) V=5 nF，因此到 4.0 V 的累计电荷为 3+5×1.5=10.5 nC。若另一个边沿仅需 2 A，同样步骤将给出 3.5 V 和 8 nC，该边沿应使用自己的电荷。',
        '将两个边沿的读数分别代回转移曲线，检查电流、栅压坐标有没有颠倒。静态转移曲线只提供动态米勒平台的近似，右图最后一段还采用了恒增量电容假设。项目允许按事件填入实测平台，或启用栅电荷曲线直接查值；应在报告中说明所选来源和温度。'],
        r'Q_{\mathrm{gs}}(I)=Q_{\mathrm{th}}+(V_{\mathrm{gp}}(I)-V_{\mathrm{th}})\frac{Q_{\mathrm{ref}}-Q_{\mathrm{th}}}{V_{\mathrm{ref}}-V_{\mathrm{th}}}', gate_lookup, '从转移曲线反查栅压，再由参考电荷斜率求事件电荷'),
    lesson(11, '开通与关断的平台持续时间为何不同', [
        '设 MOSFET 的等效米勒平台在开通和关断时都为 4 V，两次事件均需转移 12 nC 的米勒电荷。驱动器在开通时输出 10 V，关断时拉到 0 V。计入驱动器、外置电阻和器件内部电阻后，开通路径为 6 Ω，关断路径为 3 Ω。暂将平台电压与各段路径电阻视为常数。',
        '栅压停在平台附近时，驱动电阻上的电压近似不变，故栅电流接近常数。从起点沿图中斜线读转移电荷的绝对值，直线斜率即电流。充电看高电平与平台之间的差值，放电看平台与驱动低电平之间的差值。达到同一水平虚线的横坐标就是该段时长。',
        '开通电流为 (10−4)/6=1 A，转移 12 nC 需 12 ns。关断电流的大小为 (4−0)/3=1.333 A，需 9 ns。若只将驱动高电平降到 8 V 并维持本题的其他假设，开通电流降为 0.667 A，平台充电时间延至 18 ns。关断路径的压差仍为 4 V。',
        '可反向核算 1.333 A×9 ns≈12 nC，并注意 nC 除以 A 得到 ns。所得时长只含栅漏电荷搬移的一段。完整的器件波形还包含阈值前的延迟、漏极电流建立和平台后的充放电。项目半导体损耗入口按开、关边沿分别取电荷和电阻，平台不可高于驱动能力。'],
        r't_{\mathrm{M,on}}=\frac{Q_{\mathrm{gd,on}}R_{\mathrm{on}}}{V_{\mathrm{drv}}-V_{\mathrm{gp,on}}},\qquad t_{\mathrm{M,off}}=\frac{Q_{\mathrm{gd,off}}R_{\mathrm{off}}}{V_{\mathrm{gp,off}}}', plateau_time, '用电荷斜率比较三组驱动条件下的平台时间'),
    lesson(11, '从一对线性边沿推导开关重叠系数', [
        '取一个电阻性换流的教学边沿，漏源电压在 30 ns 内从 100 V 均匀降至 0，漏极电流同时从零均匀增至 4 A。把两条波形的起点对齐，规定正的漏极电流流入正的漏源电压端。只计算这一时间窗内的电压电流重叠能量，后续稳态导通的耗散另计。',
        '将时刻 t 除以总时长 τ，得无量纲坐标 u。左图两条斜线的归一化高度分别为 1−u 和 u，右图在相同时刻把高度相乘并恢复单位。功率在两个端点都为零，中点最大。从 0 积到 1，相当于求 u−u² 的面积，得到 1/2−1/3=1/6。',
        '中点时电压 50 V、电流 2 A，峰值功率 100 W。整段的平均瞬时功率为 100×4/6=66.67 W，乘 30 ns 得每次 2.00 µJ。若每秒重复这样的开通 100000 次，该项为 0.200 W。频率翻倍且不改变单次波形时，该项平均功率也翻倍。',
        '台架上可直接对同步的漏源电压与漏极电流采样逐点相乘并积分，需先消除探头时延差。项目通用损耗估算还提供感性换流的工程形状系数，感性负载下电流建立与电压下降的先后次序不同。选择系数时应检查实物边沿；重复计入同一份电容能量也会抬高预算。'],
        r'E=VI\tau\int_0^1 u(1-u)\,du=\frac{VI\tau}{6}', switching_overlap, '线性反向变化的电压、电流相乘后形成抛物线功率脉冲'),
    lesson(11, '整流管正向曲线为什么要逐点乘电流', [
        '假设某整流管在一个开关周期的前四分之一流过 1 A，随后四分之一流过 3 A，余下半周期截止。曲线来自同一结温，1 A 时正向压降 0.60 V，3 A 时为 0.80 V。另给出恢复电荷 20 nC，并设每周期发生一次 60 V 反向恢复事件，频率 100 kHz。',
        '图左的两段导通时间相同，右图却有高度相差四倍的功率矩形。原因是电流和压降均随工作点改变。对每段先查正向电压，与该段电流相乘后再按占时加权。截止段正向功率为零。恢复电荷是单独的换流能量项，在反压近似恒定时用电压乘电荷估算。',
        '两个矩形的瞬时功率分别为 0.60 W 和 2.40 W，周期平均为 (0.60+2.40)/4=0.75 W。整个周期的平均电流却只有 1 A，若以这个平均值所对应的 0.60 V 乘以 1 A，会漏计 0.15 W。每次恢复的近似能量为 1.20 µJ，即 0.12 W，总预算为 0.87 W。',
        '用波形面积也可检查平均电流，1×0.25+3×0.25=1 A。换用恒定 Vf 的模型时，压降可移到平均符号外，恢复项仍需按实际事件数计。项目二极管曲线的输入横轴为 Vf、纵轴为 If，做损耗时从电流反查压降；超出采点区间应记录所用端部趋势与温度。'],
        r'P_D=\sum_k D_k I_k V_F(I_k)+f_sV_RQ_{\mathrm{rr}}', diode_pulses, '分段正向电流与相应的周期平均导通损耗'),
    lesson(11, '用第一个峰和后续周期区分振铃与阻断平台', [
        '在换流结束附近取一个局部串联 RLC 回路。平台参考为 48 V，设局部电感 L 为 40 nH，端口并联等效电容 C 为 1 nF，回路串阻 R 为 2 Ω。端口初始电压等于平台，电感有 2 A 电流向端口电容充电。观察范围内钳位均不动作，也不接额外 RC 吸收支路。',
        '令 u 为端口电压减去平台的差值。由 i=C du/dt 和 L di/dt=−Ri−u 消去电流，得到二阶齐次方程。欠阻尼根的实部给出衰减率 α=R/(2L)，虚部给出角频率 ωd。初始电压差为零、初始斜率为 I₀/C，故振荡项取正弦。图中虚线保留了无电阻时的能量往返。',
        '无阻尼频率为 25.16 MHz，计入串阻后为 24.85 MHz。首个峰值令导数为零，得到 tan(ωd t)=ωd/α，首峰时刻约 9.04 ns。此时相对平台抬高 10.09 V，端口峰值约 58.09 V。把串阻置零则峰值抬高 2√(40 nH/1 nF)=12.65 V。',
        '先从相邻同向波峰读周期，再从相对平台的峰高读衰减；若直接拿绝对电压峰相除，会混入 48 V 的直流分量。项目局部换流求解器还可包含钳位和串联 RC 支路，此时需按支路和事件重新求解。本例对应无钳位导通的线性区间，可与其数值电压数组核对。'],
        r'u(t)=\frac{I_0}{C\omega_d}e^{-\alpha t}\sin(\omega_dt),\qquad \omega_d=\sqrt{\frac{1}{LC}-\alpha^2}', ring_damping, '相同初始换流电流下的无阻尼参考与串阻衰减'),
    lesson(11, '关断电流多大时反激钳位管才开始导通', [
        '取反激关断后的首个漏感波瓣，输入母线为 160 V，折算到原边的反射电压为 100 V。漏源电压从 260 V 的平台出发，钳位电容正端相对输入正母线为 180 V，对应漏源上限 340 V。取漏感 2 µH、恒定端口电容 200 pF，首波瓣中忽略回路电阻。',
        '要从平台跨到钳位上限，端口相对平台还需升高 80 V。开头的漏感储能在相对平台的 LC 振荡中与电容能量互换，把全部初始磁能与达到这一增量所需的等效电能相等，就得到临界电流。图左在临界点转为水平，图右则从临界点开始出现非零钳位功率。',
        '临界电流为 80√(200 pF/2 µH)=0.80 A。关断电流为 0.60 A 时，自由电压增量只有 60 V，漏源峰值 320 V，钳位电荷为零。增至 1.00 A 时，跨过 80 V 后余流为 √(1²−0.8²)=0.60 A，在 80 V/2 µH 的斜率下经 15 ns 降为零。',
        '钳位收到的电荷为 0.60 A×15 ns/2=4.50 nC。乘以相对输入正母线的 180 V，得到 0.810 µJ，每秒十万次对应 81.0 mW。这里 80 V 决定漏感续流斜率，180 V 决定钳位吸收能量，340 V 是器件所承受的绝对峰值。项目快速首波瓣按这三个节点量分别计算。'],
        r'I_{\mathrm{crit}}=(V_c-V_r)\sqrt{\frac{C}{L_\sigma}}', clamp_threshold, '钳位导通门槛两侧的漏源峰值与平均接收功率'),
    lesson(11, '效率峰值由哪两类损耗的交点决定', [
        '取一只稳压在 12 V 的单输出电源，用负载电流 I 作横坐标。为了读懂效率曲线，假定一个固定频率工作区的耗散可局部拟合为 a+bI+cI²。固定项 a 取 0.65 W，一次项系数 b 取 0.12 V，平方项系数 c 取 0.15 Ω。端口功率在输出防反器件之后统计。',
        '左图将三类耗散由下向上累加。要求效率最高，相当于让耗散与输出功率之比最小。把该比值乘以固定输出电压，就得到 a/I+b+cI。对电流求导，常数 b 消失，条件为 −a/I²+c=0。因此极值出现在固定耗散与平方耗散相等之处，一次项仍会降低整体效率。',
        '正根为 √(0.65/0.15)=2.08 A，右图虚线标出这一点。取相邻的 2.00 A 手算，输出 24.0 W，耗散为 0.65+0.24+0.60=1.49 W，效率约 94.15%。在 0.50 A 下为 88.92%，在 4 A 下为 93.15%。低负载端主要受固定功耗的相对占比影响。',
        '若把 b 提高，所有点的效率都会下降，而这个简化模型中的峰值电流位置不动。本式是解释曲线形状的教学近似，真实轻载可能跳脉冲，频率与开关能量也随负载改变。项目 loss_model.py 按器件和工作点汇总损耗，再由实际端口功率求效率，不能以此拟合代替各工况复算。'],
        r'I_{\eta,\max}=\sqrt{\frac{a}{c}},\qquad \eta=\frac{V_oI}{V_oI+a+bI+cI^2}', efficiency_load, '固定、一次和平方损耗之和产生的局部效率峰值'),
]


EXERCISES = [
    ('将占空比从 0.25 改为 0.75，输入电容的有效值是多少？',
     '导通电流仍为 4 A，故有效值为 4√(0.75×0.25)=1.73 A，两段方波的大小与占时互换。'),
    ('若把串联电阻减至零，端口峰谷位于何时？',
     '电压导数随电流过零变号，谷值在 2.5 µs，峰值在 7.5 µs，两者相差 12.5 mV。'),
    ('若装配后串联电感增至 20 nH，自谐振点移到哪里？',
     '串联电感增至四倍，频率降至 711.8/2=355.9 kHz，恒定 ESR 假设下谷值仍为 12 mΩ。'),
    ('查询频率换成 31.62 kHz，复阻抗约为多少？',
     '从 10 kHz 走过半个十倍频程，占两测点对数跨度的四分之一，插值得 25−j25 mΩ。'),
    ('仅将第三次谐波的有效值从 0.20 A 增到 0.40 A，合计耗散多少？',
     '第三项从 2.4 mW 增到 9.6 mW，合计为 28.8+10.8+9.6=49.2 mW。'),
    ('若负载只多取 0.50 A，4 µs 后端口下降多少？',
     '电阻跳变与电荷积分都减半，总跌落为 8+16=24 mV。'),
    ('若允许磁密收紧为 0.20 T，按相同铜利用系数至少需多大窗口？',
     '匝数下界为 25 匝，最小窗口为 25×0.75/0.30=62.5 mm²。'),
    ('若周期起点磁化电流变为 0.40 A，其余伏秒条件相同，峰值磁密是多少？',
     '谷值按电流比例降至 0.040 T，伏秒给出的摆幅仍为 0.120 T，峰值为 0.160 T。'),
    ('保持名义气隙和磁芯不变，将绕组改成 44 匝，线性电感是多少？',
     '磁阻固定，电感按匝数平方变化，得到 383.0×(44/40)²≈463.4 µH。'),
    ('把可用宽度扩大到恰好 10.35 mm，24 匝的层计划怎样变化？',
     '11 个 0.85 mm 匝宽与 10 个 0.10 mm 间隙正好占满，依次安排 11、11、2 匝。'),
    ('固定 2 A 总电流，两路电阻率均变为原值的两倍，各支路电流和总损耗如何变化？',
     '电阻比保持，电流仍为 1.20 A 和 0.80 A，总损耗增至 2×0.4128=0.8256 W。'),
    ('若频率从 100 kHz 降到 25 kHz，此材料的集肤深度如何变化？',
     '集肤深度与频率平方根成反比，增为原来的两倍，约 0.417 mm。'),
    ('D=0.20 时若改用 8 K/W 整体热阻，温升是多少？',
     '总损耗仍为 0.949+1.20=2.149 W，对应温升约 17.2 K。'),
    ('若边沿电流为 5 A，同一插值条件下对应的平台栅压与电荷是多少？',
     '5 A 对应栅压 4.25 V，累计电荷为 3+5×(4.25−2.5)=11.75 nC。'),
    ('若只将关断路径电阻由 3 Ω 改为 4 Ω，关断平台持续多久？',
     '关断电流变为 4 V/4 Ω=1 A，转移 12 nC 需要 12 ns。'),
    ('若将同样的电压电流变化压缩到 15 ns，重叠能量和峰值功率是多少？',
     '相同形状下积分减半至 1.00 µJ，中点仍有 50 V×2 A=100 W 峰值功率。'),
    ('若重复频率减半且两段导通比例、电流及每次恢复电荷不变，平均耗散多少？',
     '导通损耗仍为 0.75 W，恢复损耗减至 0.06 W，合计 0.81 W。'),
    ('若只将初始换流电流减为 1 A，2 Ω 串阻情况下的端口首峰是多少？',
     '相对平台的抬高量随初始电流减半，首峰约为 48+10.09/2=53.05 V。'),
    ('若母线从 160 V 增到 200 V，同时维持反射与钳位电压、关断电流 1 A，峰值是多少？',
     '平台与绝对钳位值均上移 40 V，漏源峰值为 380 V，钳位能量仍是 0.810 µJ。'),
    ('将固定损耗从 0.65 W 增到 2.60 W，拟合模型的最佳效率点移到哪里？',
     '固定项增至四倍，最佳电流增至原值的两倍，约为 √(2.60/0.15)=4.16 A。'),
]

for item, exercise in zip(LESSONS, EXERCISES, strict=True):
    item['exercise'] = exercise
