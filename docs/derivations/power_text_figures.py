"""Circuit, timing and calculation figures adjacent to the power-stage derivations."""

from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from matplotlib.patches import Circle, Rectangle

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label
from docs.derivations.power_figures import _coil, _flow, _wire


BLUE_FILL = '#dcecf3'
ORANGE_FILL = '#f3e2d6'
TEAL_FILL = '#dbede6'
BASE = Path(__file__).resolve().parents[2]


def _pair(titles, height=4.05, **kwargs):
    fig = figure(height=height)
    axes = fig.subplots(1, 2, **kwargs)
    for ax, title in zip(axes, titles):
        panel_label(ax, title)
    return fig, axes


def _stack(titles, height=4.15):
    fig = figure(height=height)
    axes = fig.subplots(len(titles), 1, sharex=True)
    for ax, title in zip(axes, titles):
        panel_label(ax, title)
    return fig, axes


def _trace(ax, x, y, xlabel=None, ylabel=None, *, ink=BLUE, shade=None, **kwargs):
    if shade:
        ax.fill_between(x, 0, y, color=shade)
    ax.plot(x, y, color=ink, **kwargs)
    ax.axhline(0, color=MUTED, lw=.55, zorder=0)
    ax.grid(alpha=.18, axis='y')
    ax.set(xlabel=xlabel, ylabel=ylabel)


def _diagram(ax, xlim=(0, 8), ylim=(0, 4.8)):
    ax.set(xlim=xlim, ylim=ylim, aspect='equal')
    ax.axis('off')


def _cell(ax, x, y, label, *, color=BLUE, width=1.48, height=.68):
    ax.add_patch(Rectangle((x-width/2,y-height/2), width,height,
                           fc='white',ec=color,lw=1.25, zorder=2))
    ax.text(x,y,label,ha='center',va='center',color=color,zorder=3,fontsize=9)


def _node(ax, x, y, label=None, *, color=INK, offset=(0,.26)):
    ax.plot(x,y,'o',color=color,ms=3.5)
    if label:
        ax.text(x+offset[0],y+offset[1],label,color=color,ha='center',va='center',fontsize=9)


def buck_capacitor():
    fig, axes = _stack(('(a)  电感电流超过负载才累积电荷', '(b)  从谷电压到峰电压的电荷行程'))
    t = np.linspace(0, 10, 1001)
    current = np.interp(t, [0, 5, 10], [-1.5, 1.5, -1.5])
    charge = np.r_[0, np.cumsum((current[:-1]+current[1:])*.5*np.diff(t))]
    _trace(axes[0],t,current,ylabel='$i_C$ / A')
    axes[0].fill_between(t,0,current,where=current>=0,color=TEAL_FILL)
    axes[0].fill_between(t,0,current,where=current<0,color=ORANGE_FILL)
    _trace(axes[1],t,charge,'时间 / µs','电荷变化 / µC',ink=TEAL)
    for ax in axes:
        for event in (2.5,7.5):
            ax.axvline(event,color=MUTED,ls=':',lw=.85)
        ax.set(xlim=(0,10),xticks=[0,2.5,5,7.5,10])
    axes[1].annotate('两极值相差 3.75 µC',xy=(7.5,1.875),xytext=(3.65,1.5),
                     arrowprops=dict(arrowstyle='->',color=MUTED),fontsize=9)
    return fig


def boost_paths():
    fig, axes = _stack(('(a)  开通　输入给电感充磁，电容给负载供电',
                        '(b)  关断　输入和电感串接，经 D 补充输出电荷'), height=4.35)
    for ax,on in zip(axes,(True,False)):
        _diagram(ax,(0,9),(0,2.75))
        y, ground, x = 2.0,.36,3.75
        source_color = BLUE
        output_color = MUTED if on else ORANGE
        _wire(ax,(.75,y),(1.45,y),color=source_color)
        _coil(ax,1.45,2.8,y,source_color)
        _wire(ax,(2.8,y),(x,y),(4.75,y),color=source_color if on else ORANGE)
        _wire(ax,(5.72,y),(7.95,y),(7.95,1.54),color=output_color)
        if on:
            _wire(ax,(x,ground),(.75,ground),color=BLUE)
            _wire(ax,(x,ground),(6.42,ground),color=MUTED)
            _wire(ax,(7.95,.86),(7.95,ground),(6.42,ground),color=TEAL)
        else:
            _wire(ax,(7.95,.86),(7.95,ground),(.75,ground),color=ORANGE)
        for xx,label,ink in [(.75,'$V_g$',BLUE),(x,'S',BLUE if on else MUTED),
                             (6.42,'C',TEAL),(7.95,'R',TEAL if on else ORANGE)]:
            _wire(ax,(xx,y),(xx,1.54),color=ink)
            _cell(ax,xx,1.20,label,color=ink,width=.58)
            _wire(ax,(xx,.86),(xx,ground),color=ink)
        _cell(ax,5.24,y,'D  →',color=output_color,width=.98)
        _node(ax,x,y,'开关节点')
        _node(ax,6.42,y,'输出端')
        _flow(ax,(.88,y),(1.27,y),BLUE)
        _flow(ax,(6.69,y),(7.38,y),TEAL if on else ORANGE)
        if on:
            _flow(ax,(x,.85),(x,.47),BLUE)
        else:
            _flow(ax,(4.02,y),(4.58,y),ORANGE)
        ax.text(2.13,2.52,'电感 L',ha='center',color=BLUE)
    return fig


def boost_charge():
    fig, axes = _stack(('(a)  电感两段通电', '(b)  只有关断后的三角形送到输出'))
    d = 1/np.sqrt(8)
    edges = [0,10*d,20*d,10]
    pk = 6*d
    _trace(axes[0],edges,[0,pk,0,0],ylabel='$i_L$ / A')
    t = [0,edges[1],edges[1],edges[2],10]
    _trace(axes[1],t,[0,0,pk,0,0],'时间 / µs','$i_D$ / A',ink=ORANGE,shade=ORANGE_FILL)
    axes[1].text(6.08,1.26,'3.750 µC',ha='center',color=ORANGE)
    for ax in axes:
        for edge in edges[1:-1]:
            ax.axvline(edge,color=MUTED,ls=':',lw=.85)
        ax.set(xlim=(0,10),xticks=edges,xticklabels=['0','3.54','7.07','10'],ylim=(-.14,2.45))
    return fig


