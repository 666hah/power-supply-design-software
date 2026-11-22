"""Figures placed alongside the equations in chapters 1 and 15–18."""

from functools import partial
from math import erf

import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle

from .illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


def paper(height=4.18):
    return figure(7.1, height)


def line(ax, title, x, y, xlabel, ylabel, color=BLUE, **style):
    panel_label(ax, title)
    ax.plot(x, y, color=color, **style)
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.grid(alpha=.18)


def boxes(ax, blocks, paths, title='', *, short_panel=False):
    if title:
        panel_label(ax, title)
    ax.set(xlim=(0, 10), ylim=(0, 6))
    ax.axis('off')
    half_height = .8 if short_panel else .54
    for x, y, name, value, color in blocks:
        ax.add_patch(Rectangle((x-.94,y-half_height),1.88,2*half_height,fc=color+'15',ec=color,lw=1.35))
        ax.text(x,y+.34*half_height,name,color=color,ha='center',va='center',weight='bold',fontsize=9.5)
        ax.text(x,y-.42*half_height,value,ha='center',va='center',fontsize=8.3)
    for x0,y0,x1,y1,label in paths:
        ax.add_patch(FancyArrowPatch((x0,y0),(x1,y1),arrowstyle='-|>',mutation_scale=12,
                      color=MUTED,lw=1.2))
        if label:
            ax.text((x0+x1)/2,(y0+y1)/2+.15,label,ha='center',va='bottom',fontsize=8.4)


def input_budget():
    fig = paper()
    top, bottom = fig.subplots(2,1,gridspec_kw={'height_ratios':[1,1.12]})
    boxes(top, [(1.2,2.8,'输入端口','24 V · 37.5 W',BLUE),(5,2.8,'防反后母线','23.5 V · 36.72 W',TEAL),
                (8.8,2.8,'三个负载端','30 W 合计',ORANGE)],
          [(2.15,2.8,4.04,2.8,'防反管损耗'),(5.95,2.8,7.84,2.8,'功率级损耗')],
          '(a) 接在输入端的功率表覆盖整个变换器',short_panel=True)
    b=bottom.barh(['负载得到','功率级耗散','输入防反管'],[30,6.71875,.78125],
                  color=[BLUE,TEAL,ORANGE],height=.5)
    bottom.bar_label(b,labels=['30.00 W','6.72 W','0.78 W'],padding=5)
    bottom.set(xlim=(0,39),xlabel='每秒的平均能量 / W')
    panel_label(bottom,'(b) 用同一输入边界检查功率之和')
    return fig


def hardware_boundary():
    fig=paper()
    ax=fig.subplots()
    boxes(ax,[(5,5,'提出规格','同一输出要求',BLUE),(5,3.1,'冻结硬件','L、匝数、器件等',INK),
              (2.2,1.15,'低线复算','12 V',TEAL),(7.8,1.15,'高线复算','24 V',ORANGE)],
          [(5,4.45,5,3.67,''),(4.05,2.8,2.35,1.73,''),(5.95,2.8,7.65,1.73,'')],
          '两个工作点使用同一硬件')
    ax.text(5,.13,'分别从本工况更新占空比、纹波、应力与损耗',ha='center',color=MUTED)
    return fig


def signed_lc():
    fig=paper(4.45)
    ax,bx,cx=fig.subplots(3,1,sharex=True)
    t=np.linspace(0,4,801); on=5/3
    i=np.where(t<=on,0.70833+.35*t,1.291663-.25*(t-on))
    ax.step([0,on,4],[7,-5,-5],where='post',color=BLUE)
    ax.fill_between([0,on],0,7,color=BLUE,alpha=.15)
    ax.fill_between([on,4],-5,0,color=ORANGE,alpha=.15)
    ax.axhline(0,lw=.8,color=MUTED); ax.set(ylabel='电感电压 / V',ylim=(-7,9))
    panel_label(ax,'(a) 伏秒的正、负部分相消')
    bx.plot(t,i,color=TEAL); bx.axhline(1,ls='--',lw=.9,color=MUTED)
    bx.set(ylabel='电感电流 / A')
    panel_label(bx,'(b) 两段斜率分别为 +0.35 和 −0.25 A/µs')
    cx.plot(t,i-1,color=ORANGE); cx.axhline(0,lw=1,color=MUTED)
    cx.fill_between(t,0,i-1,where=i>1,color=BLUE,alpha=.2)
    cx.fill_between(t,0,i-1,where=i<1,color=ORANGE,alpha=.2)
    cx.set(xlabel='一个开关周期内的时间 / µs',ylabel='电容电流 / A')
    panel_label(cx,'(c) 电感电流减去近似为直流的负载电流')
    for a in (ax,bx,cx):
        a.axvline(on,ls=':',lw=1,color=MUTED)
    return fig


