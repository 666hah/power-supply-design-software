"""Vector schematics for the SSR reference networks in comp_design."""

from contextlib import nullcontext


_BOUNDS = (-.7, 23., -.55, 11.25)
_DOCK_LEFT, _DOCK_RIGHT = .1, 22.2


class _Network:
    def __init__(self, schematic, origin, snapshot, omit_inactive, owner_ref, ports,
                 *, mirrored, docked):
        self.s = schematic
        self.ox, self.oy = origin
        self.parts = snapshot.get('parts', {})
        self.omit_inactive = omit_inactive
        self.owner_ref = owner_ref
        self.ports = ports
        self.mirrored = mirrored
        self.docked = docked

    def point(self, x, y):
        if self.mirrored:
            x = _BOUNDS[0] + _BOUNDS[1] - x
        return x + self.ox, y + self.oy

    def wire(self, *points, **style):
        self.s.wire(*(self.point(*point) for point in points), **style)

    def text(self, x, y, label, **style):
        if self.mirrored:
            alignment = style.get('ha')
            if alignment in ('left', 'right'):
                style['ha'] = 'right' if alignment == 'left' else 'left'
        self.s.text(*self.point(x, y), label, **style)

    def dot(self, x, y):
        self.s.node(*self.point(x, y))

    def port(self, x, y, label, *, offset=(0, .55), anchor=None):
        point = self.point(x, y)
        self.s.terminal(*point)
        self.text(x + offset[0], y + offset[1], label)
        if anchor is not None and self.ports is not None:
            self.ports[anchor] = (self.s.x(point[0]), point[1])

    def signal_port(self, x, y, label, anchor, edge):
        """Extend the same node to the circuit boundary for canvas wiring."""
        if self.docked:
            self.wire((x, y), (edge, y))
            x = edge
        self.port(x, y, label, anchor=anchor)

    def ground(self, x, y, label):
        for depth, half_width in ((0, .42), (.18, .28), (.36, .13)):
            self.wire((x - half_width, y - depth), (x + half_width, y - depth))
        self.text(x, y - .69, label)

    def mark(self, ref):
        return nullcontext() if self.owner_ref else self.s.mark(ref)

    def branch(self, start, end, *parts, side=1):
        """Connect an axial branch through ordered (ref, centre) pairs."""
        horizontal = start[0] != end[0]
        direction = ((-1 if self.mirrored else 1), 0) if horizontal else (0, 1)
        previous_end = self.point(*start)
        for name, center in parts:
            x, y = (center, start[1]) if horizontal else (start[0], center)
            position = self.point(x, y)
            kind = 'resistor' if name.startswith('R') else 'capacitor'
            with self.mark(name):
                a, b = self.s._part(position, direction, None, kind)
                if horizontal:
                    self.text(x, y + .72 * side, name)
                else:
                    self.text(x + .52 * side, y, name, ha='left' if side > 0 else 'right')
            self.s.wire(previous_end, a)
            previous_end = b
        self.s.wire(previous_end, self.point(*end))

    def optional(self, start, end, *parts, cap, normally_open=False, side=1):
        """Draw an enabled branch and leave omitted or impossible branches open."""
        value = self.parts.get(cap, 0 if normally_open else 1)
        if value <= 0:
            if value < 0 or not self.omit_inactive:
                label = ' / '.join(name for name, _ in parts)
                self.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
                          label + (' 不装' if value == 0 else ' 不可实现'),
                          fontsize=min(self.s.fontsize, 7))
            return False
        self.branch(start, end, *parts, side=side)
        return True

    def amplifier(self, x, y, label):
        with self.mark('U_EA'):
            self.wire((x, y - 1.84), (x + 3.45, y), (x, y + 1.84), (x, y - 1.84))
            self.text(x + .35, y + 1.1, '−')
            self.text(x + .35, y - 1.1, '+')
            self.text(x + 1.35, y, label)
        return (x, y + 1.1), (x, y - 1.1), (x + 3.45, y)


