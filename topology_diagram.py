"""Native-vector power schematics and the matching component/parameter map.

The drawings are engineering reference schematics, not routable CAD designs.
All optional symbols and table rows are driven by the same component registry.
"""
from contextlib import contextmanager
import math

import numpy as np
from matplotlib.patches import Polygon
from matplotlib.patches import Circle

from power_stage import fmt_eng, TOPOLOGIES


CAPACITOR_PITCH = 3.


def _expand_banks(*banks):
    """Insert schematic width at each bank's right edge, preserving symbol sizes."""
    return tuple((right, max(0., (count-1)*CAPACITOR_PITCH - (right-left)))
                 for (left,right),count in banks)


def topology_components(p, solved=None):
    """Ordered rows: designator, purpose, current values and source keys."""
    if p.get('topology') == 'LLC':
        from llc_ui import llc_component_rows
        return llc_component_rows(p)
    from cot_settings import active
    cot = active(p)
    if p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005':
        return isolated_components(p,solved)
    topo = p['topology']
    if topo not in TOPOLOGIES:
        raise ValueError('Unsupported schematic topology: '+str(topo))
    rows = []

    def add(ref, role, fields=(), text=''):
        values = '; '.join(f'{key}={fmt_eng(p[key], unit)}' for key, unit in fields)
        rows.append(dict(ref=ref, role=role, values=text or values,
                         keys=tuple(key for key, _ in fields)))

    add('J1', '输入端口', [('V_in', 'V')])
    add('J2', '输出端口', [('V_out', 'V'), ('P_out', 'W')])
    from component_management import primary_mos_role, controller_reference
    add('Q1', primary_mos_role(p)+'；功率级 Vgs/Vds 图对象',
        [('Rds_on', 'Ω'), ('Qg', 'C'), ('Coss', 'F')])
    if not cot or p.get('Rs', 0) > 0:
        add('R_S1', '每相高侧电流采样' if cot else '主开关电流采样（简化串联）', [('Rs', 'Ω')])
    controller = controller_reference(p)
    if controller is not None:
        rows.append(controller)
    if topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
        add('T1', '隔离变压器；N=Np/Ns',
            [('Lm_forward' if topo == 'ACF-FORWARD' else 'L', 'H'), ('N', '')])
    if topo not in ('FLYBACK', 'QR-FLYBACK'):
        from inductor_selection import purchased
        add('L1', '外购成品电感' if purchased(p) else '输出滤波电感' if topo == 'ACF-FORWARD' else '储能 / 滤波电感',
            [('L', 'H'), ('inductor_dcr', 'Ω')] if purchased(p) else [('L', 'H')])
    if cot:
        add('Q2', '各相低侧同步 N-MOS', [('Rds_aux', 'Ω'), ('Qg_aux', 'C'), ('Coss_aux', 'F')])
    elif topo == 'ACF-FORWARD':
        add('Q2', '低侧钳位 P-MOS（负栅压驱动）', [('Rds_aux', 'Ω'), ('Qg_aux', 'C'), ('Coss_aux', 'F')])
        add('C_CL1', '低侧钳位电容', [('C_clamp', 'F'), ('ESR_clamp', 'Ω')])
        add('D2', '次级续流二极管', [('Vf_diode', 'V')])
    role = '续流二极管' if topo == 'BUCK' else '输出整流二极管'
    if not cot:
        add('D1', role, [('Vf_diode', 'V')])
    from capacitor_banks import bank
    for side,prefix in (('input','C_IN'),('output','C_O')):
        for i,c in enumerate(bank(p,side),1):
            add(prefix+str(i),('输入' if side=='input' else '输出')+'电容 '+str(i),
                text='; '.join(k+'='+fmt_eng(c[k],u) for k,u in (('C','F'),('ESR','Ω'),('ESL','H'))))
    if p.get('d_in_enable'):
        add('D_IN', '输入防反二极管；耦合模型包含固定压降', [('Vf_din', 'V')])
    if p.get('d_out_enable'):
        add('D_OUT', '输出防反二极管；输出在其后，反馈在其前', [('Vf_dout', 'V')])
    if topo in ('FLYBACK', 'QR-FLYBACK') and p.get('Kc', 0.) > 1.:
        from power_stage import compute_operating_point
        from flyback_clamp import rcd_components
        op = compute_operating_point(p) if solved is None else solved
        rcd = rcd_components(op,p)
        add('D_SN1', '原边 RCD 钳位二极管', text='阳极接 Q1 漏极，阴极接 R/C 钳位汇点')
        add('R_SN1', 'RCD 电阻；⑧页计算', text='R_snub='+fmt_eng(rcd['R_snub'], 'Ω')+'（同一钳位功耗）')
        add('C_SN1', 'RCD 电容；⑧页计算', text='C_snub='+fmt_eng(rcd['C_snub'], 'F')+'（小纹波电荷预算）')
    add('R_LOAD', '等效电阻负载（非实际负载器件）',
        text=fmt_eng(p['V_out']**2 / p['P_out'], 'Ω'))
    return _diode_curve_labels(rows,p)


def _diode_curve_labels(rows,p):
    from device_curve_sources import source_for
    bank=p.get('diode_curves',{})
    for row in rows:
        if row['ref'] in bank and source_for(p,row['ref'])=='curve' and '导通损耗曲线=' not in row['values']:
            row['values']+='; 导通损耗曲线='+bank[row['ref']]['name']+' (X=Vf, Y=If)'
    return rows