def inverting_voltage():
    fig, (left,right) = _pair(('(a)  同一地线上的三个电位','(b)  储能与输出的电流面积'))
    _diagram(left,(0,4),(0,5.5))
    for y,label,col in ((4.7,'输入 +12 V',BLUE),(2.7,'输入地 0 V',MUTED),(.7,'负输出 −12 V',ORANGE)):
        _wire(left,(.38,y),(3.63,y),color=col)
        left.text(.48,y+.16,label,color=col)
    left.annotate('',xy=(2.84,4.7),xytext=(2.84,.7),arrowprops=dict(arrowstyle='<->',color=INK))
    left.text(2.66,2.7,'24 V',ha='right',va='center',bbox=dict(fc='white',ec='none'))
    _trace(right,[0,2.5,5,10],[0,1.5,0,0],'时间 / µs','$i_L$ / A')
    right.fill_between([0,2.5],0,[0,1.5],color=BLUE_FILL,label='输入')
    right.fill_between([2.5,5],0,[1.5,0],color=ORANGE_FILL,label='输出')
    right.set(xlim=(0,10),xticks=[0,2.5,5,10],ylim=(0,1.85))
    right.legend(loc='upper right')
    return fig


def buck_period_map():
    fig, (left,right) = _pair(('(a)  以同一节点写两段方程','(b)  周期末回到初态'))
    _diagram(left,(0,4),(0,5.3))
    for y,text,color in [(4.45,'开通  $v_x=V_g$',BLUE),(2.65,'续流  $v_x=0$',ORANGE),(.82,'驻留  $i_L=0$',TEAL)]:
        _cell(left,2,y,text,color=color,width=2.73)
    _flow(left,(2,4.03),(2,3.08),MUTED)
    _flow(left,(2,2.23),(2,1.25),MUTED)
    left.text(2.18,1.73,'若下降到零',va='center',fontsize=9)
    t=np.asarray([0.,2.5,5.,10.])
    current=np.interp(np.linspace(0,10,1001),t,[0.,1.5,0.,0.])
    ts=np.linspace(0,10,1001)
    v=np.r_[0,np.cumsum((current[:-1]+current[1:]-.75)*np.diff(ts)*.5)]/100*1e3
    ax=right
    _trace(ax,v,current,'电容电压相对初值 / mV','$i_L$ / A')
    for value, label, dx, va in [(0,'初态与终态',4, 'bottom'),(250,'关断',5,'center'),(500,'电流为零',5,'bottom')]:
        ax.plot(v[value],current[value],'o',color=ORANGE,ms=4)
        ax.annotate(label,(v[value],current[value]),xytext=(dx,6),textcoords='offset points',va=va,fontsize=8.5)
    ax.set(ylim=(-.08,1.74),xlim=(-6,26))
    return fig


def flyback_path():
    fig, (left,right) = _pair(('(a)  主开关导通　原边储能','(b)  主开关关断　副边传能'))
    for ax,on in ((left,True),(right,False)):
        _diagram(ax,(0,5.15),(.1,5.1))
        p,s = (BLUE,MUTED) if on else (MUTED,ORANGE)
        _wire(ax,(.60,1),(.60,4.05),(1.64,4.05),(1.64,3.65),color=p)
        _wire(ax,(1.64,1.65),(1.64,1),(.60,1),color=p)
        _cell(ax,.60,2.5,'$V_g$',color=p,width=.6)
        _cell(ax,1.64,1.33,'S',color=p,width=.52,height=.39)
        _wire(ax,(3.06,3.65),(3.06,4.05),(4.62,4.05),(4.62,1),(3.06,1),(3.06,1.65),color=s)
        _cell(ax,3.89,4.05,'D  →',color=s,width=.82,height=.56)
        _cell(ax,4.62,2.5,'C ∥ R',color=s,width=.8)
        for x,col,side in ((1.64,p,1),(3.06,s,-1)):
            for yy in np.arange(1.65,3.65,.5):
                q=np.linspace(0,np.pi,24)
                ax.plot(x+side*.24*np.sin(q),yy+.25*(1-np.cos(q)),color=col,lw=1.65)
        for x in [2.25,2.45]:
            _wire(ax,(x,1.65),(x,3.65),color=MUTED)
        _node(ax,1.64,3.87,color=p)
        _node(ax,3.06,1.31,color=s)
        if on:
            _flow(ax,(.94,4.05),(1.41,4.05),p)
            ax.text(2.38,.46,'副边整流管反偏',ha='center',color=MUTED)
        else:
            _flow(ax,(4.62,3.64),(4.62,3.02),s)
            ax.text(2.38,.46,'电流从副边非同名端流出',ha='center',color=s,fontsize=8.5)
    return fig


def flyback_current_ref():
    fig, axes = _stack(('(a)  原边的实际电流与折回原边的励磁电流',
                        '(b)  副边整流管实际导通电流'))
    t = [0,2,2,4,10]
    _trace(axes[0],t,[0,1,0,0,0],ylabel='电流 / A',shade=BLUE_FILL)
    axes[0].plot([0,2,4,10],[0,1,0,0],color=TEAL,ls='--',label='原边折算励磁坐标')
    axes[0].legend(loc='upper right')
    _trace(axes[1],t,[0,0,2,0,0],'时间 / µs','电流 / A',ink=ORANGE,shade=ORANGE_FILL)
    for ax in axes:
        ax.set(xlim=(0,10),xticks=[0,2,4,6,8,10])
        ax.axvline(2,color=MUTED,ls=':',lw=.85)
    return fig


def qr_trajectory():
    fig, (left,right) = _pair(('(a)  退磁后从右端开始运动','(b)  由高点经中心到首谷'))
    theta=np.linspace(0,np.pi,301)
    omega=1/np.sqrt(800e-6*100e-12)
    voltage=120*np.cos(theta)
    current=-.1e-9*120*omega*np.sin(theta)*1e3
    _trace(left,voltage,current,'漏极电压减母线 / V','电容电流 / mA')
    left.plot([120,0,-120],[0,current.min(),0],'o',ms=5,color=ORANGE)
    left.text(116,4,'起点',ha='right')
    left.text(-116,4,'首谷',ha='left')
    left.set(ylim=(-49,11),xlim=(-150,150))
    _trace(right,theta/omega*1e6,300+voltage,'退磁后的时间 / µs','漏极电压 / V')
    right.axhline(300,color=MUTED,ls=':')
    right.plot(np.array([0,np.pi/2,np.pi])/omega*1e6,[420,300,180],'o',color=ORANGE,ms=5)
    right.set(ylim=(145,445),xlim=(-.035,.93))
    return fig


