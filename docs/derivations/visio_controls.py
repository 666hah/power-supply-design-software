"""Electrical signal chains for the controller models described in the book."""

from .visio_circuit import BLUE, INK, MUTED, ORANGE, TEAL, Circuit


def block(c, x, y, label, w=1.65, color=BLUE):
    from matplotlib.patches import Rectangle
    c.ax.add_patch(Rectangle((x-w/2,y-.34),w,.68,ec=color,fc='#edf5fb',lw=1.24))
    c.text(x,y,label,color=color,fontsize=8.8)
    return (x-w/2,y),(x+w/2,y)


def gate(c, start, end, label='门极驱动'):
    middle=(start[0]+end[0])/2
    a,b=block(c,middle,start[1],label,w=min(1.75,end[0]-start[0]-.32),color=TEAL)
    c.wire(start,a,color=TEAL)
    c.wire(b,(end[0],b[1]),end,color=TEAL)
    c.terminal(*end,label='G−S',dy=.31)


def pwm(current=False):
    c=Circuit(ylim=(0,6.3),height=3.55)
    x,y=9.45,2.85
    s,r,q=c.latch(x,y,'周期锁存')
    c.terminal(7.70,s[1]+1.10,'时钟置位')
    c.wire((7.70,s[1]+1.10),(7.70,s[1]),s,color=BLUE)
    c.text(.85,5.38,'输出取样',color=BLUE)
    c.terminal(1.0,4.69,'Vout')
    c.wire((1.0,4.69),(1.37,4.69))
    c.resistor((1.37,4.69),(1.37,3.70),'R上')
    c.resistor((1.37,3.70),(1.37,2.83),'R下')
    c.node(1.37,3.70); c.ground(1.37,2.83)
    eu,el,eo=c.amplifier(3.57,3.92,'误差放大器')
    c.wire((1.37,3.70),el,color=BLUE)
    c.terminal(2.54,eu[1],'Vref',dy=.37)
    c.wire((2.54,eu[1]),eu,color=BLUE)
    c.resistor((3.08,5.29),(4.08,5.29),'Rz')
    c.cap((4.08,5.29),(4.87,5.29),'Cz')
    c.wire(el,(3.03,5.29),(3.08,5.29))
    c.wire(eo,(4.87,eo[1]),(4.87,5.29))
    c.node(4.87,eo[1],'VC',dx=.1)
    pu,pl,po=c.amplifier(6.76,1.90,'峰流比较器' if current else 'PWM 比较器')
    c.wire((4.87,eo[1]),(5.60,eo[1]),(5.60,pl[1]),pl,color=BLUE)
    c.wire(po,(8.11,po[1]),(8.11,r[1]),r,color=ORANGE)
    if current:
        c.terminal(.95,pu[1], 'iQ · Rs',dx=-.12)
        a,b=block(c,2.64,pu[1],'增益与消隐',w=1.8,color=ORANGE)
        c.wire((.95,pu[1]),a,color=ORANGE)
        a2,b2=block(c,4.68,pu[1],'叠加补偿斜坡',w=1.89,color=ORANGE)
        c.wire(b,a2,color=ORANGE); c.wire(b2,pu,color=ORANGE)
    else:
        c.terminal(3.95,pu[1],'振荡器锯齿波')
        c.wire((3.95,pu[1]),pu,color=ORANGE)
    gate(c,q,(13.47,q[1]))
    c.text(9.93,.63,'比较器上穿后复位，结束本周期开通',color=MUTED)
    return c.fig


def qr_signal():
    c=Circuit(ylim=(0,6.2),height=3.45)
    s,r,q=c.latch(9.96,3.12,'周期锁存')
    z1,z2,zo=c.amplifier(4.4,4.54,'ZCD 滞回比较',upper='−',lower='+')
    c.terminal(.43,z1[1],'辅助绕组')
    c.resistor((.43,z1[1]),(2.27,z1[1]),'Rz')
    c.node(2.27,z1[1]); c.cap((2.27,z1[1]),(2.27,3.45),'Cz')
    c.ground(2.27,3.45)
    c.wire((2.27,z1[1]),z1,color=BLUE)
    c.terminal(3.15,z2[1],'触发阈值',dx=.28,dy=-.42)
    c.wire((3.15,z2[1]),z2,color=BLUE)
    a,b=block(c,6.72,zo[1],'窗口与谷底延时',w=2.39,color=TEAL)
    c.wire(zo,a,color=TEAL); c.wire(b,(8.73,b[1]),(8.73,s[1]),s,color=TEAL)
    cu,cl,co=c.amplifier(4.4,1.94,'CS 比较')
    c.terminal(.72,cu[1],'CS')
    c.resistor((.72,cu[1]),(2.30,cu[1]),'Rcs 滤波')
    c.node(2.30,cu[1]); c.cap((2.30,cu[1]),(2.30,.95),'Ccs')
    c.ground(2.30,.95)
    c.wire((2.30,cu[1]),cu,color=ORANGE)
    c.terminal(3.15,cl[1],'限流命令',dx=.28,dy=-.42)
    c.wire((3.15,cl[1]),cl,color=ORANGE)
    a,b=block(c,6.72,co[1],'消隐与导通上限',w=2.39,color=ORANGE)
    c.wire(co,a,color=ORANGE); c.wire(b,(8.74,b[1]),(8.74,r[1]),r,color=ORANGE)
    gate(c,q,(13.46,q[1]))
    c.text(7.7,.61,'启动时由启动定时器提供首次置位',color=MUTED)
    return c.fig


