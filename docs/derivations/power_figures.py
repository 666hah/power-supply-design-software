"""Original teaching figures for the switched power stages in the derivation textbook."""

from pathlib import Path
import json

import numpy as np
from matplotlib.patches import Circle, Polygon, Rectangle

from docs.derivations.illustrations import (
    BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label,
)


def _wire(ax, *points, color=INK):
    x, y = zip(*points)
    ax.plot(x, y, color=color, lw=1.65, solid_capstyle='round')


def _flow(ax, start, end, color):
    ax.annotate('', xy=end, xytext=start,
                arrowprops=dict(arrowstyle='-|>', color=color, lw=1.7, shrinkA=0, shrinkB=0))


def _coil(ax, start, end, y, color):
    """A horizontal inductor drawn with four half turns."""
    for left in np.linspace(start, end, 5)[:-1]:
        w = (end - start) / 4
        th = np.linspace(np.pi, 0, 32)
        ax.plot(left + w/2 + w/2*np.cos(th), y + .17*np.sin(th), color=color, lw=1.65)


def _buck_state(ax, on):
    active = BLUE if on else ORANGE
    supply, flywheel = (active, MUTED) if on else (MUTED, active)
    top, bottom, node = 2.35, .34, 2.15
    ax.set(xlim=(-.12, 5.86), ylim=(-.07, 3.03), aspect='equal')
    ax.axis('off')
    _wire(ax, (.43,bottom), (.43,.99), color=supply)
    ax.add_patch(Circle((.43,1.33), .34, facecolor='white', edgecolor=supply, lw=1.65))
    ax.text(.43,1.46,'+',ha='center',va='center',color=supply)
    ax.text(.43,1.2,'−',ha='center',va='center',color=supply)
    _wire(ax,(.43,1.67),(.43,top),(1.00,top),color=supply)
    for x in (1.0,1.75):
        ax.add_patch(Circle((x,top), .051, color=supply))
    _wire(ax,(1.0,top),(1.75,top if on else top+.39),color=supply)
    ax.text(1.34,2.8,'S',ha='center')
    _wire(ax,(1.75,top),(node,top),color=supply)
    _wire(ax,(node,top),(2.72,top),color=active)
    _coil(ax,2.72,3.67,top,active)
    ax.text(3.2,2.78,'L',ha='center')
    _wire(ax,(3.67,top),(5.29,top),(5.29,1.69),color=active)
    ax.add_patch(Rectangle((5.16,.99),.26,.7, facecolor='white', edgecolor=active, lw=1.65))
    _wire(ax,(5.29,.99),(5.29,bottom),(node,bottom),color=active)
    ax.text(5.58,1.33,'R',ha='center',va='center')
    _wire(ax,(node,bottom),(.43,bottom),color=supply)
    _wire(ax,(node,bottom),(node,1.1),color=flywheel)
    ax.add_patch(Polygon([(node-.17,1.1),(node+.17,1.1),(node,1.48)],
                         closed=True, facecolor='white', edgecolor=flywheel, lw=1.5))
    _wire(ax,(node-.19,1.52),(node+.19,1.52),color=flywheel)
    _wire(ax,(node,1.52),(node,top),color=flywheel)
    ax.text(node+.34,1.31,'D',va='center',color=flywheel)
    _wire(ax,(4.29,top),(4.29,1.52))
    _wire(ax,(4.04,1.52),(4.54,1.52))
    _wire(ax,(4.04,1.35),(4.54,1.35))
    _wire(ax,(4.29,1.35),(4.29,bottom))
    ax.text(4.53,1.18,'C',ha='left',va='center')
    for x in (node,4.29):
        ax.plot([x,x],[top,bottom],'o',ms=3,color=INK)
    _flow(ax,(3.76,top),(4.18,top),active)
    _flow(ax,(3.59,bottom),(3.16,bottom),active)
    if on:
        _flow(ax,(.43,1.72),(.43,2.14),active)
    else:
        _flow(ax,(node,.51),(node,.91),active)
    ax.text(.78,.8,'24 V',color=supply,fontsize=8)
    ax.text(4.81,2.61,'12 V',ha='center',fontsize=8)


