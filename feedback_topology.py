"""Compose desktop feedback schematics from current control and compensation settings."""
from textwrap import wrap

from compensation_report import NETWORKS, compensation_snapshot, network_key


ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD', 'LLC')
LLC_FEEDBACK_NOTE = 'TL431 与光耦为外环硬件参考。设计和开关仿真以一个等效 PI 表示该通道。'
SENSE_INK = '#137974'
COMMAND_INK = '#265c95'
GATE_INK = '#a14f1a'


def compensation_view(p, op, state):
    """Select the same network and branch set on both desktop pages."""
    key = network_key(state['topo'])
    if p['topology'] == 'LLC':
        from example_catalog import tl431_network_key
        if key not in ('tl431f', 'tl431nf'):
            key = tl431_network_key(op['V_out'])
        return key, {'exact_type2': True, 'parts': {}}, LLC_FEEDBACK_NOTE
    try:
        data = compensation_snapshot(p, op, state)
    except (ValueError, KeyError, ArithmeticError, TypeError) as exc:
        from plants import resolve_controller_type
        active = resolve_controller_type(p.get('controller_type', 'auto'), p.get('control_mode', 'Voltage Mode'))
        if state['dir'] == 'rev':
            from compensation_report import UNITS
            parts = {name: entry['v'] * UNITS.get(entry['u'], 1.) for name, entry in state['vars'].items()}
            return key, {'parts': parts}, str(exc)
        exact = active == 'type2' and not state['type2']
        return key, {'exact_type2': exact, 'legacy_type2': state['type2'], 'parts': {}}, str(exc)
    note = '' if data['buildable'] else next(
        (line for line in data['notes'] if '不能' in line or '不高于' in line), '当前阻容需复核。')
    return key, data, note


def draw_compensation_view(s, p, key, data, *, origin=(0, 0), owner_ref=None, ports=None):
    """Render the actual selected schematic, with matching signal ground labels."""
    from feedback_compensation_diagram import draw_compensation_network

    isolated = p['topology'] in ISOLATED
    inverting = p['topology'] == 'BUCK-BOOST'
    optical = key.startswith('tl431')
    sense = 'V_FB_MAG' if inverting else 'V_SENSE'
    command = 'V_OPTO' if optical else 'COMP_SEC' if isolated else 'COMP'
    network_origin = origin
    if ports is not None and command == 'COMP_SEC':
        network_origin = (origin[0] + 7.5, origin[1])
    bounds = draw_compensation_network(
        s, key, origin=network_origin, snapshot=data, legacy_type2=bool(data.get('legacy_type2')),
        omit_inactive=True, owner_ref=owner_ref, sense_net=sense,
        sense_ground='SGND' if isolated else 'PGND', controller_ground='PGND',
        output_net=command, ports=ports, signal_right_to_left=ports is not None,
    )
    x0, x1, y0, y1 = bounds
    if command == 'COMP_SEC':
        interface_y = y0 + 4. if ports is None else ports['output'][1]
        interface_x = x1+.4 if ports is None else x0-.4
        entry, output = _equivalent_interface(s, interface_x, interface_y, 'COMP_SEC', 'COMP',
                                              '隔离传输（等效）', isolated=True, reverse=ports is not None)
        if ports is not None:
            _signal_wire(s, (ports['output'], entry), COMMAND_INK)
            ports['output'] = output
            x0 -= 7.
        else:
            x1 += 7.
        command = 'COMP'
    if inverting:
        if ports is None:
            _equivalent_interface(s, x1 + .4, y0 + 4., 'V_SENSE−', 'V_FB_MAG', '取样反相 ×−1')
            x1 += 7.
        else:
            entry, output = _equivalent_interface(s, x1+7., ports['sense'][1], 'V_SENSE−', 'V_FB_MAG',
                                                  '取样反相 ×−1', reverse=True)
            _signal_wire(s, (output, ports['sense']), SENSE_INK)
            ports['sense'] = entry
            x1 += 7.7
    return (x0, x1, y0, y1), command


def _equivalent_interface(s, x, y, input_net, output_net, label, *, isolated=False, reverse=False):
    """Show a signed input-to-output voltage interface and its return domains."""
    def pos(dx, dy=0):
        return x-dx if reverse else x+dx, y+dy

    def wire(*points, **style):
        s.wire(*(pos(*point) for point in points), **style)

    s.text(*pos(3, 2), label, fontsize=8, fontweight='bold')
    s.terminal(x, y)
    s.text(*pos(0, .55), input_net, ha='right' if reverse else 'left', fontsize=7.5)
    wire((0, 0), (2, 0))
    if isolated:
        wire((3, -1.25), (3, 1.4), ls='--', color='#94a7bb')
        wire((2, 0), (2, -.85), (1.2, -.85))
        s.text(*pos(1.2, -1.16), 'SGND', fontsize=7)
    wire((4.1, .85), (3.45, 0), (4.1, -.85), (4.75, 0), (4.1, .85))
    s.text(*pos(4.1, .34), '+', fontsize=8)
    s.text(*pos(4.1, -.36), '−', fontsize=8)
    wire((4.1, -.85), (4.1, -1.24))
    s.text(*pos(4.1, -1.55), 'PGND', fontsize=7)
    wire((4.1, .85), (4.1, 1.2), (6, 1.2), (6, 0))
    s.terminal(*pos(6))
    s.text(*pos(6, -.38), output_net, ha='left' if reverse else 'right', fontsize=7.5)
    wire((2, 0), (3.35, 0), ls='--', color='#58718b')
    return (x, y), pos(6)


