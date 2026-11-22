"""Teaching figures for ports, magnetic extraction, system budgets and verification."""

import numpy as np
from matplotlib.patches import Circle, Polygon, Rectangle

from docs.derivations.illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure, panel_label


def _port_diode(ax, x, y):
    ax.add_patch(Polygon([(x-.23, y-.19), (x+.16, y), (x-.23, y+.19)],
                         facecolor='white', edgecolor=INK, lw=1.6, zorder=3))
    ax.plot([x+.17, x+.17], [y-.20, y+.20], color=INK)


def voltage_ports():
    fig = figure(height=1.9)
    ax = fig.subplots()
    ax.set(xlim=(-.4, 11), ylim=(-.6, 1.9), aspect='equal')
    ax.axis('off')
    y = .69
    ax.plot([.3, 3.5], [y, y], color=INK)
    ax.plot([6.7, 10.5], [y, y], color=INK)
    ax.add_patch(Rectangle((3.5, .25), 3.2, .88, facecolor='#e8eff4', edgecolor=BLUE, lw=1.5))
    ax.text(5.1, y, '隔离功率级与次级整流', ha='center', va='center', color=BLUE)
    for x in (1.2, 8.45):
        _port_diode(ax, x, y)
    for x, value, label, color in ((.3,'20.0 V','输入端',BLUE), (2.6,'19.2 V','原边母线',BLUE),
                                   (7.25,'12.4 V','反馈电容端',TEAL), (10.25,'12.0 V','负载端',TEAL)):
        ax.plot(x, y, marker='o', markersize=4.2, color=color)
        ax.text(x, 1.33, value, color=color, ha='center', weight='bold')
        ax.text(x, -.01, label, color=color, ha='center', va='top')
    ax.text(1.23, .30, '0.8 V', va='top', ha='center', fontsize=8, color=ORANGE)
    ax.text(8.60, .30, '0.4 V', va='top', ha='center', fontsize=8, color=ORANGE)
    return fig


def flyback_ports():
    """Three separate secondary returns, each with its own capacitor and load."""
    fig = figure(height=2.65)
    ax = fig.subplots()
    ax.set(xlim=(-.15, 10.25), ylim=(-.08, 4.2), aspect='equal')
    ax.axis('off')
    def wire(x, y, color=INK):
        ax.plot(x, y, color=color, lw=1.35, solid_capstyle='round')

    def winding(x, top, bottom, side, count):
        pitch = (top-bottom)/count
        for j in range(count):
            phi = np.linspace(0, np.pi, 25)
            wire(x+side*.20*np.sin(phi), top-j*pitch-.5*pitch*(1-np.cos(phi)), BLUE)

    # Flyback polarity: dot at the positive primary supply and each secondary return.
    wire([.3,2.25,2.25],[3.3,3.3,2.95])
    winding(2.25,2.95,1.83,+1,5)
    wire([2.25,2.25],[1.83,1.49])
    wire([2.25,1.98],[1.49,1.04])
    ax.plot([2.25,2.25],[1.49,.91], 'o', color=INK, ms=2.6)
    wire([2.25,2.25,.3],[.91,.65,.65])
    ax.plot([.3,.3],[3.3,.65],'o',color=INK,ms=3)
    ax.add_patch(Circle((2.03,2.98),.055, color=INK))
    ax.text(.25,3.49,'输入母线',color=BLUE)
    ax.text(.25,.32,'原边回流端',color=MUTED)
    ax.text(1.45,1.18,'Q',ha='right',color=BLUE)
    for x in (2.65,2.77):
        wire([x,x],[.24,3.85],MUTED)
    for idx,(y,name,value) in enumerate(((3.55,'反馈路','30.00 V'),(2.17,'OUT2','13.38 V'),(.79,'OUT3','3.79 V'))):
        ret=y-.66
        winding(3.22,y,ret,-1,3)
        ax.add_patch(Circle((3.40,ret+.04),.046,color=INK))
        wire([3.22,8.09],[y,y]); wire([3.22,8.09],[ret,ret])
        _port_diode(ax,4.30,y); _port_diode(ax,6.34,y)
        mid=(y+ret)/2
        wire([5.3,5.3],[y,mid+.06]);wire([5.3,5.3],[mid-.06,ret])
        for yp in (mid-.06,mid+.06):
            wire([5.09,5.51],[yp,yp])
        ax.plot([5.3,5.3],[y,ret],'o',color=BLUE if idx==0 else INK,ms=2.9)
        wire([8.09,8.09],[y,mid+.18]);wire([8.09,8.09],[mid-.18,ret])
        ax.add_patch(Rectangle((7.99,mid-.18),.20,.36,facecolor='white',edgecolor=INK,lw=1.2))
        ax.text(8.46,mid+.12,name,ha='left',va='center',color=BLUE if idx==0 else INK,fontsize=9)
        ax.text(8.46,mid-.18,value,ha='left',va='center',color=TEAL,fontsize=8.5)
    for x,s in ((4.3,'整流'),(5.3,'电容'),(6.34,'防反'),(8.09,'负载')):
        ax.text(x,3.94,s,ha='center',color=MUTED,fontsize=8)
    return fig