def buck_paths():
    fig = figure(height=2.05)
    left, right = fig.subplots(1,2)
    _buck_state(left,True)
    _buck_state(right,False)
    panel_label(left,'(a)  开通　电感左端接输入')
    panel_label(right,'(b)  关断　电感电流经 D 续流')
    return fig


def buck_modes():
    fig = figure(height=2.47)
    axes = fig.subplots(1,2,sharey=True)
    for ax, label, t, i, avg in [
        (axes[0], '(a)  连续导通', [0,5,10], [.5,3.5,.5], 2),
        (axes[1], '(b)  断续导通', [0,2.5,5,10],[0,1.5,0,0], .375),
    ]:
        ax.fill_between(t,i,0,color='#d8e9ed')
        ax.plot(t,i,color=BLUE)
        ax.axhline(avg,ls='--',lw=1.2,color=ORANGE)
        ax.set(xlabel='时间 / µs', xlim=(0,10), ylim=(-.14,3.85),xticks=[0,2.5,5,7.5,10])
        ax.text(9.8,avg+.08,f'平均 {avg:g} A',ha='right',color=ORANGE,fontsize=8)
        panel_label(ax,label)
    axes[0].set_ylabel('电感电流 / A')
    axes[1].annotate('零电流驻留', xy=(7.3,0), xytext=(6.2,1.18), ha='center', fontsize=8,
                     arrowprops=dict(arrowstyle='->',color=MUTED))
    return fig


def cross_windows():
    """Equal-width event columns expose short commutations at X004."""
    fig = figure(height=2.5)
    ax = fig.subplots()
    edges = np.array([0.,.004097,1.835403,1.882132,1.899180,2.145584,4.])
    states = [{0,1},{0},{0,1,2,3},{1,2,3},{1,3},{1}]
    colors = [BLUE,TEAL,ORANGE,'#685180']
    for j, state in enumerate(states):
        for winding in range(4):
            ax.add_patch(Rectangle((j+.035,3-winding-.3),.93,.6,linewidth=.65,
                         edgecolor='#c7d1d6',facecolor=colors[winding] if winding in state else '#f6f8f9'))
        ax.text(j+.5,3.82,f'{1000*(edges[j+1]-edges[j]):.1f}',ha='center',va='center',fontsize=8.5)
    ax.text(-.06,3.82,'时长 / ns',ha='right',va='center',fontsize=8.5)
    ax.set(xlim=(-.04,6.04),ylim=(-.49,4.08),xticks=np.arange(6)+.5,
           xticklabels=['①','②','③','④','⑤','⑥'],
           yticks=np.arange(4),yticklabels=['OUT3','OUT2','OUT1','原边'])
    ax.set_xlabel('事件顺序（各列等宽）')
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0)
    return fig


def forward_reset():
    fig=figure(height=2.6)
    left,right=fig.subplots(1,2)
    vin,ratio,eta,fs,lm=30.,.5,.93,250e3,220e-6
    d=(30/eta)/(vin/ratio)
    period=1e6/fs
    ton=d*period
    reset=vin*d/(1-d)
    swing=vin*d/fs/lm
    left.fill_between([0,ton],[vin,vin],color='#d3e7ed')
    left.fill_between([ton,period],[-reset,-reset],color='#f4dfd1')
    left.plot([0,ton,ton,period],[vin,vin,-reset,-reset],color=BLUE)
    left.text(ton/2,13,'+64.5 V·µs',ha='center',fontsize=8.5)
    left.text((ton+period)/2,-20,'−64.5 V·µs',ha='center',fontsize=8.5)
    left.set(ylabel='原边电压 / V',ylim=(-47,43))
    right.plot([0,ton,period],[-swing/2,swing/2,-swing/2],color=TEAL)
    right.plot([ton],[swing/2],'o',color=TEAL,ms=4)
    right.set(ylabel='励磁电流 / A',ylim=(-.21,.21))
    for ax,title in zip((left,right),('(a)  正负伏秒','(b)  励磁电流积分')):
        ax.axhline(0,color=MUTED,lw=.7)
        ax.axvline(ton,color=MUTED,lw=.8,ls=':')
        ax.set(xlabel='时间 / µs',xlim=(0,4),xticks=[0,ton,4],xticklabels=['0','2.15','4'])
        panel_label(ax,title)
    return fig