def qr_valleys():
    fig, axes = _stack(('(a)  从退磁完成计算谷点','(b)  由关断消隐筛选最早可用谷点'))
    t = np.linspace(0,5.9,650)
    valleys = np.array([1,3,5])*.8885766
    _trace(axes[0],t,300+120*np.cos(np.pi*t/.8885766),ylabel='$V_{DS}$ / V')
    axes[0].plot(valleys,[180]*3,'o',color=ORANGE,ms=5)
    axes[1].broken_barh([(0,2)],(.35,.31),facecolors=ORANGE_FILL)
    axes[1].broken_barh([(2,3.9)],(.35,.31),facecolors=TEAL_FILL)
    axes[1].text(.9,.53,'仍在消隐',ha='center',va='center')
    axes[1].text(4.58,.53,'消隐已结束',ha='center',va='center')
    for ax in axes:
        ax.axvline(2,color=ORANGE,ls='--',lw=1.1)
        ax.set(xlim=(0,5.9))
    for j,valley in enumerate(valleys,1):
        axes[1].plot(valley,.27,'o',color=ORANGE if j==1 else TEAL,ms=6)
        axes[1].text(valley,.09,f'谷 {j}',ha='center',va='center')
    axes[1].set(ylim=(0,1),yticks=[],xlabel='退磁后的时间 / µs')
    return fig


def rcd_transition():
    fig, axes = _stack(('(a)  自然首峰与钳位介入','(b)  钳位管电荷只取触及后的面积'))
    inductance,cap,current,height = 1e-6,200e-12,2.,80.
    rt = np.sqrt(inductance*cap)
    excess = current*np.sqrt(inductance/cap)
    t1=rt*np.arcsin(height/excess)
    ic=current*np.sqrt(1-(height/excess)**2)
    t2=inductance*ic/height
    t=np.linspace(0,25e-9,401)
    axes[0].plot(t*1e9,excess*np.sin(t/rt),ls='--',color=MUTED,label='自由首波瓣')
    tb=np.linspace(0,t1,120)
    axes[0].plot(np.r_[tb,t1+t2]*1e9,np.r_[excess*np.sin(tb/rt),height],color=BLUE,label='钳位首段')
    axes[0].set(ylabel='平台以上电压 / V',ylim=(0,165))
    axes[0].legend(loc='upper left')
    _trace(axes[1],np.array([0,t1,t1,t1+t2,34e-9])*1e9,[0,0,ic,0,0],
           '距关断时间 / ns','钳位电流 / A',ink=ORANGE,shade=ORANGE_FILL)
    axes[1].text(15,.75,'约 17.0 nC',color=ORANGE,fontsize=9)
    for ax in axes:
        ax.set(xlim=(0,34))
        ax.axvline(t1*1e9,color=MUTED,ls=':')
    return fig


def cross_nodes():
    fig=figure(height=3.52)
    ax=fig.subplots()
    _diagram(ax,(0,9.7),(0,5.2))
    for y,route,ref in [(4.15,'OUT1','30.000 V'),(2.65,'OUT2','11.508 V'),(1.15,'OUT3','3.583 V')]:
        _coil(ax,1.20,2.22,y,BLUE)
        _wire(ax,(2.22,y),(8.89,y),color=BLUE)
        for x,label in [(3.08,'整流管'),(6.20,'防反管')]:
            _cell(ax,x,y,label,color=ORANGE,width=1.16,height=.55)
        _node(ax,4.76,y,'电容端',color=TEAL,offset=(0,.38))
        _node(ax,8.37,y,ref,color=BLUE,offset=(0,.38))
        ax.text(.45,y,route,ha='left',va='center',color=BLUE)
        ax.text(8.37,y-.49,'负载端参考',ha='center',fontsize=8.5)
    _flow(ax,(4.76,4.15),(4.76,3.67),TEAL)
    ax.text(4.76,3.49,'SSR 取样点',ha='center',va='center',color=TEAL,fontsize=8.7)
    return fig


def cross_matrix():
    turns=np.array([6.,12.,5.,2.])
    diag=8*(turns/turns[0])**2
    mat=.995*np.sqrt(diag[:,None]*diag[None,:])
    np.fill_diagonal(mat,diag)
    fig,(left,right)=_pair(('(a)  同名端统一的四绕组矩阵','(b)  同一原边的两种短路条件'))
    left.imshow(mat,cmap='Blues',vmin=0,vmax=37)
    for i,row in enumerate(mat):
        for j,value in enumerate(row):
            left.text(j,i,f'{value:.3f}',ha='center',va='center',fontsize=8,
                      color='white' if value>21 else INK)
    for setter in (left.set_xticks,left.set_yticks):
        setter(range(4),['P','S1','S2','S3'])
    left.set_xlabel('互感与自感 / µH')
    full=mat[0,0]-mat[0,1:]@np.linalg.solve(mat[1:,1:],mat[1:,0])
    pair=mat[0,0]-mat[0,1]**2/mat[1,1]
    for j,(value,label,color) in enumerate([(pair,'只短 S1',BLUE),(full,'短接 S1、S2、S3',TEAL)]):
        right.barh(j,value,color=color,height=.43)
        right.text(value+.004,j,f'{value:.4f}',va='center',fontsize=8.5)
    right.set(yticks=[0,1],yticklabels=['只短 S1','短接三组'],xlabel='原边增量漏感 / µH',xlim=(0,.115))
    return fig


def cross_event_conditions():
    fig,(left,right)=_pair(('(a)  已导通支路的截止事件','(b)  开路支路的再导通事件'))
    t=np.linspace(0,1,401)
    stop=.64
    _trace(left,t,np.maximum(0,1-t/stop),'段内归一化时间','二极管电流 / 归一值',ink=BLUE,shade=BLUE_FILL)
    left.plot([stop],[0],'o',color=ORANGE)
    left.annotate('电流降至零',xy=(stop,0),xytext=(.45,.38),
                  arrowprops=dict(arrowstyle='->',color=MUTED),fontsize=8.5)
    enable=.55
    u=(t-enable)*1.8
    _trace(right,t,np.minimum(0,u),'段内归一化时间','正向电压裕量 / 归一值',ink=TEAL)
    right.plot(t[t>=enable],u[t>=enable],color=MUTED,ls='--',lw=1)
    right.plot([enable],[0],'o',color=ORANGE)
    right.annotate('触及整流门槛',xy=(enable,0),xytext=(.16,.35),
                  arrowprops=dict(arrowstyle='->',color=MUTED),fontsize=8.5)
    for ax in (left,right):
        ax.set(xlim=(0,1))
    return fig