def charge_to_voltage():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.linspace(0,8,321); i=.5-.25*np.abs(t-4)
    q=np.r_[0,np.cumsum((i[1:]+i[:-1])*np.diff(t)/2)]
    line(ax,'(a) 流入电容的电流决定电荷增减',t,i,'','电流 / A')
    ax.fill_between(t,0,i,where=i>=0,color=TEAL,alpha=.16)
    ax.fill_between(t,0,i,where=i<0,color=ORANGE,alpha=.17)
    ax.axhline(0,color=MUTED,lw=.8)
    line(bx,'(b) 储能电压的极值出现在电流过零处',t,10*q,'时间 / µs',
         '储能电压增量 / mV',TEAL)
    for a in (ax,bx):
        for x in (2,6):
            a.axvline(x,color=MUTED,ls='--',lw=.85)
    return fig


def rms_split():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.r_[np.linspace(0,.4,101),.4,1]
    i=np.r_[np.linspace(1,3,101),0,0]
    line(ax,'(a) 原电流的面积除以周期得到平均值',t,i,'','电流 / A')
    line(bx,'(b) 将同一组电流先平方再积分',t,i*i,'归一化周期 t / T','电流平方 / A²',ORANGE)
    ax.fill_between(t,0,i,color=BLUE,alpha=.19)
    bx.fill_between(t,0,i*i,color=ORANGE,alpha=.19)
    ax.axhline(.8,ls='--',color=MUTED,lw=1,label='平均 0.800 A')
    bx.axhline(26/15,ls='--',color=MUTED,lw=1,label='均方 1.733 A²')
    ax.legend(); bx.legend()
    return fig


def rms_sign():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.array([0,.5,.5,1]); y=np.array([2,2,-2,-2])
    line(ax,'(a) 电流方向每半周期反转',t,y,'','电流 / A')
    ax.fill_between(t,0,y,where=y>0,color=TEAL,alpha=.15)
    ax.fill_between(t,0,y,where=y<0,color=ORANGE,alpha=.15)
    ax.axhline(0,lw=1,color=MUTED); ax.set(ylim=(-2.6,2.6))
    line(bx,'(b) 同一导体在两个方向上产生等量焦耳热',t,.05*y*y,
         '归一化周期 t / T','瞬时损耗 / W',ORANGE)
    bx.set(ylim=(0,.26))
    return fig


def field_jobs():
    fig=paper(4.5)
    top,bot=fig.subplots(1,2)
    boxes(top,[(2.0,4.8,'求解 P','P 通 1 A',BLUE),(2.0,3,'求解 S','S 通 1 A',TEAL),
               (2.0,1.2,'求解 A','A 通 1 A',ORANGE)],
          [(3.02,y,5.9,y,'保留 B、H') for y in (4.8,3,1.2)],
          '(a) 三次激励共享几何和网格')
    top.text(7.8,3,'按单元\n配对计算',ha='center',va='center',color=MUTED)
    data=np.array([[100,48,28],[48,25,14],[28,14,9]])
    bot.imshow(data,cmap='Blues',vmin=-12,vmax=120,aspect='equal')
    for (x,y),v in np.ndenumerate(data):
        bot.text(y,x,f'{v} µH',ha='center',va='center',color='white' if v==100 else INK)
    bot.set(xticks=range(3),xticklabels=['P','S','A'],yticks=range(3),yticklabels=['P','S','A'])
    panel_label(bot,'(b) 按体积累积贡献得到矩阵')
    return fig