def multiphase():
    fig = figure(height=2.65)
    left,right=fig.subplots(1,2,sharex=True)
    d=.1
    phase=np.linspace(0,1,1001)
    ripple=[]
    for j,color in enumerate((BLUE,ORANGE,TEAL,'#725585')):
        u=(phase-j/4)%1
        current=7.2*(np.where(u<=d,u/d,(1-u)/(1-d))-.5)
        ripple.append(current)
        left.plot(phase*2,current,color=color,lw=1.45,ls=['-','--','-.',':'][j],label=f'{j+1} 相')
    summed=np.sum(ripple,axis=0)
    right.fill_between(phase*2,0,summed,color='#dcece8')
    right.plot(phase*2,summed,color=TEAL)
    left.legend(ncol=2,loc='upper right',fontsize=7,handlelength=1.5,columnspacing=1.1)
    left.set(ylim=(-4.2,6.9),ylabel='每相交流分量 / A')
    right.set(ylim=(-3.5,4.5),ylabel='总交流分量 / A')
    for ax,title in zip((left,right),('(a)  各相纹波为 7.2 A 峰峰值','(b)  输出总纹波为 4.8 A 峰峰值')):
        ax.set(xlim=(0,2),xlabel='时间 / µs',xticks=[0,.5,1,1.5,2])
        ax.axhline(0,color=MUTED,lw=.6)
        panel_label(ax,title)
    return fig


def llc_network():
    fig=figure(height=2.2)
    ax=fig.subplots()
    ax.set(xlim=(-.35,7.9),ylim=(-.1,2.55),aspect='equal')
    ax.axis('off')
    top,bottom=1.7,.17
    ax.add_patch(Circle((.52,.9),.32,facecolor='white',edgecolor=BLUE,lw=1.6))
    xs=np.linspace(-.20,.20,50)
    ax.plot(.52+xs,.9+.075*np.sin(2*np.pi*xs/.4),color=BLUE,lw=1.2)
    _wire(ax,(.52,bottom),(.52,.58),color=BLUE)
    _wire(ax,(.52,1.22),(.52,top),(1.55,top),color=BLUE)
    ax.add_patch(Rectangle((1.55,top-.12),.60,.24,ec=BLUE,fc='white',lw=1.65))
    _wire(ax,(2.15,top),(2.5,top),color=BLUE)
    _coil(ax,2.5,3.4,top,BLUE)
    _wire(ax,(3.4,top),(3.89,top),color=BLUE)
    for x in (3.89,4.03):
        _wire(ax,(x,top-.24),(x,top+.24),color=BLUE)
    _wire(ax,(4.03,top),(7,top),(7,1.22))
    ax.add_patch(Rectangle((6.87,.66),.26,.56,ec=ORANGE,fc='white',lw=1.65))
    _wire(ax,(7,.66),(7,bottom),(.52,bottom))
    _wire(ax,(5.47,top),(5.47,1.32),color=TEAL)
    for y in np.linspace(.56,1.32,5)[:-1]:
        th=np.linspace(0,np.pi,28)
        ax.plot(5.47+.14*np.sin(th),y+.095*(1-np.cos(th)),color=TEAL,lw=1.65)
    _wire(ax,(5.47,.56),(5.47,bottom),color=TEAL)
    ax.plot([5.47,5.47],[top,bottom],'o',ms=3,color=INK)
    ax.text(.07,.42,'桥压基波',color=BLUE,fontsize=8.5)
    for x,s in [(1.85,'$R_t$'),(2.95,'$L_r$'),(3.96,'$C_r$')]:
        ax.text(x,2.15,s,ha='center')
    ax.text(5.08,.92,'$L_m$',ha='right',color=TEAL)
    ax.text(7.23,1.02,'$R_{ac}$',color=ORANGE)
    ax.text(6.05,-.02,'折回原边的负载',fontsize=8.25,ha='center',va='top')
    _flow(ax,(4.35,top),(4.94,top),BLUE)
    ax.text(4.65,1.85,'$i_r$',ha='center',color=BLUE)
    return fig