def cross_charge_window():
    fig=figure(height=4.15)
    axes=fig.subplots(2,1)
    panel_label(axes[0],'(a)  X004 整周期内 OUT2 的补电窗口')
    axes[0].broken_barh([(0,4000)],(.30,.32),facecolors=BLUE_FILL)
    axes[0].broken_barh([(1835.403,63.777)],(.30,.32),facecolors=ORANGE)
    axes[0].annotate('实际导通 63.777 ns',xy=(1867.3,.6),xytext=(2300,.87),
                     arrowprops=dict(arrowstyle='->',color=MUTED),fontsize=8.5)
    axes[0].set(ylim=(0,1),yticks=[],xlim=(0,4000),xlabel='周期内时间 / ns')
    bottom=axes[1]
    panel_label(bottom,'(b)  把同一 20.206 nC 分别摊到两种时间长度')
    bottom.barh([1,0],[316.818-.4,5.05143-.4],left=.4,color=[ORANGE,TEAL],height=.42)
    for y,v in [(1,316.818),(0,5.05143)]:
        bottom.text(v*1.1,y,f'{v:.3g}',va='center',fontsize=9)
    bottom.set(xscale='log',xlim=(.4,730),yticks=[1,0],yticklabels=['窗口均值','周期均值'],
               xlabel='平均电流 / mA（对数刻度）')
    return fig


def cross_energy():
    fig,(left,right)=_pair(('(a)  端口功率分账','(b)  同一端口功率除以开关频率'))
    for ax,factor,unit in [(left,1,'W'),(right,4,'µJ')]:
        power=31.13114*factor
        loss=5.16338*factor
        ax.barh([0],[power],color=TEAL,height=.43)
        ax.barh([0],[loss],left=power,color=ORANGE,height=.43)
        ax.text(power*.5,0,f'负载\n{power:.3f}',va='center',ha='center',color='white',fontsize=9)
        ax.text(power+loss*.5,.34,f'耗散\n{loss:.3f}',va='center',ha='center',color=ORANGE,fontsize=8)
        ax.set(yticks=[],ylim=(-.6,.67),xlim=(0,38.5*factor),xlabel=f'输入及去向 / {unit}')
    return fig


def cross_corner_span():
    fig,(left,right)=_pair(('(a)  固定输入和 OUT2 自身负载','(b)  放开全部输入与负载界限'))
    for ax,lo,hi,lowest,pct in [(left,12.116392,13.380403,'X008',10.9834),
                                (right,11.570544,13.380403,'X014',15.7265)]:
        ax.axvline(11.508333,ls=':',color=MUTED)
        ax.plot([lo,hi],[.54,.54],'o-',color=TEAL,lw=3,ms=5)
        for x,n,ha in [(lo,lowest,'left'),(hi,'X004','right')]:
            ax.text(x,.67,f'{n}\n{x:.3f} V',ha=ha,fontsize=8.5)
        ax.text((lo+hi)/2,.31,f'{hi-lo:.3f} V / 11.508 V = {pct:.2f}%',ha='center',fontsize=8.5)
        ax.set(yticks=[],ylim=(0,1),xlim=(11.35,13.61),xlabel='OUT2 负载端电压 / V')
    return fig


def forward_paths():
    fig,axes=_stack(('(a)  导通　次级直接向输出电感传能',
                     '(b)  复位　原边钳位与输出续流独立'),height=4.38)
    for ax,on in zip(axes,(True,False)):
        _diagram(ax,(0,9),(0,2.55))
        col=BLUE if on else ORANGE
        _cell(ax,1.23,1.42,'主开关\n输入供电' if on else '辅助开关\n钳位复位',color=col,width=1.75,height=.91)
        _cell(ax,3.36,1.42,'变压器',color=col,width=1.30,height=.75)
        _cell(ax,5.21,1.42,'正向管' if on else '续流管',color=col,width=1.12)
        _coil(ax,6.05,7.27,1.42,TEAL)
        _cell(ax,8.14,1.42,'输出',color=TEAL,width=1.07)
        _flow(ax,(2.16,1.42),(2.69,1.42),col)
        if on:
            _flow(ax,(4.10,1.42),(4.58,1.42),col)
        else:
            _wire(ax,(4.15,.57),(5.21,.57),color=TEAL)
            _flow(ax,(5.21,.57),(5.21,1.03),TEAL)
        _wire(ax,(5.8,1.42),(6.05,1.42),color=TEAL)
        _flow(ax,(7.3,1.42),(7.6,1.42),TEAL)
        ax.text(6.59,1.86,'$L_o$',ha='center',color=TEAL)
    return fig


def forward_clamp_cap():
    fig,axes=_stack(('(a)  复位电流先流入钳位电容','(b)  同一电荷隆起在复位中点出现'))
    duty=(30/.93)/60
    tr=4*(1-duty)
    imax=30*duty*4/(2*220)
    t=np.linspace(0,tr,501)
    current=imax*(1-2*t/tr)
    lift=imax*(t-t*t/tr)/.047
    _trace(axes[0],t,current,ylabel='$i_m$ / A')
    axes[0].fill_between(t,0,current,where=current>=0,color=TEAL_FILL)
    axes[0].fill_between(t,0,current,where=current<0,color=ORANGE_FILL)
    _trace(axes[1],t,lift,'从复位开始计时 / µs','$v_C$ 增量 / V',ink=TEAL)
    for ax in axes:
        ax.axvline(tr/2,color=MUTED,ls=':')
        ax.set(xlim=(0,tr),xticks=[0,tr/2,tr],xticklabels=['0',f'{tr/2:.3f}',f'{tr:.3f}'])
    return fig


def forward_main_current():
    fig,axes=_stack(('(a)  输出电感看到一个完整周期','(b)  开通时反射负载与励磁电流叠加'))
    duty=(30/.93)/60
    ton=duty*4
    ripple=(60-30/.93)*ton/68
    i0,i1=40/30-ripple/2,40/30+ripple/2
    im=30*ton/(2*220)
    _trace(axes[0],[0,ton,4],[i0,i1,i0],ylabel='$i_{L_o}$ / A')
    _trace(axes[1],[0,ton,ton,4],[i0/.5-im,i1/.5+im,0,0],
           '时间 / µs','主开关电流 / A',ink=ORANGE,shade=ORANGE_FILL)
    for ax in axes:
        ax.axvline(ton,color=MUTED,ls=':')
        ax.set(xlim=(0,4),xticks=[0,ton,4],xticklabels=['0','2.15','4'])
    return fig


