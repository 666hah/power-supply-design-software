"""Electrical symbols and shared timing axes for the book's circuit drawings."""

import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle

from .illustrations import BLUE, INK, MUTED, ORANGE, TEAL, figure


class Circuit:
    def __init__(self, xlim=(0, 14), ylim=(0, 6), height=2.75):
        self.fig = figure(7.1, height)
        self.ax = self.fig.subplots()
        self.ax.set(xlim=xlim, ylim=ylim)
        self.ax.axis('off')

    def wire(self, *points, color=INK, ls='-', **style):
        x, y = zip(*points)
        self.ax.plot(x, y, color=color, ls=ls, lw=style.pop('lw', 1.45),
                     solid_capstyle='round', **style)

    def text(self, x, y, label, **style):
        props = dict(ha='center', va='center', fontsize=9.1, color=INK)
        props.update(style)
        self.ax.text(x, y, label, **props)

    def node(self, x, y, label=None, dx=0, dy=.28):
        self.ax.plot([x], [y], marker='o', markersize=3.7, color=BLUE, zorder=5)
        if label:
            self.text(x+dx, y+dy, label, color=BLUE)

    def terminal(self, x, y, label=None, dx=0, dy=.30):
        self.ax.plot([x], [y], marker='o', markersize=5, mec=BLUE, mfc='white', zorder=5)
        if label:
            self.text(x+dx,y+dy,label,color=BLUE)

    def ground(self, x, y):
        self.wire((x,y),(x,y-.19))
        for width, height in ((.38,.19),(.26,.28),(.13,.37)):
            self.wire((x-width/2,y-height),(x+width/2,y-height),lw=1.2)

    def arrow(self, start, end, label=None, color=TEAL):
        self.ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=11,
                                         linewidth=1.2, color=color))
        if label:
            x,y=(np.array(start)+np.array(end))/2
            self.text(x,y+.24,label,color=color)

    @staticmethod
    def _frame(start, end, flip=False):
        a,b=np.array(start,dtype=float),np.array(end,dtype=float)
        length=float(np.linalg.norm(b-a))
        if length <= 0:
            raise ValueError(f'重合的符号引脚 {start}')
        u=(b-a)/length
        normal=np.array([-u[1],u[0]])*(-1 if flip else 1)
        mid=(a+b)/2
        return length, normal, lambda x,y=0: tuple(mid+x*u+y*normal)

    def _sym_label(self, start, end, label, offset=.43):
        if label:
            a,b=np.asarray(start),np.asarray(end)
            x,y=(a+b)/2
            if abs(a[0]-b[0])>=abs(a[1]-b[1]):
                self.text(x,y+offset,label)
            else:
                self.text(x+offset,y,label,ha='left')

    def coil(self, start, end, label=None, flip=False):
        n,_,p=self._frame(start,end,flip)
        span=min(n*.73,2.1)
        radius=min(.23,span/6)
        self.wire(start,p(-span/2))
        for k in range(4):
            x=np.linspace(-span/2+k*span/4,-span/2+(k+1)*span/4,26)
            y=radius*np.sin(np.linspace(0,np.pi,26))
            self.wire(*(p(a,b) for a,b in zip(x,y)))
        self.wire(p(span/2),end)
        self._sym_label(start,end,label)

    def diode(self, anode, cathode, label=None):
        n,_,p=self._frame(anode,cathode)
        s=min(.31,n*.25)
        self.wire(anode,p(-s))
        self.ax.add_patch(Polygon([p(-s,-.20),p(-s,.20),p(s)],
                                  ec=INK,fc='white',lw=1.45,zorder=3))
        self.wire(p(s,-.22),p(s,.22))
        self.wire(p(s),cathode)
        self._sym_label(anode,cathode,label)

    def cap(self, start, end, label=None, plus=False):
        n,_,p=self._frame(start,end)
        gap=min(.10,n*.16)
        for x, outside in ((-gap,start),(gap,end)):
            self.wire(outside,p(x))
            self.wire(p(x,-.26),p(x,.26))
        if plus:
            self.text(*p(-gap-.18,.32),'+',color=BLUE)
        self._sym_label(start,end,label)

    def resistor(self, start, end, label=None):
        n,_,p=self._frame(start,end)
        s=min(.39,n*.32)
        self.wire(start,p(-s))
        self.ax.add_patch(Polygon([p(-s,-.18),p(-s,.18),p(s,.18),p(s,-.18)],
                                  ec=INK,fc='white',lw=1.45))
        self.wire(p(s),end)
        self._sym_label(start,end,label)

    def mos(self, drain, source, gate_label=None, label=None, *, p_channel=False):
        flip=drain[1]>source[1] or drain[0]<source[0]
        n,_,p=self._frame(drain,source,flip)
        s=min(.48,n*.28)
        self.wire(drain,p(-s),p(-s,-.04))
        self.wire(p(s,-.04),p(s),source)
        for x0,x1 in ((-s,-.36*s),(-.23*s,.23*s),(.36*s,s)):
            self.wire(p(x0,.03),p(x1,.03))
        self.wire(p(-s,.03),p(-s,-.04))
        self.wire(p(s,.03),p(s,-.04))
        # The body connects to source. Its arrow points inward for N-channel.
        self.wire(p(s,-.04),p(s,-.23),p(0,-.23),p(0,-.10),lw=1)
        arrow_tips = (p(0,.02),p(0,-.13)) if p_channel else (p(0,-.13),p(0,.02))
        self.ax.add_patch(FancyArrowPatch(*arrow_tips,arrowstyle='-|>',
                                         mutation_scale=7,color=INK,lw=.9))
        self.wire(p(-.75*s,.23),p(.78*s,.23))
        self.wire(p(0,.23),p(0,.53))
        if gate_label:
            pos=p(0,.67)
            self.text(*pos,gate_label,color=TEAL,fontsize=8.5)
        self._sym_label(drain,source,label)

    def switch(self, start, end, label=None):
        n,_,p=self._frame(start,end)
        s=min(.35,n*.28)
        self.wire(start,p(-s))
        self.wire(p(-s),p(s*.78,.28))
        self.wire(p(s),end)
        for point in (p(-s),p(s)):
            self.ax.plot(*point,'o',mec=INK,mfc='white',ms=3.4,zorder=5)
        self._sym_label(start,end,label)

    def source(self, top, bottom, label=None):
        n,_,p=self._frame(top,bottom)
        s=min(.37,n*.30)
        self.wire(top,p(-s))
        self.wire(p(s),bottom)
        x,y=zip(*(p(s*np.cos(a),s*np.sin(a)) for a in np.linspace(0,2*np.pi,72)))
        self.ax.plot(x,y,lw=1.45,color=INK)
        self.text(*p(-.48*s),'+',color=BLUE)
        self.text(*p(.55*s),'−',color=BLUE)
        self._sym_label(top,bottom,label,.53)

    def transformer(self, primary_top, primary_bottom, secondary_top, secondary_bottom,
                    label='T1', secondary_dot_top=True):
        self.coil(primary_top,primary_bottom,flip=True)
        self.coil(secondary_top,secondary_bottom)
        lx,rx=primary_top[0],secondary_top[0]
        yy=(primary_top[1]+primary_bottom[1])/2
        mid=(lx+rx)/2
        symbol_h=min(abs(primary_top[1]-primary_bottom[1])*.67,1.9)
        for line in (mid-.06,mid+.06):
            self.wire((line,yy-symbol_h/2),(line,yy+symbol_h/2),color=MUTED,lw=1)
        px=lx+.17 if rx>lx else lx-.17
        sx=rx-.17 if rx>lx else rx+.17
        self.node(px,yy+symbol_h/2+.14)
        self.node(sx,yy+(symbol_h/2+.14)*(1 if secondary_dot_top else -1))
        if label:
            self.text(mid,max(primary_top[1],secondary_top[1])+.30,label)

    def amplifier(self, x, y, label=None, upper='+', lower='−'):
        self.ax.add_patch(Polygon([(x-.54,y-.46),(x-.54,y+.46),(x+.56,y)],closed=True,
                                  ec=BLUE,fc='#ecf3f9',lw=1.4))
        self.text(x-.32,y+.20,upper,fontsize=8,color=BLUE)
        self.text(x-.32,y-.20,lower,fontsize=8,color=BLUE)
        if label:
            self.text(x,y+.62,label,color=BLUE)
        return (x-.54,y+.22),(x-.54,y-.22),(x+.56,y)

    def latch(self, x, y, label='RS'):
        self.ax.add_patch(Rectangle((x-.58,y-.42),1.16,.84,ec=BLUE,fc='#ecf3f9',lw=1.4))
        self.text(x,y+.56,label,color=BLUE)
        self.text(x-.38,y+.20,'S',fontsize=8,color=BLUE)
        self.text(x-.38,y-.20,'R',fontsize=8,color=BLUE)
        self.text(x+.36,y,'Q',fontsize=8,color=BLUE)
        return (x-.58,y+.20),(x-.58,y-.20),(x+.58,y)


def timing_page(title=None, rows=4, height=4.4):
    fig=figure(7.1,height)
    if title:
        fig.suptitle(title,fontsize=10.5,color=BLUE,fontweight='bold')
    axes=fig.subplots(rows,1,sharex=True,squeeze=False)[:,0]
    for ax in axes:
        ax.grid(alpha=.17,color=MUTED)
        ax.yaxis.label.set_fontsize(8.9)
        ax.tick_params(labelsize=8.1)
    return fig,axes