def _signal_wire(s, points, ink):
    s.wire(*points, color=ink, lw=1.5, zorder=1.8)


def _cross_gap(s, start, end, ink, fraction=.5):
    x = start[0] + fraction*(end[0] - start[0])
    _signal_wire(s, (start, (x, start[1]), (x, end[1]), end), ink)


def draw_feedback_stage(ax, p, op, state, hits, rows, power_pins):
    """Wire the power stage to the right-side feedback and left-side controller."""
    from cot_settings import active
    from feedback_controller_diagram import draw_controller_block
    from topology_diagram import _Schematic, draw_psr_network

    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    regions = {'power': (x0, x1, y0, y1)}
    sketch = _Schematic(ax, interactive=True, hits=hits)
    psr = p.get('feedback_mode') == 'PSR-MP6005'
    cot = active(p)
    gate_count = sum(name.startswith('VG_') and name.endswith('_escape') for name in power_pins)
    lane_step = .35 if gate_count > 4 else .65
    lane_base = y0 - 1.1 - lane_step * (gate_count-1 if not cot else 0)
    row_top = lane_base - 1.9
    chip_pins = {}
    ux0, ux1, uy0, uy1 = draw_controller_block(
        sketch, p, op, origin=(x0+1., row_top), ports=chip_pins,
        command_label='FB' if psr or cot else 'COMP')
    regions['controller'] = (ux0-.65, ux1+.65, uy0-.65, uy1+.65)

    left = ux1+4.5
    feedback_pins = {}
    sense_name = 'V_SENSE−' if p['topology'] == 'BUCK-BOOST' else 'V_SENSE'
    note = ''
    if psr:
        draw_psr_network(ax, origin=(left, row_top-6.45), interactive=True, hits=hits,
                         control_ports=True, connected=True, anchors=feedback_pins)
        bounds = (left-.8, left+22., row_top-7.5, row_top)
        title = '反馈网络 · 原边辅助绕组 / COMP'
    elif cot:
        sense = (left+16.5, row_top-4.7)
        output = (left, sense[1])
        sketch.terminal(*sense)
        sketch.text(sense[0], sense[1]+.68, 'V_SENSE', ha='right')
        _signal_wire(sketch, (sense, output), SENSE_INK)
        feedback_pins.update(sense=sense, output=output)
        bounds = (left-.5, left+16.5, row_top-6.5, row_top)
        title = '输出取样 · COT 芯片内补偿'
    else:
        key, data, note = compensation_view(p, op, state)
        feedback_ref = 'U_FB' if 'U_FB' in rows else None
        comp_sketch = _Schematic(ax, interactive=True, hits=hits if feedback_ref else None)
        bounds, _ = draw_compensation_view(
            comp_sketch, p, key, data, origin=(left, row_top-11.25),
            owner_ref=feedback_ref, ports=feedback_pins)
        title = '反馈网络 · '+NETWORKS[key][0]

    cx0, cx1, cy0, cy1 = bounds
    sketch.text(left, cy1+.55, title, ha='left', fontweight='bold', fontsize=10)
    if note:
        lines = wrap(note, 32) or [note]
        sketch.text(left, cy0-.25, '\n'.join(lines), ha='left', va='top', fontsize=7.5)
        cy0 -= .65 + .68*len(lines)
    regions['compensation'] = (cx0-.35, cx1+.7, cy0, cy1+1.2)
    outer_right = max(x1, cx1)+1.45

    if psr:
        _cross_gap(sketch, feedback_pins['FB_AUX'], chip_pins['input'], SENSE_INK, .22)
        _cross_gap(sketch, feedback_pins['COMP'], chip_pins['psr_comp'], COMMAND_INK, .42)
        _cross_gap(sketch, feedback_pins['SENSE'], chip_pins['sensors']['SENSE'], SENSE_INK, .70)
        if 'CS_RAW' in power_pins:
            escape = power_pins.get('CS_RAW_escape', (power_pins['CS_RAW'],))
            sx, sy = feedback_pins['CS_RAW']
            _signal_wire(sketch, (*escape, (outer_right, escape[-1][1]),
                                  (outer_right, sy), (sx, sy)), SENSE_INK)
    else:
        _cross_gap(sketch, feedback_pins['output'], chip_pins['input'], COMMAND_INK)
        sense_escape = power_pins[f'{sense_name}_escape']
        sx, sy = feedback_pins['sense']
        outer_right = max(outer_right, sense_escape[-1][0]+.45)
        _signal_wire(sketch, (*sense_escape, (outer_right, sense_escape[-1][1]),
                              (outer_right, sy), (sx, sy)), SENSE_INK)

    left_margin = min(ux0-1.4, x0-1.)
    outer_left = left_margin - .42*max(0, gate_count-1)
    for index, (gate, chip_end) in enumerate(chip_pins['gates'].items()):
        escape = power_pins[f'{gate}_escape']
        gx, gy = escape[-1]
        outer_x = left_margin - index*.42
        if cot:
            route = (chip_end, (outer_x, chip_end[1]), (outer_x, gy), *reversed(escape))
        else:
            lane = lane_base + index*lane_step
            route = (chip_end, (outer_x, chip_end[1]), (outer_x, lane),
                     (gx, lane), *reversed(escape))
        _signal_wire(sketch, route, GATE_INK)

    regions['feedback_loop'] = (outer_left-.55, outer_right+.45, min(cy0, uy0)-.65, cy1+1.2)
    ax.set_xlim(outer_left-.75, outer_right+.65)
    ax.set_ylim(min(cy0-.45, uy0-.65), y1)
    return regions