def forward_step():
    fig=figure(height=3.8)
    axes=fig.subplots(2,1)
    panel_label(axes[0],'(a)  一个周期内按门极状态更新连接')
    panel_label(axes[1],'(b)  细化网格才能分开相近事件')
    for ax,widths,labels in [(axes[0],[2.05,.10,1.75,.10],['主开关','死区','辅助开关','死区']),
                            (axes[1],[.45,.10,.45],['主开关末段','死区','辅助开关初段'])]:
        x=0
        for width,label in zip(widths,labels):
            col=ORANGE_FILL if label=='死区' else BLUE_FILL
            ax.broken_barh([(x,width)],(.4,.32),facecolors=col,edgecolors='white')
            if width>.2:
                ax.text(x+width/2,.56,label,ha='center',va='center',fontsize=9)
            else:
                ax.text(x+width/2,.83,'死区',ha='center',va='center',fontsize=8,color=ORANGE)
            x+=width
        ax.set(xlim=(0,x),ylim=(0,1),yticks=[])
    axes[0].set_xlabel('全周期时间 / µs（示意时序）')
    axes[1].set_xlabel('关断边沿局部时间 / µs（示意时序）')
    return fig


def cot_gates():
    fig=figure(height=4)
    ax=fig.subplots()
    for phase in range(4):
        y=3-phase
        start=.5*phase
        ax.broken_barh([(0,2)],(y-.24,.48),facecolors='#eef2f4')
        ax.broken_barh([(start,.2)],(y-.24,.48),facecolors=BLUE)
        ax.text(start+.10,y,'通',color='white',ha='center',va='center',fontsize=8)
    for x in [.2,.5,.7,1,1.2,1.5,1.7]:
        ax.axvline(x,color=MUTED,lw=.55,ls=':')
    ax.set(yticks=[3,2,1,0],yticklabels=['第 1 相','第 2 相','第 3 相','第 4 相'],
           xlim=(0,2),ylim=(-.64,3.7),xticks=[0,.2,.5,.7,1,1.2,1.5,1.7,2],
           xlabel='相位对应的时间 / µs')
    return fig


def cot_cancellation():
    fig,(left,right)=_pair(('(a)  给定占空比时产生的总纹波',
                            '(b)  每相继续承受自己的纹波'))
    d=np.linspace(0,1,1001)
    alpha=(4*d)%1
    left.plot(d,20*alpha*(1-alpha),color=TEAL)
    for x in (.25,.5,.75):
        left.plot(x,0,'o',color=ORANGE,ms=4)
    left.set(xlim=(0,1),ylim=(-.25,5.5),xlabel='占空比 D',ylabel='四相总纹波 / A')
    _trace(right,d,80*d*(1-d),'占空比 D','单相纹波 / A')
    for x in (.25,.5,.75):
        right.plot(x,80*x*(1-x),'o',color=ORANGE,ms=4)
    right.set(xlim=(0,1),ylim=(-1,22))
    return fig


def cot_balance():
    fig,(left,right)=_pair(('(a)  两相导通压降不同','(b)  采样偏置搬移实际平均电流'))
    for ax,a,b,subtitle in [(left,6,4,'等有效导通电压；电阻 10、15 mΩ'),
                             (right,4.75,5.25,'采样读数一致；偏置 +0.5、0 A')]:
        for j,iv,c in [(0,a,BLUE),(1,b,TEAL)]:
            ax.bar(j,iv,color=c,width=.43)
            ax.text(j,iv+.14,f'{iv:g} A',ha='center',fontsize=9)
        ax.axhline(5,color=ORANGE,ls=':',lw=1)
        ax.text(.5,7.23,subtitle,ha='center',fontsize=8.5)
        ax.set(xlim=(-.63,1.63),ylim=(0,7.7),xticks=[0,1],xticklabels=['相 1','相 2'],ylabel='真实平均电流 / A')
    return fig


def cot_step_charge():
    fig,axes=_stack(('(a)  阶跃后先消耗延迟电荷','(b)  两段亏电叠加为电容容量的选择依据'))
    t=[0,.4,.9,1.25]
    delta=[8,8,0,0]
    _trace(axes[0],t,delta,ylabel='供电缺口 / A',ink=ORANGE)
    axes[0].fill_between(t[:2],0,delta[:2],color=BLUE_FILL)
    axes[0].fill_between(t[1:3],0,delta[1:3],color=ORANGE_FILL)
    axes[0].text(.20,3.2,'3.2 µC',ha='center')
    axes[0].text(.55,2.1,'2.0 µC',ha='center')
    t=np.linspace(0,1.25,501)
    u=np.clip(t-.4,0,.5)
    q=8*np.minimum(t,.4)+8*u-8*u**2
    _trace(axes[1],t,q,'负载跳高后的时间 / µs','累计亏电 / µC',ink=TEAL)
    axes[1].text(1.1,4.25,'5.2 µC',ha='center')
    for ax in axes:
        ax.set(xlim=(0,1.25),xticks=[0,.4,.9,1.25])
        for edge in (.4,.9):
            ax.axvline(edge,color=MUTED,ls=':',lw=.85)
    return fig


@lru_cache(maxsize=4)
def _llc(vin=360,power=300):
    from llc_model import solve
    params=json.loads((BASE/'examples/300W_LLC_HALF_HHC.json').read_text(encoding='utf-8-sig'))
    params.update(V_in=vin,P_out=power)
    result=solve(params)
    if not (result['regulation_ok'] and result['hhc_timing_ok']):
        raise ValueError(f'教材 LLC 工作点未通过稳压和 HHC 定时: {vin} V, {power} W')
    return params,result


def llc_fundamental():
    fig,(left,right)=_pair(('(a)  半桥方波取零均值后的基波','(b)  同一阻抗的相量加法'))
    phi=np.linspace(0,2*np.pi,700)
    left.plot(phi/np.pi,180*np.sign(np.sin(phi)),color=MUTED,label='桥压方波')
    left.plot(phi/np.pi,4*180/np.pi*np.sin(phi),color=BLUE,label='基波')
    left.set(xlim=(0,2),xticks=[0,.5,1,1.5,2],xlabel='相位 / π rad',ylabel='桥压交流分量 / V')
    left.legend(loc='lower left')
    w=2*np.pi*120e3
    zp=1/(1/99.60+1/(1j*w*250e-6))
    zs=1j*(w*50e-6-1/(w*50.66e-9))
    _flow(right,(0,0),(zp.real,zp.imag),BLUE)
    _flow(right,(zp.real,zp.imag),((zp+zs).real,(zp+zs).imag),ORANGE)
    right.plot([0,(zp+zs).real],[0,(zp+zs).imag],ls='--',color=TEAL,lw=1)
    right.text(33,13,'$Z_p$',color=BLUE)
    right.text(zp.real+2,zp.imag+3,'$Z_s$',color=ORANGE)
    right.text(31,26,'$Z_p+Z_s$',color=TEAL)
    right.set(xlim=(0,112),ylim=(0,66),xlabel='实部 / Ω',ylabel='虚部 / Ω',aspect='equal')
    return fig