def acf_drive():
    c=Circuit(ylim=(0,6.1),height=2.95)
    c.terminal(.55,3.12,'PWM')
    a,b=block(c,2.5,3.12,'互锁与死区',w=2.2)
    c.wire((.55,3.12),a,color=BLUE)
    for y,lab,label,aux in ((4.48,'主驱动','Q主',False),(1.81,'钳位反相驱动','Q钳',True)):
        a1,b1=block(c,6.06,y,lab,color=TEAL)
        c.wire(b,(4.45,3.12),(4.45,y),a1,color=TEAL)
        c.wire(b1,(11.25,y),color=TEAL)
        c.terminal(8.48,y,'VGS')
        d,s=(11.75,y+.55),(11.75,y-.55)
        c.mos(s if aux else d,d if aux else s,label=label,p_channel=aux)
    c.node(4.45,3.12)
    c.text(7.1,.57,'进入换流间隔时两个门极均撤去。栅源电压分别以本管源极为参考。',color=MUTED)
    return c.fig


def cot_signal():
    c=Circuit(ylim=(0,6.4),height=3.5)
    eu,el,eo=c.amplifier(3.36,4.52,'电压误差')
    c.terminal(.78,eu[1],'Vset')
    c.wire((.78,eu[1]),eu,color=BLUE)
    c.terminal(.78,el[1],'VFB',dy=-.37)
    c.wire((.78,el[1]),el,color=BLUE)
    a,b=block(c,5.27,eo[1],'PI → 触发频率',w=1.85)
    c.wire(eo,a,color=BLUE)
    a2,b2=block(c,7.75,eo[1],'按相位分发',w=1.85)
    c.wire(b,a2,color=BLUE)
    for y,index in ((4.00,1),(2.06,2)):
        a,b=block(c,10.03,y,f'单稳态 {index}',w=1.75,color=TEAL)
        c.wire(b2,(8.78,b2[1]),(8.78,y),a,color=TEAL)
        c.wire(b,(12.15,y),color=TEAL)
        c.terminal(12.15,y,f'VGS{index}')
    u,l,o=c.amplifier(3.48,1.58,'均流差值')
    for pos,label in ((u,'活动相均值'),(l,'本相电流采样')):
        c.terminal(.78,pos[1],label,dy=-.36 if pos==l else .30)
        c.wire((.78,pos[1]),pos,color=ORANGE)
    a,b=block(c,6.42,1.58,'导通时间修正',w=2.0,color=ORANGE)
    c.wire(o,a,color=ORANGE)
    c.wire(b,(9.98,1.58),(9.98,1.71),color=ORANGE)
    c.text(7.10,.60,'每相按自己的平均电流误差修正。下方示其对相 2 的路径。',color=MUTED)
    return c.fig


def psr_signal():
    c=Circuit(ylim=(0,6.05),height=3.27)
    c.coil((1.25,4.72),(1.25,1.05))
    c.node(1.44,4.06)
    c.text(.65,2.93,'Naux',color=BLUE)
    c.ground(1.25,1.05)
    c.wire((1.25,4.72),(3.18,4.72))
    c.resistor((3.18,4.72),(3.18,3.02),'Rt')
    c.resistor((3.18,3.02),(3.18,1.05),'Rb')
    c.ground(3.18,1.05)
    c.node(3.18,3.02,'Vaux 分压',dx=.42,dy=.36)
    c.wire((3.18,3.02),(5.25,3.02))
    c.switch((5.25,3.02),(6.87,3.02),'采样开关')
    c.arrow((6.05,4.28),(6.05,3.44),color=TEAL)
    c.text(6.05,4.54,'退磁阶段有效采样窗',color=TEAL)
    c.wire((6.87,3.02),(8.0,3.02))
    c.cap((8.0,3.02),(8.0,1.05),'Ch')
    c.node(8.0,3.02); c.ground(8.0,1.05)
    vu,vl,vo=c.amplifier(10.55,3.24,'保持值与基准比较')
    c.wire((8.0,3.02),vl,color=BLUE)
    c.terminal(8.86,vu[1],'Vref')
    c.wire((8.86,vu[1]),vu,color=BLUE)
    c.wire(vo,(13.25,vo[1]),color=BLUE)
    c.terminal(13.25,vo[1],'补偿命令')
    c.text(7,.37,'电路表示取样与保持的等效过程，时序窗口按控制器模型读取。',color=MUTED)
    return c.fig