class _Schematic:
    def __init__(self, ax, *, interactive=False, hits=None, expansion=(), control_anchors=None):
        self.ax, self.refs = ax, set()
        self.interactive, self.hits, self.expansion = interactive, hits, expansion
        self.control_anchors = control_anchors
        self._target = None
        self.ink = '#33465b'
        from design_theme import is_pcs
        if is_pcs(): self.ink = '#152238'
        self.fontsize = 9

    def x(self, value):
        return value + sum(amount for cut,amount in self.expansion if value >= cut)

    @contextmanager
    def mark(self, ref):
        previous = self._target
        if ref:
            self.refs.add(ref)
            self._target = ref
        try:
            yield
        finally:
            self._target = previous

    def _record(self, artist):
        if self.hits is not None and self._target is not None:
            self.hits.setdefault(self._target, []).append(artist)

    def wire(self, *points, **kw):
        x, y = zip(*points)
        kw.setdefault('color', self.ink); kw.setdefault('lw',1.35)
        self._record(self.ax.plot([self.x(value) for value in x], y, solid_capstyle='round', **kw)[0])

    def text(self, x, y, text, **kw):
        kw.setdefault('fontsize',self.fontsize); kw.setdefault('ha','center'); kw.setdefault('va','center')
        kw.setdefault('color',self.ink)
        self._record(self.ax.text(self.x(x), y, text, **kw))

    def node(self, x, y):
        self._record(self.ax.plot(self.x(x), y, 'o', ms=3.2, color=self.ink)[0])

    def terminal(self, x, y):
        self._record(self.ax.plot(self.x(x), y, 'o', ms=4, mfc='white', mec=self.ink)[0])

    def port(self, name, point, end=None, *, side='top', ref=None, junction=True, escape=()):
        """Name a real connection without spanning the other parts of the drawing."""
        end = point if end is None else end
        if self.control_anchors is not None:
            self.control_anchors[name] = (self.x(point[0]), point[1])
            if escape:
                self.control_anchors[name+'_escape'] = tuple((self.x(x), y) for x, y in (end, *escape))
        dx, dy, horizontal, vertical = {
            'top': (0, .15, 'center', 'bottom'), 'bottom': (0, -.15, 'center', 'top'),
            'left': (-.12, 0, 'right', 'center'), 'right': (.12, 0, 'left', 'center'),
        }[side]
        ink = '#2068a0'
        with self.mark(ref):
            if end != point:
                self.wire(point, end, color=ink, lw=1.)
            if junction:
                self.node(*point)
            self.text(end[0]+dx, end[1]+dy, name, color=ink, fontsize=7,
                      ha=horizontal, va=vertical)

    def drive_ports(self, x, y, suffix, source=None, *, controller_ref=None, gate_lift=0.,
                    gate_escape=(), gate_dx=-1.50):
        wired = self.control_anchors is not None and bool(gate_escape)
        end = (x + (gate_dx if wired else -1.50), y+gate_lift)
        side = 'top' if wired and gate_escape[0][1] == end[1] else 'left'
        self.port('VG_'+suffix, (x-1.15, y), end, side=side,
                  ref=controller_ref, junction=False, escape=gate_escape)
        if source is not None:
            self.port('VS_'+suffix, source, (source[0]+.55, source[1]), side='right')

    def current_probe(self, x, y, name):
        """Model current observation above a conductor, without a voltage connection."""
        ink = '#2068a0'
        self.wire((x-.52, y), (x+.52, y), color=ink, lw=.95)
        self.wire((x+.35, y+.12), (x+.52, y), (x+.35, y-.12), color=ink, lw=.95)
        self.text(x, y+.19, name, fontsize=7, color=ink, va='bottom')

    def _part(self, center, direction, ref, kind, label_side=1):
        with self.mark(ref):
            return self._draw_part(center, direction, ref, kind, label_side)

    def _draw_part(self, center, direction, ref, kind, label_side):
        c = np.array(center, float)
        d = np.array(direction, float)
        d /= np.linalg.norm(d)
        n = np.array([-d[1], d[0]])

        def point(a, b=0.):
            return tuple(c+a*d+b*n)

        a, b = point(-.75), point(.75)
        if kind == 'capacitor':
            self.wire(a, point(-.15)); self.wire(point(.15), b)
            self.wire(point(-.15, -.38), point(-.15, .38))
            self.wire(point(.15, -.38), point(.15, .38))
        elif kind == 'resistor':
            self.wire(a, point(-.48)); self.wire(point(.48), b)
            vertices = [point(-.48, -.17), point(.48, -.17),
                        point(.48, .17), point(-.48, .17), point(-.48, -.17)]
            self.wire(*vertices)
        elif kind == 'inductor':
            self.wire(a, point(-.60)); self.wire(point(.60), b)
            u = np.linspace(-.60, .60, 100)
            pts = [point(t, .25*abs(math.sin((t+.60)*math.pi/.30))) for t in u]
            self.wire(*pts)
        elif kind == 'diode':
            self.wire(a, point(-.28)); self.wire(point(.28), b)
            points = [point(-.28, -.32), point(-.28, .32), point(.28)]
            self._record(self.ax.add_patch(Polygon([(self.x(x),y) for x,y in points],
                                                   fill=False, ec=self.ink, lw=1.35)))
            self.wire(point(.28, -.36), point(.28, .36))
        if ref:
            self.refs.add(ref)
            label = c + n*.66*label_side
            self.text(*label,ref,**({'ha':'right' if label_side>0 else 'left'}
                                   if abs(d[1])>.9 else {}))
        return a, b

    def capacitor(self, x, y, ref, **kw):
        return self._part((x, y), (0, 1), ref, 'capacitor', **kw)

    def capacitor_bank(self, values, refs, x_range, top, bottom, summary_y=None):
        """Draw all desktop branches at fixed pitch and compact report banks.

        A compact bank's first/last designators and count cover the complete
        bank. Component rows always list every physical branch separately.
        """
        count = len(values)
        assert count == len(refs) and count > 0
        visible = range(count) if self.interactive or count <= 3 else (0, count-1)
        left, right = x_range
        middle = (left+right)/2
        target = self
        if self.interactive:
            target = _Schematic(self.ax, hits=self.hits)
            positions = (self.x(left)+CAPACITOR_PITCH*np.arange(count) if count > 1 else [self.x(middle)])
        else:
            positions = np.linspace(left, right, len(visible)) if count > 1 else [middle]
        cy = (top+bottom)/2
        label_offset = 1.5 if top-bottom > 5 else .82
        for rank, (index, x) in enumerate(zip(visible, positions)):
            with target.mark(refs[index]):
                a, b = target.capacitor(x, cy, None)
                # In the full drawing the clickable area is the symbol and label,
                # so the long common rails remain clear for panning.
                target.text(x, cy+(label_offset if rank % 2 == 0 else -label_offset), refs[index],
                            fontsize=min(self.fontsize, 7.5),
                            bbox=dict(facecolor='white', edgecolor='none', pad=.25))
            target.wire((x, top), b); target.wire(a, (x, bottom))
            target.node(x, top); target.node(x, bottom)
        if not self.interactive and count > 3:
            self.text(middle, cy+.3, '…', fontsize=11)
        if summary_y is not None:
            self.text(middle, summary_y,
                      f'{count} 颗 · ΣC={fmt_eng(sum(c["C"] for c in values), "F")}',
                      fontsize=7, bbox=dict(facecolor='white', edgecolor='none', pad=.2))
        self.refs.update(refs)

    def resistor(self, x, y, ref, **kw):
        return self._part((x, y), (0, 1), ref, 'resistor', **kw)

    def diode(self, x, y, ref, direction=(1, 0), **kw):
        return self._part((x, y), direction, ref, 'diode', **kw)

    def inductor(self, x, y, ref, direction=(1, 0), **kw):
        return self._part((x, y), direction, ref, 'inductor', **kw)

    def mos(self, x, y, ref, p_channel=False, label_offset=(1.02, 0.), *,
            source_above=False, show_pin_labels=True):
        with self.mark(ref):
            return self._draw_mos(x, y, ref, p_channel, label_offset, source_above, show_pin_labels)

    def _draw_mos(self, x, y, ref, p_channel, label_offset, source_above, show_pin_labels):
        self.wire((x, y+1), (x, y+.47), (x+.25, y+.47))
        self.wire((x, y-1), (x, y-.47), (x+.25, y-.47))
        for a, b in ((-.55, -.25), (-.15, .15), (.25, .55)):
            self.wire((x+.25, y+a), (x+.25, y+b))
        self.wire((x-.12, y-.50), (x-.12, y+.50))
        self.wire((x-1.15, y), (x-.32 if p_channel else x-.12, y))
        if p_channel:
            self._record(self.ax.add_patch(Circle((self.x(x-.22), y), .10, fc='white', ec=self.ink, lw=1.2)))
        # Body diode is S -> D on an N-MOS, D -> S on a P-MOS.
        self.wire((x, y+.80), (x+.65, y+.80), (x+.65, y+.75))
        self.diode(x+.65, y, None, direction=(0, 1 if p_channel == source_above else -1))
        self.wire((x+.65, y-.75), (x+.65, y-.80), (x, y-.80))
        self.text(x+label_offset[0],y+label_offset[1],ref,ha='left')
        if show_pin_labels:
            upper, lower = ('S', 'D') if source_above else ('D', 'S')
            for dx,dy,label,align in ((-.3,.77,upper,'right'),(-.3,-.77,lower,'right'),(-1.17,.18,'G','center')):
                self.text(x+dx,y+dy,label,fontsize=7,ha=align,va='baseline')
        if source_above:
            return (x, y-1), (x, y+1)
        return (x, y+1), (x, y-1)