def llc_gain_regions():
    from llc_model import fha_gain
    fig,(left,right)=_pair(('(a)  低频谐振峰','(b)  允许频段内的增益'))
    f=np.linspace(25e3,185e3,1601)
    for watts,color,ls in [(300,BLUE,'-'),(30,TEAL,'--')]:
        r=8/np.pi**2*4**2*48**2/watts
        gain=fha_gain(f,50e-6,50.66e-9,250e-6,r)
        for ax in (left,right):
            ax.plot(f/1e3,gain,color=color,ls=ls,label=f'{watts} W 恒阻')
            ax.set(xlabel='开关频率 / kHz')
    left.axvline(65,color=MUTED,ls=':',lw=.9)
    left.text(63,7.2,'65 kHz 下限',ha='right',fontsize=8.5)
    left.set(xlim=(27,75),ylim=(.45,19),yscale='log',ylabel='FHA 增益（对数刻度）')
    left.set_yticks([.5,1,2,5,10],['0.5','1','2','5','10'])
    right.axvline(100,color=MUTED,ls=':',lw=.9)
    right.text(102,1.29,'串联谐振',fontsize=8.5)
    right.set(xlim=(65,185),ylim=(.78,1.47),ylabel='FHA 增益 / 无量纲')
    right.legend(loc='upper right')
    return fig


def llc_current_split():
    p,r=_llc()
    time=r['time_s']*1e6
    fig,axes=_stack(('(a)  串联电流与励磁电流分开记录','(b)  两者之差向整流端提供电流'))
    _trace(axes[0],time,r['i_res_A'],ylabel='原边电流 / A',label='$i_r$')
    axes[0].plot(time,r['i_mag_A'],color=ORANGE,ls='--',label='$i_m$')
    axes[0].legend(loc='upper right')
    _trace(axes[1],time,r['i_rect_A'],'时间 / µs','整流电流 / A',ink=TEAL,shade=TEAL_FILL)
    for ax in axes:
        ax.axvline(.5/r['frequency_Hz']*1e6,color=MUTED,ls=':',lw=.85)
        ax.set_xlim(0,float(time[-1]))
    return fig


def llc_state_loop():
    p,r=_llc()
    fig,(left,right)=_pair(('(a)  中心化后的谐振电容坐标','(b)  电感与电容的能量交换'))
    v=r['v_res_V']
    i=r['i_res_A']
    time=r['time_s']*1e6
    _trace(left,v,i,'中心化电容电压 / V','$i_r$ / A')
    left.plot(v[0],i[0],'o',ms=5,color=ORANGE)
    left.annotate('半周期起点',(v[0],i[0]),xytext=(9,-13),textcoords='offset points',fontsize=8.5)
    half=np.abs(time-.5e6/r['frequency_Hz']).argmin()
    left.plot(v[half],i[half],'o',ms=5,color=TEAL)
    left.annotate('下一半周起点',(v[half],i[half]),xytext=(-87,9),textcoords='offset points',fontsize=8.5)
    local_l=50e-6
    local_c=50.66e-9
    _trace(right,time,5e5*local_l*i**2,'时间 / µs','交流储能 / µJ',label='$L_r$')
    right.plot(time,5e5*local_c*v**2,color=ORANGE,ls='--',label='$C_r$')
    right.legend(loc='upper right')
    return fig


def llc_bridge_capacitors():
    fig,(left,right)=_pair(('(a)  半桥　两只管共用一个变动节点',
                            '(b)  全桥　两个节点等幅反向移动'),height=4.23)
    for ax in (left,right):
        _diagram(ax,(0,5),(0,5.5))
        for y,label in [(4.63,'+ 母线'),(.83,'− 母线')]:
            _wire(ax,(.55,y),(4.5,y),color=INK)
            ax.text(.6,y+.19,label,fontsize=9)
    for ax,xs in [(left,[2.5]),(right,[1.6,3.7])]:
        for i,x in enumerate(xs):
            color=BLUE if i==0 else ORANGE
            _wire(ax,(x,.83),(x,4.63),color=color)
            _cell(ax,x,3.75,'$C_{oss}$',color=color,width=1.04,height=.54)
            _cell(ax,x,1.7,'$C_{oss}$',color=color,width=1.04,height=.54)
            _node(ax,x,2.7,'$v_a$' if i==0 else '$v_b$',color=color,offset=(-.34,0))
            _flow(ax,(x+.32,2.5 if i==0 else 3.0),(x+.32,3.0 if i==0 else 2.5),color)
        ax.text(2.55,.34,'量单节点' if ax==left else '量 $v_a-v_b$',ha='center',color=TEAL)
    return fig


def llc_hhc_threshold():
    p,r=_llc()
    t=r['time_s']
    period=.5/r['frequency_Hz']
    mask=t<=period*(1+1e-7)
    t=t[mask]
    td=p['llc_dead_time']
    k=p['llc_hhc_sense']
    slope=p['llc_hhc_ramp']
    v_sample=k*r['v_res_V'][mask]
    ramp=slope*np.maximum(0,t-td)
    fig,axes=_stack(('(a)  比较量的两部分','(b)  比较量首次达到触发阈值'))
    _trace(axes[0],t*1e6,v_sample,ylabel='比较量分量 / V',label='谐振电容取样')
    axes[0].plot(t*1e6,ramp,color=ORANGE,label='附加斜坡')
    axes[0].legend(loc='upper left')
    _trace(axes[1],t*1e6,v_sample+ramp,'半周期内的时间 / µs','合成比较量 / V',ink=TEAL)
    axes[1].axhline(r['hhc_threshold_V'],color=ORANGE,ls='--',label='比较阈值')
    axes[1].legend(loc='lower right')
    for ax in axes:
        ax.axvline(td*1e6,color=MUTED,ls=':')
        ax.set_xlim(0,period*1e6)
    return fig


def llc_inductance_split():
    fig,(left,right)=_pair(('(a)  同一总谐振电感的分配','(b)  独立磁件整匝校验'))
    left.barh([0],[39],color=BLUE,height=.43)
    left.barh([0],[11],left=39,color=TEAL,height=.43)
    left.text(19.5,0,'外置 39 µH',ha='center',va='center',color='white')
    left.text(44.5,.35,'漏感 11 µH',ha='center',color=TEAL,fontsize=8.5)
    left.set(yticks=[],ylim=(-.65,.8),xlim=(0,55),xlabel='串联电感 / µH')
    turns=np.arange(6,13)
    peak_flux=39e-6*4.2/(turns*85e-6)
    right.plot(turns,peak_flux,'o-',color=BLUE)
    right.axhline(.22,color=ORANGE,ls=':',label='假定磁通上限')
    right.plot([9],[peak_flux[3]],'o',color=TEAL,ms=6)
    right.set(xticks=turns,xlabel='整匝数',ylabel='峰值磁通密度 / T',ylim=(.14,.35))
    right.legend(loc='upper right')
    return fig