def field_connection():
    fig=paper()
    ax,bx=fig.subplots(1,2)
    ax.axis('off')
    panel_label(ax,'(a) 两段串联后的电流约束')
    ax.set(xlim=(0,4),ylim=(0,6))
    for y,label in ((4.2,'线段 1'),(2.1,'线段 2')):
        ax.add_patch(Rectangle((1.2,y-.48),1.6,.96,fill=False,edgecolor=BLUE,lw=1.7))
        ax.add_patch(Circle((1.42,y+.22),.08,fc=BLUE))
        ax.text(2,y,label,ha='center',va='center')
    ax.plot([2,2],[2.58,3.72],color=MUTED)
    ax.annotate('端口电流 i',xy=(2,4.73),xytext=(2,5.65),ha='center',
                arrowprops={'arrowstyle':'->','color':BLUE})
    ax.text(2,.7,'同向串联时 i₁ = i₂ = i',ha='center',color=BLUE)
    vals=[22,11,43]
    b=bx.bar(['第一段自感','第二段自感','合计端口'],vals,color=[BLUE,TEAL,ORANGE],width=.56)
    bx.bar_label(b,labels=['22','11','43'],padding=5)
    bx.axhline(33,ls='--',color=MUTED,lw=1,label='两个自感相加')
    bx.set(ylabel='电感 / µH',ylim=(0,53)); bx.legend()
    panel_label(bx,'(b) 互感使端口超出自感之和')
    return fig


def shorts():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    tests=['两个副边开路','短接 S','短接 A','分别短接 S 与 A']
    values=[100,7.84,100-28**2/9,196/29]
    b=ax.bar(tests,values,color=BLUE,width=.52)
    ax.bar_label(b,labels=[f'{v:.2f}' for v in values],padding=4)
    ax.set(ylim=(0,122),ylabel='原边表读数 / µH')
    panel_label(ax,'(a) 原边测试线固定，仅改变副边边界')
    x=np.arange(4)
    bx.bar(x-.16,[0,-48/25,0,-40/29],width=.3,color=TEAL,label='S 电流')
    bx.bar(x+.16,[0,0,-28/9,-28/29],width=.3,color=ORANGE,label='A 电流')
    bx.set(xticks=x,xticklabels=tests,ylabel='每 1 A 原边交流增量 / A')
    bx.legend(loc='lower left'); panel_label(bx,'(b) 短路电流抵消原边磁链')
    return fig


def field_margin():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    k=np.linspace(.95,1,221); l=100*(1-k*k)
    line(ax,'(a) 自感冻结以后，漏感与耦合的关系',k,l,'两绕组耦合系数 k','原边漏感 / µH')
    for kv,label,col in ((.98,'场解',BLUE),(np.sqrt(1-.04752),'采用值',ORANGE)):
        ax.scatter([kv],[100*(1-kv*kv)],color=col,zorder=4,label=label)
    ax.legend()
    f=np.linspace(.9,1,180)
    line(bx,'(b) 对所有非对角项施加同一衰减权重',f,100*(1-(.98*f)**2),
         '非对角项的比例 a','原边漏感 / µH',ORANGE)
    bx.axhline(4.752,ls='--',color=MUTED,lw=1,label='回填目标 4.752 µH'); bx.legend()
    return fig


def field_checks():
    fig=paper()
    ax,bx=fig.subplots(1,2)
    h=np.array([.25,.5,1,1.5])
    line(ax,'(a) 固定空气域并细化网格',h,4+.8*h*h,'特征网格边长 / mm','短路电感 / µH',marker='o')
    ax.axhline(4,color=MUTED,ls=':',lw=1)
    air=np.array([1.5,2,3,4,6])
    line(bx,'(b) 固定细网格并扩大空气域',air,4+.32/air**2,
         '空气域边长 / 磁芯外宽','短路电感 / µH',TEAL,marker='o')
    bx.axhline(4,color=MUTED,ls=':',lw=1)
    return fig