def _draw_flyback_rcd(s, bus_y, drain_x):
    """Draw parallel R/C from Vin to the diode cathode, with its anode at drain."""
    left, right = 4.8, 6.
    diode_x = (left + right) / 2
    clamp_y = bus_y - 1.60
    diode_y = bus_y - 2.40
    for x, ref, part, label_rise in ((left, 'R_SN1', s.resistor, 1.3),
                                     (right, 'C_SN1', s.capacitor, .65)):
        with s.mark(ref):
            bottom, top = part(x, bus_y - .78, None)
            s.text(x, bus_y + label_rise, ref, fontsize=min(s.fontsize, 8))
        s.wire((x, clamp_y), bottom)
        s.wire(top, (x, bus_y)); s.node(x, bus_y)
    s.wire((left, clamp_y), (right, clamp_y))
    with s.mark('D_SN1'):
        anode, cathode = s.diode(diode_x, diode_y, None, direction=(0, 1))
        s.text(diode_x + .45, diode_y, 'D_SN1', ha='left', fontsize=min(s.fontsize, 7))
    s.wire(cathode, (diode_x, clamp_y)); s.node(diode_x, clamp_y)
    drain = (drain_x, anode[1])
    s.wire(anode, drain); s.node(*drain)


def _controller_box(s, p, y):
    """Keep the reference away from power wires; no implied real IC pinout."""
    from component_management import controller_reference, primary_mos_role
    row = controller_reference(p)
    if row is None:
        return
    if s.interactive:
        # Keep the frame compact even when the input capacitor bank is wide.
        s.refs.add('U_CTRL')
        s = _Schematic(s.ax, hits=s.hits)
    item = p['component_management']['items']['U_CTRL']
    name = ' '.join(str(item.get(k) or '').strip() for k in ('manufacturer', 'model')).strip()
    with s.mark('U_CTRL'):
        s.wire((.1, y-.7), (8.1, y-.7), (8.1, y+.7), (.1, y+.7), (.1, y-.7))
        s.text(4.1, y+.3, 'U_CTRL · '+(name or '控制器型号待补充')[:58], fontsize=7.5,
               bbox=dict(facecolor='white', edgecolor='none', pad=.2))
        s.text(4.1, y-.24, '参考框：未展开引脚、驱动与偏置', fontsize=6.8)
    if 'P-MOS' in primary_mos_role(p):
        s.text(14.4, y, 'Q1 为 P-MOS；本图按幅值等效示意\n实物须按器件源漏极性及驱动设计',
               fontsize=7, bbox=dict(facecolor='white', edgecolor='none', pad=.25))


def qr_sense_winding(p, rails=()):
    """Resolve the QR exporter convention using the drawn physical windings."""
    from qr_spice_settings import QR_SETTINGS

    request = int((p.get('spice_config') or {}).get('qr_zcd_winding', QR_SETTINGS['qr_zcd_winding'][0]))
    if request != -1:
        return request
    if not rails:
        return 1
    selected = int(p.get('feedback_output', 1))
    candidates = [rail for rail in rails if rail['id'] != selected] or rails
    return min(candidates, key=lambda rail: (rail['Ns'], rail['id']))['id']


def _sense_ports(s, raw, reference, *, raw_side='right', reference_side='right', raw_drop=0., raw_escape=()):
    rx, ry = raw
    refx, refy = reference
    s.port('CS_RAW', raw, (rx+(-.45 if raw_side == 'left' else .55), ry-raw_drop),
           side='top' if raw_escape else raw_side, escape=raw_escape)
    s.port('CS_RETURN', reference, (refx+(-.45 if reference_side == 'left' else .55), refy),
           side=reference_side)