def _draw_opamp(d, sense, ground, command, type2, legacy):
    d.signal_port(2, 9.6, sense, 'sense', _DOCK_LEFT)
    d.branch((2, 4.45), (2, 9.6), ('R1', 6.55), side=-1)
    d.branch((2, 1.05), (2, 4.45), ('R_lower', 2.8))
    d.ground(2, 1.05, ground)
    negative, positive, output = d.amplifier(11.85, 3.35, 'EA')
    d.wire((2, 4.45), negative)
    d.dot(2, 4.45)
    d.text(7.45, 4.98, 'FB')
    d.port(9.05, 2.25, 'V_REF', offset=(0, -.6))
    d.wire((9.05, 2.25), positive)
    d.wire(output, (20.05, 3.35))
    d.signal_port(20.05, 3.35, command, 'output', _DOCK_RIGHT)

    if d.optional((5.95, 4.45), (5.95, 8.7), ('C3', 5.6), ('R3', 7.25),
                  cap='C3', normally_open=type2):
        d.wire((2, 8.7), (5.95, 8.7))
        d.dot(2, 8.7)
        d.dot(5.95, 4.45)
    d.branch((9.05, 6.6), (17.55, 6.6), ('R2', 11.35), ('C1', 15.05))
    d.wire((9.05, 4.45), (9.05, 6.6))
    d.wire((17.55, 3.35), (17.55, 6.6))
    d.dot(9.05, 4.45)
    d.dot(17.55, 3.35)
    if d.optional((9.05, 8.7), (17.55, 8.7), ('C2', 13.3),
                  cap='C2', normally_open=legacy):
        d.wire((9.05, 6.6), (9.05, 8.7))
        d.wire((17.55, 6.6), (17.55, 8.7))
        d.dot(9.05, 6.6)
        d.dot(17.55, 6.6)


def _draw_gm(d, sense, ground, command, type2, legacy):
    d.signal_port(1.05, 7.9, sense, 'sense', _DOCK_LEFT)
    negative, positive, output = d.amplifier(11.4, 6.8, 'gm')
    d.branch((1.05, 7.9), negative, ('R1', 4.45), side=-1)
    d.branch((8.15, 1.4), (8.15, 7.9), ('R2', 4.9), side=-1)
    d.ground(8.15, 1.4, ground)
    d.dot(8.15, 7.9)
    d.text(9.6, 8.45, 'FB')
    d.port(10.1, 5.7, 'V_REF', offset=(0, -.6))
    d.wire((10.1, 5.7), positive)
    if d.optional((2.4, 9.7), (6.5, 9.7), ('C1', 4.45), cap='C1', normally_open=type2):
        d.wire((2.4, 7.9), (2.4, 9.7))
        d.wire((6.5, 7.9), (6.5, 9.7))
        d.dot(2.4, 7.9)
        d.dot(6.5, 7.9)

    d.wire(output, (21.35, 6.8))
    d.signal_port(21.35, 6.8, command, 'output', _DOCK_RIGHT)
    d.branch((16.1, 1.4), (16.1, 6.8), ('R3', 2.95), ('C2', 4.9), side=-1)
    d.ground(16.1, 1.4, ground)
    d.dot(16.1, 6.8)
    if d.optional((19.3, 1.4), (19.3, 6.8), ('C3', 4.1), cap='C3', normally_open=legacy):
        d.wire((16.1, 1.4), (19.3, 1.4))
        d.dot(16.1, 1.4)
        d.dot(19.3, 6.8)