def sizing_buck_envelope():
    fig,(left,right)=_pair(('(a)  高线抬高电感充磁伏秒','(b)  同一标准电感跨端点复算'))
    v=np.linspace(8,16,300)
    f=400e3
    ripple=5*(1-5/v)/(15e-6*f)
    _trace(left,v,5*(1-5/v)/(.6*f)*1e6,'母线电压 / V','电感下限 / µH')
    left.axhline(15,color=TEAL,ls='--',label='选定 15 µH')
    left.legend(loc='lower right')
    _trace(right,v,ripple,'母线电压 / V','电流峰峰值 / A')
    right.axhline(.6,color=ORANGE,ls=':',label='目标 0.60 A')
    right.legend(loc='lower right')
    for ax in (left,right):
        ax.set(xlim=(8,16),xticks=[8,10,12,14,16])
    left.set_ylim(6,16)
    right.set_ylim(.25,.66)
    return fig


def sizing_boost_budget():
    fig,(left,right)=_pair(('(a)  连续模式充磁电压约束',
                            '(b)  用低线输入电流作峰值预算'))
    v=np.linspace(8,18,300)
    d=1-.9*v/24
    _trace(left,v,d,'母线电压 / V','估算占空比',ink=TEAL)
    for x in [8,24/1.8,18]:
        left.plot(x,1-.9*x/24,'o',color=ORANGE,ms=4)
    p=24
    avg=p/(.9*v)
    ripple=v*d/(100e3*27e-6)
    right.fill_between(v,avg-ripple/2,avg+ripple/2,color=BLUE_FILL,label='峰、谷范围')
    _trace(right,v,avg,'母线电压 / V','连续模式电感电流 / A',label='平均电流')
    right.legend(loc='upper right')
    for ax in (left,right):
        ax.set(xlim=(8,18),xticks=[8,10,12,14,16,18])
    left.set_ylim(.22,.77)
    right.set_ylim(0,4.87)
    return fig


def sizing_flyback_tradeoff():
    fig,(left,right)=_pair(('(a)  低线分给退磁的时间缩短','(b)  应力和匝比一起变化'))
    z=np.linspace(.01,.29,300)
    vr=24*.40/(1-.40-z)
    _trace(left,z,vr,'保留的驻留占比','原边反射电压 / V')
    left.plot(.15,24*.40/.45,'o',color=ORANGE,ms=5)
    left.set(ylim=(10,35))
    _trace(right,vr,42+vr,'原边反射电压 / V','高线漏极平台 / V',ink=ORANGE)
    right.plot(24*.40/.45,42+24*.40/.45,'o',color=TEAL,ms=5)
    right.set(ylim=(55,76))
    return fig


def sizing_flyback_turns():
    fig,(left,right)=_pair(('(a)  实际整数匝决定每个绕组的匝数','(b)  按实际原边匝数回算磁通密度'))
    candidates=np.array([1,2,3])
    for value,label,ink,offset in [(6,'P',BLUE,-.255),(12,'S1',TEAL,-.085),
                                   (5,'S2',ORANGE,.085),(2,'S3',MUTED,.255)]:
        left.bar(candidates+offset,value*candidates,width=.165,color=ink,label=label)
    left.set(xticks=candidates,xlabel='整数倍 m',ylabel='各绕组匝数')
    left.legend(loc='upper left',ncols=2)
    for m in candidates:
        val=8e-6*5.9/(6*m*42e-6)
        right.bar(m,val,width=.48,color=BLUE if m==1 else TEAL)
        right.text(m,val+.004,f'{val:.3f}',ha='center',fontsize=8.5)
    right.axhline(.17,color=ORANGE,ls=':',label='假定磁通上限')
    right.set(xticks=candidates,xlabel='整数倍 m',ylabel='原边峰值磁通 / T',ylim=(0,.236))
    right.legend(loc='upper right')
    return fig


def sizing_llc_impedance():
    fig,(left,right)=_pair(('(a)  固定谐振频率时电感与电容联动','(b)  变更 Z₀ 会同时改写品质因数'))
    z=np.linspace(15,50,250)
    l=z/(2*np.pi*100e3)*1e6
    c=1/(z*2*np.pi*100e3)*1e9
    _trace(left,l,c,'总串联谐振电感 / µH','谐振电容 / nF',ink=BLUE)
    left.plot(50,1/(np.pi**2)*500,'o',color=ORANGE,ms=5)
    left.set(ylim=(27,115))
    _trace(right,z,z/99.60,'特性阻抗 / Ω','满载品质因数',ink=TEAL)
    right.plot(31.4159,31.4159/99.60,'o',color=ORANGE,ms=5)
    right.set(ylim=(.12,.54))
    return fig