def _draw_cot_buck(ax, p, solved, show_values, interactive, hits, *,
                   control_ports=False, control_anchors=None):
    from capacitor_banks import bank

    phases = int(p.get('buck_phases', 1))
    if phases == 1:
        ys = [(1, 5.5)]
    elif interactive or control_ports:
        ys = [(i, 4.6+5.7*(phases-i)) for i in range(1, phases+1)]
    else:
        ys = [(1, 10.3), (phases, 4.6)]
    top = ys[0][1]+2.4
    ground = .7
    banks = [(bank(p,'input'),'C_IN',(2.25,4.2)), (bank(p,'output'),'C_O',(16.2,18.0))]
    expansion = _expand_banks(*((bounds,len(values)) for values,_,bounds in banks)) if interactive else ()
    s = _Schematic(ax, interactive=interactive, hits=hits, expansion=expansion, control_anchors=control_anchors)
    ax.clear()
    ax.set_aspect('equal')
    ax.set_xlim(-.4, s.x(23))
    ax.set_ylim(-.25 if control_ports else -2.05, top+1.6)
    ax.set_axis_off()
    s.fontsize = 8
    with s.mark('J1'):
        s.terminal(.3, top)
        s.terminal(.3, ground)
        s.text(.4, top+.65, 'J1 · Vin')
    if control_ports:
        s.port('PGND', (.78, ground), (.78, ground-.22), side='bottom')
    else:
        s.text(.4, ground-.55, 'PGND')
    if p.get('d_in_enable'):
        a, b = s.diode(1.42, top, 'D_IN')
        s.wire((.3, top), a)
        s.wire(b, (4.9, top))
    else:
        s.wire((.3, top), (4.9, top))
    s.wire((.3, ground), (22.3, ground))
    s.wire((4.9, top), (4.9, ys[-1][1]+2.4))
    s.wire((15.6, top), (15.6, ys[-1][1]))
    if control_ports:
        s.port('VIN_BUS', (4.9, top), (4.9, top+.35))
    for values,prefix,bounds in banks:
        s.capacitor_bank(values, [f'{prefix}{i+1}' for i in range(len(values))], bounds, top, ground)

    cfg = p.get('cot_config') or {}
    phase_current = (cfg.get('model') == 'current_feedback' or cfg.get('balance_gain_v_per_a', 0.)
                     or cfg.get('phase_limit_A', 0.) or cfg.get('light_load') == 'diode_emulation')
    for phase, y in ys:
        s.text(5.8, y+(.48 if control_ports else .85), f'相 {phase}', ha='left', fontsize=8, fontweight='bold')
        d, hs = s.mos(8.8, y+1.15, 'Q1', label_offset=(1.1, .22))
        ld, ls = s.mos(8.8, y-1.15, 'Q2', label_offset=(1.1, -.22))
        if p.get('Rs', 0) > 0:
            a, b = s._part((6.55, y+2.4), (1, 0), 'R_S1', 'resistor')
            s.wire((4.9, y+2.4), a)
            s.wire(b, (8.8, y+2.4), d)
        else:
            s.wire((4.9, y+2.4), (8.8, y+2.4), d)
        s.node(4.9, y+2.4)
        s.wire(hs, ld)
        s.wire(ls, (8.8, y-2.43))
        for k, width in enumerate((.33, .23, .12)):
            s.wire((8.8-width, y-2.43-.12*k), (8.8+width, y-2.43-.12*k))
        a, b = s.inductor(12.55, y, 'L1')
        s.wire((8.8, y), a)
        s.wire(b, (15.6, y))
        s.node(8.8, y)
        s.node(15.6, y)
        if control_ports:
            s.drive_ports(8.8, y+1.15, f'Q1_P{phase}', hs, controller_ref='U_CTRL',
                          gate_escape=((-.82, y+1.15),))
            s.drive_ports(8.8, y-1.15, f'Q2_P{phase}', ls, controller_ref='U_CTRL',
                          gate_escape=((-.82, y-1.15),))
            s.text(9.18, y-2.82, 'PGND', fontsize=6.7, ha='left', color='#2068a0')
            if phase_current:
                s.current_probe(12.55, y+1.19, f'IS_P{phase}')
    if phases > 2 and not (interactive or control_ports):
        s.text(11.6, 7.18, f'… 中间 {phases-2} 相', fontsize=7,
               bbox=dict(facecolor='white', edgecolor='none', pad=.2))

    s.wire((15.6, top), (18.45, top))
    if p.get('d_out_enable'):
        a, b = s.diode(19.55, top, 'D_OUT')
        s.wire((18.45, top), a)
        s.wire(b, (22.3, top))
    else:
        s.wire((18.45, top), (22.3, top))
    with s.mark('J2'):
        s.terminal(22.3, top)
        s.terminal(22.3, ground)
        s.text(22.0, top+.64, 'J2 · Vout')
    a, b = s.resistor(21.05, (top+ground)/2, 'R_LOAD', label_side=-1)
    s.wire((21.05, ground), a)
    s.wire(b, (21.05, top))
    s.node(21.05, top)
    if control_ports:
        lift = .48 if control_anchors is not None else .35
        s.port('V_SENSE', (18.45, top), (18.45, top+lift), escape=((23.42, top+lift),))
        if phase_current:
            s.text(13.5, .13, 'IS_Pn · 模型电感电流测量', fontsize=7, color='#2068a0')
    else:
        with s.mark('U_CTRL'):
            s.wire((5.1, -.15), (15.5 if interactive else 18.8, -.15),
                   (15.5 if interactive else 18.8, -1.22), (5.1, -1.22), (5.1, -.15))
            s.text(10.3 if interactive else 11.95, -.66,
                   f'U_CTRL · COT · {phases} 相 · 防反前取样，逐相发脉冲', fontsize=8)
        s.text(11.95, -1.65, 'Q1 / Q2 / L1 按相复制；显示公共标称值，逐相失配见配置。',
               fontsize=7)
    if show_values and solved:
        s.text(10.8, top+.82,
               f'{fmt_eng(solved["f_sw"], "Hz")} / 相 · ' +
               (f'相间 {360/phases:g}° · 共用一个输出' if phases > 1 else '单相同步'),
               fontsize=8)
    return s.refs


