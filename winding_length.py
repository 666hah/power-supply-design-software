"""Copper lengths from the same winding sections and coordinates as the 3D view."""

import math

from core_shape_catalog import get_core_shape
from transformer_preview_scene import nominal_winding_window, resolve_winding_placement
from winding_layout import assess_winding_window, iter_bundle_records


MAX_CENTRELINE_BUNDLES = 12_000


def _custom_offset_perimeter(points, offset):
    """Length of the radial offset path used by the custom-path preview.

    As in the preview, interpolate and renormalize neighbouring outward
    vertex normals. Subdivide every original edge to retain its corners.
    """
    polygon = points[:-1]  # Validated closed counter-clockwise polygon.
    n = len(polygon)
    normals = []
    for i in range(n):
        a, b = polygon[i - 1], polygon[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        magnitude = math.hypot(dx, dy)
        normals.append((dy / magnitude, -dx / magnitude))
    samples = []
    for i, (x, y) in enumerate(polygon):
        j = (i + 1) % n
        dx, dy = polygon[j][0] - x, polygon[j][1] - y
        nx, ny = normals[i]
        dnx, dny = normals[j][0] - nx, normals[j][1] - ny
        for k in range(16):
            f = k / 16
            qx, qy = nx + f * dnx, ny + f * dny
            magnitude = math.hypot(qx, qy)
            if magnitude < 1e-12:
                raise ValueError('自定义骨架的外移路径在转角处无确定法向')
            samples.append((x + f * dx + offset * qx / magnitude,
                            y + f * dy + offset * qy / magnitude))
    return math.fsum(math.dist(a, b) for a, b in zip(samples, samples[1:] + samples[:1]))


def _perimeter(placement, offset):
    route = placement['route_type']
    if route == 'circular':
        return math.tau * (placement['r0_mm'] * 1e-3 + offset)
    if route == 'rounded_rectangle':
        rect = placement['rounded_rectangle_mm']
        straight_and_corners = (2 * (rect['width_mm'] + rect['height_mm'])
                               + (math.tau - 8) * rect['corner_radius_mm']) * 1e-3
        return straight_and_corners + math.tau * offset
    points = [(x * 1e-3, y * 1e-3) for x, y in placement['path_xy_mm']]
    return _custom_offset_perimeter(points, offset)


def _helical_length(perimeter, centers):
    half = perimeter / 2
    # Along the same section, the two half-turns adjoining each neighbouring
    # pair cover the axial pitch. The two open ends retain their own half-turn.
    return perimeter + math.fsum(2 * math.hypot(half, (b - a) / 2) for a, b in zip(centers, centers[1:]))


def _equivalent_length(paths):
    """Equal copper cross-sections in parallel give a harmonic mean length."""
    return len(paths) / math.fsum(1 / length for length in paths.values())


def _row(turns, turn_length, lead_length, method, source):
    mlt = turn_length / turns
    return dict(turns=turns, length_m=turn_length + lead_length, turn_length_m=turn_length,
                lead_length_m=lead_length, mlt_m=mlt, mean_turn_length_m=mlt, method=method, source=source)


def _fallback(core, shape, windings, reason):
    nominal = float(core['MLT'])
    source = core.get('MLT_source') or '磁芯库名义平均匝长估算'
    if shape.get('template') == 'toroid':
        dims = shape['dimensions_mm']
        nominal = (2 * dims['height'] + dims['outer_diameter'] - dims['inner_diameter']) * 1e-3
        source = '磁环截面周长估算'
    return dict(method='catalog_estimate', source=source, sections={},
                windings={wire['id']: _row(int(wire['turns']), nominal * wire['turns'], 0.,
                                           'catalog_estimate', source) for wire in windings},
                notes=[reason + '。采用' + source + '，未计入引线。'])


def _lead_lengths(windings, profile):
    """Only count a single unambiguous polyline at each external winding port."""
    paths_by_node = {}
    for lead in profile.get('leads', ()):
        paths_by_node.setdefault(lead['node'], []).append(lead['path_xyz_m'])
    owners = {}
    for key, port in profile.get('ports', {}).items():
        for node in {port.get('dot_node'), port.get('other_node')} - {None}:
            owners.setdefault(node, set()).add(key)
    lengths = dict.fromkeys((wire['id'] for wire in windings), 0.)
    wires = {wire['id']: wire for wire in windings}
    included = 0
    for node, paths in paths_by_node.items():
        candidates = owners.get(node, ())
        if len(candidates) == 1 and len(paths) == 1:
            key = next(iter(candidates))
            if key in wires and wires[key].get('parallel_wires', 1) == 1:
                lengths[key] += math.fsum(math.dist(a, b) for a, b in zip(paths[0], paths[0][1:]))
                included += 1
    return lengths, sum(map(len, paths_by_node.values())) - included


def resolve_winding_lengths(core_name, core, windings, winding_config=None):
    """Compute section and winding lengths in metres without a manual MLT override.

    The per-winding length used in DCR excludes unspecified layer crossovers.
    Explicit terminal leads are accounted for separately from mean turn length.
    """
    try:
        shape = get_core_shape(core_name) or {}
    except (OSError, ValueError):
        shape = {}
    cfg, estimated_window = nominal_winding_window(winding_config or {}, shape)
    profile = cfg.get('model_3d') or {}
    route = (profile.get('bobbin') or {}).get('winding_route_type')
    if not route and shape.get('template') in ('toroid', 'u'):
        return _fallback(core, shape, windings, '该磁芯缺少实际骨架绕线路径')
    try:
        assessment = assess_winding_window(windings, cfg)
        if not assessment['configured']:
            raise ValueError('缺少有效线圈窗口')
        if not assessment['fits']:
            raise ValueError(assessment['warnings'][0] if assessment['warnings'] else '绕组排布超出有效窗口')
        if assessment['bundle_count'] > MAX_CENTRELINE_BUNDLES:
            raise ValueError('线束截面数超过逐匝长度计算上限')
        placement = resolve_winding_placement(shape, assessment['config'], profile, [])
        if not placement['route_type']:
            raise ValueError('缺少有效骨架路径')
    except ValueError as exc:
        return _fallback(core, shape, windings, str(exc))

    declared = bool(route and placement['source'] == '工程三维建模设置')
    method = 'winding_geometry' if declared else 'core_geometry'
    source = '工程骨架路径与逐匝绕制结构' if declared else '磁芯中柱与逐匝绕制结构估算'
    if estimated_window and declared:
        source += '（窗口估算）'
    notes = []
    if estimated_window:
        notes.append('缺失的窗口尺寸采用磁芯机械图和估计骨架边缘。')
    if not declared:
        notes.append('骨架路径沿用三维预览的中柱尺寸及骨架壁厚假设。')
    elif (profile.get('bobbin') or {}).get('status') != 'confirmed':
        notes.append('工程骨架路径为未确认尺寸或参考假设。')
    if not cfg.get('layer_plan'):
        notes.append('层数与逐匝位置按自动排布估算。')
    if placement['route_type'] == 'custom_closed':
        notes.append('自定义路径按三维预览的外移路径离散估算周长。')
    notes.append('计入层内螺旋节距，未声明的跨层或端子连线不计入。')

    sections, wires = {}, {}
    lead_lengths, unmapped_leads = _lead_lengths(windings, profile)
    if unmapped_leads:
        notes.append(f'{unmapped_leads} 条引线无法唯一分配到单路绕组端口，未计入。')
    perimeters = {}
    try:
        for row in assessment['windings']:
            key = row['id']
            layouts = {s['section_id']: s for s in row['layer_layout']}
            tracks = {sid: {} for sid in layouts}
            winding_paths = {}
            for box in iter_bundle_records(row, assessment['config']):
                section = tracks[box['section_id']]
                section.setdefault(box['bundle'], []).append(box['x'] + box['width'] / 2)
            for sid, layout in layouts.items():
                offset = layout['y'] + layout['height'] / 2
                if offset not in perimeters:
                    perimeters[offset] = _perimeter(placement, offset)
                perimeter = perimeters[offset]
                paths = {bundle: _helical_length(perimeter, centers) for bundle, centers in tracks[sid].items()}
                sections[sid] = dict(_row(layout['turns'], _equivalent_length(paths), 0., method, source), winding_id=key)
                for bundle, length in paths.items():
                    winding_paths[bundle] = winding_paths.get(bundle, 0.) + length
            wires[key] = _row(int(row['turns']), _equivalent_length(winding_paths), lead_lengths[key], method, source)
    except ValueError as exc:
        return _fallback(core, shape, windings, str(exc))
    return dict(method=method, source=source, notes=notes, sections=sections, windings=wires)