def ssr_opto():
    c=Circuit(ylim=(0,6.15),height=3.5)
    c.terminal(1.37,5.35,'Vout')
    c.wire((1.37,5.35),(5.59,5.35))
    c.resistor((1.37,5.35),(1.37,3.21),'Rt')
    c.resistor((1.37,3.21),(1.37,1.05),'Rb')
    c.ground(1.37,1.05)
    c.node(1.37,3.21,'FB',dx=-.43)
    c.resistor((5.59,5.35),(5.59,4.02),'RLED')
    c.diode((5.59,4.02),(5.59,2.63),'LED')
    c.diode((5.59,1.05),(5.59,2.63))
    c.text(6.05,1.84,'TL431',ha='left',color=ORANGE)
    c.wire((5.38,2.14),(5.29,2.14),(5.29,2.27))
    c.ground(5.59,1.05)
    c.wire((1.37,3.21),(3.15,3.21),(3.15,1.84),(5.45,1.84),color=ORANGE)
    c.resistor((3.15,3.21),(3.15,4.45),'Rz')
    c.cap((3.15,4.45),(4.75,4.45),'Cz')
    c.wire((4.75,4.45),(4.75,2.63),(5.59,2.63))
    c.node(5.59,2.63); c.node(3.15,3.21)
    c.wire((7.32,.52),(7.32,5.72),ls='--',color=MUTED,lw=1.1)
    c.arrow((6.25,3.66),(8.19,3.22),color=TEAL)
    c.arrow((6.25,3.98),(8.19,3.54),color=TEAL)
    c.terminal(9.19,5.35,'原边偏置')
    c.resistor((9.19,5.35),(9.19,3.86),'Rpull')
    c.wire((9.19,3.86),(9.19,3.52),(8.86,3.12))
    c.wire((8.86,2.68),(9.19,2.35),(9.19,1.05))
    c.wire((8.86,2.50),(8.86,3.30))
    c.arrow((8.88,2.66),(9.13,2.43),color=INK)
    c.ground(9.19,1.05)
    c.wire((9.19,3.86),(12.50,3.86))
    c.cap((11.13,3.86),(11.13,1.05),'Co')
    c.node(11.13,3.86); c.node(9.19,3.86)
    c.ground(11.13,1.05)
    c.terminal(12.50,3.86,'COMP')
    return c.fig


FIGURES = {
    'ctl_voltage_pwm_symbols': (pwm, '电压模式 PWM 的比较器与锁存器',
        '时钟把 S 置位。斜坡超过误差放大器输出 VC 时，比较器触发 R，结束本周期开通。'),
    'ctl_pwm_signal_chain': (lambda: pwm(current=True), '峰值电流 PWM 的取样、比较与锁存',
        '橙色路径把采样电压、增益、消隐及补偿斜坡送入关断比较器。斜坡与命令在同一电压域。'),
    'ctl_qr_symbols': (qr_signal, '准谐振反激的 ZCD 置位与 CS 复位',
        '蓝色支路调理辅助绕组信号。下降沿通过预备、消隐与延时后置位。橙色支路按 CS 和最大导通时间复位。'),
    'ctl_acf_symbols': (acf_drive, '有源钳位正激的互锁与双门极驱动',
        '门极各自对源极测量。死区令两个通道暂时关断。主开关和钳位开关的功率连接见卷首。'),
    'ctl_cot_shared_signals': (cot_signal, '多相恒定导通时间控制的公共频率与单相修正',
        '上方是公共电压回路。橙色均流回路以活动相平均与本相采样之差修正各相。'),
    'ctl_psr_symbols': (psr_signal, '原边反馈的绕组分压与采样保持',
        '重新开通前，所用控制器在指定退磁窗口读取辅助绕组。保持电容用来解释采样信号的作用。'),
    'ctl_optocoupler_paths': (ssr_opto, 'TL431 与光耦反馈的隔离电路',
        '输出小信号可经 RLED 直接作用在 LED，也可经反馈分压、补偿网络和 TL431 间接改变 LED 电流。'),
}