def field_to_leakage():
    fig = figure(height=2.65)
    left, right = fig.subplots(1, 2, gridspec_kw={'width_ratios': [1, 1.2]})
    panel_label(left, '短接副边的增量测试')
    left.set(aspect='equal', xlim=(-.1, 4.6), ylim=(-.3, 3.7))
    left.axis('off')
    for x in (1.55, 2.55):
        side = 1 if x < 2 else -1
        left.plot([x-side*.95, x, x], [3.0, 3.0, 2.6], color=BLUE)
        left.plot([x, x, x-side*.95], [.68, .36, .36], color=BLUE)
        for j in range(4):
            theta = np.linspace(0, np.pi, 40)
            left.plot(x+side*.26*np.sin(theta), 2.6-j*.48-.24*(1-np.cos(theta)),
                      color=BLUE)
        left.add_patch(Circle((x-side*.16, 2.65), .065, color=INK))
    for x in (1.98, 2.12):
        left.plot([x, x], [.53, 2.76], color=MUTED, lw=1.3)
    left.plot([3.5, 3.5], [.36, 3.], color=ORANGE, lw=2)
    left.annotate('', xy=(3.51,.95), xytext=(3.51,2.05),
                  arrowprops={'arrowstyle':'->','color':ORANGE})
    left.annotate('', xy=(1.37,3.), xytext=(.62,3.),
                  arrowprops={'arrowstyle':'->','color':TEAL})
    left.text(.14, 1.65, '原边\n测量端', ha='left', va='center', color=TEAL)
    left.text(3.7, 1.65, '短路', color=ORANGE, va='center', ha='left')
    panel_label(right, '耦合变化怎样放大为漏感变化')
    k = np.linspace(.958, .998, 300)
    right.plot(k, 100*(1-k*k), color=BLUE)
    for kv, val, label, offset, color in ((.98,3.96,'原始 3.96 µH',(9,-2),BLUE),
                                         (np.sqrt(1-.04752),4.752,'加裕量 4.752 µH',(-5,19),ORANGE)):
        right.plot(kv,val,'o',color=color,ms=5)
        right.annotate(label,(kv,val),xytext=offset,textcoords='offset points',
                       color=color,fontsize=8,arrowprops={'arrowstyle':'-','color':color,'lw':.7})
    right.set(xlabel='耦合系数 k', ylabel='原边短路电感 / µH', xlim=(.958,1.0), ylim=(0,9))
    right.grid(axis='y', color='#dde4e8', lw=.6)
    return fig


def load_characteristics():
    fig = figure(height=2.7)
    ax=fig.subplots()
    v=np.linspace(5.5,13,200)
    for current, name, color, marker in ((v/12,'恒阻　12 Ω',BLUE,'s'),
                                         (np.ones_like(v),'恒流　1 A',TEAL,'o'),
                                         (12/v,'恒功率　12 W',ORANGE,'D')):
        ax.plot(v,current,label=name,color=color)
        i=np.interp(6,v,current)
        ax.plot(6,i,marker,color=color,ms=4)
        ax.annotate(f'{i:.1f} A',(6,i),xytext=(8,5),textcoords='offset points',color=color)
    ax.axvline(6,ls=':',color=MUTED,lw=1)
    ax.plot(12,1,'o',color=INK,ms=5)
    ax.annotate('额定点 12 V / 1 A',(12,1),xytext=(-28,-27),textcoords='offset points',
                arrowprops={'arrowstyle':'->','color':INK,'lw':.8},fontsize=8.5)
    ax.legend(loc='upper right',ncols=3)
    ax.set(xlabel='已使能负载的端电压 / V',ylabel='负载电流 / A',xlim=(5.4,13.2),ylim=(.25,2.55),
           xticks=[6,8,10,12])
    ax.grid(axis='y',color='#dde4e8',lw=.6)
    return fig