def draw_topology(ax, p, solved=None, *, label_operating_values=True, interactive=False,
                  hits=None, control_ports=False, control_anchors=None):
    """Return component rows and optionally collect desktop signal route points.

    Each connected signal exports its electrical point and an ``_escape`` path
    beginning at the tip of its drawn lead. Both use the final canvas coordinates.
    """
    from cot_settings import active
    if hits is not None:
        hits.clear()
    if control_anchors is not None:
        control_anchors.clear()
    if p.get('topology') == 'LLC':
        from llc_ui import draw_llc
        draw_llc(ax, p, solved, label_operating_values, interactive, hits,
                 control_ports=control_ports, control_anchors=control_anchors)
        return topology_components(p, solved)
    if active(p):
        components = topology_components(p,solved)
        refs = {row['ref'] for row in components}
        drawn = _draw_cot_buck(ax, p, solved, label_operating_values, interactive, hits,
                              control_ports=control_ports, control_anchors=control_anchors)
        assert drawn == refs, (drawn-refs,refs-drawn)
        return components
    if p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005':
        return draw_isolated(ax, p, solved, label_operating_values=label_operating_values,
                             interactive=interactive, hits=hits, control_ports=control_ports,
                             control_anchors=control_anchors)
    components = topology_components(p,solved)
    refs = {r['ref'] for r in components}
    topo = p['topology']
    isolated = topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
    from capacitor_banks import bank
    input_caps, output_caps = bank(p,'input'), bank(p)
    input_slot, output_slot = (2.05,3.9), (14.5,16.15)
    expansion = _expand_banks((input_slot,len(input_caps)),(output_slot,len(output_caps))) if interactive else ()
    s = _Schematic(ax, interactive=interactive, hits=hits, expansion=expansion, control_anchors=control_anchors)
    ax.clear(); ax.set_aspect('equal'); ax.set_xlim(-.4, s.x(20.2))
    ax.set_ylim(-2.5 if 'U_CTRL' in refs and not control_ports else -.25, 10.7)
    ax.set_axis_off()
    voltage_buck = topo == 'BUCK' and p.get('control_mode') == 'Voltage Mode'
    current_sample = p.get('Rs', 0.) > 0 and (p.get('control_mode') == 'Peak Current Mode' or voltage_buck)
    controller_ref = 'U_CTRL' if 'U_CTRL' in refs else None
    zcd = qr_sense_winding(p) if control_ports and topo == 'QR-FLYBACK' else None
    with s.mark('J1'):
        s.terminal(.25, 9); s.terminal(.25, 1)
        s.text(.35, 9.9, 'J1 · Vin +'); s.text(.35, .35, 'J1 −')
    s.wire((.25, 1), (7 if isolated else 19.6, 1))
    input_end = 5.5 if topo == 'BOOST' else 7
    if 'D_IN' in refs:
        a, b = s.diode(1.2, 9, 'D_IN')
        s.wire((.25, 9), a); s.wire(b, (input_end, 9))
    else:
        s.wire((.25, 9), (input_end, 9))
    s.capacitor_bank(input_caps, [f'C_IN{i}' for i in range(1, len(input_caps)+1)],
                     input_slot, 9, 1, 2.15)
    if control_ports and voltage_buck:
        s.port('VIN_BUS', (5.35, 9), (5.35, 9.35))

    # Primary / switching-node connections.
    if isolated:
        with s.mark('T1'):
            s.inductor(7, 7.5, None, direction=(0, 1))
            s.inductor(9, 7.5, None, direction=(0, 1), label_side=-1)
            s.wire((7.9, 6.7), (7.9, 8.3)); s.wire((8.1, 6.7), (8.1, 8.3))
            s.text(8, 9.9, 'T1 · Np/Ns')
            # Flyback secondary dot is opposite to the forward transformer dot.
            s.node(7.32, 8.3); s.node(8.68, 8.3 if topo == 'ACF-FORWARD' else 6.7)
        s.wire((7, 9), (7, 8.25)); s.wire((7, 6.75), (7, 6))
        s.wire((9, 9), (9, 8.25)); s.wire((9, 6.75), (9, 1))
        s.wire((8.5,.5),(8.5,6.2),color='#b7c6d7',lw=.9,ls='--')
        s.text(8.5,.05,'隔离',fontsize=8,color='#7890a6',va='baseline')
        d, source = s.mos(7, 3.9, 'Q1')
        s.wire((7, 6), d)
        a, b = s.resistor(7, 1.9, 'R_S1')
        s.wire(source, b); s.wire(a, (7, 1))
        s.wire((9, 1), (19.6, 1))
        if control_ports:
            routed_clamp = topo == 'ACF-FORWARD' and control_anchors is not None
            gate_escape = (((5.76, 3.56), (6.27, 3.56), (6.27, -.62)) if routed_clamp else ((5.5, -.62),))
            s.drive_ports(7, 3.9, 'Q1', controller_ref=controller_ref,
                          gate_lift=0. if routed_clamp else .63,
                          gate_dx=-1.24 if routed_clamp else -1.50, gate_escape=gate_escape)
            if current_sample:
                _sense_ports(s, b, (7, 1), raw_drop=.38, reference_side='right' if routed_clamp else 'left')
        if topo == 'ACF-FORWARD':
            with s.mark('C_CL1'):
                bottom, top = s.capacitor(5.25, 4.9, None)
                s.text(5.25, 6.8, 'C_CL1')
            s.wire((7, 6), (5.25, 6), top); s.node(7, 6)
            d2, source2 = s.mos(5.25, 2.95, 'Q2', p_channel=True, show_pin_labels=not control_ports)
            s.wire(bottom, d2); s.wire(source2, (5.25, 1)); s.node(5.25, 1)
            if control_ports:
                s.drive_ports(5.25, 2.95, 'Q2', controller_ref=controller_ref,
                              gate_dx=-1.12, gate_escape=((4.13, -.62),))
        elif 'D_SN1' in refs:
            _draw_flyback_rcd(s, 9, 7)
        a, b = s.diode(10.7, 9, 'D1')
        s.wire((9, 9), a)
        if zcd == 0:
            s.port('ZCD_RAW+', (7, 6), (8.0, 6), side='right')
            s.port('ZCD_RAW−', (7, 9), (7, 8.77), side='left')
        elif zcd == 1:
            s.port('ZCD_RAW+', (9, 9), (9.1, 8.7), side='right')
            s.port('ZCD_RAW−', (9, 1), (9.3, 1.36), side='right')
        elif zcd is not None:
            s.text(12.2, 8.25, f'ZCD 取样 OUT{zcd} 不存在', fontsize=7, color='#2068a0')
        if topo == 'ACF-FORWARD':
            s.wire(b, (12.1, 9), (12.1, 7.55))
            a2, b2 = s.diode(12.1, 6.8, 'D2', direction=(0, 1), label_side=-1)
            s.wire((12.1, 1), a2); s.wire(b2, (12.1, 9)); s.node(12.1, 9); s.node(12.1, 1)
            la, lb = s.inductor(13.4, 9, 'L1')
            s.wire(b, la); s.wire(lb, (16.5, 9))
        else:
            s.wire(b, (16.5, 9))
        out_y = 9
    elif topo == 'BOOST':
        la, lb = s.inductor(6.25, 9, 'L1')
        d, source = s.mos(8.5, 5, 'Q1')
        s.wire((7, 9), (8.5, 9), d); s.node(8.5, 9)
        a, b = s.resistor(8.5, 2.5, 'R_S1'); s.wire(source, b); s.wire(a, (8.5, 1))
        if control_ports:
            s.drive_ports(8.5, 5, 'Q1', source, controller_ref=controller_ref,
                          gate_escape=((7., -.62),))
            if current_sample:
                _sense_ports(s, b, (8.5, 1), reference_side='left')
        da, db = s.diode(11, 9, 'D1'); s.wire((8.5, 9), da); s.wire(db, (16.5, 9))
        s.wire(lb, (8.5, 9))
        out_y = 9
    else:
        # Preserve the report magnitude view. The control diagram exposes the P-MOS
        # source and upstream shunt when the hardware declares a P-channel device.
        from component_management import primary_mos_role
        p_channel = control_ports and 'P-MOS' in primary_mos_role(p)
        gate_y = 5.9 if p_channel else 7.8
        d, source = s.mos(7, gate_y, 'Q1', p_channel, source_above=p_channel)
        a, b = s.resistor(7, 8.0 if p_channel else 5.65, 'R_S1')
        if p_channel:
            s.wire((7, 9), b); s.wire(a, source); s.wire(d, (7, 4.5))
        else:
            s.wire((7, 9), d); s.wire(source, b); s.wire(a, (7, 4.5))
        s.node(7, 4.5)
        if control_ports:
            s.drive_ports(7, gate_y, 'Q1', source, controller_ref=controller_ref,
                          gate_escape=((5.5, -.62),))
            if current_sample:
                _sense_ports(s, b, a, raw_side='left', reference_side='left' if p_channel else 'right')
        if topo == 'BUCK':
            la, lb = s.inductor(11.0, 4.5, 'L1')
            s.wire((7, 4.5), la); s.wire(lb, (16.5, 4.5))
            a, b = s.diode(8.8, 2.65, 'D1', direction=(0, 1), label_side=-1)
            s.wire((8.8, 1), a); s.wire(b, (8.8, 4.5)); s.node(8.8, 4.5)
        else:
            a, b = s.inductor(8.8, 2.65, 'L1', direction=(0, 1), label_side=-1)
            s.wire((8.8, 1), a); s.wire(b, (8.8, 4.5))
            s.wire((7, 4.5), (9.7, 4.5)); s.node(8.8, 4.5)
            da, db = s.diode(11, 4.5, 'D1', direction=(-1, 0), label_side=-1)
            s.wire((9.7, 4.5), da); s.wire(db, (16.5, 4.5))
        out_y = 4.5

    s.capacitor_bank(output_caps, [f'C_O{i}' for i in range(1, len(output_caps)+1)],
                     output_slot, out_y, 1, .35)
    if 'D_OUT' in refs:
        da, db = s.diode(17.5, out_y, 'D_OUT',
                         direction=(-1, 0) if topo == 'BUCK-BOOST' else (1, 0))
        # Direction changes terminal order, not the connection to each rail.
        ends = sorted((da, db))
        s.wire((16.5, out_y), ends[0]); s.wire(ends[1], (19.6, out_y))
    else:
        s.wire((16.5, out_y), (19.6, out_y))
    a, b = s.resistor(18.9, (out_y+1)/2, 'R_LOAD', label_side=-1)
    s.wire((18.9, out_y), b); s.wire(a, (18.9, 1)); s.node(18.9, out_y)
    with s.mark('J2'):
        s.terminal(19.6, out_y); s.terminal(19.6, 1)
        s.text(18.9, out_y+.9, 'J2 · Vout '+('−' if topo == 'BUCK-BOOST' else '+'))
    if control_ports:
        s.port('PGND', (1.78, 1), (1.78, .71), side='bottom')
        if isolated:
            s.port('SGND', (18.9, 1), (18.9, .7), side='bottom')
        sense = 'V_SENSE−' if topo == 'BUCK-BOOST' else 'V_SENSE'
        lift = .48 if control_anchors is not None else .81
        s.port(sense, (16.5, out_y), (16.5, out_y+lift), side='left',
               escape=((20.65, out_y+lift),))
    else:
        s.text(19.2, .35, 'SGND' if isolated else 'GND')
        if isolated:
            s.text(6.2, .35, 'PGND')
        _controller_box(s, p, -1.2)
    assert s.refs == refs, (s.refs-refs, refs-s.refs)
    return components