def ldo_routes():
    fig=paper()
    ax=fig.subplots()
    boxes(ax,[(1.2,4.45,'输入端','5.0 V',BLUE),(5,4.45,'调整管','压降 1.7 V',ORANGE),
              (8.8,4.45,'输出端','3.3 V',TEAL),(1.2,1.5,'芯片静态支路','50 µA',BLUE),
              (5,1.5,'芯片热流','0.340 W',ORANGE),(8.8,1.5,'下游支路','0.200 A',TEAL)],
          [(2.16,4.45,4.04,4.45,'通过电流'),(5.96,4.45,7.84,4.45,'通过电流'),
           (1.2,3.9,1.2,2.05,''),(5,3.9,5,2.05,''),(8.8,3.9,8.8,2.05,'')],
          '调整管电流走向和耗散位置')
    return fig


def or_routes():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    for a,secondary in ((ax,True),(bx,False)):
        active=BLUE if secondary else ORANGE
        boxes(a,[(1.23,4.4,'电源 B','24.5 V' if secondary else '掉电',BLUE),
                 (1.23,1.55,'电源 A','24.0 V',ORANGE),
                 (5.05,3.0,'公共母线','24.0 V' if secondary else '23.7 V',active),
                 (8.85,3.0,'负载','24 W',TEAL)],
              [(2.2,4.4,4.1,3.3,'0.5 V' if secondary else '关断'),
               (2.2,1.55,4.1,2.7,'截止' if secondary else '0.3 V'),
               (6.02,3,7.88,3,'1.000 A' if secondary else '1.013 A')],
              '(a) 两个输入均可用' if secondary else '(b) 电源 B 掉电后',
              short_panel=True)
    return fig


def start_intervals():
    fig=paper(4.5)
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.linspace(0,6,901); v0=np.minimum(12,3*t)
    v=np.minimum(12,np.where(t<2,3*t,6+2.25*(t-2)))
    line(ax,'(a) 电压跨过后级使能门限后，斜率可能变小',t,v,'','母线 / V')
    ax.plot(t,v0,color=MUTED,ls='--',label='计划斜率'); ax.legend(loc='lower right')
    demand=np.where(t<2,.95,np.where(t<4,1.25,.65))
    actual=np.where(t<2,.95,np.where(t<14/3,1.10,.65))
    line(bx,'(b) 区分电流需求与电源可实际供出的电流',t,actual,
         '从软启动开始起算 / ms','电流 / A',TEAL,label='实际源电流')
    bx.plot(t,demand,color=ORANGE,ls='--',label='按原计划推得的需求')
    bx.legend(loc='lower left')
    for a in (ax,bx):
        a.axvline(2,ls=':',color=MUTED,lw=1)
        a.axvline(14/3,ls=':',color=MUTED,lw=1)
    return fig


def hiccup_clock():
    fig=paper(4.2)
    ax,bx,cx=fig.subplots(3,1,sharex=True)
    t=np.array([0,1,2.2,4.2,6])
    ax.step(t,[.8,1.3,0,.8,.8],where='post',color=BLUE); ax.axhline(1,ls='--',color=MUTED,lw=1)
    panel_label(ax,'(a) 过流需求跨过门限'); ax.set(ylabel='需求 / A',ylim=(-.12,1.65))
    bx.plot([0,1,2.2,2.2,6],[0,0,1.2,0,0],color=ORANGE)
    panel_label(bx,'(b) 连续计时达到 1.2 ms'); bx.set(ylabel='计时 / ms',ylim=(-.1,1.55))
    cx.step(t,[1,1,0,1,1],where='post',color=TEAL)
    panel_label(cx,'(c) 关断 2 ms 后允许重新软启动')
    cx.set(xlabel='启动实验的时间 / ms',ylabel='使能状态',yticks=[0,1],ylim=(-.18,1.25))
    return fig