def llc_commutation():
    from llc_model import solve

    design=Path(__file__).resolve().parents[2]/'examples/300W_LLC_HALF_HHC.json'
    params=json.loads(design.read_text(encoding='utf-8-sig'))
    result=solve(params)
    if not result['regulation_ok'] or not result['zvs_ok']:
        raise ValueError('360 V LLC 算例未达到本书绘制的稳压及换流条件')
    t=np.asarray(result['time_s'])*1e9
    v=np.asarray(result['v_drive_V'])+result['bridge_amplitude_V']
    td=params['llc_dead_time']*1e9
    view=t<=td+1.
    fig=figure(height=2.55)
    left,right=fig.subplots(1,2)
    left.plot(t[view],v[view],color=BLUE)
    left.set(xlabel='从死区起点计时 / ns',ylabel='半桥节点电压 / V',xlim=(0,td),
             xticks=[0,50,100,150,200,250],ylim=(-15,390))
    panel_label(left,'(a)  周期解中的换流边沿')
    values=[result['zvs_required_charge_C']*1e6,result['zvs_available_charge_C']*1e6]
    bars=right.barh([1,0],values,color=[ORANGE,TEAL],height=.39)
    for bar,vq in zip(bars,values):
        right.text(vq+.015,bar.get_y()+bar.get_height()/2,f'{vq:.3f}',va='center',fontsize=8.5)
    right.set(yticks=[1,0],yticklabels=['所需','可用'],ylim=(-.55,1.55),xlim=(0,.67),
              xlabel='电荷 / µC')
    panel_label(right,'(b)  250 ns 死区的电荷预算')
    return fig


def boost_design():
    fig=figure(height=2.7)
    ax=fig.subplots()
    vin=np.linspace(8,18,250)
    def positive_voltage(v):
        return v*(1-.9*v/24)
    ax.plot(vin,positive_voltage(vin),color=BLUE)
    ax.fill_between(vin,positive_voltage(vin),5.4,color='#e2edf1')
    for v,dx,dy,align in [(8,.18,-.12,'left'),(24/(2*.9),0,.12,'center'),(18,-.15,-.12,'right')]:
        val=positive_voltage(v)
        ax.plot(v,val,'o',ms=4.5,color=ORANGE)
        ax.text(v+dx,val+dy,f'{v:.2f} V → {val:.2f} V',fontsize=8.3,ha=align)
    ax.set(xlim=(7.8,18.2),ylim=(5.32,7.05),xlabel='输入电压 / V',ylabel='电感正伏秒除以周期 / V',xticks=[8,10,12,14,16,18])
    return fig


