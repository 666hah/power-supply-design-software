"""Read-only, millimetre presentation of the shared winding geometry.

This module does not select electrical hardware or write mechanical assumptions
back to an engineering configuration.  u is axial and v is radial, in metres in
the shared assessment and millimetres at the viewer boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from winding_layout import assess_winding_window, iter_bundle_records

SCHEMA = 'power-transformer.preview.v1'
MAX_PREVIEW_BUNDLES = 12000
BOBBIN_WALL_ESTIMATE_M = .30e-3
COLORS = {'P': '#8f371a', 'OUT1': '#164a8e', 'OUT2': '#176452',
          'OUT3': '#713b85', 'OUT4': '#906019', 'OUT5': '#96394b',
          'OUT6': '#285b67', 'AUX': '#504593'}


def _mm(value):
    return float(value) * 1000.


def nominal_winding_window(config, shape):
    """Fill omitted window dimensions with mechanical drawing estimates."""
    cfg = dict(config)
    if cfg.get('window_width') and cfg.get('window_height'):
        return cfg, False
    bobbin = (cfg.get('model_3d') or {}).get('bobbin', {})
    dims = shape.get('dimensions_mm') or {}
    wall = bobbin.get('wall_thickness_m') or BOBBIN_WALL_ESTIMATE_M
    axial = dims.get('window_height', 0.) * (1 if shape.get('template') == 'ei_rect' else 2) * 1e-3
    radial = ((dims.get('window_diameter') or dims.get('window_outer_width') or 0.)
              - (dims.get('center_diameter') or dims.get('center_width') or 0.)) * .5e-3
    cfg['window_width'] = cfg.get('window_width') or max(0., axial - 2 * wall)
    cfg['window_height'] = cfg.get('window_height') or max(0., radial - wall)
    return cfg, True


def resolve_winding_placement(core, config, profile, notes):
    """Shared placement in millimetres, with declared datums taking precedence."""
    dims = core.get('dimensions_mm') or {}
    frame = profile.get('frame') or {}
    bobbin = profile.get('bobbin') or {}
    route = bobbin.get('winding_route_type')
    z0 = frame.get('z0_m')
    assumed = z0 is None or route is None or bobbin.get('status') != 'confirmed'
    if z0 is None:
        center_m = -float(dims.get('window_height', 0)) / 2000 if core.get('template') == 'ei_rect' else 0.
        z0 = center_m - config['window_width'] / 2
        notes.append('轴向基准未填写：预览将净窗口居中；工程参数保持原值。')
    result = dict(route_type=route, z0_mm=_mm(z0), r0_mm=None,
                  rounded_rectangle_mm=None, path_xy_mm=None,
                  source='工程三维建模设置', assumed=assumed)
    if route == 'custom_closed':
        path = bobbin.get('winding_path_xy_m')
        if not path:
            raise ValueError('自定义绕线路径尚未填写。')
        result['path_xy_mm'] = [[_mm(x), _mm(y)] for x, y in path]
    elif route == 'rounded_rectangle':
        rect = bobbin.get('rounded_rectangle_m')
        if not rect:
            raise ValueError('圆角矩形绕线路径尺寸尚未填写。')
        result['rounded_rectangle_mm'] = dict(
            center_xy_mm=[_mm(v) for v in rect['center_xy_m']],
            width_mm=_mm(rect['width_m']), height_mm=_mm(rect['height_m']),
            corner_radius_mm=_mm(rect['corner_radius_m']))
    elif route == 'circular' and frame.get('r0_m_if_circular') is not None:
        result['r0_mm'] = _mm(frame['r0_m_if_circular'])
    else:
        # Mechanical dimensions only.  Ae/Ve and MLT do not define a core solid.
        diameter = dims.get('center_diameter')
        width, depth = dims.get('center_width'), dims.get('center_depth')
        wall = _mm(bobbin.get('wall_thickness_m') or BOBBIN_WALL_ESTIMATE_M)
        if core.get('template') in ('toroid', 'u') and not route:
            result.update(route_type=None, source='该外形需要显式骨架路径', assumed=True)
            notes.append('该磁芯的绕线路径需单独指定；当前先显示磁芯，原工程绕组参数保留。')
            return result
        if diameter:
            result.update(route_type='circular', r0_mm=float(diameter) / 2 + wall)
        elif width and depth and route == 'circular':
            result.update(route_type='circular', r0_mm=math.hypot(float(width), float(depth)) / 2 + wall)
        elif width and depth:
            result.update(route_type='rounded_rectangle', rounded_rectangle_mm=dict(
                center_xy_mm=[float(dims.get('center_offset_x', 0)), float(dims.get('center_offset_y', 0))],
                width_mm=float(width) + 2 * wall,
                height_mm=float(depth) + 2 * wall, corner_radius_mm=wall))
        else:
            # Winding positions are available, but there is no honest radial
            # origin.  Show the library core only, not a made-up assembly.
            result.update(route_type=None, source='缺少骨架路径基准', assumed=True)
            notes.append('尚无骨架内侧半径或截面路径；填写“三维建模设置”后显示绕组。')
            return result
        result.update(source='预览定位假设：规格书中柱 + 骨架壁厚', assumed=True)
        if not bobbin.get('wall_thickness_m'):
            notes.append('骨架壁厚未填写：预览暂用 0.30 mm；仅作定位，不写回工程。')
    if result['assumed']:
        notes.append('骨架路径或基准包含假设；机械位置以工程中已确认的尺寸为准。')
    return result


def _gap(profile, estimate, notes):
    physical = (profile.get('core') or {}).get('gap_geometry')
    if physical:
        kind = physical['type']
        value = _mm(physical['length_m'])
        if kind == 'none':
            value = 0.
        return kind, value
    if estimate and estimate.get('gap_m') is not None:
        notes.append(f"电气估算等效气隙 {_mm(estimate['gap_m']):.4g} mm；物理开隙未指定，预览按未磨隙装配。")
    return 'none', 0.


def build_scene(core_name, windings, winding_config, *, profile=None, title=None,
                gap=None, stale=False):
    """Build an isolated JSON payload without running any electrical solver.

    ``windings`` comes from ``transformer_windings(result)``. ``gap`` is an
    optional electrical estimate, never a declaration of a manufactured gap.
    An invalid detailed geometry raises ValueError rather than using old turns.
    """
    from core_shape_catalog import get_core_shape, list_core_shapes
    core = get_core_shape(str(core_name))
    if core is None:
        core = dict(model=str(core_name), family='CUSTOM', template=None,
                    status='dimensions_pending', dimensions_mm=None,
                    manufacturer=None, reference_model=None, source_url=None,
                    source_page=None, notes=['自定义磁芯尚无规格书外形尺寸。'])
    assessment = assess_winding_window(copy.deepcopy(windings), copy.deepcopy(winding_config))
    config = assessment['config']
    profile = copy.deepcopy(profile if profile is not None else config.get('model_3d') or {})
    if profile:
        from transformer_geometry_contract import validate_profile
        validate_profile(profile)
    notes = []
    if stale:
        notes.append('电气参数已修改：匝数和线材来自上一有效计算；重新计算后刷新预览。')
    if core.get('status') == 'dimensions_pending':
        notes.append('该型号规格书机械尺寸待补；不生成猜测的磁芯外形。')
    placement = resolve_winding_placement(core, config, profile, notes)
    gap_kind, gap_mm = _gap(profile, gap, notes)
    available = assessment.get('bundle_count', 0)
    too_large = available > MAX_PREVIEW_BUNDLES or assessment.get('physical_layers') is None
    if too_large:
        notes.append(f'当前包含 {available} 个线束截面，超过逐匝预览容量 {MAX_PREVIEW_BUNDLES}；仅显示磁芯，绕组数据完整保留。')
    if not assessment['configured']:
        notes.append('填写“窗口净宽”和“窗口净高”后显示当前工程绕组。')
    elif not windings:
        notes.append('完成一次有效的变压器计算后显示绕组。')
    elif not assessment['fits']:
        notes.extend(assessment.get('warnings', [])[:-1])
    result = dict(schema=SCHEMA, title=title or f'{core_name} · 变压器 3D 结构',
                  core=core, catalog=list_core_shapes(), windings=[], placement=placement,
                  gap_mm=gap_mm, gap_kind=gap_kind, notes=notes, stale=bool(stale),
                  summary=dict(winding_count=len(windings), layer_count=assessment['total_layer_count'],
                               bundle_count=available, displayed_bundles=0,
                               fits=assessment['fits'], window_width_mm=_mm(config['window_width']),
                               window_height_mm=_mm(config['window_height']),
                               status='core_only'),
                  # Existing lead polylines are explicit evidence, unlike
                  # inferred layer crossovers or vendor-specific terminals.
                  leads=[dict(node=x['node'], path_xyz_mm=[[_mm(v) for v in p] for p in x['path_xyz_m']])
                         for x in profile.get('leads', [])])
    render_windings = assessment['configured'] and not too_large and placement['route_type']
    if render_windings:
        layers = {entry['section_id']: entry for entry in assessment['physical_layers']}
        for row in assessment['windings']:
            winding = dict(id=row['id'], name=row['name'], color=COLORS.get(row['id'], '#7a4330'),
                           turns=int(row['turns']), parallel_wires=row['parallel_wires'],
                           strands=int(row['strands']), wire_type=row['wire_type'], sections=[])
            grouped = {}
            for record in iter_bundle_records(row, config):
                sid = record['section_id']
                if sid not in grouped:
                    layer = layers[sid]
                    declaration = (profile.get('sections') or {}).get(sid, {})
                    if declaration and (declaration.get('winding_id') != row['id'] or
                                        declaration.get('turns') != layer['turns']):
                        notes.append(f'{sid} 的接线声明与当前层匝数不一致；预览绕向按未确认处理。')
                        declaration = {}
                    grouped[sid] = dict(id=sid, layer_index=layer['layer_index'],
                        direction=declaration.get('direction') or 'ccw',
                        direction_assumed=declaration.get('status') != 'confirmed' or not declaration.get('direction'),
                        insulation_before_mm=_mm(layer['insulation_before']),
                        turn_count=int(layer['turns']), turns=[])
                    winding['sections'].append(grouped[sid])
                grouped[sid]['turns'].append(dict(id=record['id'],
                    center_mm=[_mm(record['x'] + record['width'] / 2), _mm(record['y'] + record['height'] / 2)],
                    width_mm=_mm(record['width']), height_mm=_mm(record['height']),
                    turn_index=record['turn'], bundle_index=record['bundle'],
                    wire_index=(record['bundle'] - 1) // row['bundles_per_wire'] + 1,
                    sub_bundle_index=(record['bundle'] - 1) % row['bundles_per_wire'] + 1,
                    profile_type=record['profile_type'], edited=record['edited'],
                    conflict=bool(record.get('conflict', False))))
            result['windings'].append(winding)
        result['summary']['displayed_bundles'] = sum(len(s['turns']) for w in result['windings'] for s in w['sections'])
        result['summary']['status'] = 'assembled' if result['windings'] else 'core_only'
        notes.append('螺旋轨迹按逐匝截面连续推进；绕向未确认时用逆时针显示。层间跨线及针脚只按已填写的路径显示。')
        if any(w['strands'] > 1 for w in result['windings']):
            notes.append('利兹线显示为深色等效线束，宽高沿用绕制设置；不展开每根细股的绞合。')
        # Bound the winding against the nominal axial core window. A collision
        # is shown as-is, never "fixed" by shrinking a user's wire geometry.
        dims = core.get('dimensions_mm') or {}
        height = dims.get('window_height')
        if height:
            extents = [(placement['z0_mm'] + t['center_mm'][0] - t['width_mm'] / 2,
                        placement['z0_mm'] + t['center_mm'][0] + t['width_mm'] / 2)
                       for w in result['windings'] for s in w['sections'] for t in s['turns']]
            lower = -height
            upper = 0 if core.get('template') == 'ei_rect' else height
            if extents and (min(x[0] for x in extents) < lower - 1e-9 or max(x[1] for x in extents) > upper + 1e-9):
                notes.append('当前轴向绕组范围超出该参考磁芯窗口；请核对磁芯规格及骨架基准，预览保留原尺寸。')
        inner_span = dims.get('window_diameter') or dims.get('window_outer_width')
        if placement['route_type'] == 'circular' and inner_span and result['windings']:
            outer_radius = max(placement['r0_mm'] + t['center_mm'][1] + t['height_mm'] / 2
                               for w in result['windings'] for s in w['sections'] for t in s['turns'])
            if outer_radius * 2 > inner_span + 1e-9:
                notes.append('绕组外径超过该参考磁芯的窗口内跨距；请核对径向空间，预览保留原尺寸。')
    if core.get('status') != 'dimensions_pending':
        # Only the current mesh travels with the scene. The host serves library
        # switches by exact model name; the page never opens arbitrary paths.
        from core_mesh_library import get_core_mesh
        result['core_mesh'] = get_core_mesh(core['model'])
    notes.append('结构预览只读取几何；L、M、k 仍由电磁仿真提取并按联合流程回填。')
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf8')
    result['signature'] = hashlib.sha256(encoded).hexdigest()
    return result