FIGURES = {
    'buck_capacitor': (buck_capacitor, '从 Buck 电容电流的过零点量取电压纹波',
                       '正电流面积从 2.5 µs 积到 7.5 µs，正好对应理想电容从谷电压升到峰电压。'),
    'boost_paths': (boost_paths, 'Boost 两种开关状态下的电感与负载电流路径',
                    '开通时 D 反偏，负载由输出电容供电。关断后，从输入流出的电流经电感及 D 到达输出端。'),
    'boost_charge': (boost_charge, 'Boost 断续模式中流向输出的电荷',
                     '上下两幅图共用时间轴。下图只有电感从峰值降到零的一段，面积为 3.750 µC。'),
    'inverting_voltage': (inverting_voltage, '反相 Buck-Boost 的电位基准与两段能量交换',
                          '左图两条有色电位线间隔 24 V。右图蓝色面积从输入取电，橙色面积把电荷送到反相端。'),
    'buck_period_map': (buck_period_map, '从分段方程到断续 Buck 的周期轨迹',
                        '图中的电压是用冻结斜坡积分得到的电容增量。最后一段电感电流为零，电容电压仍下降。'),
    'flyback_path': (flyback_path, '理想反激在开通与关断时的两条电流路径',
                     '黑点标同名端。原边接通时原边电流从同名端流入，关断后副边电流从非同名端流出到负载。'),
    'flyback_current_ref': (flyback_current_ref, '反激的实际绕组电流与励磁折算电流',
                            '在 2 µs 处原边断开，副边以两倍电流接手。虚线退磁斜坡保留原边折算尺度。'),
    'qr_trajectory': (qr_trajectory, '准谐振反激退磁后的首个半周期',
                      '按线性有效电容计算。漏极从 420 V 经过 300 V 降到约 180 V，并在首谷处达到零斜率。'),
    'qr_valleys': (qr_valleys, '退磁后的谷点与控制器消隐的相对位置',
                   '示意中消隐还剩 2 µs，谷 1 落在消隐内，谷 2 是消隐后的第一个低点。'),
    'rcd_transition': (rcd_transition, '漏感首波瓣与 RCD 导通边界',
                       '自然超调达到 80 V 时，钳位回路接手。下图的面积仅含流过钳位管的阶段。'),
    'cross_nodes': (cross_nodes, '三路反激的电容端、负载端与反馈取样点',
                    '各路防反管前后电压相差一项管压降。闭环设定在 OUT1 电容端，负载和电压统计在各自端口。'),
    'cross_matrix': (cross_matrix, '三路反激的电感矩阵与短路接法',
                     '左图给出自感和互感，右图展示两种终端造成的原边增量漏感差异。'),
    'cross_event_conditions': (cross_event_conditions, '耦合绕组求解中的两类换流事件',
                               '左图在电流回零时移出导通集合。右图开路感应电压触及门槛时，按新的导通集合重算。'),
    'cross_charge_window': (cross_charge_window, 'X004 轻载 OUT2 的电荷窗口和两种平均电流',
                            '同一电荷按 63.777 ns 平均得到约 317 mA，按 4 µs 平均得到约 5.05 mA。'),
    'cross_energy': (cross_energy, 'X004 一个周期的端口能量与耗散',
                     '右图按 4 µs 将功率换算成能量，稳态储能元件从周期起点到终点的净变化为零。'),
    'cross_corner_span': (cross_corner_span, 'OUT2 纯交叉跨度和全角点跨度',
                          '两图沿用同一参考电压和横坐标。扩大工况范围后，下限从 X008 改为 X014。'),
    'forward_paths': (forward_paths, '正激导通传能与复位续流的独立路径',
                       '关断后原边由钳位支路复位，输出电感通过续流管延续原来的电流方向。'),
    'forward_clamp_cap': (forward_clamp_cap, '钳位电容复位阶段的充电与放电',
                           '按小纹波近似，两块电流面积相消。电压到复位中点取得最大增量。'),
    'forward_main_current': (forward_main_current, '正激输出电感和主开关的电流',
                              '换算到原边的负载电流需叠加有正有负的励磁电流。主开关关断，输出电感仍继续续流。'),
    'forward_step': (forward_step, '正激周期求解的门极窗口和边沿局部网格',
                     '窄死区的连接关系单独更新。此图只示意时序与观察范围。'),
    'cot_gates': (cot_gates, '四相交错 COT 的开通窗口',
                   '每相周期为 2 µs，脉宽 0.2 µs，起点依次错开 0.5 µs。浅色区间表示该相上管关断。'),
    'cot_cancellation': (cot_cancellation, '四相占空比扫描中的纹波抵消',
                           '总纹波在四分之一、二分之一和四分之三处为零，同时单相电流仍有显著摆幅。'),
    'cot_balance': (cot_balance, '导通电阻失配和采样偏置引起的平均电流偏差',
                     '两例总电流均为 10 A，左图固定相同驱动，右图为强均流下相同采样读数的极限。'),
    'cot_step_charge': (cot_step_charge, '负载突增的矩形和三角形亏电面积',
                         '电容先补 3.2 µC 的延迟电荷，随后在电感电流追赶阶段再补 2.0 µC。'),
    'llc_fundamental': (llc_fundamental, 'LLC 桥压基波与分压相量',
                         '左图方波与基波的峰值有别。右图在 120 kHz 以实、虚部相加得到腔体输入阻抗，串联电阻取零。'),
    'llc_gain_regions': (llc_gain_regions, '固定谐振腔的满载与轻载基波增益',
                          '低频峰均落在 65 kHz 下限以外。理想无串联损耗时，两条曲线在 Lr 与 Cr 电抗相抵的 100 kHz 处都接近 1。'),
    'llc_current_split': (llc_current_split, '360 V 满载 LLC 周期解的谐振、励磁和整流电流',
                           '整流电流来自谐振电流和励磁电流的差值，关断极性反转后整流电流仍取正。'),
    'llc_state_loop': (llc_state_loop, 'LLC 的半周状态对称性与交流储能',
                        '两处半周起点在中心化的坐标中关于原点对称。右图显示腔体串联元件的能量，采用同一周期解。'),
    'llc_bridge_capacitors': (llc_bridge_capacitors, 'LLC 半桥与全桥的换流电容坐标',
                                '半桥量单节点，全桥量两节点电压差。全桥两只节点各走一份母线电压，差模电压走两份。'),
    'llc_hhc_threshold': (llc_hhc_threshold, '实际周期解的 HHC 比较信号和阈值',
                           '死区内斜坡为零，之后采样电压和附加斜坡一同进入比较器。首次有效上穿决定下一次关断。'),
    'llc_inductance_split': (llc_inductance_split, 'LLC 总串联感量的分配与独立谐振电感整匝',
                              '示意设计中变压器漏感承担 11 µH，外置磁件承担 39 µH。按给定磁通限值，8 匝以上才满足磁通预算，最小整数为 9 匝。'),
    'sizing_buck_envelope': (sizing_buck_envelope, 'Buck 初选电感下限与固定件跨端点的纹波',
                              '左图从 0.6 A 纹波预算求电感下限，右图反向代入 15 µH 标准值。'),
    'sizing_boost_budget': (sizing_boost_budget, 'Boost 占空比及电流预算在两个输入端点之间的变化',
                             '图中负载 24 W，电感 27 µH。纹波的最大点落在中间，包络中最高峰值仍靠近低线。'),
    'sizing_flyback_tradeoff': (sizing_flyback_tradeoff, '反激驻留时间、反射电压与漏极平台的联动',
                                 '低线 24 V、占空比固定 0.40。为驻留留下更多时间时，较短的退磁窗需要更高的反射电压。'),
    'sizing_flyback_turns': (sizing_flyback_turns, '反激整数匝方案与峰值磁通初筛',
                              '在固定感量、峰值电流和截面积的磁预算下提高匝数，可降低峰值磁通。气隙及窗口占用须按候选匝数更新。'),
    'sizing_llc_impedance': (sizing_llc_impedance, 'LLC 的定频率等值曲线及品质因数',
                              '图中固定串联谐振频率 100 kHz 和额定 Rac。圆点标出 50 µH 与约 50.66 nF 的设计点。'),
}