def _draw_optocoupler(d, command, ground):
    primary, led, parallel_cap = 3.55, 9.65, 1.15
    collector, emitter = 5.85, .85
    led_anode, led_cathode = 5.85, 3.65
    d.wire((6.75, .35), (6.75, 9.65), ls='--', lw=.8, alpha=.40)
    d.port(primary, 10.25, 'V_DD_P')
    d.branch((primary, collector), (primary, 10.25), ('R_pullup', 8.05))
    outlet = _DOCK_LEFT if d.docked else 5.24
    d.port(outlet, collector, command, anchor='output')
    d.dot(primary, collector)
    d.ground(primary, emitter, ground)
    cap_enabled = d.optional((parallel_cap, emitter), (parallel_cap, collector),
                             ('C2', 3.3), cap='C2', side=1)
    if d.docked and cap_enabled:
        d.wire((primary, collector), (parallel_cap, collector), (outlet, collector))
        d.dot(parallel_cap, collector)
    else:
        d.wire((primary, collector), (outlet, collector))
        if cap_enabled:
            d.wire((parallel_cap, collector), (primary, collector))
    if cap_enabled:
        d.wire((parallel_cap, emitter), (primary, emitter))
        d.dot(primary, emitter)
    with d.mark('U_OPTO'):
        base = 4.37
        d.wire((primary, collector), (primary, 5.5), (base, 4.98))
        d.wire((base, 5.10), (base, 4.03), lw=2.)
        d.wire((base, 4.18), (primary, 3.57), (primary, emitter))
        d.wire((3.64, 3.87), (primary, 3.57), (3.9, 3.67))
        a, k = d.s.diode(*d.point(led, 4.75), None, direction=(0, -1))
        d.s.wire(d.point(led, led_anode), a)
        d.s.wire(k, d.point(led, led_cathode))
        for y in (4.45, 4.85):
            d.wire((8.7, y), (4.85, y), (5.16, y + .14))
            d.wire((4.85, y), (5.16, y - .14))
        d.text(6.75, 5.4, '光耦', fontsize=min(d.s.fontsize, 7.5),
               bbox=dict(facecolor=d.s.ax.get_facecolor(), edgecolor='none', pad=.2))


def _draw_shunt(d, sense_ground):
    x = 9.65
    with d.mark('U_TL431'):
        d.wire((x, 3.65), (x, 2.95))
        d.wire((x - .47, 2.04), (x + .47, 2.04), (x, 2.95), (x - .47, 2.04))
        d.wire((x - .68, 2.73), (x - .46, 2.95), (x + .46, 2.95), (x + .68, 3.17))
        d.wire((x + .21, 2.55), (10.55, 2.55))
        d.wire((x, 2.04), (x, .85))
        d.text(x - .64, 2.47, 'TL431', ha='right')
    d.wire((10.55, 2.55), (19.35, 2.55))
    d.text(11.47, 2.95, 'REF', fontsize=min(d.s.fontsize, 7.5))
    d.wire((x, .85), (19.35, .85))
    d.ground(19.35, .85, sense_ground)
    d.dot(19.35, .85)


def _draw_tl431(d, sense, ground, controller_ground, command, fast, type2):
    _draw_optocoupler(d, command, controller_ground)
    _draw_shunt(d, ground)
    led, bias, divider = 9.65, 12.65, 19.35
    cathode, anode, supply = 3.65, 5.85, 9.65
    d.signal_port(divider, 10.25, sense, 'sense', _DOCK_RIGHT)
    d.branch((divider, 2.55), (divider, 10.25), ('R1', 8.15), side=-1)
    d.branch((divider, .85), (divider, 2.55), ('R_lower', 1.7))
    d.dot(divider, 2.55)
    d.text(divider + .55, 2.55, 'FB', ha='left')
    d.branch((led, anode), (led, supply), ('R_LED', 8.15), side=1 if fast else -1)
    d.branch((bias, cathode), (bias, anode), ('R_bias', 4.75))
    d.wire((led, anode), (bias, anode))
    d.wire((led, cathode), (bias, cathode))
    d.dot(led, anode)
    d.dot(led, cathode)
    d.dot(bias, cathode)
    d.dot(divider, cathode)

    if fast:
        d.wire((led, supply), (divider, supply))
        d.branch((bias, cathode), (divider, cathode), ('C1', 16.1))
        if d.optional((bias, anode), (bias, supply), ('C_pz', 6.9), ('R_pz', 8.5),
                      cap='C_pz', normally_open=type2):
            d.dot(bias, supply)
            d.dot(bias, anode)
    else:
        d.branch((led, supply), (divider, supply), ('R_z', 17.5))
        d.branch((bias, cathode), (divider, cathode), ('C1', 14.3), ('R2', 17.1), side=-1)
        d.text(10.95, 10.18, 'V_BIAS')
        _draw_bias_supply(d, supply, ground)
        if d.optional((22.1, 4.65), (22.1, supply), ('C3', 6.25), ('R3', 8.15),
                      cap='C3', normally_open=type2, side=-1):
            d.wire((divider, supply), (22.1, supply))
            d.wire((divider, 4.65), (22.1, 4.65))
            d.dot(divider, 4.65)
    d.dot(divider, supply)