def tolerance_sample():
    fig=figure(height=2.65)
    ax=fig.subplots()
    u=np.linspace(0,1,401)
    uniform=90+20*u
    triangular=np.where(u<=.5,90+np.sqrt(200*u),110-np.sqrt(200*(1-u)))
    ax.plot(u,uniform,color=BLUE,label='均匀分布',ls='--')
    ax.plot(u,triangular,color=ORANGE,label='三角分布，众数 100 µH')
    for value, label, offset, color in ((105,'105.00 µH',(-79,15),BLUE),
                                        (110-np.sqrt(50),'102.93 µH',(12,-18),ORANGE)):
        ax.plot(.75,value,'o',color=color,ms=4.5)
        ax.annotate(label,(.75,value),xytext=offset,textcoords='offset points',color=color,
                    arrowprops={'arrowstyle':'-','color':color,'lw':.8})
    ax.axvline(.75,ymax=.74,color=MUTED,lw=1,ls=':')
    ax.set(xlabel='样机抽到的累计概率 u',ylabel='电感值 / µH',ylim=(88.5,111.5),
           xticks=[0,.25,.5,.75,1],yticks=[90,95,100,105,110])
    ax.legend(loc='upper left')
    ax.grid(axis='y',color='#dde4e8',lw=.6)
    return fig


def step_readout():
    fig=figure(height=3.05)
    load,voltage=fig.subplots(2,1,sharex=True,gridspec_kw={'height_ratios':[1,2]})
    load.step([-.4,0,2.6,4.2],[10,90,10,10],where='post',color=BLUE)
    load.set(ylabel='负载 / %',ylim=(-5,105),yticks=[10,90])
    t=[-.4,0,.10,.35,.7,1.0,1.2,1.5,2.,2.6,2.70,2.95,3.2,3.5,3.8,4.2]
    v=[12.03,12.03,11.53,11.70,11.86,11.72,11.81,11.98,12.01,12.01,12.39,12.29,12.15,12.07,12.03,12.03]
    voltage.axhspan(11.76,12.24,color='#e1efe8',label='12 V ±2%')
    voltage.plot(t,v,color=BLUE,marker='.',ms=4)
    for event in (0.,2.6):
        for ax in (voltage,load):
            ax.axvline(event,color=MUTED,lw=.9,ls=':')
    for tx,vy,label,offset in ((.10,11.53,'11.53 V',(10,0)),(2.70,12.39,'12.39 V',(8,0))):
        voltage.plot(tx,vy,'o',color=ORANGE,ms=4)
        voltage.annotate(label,(tx,vy),xytext=offset,textcoords='offset points',color=ORANGE,fontsize=8.5)
    voltage.set(xlim=(-.45,4.22),ylim=(11.39,12.51),yticks=[11.5,11.76,12,12.24,12.4],
                xlabel='相对首次加载的时间 / ms',ylabel='端口电压 / V')
    voltage.legend(loc='lower right')
    return fig


FIGURES={
    'voltage_ports': (voltage_ports, '输入连接器、内部母线、反馈电容端与负载端',
                      '两侧电压各自对本侧回流端测量。沿供电方向经过导通的防反二极管，电位降低。'),
    'field_leakage': (field_to_leakage, '副边短路时原边看到的电感',
                      '同名端由黑点标出。按图示原边电流正增量，副边感应电流从同名端流出。右图将原边自感固定在 100 µH。'),
    'load_types': (load_characteristics, '同一额定功率下三种负载的启动电流',
                   '先找三条线共用的额定点，再沿曲线向左读到 6 V。图中负载均已使能，输入电容的充电电流另计。'),
    'tolerance_sampling': (tolerance_sample, '从同一个随机分位读出两种电感样值',
                           '两种分布都落在 90 至 110 µH 之间。设 u 为 0.75，从虚线与两条曲线的交点读数。'),
    'step_readout': (step_readout, '在加载与卸载记录上读取偏差和恢复时间',
                     '上图给定跳变时刻，下图使用一组教学采样点及线性插值。浅绿色带为允许电压范围。'),
}