def worst_surfaces():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    v=np.linspace(12,36,161)
    for l,c in [(16,ORANGE),(20,BLUE),(24,TEAL)]:
        ripple=20/l*(1-5/v)
        ax.plot(v,ripple,color=c,label=f'{l} µH')
        bx.plot(v,1.0+.5*ripple,color=c,label=f'{l} µH')
    ax.legend(ncol=3); ax.set(ylabel='峰峰纹波 / A')
    bx.set(xlabel='输入电压 / V',ylabel='峰值电流 / A')
    panel_label(ax,'(a) 每条曲线代表一块硬件的扫输入结果')
    panel_label(bx,'(b) 固定输出电流为 1 A 时的器件峰值')
    for a in (ax,bx): a.grid(alpha=.18)
    return fig


def paired_sampling():
    fig=paper()
    ax,bx=fig.subplots(1,2,sharex=True,sharey=True)
    rng=np.random.default_rng(346)
    u,v=rng.uniform(-1,1,size=(2,55))
    for a,y,name in ((ax,v,'(a) 独立抽样'),(bx,u,'(b) 共用同一分位')):
        a.scatter(u,y,s=17,alpha=.72,color=BLUE)
        a.axhline(0,color=MUTED,lw=.7); a.axvline(0,color=MUTED,lw=.7)
        a.set(xlabel='Rₐ 偏差 / %',xlim=(-1.15,1.15),ylim=(-1.15,1.15),aspect='equal')
        panel_label(a,name)
    ax.set_ylabel('Rᵦ 偏差 / %')
    return fig


def four_sigma():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    x=np.linspace(-5,5,601)
    p=np.exp(-x*x/2)/np.sqrt(2*np.pi)
    line(ax,'(a) 标准正态分布中的两侧尾区',x,p,'标准差单位 z','概率密度')
    ax.fill_between(x,p,where=np.abs(x)>4,color=ORANGE,alpha=.55)
    for lim in (-4,4): ax.axvline(lim,color=ORANGE,ls=':',lw=1)
    n=np.geomspace(100,1e6,221); q=(1-erf(4/np.sqrt(2)))/2
    line(bx,'(b) 实际样本数决定能看见多少尾部点',n,n*q,
         '成功求解的样本数','单侧期望点数',ORANGE)
    bx.set(xscale='log',yscale='log')
    bx.axhline(20,ls='--',color=MUTED,lw=1,label='20 个期望尾部样本'); bx.legend()
    return fig


def efficiency_interpolate():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    f=np.array([80,100,120,140,160]); eta=np.array([88.8,90,92,92.4,91.5])
    line(ax,'(a) 扫描时记录所有有效点和目标交点',f,eta,'开关频率 / kHz',
         '效率 / %',marker='o')
    ax.axhline(91,ls='--',color=MUTED,lw=.9)
    line(bx,'(b) 放大夹住目标的两个采样点',[100,120],[90,92],
         '开关频率 / kHz','割线估计 / %',TEAL,marker='o')
    bx.axhline(91,ls='--',color=MUTED,lw=.9)
    bx.axvline(110,ls='--',color=ORANGE,lw=.9,label='110 kHz 候选点'); bx.legend()
    return fig


def device_voltage():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.array([0,1,1,2.5,2.5,4])
    vd=24*np.ones_like(t); vs=np.array([0,0,24,24,0,0])
    line(ax,'(a) 先读漏极与源极相对同一参考点的电压',t,vd,'','节点电压 / V',
         label='漏极对地')
    ax.plot(t,vs,color=ORANGE,label='源极对地'); ax.set(ylim=(-2,28)); ax.legend(loc='center right')
    line(bx,'(b) 逐点作差后才得到高侧 MOS 的 VDS',t,vd-vs,
         '开关周期内的时间 / µs','漏源电压 / V',TEAL)
    bx.set(ylim=(-2,28))
    return fig