def isolated_components(p, solved=None):
    from isolated_outputs import output_specs
    from isolated_fields import FIELDS
    from mp6005 import DEFAULTS
    rails = output_specs(p) or [dict(p,name='OUT1',id=1)]
    from power_stage import compute_operating_point
    solved=compute_operating_point(p) if solved is None else solved
    q = dict(solved.get('aggregate_params',p),outputs=[],feedback_mode='SSR',feedback_output=1,
             coupling_config=dict(enabled=False))
    q['component_management'] = p.get('component_management', {})
    if p.get('feedback_mode') == 'PSR-MP6005':
        q['component_management'] = dict(q['component_management'], items={
            key:value for key,value in q['component_management'].get('items', {}).items() if key != 'U_CTRL'})
    old = topology_components(q,solved)
    keep = {'J1','Q1','R_S1','T1','C_IN1','C_IN2','D_IN','Q2','C_CL1','D_SN1','R_SN1','C_SN1','U_CTRL'}
    rows = [r for r in old if r['ref'] in keep or r['ref'].startswith('C_IN')]
    for r in rows:
        if r['ref']=='T1':
            r['role']='共享磁芯；主反馈电压为输入，其余输出按实际副边匝数比估算'
            r['values']='N(OUT1)='+fmt_eng(p['N'],'')+'; '+('Lm_forward='+fmt_eng(p['Lm_forward'],'H') if p['topology']=='ACF-FORWARD' else 'Lm='+fmt_eng(p['L'],'H'))
            if solved.get('coupled_model'):
                r['role']='线性耦合绕组；Lp 为原边开路自感；kij 见左栏⑦'
                r['values']='Lp='+fmt_eng(p['L'],'H')+'; kij=完整对称矩阵'
    for rail in rails:
        i = rail['id']
        fields = [('J_O'+str(i),'输出端口',('V_out','P_out')),('D_O'+str(i),'整流二极管',('Vf_diode','Qrr')),
                  ('C_O'+str(i)+'A','输出电容 A',('C_out','Rc','ESL')),('R_LOAD'+str(i),'等效负载',('P_out',))]
        if rail['d_out_enable']: fields.append(('D_B'+str(i),'输出防反二极管',('Vf_dout',)))
        if p['topology']=='ACF-FORWARD':
            fields += [('D_F'+str(i),'续流二极管',('Vf_diode',)),('L_O'+str(i),'独立输出电感',('L',))]
        for ref,role,keys in fields:
            if ref.startswith('C_O'):continue
            rows.append(dict(ref=ref,role=f"OUT{i} {rail['name']} · {role}",
                             # FIELDS already chooses the display prefix;
                             # applying fmt_eng again creates e.g. "100mmΩ".
                             values='; '.join(f'{k}={rail[k]/FIELDS[k][2]:.5g}{FIELDS[k][1]}' for k in keys),keys=keys))
        from capacitor_banks import bank,output_ref
        for j,c in enumerate(bank(rail),1):
            rows.append(dict(ref=output_ref(i,j,True),role=f'OUT{i} 输出电容 {j}',
                values='; '.join(k+'='+fmt_eng(c[k],u) for k,u in (('C','F'),('ESR','Ω'),('ESL','H'))),keys=('output_capacitors',)))
    if p.get('feedback_mode')=='PSR-MP6005':
        for ref,role,key in [('N_A','独立辅助采样绕组','psr_Na'),('R_FBH','FB 分压上电阻','psr_RfbH'),
                             ('R_FBL','FB 分压下电阻（0=自动）','psr_RfbL'),('R_REG','SENSE 补偿/抖频设置','psr_Rreg'),
                             ('R_COMP','COMP 串联电阻','psr_Rcomp'),('C_COMP','COMP 串联电容','psr_Ccomp'),
                             ('C_POLE','COMP 高频并联电容','psr_Cpole')]:
            rows.append(dict(ref=ref,role=role,values=f'{key}={p.get(key,DEFAULTS[key]):.5g}',keys=(key,)))
        rows.append(dict(ref='U_PSR',role='MP6005，MODE 悬空',values='250kHz PWM / 轻载降频；非精确 IC 仿真',keys=()))
    else:
        rows.append(dict(ref='U_FB',role='SSR 主反馈通路（控制框图）',values=f"OUT{int(p.get('feedback_output',1))}；未反馈路不独立稳压",keys=('feedback_output',)))
    return _diode_curve_labels(rows,p)