def llc_design_corners():
    from llc_model import solve

    design = Path(__file__).resolve().parents[2] / 'examples/300W_LLC_HALF_HHC.json'
    params = json.loads(design.read_text(encoding='utf-8-sig'))
    cases = [(vin, power) for vin in (params['V_in_min'], params['V_in_max'])
             for power in (params['P_out'], params['P_out_min'])]
    solved = [solve(dict(params, V_in=vin, P_out=power)) for vin, power in cases]
    if not all(result['regulation_ok'] and result['hhc_timing_ok'] for result in solved):
        raise ValueError('LLC 初选例程的端点结果未达到教材所述稳压条件')
    fig = figure(height=2.85)
    left, right = fig.subplots(1, 2, sharey=True, gridspec_kw={'width_ratios': [1.3, 1.]})
    lo, hi = params['llc_fmin']/1e3, params['llc_fmax']/1e3
    resonant = solved[0]['f_res_Hz']/1e3
    left.axvspan(lo, hi, color='#e9f2f5')
    left.axvline(resonant, color=MUTED, ls='--', lw=.9)
    left.text(resonant+2, 3.46, '串联谐振', fontsize=8, color=MUTED)
    required = solved[0]['zvs_required_charge_C']*1e6
    right.axvline(required, color=ORANGE, lw=1.2, ls='--')
    right.text(required, 3.46, f'所需 {required:.3f}', ha='center', fontsize=8, color=ORANGE)
    for y, result in zip(range(3, -1, -1), solved):
        f_khz = result['frequency_Hz']/1e3
        q_microc = result['zvs_available_charge_C']*1e6
        left.plot(f_khz, y, 'o', color=BLUE, ms=5.5)
        left.annotate(f'{f_khz:.2f}', (f_khz, y), xytext=(5, -1),
                      textcoords='offset points', va='center', fontsize=8,
                      bbox=dict(facecolor='#e9f2f5', edgecolor='none', pad=.3))
        right.plot([required, q_microc], [y, y], color=TEAL, lw=3)
        right.plot(q_microc, y, 'o', color=TEAL, ms=5)
        right.annotate(f'{q_microc:.3f}', (q_microc, y), xytext=(5, -1),
                       textcoords='offset points', va='center', fontsize=8)
    left.set(yticks=[3,2,1,0], yticklabels=[f'{v:g} V · {p:g} W' for v,p in cases],
             xlim=(lo-2, hi+2), ylim=(-.52,3.85), xticks=[lo,100,140,hi],
             xlabel='开关频率 / kHz')
    right.set(xlim=(.30,.605), xticks=[.34,.42,.50,.58], xlabel='死区电荷 / µC')
    panel_label(left, '(a)  调压频率与硬件频限')
    panel_label(right, '(b)  可用换流电荷')
    return fig


FIGURES = {
    'buck_paths': (buck_paths,'理想 Buck 在一个周期内的两条电流路径','沿箭头跟踪电感电流。开关断开后，电感电流仍然由左向右流动，左端电位降至零。'),
    'buck_modes': (buck_modes,'同一只电感在重载和轻载时的一个周期','两幅图的阴影面积分别除以 10 µs，即可读出 2 A 和 0.375 A 的负载电流。'),
    'cross_windows': (cross_windows,'三路反激算例 X004 的六个导通区间','有色格表示该绕组导通。先找 OUT2 的两格，再读上方实际时长，第三与第四段连成一个补电窗口。'),
    'forward_reset': (forward_reset,'正激变压器的原边伏秒与励磁电流','关断区较短，复位电压的幅值相应提高，两块有向面积相加为零，励磁电流回到起点。'),
    'multiphase': (multiphase,'四相 Buck 的各相纹波及同一时刻的电流和','先在左图固定一个时刻，读取四个交流分量并相加，所得电流就是右图同一时刻的纵坐标。'),
    'llc_network': (llc_network,'LLC 的原边基波等效电路','励磁电感与折回原边的负载共享端电压。谐振电感、电容及串联电阻承载同一电流。'),
    'llc_commutation': (llc_commutation,'360 V 半桥 LLC 的死区换流与电荷预算','桥节点抵达母线后被钳住，余下的反向电荷提供换流裕量。曲线取自本书 300 W 算例的周期解。'),
    'boost_design': (boost_design,'Boost 输入电压范围内的电感充磁伏秒','曲线的最高点对应电感每周期最大电流增量，低线对应最大的满载平均输入电流。'),
    'llc_design_corners': (llc_design_corners, '同一套 LLC 硬件在四个边界工况下的周期解',
                           '左图底色表示允许的 65–185 kHz。右图圆点给出死区可用电荷，圆点到虚线的水平距离就是多出的换流电荷。'),
}