def windows():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.linspace(0,12,1501)
    env=np.minimum(1,t/5)
    v=12*env+.04*env*np.sin(2*np.pi*t*4)
    i=np.maximum(0,1-t/5)+.22*env*np.sin(2*np.pi*t*4)
    line(ax,'(a) 启动测试观察轨迹和电压极值',t,v,'','输出电压 / V')
    line(bx,'(b) 热纹波在收敛后的整周期窗统计',t,i,'启动后的时间 / ms','电容电流 / A',ORANGE)
    for a in (ax,bx):
        a.axvspan(0,5,color=ORANGE,alpha=.12,label='上电窗口')
        a.axvspan(8,11,color=TEAL,alpha=.17,label='稳态纹波窗口')
        a.legend(loc='upper right',ncol=2)
    return fig


def startup_readout():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    t=np.array([0,.3,.8,1.8,2.6,3.5,5.]); v=np.array([0,.3,2.3,8.,11.2,12,12])
    line(ax,'(a) 选取目标电压后读首次过阈值',t,v,'时间 / ms','输出端 / V',marker='o')
    for lim in (1.2,10.8): ax.axhline(lim,color=MUTED,ls='--',lw=.9)
    ax.set(ylim=(-.2,13.65))
    line(bx,'(b) 放大 90% 附近的两个采样点',t[3:5],v[3:5],
         '时间 / ms','输出端 / V',TEAL,marker='o')
    bx.axhline(10.8,color=MUTED,ls='--',lw=.9,label='10.8 V')
    bx.axvline(2.5,color=ORANGE,ls='--',lw=.9,label='插值 2.50 ms'); bx.legend()
    return fig


def bidirectional():
    fig=paper(4.5)
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.linspace(0,10,1001); a=np.maximum(0,t-2); b=np.maximum(0,t-6)
    v=12-.8*a*np.exp(-a/.5)/.5+.65*b*np.exp(-b/.65)/.65
    line(ax,'(a) 两次边沿之间保留稳定平台',t,np.where((t>=2)&(t<6),90,10),'','额定负载 / %')
    line(bx,'(b) 加载读下冲，卸载读上冲',t,v,'时间 / ms','负载端口 / V',ORANGE)
    bx.axhspan(11.88,12.12,color=TEAL,alpha=.16,label='12 V ±1%'); bx.legend()
    for a in (ax,bx):
        for time in (2,6): a.axvline(time,color=MUTED,ls=':',lw=1)
    return fig


def stress_limits():
    fig=paper()
    ax,bx=fig.subplots(2,1)
    words=['稳态钳位估计','启动原始峰值']
    b=ax.barh(words,[670,705],height=.5,color=[TEAL,ORANGE]); ax.bar_label(b,padding=4)
    ax.axvline(680,ls='--',lw=1,color=MUTED)
    ax.text(684,.5,'降额上限 680 V',color=MUTED,va='center')
    ax.set(xlim=(540,755),xlabel='MOS 漏源电压 / V')
    panel_label(ax,'(a) 两条证据使用不同的工况窗口')
    b=bx.barh(words,[10,-25],height=.5,color=[TEAL,ORANGE]); bx.bar_label(b,padding=4)
    bx.axvline(0,lw=1,color=MUTED); bx.set(xlim=(-34,24),xlabel='相对降额上限的余量 / V')
    panel_label(bx,'(b) 分别计算相对同一限值的有符号余量')
    return fig


def ccm_mode():
    fig=paper()
    ax,bx=fig.subplots(2,1,sharex=True)
    t=np.array([0,1,2,3,4])
    line(ax,'(a) 名义条件下始终保有正的谷值',t,[1.5,2.5,1.5,2.5,1.5],
         '','电感电流 / A')
    line(bx,'(b) 负载下降后出现真正的零电流区间',
         [0,1,1.7,2,3,3.7,4],[0,.7,0,0,.7,0,0],
         '时间 / µs','电感电流 / A',ORANGE)
    for a in (ax,bx): a.set(ylim=(-.14,2.8)); a.axhline(0,color=MUTED,lw=.8)
    bx.axvspan(1.7,2,color=TEAL,alpha=.2); bx.axvspan(3.7,4,color=TEAL,alpha=.2)
    return fig