def draw_isolated(ax, p, solved=None, *, label_operating_values=True, interactive=False,
                  hits=None, control_ports=False, control_anchors=None):
    """Expanded winding drawing. Each secondary has its own local return."""
    from isolated_outputs import output_specs
    from capacitor_banks import bank, output_ref
    rails = output_specs(p) or [dict(p,name='OUT1',id=1)]
    rows = isolated_components(p,solved); refs={r['ref'] for r in rows}
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    controller_ref = 'U_CTRL' if 'U_CTRL' in refs else None
    current_sample = p.get('Rs', 0.) > 0 and (psr or p.get('control_mode') == 'Peak Current Mode')
    zcd = qr_sense_winding(p, rails) if control_ports and p['topology'] == 'QR-FLYBACK' else None
    input_caps = bank(p,'input')
    output_banks = [bank(rail) for rail in rails]
    input_slot, output_slot = (2.05,3.9), (16.,18.5)
    expansion = _expand_banks((input_slot,len(input_caps)),
                              (output_slot,max(map(len,output_banks)))) if interactive else ()
    s = _Schematic(ax, interactive=interactive, hits=hits, expansion=expansion, control_anchors=control_anchors)
    ax.clear(); ax.set_axis_off()
    height=max(12,5*len(rails)+2)
    embedded_psr = psr and control_anchors is None
    ax.set_xlim(-.8,s.x(25)); ax.set_ylim(-7 if embedded_psr else -.25 if control_ports else -3,height); ax.set_aspect('auto')
    s.fontsize=7.5
    y=height-2; ground=y-8
    with s.mark('J1'):
        s.terminal(0,y); s.terminal(0,ground); s.text(0,y+.9,'J1 · Vin')
    s.wire((0,ground),(7,ground))
    if 'D_IN' in refs:
        a,b=s.diode(1,y,'D_IN'); s.wire((0,y),a); s.wire(b,(7,y))
    else: s.wire((0,y),(7,y))
    s.capacitor_bank(input_caps, [f'C_IN{i}' for i in range(1, len(input_caps)+1)],
                     input_slot, y, ground, y-7.2)
    with s.mark('T1'):
        a,b=s.inductor(7,y-1.5,None,direction=(0,1))
        s.node(7.35,y-.65); s.text(7.3,y+.9,'T1 · Np')
    s.wire((7,y),b); s.wire(a,(7,y-3))
    d,src=s.mos(7,y-4.5,'Q1',label_offset=(-1.6,-.65)); s.wire((7,y-3),d)
    clamp_driver = control_ports and 'Q2' in refs
    routed_psr = psr and control_ports and control_anchors is not None
    a,b=s.resistor(7,y-6.65,'R_S1',label_side=-1 if clamp_driver or routed_psr else 1)
    s.wire(src,b); s.wire(a,(7,ground))
    if control_ports:
        s.port('PGND', (1.15, ground), (1.15, ground-.23), side='bottom')
        gate_y = y-4.5
        routed_clamp = clamp_driver and control_anchors is not None
        gate_escape = (((5.76, gate_y-.43), (6.27, gate_y-.43), (6.27, -.62))
                       if routed_clamp else ((5.5, -.62),))
        s.drive_ports(7, gate_y, 'Q1', controller_ref=controller_ref,
                      gate_dx=-1.24 if routed_clamp else -1.50, gate_escape=gate_escape)
        if current_sample:
            side = 'right' if routed_clamp else 'left'
            raw_escape = ((6.09, b[1]), (6.09, -.68)) if routed_psr else ()
            _sense_ports(s, b, (7, ground), raw_side=side,
                         reference_side='right' if routed_psr else side,
                         raw_drop=.56 if clamp_driver and not routed_clamp else 0., raw_escape=raw_escape)
    else:
        s.text(6,ground-.5,'PGND')
    if 'Q2' in refs:
        a,b=s.capacitor(5.25,y-3.8,'C_CL1'); s.wire((7,y-3),(5.25,y-3),b)
        d,src=s.mos(5.25,y-5.6,'Q2',True,show_pin_labels=not control_ports)
        s.wire(a,d); s.wire(src,(5.25,ground))
        if control_ports:
            s.drive_ports(5.25, y-5.6, 'Q2', controller_ref=controller_ref,
                          gate_dx=-1.12, gate_escape=((4.13, -.62),))
    elif 'D_SN1' in refs:
        _draw_flyback_rcd(s, y, 7)
    if zcd == 0:
        s.port('ZCD_RAW+', (7, y-3), (7.95, y-3), side='right')
        s.port('ZCD_RAW−', (7, y), (7, y-.21), side='left')
    elif zcd is not None and not 1 <= zcd <= len(rails):
        s.text(12.2, y-.75, f'ZCD 取样 OUT{zcd} 不存在', fontsize=7, color='#2068a0')
    # Core and isolation boundary span every configured secondary.
    with s.mark('T1'):
        s.wire((8.3,height-3),(8.3,1)); s.wire((8.5,height-3),(8.5,1))
    s.wire((9,-2),(9,height),ls='--',lw=.8,color='#9aaec1')
    for rail, output_caps in zip(rails,output_banks):
        i=rail['id']; yy=height-2-5*(i-1); low=yy-2.8
        with s.mark('T1'):
            a,b=s.inductor(10,yy-1.4,None,direction=(0,1))
            s.node(9.65,yy-.55 if p['topology']=='ACF-FORWARD' else low+.55)
        s.wire((10,yy),b); s.wire(a,(10,low),(22.7,low))
        a,b=s.diode(11.8,yy,f'D_O{i}'); s.wire((10,yy),a)
        if zcd == i:
            s.port('ZCD_RAW+', (10, yy), (10.34, yy-.52), side='right')
            s.port('ZCD_RAW−', (10, low), (10.25, low+.25), side='right')
        if p['topology']=='ACF-FORWARD':
            c,d=s.diode(13.2,yy-1.4,f'D_F{i}',direction=(0,1),label_side=-1)
            s.wire((13.2,low),c); s.wire(d,(13.2,yy)); s.wire(b,(13.2,yy))
            c,d=s.inductor(14.5,yy,f'L_O{i}'); s.wire(b,c); s.wire(d,(20,yy))
        else: s.wire(b,(20,yy))
        s.capacitor_bank(output_caps, [output_ref(i, j, True) for j in range(1, len(output_caps)+1)],
                         output_slot, yy, low)
        if f'D_B{i}' in refs:
            a,b=s.diode(20.5,yy,f'D_B{i}'); s.wire((20,yy),a); s.wire(b,(22.7,yy))
        else: s.wire((20,yy),(22.7,yy))
        with s.mark(f'R_LOAD{i}'):
            a,b=s.resistor(22.,yy-1.4,None)
            s.text(21.5,yy-1.4,f'R_LOAD{i}',ha='right',fontsize=7.5)
        s.wire((22,yy),b); s.wire(a,(22,low))
        main=i==p.get('feedback_output',1)
        if control_ports and main and not psr:
            lift = .48 if control_anchors is not None else .71
            s.port('V_SENSE', (19.5, yy), (19.5, yy+lift), side='left', ref='U_FB',
                   escape=((25.45, yy+lift),))
            s.port('SGND', (19.5, low), (19.5, low+.39), side='right', ref='U_FB')
        name = rail['name'] if len(rails) <= 3 else ''
        if label_operating_values:
            suffix = f" {name}" if name else ''
            title = f"J_O{i} ·{suffix} {rail['V_out']:.4g}V / {rail['P_out']:.4g}W"
        else:
            title = f"J_O{i}"+(' · '+name if name else '')
        if main:
            title += ' ★'
        title += f' · 电容 {len(output_caps)} 颗 · ΣC={fmt_eng(sum(c["C"] for c in output_caps), "F")}'
        with s.mark(f'J_O{i}'):
            s.terminal(22.7,yy); s.terminal(22.7,low)
            s.text(17., yy+1.5, title, fontsize=7 if len(rails) > 3 else 7.5,
                   bbox=dict(facecolor='white', edgecolor='none', pad=.3))
        s.text(23., low, f'SGND{i}', fontsize=7, ha='left')
    if embedded_psr:
        s.refs.update(draw_psr_network(ax, origin=(0,-6), interactive=interactive or control_ports,
                                       hits=hits, control_ports=control_ports))
    elif psr:
        # The desktop connected view owns this circuit in its feedback region.
        s.refs.update(('N_A', 'R_FBH', 'R_FBL', 'R_REG', 'U_PSR', 'R_COMP', 'C_COMP', 'C_POLE'))
    elif not control_ports:
        yy=height-2-5*(p.get('feedback_output',1)-1)
        with s.mark('U_FB'):
            s.text(18,-1.8,'U_FB · SSR：★ 路防反前取样；端口输出在防反后',
                   fontsize=8,color='#2068a0',va='baseline')
        s.wire((19.3,-1.3),(19.3,yy),ls='--',color='#2068a0',lw=.8)
        if interactive:
            s.wire((19.12,yy-.25),(19.3,yy),(19.48,yy-.25),color='#2068a0',lw=.8)
        else:
            ax.annotate('',xy=(19.3,yy),xytext=(19.3,yy-.75),arrowprops=dict(arrowstyle='->',color='#2068a0',lw=.8))
    if not control_ports:
        _controller_box(s, p, ground-2.)
    assert s.refs==refs,(s.refs-refs,refs-s.refs)
    return rows