def _draw_bias_supply(d, supply, ground):
    zener, capacitor, ground_y = 12.65, 15.3, 6.92
    with d.mark('D_Z'):
        a, k = d.s.diode(*d.point(zener, 8.15), None, direction=(0, 1))
        d.s.wire(d.point(zener, ground_y), a)
        d.s.wire(k, d.point(zener, supply))
        d.wire((zener - .36, 8.43), (zener - .48, 8.29))
        d.wire((zener + .36, 8.43), (zener + .48, 8.57))
        d.text(zener + .6, 8.15, 'D_Z', ha='left')
    d.branch((capacitor, ground_y), (capacitor, supply), ('C_Z', 8.15))
    d.wire((zener, ground_y), (capacitor, ground_y))
    d.ground(capacitor, ground_y, ground)
    d.dot(zener, supply)
    d.dot(capacitor, supply)


def draw_compensation_network(s, key, *, origin=(0, 0), snapshot=None,
                              legacy_type2=False, omit_inactive=False, owner_ref=None,
                              sense_net='V_SENSE', sense_ground='SGND',
                              controller_ground='PGND', output_net=None,
                              ports=None, signal_right_to_left=False):
    """Draw on the supplied schematic and return the absolute drawing limits.

    Pass an optional compensation_snapshot to reflect fitted parts. Set owner_ref
    to group all artists under one clickable topology row. The caller controls
    axes limits, aspect ratio and refresh. A supplied ports dict receives the
    sense input and output terminal positions in canvas coordinates. Set
    signal_right_to_left to route them to the right and left edges.
    """
    snapshot = snapshot or {}
    is_opamp = key in ('opamp3', 'gm3')
    d = _Network(s, origin, snapshot, omit_inactive, owner_ref, ports,
                 mirrored=signal_right_to_left and is_opamp, docked=signal_right_to_left)
    # The legacy PI checkbox has an effect only on the two amplifier solvers.
    legacy = is_opamp and (legacy_type2 or snapshot.get('legacy_type2')
                           or (snapshot.get('type2') and not snapshot.get('exact_type2')))
    type2 = bool(snapshot.get('exact_type2') or legacy)
    command = output_net or ('COMP' if is_opamp else 'V_OPTO')
    with s.mark(owner_ref):
        if key == 'opamp3':
            _draw_opamp(d, sense_net, sense_ground, command, type2, legacy)
        elif key == 'gm3':
            _draw_gm(d, sense_net, sense_ground, command, type2, legacy)
        elif key in ('tl431nf', 'tl431f'):
            _draw_tl431(d, sense_net, sense_ground, controller_ground, command, key == 'tl431f', type2)
        else:
            raise ValueError(f'Unsupported compensation reference: {key}')
    ox, oy = origin
    x0, x1, y0, y1 = _BOUNDS
    return ox + x0, ox + x1, oy + y0, oy + y1