FIGURES = {
    'base_input_budget': (input_budget, '从输入端口到负载端口的功率边界', '图中的 80% 指整个变换器的输入到输出效率。'),
    'base_same_hardware': (hardware_boundary, '同一套硬件的输入端点验证', '两只计算框接收相同的电感和器件，分别代入各自输入电压。'),
    'base_signed_lc': (signed_lc, '同一时间轴上的伏秒与电荷平衡', '12 V 转 5 V，20 µH，250 kHz。电容电流参考方向为流入正端。'),
    'base_charge': (charge_to_voltage, '对电容电流积分得到储能电压', '100 µF 理想电容。曲线的零点是周期开始时的电压，电荷先减、后增、最后减回原值。'),
    'base_rms_split': (rms_split, '导通斜坡和它的平方波形', '两个阴影分别用于平均电流和均方电流。'),
    'base_signed_rms': (rms_sign, '双向电流在导体上的发热', '所示导体的电阻为 50 mΩ，电流以同幅值往复。'),
    'verify_field_jobs': (field_jobs, '从分次通电到互感矩阵', 'P、S、A 分别指原边、主副边和辅助绕组，例值采用约定同名端。'),
    'verify_field_connection': (field_connection, '从分段自感、互感装配绕组端口', '图示两段自感 22、11 µH，同向互感 5 µH。'),
    'verify_shorts': (shorts, '三绕组变压器的四种开短路读数', '短接各绕组自己的两脚。下图以流入同名端为正。'),
    'verify_margin': (field_margin, '漏感裕量怎样改变采用的耦合系数', '两个自感保持 100 与 25 µH，系数作用在互感上。'),
    'verify_field_checks': (field_checks, '区分网格误差与开放边界误差', '纵轴为独立改变两项设置时的教学示意值。实际判断使用场提取结果。'),
    'verify_ldo': (ldo_routes, '固定输出 LDO 的电流和耗散位置', '静态支路由输入单独供电，固定输出算例忽略外部分压。'),
    'verify_or': (or_routes, '竞争电源的可用路径与掉电换路', '每个状态都按同一个 24 W 负载计算。'),
    'verify_start': (start_intervals, '启动期间由限流重新决定电容充电斜率', '6 V 时后级使能。末端两个平台分别在 4.00 ms 与 4.67 ms 达成。'),
    'verify_hiccup': (hiccup_clock, '把连续过流、计时和重试放在同一横轴', '阈值 1 A，确认延时 1.2 ms，关断时间 2 ms。三项为教学配置。'),
    'verify_worst': (worst_surfaces, '硬件容差与输入变化在同一组坐标上的关系', '理想 5 V Buck，250 kHz，1 A 连续导通。'),
    'verify_sampling': (paired_sampling, '同样的单件范围可以产生不同的组合分布', '每点表示一对反馈电阻。两幅图的单件边界相同。'),
    'verify_four_sigma': (four_sigma, '从正态概率密度到尾部样本数量', '上图尾部很小，下图把样本数和期望点数都改用对数坐标。'),
    'verify_efficiency': (efficiency_interpolate, '由两点插值选出一次复算的频率', '示意中的效率来自假设采样点，重复交点时须结合工程约束判断。'),
    'verify_vds': (device_voltage, '高侧开关要用漏极和源极两点的差', '理想 24 V Buck 的高侧器件。'),
    'verify_windows': (windows, '启动应力与稳态纹波使用各自的读数窗口', '下图斜下降的直流充电成分仅属于启动阶段。'),
    'verify_startup_read': (startup_readout, '从离散采样插值得到启机时间', '阈值由 12 V 目标乘 10% 和 90% 得出。'),
    'verify_bidir': (bidirectional, '在同一张图对齐加载和卸载的两个边沿', '蓝色给出负载指令，橙色是教学端口波形。容差带相对额定目标绘制。'),
    'verify_stress_limits': (stress_limits, '同一器件的不同应力量分别判断', '图中电压为教学数值，不同窗口的裕量分别保留。'),
    'verify_ccm': (ccm_mode, '按谷值和零区间判断连续或断续导通', '两种电流波形对照，采用相同时间尺度和平行电流刻度。'),
}