def draw_psr_network(ax, origin=(0,0), standalone=False, *, interactive=False, hits=None,
                     control_ports=False, connected=False, anchors=None):
    """Unrectified auxiliary FB and genuine series-RC / parallel-C COMP."""
    if connected:
        return _draw_psr_external(ax, origin, hits, anchors)
    if standalone:
        ax.clear(); ax.set_axis_off(); ax.set_xlim(-.5,24); ax.set_ylim(-.5,6.4)
    ox,oy=origin
    # Print layout uses its own inset. The desktop uses the main coordinates.
    use_inset = not (standalone or interactive)
    inset=ax.inset_axes([0,0,1,1],transform=ax.transAxes) if use_inset else ax
    if use_inset:
        inset.set_axis_off(); inset.set_xlim(ax.get_xlim()); inset.set_ylim(ax.get_ylim()); inset.patch.set_alpha(0)
    s=_Schematic(inset,hits=hits)
    s.fontsize=7.5
    def coord(x,y): return (x+ox,y+oy)
    with s.mark('N_A'):
        a,b=s.inductor(*coord(1.2,3.6),None,direction=(0,1))
        s.text(*coord(1.8,5.8),'N_A',fontsize=8)
    s.wire(b,coord(1.2,5),coord(2.5,5))
    with s.mark('R_FBH'):
        a,b=s._part(coord(3.3,5),(1,0),None,'resistor')
        s.text(*coord(3.3,5.75),'R_FBH')
    s.wire(coord(2.5,5),a); s.wire(b,coord(6,5),coord(8,5))
    with s.mark('R_FBL'):
        c,d=s.resistor(*coord(6,3.3),None)
        s.text(*coord(5.55,3.4),'R_FBL',ha='right')
    s.wire(coord(6,5),d); s.wire(c,coord(6,1))
    s.wire(coord(1.2,2.85),coord(1.2,1),coord(6,1))
    c,d=s._part(coord(5.4,2),(1,0),'R_REG','resistor'); s.wire(coord(3,2),c); s.wire(d,coord(8,2))
    if control_ports:
        s.port('PGND', coord(4.2, 1), coord(4.2, .72), side='bottom')
        s.port('CS_RAW', coord(3, 2), side='left', junction=False)
        s.port('FB_AUX', coord(6, 5), coord(6, 5.38))
        s.port('SENSE', coord(7.1, 2), coord(7.1, 2.38))
        s.wire(coord(6,1), coord(8,1))
    else:
        s.text(*coord(3.3,.45),'PGND · 简化采样参考')
        s.text(*coord(2.4,2),'R_S1 采样点')
    with s.mark('U_PSR'):
        s.wire(coord(8,1),coord(13,1),coord(13,5.6),coord(8,5.6),coord(8,1))
        s.text(*coord(10.5,4),'U_PSR · MP6005',fontsize=8); s.text(*coord(10.5,3),'MODE 悬空',fontsize=8)
        s.text(*coord(8.5,5),'FB'); s.text(*coord(9,2),'SENSE'); s.text(*coord(12.2,5),'COMP')
    with s.mark('R_COMP'):
        a,b=s.resistor(*coord(16,4),None)
        s.text(*coord(15.55,4),'R_COMP',ha='right')
    s.wire(coord(13,5),coord(16,5),b)
    with s.mark('C_COMP'):
        c,d=s.capacitor(*coord(16,2),None)
        s.text(*coord(15.55,2),'C_COMP',ha='right')
    s.wire(a,d); s.wire(c,coord(16,1))
    with s.mark('C_POLE'):
        c,d=s.capacitor(*coord(19,3),None)
        s.text(*coord(18.55,3),'C_POLE',ha='right')
    s.wire(coord(16,5),coord(19,5),d); s.wire(c,coord(19,1),coord(16,1))
    if control_ports:
        s.port('COMP', coord(17.5, 5), coord(17.5, 5.39))
        s.port('PGND', coord(18, 1), coord(18, .72), side='bottom')
        s.port('VG_Q1', coord(13, 2.7), coord(14.0, 2.7), side='right', ref='U_PSR', junction=False)
    else:
        s.text(*coord(18,.45),'PGND')
    s.text(*coord(21.4,3.5),'gEA COMP\n(R + C串联) ∥ Cp',fontsize=8)
    return s.refs


def _draw_psr_external(ax, origin, hits, anchors):
    """Draw the MP6005 external network with chip pins along its left edge."""
    ox, oy = origin
    s = _Schematic(ax, hits=hits)
    s.fontsize = 7.5

    def coord(x, y):
        return ox+21-x, oy+y

    def pin(name, x, y, side='right', *, junction=False):
        point = coord(x, y)
        s.port(name, point, side=side, junction=junction)
        if anchors is not None:
            anchors[name] = point

    with s.mark('N_A'):
        bottom, top = s.inductor(*coord(1.35, 3.95), None, direction=(0, 1))
        s.text(*coord(2.28, 4.13), 'N_A', fontsize=8)
        s.wire(top, coord(1.35, 5.46), coord(3.35, 5.46))
        s.wire(bottom, coord(1.35, .35), coord(6.7, .35))
    _, divider = s._part(coord(4.1, 5.46), (-1, 0), 'R_FBH', 'resistor', label_side=-1)
    s.wire(divider, coord(21, 5.46))
    a, b = s.resistor(*coord(6.7, 3.03), 'R_FBL', label_side=-1)
    s.wire(b, coord(6.7, 5.46))
    s.wire(a, coord(6.7, .35))
    s.node(*coord(6.7, 5.46))
    pin('PGND', 6.7, .35, 'bottom', junction=True)
    pin('FB_AUX', 21, 5.46, 'top')

    raw, sense = s._part(coord(11.2, 3.41), (-1, 0), 'R_REG', 'resistor', label_side=-1)
    s.wire(raw, coord(8.7, 3.41), coord(8.7, -.75), coord(0, -.75))
    s.wire(sense, coord(21, 3.41))
    pin('CS_RAW', 0, -.75, 'top')
    pin('SENSE', 21, 3.41, 'top')

    r_to_cap, r_to_comp = s._part(coord(17.1, 1.40), (-1, 0), 'R_COMP', 'resistor', label_side=-1)
    cap_to_return, cap_to_res = s._part(coord(14.8, 1.40), (-1, 0), 'C_COMP', 'capacitor', label_side=-1)
    pole_to_return, pole_to_comp = s._part(coord(15.95, -.12), (-1, 0), 'C_POLE', 'capacitor')
    s.wire(r_to_cap, cap_to_res)
    s.wire(r_to_comp, coord(21, 1.40))
    s.wire(cap_to_return, coord(12.65, 1.40), coord(12.65, -.12), pole_to_return)
    s.wire(pole_to_comp, coord(19.25, -.12), coord(19.25, 1.40))
    s.node(*coord(19.25, 1.40))
    pin('PGND', 12.65, -.12, 'bottom', junction=True)
    pin('COMP', 21, 1.40, 'top')
    return s.refs
